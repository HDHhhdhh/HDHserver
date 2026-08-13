"""Session-bound public student authentication orchestration."""

from __future__ import annotations

from typing import Final, Sequence

from werkzeug.security import generate_password_hash

from core.student_account_repository import AccountRepositoryError
from core.student_account_rules import DEFAULT_ACTIVATION_PASSWORD, AccountInputError, ActivationDecision, activation_decision, linked_sids, normalize_account_id, validate_password
from core.student_app_auth_store import (
    StudentAuthStoreError,
    StudentRecord,
    account_sids,
    change_credentials,
    create_account,
    curriculum_rows,
    load_students,
    narrow_sids,
)
from core.student_app_auth_contract import AuthExchange, AuthResponse, StudentAuthDependencies, StudentAuthFailure, signed_out_response
from core.student_duplicate_auth import accounts_for_sids, duplicate_identity_groups, pending_account_id, redeem_duplicate_activation
from core.student_sessions import SessionView


_DEFAULT_PUSH_STATE: Final[str] = "required"


class StudentAuthService:
    def __init__(self, dependencies: StudentAuthDependencies) -> None:
        self.dependencies = dependencies

    def _students(self) -> tuple[StudentRecord, ...]:
        return load_students(self.dependencies.students_path)

    def _available(self, sids: Sequence[str]) -> tuple[str, ...]:
        allowed = tuple(sids)
        if self.dependencies.config.canary_sids and not any(sid in self.dependencies.config.canary_sids for sid in allowed):
            raise StudentAuthFailure("unavailable", 404)
        return allowed

    def _exchange(self, aid: str, sids: Sequence[str], must_change: bool, token: str, csrf: str, active_sid: str | None = None) -> AuthExchange:
        students = self._students()
        active = sids[0] if active_sid is None else active_sid
        state = "credentials_required" if must_change else "ready"
        return AuthExchange(
            {"ok": True, "state": state, "sid": active, "curris": list(curriculum_rows(sids, students)), "csrfToken": csrf, "pushState": _DEFAULT_PUSH_STATE},
            token,
            csrf,
        )

    def _new_session(self, aid: str, sids: Sequence[str], must_change: bool) -> AuthExchange:
        allowed = self._available(sids)
        if not allowed:
            raise StudentAuthFailure("unavailable", 404)
        created = self.dependencies.sessions.create_session(aid, allowed[0], allowed)
        return self._exchange(aid, allowed, must_change, created["token"], created["csrf_token"], allowed[0])

    def _fail_login(self, identifier: str, client_ip: str, code: str = "invalid_credentials", status: int = 401) -> None:
        status_result = self.dependencies.throttle.record_failure(identifier, client_ip)
        if status_result["blocked"]:
            raise StudentAuthFailure("temporarily_unavailable", 429, retry_after=status_result["retry_after"])
        raise StudentAuthFailure(code, status)

    def _duplicate_activation(self, identifier: str, client_ip: str, code: str, groups: Sequence[Sequence[StudentRecord]], students: Sequence[StudentRecord]) -> tuple[str, tuple[str, ...]]:
        if not code:
            raise StudentAuthFailure("activation_code_required", 409, "activation_code_required")
        result = redeem_duplicate_activation(self.dependencies.activations, self.dependencies.config.canary_sids, code, groups, students)
        if result is not None:
            return result
        self._fail_login(identifier, client_ip, "activation_code_required", 409)
        raise StudentAuthFailure("activation_code_required", 409, "activation_code_required")

    def login(self, identifier: str, password: str, code: str, client_ip: str) -> AuthExchange:
        try:
            normalized = normalize_account_id(identifier)
        except AccountInputError as exc:
            raise StudentAuthFailure("invalid_request", 400) from exc
        if not isinstance(password, str) or (not password and not code):
            self._fail_login(normalized, client_ip)
        try:
            status_result = self.dependencies.throttle.status(normalized, client_ip)
        except ValueError as exc:
            raise StudentAuthFailure("invalid_request", 400) from exc
        if status_result["blocked"]:
            raise StudentAuthFailure("temporarily_unavailable", 429, retry_after=status_result["retry_after"])
        try:
            students = self._students()
            duplicate_groups = duplicate_identity_groups(normalized, students)
            if len(duplicate_groups) > 1:
                identity, current = self._duplicate_activation(normalized, client_ip, code, duplicate_groups, students)
                accounts = self.dependencies.accounts.load()
                matches = accounts_for_sids(accounts, current)
                if len(matches) > 1:
                    self._fail_login(normalized, client_ip)
                if matches:
                    aid, record = matches[0]
                    if record.get("disabled") is True:
                        self._fail_login(normalized, client_ip)
                    must_change = record.get("must_change_credentials") is True
                else:
                    aid = create_account(
                        self.dependencies.accounts.accounts_path,
                        pending_account_id(identity, current),
                        current,
                    )
                    must_change = True
                self.dependencies.throttle.record_success(normalized)
                return self._new_session(aid, current, must_change)

            account = self.dependencies.accounts.get(normalized)
            if account is not None:
                if account.get("disabled") is True:
                    self._fail_login(normalized, client_ip)
                existing_sids = narrow_sids(account_sids(account), students)
                self._available(existing_sids)
                result = self.dependencies.accounts.public_login(normalized, password)
                current = narrow_sids(result.sids, students)
                if not current:
                    self._fail_login(normalized, client_ip)
                self._available(current)
                self.dependencies.throttle.record_success(normalized)
                return self._new_session(result.account_id, current, result.must_change_credentials)

            accounts = self.dependencies.accounts.load()
            decision = activation_decision(normalized, students, accounts, password)
            if decision.decision is ActivationDecision.UNIQUE_ACTIVATION:
                current = narrow_sids(linked_sids(decision.groups[0]), students)
                if password != DEFAULT_ACTIVATION_PASSWORD:
                    self._fail_login(normalized, client_ip)
                self._available(current)
                result = self.dependencies.accounts.activate_unique(normalized, password)
                self.dependencies.throttle.record_success(normalized)
                return self._new_session(result.account_id, current, True)
            if decision.decision is ActivationDecision.ACTIVATION_CODE_REQUIRED and decision.groups:
                identity, current = self._duplicate_activation(normalized, client_ip, code, decision.groups, students)
                aid = create_account(
                    self.dependencies.accounts.accounts_path,
                    pending_account_id(identity, current),
                    current,
                )
                self.dependencies.throttle.record_success(normalized)
                return self._new_session(aid, current, True)
            self._fail_login(normalized, client_ip)
        except (AccountRepositoryError, StudentAuthStoreError) as exc:
            reason = exc.reason
            if reason == "activation_code_required":
                raise StudentAuthFailure("activation_code_required", 409, "activation_code_required") from exc
            self._fail_login(normalized, client_ip)
        raise StudentAuthFailure("invalid_credentials", 401)

    def _authorized(self, token: str, csrf: str | None) -> tuple[SessionView, str, tuple[str, ...], bool]:
        if csrf is None:
            raise StudentAuthFailure("csrf_required", 403)
        view = self.dependencies.sessions.resolve(token, csrf_token=csrf)
        if view is None:
            raise StudentAuthFailure("csrf_invalid", 403)
        record = self.dependencies.accounts.get(view["aid"])
        if record is None or record.get("disabled") is True:
            self.dependencies.sessions.revoke(token)
            raise StudentAuthFailure("unauthenticated", 401)
        students = self._students()
        allowed = narrow_sids(tuple(view["allowed_sids"]), students)
        allowed = narrow_sids(allowed, students) if account_sids(record) else ()
        allowed = tuple(sid for sid in allowed if sid in set(account_sids(record)))
        self._available(allowed)
        if not allowed:
            self.dependencies.sessions.revoke(token)
            raise StudentAuthFailure("unauthenticated", 401)
        return view, view["aid"], allowed, record.get("must_change_credentials") is True

    def session(self, token: str) -> AuthExchange:
        view = self.dependencies.sessions.resolve(token)
        if view is None:
            raise StudentAuthFailure("unauthenticated", 401)
        record = self.dependencies.accounts.get(view["aid"])
        if record is None or record.get("disabled") is True:
            self.dependencies.sessions.revoke(token)
            raise StudentAuthFailure("unauthenticated", 401)
        students = self._students()
        allowed = narrow_sids(tuple(view["allowed_sids"]), students)
        stored = set(account_sids(record))
        allowed = tuple(sid for sid in allowed if sid in stored)
        self._available(allowed)
        if not allowed:
            self.dependencies.sessions.revoke(token)
            raise StudentAuthFailure("unauthenticated", 401)
        aid = view["aid"]
        must_change = record.get("must_change_credentials") is True
        active = view["active_sid"] if view["active_sid"] in allowed else allowed[0]
        if tuple(view["allowed_sids"]) == allowed and active == view["active_sid"]:
            created = self.dependencies.sessions.rotate(token, active_sid=active)
        else:
            self.dependencies.sessions.revoke(token)
            created = self.dependencies.sessions.create_session(aid, active, allowed)
        if created is None:
            raise StudentAuthFailure("unauthenticated", 401)
        return self._exchange(aid, allowed, must_change, created["token"], created["csrf_token"], active)

    def credentials(self, token: str, csrf: str | None, new_id: str, password: str) -> AuthExchange:
        _view, aid, allowed, _must_change = self._authorized(token, csrf)
        try:
            target = normalize_account_id(new_id or aid)
            valid_password = validate_password(password, target)
        except AccountInputError as exc:
            raise StudentAuthFailure("invalid_credentials", 400) from exc
        try:
            new_aid = change_credentials(self.dependencies.accounts.accounts_path, aid, target, generate_password_hash(valid_password))
        except StudentAuthStoreError as exc:
            status = 409 if exc.reason == "id_collision" else 401
            raise StudentAuthFailure("id_collision" if status == 409 else "unauthenticated", status) from exc
        self.dependencies.sessions.revoke_account(aid)
        if new_aid != aid:
            self.dependencies.sessions.revoke_account(new_aid)
        return self._new_session(new_aid, allowed, False)

    def switch(self, token: str, csrf: str | None, target_sid: str) -> AuthExchange:
        view, aid, allowed, must_change = self._authorized(token, csrf)
        if must_change:
            raise StudentAuthFailure("credentials_required", 403, "credentials_required")
        if not isinstance(target_sid, str) or target_sid not in allowed:
            raise StudentAuthFailure("forbidden_sid", 403)
        created = self.dependencies.sessions.rotate(token, active_sid=target_sid)
        if created is None:
            raise StudentAuthFailure("unauthenticated", 401)
        return self._exchange(aid, allowed, False, created["token"], created["csrf_token"], target_sid)

    def logout(self, token: str, csrf: str | None) -> AuthExchange:
        if csrf is None:
            raise StudentAuthFailure("csrf_required", 403)
        view = self.dependencies.sessions.resolve(token, csrf_token=csrf)
        if view is None:
            raise StudentAuthFailure("csrf_invalid", 403)
        self.dependencies.sessions.revoke(token)
        return signed_out_response()


__all__ = [
    "AuthExchange",
    "AuthResponse",
    "StudentAuthDependencies",
    "StudentAuthFailure",
    "StudentAuthService",
    "signed_out_response",
]
