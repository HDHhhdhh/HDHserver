# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_handoff_retention_manifest_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_post_chain_handoff_retention_manifest_guard_model import guard_report, markdown
from ocr_preflight_environment_matrix_model import LAB


REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_retention_manifest_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_retention_manifest_guard.md"


def main() -> int:
    report = guard_report()
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
