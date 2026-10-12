from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from ocr_review_schema import JsonValue

JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    question_no: int
    action: str
    final_answer: str


@dataclass(frozen=True, slots=True)
class RetakeDecision:
    question_no: int
    uploaded_status: str
    rerecognized: JsonObject
    action: str
    final_answer: str


@dataclass(frozen=True, slots=True)
class DryRunOutputs:
    review_payload: JsonObject
    retake_uploaded_payload: JsonObject
    final_payload: JsonObject
    answers_text: str


@dataclass(frozen=True, slots=True)
class BlockingCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class DryRunResult:
    outputs: DryRunOutputs
    blocking_checks: tuple[BlockingCheck, ...]
    leak_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StatusBlocker:
    question_no: int
    status: str
    source: str | None


@dataclass(frozen=True, slots=True)
class RetakeApplyContext:
    question_no: int
    item: JsonObject
    uploaded_items: tuple[JsonObject, ...]
    retakes: dict[int, RetakeDecision]


class DryRunError(Exception):
    pass
