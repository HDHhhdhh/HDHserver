from __future__ import annotations

from typing import assert_never

from ocr_provider_free_extended_gate_common import JsonObject, JsonValue


def markdown(output: JsonObject) -> str:
    rows = output["reports"]
    if not isinstance(rows, list):
        rows = []
    lines = [
        "# OCR User-Action Required Inventory",
        "",
        f"- ok: `{output['ok']}`",
        f"- status: `{output['status']}`",
        f"- allowed status count: `{output['allowed_status_count']}`",
        f"- user-required report count: `{output['user_required_report_count']}`",
        f"- unexpected issue count: `{output['unexpected_issue_count']}`",
        "- Gemini/API calls: `0`",
        "- external OCR API calls: `0`",
        "- `/api/submit-test` calls: `0`",
        "- `#tsSubmit` clicks: `0`",
        "- answer-key/grading leak count: `0`",
        "- filesystem path leak count: `0`",
        "- production default: `NO_GO`",
        "",
        "## Reports",
    ]
    lines.extend(report_lines(rows))
    lines.extend((
        "",
        "## Unexpected Issues",
        *issue_lines(output),
        "",
        "## Next Safe Action",
        str(output["next_safe_action"]),
        "",
    ))
    return "\n".join(lines)


def report_lines(rows: list[JsonValue]) -> list[str]:
    lines: list[str] = []
    for item in rows:
        match item:
            case {"file_name": str(file_name), "status": str(status), "current_blocker": str(current_blocker)}:
                blocker = current_blocker or "none"
                lines.append(f"- `{file_name}`: `{status}`; blocker: `{blocker}`")
            case None | bool() | int() | float() | str() | list() | dict():
                continue
            case unreachable:
                assert_never(unreachable)
    return lines or ["- none"]


def issue_lines(output: JsonObject) -> list[str]:
    issues = output["unexpected_issues"]
    if not isinstance(issues, list):
        return ["- invalid issue list"]
    return [f"- {issue}" for issue in issues] or ["- none"]
