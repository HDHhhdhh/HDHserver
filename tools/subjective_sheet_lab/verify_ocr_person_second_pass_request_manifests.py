# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_person_second_pass_request_manifests.py

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_person_second_pass_request_manifests_model import build_manifest, markdown_report  # noqa: E402

REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_person_second_pass_request_manifests.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_person_second_pass_request_manifests.md"


def main() -> int:
    manifest = build_manifest()
    REPORT_JSON.write_text(json.dumps(manifest.output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(manifest.cases), encoding="utf-8")
    print(json.dumps(manifest.output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
