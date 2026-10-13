# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by verify_ocr_training_pack_recognized_evidence_start_card.py.

from __future__ import annotations

from ocr_training_pack_recognized_evidence_start_card_model import StartCardReport


def start_card_markdown(report: StartCardReport) -> str:
    file_lines = [f"- `{item['required_file_name']}` for `{item['test_id']}`" for item in report["required_files"]]
    return "\n".join((
        "# OCR Training Pack Recognized Evidence Start Here",
        "",
        f"- status: `{report['status']}`",
        f"- current_blocker: `{report['current_blocker']}`",
        f"- next_action: `{report['next_action']}`",
        f"- required_file_count: `{report['required_file_count']}`",
        f"- missing_file_count: `{report['missing_file_count']}`",
        f"- handoff_step_count: `{report['handoff_step_count']}`",
        f"- handoff_failed_step_count: `{report['handoff_failed_step_count']}`",
        f"- rendered_summary_guard_failed_probe_count: `{report['rendered_summary_guard_failed_probe_count']}`",
        "- provider_call_count: `0`",
        "- external_ocr_api_call_count: `0`",
        "- submit_test_call_count: `0`",
        "- ts_submit_click_count: `0`",
        "- production_default: `NO_GO`",
        "",
        "## Required Files",
        *file_lines,
        "",
        "## One Command",
        "`python tools/subjective_sheet_lab/verify_ocr_training_pack_recognized_evidence_handoff_runner.py`",
        "",
        "## Stop Rule",
        "Do not promote, replace benchmark outputs, recompute accuracy, or touch runtime data until the handoff runner passes after all four files arrive.",
        "",
    ))


def report_markdown(report: StartCardReport) -> str:
    return "\n".join((
        "# OCR Training Pack Recognized Evidence Start Card Report",
        "",
        f"- ok: `{report['ok']}`",
        f"- status: `{report['status']}`",
        f"- card_required_snippet_count: `{report['card_required_snippet_count']}`",
        f"- card_missing_snippet_count: `{report['card_missing_snippet_count']}`",
        f"- card_forbidden_snippet_count: `{report['card_forbidden_snippet_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))
