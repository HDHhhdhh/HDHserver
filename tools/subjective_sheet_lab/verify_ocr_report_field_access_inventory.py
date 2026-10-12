# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_report_field_access_inventory.py

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import JsonObject, JsonValue

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_report_field_access_inventory.json"
REPORT_MD: Final[Path] = LAB / "ocr_report_field_access_inventory.md"
HELPER_NAMES: Final[frozenset[str]] = frozenset((
    "read_report",
    "bool_field",
    "nullable_int_field",
    "int_field",
    "str_field",
))
COMMON_HELPER_FILE: Final[str] = "ocr_report_field_access.py"


@dataclass(frozen=True, slots=True)
class HelperRow:
    file_name: str
    helper_name: str
    line_no: int
    parameter_count: int
    classification: str


def main() -> int:
    rows, parse_errors = inventory_rows()
    output = report(rows, parse_errors)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] is True else 1


def inventory_rows() -> tuple[tuple[HelperRow, ...], tuple[str, ...]]:
    rows: list[HelperRow] = []
    parse_errors: list[str] = []
    for path in sorted(LAB.glob("*.py")):
        source = path.read_text(encoding="utf-8-sig")
        try:
            module = ast.parse(source)
        except SyntaxError as error:
            parse_errors.append(f"{path.name}: {error.msg}")
            continue
        rows.extend(helper_rows(path.name, source, module))
    return tuple(rows), tuple(parse_errors)


def helper_rows(file_name: str, source: str, module: ast.Module) -> tuple[HelperRow, ...]:
    rows: list[HelperRow] = []
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name in HELPER_NAMES:
            function_source = ast.get_source_segment(source, node) or ""
            rows.append(row(file_name, node, function_source))
    return tuple(rows)


def row(file_name: str, node: ast.FunctionDef, source: str) -> HelperRow:
    return HelperRow(
        file_name=file_name,
        helper_name=node.name,
        line_no=node.lineno,
        parameter_count=len(node.args.args),
        classification=classification(file_name, node.name, len(node.args.args), source),
    )


def classification(file_name: str, helper_name: str, parameter_count: int, source: str) -> str:
    if file_name == COMMON_HELPER_FILE:
        return "common_default_helper"
    if has_strict_contract(source):
        return "strict_local_contract"
    if helper_name == "read_report":
        return "local_json_reader"
    if parameter_count == 2 and has_default_return(source):
        return "default_reader_candidate"
    return "specialized_local_helper"


def has_strict_contract(source: str) -> bool:
    return "raise " in source or "require_" in source or "ExtendedGateError" in source or "AssertionError" in source


def has_default_return(source: str) -> bool:
    defaults = ("return 0", "return False", 'return ""', "return None")
    return any(default in source for default in defaults)


def report(rows: tuple[HelperRow, ...], parse_errors: tuple[str, ...]) -> JsonObject:
    classifications = tuple(row.classification for row in rows)
    default_reader_candidate_count = classifications.count("default_reader_candidate")
    ok = not parse_errors and default_reader_candidate_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_REPORT_FIELD_ACCESS_INVENTORY_VERIFIED" if ok else "OCR_REPORT_FIELD_ACCESS_INVENTORY_FAILED",
        "helper_definition_count": len(rows),
        "common_default_helper_count": classifications.count("common_default_helper"),
        "default_reader_candidate_count": default_reader_candidate_count,
        "strict_local_contract_count": classifications.count("strict_local_contract"),
        "local_json_reader_count": classifications.count("local_json_reader"),
        "specialized_local_helper_count": classifications.count("specialized_local_helper"),
        "parse_error_count": len(parse_errors),
        "parse_errors": list(parse_errors),
        "helpers": [row_payload(item) for item in rows],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(classifications.count("default_reader_candidate")),
    }


def row_payload(row: HelperRow) -> JsonObject:
    return {
        "file_name": row.file_name,
        "helper_name": row.helper_name,
        "line_no": row.line_no,
        "parameter_count": row.parameter_count,
        "classification": row.classification,
    }


def next_safe_action(default_candidate_count: int) -> str:
    if default_candidate_count:
        return "Inspect default_reader_candidate helpers and move exact matches to ocr_report_field_access.py."
    return "Leave strict_local_contract helpers local unless their fail-fast semantics are intentionally changed."


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Report Field Access Inventory",
        "",
        f"- ok: `{output['ok']}`",
        f"- status: `{output['status']}`",
        f"- helper definition count: `{output['helper_definition_count']}`",
        f"- common default helpers: `{output['common_default_helper_count']}`",
        f"- default reader candidates: `{output['default_reader_candidate_count']}`",
        f"- strict local contracts: `{output['strict_local_contract_count']}`",
        f"- local JSON readers: `{output['local_json_reader_count']}`",
        f"- specialized local helpers: `{output['specialized_local_helper_count']}`",
        "- Gemini/API calls: `0`",
        "- external OCR API calls: `0`",
        "- `/api/submit-test` calls: `0`",
        "- `#tsSubmit` clicks: `0`",
        "- answer-key/grading leak count: `0`",
        "- filesystem path leak count: `0`",
        "- production default: `NO_GO`",
        "",
        "## Helpers",
        *helper_lines(output["helpers"]),
        "",
        "## Next Safe Action",
        str(output["next_safe_action"]),
        "",
    ]
    return "\n".join(lines)


def helper_lines(rows: JsonValue) -> tuple[str, ...]:
    match rows:
        case list() as items:
            return tuple(helper_line(item) for item in items if isinstance(item, dict))
        case None | bool() | int() | float() | str() | dict():
            return ()
        case unreachable:
            assert_never(unreachable)


def helper_line(item: JsonObject) -> str:
    return f"- `{item.get('file_name')}` `{item.get('helper_name')}`: `{item.get('classification')}`"


if __name__ == "__main__":
    raise SystemExit(main())
