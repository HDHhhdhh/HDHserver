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

from tools.subjective_sheet_lab.phase2c_crop_pipeline_adapter import Phase2CResult  # noqa: E402
from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import Phase2ERequest  # noqa: E402
from tools.subjective_sheet_lab.phase2e_live_provider_runner import phase2e_recognized_path  # noqa: E402
from tools.subjective_sheet_lab.phase2e_stable_cache import PHASE2E_CACHE_ROOT_ENV  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

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
DEFAULT_CACHE: Final[Path] = Path(r"C:\server-ocr\gemini_outputs\daesu_jisu1_lv3_r1_photo01_same_contact\recognized.json")
RUNTIME_ROOT: Final[Path] = Path(r"C:\server-ocr\phase2c_route_uploads")
FIXTURE_ROOT: Final[Path] = Path(r"C:\server-ocr\phase2e_adapter_verifier")
FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "score", "wrong", "pct")
)
PHASE2E_ENV_KEYS: Final[tuple[str, ...]] = (
    LIVE_ENABLED_ENV,
    CACHE_WRITE_ENABLED_ENV,
    LOCAL_ONLY_ENV,
    REQUIRE_CACHE_MISS_ENV,
    PROVIDER_ALLOWED_ENV,
    MAX_CALLS_ENV,
    FAIL_CLOSED_ENV,
)


class Phase2EVerificationError(Exception):
    pass


def route_env(recognized_path: Path, *, phase2e_live: bool, local_only: bool = False) -> dict[str, str | None]:
    return {
        ROUTE_ENABLED_ENV: "1",
        CACHE_ENABLED_ENV: "1",
        CACHE_RECOGNIZED_ENV: str(recognized_path),
        CACHE_REVIEW_ENV: None,
        LIVE_ENABLED_ENV: "1" if phase2e_live else None,
        CACHE_WRITE_ENABLED_ENV: None,
        LOCAL_ONLY_ENV: "1" if local_only else "0",
        REQUIRE_CACHE_MISS_ENV: "1",
        PROVIDER_ALLOWED_ENV: None,
        MAX_CALLS_ENV: "1",
        FAIL_CLOSED_ENV: "1",
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


def verify_success(client, expected_source: str, expected_statuses: dict[str, int] | None = None) -> JsonObject:
    before = runtime_dirs()
    response = client.post(ROUTE, data=valid_fields())
    payload = require_object(response.get_json(silent=True), "success response")
    if response.status_code != 200 or payload.get("ok") is not True:
        raise Phase2EVerificationError(f"success case failed {response.status_code}: {response.get_data(as_text=True)}")
    assert_no_forbidden_fields(payload)
    assert_no_paths(payload)
    review_payload = require_object(payload.get("review_payload"), "review_payload")
    if review_payload.get("source") != expected_source:
        raise Phase2EVerificationError(f"source {review_payload.get('source')} != {expected_source}")
    items = require_array(review_payload.get("items"), "review_payload.items")
    if len(items) != 20:
        raise Phase2EVerificationError("review payload must contain 20 items")
    if sorted(item_question_no(item, index) for index, item in enumerate(items, start=1)) != list(range(1, 21)):
        raise Phase2EVerificationError("review payload must contain questions 1..20")
    statuses = count_statuses(items)
    if expected_statuses is not None and statuses != expected_statuses:
        raise Phase2EVerificationError(f"statuses {statuses} != {expected_statuses}")
    case_dir = newest_created_dir(before)
    crop_count = len(tuple(case_dir.rglob("q*.png")))
    if crop_count < 20:
        raise Phase2EVerificationError("Phase 2C crop pipeline did not run")
    return {"source": str(review_payload.get("source")), "items": len(items), "statuses": statuses, "crop_pipeline_ran": True}


def provider_items(recognized: dict[int, str]) -> list[JsonObject]:
    return [{"question": question, "recognized": answer} for question, answer in sorted(recognized.items())]


def verify_stable_same_image_recognized_path() -> JsonObject:
    source_root = FIXTURE_ROOT / "stable_path_inputs"
    source_root.mkdir(parents=True, exist_ok=True)
    same_image = source_root / "same_omr.jpg"
    different_image = source_root / "different_omr.jpg"
    same_image.write_bytes(b"same-omr-image-bytes")
    different_image.write_bytes(b"different-omr-image-bytes")
    return with_env(
        {PHASE2E_CACHE_ROOT_ENV: str(FIXTURE_ROOT / "stable_path_cache")},
        lambda: assert_stable_same_image_recognized_path(same_image, different_image),
    )


def assert_stable_same_image_recognized_path(same_image: Path, different_image: Path) -> JsonObject:
    first = phase2e_recognized_path(fake_phase2e_request(fake_pipeline_result("phase2c_first_nonce", same_image)))
    second = phase2e_recognized_path(fake_phase2e_request(fake_pipeline_result("phase2c_second_nonce", same_image)))
    different = phase2e_recognized_path(fake_phase2e_request(fake_pipeline_result("phase2c_third_nonce", different_image)))
    if first != second:
        raise Phase2EVerificationError("same OMR image produced different recognized cache paths")
    if first == different:
        raise Phase2EVerificationError("different OMR images produced the same recognized cache path")
    if not first.parent.name.startswith("stable_"):
        raise Phase2EVerificationError("recognized cache path is not using the stable image cache namespace")
    return {"same_image_same_path": True, "different_image_different_path": True, "cache_parent": first.parent.name}


def fake_phase2e_request(pipeline_result: Phase2CResult | None = None) -> Phase2ERequest:
    return Phase2ERequest(
        sid="990",
        test_id=ALLOWED_TEST_ID,
        round_no=1,
        pipeline_result=fake_pipeline_result() if pipeline_result is None else pipeline_result,
        cache_miss_reason="cache_miss",
        request_metadata={"verifier": "phase2e_live_payload"},
    )


def assert_item_status(items: list[JsonValue], question_no: int, status: str, final_answer: str | None) -> None:
    item = item_for_question(items, question_no)
    if item.get("status") != status:
        raise Phase2EVerificationError(f"q{question_no:03d} status {item.get('status')} != {status}")
    if item.get("final_answer") != final_answer:
        raise Phase2EVerificationError(f"q{question_no:03d} final_answer {item.get('final_answer')} != {final_answer}")


def assert_item_warning(items: list[JsonValue], question_no: int, warning: str) -> None:
    item = item_for_question(items, question_no)
    warnings = require_array(item.get("warnings"), f"q{question_no:03d}.warnings")
    if warning not in warnings:
        raise Phase2EVerificationError(f"q{question_no:03d} warnings {warnings} missing {warning}")


def item_for_question(items: list[JsonValue], question_no: int) -> JsonObject:
    for index, value in enumerate(items, start=1):
        item = require_object(value, f"item {index}")
        if item.get("question_no") == question_no:
            return item
    raise Phase2EVerificationError(f"q{question_no:03d} missing")


def write_cache_fixtures() -> dict[str, Path]:
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    missing = FIXTURE_ROOT / "missing_recognized.json"
    return {"missing": missing}


def valid_fields() -> dict[str, str | tuple[io.BytesIO, str, str]]:
    image = (io.BytesIO(FULL_SHEET.read_bytes()), "full_sheet.jpg", "image/jpeg")
    return {"sid": "990", "testId": ALLOWED_TEST_ID, "round": "1", "image": image}


def fake_pipeline_result(case_id: str = "phase2e_fake_case", source_image: Path | None = None) -> Phase2CResult:
    root = Path(r"C:\server-ocr\phase2e_adapter_verifier\fake_case")
    source = root / "incoming" / "full_sheet.jpg" if source_image is None else source_image
    return Phase2CResult(
        case_id=case_id,
        case_dir=root,
        source_image=source,
        crop_root=root / "crop_benchmark_inputs" / "phase2e_fake_case",
        crop_dir=root / "crop_benchmark_inputs" / "phase2e_fake_case" / "crops",
        review_asset_root=root / "review_assets",
        asset_manifest=root / "review_assets" / "asset_manifest.json",
        crop_count=20,
        contact_sheet_count=4,
        debug_sheet_count=0,
        contact_sheets=tuple(root / "review_assets" / "contact_sheets" / f"group_{index}.png" for index in range(1, 5)),
        debug_sheets=(),
        asset_verification=root / "review_assets" / "asset_verification.json",
        crop_quality=root / "crop_benchmark_inputs" / "phase2e_fake_case" / "crop_quality.json",
        answer_box_source="detected_grid_repaired",
    )


def runtime_dirs() -> set[Path]:
    return {path for path in RUNTIME_ROOT.iterdir() if path.is_dir()} if RUNTIME_ROOT.exists() else set()


def newest_created_dir(before: set[Path]) -> Path:
    created = runtime_dirs() - before
    if not created:
        raise Phase2EVerificationError("route did not create a Phase 2C runtime directory")
    return max(created, key=lambda path: path.stat().st_mtime_ns)


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise Phase2EVerificationError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise Phase2EVerificationError(f"{label} must be a JSON array")
    return value


def item_question_no(value: JsonValue, index: int) -> int:
    item = require_object(value, f"item {index}")
    question_no = item.get("question_no")
    if not isinstance(question_no, int) or isinstance(question_no, bool):
        raise Phase2EVerificationError(f"item {index} question_no must be int")
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
                raise Phase2EVerificationError(f"student-facing payload leaked {path}.{key}")
            assert_no_forbidden_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_forbidden_fields(child, f"{path}[{index}]")


def assert_no_paths(value: JsonValue) -> None:
    text = json.dumps(value, ensure_ascii=False)
    path_tokens = ("C:\\", "C:/", "server-ocr", "phase2c_route_uploads", "crop_benchmark_inputs")
    if any(token in text for token in path_tokens):
        raise Phase2EVerificationError("student-facing payload exposed a local path")
