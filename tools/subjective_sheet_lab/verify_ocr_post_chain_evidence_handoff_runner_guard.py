#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_evidence_handoff_runner_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_post_chain_evidence_handoff_runner_guard_model import (
    build_guard_report,
    build_probes,
    markdown,
    refresh_live_runner,
    snapshot_handoff_artifacts,
)

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_handoff_runner_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_handoff_runner_guard.md"


def main() -> int:
    live_steps, live_report = refresh_live_runner()
    before = snapshot_handoff_artifacts()
    probes = build_probes(live_steps, live_report, before)
    report = build_guard_report(probes, live_report)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
