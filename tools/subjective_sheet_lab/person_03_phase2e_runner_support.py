from __future__ import annotations

import hashlib
import io
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

SID: Final[str] = "person_03_lab_qa"
TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
ROUND_NO: Final[int] = 1
ROUTE: Final[str] = "/api/ocr-test-sheet-review"
SERVER_OCR: Final[Path] = Path(r"C:\server-ocr")
FULL_SHEET: Final[Path] = SERVER_OCR / "incoming_cases" / "person_03" / "full_sheet.jpg"
CROP_DIR: Final[Path] = SERVER_OCR / "crop_benchmark_inputs" / "person_03" / "crops"
CONTACT_DIR: Final[Path] = SERVER_OCR / "gemini_contact_review_assets" / "person_03" / "contact_sheets"
CANONICAL_DIR: Final[Path] = SERVER_OCR / "gemini_outputs" / "person_03_same_contact"
CANONICAL_RECOGNIZED: Final[Path] = CANONICAL_DIR / "recognized.json"
CANONICAL_CACHE: Final[Path] = CANONICAL_DIR / "gemini_provider_cache.json"
RUNTIME_ROOT: Final[Path] = SERVER_OCR / "phase2c_route_uploads"
PHASE2E_CACHE_ROOT: Final[Path] = SERVER_OCR / "phase2e_live_qa_cache"
FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "score", "wrong", "pct"))
PATH_TOKENS: Final[tuple[str, ...]] = ("C:\\", "C:/", "server-ocr", "phase2c_route_uploads", "crop_benchmark_inputs")
AUTHORIZATION_PHRASES: Final[tuple[str, ...]] = (
    "외부 provider",
    "외부 전송 위험",
    "fresh provider call budget은 총 1회",
    "/api/submit-test는 호출하지 않는다",
    "#tsSubmit은 클릭하지 않는다",
    "API key/.env는 출력하지 않는다",
    "기존 person_03_same_contact recognized/cache는 덮어쓰지 않고",
)
ENV_NAMES: Final[dict[str, str]] = {
    "route": "OCR_PHASE2_REVIEW_ROUTE_ENABLED",
    "cache": "OCR_PHASE2D_CACHED_REVIEW_ENABLED",
    "recognized": "OCR_PHASE2D_RECOGNIZED_JSON",
    "review": "OCR_PHASE2D_CACHED_REVIEW_PAYLOAD",
    "live": "OCR_PHASE2E_GEMINI_LIVE_ENABLED",
    "write": "OCR_PHASE2E_CACHE_WRITE_ENABLED",
    "local": "OCR_PHASE2E_LOCAL_ONLY",
    "miss": "OCR_PHASE2E_PROVIDER_CALLS_REQUIRE_CACHE_MISS",
    "max": "OCR_PHASE2E_MAX_PROVIDER_CALLS_PER_REQUEST",
    "fail": "OCR_PHASE2E_FAIL_CLOSED_ON_PROVIDER_ERROR",
    "allowed": "OCR_PHASE2E_PROVIDER_CALLS_ALLOWED",
}


class Person03RunnerError(Exception):
    pass


class RouteEnvironment:
    def __init__(self, execute_live_call: bool, provider_call_budget: int) -> None:
        self._values = route_env_values(execute_live_call, provider_call_budget)
        self._previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        self._previous = {key: os.environ.get(key) for key in self._values}
        for key, value in self._values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        for key, value in self._previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def dry_run_summary(provider_call_budget: int) -> JsonObject:
    return {
        "ok": required_inputs_ready(),
        "mode": "dry_run_no_provider_call",
        "status": "USER_APPROVAL_REQUIRED",
        "sid": SID,
        "test_id": TEST_ID,
        "round": ROUND_NO,
        "route": ROUTE,
        "input_image_exists": FULL_SHEET.is_file(),
        "input_image_sha256": file_sha256(FULL_SHEET),
        "crop_count": count_files(CROP_DIR, "q*.png"),
        "contact_sheet_count": count_files(CONTACT_DIR, "*.png"),
        "canonical_recognized_exists": CANONICAL_RECOGNIZED.is_file(),
        "canonical_cache_exists": CANONICAL_CACHE.is_file(),
        "canonical_recognized_sha256": file_sha256(CANONICAL_RECOGNIZED),
        "canonical_cache_sha256": file_sha256(CANONICAL_CACHE),
        "provider_call_budget": provider_call_budget,
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "old_ocr_test_sheet_call_count": 0,
        "authorization_required": True,
    }


def authorization_error(execute_live_call: bool, provider_call_budget: int, authorization_file: Path | None) -> str:
    if not execute_live_call:
        return ""
    if provider_call_budget != 1:
        return "provider_call_budget_must_be_1"
    if authorization_file is None or not authorization_file.is_file():
        return "authorization_file_required"
    text = authorization_file.read_text(encoding="utf-8-sig")
    missing = [phrase for phrase in AUTHORIZATION_PHRASES if phrase not in text]
    if missing:
        return f"authorization_file_missing_required_phrase: {missing[0]}"
    if not required_inputs_ready():
        return "required_inputs_missing"
    return ""


def run_route(execute_live_call: bool, provider_call_budget: int) -> JsonObject:
    if not FULL_SHEET.is_file():
        raise Person03RunnerError(f"missing input image: {FULL_SHEET}")
    before_dirs = runtime_dirs()
    before_hashes = canonical_hashes()
    with RouteEnvironment(execute_live_call, provider_call_budget):
        from app import create_app  # noqa: PLC0415

        response = create_app().test_client().post(ROUTE, data=valid_fields())
    payload = require_object(response.get_json(silent=True), "route response")
    result = route_summary(response.status_code, payload, newest_created_dir(before_dirs))
    result["canonical_preserved"] = before_hashes == canonical_hashes()
    result["canonical_hashes"] = before_hashes
    return result


def route_env_values(execute_live_call: bool, provider_call_budget: int) -> dict[str, str | None]:
    force_miss = PHASE2E_CACHE_ROOT / f"person_03_force_cache_miss_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}" / "missing_recognized.json"
    return {
        ENV_NAMES["route"]: "true",
        ENV_NAMES["cache"]: "true",
        ENV_NAMES["recognized"]: str(force_miss),
        ENV_NAMES["review"]: None,
        ENV_NAMES["live"]: "true" if execute_live_call else "false",
        ENV_NAMES["write"]: "true" if execute_live_call else "false",
        ENV_NAMES["local"]: "false" if execute_live_call else "true",
        ENV_NAMES["miss"]: "true",
        ENV_NAMES["max"]: str(provider_call_budget if execute_live_call else 0),
        ENV_NAMES["fail"]: "true",
        ENV_NAMES["allowed"]: "true" if execute_live_call else "false",
    }


def route_summary(status_code: int, payload: JsonObject, case_dir: Path) -> JsonObject:
    review_payload = require_object(payload.get("review_payload"), "review_payload")
    items = require_array(review_payload.get("items"), "review_payload.items")
    review_meta = require_object(payload.get("review_meta"), "review_meta")
    return {
        "ok": payload.get("ok") is True,
        "mode": "live_one_call" if int_value(review_meta.get("provider_call_count")) == 1 else "provider_free_route_dry_run",
        "http_status": status_code,
        "status": "USER_APPROVAL_REQUIRED",
        "review_payload_item_count": len(items),
        "status_counts": dict(sorted(Counter(item_status(item) for item in items).items())),
        "cache_status": text_value(review_meta.get("cache_status")),
        "cache_source": text_value(review_meta.get("cache_source")),
        "provider_status": text_value(review_meta.get("provider_status")),
        "provider_call_count": int_value(review_meta.get("provider_call_count")),
        "crop_count": int_value(review_meta.get("crop_count")),
        "contact_sheet_count": int_value(review_meta.get("contact_sheet_count")),
        "case_dir": str(case_dir),
        "route_artifact_crop_count": route_artifact_crop_count(case_dir),
        "recognized_json_created_under_case": bool(tuple(case_dir.rglob("recognized.json"))),
        "student_facing_forbidden_key_hits": forbidden_key_hits(payload),
        "student_facing_path_leak_hits": path_leak_hits(payload),
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "old_ocr_test_sheet_call_count": 0,
        "api_key_env_exposed": False,
    }


def valid_fields() -> dict[str, str | tuple[io.BytesIO, str, str]]:
    return {"sid": SID, "testId": TEST_ID, "round": str(ROUND_NO), "image": (io.BytesIO(FULL_SHEET.read_bytes()), "person_03_full_sheet.jpg", "image/jpeg")}


def required_inputs_ready() -> bool:
    return FULL_SHEET.is_file() and count_files(CROP_DIR, "q*.png") == 20 and count_files(CONTACT_DIR, "*.png") == 4 and CANONICAL_RECOGNIZED.is_file() and CANONICAL_CACHE.is_file()


def runtime_dirs() -> set[Path]:
    return {path for path in RUNTIME_ROOT.iterdir() if path.is_dir()} if RUNTIME_ROOT.exists() else set()


def newest_created_dir(before: set[Path]) -> Path:
    created = runtime_dirs() - before
    if not created:
        raise Person03RunnerError("route did not create a Phase 2C runtime directory")
    return max(created, key=lambda path: path.stat().st_mtime_ns)


def canonical_hashes() -> JsonObject:
    return {"recognized": file_sha256(CANONICAL_RECOGNIZED), "cache": file_sha256(CANONICAL_CACHE)}


def count_files(root: Path, pattern: str) -> int:
    return len(tuple(root.glob(pattern))) if root.is_dir() else 0


def route_artifact_crop_count(case_dir: Path) -> int:
    result = require_object(read_json(case_dir / "pipeline_result.json"), "pipeline_result")
    return count_files(Path(text_value(result.get("crop_dir"))), "q*.png")


def read_json(path: Path) -> JsonObject:
    if not path.is_file():
        raise Person03RunnerError(f"missing JSON file: {path}")
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), str(path))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise Person03RunnerError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise Person03RunnerError(f"{label} must be a JSON array")
    return value


def item_status(value: JsonValue) -> str:
    return text_value(require_object(value, "review item").get("status"))


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""


def int_value(value: JsonValue) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def forbidden_key_hits(value: JsonValue, path: str = "$") -> list[str]:
    if isinstance(value, dict):
        return [hit for key, child in value.items() for hit in ([f"{path}.{key}"] if key in FORBIDDEN_KEYS else []) + forbidden_key_hits(child, f"{path}.{key}")]
    if isinstance(value, list):
        return [hit for index, child in enumerate(value) for hit in forbidden_key_hits(child, f"{path}[{index}]")]
    return []


def path_leak_hits(value: JsonValue, path: str = "$") -> list[str]:
    if isinstance(value, dict):
        return [hit for key, child in value.items() for hit in path_leak_hits(child, f"{path}.{key}")]
    if isinstance(value, list):
        return [hit for index, child in enumerate(value) for hit in path_leak_hits(child, f"{path}[{index}]")]
    return [path] if isinstance(value, str) and any(token in value for token in PATH_TOKENS) else []
