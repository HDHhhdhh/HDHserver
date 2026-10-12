"""Fail-closed HTTP Basic authentication for academy administration."""
from __future__ import annotations

import base64
import binascii
import hmac
import ipaddress
import os
from collections.abc import Mapping
from typing import Final

from werkzeug.security import check_password_hash

from core.admin_auth_cache import SuccessfulAuthCache
from core.network_access import RequestLike, client_ip_from_request, ip_allowed


ADMIN_USERNAME_ENV: Final = "ACADEMY_ADMIN_USERNAME"
ADMIN_PASSWORD_HASH_ENV: Final = "ACADEMY_ADMIN_PASSWORD_HASH"
ADMIN_AUTH_CHALLENGE: Final = 'Basic realm="Academy Admin", charset="UTF-8"'
EXTERNAL_ADMIN_API_EXEMPT_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/api/announce-ack",
        "/api/announce-submit",
        "/api/feedback",
        "/api/get-url",
        "/api/kollus/lms-callback",
        "/api/ping",
        "/api/student/bootstrap",
        "/api/watch-status",
    }
)
EXTERNAL_ADMIN_API_EXEMPT_PREFIXES: Final[tuple[str, ...]] = (
    "/api/auth/",
    "/api/mobile/",
)

_SUCCESS_CACHE = SuccessfulAuthCache()


def _configured_value(values: Mapping[str, str] | None, name: str) -> str:
    source = os.environ if values is None else values
    value = source.get(name, "")
    return value.strip() if isinstance(value, str) else ""


def _basic_credentials(authorization: str | None) -> tuple[str, str] | None:
    if not isinstance(authorization, str):
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].casefold() != "basic":
        return None
    try:
        decoded = base64.b64decode(parts[1], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator or not username or any(char in username for char in "\r\n\x00"):
        return None
    if any(char in password for char in "\r\n\x00"):
        return None
    return username, password


def verify_admin_authorization(
    authorization: str | None,
    values: Mapping[str, str] | None = None,
) -> bool:
    """Verify one UTF-8 Basic header against environment-backed hash config."""
    expected_username = _configured_value(values, ADMIN_USERNAME_ENV)
    password_hash = _configured_value(values, ADMIN_PASSWORD_HASH_ENV)
    generation = _SUCCESS_CACHE.observe_configuration(expected_username, password_hash)
    credentials = _basic_credentials(authorization)
    if not expected_username or not password_hash or credentials is None:
        return False
    username, password = credentials
    try:
        username_matches = hmac.compare_digest(username.encode("utf-8"), expected_username.encode("utf-8"))
    except UnicodeEncodeError:
        return False
    def check() -> bool:
        try:
            password_matches = check_password_hash(password_hash, password)
        except (TypeError, ValueError):
            password_matches = False
        return username_matches and password_matches

    verified = _SUCCESS_CACHE.verify(generation, username, password, check)
    # A configuration change during a KDF or cache lookup revokes that result.
    current_generation = _SUCCESS_CACHE.observe_configuration(
        _configured_value(values, ADMIN_USERNAME_ENV),
        _configured_value(values, ADMIN_PASSWORD_HASH_ENV),
    )
    return verified and generation == current_generation


def admin_network_allowed(request_like: RequestLike | None = None) -> bool:
    """Allow administration only from academy ranges or the server itself."""
    client_ip = client_ip_from_request(request_like)
    if ip_allowed(client_ip):
        return True
    try:
        return ipaddress.ip_address(client_ip).is_loopback
    except ValueError:
        return False


def external_admin_api_auth_required(
    path: str,
    request_like: RequestLike | None = None,
    *,
    method: str = "GET",
    public_request: bool = False,
    student_scoped: bool = False,
) -> bool:
    """Classify non-public, off-academy API requests that need admin Basic auth."""
    normalized_path = str(path or "").rstrip("/") or "/"
    if not normalized_path.startswith("/api/"):
        return False
    if public_request or normalized_path in EXTERNAL_ADMIN_API_EXEMPT_PATHS:
        return False
    if any(normalized_path.startswith(prefix) for prefix in EXTERNAL_ADMIN_API_EXEMPT_PREFIXES):
        return False
    normalized_method = str(method or "").upper()
    if normalized_path == "/api/watch" and normalized_method == "POST":
        return False
    student_query_paths = {"/api/announcements", "/api/announce-status", "/api/watch/latest"}
    if (
        student_scoped and normalized_path in student_query_paths and normalized_method in {"GET", "HEAD"}
    ):
        return False
    return not admin_network_allowed(request_like)


__all__ = (
    "ADMIN_AUTH_CHALLENGE",
    "EXTERNAL_ADMIN_API_EXEMPT_PATHS",
    "EXTERNAL_ADMIN_API_EXEMPT_PREFIXES",
    "ADMIN_PASSWORD_HASH_ENV",
    "ADMIN_USERNAME_ENV",
    "admin_network_allowed",
    "external_admin_api_auth_required",
    "verify_admin_authorization",
)
