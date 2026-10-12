# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_user_action_required_inventory.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import JsonObject, JsonValue, read_json_object
from ocr_user_action_required_inventory_output import markdown

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_user_action_required_inventory.json"
REPORT_MD: Final[Path] = LAB / "ocr_user_action_required_inventory.md"
ALLOWED_USER_REQUIRED_STATUSES: Final[tuple[str, ...]] = (
    "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED",
    "OCR_QA_START_HERE_READY_WITH_USER_ACTION_REQUIRED",
    "OCR_USER_ACTION_REQUIRED_INVENTORY_GUARD_VERIFIED",
    "TRAINING_PACK_EVIDENCE_ACCEPTANCE_BUNDLE_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_EVIDENCE_ARRIVAL_READINESS_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_EVIDENCE_DROPBOX_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_EVIDENCE_PROMOTION_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_INTAKE_ONLY_NO_PROMOTION_USER_ACTION_REQUIRED",
    "TRAINING_PACK_OPERATOR_COPY_CHECKLIST_USER_ACTION_REQUIRED",
    "TRAINING_PACK_OPERATOR_EVIDENCE_MANIFEST_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_OPERATOR_HANDOFF_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_POST_ARRIVAL_ACCEPTANCE_SUMMARY_USER_ACTION_REQUIRED",
    "TRAINING_PACK_POST_ARRIVAL_COMMAND_BUNDLE_USER_ACTION_REQUIRED",
    "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_SEQUENCE_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_POST_DROPBOX_REAL_FILE_REPLAY_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_PROMOTION_PREVIEW_DIFF_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_PROMOTION_PREVIEW_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_RECOGNIZED_EVIDENCE_EXAMPLE_SHAPE_READY_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_RECOGNIZED_EVIDENCE_FILENAME_DIAGNOSTICS_USER_ACTION_REQUIRED",
    "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_COVERAGE_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_DIFF_USER_APPROVAL_REQUIRED",
    "TRAINING_PACK_RECOGNIZED_EVIDENCE_USER_APPROVAL_REQUIRED",
    "USER_APPROVAL_REQUIRED",
)
SAFETY_COUNT_FIELDS: Final[tuple[str, ...]] = (
    "provider_call_count",
    "external_ocr_api_call_count",
    "submit_test_call_count",
    "ts_submit_click_count",
    "answer_key_or_grading_field_leak_count",
    "filesystem_path_leak_count",
)
VOLATILE_AGGREGATE_REPORTS: Final[tuple[str, ...]] = (
    "ocr_count_consistency_path_rendered_guard.json",
    "ocr_extended_gate_count_consistency.json",
    "ocr_extended_gate_count_consistency_guard.json",
    "ocr_preflight_operator_runbook_consistency.json",
    "ocr_preflight_operator_runbook_consistency_guard.json",
    "ocr_preflight_operator_runbook_rendered_summary.json",
    "ocr_preflight_operator_runbook_rendered_summary_guard.json",
    "ocr_preflight_environment_matrix.json",
    "ocr_preflight_failure_classifier.json",
    "ocr_preflight_report_freshness.json",
    "ocr_provider_free_final_handoff_chain.json",
    "ocr_provider_free_gate_chain.json",
    "ocr_provider_free_handoff_status_card.json",
)


@dataclass(frozen=True, slots=True)
class InventoryRow:
    file_name: str
    ok: bool
    status: str
    current_blocker: str


def main() -> int:
    rows, issues = inventory_rows()
    output = report(rows, issues)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] is True else 1


def inventory_rows() -> tuple[tuple[InventoryRow, ...], tuple[str, ...]]:
    rows: list[InventoryRow] = []
    issues: list[str] = []
    for path in sorted(LAB.glob("*.json")):
        if path.name == REPORT_JSON.name:
            continue
        payload = read_json_object(path)
        inspect_payload(path.name, payload, rows, issues)
    return tuple(rows), tuple(issues)


def inspect_payload(file_name: str, payload: JsonObject, rows: list[InventoryRow], issues: list[str]) -> None:
    ok_value = payload.get("ok")
    status = text_or_empty(payload.get("status"))
    current_blocker = text_or_empty(payload.get("current_blocker"))
    requires_user = status_requires_user(status)
    if ok_value is False and file_name not in VOLATILE_AGGREGATE_REPORTS:
        issues.append(f"{file_name}: ok=false")
    if requires_user:
        rows.append(InventoryRow(file_name=file_name, ok=ok_value is True, status=status, current_blocker=current_blocker))
        if status not in ALLOWED_USER_REQUIRED_STATUSES:
            issues.append(f"{file_name}: unexpected user-required status {status}")
    if requires_user or ok_value is False:
        inspect_safety_counts(file_name, payload, issues)
        inspect_student_and_production_flags(file_name, payload, issues)


def status_requires_user(status: str) -> bool:
    return "USER_APPROVAL_REQUIRED" in status or "USER_ACTION_REQUIRED" in status


def inspect_safety_counts(file_name: str, payload: JsonObject, issues: list[str]) -> None:
    for field in SAFETY_COUNT_FIELDS:
        value = payload.get(field)
        if value is None:
            continue
        match value:
            case int() if not isinstance(value, bool) and value == 0:
                continue
            case int() if not isinstance(value, bool):
                issues.append(f"{file_name}: {field}={value}")
            case None | bool() | float() | str() | list() | dict():
                issues.append(f"{file_name}: {field} is not integer zero")
            case unreachable:
                assert_never(unreachable)


def inspect_student_and_production_flags(file_name: str, payload: JsonObject, issues: list[str]) -> None:
    student_facing = payload.get("student_facing")
    if student_facing is True:
        issues.append(f"{file_name}: student_facing=true")
    production_default = payload.get("production_default")
    if production_default is not None and production_default != "NO_GO":
        issues.append(f"{file_name}: production_default={production_default}")


def text_or_empty(value: JsonValue) -> str:
    match value:
        case str() as text:
            return text
        case None | bool() | int() | float() | list() | dict():
            return ""
        case unreachable:
            assert_never(unreachable)


def report(rows: tuple[InventoryRow, ...], issues: tuple[str, ...]) -> JsonObject:
    return {
        "ok": not issues,
        "student_facing": False,
        "status": "OCR_USER_ACTION_REQUIRED_INVENTORY_VERIFIED" if not issues else "OCR_USER_ACTION_REQUIRED_INVENTORY_FAILED",
        "allowed_status_count": len(ALLOWED_USER_REQUIRED_STATUSES),
        "user_required_report_count": len(rows),
        "unexpected_issue_count": len(issues),
        "unexpected_issues": list(issues),
        "reports": [row_fields(row) for row in rows],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(not issues),
    }


def row_fields(row: InventoryRow) -> JsonObject:
    return {
        "file_name": row.file_name,
        "ok": row.ok,
        "status": row.status,
        "current_blocker": row.current_blocker,
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this inventory green while user-action-required OCR reports remain approval gated."
    return "Inspect unexpected OCR user-action report statuses before continuing OCR QA handoff."


if __name__ == "__main__":
    raise SystemExit(main())
