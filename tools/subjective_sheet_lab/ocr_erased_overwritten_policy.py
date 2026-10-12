from __future__ import annotations

from typing import Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

SAFETY_WARNING_CODES: Final[frozenset[str]] = frozenset(
    (
        "erased_trace_detected",
        "crossed_out_answer",
        "overwritten_answer",
        "multiple_answer_candidates",
        "unclear_final_answer",
        "arrow_equal_confusion",
        "relation_symbol_confusion",
        "expression_operator_confusion",
        "choice_number_invalid_for_auto_grade",
        "answer_value_letter_confusion",
        "digit_shape_confusion",
        "crop_quality_too_small",
        "crop_quality_blurry",
        "crop_quality_low_contrast",
        "crop_quality_exposure",
        "crop_quality_blank_like",
        "crop_quality_cutoff_risk",
    ),
)
RETAKE_WARNING_CODES: Final[frozenset[str]] = frozenset(
    (
        "crop_quality_too_small",
        "crop_quality_blurry",
        "crop_quality_low_contrast",
        "crop_quality_exposure",
        "crop_quality_cutoff_risk",
    )
)
AUTO_GRADE_STATUSES: Final[frozenset[str]] = frozenset(("safe_auto_grade", "safe_auto_grade_after_retake"))
UNCLEAR_PLACEHOLDERS: Final[frozenset[str]] = frozenset(("", "?", "??", "unknown", "unclear"))
TRACE_WARNING_MESSAGE: Final[str] = "지운 흔적 또는 덧쓴 흔적이 있어 확인이 필요합니다."


def has_safety_warning(warnings: tuple[str, ...] | list[str]) -> bool:
    return any(warning in SAFETY_WARNING_CODES for warning in warnings)


def blocks_auto_grade_for_safety(status: str, warnings: tuple[str, ...] | list[str]) -> bool:
    return status in AUTO_GRADE_STATUSES and has_safety_warning(warnings)


def normalize_review_item_for_safety(item: JsonObject) -> JsonObject:
    warnings = warning_strings(item.get("warnings"))
    status = text_value(item.get("status"))
    source = text_value(item.get("source"))
    if not has_safety_warning(warnings) or (status not in AUTO_GRADE_STATUSES and source not in AUTO_GRADE_STATUSES):
        return item

    normalized = dict(item)
    normalized["status"] = "retake_required" if should_require_retake(item, warnings) else "review_required"
    normalized["source"] = None
    normalized["final_answer"] = None
    return normalized


def warning_strings(value: JsonValue) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def should_require_retake(item: JsonObject, warnings: tuple[str, ...]) -> bool:
    if RETAKE_WARNING_CODES.intersection(warnings):
        return True
    if "unclear_final_answer" not in warnings:
        return False
    return not has_reliable_text(item.get("final_answer")) and not has_reliable_text(item.get("recognized")) and not has_reliable_candidate(item)


def has_reliable_candidate(item: JsonObject) -> bool:
    candidates = item.get("candidates")
    if not isinstance(candidates, list):
        return False
    return any(has_reliable_text(candidate) for candidate in candidates)


def has_reliable_text(value: JsonValue) -> bool:
    if not isinstance(value, str):
        return False
    return value.strip().lower() not in UNCLEAR_PLACEHOLDERS


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""
