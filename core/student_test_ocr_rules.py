from __future__ import annotations

import ast
import re
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Final, Iterable, Mapping, Sequence


PROBLEM_COUNT: Final = 20
FULL_RETAKE_UNCERTAIN_COUNT: Final = 4
MAX_ANSWER_VALUE_RECAPTURES: Final = 2

CHOICE_NUMBER: Final = "choice_number"
ANSWER_VALUE: Final = "answer_value"
MANUAL_REVIEW: Final = "manual_review"
OCR_ELIGIBLE_MODES: Final = frozenset({CHOICE_NUMBER, ANSWER_VALUE})

GRADE_CORRECT: Final = "correct"
GRADE_INCORRECT: Final = "incorrect"
GRADE_PENDING: Final = "pending"
GRADE_STATES: Final = frozenset({GRADE_CORRECT, GRADE_INCORRECT, GRADE_PENDING})

STATUS_READY_TO_GRADE: Final = "ready_to_grade"
STATUS_STUDENT_ACTION_REQUIRED: Final = "student_action_required"
STATUS_RETAKE_REQUIRED: Final = "retake_required"
STATUS_PENDING_TEACHER: Final = "pending_teacher"
STATUS_FINALIZED: Final = "finalized"

ACTION_NONE: Final = "none"
ACTION_STUDENT_CHOICE: Final = "student_choice"
ACTION_QUESTION_RECAPTURE: Final = "question_recapture"
ACTION_FULL_SHEET_RETAKE: Final = "full_sheet_retake"
ACTION_PENDING_TEACHER: Final = "pending_teacher"

ANSWER_SOURCE_OCR_INITIAL: Final = "ocr_initial"
ANSWER_SOURCE_STUDENT_CHOICE: Final = "student_choice_correction"
ANSWER_SOURCE_QUESTION_RECAPTURE: Final = "ocr_question_recapture"

_CIRCLED_DIGITS: Final = str.maketrans({"①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5"})
_UNICODE_REPLACEMENTS: Final = str.maketrans(
    {
        "−": "-",
        "–": "-",
        "—": "-",
        "×": "*",
        "∙": "*",
        "·": "*",
        "÷": "/",
        "²": "^2",
        "³": "^3",
    }
)
_SIMPLE_FRAC_RE: Final = re.compile(r"\\(?:d|t)?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
_SIMPLE_SQRT_RE: Final = re.compile(r"\\sqrt\s*\{([^{}]+)\}")
_WHITESPACE_RE: Final = re.compile(r"\s+")
_SAFE_EXPRESSION_RE: Final = re.compile(r"[0-9a-zA-Z.+\-*/(),]+")
_RELATIVE_TOLERANCE: Final = Decimal("1e-12")


@dataclass(frozen=True, slots=True)
class OcrRuleError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _fail(code: str, message: str) -> None:
    raise OcrRuleError(code, message)


def _round_values(container: object, round_no: str, label: str) -> list:
    if not isinstance(container, Mapping):
        _fail("ocr_test_ineligible", f"{label} must be a round-keyed object")
    raw = container.get(round_no)
    if not isinstance(raw, list):
        _fail("ocr_test_ineligible", f"{label}[{round_no}] must be an array")
    return list(raw)


def validate_test_answer_contract(
    *,
    category: str,
    test: Mapping[str, object],
    round_no: str,
) -> dict:
    """Return the immutable grading contract for an OCR-eligible UNIT round."""

    if str(category or "").strip().upper() != "UNIT":
        _fail("ocr_test_ineligible", "the first OCR release accepts UNIT tests only")
    normalized_round = str(round_no or "").strip()
    if not normalized_round.isdigit() or int(normalized_round) < 1:
        _fail("invalid_round", "round must be a positive integer")
    problems = test.get("problems")
    if isinstance(problems, bool) or not isinstance(problems, int) or problems != PROBLEM_COUNT:
        _fail("ocr_test_ineligible", "OCR tests must contain exactly 20 questions")

    modes = _round_values(test.get("answerModes"), normalized_round, "answerModes")
    keys = _round_values(test.get("answerKeys"), normalized_round, "answerKeys")
    if len(modes) != PROBLEM_COUNT or len(keys) != PROBLEM_COUNT:
        _fail("ocr_test_ineligible", "answer modes and keys must cover all 20 questions")

    normalized_modes: list[str] = []
    normalized_keys: list[str] = []
    for index, (raw_mode, raw_key) in enumerate(zip(modes, keys), start=1):
        mode = str(raw_mode or "").strip()
        if mode not in OCR_ELIGIBLE_MODES:
            _fail("ocr_test_ineligible", f"question {index} has an unsupported answer mode")
        key = canonicalize_answer_text(raw_key) if mode == CHOICE_NUMBER else normalize_recognized_answer(mode, raw_key)
        if not key:
            _fail("ocr_test_ineligible", f"question {index} has an empty answer key")
        if mode == CHOICE_NUMBER and key not in {"1", "2", "3", "4", "5"}:
            _fail("invalid_choice_key", f"question {index} choice key must be 1 through 5")
        normalized_modes.append(mode)
        normalized_keys.append(key)

    return {
        "problemCount": PROBLEM_COUNT,
        "round": normalized_round,
        "answerModes": tuple(normalized_modes),
        "answerKeys": tuple(normalized_keys),
    }


def canonicalize_answer_text(value: object) -> str:
    text = str(value or "").strip().translate(_CIRCLED_DIGITS).translate(_UNICODE_REPLACEMENTS)
    if re.search(r"\d\s+\d", text):
        return ""
    text = text.replace("\\left", "").replace("\\right", "").replace("$", "")
    text = re.sub(r"\\(?:times|cdot)(?![A-Za-z])", "*", text)
    text = re.sub(r"\\div(?![A-Za-z])", "/", text)
    text = re.sub(r"\\sqrt\s*\[\s*2\s*\]", r"\\sqrt", text)
    text = _WHITESPACE_RE.sub("", text)
    for _ in range(8):
        changed = _SIMPLE_SQRT_RE.sub(r"sqrt(\1)", text)
        changed = re.sub(r"sqrt\{([^{}]+)\}", r"sqrt(\1)", changed)
        changed = _SIMPLE_FRAC_RE.sub(r"((\1)/(\2))", changed)
        if changed == text:
            break
        text = changed
    text = text.replace("{", "(").replace("}", ")")
    text = re.sub(r"√\(([^()]*)\)", r"sqrt(\1)", text)
    text = re.sub(r"√([0-9]+(?:\.[0-9]+)?)", r"sqrt(\1)", text)
    text = text.replace("√", "sqrt")
    return text


def normalize_recognized_answer(answer_mode: str, value: object) -> str:
    text = canonicalize_answer_text(value)
    if answer_mode == CHOICE_NUMBER:
        return text if text in {"1", "2", "3", "4", "5"} else ""
    if answer_mode == ANSWER_VALUE:
        return text if len(text) <= 80 else ""
    _fail("unsupported_answer_mode", f"unsupported answer mode: {answer_mode}")


def _prepare_numeric_expression(value: object) -> str:
    text = canonicalize_answer_text(value)
    if not text or len(text) > 80:
        _fail("invalid_numeric_expression", "numeric expression is empty or too long")
    text = text.replace("^", "**")
    text = re.sub(r"(?<=[0-9.)])(?=sqrt|\()", "*", text)
    text = re.sub(r"(?<=\))(?=[0-9.])", "*", text)
    if not _SAFE_EXPRESSION_RE.fullmatch(text):
        _fail("invalid_numeric_expression", "numeric expression contains unsupported characters")
    return text


def _eval_numeric_node(node: ast.AST, *, depth: int = 0) -> Decimal:
    if depth > 32:
        _fail("invalid_numeric_expression", "numeric expression is too deeply nested")
    if isinstance(node, ast.Expression):
        return _eval_numeric_node(node.body, depth=depth + 1)
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
        if isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        _fail("invalid_numeric_expression", "numeric expression contains a non-number")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_numeric_node(node.operand, depth=depth + 1)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _eval_numeric_node(node.left, depth=depth + 1)
        right = _eval_numeric_node(node.right, depth=depth + 1)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                _fail("invalid_numeric_expression", "division by zero is not allowed")
            return left / right
        if isinstance(node.op, ast.Pow):
            if right != right.to_integral_value() or not -12 <= int(right) <= 12:
                _fail("invalid_numeric_expression", "only small integer powers are supported")
            if left == 0 and right < 0:
                _fail("invalid_numeric_expression", "zero cannot have a negative power")
            return left ** int(right)
        _fail("invalid_numeric_expression", "numeric operator is unsupported")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id.lower() != "sqrt":
            _fail("invalid_numeric_expression", "only sqrt() calls are supported")
        if len(node.args) != 1 or node.keywords:
            _fail("invalid_numeric_expression", "sqrt() requires one argument")
        value = _eval_numeric_node(node.args[0], depth=depth + 1)
        if value < 0:
            _fail("invalid_numeric_expression", "negative square roots are unsupported")
        return value.sqrt()
    _fail("invalid_numeric_expression", "numeric expression syntax is unsupported")


def numeric_answer_value(value: object) -> Decimal:
    expression = _prepare_numeric_expression(value)
    try:
        parsed = ast.parse(expression, mode="eval")
        with localcontext() as context:
            context.prec = 64
            result = _eval_numeric_node(parsed)
    except (SyntaxError, InvalidOperation, OverflowError) as error:
        raise OcrRuleError("invalid_numeric_expression", "numeric expression could not be evaluated") from error
    if not result.is_finite() or abs(result) > Decimal("1e100"):
        _fail("invalid_numeric_expression", "numeric expression result is out of range")
    return result


def answer_values_equivalent(left: object, right: object) -> bool:
    left_text = canonicalize_answer_text(left)
    right_text = canonicalize_answer_text(right)
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    try:
        left_value = numeric_answer_value(left_text)
        right_value = numeric_answer_value(right_text)
    except OcrRuleError:
        # Variable-bearing or otherwise symbolic answers stay normalized-string exact in v1.
        return False
    scale = max(abs(left_value), abs(right_value), Decimal(1))
    return abs(left_value - right_value) <= _RELATIVE_TOLERANCE * scale


def grade_answer(answer_mode: str, submitted: object, answer_key: object) -> str:
    submitted_text = normalize_recognized_answer(answer_mode, submitted)
    key_text = normalize_recognized_answer(answer_mode, answer_key)
    if not submitted_text or not key_text:
        return GRADE_INCORRECT
    if answer_mode == CHOICE_NUMBER:
        return GRADE_CORRECT if submitted_text == key_text else GRADE_INCORRECT
    if answer_mode == ANSWER_VALUE:
        return GRADE_CORRECT if answer_values_equivalent(submitted_text, key_text) else GRADE_INCORRECT
    _fail("unsupported_answer_mode", f"unsupported answer mode: {answer_mode}")


def _validated_modes(answer_modes: Sequence[object]) -> tuple[str, ...]:
    if len(answer_modes) != PROBLEM_COUNT:
        _fail("invalid_recognition_payload", "answer modes must cover 20 questions")
    modes = tuple(str(mode or "").strip() for mode in answer_modes)
    if any(mode not in OCR_ELIGIBLE_MODES for mode in modes):
        _fail("ocr_test_ineligible", "recognition payload contains an unsupported answer mode")
    return modes


def classify_sheet_recognition(
    answer_modes: Sequence[object],
    candidates: Iterable[Mapping[str, object]],
) -> dict:
    """Classify OCR output without accepting or consulting answer keys."""

    modes = _validated_modes(answer_modes)
    indexed: dict[int, Mapping[str, object]] = {}
    for candidate in candidates:
        question_no = candidate.get("questionNo")
        if isinstance(question_no, bool) or not isinstance(question_no, int):
            _fail("invalid_recognition_payload", "questionNo must be an integer")
        if not 1 <= question_no <= PROBLEM_COUNT or question_no in indexed:
            _fail("invalid_recognition_payload", "questions must uniquely cover 1 through 20")
        indexed[question_no] = candidate
    if set(indexed) != set(range(1, PROBLEM_COUNT + 1)):
        _fail("invalid_recognition_payload", "recognition payload must cover all 20 questions")

    items: list[dict] = []
    uncertain: list[int] = []
    for question_no, mode in enumerate(modes, start=1):
        candidate = indexed[question_no]
        raw_answer = str(candidate.get("rawAnswer") or "").strip()[:80]
        normalized = normalize_recognized_answer(mode, raw_answer)
        confidence = candidate.get("confidence")
        if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float))):
            _fail("invalid_recognition_payload", "confidence must be numeric or null")
        confident = candidate.get("confident") is True and bool(normalized)
        if not confident:
            uncertain.append(question_no)
        items.append(
            {
                "questionNo": question_no,
                "answerMode": mode,
                "rawAnswer": raw_answer,
                "normalizedAnswer": normalized,
                "confidence": None if confidence is None else float(confidence),
                "recognitionState": "confident" if confident else "uncertain",
                "answerSource": ANSWER_SOURCE_OCR_INITIAL if confident else "",
                "studentAction": ACTION_NONE,
            }
        )

    if len(uncertain) >= FULL_RETAKE_UNCERTAIN_COUNT:
        status = STATUS_RETAKE_REQUIRED
        for item in items:
            item["studentAction"] = ACTION_FULL_SHEET_RETAKE
    elif uncertain:
        status = STATUS_STUDENT_ACTION_REQUIRED
        for question_no in uncertain:
            item = items[question_no - 1]
            item["studentAction"] = (
                ACTION_STUDENT_CHOICE if item["answerMode"] == CHOICE_NUMBER else ACTION_QUESTION_RECAPTURE
            )
    else:
        status = STATUS_READY_TO_GRADE

    return {
        "status": status,
        "problemCount": PROBLEM_COUNT,
        "uncertainCount": len(uncertain),
        "uncertainQuestionNos": tuple(uncertain),
        "items": items,
    }


def answer_value_recapture_decision(*, attempts_used: int, confident: bool) -> str:
    if isinstance(attempts_used, bool) or not isinstance(attempts_used, int) or not 1 <= attempts_used <= MAX_ANSWER_VALUE_RECAPTURES:
        _fail("invalid_recapture_attempt", "answer-value recapture attempt must be 1 or 2")
    if confident:
        return ACTION_NONE
    if attempts_used < MAX_ANSWER_VALUE_RECAPTURES:
        return ACTION_QUESTION_RECAPTURE
    return ACTION_PENDING_TEACHER


def grade_submission(
    *,
    answer_modes: Sequence[object],
    submitted_answers: Sequence[object | None],
    answer_keys: Sequence[object],
    pending_question_nos: Iterable[int] = (),
) -> dict:
    modes = _validated_modes(answer_modes)
    if len(submitted_answers) != PROBLEM_COUNT or len(answer_keys) != PROBLEM_COUNT:
        _fail("invalid_grading_payload", "answers and keys must cover 20 questions")
    pending = set(pending_question_nos)
    if any(isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= PROBLEM_COUNT for number in pending):
        _fail("invalid_grading_payload", "pending questions must be between 1 and 20")

    grades: list[str] = []
    for question_no, (mode, submitted, answer_key) in enumerate(zip(modes, submitted_answers, answer_keys), start=1):
        if question_no in pending:
            grades.append(GRADE_PENDING)
            continue
        if submitted is None or not normalize_recognized_answer(mode, submitted):
            _fail("invalid_grading_payload", f"question {question_no} has no submitted answer")
        grades.append(grade_answer(mode, submitted, answer_key))
    return {"gradeStates": tuple(grades), **summarize_grades(grades)}


def summarize_grades(grade_states: Sequence[object]) -> dict:
    grades = tuple(str(grade or "").strip() for grade in grade_states)
    if len(grades) != PROBLEM_COUNT or any(grade not in GRADE_STATES for grade in grades):
        _fail("invalid_grade_state", "grade states must contain 20 valid values")
    correct = grades.count(GRADE_CORRECT)
    incorrect = grades.count(GRADE_INCORRECT)
    pending = grades.count(GRADE_PENDING)
    return {
        "correctCount": correct,
        "incorrectCount": incorrect,
        "pendingCount": pending,
        "problemCount": PROBLEM_COUNT,
        "score": None if pending else correct,
        "status": STATUS_PENDING_TEACHER if pending else STATUS_FINALIZED,
    }


def resolve_pending_grade(grade_states: Sequence[object], *, question_no: int, correct: bool) -> dict:
    grades = list(str(grade or "").strip() for grade in grade_states)
    summarize_grades(grades)
    if isinstance(question_no, bool) or not isinstance(question_no, int) or not 1 <= question_no <= PROBLEM_COUNT:
        _fail("invalid_question", "question number must be between 1 and 20")
    if grades[question_no - 1] != GRADE_PENDING:
        _fail("grade_transition_rejected", "only a pending question can be resolved")
    grades[question_no - 1] = GRADE_CORRECT if correct else GRADE_INCORRECT
    return {"gradeStates": tuple(grades), **summarize_grades(grades)}


def apply_wrong_to_correct(
    grade_states: Sequence[object],
    *,
    question_no: int,
    history: Sequence[Mapping[str, object]] = (),
) -> dict:
    grades = list(str(grade or "").strip() for grade in grade_states)
    summarize_grades(grades)
    if isinstance(question_no, bool) or not isinstance(question_no, int) or not 1 <= question_no <= PROBLEM_COUNT:
        _fail("invalid_question", "question number must be between 1 and 20")
    if grades[question_no - 1] != GRADE_INCORRECT:
        _fail("grade_transition_rejected", "only an incorrect question can be changed to correct")
    grades[question_no - 1] = GRADE_CORRECT
    updated_history = [deepcopy(dict(item)) for item in history]
    updated_history.append({"questionNo": question_no, "from": GRADE_INCORRECT, "to": GRADE_CORRECT})
    return {
        "gradeStates": tuple(grades),
        "history": updated_history,
        **summarize_grades(grades),
    }
