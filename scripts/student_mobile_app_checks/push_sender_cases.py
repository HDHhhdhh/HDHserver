"""Focused, network-free contract checks for the student Push sender."""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import types
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_push_sender import (  # noqa: E402
    PushResultStatus,
    StudentPushConfigurationError,
    StudentPushDependencyError,
    StudentPushInputError,
    StudentPushKeyError,
    StudentPushConfig,
    StudentPushSender,
    WebPushTransport,
    announcement_topic,
    build_announcement_payload,
    parse_subscription,
    validate_private_key_path,
    vapid_public_key_from_pem,
)
from scripts.student_mobile_app_checks.push_sender_generator_cases import run_generator_check, run_generator_command, run_generator_rollback_check  # noqa: E402


_DUMMY_PEM: Final = b"-----BEGIN EC PRIVATE KEY-----\nfixture\n-----END EC PRIVATE KEY-----\n"
FakeKwarg: TypeAlias = str | int | dict[str, str] | dict[str, dict[str, str]]


def _assert(condition: bool, message: str, count: list[int]) -> None:
    count[0] += 1
    if not condition:
        raise AssertionError(message)


class _FakeResponse:
    def __init__(self, status_code: int | None) -> None:
        self.status_code = status_code


class _FakePushError(Exception):
    def __init__(self, status_code: int) -> None:
        self.response = _FakeResponse(status_code)


class _FakeRuntimeFailure(Exception):
    """Unknown transport failure used to verify fail-closed result mapping."""


class _FakeTransport:
    def __init__(self, outcome: int | str) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, str | int]] = []
        self.raw_keys: list[frozenset[str]] = []
        self.raw_call: dict[str, FakeKwarg] | None = None

    def __call__(self, **kwargs: FakeKwarg) -> _FakeResponse:
        self.raw_keys.append(frozenset(kwargs))
        self.raw_call = kwargs
        data = kwargs["data"]
        self.calls.append({
            "data": str(data),
            "ttl": int(kwargs["ttl"]),
            "headers": str(kwargs["headers"]),
        })
        if self.outcome == "timeout":
            raise TimeoutError
        if self.outcome == "provider-timeout":
            raise _FakeProviderTimeout("endpoint, auth, and payload must stay private")
        if self.outcome == "runtime":
            raise _FakeRuntimeFailure("secret-shaped endpoint auth payload")
        if self.outcome == "exception-success":
            raise _FakePushError(201)
        if self.outcome == "none":
            return None
        if self.outcome == "status-none":
            return _FakeResponse(None)
        if isinstance(self.outcome, int):
            if self.outcome >= 400:
                raise _FakePushError(self.outcome)
            return _FakeResponse(self.outcome)
        return _FakeResponse(201)


class _FakeProviderTimeout(Exception):
    """Timeout-shaped provider failure whose message contains secrets."""


def _subscription() -> dict[str, str | dict[str, str]]:
    p256dh = base64.urlsafe_b64encode(b"\x04" + b"\x01" * 64).rstrip(b"=").decode("ascii")
    auth = base64.urlsafe_b64encode(b"\x02" * 16).rstrip(b"=").decode("ascii")
    return {
        "endpoint": "https://push.example.test/send/opaque",
        "keys": {"p256dh": p256dh, "auth": auth},
    }


def _fixture_key_validator(_pem: bytes) -> None:
    """Test seam: accept the fixture without reproducing production PEM parsing."""


def _fixture_sender(config: StudentPushConfig, transport: WebPushTransport | None) -> StudentPushSender:
    return StudentPushSender(config, transport, _fixture_key_validator)


def run_checks() -> dict[str, str | int | bool]:
    """Exercise result mapping, privacy, dependency gates, and generator safety."""

    count = [0]
    subscription = _subscription()
    parsed = parse_subscription(subscription)
    _assert(parsed.endpoint.startswith("https://"), "HTTPS subscription was not parsed", count)
    _assert(parsed.as_pywebpush()["keys"]["auth"] == subscription["keys"]["auth"], "subscription key shape mismatch", count)
    try:
        parse_subscription({"endpoint": "http://insecure.test", "keys": subscription["keys"]})
    except StudentPushInputError:
        count[0] += 1
    else:
        raise AssertionError("non-HTTPS endpoint was accepted")
    try:
        parse_subscription({"endpoint": "https://[malformed", "keys": subscription["keys"]})
    except StudentPushInputError:
        count[0] += 1
    else:
        raise AssertionError("malformed HTTPS endpoint was accepted")
    valid_keys = subscription["keys"]
    if not isinstance(valid_keys, dict):
        raise AssertionError("fixture keys were not a dict")
    invalid_shapes = (
        ("short_p256dh", {"p256dh": "x", "auth": valid_keys["auth"]}),
        ("wrong_prefix", {"p256dh": base64.urlsafe_b64encode(b"\x02" + b"\x01" * 64).rstrip(b"=").decode("ascii"), "auth": valid_keys["auth"]}),
        ("wrong_length", {"p256dh": base64.urlsafe_b64encode(b"\x04" + b"\x01" * 63).rstrip(b"=").decode("ascii"), "auth": valid_keys["auth"]}),
        ("invalid_base64", {"p256dh": "!", "auth": valid_keys["auth"]}),
        ("short_auth", {"p256dh": valid_keys["p256dh"], "auth": "x"}),
    )
    for label, invalid_keys in invalid_shapes:
        try:
            parse_subscription({"endpoint": subscription["endpoint"], "keys": invalid_keys})
        except StudentPushInputError:
            count[0] += 1
        else:
            raise AssertionError(f"{label} subscription key shape was accepted")

    _assert(len(announcement_topic("announcement-1")) <= 32, "topic exceeds Web Push limit", count)
    _assert(announcement_topic("announcement-1") == announcement_topic("announcement-1"), "topic is not deterministic", count)
    payload = json.loads(build_announcement_payload("announcement-1"))
    _assert(set(payload) == {"type", "announcementId", "url"}, "payload is not privacy-minimal", count)
    _assert("push.example" not in json.dumps(payload), "payload leaked endpoint data", count)

    try:
        vapid_public_key_from_pem(_DUMMY_PEM)
    except StudentPushDependencyError:
        count[0] += 1
    except ValueError:
        count[0] += 1
    else:
        raise AssertionError("public-key derivation unexpectedly succeeded without a provider")

    with tempfile.TemporaryDirectory(prefix="student-push-check-") as temporary:
        key_path = Path(temporary) / "instance" / "vapid-private.pem"
        key_path.parent.mkdir(parents=True)
        key_path.write_bytes(_DUMMY_PEM)
        config = StudentPushConfig(enabled=True, vapid_subject="mailto:student@example.test", vapid_private_key_path=key_path)
        expected = {
            201: PushResultStatus.SUCCESS,
            404: PushResultStatus.PERMANENT_FAILURE,
            410: PushResultStatus.PERMANENT_FAILURE,
            429: PushResultStatus.TRANSIENT_FAILURE,
            500: PushResultStatus.TRANSIENT_FAILURE,
            301: PushResultStatus.TRANSIENT_FAILURE,
            "exception-success": PushResultStatus.TRANSIENT_FAILURE,
            "timeout": PushResultStatus.TRANSIENT_FAILURE,
        }
        for outcome, status in expected.items():
            fake = _FakeTransport(outcome)
            result = _fixture_sender(config, fake).send(subscription, "announcement-1")
            _assert(result.status is status, f"status {outcome!r} was classified incorrectly", count)
            if outcome == 201:
                call = fake.calls[0]
                _assert(call["ttl"] == 86_400 and "'Urgency': 'normal'" in str(call["headers"]), "Web Push options mismatch", count)
                _assert("'Topic': 'ann-" in str(call["headers"]) and len(announcement_topic("announcement-1")) <= 32, "topic option exceeds 32 characters", count)
                _assert(set(json.loads(str(call["data"]))) == {"type", "announcementId", "url"}, "fake transport saw non-minimal payload", count)
                _assert(fake.raw_keys == [frozenset({"subscription_info", "data", "vapid_private_key", "vapid_claims", "ttl", "headers"})], "pywebpush contract received direct urgency/topic kwargs", count)
                _assert(fake.raw_call is not None and str(fake.raw_call["vapid_private_key"]) == str(key_path), "private key bytes/path contract changed", count)
                _assert(fake.raw_call is not None and fake.raw_call["vapid_claims"] == {"sub": "mailto:student@example.test"}, "VAPID subject claim mismatch", count)
        privacy_fake = _FakeTransport("provider-timeout")
        privacy_result = _fixture_sender(config, privacy_fake).send(subscription, "announcement-1")
        _assert(privacy_result.status is PushResultStatus.TRANSIENT_FAILURE, "provider timeout was not transient", count)
        _assert("endpoint" not in privacy_result.reason and "auth" not in privacy_result.reason and "payload" not in privacy_result.reason, "provider details leaked in result", count)
        for outcome in ("runtime", "none", "status-none"):
            unknown_fake = _FakeTransport(outcome)
            unknown_result = _fixture_sender(config, unknown_fake).send(subscription, "announcement-1")
            _assert(unknown_result.status is PushResultStatus.TRANSIENT_FAILURE and not unknown_result.ok, f"{outcome} was not fail-closed", count)
            _assert(unknown_result.http_status is None and len(unknown_fake.calls) == 1 and "secret" not in unknown_result.reason, f"{outcome} leaked or skipped transport accounting", count)
        def reject_fixture_key(_pem: bytes) -> None:
            raise StudentPushKeyError("fixture key rejected")

        malformed_fake = _FakeTransport(201)
        malformed_result = StudentPushSender(config, malformed_fake, reject_fixture_key).send(subscription, "announcement-1")
        _assert(malformed_result.status is PushResultStatus.INVALID_CONFIGURATION and not malformed_fake.calls, "malformed key reached transport", count)
        fake_module = types.ModuleType("pywebpush")
        lazy_fake = _FakeTransport(201)
        setattr(fake_module, "webpush", lazy_fake)
        previous_module = sys.modules.get("pywebpush")
        sys.modules["pywebpush"] = fake_module
        try:
            lazy_result = _fixture_sender(config, None).send(subscription, "announcement-1")
        finally:
            if previous_module is None:
                sys.modules.pop("pywebpush", None)
            else:
                sys.modules["pywebpush"] = previous_module
        _assert(lazy_result.status is PushResultStatus.SUCCESS and lazy_fake.raw_call is not None, "lazy pywebpush.webpush adapter was not called", count)
        malformed = _fixture_sender(config, _FakeTransport(201)).send(None, "announcement-1")
        _assert(malformed.status is PushResultStatus.INVALID_INPUT, "malformed subscription was accepted", count)
        oversized = _fixture_sender(config, _FakeTransport(201)).send(subscription, "a" * 129)
        _assert(oversized.status is PushResultStatus.INVALID_INPUT, "oversized announcement id was accepted", count)
        bad_subject = _fixture_sender(StudentPushConfig(enabled=True, vapid_subject="not-mailto", vapid_private_key_path=key_path), _FakeTransport(201)).send(subscription, "announcement-1")
        _assert(bad_subject.status is PushResultStatus.INVALID_CONFIGURATION, "invalid VAPID subject was accepted", count)
        missing_subject = _fixture_sender(StudentPushConfig(enabled=True, vapid_private_key_path=key_path), _FakeTransport(201)).send(subscription, "announcement-1")
        _assert(missing_subject.status is PushResultStatus.INVALID_CONFIGURATION, "missing VAPID subject did not fail closed", count)
        missing_key = _fixture_sender(StudentPushConfig(enabled=True, vapid_subject="mailto:student@example.test"), _FakeTransport(201)).send(subscription, "announcement-1")
        _assert(missing_key.status is PushResultStatus.INVALID_CONFIGURATION, "missing VAPID key did not fail closed", count)
        https_subject = _fixture_sender(StudentPushConfig(enabled=True, vapid_subject="https://app.example.test/contact", vapid_private_key_path=key_path), _FakeTransport(201)).send(subscription, "announcement-1")
        _assert(https_subject.status is PushResultStatus.SUCCESS, "valid HTTPS VAPID subject was rejected", count)
        default_fake = _FakeTransport(201)
        default_result = StudentPushSender(config, default_fake).send(subscription, "announcement-1")
        _assert(default_result.status in (PushResultStatus.INVALID_CONFIGURATION, PushResultStatus.DEPENDENCY_UNAVAILABLE) and not default_fake.calls, "marker-only PEM reached transport without a vetted provider", count)
        key_path.unlink()
        stale = _fixture_sender(config, _FakeTransport(201)).send(subscription, "announcement-1")
        _assert(stale.status is PushResultStatus.INVALID_CONFIGURATION, "removed key did not fail closed", count)

        disabled = _fixture_sender(StudentPushConfig(enabled=False), None).send({"bad": "shape"}, "bad")
        _assert(disabled.status is PushResultStatus.DISABLED, "feature-off sender did not short-circuit", count)

        imported_before = {name for name in sys.modules if name == "pywebpush" or name.startswith(("cryptography", "py_vapid"))}
        _fixture_sender(StudentPushConfig(enabled=False), None).send(subscription, "announcement-1")
        imported_after = {name for name in sys.modules if name == "pywebpush" or name.startswith(("cryptography", "py_vapid"))}
        _assert(imported_before == imported_after, "feature-off sender imported provider dependencies", count)

        missing_dependency = key_path
        missing_dependency.write_bytes(_DUMMY_PEM)
        previous = sys.modules.get("pywebpush")
        sys.modules["pywebpush"] = None
        try:
            result = _fixture_sender(config, None).send(subscription, "announcement-1")
        finally:
            if previous is None:
                sys.modules.pop("pywebpush", None)
            else:
                sys.modules["pywebpush"] = previous
        _assert(result.status is PushResultStatus.DEPENDENCY_UNAVAILABLE, "missing dependency did not fail closed", count)

    try:
        validate_private_key_path(ROOT / "core" / "tracked-key.pem")
    except StudentPushConfigurationError:
        count[0] += 1
    else:
        raise AssertionError("tracked source key path was accepted")
    with tempfile.TemporaryDirectory(prefix="student-vapid-boundary-") as temporary:
        outside_private = Path(temporary) / "instance" / "private.pem"
        tracked_public = ROOT / "scripts" / "student-vapid-public-negative.txt"
        command = [sys.executable, str(ROOT / "scripts" / "generate_student_vapid_key.py"), "--private-path", str(outside_private), "--public-output", str(tracked_public)]
        boundary = run_generator_command(command)
        _assert(boundary.returncode == 2, "tracked public output path was accepted", count)
        _assert("tracked source" in boundary.stderr.lower() or "runtime" in boundary.stderr.lower(), "public output boundary failure was not explicit", count)
        _assert(not tracked_public.exists(), "tracked public output path was created", count)
    requirements = [line.strip() for line in (ROOT / "requirements-student-app.txt").read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    _assert(requirements == ["pywebpush==2.3.0"], "student-app dependency pin is not exactly pywebpush 2.3.0", count)
    sender_source = (ROOT / "core" / "student_push_sender.py").read_text(encoding="utf-8")
    for marker in ("AESGCM(", "ECDH(", "HKDF(", "ec.ECDSA("):
        _assert(marker not in sender_source, f"handwritten crypto marker found: {marker}", count)
    _assert("import pywebpush" not in sender_source, "pywebpush was imported eagerly", count)
    def record(condition: bool, message: str) -> None: _assert(condition, message, count)
    run_generator_check(record)
    run_generator_rollback_check(record)
    return {"name": "push-sender", "assertions": count[0], "passed": True}
