# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_evidence_index_rendered_summary_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import read_json_object
from ocr_post_chain_evidence_index_rendered_summary_guard_model import (
    EvidenceRenderedGuardReport,
    build_guard_report,
    build_probes,
)
from ocr_preflight_environment_matrix_model import LAB
import verify_ocr_post_chain_evidence_index as evidence_index

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_index_rendered_summary_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_index_rendered_summary_guard.md"


def main() -> int:
    live_mtime_before = evidence_index.REPORT_MD_OUT.stat().st_mtime_ns
    evidence_payload = read_json_object(evidence_index.REPORT_JSON_OUT)
    live_text = evidence_index.REPORT_MD_OUT.read_text(encoding="utf-8")
    probes = build_probes(evidence_payload, live_text)
    live_mtime_after = evidence_index.REPORT_MD_OUT.stat().st_mtime_ns
    report = build_guard_report(probes, live_mtime_before != live_mtime_after)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def markdown(report: EvidenceRenderedGuardReport) -> str:
    probe_lines = [f"- {probe['name']}: ok `{probe['ok']}`, blocked `{probe['blocked']}`" for probe in report["probes"]]
    return "\n".join((
        "# OCR Post-Chain Evidence Index Rendered Summary Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_evidence_markdown_write_attempted: `{report['live_evidence_markdown_write_attempted']}`",
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
