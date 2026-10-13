# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_visible_digit_candidate_targets.py

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_preprocess_variants import OpenCvModule, read_grayscale_crop, require_cv2  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_postprocessing_gate_matrix import item_for, warning_tuple  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_priority_crop_feature_targets import BoundingBox, answer_components  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_priority_digit_shape_scores import ComponentScore, component_score  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

CASE_ID: Final[str] = "gangyuhyun849_current_phase2c_20260701T155839Z"
PHASE2C_CASE_ID: Final[str] = "phase2c_20260701T155839Z_48069762_0523e9a0_t_unit_daesu_01_lv3_r1_r1"
CROP_DIR: Final[Path] = Path("C:/server-ocr/phase2c_route_uploads") / PHASE2C_CASE_ID / "crop_benchmark_inputs" / PHASE2C_CASE_ID / "crops"
HUMAN_TRANSCRIPTION: Final[Path] = ROOT / "tools/subjective_sheet_lab/gangyuhyun849_current_crop_human_transcription.json"
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_visible_digit_candidate_targets.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_visible_digit_candidate_targets.md"
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


@dataclass(frozen=True, slots=True)
class VisibleDigitTarget:
    question_no: int
    human_visible_digit: str
    final_position: str


@dataclass(frozen=True, slots=True)
class CandidateGeometry:
    component_count: int
    crossed_component_count: int
    candidate_count: int
    candidate_side: str
    candidate_holes: int
    candidate_density: float
    crossed_density: float
    signal_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VisibleDigitResult:
    case_id: str
    question_no: int
    provider_recognized: str
    provider_status: str
    human_visible_digit: str
    safe_counterpart_status: str
    warnings: tuple[str, ...]
    geometry: CandidateGeometry


class VisibleDigitCandidateError(Exception):
    pass


def main() -> int:
    cv2 = require_cv2()
    human_answers = human_answer_map()
    targets = tuple(VisibleDigitTarget(question, require_answer(human_answers, question), side) for question, side in ((16, "right"), (17, "left")))
    results = [verify_target(cv2, target) for target in targets]
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "answer_key_used": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "target_count": len(results),
        "visible_candidate_count": sum(1 for result in results if "visible_digit_candidate" in result.geometry.signal_flags),
        "results": [asdict(result) for result in results],
    }
    text = json.dumps(output, ensure_ascii=False)
    output["sensitive_field_leak_count"] = leak_count(text)
    if output["sensitive_field_leak_count"] != 0:
        raise VisibleDigitCandidateError("sensitive field or path token leaked into output")
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(results), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def verify_target(cv2: OpenCvModule, target: VisibleDigitTarget) -> VisibleDigitResult:
    gray = read_grayscale_crop(cv2, CROP_DIR / f"q{target.question_no:03d}.png")
    components = tuple(sorted(answer_components(cv2, gray), key=lambda box: box.x))
    scores = tuple(component_score(cv2, gray, box) for box in components)
    geometry = candidate_geometry(scores, target.final_position)
    unresolved = item_for(target.question_no, "?")
    safe_counterpart = item_for(target.question_no, target.human_visible_digit)
    provider_status = text_value(unresolved.get("status"))
    safe_status = text_value(safe_counterpart.get("status"))
    warnings = warning_tuple(unresolved)
    if provider_status != "review_required":
        raise VisibleDigitCandidateError(f"q{target.question_no:03d} unresolved status {provider_status}")
    if safe_status != "safe_auto_grade":
        raise VisibleDigitCandidateError(f"q{target.question_no:03d} visible digit counterpart status {safe_status}")
    if "unclear_final_answer" not in warnings:
        raise VisibleDigitCandidateError(f"q{target.question_no:03d} missing unclear warning: {warnings}")
    if "visible_digit_candidate" not in geometry.signal_flags:
        raise VisibleDigitCandidateError(f"q{target.question_no:03d} missing candidate signal: {geometry}")
    return VisibleDigitResult(CASE_ID, target.question_no, "?", provider_status, target.human_visible_digit, safe_status, warnings, geometry)


def candidate_geometry(scores: tuple[ComponentScore, ...], final_position: str) -> CandidateGeometry:
    crossed = tuple(score for score in scores if is_crossed_component(score))
    candidates = tuple(score for score in scores if is_digit_candidate(score))
    selected = select_candidate(candidates, final_position)
    crossed_density = max((score.density for score in crossed), default=0.0)
    flags: list[str] = []
    if selected is not None:
        flags.append("visible_digit_candidate")
    if crossed:
        flags.append("crossed_or_overwritten_neighbor")
    return CandidateGeometry(
        component_count=len(scores),
        crossed_component_count=len(crossed),
        candidate_count=len(candidates),
        candidate_side=final_position if selected else "",
        candidate_holes=selected.holes if selected else 0,
        candidate_density=round(selected.density, 3) if selected else 0.0,
        crossed_density=round(crossed_density, 3),
        signal_flags=tuple(flags),
    )


def select_candidate(candidates: tuple[ComponentScore, ...], final_position: str) -> ComponentScore | None:
    if not candidates:
        return None
    match final_position:
        case "left":
            return min(candidates, key=lambda score: score.bbox.x)
        case "right":
            return max(candidates, key=lambda score: score.bbox.x)
        case unreachable:
            assert_never(unreachable)


def is_digit_candidate(score: ComponentScore) -> bool:
    return score.bbox.area <= 520 and score.density <= 0.36 and score.bbox.height >= 30 and score.aspect_ratio <= 0.9


def is_crossed_component(score: ComponentScore) -> bool:
    return score.holes >= 3 and score.density >= 0.45 and score.bbox.area >= 750


def human_answer_map() -> dict[int, str]:
    payload = read_json(HUMAN_TRANSCRIPTION)
    answers = payload.get("answers")
    if not isinstance(answers, list):
        raise VisibleDigitCandidateError("human transcription answers must be a list")
    result: dict[int, str] = {}
    for item in answers:
        if isinstance(item, dict):
            question = item.get("question_no")
            answer = item.get("human_answer")
            if isinstance(question, int) and isinstance(answer, str):
                result[question] = answer
    return result


def require_answer(answers: dict[int, str], question_no: int) -> str:
    answer = answers.get(question_no, "").strip()
    if answer not in ("3", "5"):
        raise VisibleDigitCandidateError(f"q{question_no:03d} human visible digit missing")
    return answer


def read_json(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VisibleDigitCandidateError("JSON root must be an object")
    return value


def markdown_report(results: list[VisibleDigitResult]) -> str:
    lines = [
        "# OCR Visible Digit Candidate Targets",
        "",
        "Provider-free missed-recognition targets for q016/q017 visible final digits.",
        "",
        "| Case | q | Provider | Human visible | Candidate | Crossed | Status |",
        "|---|---:|---|---|---:|---:|---|",
    ]
    for result in results:
        lines.append(
            f"| `{result.case_id}` | {result.question_no} | `{result.provider_recognized}` | "
            f"`{result.human_visible_digit}` | {result.geometry.candidate_count} | "
            f"{result.geometry.crossed_component_count} | `{result.provider_status}` |"
        )
    lines.extend(("", "- Gemini/API calls: 0", "- External OCR API calls: 0", "- `/api/submit-test` calls: 0", "- `#tsSubmit` clicks: 0"))
    return "\n".join(lines) + "\n"


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""


def leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)


if __name__ == "__main__":
    raise SystemExit(main())
