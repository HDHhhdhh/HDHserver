from __future__ import annotations

from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import JsonObject, JsonValue

REQUIRED_APPROVAL_STATUS: Final[str] = "USER_APPROVAL_REQUIRED"
REQUIRED_APPROVAL_REPORTS: Final[tuple[str, ...]] = (
    "ocr_person03_second_pass_live_handoff.json",
    "ocr_person_second_pass_request_manifests.json",
    "ocr_second_pass_batch_request_manifest.json",
    "ocr_visible_digit_second_pass_batch.json",
)
REQUIRED_BLOCKER_ROWS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "ocr_operator_next_action_summary.json",
        "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED",
        "training_pack_recognized_evidence_files_missing",
    ),
    (
        "ocr_qa_start_here_verification.json",
        "OCR_QA_START_HERE_READY_WITH_USER_ACTION_REQUIRED",
        "training_pack_recognized_evidence_files_missing",
    ),
    (
        "ocr_training_pack_operator_handoff.json",
        "TRAINING_PACK_OPERATOR_HANDOFF_USER_APPROVAL_REQUIRED",
        "missing_training_pack_recognized_evidence_files",
    ),
    (
        "ocr_training_pack_post_arrival_acceptance_summary.json",
        "TRAINING_PACK_POST_ARRIVAL_ACCEPTANCE_SUMMARY_USER_ACTION_REQUIRED",
        "training_pack_recognized_evidence_files_missing",
    ),
    (
        "ocr_training_pack_post_arrival_command_bundle.json",
        "TRAINING_PACK_POST_ARRIVAL_COMMAND_BUNDLE_USER_ACTION_REQUIRED",
        "training_pack_recognized_evidence_files_missing",
    ),
    (
        "ocr_training_pack_recognized_evidence_filename_diagnostics.json",
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_FILENAME_DIAGNOSTICS_USER_ACTION_REQUIRED",
        "training_pack_recognized_evidence_files_missing",
    ),
)


def required_approval_rows_present(rows: tuple[JsonObject, ...]) -> bool:
    report_pairs = approval_report_pairs(rows)
    return all((file_name, REQUIRED_APPROVAL_STATUS) in report_pairs for file_name in REQUIRED_APPROVAL_REPORTS)


def required_blocker_rows_present(rows: tuple[JsonObject, ...]) -> bool:
    return all(row in blocker_report_triples(rows) for row in REQUIRED_BLOCKER_ROWS)


def approval_report_pairs(rows: tuple[JsonObject, ...]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for row in rows:
        file_name = optional_text(row.get("file_name"))
        status = optional_text(row.get("status"))
        if file_name != "" and status != "":
            pairs.add((file_name, status))
    return pairs


def blocker_report_triples(rows: tuple[JsonObject, ...]) -> set[tuple[str, str, str]]:
    triples: set[tuple[str, str, str]] = set()
    for row in rows:
        file_name = optional_text(row.get("file_name"))
        status = optional_text(row.get("status"))
        blocker = optional_text(row.get("current_blocker"))
        if file_name != "" and status != "":
            triples.add((file_name, status, blocker))
    return triples


def required_approval_rows() -> tuple[JsonObject, ...]:
    return tuple(
        {
            "file_name": file_name,
            "ok": True,
            "status": REQUIRED_APPROVAL_STATUS,
            "current_blocker": "",
        }
        for file_name in REQUIRED_APPROVAL_REPORTS
    )


def required_blocker_rows() -> tuple[JsonObject, ...]:
    return tuple(
        {
            "file_name": file_name,
            "ok": True,
            "status": status,
            "current_blocker": blocker,
        }
        for file_name, status, blocker in REQUIRED_BLOCKER_ROWS
    )


def optional_text(value: JsonValue) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            return ""
        case unreachable:
            assert_never(unreachable)
