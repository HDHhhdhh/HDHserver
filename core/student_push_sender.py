"""Fail-closed Web Push sender and VAPID key primitives; provider calls stay lazy and redacted."""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, Mapping, Protocol
from urllib.parse import quote

from core.student_push_validation import (
    JsonValue,
    ParsedSubscription,
    StudentPushConfigurationError,
    StudentPushDependencyError,
    StudentPushInputError,
    StudentPushKeyError,
    SubscriptionInfo,
    VapidKeyValidator,
    parse_subscription,
    valid_announcement_id,
    valid_vapid_subject,
    validate_private_key_path,
    validate_public_output_path,
    validate_vapid_private_key,
    vapid_public_key_from_pem,
)


PUSH_TTL_SECONDS: Final = 86_400
PUSH_URGENCY: Final = "normal"
class StatusCarrier(Protocol):
    status_code: int | None


class WebPushTransport(Protocol):
    def __call__(self, *, subscription_info: SubscriptionInfo, data: str, vapid_private_key: str, vapid_claims: Mapping[str, str], ttl: int, headers: Mapping[str, str]) -> StatusCarrier | None: ...


@dataclass(frozen=True, slots=True)
class StudentPushConfig:
    """Runtime push settings; private-key bytes are never retained."""

    enabled: bool = False
    vapid_subject: str | None = None
    vapid_private_key_path: Path | str | None = None

@unique
class PushResultStatus(StrEnum):
    SUCCESS = "success"
    PERMANENT_FAILURE = "permanent_failure"
    TRANSIENT_FAILURE = "transient_failure"
    INVALID_INPUT = "invalid_input"
    INVALID_CONFIGURATION = "invalid_configuration"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class PushSendResult:
    """Typed, privacy-minimal outcome of one attempted delivery."""

    status: PushResultStatus
    reason: str = ""
    http_status: int | None = None
    topic: str | None = None
    ttl: int = PUSH_TTL_SECONDS
    urgency: str = PUSH_URGENCY

    @property
    def ok(self) -> bool:
        return self.status is PushResultStatus.SUCCESS


def announcement_topic(announcement_id: str) -> str:
    """Return a deterministic opaque topic no longer than 32 characters."""

    if not valid_announcement_id(announcement_id):
        raise StudentPushInputError("announcement id is invalid")
    return "ann-" + hashlib.sha256(announcement_id.encode("utf-8")).hexdigest()[:28]


def build_announcement_payload(announcement_id: str) -> str:
    """Build the only payload shape permitted for student announcements."""

    if not valid_announcement_id(announcement_id):
        raise StudentPushInputError("announcement id is invalid")
    payload = {
        "type": "announcement",
        "announcementId": announcement_id,
        "url": "/app?announcement=" + quote(announcement_id, safe=""),
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 512:
        raise StudentPushInputError("announcement payload is too large")
    return encoded


def _validate_config(config: StudentPushConfig) -> Path:
    if not config.vapid_subject or not valid_vapid_subject(config.vapid_subject):
        raise StudentPushConfigurationError("VAPID subject must be a mailto address or HTTPS URL")
    if config.vapid_private_key_path is None:
        raise StudentPushConfigurationError("VAPID private-key path is required")
    path = validate_private_key_path(config.vapid_private_key_path)
    if not path.is_file():
        raise StudentPushConfigurationError("VAPID private-key file is unavailable")
    return path


def _status_from(value: StatusCarrier | BaseException | None) -> int | None:
    for candidate in (value, getattr(value, "response", None)):
        status = getattr(candidate, "status_code", None)
        if isinstance(status, int) and not isinstance(status, bool):
            return status
    return None


def _classify(status: int | None) -> PushResultStatus:
    if status is not None and 200 <= status < 300:
        return PushResultStatus.SUCCESS
    if status == 429 or (status is not None and status >= 500):
        return PushResultStatus.TRANSIENT_FAILURE
    if status is not None and 400 <= status < 500:
        return PushResultStatus.PERMANENT_FAILURE
    return PushResultStatus.TRANSIENT_FAILURE


def _classify_provider_exception(status: int | None) -> PushResultStatus:
    """Classify a provider exception without ever treating it as delivery."""

    if status is not None and 400 <= status < 500 and status != 429:
        return PushResultStatus.PERMANENT_FAILURE
    return PushResultStatus.TRANSIENT_FAILURE


def _is_timeout_error(error: BaseException) -> bool:
    """Recognize builtin and provider-specific timeout exception names."""

    return isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower()


class StudentPushSender:
    """Adapter that gates pywebpush and maps library outcomes to typed results."""

    def __init__(self, config: StudentPushConfig, transport: WebPushTransport | None = None, key_validator: VapidKeyValidator | None = None) -> None:
        self._config = config
        self._transport = transport
        self._key_validator = key_validator

    def public_key(self) -> str:
        """Derive the public VAPID key from the current private file, never cached."""

        path = _validate_config(self._config)
        try:
            return vapid_public_key_from_pem(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise StudentPushConfigurationError("VAPID private-key file is invalid") from exc

    def send(self, subscription: Mapping[str, JsonValue] | JsonValue, announcement_id: str) -> PushSendResult:
        """Send one generic announcement, without making a real request in tests."""

        if not self._config.enabled:
            return PushSendResult(PushResultStatus.DISABLED, reason="feature_disabled")
        topic: str | None = None
        try:
            parsed = parse_subscription(subscription)
            payload = build_announcement_payload(announcement_id)
            topic = announcement_topic(announcement_id)
            path = _validate_config(self._config)
            key_bytes = path.read_bytes()
            (self._key_validator or validate_vapid_private_key)(key_bytes)
        except StudentPushInputError as exc:
            return PushSendResult(PushResultStatus.INVALID_INPUT, reason=exc.reason, topic=topic)
        except StudentPushDependencyError as exc:
            return PushSendResult(PushResultStatus.DEPENDENCY_UNAVAILABLE, reason=exc.reason, topic=topic)
        except (StudentPushConfigurationError, OSError, ValueError) as exc:
            return PushSendResult(PushResultStatus.INVALID_CONFIGURATION, reason="configuration_unavailable", topic=topic)

        transport = self._transport
        if transport is None:
            try:
                module = importlib.import_module("pywebpush")
                candidate = getattr(module, "webpush", None)
                if not callable(candidate):
                    raise AttributeError("pywebpush.webpush is unavailable")
                transport = candidate
            except (ImportError, AttributeError):
                return PushSendResult(PushResultStatus.DEPENDENCY_UNAVAILABLE, reason="pywebpush_unavailable", topic=topic)
        try:
            response = transport(
                subscription_info=parsed.as_pywebpush(),
                data=payload,
                vapid_private_key=str(path),
                vapid_claims={"sub": self._config.vapid_subject or ""},
                ttl=PUSH_TTL_SECONDS,
                headers={"Urgency": PUSH_URGENCY, "Topic": topic},
            )
        except TimeoutError:
            return PushSendResult(PushResultStatus.TRANSIENT_FAILURE, reason="timeout", topic=topic)
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - third-party boundary
            status = _status_from(exc)
            if _is_timeout_error(exc):
                return PushSendResult(PushResultStatus.TRANSIENT_FAILURE, reason="timeout", http_status=status, topic=topic)
            reason = "transport_error" if status is not None else "transport_unavailable"
            return PushSendResult(_classify_provider_exception(status), reason=reason, http_status=status, topic=topic)
        status = _status_from(response)
        result_status = _classify(status)
        reason = "delivered" if result_status is PushResultStatus.SUCCESS else ("transport_unavailable" if status is None else "http_status")
        return PushSendResult(result_status, reason=reason, http_status=status, topic=topic)


__all__ = ["PUSH_TTL_SECONDS", "PUSH_URGENCY", "ParsedSubscription", "PushResultStatus", "PushSendResult", "StudentPushConfig", "StudentPushConfigurationError", "StudentPushDependencyError", "StudentPushInputError", "StudentPushKeyError", "StudentPushSender", "announcement_topic", "build_announcement_payload", "parse_subscription", "validate_private_key_path", "validate_public_output_path", "vapid_public_key_from_pem"]
