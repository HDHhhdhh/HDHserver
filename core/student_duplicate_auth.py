"""Pure duplicate-identity selection plus atomic activation redemption."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from core.student_account_rules import AccountInputError, JsonValue, account_id_key, identity_groups, identity_key, linked_sids
from core.student_activation_codes import StudentActivationCodeRepository
from core.student_app_auth_store import StudentRecord, account_sids, narrow_sids


def _same_account_id(left: str, right: str) -> bool:
    try:
        return account_id_key(left) == account_id_key(right)
    except (AccountInputError, TypeError):
        return False


def pending_account_id(identity: str, sids: Sequence[str]) -> str:
    sid_material = "\0".join(sorted(set(sids)))
    material = f"{identity}\0{sid_material}"
    return f"pending-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"


def duplicate_identity_groups(identifier: str, students: Sequence[StudentRecord]) -> tuple[tuple[StudentRecord, ...], ...]:
    return tuple(tuple(rows) for key, rows in identity_groups(students).items() if _same_account_id(key.name, identifier))


def accounts_for_sids(accounts: Mapping[str, JsonValue], sids: Sequence[str]) -> tuple[tuple[str, Mapping[str, JsonValue]], ...]:
    expected = set(sids)
    if not expected:
        return ()
    return tuple(
        (aid, value)
        for aid, value in accounts.items()
        if _same_account_id(aid, aid) and isinstance(value, dict) and account_sids(value) and set(account_sids(value)) == expected
    )


def redeem_duplicate_activation(
    repository: StudentActivationCodeRepository,
    canary_sids: frozenset[str],
    code: str,
    groups: Sequence[Sequence[StudentRecord]],
    students: Sequence[StudentRecord],
) -> tuple[str, tuple[str, ...]] | None:
    candidates: dict[str, tuple[str, ...]] = {}
    for group in groups:
        key = identity_key(group[0])
        current = narrow_sids(linked_sids(group), students)
        if current and (not canary_sids or any(sid in canary_sids for sid in current)):
            candidates[f"{key.name}||{key.school}||{key.grade}"] = current
    redemption = repository.redeem_candidates(candidates, code)
    if redemption is None:
        return None
    current = candidates.get(redemption["identity_key"])
    if current is None or set(redemption["sids"]) != set(current):
        return None
    return redemption["identity_key"], current


__all__ = ["accounts_for_sids", "duplicate_identity_groups", "pending_account_id", "redeem_duplicate_activation"]
