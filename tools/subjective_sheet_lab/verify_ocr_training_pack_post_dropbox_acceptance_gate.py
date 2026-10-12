# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_post_dropbox_acceptance_gate.py

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
from verify_ocr_training_pack_dropbox_ready_simulation import REPORT_JSON as DROPBOX_SIMULATION_JSON
from verify_ocr_training_pack_post_dropbox_intake_replay import REPORT_JSON as POST_DROPBOX_JSON

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_post_dropbox_acceptance_gate.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_post_dropbox_acceptance_gate.md"


def main() -> int:
    output = acceptance_summary(read_json_object(DROPBOX_SIMULATION_JSON), read_json_object(POST_DROPBOX_JSON))
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def acceptance_summary(dropbox: JsonObject, post_dropbox: JsonObject) -> JsonObject:
    require_text_value(dropbox.get("status"), "TRAINING_PACK_DROPBOX_READY_SIMULATION_READY", "dropbox.status")
    require_text_value(
        post_dropbox.get("status"),
        "TRAINING_PACK_POST_DROPBOX_INTAKE_REPLAY_READY_WAITING_FOR_EVIDENCE",
        "post_dropbox.status",
    )
    checks = acceptance_checks(dropbox, post_dropbox)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_POST_DROPBOX_ACCEPTANCE_GATE_READY",
        "acceptance_check_count": len(checks),
        "accepted_check_count": sum(1 for check in checks if check["passed"] is True),
        "rejected_check_count": sum(1 for check in checks if check["passed"] is not True),
        "current_real_evidence_file_count": post_dropbox.get("actual_evidence_file_count"),
        "current_real_dropbox_ready": dropbox.get("current_real_dropbox_ready"),
        "simulated_full_dropbox_ready": dropbox.get("simulated_full_dropbox_ready"),
        "simulated_full_copy_evidence_ready": dropbox.get("simulated_full_copy_evidence_ready"),
        "simulated_intake_preconditions_ready": post_dropbox.get("simulated_promotion_preconditions_ready"),
        "safe_auto_grade_evidence_rejected_count": post_dropbox.get("safe_auto_grade_status_probe_rejected_count"),
        "promotion_allowed_without_user_approval": post_dropbox.get("promotion_allowed_without_user_approval"),
        "replacement_payload_write_attempted": post_dropbox.get("replacement_payload_write_attempted"),
        "acceptance_ready_now": False,
        "acceptance_ready_after_required_files": True,
        "checks": list(checks),
        "next_status": "USER_APPROVAL_REQUIRED",
        "next_safe_action": "collect_four_target_named_payload_files_with_user_approval",
        "required_next_artifact": "four_target_named_payload_files",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def acceptance_checks(dropbox: JsonObject, post_dropbox: JsonObject) -> tuple[JsonObject, ...]:
    return (
        check("current_dropbox_blocked_until_files_arrive", dropbox.get("current_real_dropbox_ready") is False),
        check("simulated_dropbox_ready_with_all_required_files", dropbox.get("simulated_full_dropbox_ready") is True),
        check("simulated_copy_checklist_ready_with_all_required_files", dropbox.get("simulated_full_copy_evidence_ready") is True),
        check("post_dropbox_intake_preconditions_ready", post_dropbox.get("simulated_promotion_preconditions_ready") is True),
        check("safe_auto_grade_evidence_rejected_before_acceptance", post_dropbox.get("safe_auto_grade_status_probe_rejected_count") == 4),
        check("approval_still_required_before_promotion", post_dropbox.get("promotion_allowed_without_user_approval") is False),
        check("replacement_write_not_attempted", post_dropbox.get("replacement_payload_write_attempted") is False),
    )


def check(name: str, passed: bool) -> JsonObject:
    return {"name": name, "passed": passed}


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_POST_DROPBOX_ACCEPTANCE_GATE_READY", "status")
    for key, expected in integer_expectations():
        require_int_value(output.get(key), expected, key)
    for key, expected in bool_expectations():
        require_bool_value(output.get(key), expected, key)
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_text_value(
        output.get("next_safe_action"),
        "collect_four_target_named_payload_files_with_user_approval",
        "next_safe_action",
    )
    require_all_checks_passed(output.get("checks"))


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("acceptance_check_count", 7), ("accepted_check_count", 7), ("rejected_check_count", 0),
        ("current_real_evidence_file_count", 0), ("safe_auto_grade_evidence_rejected_count", 4), ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0), ("submit_test_call_count", 0), ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )


def bool_expectations() -> tuple[tuple[str, bool], ...]:
    return (
        ("current_real_dropbox_ready", False), ("simulated_full_dropbox_ready", True),
        ("simulated_full_copy_evidence_ready", True), ("simulated_intake_preconditions_ready", True),
        ("promotion_allowed_without_user_approval", False), ("replacement_payload_write_attempted", False),
        ("acceptance_ready_now", False), ("acceptance_ready_after_required_files", True),
    )


def require_all_checks_passed(value: JsonValue) -> None:
    match value:
        case list() as checks:
            for item in checks:
                require_check_passed(item)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("checks must be a list")
        case unreachable:
            assert_never(unreachable)


def require_check_passed(value: JsonValue) -> None:
    match value:
        case dict() as check_payload:
            require_bool_value(check_payload.get("passed"), True, "check.passed")
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError("check must be an object")
        case unreachable:
            assert_never(unreachable)


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Post-Dropbox Acceptance Gate", "",
        "- Gemini/API calls: 0; external OCR API calls: 0", "- submit route calls: 0", "- submit button clicks: 0",
        "- student-facing: false", "- production default: `NO-GO`", f"- status: `{output['status']}`",
        f"- current evidence files: {output['current_real_evidence_file_count']}",
        f"- safe-auto-grade evidence rejected: {output['safe_auto_grade_evidence_rejected_count']}",
        f"- acceptance ready now: {output['acceptance_ready_now']}",
        f"- acceptance ready after required files: {output['acceptance_ready_after_required_files']}",
        f"- checks passed: {output['accepted_check_count']} / {output['acceptance_check_count']}",
        f"- next status: `{output['next_status']}`", f"- next safe action: `{output['next_safe_action']}`",
        "- sensitive/path leak count: 0", "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
