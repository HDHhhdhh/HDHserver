from __future__ import annotations

from typing import assert_never

from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject, JsonValue


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Intake-Only Command Checklist",
        "",
        f"- status: `{output['status']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- files present/missing: {output['present_file_count']} / {output['missing_file_count']}",
        f"- ordered commands: {output['ordered_command_count']}",
        f"- stops before: `{output['stops_before']}`",
        "- provider/Gemini/API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- answer-key/grading/path leak count: 0",
        "- production default: `NO-GO`",
        "",
        "## Commands",
        "",
        *command_lines(output),
        "",
    ]
    return "\n".join(lines)


def command_lines(output: JsonObject) -> list[str]:
    match output.get("commands"):
        case list() as rows:
            return [command_line(row) for row in rows]
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("commands must be a list")
        case unreachable:
            assert_never(unreachable)


def command_line(value: JsonValue) -> str:
    match value:
        case dict() as row:
            step_no = row.get("step_no")
            command = text_value(row.get("command"), "command")
            purpose = text_value(row.get("purpose"), "purpose")
            return f"{step_no}. `{command}` - {purpose}"
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError("command row must be a mapping")
        case unreachable:
            assert_never(unreachable)


def text_value(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)
