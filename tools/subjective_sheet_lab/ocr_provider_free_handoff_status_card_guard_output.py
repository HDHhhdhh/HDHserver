from __future__ import annotations

from typing import Final

from ocr_provider_free_extended_gate_common import JsonObject

MARKDOWN_FIELD_KEYS: Final[tuple[str, ...]] = (
    "ok",
    "student_facing",
    "status",
    "probe_count",
    "failed_probe_count",
    "live_status_card_passed",
    "copied_stale_guard_report_blocked",
    "copied_nonzero_source_count_blocked",
    "copied_final_metric_rejected",
    "copied_guard_metric_rejected",
    "copied_missing_helper_metric_rejected",
    "copied_probes_preserved_status_artifacts",
    "live_source_report_count",
    "live_stale_source_count",
    "live_failed_source_count",
    "provider_call_count",
    "external_ocr_api_call_count",
    "submit_test_call_count",
    "ts_submit_click_count",
    "answer_key_or_grading_field_leak_count",
    "filesystem_path_leak_count",
    "production_default",
)


def markdown(report: JsonObject) -> str:
    field_lines = [f"- {key}: `{report[key]}`" for key in MARKDOWN_FIELD_KEYS]
    return "\n".join((
        "# OCR Provider-Free Handoff Status Card Guard",
        "",
        *field_lines,
        "",
        "## Next Safe Action",
        str(report["next_safe_action"]),
        "",
    ))
