"""Characterization and contract checks for the isolated student-app config."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Final


ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _assert(condition: bool, message: str, count: list[int]) -> None:
    count[0] += 1
    if not condition:
        raise AssertionError(message)


def _clean_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("STUDENT_APP_")
    }


def _load_config(env: dict[str, str]):
    module = importlib.import_module("core.student_app_config")
    return module, module.load_student_app_config(env)


def _expect_config_error(module, env: dict[str, str], count: list[int]) -> None:
    try:
        module.load_student_app_config(env)
    except module.StudentAppConfigurationError:
        count[0] += 1
    else:
        raise AssertionError("malformed configuration must fail with a typed error")


def run_checks() -> dict[str, object]:  # noqa: DICT_OK # noqa: OBJECT_OK -- dispatcher contract is intentionally generic
    """Run config checks without importing runtime paths or the Flask app."""
    count = [0]
    before_module = set(ROOT.glob("__config_import_probe__*"))
    with tempfile.TemporaryDirectory(prefix="student-app-config-import-") as tmp:
        probe = Path(tmp)
        before = tuple(probe.iterdir())
        module = importlib.import_module("core.student_app_config")
        importlib.reload(module)
        after = tuple(probe.iterdir())
    _assert(before == after, "isolated config import wrote to its working directory", count)
    _assert(before_module == set(ROOT.glob("__config_import_probe__*")), "config import created a probe", count)

    env = _clean_env()
    module, default = _load_config(env)
    _assert(default.public_enabled is False, "public mode must default off", count)
    _assert(default.legacy_redirect_enabled is False, "legacy redirect must default off", count)
    _assert(default.dashboard_enabled is False, "dashboard feature must default off", count)
    _assert(default.homework_enabled is False, "homework feature must default off", count)
    _assert(default.reminders_enabled is False, "reminders feature must default off", count)
    _assert(default.focus_enabled is False, "focus feature must default off", count)
    _assert(default.public_host == "app.5a-math.com", "default public host mismatch", count)
    _assert(default.legacy_host == "5a-math.com", "default legacy host mismatch", count)
    _assert(default.session_cookie_name == "student_app_session", "default cookie name mismatch", count)
    _assert(default.canary_sids == frozenset(), "default canary set must be empty", count)
    _assert(default.trusted_proxy_cidrs == ("127.0.0.0/8", "::1/128"), "default proxy loopback mismatch", count)
    _assert(default.session_cookie_secure is True, "secure cookie must be the default", count)
    _assert(default.vapid_subject is None, "VAPID subject must be unset by default", count)
    _assert(default.vapid_private_key_path is None, "VAPID private key must be unset by default", count)
    first_map = _clean_env() | {"STUDENT_APP_PUBLIC_HOST": "first.example.test"}
    second_map = _clean_env() | {"STUDENT_APP_PUBLIC_HOST": "second.example.test"}
    _assert(_load_config(first_map)[1].public_host == "first.example.test", "first env map was not honored", count)
    _assert(_load_config(second_map)[1].public_host == "second.example.test", "config values leaked across env maps", count)

    env = _clean_env() | {
        "STUDENT_APP_PUBLIC_ENABLED": "1",
        "STUDENT_APP_DASHBOARD_ENABLED": "true",
        "STUDENT_APP_HOMEWORK_ENABLED": "yes",
        "STUDENT_APP_REMINDERS_ENABLED": "on",
        "STUDENT_APP_FOCUS_ENABLED": "1",
        "STUDENT_APP_PUBLIC_HOST": "APP.5A-MATH.COM:443",
        "STUDENT_APP_LEGACY_HOST": "5A-MATH.COM:443",
        "STUDENT_APP_LEGACY_REDIRECT_ENABLED": "1",
        "STUDENT_APP_TRUSTED_PROXIES": "127.0.0.1, 2001:db8::/32",
        "STUDENT_APP_CANARY_SIDS": "sid-a,sid-b,sid-a",
        "STUDENT_APP_SESSION_COOKIE_SECURE": "0",
        "STUDENT_APP_TEST_INSECURE_COOKIE": "1",
        "STUDENT_APP_VAPID_SUBJECT": "mailto:student@example.test",
        "STUDENT_APP_VAPID_PRIVATE_KEY_PATH": "instance/student-vapid.pem",
    }
    module, configured = _load_config(env)
    _assert(configured.public_enabled is True, "enabled flag was not parsed", count)
    _assert(configured.legacy_redirect_enabled is True, "legacy redirect flag was not parsed", count)
    _assert(configured.dashboard_enabled is True, "dashboard feature flag was not parsed", count)
    _assert(configured.homework_enabled is True, "homework feature flag was not parsed", count)
    _assert(configured.reminders_enabled is True, "reminders feature flag was not parsed", count)
    _assert(configured.focus_enabled is True, "focus feature flag was not parsed", count)
    _assert(configured.public_host == "app.5a-math.com", "host was not normalized", count)
    _assert(configured.legacy_host == "5a-math.com", "legacy host was not normalized", count)
    _assert(configured.trusted_proxy_cidrs == ("127.0.0.1/32", "2001:db8::/32"), "proxy CIDRs were not normalized", count)
    _assert(configured.canary_sids == frozenset({"sid-a", "sid-b"}), "canary SID set is not exact", count)
    _assert(configured.session_cookie_secure is False, "explicit insecure test override was ignored", count)
    _assert(configured.vapid_subject == "mailto:student@example.test", "VAPID subject mismatch", count)
    _assert(str(configured.vapid_private_key_path).endswith("instance\\student-vapid.pem"), "VAPID path mismatch", count)
    _assert(configured.cookie.httponly and configured.cookie.path == "/", "session cookie safety attributes mismatch", count)
    _assert(configured.cookie.samesite == "Lax" and configured.cookie.max_age > 0, "session cookie lifetime mismatch", count)
    _assert(configured.cookie.domain is None, "session cookie must be host-only", count)
    dump = configured.redacted_dict()
    _assert("vapid_private_key_path" not in dump, "config dump must omit private key path", count)
    _assert(dump["vapid_configured"] is True, "config dump must expose only VAPID presence", count)
    _assert(dump["dashboard_enabled"] is True, "config dump omitted dashboard feature state", count)
    _assert(dump["homework_enabled"] is True, "config dump omitted homework feature state", count)
    _assert(dump["reminders_enabled"] is True, "config dump omitted reminders feature state", count)
    _assert(dump["focus_enabled"] is True, "config dump omitted focus feature state", count)
    _assert(dump["legacy_redirect_enabled"] is True, "config dump omitted legacy redirect state", count)
    _assert(dump["legacy_host"] == "5a-math.com", "config dump omitted legacy host", count)

    for key, value in (
        ("STUDENT_APP_PUBLIC_HOST", "https://bad/path"),
        ("STUDENT_APP_PUBLIC_HOST", ""),
        ("STUDENT_APP_LEGACY_HOST", "https://bad/path"),
        ("STUDENT_APP_LEGACY_REDIRECT_ENABLED", "sometimes"),
        ("STUDENT_APP_TRUSTED_PROXIES", "not-a-cidr"),
        ("STUDENT_APP_CANARY_SIDS", "sid with spaces"),
        ("STUDENT_APP_PUBLIC_ENABLED", "sometimes"),
        ("STUDENT_APP_DASHBOARD_ENABLED", "sometimes"),
        ("STUDENT_APP_HOMEWORK_ENABLED", "sometimes"),
        ("STUDENT_APP_REMINDERS_ENABLED", "sometimes"),
        ("STUDENT_APP_FOCUS_ENABLED", "sometimes"),
        ("STUDENT_APP_SESSION_COOKIE_SECURE", "maybe"),
    ):
        malformed = _clean_env() | {key: value}
        _expect_config_error(module, malformed, count)

    _expect_config_error(module, _clean_env() | {
        "STUDENT_APP_PUBLIC_HOST": "same.example",
        "STUDENT_APP_LEGACY_HOST": "same.example",
    }, count)

    return {
        "name": "config",
        "assertions": count[0],
        "passed": True,
        "config": dump,
    }


def main() -> int:
    """Run checks as a standalone command."""
    result = run_checks()
    print(f"config checks passed: {result['assertions']} assertions")
    return 0 if result["passed"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
