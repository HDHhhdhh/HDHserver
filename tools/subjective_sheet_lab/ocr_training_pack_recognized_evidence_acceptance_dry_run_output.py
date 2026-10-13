from __future__ import annotations

from typing import assert_never

from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject, JsonValue


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Recognized Evidence Acceptance Dry Run",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- complete candidate ready: `{output['complete_candidate_ready']}`",
        f"- invalid probe blocked count: `{output['invalid_probe_blocked_count']}`",
        f"- failed probe count: `{output['failed_probe_count']}`",
        f"- next action: `{output['next_action']}`",
        "- answer-key/grading/path leak count: 0",
        "",
        "## Required Evidence Files",
    ]
    for item in expected_file_rows(output.get("expected_files")):
        lines.append(f"- `{item['test_id']}` -> `{item['required_file_name']}`")
    return "\n".join(lines) + "\n"


def expected_file_rows(value: JsonValue) -> tuple[JsonObject, ...]:
    match value:
        case list() as rows:
            return tuple(row for row in rows if isinstance(row, dict))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("expected_files must be a list")
        case unreachable:
            assert_never(unreachable)
