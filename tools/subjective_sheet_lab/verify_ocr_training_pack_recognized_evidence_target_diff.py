# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_target_diff.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
)
from ocr_training_pack_recognized_evidence_target_diff_core import (
    evidence_files,
    require_target_diff_summary,
    target_diff_summary,
)

LAB: Final[Path] = Path(__file__).resolve().parent
SOURCE_JSON: Final[Path] = LAB / "ocr_training_pack_source_inventory.json"
EVIDENCE_DIR: Final[Path] = LAB / "training_pack_recognized_evidence"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_target_diff.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_target_diff.md"


def main() -> int:
    output = target_diff_summary(read_json_object(SOURCE_JSON), evidence_files(EVIDENCE_DIR))
    require_target_diff_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Recognized Evidence Target Diff",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- target rows: {output['target_row_count']}",
        f"- evidence files: {output['evidence_file_count']}",
        f"- coverage: {output['covered_target_count']} covered / {output['missing_target_count']} missing",
        f"- blocked inputs: duplicates {output['duplicate_evidence_target_count']}, unexpected {output['unexpected_evidence_target_count']}, missing test_id {output['missing_test_id_file_count']}",
        f"- target diff ready: {output['target_diff_ready']}",
        f"- next status: `{output['next_status']}`",
        "- sensitive/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
