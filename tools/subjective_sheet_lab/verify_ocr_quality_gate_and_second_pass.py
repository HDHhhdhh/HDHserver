# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_quality_gate_and_second_pass.py

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.phase2c_crop_pipeline_adapter import Phase2CResult  # noqa: E402
from tools.subjective_sheet_lab.phase2d_cached_review_payload_adapter import Phase2DRequest, rebuild_review_payload  # noqa: E402
from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import Phase2ERequest  # noqa: E402
from tools.subjective_sheet_lab.phase2e_live_provider_runner import review_payload_from_provider_items  # noqa: E402
from tools.subjective_sheet_lab.phase2e_second_pass_experiment import (  # noqa: E402
    SecondPassGate,
    merge_second_pass_item,
    prepare_second_pass_experiment,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

ALLOWED_TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
FIXTURE_ROOT_ENV: Final[str] = "OCR_QUALITY_GATE_FIXTURE_ROOT"
DEFAULT_FIXTURE_ROOT: Final[Path] = Path(r"C:\tmp\ocr_quality_gate_verifier")


class QualityGateVerifierError(Exception):
    pass


def main() -> int:
    pipeline = write_quality_fixture()
    phase2e_result = verify_phase2e_quality_gate(pipeline)
    phase2d_result = verify_phase2d_quality_gate(pipeline)
    ambiguity_result = verify_overwritten_ambiguity_gate(pipeline)
    second_pass_result = verify_second_pass_skeleton(pipeline)
    output = {
        "ok": True,
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "phase2e_quality_gate": phase2e_result,
        "phase2d_quality_gate": phase2d_result,
        "overwritten_ambiguity_gate": ambiguity_result,
        "second_pass_skeleton": second_pass_result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def write_quality_fixture() -> Phase2CResult:
    fixture_root = configured_fixture_root()
    crop_dir = fixture_root / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    for question in range(1, 21):
        (crop_dir / f"q{question:03d}.png").write_bytes(b"fixture-crop")
    quality_path = fixture_root / "crop_quality.json"
    metrics = [normal_metric(question) for question in range(1, 21)]
    metrics[0] = normal_metric(1) | {"width": 120, "height": 40, "warnings": ["crop_quality_too_small"]}
    metrics[1] = normal_metric(2) | {"ink_density": 0.001, "warnings": ["crop_quality_blank_like"]}
    quality_path.write_text(
        json.dumps(
            {
                "ok": True,
                "failures": [],
                "answer_box_source": "detected_grid_repaired",
                "blur_variance": 80.0,
                "brightness_mean": 200.0,
                "brightness_std": 16.0,
                "shadow_spread": 20.0,
                "crop_metrics": metrics,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    ambiguity_path = fixture_root / "overwritten_ambiguity.json"
    ambiguity_path.write_text(
        json.dumps(
            {
                "schema_version": "overwritten_ambiguity_v1",
                "ok": True,
                "student_facing": False,
                "items": [
                    {"question_no": question, "warnings": ["overwritten_answer"] if question == 16 else []}
                    for question in range(1, 21)
                ],
                "provider_call_count": 0,
                "external_ocr_api_call_count": 0,
                "submit_test_call_count": 0,
                "ts_submit_click_count": 0,
                "answer_key_or_grading_field_leak_count": 0,
                "filesystem_path_leak_count": 0,
                "production_default": "NO_GO",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return fake_pipeline_result(fixture_root, quality_path, crop_dir, ambiguity_path)


def normal_metric(question: int) -> JsonObject:
    return {
        "question": question,
        "width": 485,
        "height": 116,
        "blur_variance": 80.0,
        "brightness_mean": 200.0,
        "brightness_std": 16.0,
        "ink_density": 0.08,
        "border_ink_ratio": 0.1,
        "warnings": [],
    }


def verify_phase2e_quality_gate(pipeline: Phase2CResult) -> JsonObject:
    payload = review_payload_from_provider_items(provider_items(), fake_phase2e_request(pipeline))
    items = require_items(payload)
    assert_item(items, 1, "retake_required", "crop_quality_too_small")
    assert_item(items, 2, "review_required", "crop_quality_blank_like")
    assert_item(items, 4, "safe_auto_grade", None)
    return {"q001": item_summary(items, 1), "q002": item_summary(items, 2), "q004": item_summary(items, 4)}


def verify_phase2d_quality_gate(pipeline: Phase2CResult) -> JsonObject:
    payload = rebuild_review_payload(safe_review_payload(), Phase2DRequest("990", ALLOWED_TEST_ID, 1, pipeline))
    items = require_items(payload)
    assert_item(items, 1, "retake_required", "crop_quality_too_small")
    assert_item(items, 2, "review_required", "crop_quality_blank_like")
    return {"q001": item_summary(items, 1), "q002": item_summary(items, 2)}


def verify_overwritten_ambiguity_gate(pipeline: Phase2CResult) -> JsonObject:
    phase2e_items = require_items(review_payload_from_provider_items(provider_items(), fake_phase2e_request(pipeline)))
    phase2d_items = require_items(rebuild_review_payload(safe_review_payload(), Phase2DRequest("990", ALLOWED_TEST_ID, 1, pipeline)))
    assert_item(phase2e_items, 16, "review_required", "overwritten_answer")
    assert_item(phase2d_items, 16, "review_required", "overwritten_answer")
    return {"phase2e_q016": item_summary(phase2e_items, 16), "phase2d_q016": item_summary(phase2d_items, 16)}


def verify_second_pass_skeleton(pipeline: Phase2CResult) -> JsonObject:
    payload = review_payload_from_provider_items(provider_items(), fake_phase2e_request(pipeline))
    fixture_root = pipeline.case_dir
    disabled = prepare_second_pass_experiment(
        payload,
        pipeline.crop_dir,
        fixture_root / "second_pass_disabled",
        SecondPassGate(enabled=False, provider_calls_allowed=False, max_provider_calls=0),
    )
    gated = prepare_second_pass_experiment(
        payload,
        pipeline.crop_dir,
        fixture_root / "second_pass_gated",
        SecondPassGate(enabled=True, provider_calls_allowed=False, max_provider_calls=0),
    )
    if disabled.status != "disabled" or disabled.provider_call_count != 0:
        raise QualityGateVerifierError(f"unexpected disabled second-pass status: {disabled}")
    if gated.status != "USER_APPROVAL_REQUIRED" or gated.provider_call_count != 0 or gated.manifest_path is None:
        raise QualityGateVerifierError(f"unexpected gated second-pass status: {gated}")
    primary = item_for_question(require_items(payload), 1)
    merged = merge_second_pass_item(primary, {"recognized": "4", "warnings": []})
    if merged.get("status") != "review_required" or merged.get("final_answer") is not None:
        raise QualityGateVerifierError(f"second pass merge auto-confirmed unexpectedly: {merged}")
    return {
        "disabled_status": disabled.status,
        "gated_status": gated.status,
        "candidate_count": len(gated.candidates),
        "manifest_created": gated.manifest_path.is_file(),
        "merge_status": str(merged.get("status")),
    }


def provider_items() -> list[JsonObject]:
    return [{"question": question, "recognized": "3" if question in {1, 3, 5, 9, 13, 14, 17, 19} else "12"} for question in range(1, 21)]


def safe_review_payload() -> JsonObject:
    return {
        "source": "quality_gate_fixture",
        "test_id": ALLOWED_TEST_ID,
        "round": "1",
        "problem_count": 20,
        "items": [
            {
                "question_no": question,
                "status": "safe_auto_grade",
                "recognized": "3" if question in {1, 3, 5, 9, 13, 14, 17, 19} else "12",
                "warnings": [],
                "candidates": [],
                "final_answer": "3" if question in {1, 3, 5, 9, 13, 14, 17, 19} else "12",
                "source": "safe_auto_grade",
            }
            for question in range(1, 21)
        ],
    }


def fake_phase2e_request(pipeline: Phase2CResult) -> Phase2ERequest:
    return Phase2ERequest(
        sid="990",
        test_id=ALLOWED_TEST_ID,
        round_no=1,
        pipeline_result=pipeline,
        cache_miss_reason="quality_gate_fixture",
        request_metadata={"verifier": "quality_gate"},
    )


def fake_pipeline_result(fixture_root: Path, quality_path: Path, crop_dir: Path, ambiguity_path: Path) -> Phase2CResult:
    return Phase2CResult(
        case_id="quality_gate_fixture",
        case_dir=fixture_root,
        source_image=fixture_root / "incoming" / "full_sheet.jpg",
        crop_root=fixture_root,
        crop_dir=crop_dir,
        review_asset_root=fixture_root / "review_assets",
        asset_manifest=fixture_root / "review_assets" / "asset_manifest.json",
        crop_count=20,
        contact_sheet_count=4,
        debug_sheet_count=0,
        contact_sheets=(),
        debug_sheets=(),
        asset_verification=fixture_root / "review_assets" / "asset_verification.json",
        crop_quality=quality_path,
        answer_box_source="detected_grid_repaired",
        overwritten_ambiguity=ambiguity_path,
    )


def configured_fixture_root() -> Path:
    raw = os.environ.get(FIXTURE_ROOT_ENV)
    if raw:
        return Path(raw)
    return DEFAULT_FIXTURE_ROOT


def require_items(payload: JsonObject) -> list[JsonValue]:
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 20:
        raise QualityGateVerifierError("payload items must contain exactly 20 questions")
    return items


def assert_item(items: list[JsonValue], question_no: int, status: str, warning: str | None) -> None:
    item = item_for_question(items, question_no)
    if item.get("status") != status:
        raise QualityGateVerifierError(f"q{question_no:03d} status {item.get('status')} != {status}")
    warnings = item.get("warnings")
    if warning is not None and (not isinstance(warnings, list) or warning not in warnings):
        raise QualityGateVerifierError(f"q{question_no:03d} missing warning {warning}: {warnings}")


def item_summary(items: list[JsonValue], question_no: int) -> JsonObject:
    item = item_for_question(items, question_no)
    return {
        "status": str(item.get("status")),
        "warnings": item.get("warnings") if isinstance(item.get("warnings"), list) else [],
        "final_answer": item.get("final_answer"),
    }


def item_for_question(items: list[JsonValue], question_no: int) -> JsonObject:
    for item in items:
        if isinstance(item, dict) and item.get("question_no") == question_no:
            return item
    raise QualityGateVerifierError(f"q{question_no:03d} missing")


if __name__ == "__main__":
    raise SystemExit(main())
