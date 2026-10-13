# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by verify_ocr_training_pack_recognized_evidence_contract.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    JsonValue,
    require_text_value,
)
from ocr_training_pack_recognized_evidence_contract_probes import synthetic_probe_payloads

FORBIDDEN_KEYS: Final[set[str]] = {
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
}
PATH_MARKERS: Final[tuple[str, ...]] = ("C:\\", "C:/", "/c/")
ALLOWED_STATUSES: Final[tuple[str, ...]] = (
    "review_required",
    "retake_required",
    "data_check_required",
)
BLOCKED_RECOGNIZED_ONLY_STATUS: Final[str] = "safe_auto_grade"


@dataclass(frozen=True, slots=True)
class ContractResult:
    accepted: bool
    reason: str


def contract_summary(source: JsonObject, payloads: list[JsonObject]) -> JsonObject:
    require_text_value(
        source.get("status"),
        "TRAINING_PACK_ROUTE_UPLOAD_SOURCES_READY_CACHE_REPLAY_MISSING",
        "source.status",
    )
    probes = [validate_payload(payload) for payload in synthetic_probe_payloads()]
    evidence_results = [validate_payload(payload) for payload in payloads]
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_READY_WAITING_FOR_PAYLOADS",
        "target_count": target_count(source),
        "evidence_file_count": len(payloads),
        "live_evidence_accepted_count": accepted_count(evidence_results),
        "live_evidence_rejected_count": rejected_count(evidence_results),
        "contract_probe_count": len(probes),
        "contract_probe_accepted_count": accepted_count(probes),
        "contract_probe_rejected_count": rejected_count(probes),
        "forbidden_field_probe_rejected_count": reason_count(probes, "sensitive_field"),
        "filesystem_path_probe_rejected_count": reason_count(probes, "filesystem_path"),
        "schema_probe_rejected_count": schema_reason_count(probes),
        "item_count_schema_probe_rejected_count": reason_count(probes, "schema_item_count"),
        "question_sequence_schema_probe_rejected_count": reason_count(probes, "schema_question_sequence"),
        "status_schema_probe_rejected_count": reason_count(probes, "schema_status"),
        "safe_auto_grade_status_probe_rejected_count": reason_count(probes, "schema_safe_auto_grade_status"),
        "recognized_answer_schema_probe_rejected_count": reason_count(probes, "schema_recognized_answer"),
        "blank_recognized_answer_probe_rejected_count": reason_count(probes, "schema_blank_recognized_answer"),
        "contract_ready": True,
        "next_status": "USER_APPROVAL_REQUIRED",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    output["answer_key_or_grading_field_leak_count"] = forbidden_key_count(scrub_leak_counter_keys(output))
    output["filesystem_path_leak_count"] = path_leak_count(output)
    return output


def target_count(source: JsonObject) -> int:
    targets = source.get("targets")
    if not isinstance(targets, list):
        return 0
    return len(targets)


def validate_payload(payload: JsonObject) -> ContractResult:
    if forbidden_key_count(payload) > 0:
        return ContractResult(accepted=False, reason="sensitive_field")
    if path_leak_count(payload) > 0:
        return ContractResult(accepted=False, reason="filesystem_path")
    items = review_items(payload)
    if len(items) != 20:
        return ContractResult(accepted=False, reason="schema_item_count")
    question_numbers = [question_no(item) for item in items]
    if sorted(question_numbers) != list(range(1, 21)):
        return ContractResult(accepted=False, reason="schema_question_sequence")
    for item in items:
        schema_reason = item_schema_reason(item)
        if schema_reason is not None:
            return ContractResult(accepted=False, reason=schema_reason)
    return ContractResult(accepted=True, reason="ok")


def item_schema_reason(item: JsonObject) -> str | None:
    if item.get("status") == BLOCKED_RECOGNIZED_ONLY_STATUS:
        return "schema_safe_auto_grade_status"
    if not status_valid(item.get("status")):
        return "schema_status"
    return recognized_answer_schema_reason(item)


def status_valid(value: JsonValue) -> bool:
    return isinstance(value, str) and value in ALLOWED_STATUSES


def recognized_answer_schema_reason(item: JsonObject) -> str | None:
    if "recognized" in item:
        return recognized_value_reason(item.get("recognized"))
    if "recognized_answer" in item:
        return recognized_value_reason(item.get("recognized_answer"))
    return "schema_recognized_answer"


def recognized_value_reason(value: JsonValue) -> str | None:
    if not isinstance(value, str):
        return "schema_recognized_answer"
    if value.strip() in {"", "?"}:
        return "schema_blank_recognized_answer"
    return None


def review_items(payload: JsonObject) -> list[JsonObject]:
    value = payload.get("review_payload")
    items = value.get("items") if isinstance(value, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def question_no(item: JsonObject) -> int:
    value = item.get("question_no")
    if not isinstance(value, int) or isinstance(value, bool):
        return -1
    return value


def accepted_count(results: list[ContractResult]) -> int:
    return sum(1 for result in results if result.accepted)


def rejected_count(results: list[ContractResult]) -> int:
    return sum(1 for result in results if not result.accepted)


def reason_count(results: list[ContractResult], reason: str) -> int:
    return sum(1 for result in results if result.reason == reason)


def schema_reason_count(results: list[ContractResult]) -> int:
    return sum(1 for result in results if result.reason.startswith("schema_"))


def forbidden_key_count(value: JsonValue) -> int:
    match value:
        case dict():
            return sum((1 if key in FORBIDDEN_KEYS else 0) + forbidden_key_count(child) for key, child in value.items())
        case list():
            return sum(forbidden_key_count(child) for child in value)
        case None | bool() | int() | float() | str():
            return 0
        case unreachable:
            assert_never(unreachable)


def path_leak_count(value: JsonValue) -> int:
    match value:
        case str():
            return sum(value.count(marker) for marker in PATH_MARKERS)
        case dict():
            return sum(path_leak_count(child) for child in value.values())
        case list():
            return sum(path_leak_count(child) for child in value)
        case None | bool() | int() | float():
            return 0
        case unreachable:
            assert_never(unreachable)


def scrub_leak_counter_keys(output: JsonObject) -> JsonObject:
    return {key: value for key, value in output.items() if not key.endswith("_leak_count")}
