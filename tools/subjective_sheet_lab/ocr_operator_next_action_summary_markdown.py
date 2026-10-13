from __future__ import annotations

from typing import assert_never

from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject, JsonValue


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Operator Next Action Summary",
        "",
        f"- status: `{output['status']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- next action: `{output['operator_next_action']}`",
        f"- required files: {output['required_file_count']}",
        f"- present files: {output['present_file_count']}",
        f"- missing files: {output['missing_file_count']}",
        f"- ready now: {output['ready_now']}",
        f"- ready after required files: {output['ready_after_required_files']}",
        f"- API authorization required for next action: {output['api_authorization_required_for_next_action']}",
        f"- provider call required for next action: {output['provider_call_required_for_next_action']}",
        f"- promotion write authorization required: {output['promotion_write_authorization_required']}",
        f"- extended gate count: {output['extended_gate_count']}",
        f"- wrong safe auto grade: {output['wrong_safe_auto_grade']}",
        "- provider/Gemini/API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- answer-key/grading/path leak count: 0",
        "- production default: `NO-GO`",
        "",
        "## Required Files",
        "",
        *required_file_lines(output),
        "",
    ]
    return "\n".join(lines)


def required_file_lines(output: JsonObject) -> list[str]:
    match output.get("required_files"):
        case list() as rows:
            return [required_file_line(row, index) for index, row in enumerate(rows, start=1)]
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("required_files must be a list")
        case unreachable:
            assert_never(unreachable)


def required_file_line(value: JsonValue, index: int) -> str:
    match value:
        case dict() as row:
            file_name = text_value(row.get("required_file_name"), f"required_files[{index}].required_file_name")
            status = text_value(row.get("status"), f"required_files[{index}].status")
            return f"{index}. `{file_name}` - `{status}`"
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError(f"required_files[{index}] must be a mapping")
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
