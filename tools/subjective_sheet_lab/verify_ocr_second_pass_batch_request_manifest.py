# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_second_pass_batch_request_manifest.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_second_pass_batch_request_manifest_model import (
    BatchRequestManifestError,
    RequestSources,
    build_request_manifest,
    read_json_object,
)
from ocr_second_pass_batch_request_manifest_output import leak_count, markdown_report, output_json

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MANIFEST_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_second_pass_manifest_from_review_payload.json"
BATCH_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_visible_digit_second_pass_batch.json"
ARTIFACT_DIR: Final[Path] = ROOT / "tools/subjective_sheet_lab/visual_evidence/visible_digit_second_pass_batch"
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_second_pass_batch_request_manifest.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_second_pass_batch_request_manifest.md"


def main() -> int:
    request = build_request_manifest(
        RequestSources(
            manifest=read_json_object(MANIFEST_JSON),
            batch=read_json_object(BATCH_JSON),
            source_batch_name=BATCH_JSON.name,
            artifact_dir=ARTIFACT_DIR,
        )
    )
    output = output_json(request)
    output["sensitive_field_leak_count"] = leak_count(json.dumps(output, ensure_ascii=False))
    if output["sensitive_field_leak_count"] != 0:
        raise BatchRequestManifestError("sensitive token leaked into batch request manifest")
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(request), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
