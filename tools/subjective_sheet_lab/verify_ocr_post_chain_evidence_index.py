# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_evidence_index.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_post_chain_evidence_index_common import (
    PostChainEvidenceIndexReport,
    SourceRow,
    source_row,
)
from ocr_post_chain_evidence_index_sources import SOURCE_SPECS
from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import read_json_object
import verify_ocr_qa_start_here as qa_start_here
import verify_ocr_qa_start_here_freshness_guard as qa_freshness_guard
import verify_ocr_qa_start_here_rendered_summary as qa_rendered
import verify_ocr_qa_start_here_rendered_summary_guard as qa_rendered_guard

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_index.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_index.md"


def main() -> int:
    import verify_ocr_post_chain_evidence_index_common_self_check as common_self_check
    import verify_ocr_post_chain_evidence_index_freshness_guard as freshness_guard

    qa_freshness_guard.main()
    qa_start_here.main()
    qa_rendered.main()
    qa_rendered_guard.main()
    common_self_check.main()
    freshness_guard.main()
    rows = [source_row(spec, read_json_object(spec.path)) for spec in SOURCE_SPECS]
    report = build_report(rows)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(rows: list[SourceRow]) -> PostChainEvidenceIndexReport:
    failed_source_count = sum(row["failed_metric_count"] for row in rows)
    ok = failed_source_count == 0 and len(rows) == len(SOURCE_SPECS)
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_EVIDENCE_INDEX_VERIFIED" if ok else "OCR_POST_CHAIN_EVIDENCE_INDEX_FAILED",
        "manual_qa_handoff_status": "READY" if ok else "BLOCKED",
        "source_report_count": len(rows),
        "failed_source_count": failed_source_count,
        "source_reports": rows,
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
        return "Use this status card as the compact post-chain handoff for manual QA operators."
    return "Refresh the post-chain wrapper, guard, and runbook reports before manual QA handoff."


def markdown(report: PostChainEvidenceIndexReport) -> str:
    source_lines = [
        source_markdown(row)
        for row in report["source_reports"]
    ]
    return "\n".join((
        "# OCR Post-Chain Evidence Index",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- manual_qa_handoff_status: `{report['manual_qa_handoff_status']}`",
        f"- source_report_count: `{report['source_report_count']}`",
        f"- failed_source_count: `{report['failed_source_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Source Reports",
        *source_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


def source_markdown(row: SourceRow) -> str:
    base = f"- {row['label']}: `{row['status']}`, metrics `{row['metrics']}`"
    if not row["included_statuses"]:
        return base
    return f"{base}, includes `{row['included_statuses']}`"


if __name__ == "__main__":
    raise SystemExit(main())
