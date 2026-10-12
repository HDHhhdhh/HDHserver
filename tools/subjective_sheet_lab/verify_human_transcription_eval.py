# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_human_transcription_eval.py --case-dir C:\server-ocr\gemini_outputs\<case>_same_contact

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

REQUIRED_FILES: Final[tuple[str, ...]] = (
    "human_transcription.json",
    "human_transcription_eval.json",
    "human_transcription_eval.csv",
    "human_transcription_eval.md",
    "combined_case_interpretation.md",
)
SECRET_PATTERN: Final[re.Pattern[str]] = re.compile(r"AIza|GEMINI_" + "API_KEY|x-goog-api-key|sk-[A-Za-z0-9]")


class VerifyHumanEvalError(Exception):
    pass


def main() -> int:
    case_dir = parse_args()
    check_required_files(case_dir)
    human = read_json_object(case_dir / "human_transcription.json")
    eval_payload = read_json_object(case_dir / "human_transcription_eval.json")
    validate_human_transcription(case_dir / "human_transcription.json", human)
    validate_audience(eval_payload)
    validate_summary(eval_payload)
    validate_source_hashes(eval_payload)
    validate_no_forbidden_text(case_dir)
    print(json.dumps({"ok": True, "case_dir": str(case_dir)}, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> Path:
    parser = argparse.ArgumentParser(description="Verify human transcription OCR evaluation outputs without API calls.")
    parser.add_argument("--case-dir", required=True, type=Path)
    return parser.parse_args().case_dir.resolve()


def check_required_files(case_dir: Path) -> None:
    missing = [name for name in REQUIRED_FILES if not (case_dir / name).is_file()]
    if missing:
        raise VerifyHumanEvalError(f"missing output file(s): {', '.join(missing)}")


def read_json_object(path: Path) -> dict[str, JsonValue]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise VerifyHumanEvalError(f"{path} must contain a JSON object")
    return payload


def validate_human_transcription(path: Path, payload: dict[str, JsonValue]) -> None:
    answers = payload.get("answers")
    if not isinstance(answers, list):
        raise VerifyHumanEvalError(f"{path} must contain answers list")
    questions: list[int] = []
    for index, answer in enumerate(answers, start=1):
        if not isinstance(answer, dict):
            raise VerifyHumanEvalError(f"{path} answer {index} must be an object")
        forbidden = {"expected", "canonical_answer", "accepted_answers"}.intersection(answer)
        if forbidden:
            raise VerifyHumanEvalError(f"{path} answer {index} leaks forbidden key(s): {', '.join(sorted(forbidden))}")
        questions.append(int(answer.get("question_no", 0)))
    if sorted(questions) != list(range(1, 21)):
        raise VerifyHumanEvalError(f"{path} must contain exactly question_no 1..20")


def validate_summary(payload: dict[str, JsonValue]) -> None:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise VerifyHumanEvalError("human_transcription_eval.json missing summary")
    required = {
        "total",
        "ocr_evaluated_total",
        "exact_or_normalized_match",
        "mismatch_vs_human",
        "mismatch_vs_expected",
        "missing",
        "ambiguous_human_label_count",
        "ocr_recognition_accuracy_against_human_transcription",
        "answer_key_grading_accuracy_recognized_vs_expected",
        "source_wrong_safe_auto_grade_against_human_transcription",
        "wrong_safe_auto_grade_against_human_transcription",
        "safe_auto_grade",
        "review_required",
        "data_check_required",
    }
    missing = sorted(required.difference(summary))
    if missing:
        raise VerifyHumanEvalError(f"summary missing key(s): {', '.join(missing)}")
    if int(summary["total"]) != 20:
        raise VerifyHumanEvalError("summary total must be 20")


def validate_audience(payload: dict[str, JsonValue]) -> None:
    if payload.get("audience") != "developer_lab_only" or payload.get("student_facing") is not False:
        raise VerifyHumanEvalError("human_transcription_eval.json must be marked developer_lab_only and non-student-facing")


def validate_source_hashes(payload: dict[str, JsonValue]) -> None:
    raw_hashes = payload.get("source_hashes")
    if not isinstance(raw_hashes, list):
        raise VerifyHumanEvalError("human_transcription_eval.json missing source_hashes")
    for index, raw_hash in enumerate(raw_hashes, start=1):
        if not isinstance(raw_hash, dict):
            raise VerifyHumanEvalError(f"source_hashes item {index} must be an object")
        path = Path(str(raw_hash.get("path", "")))
        expected_hash = str(raw_hash.get("sha256", ""))
        if not path.is_file():
            raise VerifyHumanEvalError(f"source hash file missing: {path}")
        if sha256(path) != expected_hash:
            raise VerifyHumanEvalError(f"source file changed after eval: {path}")


def validate_no_forbidden_text(case_dir: Path) -> None:
    for name in REQUIRED_FILES:
        text = (case_dir / name).read_text(encoding="utf-8-sig", errors="replace")
        if SECRET_PATTERN.search(text):
            raise VerifyHumanEvalError(f"secret-like token found in {name}")
        if "/api/" + "submit-test" in text:
            raise VerifyHumanEvalError(f"submit endpoint string found in {name}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
