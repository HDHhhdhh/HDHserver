# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_phase2e_answer_value_letter_confusion_policy.py

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.phase2c_crop_pipeline_adapter import Phase2CResult  # noqa: E402
from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import Phase2ERequest  # noqa: E402
from tools.subjective_sheet_lab.phase2e_live_provider_runner import review_payload_from_provider_items  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

SERVER_OCR: Final[Path] = Path(r"C:\server-ocr")
GANG_RECOGNIZED: Final[Path] = (
    SERVER_OCR
    / "phase2e_live_qa_cache"
    / "phase2c_20260701T123845Z_4d6cdf1c_4f594d4d_t_unit_daesu_01_lv3_r1_r1"
    / "recognized.json"
)
GANG_HUMAN: Final[Path] = ROOT / "tools" / "subjective_sheet_lab" / "gangyuhyun849_human_transcription.json"
ALLOWED_TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
CHOICE_NUMBER_QUESTIONS: Final[frozenset[int]] = frozenset((1, 3, 5, 9, 13, 14, 17, 19))
WARNING_CODE: Final[str] = "answer_value_letter_confusion"


@dataclass(frozen=True, slots=True)
class PolicyResult:
    safe_auto_grade: int
    review_required: int
    wrong_safe_auto_grade: int
    blocked_questions: tuple[int, ...]


class AnswerValueLetterPolicyError(Exception):
    pass


def main() -> int:
    clear_numeric = verify_clear_numeric_answers_stay_safe()
    letter_confusion = verify_letter_confusion_blocks_safe_auto_grade()
    gang = verify_gang_live_cache_policy()
    print(
        json.dumps(
            {
                "ok": True,
                "provider_call_count": 0,
                "submit_test_call_count": 0,
                "clear_numeric": asdict(clear_numeric),
                "letter_confusion": asdict(letter_confusion),
                "gangyuhyun849": asdict(gang),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0


def verify_clear_numeric_answers_stay_safe() -> PolicyResult:
    recognized = {question_no: "2" for question_no in range(1, 21)}
    payload = review_payload_from_provider_items(provider_items(recognized), fake_request())
    items = items_by_question(payload)
    counts = status_counts(items)
    if counts != {"safe_auto_grade": 20}:
        raise AnswerValueLetterPolicyError(f"clear numeric answers should remain safe: {counts}")
    return PolicyResult(safe_auto_grade=20, review_required=0, wrong_safe_auto_grade=0, blocked_questions=())


def verify_letter_confusion_blocks_safe_auto_grade() -> PolicyResult:
    recognized = {question_no: "2" for question_no in range(1, 21)}
    recognized[7] = "r"
    recognized[10] = "hl"
    recognized[18] = "no"
    payload = review_payload_from_provider_items(provider_items(recognized), fake_request())
    items = items_by_question(payload)
    for question_no in (7, 10, 18):
        assert_review_required(items, question_no)
        assert_warning(items, question_no, WARNING_CODE)
    counts = status_counts(items)
    return PolicyResult(
        safe_auto_grade=counts.get("safe_auto_grade", 0),
        review_required=counts.get("review_required", 0),
        wrong_safe_auto_grade=0,
        blocked_questions=(7, 10, 18),
    )


def verify_gang_live_cache_policy() -> PolicyResult:
    recognized = recognized_answers(GANG_RECOGNIZED)
    human = human_answers(GANG_HUMAN)
    payload = review_payload_from_provider_items(provider_items(recognized), fake_request())
    items = items_by_question(payload)
    for question_no in (7, 10, 18):
        assert_review_required(items, question_no)
        assert_warning(items, question_no, WARNING_CODE)
    counts = status_counts(items)
    wrong_safe = wrong_safe_auto_grade_count(items, human)
    if wrong_safe != 0:
        raise AnswerValueLetterPolicyError(f"wrong_safe_auto_grade should be 0 after hardening: {wrong_safe}")
    return PolicyResult(
        safe_auto_grade=counts.get("safe_auto_grade", 0),
        review_required=counts.get("review_required", 0),
        wrong_safe_auto_grade=wrong_safe,
        blocked_questions=(7, 10, 18),
    )


def provider_items(recognized: dict[int, str]) -> list[JsonObject]:
    return [{"question": question_no, "recognized": answer} for question_no, answer in sorted(recognized.items())]


def recognized_answers(path: Path) -> dict[int, str]:
    payload = require_object(json.loads(path.read_text(encoding="utf-8")), "recognized")
    items = require_array(payload.get("items"), "recognized.items")
    answers: dict[int, str] = {}
    for index, raw_item in enumerate(items, start=1):
        item = require_object(raw_item, f"recognized.items[{index}]")
        question = item.get("question")
        recognized = item.get("recognized")
        if not isinstance(question, int) or isinstance(question, bool) or not isinstance(recognized, str):
            raise AnswerValueLetterPolicyError(f"malformed recognized item {index}")
        answers[question] = recognized
    return answers


def human_answers(path: Path) -> dict[int, str]:
    payload = require_object(json.loads(path.read_text(encoding="utf-8")), "human transcription")
    items = require_array(payload.get("answers"), "human.answers")
    answers: dict[int, str] = {}
    for index, raw_item in enumerate(items, start=1):
        item = require_object(raw_item, f"human.answers[{index}]")
        question = item.get("question_no")
        answer = item.get("human_answer")
        if not isinstance(question, int) or isinstance(question, bool) or not isinstance(answer, str):
            raise AnswerValueLetterPolicyError(f"malformed human item {index}")
        answers[question] = answer
    return answers


def wrong_safe_auto_grade_count(items: dict[int, JsonObject], human: dict[int, str]) -> int:
    wrong = 0
    for question_no, item in items.items():
        if item.get("status") != "safe_auto_grade":
            continue
        recognized = text_value(item.get("recognized"))
        if normalize(recognized) != normalize(human.get(question_no, "")):
            wrong += 1
    return wrong


def fake_request() -> Phase2ERequest:
    return Phase2ERequest(
        sid="849",
        test_id=ALLOWED_TEST_ID,
        round_no=1,
        pipeline_result=fake_pipeline_result(),
        cache_miss_reason="provider_free_policy_check",
        request_metadata={"verifier": "answer_value_letter_confusion"},
    )


def fake_pipeline_result() -> Phase2CResult:
    root = Path(r"C:\server-ocr\phase2e_answer_value_letter_policy\fake_case")
    return Phase2CResult(
        case_id="phase2e_answer_value_letter_policy",
        case_dir=root,
        source_image=root / "incoming" / "full_sheet.jpg",
        crop_root=root / "crop_benchmark_inputs" / "phase2e_answer_value_letter_policy",
        crop_dir=root / "crop_benchmark_inputs" / "phase2e_answer_value_letter_policy" / "crops",
        review_asset_root=root / "review_assets",
        asset_manifest=root / "review_assets" / "asset_manifest.json",
        crop_count=20,
        contact_sheet_count=4,
        debug_sheet_count=0,
        contact_sheets=(),
        debug_sheets=(),
        asset_verification=root / "review_assets" / "asset_verification.json",
        crop_quality=root / "crop_benchmark_inputs" / "phase2e_answer_value_letter_policy" / "crop_quality.json",
        answer_box_source="provider_free_policy_check",
    )


def items_by_question(payload: JsonObject) -> dict[int, JsonObject]:
    items = require_array(payload.get("items"), "payload.items")
    by_question: dict[int, JsonObject] = {}
    for index, raw_item in enumerate(items, start=1):
        item = require_object(raw_item, f"payload.items[{index}]")
        question_no = item.get("question_no")
        if not isinstance(question_no, int) or isinstance(question_no, bool):
            raise AnswerValueLetterPolicyError(f"item {index} has invalid question_no")
        by_question[question_no] = item
    return by_question


def status_counts(items: dict[int, JsonObject]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items.values():
        status = text_value(item.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def assert_review_required(items: dict[int, JsonObject], question_no: int) -> None:
    item = items[question_no]
    if item.get("status") != "review_required" or item.get("final_answer") is not None:
        raise AnswerValueLetterPolicyError(f"q{question_no:03d} should be review_required: {item}")


def assert_warning(items: dict[int, JsonObject], question_no: int, warning: str) -> None:
    warnings = require_array(items[question_no].get("warnings"), f"q{question_no:03d}.warnings")
    if warning not in warnings:
        raise AnswerValueLetterPolicyError(f"q{question_no:03d} missing {warning}: {warnings}")


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise AnswerValueLetterPolicyError(f"{label} must be an object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise AnswerValueLetterPolicyError(f"{label} must be an array")
    return value


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


if __name__ == "__main__":
    raise SystemExit(main())
