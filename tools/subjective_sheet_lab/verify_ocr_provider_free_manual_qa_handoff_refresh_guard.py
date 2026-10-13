#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_manual_qa_handoff_refresh_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_file_lock import FileLockBusy
from ocr_provider_free_manual_qa_handoff_refresh_guard_model import (
    build_guard_report,
    build_probes,
    markdown,
    refresh_live_handoff,
    snapshot_refresh_artifacts,
)
import verify_ocr_provider_free_manual_qa_handoff_refresh as refresh

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_manual_qa_handoff_refresh_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_manual_qa_handoff_refresh_guard.md"


def main() -> int:
    try:
        live_steps, live_report = refresh_live_handoff()
    except FileLockBusy as exc:
        report = refresh.lock_busy_report(exc)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    before = snapshot_refresh_artifacts()
    probes = build_probes(live_steps, live_report, before)
    report = build_guard_report(probes, live_report)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
