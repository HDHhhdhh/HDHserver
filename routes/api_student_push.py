"""Session-bound student Push API and announcement enqueue boundary."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from flask import Blueprint, Response, jsonify, request

from core.student_account_repository import AccountRepositoryError, StudentAccountRepository
from core.student_app_config import StudentAppConfig, load_student_app_config
from core.student_notification_events import NotificationInputError
from core.student_notification_hooks import enqueue_announcement_events
from core.student_notification_repository import (
    NotificationConflictError,
    NotificationNotInitializedError,
    StudentNotificationRepository,
)
from core.student_push_payload import JsonValue, StudentPushRepositoryInputError
from core.student_push_repository import StudentPushRepository
from core.student_push_sender import StudentPushConfig, StudentPushSender, build_announcement_payload
from core.student_push_validation import StudentPushConfigurationError, StudentPushInputError, parse_subscription
from core.student_session_input import StudentSessionInputError
from core.student_sessions import SessionView, StudentSessionRepository


_DEVICE_RE = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_CAPABILITY_KEYS = frozenset({"serviceWorker", "pushManager", "notification", "standalone"})
_BYPASS_SECONDS = 24 * 60 * 60


class PublicKeyProvider(Protocol):
    def public_key(self) -> str: ...


@dataclass(slots=True)
class StudentPushApiDependencies:
    config: StudentAppConfig
    accounts: StudentAccountRepository
    sessions: StudentSessionRepository
    push: StudentPushRepository
    sender: PublicKeyProvider
    clock: Callable[[], float] = time.time
    notifications: StudentNotificationRepository | None = None


@dataclass(slots=True)
class _DependencyProvider:
    dependencies: StudentPushApiDependencies | None = None

    def get(self) -> StudentPushApiDependencies:
        if self.dependencies is None:
            self.dependencies = _build_dependencies()
        return self.dependencies


def _build_dependencies() -> StudentPushApiDependencies:
    base = Path(__file__).resolve().parents[1]
    config = load_student_app_config()
    accounts_path = Path(os.environ.get("STUDENT_APP_ACCOUNTS_PATH", base / "auth_accounts.json"))
    students_path = Path(os.environ.get("STUDENT_APP_STUDENTS_PATH", base / "students.json"))
    db_path = Path(os.environ.get("STUDENT_APP_DB_PATH", base / "app.sqlite"))
    return StudentPushApiDependencies(
        config,
        StudentAccountRepository(accounts_path, students_path),
        StudentSessionRepository(db_path),
        StudentPushRepository(db_path),
        _build_sender(config),
        notifications=StudentNotificationRepository(db_path),
    )


def _build_sender(config: StudentAppConfig | None = None) -> StudentPushSender:
    selected = load_student_app_config() if config is None else config
    return StudentPushSender(StudentPushConfig(selected.public_enabled, selected.vapid_subject, selected.vapid_private_key_path))


_DEFAULT_PROVIDER = _DependencyProvider()


def _reply(payload: Mapping[str, JsonValue], status: int = 200) -> tuple[Response, int] | Response:
    response = jsonify(dict(payload))
    response.headers["Cache-Control"] = "no-store"
    return response if status == 200 else (response, status)


def _body() -> Mapping[str, JsonValue]:
    value = request.get_json(silent=True)
    return value if isinstance(value, Mapping) else {}


def _dependencies(provider: _DependencyProvider) -> StudentPushApiDependencies | None:
    try:
        return provider.get()
    except Exception:  # noqa: BROAD_EXCEPT_OK - configuration/storage details stay private
        return None


def _device(value: object) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text if _DEVICE_RE.fullmatch(text) else None


def _authorized(deps: StudentPushApiDependencies, *, csrf: bool) -> tuple[SessionView, dict[str, JsonValue]] | tuple[Response, int]:
    token = request.cookies.get(deps.config.cookie.name)
    if not token:
        return _reply({"ok": False, "code": "unauthenticated"}, 401)
    csrf_token = request.headers.get("X-CSRF-Token") if csrf else None
    if csrf and not csrf_token:
        return _reply({"ok": False, "code": "csrf_required"}, 403)
    try:
        view = deps.sessions.resolve(token, csrf_token=csrf_token if csrf else None)
        if view is None:
            code = "csrf_invalid" if csrf else "unauthenticated"
            return _reply({"ok": False, "code": code}, 403 if csrf else 401)
        account = deps.accounts.get(view["aid"])
    except (AccountRepositoryError, OSError, sqlite3.Error, StudentSessionInputError, ValueError):
        return _reply({"ok": False, "code": "unauthenticated"}, 401)
    sids = account.get("sids") if isinstance(account, dict) else None
    linked = {sid for sid in sids if isinstance(sid, str)} if isinstance(sids, list) else set()
    if not isinstance(account, dict) or account.get("disabled") is True or view["active_sid"] not in linked or view["active_sid"] not in view["allowed_sids"]:
        return _reply({"ok": False, "code": "unauthenticated"}, 401)
    if not deps.config.allows_canary_sid(view["active_sid"]):
        return _reply({"ok": False, "code": "unavailable"}, 404)
    if account.get("must_change_credentials") is True:
        return _reply({"ok": False, "code": "credentials_required"}, 403)
    return view, account


def _capabilities(value: JsonValue | None) -> dict[str, bool] | None:
    if not isinstance(value, Mapping) or set(value) != _CAPABILITY_KEYS:
        return None
    if any(type(item) is not bool for item in value.values()):
        return None
    return {key: bool(value[key]) for key in sorted(_CAPABILITY_KEYS)}


def default_push_repository() -> StudentPushRepository:
    """Return the lazy runtime repository used by announcement enqueue."""
    return _DEFAULT_PROVIDER.get().push


def enqueue_announcement(
    announcement_id: str,
    target_sids: Sequence[str],
    repository: StudentPushRepository | None = None,
    *,
    config: StudentAppConfig | None = None,
    notification_repository: StudentNotificationRepository | None = None,
) -> list[int]:
    """Dedupe rows only while the public rollout currently authorizes each SID."""

    selected = load_student_app_config() if config is None else config
    if not selected.public_enabled:
        return []
    targets = [
        sid
        for sid in dict.fromkeys(target_sids)
        if isinstance(sid, str) and sid and selected.allows_canary_sid(sid)
    ]
    if not targets:
        return []
    if selected.reminders_enabled:
        base = Path(__file__).resolve().parents[1]
        generic = notification_repository or StudentNotificationRepository(
            Path(os.environ.get("STUDENT_APP_DB_PATH", base / "app.sqlite"))
        )
        return enqueue_announcement_events(generic, str(announcement_id), targets, now=time.time())
    payload = json.loads(build_announcement_payload(str(announcement_id)))
    repo = repository or default_push_repository()
    return [repo.enqueue(str(announcement_id), sid, payload) for sid in targets]


def create_blueprint(dependencies: StudentPushApiDependencies | None = None) -> Blueprint:
    provider = _DEFAULT_PROVIDER if dependencies is None else _DependencyProvider(dependencies)
    blueprint = Blueprint("student_push", __name__, url_prefix="/api/mobile/push")

    @blueprint.get("/public-key")
    def public_key():
        try:
            key = (dependencies.sender if dependencies is not None else _build_sender()).public_key()
        except Exception:  # noqa: BROAD_EXCEPT_OK - configuration boundary stays generic
            return _reply({"ok": False, "code": "push_unavailable"}, 503)
        return _reply({"ok": True, "publicKey": key})

    @blueprint.get("/status")
    def status():
        deps = _dependencies(provider)
        if deps is None:
            return _reply({"ok": False, "code": "push_unavailable"}, 503)
        authorized = _authorized(deps, csrf=False)
        if isinstance(authorized[0], Response):
            return authorized
        view, _account = authorized
        device = _device(request.args.get("deviceId"))
        if device is None:
            return _reply({"ok": False, "code": "invalid_request"}, 400)
        try:
            expiry = deps.push.bypass_expiry(view["aid"], device)
            subscribed = deps.push.has_active_subscription(view["aid"], view["active_sid"], device)
        except Exception:  # noqa: BROAD_EXCEPT_OK - never expose SQLite or subscription data
            return _reply({"ok": False, "code": "push_unavailable"}, 503)
        return _reply({"ok": True, "subscribed": subscribed, "bypassExpiresAt": expiry, "pushRequired": not subscribed and expiry is None})

    @blueprint.post("/subscribe")
    def subscribe():
        deps = _dependencies(provider)
        if deps is None:
            return _reply({"ok": False, "code": "push_unavailable"}, 503)
        authorized = _authorized(deps, csrf=True)
        if isinstance(authorized[0], Response):
            return authorized
        view, _account = authorized
        data, device = _body(), None
        try:
            device = _device(data.get("deviceId"))
            raw_subscription = data.get("subscription")
            keys = raw_subscription.get("keys") if isinstance(raw_subscription, Mapping) else None
            if not isinstance(keys, Mapping) or set(keys) != {"p256dh", "auth"}:
                raise StudentPushInputError("subscription keys are invalid")
            parsed = parse_subscription(raw_subscription)
            if device is None:
                raise StudentPushInputError("device is invalid")
        except (StudentPushInputError, StudentPushRepositoryInputError, TypeError, ValueError):
            return _reply({"ok": False, "code": "invalid_subscription"}, 400)
        except StudentPushConfigurationError:
            return _reply({"ok": False, "code": "push_unavailable"}, 503)
        try:
            deps.push.upsert_subscription(view["aid"], view["active_sid"], device, parsed.endpoint, parsed.p256dh, parsed.auth, session_id=view["session_id"])
        except Exception:  # noqa: BROAD_EXCEPT_OK - never expose SQLite or subscription data
            return _reply({"ok": False, "code": "push_unavailable"}, 503)
        return _reply({"ok": True, "subscribed": True})

    @blueprint.post("/unsubscribe")
    def unsubscribe():
        deps = _dependencies(provider)
        if deps is None:
            return _reply({"ok": False, "code": "push_unavailable"}, 503)
        authorized = _authorized(deps, csrf=True)
        if isinstance(authorized[0], Response):
            return authorized
        view, _account = authorized
        device = _device(_body().get("deviceId"))
        if device is None:
            return _reply({"ok": False, "code": "invalid_request"}, 400)
        try:
            changed = deps.push.revoke_subscription(aid=view["aid"], sid=view["active_sid"], device_id=device)
        except Exception:  # noqa: BROAD_EXCEPT_OK - never expose SQLite or subscription data
            return _reply({"ok": False, "code": "push_unavailable"}, 503)
        return _reply({"ok": True, "unsubscribed": changed > 0})

    @blueprint.post("/bypass")
    def bypass():
        deps = _dependencies(provider)
        if deps is None:
            return _reply({"ok": False, "code": "push_unavailable"}, 503)
        authorized = _authorized(deps, csrf=True)
        if isinstance(authorized[0], Response):
            return authorized
        view, _account = authorized
        data = _body()
        device, capabilities = _device(data.get("deviceId")), _capabilities(data.get("capabilities"))
        if device is None or capabilities is None:
            return _reply({"ok": False, "code": "invalid_request"}, 400)
        if capabilities["serviceWorker"] and capabilities["pushManager"] and capabilities["notification"]:
            return _reply({"ok": False, "code": "bypass_not_available"}, 409)
        now = float(deps.clock())
        expires = now + _BYPASS_SECONDS
        try:
            deps.push.grant_bypass(view["aid"], device, expires_at=expires, capabilities=capabilities, now=now)
        except Exception:  # noqa: BROAD_EXCEPT_OK - never expose SQLite or capability data
            return _reply({"ok": False, "code": "push_unavailable"}, 503)
        return _reply({"ok": True, "bypassExpiresAt": expires})

    @blueprint.get("/preferences")
    def preferences_get():
        deps = _dependencies(provider)
        if deps is None or not deps.config.reminders_enabled:
            return _reply({"ok": False, "code": "unavailable"}, 404)
        authorized = _authorized(deps, csrf=False)
        if isinstance(authorized[0], Response):
            return authorized
        view, _account = authorized
        if request.args or deps.notifications is None:
            return _reply({"ok": False, "code": "invalid_request"}, 400) if request.args else _reply(
                {"ok": False, "code": "notification_unavailable"}, 503
            )
        try:
            result = deps.notifications.get_preferences(view["aid"])
        except NotificationNotInitializedError:
            return _reply({"ok": False, "code": "notification_unavailable"}, 503)
        except Exception:  # noqa: BROAD_EXCEPT_OK - storage details stay private
            return _reply({"ok": False, "code": "notification_unavailable"}, 503)
        return _reply({"ok": True, "preferences": result["categories"], "revision": result["revision"]})

    @blueprint.post("/preferences")
    def preferences_post():
        deps = _dependencies(provider)
        if deps is None or not deps.config.reminders_enabled:
            return _reply({"ok": False, "code": "unavailable"}, 404)
        authorized = _authorized(deps, csrf=True)
        if isinstance(authorized[0], Response):
            return authorized
        view, _account = authorized
        data = _body()
        if set(data) != {"preferences", "expectedRevision"} or deps.notifications is None:
            return _reply({"ok": False, "code": "invalid_request"}, 400) if deps.notifications is not None else _reply(
                {"ok": False, "code": "notification_unavailable"}, 503
            )
        try:
            result = deps.notifications.update_preferences(
                view["aid"],
                data.get("preferences"),
                expected_revision=data.get("expectedRevision"),
                now=deps.clock(),
            )
        except NotificationInputError:
            return _reply({"ok": False, "code": "invalid_request"}, 400)
        except NotificationConflictError:
            return _reply({"ok": False, "code": "preference_revision_conflict"}, 409)
        except NotificationNotInitializedError:
            return _reply({"ok": False, "code": "notification_unavailable"}, 503)
        except Exception:  # noqa: BROAD_EXCEPT_OK - storage details stay private
            return _reply({"ok": False, "code": "notification_unavailable"}, 503)
        return _reply({"ok": True, "preferences": result["categories"], "revision": result["revision"]})

    return blueprint


bp_api_student_push = create_blueprint()


__all__ = ["StudentPushApiDependencies", "bp_api_student_push", "create_blueprint", "default_push_repository", "enqueue_announcement"]
