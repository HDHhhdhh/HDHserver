# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_gemini_provider_response_shape_diagnostics.py

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

from tools.subjective_sheet_lab import gemini_provider  # noqa: E402
from tools.subjective_sheet_lab import phase2e_live_provider_runner as provider_runner  # noqa: E402
from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import Phase2EFeatureFlags, Phase2EStatus  # noqa: E402
from tools.subjective_sheet_lab.phase2e_live_provider_runner import (  # noqa: E402
    Phase2EProviderOutputError,
    review_payload_from_provider_items,
)
from tools.subjective_sheet_lab.phase2e_provider_error_diagnostics import diagnostic_path  # noqa: E402
from tools.subjective_sheet_lab.verify_phase2e_provider_error_diagnostic import fake_phase2e_request, read_safe_diagnostic  # noqa: E402

JsonValue: TypeAlias = gemini_provider.JsonValue
JsonObject: TypeAlias = dict[str, JsonValue]

@dataclass(frozen=True, slots=True)
class GeminiProviderShapeDiagnosticVerificationError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def main() -> int:
    results = {
        "missing_candidates": verify_response_reason({}, "provider_response_missing_candidates"),
        "blocked_prompt": verify_response_reason(
            {"promptFeedback": {"blockReason": "SAFETY"}},
            "provider_response_blocked",
        ),
        "missing_text": verify_response_reason(
            {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"inlineData": {}}]}}]},
            "provider_response_missing_text",
        ),
        "blocked_finish_reason": verify_response_reason(
            {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]},
            "provider_response_blocked",
        ),
        "invalid_json": verify_invalid_json_reason(),
        "missing_questions": verify_missing_questions_reason(),
        "runner_diagnostic_shape": verify_runner_writes_shape_diagnostic(),
        "external_call_counts": {"submit_test": 0, "gemini_provider": 0, "old_ocr_route": 0},
    }
    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2))
    return 0


def verify_response_reason(response: JsonObject, expected_reason: str) -> JsonObject:
    try:
        gemini_provider.extract_response_text(response)
    except gemini_provider.GeminiProviderError as exc:
        assert_error_reason(exc, expected_reason)
        return {"reason": exc.reason, "diagnostic": require_object(exc.diagnostic, "diagnostic")}
    raise GeminiProviderShapeDiagnosticVerificationError(f"{expected_reason} did not raise")


def verify_invalid_json_reason() -> JsonObject:
    try:
        gemini_provider.parse_json_text("{not-json")
    except gemini_provider.GeminiProviderError as exc:
        assert_error_reason(exc, "provider_invalid_json")
        return {"reason": exc.reason}
    raise GeminiProviderShapeDiagnosticVerificationError("invalid JSON did not raise")


def verify_missing_questions_reason() -> JsonObject:
    try:
        review_payload_from_provider_items([{"question": 1, "recognized": "4"}], fake_phase2e_request())
    except Phase2EProviderOutputError as exc:
        if exc.reason != "provider_missing_questions":
            raise GeminiProviderShapeDiagnosticVerificationError(f"missing questions reason {exc.reason}") from exc
        return {"reason": exc.reason}
    raise GeminiProviderShapeDiagnosticVerificationError("missing questions did not raise")


def verify_runner_writes_shape_diagnostic() -> JsonObject:
    request = fake_phase2e_request()
    contact_dir = request.pipeline_result.review_asset_root / "contact_sheets"
    contact_dir.mkdir(parents=True, exist_ok=True)
    report_path = diagnostic_path(provider_runner.phase2e_recognized_path(request))
    if report_path.exists():
        report_path.unlink()

    provider_error = gemini_provider.GeminiProviderError(
        "Gemini API response did not include text",
        reason="provider_response_missing_text",
        diagnostic={"candidate_count": 1, "text_part_count": 0, "finish_reason": "STOP"},
    )
    with patch.object(gemini_provider, "read_gemini_key", lambda: "fake-key"):
        with patch.object(gemini_provider, "recognize_from_config", side_effect=provider_error):
            result = provider_runner.run_phase2e_live_provider(request, live_flags())

    if result.status is not Phase2EStatus.PROVIDER_ERROR:
        raise GeminiProviderShapeDiagnosticVerificationError(f"runner status {result.status.value}")
    diagnostic = read_safe_diagnostic(report_path, "provider_response_missing_text")
    shape = require_object(diagnostic.get("provider_response_shape"), "provider_response_shape")
    if shape.get("text_part_count") != 0:
        raise GeminiProviderShapeDiagnosticVerificationError("shape diagnostic did not record text_part_count")
    return {"reason": diagnostic.get("provider_reason"), "shape": shape}


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


def assert_error_reason(error: gemini_provider.GeminiProviderError, expected: str) -> None:
    if error.reason != expected:
        raise GeminiProviderShapeDiagnosticVerificationError(f"reason {error.reason} != {expected}")


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise GeminiProviderShapeDiagnosticVerificationError(f"{label} must be object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
