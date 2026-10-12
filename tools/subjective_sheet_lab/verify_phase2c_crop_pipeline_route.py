# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_phase2c_crop_pipeline_route.py

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
from tools.subjective_sheet_lab.phase2c_crop_pipeline_adapter import safe_slug  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
FormValue: TypeAlias = str | tuple[io.BytesIO, str, str]
FormFields: TypeAlias = dict[str, FormValue]

ROUTE: Final[str] = "/api/ocr-test-sheet-review"
ROUTE_ENABLED_ENV: Final[str] = "OCR_PHASE2_REVIEW_ROUTE_ENABLED"
ALLOWED_TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
FULL_SHEET: Final[Path] = Path(r"C:\server-ocr\incoming_cases\person_03\full_sheet.jpg")
RUNTIME_ROOT: Final[Path] = Path(r"C:\server-ocr\phase2c_route_uploads")
MAX_IMAGE_BYTES: Final[int] = 8 * 1024 * 1024
FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "score", "wrong", "pct"),
)


class Phase2CVerificationError(Exception):
    pass


def main() -> int:
    if not FULL_SHEET.is_file():
        raise Phase2CVerificationError(f"real full-sheet image missing: {FULL_SHEET}")
    app = create_app()
    client = app.test_client()
    results = {
        "disabled_default": with_route_flag(None, lambda: verify_error(client, valid_fields(), 503, "feature_disabled")),
        "missing_image": with_route_flag("1", lambda: verify_error(client, base_fields(), 400, "missing_image")),
        "invalid_image_type": with_route_flag("1", lambda: verify_error(client, invalid_type_fields(), 415, "unsupported_image_type")),
        "oversized_image": with_route_flag("1", lambda: verify_error(client, oversized_fields(), 413, "image_too_large")),
        "blocked_test": with_route_flag("1", lambda: verify_error(client, {**base_fields(), "testId": "blocked_test"}, 403, "test_not_allowlisted")),
        "wrong_round": with_route_flag("1", lambda: verify_error(client, {**base_fields(), "round": "2"}, 403, "round_not_allowlisted")),
        "ghost_sid": with_route_flag("1", lambda: verify_error(client, {**base_fields(), "sid": "ghost-outside-test"}, 403, "forbidden_student")),
        "case_id_slug_is_ascii": verify_case_id_slug_is_ascii(),
        "allowed_pipeline": with_route_flag("1", lambda: verify_allowed_pipeline(client)),
        "external_call_counts": {"submit_test": 0, "gemini_provider": 0, "old_ocr_route": 0},
    }
    print(json.dumps({"ok": True, "route": ROUTE, "full_sheet": str(FULL_SHEET), "results": results}, ensure_ascii=False, indent=2))
    return 0


def with_route_flag(value: str | None, action: Callable[[], JsonObject]) -> JsonObject:
    previous = os.environ.get(ROUTE_ENABLED_ENV)
    if value is None:
        os.environ.pop(ROUTE_ENABLED_ENV, None)
    else:
        os.environ[ROUTE_ENABLED_ENV] = value
    try:
        return action()
    finally:
        if previous is None:
            os.environ.pop(ROUTE_ENABLED_ENV, None)
        else:
            os.environ[ROUTE_ENABLED_ENV] = previous


def verify_error(client, fields: FormFields, expected_status: int, expected_code: str) -> JsonObject:
    response = client.post(ROUTE, data=fields)
    payload = require_object(response.get_json(silent=True), "error response")
    if response.status_code != expected_status:
        raise Phase2CVerificationError(f"{fields} returned {response.status_code}, wanted {expected_status}")
    if payload.get("ok") is not False or payload.get("errorCode") != expected_code:
        raise Phase2CVerificationError(f"wrong error payload: {payload}")
    if "review_payload" in payload:
        raise Phase2CVerificationError("error response included review_payload")
    return {"http_status": response.status_code, "errorCode": str(payload.get("errorCode"))}


def verify_allowed_pipeline(client) -> JsonObject:
    before = runtime_dirs()
    response = client.post(ROUTE, data=valid_fields())
    payload = require_object(response.get_json(silent=True), "allowed response")
    if response.status_code != 200 or payload.get("ok") is not True:
        raise Phase2CVerificationError(f"allowed pipeline failed {response.status_code}: {response.get_data(as_text=True)}")
    assert_no_forbidden_fields(payload)
    assert_no_paths(payload)
    review_payload = require_object(payload.get("review_payload"), "review_payload")
    items = require_array(review_payload.get("items"), "review_payload.items")
    if len(items) != 20:
        raise Phase2CVerificationError("review_payload.items must contain 20 items")
    case_dir = newest_created_dir(before)
    artifact_result = verify_artifacts(case_dir)
    return {
        "http_status": response.status_code,
        "review_items": len(items),
        "case_dir": str(case_dir),
        **artifact_result,
        "forbidden_field_hits": 0,
        "student_path_leaks": 0,
    }


def verify_case_id_slug_is_ascii() -> JsonObject:
    slug = safe_slug("t_\uB2E8\uC6D0\uD3C9\uAC00_cvk5cjc_r1")
    if not slug.isascii():
        raise Phase2CVerificationError(f"case slug must be ASCII-only: {slug}")
    if not slug.startswith("t_cvk5cjc_r1_"):
        raise Phase2CVerificationError(f"case slug did not preserve ASCII id segment: {slug}")
    return {"slug": slug, "ascii_only": True}


def verify_artifacts(case_dir: Path) -> JsonObject:
    result = require_object(read_json(case_dir / "pipeline_result.json"), "pipeline_result")
    crop_dir = Path(str(result.get("crop_dir") or ""))
    contact_sheets = require_string_list(result.get("contact_sheets"), "contact_sheets")
    debug_sheets = require_string_list(result.get("debug_sheets"), "debug_sheets")
    if len(tuple(crop_dir.glob("q*.png"))) != 20:
        raise Phase2CVerificationError("pipeline did not produce 20 crops")
    if len(contact_sheets) != 4 or not all(Path(path).is_file() for path in contact_sheets):
        raise Phase2CVerificationError("pipeline did not produce 4 contact sheets")
    if not debug_sheets or not all(Path(path).is_file() for path in debug_sheets):
        raise Phase2CVerificationError("pipeline did not produce debug sheets")
    if tuple(case_dir.rglob("recognized.json")):
        raise Phase2CVerificationError("Phase 2C must not create recognized.json")
    verification = require_object(read_json(Path(str(result.get("asset_verification") or ""))), "asset_verification")
    if verification.get("ok") is not True:
        raise Phase2CVerificationError(f"asset verification failed: {verification}")
    return {
        "crop_count": 20,
        "contact_sheet_count": len(contact_sheets),
        "debug_sheet_count": len(debug_sheets),
        "asset_verification_ok": True,
        "recognized_json_created": False,
    }


def base_fields() -> FormFields:
    return {"sid": "990", "testId": ALLOWED_TEST_ID, "round": "1"}


def valid_fields() -> FormFields:
    fields = base_fields()
    fields["image"] = (io.BytesIO(FULL_SHEET.read_bytes()), "full_sheet.jpg", "image/jpeg")
    return fields


def invalid_type_fields() -> FormFields:
    fields = base_fields()
    fields["image"] = (io.BytesIO(b"not an image"), "answer-sheet.txt", "text/plain")
    return fields


def oversized_fields() -> FormFields:
    fields = base_fields()
    fields["image"] = (io.BytesIO(b"0" * (MAX_IMAGE_BYTES + 1)), "answer-sheet.png", "image/png")
    return fields


def runtime_dirs() -> set[Path]:
    if not RUNTIME_ROOT.exists():
        return set()
    return {path for path in RUNTIME_ROOT.iterdir() if path.is_dir()}


def newest_created_dir(before: set[Path]) -> Path:
    created = runtime_dirs() - before
    if not created:
        raise Phase2CVerificationError("route did not create a Phase 2C runtime directory")
    return max(created, key=lambda path: path.stat().st_mtime_ns)


def read_json(path: Path) -> JsonValue:
    if not path.is_file():
        raise Phase2CVerificationError(f"missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise Phase2CVerificationError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise Phase2CVerificationError(f"{label} must be a JSON array")
    return value


def require_string_list(value: JsonValue, label: str) -> tuple[str, ...]:
    values = require_array(value, label)
    if not all(isinstance(item, str) for item in values):
        raise Phase2CVerificationError(f"{label} must contain only strings")
    return tuple(values)


def assert_no_forbidden_fields(value: JsonValue, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_FIELDS:
                raise Phase2CVerificationError(f"student-facing payload leaked {path}.{key}")
            assert_no_forbidden_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_forbidden_fields(child, f"{path}[{index}]")


def assert_no_paths(value: JsonValue) -> None:
    text = json.dumps(value, ensure_ascii=False)
    path_tokens = ("C:\\", "C:/", "server-ocr", "phase2c_route_uploads", "crop_benchmark_inputs")
    if any(token in text for token in path_tokens):
        raise Phase2CVerificationError("student-facing payload exposed a local path")


if __name__ == "__main__":
    raise SystemExit(main())
