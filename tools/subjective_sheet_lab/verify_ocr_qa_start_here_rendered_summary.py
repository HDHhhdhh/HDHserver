# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_qa_start_here_rendered_summary.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import read_json_object
from ocr_qa_start_here_rendered_summary_model import build_report, markdown
from verify_ocr_qa_start_here import REPORT_JSON_OUT as START_HERE_JSON
from verify_ocr_qa_start_here import START_HERE_MD


REPORT_JSON_OUT: Final[Path] = LAB / "ocr_qa_start_here_rendered_summary.json"


def main() -> int:
    report = build_report(read_json_object(START_HERE_JSON), START_HERE_MD.read_text(encoding="utf-8"))
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (LAB / "ocr_qa_start_here_rendered_summary.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
