# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_replay_cache_skeleton.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import JsonObject, JsonValue, require_int_value
from ocr_review_payload_validator import PayloadMode, require_object, validate_payload

LAB: Final[Path] = Path(__file__).resolve().parent
CACHE_DIR: Final[Path] = LAB / "training_pack_provider_free_replay_cache"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_replay_cache_skeleton.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_replay_cache_skeleton.md"
WARNING: Final[str] = "provider_free_skeleton_review_required"
TARGETS: Final[tuple[tuple[str, str], ...]] = (
    ("t_training_pack_gongsu2_non_frequent_r1", "1"),
    ("t_training_pack_gongsu2_non_frequent_r2", "2"),
    ("t_training_pack_mijeok1_non_frequent_r1", "1"),
    ("t_training_pack_mijeok1_non_frequent_r2", "2"),
)
SENSITIVE_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
)


@dataclass(frozen=True, slots=True)
class TrainingPackReplaySkeletonError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class CacheRow:
    test_id: str
    round_no: str
    file_name: str
    item_count: int
    review_required_count: int
    safe_auto_grade_count: int
    recognized_value_count: int


def main() -> int:
    CACHE_DIR.mkdir(exist_ok=True)
    rows = tuple(write_payload(test_id, round_no) for test_id, round_no in TARGETS)
    output = summary(rows)
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def write_payload(test_id: str, round_no: str) -> CacheRow:
    payload = review_payload(test_id, round_no)
    validate_payload(require_object(payload.get("review_payload"), "review_payload"), PayloadMode.REVIEW, test_id)
    path = CACHE_DIR / f"{test_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    items = require_items(payload)
    return CacheRow(
        test_id=test_id,
        round_no=round_no,
        file_name=path.name,
        item_count=len(items),
        review_required_count=sum(1 for item in items if status_of(item) == "review_required"),
        safe_auto_grade_count=sum(1 for item in items if status_of(item) == "safe_auto_grade"),
        recognized_value_count=sum(1 for item in items if recognized_of(item).strip()),
    )


def review_payload(test_id: str, round_no: str) -> JsonObject:
    return {
        "review_payload": {
            "test_id": test_id,
            "round": round_no,
            "problem_count": 20,
            "source": "provider_free_training_pack_replay_skeleton",
            "items": [review_item(question_no) for question_no in range(1, 21)],
        }
    }


def review_item(question_no: int) -> JsonObject:
    return {
        "question_no": question_no,
        "status": "review_required",
        "recognized": "",
        "warnings": [WARNING],
        "candidates": [],
        "final_answer": None,
        "source": None,
    }


def require_items(payload: JsonObject) -> list[JsonObject]:
    review = require_object(payload.get("review_payload"), "review_payload")
    raw_items = review.get("items")
    match raw_items:
        case list():
            return [require_object(item, "review_payload.items[]") for item in raw_items]
        case None | bool() | int() | float() | str() | dict():
            raise TrainingPackReplaySkeletonError("review_payload.items must be an array")
        case unreachable:
            assert_never(unreachable)


def status_of(item: JsonObject) -> str:
    return string_field(item.get("status"), "status")


def recognized_of(item: JsonObject) -> str:
    return string_field(item.get("recognized"), "recognized")


def string_field(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise TrainingPackReplaySkeletonError(f"{label} must be a string")
        case unreachable:
            assert_never(unreachable)


def summary(rows: tuple[CacheRow, ...]) -> JsonObject:
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_PROVIDER_FREE_REPLAY_SKELETON_READY",
        "cache_replay_payload_count": len(rows),
        "target_count": len({row.test_id for row in rows}),
        "total_item_count": sum(row.item_count for row in rows),
        "review_required_count": sum(row.review_required_count for row in rows),
        "safe_auto_grade_count": sum(row.safe_auto_grade_count for row in rows),
        "recognized_value_count": sum(row.recognized_value_count for row in rows),
        "ready_for_provider_free_manual_confirmation_replay": True,
        "ready_for_ocr_accuracy_claim": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "sensitive_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "payloads": [row_payload(row) for row in rows],
    }
    text = json.dumps(output, ensure_ascii=False)
    output["sensitive_field_leak_count"] = sensitive_leak_count(text)
    output["filesystem_path_leak_count"] = filesystem_path_leak_count(text)
    return output


def row_payload(row: CacheRow) -> JsonObject:
    return {
        "test_id": row.test_id,
        "round": row.round_no,
        "file_name": row.file_name,
        "item_count": row.item_count,
        "review_required_count": row.review_required_count,
        "safe_auto_grade_count": row.safe_auto_grade_count,
        "recognized_value_count": row.recognized_value_count,
    }


def require_summary(output: JsonObject) -> None:
    require_int_value(output.get("cache_replay_payload_count"), 4, "cache_replay_payload_count")
    require_int_value(output.get("target_count"), 4, "target_count")
    require_int_value(output.get("total_item_count"), 80, "total_item_count")
    require_int_value(output.get("review_required_count"), 80, "review_required_count")
    require_int_value(output.get("safe_auto_grade_count"), 0, "safe_auto_grade_count")
    require_int_value(output.get("recognized_value_count"), 0, "recognized_value_count")
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
        "# OCR Training Pack Replay Cache Skeleton",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- cache replay payloads: {output['cache_replay_payload_count']}",
        f"- total items: {output['total_item_count']}",
        f"- review-required items: {output['review_required_count']}",
        f"- safe-auto-grade items: {output['safe_auto_grade_count']}",
        f"- recognized values: {output['recognized_value_count']}",
        "- ready for manual-confirmation replay: true",
        "- ready for OCR accuracy claim: false",
        "- sensitive/path leak count: 0",
        "",
        "| test_id | round | payload file | items | review required |",
        "|---|---:|---|---:|---:|",
    ]
    for item in payloads_array(output):
        lines.append(
            f"| `{item['test_id']}` | {item['round']} | `{item['file_name']}` | "
            f"{item['item_count']} | {item['review_required_count']} |"
        )
    return "\n".join(lines) + "\n"


def payloads_array(output: JsonObject) -> list[JsonObject]:
    raw_payloads = output.get("payloads")
    match raw_payloads:
        case list():
            return [require_object(item, "payloads[]") for item in raw_payloads]
        case None | bool() | int() | float() | str() | dict():
            raise TrainingPackReplaySkeletonError("payloads must be an array")
        case unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    raise SystemExit(main())
