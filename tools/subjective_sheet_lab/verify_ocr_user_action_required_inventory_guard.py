# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_user_action_required_inventory_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import JsonObject, read_json_object, require_object
from ocr_user_action_required_inventory_guard_output import GuardReport, markdown
from ocr_user_action_required_inventory_guard_probes import guard_probes
from ocr_user_action_required_inventory_guard_policy import (
    required_approval_rows_present,
    required_blocker_rows_present,
)
from verify_ocr_user_action_required_inventory import (
    REPORT_JSON as INVENTORY_JSON,
    main as verify_inventory,
)

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_user_action_required_inventory_guard.json"
REPORT_MD: Final[Path] = LAB / "ocr_user_action_required_inventory_guard.md"


def main() -> int:
    verify_inventory()
    report = build_report()
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report() -> GuardReport:
    live_payload = live_inventory_payload()
    live_inventory_ok = live_inventory_is_ok(live_payload)
    required_approval_reports_present = required_approval_reports_present_in(live_payload)
    required_blocker_reports_present = required_blocker_reports_present_in(live_payload)
    probes = guard_probes()
    failed_probe_count = sum(1 for probe in probes if not probe.passed)
    live_failed_count = 0 if live_inventory_ok else 1
    approval_failed_count = 0 if required_approval_reports_present else 1
    blocker_failed_count = 0 if required_blocker_reports_present else 1
    ok = (
        live_inventory_ok
        and required_approval_reports_present
        and required_blocker_reports_present
        and failed_probe_count == 0
    )
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_USER_ACTION_REQUIRED_INVENTORY_GUARD_VERIFIED"
        if ok
        else "OCR_USER_ACTION_REQUIRED_INVENTORY_GUARD_FAILED",
        "probe_count": len(probes) + 3,
        "failed_probe_count": failed_probe_count + live_failed_count + approval_failed_count + blocker_failed_count,
        "live_inventory_ok": live_inventory_ok,
        "volatile_aggregate_failure_ignored": probes[0].passed and probes[1].passed and probes[2].passed,
        "nonvolatile_failure_blocked": probes[3].passed,
        "unexpected_user_action_status_blocked": probes[4].passed,
        "nonzero_provider_count_blocked": probes[5].passed,
        "student_facing_user_action_blocked": probes[6].passed,
        "allowed_user_action_status_accepted": probes[7].passed,
        "required_approval_reports_present": required_approval_reports_present,
        "missing_required_approval_report_blocked": probes[8].passed,
        "required_approval_status_mismatch_blocked": probes[9].passed,
        "required_blocker_reports_present": required_blocker_reports_present,
        "missing_required_blocker_report_blocked": probes[10].passed,
        "required_blocker_status_mismatch_blocked": probes[11].passed,
        "required_blocker_value_mismatch_blocked": probes[12].passed,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def live_inventory_payload() -> JsonObject:
    return read_json_object(INVENTORY_JSON)


def live_inventory_is_ok(payload: JsonObject) -> bool:
    return payload.get("ok") is True


def required_approval_reports_present_in(payload: JsonObject) -> bool:
    return required_approval_rows_present(inventory_report_rows(payload))


def required_blocker_reports_present_in(payload: JsonObject) -> bool:
    return required_blocker_rows_present(inventory_report_rows(payload))


def inventory_report_rows(payload: JsonObject) -> tuple[JsonObject, ...]:
    rows = payload.get("reports")
    match rows:
        case list():
            return tuple(require_object(row, f"inventory.reports[{index}]") for index, row in enumerate(rows, start=1))
        case None | bool() | int() | float() | str() | dict():
            return ()
        case unreachable:
            assert_never(unreachable)


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this guard with the user-action inventory extended gate step."
    return "Fix user-action inventory probe handling before trusting approval-gated report inventory."


if __name__ == "__main__":
    raise SystemExit(main())
