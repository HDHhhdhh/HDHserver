# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_ui_replay_bridge.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_answers_text_bridge import BridgeError, convert_json_payload
from ocr_provider_free_extended_gate_common import JsonObject, JsonValue, require_int_value
from ocr_review_payload_validator import ContractError, PayloadMode, require_object, validate_payload

LAB: Final[Path] = Path(__file__).resolve().parent
CACHE_DIR: Final[Path] = LAB / "training_pack_provider_free_replay_cache"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_ui_replay_bridge.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_ui_replay_bridge.md"
TARGET_FILES: Final[tuple[str, ...]] = (
    "t_training_pack_gongsu2_non_frequent_r1.json",
    "t_training_pack_gongsu2_non_frequent_r2.json",
    "t_training_pack_mijeok1_non_frequent_r1.json",
    "t_training_pack_mijeok1_non_frequent_r2.json",
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
class TrainingPackUiReplayBridgeError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ReplayBridgeRow:
    file_name: str
    item_count: int
    review_required_count: int
    safe_auto_grade_count: int
    recognized_value_count: int
    final_bridge_allowed: bool
    answers_text_line_count: int
    fill_answers_button_allowed: bool
    ui_review_card_count: int
    ui_review_question_count: int


def main() -> int:
    rows = tuple(analyze_payload(file_name) for file_name in TARGET_FILES)
    output = summary(rows)
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def analyze_payload(file_name: str) -> ReplayBridgeRow:
    raw = read_json_object(CACHE_DIR / file_name)
    review_payload = require_object(raw.get("review_payload"), f"{file_name}.review_payload")
    validate_payload(review_payload, PayloadMode.REVIEW, file_name)
    items = require_items(review_payload, file_name)
    final_bridge_allowed = bridge_allows_final_answers(review_payload)
    if final_bridge_allowed:
        raise TrainingPackUiReplayBridgeError(f"{file_name} unexpectedly allowed answersText fill")
    review_required_count = sum(1 for item in items if status_of(item) == "review_required")
    return ReplayBridgeRow(
        file_name=file_name,
        item_count=len(items),
        review_required_count=review_required_count,
        safe_auto_grade_count=sum(1 for item in items if status_of(item) == "safe_auto_grade"),
        recognized_value_count=sum(1 for item in items if recognized_of(item).strip()),
        final_bridge_allowed=final_bridge_allowed,
        answers_text_line_count=0,
        fill_answers_button_allowed=False,
        ui_review_card_count=review_required_count,
        ui_review_question_count=review_required_count,
    )


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), path.name)


def bridge_allows_final_answers(review_payload: JsonObject) -> bool:
    try:
        validate_payload(review_payload, PayloadMode.FINAL, "training_pack_ui_replay_bridge")
        convert_json_payload(review_payload)
    except (BridgeError, ContractError):
        return False
    return True


def require_items(payload: JsonObject, label: str) -> list[JsonObject]:
    raw_items = payload.get("items")
    match raw_items:
        case list():
            return [require_object(item, f"{label}.items[]") for item in raw_items]
        case None | bool() | int() | float() | str() | dict():
            raise TrainingPackUiReplayBridgeError(f"{label}.items must be an array")
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
            raise TrainingPackUiReplayBridgeError(f"{label} must be a string")
        case unreachable:
            assert_never(unreachable)


def summary(rows: tuple[ReplayBridgeRow, ...]) -> JsonObject:
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_UI_REPLAY_BRIDGE_SKELETON_BLOCKS_FILL",
        "payload_count": len(rows),
        "total_item_count": sum(row.item_count for row in rows),
        "review_required_count": sum(row.review_required_count for row in rows),
        "safe_auto_grade_count": sum(row.safe_auto_grade_count for row in rows),
        "recognized_value_count": sum(row.recognized_value_count for row in rows),
        "final_bridge_allowed_count": sum(1 for row in rows if row.final_bridge_allowed),
        "blocked_final_bridge_count": sum(1 for row in rows if not row.final_bridge_allowed),
        "answers_text_line_count": sum(row.answers_text_line_count for row in rows),
        "answers_text_fill_allowed_count": sum(1 for row in rows if row.fill_answers_button_allowed),
        "ui_review_card_count": sum(row.ui_review_card_count for row in rows),
        "ui_review_question_count": sum(row.ui_review_question_count for row in rows),
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


def row_payload(row: ReplayBridgeRow) -> JsonObject:
    return {
        "file_name": row.file_name,
        "item_count": row.item_count,
        "review_required_count": row.review_required_count,
        "safe_auto_grade_count": row.safe_auto_grade_count,
        "recognized_value_count": row.recognized_value_count,
        "final_bridge_allowed": row.final_bridge_allowed,
        "answers_text_line_count": row.answers_text_line_count,
        "fill_answers_button_allowed": row.fill_answers_button_allowed,
        "ui_review_card_count": row.ui_review_card_count,
        "ui_review_question_count": row.ui_review_question_count,
    }


def require_summary(output: JsonObject) -> None:
    require_int_value(output.get("payload_count"), 4, "payload_count")
    require_int_value(output.get("total_item_count"), 80, "total_item_count")
    require_int_value(output.get("review_required_count"), 80, "review_required_count")
    require_int_value(output.get("safe_auto_grade_count"), 0, "safe_auto_grade_count")
    require_int_value(output.get("recognized_value_count"), 0, "recognized_value_count")
    require_int_value(output.get("final_bridge_allowed_count"), 0, "final_bridge_allowed_count")
    require_int_value(output.get("blocked_final_bridge_count"), 4, "blocked_final_bridge_count")
    require_int_value(output.get("answers_text_line_count"), 0, "answers_text_line_count")
    require_int_value(output.get("answers_text_fill_allowed_count"), 0, "answers_text_fill_allowed_count")
    require_int_value(output.get("ui_review_card_count"), 80, "ui_review_card_count")
    require_int_value(output.get("ui_review_question_count"), 80, "ui_review_question_count")
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
        "# OCR Training Pack UI Replay Bridge",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- payloads checked: {output['payload_count']}",
        f"- review-required UI cards: {output['ui_review_card_count']}",
        f"- answersText fill allowed: {output['answers_text_fill_allowed_count']}",
        f"- final bridge blocked payloads: {output['blocked_final_bridge_count']}",
        f"- safe-auto-grade items: {output['safe_auto_grade_count']}",
        f"- recognized values: {output['recognized_value_count']}",
        "- ready for manual-confirmation replay: true",
        "- ready for OCR accuracy claim: false",
        "- sensitive/path leak count: 0",
        "",
        "| payload file | items | review cards | final bridge allowed |",
        "|---|---:|---:|---:|",
    ]
    for item in payloads_array(output):
        lines.append(
            f"| `{item['file_name']}` | {item['item_count']} | "
            f"{item['ui_review_card_count']} | {item['final_bridge_allowed']} |"
        )
    return "\n".join(lines) + "\n"


def payloads_array(output: JsonObject) -> list[JsonObject]:
    raw_payloads = output.get("payloads")
    match raw_payloads:
        case list():
            return [require_object(item, "payloads[]") for item in raw_payloads]
        case None | bool() | int() | float() | str() | dict():
            raise TrainingPackUiReplayBridgeError("payloads must be an array")
        case unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    raise SystemExit(main())
