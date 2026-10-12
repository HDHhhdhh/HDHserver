# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_accuracy_claim_guard.py

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
SKELETON_JSON: Final[Path] = LAB / "ocr_training_pack_replay_cache_skeleton.json"
UI_BRIDGE_JSON: Final[Path] = LAB / "ocr_training_pack_ui_replay_bridge.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_accuracy_claim_guard.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_accuracy_claim_guard.md"
SENSITIVE_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
)


@dataclass(frozen=True, slots=True)
class TrainingPackAccuracyClaimGuardError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    skeleton = read_json_object(SKELETON_JSON)
    ui_bridge = read_json_object(UI_BRIDGE_JSON)
    output = summary(skeleton, ui_bridge)
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def read_json_object(path: Path) -> JsonObject:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise TrainingPackAccuracyClaimGuardError(f"{path.name} must be a JSON object")
    return raw


def summary(skeleton: JsonObject, ui_bridge: JsonObject) -> JsonObject:
    require_text_value(
        skeleton.get("status"),
        "TRAINING_PACK_PROVIDER_FREE_REPLAY_SKELETON_READY",
        "skeleton.status",
    )
    require_text_value(
        ui_bridge.get("status"),
        "TRAINING_PACK_UI_REPLAY_BRIDGE_SKELETON_BLOCKS_FILL",
        "ui_bridge.status",
    )
    require_bool_value(skeleton.get("ready_for_ocr_accuracy_claim"), False, "skeleton.ready_for_ocr_accuracy_claim")
    require_bool_value(ui_bridge.get("ready_for_ocr_accuracy_claim"), False, "ui_bridge.ready_for_ocr_accuracy_claim")
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_SKELETON_EXCLUDED_FROM_ACCURACY_CLAIMS",
        "skeleton_payload_count": int_field(skeleton, "cache_replay_payload_count"),
        "skeleton_review_required_count": int_field(skeleton, "review_required_count"),
        "skeleton_safe_auto_grade_count": int_field(skeleton, "safe_auto_grade_count"),
        "skeleton_recognized_value_count": int_field(skeleton, "recognized_value_count"),
        "ui_replay_payload_count": int_field(ui_bridge, "payload_count"),
        "ui_bridge_blocked_final_count": int_field(ui_bridge, "blocked_final_bridge_count"),
        "ui_bridge_fill_allowed_count": int_field(ui_bridge, "answers_text_fill_allowed_count"),
        "accuracy_claim_allowed": False,
        "ready_for_provider_free_manual_confirmation_replay": True,
        "ready_for_ocr_accuracy_claim": False,
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
        raise TrainingPackAccuracyClaimGuardError(f"{key} must be an integer")
    return value


def require_summary(output: JsonObject) -> None:
    require_int_value(output.get("skeleton_payload_count"), 4, "skeleton_payload_count")
    require_int_value(output.get("skeleton_review_required_count"), 80, "skeleton_review_required_count")
    require_int_value(output.get("skeleton_safe_auto_grade_count"), 0, "skeleton_safe_auto_grade_count")
    require_int_value(output.get("skeleton_recognized_value_count"), 0, "skeleton_recognized_value_count")
    require_int_value(output.get("ui_replay_payload_count"), 4, "ui_replay_payload_count")
    require_int_value(output.get("ui_bridge_blocked_final_count"), 4, "ui_bridge_blocked_final_count")
    require_int_value(output.get("ui_bridge_fill_allowed_count"), 0, "ui_bridge_fill_allowed_count")
    require_bool_value(output.get("accuracy_claim_allowed"), False, "accuracy_claim_allowed")
    require_bool_value(output.get("ready_for_ocr_accuracy_claim"), False, "ready_for_ocr_accuracy_claim")
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
        "# OCR Training Pack Accuracy Claim Guard",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- skeleton payloads: {output['skeleton_payload_count']}",
        f"- skeleton review-required items: {output['skeleton_review_required_count']}",
        f"- skeleton recognized values: {output['skeleton_recognized_value_count']}",
        f"- UI bridge fill allowed: {output['ui_bridge_fill_allowed_count']}",
        f"- final bridge blocked payloads: {output['ui_bridge_blocked_final_count']}",
        "- accuracy claim allowed: false",
        "- ready for OCR accuracy claim: false",
        "- sensitive/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
