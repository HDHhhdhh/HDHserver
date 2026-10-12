# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_handoff_retention_manifest.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import (
    JsonObject,
    assert_common_safety,
    read_json_object,
    require_text_value,
)

ArtifactRole = Literal["canonical_operator_handoff", "regenerated_helper_artifact", "source_evidence"]
ArtifactKind = Literal["json", "markdown"]

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_retention_manifest.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_retention_manifest.md"


class ArtifactRow(TypedDict):
    label: str
    role: str
    kind: str
    path: str
    exists: bool
    safe_json: bool
    primary_handoff: bool


class HandoffRetentionManifestReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    artifact_count: int
    canonical_operator_handoff_count: int
    regenerated_helper_artifact_count: int
    source_evidence_count: int
    missing_artifact_count: int
    unsafe_json_artifact_count: int
    artifacts: list[ArtifactRow]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    label: str
    path: Path
    role: ArtifactRole
    kind: ArtifactKind
    expected_status: str | None
    primary_handoff: bool


ARTIFACT_SPECS: Final[tuple[ArtifactSpec, ...]] = (
    ArtifactSpec("operator_runbook", LAB / "ocr_preflight_env_split_operator_runbook.md", "canonical_operator_handoff", "markdown", None, True),
    ArtifactSpec("qa_start_here_markdown", LAB / "OCR_QA_START_HERE.md", "canonical_operator_handoff", "markdown", None, True),
    ArtifactSpec("post_chain_evidence_index_json", LAB / "ocr_post_chain_evidence_index.json", "canonical_operator_handoff", "json", "OCR_POST_CHAIN_EVIDENCE_INDEX_VERIFIED", True),
    ArtifactSpec("post_chain_evidence_index_markdown", LAB / "ocr_post_chain_evidence_index.md", "canonical_operator_handoff", "markdown", None, True),
    ArtifactSpec("post_chain_operator_refresh", LAB / "ocr_post_chain_operator_refresh.json", "source_evidence", "json", "OCR_POST_CHAIN_OPERATOR_REFRESH_VERIFIED", False),
    ArtifactSpec("post_chain_operator_refresh_guard", LAB / "ocr_post_chain_operator_refresh_guard.json", "regenerated_helper_artifact", "json", "OCR_POST_CHAIN_OPERATOR_REFRESH_GUARD_VERIFIED", False),
    ArtifactSpec("post_chain_evidence_index_guard", LAB / "ocr_post_chain_evidence_index_guard.json", "regenerated_helper_artifact", "json", "OCR_POST_CHAIN_EVIDENCE_INDEX_GUARD_VERIFIED", False),
    ArtifactSpec("qa_start_here_evidence_index_freshness_json", LAB / "ocr_qa_start_here_evidence_index_freshness.json", "regenerated_helper_artifact", "json", "OCR_QA_START_HERE_EVIDENCE_INDEX_FRESHNESS_VERIFIED", False),
    ArtifactSpec("qa_start_here_evidence_index_freshness_markdown", LAB / "ocr_qa_start_here_evidence_index_freshness.md", "regenerated_helper_artifact", "markdown", None, False),
    ArtifactSpec("evidence_index_rendered_summary_guard", LAB / "ocr_post_chain_evidence_index_rendered_summary_guard.json", "regenerated_helper_artifact", "json", "OCR_POST_CHAIN_EVIDENCE_INDEX_RENDERED_SUMMARY_GUARD_VERIFIED", False),
    ArtifactSpec("evidence_index_rendered_summary_guard_rendered_summary", LAB / "ocr_post_chain_evidence_index_rendered_summary_guard_rendered_summary.json", "regenerated_helper_artifact", "json", "OCR_POST_CHAIN_EVIDENCE_INDEX_RENDERED_SUMMARY_GUARD_RENDERED_SUMMARY_VERIFIED", False),
    ArtifactSpec("handoff_retention_manifest_guard_rendered_summary", LAB / "ocr_post_chain_handoff_retention_manifest_guard_rendered_summary.json", "regenerated_helper_artifact", "json", "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_GUARD_RENDERED_SUMMARY_VERIFIED", False),
    ArtifactSpec("queue_state_guard", LAB / "ocr_next_action_queue_state_guard.json", "regenerated_helper_artifact", "json", "OCR_NEXT_ACTION_QUEUE_STATE_GUARD_VERIFIED", False),
    ArtifactSpec("runbook_rendered_summary", LAB / "ocr_preflight_operator_runbook_rendered_summary.json", "regenerated_helper_artifact", "json", "OCR_PREFLIGHT_OPERATOR_RUNBOOK_RENDERED_SUMMARY_VERIFIED", False),
    ArtifactSpec("runbook_consistency", LAB / "ocr_preflight_operator_runbook_consistency.json", "regenerated_helper_artifact", "json", "OCR_PREFLIGHT_OPERATOR_RUNBOOK_CONSISTENT", False),
)


def main() -> int:
    rows = [artifact_row(spec) for spec in ARTIFACT_SPECS]
    report = build_report(rows)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def artifact_row(spec: ArtifactSpec) -> ArtifactRow:
    exists = spec.path.exists()
    return {
        "label": spec.label,
        "role": spec.role,
        "kind": spec.kind,
        "path": display_path(spec.path),
        "exists": exists,
        "safe_json": json_artifact_is_safe(spec) if exists and spec.kind == "json" else True,
        "primary_handoff": spec.primary_handoff,
    }


def json_artifact_is_safe(spec: ArtifactSpec) -> bool:
    payload = read_json_object(spec.path)
    assert_common_safety(spec.label, payload)
    if spec.expected_status is not None:
        require_text_value(payload.get("status"), spec.expected_status, f"{spec.label}.status")
    return True


def build_report(rows: list[ArtifactRow]) -> HandoffRetentionManifestReport:
    missing_count = sum(1 for row in rows if not row["exists"])
    unsafe_json_count = sum(1 for row in rows if not row["safe_json"])
    ok = missing_count == 0 and unsafe_json_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_FAILED",
        "artifact_count": len(rows),
        "canonical_operator_handoff_count": role_count(rows, "canonical_operator_handoff"),
        "regenerated_helper_artifact_count": role_count(rows, "regenerated_helper_artifact"),
        "source_evidence_count": role_count(rows, "source_evidence"),
        "missing_artifact_count": missing_count,
        "unsafe_json_artifact_count": unsafe_json_count,
        "artifacts": rows,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def role_count(rows: list[ArtifactRow], role: ArtifactRole) -> int:
    return sum(1 for row in rows if row["role"] == role)


def display_path(path: Path) -> str:
    return f"tools/subjective_sheet_lab/{path.name}"


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Use canonical_operator_handoff files for manual QA; regenerate helper artifacts as needed."
    return "Refresh or recreate missing/unsafe post-chain handoff artifacts before manual QA."


def markdown(report: HandoffRetentionManifestReport) -> str:
    artifact_lines = [
        f"- `{row['role']}` `{row['label']}`: `{row['path']}` exists=`{row['exists']}` safe_json=`{row['safe_json']}`"
        for row in report["artifacts"]
    ]
    return "\n".join((
        "# OCR Post-Chain Handoff Retention Manifest",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- artifact_count: `{report['artifact_count']}`",
        f"- canonical_operator_handoff_count: `{report['canonical_operator_handoff_count']}`",
        f"- regenerated_helper_artifact_count: `{report['regenerated_helper_artifact_count']}`",
        f"- source_evidence_count: `{report['source_evidence_count']}`",
        f"- missing_artifact_count: `{report['missing_artifact_count']}`",
        f"- unsafe_json_artifact_count: `{report['unsafe_json_artifact_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Artifacts",
        *artifact_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
