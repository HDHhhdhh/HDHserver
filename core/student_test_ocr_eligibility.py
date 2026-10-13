from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from core.student_test_formula_profiles import FormulaProfileError, formula_profile_for_test
from core.student_test_ocr_rules import OcrRuleError, validate_test_answer_contract


ACTIVE_ASSIGNMENT_STATES = frozenset({"assigned", "interrupted"})
LOG_ASSIGNMENT_FIELDS = ("testAssignmentDailyTests", "assignedTests")


@dataclass(frozen=True, slots=True)
class OcrEligibilityError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _fail(code: str, message: str) -> None:
    raise OcrEligibilityError(code, message)


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _sid_entry(day: object, sid: str) -> dict:
    if not isinstance(day, Mapping):
        return {}
    candidates: list[object] = [sid]
    if str(sid).isdigit():
        candidates.append(int(str(sid)))
    for key in candidates:
        value = day.get(key)
        if isinstance(value, dict):
            return value
    return {}


def find_test_definition(tests_config: Mapping[str, object], test_id: str) -> dict:
    categories = tests_config.get("categories")
    if not isinstance(categories, Mapping):
        _fail("test_catalog_unavailable", "test catalog is unavailable")
    target_id = _text(test_id)
    matches: list[dict] = []
    for category_key, raw_category in categories.items():
        if not isinstance(raw_category, Mapping):
            continue
        tests = raw_category.get("tests")
        if not isinstance(tests, list):
            continue
        for raw_test in tests:
            if isinstance(raw_test, dict) and _text(raw_test.get("id")) == target_id:
                matches.append(
                    {
                        "categoryKey": _text(category_key).upper(),
                        "categoryLabel": _text(raw_category.get("label") or category_key),
                        "test": dict(raw_test),
                    }
                )
    if not matches:
        _fail("test_not_found", "assigned test was not found in the catalog")
    if len(matches) != 1:
        _fail("ambiguous_test_id", "test id is duplicated in the catalog")
    return matches[0]


def _assignment_metadata(log_entry: Mapping[str, object], assignment_label: str) -> list[dict]:
    matches: list[dict] = []
    for field in LOG_ASSIGNMENT_FIELDS:
        rows = log_entry.get(field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = _text(row.get("label"))
            if not label:
                pieces = [
                    row.get("categoryLabel"),
                    row.get("curriculum"),
                    row.get("difficulty"),
                    f"{_text(row.get('round'))}회차" if _text(row.get("round")) else "",
                    row.get("name"),
                ]
                label = " / ".join(_text(piece) for piece in pieces if _text(piece))
            if label == assignment_label:
                matches.append(dict(row))
    return matches


def assignment_label_matches_definition(assignment_label: str, definition: Mapping[str, object]) -> bool:
    test = definition.get("test")
    if not isinstance(test, Mapping):
        return False
    parts = [_text(part) for part in str(assignment_label or "").split("/") if _text(part)]
    if len(parts) < 5:
        return False
    category_label = _compact(definition.get("categoryLabel"))
    curriculum = _compact(test.get("curriculum"))
    difficulty = _compact(test.get("difficulty"))
    round_no = _compact(test.get("round"))
    name = _compact(test.get("name"))
    label_round = _compact(parts[-2]).replace("회차", "").replace("회", "")
    return bool(
        category_label
        and _compact(parts[0]) == category_label
        and curriculum
        and _compact(parts[1]) == curriculum
        and difficulty
        and _compact(parts[2]) == difficulty
        and round_no
        and label_round == round_no
        and name
        and _compact(parts[-1]) == name
    )


def resolve_ocr_eligible_assignment(
    *,
    tests_config: Mapping[str, object],
    progress: Mapping[str, object],
    log_entry: Mapping[str, object],
    sid: str,
    assignment_date: str,
    test_id: str,
    assignment_label: str,
) -> dict:
    label = _text(assignment_label)
    if not label:
        _fail("assignment_not_found", "assigned test label is missing")
    day = progress.get(assignment_date) if isinstance(progress, Mapping) else None
    progress_entry = _sid_entry(day, sid)
    tests = progress_entry.get("tests") if isinstance(progress_entry, dict) else None
    state = tests.get(label) if isinstance(tests, Mapping) else None
    if isinstance(state, Mapping):
        state = state.get("status")
    normalized_state = _text(state)
    if normalized_state not in ACTIVE_ASSIGNMENT_STATES:
        _fail("assignment_not_active", "test is not currently assigned for OCR submission")

    definition = find_test_definition(tests_config, test_id)
    test = definition["test"]
    round_no = _text(test.get("round"))
    metadata = _assignment_metadata(log_entry, label)
    metadata_ids = {
        _text(item.get("id") or item.get("testId") or item.get("test_id"))
        for item in metadata
        if _text(item.get("id") or item.get("testId") or item.get("test_id"))
    }
    if metadata_ids and metadata_ids != {_text(test_id)}:
        _fail("assignment_identity_mismatch", "assigned test metadata does not match the requested test")
    if not metadata_ids and not assignment_label_matches_definition(label, definition):
        _fail("assignment_identity_mismatch", "assigned test label does not match the requested test")
    try:
        contract = validate_test_answer_contract(
            category=definition["categoryKey"],
            test=test,
            round_no=round_no,
        )
        formula_profile = formula_profile_for_test(test, contract["answerModes"])
    except OcrRuleError as error:
        raise OcrEligibilityError(error.code, error.message) from error
    except FormulaProfileError as error:
        raise OcrEligibilityError(error.code, error.message) from error
    return {
        "sid": _text(sid),
        "assignmentDate": _text(assignment_date),
        "assignmentLabel": label,
        "testId": _text(test_id),
        "testName": _text(test.get("name")),
        "round": round_no,
        "categoryKey": definition["categoryKey"],
        "answerModes": contract["answerModes"],
        "answerKeys": contract["answerKeys"],
        "formulaProfile": formula_profile,
    }
