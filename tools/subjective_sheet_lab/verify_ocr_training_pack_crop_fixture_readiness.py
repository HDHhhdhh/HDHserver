# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_crop_fixture_readiness.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_accuracy_next_items_scope_checks import mijeok_training_fixture_scope
from ocr_provider_free_extended_gate_common import JsonObject, JsonValue, require_int_value

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_training_pack_crop_fixture_readiness.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_training_pack_crop_fixture_readiness.md")
TRAINING_PACK_IDS: Final[frozenset[str]] = frozenset(
    (
        "t_training_pack_mijeok1_non_frequent_r1",
        "t_training_pack_mijeok1_non_frequent_r2",
        "t_training_pack_gongsu2_non_frequent_r1",
        "t_training_pack_gongsu2_non_frequent_r2",
    )
)


@dataclass(frozen=True, slots=True)
class TrainingPackFixtureError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    scope = mijeok_training_fixture_scope()
    output = summary(scope)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def summary(scope: JsonObject) -> JsonObject:
    targets = training_pack_targets(scope)
    crop_set_count = sum(require_int(target.get("crop_set_count"), "crop_set_count") for target in targets)
    complete_crop_set_count = sum(require_int(target.get("complete_crop_set_count"), "complete_crop_set_count") for target in targets)
    postprocess_verified_count = sum(1 for target in targets if require_bool(target.get("postprocess_verified"), "postprocess_verified"))
    if postprocess_verified_count != len(TRAINING_PACK_IDS):
        raise TrainingPackFixtureError("all Training Pack targets must have provider-free postprocess verification")
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_CROP_FIXTURES_MISSING",
        "target_count": len(targets),
        "postprocess_verified_count": postprocess_verified_count,
        "crop_set_count": crop_set_count,
        "complete_crop_set_count": complete_crop_set_count,
        "manual_fixture_needed": crop_set_count == 0,
        "ready_for_provider_free_ui_replay": complete_crop_set_count > 0,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "targets": [target_payload(target) for target in targets],
    }


def training_pack_targets(scope: JsonObject) -> tuple[JsonObject, ...]:
    raw_targets = require_array(scope.get("targets"), "scope.targets")
    targets: list[JsonObject] = []
    for raw_target in raw_targets:
        target = require_object(raw_target, "scope.targets[]")
        test_id = require_string(target.get("test_id"), "target.test_id")
        if test_id in TRAINING_PACK_IDS:
            targets.append(target)
    found_ids = {require_string(target.get("test_id"), "target.test_id") for target in targets}
    if found_ids != TRAINING_PACK_IDS:
        raise TrainingPackFixtureError(f"Training Pack target set mismatch: {sorted(found_ids)}")
    return tuple(sorted(targets, key=lambda target: require_string(target.get("test_id"), "target.test_id")))


def target_payload(target: JsonObject) -> JsonObject:
    crop_set_count = require_int(target.get("crop_set_count"), "target.crop_set_count")
    complete_crop_set_count = require_int(target.get("complete_crop_set_count"), "target.complete_crop_set_count")
    return {
        "test_id": require_string(target.get("test_id"), "target.test_id"),
        "crop_set_count": crop_set_count,
        "complete_crop_set_count": complete_crop_set_count,
        "postprocess_verified": require_bool(target.get("postprocess_verified"), "target.postprocess_verified"),
        "readiness": "missing_crop_fixture" if complete_crop_set_count == 0 else "provider_free_replay_ready",
    }


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise TrainingPackFixtureError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise TrainingPackFixtureError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_string(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise TrainingPackFixtureError(f"{label} must be a string")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise TrainingPackFixtureError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_bool(value: JsonValue, label: str) -> bool:
    match value:
        case bool():
            return value
        case None | int() | float() | str() | list() | dict():
            raise TrainingPackFixtureError(f"{label} must be a boolean")
        case unreachable:
            assert_never(unreachable)


def markdown(output: JsonObject) -> str:
    require_int_value(output.get("provider_call_count"), 0, "provider_call_count")
    lines = [
        "# OCR Training Pack Crop Fixture Readiness",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- Training Pack targets: {output['target_count']}",
        f"- postprocess verified: {output['postprocess_verified_count']}",
        f"- crop sets found: {output['crop_set_count']}",
        f"- complete crop sets found: {output['complete_crop_set_count']}",
        f"- manual fixture needed: {output['manual_fixture_needed']}",
        "- answer-key/grading/path leak count: 0",
        "",
        "| test_id | crop sets | complete crop sets | readiness |",
        "|---|---:|---:|---|",
    ]
    for item in require_array(output.get("targets"), "output.targets"):
        target = require_object(item, "output.targets[]")
        lines.append(
            f"| `{target['test_id']}` | {target['crop_set_count']} | "
            f"{target['complete_crop_set_count']} | `{target['readiness']}` |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
