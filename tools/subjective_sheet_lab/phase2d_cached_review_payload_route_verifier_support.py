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

from tools.subjective_sheet_lab.phase2e_stable_cache import (  # noqa: E402
    PHASE2E_CACHE_ROOT_ENV,
    StableOcrCacheRequest,
    stable_recognized_path_or_none,
)

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
DEFAULT_CACHE: Final[Path] = Path(r"C:\server-ocr\gemini_outputs\daesu_jisu1_lv3_r1_photo01_same_contact\recognized.json")
RUNTIME_ROOT: Final[Path] = Path(r"C:\server-ocr\phase2c_route_uploads")
FIXTURE_ROOT: Final[Path] = Path(r"C:\server-ocr\phase2d_cache_verifier")
FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "score", "wrong", "pct"),
)


class Phase2DVerificationError(Exception):
    pass


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


def write_cache_fixtures() -> dict[str, Path]:
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    stable_cache_root = FIXTURE_ROOT / "stable_cache"
    stable_recognized = stable_recognized_fixture_path(stable_cache_root)
    review_payload = FIXTURE_ROOT / "safe_review_payload.json"
    recognized_status = FIXTURE_ROOT / "recognized_with_status.json"
    malformed = FIXTURE_ROOT / "malformed_recognized.json"
    forbidden = FIXTURE_ROOT / "forbidden_recognized.json"
    malformed_review_payload = FIXTURE_ROOT / "malformed_review_payload.json"
    forbidden_review_payload = FIXTURE_ROOT / "forbidden_review_payload.json"
    path_leak_review_payload = FIXTURE_ROOT / "path_leak_review_payload.json"
    invalid_choice_review_payload = FIXTURE_ROOT / "invalid_choice_review_payload.json"
    wrapped_route_response = FIXTURE_ROOT / "wrapped_route_response.json"
    missing = FIXTURE_ROOT / "missing_recognized.json"
    empty_stable_cache_root = FIXTURE_ROOT / "empty_stable_cache"
    stable_recognized.parent.mkdir(parents=True, exist_ok=True)
    stable_recognized.write_text(json.dumps(recognized_with_status_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_payload.write_text(json.dumps(safe_review_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    recognized_status.write_text(json.dumps(recognized_with_status_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    malformed.write_text(json.dumps({"items": [{"question": 1, "recognized": "1"}]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    forbidden.write_text(
        json.dumps({"items": [{"question": 1, "recognized": "1", "expected": "1"}]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    malformed_review_payload.write_text(
        json.dumps({"items": [{"question_no": 1, "status": "review_required", "recognized": "1"}]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    forbidden_review_payload.write_text(json.dumps(forbidden_review_payload_fixture(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path_leak_review_payload.write_text(json.dumps(path_leak_review_payload_fixture(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    invalid_choice_review_payload.write_text(json.dumps(invalid_choice_review_payload_fixture(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    wrapped_route_response.write_text(json.dumps(wrapped_route_response_fixture(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "review_payload": review_payload,
        "stable_cache_root": stable_cache_root,
        "stable_recognized": stable_recognized,
        "recognized_status": recognized_status,
        "malformed": malformed,
        "forbidden": forbidden,
        "malformed_review_payload": malformed_review_payload,
        "forbidden_review_payload": forbidden_review_payload,
        "path_leak_review_payload": path_leak_review_payload,
        "invalid_choice_review_payload": invalid_choice_review_payload,
        "wrapped_route_response": wrapped_route_response,
        "missing": missing,
        "empty_stable_cache_root": empty_stable_cache_root,
    }


def stable_recognized_fixture_path(cache_root: Path) -> Path:
    path = stable_recognized_path_or_none(
        StableOcrCacheRequest(
            sid="990",
            test_id=ALLOWED_TEST_ID,
            round_no=1,
            source_image=FULL_SHEET,
            cache_root=cache_root,
        )
    )
    if path is None:
        raise Phase2DVerificationError("could not derive stable recognized cache path for fixture image")
    return path


def safe_review_payload() -> JsonObject:
    return {
        "source": "test_cache_fixture",
        "test_id": ALLOWED_TEST_ID,
        "round": "1",
        "problem_count": 20,
        "items": [
            {
                "question_no": number,
                "status": "review_required",
                "recognized": f"cached-{number}",
                "warnings": ["cached_review_fixture"],
                "candidates": [],
                "final_answer": None,
                "source": None,
            }
            for number in range(1, 21)
        ],
    }


def recognized_with_status_payload() -> JsonObject:
    return {
        "items": [
            {
                "question": number,
                "recognized": f"recognized-{number}",
                "status": "safe_auto_grade",
                "warnings": ["recognized_status_fixture"],
            }
            for number in range(1, 21)
        ],
    }


def safe_auto_review_payload() -> JsonObject:
    return {
        "source": "test_cache_fixture_safe_auto",
        "test_id": ALLOWED_TEST_ID,
        "round": "1",
        "problem_count": 20,
        "items": [
            {
                "question_no": number,
                "status": "safe_auto_grade",
                "recognized": str(((number - 1) % 5) + 1),
                "warnings": [],
                "candidates": [],
                "final_answer": str(((number - 1) % 5) + 1),
                "source": "safe_auto_grade",
            }
            for number in range(1, 21)
        ],
    }


def invalid_choice_review_payload_fixture() -> JsonObject:
    payload = safe_auto_review_payload()
    items = require_array(payload.get("items"), "safe_auto_review_payload.items")
    choice_item = require_object(items[4], "safe_auto_review_payload.items[4]")
    choice_item["recognized"] = "x=2"
    choice_item["final_answer"] = "x=2"
    return payload


def wrapped_route_response_fixture() -> JsonObject:
    return {
        "ok": True,
        "review_meta": {
            "cache_status": "cache_miss",
            "provider_status": "live_call_succeeded",
            "provider_call_count": 1,
            "provider_input": "crop_contact_sheet",
        },
        "review_payload": safe_auto_review_payload(),
    }


def forbidden_review_payload_fixture() -> JsonObject:
    payload = safe_review_payload()
    items = require_array(payload.get("items"), "safe_review_payload.items")
    first = require_object(items[0], "safe_review_payload.items[0]")
    first["expected"] = "1"
    return payload


def path_leak_review_payload_fixture() -> JsonObject:
    payload = safe_review_payload()
    items = require_array(payload.get("items"), "safe_review_payload.items")
    first = require_object(items[0], "safe_review_payload.items[0]")
    first["warnings"] = [r"C:\server-ocr\phase2c_route_uploads\leak"]
    return payload


def valid_fields() -> FormFields:
    return {
        "sid": "990",
        "testId": ALLOWED_TEST_ID,
        "round": "1",
        "image": (io.BytesIO(FULL_SHEET.read_bytes()), "full_sheet.jpg", "image/jpeg"),
    }


def runtime_dirs() -> set[Path]:
    if not RUNTIME_ROOT.exists():
        return set()
    return {path for path in RUNTIME_ROOT.iterdir() if path.is_dir()}


def newest_created_dir(before: set[Path]) -> Path:
    created = runtime_dirs() - before
    if not created:
        raise Phase2DVerificationError("route did not create a Phase 2C runtime directory")
    return max(created, key=lambda path: path.stat().st_mtime_ns)


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise Phase2DVerificationError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise Phase2DVerificationError(f"{label} must be a JSON array")
    return value


def item_question_no(value: JsonValue, index: int) -> int:
    item = require_object(value, f"item {index}")
    question_no = item.get("question_no")
    if not isinstance(question_no, int) or isinstance(question_no, bool):
        raise Phase2DVerificationError(f"item {index} question_no must be int")
    return question_no


def count_statuses(items: list[JsonValue]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for index, value in enumerate(items, start=1):
        item = require_object(value, f"item {index}")
        status = str(item.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
    return counts


def assert_no_forbidden_fields(value: JsonValue, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_FIELDS:
                raise Phase2DVerificationError(f"student-facing payload leaked {path}.{key}")
            assert_no_forbidden_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_forbidden_fields(child, f"{path}[{index}]")


def assert_no_paths(value: JsonValue) -> None:
    text = json.dumps(value, ensure_ascii=False)
    path_tokens = ("C:\\", "C:/", "server-ocr", "phase2c_route_uploads", "crop_benchmark_inputs")
    if any(token in text for token in path_tokens):
        raise Phase2DVerificationError("student-facing payload exposed a local path")
