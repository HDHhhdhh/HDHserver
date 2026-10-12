# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# Run: C:\server-ocr\.venv\Scripts\python.exe tools\subjective_sheet_lab\verify_gemini_accuracy_sprint_report.py --sprint-root <root>
"""Offline validation for the Gemini accuracy-sprint result reporter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gemini_accuracy_sprint_report import build_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sprint-root", required=True, type=Path)
    args = parser.parse_args()
    report = build_report(args.sprint_root.resolve())
    assert report["provider_calls"] == 10
    assert report["variant_count"] == 5
    assert report["case_count"] == 2
    assert report["wrong_safe_auto_grade"] == 0
    assert report["decision"] == "NO_GO"
    rendered = json.dumps(report, ensure_ascii=False)
    forbidden = ("C:\\", "expected", "canonical_answer", "accepted_answers", "grading", "AIza", "GEMINI_API_KEY")
    assert all(term.casefold() not in rendered.casefold() for term in forbidden)
    print("PASS: gemini_accuracy_sprint_report offline contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
