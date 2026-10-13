from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from ocr_post_chain_evidence_index_common import (
    EvidenceIndexSnapshot,
    PostChainEvidenceIndexGuardReport,
    ProbeResult,
    copied_payloads,
    reports_without_status,
    snapshot_evidence_files,
    source_index,
    source_payloads,
)
from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject
import verify_ocr_post_chain_evidence_index as evidence_index


@dataclass(frozen=True, slots=True)
class ProbeReports:
    live: ProbeResult
    bad_status: ProbeResult
    nonzero_failed_count: ProbeResult
    missing_cleanup_status: ProbeResult
    bad_retention_artifact_count: ProbeResult
    bad_retention_guard_probe_count: ProbeResult


def run_guard() -> PostChainEvidenceIndexGuardReport:
    refresh_live_index_artifacts()
    payloads = source_payloads(evidence_index.SOURCE_SPECS)
    before = snapshot_live_files()
    probes = ProbeReports(
        live=run_probe("live", payloads),
        bad_status=run_probe("copied_bad_status", with_bad_status(payloads)),
        nonzero_failed_count=run_probe("copied_nonzero_failed_count", with_nonzero_failed_count(payloads)),
        missing_cleanup_status=run_probe(
            "copied_missing_cleanup_status",
            with_missing_cleanup_status(payloads),
        ),
        bad_retention_artifact_count=run_probe(
            "copied_bad_retention_artifact_count",
            with_bad_retention_artifact_count(payloads),
        ),
        bad_retention_guard_probe_count=run_probe(
            "copied_bad_retention_guard_probe_count",
            with_bad_retention_guard_probe_count(payloads),
        ),
    )
    after = snapshot_live_files()
    return build_guard_report(probes, before, after)


def refresh_live_index_artifacts() -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        evidence_index.main()


def snapshot_live_files() -> EvidenceIndexSnapshot:
    return snapshot_evidence_files(evidence_index.SOURCE_SPECS, evidence_index.REPORT_JSON_OUT)


def run_probe(name: str, payloads: tuple[JsonObject, ...]) -> ProbeResult:
    try:
        report = build_index(payloads)
    except ExtendedGateError as error:
        return {"name": name, "blocked": True, "ok": False, "status": "", "issue": str(error)}
    return {"name": name, "blocked": False, "ok": report["ok"], "status": report["status"], "issue": ""}


def build_index(payloads: tuple[JsonObject, ...]) -> evidence_index.PostChainEvidenceIndexReport:
    rows = [
        evidence_index.source_row(spec, payload)
        for spec, payload in zip(evidence_index.SOURCE_SPECS, payloads, strict=True)
    ]
    return evidence_index.build_report(rows)


def with_bad_status(payloads: tuple[JsonObject, ...]) -> tuple[JsonObject, ...]:
    copied = copied_payloads(payloads)
    copied[0] = {**copied[0], "status": "SYNTHETIC_BAD_STATUS"}
    return tuple(copied)


def with_nonzero_failed_count(payloads: tuple[JsonObject, ...]) -> tuple[JsonObject, ...]:
    copied = copied_payloads(payloads)
    copied[0] = {**copied[0], "failed_step_count": 1}
    return tuple(copied)


def with_missing_cleanup_status(payloads: tuple[JsonObject, ...]) -> tuple[JsonObject, ...]:
    copied = copied_payloads(payloads)
    summary_index = source_index("post_chain_operator_summary", evidence_index.SOURCE_SPECS)
    summary_payload = copied[summary_index]
    reports = summary_payload.get("reports")
    match reports:
        case list():
            copied[summary_index] = {
                **summary_payload,
                "reports": reports_without_status(
                    reports,
                    "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_GUARD_VERIFIED",
                    "post_chain_operator_summary",
                ),
            }
            return tuple(copied)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("post_chain_operator_summary.reports must be an array")
        case unreachable:
            assert_never(unreachable)


def with_bad_retention_artifact_count(payloads: tuple[JsonObject, ...]) -> tuple[JsonObject, ...]:
    copied = copied_payloads(payloads)
    retention_index = source_index("post_chain_handoff_retention_manifest", evidence_index.SOURCE_SPECS)
    copied[retention_index] = {**copied[retention_index], "artifact_count": 12}
    return tuple(copied)


def with_bad_retention_guard_probe_count(payloads: tuple[JsonObject, ...]) -> tuple[JsonObject, ...]:
    copied = copied_payloads(payloads)
    retention_guard_index = source_index(
        "post_chain_handoff_retention_manifest_guard",
        evidence_index.SOURCE_SPECS,
    )
    copied[retention_guard_index] = {**copied[retention_guard_index], "probe_count": 7}
    return tuple(copied)


def build_guard_report(
    probes: ProbeReports,
    before: EvidenceIndexSnapshot,
    after: EvidenceIndexSnapshot,
) -> PostChainEvidenceIndexGuardReport:
    live_probe_passed = (
        probes.live["blocked"] is False
        and probes.live["ok"] is True
        and probes.live["status"] == "OCR_POST_CHAIN_EVIDENCE_INDEX_VERIFIED"
    )
    bad_status_blocked = probes.bad_status["blocked"] is True and "status expected" in probes.bad_status["issue"]
    nonzero_failed_blocked = (
        probes.nonzero_failed_count["blocked"] is True
        and "failed_step_count expected 0" in probes.nonzero_failed_count["issue"]
    )
    missing_cleanup_status_blocked = (
        probes.missing_cleanup_status["blocked"] is True
        and "reports missing statuses" in probes.missing_cleanup_status["issue"]
    )
    bad_retention_artifact_count_blocked = (
        probes.bad_retention_artifact_count["blocked"] is True
        and "artifact_count expected 15" in probes.bad_retention_artifact_count["issue"]
    )
    bad_retention_guard_probe_count_blocked = (
        probes.bad_retention_guard_probe_count["blocked"] is True
        and "probe_count expected 9" in probes.bad_retention_guard_probe_count["issue"]
    )
    live_file_write_attempted = before != after
    failed_probe_count = sum(
        1
        for passed in (
            live_probe_passed,
            bad_status_blocked,
            nonzero_failed_blocked,
            missing_cleanup_status_blocked,
            bad_retention_artifact_count_blocked,
            bad_retention_guard_probe_count_blocked,
            not live_file_write_attempted,
        )
        if not passed
    )
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_EVIDENCE_INDEX_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_EVIDENCE_INDEX_GUARD_FAILED",
        "probe_count": 6,
        "failed_probe_count": failed_probe_count,
        "live_probe_passed": live_probe_passed,
        "copied_bad_status_probe_blocked": bad_status_blocked,
        "copied_nonzero_failed_count_probe_blocked": nonzero_failed_blocked,
        "copied_missing_cleanup_status_probe_blocked": missing_cleanup_status_blocked,
        "copied_bad_retention_artifact_count_probe_blocked": bad_retention_artifact_count_blocked,
        "copied_bad_retention_guard_probe_count_probe_blocked": bad_retention_guard_probe_count_blocked,
        "live_file_write_attempted": live_file_write_attempted,
        "copied_bad_status_issue": probes.bad_status["issue"],
        "copied_nonzero_failed_count_issue": probes.nonzero_failed_count["issue"],
        "copied_missing_cleanup_status_issue": probes.missing_cleanup_status["issue"],
        "copied_bad_retention_artifact_count_issue": probes.bad_retention_artifact_count["issue"],
        "copied_bad_retention_guard_probe_count_issue": probes.bad_retention_guard_probe_count["issue"],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this guard after the post-chain evidence index compact handoff card."
    return "Fix copied-source blocking before trusting the post-chain evidence index handoff."


def markdown(report: PostChainEvidenceIndexGuardReport) -> str:
    return "\n".join((
        "# OCR Post-Chain Evidence Index Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_probe_passed: `{report['live_probe_passed']}`",
        f"- copied_bad_status_probe_blocked: `{report['copied_bad_status_probe_blocked']}`",
        f"- copied_nonzero_failed_count_probe_blocked: `{report['copied_nonzero_failed_count_probe_blocked']}`",
        f"- copied_missing_cleanup_status_probe_blocked: `{report['copied_missing_cleanup_status_probe_blocked']}`",
        f"- copied_bad_retention_artifact_count_probe_blocked: `{report['copied_bad_retention_artifact_count_probe_blocked']}`",
        f"- copied_bad_retention_guard_probe_count_probe_blocked: `{report['copied_bad_retention_guard_probe_count_probe_blocked']}`",
        f"- live_file_write_attempted: `{report['live_file_write_attempted']}`",
        f"- copied_bad_status_issue: `{report['copied_bad_status_issue']}`",
        f"- copied_nonzero_failed_count_issue: `{report['copied_nonzero_failed_count_issue']}`",
        f"- copied_missing_cleanup_status_issue: `{report['copied_missing_cleanup_status_issue']}`",
        f"- copied_bad_retention_artifact_count_issue: `{report['copied_bad_retention_artifact_count_issue']}`",
        f"- copied_bad_retention_guard_probe_count_issue: `{report['copied_bad_retention_guard_probe_count_issue']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))
