from __future__ import annotations

from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    assert_common_safety,
    read_json_object,
    require_bool_value,
    require_int,
    require_int_value,
    require_text_value,
)
from ocr_qa_start_here_core import ReportModifiedTimes, StartHereInputs, build_output
from ocr_qa_start_here_manual_handoff_freshness import (
    HANDOFF_REFRESH_GUARD_JSON,
    HANDOFF_REFRESH_JSON,
    HANDOFF_REFRESH_SERIAL_GUARD_JSON,
    HANDOFF_REFRESH_SOURCE_JSONS,
)
from ocr_preflight_environment_matrix_model import LAB
from verify_ocr_extended_gate_count_consistency import REPORT_JSON_OUT as COUNT_JSON
from verify_ocr_operator_next_action_summary import REPORT_JSON as OPERATOR_SUMMARY_JSON
from verify_ocr_preflight_report_freshness import REPORT_FRESHNESS_JSON
from verify_ocr_qa_start_here_freshness_guard import REPORT_JSON_OUT as FRESHNESS_GUARD_JSON
from verify_ocr_training_pack_intake_only_command_checklist import REPORT_JSON as COMMAND_CHECKLIST_JSON

EVIDENCE_INDEX_JSON: Final[Path] = LAB / "ocr_post_chain_evidence_index.json"


def build_verification_output() -> JsonObject:
    return (
        build_output(
            StartHereInputs(
                count=read_json_object(COUNT_JSON),
                operator=read_json_object(OPERATOR_SUMMARY_JSON),
                freshness=read_json_object(REPORT_FRESHNESS_JSON),
                command_checklist=read_json_object(COMMAND_CHECKLIST_JSON),
                modified_times=modified_times(),
            ),
        )
        | freshness_guard_summary()
        | evidence_index_summary()
        | handoff_refresh_summary()
    )


def modified_times() -> ReportModifiedTimes:
    return ReportModifiedTimes(
        command_checklist=COMMAND_CHECKLIST_JSON.stat().st_mtime_ns,
        operator_summary=OPERATOR_SUMMARY_JSON.stat().st_mtime_ns,
        count_consistency=COUNT_JSON.stat().st_mtime_ns,
    )


def freshness_guard_summary() -> JsonObject:
    guard = read_json_object(FRESHNESS_GUARD_JSON)
    assert_common_safety("freshness_guard", guard)
    require_text_value(
        guard.get("status"),
        "OCR_QA_START_HERE_FRESHNESS_GUARD_VERIFIED",
        "freshness_guard.status",
    )
    require_int_value(guard.get("failed_probe_count"), 0, "freshness_guard.failed_probe_count")
    require_bool_value(guard.get("stale_operator_probe_blocked"), True, "freshness_guard.stale_operator_probe")
    require_bool_value(guard.get("stale_count_probe_blocked"), True, "freshness_guard.stale_count_probe")
    require_bool_value(
        guard.get("stale_manual_handoff_source_probe_blocked"),
        True,
        "freshness_guard.stale_manual_handoff_source_probe",
    )
    require_bool_value(
        guard.get("stale_manual_handoff_guard_probe_blocked"),
        True,
        "freshness_guard.stale_manual_handoff_guard_probe",
    )
    require_text_value(
        guard.get("runbook_rendered_summary_guard_status"),
        "OCR_PREFLIGHT_OPERATOR_RUNBOOK_RENDERED_SUMMARY_GUARD_VERIFIED",
        "freshness_guard.runbook_rendered_summary_guard_status",
    )
    require_text_value(
        guard.get("runbook_consistency_guard_status"),
        "OCR_PREFLIGHT_OPERATOR_RUNBOOK_CONSISTENCY_GUARD_VERIFIED",
        "freshness_guard.runbook_consistency_guard_status",
    )
    require_int_value(
        guard.get("runbook_rendered_summary_guard_failed_probe_count"),
        0,
        "freshness_guard.runbook_rendered_summary_guard_failed_probe_count",
    )
    require_int_value(
        guard.get("runbook_consistency_guard_failed_probe_count"),
        0,
        "freshness_guard.runbook_consistency_guard_failed_probe_count",
    )
    require_bool_value(
        guard.get("failed_runbook_rendered_guard_probe_blocked"),
        True,
        "freshness_guard.failed_runbook_rendered_guard_probe_blocked",
    )
    require_bool_value(
        guard.get("failed_runbook_consistency_guard_probe_blocked"),
        True,
        "freshness_guard.failed_runbook_consistency_guard_probe_blocked",
    )
    require_bool_value(guard.get("live_start_here_write_attempted"), False, "freshness_guard.live_write")
    return {
        "freshness_guard_report_path": "tools/subjective_sheet_lab/ocr_qa_start_here_freshness_guard.json",
        "freshness_guard_status": "OCR_QA_START_HERE_FRESHNESS_GUARD_VERIFIED",
        "freshness_guard_probe_count": require_int(guard.get("probe_count"), "freshness_guard.probe_count"),
        "freshness_guard_stale_operator_probe_blocked": True,
        "freshness_guard_stale_count_probe_blocked": True,
        "freshness_guard_stale_manual_handoff_source_probe_blocked": True,
        "freshness_guard_stale_manual_handoff_guard_probe_blocked": True,
        "runbook_rendered_summary_guard_report_path": (
            "tools/subjective_sheet_lab/ocr_preflight_operator_runbook_rendered_summary_guard.json"
        ),
        "runbook_rendered_summary_guard_status": "OCR_PREFLIGHT_OPERATOR_RUNBOOK_RENDERED_SUMMARY_GUARD_VERIFIED",
        "runbook_consistency_guard_report_path": (
            "tools/subjective_sheet_lab/ocr_preflight_operator_runbook_consistency_guard.json"
        ),
        "runbook_consistency_guard_status": "OCR_PREFLIGHT_OPERATOR_RUNBOOK_CONSISTENCY_GUARD_VERIFIED",
        "freshness_guard_failed_runbook_rendered_guard_probe_blocked": True,
        "freshness_guard_failed_runbook_consistency_guard_probe_blocked": True,
        "freshness_guard_live_start_here_write_attempted": False,
    }


def evidence_index_summary() -> JsonObject:
    evidence = read_json_object(EVIDENCE_INDEX_JSON)
    assert_common_safety("post_chain_evidence_index", evidence)
    require_text_value(
        evidence.get("status"),
        "OCR_POST_CHAIN_EVIDENCE_INDEX_VERIFIED",
        "post_chain_evidence_index.status",
    )
    require_text_value(
        evidence.get("manual_qa_handoff_status"),
        "READY",
        "post_chain_evidence_index.manual_qa_handoff_status",
    )
    require_int_value(evidence.get("source_report_count"), 18, "post_chain_evidence_index.source_report_count")
    require_int_value(evidence.get("failed_source_count"), 0, "post_chain_evidence_index.failed_source_count")
    return {
        "post_chain_evidence_index_report_path": "tools/subjective_sheet_lab/ocr_post_chain_evidence_index.json",
        "post_chain_evidence_index_status": "OCR_POST_CHAIN_EVIDENCE_INDEX_VERIFIED",
        "post_chain_evidence_index_manual_qa_handoff_status": "READY",
        "post_chain_evidence_index_source_report_count": 18,
        "post_chain_evidence_index_failed_source_count": 0,
    }


def handoff_refresh_summary() -> JsonObject:
    refresh = read_json_object(HANDOFF_REFRESH_JSON)
    guard = read_json_object(HANDOFF_REFRESH_GUARD_JSON)
    serial_guard = read_json_object(HANDOFF_REFRESH_SERIAL_GUARD_JSON)
    source_latest_modified_ns = max(path.stat().st_mtime_ns for path in HANDOFF_REFRESH_SOURCE_JSONS)
    refresh_modified_ns = HANDOFF_REFRESH_JSON.stat().st_mtime_ns
    guard_modified_ns = HANDOFF_REFRESH_GUARD_JSON.stat().st_mtime_ns
    serial_guard_modified_ns = HANDOFF_REFRESH_SERIAL_GUARD_JSON.stat().st_mtime_ns
    refresh_status = str(refresh.get("status", ""))
    guard_status = str(guard.get("status", ""))
    serial_guard_status = str(serial_guard.get("status", ""))
    failed_step_count = require_int(refresh.get("failed_step_count"), "manual_refresh.failed_step_count")
    guard_failed_probe_count = require_int(guard.get("failed_probe_count"), "manual_refresh_guard.failed_probe_count")
    serial_failed_probe_count = require_int(
        serial_guard.get("failed_probe_count"),
        "manual_refresh_serial_guard.failed_probe_count",
    )
    operator_state = str(refresh.get("operator_summary_state", ""))
    operator_ready = refresh.get("operator_summary_manual_qa_ready") is True
    guard_live_passed = guard.get("live_handoff_refresh_passed") is True
    require_text_value(
        serial_guard.get("status"),
        "OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_SERIAL_GUARD_VERIFIED",
        "manual_refresh_serial_guard.status",
    )
    require_int_value(serial_guard.get("failed_probe_count"), 0, "manual_refresh_serial_guard.failed_probe_count")
    require_bool_value(serial_guard.get("refresh_busy_blocked"), True, "manual_refresh_serial_guard.refresh_busy")
    require_bool_value(serial_guard.get("guard_busy_blocked"), True, "manual_refresh_serial_guard.guard_busy")
    require_bool_value(serial_guard.get("lock_file_removed"), True, "manual_refresh_serial_guard.lock_removed")
    require_bool_value(
        serial_guard.get("busy_probes_preserved_refresh_artifacts"),
        True,
        "manual_refresh_serial_guard.artifacts_preserved",
    )
    return {
        "manual_qa_handoff_refresh_report_path": (
            "tools/subjective_sheet_lab/ocr_provider_free_manual_qa_handoff_refresh.json"
        ),
        "manual_qa_handoff_refresh_status": refresh_status,
        "manual_qa_handoff_refresh_step_count": require_int(refresh.get("step_count"), "manual_refresh.step_count"),
        "manual_qa_handoff_refresh_failed_step_count": failed_step_count,
        "manual_qa_handoff_refresh_operator_state": operator_state,
        "manual_qa_handoff_refresh_manual_qa_ready": operator_ready,
        "manual_qa_handoff_refresh_guard_report_path": (
            "tools/subjective_sheet_lab/ocr_provider_free_manual_qa_handoff_refresh_guard.json"
        ),
        "manual_qa_handoff_refresh_guard_status": guard_status,
        "manual_qa_handoff_refresh_guard_probe_count": require_int(guard.get("probe_count"), "manual_refresh_guard.probe_count"),
        "manual_qa_handoff_refresh_guard_failed_probe_count": guard_failed_probe_count,
        "manual_qa_handoff_refresh_guard_live_passed": guard_live_passed,
        "manual_qa_handoff_refresh_serial_guard_report_path": (
            "tools/subjective_sheet_lab/ocr_provider_free_manual_qa_handoff_refresh_serial_guard.json"
        ),
        "manual_qa_handoff_refresh_serial_guard_status": serial_guard_status,
        "manual_qa_handoff_refresh_serial_guard_probe_count": require_int(
            serial_guard.get("probe_count"),
            "manual_refresh_serial_guard.probe_count",
        ),
        "manual_qa_handoff_refresh_serial_guard_failed_probe_count": serial_failed_probe_count,
        "manual_qa_handoff_refresh_serial_guard_refresh_busy_blocked": True,
        "manual_qa_handoff_refresh_serial_guard_guard_busy_blocked": True,
        "manual_qa_handoff_refresh_serial_guard_lock_file_removed": True,
        "manual_qa_handoff_refresh_serial_guard_artifacts_preserved": True,
        "manual_qa_handoff_refresh_source_artifact_count": len(HANDOFF_REFRESH_SOURCE_JSONS),
        "manual_qa_handoff_refresh_source_latest_modified_ns": source_latest_modified_ns,
        "manual_qa_handoff_refresh_report_modified_ns": refresh_modified_ns,
        "manual_qa_handoff_refresh_guard_report_modified_ns": guard_modified_ns,
        "manual_qa_handoff_refresh_serial_guard_report_modified_ns": serial_guard_modified_ns,
        "manual_qa_handoff_refresh_newer_than_sources": refresh_modified_ns >= source_latest_modified_ns,
        "manual_qa_handoff_refresh_guard_newer_than_refresh": guard_modified_ns >= refresh_modified_ns,
        "manual_qa_handoff_refresh_serial_guard_newer_than_guard": serial_guard_modified_ns >= guard_modified_ns,
    }
