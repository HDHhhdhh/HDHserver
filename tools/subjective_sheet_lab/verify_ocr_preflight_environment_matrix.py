# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_preflight_environment_matrix.py

from __future__ import annotations

import json

from ocr_preflight_environment_matrix_model import REPORT_JSON, REPORT_MD
from ocr_preflight_environment_matrix_output import markdown
from ocr_preflight_environment_matrix_runner import EnvironmentMatrixError, create_report


def main() -> int:
    report = create_report()
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if not report["ok"]:
        raise EnvironmentMatrixError("OCR preflight environment matrix failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
