from __future__ import annotations

from typing import assert_never

from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject, JsonValue


def start_here_markdown(output: JsonObject) -> str:
    return "\n".join((
        "# OCR QA Start Here",
        "",
        "이 문서는 provider-free gate 결과에서 자동 생성되는 OCR QA 시작점입니다.",
        "학생 화면에 표시하는 문서가 아니며, 운영 기본값은 계속 `NO_GO`입니다.",
        "",
        "## 현재 상태",
        "",
        f"- status: `{output['status']}`",
        f"- extended provider-free gate count: `{output['extended_gate_count']}`",
        f"- provider-free chain step count: `{output['chain_step_count']}`",
        f"- failed chain steps: `{output['failed_step_count']}`",
        f"- command checklist fresh: `{output['command_checklist_fresh_for_start_here']}`",
        f"- production default: `{output['production_default']}`",
        f"- ready now: `{output['ready_now']}`",
        f"- ready after required files: `{output['ready_after_required_files']}`",
        "",
        "## Freshness Guard",
        "",
        f"- regression report: `{output['freshness_guard_report_path']}`",
        f"- regression status: `{output['freshness_guard_status']}`",
        f"- probe count: `{output['freshness_guard_probe_count']}`",
        f"- stale vs operator summary blocked: `{output['freshness_guard_stale_operator_probe_blocked']}`",
        f"- stale vs count consistency blocked: `{output['freshness_guard_stale_count_probe_blocked']}`",
        "- stale manual handoff source blocked: "
        f"`{output['freshness_guard_stale_manual_handoff_source_probe_blocked']}`",
        "- stale manual handoff guard blocked: "
        f"`{output['freshness_guard_stale_manual_handoff_guard_probe_blocked']}`",
        f"- runbook rendered-summary guard: `{output['runbook_rendered_summary_guard_report_path']}`",
        f"- runbook rendered-summary guard status: `{output['runbook_rendered_summary_guard_status']}`",
        f"- runbook consistency guard: `{output['runbook_consistency_guard_report_path']}`",
        f"- runbook consistency guard status: `{output['runbook_consistency_guard_status']}`",
        "- count consistency guard: `tools/subjective_sheet_lab/ocr_extended_gate_count_consistency_guard.json`",
        "- count consistency rendered-path guard: "
        "`tools/subjective_sheet_lab/ocr_count_consistency_path_rendered_guard.json`",
        "- queue-state guard: `tools/subjective_sheet_lab/ocr_next_action_queue_state_guard.json`",
        f"- post-chain evidence index: `{output['post_chain_evidence_index_report_path']}`",
        f"- post-chain evidence index status: `{output['post_chain_evidence_index_status']}`",
        f"- post-chain evidence source reports: `{output['post_chain_evidence_index_source_report_count']}`",
        f"- post-chain evidence failed sources: `{output['post_chain_evidence_index_failed_source_count']}`",
        "- post-chain evidence manual QA handoff: "
        f"`{output['post_chain_evidence_index_manual_qa_handoff_status']}`",
        "- failed runbook rendered-summary guard blocked: "
        f"`{output['freshness_guard_failed_runbook_rendered_guard_probe_blocked']}`",
        "- failed runbook consistency guard blocked: "
        f"`{output['freshness_guard_failed_runbook_consistency_guard_probe_blocked']}`",
        f"- live start-here write attempted by regression: `{output['freshness_guard_live_start_here_write_attempted']}`",
        "",
        "## Manual QA Handoff Refresh",
        "",
        f"- report: `{output['manual_qa_handoff_refresh_report_path']}`",
        f"- guard report: `{output['manual_qa_handoff_refresh_guard_report_path']}`",
        f"- manual QA handoff refresh status: `{output['manual_qa_handoff_refresh_status']}`",
        f"- manual QA handoff refresh steps: `{output['manual_qa_handoff_refresh_step_count']}`",
        f"- manual QA handoff refresh failed steps: `{output['manual_qa_handoff_refresh_failed_step_count']}`",
        f"- manual QA handoff refresh guard status: `{output['manual_qa_handoff_refresh_guard_status']}`",
        f"- manual QA handoff refresh guard probes: `{output['manual_qa_handoff_refresh_guard_probe_count']}`",
        f"- manual QA handoff refresh guard failed probes: `{output['manual_qa_handoff_refresh_guard_failed_probe_count']}`",
        f"- manual QA handoff refresh guard live passed: `{output['manual_qa_handoff_refresh_guard_live_passed']}`",
        f"- serial guard report: `{output['manual_qa_handoff_refresh_serial_guard_report_path']}`",
        f"- serial guard status: `{output['manual_qa_handoff_refresh_serial_guard_status']}`",
        f"- serial guard probes: `{output['manual_qa_handoff_refresh_serial_guard_probe_count']}`",
        f"- serial guard failed probes: `{output['manual_qa_handoff_refresh_serial_guard_failed_probe_count']}`",
        f"- serial guard refresh busy blocked: `{output['manual_qa_handoff_refresh_serial_guard_refresh_busy_blocked']}`",
        f"- serial guard guard busy blocked: `{output['manual_qa_handoff_refresh_serial_guard_guard_busy_blocked']}`",
        f"- serial guard lock removed: `{output['manual_qa_handoff_refresh_serial_guard_lock_file_removed']}`",
        f"- serial guard artifacts preserved: `{output['manual_qa_handoff_refresh_serial_guard_artifacts_preserved']}`",
        f"- manual QA handoff refresh source artifacts: `{output['manual_qa_handoff_refresh_source_artifact_count']}`",
        f"- manual QA handoff refresh source latest modified ns: `{output['manual_qa_handoff_refresh_source_latest_modified_ns']}`",
        f"- manual QA handoff refresh report modified ns: `{output['manual_qa_handoff_refresh_report_modified_ns']}`",
        f"- manual QA handoff refresh guard report modified ns: `{output['manual_qa_handoff_refresh_guard_report_modified_ns']}`",
        "- manual QA handoff refresh serial guard report modified ns: "
        f"`{output['manual_qa_handoff_refresh_serial_guard_report_modified_ns']}`",
        f"- manual QA handoff refresh newer than sources: `{output['manual_qa_handoff_refresh_newer_than_sources']}`",
        "- manual QA handoff refresh guard newer than refresh: "
        f"`{output['manual_qa_handoff_refresh_guard_newer_than_refresh']}`",
        "- manual QA handoff refresh serial guard newer than guard: "
        f"`{output['manual_qa_handoff_refresh_serial_guard_newer_than_guard']}`",
        f"- manual QA handoff operator state: `{output['manual_qa_handoff_refresh_operator_state']}`",
        f"- manual QA handoff ready: `{output['manual_qa_handoff_refresh_manual_qa_ready']}`",
        "",
        "## 지금 해야 할 일",
        "",
        f"- next action: `{output['next_safe_action']}`",
        f"- blocker: `{output['current_blocker']}`",
        f"- required files: `{output['required_file_count']}`",
        f"- present files: `{output['present_file_count']}`",
        f"- missing files: `{output['missing_file_count']}`",
        f"- required review items per payload: `{output['required_review_item_count_per_payload']}`",
        f"- required question sequence: `{output['required_question_sequence']}`",
        "",
        "## 필요한 evidence 파일",
        "",
        *required_file_lines(output),
        "",
        "## Intake-only 검증 명령",
        "",
        *command_lines(output),
        "",
        "## 승인 필요 여부",
        "",
        "- Gemini/API provider call: not required for the next action.",
        "- API authorization: not required for the next action.",
        "- Promotion/write authorization: required before replacing benchmark/cache outputs.",
        "- Current status: `USER_ACTION_REQUIRED` for the four recognized evidence files.",
        "",
        "## 안전 카운트",
        "",
        f"- Gemini/API provider calls: `{output['provider_call_count']}`",
        f"- external OCR API calls: `{output['external_ocr_api_call_count']}`",
        f"- `/api/submit-test` calls: `{output['submit_test_call_count']}`",
        f"- `#tsSubmit` clicks: `{output['ts_submit_click_count']}`",
        f"- answer-key/grading leak count: `{output['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem path leak count: `{output['filesystem_path_leak_count']}`",
        "",
        "## 다음 실행 명령",
        "",
        "```powershell",
        "python tools\\subjective_sheet_lab\\verify_ocr_provider_free_gate_chain.py",
        "```",
        "",
        "이 명령은 provider-free 검증만 실행합니다. Gemini/API 호출, `/api/submit-test` 호출,",
        "`#tsSubmit` 클릭, production default enable은 하지 않습니다.",
        "",
    ))


def verification_markdown(output: JsonObject) -> str:
    return "\n".join((
        "# OCR QA Start Here Verification",
        "",
        f"- ok: `{output['ok']}`",
        f"- student_facing: `{output['student_facing']}`",
        f"- status: `{output['status']}`",
        f"- chain_step_count: `{output['chain_step_count']}`",
        f"- extended_gate_count: `{output['extended_gate_count']}`",
        f"- command_checklist_fresh_for_start_here: `{output['command_checklist_fresh_for_start_here']}`",
        f"- command_checklist_newer_than_operator_summary: `{output['command_checklist_newer_than_operator_summary']}`",
        f"- command_checklist_newer_than_count_consistency: `{output['command_checklist_newer_than_count_consistency']}`",
        f"- freshness_guard_status: `{output['freshness_guard_status']}`",
        f"- freshness_guard_stale_operator_probe_blocked: `{output['freshness_guard_stale_operator_probe_blocked']}`",
        f"- freshness_guard_stale_count_probe_blocked: `{output['freshness_guard_stale_count_probe_blocked']}`",
        "- freshness_guard_stale_manual_handoff_source_probe_blocked: "
        f"`{output['freshness_guard_stale_manual_handoff_source_probe_blocked']}`",
        "- freshness_guard_stale_manual_handoff_guard_probe_blocked: "
        f"`{output['freshness_guard_stale_manual_handoff_guard_probe_blocked']}`",
        f"- runbook_rendered_summary_guard_status: `{output['runbook_rendered_summary_guard_status']}`",
        f"- runbook_consistency_guard_status: `{output['runbook_consistency_guard_status']}`",
        f"- post_chain_evidence_index_status: `{output['post_chain_evidence_index_status']}`",
        f"- post_chain_evidence_index_source_report_count: `{output['post_chain_evidence_index_source_report_count']}`",
        f"- post_chain_evidence_index_failed_source_count: `{output['post_chain_evidence_index_failed_source_count']}`",
        "- freshness_guard_failed_runbook_rendered_guard_probe_blocked: "
        f"`{output['freshness_guard_failed_runbook_rendered_guard_probe_blocked']}`",
        "- freshness_guard_failed_runbook_consistency_guard_probe_blocked: "
        f"`{output['freshness_guard_failed_runbook_consistency_guard_probe_blocked']}`",
        f"- manual_qa_handoff_refresh_status: `{output['manual_qa_handoff_refresh_status']}`",
        f"- manual_qa_handoff_refresh_step_count: `{output['manual_qa_handoff_refresh_step_count']}`",
        f"- manual_qa_handoff_refresh_guard_status: `{output['manual_qa_handoff_refresh_guard_status']}`",
        f"- manual_qa_handoff_refresh_guard_probe_count: `{output['manual_qa_handoff_refresh_guard_probe_count']}`",
        f"- manual_qa_handoff_refresh_serial_guard_status: `{output['manual_qa_handoff_refresh_serial_guard_status']}`",
        f"- manual_qa_handoff_refresh_serial_guard_probe_count: `{output['manual_qa_handoff_refresh_serial_guard_probe_count']}`",
        f"- manual_qa_handoff_refresh_source_artifact_count: `{output['manual_qa_handoff_refresh_source_artifact_count']}`",
        f"- manual_qa_handoff_refresh_newer_than_sources: `{output['manual_qa_handoff_refresh_newer_than_sources']}`",
        "- manual_qa_handoff_refresh_guard_newer_than_refresh: "
        f"`{output['manual_qa_handoff_refresh_guard_newer_than_refresh']}`",
        "- manual_qa_handoff_refresh_serial_guard_newer_than_guard: "
        f"`{output['manual_qa_handoff_refresh_serial_guard_newer_than_guard']}`",
        f"- manual_qa_handoff_refresh_operator_state: `{output['manual_qa_handoff_refresh_operator_state']}`",
        f"- manual_qa_handoff_refresh_manual_qa_ready: `{output['manual_qa_handoff_refresh_manual_qa_ready']}`",
        f"- current_blocker: `{output['current_blocker']}`",
        f"- next_safe_action: `{output['next_safe_action']}`",
        f"- required/present/missing files: `{output['required_file_count']}/{output['present_file_count']}/{output['missing_file_count']}`",
        f"- intake_command_count: `{output['intake_command_count']}`",
        f"- provider_call_count: `{output['provider_call_count']}`",
        f"- submit_test_call_count: `{output['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{output['ts_submit_click_count']}`",
        f"- answer-key/grading leak count: `{output['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem path leak count: `{output['filesystem_path_leak_count']}`",
        f"- production_default: `{output['production_default']}`",
        "",
    ))


def required_file_lines(output: JsonObject) -> list[str]:
    return [
        f"- `{text_value(row.get('test_id'), 'required_file.test_id')}` -> "
        f"`{text_value(row.get('required_file_name'), 'required_file.required_file_name')}`"
        for row in rows(output, "required_files")
    ]


def command_lines(output: JsonObject) -> list[str]:
    return [
        f"{int_value(row.get('step_no'), 'command.step_no')}. "
        f"`{text_value(row.get('command'), 'command.command')}` - "
        f"{text_value(row.get('purpose'), 'command.purpose')}"
        for row in rows(output, "intake_commands")
    ]


def rows(output: JsonObject, key: str) -> tuple[JsonObject, ...]:
    match output.get(key):
        case list() as values:
            return tuple(json_row(value, index, key) for index, value in enumerate(values, start=1))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError(f"{key} must be a list")
        case unreachable:
            assert_never(unreachable)


def json_row(value: JsonValue, index: int, key: str) -> JsonObject:
    match value:
        case dict() as row:
            return row
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError(f"{key}[{index}] must be a mapping")
        case unreachable:
            assert_never(unreachable)


def text_value(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def int_value(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise ExtendedGateError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)
