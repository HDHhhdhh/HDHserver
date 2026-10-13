# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_handoff_status_card_rendered_summary_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import read_json_object
from ocr_provider_free_handoff_status_card_rendered_summary_guard_model import (
    Probe,
    ProbeReport,
    StatusCardRenderedSummaryGuardReport,
    build_guard_report,
    copied_payload,
    expected_probe_result,
    next_safe_action,
    probes,
    run_probe,
)
from ocr_provider_free_handoff_status_card_rendered_summary_guard_output import markdown
import verify_ocr_provider_free_handoff_status_card as status_card

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_handoff_status_card_rendered_summary_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_handoff_status_card_rendered_summary_guard.md"


def main() -> int:
    payload = read_json_object(status_card.REPORT_JSON_OUT)
    before_mtime = status_card.REPORT_MD_OUT.stat().st_mtime_ns
    live_markdown = status_card.REPORT_MD_OUT.read_text(encoding="utf-8")
    probe_reports = [run_probe(probe) for probe in probes(payload, live_markdown)]
    report = build_guard_report(probe_reports, before_mtime != status_card.REPORT_MD_OUT.stat().st_mtime_ns)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
