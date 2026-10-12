#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# 1. Install uv if needed: https://docs.astral.sh/uv/
# 2. Run directly:
#      uv run tools/subjective_sheet_lab/ocr_benchmark_gate.py
# 3. Or with the project Python:
#      python tools/subjective_sheet_lab/ocr_benchmark_gate.py
# ------------------

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, assert_never

from human_transcription_eval import answers_match, load_human, load_recognized, normalize as normalize_answer
from ocr_benchmark_gate_reports import render_markdown
from ocr_review_schema import JsonObject, JsonValue
from ocr_review_payload_validator import require_array, require_object, require_string

OUTPUT_ROOT: Final = Path("C:/server-ocr/gemini_outputs")
REPORT_JSON: Final = OUTPUT_ROOT / "ocr_benchmark_gate_report.json"
REPORT_MD: Final = OUTPUT_ROOT / "ocr_benchmark_gate_report.md"
TRANSCRIPTION_THRESHOLD: Final = 90.0


@dataclass(frozen=True, slots=True)
class CaseConfig:
    case_id: str
    directory: str
    eval_file: str
    role: str
    independent_handwriting: bool
    capture_condition_case: bool


@dataclass(frozen=True, slots=True)
class TranscriptionMetric:
    available: bool
    correct: int | None
    total: int | None
    accuracy_percent: float | None
    source_path: str | None
    note: str
    human_total: int | None = None
    ambiguous_human_label_count: int | None = None


@dataclass(frozen=True, slots=True)
class CaseMetric:
    case_id: str
    role: str
    source_eval_path: str
    completed: int
    pending: int
    total: int
    answer_key_accuracy_percent: float | None
    safe_auto_grade: int
    review_required: int
    data_check_required: int
    retake_required: int
    missing: int
    mismatch: int
    wrong_safe_auto_grade: int | None
    transcription: TranscriptionMetric
    independent_handwriting: bool
    capture_condition_case: bool
    notes: str


CASES: Final = (
    CaseConfig("person_02_same_contact", "person_02_same_contact", "same_contact_final_eval.json", "baseline handwriting same-contact case", True, False),
    CaseConfig("daesu_jisu1_lv3_r1_photo01_same_contact", "daesu_jisu1_lv3_r1_photo01_same_contact", "final_eval_q001_q020.json", "real daesu jisu1 lv3 round1 handwriting case", True, False),
    CaseConfig("photo_1_same_contact", "photo_1_same_contact", "same_contact_partial_eval_q001_q005.json", "capture-condition case, same handwriting as person_02", False, True),
    CaseConfig("photo_2_same_contact", "photo_2_same_contact", "same_contact_partial_eval_q001_q005.json", "capture-condition case, same handwriting as person_02", False, True),
)


def main() -> int:
    report = build_gate_report(OUTPUT_ROOT)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"ok": True, "gate_status": report["gate_status"], "cases": len(report["cases"]), "report": str(REPORT_MD)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


def build_gate_report(root: Path) -> JsonObject:
    cases = tuple(read_case(root, config) for config in CASES)
    wrong_safe_total = sum(case.wrong_safe_auto_grade for case in cases if case.wrong_safe_auto_grade is not None)
    transcription_cases = tuple(case for case in cases if case.transcription.available)
    feature_flag_blockers = feature_flag_blockers_for(cases)
    production_blockers = production_blockers_for(cases, transcription_cases)
    leak_scan = scan_student_payloads(root)
    if leak_scan["status"] != "passed":
        feature_flag_blockers.append("student-facing leak scan is missing, incomplete, or failed")
    return {
        "ok": len(feature_flag_blockers) == 0,
        "gate_status": "GO_FOR_FEATURE_FLAG_INTEGRATION_WITH_CONDITIONS" if not feature_flag_blockers else "BLOCKED_MISSING_OR_FAILED_EVIDENCE",
        "production_default_status": "NO_GO",
        "feature_flag_integration_allowed": len(feature_flag_blockers) == 0,
        "production_default_allowed": False,
        "preferred_strategy": "same-contact",
        "student_facing_leak_scan": leak_scan,
        "criteria": {
            "ocr_transcription_accuracy_threshold_when_available": TRANSCRIPTION_THRESHOLD,
            "ocr_transcription_threshold_is_production_diagnostic": True,
            "wrong_safe_auto_grade_required": 0,
            "missing_required": "0 or explicitly explained",
            "answer_key_accuracy_is_not_ocr_quality": True,
        },
        "aggregate": {
            "cases_included": len(cases),
            "independent_handwriting_cases": sum(1 for case in cases if case.independent_handwriting),
            "capture_condition_cases": sum(1 for case in cases if case.capture_condition_case),
            "cases_with_human_transcription": len(transcription_cases),
            "wrong_safe_auto_grade_total": wrong_safe_total,
            "missing_total": sum(case.missing for case in cases),
        },
        "cases": [case_to_json(case) for case in cases],
        "blockers": feature_flag_blockers,
        "feature_flag_blockers": feature_flag_blockers,
        "production_blockers": production_blockers,
        "missing_evidence": missing_evidence_for(cases),
        "recommended_next_action": "Resolve missing/failed evidence before integration" if feature_flag_blockers else "Feature-flag integration only; production default remains disabled",
        "validation": {"gemini_api_called": False, "submit_test_called": False, "operating_app_code_touched": False, "api_key_or_env_exposed": False},
    }


def read_case(root: Path, config: CaseConfig) -> CaseMetric:
    case_dir = root / config.directory
    eval_path = case_dir / config.eval_file
    if not eval_path.is_file():
        return missing_case_metric(config, eval_path, "missing evaluator output")
    try:
        payload = read_json_object(eval_path)
        summary = require_object(payload.get("summary"), f"{eval_path}.summary")
        for field in ("total", "safe_auto_grade", "review_required", "data_check_required", "missing", "mismatch"):
            value = summary.get(field)
            if type(value) is not int or value < 0:
                raise ValueError(f"missing or invalid metric: {field}")
    except (ValueError, TypeError, KeyError, OSError):
        return missing_case_metric(config, eval_path, "invalid evaluator metrics")
    summary = require_object(payload.get("summary"), f"{eval_path}.summary")
    total = int(summary.get("total", summary.get("total_attempted", 0)))
    completed_value = summary.get("completed", summary.get("completed_total"))
    pending_value = summary.get("pending", summary.get("pending_count"))
    if type(completed_value) is not int or type(pending_value) is not int or completed_value < 0 or pending_value < 0 or completed_value + pending_value != total:
        return missing_case_metric(config, eval_path, "missing or inconsistent completion metrics")
    completed, pending = completed_value, pending_value
    return CaseMetric(
        config.case_id,
        config.role,
        str(eval_path),
        completed,
        pending,
        total,
        number(summary.get("full_accuracy", summary.get("accuracy"))),
        int(summary.get("safe_auto_grade", 0)),
        int(summary.get("review_required", 0)),
        int(summary.get("data_check_required", 0)),
        int(summary.get("retake_required", 0)),
        int(summary.get("missing", 0)),
        int(summary.get("mismatch", 0)),
        wrong_safe_auto_grade_for(case_dir, summary),
        transcription_metric(case_dir),
        config.independent_handwriting,
        config.capture_condition_case,
        require_optional_string(summary.get("notes")),
    )


def missing_case_metric(config: CaseConfig, path: Path, note: str) -> CaseMetric:
    return CaseMetric(config.case_id, config.role, str(path), 0, 20, 20, None, 0, 0, 0, 0, 20, 0, None,
                      TranscriptionMetric(False, None, None, None, None, note),
                      config.independent_handwriting, config.capture_condition_case, note)


def wrong_safe_auto_grade_for(case_dir: Path, summary: JsonObject) -> int | None:
    human_eval_path = case_dir / "human_transcription_eval.json"
    if not human_eval_path.is_file():
        return None
    human_summary = require_object(read_json_object(human_eval_path).get("summary"), f"{human_eval_path}.summary")
    value = human_summary.get("wrong_safe_auto_grade_against_human_transcription")
    if type(value) is not int or value < 0:
        return None
    # Missing/placeholder safe claims are unsafe even if an old summary excluded them.
    items = read_json_object(human_eval_path).get("items")
    if not isinstance(items, list) or len(items) != 20:
        return None
    seen: set[int] = set()
    observed_wrong = 0
    for raw in items:
        if not isinstance(raw, dict):
            return None
        question = raw.get("question_no")
        if type(question) is not int or not 1 <= question <= 20 or question in seen:
            return None
        seen.add(question)
        if raw.get("existing_final_policy") == "safe_auto_grade":
            recognized, human = raw.get("recognized"), raw.get("human_answer")
            if not isinstance(recognized, str) or not isinstance(human, str):
                return None
            if not answers_match(recognized, human) or raw.get("human_confidence") == "low" or raw.get("policy_warnings"):
                observed_wrong += 1
    return max(value, observed_wrong)


def transcription_metric(case_dir: Path) -> TranscriptionMetric:
    human_path = case_dir / "human_transcription.json"
    if human_path.is_file() and (case_dir / "recognized.json").is_file():
        return compute_transcription_from_human(case_dir, human_path)
    eval_path = case_dir / "human_transcription_eval.json"
    if eval_path.exists():
        summary = require_object(read_json_object(eval_path).get("summary"), f"{eval_path}.summary")
        total = int(summary.get("ocr_evaluated_total", summary.get("total", 0)))
        human_total = int(summary.get("total", total))
        ambiguous = int(summary.get("ambiguous_human_label_count", max(human_total - total, 0)))
        correct_value = summary.get("exact_or_normalized_match")
        if type(correct_value) is not int or not 0 <= correct_value <= total or human_total != 20 or total <= 0:
            return TranscriptionMetric(False, None, None, None, str(eval_path), "invalid or incomplete human transcription evidence")
        rows = read_json_object(eval_path).get("items")
        if not isinstance(rows, list) or len(rows) != 20:
            return TranscriptionMetric(False, None, None, None, str(eval_path), "missing independent human evaluator rows")
        seen: set[int] = set()
        observed_correct, observed_total = 0, 0
        for row in rows:
            if not isinstance(row, dict):
                return TranscriptionMetric(False, None, None, None, str(eval_path), "invalid human evaluator row")
            question = row.get("question_no")
            if type(question) is not int or not 1 <= question <= 20 or question in seen or row.get("human_confidence") not in {"high", "low"}:
                return TranscriptionMetric(False, None, None, None, str(eval_path), "invalid human evaluator coverage")
            seen.add(question)
            recognized, human = row.get("recognized"), row.get("human_answer")
            if not isinstance(recognized, str) or not isinstance(human, str):
                return TranscriptionMetric(False, None, None, None, str(eval_path), "invalid human evaluator text")
            if row["human_confidence"] != "low":
                observed_total += 1
                observed_correct += int(answers_match(recognized, human))
        if (observed_correct, observed_total) != (correct_value, total):
            return TranscriptionMetric(False, None, None, None, str(eval_path), "cached evaluator counts conflict with current independent comparison")
        correct = correct_value
        accuracy = number(summary.get("ocr_recognition_accuracy_against_human_transcription"))
        if accuracy is None or abs(accuracy - (correct / total) * 100) > 0.02:
            return TranscriptionMetric(False, None, None, None, str(eval_path), "human transcription accuracy conflicts with counts")
        return TranscriptionMetric(True, correct, total, accuracy, str(eval_path), "human transcription evaluation available", human_total, ambiguous)
    human_path = case_dir / "human_transcription.json"
    if human_path.exists():
        return compute_transcription_from_human(case_dir, human_path)
    return TranscriptionMetric(False, None, None, None, None, "human_transcription.json unavailable")


def compute_transcription_from_human(case_dir: Path, human_path: Path) -> TranscriptionMetric:
    recognized_path = case_dir / "recognized.json"
    if not recognized_path.exists():
        return TranscriptionMetric(False, None, None, None, str(human_path), "human transcription exists but recognized.json is unavailable")
    try:
        human_answers = load_human(human_path)
        recognized_answers = load_recognized(recognized_path)
    except Exception as exc:
        return TranscriptionMetric(False, None, None, None, str(human_path), f"invalid transcription input: {type(exc).__name__}")
    high_answers = {q: answer for q, answer in human_answers.items() if answer.confidence != "low"}
    total = len(high_answers)
    correct = sum(1 for question_no, human_answer in high_answers.items() if answers_match(recognized_answers[question_no].text, human_answer.text))
    accuracy = round((correct / total) * 100, 2) if total else None
    return TranscriptionMetric(total > 0, correct, total, accuracy, str(human_path), "computed with strict key-free human evaluator", 20, 20-total)


def case_to_json(case: CaseMetric) -> JsonObject:
    data = asdict(case)
    data["transcription"]["passes_threshold"] = passes_transcription_gate(case.transcription)
    data["passes_wrong_safe_gate"] = case.wrong_safe_auto_grade == 0
    data["missing_explanation"] = missing_explanation(case)
    return data


def feature_flag_blockers_for(cases: tuple[CaseMetric, ...]) -> list[str]:
    blockers: list[str] = []
    if not cases:
        blockers.append("no benchmark cases were evaluated")
    if any(case.wrong_safe_auto_grade is None for case in cases):
        blockers.append("wrong_safe_auto_grade evidence is missing or invalid")
    if any(case.wrong_safe_auto_grade not in {None, 0} for case in cases):
        blockers.append("wrong_safe_auto_grade is nonzero in at least one case")
    if any(case.total != 20 or case.completed != 20 or case.pending or case.missing for case in cases):
        blockers.append("required full 20-question evaluation is incomplete")
    if any(case.missing != 0 and not missing_explanation(case) for case in cases):
        blockers.append("missing answers exist without an explicit explanation")
    if any(case.independent_handwriting and not case.transcription.available for case in cases):
        blockers.append("independent handwriting case is missing human transcription evaluation")
    return blockers


def production_blockers_for(cases: tuple[CaseMetric, ...], transcription_cases: tuple[CaseMetric, ...]) -> list[str]:
    blockers: list[str] = []
    if any(not passes_transcription_gate(case.transcription) for case in transcription_cases):
        blockers.append("OCR transcription accuracy below 90% where human transcription exists")
    blockers.append("Production readiness still needs more independent handwriting cases with human transcription evaluation")
    blockers.append("photo_1/photo_2 are capture-condition checks, not independent handwriting evidence")
    return blockers


def missing_evidence_for(cases: tuple[CaseMetric, ...]) -> list[str]:
    return [
        *(f"{case.case_id}: independent handwriting human_transcription unavailable" for case in cases if case.independent_handwriting and not case.transcription.available),
        "photo_1/photo_2 are capture-condition-only cases; they are not counted as independent handwriting evidence",
        "More independent handwriting cases with human_transcription evaluation",
        "Operator review UX evidence for data_check_required cases before production default",
    ]


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), str(path))


def human_answer_map(payload: JsonObject) -> dict[int, str]:
    return {
        int(row["question_no"]): require_string(row.get("human_answer"), "human_answer")
        for item in require_array(payload.get("answers"), "human.answers")
        for row in [require_object(item, "human.answers[]")]
    }


def recognized_answer_map(payload: JsonObject) -> dict[int, str]:
    return {
        int(row.get("question", row.get("question_no", 0))): require_string(row.get("recognized"), "recognized")
        for item in require_array(payload.get("items"), "recognized.items")
        for row in [require_object(item, "recognized.items[]")]
    }


def passes_transcription_gate(metric: TranscriptionMetric) -> bool | None:
    if not metric.available or metric.accuracy_percent is None:
        return None
    return metric.accuracy_percent >= TRANSCRIPTION_THRESHOLD


def missing_explanation(case: CaseMetric) -> str:
    if case.missing == 0:
        return "none"
    if case.pending > 0:
        return "partial capture-condition run has pending questions"
    return ""


def normalize(value: str) -> str:
    return normalize_answer(value)


def scan_payload_for_leaks(payload: object) -> dict:
    forbidden = {"expected", "canonical_answer", "accepted_answers", "answer_key", "grading", "crop_path", "source_path", "source_image", "contact_dir", "cache_path", "raw_path"}
    field_hits = 0
    path_hits = 0
    def walk(value: object) -> None:
        nonlocal field_hits, path_hits
        if isinstance(value, dict):
            for key, child in value.items():
                field_hits += int(str(key).casefold() in forbidden)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str):
            path_hits += int(bool(re.search(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|file://|\\\\[A-Za-z0-9]|(?:^|\s)/(?:home|tmp|server|users)/", value, re.I)))
    walk(payload)
    return {"status": "failed" if field_hits or path_hits else "passed", "forbidden_field_hits": field_hits, "path_leak_hits": path_hits}


def scan_student_payloads(root: Path) -> dict:
    scans = []
    for config in CASES:
        path = root / config.directory / "student_review_payload.json"
        if not path.is_file():
            return {"status": "not_run", "reason": "required student-facing payload unavailable", "forbidden_field_hits": None, "path_leak_hits": None}
        scans.append(scan_payload_for_leaks(read_json_object(path)))
    field_hits = sum(item["forbidden_field_hits"] for item in scans)
    path_hits = sum(item["path_leak_hits"] for item in scans)
    return {"status": "passed" if scans and not field_hits and not path_hits else "failed", "forbidden_field_hits": field_hits, "path_leak_hits": path_hits, "scanned_payloads": len(scans)}


def number(value: JsonValue) -> float | None:
    match value:
        case int() | float() if not isinstance(value, bool):
            return float(value)
        case None:
            return None
        case str():
            return float(value)
        case bool() | list() | dict():
            return None
        case unreachable:
            assert_never(unreachable)


def require_optional_string(value: JsonValue) -> str:
    match value:
        case str():
            return value
        case None:
            return ""
        case bool() | int() | float() | list() | dict():
            return ""
        case unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    raise SystemExit(main())
