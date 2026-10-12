from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_answer_mode_policy import answer_mode_for_question
from tools.subjective_sheet_lab.ocr_payload_leak_policy import forbidden_paths, path_exposures
from tools.subjective_sheet_lab.phase2c_crop_pipeline_contracts import Phase2CResult
from tools.subjective_sheet_lab.phase2g_texteller_review_adapter import (
    ANSWER_VALUE,
    CHOICE_NUMBER,
    ENABLED_ENV,
    MANUAL_REVIEW,
    Phase2GRequest,
    load_phase2g_texteller_review_payload,
)


def run_smoke(crop_dir: Path, test_id: str, round_no: int) -> dict[str, object]:
    resolved_crop_dir = crop_dir.resolve()
    answer_modes = tuple(
        answer_mode_for_question(test_id, question_no)
        for question_no in range(1, 21)
    )
    if any(not mode for mode in answer_modes):
        raise ValueError("answer mode policy is incomplete for this test")
    placeholder = resolved_crop_dir.parent / "smoke_placeholder.json"
    pipeline_result = Phase2CResult(
        case_id="deidentified_offline_smoke",
        case_dir=resolved_crop_dir.parent,
        source_image=resolved_crop_dir.parent / "source_not_read.png",
        crop_root=resolved_crop_dir.parent,
        crop_dir=resolved_crop_dir,
        review_asset_root=resolved_crop_dir.parent,
        asset_manifest=placeholder,
        crop_count=20,
        contact_sheet_count=0,
        debug_sheet_count=0,
        contact_sheets=(),
        debug_sheets=(),
        asset_verification=placeholder,
        crop_quality=resolved_crop_dir.parent / "crop_quality_not_present.json",
        answer_box_source="benchmark_crop",
        overwritten_ambiguity=None,
    )
    os.environ[ENABLED_ENV] = "1"
    payload = load_phase2g_texteller_review_payload(
        Phase2GRequest(
            sid="deidentified",
            test_id=test_id,
            round_no=round_no,
            pipeline_result=pipeline_result,
            answer_modes=answer_modes,
        )
    )
    items = payload["items"]
    answer_value_items = [item for item in items if item["answer_mode"] == ANSWER_VALUE]
    return {
        "ok": True,
        "source": payload["source"],
        "problem_count": len(items),
        "answer_value_inference_count": len(answer_value_items),
        "answer_value_candidate_count": sum(
            item["recognized"] != "?" for item in answer_value_items
        ),
        "choice_number_skipped_count": sum(
            item["answer_mode"] == CHOICE_NUMBER for item in items
        ),
        "manual_review_skipped_count": sum(
            item["answer_mode"] == MANUAL_REVIEW for item in items
        ),
        "review_required_count": sum(
            item["status"] == "review_required" for item in items
        ),
        "unsafe_auto_grade_count": sum(
            item["status"] == "safe_auto_grade" for item in items
        ),
        "provider_call_count": payload["provider_call_count"],
        "answer_key_field_leak_count": len(forbidden_paths(payload)),
        "filesystem_path_leak": path_exposures(payload),
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an offline review-only TexTeller smoke test.")
    parser.add_argument("--crop-dir", type=Path, required=True)
    parser.add_argument("--test-id", default="t_unit_daesu_01_lv3_r1")
    parser.add_argument("--round", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    summary = run_smoke(args.crop_dir, args.test_id, args.round)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
