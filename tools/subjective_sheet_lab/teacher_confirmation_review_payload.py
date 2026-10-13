# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from tools.subjective_sheet_lab.ocr_answer_mode_policy import answer_mode_auto_grade_warning

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
QUESTION_COUNT: Final[int] = 20
UNRESOLVED_QUESTIONS: Final[frozenset[int]] = frozenset((3, 16, 17))


@dataclass(frozen=True, slots=True)
class PayloadError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class CliConfig:
    fresh_recognized: Path
    second_pass_recognized: Path
    out_path: Path


def main() -> int:
    config = parse_args()
    payload = build_payload(config)
    write_payload(config.out_path, payload)
    print(
        json.dumps(
            {
                "ok": True,
                "out_path": str(config.out_path),
                "item_count": QUESTION_COUNT,
                "safe_auto_grade_count": 0,
                "provider_call_count": 0,
            },
            ensure_ascii=False,
        ),
    )
    return 0


def parse_args() -> CliConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh-recognized", required=True, type=Path)
    parser.add_argument("--second-pass-recognized", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    return CliConfig(
        fresh_recognized=args.fresh_recognized.resolve(),
        second_pass_recognized=args.second_pass_recognized.resolve(),
        out_path=args.out.resolve(),
    )


def build_payload(config: CliConfig) -> dict[str, JsonValue]:
    fresh = recognized_by_question(config.fresh_recognized)
    second_pass = recognized_by_question(config.second_pass_recognized)
    recovered_q018 = second_pass.get(18, "?")
    if answer_mode_auto_grade_warning(18, recovered_q018, TEST_ID) is not None:
        raise PayloadError("q018 second-pass value is not a valid review candidate")
    items = [review_item(question_no, fresh.get(question_no, "?"), recovered_q018) for question_no in range(1, QUESTION_COUNT + 1)]
    return {
        "ok": True,
        "review_payload": {
            "source": "teacher_confirmation_review_payload",
            "test_id": TEST_ID,
            "round": "1",
            "problem_count": QUESTION_COUNT,
            "items": items,
        },
        "review_meta": {
            "photo_correction": "completed",
            "answer_box_extraction": "completed",
            "answer_box_source": "isolated_lab",
            "provider_input": "not_called",
            "crop_count": QUESTION_COUNT,
            "contact_sheet_count": 4,
            "cache_status": "hit",
            "cache_source": "teacher_confirmation",
            "provider_status": "disabled",
            "provider_call_count": 0,
        },
    }


def recognized_by_question(path: Path) -> dict[int, str]:
    payload = read_object(path)
    items = payload.get("items")
    if not isinstance(items, list):
        raise PayloadError(f"{path.name} items must be a list")
    output: dict[int, str] = {}
    for raw in items:
        if not isinstance(raw, dict):
            raise PayloadError(f"{path.name} item must be an object")
        question = raw.get("question")
        recognized = raw.get("recognized")
        if not isinstance(question, int) or isinstance(question, bool) or question < 1 or question > QUESTION_COUNT:
            raise PayloadError(f"{path.name} question must be 1..20")
        if question in output:
            raise PayloadError(f"{path.name} contains duplicate question {question}")
        if not isinstance(recognized, str) or "\n" in recognized or "\r" in recognized:
            raise PayloadError(f"{path.name} recognized value must be single-line text")
        output[question] = recognized.strip() or "?"
    return output


def read_object(path: Path) -> dict[str, JsonValue]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise PayloadError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise PayloadError(f"{path.name} must be an object")
    return value


def review_item(question_no: int, fresh_value: str, recovered_q018: str) -> dict[str, JsonValue]:
    recognized = recognized_value(question_no, fresh_value, recovered_q018)
    warning = warning_for(question_no, recognized)
    candidate = candidate_for(question_no, recognized, warning)
    return {
        "question_no": question_no,
        "status": "review_required",
        "recognized": recognized,
        "warnings": [warning],
        "candidates": [candidate] if candidate is not None else [],
        "final_answer": None,
        "source": None,
    }


def recognized_value(question_no: int, fresh_value: str, recovered_q018: str) -> str:
    if question_no in UNRESOLVED_QUESTIONS:
        return "?"
    if question_no == 18:
        return recovered_q018
    return fresh_value


def warning_for(question_no: int, recognized: str) -> str:
    if question_no == 3:
        return "unresolved_after_second_pass"
    if question_no in {16, 17}:
        return "unresolved_first_pass"
    if question_no == 18:
        return "second_pass_recovered_requires_teacher_confirmation"
    warning = answer_mode_auto_grade_warning(question_no, recognized, TEST_ID)
    return warning if warning is not None else "teacher_confirmation_required"


def candidate_for(question_no: int, recognized: str, warning: str) -> str | None:
    if question_no in UNRESOLVED_QUESTIONS:
        return None
    if warning != "teacher_confirmation_required" and question_no != 18:
        return None
    return recognized if answer_mode_auto_grade_warning(question_no, recognized, TEST_ID) is None else None


def write_payload(path: Path, payload: dict[str, JsonValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
