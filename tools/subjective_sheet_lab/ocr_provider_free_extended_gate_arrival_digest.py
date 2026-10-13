from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_arrival_smoke_operator_digest import REPORT_JSON as ARRIVAL_DIGEST_JSON
from verify_ocr_training_pack_arrival_smoke_operator_digest import main as verify_arrival_digest

Verifier: TypeAlias = Callable[[], int]


def arrival_digest_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (("training pack arrival smoke operator digest", verify_arrival_digest),)


def arrival_digest_reports() -> dict[str, JsonObject]:
    return {"training_pack_arrival_smoke_operator_digest": read_json_object(ARRIVAL_DIGEST_JSON)}


def require_training_pack_arrival_smoke_operator_digest(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_ARRIVAL_SMOKE_OPERATOR_DIGEST_READY",
        "arrival_digest.status",
    )
    require_text_value(
        report.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "arrival_digest.current_blocker",
    )
    require_text_value(report.get("smoke_scope"), "file_name_and_size_only", "arrival_digest.scope")
    require_text_value(
        report.get("next_safe_stage"),
        "blank_rejection_then_contract_validate_then_target_coverage_then_intake_replay",
        "arrival_digest.next_safe_stage",
    )
    for key, value in arrival_digest_counts():
        require_int_value(report.get(key), value, f"arrival_digest.{key}")
    for key, value in arrival_digest_booleans():
        require_bool_value(report.get(key), value, f"arrival_digest.{key}")


def arrival_digest_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("matching_file_count", 0),
        ("missing_file_count", 4),
        ("unexpected_file_count", 0),
        ("zero_byte_file_count", 0),
        ("positive_size_file_count", 0),
    )


def arrival_digest_booleans() -> tuple[tuple[str, bool], ...]:
    return (
        ("payload_parse_attempted", False),
        ("smoke_ready_now", False),
        ("ready_after_required_files", True),
        ("provider_call_required", False),
        ("write_allowed", False),
    )


def arrival_digest_summary_fields() -> JsonObject:
    return {
        "training_pack_arrival_smoke_digest_status": "TRAINING_PACK_ARRIVAL_SMOKE_OPERATOR_DIGEST_READY",
        "training_pack_arrival_smoke_digest_required_file_count": 4,
        "training_pack_arrival_smoke_digest_present_file_count": 0,
        "training_pack_arrival_smoke_digest_missing_file_count": 4,
        "training_pack_arrival_smoke_digest_payload_parse_attempted": False,
        "training_pack_arrival_smoke_digest_ready_now": False,
        "training_pack_arrival_smoke_digest_ready_after_files": True,
        "training_pack_arrival_smoke_digest_provider_call_required": False,
        "training_pack_arrival_smoke_digest_write_allowed": False,
    }
