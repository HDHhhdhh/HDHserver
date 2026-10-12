from __future__ import annotations

from typing import TypedDict


class RefreshStepRow(TypedDict):
    order: int
    label: str
    command: str
    report_path: str
    exit_code: int | None
    ok: bool
    report_status: str
    report_rewritten: bool
    duration_seconds: float
    stdout_tail: str
    stderr_tail: str
    issue: str


class PostChainOperatorRefreshReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    ordered_step_count: int
    failed_step_count: int
    steps: list[RefreshStepRow]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str
