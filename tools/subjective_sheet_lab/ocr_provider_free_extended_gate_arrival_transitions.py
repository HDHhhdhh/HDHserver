from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_evidence_arrival_status_transitions import REPORT_JSON as ARRIVAL_TRANSITIONS_JSON
from verify_ocr_training_pack_evidence_arrival_status_transitions import main as verify_arrival_transitions

Verifier: TypeAlias = Callable[[], int]


def arrival_transition_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (("training pack evidence arrival status transitions", verify_arrival_transitions),)


def arrival_transition_reports() -> dict[str, JsonObject]:
    return {"training_pack_arrival_status_transitions": read_json_object(ARRIVAL_TRANSITIONS_JSON)}


def require_training_pack_arrival_status_transitions(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_EVIDENCE_ARRIVAL_STATUS_TRANSITIONS_READY",
        "arrival_transitions.status",
    )
    require_text_value(report.get("current_stage"), "before_required_files", "arrival_transitions.current_stage")
    require_text_value(
        report.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "arrival_transitions.current_blocker",
    )
    require_text_value(
        report.get("stops_before"),
        "promotion_replacement_accuracy_recompute_or_runtime_write",
        "arrival_transitions.stops_before",
    )
    require_int_value(report.get("transition_count"), 4, "arrival_transitions.transition_count")
    require_bool_value(report.get("current_ready"), False, "arrival_transitions.current_ready")
    require_bool_value(report.get("ready_after_required_files"), True, "arrival_transitions.ready_after_required_files")
    for key in (
        "payload_parse_before_smoke_allowed",
        "promotion_write_allowed",
        "replacement_write_allowed",
        "accuracy_recompute_allowed",
        "runtime_write_allowed",
    ):
        require_bool_value(report.get(key), False, f"arrival_transitions.{key}")


def arrival_transition_summary_fields() -> JsonObject:
    return {
        "training_pack_arrival_status_transitions_status": "TRAINING_PACK_EVIDENCE_ARRIVAL_STATUS_TRANSITIONS_READY",
        "training_pack_arrival_status_transitions_count": 4,
        "training_pack_arrival_status_transitions_current_stage": "before_required_files",
        "training_pack_arrival_status_transitions_ready_now": False,
        "training_pack_arrival_status_transitions_ready_after_required_files": True,
        "training_pack_arrival_status_transitions_writes_allowed": False,
    }
