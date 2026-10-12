# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_promotion_preview_diff_gate.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import read_json_object
from ocr_training_pack_promotion_preview_diff_gate_model import diff_summary, markdown, require_summary
from verify_ocr_training_pack_promotion_preview_gate import REPORT_JSON as PREVIEW_JSON
from verify_ocr_training_pack_recognized_evidence_intake_replay import REPORT_JSON as INTAKE_REPLAY_JSON

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_promotion_preview_diff_gate.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_promotion_preview_diff_gate.md"


def main() -> int:
    output = diff_summary(read_json_object(PREVIEW_JSON), read_json_object(INTAKE_REPLAY_JSON))
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
