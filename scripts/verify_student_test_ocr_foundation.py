from __future__ import annotations

from core.student_test_ocr_rules import (
    ACTION_FULL_SHEET_RETAKE,
    ACTION_NONE,
    ACTION_PENDING_TEACHER,
    ACTION_QUESTION_RECAPTURE,
    ACTION_STUDENT_CHOICE,
    ANSWER_VALUE,
    CHOICE_NUMBER,
    GRADE_CORRECT,
    GRADE_INCORRECT,
    GRADE_PENDING,
    OcrRuleError,
    STATUS_FINALIZED,
    STATUS_PENDING_TEACHER,
    STATUS_READY_TO_GRADE,
    STATUS_RETAKE_REQUIRED,
    STATUS_STUDENT_ACTION_REQUIRED,
    answer_value_recapture_decision,
    answer_values_equivalent,
    apply_wrong_to_correct,
    classify_sheet_recognition,
    grade_submission,
    resolve_pending_grade,
    validate_test_answer_contract,
)


def _raises(code: str, callback) -> None:
    try:
        callback()
    except OcrRuleError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError(f"expected {code}")


def _test_definition(*, modes=None, keys=None, problems=20) -> dict:
    return {
        "problems": problems,
        "answerModes": {"1": list(modes or ([CHOICE_NUMBER, ANSWER_VALUE] * 10))},
        "answerKeys": {"1": list(keys or (["3", "1/2"] * 10))},
        "unknownField": {"preserved": True},
    }


def _candidates(*, uncertain=()) -> list[dict]:
    uncertain_set = set(uncertain)
    return [
        {
            "questionNo": question_no,
            "rawAnswer": "3" if question_no % 2 else "\\frac{2}{4}",
            "confidence": 0.99 if question_no not in uncertain_set else 0.1,
            "confident": question_no not in uncertain_set,
        }
        for question_no in range(1, 21)
    ]


def run() -> dict:
    assertions = 0

    contract = validate_test_answer_contract(category="UNIT", test=_test_definition(), round_no="1")
    assert contract["problemCount"] == 20 and contract["answerModes"][0] == CHOICE_NUMBER
    assertions += 1
    _raises(
        "ocr_test_ineligible",
        lambda: validate_test_answer_contract(category="REVIEW", test=_test_definition(), round_no="1"),
    )
    _raises(
        "invalid_choice_key",
        lambda: validate_test_answer_contract(
            category="UNIT",
            test=_test_definition(keys=["7", "1/2"] * 10),
            round_no="1",
        ),
    )
    _raises(
        "ocr_test_ineligible",
        lambda: validate_test_answer_contract(
            category="UNIT",
            test=_test_definition(modes=["manual_review", ANSWER_VALUE] * 10),
            round_no="1",
        ),
    )
    assertions += 3

    assert answer_values_equivalent("1/2", "0.5")
    assert answer_values_equivalent("2sqrt(2)", "sqrt(8)")
    assert answer_values_equivalent("\\frac{\\sqrt{2}}{2}", "sqrt(2)/2")
    assert not answer_values_equivalent("1.414", "sqrt(2)")
    assert answer_values_equivalent("ab^2/7", "ab^2/7")
    assert not answer_values_equivalent("ab^2/7", "a*b^2/7")
    assertions += 6

    modes = [CHOICE_NUMBER, ANSWER_VALUE] * 10
    ready = classify_sheet_recognition(modes, _candidates())
    assert ready["status"] == STATUS_READY_TO_GRADE and ready["uncertainCount"] == 0
    assert all(item["studentAction"] == ACTION_NONE for item in ready["items"])
    assertions += 2

    action_required = classify_sheet_recognition(modes, _candidates(uncertain=(1, 2, 3)))
    assert action_required["status"] == STATUS_STUDENT_ACTION_REQUIRED
    assert action_required["items"][0]["studentAction"] == ACTION_STUDENT_CHOICE
    assert action_required["items"][1]["studentAction"] == ACTION_QUESTION_RECAPTURE
    assert action_required["uncertainQuestionNos"] == (1, 2, 3)
    assertions += 4

    retake = classify_sheet_recognition(modes, _candidates(uncertain=(1, 2, 3, 4)))
    assert retake["status"] == STATUS_RETAKE_REQUIRED
    assert all(item["studentAction"] == ACTION_FULL_SHEET_RETAKE for item in retake["items"])
    assertions += 2

    assert answer_value_recapture_decision(attempts_used=1, confident=False) == ACTION_QUESTION_RECAPTURE
    assert answer_value_recapture_decision(attempts_used=2, confident=False) == ACTION_PENDING_TEACHER
    assert answer_value_recapture_decision(attempts_used=2, confident=True) == ACTION_NONE
    assertions += 3

    graded = grade_submission(
        answer_modes=modes,
        submitted_answers=["3", "2/4"] * 10,
        answer_keys=["3", "0.5"] * 10,
        pending_question_nos=(2,),
    )
    assert graded["correctCount"] == 19 and graded["pendingCount"] == 1
    assert graded["score"] is None and graded["status"] == STATUS_PENDING_TEACHER
    assertions += 2

    resolved = resolve_pending_grade(graded["gradeStates"], question_no=2, correct=False)
    assert resolved["gradeStates"][1] == GRADE_INCORRECT
    assert resolved["score"] == 19 and resolved["status"] == STATUS_FINALIZED
    assertions += 2

    corrected = apply_wrong_to_correct(resolved["gradeStates"], question_no=2)
    assert corrected["gradeStates"][1] == GRADE_CORRECT and corrected["score"] == 20
    assert corrected["history"] == [{"questionNo": 2, "from": GRADE_INCORRECT, "to": GRADE_CORRECT}]
    assert set(corrected["history"][0]) == {"questionNo", "from", "to"}
    assertions += 3

    _raises(
        "grade_transition_rejected",
        lambda: apply_wrong_to_correct(corrected["gradeStates"], question_no=2),
    )
    _raises(
        "grade_transition_rejected",
        lambda: resolve_pending_grade(corrected["gradeStates"], question_no=1, correct=True),
    )
    assertions += 2

    assert GRADE_PENDING not in corrected["gradeStates"]
    assertions += 1
    return {"name": "student-test-ocr-foundation", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
