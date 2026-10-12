#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_handoff_status_card_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_handoff_status_card_guard_model import (
    BLOCKED_STATUS,
    OK_STATUS,
    GuardProbes,
    blocked_for,
    build_guard_report,
    build_probes,
    clone_row,
    copied_payload_with_int,
    copied_rows_with_failure,
    copied_stale_guard_report,
    live_status_card_passed,
    refresh_live_status_card,
    snapshot_status_artifacts,
    source_metric_rejected,
    source_rows_from,
)
from ocr_provider_free_handoff_status_card_guard_output import MARKDOWN_FIELD_KEYS, markdown

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_handoff_status_card_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_handoff_status_card_guard.md"


def main() -> int:
    live_rows, live_report = refresh_live_status_card()
    before = snapshot_status_artifacts()
    probes = build_probes(live_rows, live_report, before)
    report = build_guard_report(probes, live_report)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
