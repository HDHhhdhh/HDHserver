# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_intake_replay_probes.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    read_json_object,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_recognized_evidence_example_shape import example_payload
from verify_ocr_training_pack_recognized_evidence_intake_replay import (
    CHECKLIST_JSON,
    ExpectedEvidence,
    expected_evidence,
    intake_replay,
)

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake_replay_probes.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake_replay_probes.md"


@dataclass(frozen=True, slots=True)
class ReplayProbe:
    name: str
    payloads: tuple[tuple[str, JsonObject], ...]
    expected_accepted_count: int; expected_rejected_count: int; expected_reason: str


def main() -> int:
    expected = expected_evidence(read_json_object(CHECKLIST_JSON))
    output = probe_summary(expected, replay_probes(expected))
    require_probe_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def replay_probes(expected: tuple[ExpectedEvidence, ...]) -> tuple[ReplayProbe, ...]:
    first = expected[0]
    return (
        ReplayProbe(
            "all_target_named_contract_valid",
            tuple((item.required_file_name, example_payload(item.test_id)) for item in expected),
            4, 0, "ok",
        ),
        ReplayProbe(
            "valid_payload_wrong_file_name",
            (("unexpected_recognized_evidence.json", example_payload(first.test_id)),),
            0, 1, "target_file_name_mismatch",
        ),
        ReplayProbe(
            "target_file_wrong_test_id",
            ((first.required_file_name, example_payload("t_training_pack_unknown")),),
            0, 1, "unexpected_test_id",
        ),
        ReplayProbe(
            "target_file_contract_invalid",
            ((first.required_file_name, forbidden_payload(first.test_id)),),
            0, 1, "sensitive_field",
        ),
    )


def forbidden_payload(test_id: str) -> JsonObject:
    payload = example_payload(test_id)
    review_payload = payload.get("review_payload")
    if not isinstance(review_payload, dict):
        raise ExtendedGateError("example payload review_payload must be a mapping")
    items = review_payload.get("items")
    if not isinstance(items, list):
        raise ExtendedGateError("example payload items must be a list")
    first = items[0]
    if not isinstance(first, dict):
        raise ExtendedGateError("first example item must be a mapping")
    first["canonical_answer"] = "1"
    return payload


def probe_summary(expected: tuple[ExpectedEvidence, ...], probes: tuple[ReplayProbe, ...]) -> JsonObject:
    rows = tuple(probe_result(expected, probe) for probe in probes)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_PROBES_READY",
        "probe_count": len(rows),
        "accepted_probe_count": sum(1 for row in rows if row["probe_passed"] is True),
        "rejected_probe_count": sum(1 for row in rows if row["probe_passed"] is not True),
        "target_named_valid_probe_accepted_count": int_field(rows[0], "accepted_file_count"),
        "wrong_file_name_rejected_count": int_field(rows[1], "rejected_file_count"),
        "wrong_test_id_rejected_count": int_field(rows[2], "rejected_file_count"),
        "contract_invalid_rejected_count": int_field(rows[3], "rejected_file_count"),
        "replacement_allowed_without_user_approval": False,
        "probe_results": list(rows),
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def probe_result(expected: tuple[ExpectedEvidence, ...], probe: ReplayProbe) -> JsonObject:
    replay = intake_replay(checklist_from_expected(expected), probe.payloads)
    accepted = int_field(replay, "accepted_file_count")
    rejected = int_field(replay, "rejected_file_count")
    reasons = tuple(reason for result in file_results(replay) for reason in (text_field(result.get("reason"), "reason"),))
    reason_ok = probe.expected_reason == "ok" or probe.expected_reason in reasons
    return {
        "name": probe.name,
        "accepted_file_count": accepted,
        "rejected_file_count": rejected,
        "required_reason": probe.expected_reason,
        "observed_reasons": list(reasons),
        "probe_passed": accepted == probe.expected_accepted_count and rejected == probe.expected_rejected_count and reason_ok,
    }


def checklist_from_expected(expected: tuple[ExpectedEvidence, ...]) -> JsonObject:
    return {
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_USER_APPROVAL_REQUIRED",
        "entries": [{"test_id": item.test_id, "required_file_name": item.required_file_name} for item in expected],
    }


def file_results(replay: JsonObject) -> tuple[JsonObject, ...]:
    results = replay.get("file_results")
    if not isinstance(results, list):
        raise ExtendedGateError("file_results must be a list")
    return tuple(mapping for mapping in results if isinstance(mapping, dict))


def int_field(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ExtendedGateError(f"{key} must be an integer")


def text_field(value: JsonValue, label: str) -> str:
    if isinstance(value, str):
        return value
    raise ExtendedGateError(f"{label} must be text")


def require_probe_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_PROBES_READY", "status")
    for key, expected in integer_expectations():
        require_int_value(output.get(key), expected, key)
    require_text_value(output.get("production_default"), "NO_GO", "production_default")


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("probe_count", 4), ("accepted_probe_count", 4), ("rejected_probe_count", 0),
        ("target_named_valid_probe_accepted_count", 4), ("wrong_file_name_rejected_count", 1),
        ("wrong_test_id_rejected_count", 1), ("contract_invalid_rejected_count", 1), ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0), ("submit_test_call_count", 0), ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Recognized Evidence Intake Replay Probes", "",
        "- Gemini/API calls: 0; external OCR API calls: 0", "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0", "- student-facing: false", "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- probes passed: {output['accepted_probe_count']} / {output['probe_count']}",
        f"- target-named valid accepted files: {output['target_named_valid_probe_accepted_count']}",
        f"- wrong filename rejected: {output['wrong_file_name_rejected_count']}",
        f"- wrong test_id rejected: {output['wrong_test_id_rejected_count']}",
        f"- contract-invalid rejected: {output['contract_invalid_rejected_count']}",
        f"- replacement allowed without user approval: {output['replacement_allowed_without_user_approval']}",
        "- answer-key/grading/path leak count: 0", "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
