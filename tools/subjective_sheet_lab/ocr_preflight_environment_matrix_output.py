from __future__ import annotations

import json

from ocr_preflight_environment_matrix_model import JsonValue, MatrixReport


def parse_json(value: str) -> JsonValue:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        loaded: JsonValue = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return loaded


def parse_module_map(value: str) -> dict[str, bool]:
    parsed = parse_json(value)
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, bool] = {}
    for key, item in parsed.items():
        if isinstance(key, str) and isinstance(item, bool):
            result[key] = item
    return result


def tail(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-1000:]
    return value[-1000:]


def command_label(command: tuple[str, ...]) -> str:
    return " ".join(command)


def markdown(report: MatrixReport) -> str:
    package_lines = [
        f"- {item['environment']}: {'PASS' if item['ok'] else 'FAIL'} modules={item['modules']}"
        for item in report["package_probes"]
    ]
    command_lines = [
        f"- {item['name']} ({item['environment']}): {'PASS' if item['ok'] else 'FAIL'}"
        for item in report["command_probes"]
    ]
    return "\n".join((
        "# OCR Preflight Environment Matrix",
        "",
        f"- ok: {report['ok']}",
        f"- production_default: {report['production_default']}",
        f"- provider_call_count: {report['provider_call_count']}",
        f"- external_ocr_api_call_count: {report['external_ocr_api_call_count']}",
        f"- submit_test_call_count: {report['submit_test_call_count']}",
        f"- ts_submit_click_count: {report['ts_submit_click_count']}",
        f"- extended_gate_count: {report['extended_gate_count']}",
        f"- answer_key_or_grading_field_leak_count: {report['answer_key_or_grading_field_leak_count']}",
        f"- filesystem_path_leak_count: {report['filesystem_path_leak_count']}",
        f"- preflight_script_modified: {report['preflight_script_modified']}",
        "",
        "## Package Probes",
        *package_lines,
        "",
        "## Command Probes",
        *command_lines,
        "",
        "## Operator Note",
        report["recommended_operator_note"],
        "",
    ))
