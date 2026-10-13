from __future__ import annotations

from dataclasses import dataclass
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    assert_common_safety,
    require_bool_value,
    require_int_value,
    require_text_value,
)

EXPECTED_TARGET_IDS: Final[tuple[str, ...]] = (
    "t_training_pack_gongsu2_non_frequent_r1",
    "t_training_pack_gongsu2_non_frequent_r2",
    "t_training_pack_mijeok1_non_frequent_r1",
    "t_training_pack_mijeok1_non_frequent_r2",
)


@dataclass(frozen=True, slots=True)
class EvidenceTarget:
    test_id: str
    required_file_name: str
    status: str


@dataclass(frozen=True, slots=True)
class PrearrivalInputs:
    checklist: JsonObject
    dropbox: JsonObject
    intake: JsonObject
    next_action: JsonObject
    evidence_file_names: tuple[str, ...]


def prearrival_contract(inputs: PrearrivalInputs) -> JsonObject:
    require_inputs(inputs)
    checklist_targets = targets_from_entries(inputs.checklist, "entries", "action_status")
    next_action_targets = targets_from_entries(inputs.next_action, "required_files", "status")
    required_file_names = expected_file_names()
    require_target_sequence(checklist_targets, "checklist")
    require_target_sequence(next_action_targets, "next_action")
    require_file_names(text_tuple(inputs.dropbox.get("required_file_names"), "dropbox.required_file_names"), "dropbox")
    require_file_names(
        text_tuple(inputs.intake.get("missing_required_file_names"), "intake.missing_required_file_names"),
        "intake",
    )
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_EVIDENCE_PREARRIVAL_CONTRACT_VERIFIED",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "next_safe_action": "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "target_count": len(EXPECTED_TARGET_IDS),
        "required_file_count": len(required_file_names),
        "checklist_required_file_count": len(checklist_targets),
        "dropbox_required_file_count": int_value(inputs.dropbox, "required_file_count"),
        "dropbox_present_file_count": int_value(inputs.dropbox, "present_file_count"),
        "dropbox_missing_file_count": int_value(inputs.dropbox, "missing_file_count"),
        "intake_evidence_file_count": int_value(inputs.intake, "evidence_file_count"),
        "intake_accepted_file_count": int_value(inputs.intake, "accepted_file_count"),
        "intake_rejected_file_count": int_value(inputs.intake, "rejected_file_count"),
        "operator_present_file_count": int_value(inputs.next_action, "present_file_count"),
        "operator_missing_file_count": int_value(inputs.next_action, "missing_file_count"),
        "actual_evidence_file_count": len(inputs.evidence_file_names),
        "prearrival_contract_verified": True,
        "current_evidence_payload_ready": False,
        "ready_after_required_files": True,
        "required_review_item_count_per_payload": 20,
        "required_question_sequence": "1-20",
        "required_targets": [target_fields(target) for target in checklist_targets],
        "required_file_names": list(required_file_names),
        "dropbox_state": "empty_or_not_created",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_inputs(inputs: PrearrivalInputs) -> None:
    require_text_value(
        inputs.checklist.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_USER_APPROVAL_REQUIRED",
        "checklist.status",
    )
    require_text_value(inputs.dropbox.get("status"), "TRAINING_PACK_EVIDENCE_DROPBOX_USER_APPROVAL_REQUIRED", "dropbox.status")
    require_text_value(
        inputs.intake.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_USER_APPROVAL_REQUIRED",
        "intake.status",
    )
    require_text_value(inputs.next_action.get("status"), "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED", "next_action.status")
    for label, payload in (
        ("checklist", inputs.checklist),
        ("dropbox", inputs.dropbox),
        ("intake", inputs.intake),
        ("next_action", inputs.next_action),
    ):
        assert_common_safety(label, payload)
        require_text_value(payload.get("production_default"), "NO_GO", f"{label}.production_default")
    require_current_empty_counts(inputs)
    require_text_value(
        inputs.next_action.get("operator_next_action"),
        "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "next_action.operator_next_action",
    )
    require_text_value(
        inputs.next_action.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "next_action.current_blocker",
    )
    require_bool_value(inputs.next_action.get("ready_now"), False, "next_action.ready_now")
    require_bool_value(inputs.next_action.get("ready_after_required_files"), True, "next_action.ready_after_required_files")
    require_empty_actual_evidence(inputs.evidence_file_names)


def require_current_empty_counts(inputs: PrearrivalInputs) -> None:
    for payload, pairs in (
        (
            inputs.checklist,
            (("required_file_count", 4),),
        ),
        (
            inputs.dropbox,
            (("required_file_count", 4), ("present_file_count", 0), ("missing_file_count", 4)),
        ),
        (
            inputs.intake,
            (("evidence_file_count", 0), ("accepted_file_count", 0), ("missing_required_file_count", 4)),
        ),
    ):
        for key, value in pairs:
            require_int_value(payload.get(key), value, key)


def targets_from_entries(payload: JsonObject, key: str, status_key: str) -> tuple[EvidenceTarget, ...]:
    match payload.get(key):
        case list() as rows:
            return tuple(target_from_row(row, index, key, status_key) for index, row in enumerate(rows, start=1))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError(f"{key} must be a list")
        case unreachable:
            assert_never(unreachable)


def target_from_row(value: JsonValue, index: int, key: str, status_key: str) -> EvidenceTarget:
    match value:
        case dict() as row:
            return EvidenceTarget(
                test_id=text_value(row.get("test_id"), f"{key}[{index}].test_id"),
                required_file_name=text_value(row.get("required_file_name"), f"{key}[{index}].required_file_name"),
                status=text_value(row.get(status_key), f"{key}[{index}].{status_key}"),
            )
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError(f"{key}[{index}] must be a mapping")
        case unreachable:
            assert_never(unreachable)


def require_target_sequence(targets: tuple[EvidenceTarget, ...], label: str) -> None:
    actual_ids = tuple(target.test_id for target in targets)
    if actual_ids != EXPECTED_TARGET_IDS:
        raise ExtendedGateError(f"{label}.target_ids do not match the expected training-pack sequence")
    require_file_names(tuple(target.required_file_name for target in targets), label)
    for index, target in enumerate(targets, start=1):
        require_text_value(target.status, "missing", f"{label}[{index}].status")


def expected_file_names() -> tuple[str, ...]:
    return tuple(f"{test_id}_recognized_evidence.json" for test_id in EXPECTED_TARGET_IDS)


def require_file_names(actual: tuple[str, ...], label: str) -> None:
    if actual != expected_file_names():
        raise ExtendedGateError(f"{label}.required_file_names do not match the expected evidence filenames")


def require_empty_actual_evidence(file_names: tuple[str, ...]) -> None:
    if file_names != ():
        raise ExtendedGateError("training-pack evidence dropbox must be empty before operator files arrive")


def int_value(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise ExtendedGateError(f"{key} must be an integer")
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


def text_tuple(value: JsonValue, label: str) -> tuple[str, ...]:
    match value:
        case list() as rows:
            return tuple(text_value(row, f"{label}[{index}]") for index, row in enumerate(rows, start=1))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError(f"{label} must be a list")
        case unreachable:
            assert_never(unreachable)


def target_fields(target: EvidenceTarget) -> JsonObject:
    return {
        "test_id": target.test_id,
        "required_file_name": target.required_file_name,
        "status": target.status,
        "required_review_item_count": 20,
        "required_question_sequence": "1-20",
    }


def require_prearrival_contract(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_EVIDENCE_PREARRIVAL_CONTRACT_VERIFIED", "status")
    require_text_value(output.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "current_blocker")
    require_text_value(
        output.get("next_safe_action"),
        "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "next_safe_action",
    )
    for key, value in integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("prearrival_contract_verified"), True, "prearrival_contract_verified")
    require_bool_value(output.get("current_evidence_payload_ready"), False, "current_evidence_payload_ready")
    require_bool_value(output.get("ready_after_required_files"), True, "ready_after_required_files")
    require_text_value(output.get("production_default"), "NO_GO", "production_default")


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4), ("required_file_count", 4), ("checklist_required_file_count", 4),
        ("dropbox_required_file_count", 4), ("dropbox_present_file_count", 0), ("dropbox_missing_file_count", 4),
        ("intake_evidence_file_count", 0), ("intake_accepted_file_count", 0), ("intake_rejected_file_count", 0),
        ("operator_present_file_count", 0), ("operator_missing_file_count", 4), ("actual_evidence_file_count", 0),
        ("required_review_item_count_per_payload", 20), ("provider_call_count", 0), ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0), ("ts_submit_click_count", 0), ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )
