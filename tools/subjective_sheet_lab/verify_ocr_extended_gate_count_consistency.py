# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_extended_gate_count_consistency.py

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from ocr_extended_gate_count_consistency_model import build_report
from ocr_extended_gate_count_consistency_output import markdown
from ocr_preflight_environment_matrix_model import LAB, REPORT_JSON
from ocr_report_field_access import read_report
from verify_ocr_next_action_queue_state import (
    QUEUE_PATH,
    REPORT_JSON_OUT as QUEUE_STATE_JSON,
)
from verify_ocr_operator_next_action_summary import REPORT_JSON as OPERATOR_SUMMARY_JSON
from verify_ocr_preflight_failure_classifier import REPORT_CLASSIFIER_JSON
from verify_ocr_preflight_report_freshness import REPORT_FRESHNESS_JSON

EXTENDED_REPORT_JSON: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_extended.json"
REPORT_JSON_OUT: Final[Path] = LAB / "ocr_extended_gate_count_consistency.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_extended_gate_count_consistency.md"


def main() -> int:
    report_paths = {
        "extended": EXTENDED_REPORT_JSON,
        "matrix": REPORT_JSON,
        "classifier": REPORT_CLASSIFIER_JSON,
        "freshness": REPORT_FRESHNESS_JSON,
        "queue_state": QUEUE_STATE_JSON,
        "operator_summary": OPERATOR_SUMMARY_JSON,
    }
    reports = {
        "extended": read_report(EXTENDED_REPORT_JSON),
        "matrix": read_report(REPORT_JSON),
        "classifier": read_report(REPORT_CLASSIFIER_JSON),
        "freshness": read_report(REPORT_FRESHNESS_JSON),
        "queue_state": read_report(QUEUE_STATE_JSON),
        "operator_summary": read_report(OPERATOR_SUMMARY_JSON),
    }
    queue_text = QUEUE_PATH.read_text(encoding="utf-8")
    report = build_report(reports, queue_text, modified_times_ns(report_paths))
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def modified_times_ns(paths: Mapping[str, Path]) -> Mapping[str, int]:
    return {name: path.stat().st_mtime_ns for name, path in paths.items()}


if __name__ == "__main__":
    raise SystemExit(main())
