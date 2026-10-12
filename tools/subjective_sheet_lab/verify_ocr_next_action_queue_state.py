# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_next_action_queue_state.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_next_action_queue_state_model import (
    LATEST_HEADING,
    QUEUE_PATH,
    QueueStateReport,
    build_report,
)
from ocr_next_action_queue_state_output import markdown
from ocr_preflight_environment_matrix_model import LAB, REPORT_JSON
from ocr_report_field_access import read_report
from verify_ocr_preflight_failure_classifier import REPORT_CLASSIFIER_JSON
from verify_ocr_preflight_report_freshness import REPORT_FRESHNESS_JSON

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_next_action_queue_state_verification.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_next_action_queue_state_verification.md"


def main() -> int:
    queue_text = QUEUE_PATH.read_text(encoding="utf-8")
    matrix = read_report(REPORT_JSON)
    classifier = read_report(REPORT_CLASSIFIER_JSON)
    freshness = read_report(REPORT_FRESHNESS_JSON)
    report = build_report(queue_text, matrix, classifier, freshness)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
