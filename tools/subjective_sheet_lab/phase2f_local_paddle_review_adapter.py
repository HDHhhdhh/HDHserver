from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Final, TypeAlias

from tools.subjective_sheet_lab.ocr_local_worker_adapter import OcrError, OcrLine, run_local_ocr
from tools.subjective_sheet_lab.ocr_image_quality_gate import crop_quality_warnings
from tools.subjective_sheet_lab.ocr_overwritten_ambiguity_artifact import (
    OverwrittenAmbiguityArtifactError,
    load_overwritten_ambiguity_warnings,
)
from tools.subjective_sheet_lab.ocr_payload_leak_policy import forbidden_paths, path_exposures
from tools.subjective_sheet_lab.phase2c_crop_pipeline_adapter import Phase2CResult
from tools.subjective_sheet_lab.phase2d_student_item_normalizer import normalize_student_item

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

QUESTION_COUNT: Final[int] = 20
LOW_CONFIDENCE_THRESHOLD: Final[float] = 0.65
LOCAL_OCR_UNVERIFIED_WARNING: Final[str] = "local_ocr_unverified"
LOCAL_OCR_LOW_CONFIDENCE_WARNING: Final[str] = "local_ocr_low_confidence"
QUESTION_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"^0?([1-9]|1[0-9]|20)$")
NUMERIC_ONLY_RE: Final[re.Pattern[str]] = re.compile(r"^\d+$")
NUMERIC_ONLY_ENV: Final[str] = "OCR_PHASE2_NUMERIC_ONLY"


@dataclass(frozen=True, slots=True)
class Phase2FRequest:
    sid: str
    test_id: str
    round_no: int
    pipeline_result: Phase2CResult
    form_id: str = "answer_sheet_20_v1"
    preprocessing_version: str = "crop_contact_v1"


@dataclass(frozen=True, slots=True)
class Phase2FLocalOcrUnavailable(Exception):
    reason: str
    detail: str = ""

    def __str__(self) -> str:
        return self.detail or self.reason


def load_phase2f_local_review_payload(request: Phase2FRequest) -> JsonObject:
    from tools.subjective_sheet_lab.ocr_run_identity import identity_for_request
    from tools.subjective_sheet_lab.ocr_review_run_payload import bind_review_payload, validate_pipeline_input
    identity = identity_for_request(request,model="paddle-local-unverified",prompt_version="local_transcription_v1",form_id=request.form_id,preprocessing_version=request.preprocessing_version)
    validate_pipeline_input(request.pipeline_result,identity)
    if numeric_only_enabled():
        raise Phase2FLocalOcrUnavailable("numeric_only_scope_invalid","full-sheet fallback preserves math transcription")
    source_image = request.pipeline_result.source_image
    try:
        lines = run_local_ocr(source_image, request.pipeline_result.case_dir / "offline_paddle_runtime")
    except (OSError, OcrError) as exc:
        raise Phase2FLocalOcrUnavailable("local_ocr_failed", str(exc)) from exc

    recognized = parse_two_column_answer_lines(lines)
    ambiguity_warnings = pipeline_ambiguity_warnings(request.pipeline_result)
    items: list[JsonObject] = []
    for question_no in range(1, QUESTION_COUNT + 1):
        answer, confidence = recognized[question_no]
        warnings = [LOCAL_OCR_UNVERIFIED_WARNING]
        if numeric_only_enabled() and not NUMERIC_ONLY_RE.fullmatch(answer):
            answer = "?"
            warnings.append("unclear_final_answer")
        if confidence is None or confidence < LOW_CONFIDENCE_THRESHOLD:
            warnings.append(LOCAL_OCR_LOW_CONFIDENCE_WARNING)
        warnings.extend(crop_quality_warnings(request.pipeline_result.crop_quality, question_no))
        warnings.extend(ambiguity_warnings.get(question_no, ()))
        items.append(
            normalize_student_item(
                {
                    "question_no": question_no,
                    "status": "review_required",
                    "recognized": answer,
                    "warnings": list(dict.fromkeys(warnings)),
                    "candidates": [],
                    "final_answer": None,
                    "source": None,
                },
                question_no,
                request.test_id,
                optional_text,
            )
        )

    payload: JsonObject = {
        "source": "phase2f_local_paddle_ocr",
        "test_id": request.test_id,
        "round": str(request.round_no),
        "problem_count": QUESTION_COUNT,
        "items": items,
    }
    if forbidden_paths(payload):
        raise Phase2FLocalOcrUnavailable("local_ocr_forbidden_fields")
    if path_exposures(payload):
        raise Phase2FLocalOcrUnavailable("local_ocr_path_leak")
    return bind_review_payload(payload,request.pipeline_result,identity)


def parse_two_column_answer_lines(lines: list[OcrLine]) -> dict[int, tuple[str, float | None]]:
    normalized = [(line_text(line), line_confidence(line)) for line in lines]
    answers: dict[int, tuple[str, float | None]] = {}
    cursor = 0
    for left_question in range(1, 11):
        right_question = left_question + 10
        row = find_question_row(normalized, cursor, left_question, right_question)
        if row is None:
            raise Phase2FLocalOcrUnavailable("local_ocr_layout_unrecognized", f"question row {left_question}/{right_question} was not found")
        left_answer, right_answer, cursor = row
        if not left_answer[0] or not right_answer[0] or next_row_was_consumed(left_answer[0], right_answer[0], left_question):
            raise Phase2FLocalOcrUnavailable("local_ocr_layout_unrecognized", f"question row {left_question}/{right_question} has no stable answer pair")
        answers[left_question] = left_answer
        answers[right_question] = right_answer
    if sorted(answers) != list(range(1, QUESTION_COUNT + 1)):
        raise Phase2FLocalOcrUnavailable("local_ocr_layout_unrecognized", "OCR did not produce 20 mapped answers")
    return answers


def find_question_row(
    lines: list[tuple[str, float | None]], start: int, left_question: int, right_question: int
) -> tuple[tuple[str, float | None], tuple[str, float | None], int] | None:
    for index in range(start, max(start, len(lines) - 3)):
        if question_label(lines[index][0]) != left_question:
            continue
        if question_label(lines[index + 1][0]) == right_question:
            return lines[index + 2], lines[index + 3], index + 4
        if question_label(lines[index + 2][0]) == right_question:
            return lines[index + 1], lines[index + 3], index + 4
    return None


def next_row_was_consumed(left_answer: str, right_answer: str, left_question: int) -> bool:
    return question_label(left_answer) == left_question + 1 and question_label(right_answer) == left_question + 11


def question_label(value: str) -> int | None:
    matched = QUESTION_LABEL_RE.fullmatch(value.strip())
    return int(matched.group(1)) if matched else None


def numeric_only_enabled() -> bool:
    return os.environ.get(NUMERIC_ONLY_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def line_text(line: OcrLine) -> str:
    value = line.get("text") if isinstance(line, dict) else getattr(line, "text", None)
    return value.strip() if isinstance(value, str) else ""


def line_confidence(line: OcrLine) -> float | None:
    value = line.get("confidence") if isinstance(line, dict) else getattr(line, "confidence", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    confidence = float(value)
    return confidence if 0.0 <= confidence <= 1.0 else None


def pipeline_ambiguity_warnings(pipeline_result: Phase2CResult) -> dict[int, tuple[str, ...]]:
    try:
        return load_overwritten_ambiguity_warnings(pipeline_result.overwritten_ambiguity)
    except OverwrittenAmbiguityArtifactError as exc:
        raise Phase2FLocalOcrUnavailable("pipeline_ambiguity_invalid", str(exc)) from exc


def optional_text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise Phase2FLocalOcrUnavailable("local_ocr_malformed", f"{label} must be a string")
    text = value.strip()
    if not text or "\n" in text or "\r" in text:
        raise Phase2FLocalOcrUnavailable("local_ocr_malformed", f"{label} must be a non-empty single-line string")
    return text
