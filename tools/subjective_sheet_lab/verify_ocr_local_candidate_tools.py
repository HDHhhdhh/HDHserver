# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_local_candidate_tools.py

from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

FIXTURE_ROOT: Final[Path] = Path(r"C:\tmp\ocr_local_candidate_tools_verifier")


class LocalCandidateVerifierError(Exception):
    pass


def main() -> int:
    missing = missing_local_dependencies()
    if missing:
        output = {
            "ok": True,
            "skipped": True,
            "reason": "optional_local_ocr_dependencies_missing",
            "missing_dependencies": missing,
            "provider_call_count": 0,
            "external_ocr_api_call_count": 0,
            "submit_test_call_count": 0,
            "ts_submit_click_count": 0,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    crop_dir = write_synthetic_crops()
    variants = verify_preprocess_variants(crop_dir)
    policy = verify_checker_policy()
    local_tools = verify_optional_tool_dry_run(crop_dir)
    output = {
        "ok": True,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "preprocess_variants": variants,
        "checker_policy": policy,
        "optional_tool_dry_run": local_tools,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def missing_local_dependencies() -> list[str]:
    return [name for name in ("cv2", "numpy") if importlib.util.find_spec(name) is None]


def write_synthetic_crops() -> Path:
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    crop_dir = FIXTURE_ROOT / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    for question in range(1, 21):
        image = np.full((128, 420), 255, dtype=np.uint8)
        cv2.putText(image, str((question % 5) + 1), (180, 82), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 4, cv2.LINE_AA)
        cv2.imwrite(str(crop_dir / f"q{question:03d}.png"), image)
    return crop_dir


def verify_preprocess_variants(crop_dir: Path) -> JsonObject:
    from tools.subjective_sheet_lab.ocr_preprocess_variants import (  # noqa: PLC0415
        VariantConfig,
        generate_preprocess_variants,
    )

    out_dir = FIXTURE_ROOT / "variants"
    result = generate_preprocess_variants(VariantConfig(crop_dir, out_dir, (1, 2), 2))
    manifest_path = Path(str(result["manifest"]))
    manifest = read_json_object(manifest_path)
    items = manifest.get("variants")
    if not isinstance(items, list) or len(items) != 2:
        raise LocalCandidateVerifierError("preprocess manifest must include two requested questions")
    first = require_object(items[0], "variants[0]")
    variants = first.get("variants")
    if not isinstance(variants, list) or len(variants) != 6:
        raise LocalCandidateVerifierError("each question must include six OpenCV variants")
    metrics = require_object(require_object(variants[0], "variant[0]").get("metrics"), "variant metrics")
    for key in ("blur_variance", "brightness_mean", "brightness_std", "ink_density", "width", "height", "border_ink_ratio"):
        if key not in metrics:
            raise LocalCandidateVerifierError(f"missing metric: {key}")
    return {"manifest_created": manifest_path.is_file(), "questions": len(items), "variants_per_question": len(variants)}


def verify_checker_policy() -> JsonObject:
    from tools.subjective_sheet_lab.ocr_local_candidate_tools import (  # noqa: PLC0415
        CheckerSignal,
        apply_checker_signal,
        classify_tesseract_text,
    )

    safe_item: JsonObject = {
        "question_no": 1,
        "status": "safe_auto_grade",
        "recognized": "3",
        "warnings": [],
        "candidates": [],
        "final_answer": "3",
        "source": "safe_auto_grade",
    }
    conflict = apply_checker_signal(safe_item, CheckerSignal("tesseract", 1, "candidate", "4", "4", None))
    if conflict.get("status") != "review_required" or conflict.get("final_answer") is not None:
        raise LocalCandidateVerifierError("checker conflict must downgrade safe item to review_required")
    review_item = dict(safe_item)
    review_item["status"] = "review_required"
    review_item["source"] = None
    review_item["final_answer"] = None
    candidate = apply_checker_signal(review_item, CheckerSignal("tesseract", 1, "candidate", "3", "3", None))
    if candidate.get("status") != "review_required" or candidate.get("final_answer") is not None:
        raise LocalCandidateVerifierError("checker candidate must not promote review item")
    blank = apply_checker_signal(safe_item, CheckerSignal("tesseract", 1, "blank_like", "", None, "tesseract_blank_like"))
    if blank.get("status") != "review_required":
        raise LocalCandidateVerifierError("blank-like signal must block safe auto-grade")
    choice = classify_tesseract_text(1, "choice_number", "3")
    bad_choice = classify_tesseract_text(1, "choice_number", "x=2")
    return {
        "conflict_status": str(conflict.get("status")),
        "review_candidate_status": str(candidate.get("status")),
        "blank_status": str(blank.get("status")),
        "choice_signal": choice.kind,
        "bad_choice_signal": bad_choice.kind,
    }


def verify_optional_tool_dry_run(crop_dir: Path) -> JsonObject:
    from tools.subjective_sheet_lab.ocr_local_candidate_tools import (  # noqa: PLC0415
        CandidateToolConfig,
        run_candidate_tool_dry_run,
    )
    from tools.subjective_sheet_lab.ocr_payload_leak_policy import (  # noqa: PLC0415
        forbidden_paths,
        path_exposures,
    )

    out_dir = FIXTURE_ROOT / "optional_tools"
    report = run_candidate_tool_dry_run(
        CandidateToolConfig(
            crop_dir=crop_dir,
            out_dir=out_dir,
            test_id="t_unit_daesu_01_lv3_r1",
            questions=(1, 2),
            run_tesseract=False,
            run_paddle=False,
            run_pix2tex=False,
            allow_model_load=False,
        )
    )
    if report.get("provider_call_count") != 0 or report.get("external_ocr_api_call_count") != 0:
        raise LocalCandidateVerifierError("optional tool dry-run attempted an external call")
    if report.get("submit_test_call_count") != 0:
        raise LocalCandidateVerifierError("optional tool dry-run attempted submit-test")
    student_payload = {"ok": True, "review_payload": {"items": [{"question_no": 1, "status": "review_required"}]}}
    if forbidden_paths(student_payload) or path_exposures(student_payload):
        raise LocalCandidateVerifierError("student-facing leak fixture is not clean")
    return {
        "report_created": Path(str(report["report_path"])).is_file(),
        "tesseract_status": status_of(report.get("tesseract")),
        "paddleocr_status": status_of(report.get("paddleocr")),
        "pix2tex_status": status_of(report.get("pix2tex")),
        "student_payload_forbidden_paths": 0,
        "student_payload_path_leak": 0,
    }


def status_of(value: JsonValue) -> str:
    if isinstance(value, dict) and isinstance(value.get("status"), str):
        return value["status"]
    return "unknown"


def read_json_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise LocalCandidateVerifierError(f"{path} must contain a JSON object")
    return value


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise LocalCandidateVerifierError(f"{label} must be a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
