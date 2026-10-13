#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_handoff_status_card.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import read_json_object
from ocr_provider_free_handoff_status_card_model import (
    SOURCE_SPECS,
    HandoffStatusCardReport,
    HandoffStatusSourceRow,
    HandoffStatusSourceSpec,
    SourceLabel,
    build_report,
    source_row,
)
from ocr_provider_free_handoff_status_card_output import markdown

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_handoff_status_card.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_handoff_status_card.md"


def main() -> int:
    rows = [source_row(spec, read_json_object(spec.path)) for spec in SOURCE_SPECS]
    report = build_report(rows)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
