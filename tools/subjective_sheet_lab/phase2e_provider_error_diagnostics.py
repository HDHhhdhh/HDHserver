from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import (
    JsonObject,
    Phase2EFeatureFlags,
    Phase2ERequest,
    Phase2EStatus,
)

PROVIDER_ERROR_DIAGNOSTIC_FILE_NAME: Final[str] = "provider_error_diagnostic.json"


@dataclass(frozen=True, slots=True)
class ProviderErrorDiagnostic:
    request: Phase2ERequest
    flags: Phase2EFeatureFlags
    reason: str
    recognized_path: Path
    attempted: bool
    quota_or_rate_limited: bool
    provider_response_shape: JsonObject | None = None


def try_write_provider_error_diagnostic(diagnostic: ProviderErrorDiagnostic) -> bool:
    try:
        write_provider_error_diagnostic(diagnostic)
    except OSError:
        return False
    return True


def write_provider_error_diagnostic(diagnostic: ProviderErrorDiagnostic) -> None:
    diagnostic.recognized_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path(diagnostic.recognized_path).write_text(
        json.dumps(provider_error_payload(diagnostic), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def provider_error_payload(diagnostic: ProviderErrorDiagnostic) -> JsonObject:
    payload: JsonObject = {
        "status": Phase2EStatus.PROVIDER_ERROR.value,
        "provider_reason": safe_provider_reason(diagnostic.reason),
        "provider_call_attempted": diagnostic.attempted,
        "provider_call_count": 1 if diagnostic.attempted else 0,
        "max_provider_calls": diagnostic.flags.max_provider_calls_per_request,
        "quota_or_rate_limited": diagnostic.quota_or_rate_limited,
        "cache_write_enabled": diagnostic.flags.cache_write_enabled,
        "test_id": diagnostic.request.test_id,
        "round": diagnostic.request.round_no,
        "case_id": safe_case_id(diagnostic.request.pipeline_result.case_id),
        "crop_count": diagnostic.request.pipeline_result.crop_count,
        "contact_sheet_count": diagnostic.request.pipeline_result.contact_sheet_count,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if diagnostic.provider_response_shape is not None:
        payload["provider_response_shape"] = safe_provider_response_shape(diagnostic.provider_response_shape)
    return payload


def diagnostic_path(recognized_path: Path) -> Path:
    return recognized_path.parent / PROVIDER_ERROR_DIAGNOSTIC_FILE_NAME


def safe_provider_reason(reason: str) -> str:
    cleaned = "".join(char for char in reason.strip() if char.isalnum() or char in "_-")
    return cleaned[:80] or "provider_error"


def safe_provider_response_shape(shape: JsonObject) -> JsonObject:
    safe: JsonObject = {}
    for key, value in shape.items():
        safe_key = safe_provider_reason(key)
        if isinstance(value, bool):
            safe[safe_key] = value
        elif isinstance(value, int) and not isinstance(value, bool):
            safe[safe_key] = value
        elif isinstance(value, str):
            safe[safe_key] = safe_provider_reason(value)
    return safe


def safe_case_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
    return cleaned[:120] or "case"
