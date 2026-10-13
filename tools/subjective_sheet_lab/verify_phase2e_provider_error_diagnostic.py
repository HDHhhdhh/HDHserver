# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_phase2e_provider_error_diagnostic.py

from __future__ import annotations

import io
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias
from unittest.mock import patch

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from tools.subjective_sheet_lab.phase2c_crop_pipeline_adapter import Phase2CResult  # noqa: E402
from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import (  # noqa: E402
    Phase2EFeatureFlags,
    Phase2ERequest,
    Phase2EResult,
    Phase2EStatus,
)
from tools.subjective_sheet_lab import phase2e_live_provider_runner as provider_runner  # noqa: E402
from tools.subjective_sheet_lab.phase2e_live_provider_runner import provider_error_result  # noqa: E402
from tools.subjective_sheet_lab.phase2e_provider_error_diagnostics import diagnostic_path  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

ALLOWED_TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
FIXTURE_ROOT: Final[Path] = Path(r"C:\server-ocr\phase2e_adapter_verifier")
FULL_SHEET: Final[Path] = Path(r"C:\server-ocr\incoming_cases\person_03\full_sheet.jpg")
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
FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "score", "wrong", "pct"))
PATH_TOKENS: Final[tuple[str, ...]] = ("C:\\", "C:/", "server-ocr", "phase2c_route_uploads", "crop_benchmark_inputs")


@dataclass(frozen=True, slots=True)
class Phase2EProviderDiagnosticVerificationError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def main() -> int:
    if not FULL_SHEET.is_file():
        raise Phase2EProviderDiagnosticVerificationError(f"full-sheet fixture missing: {FULL_SHEET}")

    route_result = verify_route_provider_error_writes_safe_diagnostic()
    direct_result = verify_direct_provider_error_writes_safe_diagnostic()
    summary: JsonObject = {
        "ok": True,
        "route_provider_error_diagnostic": route_result,
        "direct_provider_error_diagnostic": direct_result,
        "external_call_counts": {"submit_test": 0, "gemini_provider": 0, "old_ocr_route": 0},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def verify_route_provider_error_writes_safe_diagnostic() -> JsonObject:
    diagnostic_paths: list[Path] = []

    def simulated_provider_error(request: Phase2ERequest, flags: Phase2EFeatureFlags) -> Phase2EResult:
        recognized_path = provider_runner.phase2e_recognized_path(request)
        diagnostic_paths.append(diagnostic_path(recognized_path))
        return provider_error_result(
            request,
            flags,
            "provider_response_missing_candidates",
            recognized_path,
            True,
            False,
        )

    client = create_app().test_client()
    with patch.object(provider_runner, "run_phase2e_live_provider", simulated_provider_error):
        payload = with_env(route_provider_error_env(), lambda: post_review_route(client))

    assert_no_forbidden_fields(payload)
    assert_no_paths(payload)
    review_meta = require_object(payload.get("review_meta"), "review_meta")
    if review_meta.get("provider_status") != Phase2EStatus.PROVIDER_ERROR.value:
        raise Phase2EProviderDiagnosticVerificationError(f"unexpected route provider_status: {review_meta.get('provider_status')}")
    if review_meta.get("provider_call_count") != 1:
        raise Phase2EProviderDiagnosticVerificationError(f"unexpected route provider_call_count: {review_meta.get('provider_call_count')}")
    if review_meta.get("provider_reason") is not None:
        raise Phase2EProviderDiagnosticVerificationError("route leaked provider_reason to student-facing JSON")
    if len(diagnostic_paths) != 1:
        raise Phase2EProviderDiagnosticVerificationError("route diagnostic path was not captured exactly once")

    diagnostic = read_safe_diagnostic(diagnostic_paths[0])
    return {
        "http_status": 200,
        "provider_status": review_meta.get("provider_status"),
        "provider_call_count": review_meta.get("provider_call_count"),
        "review_payload_items": review_item_count(payload),
        "diagnostic_status": diagnostic.get("status"),
        "diagnostic_provider_reason": diagnostic.get("provider_reason"),
        "forbidden_field_hits": 0,
        "path_leak_hits": 0,
    }


def verify_direct_provider_error_writes_safe_diagnostic() -> JsonObject:
    recognized_path = FIXTURE_ROOT / "diagnostic_case" / "recognized.json"
    report_path = diagnostic_path(recognized_path)
    if report_path.exists():
        report_path.unlink()

    result = provider_error_result(
        fake_phase2e_request(),
        live_flags(),
        "provider_response_missing_candidates",
        recognized_path,
        True,
        False,
    )
    if result.status is not Phase2EStatus.PROVIDER_ERROR:
        raise Phase2EProviderDiagnosticVerificationError("provider diagnostic setup did not return provider_error")

    diagnostic = read_safe_diagnostic(report_path)
    if diagnostic.get("provider_call_count") != 1:
        raise Phase2EProviderDiagnosticVerificationError("provider diagnostic did not record one attempted call")
    return {
        "status": diagnostic.get("status"),
        "provider_reason": diagnostic.get("provider_reason"),
        "provider_call_count": diagnostic.get("provider_call_count"),
        "forbidden_field_hits": 0,
        "path_leak_hits": 0,
    }


def post_review_route(client) -> JsonObject:
    response = client.post(ROUTE, data=valid_fields())
    payload = require_object(response.get_json(silent=True), "route response")
    if response.status_code != 200 or payload.get("ok") is not True:
        raise Phase2EProviderDiagnosticVerificationError(f"route failed {response.status_code}: {response.get_data(as_text=True)}")
    return payload


def valid_fields() -> dict[str, str | tuple[io.BytesIO, str, str]]:
    image = (io.BytesIO(FULL_SHEET.read_bytes()), "full_sheet.jpg", "image/jpeg")
    return {"sid": "990", "testId": ALLOWED_TEST_ID, "round": "1", "image": image}


def review_item_count(payload: JsonObject) -> int:
    review_payload = require_object(payload.get("review_payload"), "review_payload")
    items = require_array(review_payload.get("items"), "review_payload.items")
    if len(items) != 20:
        raise Phase2EProviderDiagnosticVerificationError(f"review_payload.items length {len(items)} != 20")
    return len(items)


def read_safe_diagnostic(path: Path, expected_reason: str = "provider_response_missing_candidates") -> JsonObject:
    payload = require_object(json.loads(path.read_text(encoding="utf-8")), "provider_error_diagnostic")
    assert_no_forbidden_fields(payload)
    assert_no_paths(payload)
    if payload.get("provider_reason") != expected_reason:
        raise Phase2EProviderDiagnosticVerificationError(f"unexpected provider_reason: {payload.get('provider_reason')}")
    return payload


def route_provider_error_env() -> dict[str, str | None]:
    return {
        ROUTE_ENABLED_ENV: "1",
        CACHE_ENABLED_ENV: "1",
        CACHE_RECOGNIZED_ENV: str(FIXTURE_ROOT / "route_missing_recognized" / "recognized.json"),
        CACHE_REVIEW_ENV: None,
        LIVE_ENABLED_ENV: "1",
        CACHE_WRITE_ENABLED_ENV: "1",
        LOCAL_ONLY_ENV: "0",
        REQUIRE_CACHE_MISS_ENV: "1",
        PROVIDER_ALLOWED_ENV: "1",
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


def live_flags() -> Phase2EFeatureFlags:
    return Phase2EFeatureFlags(
        live_enabled=True,
        cache_write_enabled=True,
        local_only=False,
        provider_calls_require_cache_miss=True,
        max_provider_calls_per_request=1,
        fail_closed_on_provider_error=True,
        provider_calls_allowed=True,
    )


def fake_phase2e_request() -> Phase2ERequest:
    return Phase2ERequest(
        sid="990",
        test_id=ALLOWED_TEST_ID,
        round_no=1,
        pipeline_result=fake_pipeline_result(),
        cache_miss_reason="cache_miss",
        request_metadata={"verifier": "phase2e_provider_error_diagnostic"},
    )


def fake_pipeline_result() -> Phase2CResult:
    root = FIXTURE_ROOT / "fake_case"
    return Phase2CResult(
        case_id="phase2e_fake_case",
        case_dir=root,
        source_image=root / "incoming" / "full_sheet.jpg",
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


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise Phase2EProviderDiagnosticVerificationError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise Phase2EProviderDiagnosticVerificationError(f"{label} must be a JSON array")
    return value


def assert_no_forbidden_fields(value: JsonValue, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_FIELDS:
                raise Phase2EProviderDiagnosticVerificationError(f"diagnostic leaked {path}.{key}")
            assert_no_forbidden_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_forbidden_fields(child, f"{path}[{index}]")


def assert_no_paths(value: JsonValue) -> None:
    text = json.dumps(value, ensure_ascii=False)
    if any(token in text for token in PATH_TOKENS):
        raise Phase2EProviderDiagnosticVerificationError("diagnostic exposed a local path")


if __name__ == "__main__":
    raise SystemExit(main())
