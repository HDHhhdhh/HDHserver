#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_operator_summary.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import JsonValue, read_json_object
from ocr_provider_free_operator_summary_model import (
    OperatorState,
    OperatorSummaryReport,
    assert_status_card_safety,
    build_report,
    next_safe_action,
    operator_state,
    require_bool,
    require_text,
    required_user_action,
    status_card_path,
)
from ocr_provider_free_operator_summary_output import markdown
import verify_ocr_provider_free_handoff_status_card as status_card
from verify_ocr_operator_next_action_summary import REPORT_JSON as OPERATOR_NEXT_ACTION_JSON

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_operator_summary.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_operator_summary.md"
READY_CARD_STATUS: Final = "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_READY"
BLOCKED_CARD_STATUS: Final = "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_BLOCKED"


def main() -> int:
    report = build_report(
        read_json_object(status_card.REPORT_JSON_OUT),
        read_json_object(OPERATOR_NEXT_ACTION_JSON),
    )
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
