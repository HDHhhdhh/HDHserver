from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject
from verify_ocr_post_chain_evidence_index_rendered_summary import build_report as build_rendered_summary

SOURCE_COUNT_LINE: Final[str] = "- source_report_count: `18`"
RETENTION_MANIFEST_STATUS: Final[str] = (
    "post_chain_handoff_retention_manifest: `OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_VERIFIED`"
)
RETENTION_MANIFEST_ARTIFACT_COUNT: Final[str] = "'artifact_count': 15"
RETENTION_GUARD_STATUS: Final[str] = (
    "post_chain_handoff_retention_manifest_guard: `OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_GUARD_VERIFIED`"
)
RETENTION_GUARD_PROBE_COUNT: Final[str] = "'probe_count': 9"
RETENTION_GUARD_QUEUE_COUNT: Final[str] = "'copied_missing_queue_state_guard_missing_count': 1"
RETENTION_GUARD_RENDERED_COUNT: Final[str] = "'copied_missing_evidence_rendered_guard_missing_count': 1"
RETENTION_GUARD_RENDERED_SUMMARY_COUNT: Final[str] = (
    "'copied_missing_evidence_rendered_guard_summary_missing_count': 1"
)
RETENTION_GUARD_RETENTION_SUMMARY_COUNT: Final[str] = (
    "'copied_missing_retention_guard_summary_missing_count': 1"
)
COMMAND_CHECKLIST_RENDERED_GUARD_STATUS: Final[str] = (
    "post_chain_handoff_command_checklist_rendered_summary_guard: "
    "`OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_RENDERED_SUMMARY_GUARD_VERIFIED`"
)
COMMAND_CHECKLIST_RENDERED_GUARD_PROBE_COUNT: Final[str] = "'probe_count': 6"
USER_ACTION_INVENTORY_STATUS: Final[str] = (
    "user_action_required_inventory: `OCR_USER_ACTION_REQUIRED_INVENTORY_VERIFIED`"
)
USER_ACTION_INVENTORY_ISSUE_COUNT: Final[str] = "'unexpected_issue_count': 0"
USER_ACTION_INVENTORY_GUARD_STATUS: Final[str] = (
    "user_action_required_inventory_guard: `OCR_USER_ACTION_REQUIRED_INVENTORY_GUARD_VERIFIED`"
)
USER_ACTION_INVENTORY_GUARD_PROBE_COUNT: Final[str] = "'probe_count': 16"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    ok: bool
    blocked: bool
    missing_snippet_count: int
    forbidden_snippet_count: int
    error: str


class ProbeJson(TypedDict):
    name: str
    ok: bool
    blocked: bool
    missing_snippet_count: int
    forbidden_snippet_count: int
    error: str


class EvidenceRenderedGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_evidence_markdown_write_attempted: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    probes: list[ProbeJson]
    next_safe_action: str


def build_probes(evidence_payload: JsonObject, live_text: str) -> tuple[ProbeResult, ...]:
    return (
        pass_probe("current_rendered", evidence_payload, live_text),
        block_missing_probe("missing_source_count", evidence_payload, live_text.replace(SOURCE_COUNT_LINE, "")),
        block_missing_probe(
            "missing_retention_manifest_status",
            evidence_payload,
            live_text.replace(RETENTION_MANIFEST_STATUS, ""),
        ),
        block_missing_probe(
            "missing_retention_manifest_artifact_count",
            evidence_payload,
            live_text.replace(RETENTION_MANIFEST_ARTIFACT_COUNT, ""),
        ),
        block_missing_probe(
            "missing_retention_guard_status",
            evidence_payload,
            live_text.replace(RETENTION_GUARD_STATUS, ""),
        ),
        block_missing_probe(
            "missing_retention_guard_probe_count",
            evidence_payload,
            live_text.replace(RETENTION_GUARD_PROBE_COUNT, ""),
        ),
        block_missing_probe(
            "missing_retention_guard_queue_count",
            evidence_payload,
            live_text.replace(RETENTION_GUARD_QUEUE_COUNT, ""),
        ),
        block_missing_probe(
            "missing_retention_guard_rendered_count",
            evidence_payload,
            live_text.replace(RETENTION_GUARD_RENDERED_COUNT, ""),
        ),
        block_missing_probe(
            "missing_retention_guard_rendered_summary_count",
            evidence_payload,
            live_text.replace(RETENTION_GUARD_RENDERED_SUMMARY_COUNT, ""),
        ),
        block_missing_probe(
            "missing_retention_guard_retention_summary_count",
            evidence_payload,
            live_text.replace(RETENTION_GUARD_RETENTION_SUMMARY_COUNT, ""),
        ),
        block_missing_probe(
            "missing_command_checklist_rendered_guard_status",
            evidence_payload,
            live_text.replace(COMMAND_CHECKLIST_RENDERED_GUARD_STATUS, ""),
        ),
        block_missing_probe(
            "missing_command_checklist_rendered_guard_probe_count",
            evidence_payload,
            live_text.replace(COMMAND_CHECKLIST_RENDERED_GUARD_PROBE_COUNT, ""),
        ),
        block_missing_probe(
            "missing_user_action_inventory_status",
            evidence_payload,
            live_text.replace(USER_ACTION_INVENTORY_STATUS, ""),
        ),
        block_missing_probe(
            "missing_user_action_inventory_issue_count",
            evidence_payload,
            live_text.replace(USER_ACTION_INVENTORY_ISSUE_COUNT, ""),
        ),
        block_missing_probe(
            "missing_user_action_inventory_guard_status",
            evidence_payload,
            live_text.replace(USER_ACTION_INVENTORY_GUARD_STATUS, ""),
        ),
        block_missing_probe(
            "missing_user_action_inventory_guard_probe_count",
            evidence_payload,
            live_text.replace(USER_ACTION_INVENTORY_GUARD_PROBE_COUNT, ""),
        ),
        block_forbidden_probe("forbidden_path", evidence_payload, f"{live_text}\nC:/server redacted probe\n"),
    )


def pass_probe(name: str, evidence_payload: JsonObject, markdown_text: str) -> ProbeResult:
    try:
        report = build_rendered_summary(evidence_payload, markdown_text)
    except ExtendedGateError as error:
        return ProbeResult(name, ok=False, blocked=False, missing_snippet_count=0, forbidden_snippet_count=0, error=str(error))
    ok = report["ok"] is True and report["missing_snippet_count"] == 0 and report["forbidden_snippet_count"] == 0
    return ProbeResult(
        name,
        ok=ok,
        blocked=False,
        missing_snippet_count=report["missing_snippet_count"],
        forbidden_snippet_count=report["forbidden_snippet_count"],
        error="" if ok else "current evidence index rendered summary did not pass",
    )


def block_missing_probe(name: str, evidence_payload: JsonObject, markdown_text: str) -> ProbeResult:
    try:
        report = build_rendered_summary(evidence_payload, markdown_text)
    except ExtendedGateError as error:
        return ProbeResult(name, ok=False, blocked=False, missing_snippet_count=0, forbidden_snippet_count=0, error=str(error))
    blocked = report["ok"] is False and report["missing_snippet_count"] > 0
    return ProbeResult(
        name,
        ok=blocked,
        blocked=blocked,
        missing_snippet_count=report["missing_snippet_count"],
        forbidden_snippet_count=report["forbidden_snippet_count"],
        error="" if blocked else "evidence index rendered summary accepted a missing snippet",
    )


def block_forbidden_probe(name: str, evidence_payload: JsonObject, markdown_text: str) -> ProbeResult:
    try:
        report = build_rendered_summary(evidence_payload, markdown_text)
    except ExtendedGateError as error:
        return ProbeResult(name, ok=False, blocked=False, missing_snippet_count=0, forbidden_snippet_count=0, error=str(error))
    blocked = report["ok"] is False and report["forbidden_snippet_count"] > 0
    return ProbeResult(
        name,
        ok=blocked,
        blocked=blocked,
        missing_snippet_count=report["missing_snippet_count"],
        forbidden_snippet_count=report["forbidden_snippet_count"],
        error="" if blocked else "evidence index rendered summary accepted a forbidden snippet",
    )


def build_guard_report(
    probes: tuple[ProbeResult, ...],
    live_evidence_markdown_write_attempted: bool,
) -> EvidenceRenderedGuardReport:
    failed_probe_count = sum(1 for probe in probes if not probe.ok)
    ok = failed_probe_count == 0 and not live_evidence_markdown_write_attempted
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_EVIDENCE_INDEX_RENDERED_SUMMARY_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_EVIDENCE_INDEX_RENDERED_SUMMARY_GUARD_FAILED",
        "probe_count": len(probes),
        "failed_probe_count": failed_probe_count,
        "live_evidence_markdown_write_attempted": live_evidence_markdown_write_attempted,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "probes": [probe_json(probe) for probe in probes],
        "next_safe_action": next_safe_action(ok),
    }


def probe_json(probe: ProbeResult) -> ProbeJson:
    return {
        "name": probe.name,
        "ok": probe.ok,
        "blocked": probe.blocked,
        "missing_snippet_count": probe.missing_snippet_count,
        "forbidden_snippet_count": probe.forbidden_snippet_count,
        "error": probe.error,
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep evidence index rendered-summary guard regression in the provider-free chain."
    return "Inspect evidence index rendered-summary guard probes before relying on compact evidence handoff."
