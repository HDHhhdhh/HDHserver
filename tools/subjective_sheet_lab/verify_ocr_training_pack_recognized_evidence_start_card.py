# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_start_card.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import read_json_object
from ocr_training_pack_recognized_evidence_start_card_model import (
    FORBIDDEN_SNIPPETS,
    build_report,
    with_card_checks,
)
from ocr_training_pack_recognized_evidence_start_card_output import report_markdown, start_card_markdown
from verify_ocr_training_pack_recognized_evidence_filename_diagnostics import REPORT_JSON as FILENAME_JSON
import verify_ocr_training_pack_recognized_evidence_handoff_runner as handoff_runner
import verify_ocr_training_pack_recognized_evidence_handoff_runner_rendered_summary as rendered_summary
import verify_ocr_training_pack_recognized_evidence_handoff_runner_rendered_summary_guard as rendered_guard

START_CARD_MD: Final[Path] = LAB / "OCR_TRAINING_PACK_RECOGNIZED_EVIDENCE_START_HERE.md"
REPORT_JSON_OUT: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_start_card.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_start_card.md"


def main() -> int:
    report = build_report(
        read_json_object(handoff_runner.REPORT_JSON),
        read_json_object(rendered_summary.REPORT_JSON_OUT),
        read_json_object(rendered_guard.REPORT_JSON_OUT),
        read_json_object(FILENAME_JSON),
    )
    card_text = start_card_markdown(report)
    report = with_card_checks(report, card_text)
    START_CARD_MD.write_text(card_text, encoding="utf-8")
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(report_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
