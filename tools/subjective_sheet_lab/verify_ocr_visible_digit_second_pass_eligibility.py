# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_visible_digit_second_pass_eligibility.py

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
from tools.subjective_sheet_lab.verify_ocr_postprocessing_gate_matrix import item_for, warning_tuple  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_priority_crop_feature_targets import answer_components  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_priority_digit_shape_scores import component_score  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_visible_digit_candidate_targets import (  # noqa: E402
    is_crossed_component,
    is_digit_candidate,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

CASE_ID: Final[str] = "gangyuhyun849_current_phase2c_20260701T155839Z"
PHASE2C_CASE_ID: Final[str] = "phase2c_20260701T155839Z_48069762_0523e9a0_t_unit_daesu_01_lv3_r1_r1"
CROP_DIR: Final[Path] = (
    Path("C:/server-ocr/phase2c_route_uploads")
    / PHASE2C_CASE_ID
    / "crop_benchmark_inputs"
    / PHASE2C_CASE_ID
    / "crops"
)
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_visible_digit_second_pass_eligibility.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_visible_digit_second_pass_eligibility.md"
FORBIDDEN_OUTPUT_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
    "C:\\",
    "C:/",
    "/c/",
)
REVIEW_WARNINGS: Final[frozenset[str]] = frozenset(
    (
        "unclear_final_answer",
        "choice_number_invalid_for_auto_grade",
        "answer_value_letter_confusion",
        "multiple_answer_candidates",
    )
)
UNRESOLVED_TEXTS: Final[frozenset[str]] = frozenset(("", "?", "unknown", "unclear", "확인 필요"))


@dataclass(frozen=True, slots=True)
class EligibilityCase:
    name: str
    question_no: int
    recognized: str
    desired_eligible: bool


@dataclass(frozen=True, slots=True)
class GeometrySignals:
    component_count: int
    visible_digit_candidate_count: int
    crossed_neighbor_count: int


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    name: str
    case_id: str
    question_no: int
    recognized: str
    status: str
    warnings: tuple[str, ...]
    geometry: GeometrySignals
    second_pass_eligible: bool
    auto_confirm_allowed: bool
    reason: str


class VisibleDigitEligibilityError(Exception):
    pass


def main() -> int:
    cv2 = require_cv2()
    results = [evaluate_case(cv2, case) for case in cases()]
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "case_count": len(results),
        "eligible_count": sum(1 for result in results if result.second_pass_eligible),
        "positive_eligible_count": sum(
            1 for result in results if result.second_pass_eligible and result.name.startswith("positive")
        ),
        "negative_blocked_count": sum(
            1 for result in results if not result.second_pass_eligible and result.name.startswith("negative")
        ),
        "auto_confirm_allowed_count": sum(1 for result in results if result.auto_confirm_allowed),
        "results": [asdict(result) for result in results],
    }
    output["sensitive_field_leak_count"] = leak_count(json.dumps(output, ensure_ascii=False))
    if output["sensitive_field_leak_count"] != 0:
        raise VisibleDigitEligibilityError("sensitive token leaked into output")
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(results), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cases() -> tuple[EligibilityCase, ...]:
    return (
        EligibilityCase("positive_q016_unresolved_visible_digit", 16, "?", True),
        EligibilityCase("positive_q017_invalid_with_visible_digit", 17, "3X", True),
        EligibilityCase("negative_q016_already_resolved_digit", 16, "5", False),
        EligibilityCase("negative_q017_already_resolved_digit", 17, "3", False),
        EligibilityCase("negative_q003_relation_ambiguity", 3, "x->n", False),
        EligibilityCase("negative_q018_digit_shape_confusion", 18, "90", False),
        EligibilityCase("negative_q001_clean_choice", 1, "4", False),
    )


def evaluate_case(cv2: OpenCvModule, case: EligibilityCase) -> EligibilityResult:
    item = item_for(case.question_no, case.recognized)
    status = text_value(item.get("status"))
    warnings = warning_tuple(item)
    geometry = geometry_signals(cv2, case.question_no)
    eligible, reason = eligibility(case.recognized, status, warnings, geometry)
    if eligible != case.desired_eligible:
        raise VisibleDigitEligibilityError(f"{case.name} eligibility mismatch: {eligible}")
    return EligibilityResult(
        name=case.name,
        case_id=CASE_ID,
        question_no=case.question_no,
        recognized=case.recognized,
        status=status,
        warnings=warnings,
        geometry=geometry,
        second_pass_eligible=eligible,
        auto_confirm_allowed=False,
        reason=reason,
    )


def geometry_signals(cv2: OpenCvModule, question_no: int) -> GeometrySignals:
    gray = read_grayscale_crop(cv2, CROP_DIR / f"q{question_no:03d}.png")
    scores = tuple(component_score(cv2, gray, box) for box in answer_components(cv2, gray))
    return GeometrySignals(
        component_count=len(scores),
        visible_digit_candidate_count=sum(1 for score in scores if is_digit_candidate(score)),
        crossed_neighbor_count=sum(1 for score in scores if is_crossed_component(score)),
    )


def eligibility(
    recognized: str, status: str, warnings: tuple[str, ...], geometry: GeometrySignals
) -> tuple[bool, str]:
    if status != "review_required":
        return False, "not_review_required"
    if not unresolved_or_warning(recognized, warnings):
        return False, "not_unresolved_or_invalid"
    if geometry.visible_digit_candidate_count == 0:
        return False, "no_visible_digit_candidate"
    if geometry.crossed_neighbor_count == 0:
        return False, "no_crossed_or_overwritten_neighbor"
    return True, "manual_second_pass_candidate"


def unresolved_or_warning(recognized: str, warnings: tuple[str, ...]) -> bool:
    normalized = recognized.strip().lower()
    return normalized in UNRESOLVED_TEXTS or any(warning in REVIEW_WARNINGS for warning in warnings)


def markdown_report(results: list[EligibilityResult]) -> str:
    lines = [
        "# OCR Visible Digit Second-Pass Eligibility",
        "",
        "Provider-free gate that limits q016/q017-style second-pass work to unresolved or invalid review items.",
        "",
        "| Case | q | Recognized | Status | Eligible | Reason | Visible | Crossed |",
        "|---|---:|---|---|---|---|---:|---:|",
    ]
    for result in results:
        lines.append(
            f"| `{result.name}` | {result.question_no} | `{result.recognized}` | `{result.status}` | "
            f"{str(result.second_pass_eligible).lower()} | `{result.reason}` | "
            f"{result.geometry.visible_digit_candidate_count} | {result.geometry.crossed_neighbor_count} |"
        )
    lines.extend(
        (
            "",
            "- Auto-confirm from this gate: 0",
            "- Gemini/API calls: 0",
            "- External OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- Student-facing output: false",
        )
    )
    return "\n".join(lines) + "\n"


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""


def leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)


if __name__ == "__main__":
    raise SystemExit(main())
