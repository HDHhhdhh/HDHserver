#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_operator_summary_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import read_json_object
from ocr_provider_free_operator_summary_guard_model import (
    GuardProbes,
    OperatorSummaryGuardReport,
    build_guard_report,
    build_probes,
    copied_payload,
    copied_status_card,
    next_safe_action,
    payload_rejected,
    snapshot_status_card,
    summary_state,
)
from ocr_provider_free_operator_summary_guard_output import markdown
import verify_ocr_provider_free_handoff_status_card as status_card
import verify_ocr_provider_free_operator_summary as operator_summary

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_operator_summary_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_operator_summary_guard.md"


def main() -> int:
    live_report = operator_summary.build_report(
        read_json_object(status_card.REPORT_JSON_OUT),
        read_json_object(operator_summary.OPERATOR_NEXT_ACTION_JSON),
    )
    before = snapshot_status_card()
    probes = build_probes(live_report, before)
    report = build_guard_report(probes, live_report)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
