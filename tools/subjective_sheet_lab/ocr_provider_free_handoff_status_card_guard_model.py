from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from ocr_post_chain_evidence_index_common import path_mtime
from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject, read_json_object
import verify_ocr_provider_free_final_handoff_chain as final_chain
import verify_ocr_provider_free_final_handoff_chain_guard as final_guard
import verify_ocr_provider_free_handoff_status_card as status_card

OK_STATUS: Final = "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_READY"
BLOCKED_STATUS: Final = "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_BLOCKED"


@dataclass(frozen=True, slots=True)
class GuardProbes:
    live_status_card_passed: bool
    stale_guard_report_blocked: bool
    nonzero_source_count_blocked: bool
    final_metric_rejected: bool
    guard_metric_rejected: bool
    missing_helper_metric_rejected: bool
    status_artifacts_preserved: bool


def refresh_live_status_card() -> tuple[list[status_card.HandoffStatusSourceRow], status_card.HandoffStatusCardReport]:
    live_rows = source_rows_from(status_card.SOURCE_SPECS)
    live_report = status_card.build_report(live_rows)
    status_card.REPORT_JSON_OUT.write_text(
        json.dumps(live_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    status_card.REPORT_MD_OUT.write_text(status_card.markdown(live_report), encoding="utf-8")
    return live_rows, live_report


def source_rows_from(
    specs: tuple[status_card.HandoffStatusSourceSpec, ...],
) -> list[status_card.HandoffStatusSourceRow]:
    return [status_card.source_row(spec, read_json_object(spec.path)) for spec in specs]


def build_probes(
    live_rows: list[status_card.HandoffStatusSourceRow],
    live_report: status_card.HandoffStatusCardReport,
    before: tuple[int, ...],
) -> GuardProbes:
    stale_guard_report = copied_stale_guard_report()
    nonzero_count_report = status_card.build_report(copied_rows_with_failure(live_rows))
    after = snapshot_status_artifacts()
    return GuardProbes(
        live_status_card_passed=live_status_card_passed(live_report),
        stale_guard_report_blocked=blocked_for(stale_guard_report, stale_count=1, failed_count=1),
        nonzero_source_count_blocked=blocked_for(nonzero_count_report, stale_count=0, failed_count=1),
        final_metric_rejected=source_metric_rejected(
            status_card.SOURCE_SPECS[0],
            "failed_step_count",
        ),
        guard_metric_rejected=source_metric_rejected(
            status_card.SOURCE_SPECS[1],
            "failed_probe_count",
        ),
        missing_helper_metric_rejected=source_metric_rejected(
            status_card.SOURCE_SPECS[0],
            "handoff_retention_missing_start_card_freshness_helper_missing_count",
            copied_value=0,
        ),
        status_artifacts_preserved=before == after,
    )


def copied_stale_guard_report() -> status_card.HandoffStatusCardReport:
    with TemporaryDirectory(prefix="ocr_status_card_guard_") as directory:
        temporary_root = Path(directory)
        final_copy = temporary_root / "final_handoff_chain.json"
        guard_copy = temporary_root / "final_handoff_chain_guard.json"
        final_copy.write_text(final_chain.REPORT_JSON_OUT.read_text(encoding="utf-8"), encoding="utf-8")
        guard_copy.write_text(final_guard.REPORT_JSON_OUT.read_text(encoding="utf-8"), encoding="utf-8")
        os.utime(guard_copy, ns=(100, 100))
        os.utime(final_copy, ns=(200, 200))
        final_spec = status_card.HandoffStatusSourceSpec(
            status_card.SourceLabel.FINAL_HANDOFF_CHAIN,
            final_copy,
            "OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_VERIFIED",
            None,
        )
        guard_spec = status_card.HandoffStatusSourceSpec(
            status_card.SourceLabel.FINAL_HANDOFF_CHAIN_GUARD,
            guard_copy,
            "OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_GUARD_VERIFIED",
            final_copy,
        )
        return status_card.build_report(source_rows_from((final_spec, guard_spec)))


def copied_rows_with_failure(
    live_rows: list[status_card.HandoffStatusSourceRow],
) -> list[status_card.HandoffStatusSourceRow]:
    copied_rows = [clone_row(row) for row in live_rows]
    copied_rows[0]["failed_metric_count"] = 1
    return copied_rows


def clone_row(row: status_card.HandoffStatusSourceRow) -> status_card.HandoffStatusSourceRow:
    return {
        "label": row["label"],
        "report_path": row["report_path"],
        "status": row["status"],
        "metrics": dict(row["metrics"]),
        "fresh": row["fresh"],
        "failed_metric_count": row["failed_metric_count"],
    }


def source_metric_rejected(
    spec: status_card.HandoffStatusSourceSpec,
    metric_name: str,
    copied_value: int = 1,
) -> bool:
    payload = copied_payload_with_int(spec.path, metric_name, copied_value)
    try:
        status_card.source_row(spec, payload)
    except ExtendedGateError:
        return True
    return False


def copied_payload_with_int(path: Path, key: str, value: int) -> JsonObject:
    payload = read_json_object(path)
    copied = dict(payload)
    copied[key] = value
    return copied


def live_status_card_passed(report: status_card.HandoffStatusCardReport) -> bool:
    return (
        report["ok"] is True
        and report["status"] == OK_STATUS
        and report["manual_qa_handoff_status"] == "READY"
        and report["source_report_count"] == 2
        and report["stale_source_count"] == 0
        and report["failed_source_count"] == 0
    )


def blocked_for(report: status_card.HandoffStatusCardReport, stale_count: int, failed_count: int) -> bool:
    return (
        report["ok"] is False
        and report["status"] == BLOCKED_STATUS
        and report["manual_qa_handoff_status"] == "BLOCKED"
        and report["stale_source_count"] == stale_count
        and report["failed_source_count"] == failed_count
    )


def snapshot_status_artifacts() -> tuple[int, ...]:
    paths = (
        final_chain.REPORT_JSON_OUT,
        final_chain.REPORT_MD_OUT,
        final_guard.REPORT_JSON_OUT,
        final_guard.REPORT_MD_OUT,
        status_card.REPORT_JSON_OUT,
        status_card.REPORT_MD_OUT,
    )
    return tuple(path_mtime(path) for path in paths)


def build_guard_report(
    probes: GuardProbes,
    live_report: status_card.HandoffStatusCardReport,
) -> JsonObject:
    probe_results = (
        probes.live_status_card_passed,
        probes.stale_guard_report_blocked,
        probes.nonzero_source_count_blocked,
        probes.final_metric_rejected,
        probes.guard_metric_rejected,
        probes.missing_helper_metric_rejected,
        probes.status_artifacts_preserved,
    )
    failed_probe_count = sum(1 for passed in probe_results if not passed)
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_GUARD_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_GUARD_FAILED",
        "probe_count": len(probe_results),
        "failed_probe_count": failed_probe_count,
        "live_status_card_passed": probes.live_status_card_passed,
        "copied_stale_guard_report_blocked": probes.stale_guard_report_blocked,
        "copied_nonzero_source_count_blocked": probes.nonzero_source_count_blocked,
        "copied_final_metric_rejected": probes.final_metric_rejected,
        "copied_guard_metric_rejected": probes.guard_metric_rejected,
        "copied_missing_helper_metric_rejected": probes.missing_helper_metric_rejected,
        "copied_probes_preserved_status_artifacts": probes.status_artifacts_preserved,
        "live_source_report_count": live_report["source_report_count"],
        "live_stale_source_count": live_report["stale_source_count"],
        "live_failed_source_count": live_report["failed_source_count"],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": (
            "Run this guard after provider-free handoff status card changes."
            if ok
            else "Fix status-card blocking probes before using it for manual-QA handoff."
        ),
    }
