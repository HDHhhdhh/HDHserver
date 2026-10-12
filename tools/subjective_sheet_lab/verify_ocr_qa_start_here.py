# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_qa_start_here.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_qa_start_here_markdown import start_here_markdown, verification_markdown
from ocr_qa_start_here_verification_model import EVIDENCE_INDEX_JSON, build_verification_output
from ocr_preflight_environment_matrix_model import LAB
from verify_ocr_qa_start_here_freshness_guard import write_report as refresh_freshness_guard

START_HERE_MD: Final[Path] = LAB / "OCR_QA_START_HERE.md"
REPORT_JSON_OUT: Final[Path] = LAB / "ocr_qa_start_here_verification.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_qa_start_here_verification.md"


def main() -> int:
    refresh_freshness_guard()
    output = build_verification_output()
    START_HERE_MD.write_text(start_here_markdown(output), encoding="utf-8")
    REPORT_JSON_OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(verification_markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
