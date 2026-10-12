# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_report_field_access_inventory_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import JsonObject, read_json_object
from verify_ocr_report_field_access_inventory import HelperRow
from verify_ocr_report_field_access_inventory import REPORT_JSON as INVENTORY_JSON
from verify_ocr_report_field_access_inventory import main as verify_inventory
from verify_ocr_report_field_access_inventory import report as inventory_report

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_report_field_access_inventory_guard.json"
REPORT_MD: Final[Path] = LAB / "ocr_report_field_access_inventory_guard.md"


class GuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_inventory_probe_passed: bool
    default_reader_candidate_probe_blocked: bool
    parse_error_probe_blocked: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    live_exit_code = verify_inventory()
    live = read_json_object(INVENTORY_JSON)
    default_candidate = default_reader_candidate_report()
    parse_error = inventory_report((), ("synthetic.py: invalid syntax",))
    output = guard_report(live_exit_code, live, default_candidate, parse_error)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] else 1


def default_reader_candidate_report() -> JsonObject:
    rows = (
        HelperRow(
            file_name="synthetic_default_reader.py",
            helper_name="int_field",
            line_no=1,
            parameter_count=2,
            classification="default_reader_candidate",
        ),
    )
    return inventory_report(rows, ())


def guard_report(
    live_exit_code: int,
    live: JsonObject,
    default_candidate: JsonObject,
    parse_error: JsonObject,
) -> GuardReport:
    live_passed = live_exit_code == 0 and live.get("ok") is True
    default_candidate_blocked = (
        default_candidate.get("ok") is False
        and default_candidate.get("default_reader_candidate_count") == 1
    )
    parse_error_blocked = parse_error.get("ok") is False and parse_error.get("parse_error_count") == 1
    failed_probe_count = sum(1 for passed in (live_passed, default_candidate_blocked, parse_error_blocked) if not passed)
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_REPORT_FIELD_ACCESS_INVENTORY_GUARD_VERIFIED"
        if ok
        else "OCR_REPORT_FIELD_ACCESS_INVENTORY_GUARD_FAILED",
        "probe_count": 3,
        "failed_probe_count": failed_probe_count,
        "live_inventory_probe_passed": live_passed,
        "default_reader_candidate_probe_blocked": default_candidate_blocked,
        "parse_error_probe_blocked": parse_error_blocked,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep default-reader candidate regressions blocked before extended gate handoff."
    return "Restore default-reader candidate failure semantics in the field-access inventory verifier."


def markdown(report: GuardReport) -> str:
    return "\n".join((
        "# OCR Report Field Access Inventory Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_inventory_probe_passed: `{report['live_inventory_probe_passed']}`",
        "- default_reader_candidate_probe_blocked: "
        f"`{report['default_reader_candidate_probe_blocked']}`",
        f"- parse_error_probe_blocked: `{report['parse_error_probe_blocked']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
