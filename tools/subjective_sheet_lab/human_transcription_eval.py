# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\human_transcription_eval.py --case-dir C:\server-ocr\gemini_outputs\<case>_same_contact --expected C:\server-ocr\crop_benchmark_inputs\<case>\expected.json

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from human_transcription_eval_reports import summary_to_dict, write_outputs
from ocr_relation_ambiguity import any_relation_ambiguity_warnings

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

OUTPUT_STEM: Final[str] = "human_transcription_eval"
FORBIDDEN_SECRET_RE: Final[re.Pattern[str]] = re.compile(r"AIza|GEMINI_" + "API_KEY|x-goog-api-key|sk-[A-Za-z0-9]")


class HumanEvalError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CliConfig:
    case_dir: Path
    expected_path: Path
    recognized_path: Path
    human_path: Path


@dataclass(frozen=True, slots=True)
class Answer:
    question_no: int
    text: str
    confidence: str = "high"
    notes: str = ""
    needs_review: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnswerMapSpec:
    list_key: str
    question_key: str
    answer_key: str
    require_complete: bool = False


@dataclass(frozen=True, slots=True)
class SourceHash:
    role: str
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class EvalRow:
    question_no: int
    human_answer: str
    human_confidence: str
    recognized: str
    expected: str
    match_to_human: bool
    match_to_expected: bool
    source_final_policy: str
    existing_final_policy: str
    policy_warnings: tuple[str, ...]
    crop_path: str
    notes: str


@dataclass(frozen=True, slots=True)
class EvalSummary:
    total: int
    ocr_evaluated_total: int
    exact_or_normalized_match: int
    mismatch_vs_human: int
    mismatch_vs_expected: int
    missing: int
    ambiguous_human_label_count: int
    ocr_recognition_accuracy_against_human_transcription: float
    answer_key_grading_accuracy_recognized_vs_expected: float
    source_wrong_safe_auto_grade_against_human_transcription: int
    wrong_safe_auto_grade_against_human_transcription: int
    safe_auto_grade: int
    review_required: int
    data_check_required: int


def main() -> int:
    config = parse_args()
    expected = load_expected(config.expected_path)
    recognized = load_recognized(config.recognized_path)
    human = load_human(config.human_path)
    policies = load_existing_policies(config.case_dir)
    rows = evaluate_rows(config, expected, recognized, human, policies)
    summary = summarize(rows)
    source_hashes = hash_sources(config)
    assert_no_forbidden_output_strings(rows)
    write_outputs(config, summary, rows, source_hashes)
    complete = summary.total == 20 and summary.ocr_evaluated_total == 20 and summary.missing == 0
    print(json.dumps({"ok": complete, "evaluation_complete": complete, "summary": summary_to_dict(summary), "out_dir": str(config.case_dir)}, ensure_ascii=False, indent=2))
    return 0 if complete else 1


def parse_args() -> CliConfig:
    parser = argparse.ArgumentParser(description="Compare recognized OCR against expected answers and human visual transcription.")
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--recognized", type=Path)
    parser.add_argument("--human", type=Path)
    args = parser.parse_args()
    case_dir = args.case_dir.resolve()
    return CliConfig(
        case_dir=case_dir,
        expected_path=args.expected.resolve(),
        recognized_path=(args.recognized or case_dir / "recognized.json").resolve(),
        human_path=(args.human or case_dir / "human_transcription.json").resolve(),
    )


def load_expected(path: Path) -> dict[int, Answer]:
    return load_answer_map(path, AnswerMapSpec("items", "question", "expected", require_complete=True))


def load_recognized(path: Path) -> dict[int, Answer]:
    return load_answer_map(path, AnswerMapSpec("items", "question", "recognized", require_complete=True))


def load_answer_map(path: Path, spec: AnswerMapSpec) -> dict[int, Answer]:
    payload = read_json_object(path)
    raw_items = payload.get(spec.list_key)
    if not isinstance(raw_items, list):
        raise HumanEvalError(f"{path} must contain a {spec.list_key} list")
    answers: dict[int, Answer] = {}
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise HumanEvalError(f"{path} item {index} must be an object")
        question = require_question(raw.get(spec.question_key), path)
        if question in answers:
            raise HumanEvalError(f"{path} contains duplicate question {question}")
        text = raw.get(spec.answer_key)
        if not isinstance(text, str):
            raise HumanEvalError(f"{path} question {question} requires a string {spec.answer_key}")
        needs_review = raw.get("needs_review", False)
        uncertainty = raw.get("uncertainty", "clear")
        if not isinstance(uncertainty, str):
            raise HumanEvalError(f"{path} question {question} has invalid uncertainty")
        if not isinstance(needs_review, bool):
            raise HumanEvalError(f"{path} question {question} has invalid needs_review")
        needs_review = needs_review or uncertainty not in {"none", "clear"}
        warnings = raw.get("warnings", [])
        if not isinstance(needs_review, bool) or not isinstance(warnings, list) or any(not isinstance(w, str) for w in warnings):
            raise HumanEvalError(f"{path} question {question} has invalid review metadata")
        answers[question] = Answer(question, text.strip(), needs_review=needs_review, warnings=tuple(warnings))
    if spec.require_complete:
        validate_complete_questions(path, answers)
    return answers


def load_human(path: Path) -> dict[int, Answer]:
    payload = read_json_object(path)
    raw_answers = payload.get("answers")
    if not isinstance(raw_answers, list):
        raise HumanEvalError(f"{path} must contain an answers list")
    answers: dict[int, Answer] = {}
    for index, raw in enumerate(raw_answers, start=1):
        if not isinstance(raw, dict):
            raise HumanEvalError(f"{path} answer {index} must be an object")
        forbidden = {"expected", "canonical_answer", "accepted_answers"}.intersection(raw)
        if forbidden:
            raise HumanEvalError(f"{path} answer {index} contains forbidden key(s): {', '.join(sorted(forbidden))}")
        question = require_question(raw.get("question_no"), path)
        if question in answers:
            raise HumanEvalError(f"{path} contains duplicate question_no {question}")
        text = raw.get("human_answer")
        confidence = raw.get("confidence", "high")
        notes = raw.get("notes", "")
        if not isinstance(text, str) or not isinstance(notes, str) or not isinstance(confidence, str) or confidence not in {"high", "low"}:
            raise HumanEvalError(f"{path} question {question} has invalid human transcription metadata")
        if text.strip() in {"", "?"} and confidence == "high":
            raise HumanEvalError(f"{path} question {question} cannot have a high-confidence placeholder")
        text, notes = text.strip(), notes.strip()
        answers[question] = Answer(question, text, confidence, notes)
    validate_complete_questions(path, answers)
    return answers


def validate_complete_questions(path: Path, answers: dict[int, Answer]) -> None:
    questions = sorted(answers)
    if len(questions) != 20 or questions != list(range(1, 21)):
        raise HumanEvalError(f"{path} must contain exactly question_no 1..20 once")


def require_question(value: object, path: Path) -> int:
    if type(value) is not int or not 1 <= value <= 20:
        raise HumanEvalError(f"{path} question must be an integer in 1..20 (bool is invalid)")
    return value


def read_json_object(path: Path) -> dict[str, JsonValue]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise HumanEvalError(f"{path} must contain a JSON object")
    return payload


def load_existing_policies(case_dir: Path) -> dict[int, str]:
    for name in ("same_contact_final_eval.json", "final_eval_q001_q020.json", "same_contact_review_policy_eval.json"):
        path = case_dir / name
        if path.is_file():
            return policy_map_from(path)
    return {}


def policy_map_from(path: Path) -> dict[int, str]:
    payload = read_json_object(path)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise HumanEvalError(f"{path} must contain an items list")
    output: dict[int, str] = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise HumanEvalError(f"{path} policy item must be an object")
        question = require_question(raw.get("question", raw.get("question_no")), path)
        if question in output:
            raise HumanEvalError(f"{path} contains duplicate policy question {question}")
        policy = raw.get("review_policy", raw.get("policy", raw.get("status", "")))
        if not isinstance(policy, str):
            raise HumanEvalError(f"{path} policy must be a string")
        output[question] = policy
    return output


def evaluate_rows(config: CliConfig, expected: dict[int, Answer], recognized: dict[int, Answer], human: dict[int, Answer], policies: dict[int, str]) -> tuple[EvalRow, ...]:
    rows: list[EvalRow] = []
    crop_dir = infer_crop_dir(config)
    for question in range(1, 21):
        human_answer = human[question]
        recognized_answer = recognized.get(question, Answer(question, "?"))
        expected_answer = expected.get(question, Answer(question, ""))
        source_policy = policies.get(question, "")
        policy_warnings = tuple(dict.fromkeys((
            *any_relation_ambiguity_warnings(expected_answer.text, recognized_answer.text, human_answer.text),
            *recognized_answer.warnings,
            *(("missing",) if recognized_answer.text.strip() in {"", "?"} else ()),
            *(("model_needs_review",) if recognized_answer.needs_review else ()),
            *(("ambiguous_human_label",) if human_answer.confidence == "low" else ()),
        )))
        rows.append(
            EvalRow(
                question_no=question,
                human_answer=human_answer.text,
                human_confidence=human_answer.confidence,
                recognized=recognized_answer.text,
                expected=expected_answer.text,
                match_to_human=answers_match(recognized_answer.text, human_answer.text),
                match_to_expected=answers_match(recognized_answer.text, expected_answer.text),
                source_final_policy=source_policy,
                existing_final_policy=effective_policy_for(source_policy, policy_warnings),
                policy_warnings=policy_warnings,
                crop_path=str(crop_dir / f"q{question:03d}.png") if crop_dir is not None else "",
                notes=human_answer.notes,
            ),
        )
    return tuple(rows)


def effective_policy_for(source_policy: str, policy_warnings: tuple[str, ...]) -> str:
    if source_policy == "safe_auto_grade" and policy_warnings:
        return "review_required"
    return source_policy


def infer_crop_dir(config: CliConfig) -> Path | None:
    case_name = config.case_dir.name.removesuffix("_same_contact")
    candidate = Path(r"C:\server-ocr\crop_benchmark_inputs") / case_name / "crops"
    return candidate if candidate.is_dir() else None


def answers_match(left: str, right: str) -> bool:
    if not left.strip() or "?" in left or not right.strip() or "?" in right:
        return False
    return normalize(left) == normalize(right)


def normalize(value: str) -> str:
    cleaned = value.strip().lower().replace("\\sqrt", "sqrt").replace("√", "sqrt")
    # Preserve token boundaries: '2 3' and '2*3' must not become '23'.
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s*([+*/^=<>(),{}\[\]\-])\s*", r"\1", cleaned)
    cleaned = re.sub(r"sqrt\{([^{}]+)\}", r"sqrt(\1)", cleaned)
    return re.sub(r"sqrt(?![({])([a-z0-9]+)", r"sqrt(\1)", cleaned)


def summarize(rows: tuple[EvalRow, ...]) -> EvalSummary:
    total = len(rows)
    evaluated_rows = tuple(row for row in rows if row.human_confidence.casefold() != "low")
    ambiguous = total - len(evaluated_rows)
    evaluated = len(evaluated_rows)
    human_matches = sum(1 for row in evaluated_rows if row.match_to_human)
    expected_matches = sum(1 for row in rows if row.match_to_expected)
    missing = sum(1 for row in rows if row.recognized in {"", "?"})
    return EvalSummary(
        total=total,
        ocr_evaluated_total=evaluated,
        exact_or_normalized_match=human_matches,
        mismatch_vs_human=sum(1 for row in evaluated_rows if not row.match_to_human and row.recognized not in {"", "?"}),
        mismatch_vs_expected=total - expected_matches - missing,
        missing=missing,
        ambiguous_human_label_count=ambiguous,
        ocr_recognition_accuracy_against_human_transcription=round((human_matches / evaluated) * 100, 2) if evaluated else 0.0,
        answer_key_grading_accuracy_recognized_vs_expected=round((expected_matches / total) * 100, 2) if total else 0.0,
        source_wrong_safe_auto_grade_against_human_transcription=sum(1 for row in rows if row.source_final_policy == "safe_auto_grade" and (not row.match_to_human or row.human_confidence == "low" or row.policy_warnings)),
        wrong_safe_auto_grade_against_human_transcription=sum(1 for row in rows if row.existing_final_policy == "safe_auto_grade" and (not row.match_to_human or row.human_confidence == "low" or row.policy_warnings)),
        safe_auto_grade=sum(1 for row in rows if row.existing_final_policy == "safe_auto_grade"),
        review_required=sum(1 for row in rows if row.existing_final_policy == "review_required"),
        data_check_required=sum(1 for row in rows if row.existing_final_policy == "data_check_required"),
    )


def hash_sources(config: CliConfig) -> tuple[SourceHash, ...]:
    candidates = (
        ("recognized", config.recognized_path),
        ("human_transcription", config.human_path),
        ("expected", config.expected_path),
        ("cache", config.case_dir / "gemini_provider_cache.json"),
        ("same_contact_final_eval", config.case_dir / "same_contact_final_eval.json"),
        ("final_eval", config.case_dir / "final_eval_q001_q020.json"),
        ("policy_eval", config.case_dir / "same_contact_review_policy_eval.json"),
    )
    return tuple(SourceHash(role, str(path), sha256(path)) for role, path in candidates if path.is_file())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_no_forbidden_output_strings(rows: tuple[EvalRow, ...]) -> None:
    for row in rows:
        if FORBIDDEN_SECRET_RE.search(row.human_answer + row.recognized + row.expected + row.notes):
            raise HumanEvalError(f"forbidden secret-like text in q{row.question_no:03d}")


if __name__ == "__main__":
    raise SystemExit(main())
