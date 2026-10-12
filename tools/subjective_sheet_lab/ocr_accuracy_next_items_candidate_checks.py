from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_local_candidate_tools import (  # noqa: E402
    CandidateToolConfig,
    detect_tool_availability,
    run_candidate_tool_dry_run,
)
from tools.subjective_sheet_lab.ocr_preprocess_variants import OpenCvModule, read_grayscale_crop, require_cv2  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_priority_crop_feature_targets import answer_components  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_priority_digit_shape_scores import component_score  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_visible_digit_candidate_targets import is_digit_candidate  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

PHASE2C_ROOT: Final[Path] = Path("C:/server-ocr/phase2c_route_uploads")
LOCAL_ARTIFACT_ROOT: Final[Path] = ROOT / "tools/subjective_sheet_lab/visual_evidence/accuracy_next_items_gate"
VISIBLE_DIGIT_SOURCE: Final[Path] = ROOT / "tools/subjective_sheet_lab/visual_evidence/visible_digit_second_pass_batch"


class CandidateCheckError(Exception):
    pass


def q016_q017_local_candidate_tools() -> JsonObject:
    crop_dir = LOCAL_ARTIFACT_ROOT / "local_candidate_crops"
    out_dir = LOCAL_ARTIFACT_ROOT / "local_candidate_report"
    crop_dir.mkdir(parents=True, exist_ok=True)
    copy_visible_digit_crop(16, crop_dir)
    copy_visible_digit_crop(17, crop_dir)
    availability = detect_tool_availability()
    report = run_candidate_tool_dry_run(
        CandidateToolConfig(
            crop_dir=crop_dir,
            out_dir=out_dir,
            test_id="t_unit_daesu_01_lv3_r1",
            questions=(16, 17),
            run_tesseract=availability.tesseract_executable is not None,
            run_paddle=False,
            run_pix2tex=False,
            allow_model_load=False,
        )
    )
    tesseract = require_object(report.get("tesseract"), "tesseract")
    signals = signal_kinds(tesseract)
    return {
        "questions": [16, 17],
        "enlarged_crop_count": 2,
        "report_created": True,
        "tesseract_available": availability.tesseract_executable is not None,
        "paddleocr_available": availability.paddleocr_module,
        "pix2tex_available": availability.pix2tex_module or availability.latex_ocr_module,
        "tesseract_status": text_value(tesseract.get("status")),
        "tesseract_signal_count": len(signals),
        "tesseract_signal_kinds": signals,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
    }


def dependency_readiness() -> JsonObject:
    required_scripts = (
        "verify_ocr_provider_free_accuracy_gate_extended.py",
        "verify_ocr_visible_digit_second_pass_batch.py",
        "verify_ocr_q003_signal_audit.py",
        "verify_ocr_mijeok1_draft_postprocess_policy.py",
        "verify_ocr_training_pack_draft_postprocess_policy.py",
    )
    all_scripts_present = all(Path(__file__).with_name(script).is_file() for script in required_scripts)
    opencv_available = importlib.util.find_spec("cv2") is not None
    numpy_available = importlib.util.find_spec("numpy") is not None
    if not all_scripts_present:
        raise CandidateCheckError("required provider-free gate scripts are missing")
    return {
        "ocr_venv_required": True,
        "opencv_available": opencv_available,
        "numpy_available": numpy_available,
        "required_script_count": len(required_scripts),
        "required_scripts_present": all_scripts_present,
        "ready": opencv_available and numpy_available and all_scripts_present,
    }


def route_upload_visible_digit_generalization() -> JsonObject:
    cv2 = require_cv2()
    crop_dirs = route_crop_dirs("t_unit_daesu_01_lv3_r1")[:40]
    if not crop_dirs:
        raise CandidateCheckError("no daesu route-upload crop dirs found")
    scanned = 0
    signal_count = 0
    complete_sets = 0
    for crop_dir in crop_dirs:
        if complete_crop_set(crop_dir):
            complete_sets += 1
        for question_no in (16, 17):
            crop_path = crop_dir / f"q{question_no:03d}.png"
            if crop_path.is_file():
                scanned += 1
                signal_count += visible_digit_signal_count(cv2, crop_path)
    if scanned == 0:
        raise CandidateCheckError("route-upload q016/q017 crops were not scannable")
    return {
        "crop_set_count": len(crop_dirs),
        "complete_crop_set_count": complete_sets,
        "question_scan_count": scanned,
        "visible_digit_signal_count": signal_count,
        "scorer_status": "ran_on_route_upload_crops",
    }


def copy_visible_digit_crop(question_no: int, crop_dir: Path) -> None:
    source = VISIBLE_DIGIT_SOURCE / f"q{question_no:03d}_visible_digit_x4.png"
    if not source.is_file():
        raise CandidateCheckError(f"visible digit source missing for q{question_no:03d}")
    (crop_dir / f"q{question_no:03d}.png").write_bytes(source.read_bytes())


def signal_kinds(tesseract: JsonObject) -> list[str]:
    signals = tesseract.get("signals")
    if not isinstance(signals, list):
        return []
    kinds: list[str] = []
    for signal in signals:
        item = require_object(signal, "tesseract.signals[]")
        kind = text_value(item.get("kind"))
        if kind:
            kinds.append(kind)
    return kinds


def route_crop_dirs(test_id: str) -> list[Path]:
    pattern = f"phase2c_*_{test_id}*/crop_benchmark_inputs/*/crops"
    return sorted(PHASE2C_ROOT.glob(pattern), reverse=True)


def complete_crop_set(crop_dir: Path) -> bool:
    return all((crop_dir / f"q{question_no:03d}.png").is_file() for question_no in range(1, 21))


def visible_digit_signal_count(cv2: OpenCvModule, crop_path: Path) -> int:
    gray = read_grayscale_crop(cv2, crop_path)
    boxes = answer_components(cv2, gray)
    scores = tuple(component_score(cv2, gray, box) for box in boxes)
    return sum(1 for score in scores if is_digit_candidate(score))


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise CandidateCheckError(f"{label} must be a JSON object")
    return value


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""
