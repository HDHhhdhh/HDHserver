# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_standard_field_coverage.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_standard_field_coverage.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_standard_field_coverage.md"
SOURCE_FIELDS: Final[tuple[str, ...]] = (
    "next_safe_action",
    "production_default",
    "answer_key_or_grading_field_leak_count",
    "filesystem_path_leak_count",
)
REPORT_FIELDS: Final[tuple[str, ...]] = (
    "ok",
    "student_facing",
    "provider_call_count",
    "external_ocr_api_call_count",
    "submit_test_call_count",
    "ts_submit_click_count",
    "production_default",
    "answer_key_or_grading_field_leak_count",
    "filesystem_path_leak_count",
    "next_safe_action",
)
DELEGATED_WRAPPER_MARKERS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "verify_ocr_training_pack_promotion_preview_diff_gate.py",
        ("ocr_training_pack_promotion_preview_diff_gate_model", "diff_summary(", "require_summary(output)"),
    ),
    (
        "verify_ocr_training_pack_evidence_prearrival_contract_gate.py",
        (
            "ocr_training_pack_evidence_prearrival_contract_model",
            "prearrival_contract(",
            "require_prearrival_contract(output)",
        ),
    ),
)


def main() -> int:
    output = coverage_summary()
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def coverage_summary() -> JsonObject:
    source_rows = training_source_rows()
    report_rows = training_report_rows()
    source_missing = sum(row_missing_count(row) for row in source_rows)
    report_missing = sum(row_missing_count(row) for row in report_rows)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "OCR_TRAINING_PACK_STANDARD_FIELD_COVERAGE_VERIFIED",
        "source_file_count": len(source_rows),
        "report_file_count": len(report_rows),
        "delegated_wrapper_count": sum(1 for row in source_rows if row.get("delegated_to_model") is True),
        "source_missing_field_count": source_missing,
        "report_missing_field_count": report_missing,
        "source_rows": list(source_rows),
        "report_rows": list(report_rows),
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "next_safe_action": "keep_training_pack_standard_field_coverage_guard_in_provider_free_checks",
    }
    return output


def training_source_rows() -> tuple[JsonObject, ...]:
    scripts = tuple(sorted(LAB.glob("verify_ocr_training_pack_*gate.py"))) + tuple(
        sorted(LAB.glob("ocr_training_pack_*gate_model.py")),
    )
    return tuple(source_row(script) for script in scripts)


def source_row(path: Path) -> JsonObject:
    text = path.read_text(encoding="utf-8")
    markers = delegated_markers(path.name)
    if markers is not None:
        missing = missing_fields(text, markers)
        return row(path.name, missing, delegated_to_model=True)
    return row(path.name, missing_fields(text, SOURCE_FIELDS), delegated_to_model=False)


def delegated_markers(file_name: str) -> tuple[str, ...] | None:
    return next((markers for wrapper, markers in DELEGATED_WRAPPER_MARKERS if wrapper == file_name), None)


def training_report_rows() -> tuple[JsonObject, ...]:
    return tuple(report_row(path) for path in sorted(LAB.glob("ocr_training_pack_*gate.json")))


def report_row(path: Path) -> JsonObject:
    payload = read_json_object(path)
    missing = missing_payload_fields(payload, REPORT_FIELDS)
    if not missing:
        require_report_values(path.name, payload)
    return row(path.name, missing, delegated_to_model=False)


def row(file_name: str, missing: tuple[str, ...], *, delegated_to_model: bool) -> JsonObject:
    return {
        "file_name": file_name,
        "delegated_to_model": delegated_to_model,
        "missing_field_count": len(missing),
        "missing_fields": list(missing),
    }


def row_missing_count(payload: JsonObject) -> int:
    value = payload.get("missing_field_count")
    if not isinstance(value, int) or isinstance(value, bool):
        raise ExtendedGateError("missing_field_count must be an integer")
    return value


def missing_fields(text: str, fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(field for field in fields if field not in text)


def missing_payload_fields(payload: JsonObject, fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(field for field in fields if field not in payload)


def require_report_values(file_name: str, payload: JsonObject) -> None:
    require_bool_value(payload.get("ok"), True, f"{file_name}.ok")
    require_bool_value(payload.get("student_facing"), False, f"{file_name}.student_facing")
    require_text_value(payload.get("production_default"), "NO_GO", f"{file_name}.production_default")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{file_name}.{key}")
    require_int_value(payload.get("answer_key_or_grading_field_leak_count"), 0, f"{file_name}.answer_key_leak")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{file_name}.filesystem_path_leak")


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "OCR_TRAINING_PACK_STANDARD_FIELD_COVERAGE_VERIFIED", "status")
    for key, value in integer_requirements():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("student_facing"), False, "student_facing")
    require_text_value(output.get("production_default"), "NO_GO", "production_default")
    require_text_value(
        output.get("next_safe_action"),
        "keep_training_pack_standard_field_coverage_guard_in_provider_free_checks",
        "next_safe_action",
    )


def integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("source_file_count", 11),
        ("report_file_count", 10),
        ("delegated_wrapper_count", 2),
        ("source_missing_field_count", 0),
        ("report_missing_field_count", 0),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Standard Field Coverage",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- submit route calls: 0",
        "- submit button clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- source files checked: {output['source_file_count']}",
        f"- JSON reports checked: {output['report_file_count']}",
        f"- delegated wrappers: {output['delegated_wrapper_count']}",
        f"- source missing fields: {output['source_missing_field_count']}",
        f"- report missing fields: {output['report_missing_field_count']}",
        f"- next safe action: `{output['next_safe_action']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
