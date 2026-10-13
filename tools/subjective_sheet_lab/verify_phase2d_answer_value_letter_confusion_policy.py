# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_phase2d_answer_value_letter_confusion_policy.py

from __future__ import annotations

import io
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
FormValue: TypeAlias = str | tuple[io.BytesIO, str, str]
FormFields: TypeAlias = dict[str, FormValue]

ROUTE: Final[str] = "/api/ocr-test-sheet-review"
ROUTE_ENABLED_ENV: Final[str] = "OCR_PHASE2_REVIEW_ROUTE_ENABLED"
CACHE_ENABLED_ENV: Final[str] = "OCR_PHASE2D_CACHED_REVIEW_ENABLED"
CACHE_RECOGNIZED_ENV: Final[str] = "OCR_PHASE2D_RECOGNIZED_JSON"
CACHE_REVIEW_ENV: Final[str] = "OCR_PHASE2D_CACHED_REVIEW_PAYLOAD"
ALLOWED_TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
FULL_SHEET: Final[Path] = Path(r"C:\server-ocr\incoming_cases\person_03\full_sheet.jpg")
FIXTURE_ROOT: Final[Path] = Path(r"C:\server-ocr\phase2d_cache_verifier")
FIXTURE_PATH: Final[Path] = FIXTURE_ROOT / "answer_value_letter_confusion_review_payload.json"
WARNING_CODE: Final[str] = "answer_value_letter_confusion"
FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "score", "wrong", "pct"))


class Phase2DLetterPolicyError(Exception):
    pass


def main() -> int:
    if not FULL_SHEET.is_file():
        raise Phase2DLetterPolicyError(f"full-sheet image missing: {FULL_SHEET}")
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(review_payload_fixture(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = with_env(route_env(), verify_route)
    print(json.dumps({"ok": True, "provider_call_count": 0, "submit_test_call_count": 0, "result": result}, ensure_ascii=False, indent=2))
    return 0


def verify_route() -> JsonObject:
    client = create_app().test_client()
    response = client.post(ROUTE, data=valid_fields())
    payload = require_object(response.get_json(silent=True), "response")
    if response.status_code != 200 or payload.get("ok") is not True:
        raise Phase2DLetterPolicyError(f"route failed {response.status_code}: {response.get_data(as_text=True)}")
    assert_no_forbidden_fields(payload)
    assert_no_paths(payload)
    review_payload = require_object(payload.get("review_payload"), "review_payload")
    if review_payload.get("source") != "phase2d_cached_review_payload":
        raise Phase2DLetterPolicyError(f"unexpected source: {review_payload.get('source')}")
    items = items_by_question(review_payload)
    for question_no in (7, 10, 18):
        assert_review_required(items, question_no)
        assert_warning(items, question_no, WARNING_CODE)
    statuses = status_counts(items)
    if statuses != {"safe_auto_grade": 17, "review_required": 3}:
        raise Phase2DLetterPolicyError(f"unexpected statuses: {statuses}")
    return {"items": len(items), "statuses": statuses, "blocked_questions": [7, 10, 18]}


def review_payload_fixture() -> JsonObject:
    items = [safe_item(question_no, "2") for question_no in range(1, 21)]
    for question_no, answer in ((7, "r"), (10, "hl"), (18, "no")):
        items[question_no - 1] = safe_item(question_no, answer)
    return {
        "source": "answer_value_letter_confusion_fixture",
        "test_id": ALLOWED_TEST_ID,
        "round": "1",
        "problem_count": 20,
        "items": items,
    }


def safe_item(question_no: int, answer: str) -> JsonObject:
    return {
        "question_no": question_no,
        "status": "safe_auto_grade",
        "recognized": answer,
        "warnings": [],
        "candidates": [],
        "final_answer": answer,
        "source": "safe_auto_grade",
    }


def route_env() -> dict[str, str | None]:
    return {
        ROUTE_ENABLED_ENV: "1",
        CACHE_ENABLED_ENV: "1",
        CACHE_REVIEW_ENV: str(FIXTURE_PATH),
        CACHE_RECOGNIZED_ENV: None,
    }


def with_env(values: dict[str, str | None], action: Callable[[], JsonObject]) -> JsonObject:
    previous = {key: os.environ.get(key) for key in values}
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        return action()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def valid_fields() -> FormFields:
    return {
        "sid": "990",
        "testId": ALLOWED_TEST_ID,
        "round": "1",
        "image": (io.BytesIO(FULL_SHEET.read_bytes()), "full_sheet.jpg", "image/jpeg"),
    }


def items_by_question(payload: JsonObject) -> dict[int, JsonObject]:
    items = require_array(payload.get("items"), "review_payload.items")
    by_question: dict[int, JsonObject] = {}
    for index, raw_item in enumerate(items, start=1):
        item = require_object(raw_item, f"review_payload.items[{index}]")
        question_no = item.get("question_no")
        if not isinstance(question_no, int) or isinstance(question_no, bool):
            raise Phase2DLetterPolicyError(f"invalid question_no at item {index}")
        by_question[question_no] = item
    return by_question


def status_counts(items: dict[int, JsonObject]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items.values():
        status = str(item.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
    return counts


def assert_review_required(items: dict[int, JsonObject], question_no: int) -> None:
    item = items[question_no]
    if item.get("status") != "review_required" or item.get("final_answer") is not None:
        raise Phase2DLetterPolicyError(f"q{question_no:03d} should be review_required: {item}")


def assert_warning(items: dict[int, JsonObject], question_no: int, warning: str) -> None:
    warnings = require_array(items[question_no].get("warnings"), f"q{question_no:03d}.warnings")
    if warning not in warnings:
        raise Phase2DLetterPolicyError(f"q{question_no:03d} missing {warning}: {warnings}")


def assert_no_forbidden_fields(value: JsonValue, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_FIELDS:
                raise Phase2DLetterPolicyError(f"student-facing payload leaked {path}.{key}")
            assert_no_forbidden_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_forbidden_fields(child, f"{path}[{index}]")


def assert_no_paths(value: JsonValue) -> None:
    text = json.dumps(value, ensure_ascii=False)
    path_tokens = ("C:\\", "C:/", "server-ocr", "phase2c_route_uploads", "crop_benchmark_inputs")
    if any(token in text for token in path_tokens):
        raise Phase2DLetterPolicyError("student-facing payload exposed a local path")


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise Phase2DLetterPolicyError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise Phase2DLetterPolicyError(f"{label} must be a JSON array")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
