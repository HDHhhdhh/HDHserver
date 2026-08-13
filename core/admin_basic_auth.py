"""Fail-closed HTTP Basic authentication for academy administration."""
from __future__ import annotations

import base64
import binascii
import hmac
import os
from collections.abc import Mapping
from typing import Final

from werkzeug.security import check_password_hash

ADMIN_USERNAME_ENV: Final = "ACADEMY_ADMIN_USERNAME"
ADMIN_PASSWORD_HASH_ENV: Final = "ACADEMY_ADMIN_PASSWORD_HASH"
ADMIN_AUTH_CHALLENGE: Final = 'Basic realm="Academy Admin", charset="UTF-8"'


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
    credentials = _basic_credentials(authorization)
    if not expected_username or not password_hash or credentials is None:
        return False
    username, password = credentials
    username_matches = hmac.compare_digest(username.encode("utf-8"), expected_username.encode("utf-8"))
    try:
        password_matches = check_password_hash(password_hash, password)
    except (TypeError, ValueError):
        password_matches = False
    return username_matches and password_matches


__all__ = (
    "ADMIN_AUTH_CHALLENGE",
    "ADMIN_PASSWORD_HASH_ENV",
    "ADMIN_USERNAME_ENV",
    "verify_admin_authorization",
)
