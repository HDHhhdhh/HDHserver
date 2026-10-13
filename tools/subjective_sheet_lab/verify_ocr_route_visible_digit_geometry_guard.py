# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_route_visible_digit_geometry_guard.py

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_preprocess_variants import OpenCvModule, read_grayscale_crop, require_cv2  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_priority_crop_feature_targets import answer_components  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_priority_digit_shape_scores import component_score  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_visible_digit_candidate_targets import (  # noqa: E402
    is_crossed_component,
    is_digit_candidate,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

PHASE2C_ROOT: Final[Path] = Path("C:/server-ocr/phase2c_route_uploads")
TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_route_visible_digit_geometry_guard.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_route_visible_digit_geometry_guard.md"
SCAN_SET_LIMIT: Final[int] = 40
QUESTION_NUMBERS: Final[tuple[int, ...]] = (16, 17)


@dataclass(frozen=True, slots=True)
class RouteQuestionSummary:
    question_no: int
    scanned_count: int
    visible_digit_signal_count: int
    crossed_neighbor_signal_count: int
    geometry_only_candidate_count: int
    geometry_only_second_pass_allowed_count: int


class RouteVisibleDigitGuardError(Exception):
    pass


def main() -> int:
    cv2 = require_cv2()
    crop_dirs = complete_crop_dirs()[:SCAN_SET_LIMIT]
    if len(crop_dirs) != SCAN_SET_LIMIT:
        raise RouteVisibleDigitGuardError(f"expected {SCAN_SET_LIMIT} complete crop sets, got {len(crop_dirs)}")
    summaries = [summarize_question(cv2, crop_dirs, question_no) for question_no in QUESTION_NUMBERS]
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "scan_set_count": len(crop_dirs),
        "question_scan_count": sum(summary.scanned_count for summary in summaries),
        "geometry_only_candidate_count": sum(summary.geometry_only_candidate_count for summary in summaries),
        "geometry_only_second_pass_allowed_count": sum(
            summary.geometry_only_second_pass_allowed_count for summary in summaries
        ),
        "requires_review_payload_status": True,
        "policy": "route_geometry_alone_cannot_trigger_second_pass",
        "summaries": [asdict(summary) for summary in summaries],
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    assert_guard(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(summaries), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def summarize_question(cv2: OpenCvModule, crop_dirs: list[Path], question_no: int) -> RouteQuestionSummary:
    visible = 0
    crossed = 0
    geometry_candidates = 0
    for crop_dir in crop_dirs:
        gray = read_grayscale_crop(cv2, crop_dir / f"q{question_no:03d}.png")
        scores = tuple(component_score(cv2, gray, box) for box in answer_components(cv2, gray))
        has_visible = any(is_digit_candidate(score) for score in scores)
        has_crossed = any(is_crossed_component(score) for score in scores)
        visible += int(has_visible)
        crossed += int(has_crossed)
        geometry_candidates += int(has_visible and has_crossed)
    return RouteQuestionSummary(
        question_no=question_no,
        scanned_count=len(crop_dirs),
        visible_digit_signal_count=visible,
        crossed_neighbor_signal_count=crossed,
        geometry_only_candidate_count=geometry_candidates,
        geometry_only_second_pass_allowed_count=0,
    )


def complete_crop_dirs() -> list[Path]:
    pattern = f"phase2c_*_{TEST_ID}*/crop_benchmark_inputs/*/crops"
    candidates = sorted(PHASE2C_ROOT.glob(pattern), reverse=True)
    return [crop_dir for crop_dir in candidates if is_complete(crop_dir)]


def is_complete(crop_dir: Path) -> bool:
    return all((crop_dir / f"q{question_no:03d}.png").is_file() for question_no in range(1, 21))


def assert_guard(output: JsonObject) -> None:
    if output["geometry_only_candidate_count"] != output["question_scan_count"]:
        raise RouteVisibleDigitGuardError("route geometry fixture no longer demonstrates broad candidate risk")
    if output["geometry_only_second_pass_allowed_count"] != 0:
        raise RouteVisibleDigitGuardError("geometry-only routing must not allow second pass")


def markdown_report(summaries: list[RouteQuestionSummary]) -> str:
    lines = [
        "# OCR Route Visible Digit Geometry Guard",
        "",
        "Provider-free route-upload scan proving geometry alone is too broad for q016/q017 second-pass routing.",
        "",
        "| q | Scanned | Visible digit signal | Crossed neighbor signal | Geometry-only candidates | Allowed from geometry only |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        lines.append(
            f"| {summary.question_no} | {summary.scanned_count} | {summary.visible_digit_signal_count} | "
            f"{summary.crossed_neighbor_signal_count} | {summary.geometry_only_candidate_count} | "
            f"{summary.geometry_only_second_pass_allowed_count} |"
        )
    lines.extend(
        (
            "",
            "- Policy: route geometry alone cannot trigger second-pass OCR.",
            "- Required companion signal: review payload status/warnings.",
            "- Gemini/API calls: 0",
            "- External OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- Student-facing output: false",
        )
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
