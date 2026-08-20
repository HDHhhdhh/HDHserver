"""Privacy-minimal orchestration for academy-only student account administration."""
from __future__ import annotations

import math
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.student_account_audit import StudentAccountAuditRepository
from core.student_account_repository import AccountRepositoryError, StudentAccountRepository
from core.student_account_rules import (
    DEFAULT_ACTIVATION_PASSWORD,
    AccountInputError,
    IdentityKey,
    JsonValue,
    StudentRecord,
    account_id_key,
    identity_groups,
    linked_sids,
    normalize_account_id,
)
from core.student_activation_codes import StudentActivationCodeRepository
from core.student_push_repository import StudentPushRepository
from core.student_sessions import StudentSessionRepository

ACTIVATION_CODE_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class StudentAccountAdminDependencies:
    accounts: StudentAccountRepository
    sessions: StudentSessionRepository
    push: StudentPushRepository
    activations: StudentActivationCodeRepository
    audit: StudentAccountAuditRepository
    clock: Callable[[], float] = time.time


@dataclass(frozen=True, slots=True)
class StudentAccountAdminError(Exception):
    code: str
    status: int

    def __str__(self) -> str:
        return self.code


class StudentAccountAdminService:
    """Validate current roster identity before every administrative mutation."""

    def __init__(self, dependencies: StudentAccountAdminDependencies) -> None:
        self.dependencies = dependencies

    def _now(self) -> float:
        try:
            current = float(self.dependencies.clock())
        except (TypeError, ValueError, OverflowError) as exc:
            raise StudentAccountAdminError("invalid_clock", 409) from exc
        if not math.isfinite(current) or current < 0:
            raise StudentAccountAdminError("invalid_clock", 409)
        return current

    def _snapshot(self) -> tuple[list[StudentRecord], dict[str, JsonValue]]:
        try:
            return self.dependencies.accounts.admin_snapshot()
        except AccountRepositoryError as exc:
            raise StudentAccountAdminError("malformed_storage", 409) from exc

    @staticmethod
    def _normalized_aid(aid: str) -> str:
        try:
            return normalize_account_id(aid)
        except (AccountInputError, TypeError):
            raise StudentAccountAdminError("invalid_account_id", 400) from None

    @staticmethod
    def _find_account(accounts: Mapping[str, JsonValue], aid: str) -> tuple[str, Mapping[str, JsonValue]] | None:
        wanted = account_id_key(aid)
        for key, value in accounts.items():
            try:
                matches = account_id_key(key) == wanted
            except (AccountInputError, TypeError):
                continue
            if matches:
                if not isinstance(value, Mapping):
                    raise StudentAccountAdminError("malformed_account", 409)
                return key, value
        return None

    @staticmethod
    def _links(record: Mapping[str, JsonValue], *, strict: bool) -> tuple[str, ...] | None:
        value = record.get("sids")
        valid = isinstance(value, list) and bool(value) and all(isinstance(sid, str) and sid and sid == sid.strip() for sid in value)
        if valid:
            result = tuple(value)
            valid = len(set(result)) == len(result)
        if not valid:
            if strict:
                raise StudentAccountAdminError("malformed_account", 409)
            return None
        return result

    @staticmethod
    def _disabled(record: Mapping[str, JsonValue]) -> bool:
        value = record.get("disabled", False)
        if type(value) is not bool:
            raise StudentAccountAdminError("malformed_account", 409)
        return value

    def _validated_account(self, aid: str) -> tuple[str, Mapping[str, JsonValue], IdentityKey, tuple[str, ...]]:
        normalized = self._normalized_aid(aid)
        students, accounts = self._snapshot()
        found = self._find_account(accounts, normalized)
        if found is None:
            raise StudentAccountAdminError("account_not_found", 404)
        key, record = found
        links = self._links(record, strict=True)
        stored_hash = record.get("pw_hash")
        if not isinstance(stored_hash, str) or not stored_hash:
            raise StudentAccountAdminError("malformed_account", 409)
        matches = [(identity, linked_sids(rows)) for identity, rows in identity_groups(students).items() if set(linked_sids(rows)) == set(links)]
        if len(matches) != 1 or set(matches[0][1]) != set(links):
            raise StudentAccountAdminError("stale_account", 409)
        collisions = 0
        for other in accounts.values():
            if isinstance(other, Mapping) and set(self._links(other, strict=False) or ()) == set(links):
                collisions += 1
        if collisions != 1:
            raise StudentAccountAdminError("account_conflict", 409)
        return key, record, matches[0][0], links

    def _account_projection(self, aid: str, record: Mapping[str, JsonValue], now: float) -> dict[str, Any]:
        disabled = self._disabled(record)
        return {
            "aid": aid,
            "status": "disabled" if disabled else "active",
            "mustChangeCredentials": record.get("must_change_credentials") is True,
            "activeSessionCount": self.dependencies.sessions.active_count(aid, now=now),
            "activePushSubscriptionCount": self.dependencies.push.active_count(aid),
        }

    def list_groups(self) -> list[dict[str, Any]]:
        students, accounts = self._snapshot()
        groups = identity_groups(students)
        names = Counter(identity.name for identity in groups)
        bindings: dict[frozenset[str], tuple[str, Mapping[str, JsonValue]]] = {}
        roster_sets = {frozenset(linked_sids(rows)) for rows in groups.values()}
        for aid, raw in accounts.items():
            if not isinstance(raw, Mapping):
                continue
            links = self._links(raw, strict=False)
            sid_set = frozenset(links or ())
            if not sid_set or sid_set not in roster_sets:
                continue
            if sid_set in bindings:
                raise StudentAccountAdminError("account_conflict", 409)
            bindings[sid_set] = (aid, raw)
        now = self._now()
        output: list[dict[str, Any]] = []
        for identity, rows in groups.items():
            sids = linked_sids(rows)
            bound = bindings.get(frozenset(sids))
            account = None if bound is None else self._account_projection(bound[0], bound[1], now)
            output.append({
                "identity": {"name": identity.name, "school": identity.school, "grade": identity.grade, "sids": list(sids)},
                "account": account,
                "activationCodeRequired": names[identity.name] > 1,
            })
        return output

    @staticmethod
    def _map_repository_error(exc: AccountRepositoryError) -> StudentAccountAdminError:
        mapping = {
            "unknown_account": ("account_not_found", 404),
            "disabled": ("account_disabled", 409),
            "already_disabled": ("account_disabled", 409),
            "already_enabled": ("account_enabled", 409),
        }
        code, status = mapping.get(exc.reason, ("account_conflict", 409))
        return StudentAccountAdminError(code, status)

    def reset(self, aid: str) -> dict[str, Any]:
        key, record, _identity, _links = self._validated_account(aid)
        if self._disabled(record):
            raise StudentAccountAdminError("account_disabled", 409)
        now = self._now()
        revoked = self.dependencies.sessions.revoke_account(key, now=now)
        try:
            result = self.dependencies.accounts.admin_reset(key, DEFAULT_ACTIVATION_PASSWORD)
        except AccountRepositoryError as exc:
            raise self._map_repository_error(exc) from exc
        self.dependencies.audit.record("account.reset", target_aid=result.account_id, actor_surface="admin.api", metadata={"sessionsRevoked": revoked, "forcedChange": True}, now=now)
        return {"account": {"aid": result.account_id, "status": "active", "mustChangeCredentials": True}, "sessionsRevoked": revoked}

    def disable(self, aid: str) -> dict[str, Any]:
        key, record, _identity, _links = self._validated_account(aid)
        if self._disabled(record):
            raise StudentAccountAdminError("account_disabled", 409)
        now = self._now()
        sessions = self.dependencies.sessions.revoke_account(key, now=now)
        subscriptions = self.dependencies.push.revoke_account(key, now=now)
        try:
            result = self.dependencies.accounts.admin_set_disabled(key, True)
        except AccountRepositoryError as exc:
            raise self._map_repository_error(exc) from exc
        self.dependencies.audit.record("account.disable", target_aid=result.account_id, actor_surface="admin.api", metadata={"sessionsRevoked": sessions, "subscriptionsRevoked": subscriptions}, now=now)
        return {"account": {"aid": result.account_id, "status": "disabled"}, "sessionsRevoked": sessions, "pushSubscriptionsRevoked": subscriptions}

    def enable(self, aid: str) -> dict[str, Any]:
        key, record, _identity, _links = self._validated_account(aid)
        if not self._disabled(record):
            raise StudentAccountAdminError("account_enabled", 409)
        try:
            result = self.dependencies.accounts.admin_set_disabled(key, False)
        except AccountRepositoryError as exc:
            raise self._map_repository_error(exc) from exc
        now = self._now()
        self.dependencies.audit.record("account.enable", target_aid=result.account_id, actor_surface="admin.api", metadata={"credentialsPreserved": True}, now=now)
        return {"account": {"aid": result.account_id, "status": "active"}}

    def revoke_sessions(self, aid: str) -> dict[str, Any]:
        key, record, _identity, _links = self._validated_account(aid)
        if self._disabled(record):
            raise StudentAccountAdminError("account_disabled", 409)
        now = self._now()
        revoked = self.dependencies.sessions.revoke_account(key, now=now)
        self.dependencies.audit.record("sessions.revoke", target_aid=key, actor_surface="admin.api", metadata={"sessionsRevoked": revoked}, now=now)
        return {"account": {"aid": key, "status": "active"}, "sessionsRevoked": revoked}

    def issue_activation_code(self, aid: str, sids: Sequence[str]) -> dict[str, Any]:
        selector = self._normalized_aid(aid)
        if isinstance(sids, (str, bytes)) or not isinstance(sids, Sequence) or not sids or any(not isinstance(sid, str) or not sid or sid != sid.strip() for sid in sids) or len(set(sids)) != len(sids):
            raise StudentAccountAdminError("invalid_sids", 400)
        students, accounts = self._snapshot()
        selected_account = self._find_account(accounts, selector)
        account_links = None if selected_account is None else self._links(selected_account[1], strict=True)
        matching = [
            (identity, linked_sids(rows))
            for identity, rows in identity_groups(students).items()
            if identity.name == selector or (account_links is not None and set(linked_sids(rows)) == set(account_links))
        ]
        if not matching:
            raise StudentAccountAdminError("identity_not_found", 404)
        selected = [(identity, links) for identity, links in matching if set(links) == set(sids) and len(links) == len(sids)]
        if len(selected) != 1:
            raise StudentAccountAdminError("sid_set_mismatch", 409)
        identity, links = selected[0]
        if sum(1 for candidate in identity_groups(students) if candidate.name == identity.name) < 2:
            raise StudentAccountAdminError("activation_code_not_required", 409)
        requested = set(links)
        bound: list[Mapping[str, JsonValue]] = []
        for raw in accounts.values():
            if isinstance(raw, Mapping) and set(self._links(raw, strict=False) or ()) == requested:
                bound.append(raw)
        if len(bound) > 1:
            raise StudentAccountAdminError("account_conflict", 409)
        if bound and self._disabled(bound[0]):
            raise StudentAccountAdminError("account_disabled", 409)
        now = self._now()
        identity_key = f"{identity.name}||{identity.school}||{identity.grade}"
        code = self.dependencies.activations.issue(identity_key, links, ttl_seconds=ACTIVATION_CODE_TTL_SECONDS, now=now)
        self.dependencies.audit.record("activation_code_issue", target_ref=identity_key, actor_surface="admin.api", metadata={"sidCount": len(links), "oneUse": True}, now=now)
        return {"activationCode": code, "expiresAt": now + ACTIVATION_CODE_TTL_SECONDS}


__all__ = ["ACTIVATION_CODE_TTL_SECONDS", "StudentAccountAdminDependencies", "StudentAccountAdminError", "StudentAccountAdminService"]
