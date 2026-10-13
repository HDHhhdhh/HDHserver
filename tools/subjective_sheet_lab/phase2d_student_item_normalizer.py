from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Final, TypeAlias

from tools.subjective_sheet_lab.ocr_answer_mode_policy import answer_mode_auto_grade_warning
from tools.subjective_sheet_lab.ocr_erased_overwritten_policy import normalize_review_item_for_safety


JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
DEFAULT_CACHE_TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
FINAL_STATUSES: Final[frozenset[str]] = frozenset(
    (
        "safe_auto_grade",
        "confirmed",
        "student_selected_candidate",
        "student_direct_input",
        "safe_auto_grade_after_retake",
        "student_selected_candidate_after_retake",
        "student_direct_input_after_retake",
    )
)
UNRESOLVED_STATUSES: Final[frozenset[str]] = frozenset(("review_required", "retake_required", "data_check_required"))
VALID_STATUSES: Final[frozenset[str]] = FINAL_STATUSES | UNRESOLVED_STATUSES | frozenset(("retake_uploaded",))
SOURCE_BY_STATUS: Final[dict[str, str]] = {
    "safe_auto_grade": "safe_auto_grade",
    "student_selected_candidate": "student_selected_candidate",
    "student_direct_input": "student_direct_input",
    "safe_auto_grade_after_retake": "safe_auto_grade_after_retake",
    "student_selected_candidate_after_retake": "student_selected_candidate_after_retake",
    "student_direct_input_after_retake": "student_direct_input_after_retake",
}


@dataclass(frozen=True, slots=True)
class StudentItemNormalizationError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def normalize_review_item_for_answer_mode(item: JsonObject, test_id: str = DEFAULT_CACHE_TEST_ID) -> JsonObject:
    status = text_value(item.get("status"))
    source = text_value(item.get("source"))
    if status not in FINAL_STATUSES and source not in FINAL_STATUSES:
        return item
    question_no = item.get("question_no")
    if not isinstance(question_no, int) or isinstance(question_no, bool):
        return downgrade_to_review_required(item, "unclear_final_answer")
    answer = text_value(item.get("final_answer")) or text_value(item.get("recognized"))
    warning = answer_mode_auto_grade_warning(question_no, answer, test_id)
    return downgrade_to_review_required(item, warning) if warning is not None else item


def normalize_student_item(item: JsonObject, question_no: int, test_id: str, optional_text: Callable[[JsonValue, str], str]) -> JsonObject:
    recognized = optional_text(item.get("recognized"), "recognized")
    status = status_text(item.get("status"), "status")
    source = source_for_status(item.get("source"), status, optional_text)
    final_answer = final_answer_for_status(item.get("final_answer"), status, optional_text)
    warnings = string_list(item.get("warnings"), "warnings")
    student_item: JsonObject = {
        "question_no": question_no,
        "status": status,
        "recognized": recognized,
        "warnings": list(dict.fromkeys(warnings)),
        "candidates": string_list(item.get("candidates"), "candidates"),
        "final_answer": final_answer,
        "source": source,
    }
    return normalize_review_item_for_answer_mode(normalize_review_item_for_safety(student_item), test_id)


def downgrade_to_review_required(item: JsonObject, warning_code: str) -> JsonObject:
    normalized = dict(item)
    raw_warnings = item.get("warnings")
    warnings = [warning for warning in raw_warnings if isinstance(warning, str)] if isinstance(raw_warnings, list) else []
    if warning_code not in warnings:
        warnings.append(warning_code)
    normalized["warnings"] = warnings
    normalized["status"] = "review_required"
    normalized["source"] = None
    normalized["final_answer"] = None
    return normalized


def status_text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StudentItemNormalizationError(f"{label} must be a status string")
    status = value.strip()
    if status not in VALID_STATUSES:
        raise StudentItemNormalizationError(f"unsupported status: {status}")
    return status


def source_for_status(value: JsonValue, status: str, optional_text: Callable[[JsonValue, str], str]) -> str | None:
    if status in UNRESOLVED_STATUSES or status == "retake_uploaded":
        return None
    if status == "confirmed":
        return optional_text(value, "source") if isinstance(value, str) else None
    return SOURCE_BY_STATUS.get(status)


def final_answer_for_status(value: JsonValue, status: str, optional_text: Callable[[JsonValue, str], str]) -> str | None:
    if status in UNRESOLVED_STATUSES or status == "retake_uploaded":
        return None
    return optional_text(value, "final_answer")


def string_list(value: JsonValue, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StudentItemNormalizationError(f"{label} must be a list")
    if not all(isinstance(item, str) and "\n" not in item and "\r" not in item for item in value):
        raise StudentItemNormalizationError(f"{label} must contain single-line strings")
    return list(value)


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""
