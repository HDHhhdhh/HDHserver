from __future__ import annotations

from typing import Final

from ocr_post_chain_operator_refresh_model import PostChainOperatorRefreshReport


SUMMARY_FIELDS: Final[tuple[str, ...]] = (
    "ok",
    "student_facing",
    "status",
    "ordered_step_count",
    "failed_step_count",
    "provider_call_count",
    "external_ocr_api_call_count",
    "submit_test_call_count",
    "ts_submit_click_count",
    "answer_key_or_grading_field_leak_count",
    "filesystem_path_leak_count",
    "production_default",
)


def markdown(report: PostChainOperatorRefreshReport) -> str:
    field_lines = [f"- {field}: `{report[field]}`" for field in SUMMARY_FIELDS]
    step_lines = [
        f"- {row['order']}. {row['label']}: ok `{row['ok']}`, exit `{row['exit_code']}`, status `{row['report_status']}`"
        for row in report["steps"]
    ]
    return "\n".join((
        "# OCR Post-Chain Operator Refresh",
        "",
        *field_lines,
        "",
        "## Steps",
        *step_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))
