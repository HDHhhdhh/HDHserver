# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_chain_manifest_consistency_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import ExtendedGateError
from verify_ocr_provider_free_chain_manifest_consistency import (
    CHAIN_SOURCE,
    build_report,
    chain_step_count,
    chain_step_names,
)

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_chain_manifest_consistency_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_chain_manifest_consistency_guard.md"
CHAIN_MANIFEST_STEP: Final[str] = '    ("chain_manifest_consistency", verify_chain_manifest, CHAIN_MANIFEST_JSON),'
PREFLIGHT_READINESS_GUARD_STEP: Final[str] = (
    '    ("preflight_readiness_guard", verify_preflight_readiness_guard, PREFLIGHT_READINESS_GUARD_JSON),'
)
PREFLIGHT_READINESS_GUARD_DECOY_STEP: Final[str] = (
    '    ("preflight_readiness_guard_decoy", verify_queue_state, QUEUE_STATE_JSON),'
)
QUEUE_STATE_STEP: Final[str] = '    ("queue_state", verify_queue_state, QUEUE_STATE_JSON),'
OPERATOR_SUMMARY_STEP: Final[str] = '    ("operator_summary", verify_operator_summary, OPERATOR_SUMMARY_JSON),'
RUNBOOK_GUARD_STEP: Final[str] = (
    '    ("operator_runbook_consistency_guard", verify_runbook_consistency_guard, RUNBOOK_CONSISTENCY_GUARD_JSON),'
)
EXTRA_STEP: Final[str] = '    ("duplicate_chain_manifest_consistency", verify_chain_manifest, CHAIN_MANIFEST_JSON),'


class ProbeReport(TypedDict):
    name: str
    blocked: bool
    ok: bool
    actual_chain_step_count: int
    chain_step_count_delta: int
    missing_required_chain_step_count: int
    missing_required_chain_steps: list[str]


class ChainManifestGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    current_chain_source_probe_passed: bool
    missing_chain_manifest_step_blocked: bool
    preflight_readiness_guard_substitution_blocked: bool
    missing_operator_runbook_guard_step_blocked: bool
    extra_chain_step_blocked: bool
    chain_step_order_mutation_blocked: bool
    live_chain_write_attempted: bool
    probes: list[ProbeReport]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class Probe:
    name: str
    source_text: str


def main() -> int:
    before_mtime = CHAIN_SOURCE.stat().st_mtime_ns
    live_source = CHAIN_SOURCE.read_text(encoding="utf-8")
    report = build_guard_report(live_source, before_mtime)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_guard_report(live_source: str, before_mtime: int) -> ChainManifestGuardReport:
    probe_reports = [run_probe(probe) for probe in probes(live_source)]
    current_passed = probe_reports[0]["ok"] is True and probe_reports[0]["blocked"] is False
    missing_manifest_blocked = probe_reports[1]["blocked"]
    preflight_guard_substitution_blocked = probe_reports[2]["blocked"]
    missing_runbook_guard_blocked = probe_reports[3]["blocked"]
    extra_step_blocked = probe_reports[4]["blocked"]
    order_mutation_blocked = probe_reports[5]["blocked"]
    live_write_attempted = CHAIN_SOURCE.stat().st_mtime_ns != before_mtime
    failed_probe_count = sum(1 for probe in probe_reports if not expected_probe_outcome(probe))
    ok = failed_probe_count == 0 and not live_write_attempted
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_CHAIN_MANIFEST_CONSISTENCY_GUARD_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_CHAIN_MANIFEST_CONSISTENCY_GUARD_FAILED",
        "probe_count": len(probe_reports),
        "failed_probe_count": failed_probe_count,
        "current_chain_source_probe_passed": current_passed,
        "missing_chain_manifest_step_blocked": missing_manifest_blocked,
        "preflight_readiness_guard_substitution_blocked": preflight_guard_substitution_blocked,
        "missing_operator_runbook_guard_step_blocked": missing_runbook_guard_blocked,
        "extra_chain_step_blocked": extra_step_blocked,
        "chain_step_order_mutation_blocked": order_mutation_blocked,
        "live_chain_write_attempted": live_write_attempted,
        "probes": probe_reports,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def probes(live_source: str) -> tuple[Probe, ...]:
    return (
        Probe("current_chain_source", live_source),
        Probe("missing_chain_manifest_step", source_without_line(live_source, CHAIN_MANIFEST_STEP)),
        Probe(
            "preflight_readiness_guard_substitution",
            source_with_replacement(
                live_source,
                PREFLIGHT_READINESS_GUARD_STEP,
                PREFLIGHT_READINESS_GUARD_DECOY_STEP,
            ),
        ),
        Probe("missing_operator_runbook_guard_step", source_without_line(live_source, RUNBOOK_GUARD_STEP)),
        Probe("extra_chain_step", source_with_extra_step(live_source)),
        Probe("chain_step_order_mutation", source_with_swapped_lines(live_source, QUEUE_STATE_STEP, OPERATOR_SUMMARY_STEP)),
    )


def source_without_line(source_text: str, line_text: str) -> str:
    if line_text not in source_text:
        raise ExtendedGateError("chain probe target line was not found")
    return source_text.replace(f"{line_text}\n", "")


def source_with_extra_step(source_text: str) -> str:
    if CHAIN_MANIFEST_STEP not in source_text:
        raise ExtendedGateError("chain manifest step was not found")
    return source_text.replace(CHAIN_MANIFEST_STEP, f"{CHAIN_MANIFEST_STEP}\n{EXTRA_STEP}")


def source_with_replacement(source_text: str, old_line: str, new_line: str) -> str:
    if old_line not in source_text:
        raise ExtendedGateError("chain replacement probe target line was not found")
    return source_text.replace(old_line, new_line, 1)


def source_with_swapped_lines(source_text: str, first_line: str, second_line: str) -> str:
    if first_line not in source_text or second_line not in source_text:
        raise ExtendedGateError("chain order probe target line was not found")
    return source_text.replace(first_line, "__CHAIN_SWAP_TEMP__", 1).replace(second_line, first_line, 1).replace(
        "__CHAIN_SWAP_TEMP__",
        second_line,
        1,
    )


def run_probe(probe: Probe) -> ProbeReport:
    report = build_report(chain_step_count(probe.source_text), chain_step_names(probe.source_text))
    blocked = report["ok"] is False
    return {
        "name": probe.name,
        "blocked": blocked,
        "ok": report["ok"],
        "actual_chain_step_count": report["actual_chain_step_count"],
        "chain_step_count_delta": report["chain_step_count_delta"],
        "missing_required_chain_step_count": report["missing_required_chain_step_count"],
        "missing_required_chain_steps": report["missing_required_chain_steps"],
    }


def expected_probe_outcome(probe: ProbeReport) -> bool:
    if probe["name"] == "current_chain_source":
        return probe["ok"] is True and probe["blocked"] is False
    return probe["blocked"] is True


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep chain manifest consistency guard in the provider-free chain."
    return "Refresh chain manifest guard probes before treating the chain count as protected."


def markdown(report: ChainManifestGuardReport) -> str:
    probe_lines = [
        f"- {probe['name']}: blocked `{probe['blocked']}`, ok `{probe['ok']}`, "
        f"actual_chain_step_count `{probe['actual_chain_step_count']}`, "
        f"chain_step_count_delta `{probe['chain_step_count_delta']}`, "
        f"missing_required_chain_steps `{probe['missing_required_chain_steps']}`"
        for probe in report["probes"]
    ]
    return "\n".join((
        "# OCR Provider-Free Chain Manifest Consistency Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- current_chain_source_probe_passed: `{report['current_chain_source_probe_passed']}`",
        f"- missing_chain_manifest_step_blocked: `{report['missing_chain_manifest_step_blocked']}`",
        "- preflight_readiness_guard_substitution_blocked: "
        f"`{report['preflight_readiness_guard_substitution_blocked']}`",
        f"- missing_operator_runbook_guard_step_blocked: `{report['missing_operator_runbook_guard_step_blocked']}`",
        f"- extra_chain_step_blocked: `{report['extra_chain_step_blocked']}`",
        f"- chain_step_order_mutation_blocked: `{report['chain_step_order_mutation_blocked']}`",
        f"- live_chain_write_attempted: `{report['live_chain_write_attempted']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Probes",
        *probe_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
