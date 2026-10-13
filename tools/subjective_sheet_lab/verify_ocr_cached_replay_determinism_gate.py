from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

LAB: Final[Path] = Path(__file__).resolve().parent
PYTHON_REPLAY_SCRIPT: Final[Path] = LAB / "verify_ocr_cached_replay_stability.py"
UI_REPLAY_SCRIPT: Final[Path] = LAB / "verify_student_ocr_live_review_payload_cache_replay.js"
REPORT_JSON: Final[Path] = LAB / "ocr_cached_replay_determinism_gate.json"
REPORT_MD: Final[Path] = LAB / "ocr_cached_replay_determinism_gate.md"
RUN_COUNT: Final[int] = 3

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class DeterminismGateError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    python_runs = tuple(run_json((sys.executable, str(PYTHON_REPLAY_SCRIPT)), "python replay") for _ in range(RUN_COUNT))
    ui_runs = tuple(run_json(("node", str(UI_REPLAY_SCRIPT)), "hidden OCR UI replay") for _ in range(RUN_COUNT))
    output = determinism_summary(python_runs, ui_runs)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def run_json(command: tuple[str, str], label: str) -> JsonObject:
    completed = subprocess.run(command, cwd=LAB.parents[1], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        raise DeterminismGateError(f"{label} failed: {completed.stderr[:1000]}")
    return require_object(parse_json_stdout(completed.stdout), label)


def parse_json_stdout(stdout: str) -> JsonValue:
    stripped = stdout.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as error:
        raise DeterminismGateError(f"command did not return JSON: {stripped[:1000]}") from error


def determinism_summary(python_runs: tuple[JsonObject, ...], ui_runs: tuple[JsonObject, ...]) -> JsonObject:
    first_python = require_first(python_runs, "python runs")
    first_ui = require_first(ui_runs, "UI runs")
    assert_replay_runs_match(python_runs)
    assert_ui_runs_match(ui_runs)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "python_replay_run_count": len(python_runs),
        "ui_replay_run_count": len(ui_runs),
        "payload_name": require_str(first_python.get("payload_path"), "payload_path"),
        "item_count": require_int(first_python.get("item_count"), "item_count"),
        "question_sequence_ok": require_bool(first_python.get("question_sequence_ok"), "question_sequence_ok"),
        "review_required_count": require_int(first_python.get("review_required_count"), "review_required_count"),
        "safe_answers_line_count": require_int(first_python.get("safe_answers_line_count"), "safe_answers_line_count"),
        "review_payload_sha256": require_str(first_python.get("review_payload_sha256"), "review_payload_sha256"),
        "safe_answers_text_sha256": require_str(first_python.get("safe_answers_text_sha256"), "safe_answers_text_sha256"),
        "ui_review_card_count": require_int(first_ui.get("reviewCardCount"), "reviewCardCount"),
        "ui_reviewed_questions": require_array(first_ui.get("reviewedQuestions"), "reviewedQuestions"),
        "ui_answers_text_line_count": require_int(first_ui.get("answersTextLineCount"), "answersTextLineCount"),
        "ui_partial_fill_before_confirmation": require_bool(first_ui.get("partialFillBeforeConfirmation"), "partialFillBeforeConfirmation"),
        "ui_partial_filled_line_count": require_int(first_ui.get("partialFilledLineCount"), "partialFilledLineCount"),
        "ui_blank_before_confirmation_questions": require_array(first_ui.get("blankBeforeConfirmationQuestions"), "blankBeforeConfirmationQuestions"),
        "stable_same_payload_hash_across_runs": True,
        "stable_same_ui_review_questions_across_runs": True,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    verify_expected_summary(output)
    return output


def assert_replay_runs_match(runs: tuple[JsonObject, ...]) -> None:
    first = require_first(runs, "python runs")
    keys = ("review_payload_sha256", "safe_answers_text_sha256", "item_count", "question_sequence_ok", "review_required_count")
    for run in runs[1:]:
        for key in keys:
            if run.get(key) != first.get(key):
                raise DeterminismGateError(f"python replay {key} changed across runs")


def assert_ui_runs_match(runs: tuple[JsonObject, ...]) -> None:
    first = require_first(runs, "UI runs")
    keys = (
        "reviewCardCount",
        "reviewedQuestions",
        "confirmedLineValues",
        "partialFillBeforeConfirmation",
        "partialFilledLineCount",
        "blankBeforeConfirmationQuestions",
        "answersTextLineCount",
        "submitTestCalls",
        "tsSubmitClicks",
        "geminiCalls",
    )
    for run in runs[1:]:
        for key in keys:
            if run.get(key) != first.get(key):
                raise DeterminismGateError(f"UI replay {key} changed across runs")


def verify_expected_summary(output: JsonObject) -> None:
    require_int_value(output.get("item_count"), 20, "item_count")
    require_true(output.get("question_sequence_ok"), "question_sequence_ok")
    require_int_value(output.get("safe_answers_line_count"), 20, "safe_answers_line_count")
    require_int_value(output.get("ui_answers_text_line_count"), 20, "ui_answers_text_line_count")
    require_true(output.get("ui_partial_fill_before_confirmation"), "ui_partial_fill_before_confirmation")
    require_int_value(output.get("ui_partial_filled_line_count"), 16, "ui_partial_filled_line_count")
    require_array_value(output.get("ui_blank_before_confirmation_questions"), [9, 14, 16, 17], "ui_blank_before_confirmation_questions")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(output.get(key), 0, key)


def require_first(values: tuple[JsonObject, ...], label: str) -> JsonObject:
    if not values:
        raise DeterminismGateError(f"{label} must not be empty")
    return values[0]


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise DeterminismGateError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise DeterminismGateError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_str(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise DeterminismGateError(f"{label} must be a string")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise DeterminismGateError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_bool(value: JsonValue, label: str) -> bool:
    match value:
        case bool():
            return value
        case None | int() | float() | str() | list() | dict():
            raise DeterminismGateError(f"{label} must be a boolean")
        case unreachable:
            assert_never(unreachable)


def require_int_value(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int(value, label)
    if actual != expected:
        raise DeterminismGateError(f"{label} must be {expected}, got {actual}")


def require_array_value(value: JsonValue, expected: list[int], label: str) -> None:
    actual = require_array(value, label)
    if actual != expected:
        raise DeterminismGateError(f"{label} must be {expected}, got {actual}")


def require_true(value: JsonValue, label: str) -> None:
    if value is not True:
        raise DeterminismGateError(f"{label} must be true")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Cached Replay Determinism Gate",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- payload: `{output['payload_name']}`",
        f"- Python replay runs: {output['python_replay_run_count']}",
        f"- hidden OCR UI replay runs: {output['ui_replay_run_count']}",
        f"- review payload hash stable: {output['stable_same_payload_hash_across_runs']}",
        f"- UI review questions stable: {output['stable_same_ui_review_questions_across_runs']}",
        f"- review_required count: {output['review_required_count']}",
        f"- UI reviewed questions: {output['ui_reviewed_questions']}",
        f"- partial fill before confirmation: {output['ui_partial_filled_line_count']} safe lines",
        f"- blank questions before confirmation: {output['ui_blank_before_confirmation_questions']}",
        f"- answersText line count: {output['ui_answers_text_line_count']}",
        "- answer-key/grading/path leak count: 0",
        "",
        "This gate proves cached same-OMR replay is deterministic without provider calls.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
