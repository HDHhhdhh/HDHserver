# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\run_cached_ocr_regression_summary.py

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, NotRequired, TypedDict


ROOT: Final[Path] = Path(__file__).resolve().parents[2]
LAB_DIR: Final[Path] = ROOT / "tools" / "subjective_sheet_lab"
SERVER_OCR: Final[Path] = Path(r"C:\server-ocr")
GANG_RECOGNIZED: Final[Path] = (
    SERVER_OCR
    / "phase2e_live_qa_cache"
    / "phase2c_20260701T123845Z_4d6cdf1c_4f594d4d_t_unit_daesu_01_lv3_r1_r1"
    / "recognized.json"
)
GANG_HUMAN: Final[Path] = LAB_DIR / "gangyuhyun849_human_transcription.json"
SUMMARY_JSON: Final[Path] = LAB_DIR / "cached_ocr_regression_summary.json"
SUMMARY_MD: Final[Path] = LAB_DIR / "cached_ocr_regression_summary.md"
CASE_EVALS: Final[dict[str, Path]] = {
    "person_02_same_contact": SERVER_OCR / "gemini_outputs" / "person_02_same_contact" / "human_transcription_eval.json",
    "person_04_same_contact": SERVER_OCR / "gemini_outputs" / "person_04_same_contact" / "human_transcription_eval.json",
}
CHOICE_NUMBER_QUESTIONS: Final[frozenset[int]] = frozenset((1, 3, 5, 9, 13, 14, 17, 19))
FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "score", "wrong", "pct", "grading")
)
PATH_TOKENS: Final[tuple[str, ...]] = ("C:\\", "C:/", "server-ocr", "phase2c_route_uploads", "crop_benchmark_inputs")


Confidence = Literal["high", "low"]
Status = Literal["safe_auto_grade", "review_required", "retake_required", "data_check_required", "missing"]


class HumanAnswer(TypedDict):
    question_no: int
    human_answer: str
    confidence: Confidence
    notes: str


class HumanFixture(TypedDict):
    case_id: str
    source: str
    answers: list[HumanAnswer]


class RecognizedItem(TypedDict):
    question: int
    recognized: str


class RecognizedFixture(TypedDict):
    items: list[RecognizedItem]


class CaseSummary(TypedDict):
    total: int
    evaluated_total: int
    ocr_vs_human_accuracy: float | None
    high_confidence_evaluated_total: int
    high_confidence_ocr_vs_human_accuracy: float | None
    wrong_safe_auto_grade: int
    missing: int
    safe_auto_grade: int
    review_required: int
    retake_required: int
    data_check_required: int
    ambiguous_human_labels: int
    answer_key_grading_accuracy: NotRequired[float | None]
    source: NotRequired[str]


class LeakSummary(TypedDict):
    forbidden_field_hits: list[str]
    path_leak_hits: list[str]


@dataclass(frozen=True, slots=True)
class GangItem:
    question_no: int
    human_answer: str
    confidence: Confidence
    recognized_answer: str
    status: Status


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_answer(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def classify_status(question_no: int, recognized: str) -> Status:
    value = recognized.strip()
    if not value:
        return "missing"
    if value in {"?", "unknown", "unclear"}:
        return "review_required"
    if question_no in CHOICE_NUMBER_QUESTIONS and value not in {"1", "2", "3", "4", "5"}:
        return "review_required"
    return "safe_auto_grade"


def load_gang_items() -> list[GangItem]:
    human = read_json(GANG_HUMAN)
    recognized = read_json(GANG_RECOGNIZED)
    human_answers = {int(item["question_no"]): item for item in human["answers"]}
    recognized_answers = {int(item["question"]): str(item.get("recognized", "")) for item in recognized["items"]}
    return [
        GangItem(
            question_no=question_no,
            human_answer=str(human_answers[question_no]["human_answer"]),
            confidence=human_answers[question_no]["confidence"],
            recognized_answer=recognized_answers.get(question_no, ""),
            status=classify_status(question_no, recognized_answers.get(question_no, "")),
        )
        for question_no in range(1, 21)
    ]


def accuracy(matches: int, total: int) -> float | None:
    if total == 0:
        return None
    return round(matches * 100 / total, 1)


def summarize_gang() -> CaseSummary:
    items = load_gang_items()
    evaluated = [item for item in items if item.human_answer and item.recognized_answer]
    high_confidence = [item for item in evaluated if item.confidence == "high"]
    matches = sum(1 for item in evaluated if normalize_answer(item.human_answer) == normalize_answer(item.recognized_answer))
    high_matches = sum(1 for item in high_confidence if normalize_answer(item.human_answer) == normalize_answer(item.recognized_answer))
    wrong_safe = sum(
        1
        for item in evaluated
        if item.status == "safe_auto_grade" and normalize_answer(item.human_answer) != normalize_answer(item.recognized_answer)
    )
    return {
        "total": len(items),
        "evaluated_total": len(evaluated),
        "ocr_vs_human_accuracy": accuracy(matches, len(evaluated)),
        "high_confidence_evaluated_total": len(high_confidence),
        "high_confidence_ocr_vs_human_accuracy": accuracy(high_matches, len(high_confidence)),
        "wrong_safe_auto_grade": wrong_safe,
        "missing": sum(1 for item in items if item.status == "missing"),
        "safe_auto_grade": sum(1 for item in items if item.status == "safe_auto_grade"),
        "review_required": sum(1 for item in items if item.status == "review_required"),
        "retake_required": 0,
        "data_check_required": 0,
        "ambiguous_human_labels": sum(1 for item in items if item.confidence == "low"),
        "source": "phase2e_live_cache_vs_human_visual_transcription",
    }


def summarize_existing_case(path: Path) -> CaseSummary:
    payload = read_json(path)
    summary = payload.get("summary", {})
    return {
        "total": int(summary.get("total", 0)),
        "evaluated_total": int(summary.get("ocr_evaluated_total", 0)),
        "ocr_vs_human_accuracy": summary.get("ocr_recognition_accuracy_against_human_transcription"),
        "high_confidence_evaluated_total": 0,
        "high_confidence_ocr_vs_human_accuracy": None,
        "wrong_safe_auto_grade": int(summary.get("wrong_safe_auto_grade_against_human_transcription", 0)),
        "missing": int(summary.get("missing", 0)),
        "safe_auto_grade": int(summary.get("safe_auto_grade", 0)),
        "review_required": int(summary.get("review_required", 0)),
        "retake_required": int(summary.get("retake_required", 0)),
        "data_check_required": int(summary.get("data_check_required", 0)),
        "ambiguous_human_labels": int(summary.get("ambiguous_human_label_count", 0)),
        "answer_key_grading_accuracy": summary.get("answer_key_grading_accuracy_recognized_vs_expected"),
        "source": "existing_human_transcription_eval",
    }


def forbidden_field_hits(value, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                hits.append(f"{path}.{key}")
            hits.extend(forbidden_field_hits(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(forbidden_field_hits(child, f"{path}[{index}]"))
    return hits


def path_leak_hits(value) -> list[str]:
    text = json.dumps(value, ensure_ascii=False)
    return [token for token in PATH_TOKENS if token in text]


def leak_summary(payload) -> LeakSummary:
    return {"forbidden_field_hits": forbidden_field_hits(payload), "path_leak_hits": path_leak_hits(payload)}


def render_markdown(results: dict[str, CaseSummary], leaks: dict[str, LeakSummary]) -> str:
    lines = [
        "# Cached OCR Regression Summary",
        "",
        "Date: 2026-07-01",
        "Provider calls: 0",
        "Submit-test calls: 0",
        "",
        "| Case | OCR vs human | High-confidence OCR vs human | Evaluated | Safe | Review | Missing | Wrong safe auto-grade | Ambiguous human labels |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case_id, summary in results.items():
        lines.append(
            "| "
            + " | ".join(
                (
                    case_id,
                    str(summary["ocr_vs_human_accuracy"]),
                    str(summary["high_confidence_ocr_vs_human_accuracy"]),
                    str(summary["evaluated_total"]),
                    str(summary["safe_auto_grade"]),
                    str(summary["review_required"]),
                    str(summary["missing"]),
                    str(summary["wrong_safe_auto_grade"]),
                    str(summary["ambiguous_human_labels"]),
                )
            )
            + " |"
        )
    lines.extend(["", "## Leak Scan", ""])
    for case_id, leak in leaks.items():
        lines.extend(
            [
                f"- {case_id}: forbidden_field_hits={len(leak['forbidden_field_hits'])}, "
                f"path_leak_hits={len(leak['path_leak_hits'])}",
            ]
        )
    lines.extend(
        [
            "",
            "Notes:",
            "- 강규현849 summary uses local human visual transcription only; answer keys are not used.",
            "- person_02/person_04 summaries reuse existing human_transcription_eval outputs.",
            "- This regression is provider-free and does not call /api/submit-test.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    results: dict[str, CaseSummary] = {"gangyuhyun849": summarize_gang()}
    payloads: dict[str, object] = {
        "gangyuhyun849_recognized": read_json(GANG_RECOGNIZED),
        "gangyuhyun849_human_transcription": read_json(GANG_HUMAN),
    }

    for case_id, eval_path in CASE_EVALS.items():
        if eval_path.exists():
            eval_payload = read_json(eval_path)
            results[case_id] = summarize_existing_case(eval_path)
            payloads[f"{case_id}_human_transcription_eval"] = eval_payload
        else:
            results[case_id] = {
                "total": 0,
                "evaluated_total": 0,
                "ocr_vs_human_accuracy": None,
                "high_confidence_evaluated_total": 0,
                "high_confidence_ocr_vs_human_accuracy": None,
                "wrong_safe_auto_grade": 0,
                "missing": 0,
                "safe_auto_grade": 0,
                "review_required": 0,
                "retake_required": 0,
                "data_check_required": 0,
                "ambiguous_human_labels": 0,
                "source": f"missing_eval:{eval_path.name}",
            }

    leaks = {case_id: leak_summary(payload) for case_id, payload in payloads.items()}
    output = {
        "generated_at": "2026-07-01",
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "results": results,
        "leak_scan": leaks,
    }
    SUMMARY_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    SUMMARY_MD.write_text(render_markdown(results, leaks), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
