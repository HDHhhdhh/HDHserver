from __future__ import annotations

from typing import Callable, TypeAlias, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    read_json_object,
    require_bool_value,
    require_int,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_evidence_arrival_smoke import REPORT_JSON as ARRIVAL_SMOKE_JSON
from verify_ocr_training_pack_evidence_arrival_smoke import main as verify_arrival_smoke

Verifier: TypeAlias = Callable[[], int]


def arrival_smoke_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (("training pack evidence arrival smoke", verify_arrival_smoke),)


def arrival_smoke_reports() -> dict[str, JsonObject]:
    return {"training_pack_evidence_arrival_smoke": read_json_object(ARRIVAL_SMOKE_JSON)}


def require_training_pack_evidence_arrival_smoke(report: JsonObject) -> None:
    require_text_value(report.get("status"), "TRAINING_PACK_EVIDENCE_ARRIVAL_SMOKE_READY", "arrival_smoke.status")
    require_text_value(report.get("scope"), "file_name_and_size_only", "arrival_smoke.scope")
    require_text_value(report.get("production_default"), "NO_GO", "arrival_smoke.production_default")
    require_bool_value(report.get("payload_parse_attempted"), False, "arrival_smoke.payload_parse_attempted")
    require_bool_value(report.get("ready_after_required_files"), True, "arrival_smoke.ready_after_required_files")
    require_int_value(report.get("required_file_count"), 4, "arrival_smoke.required_file_count")
    require_int_value(report.get("unexpected_file_count"), 0, "arrival_smoke.unexpected_file_count")
    require_int_value(report.get("zero_byte_file_count"), 0, "arrival_smoke.zero_byte_file_count")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(report.get(key), 0, f"arrival_smoke.{key}")
    require_int_value(
        report.get("answer_key_or_grading_field_leak_count"),
        0,
        "arrival_smoke.answer_key_or_grading_field_leak_count",
    )
    require_int_value(report.get("filesystem_path_leak_count"), 0, "arrival_smoke.filesystem_path_leak_count")
    require_matching_present_count(report)


def require_matching_present_count(report: JsonObject) -> None:
    present = require_int(report.get("present_file_count"), "arrival_smoke.present_file_count")
    matching = require_int(report.get("matching_file_count"), "arrival_smoke.matching_file_count")
    if matching != present:
        raise ExtendedGateError("arrival_smoke matching_file_count must equal present_file_count")


def arrival_smoke_summary_fields(report: JsonObject) -> JsonObject:
    return {
        "training_pack_evidence_arrival_smoke_status": "TRAINING_PACK_EVIDENCE_ARRIVAL_SMOKE_READY",
        "training_pack_evidence_arrival_smoke_scope": "file_name_and_size_only",
        "training_pack_evidence_arrival_smoke_payload_parse_attempted": False,
        "training_pack_evidence_arrival_smoke_present_file_count": int_field(report.get("present_file_count")),
        "training_pack_evidence_arrival_smoke_missing_file_count": int_field(report.get("missing_file_count")),
        "training_pack_evidence_arrival_smoke_zero_byte_file_count": int_field(report.get("zero_byte_file_count")),
        "training_pack_evidence_arrival_smoke_ready_now": bool_field(report.get("smoke_ready_now")),
        "training_pack_evidence_arrival_smoke_ready_after_required_files": True,
    }


def int_field(value: JsonValue) -> int:
    return require_int(value, "arrival_smoke.summary_int")


def bool_field(value: JsonValue) -> bool:
    match value:
        case bool():
            return value
        case None | int() | float() | str() | list() | dict():
            raise ExtendedGateError("arrival_smoke.summary_bool must be boolean")
        case unreachable:
            assert_never(unreachable)
