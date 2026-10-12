# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_digit_shape_generalization_matrix.py

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
from tools.subjective_sheet_lab.verify_ocr_priority_digit_shape_scores import ShapeSummary, shape_summary  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

CROP_ROOT: Final[Path] = Path("C:/server-ocr/crop_benchmark_inputs")
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_digit_shape_generalization_matrix.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_digit_shape_generalization_matrix.md"
CROP_CASES: Final[tuple[str, ...]] = (
    "answer_sheet_v3_blank_smoke",
    "daesu_jisu1_lv3_r1_photo01",
    "intake_smoke_person_02",
    "person_02",
    "person_02_good",
    "person_02_tilted",
    "person_03",
    "person_04",
    "photo_1",
    "photo_2",
    "sample_photo_2",
)
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
class MatrixRow:
    case_id: str
    question_no: int
    component_count: int
    cluster_component_count: int
    leading_holes: int
    second_holes: int
    leading_right_bias: float
    leading_top_bias: float
    signal_flags: tuple[str, ...]


class DigitShapeGeneralizationError(Exception):
    pass


def main() -> int:
    cv2 = require_cv2()
    rows = [matrix_row(case_id, question_no, shape_for(cv2, case_id, question_no)) for case_id in CROP_CASES for question_no in (3, 18)]
    summary = matrix_summary(rows)
    verify_summary(summary)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "case_set_count": len(CROP_CASES),
        "row_count": len(rows),
        "summary": summary,
        "rows": [asdict(row) for row in rows],
    }
    text = json.dumps(output, ensure_ascii=False)
    output["sensitive_field_leak_count"] = leak_count(text)
    if output["sensitive_field_leak_count"] != 0:
        raise DigitShapeGeneralizationError("sensitive field or path token leaked into output")
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(rows, summary), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def shape_for(cv2: OpenCvModule, case_id: str, question_no: int) -> ShapeSummary:
    crop = CROP_ROOT / case_id / "crops" / f"q{question_no:03d}.png"
    if not crop.exists():
        raise DigitShapeGeneralizationError(f"missing crop for {case_id} q{question_no:03d}")
    return shape_summary(cv2, read_grayscale_crop(cv2, crop))


def matrix_row(case_id: str, question_no: int, summary: ShapeSummary) -> MatrixRow:
    return MatrixRow(
        case_id=case_id,
        question_no=question_no,
        component_count=summary.component_count,
        cluster_component_count=summary.cluster_component_count,
        leading_holes=summary.leading_holes,
        second_holes=summary.second_holes,
        leading_right_bias=summary.leading_right_bias,
        leading_top_bias=summary.leading_top_bias,
        signal_flags=summary.signal_flags,
    )


def matrix_summary(rows: list[MatrixRow]) -> JsonObject:
    q003_signal_cases = tuple(row.case_id for row in rows if row.question_no == 3 and "three_n_shape_conflict" in row.signal_flags)
    q018_signal_cases = tuple(row.case_id for row in rows if row.question_no == 18 and "leading_digit_not_nine_like" in row.signal_flags)
    blank_like_rows = tuple(f"{row.case_id}:q{row.question_no:03d}" for row in rows if row.component_count == 0)
    return {
        "q003_three_n_signal_count": len(q003_signal_cases),
        "q003_three_n_signal_cases": list(q003_signal_cases),
        "q018_leading_digit_not_nine_like_count": len(q018_signal_cases),
        "q018_leading_digit_not_nine_like_cases": list(q018_signal_cases),
        "blank_like_row_count": len(blank_like_rows),
        "blank_like_rows": list(blank_like_rows),
    }


def verify_summary(summary: JsonObject) -> None:
    if summary.get("q003_three_n_signal_count") != 2:
        raise DigitShapeGeneralizationError(f"unexpected q003 signal count: {summary}")
    if summary.get("q018_leading_digit_not_nine_like_count") != 1:
        raise DigitShapeGeneralizationError(f"unexpected q018 signal count: {summary}")
    if summary.get("blank_like_row_count") != 5:
        raise DigitShapeGeneralizationError(f"unexpected blank-like row count: {summary}")


def markdown_report(rows: list[MatrixRow], summary: JsonObject) -> str:
    lines = [
        "# OCR Digit Shape Generalization Matrix",
        "",
        "Provider-free threshold generalization check across existing read-only crop sets.",
        "",
        f"- Crop sets: {len(CROP_CASES)}",
        f"- Rows: {len(rows)}",
        f"- q003 three/n signal count: {summary['q003_three_n_signal_count']}",
        f"- q018 3/9 signal count: {summary['q018_leading_digit_not_nine_like_count']}",
        f"- blank-like row count: {summary['blank_like_row_count']}",
        "",
        "| Case | q | Components | Cluster | Holes | Bias | Signals |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row.case_id}` | {row.question_no} | {row.component_count} | {row.cluster_component_count} | "
            f"{row.leading_holes}/{row.second_holes} | {row.leading_right_bias}/{row.leading_top_bias} | "
            f"`{', '.join(row.signal_flags)}` |"
        )
    lines.extend(("", "- Gemini/API calls: 0", "- External OCR API calls: 0", "- `/api/submit-test` calls: 0", "- `#tsSubmit` clicks: 0"))
    return "\n".join(lines) + "\n"


def leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)


if __name__ == "__main__":
    raise SystemExit(main())
