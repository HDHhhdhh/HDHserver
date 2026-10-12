# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_cleanup_candidate_manifest.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, Literal, TypedDict, assert_never

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    assert_common_safety,
    read_json_object,
    require_int,
    require_int_value,
    require_object,
    require_text_value,
)
import verify_ocr_post_chain_handoff_retention_manifest as retention

CleanupAction = Literal["keep_for_manual_qa", "retain_source_evidence", "recreate_only"]

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_cleanup_candidate_manifest.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_cleanup_candidate_manifest.md"


class CleanupCandidateRow(TypedDict):
    label: str
    role: str
    kind: str
    path: str
    action: CleanupAction
    keep_for_manual_qa: bool
    recreate_allowed: bool
    delete_allowed: bool
    move_allowed: bool
    reason: str


class CleanupCandidateManifestReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    source_manifest_path: str
    source_manifest_status: str
    candidate_count: int
    keep_for_manual_qa_count: int
    retain_source_evidence_count: int
    recreate_only_count: int
    delete_candidate_count: int
    move_candidate_count: int
    destructive_action_attempted: bool
    candidates: list[CleanupCandidateRow]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    payload = read_json_object(retention.REPORT_JSON_OUT)
    candidates = cleanup_candidates(payload)
    report = build_report(payload, candidates)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def cleanup_candidates(payload: JsonObject) -> list[CleanupCandidateRow]:
    assert_retention_manifest(payload)
    return [candidate_row(require_object(raw_row, "retention.artifacts[]")) for raw_row in require_list(payload.get("artifacts"), "retention.artifacts")]


def assert_retention_manifest(payload: JsonObject) -> None:
    assert_common_safety("handoff_retention_manifest", payload)
    require_text_value(
        payload.get("status"),
        "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_VERIFIED",
        "handoff_retention_manifest.status",
    )
    require_int_value(payload.get("missing_artifact_count"), 0, "handoff_retention_manifest.missing_artifact_count")
    require_int_value(payload.get("unsafe_json_artifact_count"), 0, "handoff_retention_manifest.unsafe_json_artifact_count")


def candidate_row(row: JsonObject) -> CleanupCandidateRow:
    label = require_text(row.get("label"), "artifact.label")
    role = require_text(row.get("role"), f"{label}.role")
    kind = require_text(row.get("kind"), f"{label}.kind")
    path = require_text(row.get("path"), f"{label}.path")
    action = action_for_role(role)
    return {
        "label": label,
        "role": role,
        "kind": kind,
        "path": path,
        "action": action,
        "keep_for_manual_qa": action == "keep_for_manual_qa",
        "recreate_allowed": action == "recreate_only",
        "delete_allowed": False,
        "move_allowed": False,
        "reason": reason_for_action(action),
    }


def action_for_role(role: str) -> CleanupAction:
    match role:
        case "canonical_operator_handoff":
            return "keep_for_manual_qa"
        case "source_evidence":
            return "retain_source_evidence"
        case "regenerated_helper_artifact":
            return "recreate_only"
        case str():
            raise ExtendedGateError(f"unsupported retention role: {role}")
        case unreachable:
            assert_never(unreachable)


def reason_for_action(action: CleanupAction) -> str:
    match action:
        case "keep_for_manual_qa":
            return "canonical operator handoff artifact"
        case "retain_source_evidence":
            return "source evidence used to rebuild compact handoff reports"
        case "recreate_only":
            return "helper artifact can be regenerated, but this manifest never deletes it"
        case unreachable:
            assert_never(unreachable)


def build_report(payload: JsonObject, candidates: list[CleanupCandidateRow]) -> CleanupCandidateManifestReport:
    delete_count = sum(1 for row in candidates if row["delete_allowed"])
    move_count = sum(1 for row in candidates if row["move_allowed"])
    artifact_count = require_int(payload.get("artifact_count"), "artifact_count")
    ok = delete_count == 0 and move_count == 0 and len(candidates) == artifact_count
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_FAILED",
        "source_manifest_path": "tools/subjective_sheet_lab/ocr_post_chain_handoff_retention_manifest.json",
        "source_manifest_status": "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_VERIFIED",
        "candidate_count": len(candidates),
        "keep_for_manual_qa_count": action_count(candidates, "keep_for_manual_qa"),
        "retain_source_evidence_count": action_count(candidates, "retain_source_evidence"),
        "recreate_only_count": action_count(candidates, "recreate_only"),
        "delete_candidate_count": delete_count,
        "move_candidate_count": move_count,
        "destructive_action_attempted": False,
        "candidates": candidates,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": "Use this as a read-only cleanup guide; do not delete helper artifacts without explicit approval."
        if ok
        else "Refresh the retention manifest before using cleanup guidance.",
    }


def action_count(candidates: list[CleanupCandidateRow], action: CleanupAction) -> int:
    return sum(1 for row in candidates if row["action"] == action)


def require_list(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError(f"{label} must be a list")
        case unreachable:
            assert_never(unreachable)


def require_text(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value.strip()
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def markdown(report: CleanupCandidateManifestReport) -> str:
    candidate_lines = [
        f"- `{row['action']}` `{row['label']}`: `{row['path']}` delete_allowed=`{row['delete_allowed']}`"
        for row in report["candidates"]
    ]
    return "\n".join((
        "# OCR Post-Chain Cleanup Candidate Manifest",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- source_manifest_path: `{report['source_manifest_path']}`",
        f"- source_manifest_status: `{report['source_manifest_status']}`",
        f"- candidate_count: `{report['candidate_count']}`",
        f"- keep_for_manual_qa_count: `{report['keep_for_manual_qa_count']}`",
        f"- retain_source_evidence_count: `{report['retain_source_evidence_count']}`",
        f"- recreate_only_count: `{report['recreate_only_count']}`",
        f"- delete_candidate_count: `{report['delete_candidate_count']}`",
        f"- move_candidate_count: `{report['move_candidate_count']}`",
        f"- destructive_action_attempted: `{report['destructive_action_attempted']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Candidates",
        *candidate_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
