#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_provider_free_final_handoff_chain.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_final_handoff_chain_model import (
    HANDOFF_GUARD_JSON,
    HANDOFF_RUNNER_JSON,
    PROVIDER_FREE_CHAIN_JSON,
    SERIAL_GUARD_JSON,
    STEP_SPECS,
    FinalHandoffReport,
    FinalHandoffStep,
    build_report,
    run_steps,
)
from ocr_provider_free_final_handoff_chain_output import markdown

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_final_handoff_chain.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_final_handoff_chain.md"


def main() -> int:
    steps = run_steps()
    report = build_report(steps)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
