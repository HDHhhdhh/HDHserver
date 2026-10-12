from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from ocr_post_chain_evidence_index_common import path_mtime
import verify_ocr_post_chain_handoff_retention_manifest as manifest


class HandoffRetentionManifestGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_probe_passed: bool
    live_file_write_attempted: bool
    copied_missing_canonical_handoff_missing_count: int
    copied_missing_start_here_missing_count: int
    copied_missing_queue_state_guard_missing_count: int
    copied_missing_evidence_rendered_guard_missing_count: int
    copied_missing_evidence_rendered_guard_summary_missing_count: int
    copied_missing_retention_guard_summary_missing_count: int
    copied_missing_start_card_freshness_helper_missing_count: int
    copied_unsafe_helper_json_unsafe_count: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class HandoffRetentionSnapshot:
    artifact_modified_ns: tuple[int, ...]
    manifest_json_modified_ns: int
    manifest_md_modified_ns: int


@dataclass(frozen=True, slots=True)
class ProbeReports:
    live: manifest.HandoffRetentionManifestReport
    missing_canonical: manifest.HandoffRetentionManifestReport
    missing_start_here: manifest.HandoffRetentionManifestReport
    missing_queue_state_guard: manifest.HandoffRetentionManifestReport
    missing_evidence_rendered_guard: manifest.HandoffRetentionManifestReport
    missing_evidence_rendered_guard_summary: manifest.HandoffRetentionManifestReport
    missing_retention_guard_summary: manifest.HandoffRetentionManifestReport
    missing_start_card_freshness_helper: manifest.HandoffRetentionManifestReport
    unsafe_helper: manifest.HandoffRetentionManifestReport


@dataclass(frozen=True, slots=True)
class HandoffRetentionGuardError(RuntimeError):
    issue: str

    def __str__(self) -> str:
        return self.issue


def guard_report() -> HandoffRetentionManifestGuardReport:
    before = snapshot_live_files()
    rows = live_artifact_rows()
    probes = ProbeReports(
        live=manifest.build_report(rows),
        missing_canonical=manifest.build_report(with_missing_canonical_handoff(rows)),
        missing_start_here=manifest.build_report(with_missing_label(rows, "qa_start_here_markdown")),
        missing_queue_state_guard=manifest.build_report(with_missing_label(rows, "queue_state_guard")),
        missing_evidence_rendered_guard=manifest.build_report(
            with_missing_label(rows, "evidence_index_rendered_summary_guard"),
        ),
        missing_evidence_rendered_guard_summary=manifest.build_report(
            with_missing_label(rows, "evidence_index_rendered_summary_guard_rendered_summary"),
        ),
        missing_retention_guard_summary=manifest.build_report(
            with_missing_label(rows, "handoff_retention_manifest_guard_rendered_summary"),
        ),
        missing_start_card_freshness_helper=manifest.build_report(
            with_missing_label(rows, "qa_start_here_evidence_index_freshness_json"),
        ),
        unsafe_helper=manifest.build_report(with_unsafe_helper_json(rows)),
    )
    after = snapshot_live_files()
    return build_guard_report(probes, before, after)


def snapshot_live_files() -> HandoffRetentionSnapshot:
    return HandoffRetentionSnapshot(
        artifact_modified_ns=tuple(path_mtime(spec.path) for spec in manifest.ARTIFACT_SPECS),
        manifest_json_modified_ns=path_mtime(manifest.REPORT_JSON_OUT),
        manifest_md_modified_ns=path_mtime(manifest.REPORT_MD_OUT),
    )


def live_artifact_rows() -> list[manifest.ArtifactRow]:
    return [manifest.artifact_row(spec) for spec in manifest.ARTIFACT_SPECS]


def with_missing_canonical_handoff(rows: list[manifest.ArtifactRow]) -> list[manifest.ArtifactRow]:
    copied = copied_rows(rows)
    for index, row in enumerate(copied):
        if row["role"] == "canonical_operator_handoff":
            copied[index] = {**row, "exists": False}
            return copied
    raise HandoffRetentionGuardError("canonical operator handoff row was not available for probe")


def with_missing_label(rows: list[manifest.ArtifactRow], label: str) -> list[manifest.ArtifactRow]:
    copied = copied_rows(rows)
    for index, row in enumerate(copied):
        if row["label"] == label:
            copied[index] = {**row, "exists": False}
            return copied
    raise HandoffRetentionGuardError(f"{label} row was not available for probe")


def with_unsafe_helper_json(rows: list[manifest.ArtifactRow]) -> list[manifest.ArtifactRow]:
    copied = copied_rows(rows)
    for index, row in enumerate(copied):
        if row["role"] == "regenerated_helper_artifact" and row["kind"] == "json":
            copied[index] = {**row, "safe_json": False}
            return copied
    raise HandoffRetentionGuardError("regenerated helper JSON row was not available for probe")


def copied_rows(rows: list[manifest.ArtifactRow]) -> list[manifest.ArtifactRow]:
    return [row.copy() for row in rows]


def build_guard_report(
    probes: ProbeReports,
    before: HandoffRetentionSnapshot,
    after: HandoffRetentionSnapshot,
) -> HandoffRetentionManifestGuardReport:
    live_probe_passed = (
        probes.live["ok"] is True
        and probes.live["status"] == "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_VERIFIED"
        and probes.live["missing_artifact_count"] == 0
        and probes.live["unsafe_json_artifact_count"] == 0
    )
    missing_canonical_blocked = missing_artifact_probe_blocked(probes.missing_canonical)
    missing_start_here_blocked = missing_artifact_probe_blocked(probes.missing_start_here)
    missing_queue_state_guard_blocked = missing_artifact_probe_blocked(probes.missing_queue_state_guard)
    missing_evidence_rendered_guard_blocked = missing_artifact_probe_blocked(probes.missing_evidence_rendered_guard)
    missing_evidence_rendered_guard_summary_blocked = missing_artifact_probe_blocked(
        probes.missing_evidence_rendered_guard_summary,
    )
    missing_retention_guard_summary_blocked = missing_artifact_probe_blocked(probes.missing_retention_guard_summary)
    missing_start_card_freshness_helper_blocked = missing_artifact_probe_blocked(
        probes.missing_start_card_freshness_helper,
    )
    unsafe_helper_blocked = (
        probes.unsafe_helper["ok"] is False
        and probes.unsafe_helper["unsafe_json_artifact_count"] == 1
        and probes.unsafe_helper["status"] == "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_FAILED"
    )
    live_file_write_attempted = before != after
    failed_probe_count = sum(
        1
        for passed in (
            live_probe_passed,
            missing_canonical_blocked,
            missing_start_here_blocked,
            missing_queue_state_guard_blocked,
            missing_evidence_rendered_guard_blocked,
            missing_evidence_rendered_guard_summary_blocked,
            missing_retention_guard_summary_blocked,
            missing_start_card_freshness_helper_blocked,
            unsafe_helper_blocked,
            not live_file_write_attempted,
        )
        if not passed
    )
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_GUARD_FAILED",
        "probe_count": 9,
        "failed_probe_count": failed_probe_count,
        "live_probe_passed": live_probe_passed,
        "live_file_write_attempted": live_file_write_attempted,
        "copied_missing_canonical_handoff_missing_count": probes.missing_canonical["missing_artifact_count"],
        "copied_missing_start_here_missing_count": probes.missing_start_here["missing_artifact_count"],
        "copied_missing_queue_state_guard_missing_count": probes.missing_queue_state_guard["missing_artifact_count"],
        "copied_missing_evidence_rendered_guard_missing_count": probes.missing_evidence_rendered_guard[
            "missing_artifact_count"
        ],
        "copied_missing_evidence_rendered_guard_summary_missing_count": probes.missing_evidence_rendered_guard_summary[
            "missing_artifact_count"
        ],
        "copied_missing_retention_guard_summary_missing_count": probes.missing_retention_guard_summary[
            "missing_artifact_count"
        ],
        "copied_missing_start_card_freshness_helper_missing_count": probes.missing_start_card_freshness_helper[
            "missing_artifact_count"
        ],
        "copied_unsafe_helper_json_unsafe_count": probes.unsafe_helper["unsafe_json_artifact_count"],
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
        return "Keep this guard after the handoff retention manifest before cleanup or operator handoff."
    return "Fix retention manifest blocking before trusting manual-QA cleanup guidance."


def missing_artifact_probe_blocked(report: manifest.HandoffRetentionManifestReport) -> bool:
    return (
        report["ok"] is False
        and report["missing_artifact_count"] == 1
        and report["status"] == "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_FAILED"
    )


def markdown(report: HandoffRetentionManifestGuardReport) -> str:
    return "\n".join((
        "# OCR Post-Chain Handoff Retention Manifest Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_probe_passed: `{report['live_probe_passed']}`",
        f"- live_file_write_attempted: `{report['live_file_write_attempted']}`",
        f"- copied_missing_canonical_handoff_missing_count: `{report['copied_missing_canonical_handoff_missing_count']}`",
        f"- copied_missing_start_here_missing_count: `{report['copied_missing_start_here_missing_count']}`",
        f"- copied_missing_queue_state_guard_missing_count: `{report['copied_missing_queue_state_guard_missing_count']}`",
        "- copied_missing_evidence_rendered_guard_missing_count: "
        f"`{report['copied_missing_evidence_rendered_guard_missing_count']}`",
        "- copied_missing_evidence_rendered_guard_summary_missing_count: "
        f"`{report['copied_missing_evidence_rendered_guard_summary_missing_count']}`",
        "- copied_missing_retention_guard_summary_missing_count: "
        f"`{report['copied_missing_retention_guard_summary_missing_count']}`",
        "- copied_missing_start_card_freshness_helper_missing_count: "
        f"`{report['copied_missing_start_card_freshness_helper_missing_count']}`",
        f"- copied_unsafe_helper_json_unsafe_count: `{report['copied_unsafe_helper_json_unsafe_count']}`",
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
