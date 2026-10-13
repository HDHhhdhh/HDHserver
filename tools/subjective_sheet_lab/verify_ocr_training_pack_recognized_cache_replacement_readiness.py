# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_cache_replacement_readiness.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
)

LAB: Final[Path] = Path(__file__).resolve().parent
SOURCE_JSON: Final[Path] = LAB / "ocr_training_pack_source_inventory.json"
SKELETON_JSON: Final[Path] = LAB / "ocr_training_pack_replay_cache_skeleton.json"
CLAIM_GUARD_JSON: Final[Path] = LAB / "ocr_training_pack_accuracy_claim_guard.json"
INTAKE_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_cache_replacement_readiness.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_cache_replacement_readiness.md"
SENSITIVE_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
)


@dataclass(frozen=True, slots=True)
class TrainingPackReplacementReadinessError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ReadinessInputs:
    source: JsonObject
    skeleton: JsonObject
    claim_guard: JsonObject
    intake: JsonObject


def main() -> int:
    output = summary(
        ReadinessInputs(
            source=read_json_object(SOURCE_JSON),
            skeleton=read_json_object(SKELETON_JSON),
            claim_guard=read_json_object(CLAIM_GUARD_JSON),
            intake=read_json_object(INTAKE_JSON),
        ),
    )
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def read_json_object(path: Path) -> JsonObject:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise TrainingPackReplacementReadinessError(f"{path.name} must be a JSON object")
    return raw


def summary(inputs: ReadinessInputs) -> JsonObject:
    source = inputs.source
    skeleton = inputs.skeleton
    claim_guard = inputs.claim_guard
    intake = inputs.intake
    require_text_value(
        source.get("status"),
        "TRAINING_PACK_ROUTE_UPLOAD_SOURCES_READY_CACHE_REPLAY_MISSING",
        "source.status",
    )
    require_text_value(
        skeleton.get("status"),
        "TRAINING_PACK_PROVIDER_FREE_REPLAY_SKELETON_READY",
        "skeleton.status",
    )
    require_text_value(
        claim_guard.get("status"),
        "TRAINING_PACK_SKELETON_EXCLUDED_FROM_ACCURACY_CLAIMS",
        "claim_guard.status",
    )
    require_bool_value(claim_guard.get("accuracy_claim_allowed"), False, "claim_guard.accuracy_claim_allowed")
    require_text_value(
        intake.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_USER_APPROVAL_REQUIRED",
        "intake.status",
    )
    require_int_value(intake.get("target_count"), 4, "intake.target_count")
    require_int_value(intake.get("evidence_file_count"), 0, "intake.evidence_file_count")
    require_int_value(intake.get("complete_payload_count"), 0, "intake.complete_payload_count")
    require_int_value(
        intake.get("nonzero_recognized_payload_count"),
        0,
        "intake.nonzero_recognized_payload_count",
    )
    require_int_value(intake.get("recognized_value_count"), 0, "intake.recognized_value_count")
    require_bool_value(intake.get("replacement_input_ready"), False, "intake.replacement_input_ready")
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_CACHE_REPLACEMENT_REQUIRES_OCR_EVIDENCE",
        "source_candidate_count": int_field(source, "source_candidate_count"),
        "source_assets_ready_count": int_field(source, "source_assets_ready_count"),
        "current_cache_replay_payload_count": int_field(source, "cache_replay_payload_count"),
        "skeleton_payload_count": int_field(skeleton, "cache_replay_payload_count"),
        "skeleton_recognized_value_count": int_field(skeleton, "recognized_value_count"),
        "recognized_evidence_target_count": int_field(intake, "target_count"),
        "recognized_evidence_file_count": int_field(intake, "evidence_file_count"),
        "recognized_evidence_complete_payload_count": int_field(intake, "complete_payload_count"),
        "recognized_evidence_value_count": int_field(intake, "recognized_value_count"),
        "approved_ocr_evidence_count": int_field(intake, "nonzero_recognized_payload_count"),
        "readiness_probe_count": int_field(intake, "replacement_readiness_probe_count"),
        "readiness_ready_probe_count": int_field(intake, "replacement_readiness_probe_ready_count"),
        "readiness_blocked_probe_count": int_field(intake, "replacement_readiness_probe_blocked_count"),
        "replacement_ready": bool_field(intake, "replacement_input_ready"),
        "replacement_allowed": False,
        "next_status": "USER_APPROVAL_REQUIRED",
        "required_next_artifact": "recognized_cache_payloads_with_nonzero_recognized_values",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "sensitive_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    text = json.dumps(output, ensure_ascii=False)
    output["sensitive_field_leak_count"] = sensitive_leak_count(text)
    output["filesystem_path_leak_count"] = filesystem_path_leak_count(text)
    return output


def int_field(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TrainingPackReplacementReadinessError(f"{key} must be an integer")
    return value


def bool_field(payload: JsonObject, key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise TrainingPackReplacementReadinessError(f"{key} must be a boolean")
    return value


def require_summary(output: JsonObject) -> None:
    require_int_value(output.get("source_candidate_count"), 4, "source_candidate_count")
    require_int_value(output.get("source_assets_ready_count"), 4, "source_assets_ready_count")
    require_int_value(output.get("current_cache_replay_payload_count"), 0, "current_cache_replay_payload_count")
    require_int_value(output.get("skeleton_payload_count"), 4, "skeleton_payload_count")
    require_int_value(output.get("skeleton_recognized_value_count"), 0, "skeleton_recognized_value_count")
    require_int_value(output.get("recognized_evidence_target_count"), 4, "recognized_evidence_target_count")
    require_int_value(output.get("recognized_evidence_file_count"), 0, "recognized_evidence_file_count")
    require_int_value(
        output.get("recognized_evidence_complete_payload_count"),
        0,
        "recognized_evidence_complete_payload_count",
    )
    require_int_value(output.get("recognized_evidence_value_count"), 0, "recognized_evidence_value_count")
    require_int_value(output.get("approved_ocr_evidence_count"), 0, "approved_ocr_evidence_count")
    require_int_value(output.get("readiness_probe_count"), 3, "readiness_probe_count")
    require_int_value(output.get("readiness_ready_probe_count"), 1, "readiness_ready_probe_count")
    require_int_value(output.get("readiness_blocked_probe_count"), 2, "readiness_blocked_probe_count")
    require_bool_value(output.get("replacement_ready"), False, "replacement_ready")
    require_bool_value(output.get("replacement_allowed"), False, "replacement_allowed")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_int_value(output.get("provider_call_count"), 0, "provider_call_count")
    require_int_value(output.get("external_ocr_api_call_count"), 0, "external_ocr_api_call_count")
    require_int_value(output.get("submit_test_call_count"), 0, "submit_test_call_count")
    require_int_value(output.get("ts_submit_click_count"), 0, "ts_submit_click_count")
    require_int_value(output.get("sensitive_field_leak_count"), 0, "sensitive_field_leak_count")
    require_int_value(output.get("filesystem_path_leak_count"), 0, "filesystem_path_leak_count")


def sensitive_leak_count(text: str) -> int:
    return sum(text.count(token) for token in SENSITIVE_TOKENS)


def filesystem_path_leak_count(text: str) -> int:
    return text.count("C:\\") + text.count("C:/") + text.count("/c/")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Recognized Cache Replacement Readiness",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- source candidates: {output['source_candidate_count']}",
        f"- source assets ready: {output['source_assets_ready_count']}",
        f"- current recognized cache payloads: {output['current_cache_replay_payload_count']}",
        f"- skeleton payloads: {output['skeleton_payload_count']}",
        f"- skeleton recognized values: {output['skeleton_recognized_value_count']}",
        f"- recognized evidence targets: {output['recognized_evidence_target_count']}",
        f"- recognized evidence files: {output['recognized_evidence_file_count']}",
        f"- recognized evidence complete payloads: {output['recognized_evidence_complete_payload_count']}",
        f"- recognized evidence values: {output['recognized_evidence_value_count']}",
        f"- approved OCR evidence: {output['approved_ocr_evidence_count']}",
        f"- readiness probes: {output['readiness_ready_probe_count']} ready / "
        f"{output['readiness_blocked_probe_count']} blocked",
        f"- replacement ready: {output['replacement_ready']}",
        f"- replacement allowed: {output['replacement_allowed']}",
        f"- next status: `{output['next_status']}`",
        "- sensitive/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
