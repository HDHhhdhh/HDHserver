# /// script
# requires-python = ">=3.11"
# ///
#
# --- How to run ---
# python tools/subjective_sheet_lab/verify_final_review_payload_bridge.py

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Final, TypeAlias

from final_review_payload_bridge import (
    BridgeError,
    BridgeResult,
    convert_json_payload,
    find_forbidden_answer_key_paths,
)

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]

ROOT: Final = Path(__file__).resolve().parent
FIXTURE_PATH: Final = ROOT / "final_review_payload_bridge_fixture.json"
ANSWERS_TEXT_PATH: Final = ROOT / "final_review_payload_answersText.txt"
REPORT_PATH: Final = ROOT / "final_review_payload_bridge_report.md"
FIXTURE_MULTI_CHARACTER_ANSWERS: Final = frozenset(
    {"1<=x<=3", "-1<x<5", "1/2,9/2", "129/2", "x+2=4", "26sqrt(21)"},
)
PARSER_AUDIT_MULTI_DIGIT_ANSWERS: Final = frozenset({"12", "64", "42"})


def read_json(path: Path) -> JsonValue:
    return json.loads(path.read_text(encoding="utf-8"))


def require_object(value: JsonValue, label: str) -> JsonObject:
    if isinstance(value, dict):
        return value
    msg = f"{label} must be a JSON object"
    raise AssertionError(msg)


def require_list(value: JsonValue, label: str) -> list[JsonValue]:
    if isinstance(value, list):
        return value
    msg = f"{label} must be a JSON array"
    raise AssertionError(msg)


def require_str(value: JsonValue, label: str) -> str:
    if isinstance(value, str):
        return value
    msg = f"{label} must be a string"
    raise AssertionError(msg)


def case_payload(base_payload: JsonObject, blocker_case: JsonObject) -> JsonObject:
    payload = deepcopy(base_payload)
    items = require_list(payload.get("items"), "valid_payload.items")
    question_no = blocker_case.get("override_question_no")
    override = require_object(blocker_case.get("override"), "blocker_case.override")
    for item_value in items:
        item = require_object(item_value, "payload item")
        if item.get("question_no") == question_no:
            item.update(override)
            return payload
    msg = f"question {question_no} not found in fixture"
    raise AssertionError(msg)


def assert_bridge_error(payload: JsonObject, error_text: str) -> None:
    try:
        convert_json_payload(payload)
    except BridgeError as exc:
        if error_text not in str(exc):
            msg = f"wanted error containing {error_text!r}, got {exc!s}"
            raise AssertionError(msg) from exc
        return
    msg = f"wanted BridgeError containing {error_text!r}"
    raise AssertionError(msg)


def assert_answers_text_newline_policy(
    result: BridgeResult,
    expected_multi_character_answers: frozenset[str],
) -> None:
    lines = result.answers_text.split("\n")
    if len(lines) != result.problem_count:
        msg = f"expected {result.problem_count} newline-separated lines, got {len(lines)}"
        raise AssertionError(msg)
    if any(not line for line in lines):
        msg = "answersText contains an empty line"
        raise AssertionError(msg)
    expected_lines = [item.final_answer for item in result.items]
    if lines != expected_lines:
        msg = "answersText lines do not preserve q001..q020 item order"
        raise AssertionError(msg)
    if "\n".join(lines) != result.answers_text:
        msg = "answersText is not a plain newline join of final answers"
        raise AssertionError(msg)
    missing = sorted(expected_multi_character_answers.difference(lines))
    if missing:
        msg = f"multi-character answers were not preserved as complete lines: {', '.join(missing)}"
        raise AssertionError(msg)


def build_report(
    answers_text: str,
    blocker_names: list[str],
    leak_paths: list[str],
    final_sources: list[str],
) -> str:
    escaped_answers = answers_text.replace("\n", "\\n")
    blocker_lines = "\n".join(f"- {name}" for name in blocker_names)
    leak_line = "none" if not leak_paths else ", ".join(leak_paths)
    source_lines = "\n".join(f"- {source}" for source in final_sources)
    return f"""# Final Review Payload Bridge Report

## Scope

- Lab-only verification.
- No Gemini/API call.
- No `/api/submit-test` call.
- No operating app files modified.

## Result

- Valid fixture converted to ordered `answersText`.
- Output is exactly 20 newline-separated lines, one answer per question.
- 20-question order is stable from q001 through q020.
- Multi-character answers remain intact as single lines.
- Parser-audit multi-digit answers `12`, `64`, and `42` remain intact as separate lines.
- Concatenated digit output is not used.
- Blocking states rejected conversion.
- Safe auto-graded and student-confirmed answers are both included.
- Answer-key leak scan: {leak_line}.

## Final Sources Included

{source_lines}

## answersText

```text
{answers_text}
```

Escaped one-line form:

```text
{escaped_answers}
```

## Blocking Cases Verified

{blocker_lines}
"""


def main() -> int:
    raw = require_object(read_json(FIXTURE_PATH), "fixture")
    valid_payload = require_object(raw.get("valid_payload"), "fixture.valid_payload")
    golden_answers_text = require_str(
        raw.get("golden_answers_text"),
        "fixture.golden_answers_text",
    )
    blocker_cases = require_list(raw.get("blocker_cases"), "fixture.blocker_cases")

    # Given: a student-safe final review payload fixture.
    # When: scanning it for answer-key-only fields.
    # Then: no expected/canonical/accepted answer fields are present.
    leak_paths = find_forbidden_answer_key_paths(valid_payload)
    if leak_paths:
        msg = f"fixture leaks answer-key fields: {', '.join(leak_paths)}"
        raise AssertionError(msg)

    # Given: a complete 20-question final review payload in shuffled item order.
    # When: converting it to answersText.
    # Then: answers are emitted in question number order.
    result = convert_json_payload(valid_payload)
    if result.problem_count != 20:
        msg = f"expected 20 questions, got {result.problem_count}"
        raise AssertionError(msg)
    if result.answers_text != golden_answers_text:
        msg = "answersText did not match expected question order"
        raise AssertionError(msg)
    assert_answers_text_newline_policy(result, FIXTURE_MULTI_CHARACTER_ANSWERS)

    # Given: the parser-audit multi-digit answers that are unsafe when concatenated.
    # When: converting them through the bridge.
    # Then: they remain one complete answer per newline-separated line.
    multi_digit_payload: JsonObject = {
        "problem_count": 3,
        "items": [
            {
                "question_no": 1,
                "status": "safe_auto_grade",
                "final_answer": "12",
                "source": "safe_auto_grade",
            },
            {
                "question_no": 2,
                "status": "safe_auto_grade",
                "final_answer": "64",
                "source": "safe_auto_grade",
            },
            {
                "question_no": 3,
                "status": "safe_auto_grade",
                "final_answer": "42",
                "source": "safe_auto_grade",
            },
        ],
    }
    multi_digit_result = convert_json_payload(multi_digit_payload)
    if multi_digit_result.answers_text != "12\n64\n42":
        msg = "multi-digit answers were not emitted as newline-separated complete values"
        raise AssertionError(msg)
    assert_answers_text_newline_policy(
        multi_digit_result,
        PARSER_AUDIT_MULTI_DIGIT_ANSWERS,
    )

    blocker_names: list[str] = []
    for case_value in blocker_cases:
        case = require_object(case_value, "blocker_case")
        name = require_str(case.get("name"), "blocker_case.name")
        error_text = require_str(
            case.get("error_text_contains"),
            "blocker_case.error_text_contains",
        )
        # Given: a final review payload with one unresolved blocking status.
        # When: converting it to answersText.
        # Then: conversion fails before any submit-ready output is accepted.
        assert_bridge_error(case_payload(valid_payload, case), error_text)
        blocker_names.append(name)

    ANSWERS_TEXT_PATH.write_text(result.answers_text + "\n", encoding="utf-8")
    REPORT_PATH.write_text(
        build_report(
            result.answers_text,
            blocker_names,
            leak_paths,
            sorted({item.source for item in result.items}),
        ),
        encoding="utf-8",
    )
    print(f"ok: wrote {ANSWERS_TEXT_PATH}")
    print(f"ok: wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
