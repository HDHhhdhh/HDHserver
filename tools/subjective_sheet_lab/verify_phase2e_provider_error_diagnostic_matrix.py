# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_phase2e_provider_error_diagnostic_matrix.py

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias
from unittest.mock import patch

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from tools.subjective_sheet_lab import phase2e_live_provider_runner as provider_runner  # noqa: E402
from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import (  # noqa: E402
    Phase2EFeatureFlags,
    Phase2ERequest,
    Phase2EResult,
    Phase2EStatus,
)
from tools.subjective_sheet_lab.phase2e_live_provider_runner import provider_error_result  # noqa: E402
from tools.subjective_sheet_lab.phase2e_provider_error_diagnostics import diagnostic_path  # noqa: E402
from tools.subjective_sheet_lab.verify_phase2e_provider_error_diagnostic import (  # noqa: E402
    FORBIDDEN_FIELDS,
    PATH_TOKENS,
    Phase2EProviderDiagnosticVerificationError,
    JsonObject,
    JsonValue,
    post_review_route,
    require_object,
    review_item_count,
    route_provider_error_env,
    with_env,
)

SensitiveToken: TypeAlias = str

SENSITIVE_TOKENS: Final[tuple[SensitiveToken, ...]] = (
    "GEMINI_API_KEY",
    ".env",
    "api_key",
    "x-goog-api-key",
    "AIza",
    "sk-",
    "contents",
    "inlineData",
    "inline_data",
    "base64",
    "raw_response",
    "response_body",
    "prompt_body",
    "system_instruction",
)
STUDENT_FORBIDDEN_KEYS: Final[frozenset[str]] = FORBIDDEN_FIELDS | frozenset(("provider_reason", "provider_response_shape"))
DIAGNOSTIC_FORBIDDEN_KEYS: Final[frozenset[str]] = FORBIDDEN_FIELDS | frozenset(("api_key", "raw_response", "response_body"))


@dataclass(frozen=True, slots=True)
class RouteDiagnosticCase:
    name: str
    reason: str
    provider_response_shape: JsonObject


def main() -> int:
    results = {case.name: verify_route_case(case) for case in route_cases()}
    summary: JsonObject = {
        "ok": True,
        "route_provider_error_matrix": results,
        "external_call_counts": {"submit_test": 0, "gemini_provider": 0, "old_ocr_route": 0},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def route_cases() -> tuple[RouteDiagnosticCase, ...]:
    return (
        RouteDiagnosticCase(
            name="provider_response_blocked",
            reason="provider_response_blocked",
            provider_response_shape={"candidate_count": 0, "prompt_block_reason": "SAFETY"},
        ),
        RouteDiagnosticCase(
            name="provider_response_missing_text",
            reason="provider_response_missing_text",
            provider_response_shape={"candidate_count": 1, "parts_count": 1, "text_part_count": 0, "finish_reason": "STOP"},
        ),
        RouteDiagnosticCase(
            name="provider_invalid_json",
            reason="provider_invalid_json",
            provider_response_shape={"parse_stage": "json", "text_part_count": 1},
        ),
    )


def verify_route_case(case: RouteDiagnosticCase) -> JsonObject:
    diagnostic_paths: list[Path] = []

    def simulated_provider_error(request: Phase2ERequest, flags: Phase2EFeatureFlags) -> Phase2EResult:
        recognized_path = provider_runner.phase2e_recognized_path(request)
        diagnostic_paths.append(diagnostic_path(recognized_path))
        return provider_error_result(request, flags, case.reason, recognized_path, True, False, case.provider_response_shape)

    client = create_app().test_client()
    with patch.object(provider_runner, "run_phase2e_live_provider", simulated_provider_error):
        payload = with_env(route_provider_error_env(), lambda: post_review_route(client))

    assert_route_payload_safe(payload)
    review_meta = require_object(payload.get("review_meta"), "review_meta")
    assert_provider_error_meta(review_meta)
    if len(diagnostic_paths) != 1:
        raise Phase2EProviderDiagnosticVerificationError("diagnostic path was not captured exactly once")
    diagnostic = read_diagnostic(diagnostic_paths[0], case)
    return {
        "http_status": 200,
        "provider_status": review_meta.get("provider_status"),
        "provider_call_count": review_meta.get("provider_call_count"),
        "review_payload_items": review_item_count(payload),
        "diagnostic_provider_reason": diagnostic.get("provider_reason"),
        "provider_response_shape_in_route_json": False,
        "forbidden_field_hits": 0,
        "path_leak_hits": 0,
        "sensitive_token_hits": 0,
    }


def assert_provider_error_meta(review_meta: JsonObject) -> None:
    if review_meta.get("provider_status") != Phase2EStatus.PROVIDER_ERROR.value:
        raise Phase2EProviderDiagnosticVerificationError(f"unexpected provider_status: {review_meta.get('provider_status')}")
    if review_meta.get("provider_call_count") != 1:
        raise Phase2EProviderDiagnosticVerificationError(f"unexpected provider_call_count: {review_meta.get('provider_call_count')}")


def assert_route_payload_safe(payload: JsonObject) -> None:
    assert_no_keys(payload, STUDENT_FORBIDDEN_KEYS, "student route JSON")
    assert_no_tokens(payload, PATH_TOKENS, "student route JSON path")
    assert_no_tokens(payload, SENSITIVE_TOKENS, "student route JSON sensitive token")


def read_diagnostic(path: Path, case: RouteDiagnosticCase) -> JsonObject:
    payload = require_object(json.loads(path.read_text(encoding="utf-8")), "provider_error_diagnostic")
    assert_no_keys(payload, DIAGNOSTIC_FORBIDDEN_KEYS, "provider diagnostic")
    assert_no_tokens(payload, PATH_TOKENS, "provider diagnostic path")
    assert_no_tokens(payload, SENSITIVE_TOKENS, "provider diagnostic sensitive token")
    if payload.get("provider_reason") != case.reason:
        raise Phase2EProviderDiagnosticVerificationError(f"unexpected provider_reason: {payload.get('provider_reason')}")
    shape = require_object(payload.get("provider_response_shape"), "provider_response_shape")
    assert_shape_contains(shape, case.provider_response_shape)
    return payload


def assert_shape_contains(actual: JsonObject, expected: JsonObject) -> None:
    for key, value in expected.items():
        if actual.get(key) != value:
            raise Phase2EProviderDiagnosticVerificationError(f"shape field {key}={actual.get(key)} != {value}")


def assert_no_keys(value: JsonValue, forbidden: frozenset[str], label: str) -> None:
    hits = forbidden_key_hits(value, forbidden)
    if hits:
        raise Phase2EProviderDiagnosticVerificationError(f"{label} leaked keys: {', '.join(hits)}")


def forbidden_key_hits(value: JsonValue, forbidden: frozenset[str], path: str = "$") -> list[str]:
    if isinstance(value, dict):
        hits: list[str] = []
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in forbidden:
                hits.append(child_path)
            hits.extend(forbidden_key_hits(child, forbidden, child_path))
        return hits
    if isinstance(value, list):
        hits = []
        for index, child in enumerate(value):
            hits.extend(forbidden_key_hits(child, forbidden, f"{path}[{index}]"))
        return hits
    return []


def assert_no_tokens(value: JsonValue, tokens: tuple[str, ...], label: str) -> None:
    text = json.dumps(value, ensure_ascii=False)
    hits = [token for token in tokens if token in text]
    if hits:
        raise Phase2EProviderDiagnosticVerificationError(f"{label} hits: {', '.join(hits)}")


if __name__ == "__main__":
    raise SystemExit(main())
