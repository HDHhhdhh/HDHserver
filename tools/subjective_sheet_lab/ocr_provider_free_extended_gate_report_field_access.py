from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_report_field_access_inventory import REPORT_JSON as FIELD_ACCESS_INVENTORY_JSON
from verify_ocr_report_field_access_inventory import main as verify_field_access_inventory
from verify_ocr_report_field_access_inventory_guard import REPORT_JSON as FIELD_ACCESS_INVENTORY_GUARD_JSON
from verify_ocr_report_field_access_inventory_guard import main as verify_field_access_inventory_guard

Verifier: TypeAlias = Callable[[], int]


def report_field_access_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (
        ("OCR report field-access inventory", verify_field_access_inventory),
        ("OCR report field-access inventory guard", verify_field_access_inventory_guard),
    )


def report_field_access_reports() -> dict[str, JsonObject]:
    return {
        "report_field_access_inventory": read_json_object(FIELD_ACCESS_INVENTORY_JSON),
        "report_field_access_inventory_guard": read_json_object(FIELD_ACCESS_INVENTORY_GUARD_JSON),
    }


def require_report_field_access_inventory(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "OCR_REPORT_FIELD_ACCESS_INVENTORY_VERIFIED",
        "report_field_access_inventory.status",
    )
    require_int_value(report.get("helper_definition_count"), 14, "report_field_access_inventory.helper_definition_count")
    require_int_value(report.get("common_default_helper_count"), 5, "report_field_access_inventory.common_default_helper_count")
    require_int_value(report.get("default_reader_candidate_count"), 0, "report_field_access_inventory.default_reader_candidate_count")
    require_int_value(report.get("strict_local_contract_count"), 9, "report_field_access_inventory.strict_local_contract_count")
    require_int_value(report.get("parse_error_count"), 0, "report_field_access_inventory.parse_error_count")


def require_report_field_access_inventory_guard(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "OCR_REPORT_FIELD_ACCESS_INVENTORY_GUARD_VERIFIED",
        "report_field_access_inventory_guard.status",
    )
    require_int_value(report.get("probe_count"), 3, "report_field_access_inventory_guard.probe_count")
    require_int_value(report.get("failed_probe_count"), 0, "report_field_access_inventory_guard.failed_probe_count")
    require_bool_value(
        report.get("default_reader_candidate_probe_blocked"),
        True,
        "report_field_access_inventory_guard.default_reader_candidate_probe_blocked",
    )
    require_bool_value(
        report.get("parse_error_probe_blocked"),
        True,
        "report_field_access_inventory_guard.parse_error_probe_blocked",
    )


def report_field_access_summary_fields() -> JsonObject:
    return {
        "report_field_access_inventory_status": "OCR_REPORT_FIELD_ACCESS_INVENTORY_VERIFIED",
        "report_field_access_helper_definition_count": 14,
        "report_field_access_common_default_helper_count": 5,
        "report_field_access_default_reader_candidate_count": 0,
        "report_field_access_strict_local_contract_count": 9,
        "report_field_access_parse_error_count": 0,
        "report_field_access_inventory_guard_status": "OCR_REPORT_FIELD_ACCESS_INVENTORY_GUARD_VERIFIED",
        "report_field_access_inventory_guard_probe_count": 3,
        "report_field_access_default_reader_candidate_probe_blocked": True,
    }
