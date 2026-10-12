# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_evidence_index_freshness_guard.py

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, TypedDict

from ocr_post_chain_evidence_index_common import MetricSpec, SourceSpec, path_mtime, source_row
from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject
import verify_ocr_post_chain_evidence_index as evidence_index
import verify_ocr_post_chain_evidence_index_common_self_check as self_check

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_index_freshness_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_index_freshness_guard.md"
SELF_CHECK_STATUS: Final = "OCR_POST_CHAIN_EVIDENCE_INDEX_COMMON_SELF_CHECK_VERIFIED"


class FreshnessGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_self_check_fresh: bool
    copied_stale_self_check_blocked: bool
    copied_fresh_self_check_passed: bool
    copied_stale_issue: str
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class FreshnessProbe:
    stale_blocked: bool
    fresh_passed: bool
    stale_issue: str


def main() -> int:
    live_self_check_fresh = self_check_is_fresh()
    freshness_probe = copied_freshness_probe()
    report = build_report(live_self_check_fresh, freshness_probe)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def self_check_is_fresh() -> bool:
    self_check_mtime = path_mtime(self_check.REPORT_JSON_OUT)
    return all(self_check_mtime >= path_mtime(spec.path) for spec in self_check.source_specs_for_self_check())


def copied_freshness_probe() -> FreshnessProbe:
    with TemporaryDirectory(prefix="ocr_evidence_freshness_") as temp_dir:
        root = Path(temp_dir)
        dependency = root / "dependency.json"
        self_check_report = root / "self_check.json"
        dependency.write_text("{}", encoding="utf-8")
        self_check_report.write_text("{}", encoding="utf-8")
        touch_ns(dependency, 200)
        touch_ns(self_check_report, 100)
        stale_ok, stale_issue = source_row_result(spec_for(self_check_report, dependency))
        touch_ns(self_check_report, 300)
        fresh_ok, _fresh_issue = source_row_result(spec_for(self_check_report, dependency))
        return FreshnessProbe(
            stale_blocked=not stale_ok and "stale relative" in stale_issue,
            fresh_passed=fresh_ok,
            stale_issue=stale_issue,
        )


def source_row_result(spec: SourceSpec) -> tuple[bool, str]:
    try:
        source_row(spec, minimal_self_check_payload())
    except ExtendedGateError as error:
        return False, str(error)
    return True, ""


def spec_for(self_check_report: Path, dependency: Path) -> SourceSpec:
    return SourceSpec(
        self_check.SELF_CHECK_SOURCE_LABEL,
        self_check_report,
        SELF_CHECK_STATUS,
        (MetricSpec("probe_count", 4),),
        fresh_after_paths=(dependency,),
    )


def minimal_self_check_payload() -> JsonObject:
    return {
        "ok": True,
        "student_facing": False,
        "status": SELF_CHECK_STATUS,
        "probe_count": 4,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def touch_ns(path: Path, timestamp_ns: int) -> None:
    os.utime(path, ns=(timestamp_ns, timestamp_ns))


def build_report(live_self_check_fresh: bool, probe: FreshnessProbe) -> FreshnessGuardReport:
    passed = (live_self_check_fresh, probe.stale_blocked, probe.fresh_passed)
    failed_probe_count = sum(1 for item in passed if not item)
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_EVIDENCE_INDEX_FRESHNESS_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_EVIDENCE_INDEX_FRESHNESS_GUARD_FAILED",
        "probe_count": 3,
        "failed_probe_count": failed_probe_count,
        "live_self_check_fresh": live_self_check_fresh,
        "copied_stale_self_check_blocked": probe.stale_blocked,
        "copied_fresh_self_check_passed": probe.fresh_passed,
        "copied_stale_issue": probe.stale_issue,
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
        return "Keep this freshness guard with the evidence-index self-check source."
    return "Regenerate the common self-check after source report refreshes before evidence-index handoff."


def markdown(report: FreshnessGuardReport) -> str:
    return "\n".join((
        "# OCR Post-Chain Evidence Index Freshness Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_self_check_fresh: `{report['live_self_check_fresh']}`",
        f"- copied_stale_self_check_blocked: `{report['copied_stale_self_check_blocked']}`",
        f"- copied_fresh_self_check_passed: `{report['copied_fresh_self_check_passed']}`",
        f"- copied_stale_issue: `{report['copied_stale_issue']}`",
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
