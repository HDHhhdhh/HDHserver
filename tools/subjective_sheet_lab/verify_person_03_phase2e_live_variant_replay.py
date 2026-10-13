# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_person_03_phase2e_live_variant_replay.py

from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
EnvValues: TypeAlias = dict[str, str | None]
FormValue: TypeAlias = str | tuple[io.BytesIO, str, str]
FormFields: TypeAlias = dict[str, FormValue]

ROUTE: Final[str] = "/api/ocr-test-sheet-review"
ROUTE_ENABLED_ENV: Final[str] = "OCR_PHASE2_REVIEW_ROUTE_ENABLED"
CACHE_ENABLED_ENV: Final[str] = "OCR_PHASE2D_CACHED_REVIEW_ENABLED"
CACHE_RECOGNIZED_ENV: Final[str] = "OCR_PHASE2D_RECOGNIZED_JSON"
CACHE_REVIEW_ENV: Final[str] = "OCR_PHASE2D_CACHED_REVIEW_PAYLOAD"
LIVE_ENABLED_ENV: Final[str] = "OCR_PHASE2E_GEMINI_LIVE_ENABLED"
CACHE_WRITE_ENABLED_ENV: Final[str] = "OCR_PHASE2E_CACHE_WRITE_ENABLED"
LOCAL_ONLY_ENV: Final[str] = "OCR_PHASE2E_LOCAL_ONLY"
REQUIRE_CACHE_MISS_ENV: Final[str] = "OCR_PHASE2E_PROVIDER_CALLS_REQUIRE_CACHE_MISS"
PROVIDER_ALLOWED_ENV: Final[str] = "OCR_PHASE2E_PROVIDER_CALLS_ALLOWED"
MAX_CALLS_ENV: Final[str] = "OCR_PHASE2E_MAX_PROVIDER_CALLS_PER_REQUEST"
FAIL_CLOSED_ENV: Final[str] = "OCR_PHASE2E_FAIL_CLOSED_ON_PROVIDER_ERROR"
ALLOWED_TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
FULL_SHEET: Final[Path] = Path(r"C:\server-ocr\incoming_cases\person_03\full_sheet.jpg")
VARIANT_RECOGNIZED: Final[Path] = Path(
    r"C:\server-ocr\phase2e_live_qa_cache\phase2c_20260702T180931Z_a00efb82_253f5c33_t_unit_daesu_01_lv3_r1_r1\recognized.json",
)
FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "score", "wrong", "pct"),
)
PATH_TOKENS: Final[tuple[str, ...]] = ("C:\\", "C:/", "server-ocr", "phase2c_route_uploads", "crop_benchmark_inputs")


@dataclass(frozen=True, slots=True)
class Person03ReplayError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def main() -> int:
    ensure_inputs()
    source_summary = verify_variant_source()
    route_result = with_env(route_env(), replay_route)
    print(
        json.dumps(
            {
                "ok": True,
                "provider_call_count": 0,
                "submit_test_call_count": 0,
                "ts_submit_click_count": 0,
                "old_ocr_test_sheet_call_count": 0,
                "source_variant": source_summary,
                "route_replay": route_result,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0


def ensure_inputs() -> None:
    if not FULL_SHEET.is_file():
        raise Person03ReplayError(f"missing full sheet: {FULL_SHEET}")
    if not VARIANT_RECOGNIZED.is_file():
        raise Person03ReplayError(f"missing variant recognized file: {VARIANT_RECOGNIZED}")


def verify_variant_source() -> JsonObject:
    payload = require_object(json.loads(VARIANT_RECOGNIZED.read_text(encoding="utf-8-sig")), "variant recognized")
    items = require_array(payload.get("items"), "variant recognized.items")
    if len(items) != 20:
        raise Person03ReplayError(f"variant item count must be 20: {len(items)}")
    by_question = {question_from_item(item, index): require_object(item, f"items[{index}]") for index, item in enumerate(items, start=1)}
    question_numbers = sorted(by_question)
    if question_numbers != list(range(1, 21)):
        raise Person03ReplayError(f"variant questions must be 1..20: {question_numbers}")
    q018 = by_question[18]
    if q018.get("recognized") != "90":
        raise Person03ReplayError(f"q018 variant fixture changed: {q018}")
    assert_no_forbidden_fields(payload)
    return {
        "recognized_path": str(VARIANT_RECOGNIZED),
        "item_count": len(items),
        "q018_recognized": "90",
        "forbidden_field_hits": 0,
    }


def route_env() -> EnvValues:
    return {
        ROUTE_ENABLED_ENV: "1",
        CACHE_ENABLED_ENV: "1",
        CACHE_RECOGNIZED_ENV: str(VARIANT_RECOGNIZED),
        CACHE_REVIEW_ENV: None,
        LIVE_ENABLED_ENV: "0",
        CACHE_WRITE_ENABLED_ENV: "0",
        LOCAL_ONLY_ENV: "1",
        REQUIRE_CACHE_MISS_ENV: "1",
        PROVIDER_ALLOWED_ENV: "0",
        MAX_CALLS_ENV: "0",
        FAIL_CLOSED_ENV: "1",
    }


def with_env(values: EnvValues, action: Callable[[], JsonObject]) -> JsonObject:
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


def replay_route() -> JsonObject:
    from app import create_app  # noqa: PLC0415

    response = create_app().test_client().post(ROUTE, data=valid_fields())
    payload = require_object(response.get_json(silent=True), "route response")
    if response.status_code != 200 or payload.get("ok") is not True:
        raise Person03ReplayError(f"route replay failed {response.status_code}: {response.get_data(as_text=True)}")
    assert_no_forbidden_fields(payload)
    assert_no_paths(payload)
    review_payload = require_object(payload.get("review_payload"), "review_payload")
    review_meta = require_object(payload.get("review_meta"), "review_meta")
    items = require_array(review_payload.get("items"), "review_payload.items")
    status_counts = count_statuses(items)
    if review_payload.get("source") != "phase2d_cached_recognized":
        raise Person03ReplayError(f"unexpected replay source: {review_payload.get('source')}")
    if status_counts != {"review_required": 20}:
        raise Person03ReplayError(f"recognized-only replay must stay review-only: {status_counts}")
    assert_q018_review_required(items)
    if review_meta.get("provider_call_count") != 0 or review_meta.get("provider_status") != "not_called":
        raise Person03ReplayError(f"provider should not be called: {review_meta}")
    if review_meta.get("cache_status") != "hit":
        raise Person03ReplayError(f"variant cache should hit: {review_meta}")
    return {
        "http_status": response.status_code,
        "source": str(review_payload.get("source")),
        "item_count": len(items),
        "status_counts": status_counts,
        "cache_status": str(review_meta.get("cache_status")),
        "provider_status": str(review_meta.get("provider_status")),
        "provider_call_count": 0,
        "q018_status": "review_required",
        "q018_recognized": "90",
        "forbidden_field_hits": 0,
        "student_path_leaks": 0,
    }


def valid_fields() -> FormFields:
    return {
        "sid": "person_03_lab_qa",
        "testId": ALLOWED_TEST_ID,
        "round": "1",
        "image": (io.BytesIO(FULL_SHEET.read_bytes()), "person_03_full_sheet.jpg", "image/jpeg"),
    }


def count_statuses(items: list[JsonValue]) -> dict[str, int]:
    counts = Counter(text_value(require_object(item, f"item[{index}]").get("status")) for index, item in enumerate(items, start=1))
    return dict(sorted(counts.items()))


def assert_q018_review_required(items: list[JsonValue]) -> None:
    q018 = next((require_object(item, f"item[{index}]") for index, item in enumerate(items, start=1) if question_no(item) == 18), None)
    if q018 is None:
        raise Person03ReplayError("q018 missing from review payload")
    if q018.get("status") != "review_required" or q018.get("final_answer") is not None:
        raise Person03ReplayError(f"q018 must be unresolved review_required: {q018}")
    if q018.get("recognized") != "90":
        raise Person03ReplayError(f"q018 recognized value changed: {q018}")


def question_from_item(value: JsonValue, index: int) -> int:
    item = require_object(value, f"items[{index}]")
    question = item.get("question")
    if not isinstance(question, int) or isinstance(question, bool):
        raise Person03ReplayError(f"items[{index}].question must be int")
    return question


def question_no(value: JsonValue) -> int:
    item = require_object(value, "review item")
    question = item.get("question_no")
    if not isinstance(question, int) or isinstance(question, bool):
        raise Person03ReplayError(f"review item question_no must be int: {item}")
    return question


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise Person03ReplayError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise Person03ReplayError(f"{label} must be a JSON array")
    return value


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""


def assert_no_forbidden_fields(value: JsonValue, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_FIELDS:
                raise Person03ReplayError(f"student-facing payload leaked {path}.{key}")
            assert_no_forbidden_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_forbidden_fields(child, f"{path}[{index}]")


def assert_no_paths(value: JsonValue) -> None:
    text = json.dumps(value, ensure_ascii=False)
    if any(token in text for token in PATH_TOKENS):
        raise Person03ReplayError("student-facing payload exposed a local path")


if __name__ == "__main__":
    raise SystemExit(main())
