# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_start_card_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import read_json_object
from ocr_training_pack_recognized_evidence_start_card_guard_model import (
    build_guard_report,
    build_probes,
    run_probe,
)
from ocr_training_pack_recognized_evidence_start_card_guard_output import markdown
import verify_ocr_training_pack_recognized_evidence_start_card as start_card

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_start_card_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_start_card_guard.md"


def main() -> int:
    payload = read_json_object(start_card.REPORT_JSON_OUT)
    markdown_text = start_card.START_CARD_MD.read_text(encoding="utf-8")
    probe_reports = [run_probe(probe) for probe in build_probes(payload, markdown_text)]
    report = build_guard_report(probe_reports)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
