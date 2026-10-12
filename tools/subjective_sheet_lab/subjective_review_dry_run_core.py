from __future__ import annotations

from final_review_payload_bridge import (
    BridgeError,
    convert_json_payload,
    find_forbidden_answer_key_paths,
)
from subjective_review_dry_run_payloads import (
    build_review_payload,
    clone_json_object,
    item_objects,
    require_array,
    require_int,
    require_object,
    require_string,
)
from subjective_review_dry_run_types import (
    BlockingCheck,
    DryRunError,
    DryRunOutputs,
    DryRunResult,
    JsonObject,
    RetakeApplyContext,
    RetakeDecision,
    ReviewDecision,
    StatusBlocker,
)


def run_dry_flow(fixture: JsonObject) -> DryRunResult:
    review_payload = build_review_payload(fixture)
    outputs = apply_student_decisions(review_payload, fixture)
    checks = (
        assert_blocked("review_required_blocks_conversion", outputs.review_payload, "review_required"),
        assert_blocked("retake_required_blocks_conversion", status_blocker_payload(outputs.final_payload, StatusBlocker(6, "retake_required", None)), "retake_required"),
        assert_blocked("retake_uploaded_blocks_conversion", status_blocker_payload(outputs.final_payload, StatusBlocker(6, "retake_uploaded", "retake_uploaded")), "retake_uploaded"),
        assert_blocked("data_check_required_blocks_conversion", data_check_payload(outputs.final_payload, fixture), "data_check_required"),
    )
    assert_all_passed(checks)
    golden = require_string(fixture.get("golden_answers_text"), "golden_answers_text")
    if outputs.answers_text != golden:
        raise DryRunError("answersText order does not match golden 20-question order")
    leaks = tuple(find_forbidden_answer_key_paths(outputs.review_payload) + find_forbidden_answer_key_paths(outputs.final_payload))
    if leaks:
        raise DryRunError(f"student-facing JSON leaked answer-key fields: {', '.join(leaks)}")
    return DryRunResult(outputs, checks, leaks)


def apply_student_decisions(review_payload: JsonObject, fixture: JsonObject) -> DryRunOutputs:
    decisions = read_decisions(fixture)
    retakes = read_retake_decisions(fixture)
    retake_uploaded = clone_json_object(review_payload)
    final_payload = clone_json_object(review_payload)
    retake_uploaded_items = item_objects(retake_uploaded)
    for item in item_objects(final_payload):
        question_no = require_int(item.get("question_no"), "item.question_no")
        status = require_string(item.get("status"), "item.status")
        if status == "safe_auto_grade":
            continue
        if status == "retake_required":
            apply_retake(RetakeApplyContext(question_no, item, retake_uploaded_items, retakes))
            continue
        apply_decision(question_no, item, decisions)
    return DryRunOutputs(review_payload, retake_uploaded, final_payload, convert_json_payload(final_payload).answers_text)


def read_decisions(payload: JsonObject) -> dict[int, ReviewDecision]:
    output: dict[int, ReviewDecision] = {}
    for value in require_array(payload.get("student_decisions"), "student_decisions"):
        item = require_object(value, "student_decision")
        question_no = require_int(item.get("question_no"), "student_decision.question_no")
        output[question_no] = ReviewDecision(
            question_no,
            require_string(item.get("action"), "student_decision.action"),
            require_string(item.get("final_answer"), "student_decision.final_answer"),
        )
    return output


def read_retake_decisions(payload: JsonObject) -> dict[int, RetakeDecision]:
    output: dict[int, RetakeDecision] = {}
    for value in require_array(payload.get("retake_decisions"), "retake_decisions"):
        item = require_object(value, "retake_decision")
        question_no = require_int(item.get("question_no"), "retake_decision.question_no")
        output[question_no] = RetakeDecision(
            question_no,
            require_string(item.get("uploaded_status"), "retake_decision.uploaded_status"),
            require_object(item.get("rerecognized"), "retake_decision.rerecognized"),
            require_string(item.get("action"), "retake_decision.action"),
            require_string(item.get("final_answer"), "retake_decision.final_answer"),
        )
    return output


def apply_decision(question_no: int, item: JsonObject, decisions: dict[int, ReviewDecision]) -> None:
    decision = decisions.get(question_no)
    if decision is None:
        raise DryRunError(f"question {question_no} needs a simulated student decision")
    match decision.action:
        case "candidate_selected":
            item["status"] = "student_selected_candidate"
            item["source"] = "student_selected_candidate"
        case "direct_input":
            item["status"] = "student_direct_input"
            item["source"] = "student_direct_input"
        case _:
            raise DryRunError(f"question {question_no} has unsupported action {decision.action}")
    item["final_answer"] = decision.final_answer


def apply_retake(context: RetakeApplyContext) -> None:
    decision = context.retakes.get(context.question_no)
    if decision is None:
        raise DryRunError(f"question {context.question_no} needs a retake decision")
    for uploaded_item in context.uploaded_items:
        if uploaded_item.get("question_no") == context.question_no:
            uploaded_item["status"] = decision.uploaded_status
            uploaded_item["source"] = "retake_uploaded"
            uploaded_item["retake_image_attached"] = True
            uploaded_item["final_answer"] = None
    context.item.update(decision.rerecognized)
    match decision.action:
        case "candidate_selected_after_retake":
            context.item["status"] = "student_selected_candidate_after_retake"
            context.item["source"] = "student_selected_candidate_after_retake"
        case "direct_input_after_retake":
            context.item["status"] = "student_direct_input_after_retake"
            context.item["source"] = "student_direct_input_after_retake"
        case "safe_auto_grade_after_retake":
            context.item["status"] = "safe_auto_grade_after_retake"
            context.item["source"] = "safe_auto_grade_after_retake"
        case _:
            raise DryRunError(f"question {context.question_no} has unsupported retake action {decision.action}")
    context.item["final_answer"] = decision.final_answer
    context.item["retake_image_attached"] = True


def assert_blocked(name: str, payload: JsonObject, token: str) -> BlockingCheck:
    try:
        convert_json_payload(payload)
    except BridgeError as exc:
        detail = str(exc)
        return BlockingCheck(name, token in detail, detail)
    return BlockingCheck(name, False, "conversion unexpectedly succeeded")


def data_check_payload(final_payload: JsonObject, fixture: JsonObject) -> JsonObject:
    payload = clone_json_object(final_payload)
    blocker = require_object(fixture.get("data_check_blocker"), "data_check_blocker")
    question_no = require_int(blocker.get("question_no"), "data_check_blocker.question_no")
    for item in item_objects(payload):
        if item.get("question_no") == question_no:
            item.update(blocker)
            item["final_answer"] = None
            item["source"] = None
    return payload


def status_blocker_payload(final_payload: JsonObject, blocker: StatusBlocker) -> JsonObject:
    payload = clone_json_object(final_payload)
    for item in item_objects(payload):
        if item.get("question_no") == blocker.question_no:
            item["status"] = blocker.status
            item["source"] = blocker.source
            item["final_answer"] = None
    return payload


def assert_all_passed(checks: tuple[BlockingCheck, ...]) -> None:
    failed = tuple(check.name for check in checks if not check.passed)
    if failed:
        raise DryRunError(f"blocking checks failed: {', '.join(failed)}")
