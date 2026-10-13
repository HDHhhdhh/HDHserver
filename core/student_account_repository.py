"""Lock-safe, merge-preserving persistence for student accounts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import secrets
from pathlib import Path
from typing import Mapping, Sequence

from werkzeug.security import check_password_hash, generate_password_hash

from core.storage import file_lock, save_atomic
from core.student_account_rules import (
    DEFAULT_ACTIVATION_PASSWORD,
    ActivationDecision,
    ActivationDecisionResult,
    AccountInputError,
    JsonValue,
    StudentRecord,
    account_id_key,
    account_matches_linked_name,
    activation_decision,
    linked_sids,
    normalize_account_id,
    validate_password,
)


@dataclass(frozen=True, slots=True)
class AccountLoginResult:
    account_id: str
    sids: tuple[str, ...]
    must_change_credentials: bool
    decision: ActivationDecision
    created: bool


@dataclass(frozen=True, slots=True)
class AdminResetResult:
    account_id: str
    must_change_credentials: bool
    revoke_sessions: bool


@dataclass(frozen=True, slots=True)
class AdminStateResult:
    account_id: str
    disabled: bool


@dataclass(frozen=True, slots=True)
class AccountRepositoryError(Exception):
    """Typed persistence or transition failure."""

    reason: str
    identifier: str

    def __str__(self) -> str:
        return f"account repository error: {self.reason}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_map(value: JsonValue, identifier: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise AccountRepositoryError("malformed_json_shape", identifier)
    return value


def _read_json(path: Path, default: JsonValue, identifier: str) -> JsonValue:
    try:
        return json.loads(path.read_text("utf-8-sig"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise AccountRepositoryError("malformed_json", identifier) from exc


def _record(value: JsonValue, identifier: str) -> dict[str, JsonValue]:
    return _json_map(value, identifier)


class StudentAccountRepository:
    """Read and mutate an explicit temporary/account JSON pair.

    The repository deliberately has no default paths, so importing it cannot
    touch live runtime stores. Every mutation re-reads under the account lock.
    """

    def __init__(self, accounts_path: Path, students_path: Path) -> None:
        self.accounts_path = Path(accounts_path)
        self.students_path = Path(students_path)

    def _load_accounts(self) -> dict[str, JsonValue]:
        value = _read_json(self.accounts_path, {}, str(self.accounts_path))
        return _json_map(value, str(self.accounts_path))

    def _load_students(self) -> list[StudentRecord]:
        value = _read_json(self.students_path, [], str(self.students_path))
        if not isinstance(value, list):
            raise AccountRepositoryError("malformed_students_shape", str(self.students_path))
        rows: list[StudentRecord] = []
        for row in value:
            if not isinstance(row, dict):
                raise AccountRepositoryError("malformed_student_row", str(self.students_path))
            rows.append(row)
        return rows

    def load(self) -> dict[str, JsonValue]:
        """Read a fresh account map without migrating or writing it."""

        with file_lock(self.accounts_path):
            return self._load_accounts()

    def load_students(self) -> list[StudentRecord]:
        """Read a fresh roster without importing runtime path constants."""

        with file_lock(self.students_path):
            return self._load_students()

    def admin_snapshot(self) -> tuple[list[StudentRecord], dict[str, JsonValue]]:
        """Return independent fresh roster/account values for admin projection."""

        return self.load_students(), self.load()

    def get(self, identifier: str) -> dict[str, JsonValue] | None:
        """Read one account while preserving the exact stored account key."""

        key = account_id_key(identifier)
        for candidate, value in self.load().items():
            try:
                if account_id_key(candidate) == key:
                    return _record(value, candidate)
            except AccountInputError:
                continue
        return None

    @staticmethod
    def _find_key(accounts: Mapping[str, JsonValue], identifier: str) -> str | None:
        key = account_id_key(identifier)
        for candidate in accounts:
            try:
                if account_id_key(candidate) == key:
                    return candidate
            except AccountInputError:
                continue
        return None

    @staticmethod
    def _decision(
        identifier: str,
        students: Sequence[StudentRecord],
        accounts: Mapping[str, JsonValue],
        password: str | None,
    ) -> ActivationDecisionResult:
        return activation_decision(identifier, students, accounts, password)

    def _new_record(self, sids: tuple[str, ...], password: str) -> dict[str, JsonValue]:
        now = _iso_now()
        return {
            "sids": list(sids),
            "pw_hash": generate_password_hash(password),
            "must_change_credentials": True,
            "disabled": False,
            "created_at": now,
            "updated_at": now,
            "credentials_updated_at": now,
            "legacy_session_id": secrets.token_urlsafe(32),
        }

    def activate_unique(self, identifier: str, password: str = DEFAULT_ACTIVATION_PASSWORD) -> AccountLoginResult:
        """Create the sole identity's account only for exact name+1234."""

        normalized = normalize_account_id(identifier)
        if password != DEFAULT_ACTIVATION_PASSWORD:
            raise AccountRepositoryError("default_password_required", normalized)
        with file_lock(self.accounts_path):
            accounts = self._load_accounts()
            students = self._load_students()
            decision = self._decision(normalized, students, accounts, password)
            if decision.decision is not ActivationDecision.UNIQUE_ACTIVATION:
                raise AccountRepositoryError(decision.decision.value, normalized)
            rows = decision.groups[0]
            sids = linked_sids(rows)
            if not sids:
                raise AccountRepositoryError("no_linked_sid", normalized)
            accounts[normalized] = self._new_record(sids, password)
            save_atomic(self.accounts_path, accounts)
            return AccountLoginResult(normalized, sids, True, decision.decision, True)

    def public_login(self, identifier: str, password: str) -> AccountLoginResult:
        """Authenticate or transition a legacy account under one lock."""

        normalized = normalize_account_id(identifier)
        with file_lock(self.accounts_path):
            accounts = self._load_accounts()
            students = self._load_students()
            key = self._find_key(accounts, normalized)
            if key is not None:
                record = _record(accounts[key], key)
                if record.get("disabled") is True:
                    raise AccountRepositoryError(ActivationDecision.DISABLED.value, normalized)
                stored_hash = record.get("pw_hash")
                if not isinstance(stored_hash, str) or not self._password_matches(stored_hash, password):
                    raise AccountRepositoryError("bad_password", normalized)
                linked = record.get("sids")
                sids = tuple(str(sid) for sid in linked if isinstance(sid, str)) if isinstance(linked, list) else ()
                if not sids:
                    raise AccountRepositoryError("no_linked_sid", normalized)
                must_change = record.get("must_change_credentials") is True
                if account_matches_linked_name(key, password, record, students):
                    if not must_change:
                        record["must_change_credentials"] = True
                        record["updated_at"] = _iso_now()
                        accounts[key] = record
                        save_atomic(self.accounts_path, accounts)
                        must_change = True
                return AccountLoginResult(key, sids, must_change, ActivationDecision.EXISTING, False)

            decision = self._decision(normalized, students, accounts, password)
            if decision.decision is not ActivationDecision.UNIQUE_ACTIVATION:
                raise AccountRepositoryError(decision.decision.value, normalized)
            if password != DEFAULT_ACTIVATION_PASSWORD:
                raise AccountRepositoryError("default_password_required", normalized)
            rows = decision.groups[0]
            sids = linked_sids(rows)
            if not sids:
                raise AccountRepositoryError("no_linked_sid", normalized)
            accounts[normalized] = self._new_record(sids, password)
            save_atomic(self.accounts_path, accounts)
            return AccountLoginResult(normalized, sids, True, decision.decision, True)

    def public_login_transition(self, identifier: str, password: str) -> AccountLoginResult:
        """Compatibility name for the explicit public-login transition."""

        return self.public_login(identifier, password)

    def admin_reset(self, identifier: str, temporary_password: str) -> AdminResetResult:
        """Reset only credentials/state timestamps; preserve all other fields."""

        normalized = normalize_account_id(identifier)
        if temporary_password != DEFAULT_ACTIVATION_PASSWORD:
            validate_password(temporary_password, normalized)
        with file_lock(self.accounts_path):
            accounts = self._load_accounts()
            key = self._find_key(accounts, normalized)
            if key is None:
                raise AccountRepositoryError("unknown_account", normalized)
            record = _record(accounts[key], key)
            if record.get("disabled") is True:
                raise AccountRepositoryError("disabled", normalized)
            now = _iso_now()
            record["pw_hash"] = generate_password_hash(temporary_password)
            record["must_change_credentials"] = True
            record["updated_at"] = now
            record["credentials_updated_at"] = now
            accounts[key] = record
            save_atomic(self.accounts_path, accounts)
            return AdminResetResult(key, True, True)

    def admin_set_disabled(self, identifier: str, disabled: bool) -> AdminStateResult:
        """Change only disabled/update fields and reject stale transitions."""

        normalized = normalize_account_id(identifier)
        if type(disabled) is not bool:
            raise AccountRepositoryError("invalid_disabled_state", normalized)
        with file_lock(self.accounts_path):
            accounts = self._load_accounts()
            key = self._find_key(accounts, normalized)
            if key is None:
                raise AccountRepositoryError("unknown_account", normalized)
            record = _record(accounts[key], key)
            current = record.get("disabled") is True
            if current is disabled:
                reason = "already_disabled" if disabled else "already_enabled"
                raise AccountRepositoryError(reason, normalized)
            record["disabled"] = disabled
            record["updated_at"] = _iso_now()
            accounts[key] = record
            save_atomic(self.accounts_path, accounts)
            return AdminStateResult(key, disabled)

    read_accounts = load
    activate = activate_unique
    login = public_login
    reset_credentials = admin_reset

    @staticmethod
    def _password_matches(stored_hash: str, password: str) -> bool:
        try:
            return check_password_hash(stored_hash, password)
        except ValueError:
            return False


__all__ = [
    "AccountLoginResult",
    "AccountRepositoryError",
    "AdminResetResult",
    "AdminStateResult",
    "StudentAccountRepository",
]
