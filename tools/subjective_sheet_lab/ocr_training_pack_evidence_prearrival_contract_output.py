from __future__ import annotations

from typing import assert_never

from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject, JsonValue


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Evidence Prearrival Contract Gate",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- next safe action: `{output['next_safe_action']}`",
        f"- required files: {output['required_file_count']}",
        f"- dropbox present files: {output['dropbox_present_file_count']}",
        f"- intake accepted files: {output['intake_accepted_file_count']}",
        f"- actual evidence files: {output['actual_evidence_file_count']}",
        f"- ready after required files: {output['ready_after_required_files']}",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    for row in target_rows(output):
        lines.append(f"- `{row['test_id']}` -> `{row['required_file_name']}`: {row['status']}")
    return "\n".join(lines) + "\n"


def target_rows(output: JsonObject) -> tuple[JsonObject, ...]:
    match output.get("required_targets"):
        case list() as rows:
            return tuple(target_row(row, index) for index, row in enumerate(rows, start=1))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("required_targets must be a list")
        case unreachable:
            assert_never(unreachable)


def target_row(value: JsonValue, index: int) -> JsonObject:
    match value:
        case dict() as row:
            return row
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError(f"required_targets[{index}] must be a mapping")
        case unreachable:
            assert_never(unreachable)
