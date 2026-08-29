from __future__ import annotations

from core.student_test_formula_profiles import FORMULA_PROFILE_COMMON, FORMULA_PROFILE_UPPER
from core.student_test_ocr_eligibility import OcrEligibilityError, resolve_ocr_eligible_assignment
from core.student_test_ocr_rules import ANSWER_VALUE, CHOICE_NUMBER


LABEL = "단원평가 / 공수1 / Lv.3 / 1회차 / 지수 Lv.3"


def _config(*, category="UNIT", modes=None, choice_key="3", curriculum="공수1") -> dict:
    selected_modes = modes or [CHOICE_NUMBER, ANSWER_VALUE] * 10
    answer_keys = [choice_key if mode == CHOICE_NUMBER else "1/2" for mode in selected_modes]
    return {
        "categories": {
            category: {
                "label": "단원평가" if category == "UNIT" else "복습",
                "tests": [
                    {
                        "id": "test-1",
                        "name": "지수 Lv.3",
                        "curriculum": curriculum,
                        "difficulty": "Lv.3",
                        "round": "1",
                        "problems": 20,
                        "answerModes": {"1": selected_modes},
                        "answerKeys": {"1": answer_keys},
                    }
                ],
            }
        }
    }


def _raises(code: str, callback) -> None:
    try:
        callback()
    except OcrEligibilityError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError(f"expected {code}")


def run() -> dict:
    assertions = 0
    progress = {"2026-08-28": {"student-1": {"tests": {LABEL: "assigned"}}}}
    log_entry = {"testAssignmentDailyTests": [{"id": "test-1", "label": LABEL, "status": "assigned"}]}
    resolved = resolve_ocr_eligible_assignment(
        tests_config=_config(),
        progress=progress,
        log_entry=log_entry,
        sid="student-1",
        assignment_date="2026-08-28",
        test_id="test-1",
        assignment_label=LABEL,
    )
    assert resolved["categoryKey"] == "UNIT" and resolved["round"] == "1"
    assert len(resolved["answerModes"]) == 20 and len(resolved["answerKeys"]) == 20
    assert resolved["formulaProfile"] == FORMULA_PROFILE_COMMON
    assertions += 3

    upper = resolve_ocr_eligible_assignment(
        tests_config=_config(curriculum="미적분Ⅱ"),
        progress=progress,
        log_entry=log_entry,
        sid="student-1",
        assignment_date="2026-08-28",
        test_id="test-1",
        assignment_label=LABEL,
    )
    assert upper["formulaProfile"] == FORMULA_PROFILE_UPPER
    choice_only = resolve_ocr_eligible_assignment(
        tests_config=_config(curriculum="미등록", modes=[CHOICE_NUMBER] * 20),
        progress=progress,
        log_entry=log_entry,
        sid="student-1",
        assignment_date="2026-08-28",
        test_id="test-1",
        assignment_label=LABEL,
    )
    assert choice_only["formulaProfile"] is None
    _raises(
        "unsupported_formula_curriculum",
        lambda: resolve_ocr_eligible_assignment(
            tests_config=_config(curriculum="미등록"),
            progress=progress,
            log_entry=log_entry,
            sid="student-1",
            assignment_date="2026-08-28",
            test_id="test-1",
            assignment_label=LABEL,
        ),
    )
    assertions += 3

    no_metadata = resolve_ocr_eligible_assignment(
        tests_config=_config(),
        progress=progress,
        log_entry={},
        sid="student-1",
        assignment_date="2026-08-28",
        test_id="test-1",
        assignment_label=LABEL,
    )
    assert no_metadata["testName"] == "지수 Lv.3"
    assertions += 1

    done_progress = {"2026-08-28": {"student-1": {"tests": {LABEL: "done"}}}}
    _raises(
        "assignment_not_active",
        lambda: resolve_ocr_eligible_assignment(
            tests_config=_config(),
            progress=done_progress,
            log_entry=log_entry,
            sid="student-1",
            assignment_date="2026-08-28",
            test_id="test-1",
            assignment_label=LABEL,
        ),
    )
    assertions += 1

    wrong_log = {"assignedTests": [{"id": "other-test", "label": LABEL}]}
    _raises(
        "assignment_identity_mismatch",
        lambda: resolve_ocr_eligible_assignment(
            tests_config=_config(),
            progress=progress,
            log_entry=wrong_log,
            sid="student-1",
            assignment_date="2026-08-28",
            test_id="test-1",
            assignment_label=LABEL,
        ),
    )
    _raises(
        "ocr_test_ineligible",
        lambda: resolve_ocr_eligible_assignment(
            tests_config=_config(category="REVIEW"),
            progress=progress,
            log_entry=log_entry,
            sid="student-1",
            assignment_date="2026-08-28",
            test_id="test-1",
            assignment_label=LABEL,
        ),
    )
    _raises(
        "invalid_choice_key",
        lambda: resolve_ocr_eligible_assignment(
            tests_config=_config(choice_key="7"),
            progress=progress,
            log_entry=log_entry,
            sid="student-1",
            assignment_date="2026-08-28",
            test_id="test-1",
            assignment_label=LABEL,
        ),
    )
    assertions += 3
    return {"name": "student-test-ocr-eligibility", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
