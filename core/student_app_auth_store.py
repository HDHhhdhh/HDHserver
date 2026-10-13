"""Small, injected file-store helpers for public student authentication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import secrets
from pathlib import Path
from typing import Mapping, Sequence, TypeAlias, TypedDict

from werkzeug.security import generate_password_hash

from core.storage import file_lock, save_atomic
from core.stores import get_store
from core.student_account_rules import account_id_key, normalize_account_id

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
StudentRecord: TypeAlias = Mapping[str, JsonValue]


class Curriculum(TypedDict):
    """Safe curriculum projection returned to the mobile client."""

    cur: str
    sid: str


@dataclass(frozen=True, slots=True)
class StudentAuthStoreError(Exception):
    """Typed file-store failure without account or secret disclosure."""

    reason: str

    def __str__(self) -> str:
        return f"student auth store: {self.reason}"


def _read(path: Path, default: JsonValue) -> JsonValue:
    try:
        return json.loads(path.read_text("utf-8-sig"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise StudentAuthStoreError("malformed_json") from exc


def load_students(path: Path) -> tuple[StudentRecord, ...]:
    """Read roster rows from an injected path without creating it."""
    value = _read(path, [])
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise StudentAuthStoreError("malformed_students")
    return tuple(row for row in value if isinstance(row, dict))


def student_sid(student: StudentRecord) -> str:
    """Return one normalized roster SID or an empty value."""
    value = student.get("id")
    return value.strip() if isinstance(value, str) else ""


def narrow_sids(stored: Sequence[str], students: Sequence[StudentRecord]) -> tuple[str, ...]:
    """Keep account SIDs that still exist in the current roster, in stored order."""
    current = {sid for row in students if (sid := student_sid(row))}
    seen: set[str] = set()
    result: list[str] = []
    for sid in stored:
        if sid in current and sid not in seen:
            result.append(sid)
            seen.add(sid)
    return tuple(result)


def curriculum_rows(sids: Sequence[str], students: Sequence[StudentRecord]) -> tuple[Curriculum, ...]:
    """Build a deterministic, non-sensitive curriculum projection."""
    wanted = set(sids)
    rows: list[Curriculum] = []
    for student in students:
        sid = student_sid(student)
        curriculum = student.get("curriculum")
        if sid in wanted and isinstance(curriculum, str) and curriculum.strip():
            rows.append({"cur": curriculum.strip(), "sid": sid})
    rows.sort(key=lambda row: (row["cur"], row["sid"]))
    return tuple(rows)


def account_sids(record: Mapping[str, JsonValue]) -> tuple[str, ...]:
    """Parse only string SIDs from an account record."""
    value = record.get("sids")
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip()) if isinstance(value, list) else ()


def _accounts(path: Path) -> dict[str, JsonValue]:
    value = _read(path, {})
    if not isinstance(value, dict):
        raise StudentAuthStoreError("malformed_accounts")
    return value


def _find_key(accounts: Mapping[str, JsonValue], identifier: str) -> str | None:
    key = account_id_key(identifier)
    for candidate in accounts:
        try:
            if account_id_key(candidate) == key:
                return candidate
        except ValueError:
            continue
    return None


def create_account(path: Path, identifier: str, sids: Sequence[str]) -> str:
    """Create an activation account while preserving unrelated map fields."""
    normalized = normalize_account_id(identifier)
    sid_list = tuple(dict.fromkeys(sids))
    if not sid_list:
        raise StudentAuthStoreError("no_linked_sid")
    with file_lock(path):
        accounts = _accounts(path)
        if _find_key(accounts, normalized) is not None:
            raise StudentAuthStoreError("account_exists")
        now = datetime.now(timezone.utc).isoformat()
        accounts[normalized] = {
            "sids": list(sid_list),
            "pw_hash": generate_password_hash("1234"),
            "must_change_credentials": True,
            "disabled": False,
            "created_at": now,
            "updated_at": now,
            "credentials_updated_at": now,
            "legacy_session_id": secrets.token_urlsafe(32),
        }
        get_store("accounts", path).write_data_locked(accounts, writer=save_atomic)
    return normalized


def change_credentials(path: Path, current_id: str, new_id: str, password_hash: str) -> str:
    """Atomically rename/update one account and preserve unknown fields."""
    current = normalize_account_id(current_id)
    target = normalize_account_id(new_id)
    with file_lock(path):
        accounts = _accounts(path)
        current_key = _find_key(accounts, current)
        if current_key is None:
            raise StudentAuthStoreError("account_missing")
        target_key = _find_key(accounts, target)
        if target_key is not None and target_key != current_key:
            raise StudentAuthStoreError("id_collision")
        value = accounts.get(current_key)
        if not isinstance(value, dict):
            raise StudentAuthStoreError("malformed_account")
        record = dict(value)
        now = datetime.now(timezone.utc).isoformat()
        record.update({"pw_hash": password_hash, "must_change_credentials": False, "updated_at": now, "credentials_updated_at": now})
        if target_key == current_key and target == current_key:
            accounts[current_key] = record
        else:
            accounts.pop(current_key, None)
            record["legacy_session_id"] = secrets.token_urlsafe(32)
            accounts[target] = record
        get_store("accounts", path).write_data_locked(accounts, writer=save_atomic)
    return target if target_key != current_key else current_key


__all__ = [
    "Curriculum",
    "JsonValue",
    "StudentAuthStoreError",
    "StudentRecord",
    "account_sids",
    "change_credentials",
    "create_account",
    "curriculum_rows",
    "load_students",
    "narrow_sids",
    "student_sid",
]
