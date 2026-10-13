"""Pure rules for student account identity, activation, and credentials."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Mapping, Sequence, TypeAlias
import unicodedata


JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
StudentRecord: TypeAlias = Mapping[str, JsonValue]

DEFAULT_ACTIVATION_PASSWORD: Final[str] = "1234"
_ACCOUNT_MIN_LENGTH: Final[int] = 2
_ACCOUNT_MAX_LENGTH: Final[int] = 32


class ActivationDecision(StrEnum):
    """The public-login path selected from current roster and account state."""

    EXISTING = "existing"
    UNIQUE_ACTIVATION = "unique_activation"
    ACTIVATION_CODE_REQUIRED = "activation_code_required"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class IdentityKey:
    """Normalized roster identity grouping key."""

    name: str
    school: str
    grade: str
    person_id: str = ""


@dataclass(frozen=True, slots=True)
class ActivationDecisionResult:
    """Decision plus the identity groups considered for activation."""

    decision: ActivationDecision
    identifier: str
    groups: tuple[tuple[StudentRecord, ...], ...]
    account_key: str | None = None


@dataclass(frozen=True, slots=True)
class AccountInputError(ValueError):
    """Typed account input rejection."""

    field: str
    reason: str
    value: str

    def __str__(self) -> str:
        return f"invalid {self.field}: {self.reason}"


def nfkc(value: str) -> str:
    """Normalize one user-visible string with Unicode NFKC."""

    return unicodedata.normalize("NFKC", value)


def roster_text(value: JsonValue) -> str:
    """Normalize a roster field using the legacy route's trim semantics."""

    if isinstance(value, str):
        return nfkc(value).strip()
    if value is None:
        return ""
    return nfkc(str(value)).strip()


def _student_field(student: StudentRecord, key: str) -> str:
    return roster_text(student.get(key))


def identity_key(student: StudentRecord) -> IdentityKey:
    """Return the stable person key with a legacy profile fallback."""

    school = _student_field(student, "school")
    if not school:
        school = _student_field(student, "highSchool")
    if not school:
        school = _student_field(student, "middleSchool")
    return IdentityKey(
        name=_student_field(student, "name"),
        school=school,
        grade=_student_field(student, "grade"),
        person_id=_student_field(student, "personId"),
    )


def identity_groups(students: Sequence[StudentRecord]) -> dict[IdentityKey, tuple[StudentRecord, ...]]:
    """Group roster rows without choosing one row from an ambiguous name."""

    grouped: dict[IdentityKey, list[StudentRecord]] = {}
    for student in students:
        key = identity_key(student)
        if not key.name:
            continue
        grouped.setdefault(key, []).append(student)
    return {key: tuple(rows) for key, rows in grouped.items()}


def linked_sids(rows: Sequence[StudentRecord]) -> tuple[str, ...]:
    """Return unique non-empty SIDs in stable roster order."""

    seen: set[str] = set()
    result: list[str] = []
    for row in rows:
        sid = _student_field(row, "id")
        if sid and sid not in seen:
            result.append(sid)
            seen.add(sid)
    return tuple(result)


def normalize_account_id(value: str) -> str:
    """Parse an account ID accepted by the public account contract."""

    normalized = nfkc(value)
    if not normalized or len(normalized) < _ACCOUNT_MIN_LENGTH or len(normalized) > _ACCOUNT_MAX_LENGTH:
        raise AccountInputError("id", "length", value)
    if normalized != normalized.strip():
        raise AccountInputError("id", "whitespace", value)
    for char in normalized:
        name = unicodedata.name(char, "")
        allowed_letter = char.isalpha() and ("LATIN" in name or "HANGUL" in name)
        allowed_digit = char.isdigit() and unicodedata.category(char) == "Nd"
        if not (allowed_letter or allowed_digit or char in "._-"):
            raise AccountInputError("id", "character", value)
    return normalized


def account_id_key(value: str) -> str:
    """Return the case-folded normalized key used for uniqueness."""

    return normalize_account_id(value).casefold()


def validate_password(password: str, account_id: str | None = None) -> str:
    """Parse a user-chosen password under the length and identity rules."""

    if len(password) < 8 or len(password) > 64:
        raise AccountInputError("password", "length", password)
    if password != password.strip():
        raise AccountInputError("password", "leading_or_trailing_whitespace", password)
    if any(unicodedata.category(char).startswith("C") for char in password):
        raise AccountInputError("password", "control_character", password)
    if password == DEFAULT_ACTIVATION_PASSWORD:
        raise AccountInputError("password", "default_password", password)
    if account_id is not None and nfkc(password).casefold() == account_id_key(account_id):
        raise AccountInputError("password", "same_as_id", password)
    return password


def _account_key(accounts: Mapping[str, JsonValue], identifier: str) -> str | None:
    key = account_id_key(identifier)
    for candidate in accounts:
        try:
            if account_id_key(candidate) == key:
                return candidate
        except AccountInputError:
            continue
    return None


def _record_disabled(accounts: Mapping[str, JsonValue], key: str) -> bool:
    record = accounts.get(key)
    return isinstance(record, dict) and record.get("disabled") is True


def activation_decision(
    identifier: str,
    students: Sequence[StudentRecord],
    accounts: Mapping[str, JsonValue],
    password: str | None = None,
) -> ActivationDecisionResult:
    """Choose an activation path without selecting a duplicate-name group."""

    normalized = normalize_account_id(identifier)
    account_key = _account_key(accounts, normalized)
    if account_key is not None:
        decision = ActivationDecision.DISABLED if _record_disabled(accounts, account_key) else ActivationDecision.EXISTING
        return ActivationDecisionResult(decision, normalized, (), account_key)

    groups = tuple(
        rows
        for key, rows in identity_groups(students).items()
        if key.name == normalized
    )
    if len(groups) == 1:
        decision = ActivationDecision.UNIQUE_ACTIVATION
    else:
        decision = ActivationDecision.ACTIVATION_CODE_REQUIRED
    return ActivationDecisionResult(decision, normalized, groups)


def decide_activation(
    identifier: str,
    students: Sequence[StudentRecord],
    accounts: Mapping[str, JsonValue],
    password: str | None = None,
) -> ActivationDecisionResult:
    """Compatibility spelling for callers that treat decisions as a verb."""

    return activation_decision(identifier, students, accounts, password)


def account_matches_linked_name(
    account_id: str,
    password: str,
    record: Mapping[str, JsonValue],
    students: Sequence[StudentRecord],
) -> bool:
    """Identify legacy name+1234 records eligible for lazy force-change state."""

    if password != DEFAULT_ACTIVATION_PASSWORD:
        return False
    linked = record.get("sids")
    if not isinstance(linked, list):
        return False
    linked_set = {roster_text(item) for item in linked if isinstance(item, str)}
    if not linked_set:
        return False
    normalized_id = normalize_account_id(account_id)
    return any(
        _student_field(student, "id") in linked_set
        and _student_field(student, "name") == normalized_id
        for student in students
    )
