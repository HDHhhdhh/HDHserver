from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_post_arrival_acceptance_summary import REPORT_JSON as POST_ARRIVAL_ACCEPTANCE_JSON
from verify_ocr_training_pack_post_arrival_acceptance_summary import main as verify_post_arrival_acceptance

Verifier: TypeAlias = Callable[[], int]


def post_arrival_acceptance_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (("training pack post-arrival acceptance summary", verify_post_arrival_acceptance),)


def post_arrival_acceptance_reports() -> dict[str, JsonObject]:
    return {"training_pack_post_arrival_acceptance_summary": read_json_object(POST_ARRIVAL_ACCEPTANCE_JSON)}


def require_training_pack_post_arrival_acceptance_summary(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_ACCEPTANCE_SUMMARY_USER_ACTION_REQUIRED",
        "post_arrival_acceptance.status",
    )
    require_text_value(
        report.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "post_arrival_acceptance.current_blocker",
    )
    for key, value in acceptance_counts():
        require_int_value(report.get(key), value, f"post_arrival_acceptance.{key}")
    require_bool_value(report.get("acceptance_ready_now"), False, "post_arrival_acceptance.acceptance_ready_now")
    require_bool_value(
        report.get("acceptance_ready_after_required_files"),
        True,
        "post_arrival_acceptance.acceptance_ready_after_files",
    )
    require_bool_value(
        report.get("contract_payload_parse_allowed_now"),
        False,
        "post_arrival_acceptance.contract_payload_parse_allowed_now",
    )


def acceptance_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("missing_file_count", 4),
        ("accepted_file_count", 0),
        ("rejected_file_count", 0),
        ("pending_file_count", 4),
        ("required_review_item_count_per_payload", 20),
    )


def post_arrival_acceptance_summary_fields() -> JsonObject:
    return {
        "training_pack_post_arrival_acceptance_status": "TRAINING_PACK_POST_ARRIVAL_ACCEPTANCE_SUMMARY_USER_ACTION_REQUIRED",
        "training_pack_post_arrival_acceptance_ready_now": False,
        "training_pack_post_arrival_acceptance_ready_after_files": True,
        "training_pack_post_arrival_acceptance_required_file_count": 4,
        "training_pack_post_arrival_acceptance_present_file_count": 0,
        "training_pack_post_arrival_acceptance_missing_file_count": 4,
        "training_pack_post_arrival_acceptance_pending_file_count": 4,
        "training_pack_post_arrival_acceptance_accepted_file_count": 0,
        "training_pack_post_arrival_acceptance_rejected_file_count": 0,
        "training_pack_post_arrival_acceptance_item_count_per_payload": 20,
    }
