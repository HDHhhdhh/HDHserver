# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_accuracy_gate.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, TypeAlias, assert_never

from verify_ocr_cached_replay_determinism_gate import REPORT_JSON as REPLAY_JSON
from verify_ocr_cached_replay_determinism_gate import main as verify_replay
from verify_ocr_local_candidate_policy_matrix import REPORT_JSON as LOCAL_POLICY_JSON
from verify_ocr_local_candidate_policy_matrix import main as verify_local_policy
from verify_ocr_postprocessing_gate_standard_report import REPORT_JSON as POSTPROCESSING_JSON
from verify_ocr_postprocessing_gate_standard_report import main as verify_postprocessing
from verify_ocr_quality_threshold_boundary_matrix import REPORT_JSON as QUALITY_JSON
from verify_ocr_quality_threshold_boundary_matrix import main as verify_quality
from verify_ocr_second_pass_candidate_matrix import REPORT_JSON as SECOND_PASS_JSON
from verify_ocr_second_pass_candidate_matrix import main as verify_second_pass

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_provider_free_accuracy_gate.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_provider_free_accuracy_gate.md")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
Verifier: TypeAlias = Callable[[], int]


@dataclass(frozen=True, slots=True)
class AccuracyGateError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    for label, verifier in verifiers():
        result = verifier()
        if result != 0:
            raise AccuracyGateError(f"{label} failed with exit code {result}")
    replay = read_json_object(REPLAY_JSON)
    quality = read_json_object(QUALITY_JSON)
    second_pass = read_json_object(SECOND_PASS_JSON)
    local_policy = read_json_object(LOCAL_POLICY_JSON)
    postprocessing = read_json_object(POSTPROCESSING_JSON)
    output = summary(replay, quality, second_pass, local_policy, postprocessing)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (
        ("cached replay determinism", verify_replay),
        ("quality threshold boundary matrix", verify_quality),
        ("second-pass candidate matrix", verify_second_pass),
        ("local candidate policy matrix", verify_local_policy),
        ("postprocessing gate standard report", verify_postprocessing),
    )


def summary(replay: JsonObject, quality: JsonObject, second_pass: JsonObject, local_policy: JsonObject, postprocessing: JsonObject) -> JsonObject:
    for label, payload in (
        ("replay", replay),
        ("quality", quality),
        ("second_pass", second_pass),
        ("local_policy", local_policy),
        ("postprocessing", postprocessing),
    ):
        assert_common_safety(label, payload)
    require_int_value(replay.get("item_count"), 20, "replay.item_count")
    require_true(replay.get("stable_same_payload_hash_across_runs"), "replay.stable_same_payload_hash_across_runs")
    require_true(replay.get("stable_same_ui_review_questions_across_runs"), "replay.stable_same_ui_review_questions_across_runs")
    require_int_value(quality.get("retake_required_case_count"), 7, "quality.retake_required_case_count")
    require_int_value(quality.get("review_only_case_count"), 1, "quality.review_only_case_count")
    require_int_value(second_pass.get("candidate_count"), 7, "second_pass.candidate_count")
    require_int_value(second_pass.get("merge_auto_confirm_count"), 0, "second_pass.merge_auto_confirm_count")
    require_int_value(local_policy.get("policy_review_required_count"), 5, "local_policy.policy_review_required_count")
    require_int_value(local_policy.get("policy_safe_preserved_count"), 2, "local_policy.policy_safe_preserved_count")
    require_int_value(postprocessing.get("blocked_case_count"), 14, "postprocessing.blocked_case_count")
    require_int_value(postprocessing.get("recognized_only_cache_case_count"), 1, "postprocessing.recognized_only_cache_case_count")
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "gate_count": 5,
        "cached_replay_item_count": 20,
        "cached_replay_review_required_count": require_int(replay.get("review_required_count"), "replay.review_required_count"),
        "quality_retake_required_case_count": 7,
        "quality_review_only_case_count": 1,
        "second_pass_candidate_count": 7,
        "second_pass_merge_auto_confirm_count": 0,
        "local_policy_review_required_count": 5,
        "local_policy_safe_preserved_count": 2,
        "postprocessing_blocked_case_count": 14,
        "postprocessing_recognized_only_cache_case_count": 1,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def assert_common_safety(label: str, payload: JsonObject) -> None:
    if payload.get("ok") is not True:
        raise AccuracyGateError(f"{label}.ok must be true")
    if payload.get("student_facing") is not False:
        raise AccuracyGateError(f"{label}.student_facing must be false")
    if payload.get("production_default") != "NO_GO":
        raise AccuracyGateError(f"{label}.production_default must be NO_GO")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")
    require_int_value(payload.get("answer_key_or_grading_field_leak_count"), 0, f"{label}.answer_key_or_grading_field_leak_count")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{label}.filesystem_path_leak_count")


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), str(path))


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise AccuracyGateError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise AccuracyGateError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_int_value(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int(value, label)
    if actual != expected:
        raise AccuracyGateError(f"{label} expected {expected}, got {actual}")


def require_true(value: JsonValue, label: str) -> None:
    if value is not True:
        raise AccuracyGateError(f"{label} must be true")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Provider-Free Accuracy Gate",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- provider-free gates run: {output['gate_count']}",
        f"- cached replay review-required count: {output['cached_replay_review_required_count']}",
        f"- quality retake-required boundary cases: {output['quality_retake_required_case_count']}",
        f"- quality review-only boundary cases: {output['quality_review_only_case_count']}",
        f"- second-pass candidate count: {output['second_pass_candidate_count']}",
        f"- second-pass auto-confirm count: {output['second_pass_merge_auto_confirm_count']}",
        f"- local candidate review-required outcomes: {output['local_policy_review_required_count']}",
        f"- local candidate safe-preserved outcomes: {output['local_policy_safe_preserved_count']}",
        f"- postprocessing blocked cases: {output['postprocessing_blocked_case_count']}",
        f"- recognized-only cache cases kept review: {output['postprocessing_recognized_only_cache_case_count']}",
        "- answer-key/grading/path leak count: 0",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
