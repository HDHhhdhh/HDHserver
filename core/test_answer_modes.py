from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final


CHOICE_NUMBER: Final[str] = "choice_number"
ANSWER_VALUE: Final[str] = "answer_value"
MANUAL_REVIEW: Final[str] = "manual_review"
VALID_ANSWER_MODES: Final[frozenset[str]] = frozenset(
    {CHOICE_NUMBER, ANSWER_VALUE, MANUAL_REVIEW}
)

_ANSWER_MODE_ALIASES: Final[dict[str, str]] = {
    CHOICE_NUMBER: CHOICE_NUMBER,
    "choice": CHOICE_NUMBER,
    "multiple_choice": CHOICE_NUMBER,
    "objective": CHOICE_NUMBER,
    "객관식": CHOICE_NUMBER,
    "선택형": CHOICE_NUMBER,
    ANSWER_VALUE: ANSWER_VALUE,
    "short_answer": ANSWER_VALUE,
    "subjective": ANSWER_VALUE,
    "주관식": ANSWER_VALUE,
    "단답형": ANSWER_VALUE,
    MANUAL_REVIEW: MANUAL_REVIEW,
    "manual": MANUAL_REVIEW,
    "수동검토": MANUAL_REVIEW,
}


def normalize_answer_mode(value: object) -> str:
    text = str(value or "").strip().casefold()
    return _ANSWER_MODE_ALIASES.get(text, "")


def normalize_answer_modes(value: object, problems: int) -> list[str]:
    total = max(int(problems or 0), 0)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        values: list[object] = []
    else:
        values = list(value[:total])
    modes = [normalize_answer_mode(item) for item in values]
    if len(modes) < total:
        modes.extend([""] * (total - len(modes)))
    return modes


def answer_modes_for_round(
    test_def: object,
    problems: int | None = None,
    round_no: object | None = None,
) -> list[str]:
    if not isinstance(test_def, Mapping):
        return [] if problems is None else [""] * max(int(problems or 0), 0)

    try:
        total = max(int(problems if problems is not None else test_def.get("problems") or 0), 0)
    except (TypeError, ValueError):
        total = 0
    round_key = str(round_no if round_no is not None else test_def.get("round") or "1").strip() or "1"

    raw_modes = test_def.get("answerModes")
    if raw_modes is None:
        raw_modes = test_def.get("answer_modes")
    if isinstance(raw_modes, Mapping):
        raw_modes = raw_modes.get(round_key)
    return normalize_answer_modes(raw_modes, total)


def answer_mode_for_question(
    test_def: object,
    question_no: object,
    *,
    problems: int | None = None,
    round_no: object | None = None,
) -> str:
    try:
        index = int(question_no) - 1
    except (TypeError, ValueError):
        return ""
    modes = answer_modes_for_round(test_def, problems, round_no)
    return modes[index] if 0 <= index < len(modes) else ""


def answer_modes_complete(modes: object, problems: int) -> bool:
    normalized = normalize_answer_modes(modes, problems)
    return len(normalized) == max(int(problems or 0), 0) and all(
        mode in VALID_ANSWER_MODES for mode in normalized
    )
