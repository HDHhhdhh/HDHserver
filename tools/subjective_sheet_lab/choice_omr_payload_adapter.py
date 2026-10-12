from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from choice_omr import OmrReading, detect_crop
from ocr_payload_leak_policy import forbidden_paths, path_exposures
from ocr_review_payload_validator import ContractError, PayloadMode, validate_payload

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

QUESTION_COUNT: Final[int] = 20
CHOICE_MODE: Final[str] = "choice_number"


class ChoiceOmrAdapterError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ChoiceOmrRequest:
    test_id: str
    round_no: int
    crop_dir: Path
    answer_modes: tuple[str, ...]


def load_choice_omr_payload(request: ChoiceOmrRequest) -> JsonObject:
    validate_request(request)
    items: list[JsonObject] = []
    for question in range(1, QUESTION_COUNT + 1):
        reading = detect_crop(request.crop_dir / f"q{question:03d}.png")
        items.append(item_from_reading(question, reading))

    payload: JsonObject = {
        "source": "choice_omr_v1",
        "test_id": request.test_id,
        "round": str(request.round_no),
        "problem_count": QUESTION_COUNT,
        "items": items,
    }
    if forbidden_paths(payload):
        raise ChoiceOmrAdapterError("OMR payload contains forbidden fields")
    if path_exposures(payload):
        raise ChoiceOmrAdapterError("OMR payload exposes a local filesystem path")
    try:
        validate_payload(payload, PayloadMode.REVIEW, "choice_omr_payload")
    except ContractError as exc:
        raise ChoiceOmrAdapterError(f"OMR payload contract failed: {exc}") from exc
    return payload


def validate_request(request: ChoiceOmrRequest) -> None:
    if not request.test_id.strip():
        raise ChoiceOmrAdapterError("test_id is required")
    if request.round_no <= 0:
        raise ChoiceOmrAdapterError("round_no must be positive")
    if not request.crop_dir.is_dir():
        raise ChoiceOmrAdapterError("crop directory is missing")
    if len(request.answer_modes) != QUESTION_COUNT:
        raise ChoiceOmrAdapterError("exactly 20 answer modes are required")
    non_choice = [index for index, mode in enumerate(request.answer_modes, start=1) if mode != CHOICE_MODE]
    if non_choice:
        raise ChoiceOmrAdapterError(
            f"OMR accepts choice_number questions only: {', '.join(map(str, non_choice))}"
        )
    missing = [
        question
        for question in range(1, QUESTION_COUNT + 1)
        if not (request.crop_dir / f"q{question:03d}.png").is_file()
    ]
    if missing:
        raise ChoiceOmrAdapterError(f"missing OMR crops: {', '.join(map(str, missing))}")


def item_from_reading(question: int, reading: OmrReading) -> JsonObject:
    if reading.accepted and reading.selected is not None:
        answer = str(reading.selected)
        return {
            "question_no": question,
            "status": "safe_auto_grade",
            "recognized": answer,
            "warnings": [],
            "candidates": [],
            "final_answer": answer,
            "source": "safe_auto_grade",
        }
    warning = {
        "blank": "omr_unfilled",
        "multiple": "multiple_answers",
        "ambiguous": "unclear_final_answer",
    }.get(reading.status, "omr_unreadable")
    return {
        "question_no": question,
        "status": "retake_required",
        "recognized": "?",
        "warnings": [warning],
        "candidates": [],
        "final_answer": None,
        "source": None,
    }
