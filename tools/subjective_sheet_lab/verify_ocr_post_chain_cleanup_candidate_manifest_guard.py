# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_cleanup_candidate_manifest_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import JsonObject, read_json_object
import verify_ocr_post_chain_cleanup_candidate_manifest as cleanup
import verify_ocr_post_chain_handoff_retention_manifest as retention

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_cleanup_candidate_manifest_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_cleanup_candidate_manifest_guard.md"
ProbeName = Literal["live", "copied_delete_allowed", "copied_move_allowed"]


class ProbeResult(TypedDict):
    name: ProbeName
    ok: bool
    status: str
    delete_candidate_count: int
    move_candidate_count: int


class CleanupCandidateManifestGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_probe_passed: bool
    copied_delete_allowed_probe_blocked: bool
    copied_move_allowed_probe_blocked: bool
    live_file_write_attempted: bool
    copied_delete_allowed_delete_count: int
    copied_move_allowed_move_count: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class CleanupCandidateSnapshot:
    cleanup_json_modified_ns: int
    cleanup_md_modified_ns: int
    retention_json_modified_ns: int


@dataclass(frozen=True, slots=True)
class ProbeReports:
    live: ProbeResult
    delete_allowed: ProbeResult
    move_allowed: ProbeResult


@dataclass(frozen=True, slots=True)
class CleanupCandidateGuardError(RuntimeError):
    issue: str

    def __str__(self) -> str:
        return self.issue


def main() -> int:
    retention_payload = read_json_object(retention.REPORT_JSON_OUT)
    candidates = cleanup.cleanup_candidates(retention_payload)
    before = snapshot_live_files()
    probes = ProbeReports(
        live=run_probe("live", retention_payload, candidates),
        delete_allowed=run_probe("copied_delete_allowed", retention_payload, with_delete_allowed(candidates)),
        move_allowed=run_probe("copied_move_allowed", retention_payload, with_move_allowed(candidates)),
    )
    after = snapshot_live_files()
    report = build_guard_report(probes, before, after)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def snapshot_live_files() -> CleanupCandidateSnapshot:
    return CleanupCandidateSnapshot(
        cleanup_json_modified_ns=path_mtime(cleanup.REPORT_JSON_OUT),
        cleanup_md_modified_ns=path_mtime(cleanup.REPORT_MD_OUT),
        retention_json_modified_ns=path_mtime(retention.REPORT_JSON_OUT),
    )


def path_mtime(path: Path) -> int:
    if path.exists():
        return path.stat().st_mtime_ns
    return -1


def run_probe(
    name: ProbeName,
    payload: JsonObject,
    candidates: list[cleanup.CleanupCandidateRow],
) -> ProbeResult:
    report = cleanup.build_report(payload, candidates)
    return {
        "name": name,
        "ok": report["ok"],
        "status": report["status"],
        "delete_candidate_count": report["delete_candidate_count"],
        "move_candidate_count": report["move_candidate_count"],
    }


def with_delete_allowed(
    candidates: list[cleanup.CleanupCandidateRow],
) -> list[cleanup.CleanupCandidateRow]:
    copied = copied_candidates(candidates)
    for index, row in enumerate(copied):
        if row["recreate_allowed"]:
            copied[index] = {**row, "delete_allowed": True}
            return copied
    raise CleanupCandidateGuardError("recreate-only cleanup row was not available for delete probe")


def with_move_allowed(
    candidates: list[cleanup.CleanupCandidateRow],
) -> list[cleanup.CleanupCandidateRow]:
    copied = copied_candidates(candidates)
    for index, row in enumerate(copied):
        if row["keep_for_manual_qa"]:
            copied[index] = {**row, "move_allowed": True}
            return copied
    raise CleanupCandidateGuardError("manual-QA cleanup row was not available for move probe")


def copied_candidates(
    candidates: list[cleanup.CleanupCandidateRow],
) -> list[cleanup.CleanupCandidateRow]:
    return [row.copy() for row in candidates]


def build_guard_report(
    probes: ProbeReports,
    before: CleanupCandidateSnapshot,
    after: CleanupCandidateSnapshot,
) -> CleanupCandidateManifestGuardReport:
    live_probe_passed = (
        probes.live["ok"] is True
        and probes.live["status"] == "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_VERIFIED"
        and probes.live["delete_candidate_count"] == 0
        and probes.live["move_candidate_count"] == 0
    )
    delete_probe_blocked = (
        probes.delete_allowed["ok"] is False
        and probes.delete_allowed["status"] == "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_FAILED"
        and probes.delete_allowed["delete_candidate_count"] == 1
    )
    move_probe_blocked = (
        probes.move_allowed["ok"] is False
        and probes.move_allowed["status"] == "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_FAILED"
        and probes.move_allowed["move_candidate_count"] == 1
    )
    live_file_write_attempted = before != after
    failed_probe_count = sum(
        1
        for passed in (live_probe_passed, delete_probe_blocked, move_probe_blocked, not live_file_write_attempted)
        if not passed
    )
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_GUARD_FAILED",
        "probe_count": 3,
        "failed_probe_count": failed_probe_count,
        "live_probe_passed": live_probe_passed,
        "copied_delete_allowed_probe_blocked": delete_probe_blocked,
        "copied_move_allowed_probe_blocked": move_probe_blocked,
        "live_file_write_attempted": live_file_write_attempted,
        "copied_delete_allowed_delete_count": probes.delete_allowed["delete_candidate_count"],
        "copied_move_allowed_move_count": probes.move_allowed["move_candidate_count"],
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
        return "Keep this guard after the cleanup candidate manifest before cleanup or operator handoff."
    return "Fix destructive cleanup blocking before using cleanup guidance."


def markdown(report: CleanupCandidateManifestGuardReport) -> str:
    return "\n".join((
        "# OCR Post-Chain Cleanup Candidate Manifest Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_probe_passed: `{report['live_probe_passed']}`",
        f"- copied_delete_allowed_probe_blocked: `{report['copied_delete_allowed_probe_blocked']}`",
        f"- copied_move_allowed_probe_blocked: `{report['copied_move_allowed_probe_blocked']}`",
        f"- live_file_write_attempted: `{report['live_file_write_attempted']}`",
        f"- copied_delete_allowed_delete_count: `{report['copied_delete_allowed_delete_count']}`",
        f"- copied_move_allowed_move_count: `{report['copied_move_allowed_move_count']}`",
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


if __name__ == "__main__":
    raise SystemExit(main())
