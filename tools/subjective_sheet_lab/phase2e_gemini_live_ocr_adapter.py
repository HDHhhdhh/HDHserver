from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, TypeAlias

from tools.subjective_sheet_lab.phase2c_crop_pipeline_adapter import Phase2CResult

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

LIVE_ENABLED_ENV: Final[str] = "OCR_PHASE2E_GEMINI_LIVE_ENABLED"
CACHE_WRITE_ENABLED_ENV: Final[str] = "OCR_PHASE2E_CACHE_WRITE_ENABLED"
LOCAL_ONLY_ENV: Final[str] = "OCR_PHASE2E_LOCAL_ONLY"
REQUIRE_CACHE_MISS_ENV: Final[str] = "OCR_PHASE2E_PROVIDER_CALLS_REQUIRE_CACHE_MISS"
MAX_PROVIDER_CALLS_ENV: Final[str] = "OCR_PHASE2E_MAX_PROVIDER_CALLS_PER_REQUEST"
FAIL_CLOSED_ENV: Final[str] = "OCR_PHASE2E_FAIL_CLOSED_ON_PROVIDER_ERROR"
PROVIDER_CALLS_ALLOWED_ENV: Final[str] = "OCR_PHASE2E_PROVIDER_CALLS_ALLOWED"
UNIT_TEST_ID_RE: Final[re.Pattern[str]] = re.compile(r"^t_unit_[a-z0-9_]+_r[123]$", re.IGNORECASE)
QUESTION_COUNT: Final[int] = 20
DEFAULT_MAX_PROVIDER_CALLS: Final[int] = 1
TRUTHY_VALUES: Final[frozenset[str]] = frozenset(("1", "true", "yes", "on"))
FALSY_VALUES: Final[frozenset[str]] = frozenset(("0", "false", "no", "off"))


class Phase2EStatus(StrEnum):
    PROVIDER_DISABLED = "provider_disabled"
    LIVE_CALL_NOT_AUTHORIZED = "live_call_not_authorized"
    PROVIDER_BUDGET_EXHAUSTED = "provider_budget_exhausted"
    LIVE_CALL_NOT_IMPLEMENTED = "live_call_not_implemented"
    LIVE_CALL_SUCCEEDED = "live_call_succeeded"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True, slots=True)
class Phase2EFeatureFlags:
    live_enabled: bool
    cache_write_enabled: bool
    local_only: bool
    provider_calls_require_cache_miss: bool
    max_provider_calls_per_request: int
    fail_closed_on_provider_error: bool
    provider_calls_allowed: bool


@dataclass(frozen=True, slots=True)
class Phase2ERequest:
    sid: str
    test_id: str
    round_no: int
    pipeline_result: Phase2CResult
    cache_miss_reason: str
    request_metadata: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Phase2EResult:
    status: Phase2EStatus
    reason: str
    provider_call_attempted: bool
    provider_call_count: int
    max_provider_calls: int
    cache_write_enabled: bool
    contact_sheet_count: int
    crop_count: int
    review_payload: JsonObject | None = None
    recognized_path: Path | None = None
    quota_or_rate_limited: bool = False


def phase2e_flags_from_env(environ: Mapping[str, str] | None = None) -> Phase2EFeatureFlags:
    source = os.environ if environ is None else environ
    return Phase2EFeatureFlags(
        live_enabled=env_bool(source, LIVE_ENABLED_ENV, False),
        cache_write_enabled=env_bool(source, CACHE_WRITE_ENABLED_ENV, False),
        local_only=env_bool(source, LOCAL_ONLY_ENV, True),
        provider_calls_require_cache_miss=env_bool(source, REQUIRE_CACHE_MISS_ENV, True),
        max_provider_calls_per_request=env_int(source, MAX_PROVIDER_CALLS_ENV, DEFAULT_MAX_PROVIDER_CALLS),
        fail_closed_on_provider_error=env_bool(source, FAIL_CLOSED_ENV, True),
        provider_calls_allowed=env_bool(source, PROVIDER_CALLS_ALLOWED_ENV, False),
    )


def prepare_phase2e_live_ocr(request: Phase2ERequest, flags: Phase2EFeatureFlags | None = None) -> Phase2EResult:
    active_flags = phase2e_flags_from_env() if flags is None else flags
    gate_result = assert_phase2e_provider_gate_open(request, active_flags)
    if gate_result is not None:
        return gate_result

    from tools.subjective_sheet_lab.phase2e_live_provider_runner import run_phase2e_live_provider

    return run_phase2e_live_provider(request, active_flags)


def assert_phase2e_provider_gate_open(request: Phase2ERequest, flags: Phase2EFeatureFlags) -> Phase2EResult | None:
    if not phase2e_live_allowed(request):
        return phase2e_result(Phase2EStatus.LIVE_CALL_NOT_AUTHORIZED, "not_allowlisted", request, flags)
    if not flags.live_enabled:
        return phase2e_result(Phase2EStatus.PROVIDER_DISABLED, "live_flag_disabled", request, flags)
    if not flags.provider_calls_require_cache_miss:
        return phase2e_result(Phase2EStatus.LIVE_CALL_NOT_AUTHORIZED, "cache_miss_gate_not_enforced", request, flags)
    if flags.provider_calls_require_cache_miss and not request.cache_miss_reason.strip():
        return phase2e_result(Phase2EStatus.LIVE_CALL_NOT_AUTHORIZED, "cache_miss_required", request, flags)
    if flags.local_only:
        return phase2e_result(Phase2EStatus.LIVE_CALL_NOT_AUTHORIZED, "local_only_enabled", request, flags)
    if not flags.provider_calls_allowed:
        return phase2e_result(Phase2EStatus.LIVE_CALL_NOT_AUTHORIZED, "provider_calls_not_authorized", request, flags)
    if not flags.cache_write_enabled:
        return phase2e_result(Phase2EStatus.LIVE_CALL_NOT_AUTHORIZED, "cache_write_disabled", request, flags)
    if flags.max_provider_calls_per_request < 1:
        return phase2e_result(Phase2EStatus.PROVIDER_BUDGET_EXHAUSTED, "provider_call_budget_exhausted", request, flags)
    if flags.max_provider_calls_per_request > DEFAULT_MAX_PROVIDER_CALLS:
        return phase2e_result(Phase2EStatus.LIVE_CALL_NOT_AUTHORIZED, "provider_call_budget_above_phase2e_limit", request, flags)
    if not phase2e_provider_gate_is_open(flags):
        raise RuntimeError("Phase 2E provider gate assertion failed")
    return None


def phase2e_live_allowed(request: Phase2ERequest) -> bool:
    return request.round_no in {1, 2, 3} and UNIT_TEST_ID_RE.match(request.test_id) is not None


def phase2e_provider_gate_is_open(flags: Phase2EFeatureFlags) -> bool:
    return (
        flags.live_enabled
        and flags.cache_write_enabled
        and not flags.local_only
        and flags.provider_calls_require_cache_miss
        and flags.provider_calls_allowed
        and flags.max_provider_calls_per_request == DEFAULT_MAX_PROVIDER_CALLS
    )


def phase2e_result(status: Phase2EStatus, reason: str, request: Phase2ERequest, flags: Phase2EFeatureFlags) -> Phase2EResult:
    return Phase2EResult(
        status=status,
        reason=reason,
        provider_call_attempted=False,
        provider_call_count=0,
        max_provider_calls=flags.max_provider_calls_per_request,
        cache_write_enabled=flags.cache_write_enabled,
        contact_sheet_count=request.pipeline_result.contact_sheet_count,
        crop_count=request.pipeline_result.crop_count,
    )


def env_bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name)
    if raw is None:
        return default
    text = raw.strip().lower()
    if not text:
        return default
    if text in TRUTHY_VALUES:
        return True
    if text in FALSY_VALUES:
        return False
    return default


def env_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        parsed = int(raw.strip())
    except ValueError:
        return default
    return max(parsed, 0)
