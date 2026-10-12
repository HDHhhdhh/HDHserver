# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by verify_ocr_root_cause_dashboard.py

from __future__ import annotations

from ocr_provider_free_extended_gate_common import JsonObject


def markdown_report(dashboard: JsonObject) -> str:
    lines = [
        "# OCR Root Cause Dashboard",
        "",
        "| bucket | items | next action |",
        "|---|---:|---|",
    ]
    for item in dashboard["buckets"]:
        lines.append(f"| `{item['bucket']}` | {item['item_count']} | {item['action']} |")
    lines.extend(
        (
            "",
            "## Evidence",
            "",
            f"- Extended provider-free gate count: {dashboard['extended_gate_count']}",
            f"- High-priority review-required rows: {dashboard['high_priority_review_required_count']}",
            f"- High-priority auto-fill allowed rows: {dashboard['high_priority_auto_fill_allowed_count']}",
            f"- Wrong safe auto grade rows: {dashboard['wrong_safe_auto_grade']}",
            f"- Digit-shape candidate comparison rows: {dashboard['digit_shape_candidate_comparison_row_count']}",
            f"- Digit-shape candidate comparison review-required rows: {dashboard['digit_shape_candidate_comparison_review_required_count']}",
            f"- Training Pack source assets ready: {dashboard['training_pack_source_assets_ready_count']}",
            f"- Training Pack cache replay payloads: {dashboard['training_pack_cache_replay_payload_count']}",
            "- Gemini/API calls: 0",
            "- External OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- Production default: `NO_GO`",
            "",
        )
    )
    return "\n".join(lines)


def sensitive_leak_count(text: str) -> int:
    forbidden = ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "grading")
    return sum(text.count(token) for token in forbidden)


def filesystem_path_leak_count(text: str) -> int:
    return text.count("C:\\") + text.count("C:/") + text.count("/c/")
