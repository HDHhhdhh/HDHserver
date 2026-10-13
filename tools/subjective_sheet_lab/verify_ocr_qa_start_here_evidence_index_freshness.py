# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_qa_start_here_evidence_index_freshness.py

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from verify_ocr_post_chain_evidence_index import REPORT_JSON_OUT as EVIDENCE_INDEX_JSON
from verify_ocr_qa_start_here import START_HERE_MD

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_qa_start_here_evidence_index_freshness.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_qa_start_here_evidence_index_freshness.md"


class EvidenceIndexFreshnessReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_start_here_newer_than_evidence_index: bool
    copied_stale_evidence_index_blocked: bool
    copied_equal_boundary_passed: bool
    copied_fresh_start_here_passed: bool
    start_here_modified_ns: int
    evidence_index_modified_ns: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class CopiedFreshnessProbe:
    stale_blocked: bool
    equal_passed: bool
    fresh_passed: bool


def main() -> int:
    report = build_report(
        start_here_modified_ns=START_HERE_MD.stat().st_mtime_ns,
        evidence_index_modified_ns=EVIDENCE_INDEX_JSON.stat().st_mtime_ns,
        probe=copied_freshness_probe(),
    )
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def copied_freshness_probe() -> CopiedFreshnessProbe:
    with TemporaryDirectory(prefix="ocr_start_here_evidence_freshness_") as temp_dir:
        root = Path(temp_dir)
        start_here = root / "OCR_QA_START_HERE.md"
        evidence_index = root / "ocr_post_chain_evidence_index.json"
        start_here.write_text("# synthetic start card\n", encoding="utf-8")
        evidence_index.write_text("{}\n", encoding="utf-8")
        touch_ns(start_here, 100)
        touch_ns(evidence_index, 200)
        stale_blocked = not start_here_newer_than_evidence_index(start_here, evidence_index)
        touch_ns(start_here, 200)
        equal_passed = start_here_newer_than_evidence_index(start_here, evidence_index)
        touch_ns(start_here, 300)
        fresh_passed = start_here_newer_than_evidence_index(start_here, evidence_index)
        return CopiedFreshnessProbe(stale_blocked, equal_passed, fresh_passed)


def start_here_newer_than_evidence_index(start_here: Path, evidence_index: Path) -> bool:
    return start_here.stat().st_mtime_ns >= evidence_index.stat().st_mtime_ns


def touch_ns(path: Path, timestamp_ns: int) -> None:
    os.utime(path, ns=(timestamp_ns, timestamp_ns))


def build_report(
    *,
    start_here_modified_ns: int,
    evidence_index_modified_ns: int,
    probe: CopiedFreshnessProbe,
) -> EvidenceIndexFreshnessReport:
    live_fresh = start_here_modified_ns >= evidence_index_modified_ns
    failed_probe_count = sum(
        1
        for passed in (
            live_fresh,
            probe.stale_blocked,
            probe.equal_passed,
            probe.fresh_passed,
        )
        if not passed
    )
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_QA_START_HERE_EVIDENCE_INDEX_FRESHNESS_VERIFIED"
        if ok
        else "OCR_QA_START_HERE_EVIDENCE_INDEX_FRESHNESS_FAILED",
        "probe_count": 4,
        "failed_probe_count": failed_probe_count,
        "live_start_here_newer_than_evidence_index": live_fresh,
        "copied_stale_evidence_index_blocked": probe.stale_blocked,
        "copied_equal_boundary_passed": probe.equal_passed,
        "copied_fresh_start_here_passed": probe.fresh_passed,
        "start_here_modified_ns": start_here_modified_ns,
        "evidence_index_modified_ns": evidence_index_modified_ns,
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
        return "Keep the start-card evidence-index freshness verifier after the post-chain evidence index."
    return "Regenerate OCR_QA_START_HERE.md after the post-chain evidence index before manual-QA handoff."


def markdown(report: EvidenceIndexFreshnessReport) -> str:
    return "\n".join((
        "# OCR QA Start Here Evidence Index Freshness",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_start_here_newer_than_evidence_index: `{report['live_start_here_newer_than_evidence_index']}`",
        f"- copied_stale_evidence_index_blocked: `{report['copied_stale_evidence_index_blocked']}`",
        f"- copied_equal_boundary_passed: `{report['copied_equal_boundary_passed']}`",
        f"- copied_fresh_start_here_passed: `{report['copied_fresh_start_here_passed']}`",
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
