# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from tools.subjective_sheet_lab.ocr_answer_mode_policy import answer_mode_auto_grade_warning

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    ("expected", "canonical_answer", "accepted_answers", "grading", "answer_key", "path", "source_path")
)
PATH_RE: Final[re.Pattern[str]] = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|file:|/(?:Users|home|var|tmp|server|mnt|opt|private)/)", re.IGNORECASE)
TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"


@dataclass(frozen=True, slots=True)
class VerificationError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def main() -> int:
    path = parse_args()
    payload = read_object(path)
    summary = verify_payload(payload)
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True, type=Path)
    return parser.parse_args().payload.resolve()


def read_object(path: Path) -> dict[str, JsonValue]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot read payload: {error}") from error
    if not isinstance(value, dict):
        raise VerificationError("payload must be an object")
    return value


def verify_payload(wrapped: dict[str, JsonValue]) -> dict[str, JsonValue]:
    find_forbidden(wrapped)
    payload = wrapped.get("review_payload")
    if not isinstance(payload, dict):
        raise VerificationError("review_payload must be an object")
    if payload.get("test_id") != TEST_ID or payload.get("round") != "1":
        raise VerificationError("test/round mismatch")
    if payload.get("problem_count") != 20:
        raise VerificationError("problem_count must be 20")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 20:
        raise VerificationError("items must contain 20 entries")
    by_question: dict[int, dict[str, JsonValue]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            raise VerificationError("item must be an object")
        question = raw.get("question_no")
        if not isinstance(question, int) or isinstance(question, bool) or question < 1 or question > 20:
            raise VerificationError("question_no must be 1..20")
        if question in by_question:
            raise VerificationError(f"duplicate question_no {question}")
        by_question[question] = raw
    if sorted(by_question) != list(range(1, 21)):
        raise VerificationError("question sequence must be 1..20")
    candidate_questions: list[int] = []
    direct_input_questions: list[int] = []
    for question, item in sorted(by_question.items()):
        if item.get("status") != "review_required":
            raise VerificationError(f"q{question:03d} must remain review_required")
        if item.get("final_answer") is not None or item.get("source") is not None:
            raise VerificationError(f"q{question:03d} must not contain a final answer or source")
        candidates = item.get("candidates")
        if not isinstance(candidates, list):
            raise VerificationError(f"q{question:03d}.candidates must be a list")
        for candidate in candidates:
            if not isinstance(candidate, str) or answer_mode_auto_grade_warning(question, candidate, TEST_ID) is not None:
                raise VerificationError(f"q{question:03d} contains invalid candidate")
        if candidates:
            candidate_questions.append(question)
        else:
            direct_input_questions.append(question)
    if by_question[3].get("candidates") != []:
        raise VerificationError("q003 must stay unresolved without a candidate")
    q018_candidates = by_question[18].get("candidates")
    if not isinstance(q018_candidates, list) or len(q018_candidates) != 1:
        raise VerificationError("q018 must expose exactly one teacher-confirmation candidate")
    return {
        "payload_item_count": 20,
        "safe_auto_grade_count": 0,
        "candidate_control_count": len(candidate_questions),
        "direct_input_control_count": len(direct_input_questions),
        "candidate_questions": candidate_questions,
        "direct_input_questions": direct_input_questions,
        "q003_auto_fill": 0,
        "q018_auto_fill": 0,
        "forbidden_field_count": 0,
        "path_leak_count": 0,
    }


def find_forbidden(value: JsonValue) -> None:
    match value:
        case str() if PATH_RE.search(value.strip()):
            raise VerificationError("payload contains a path-like value")
        case str() | None | bool() | int() | float():
            return
        case list():
            for item in value:
                find_forbidden(item)
        case dict():
            for key, child in value.items():
                if key in FORBIDDEN_KEYS:
                    raise VerificationError(f"payload contains forbidden key {key}")
                find_forbidden(child)


if __name__ == "__main__":
    raise SystemExit(main())
