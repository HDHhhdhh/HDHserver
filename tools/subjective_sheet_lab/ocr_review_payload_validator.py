from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import sys
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from typing import Final, assert_never

from tools.subjective_sheet_lab.ocr_review_schema import (
    DEFAULT_PROBLEM_COUNT,
    EXACT_SOURCE_BY_STATUS,
    FINAL_STATUSES,
    JsonObject,
    JsonValue,
    PayloadMode,
    RETAKE_FINAL_STATUSES,
    UNRESOLVED_STATUSES,
    AnswerSource,
    ReviewStatus,
    find_forbidden_answer_key_paths,
)
from tools.subjective_sheet_lab.ocr_erased_overwritten_policy import blocks_auto_grade_for_safety

ROOT: Final = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class ContractError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ItemState:
    status: ReviewStatus
    source: AnswerSource | None
    final_answer: str | None
    item: JsonObject
    label: str


def read_json(path: Path) -> JsonValue:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise ContractError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise ContractError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_string(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ContractError(f"{label} must be a string")
        case unreachable:
            assert_never(unreachable)


def optional_string(value: JsonValue, label: str) -> str | None:
    match value:
        case None:
            return None
        case str():
            return value
        case bool() | int() | float() | list() | dict():
            raise ContractError(f"{label} must be a string or null")
        case unreachable:
            assert_never(unreachable)


def require_positive_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            parsed = value
        case None | bool() | float() | str() | list() | dict():
            raise ContractError(f"{label} must be a positive integer")
        case unreachable:
            assert_never(unreachable)
    if parsed <= 0:
        raise ContractError(f"{label} must be positive")
    return parsed


def validate_payload(payload: JsonObject, mode: PayloadMode, label: str) -> str | None:
    validate_versioned_identity(payload)
    leaks = find_forbidden_answer_key_paths(payload)
    if leaks:
        raise ContractError(f"{label} leaks answer-key fields: {', '.join(leaks)}")
    require_string(payload.get("test_id"), f"{label}.test_id")
    require_string(payload.get("round"), f"{label}.round")
    problem_count = require_problem_count(payload, label)
    by_question: dict[int, str] = {}
    for index, item_value in enumerate(require_array(payload.get("items"), f"{label}.items"), start=1):
        item = require_object(item_value, f"{label}.items[{index}]")
        question_no = require_positive_int(item.get("question_no"), f"{label}.items[{index}].question_no")
        if question_no > problem_count:
            raise ContractError(f"{label} question {question_no} is outside 1..{problem_count}")
        if question_no in by_question:
            raise ContractError(f"{label} question {question_no} is duplicated")
        by_question[question_no] = validate_item(item, mode, f"{label}.items[{index}]") or ""
    missing = [str(no) for no in range(1, problem_count + 1) if no not in by_question]
    if missing:
        raise ContractError(f"{label} missing questions: {', '.join(missing)}")
    match mode:
        case PayloadMode.REVIEW:
            return None
        case PayloadMode.FINAL:
            return "\n".join(by_question[no] for no in range(1, problem_count + 1))
        case unreachable:
            assert_never(unreachable)


def validate_item(item: JsonObject, mode: PayloadMode, label: str) -> str | None:
    require_string(item.get("recognized"), f"{label}.recognized")
    warnings = require_string_array(item.get("warnings"), f"{label}.warnings")
    candidates = require_string_array(item.get("candidates"), f"{label}.candidates")
    if len(candidates) > 5 or len(set(candidates)) != len(candidates):
        raise ContractError(f"{label}.candidates must contain at most five distinct values")
    status = parse_status(item.get("status"), f"{label}.status")
    source = parse_source(item.get("source"), f"{label}.source")
    final_answer = optional_string(item.get("final_answer"), f"{label}.final_answer")
    validate_status_source(ItemState(status, source, final_answer, item, label))
    if blocks_auto_grade_for_safety(status.value, warnings):
        raise ContractError(f"{label} safe_auto_grade is blocked by erased/overwritten warning")
    match mode:
        case PayloadMode.REVIEW:
            return final_answer
        case PayloadMode.FINAL:
            if status not in FINAL_STATUSES:
                raise ContractError(f"{label} has unresolved status {status.value}")
            if final_answer is None or not final_answer.strip() or "?" in final_answer:
                raise ContractError(f"{label}.final_answer is required for final payload")
            if "\n" in final_answer or "\r" in final_answer:
                raise ContractError(f"{label}.final_answer must be a single line")
            return final_answer
        case unreachable:
            assert_never(unreachable)


def validate_all(root: Path = ROOT) -> None:
    review = require_object(read_json(root / "subjective_review_dry_run_review_payload.json"), "review_payload")
    validate_payload(review, PayloadMode.REVIEW, "subjective_review_dry_run_review_payload")
    final_payload = require_object(read_json(root / "subjective_review_dry_run_final_payload.json"), "final_payload")
    answers_text = validate_payload(final_payload, PayloadMode.FINAL, "subjective_review_dry_run_final_payload")
    expected = (root / "subjective_review_dry_run_answersText.txt").read_text(encoding="utf-8-sig").rstrip("\n")
    if answers_text != expected:
        raise ContractError("subjective_review_dry_run_answersText.txt does not match final payload")
    phase1 = require_object(read_json(root / "phase1_internal_contract_review_payload.json"), "phase1")
    validate_payload(require_object(phase1.get("review_payload"), "phase1.review_payload"), PayloadMode.REVIEW, "phase1.review_payload")
    validate_bridge_fixture(root)


def parse_status(value: JsonValue, label: str) -> ReviewStatus:
    raw = require_string(value, label)
    try:
        return ReviewStatus(raw)
    except ValueError as exc:
        raise ContractError(f"{label} has unknown status {raw}") from exc


def parse_source(value: JsonValue, label: str) -> AnswerSource | None:
    raw = optional_string(value, label)
    if raw is None:
        return None
    try:
        return AnswerSource(raw)
    except ValueError as exc:
        raise ContractError(f"{label} has unknown source {raw}") from exc


def require_string_array(value: JsonValue, label: str) -> list[str]:
    values = [] if value is None else require_array(value, label)
    strings: list[str] = []
    for index, item in enumerate(values, start=1):
        text = require_string(item, f"{label}[{index}]")
        if "\n" in text or "\r" in text:
            raise ContractError(f"{label}[{index}] must be a single line")
        strings.append(text)
    return strings


def require_problem_count(payload: JsonObject, label: str) -> int:
    problem_count = require_positive_int(payload.get("problem_count", DEFAULT_PROBLEM_COUNT), f"{label}.problem_count")
    if problem_count != DEFAULT_PROBLEM_COUNT:
        raise ContractError(f"{label}.problem_count must be {DEFAULT_PROBLEM_COUNT}")
    return problem_count


def validate_status_source(state: ItemState) -> None:
    if state.status in UNRESOLVED_STATUSES:
        if state.source is not None or state.final_answer is not None:
            raise ContractError(f"{state.label} unresolved items require null source and final_answer")
        return
    if state.status is ReviewStatus.CONFIRMED:
        if state.source is None or state.source is AnswerSource.RETAKE_UPLOADED:
            raise ContractError(f"{state.label}.source must be a final answer source")
        return
    expected = EXACT_SOURCE_BY_STATUS[state.status]
    if state.source is not expected:
        raise ContractError(f"{state.label}.source must be {expected.value}")
    if state.status is ReviewStatus.RETAKE_UPLOADED and state.final_answer is not None:
        raise ContractError(f"{state.label}.final_answer must be null while retake_uploaded")
    if state.status in RETAKE_FINAL_STATUSES and state.item.get("retake_image_attached") is not True:
        raise ContractError(f"{state.label}.retake_image_attached must be true")


def validate_bridge_fixture(root: Path) -> None:
    raw = require_object(read_json(root / "final_review_payload_bridge_fixture.json"), "bridge_fixture")
    payload = require_object(raw.get("valid_payload"), "bridge_fixture.valid_payload")
    answers_text = validate_payload(payload, PayloadMode.FINAL, "bridge_fixture.valid_payload")
    expected = require_string(raw.get("golden_answers_text"), "bridge_fixture.golden_answers_text")
    if answers_text != expected:
        raise ContractError("bridge fixture answersText does not match golden_answers_text")


def validate_versioned_identity(payload: JsonObject) -> None:
    if payload.get("schema") is None:
        return  # Historical pure fixtures remain supported; they cannot enter the versioned UI/cache.
    from tools.subjective_sheet_lab.ocr_run_identity import REVIEW_SCHEMA, validate_run_identity
    if payload.get("schema") != REVIEW_SCHEMA:
        raise ContractError("unsupported review run schema")
    try:
        identity = validate_run_identity(payload.get("identity"))
    except ValueError as exc:
        raise ContractError(str(exc)) from exc
    if payload.get("test_id") != identity["test_id"] or payload.get("round") != identity["round"]:
        raise ContractError("review identity mismatch")
    if payload.get("demo") is True:
        raise ContractError("demo cannot satisfy completion")
    allowed_top = {"schema","identity","test_id","round","problem_count","items","photo_preview","source","demo"}
    allowed_item = {"question_no","status","recognized","candidates","warnings","final_answer","source",
                    "review_history","identity_sha256","crop_preview","crop_sha256","uncertainty",
                    "needs_review","retake_image_attached"}
    from tools.subjective_sheet_lab.ocr_payload_leak_policy import path_exposures
    if set(payload)-allowed_top or path_exposures(payload):
        raise ContractError("unknown field or local path in review run")
    for item in require_array(payload.get("items"), "items"):
        if isinstance(item,dict) and set(item)-allowed_item:
            raise ContractError("unknown field in review item")
        if isinstance(item,dict) and item.get("status") in {"safe_auto_grade","safe_auto_grade_after_retake"}:
            if item.get("needs_review") is not False or item.get("uncertainty") not in {"none","clear"} or item.get("warnings"):
                raise ContractError("uncertain items cannot be safe_auto_grade")
        if not isinstance(item,dict) or item.get("identity_sha256") != identity["identity_sha256"]:
            raise ContractError("item belongs to a different run")
