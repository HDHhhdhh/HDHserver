# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_acceptance_dry_run.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    read_json_object,
    require_text_value,
)
from ocr_training_pack_recognized_evidence_acceptance_dry_run_output import markdown
from ocr_training_pack_recognized_evidence_acceptance_dry_run_policy import require_acceptance_dry_run
from ocr_training_pack_recognized_evidence_contract_core import (
    ContractResult,
    validate_payload,
)
from ocr_training_pack_recognized_evidence_target_diff_core import (
    duplicate_count,
    target_test_ids,
    unique_values,
)

LAB: Final[Path] = Path(__file__).resolve().parent
SOURCE_JSON: Final[Path] = LAB / "ocr_training_pack_source_inventory.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_acceptance_dry_run.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_acceptance_dry_run.md"
EXPECTED_TARGET_COUNT: Final[int] = 4
EXPECTED_REVIEW_ITEM_COUNT: Final[int] = 20


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    file_name: str
    test_id: str
    payload: JsonObject


@dataclass(frozen=True, slots=True)
class CandidateSetResult:
    name: str
    ready: bool
    candidate_count: int
    accepted_payload_count: int
    filename_match_count: int
    covered_target_count: int
    missing_target_count: int
    duplicate_target_count: int
    unexpected_target_count: int
    rejected_payload_count: int


def main() -> int:
    source = read_json_object(SOURCE_JSON)
    output = acceptance_dry_run(source)
    require_acceptance_dry_run(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def acceptance_dry_run(source: JsonObject) -> JsonObject:
    require_text_value(
        source.get("status"),
        "TRAINING_PACK_ROUTE_UPLOAD_SOURCES_READY_CACHE_REPLAY_MISSING",
        "source.status",
    )
    targets = target_test_ids(source)
    if len(targets) != EXPECTED_TARGET_COUNT:
        raise ExtendedGateError("training pack acceptance dry-run requires 4 targets")
    complete = candidate_set_result("complete_valid_candidate_set", targets, complete_candidates(targets))
    probes = invalid_probe_results(targets)
    failed_probe_count = sum(1 for result in probes if result.ready)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_ACCEPTANCE_DRY_RUN_VERIFIED",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "target_count": len(targets),
        "required_file_count": len(targets),
        "required_review_item_count_per_payload": EXPECTED_REVIEW_ITEM_COUNT,
        "complete_candidate_count": complete.candidate_count,
        "complete_candidate_accepted_payload_count": complete.accepted_payload_count,
        "complete_candidate_filename_match_count": complete.filename_match_count,
        "complete_candidate_covered_target_count": complete.covered_target_count,
        "complete_candidate_missing_target_count": complete.missing_target_count,
        "complete_candidate_duplicate_target_count": complete.duplicate_target_count,
        "complete_candidate_unexpected_target_count": complete.unexpected_target_count,
        "complete_candidate_ready": complete.ready,
        "invalid_probe_count": len(probes),
        "invalid_probe_blocked_count": sum(1 for result in probes if not result.ready),
        "failed_probe_count": failed_probe_count,
        "expected_files": expected_files(targets),
        "invalid_probe_names": [result.name for result in probes],
        "next_status": "USER_APPROVAL_REQUIRED",
        "next_action": "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def complete_candidates(targets: tuple[str, ...]) -> tuple[EvidenceCandidate, ...]:
    return tuple(valid_candidate(test_id) for test_id in targets)


def invalid_probe_results(targets: tuple[str, ...]) -> tuple[CandidateSetResult, ...]:
    return (
        candidate_set_result("missing_target_candidate_set", targets, complete_candidates(targets[:3])),
        candidate_set_result("duplicate_target_candidate_set", targets, duplicate_candidates(targets)),
        candidate_set_result("unexpected_target_candidate_set", targets, unexpected_candidates(targets)),
        candidate_set_result("filename_mismatch_candidate_set", targets, filename_mismatch_candidates(targets)),
        candidate_set_result("safe_auto_grade_payload_candidate_set", targets, safe_auto_grade_candidates(targets)),
        candidate_set_result("filesystem_path_payload_candidate_set", targets, filesystem_path_candidates(targets)),
    )


def duplicate_candidates(targets: tuple[str, ...]) -> tuple[EvidenceCandidate, ...]:
    return (*complete_candidates(targets[:3]), valid_candidate(targets[0]))


def unexpected_candidates(targets: tuple[str, ...]) -> tuple[EvidenceCandidate, ...]:
    return (*complete_candidates(targets[:3]), valid_candidate("t_training_pack_unexpected_r1"))


def filename_mismatch_candidates(targets: tuple[str, ...]) -> tuple[EvidenceCandidate, ...]:
    first, *rest = complete_candidates(targets)
    mismatched = EvidenceCandidate(file_name="wrong_name_recognized_evidence.json", test_id=first.test_id, payload=first.payload)
    return (mismatched, *rest)


def safe_auto_grade_candidates(targets: tuple[str, ...]) -> tuple[EvidenceCandidate, ...]:
    first, *rest = complete_candidates(targets)
    return (candidate_with_item(first.test_id, {"status": "safe_auto_grade"}), *rest)


def filesystem_path_candidates(targets: tuple[str, ...]) -> tuple[EvidenceCandidate, ...]:
    first, *rest = complete_candidates(targets)
    return (candidate_with_item(first.test_id, {"note": "C:/server/internal.png"}), *rest)


def valid_candidate(test_id: str) -> EvidenceCandidate:
    return EvidenceCandidate(
        file_name=required_file_name(test_id),
        test_id=test_id,
        payload=payload_for_test_id(test_id, {}),
    )


def candidate_with_item(test_id: str, item_patch: JsonObject) -> EvidenceCandidate:
    return EvidenceCandidate(
        file_name=required_file_name(test_id),
        test_id=test_id,
        payload=payload_for_test_id(test_id, item_patch),
    )


def payload_for_test_id(test_id: str, first_item_patch: JsonObject) -> JsonObject:
    items = [
        {
            "question_no": question_no,
            "status": "review_required",
            "recognized": "1",
        }
        for question_no in range(1, EXPECTED_REVIEW_ITEM_COUNT + 1)
    ]
    items[0].update(first_item_patch)
    return {
        "review_payload": {
            "test_id": test_id,
            "round": "1",
            "problem_count": EXPECTED_REVIEW_ITEM_COUNT,
            "items": items,
        },
    }


def candidate_set_result(
    name: str,
    targets: tuple[str, ...],
    candidates: tuple[EvidenceCandidate, ...],
) -> CandidateSetResult:
    payload_results = tuple(validate_payload(candidate.payload) for candidate in candidates)
    test_ids = tuple(candidate.test_id for candidate in candidates)
    filename_matches = sum(1 for candidate in candidates if candidate.file_name == required_file_name(candidate.test_id))
    accepted = accepted_payload_count(payload_results)
    missing = sum(1 for target in targets if target not in test_ids)
    duplicates = duplicate_count(test_ids)
    unexpected = sum(1 for test_id in unique_values(test_ids) if test_id not in targets)
    ready = (
        len(candidates) == len(targets)
        and accepted == len(targets)
        and filename_matches == len(targets)
        and missing == 0
        and duplicates == 0
        and unexpected == 0
    )
    return CandidateSetResult(
        name=name,
        ready=ready,
        candidate_count=len(candidates),
        accepted_payload_count=accepted,
        filename_match_count=filename_matches,
        covered_target_count=sum(1 for target in targets if target in test_ids),
        missing_target_count=missing,
        duplicate_target_count=duplicates,
        unexpected_target_count=unexpected,
        rejected_payload_count=len(candidates) - accepted,
    )


def accepted_payload_count(results: tuple[ContractResult, ...]) -> int:
    return sum(1 for result in results if result.accepted)


def required_file_name(test_id: str) -> str:
    return f"{test_id}_recognized_evidence.json"


def expected_files(targets: tuple[str, ...]) -> list[JsonObject]:
    return [{"test_id": target, "required_file_name": required_file_name(target)} for target in targets]


if __name__ == "__main__":
    raise SystemExit(main())
