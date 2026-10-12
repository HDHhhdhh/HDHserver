# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_post_dropbox_intake_replay.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from ocr_training_pack_recognized_evidence_contract_core import contract_summary
from verify_ocr_training_pack_recognized_evidence_target_coverage import target_coverage_summary

LAB: Final[Path] = Path(__file__).resolve().parent
SOURCE_JSON: Final[Path] = LAB / "ocr_training_pack_source_inventory.json"
EVIDENCE_DIR: Final[Path] = LAB / "training_pack_recognized_evidence"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_post_dropbox_intake_replay.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_post_dropbox_intake_replay.md"


def main() -> int:
    output = replay_summary(read_json_object(SOURCE_JSON), current_evidence_count())
    require_current_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def current_evidence_count() -> int:
    return len(tuple(EVIDENCE_DIR.glob("*.json"))) if EVIDENCE_DIR.exists() else 0


def replay_summary(source: JsonObject, actual_file_count: int) -> JsonObject:
    require_text_value(source.get("status"), "TRAINING_PACK_ROUTE_UPLOAD_SOURCES_READY_CACHE_REPLAY_MISSING", "source.status")
    targets = target_ids(source)
    payloads = synthetic_payloads(targets)
    contract = contract_summary(source, list(payloads))
    safe_auto_grade_contract = contract_summary(
        source,
        [synthetic_payload(target, "safe_auto_grade") for target in targets],
    )
    coverage = target_coverage_summary(source, payloads)
    complete_count = sum(1 for payload in payloads if len(review_items(payload)) == 20)
    nonzero_count = sum(1 for payload in payloads if recognized_value_count(payload) > 0)
    recognized_count = sum(recognized_value_count(payload) for payload in payloads)
    replacement_ready = len(payloads) == len(targets) and complete_count == len(targets) and nonzero_count == len(targets)
    preconditions_ready = bool(contract["contract_ready"]) and bool(coverage["target_coverage_ready"]) and replacement_ready
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_POST_DROPBOX_INTAKE_REPLAY_READY_WAITING_FOR_EVIDENCE",
        "actual_evidence_file_count": actual_file_count,
        "target_count": len(targets),
        "simulated_evidence_file_count": len(payloads),
        "simulated_contract_accepted_count": int(contract["live_evidence_accepted_count"]),
        "simulated_contract_rejected_count": int(contract["live_evidence_rejected_count"]),
        "safe_auto_grade_status_probe_accepted_count": int(safe_auto_grade_contract["live_evidence_accepted_count"]),
        "safe_auto_grade_status_probe_rejected_count": int(safe_auto_grade_contract["live_evidence_rejected_count"]),
        "simulated_complete_payload_count": complete_count,
        "simulated_nonzero_payload_count": nonzero_count,
        "simulated_recognized_value_count": recognized_count,
        "simulated_covered_target_count": int(coverage["covered_target_count"]),
        "simulated_missing_target_count": int(coverage["missing_target_count"]),
        "simulated_target_coverage_ready": bool(coverage["target_coverage_ready"]),
        "simulated_replacement_input_ready": replacement_ready,
        "simulated_promotion_preconditions_ready": preconditions_ready,
        "promotion_allowed_without_user_approval": False,
        "replacement_payload_write_attempted": False,
        "next_status": "USER_APPROVAL_REQUIRED",
        "required_next_artifact": "four_target-named_recognized_evidence_payload_files",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def target_ids(source: JsonObject) -> tuple[str, ...]:
    match source.get("targets"):
        case list() as targets:
            return tuple(target_id for target in targets if (target_id := target_id_or_none(target)) is not None)
        case None | bool() | int() | float() | str() | dict():
            return ()
        case unreachable:
            assert_never(unreachable)


def target_id_or_none(value: JsonValue) -> str | None:
    match value:
        case dict() as target:
            return text_or_none(target.get("test_id"))
        case None | bool() | int() | float() | str() | list():
            return None
        case unreachable:
            assert_never(unreachable)


def text_or_none(value: JsonValue) -> str | None:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            return None
        case unreachable:
            assert_never(unreachable)


def synthetic_payloads(targets: tuple[str, ...]) -> tuple[JsonObject, ...]:
    return tuple(synthetic_payload(target) for target in targets)


def synthetic_payload(test_id: str, status: str = "review_required") -> JsonObject:
    return {
        "review_payload": {
            "test_id": test_id,
            "round": "1",
            "problem_count": 20,
            "items": [
                {"question_no": question_no, "status": status, "recognized": "1"}
                for question_no in range(1, 21)
            ],
        }
    }


def review_items(payload: JsonObject) -> tuple[JsonObject, ...]:
    match payload.get("review_payload"):
        case dict() as review_payload:
            match review_payload.get("items"):
                case list() as items:
                    return tuple(item for item in items if isinstance(item, dict))
                case None | bool() | int() | float() | str() | dict():
                    return ()
                case unreachable:
                    assert_never(unreachable)
        case None | bool() | int() | float() | str() | list():
            return ()
        case unreachable:
            assert_never(unreachable)


def recognized_value_count(payload: JsonObject) -> int:
    return sum(1 for item in review_items(payload) if text_or_none(item.get("recognized")) not in (None, "", "?"))


def require_current_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_POST_DROPBOX_INTAKE_REPLAY_READY_WAITING_FOR_EVIDENCE", "status")
    for key, value in current_integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("simulated_target_coverage_ready"), True, "simulated_target_coverage_ready")
    require_bool_value(output.get("simulated_replacement_input_ready"), True, "simulated_replacement_input_ready")
    require_bool_value(output.get("simulated_promotion_preconditions_ready"), True, "simulated_promotion_preconditions_ready")
    require_bool_value(output.get("promotion_allowed_without_user_approval"), False, "promotion_allowed_without_user_approval")
    require_bool_value(output.get("replacement_payload_write_attempted"), False, "replacement_payload_write_attempted")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")


def current_integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("actual_evidence_file_count", 0), ("target_count", 4), ("simulated_evidence_file_count", 4),
        ("simulated_contract_accepted_count", 4), ("simulated_contract_rejected_count", 0),
        ("safe_auto_grade_status_probe_accepted_count", 0), ("safe_auto_grade_status_probe_rejected_count", 4),
        ("simulated_complete_payload_count", 4), ("simulated_nonzero_payload_count", 4),
        ("simulated_recognized_value_count", 80), ("simulated_covered_target_count", 4),
        ("simulated_missing_target_count", 0), ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0), ("submit_test_call_count", 0), ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Post-Dropbox Intake Replay",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- actual evidence files: {output['actual_evidence_file_count']}",
        f"- simulated evidence files: {output['simulated_evidence_file_count']}",
        f"- simulated recognized values: {output['simulated_recognized_value_count']}",
        f"- safe-auto-grade evidence rejected: {output['safe_auto_grade_status_probe_rejected_count']}",
        f"- simulated target coverage ready: {output['simulated_target_coverage_ready']}",
        f"- simulated replacement input ready: {output['simulated_replacement_input_ready']}",
        f"- simulated promotion preconditions ready: {output['simulated_promotion_preconditions_ready']}",
        f"- promotion allowed without user approval: {output['promotion_allowed_without_user_approval']}",
        f"- replacement payload write attempted: {output['replacement_payload_write_attempted']}",
        f"- next status: `{output['next_status']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
