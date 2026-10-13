# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_visible_digit_second_pass_batch.py

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_preprocess_variants import ImageArray, OpenCvModule, read_grayscale_crop, require_cv2  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_priority_crop_feature_targets import BoundingBox, answer_components  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_priority_digit_shape_scores import ComponentScore, component_score  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_visible_digit_candidate_targets import human_answer_map, is_digit_candidate  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

CASE_ID: Final[str] = "gangyuhyun849_current_phase2c_20260701T155839Z"
PHASE2C_CASE_ID: Final[str] = "phase2c_20260701T155839Z_48069762_0523e9a0_t_unit_daesu_01_lv3_r1_r1"
CROP_DIR: Final[Path] = Path("C:/server-ocr/phase2c_route_uploads") / PHASE2C_CASE_ID / "crop_benchmark_inputs" / PHASE2C_CASE_ID / "crops"
ARTIFACT_DIR: Final[Path] = ROOT / "tools/subjective_sheet_lab/visual_evidence/visible_digit_second_pass_batch"
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_visible_digit_second_pass_batch.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_visible_digit_second_pass_batch.md"
SCALE: Final[int] = 4
PAD: Final[int] = 10


@dataclass(frozen=True, slots=True)
class BatchTarget:
    question_no: int
    expected_digit: str
    final_side: str


@dataclass(frozen=True, slots=True)
class CandidateCrop:
    question_no: int
    provider_recognized: str
    expected_digit: str
    final_side: str
    source_component_count: int
    candidate_width: int
    candidate_height: int
    enlarged_width: int
    enlarged_height: int
    artifact_file: str
    status: str
    provider_call_count: int


class VisibleDigitSecondPassBatchError(Exception):
    pass


def main() -> int:
    cv2 = require_cv2()
    answers = human_answer_map()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    crops = [build_candidate_crop(cv2, target) for target in targets(answers)]
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "answer_key_used": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "case_id": CASE_ID,
        "status": "USER_APPROVAL_REQUIRED",
        "candidate_count": len(crops),
        "enlarged_crop_scale": SCALE,
        "merge_policy": "second_pass_result_requires_manual_confirmation",
        "candidates": [asdict(crop) for crop in crops],
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(crops), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def targets(answers: dict[int, str]) -> tuple[BatchTarget, ...]:
    return (
        BatchTarget(16, require_digit(answers, 16, "5"), "right"),
        BatchTarget(17, require_digit(answers, 17, "3"), "left"),
    )


def build_candidate_crop(cv2: OpenCvModule, target: BatchTarget) -> CandidateCrop:
    gray = read_grayscale_crop(cv2, CROP_DIR / f"q{target.question_no:03d}.png")
    components = tuple(sorted(answer_components(cv2, gray), key=lambda box: box.x))
    scored = tuple(component_score(cv2, gray, box) for box in components)
    candidate = select_visible_candidate(scored, target.final_side)
    cropped = padded_crop(gray, candidate.bbox, PAD)
    enlarged = enlarge(cv2, cropped, SCALE)
    artifact_file = f"q{target.question_no:03d}_visible_digit_x{SCALE}.png"
    if not cv2.imwrite(str(ARTIFACT_DIR / artifact_file), enlarged):
        raise VisibleDigitSecondPassBatchError(f"failed to write {artifact_file}")
    height, width = cropped.shape[:2]
    enlarged_height, enlarged_width = enlarged.shape[:2]
    return CandidateCrop(
        question_no=target.question_no,
        provider_recognized="?",
        expected_digit=target.expected_digit,
        final_side=target.final_side,
        source_component_count=len(components),
        candidate_width=int(width),
        candidate_height=int(height),
        enlarged_width=int(enlarged_width),
        enlarged_height=int(enlarged_height),
        artifact_file=artifact_file,
        status="USER_APPROVAL_REQUIRED",
        provider_call_count=0,
    )


def select_visible_candidate(scores: tuple[ComponentScore, ...], final_side: str) -> ComponentScore:
    candidates = tuple(score for score in scores if is_digit_candidate(score))
    if not candidates:
        raise VisibleDigitSecondPassBatchError("visible digit candidate missing")
    match final_side:
        case "left":
            return min(candidates, key=lambda score: score.bbox.x)
        case "right":
            return max(candidates, key=lambda score: score.bbox.x)
        case unreachable:
            assert_never(unreachable)


def padded_crop(gray: ImageArray, box: BoundingBox, pad: int) -> ImageArray:
    height, width = gray.shape[:2]
    left = max(0, box.x - pad)
    top = max(0, box.y - pad)
    right = min(width, box.x + box.width + pad)
    bottom = min(height, box.y + box.height + pad)
    return gray[top:bottom, left:right]


def enlarge(cv2: OpenCvModule, gray: ImageArray, scale: int) -> ImageArray:
    height, width = gray.shape[:2]
    return cv2.resize(gray, (width * scale, height * scale), interpolation=cv2.INTER_CUBIC)


def require_digit(answers: dict[int, str], question_no: int, expected: str) -> str:
    actual = answers.get(question_no, "").strip()
    if actual != expected:
        raise VisibleDigitSecondPassBatchError(f"q{question_no:03d} expected visible digit {expected}, got {actual}")
    return actual


def markdown_report(crops: list[CandidateCrop]) -> str:
    lines = [
        "# OCR Visible Digit Second-Pass Batch",
        "",
        "Provider-free enlarged crop batch for q016/q017 visible-digit missed-recognition targets.",
        "",
        "| q | Provider | Visible digit | Side | Source components | Enlarged size | Artifact |",
        "|---:|---|---|---|---:|---|---|",
    ]
    for crop in crops:
        lines.append(
            f"| {crop.question_no} | `{crop.provider_recognized}` | `{crop.expected_digit}` | `{crop.final_side}` | "
            f"{crop.source_component_count} | {crop.enlarged_width}x{crop.enlarged_height} | `{crop.artifact_file}` |"
        )
    lines.extend(
        (
            "",
            "- Status: `USER_APPROVAL_REQUIRED`",
            "- Gemini/API calls: 0",
            "- External OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- Merge policy: second-pass result still requires manual confirmation",
        )
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
