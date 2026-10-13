from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Final, TypeAlias

from tools.subjective_sheet_lab.ocr_image_quality_gate import crop_quality_warnings
from tools.subjective_sheet_lab.ocr_payload_leak_policy import forbidden_paths, path_exposures
from tools.subjective_sheet_lab.ocr_overwritten_ambiguity_artifact import (
    OverwrittenAmbiguityArtifactError,
    load_overwritten_ambiguity_warnings,
)
from tools.subjective_sheet_lab.phase2c_crop_pipeline_adapter import Phase2CResult
from tools.subjective_sheet_lab.phase2e_stable_cache import (
    StableOcrCacheRequest,
    phase2e_cache_root,
    stable_recognized_path_or_none,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

PHASE2D_ENABLED_ENV: Final[str] = "OCR_PHASE2D_CACHED_REVIEW_ENABLED"
PHASE2D_REVIEW_PAYLOAD_ENV: Final[str] = "OCR_PHASE2D_CACHED_REVIEW_PAYLOAD"
PHASE2D_RECOGNIZED_ENV: Final[str] = "OCR_PHASE2D_RECOGNIZED_JSON"
UNIT_TEST_ID_RE: Final[re.Pattern[str]] = re.compile(r"^t_unit_[a-z0-9_]+_r[123]$", re.IGNORECASE)
QUESTION_COUNT: Final[int] = 20
TRUTHY_VALUES: Final[frozenset[str]] = frozenset(("1", "true", "yes", "on"))
VERSIONED_CACHE_SCHEMA: Final[str] = "student_self_review_v1"
LEGACY_RECOGNIZED_SCHEMA: Final[str] = "recognized_legacy_v0"
LEGACY_REVIEW_SCHEMA: Final[str] = "review_payload_legacy_v0"
NORMALIZED_SCHEMA: Final[str] = "cached_review_adapter_v1"
AUTO_CONFIRM_POLICY_VERSION: Final[str] = "gemini_flash_lite_policy_d_boundary_v1"
REVIEW_STATES: Final[frozenset[str]] = frozenset(
    ("auto_confirm", "review_recommended", "direct_input", "retake_required")
)
ADAPTER_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    (
        "answer_key",
        "expected",
        "canonical_answer",
        "accepted_answers",
        "grading",
        "is_correct",
        "score",
        "safe_auto_grade",
        "filesystem_path",
        "cache_path",
    )
)
AUTO_CONFIRM_EVIDENCE_KEYS: Final[frozenset[str]] = frozenset(
    (
        "policy_version",
        "truth_used_by_gate",
        "parser_pass",
        "historical_agreement",
        "model_confidence",
        "original_confidence",
        "enhanced_confidence",
        "original_candidate",
        "enhanced_candidate",
    )
)


@dataclass(frozen=True, slots=True)
class Phase2DRequest:
    sid: str
    test_id: str
    round_no: int
    pipeline_result: Phase2CResult
    form_id: str = "answer_sheet_20_v1"
    provider_model: str | None = None
    prompt_version: str | None = None
    preprocessing_version: str = "crop_contact_v1"


@dataclass(frozen=True, slots=True)
class Phase2DCacheResult:
    review_payload: JsonObject
    source_kind: str
    cache_path: Path
    cache_status: str


@dataclass(frozen=True, slots=True)
class Phase2DCacheUnavailable(Exception):
    reason: str
    detail: str = ""

    def __str__(self) -> str:
        return self.detail or self.reason


def load_phase2d_cached_review_payload(request: Phase2DRequest) -> Phase2DCacheResult:
    if not phase2d_cache_enabled():
        raise Phase2DCacheUnavailable("cache_disabled")
    if request.round_no not in {1, 2, 3} or UNIT_TEST_ID_RE.match(request.test_id) is None:
        raise Phase2DCacheUnavailable("cache_not_allowlisted")

    review_path = configured_path(PHASE2D_REVIEW_PAYLOAD_ENV)
    if review_path is not None:
        return load_review_payload_cache(review_path, request)

    recognized_path = configured_path(PHASE2D_RECOGNIZED_ENV)
    if recognized_path is None:
        stable_path = stable_recognized_cache_path(request)
        if stable_path is not None and stable_path.is_file():
            return load_recognized_cache(stable_path, request)
        raise Phase2DCacheUnavailable("cache_miss", "no cache matches the uploaded answer-sheet image")
    return load_recognized_cache(recognized_path, request)


def phase2d_cache_enabled() -> bool:
    return os.environ.get(PHASE2D_ENABLED_ENV, "").strip().lower() in TRUTHY_VALUES


def configured_path(env_name: str) -> Path | None:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return None
    return Path(raw)


def stable_recognized_cache_path(request: Phase2DRequest) -> Path | None:
    return stable_recognized_path_or_none(
        StableOcrCacheRequest(
            sid=request.sid,
            test_id=request.test_id,
            round_no=request.round_no,
            source_image=request.pipeline_result.source_image,
            cache_root=phase2e_cache_root(),
            form_id=request.form_id, provider_model=request.provider_model,
            prompt_version=request.prompt_version, preprocessing_version=request.preprocessing_version,
        )
    )


def load_review_payload_cache(path: Path, request: Phase2DRequest) -> Phase2DCacheResult:
    from tools.subjective_sheet_lab.ocr_review_payload_validator import validate_payload
    from tools.subjective_sheet_lab.ocr_review_schema import PayloadMode
    payload = require_object(read_json(path), "cached review payload")
    candidate = payload.get("review_payload") if isinstance(payload.get("review_payload"), dict) else payload
    candidate = require_object(candidate, "review_payload")
    require_current_cache_identity(candidate, request)
    validate_payload(candidate, PayloadMode.REVIEW, "cached_review")
    # Preserve identity and raw recognition. Never relabel another exam's result.
    return Phase2DCacheResult(review_payload=candidate, source_kind="cached_review_payload", cache_path=path, cache_status="hit")


def load_recognized_cache(path: Path, request: Phase2DRequest) -> Phase2DCacheResult:
    from tools.subjective_sheet_lab.gemini_provider import parse_item, GeminiProviderError
    from tools.subjective_sheet_lab.ocr_run_identity import RECOGNITION_SCHEMA, REVIEW_SCHEMA
    payload = require_object(read_json(path), "recognized cache")
    if set(payload)-{"schema","identity","items","diagnostics"}:
        raise Phase2DCacheUnavailable("cache_malformed","unknown recognition cache field")
    identity = require_current_cache_identity(payload, request)
    if payload.get("schema") != RECOGNITION_SCHEMA:
        raise Phase2DCacheUnavailable("cache_schema_unsupported")
    items = require_array(payload.get("items"), "recognized.items")
    by_question = {}
    for index,value in enumerate(items, start=1):
        try:
            item = parse_item(value)
        except GeminiProviderError as exc:
            raise Phase2DCacheUnavailable("cache_malformed", exc.reason) from exc
        if item.question in by_question:
            raise Phase2DCacheUnavailable("cache_malformed", "duplicate cached question")
        by_question[item.question] = {
            "question_no": item.question, "status": "review_required", "recognized": item.recognized,
            "candidates": list(item.candidates), "warnings": ["recognition_confirmation_required"],
            "uncertainty": item.uncertainty, "needs_review": item.needs_review,
            "final_answer": None, "source": None, "review_history": [],
            "identity_sha256": identity["identity_sha256"]}
    if sorted(by_question) != list(range(1,21)):
        raise Phase2DCacheUnavailable("cache_malformed", "exact 20-question coverage required")
    review = {"schema": REVIEW_SCHEMA, "identity": identity, "test_id": identity["test_id"],
              "round": identity["round"], "problem_count": 20,
              "items": [by_question[n] for n in range(1,21)]}
    if hasattr(request.pipeline_result,"crop_dir"):
        from tools.subjective_sheet_lab.ocr_review_run_payload import bind_review_payload
        review = bind_review_payload(review,request.pipeline_result,identity)
    return Phase2DCacheResult(review_payload=review, source_kind="cached_recognized_json", cache_path=path, cache_status="hit")


def read_json(path: Path) -> JsonValue:
    if not path.is_file():
        raise Phase2DCacheUnavailable("cache_miss", f"cache file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except JSONDecodeError as exc:
        raise Phase2DCacheUnavailable("cache_malformed", f"invalid JSON: {path}") from exc
    except OSError as exc:
        raise Phase2DCacheUnavailable("cache_unreadable", f"cannot read cache: {path}") from exc


def is_wrapped_route_response(payload: JsonObject) -> bool:
    return isinstance(payload.get("review_payload"), dict) and isinstance(payload.get("review_meta"), dict)


def rebuild_review_payload(payload: JsonObject, request: Phase2DRequest, include_pipeline_quality: bool = True) -> JsonObject:
    ensure_cache_safe(payload, "cached review payload")
    items = require_array(payload.get("items"), "review_payload.items")
    schema_version = cache_schema_version(payload, items)
    ambiguity_warnings = pipeline_ambiguity_warnings(request)
    by_question: dict[int, JsonObject] = {}
    normalization_warnings: list[str] = []
    for index, value in enumerate(items, start=1):
        item = require_object(value, f"review_payload.items[{index}]")
        question_no = item_question_no(item, f"review_payload.items[{index}]")
        if question_no in by_question:
            raise Phase2DCacheUnavailable("cache_malformed", f"duplicate question {question_no}")
        if include_pipeline_quality:
            item = item_with_pipeline_quality(item, question_no, request, ambiguity_warnings)
        if schema_version == VERSIONED_CACHE_SCHEMA:
            normalized, warnings = normalize_versioned_item(item, question_no, request, payload)
        else:
            normalized = normalize_legacy_item(
                item,
                question_no,
                request,
                candidate_source="legacy_review_cache",
            )
            warnings = ("legacy_cache_downgraded_to_review",)
        by_question[question_no] = normalized
        normalization_warnings.extend(warnings)
    return build_payload_from_items(
        by_question,
        request,
        "phase2d_cached_review_payload",
        source_schema_version=schema_version,
        normalization_warnings=tuple(dict.fromkeys(normalization_warnings)),
        auto_confirm_policy_version=(
            optional_string(payload.get("auto_confirm_policy_version"), "auto_confirm_policy_version")
            if schema_version == VERSIONED_CACHE_SCHEMA
            else None
        ),
    )


def build_payload_from_items(
    by_question: dict[int, JsonObject],
    request: Phase2DRequest,
    source: str,
    *,
    source_schema_version: str,
    normalization_warnings: tuple[str, ...] = (),
    auto_confirm_policy_version: str | None = None,
) -> JsonObject:
    missing = [number for number in range(1, QUESTION_COUNT + 1) if number not in by_question]
    if missing:
        raise Phase2DCacheUnavailable("cache_malformed", f"missing questions: {missing}")
    payload: JsonObject = {
        "source": source,
        "test_id": request.test_id,
        "round": str(request.round_no),
        "problem_count": QUESTION_COUNT,
        "items": [by_question[number] for number in range(1, QUESTION_COUNT + 1)],
        "source_schema_version": source_schema_version,
        "normalized_schema_version": NORMALIZED_SCHEMA,
        "normalization_warnings": list(normalization_warnings),
    }
    if auto_confirm_policy_version is not None:
        payload["auto_confirm_policy_version"] = auto_confirm_policy_version
    ensure_cache_safe(payload, "normalized cached payload")
    return payload


def cache_schema_version(payload: JsonObject, items: list[JsonValue]) -> str:
    explicit = payload.get("schema_version")
    if explicit is not None:
        schema_version = optional_string(explicit, "schema_version")
        if schema_version != VERSIONED_CACHE_SCHEMA:
            raise Phase2DCacheUnavailable("cache_schema_unsupported", f"unsupported cache schema: {schema_version}")
        return schema_version
    has_review_state = any(isinstance(item, dict) and "review_state" in item for item in items)
    if not has_review_state:
        return LEGACY_REVIEW_SCHEMA
    policy_version = optional_string(payload.get("auto_confirm_policy_version"), "auto_confirm_policy_version")
    if policy_version != AUTO_CONFIRM_POLICY_VERSION:
        raise Phase2DCacheUnavailable("cache_schema_unsupported", "versioned cache policy is missing or unsupported")
    return VERSIONED_CACHE_SCHEMA


def normalize_versioned_item(
    item: JsonObject,
    question_no: int,
    request: Phase2DRequest,
    payload: JsonObject,
) -> tuple[JsonObject, tuple[str, ...]]:
    raw_state = optional_string(item.get("review_state"), "review_state")
    state = raw_state
    normalization_warnings: list[str] = []
    warnings = warning_list(item)
    candidate = candidate_text(item.get("candidate"))
    candidates = candidate_list(item.get("candidates"))
    if candidate is None and candidates:
        candidate = candidates[0]
    if candidate is not None and candidate not in candidates:
        candidates.insert(0, candidate)
    if state not in REVIEW_STATES:
        state = "direct_input"
        candidate = None
        candidates = []
        warnings.append("unknown_review_state")
        normalization_warnings.append(f"q{question_no:03d}_unknown_review_state")
    policy_version = optional_string(payload.get("auto_confirm_policy_version"), "auto_confirm_policy_version")
    evidence = sanitized_auto_confirm_evidence(item.get("auto_confirm_evidence"))
    if state == "auto_confirm" and (
        candidate is None
        or policy_version != AUTO_CONFIRM_POLICY_VERSION
        or evidence is None
    ):
        state = "review_recommended" if candidate is not None else "direct_input"
        warnings.append("auto_confirm_policy_unverified")
        normalization_warnings.append(f"q{question_no:03d}_auto_confirm_downgraded")
    if state == "review_recommended" and candidate is None:
        state = "direct_input"
        warnings.append("candidate_missing")
        normalization_warnings.append(f"q{question_no:03d}_candidate_missing")
    if state in {"direct_input", "retake_required"}:
        candidate = None
        candidates = []
    retake_reason = optional_string(item.get("retake_reason"), "retake_reason", allow_empty=True)
    if state == "retake_required" and not retake_reason:
        retake_reason = "사진 품질 확인 필요"
        normalization_warnings.append(f"q{question_no:03d}_retake_reason_defaulted")
    crop_preview = safe_crop_preview(item.get("crop_preview"), question_no, request)
    normalized: JsonObject = {
        "question_no": question_no,
        "review_state": state,
        "status": state,
        "resolution": "unresolved",
        "recognized": candidate or "?",
        "candidate": candidate,
        "candidates": candidates,
        "warning": list(dict.fromkeys(warnings)),
        "warnings": list(dict.fromkeys(warnings)),
        "crop_preview": crop_preview,
        "allow_edit": True,
        "allow_direct_input": True,
        "requires_confirmation": state != "auto_confirm",
        "retake_reason": retake_reason,
        "candidate_source": optional_string(item.get("candidate_source"), "candidate_source", allow_empty=True)
        or "versioned_cache",
        "final_answer": None,
        "source": None,
    }
    confidence = optional_string(item.get("confidence"), "confidence", allow_empty=True)
    tier = optional_string(item.get("tier"), "tier", allow_empty=True)
    if confidence:
        normalized["confidence"] = confidence
    if tier:
        normalized["tier"] = tier
    if evidence is not None and state == "auto_confirm":
        normalized["auto_confirm_evidence"] = evidence
    return normalized, tuple(normalization_warnings)


def normalize_legacy_item(
    item: JsonObject,
    question_no: int,
    request: Phase2DRequest,
    *,
    candidate_source: str,
) -> JsonObject:
    warnings = warning_list(item)
    candidates = candidate_list(item.get("candidates"))
    candidate = candidate_text(item.get("recognized", item.get("answer")))
    if candidate is None:
        candidate = candidate_text(item.get("final_answer"))
    if candidate is None and candidates:
        candidate = candidates[0]
    if candidate is not None and candidate not in candidates:
        candidates.insert(0, candidate)
    raw_status = optional_string(item.get("status"), "status", allow_empty=True)
    retake_reason = optional_string(item.get("retake_reason"), "retake_reason", allow_empty=True)
    if raw_status == "retake_required":
        state = "retake_required"
        candidate = None
        candidates = []
        retake_reason = retake_reason or "사진 품질 확인 필요"
    elif candidate is None:
        state = "direct_input"
    else:
        state = "review_recommended"
    crop_preview = safe_crop_preview(item.get("crop_preview"), question_no, request)
    return {
        "question_no": question_no,
        "review_state": state,
        "status": state,
        "resolution": "unresolved",
        "recognized": candidate or "?",
        "candidate": candidate,
        "candidates": candidates,
        "warning": list(dict.fromkeys(warnings)),
        "warnings": list(dict.fromkeys(warnings)),
        "crop_preview": crop_preview,
        "allow_edit": True,
        "allow_direct_input": True,
        "requires_confirmation": True,
        "retake_reason": retake_reason,
        "candidate_source": candidate_source,
        "final_answer": None,
        "source": None,
    }


def pipeline_ambiguity_warnings(request: Phase2DRequest) -> dict[int, tuple[str, ...]]:
    try:
        return load_overwritten_ambiguity_warnings(request.pipeline_result.overwritten_ambiguity)
    except OverwrittenAmbiguityArtifactError as exc:
        raise Phase2DCacheUnavailable("pipeline_ambiguity_invalid", str(exc)) from exc


def item_with_pipeline_quality(item: JsonObject, question_no: int, request: Phase2DRequest, ambiguity_warnings: dict[int, tuple[str, ...]]) -> JsonObject:
    normalized = dict(item)
    warnings = string_list(item.get("warnings"), "warnings")
    warnings.extend(crop_quality_warnings(request.pipeline_result.crop_quality, question_no))
    warnings.extend(ambiguity_warnings.get(question_no, ()))
    normalized["warnings"] = list(dict.fromkeys(warnings))
    return normalized


def warning_list(item: JsonObject) -> list[str]:
    warnings: list[str] = []
    for value in (item.get("warning"), item.get("warnings")):
        if value is None:
            continue
        if isinstance(value, str):
            warnings.append(single_line(value, "warning"))
        else:
            warnings.extend(string_list(value, "warning"))
    return list(dict.fromkeys(warnings))


def candidate_text(value: JsonValue) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        text = str(value).strip()
    elif isinstance(value, str):
        text = single_line(value, "candidate")
    elif isinstance(value, dict):
        return candidate_text(value.get("value", value.get("answer")))
    else:
        raise Phase2DCacheUnavailable("cache_malformed", "candidate must be text, number, object, or null")
    return None if not text or text == "?" else text


def candidate_list(value: JsonValue) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise Phase2DCacheUnavailable("cache_malformed", "candidates must be a list")
    candidates: list[str] = []
    for raw in value:
        candidate = candidate_text(raw)
        if candidate is not None and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def sanitized_auto_confirm_evidence(value: JsonValue) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    return {key: child for key, child in value.items() if key in AUTO_CONFIRM_EVIDENCE_KEYS}


def safe_crop_preview(value: JsonValue, question_no: int, request: Phase2DRequest) -> str:
    if isinstance(value, str):
        preview = value.strip()
        if re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=\s]+", preview):
            return preview
        if re.fullmatch(r"/api/ocr-[a-z0-9_\-/]+(?:\?[a-z0-9_=&-]+)?", preview, flags=re.IGNORECASE):
            return preview
    crop_path = request.pipeline_result.crop_dir / f"q{question_no:03d}.png"
    try:
        encoded = base64.b64encode(crop_path.read_bytes()).decode("ascii")
    except OSError as exc:
        raise Phase2DCacheUnavailable("cache_malformed", f"safe crop preview unavailable for q{question_no:03d}") from exc
    return f"data:image/png;base64,{encoded}"


def ensure_cache_safe(value: JsonValue, label: str) -> None:
    leaks = forbidden_paths(value)
    leaks.extend(adapter_forbidden_paths(value))
    if leaks:
        raise Phase2DCacheUnavailable("cache_forbidden_fields", f"{label} contains forbidden fields: {', '.join(dict.fromkeys(leaks))}")
    if path_exposures(value):
        raise Phase2DCacheUnavailable("cache_path_leak", f"{label} contains filesystem paths")


def adapter_forbidden_paths(value: JsonValue, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in ADAPTER_FORBIDDEN_KEYS:
                found.append(child_path)
            found.extend(adapter_forbidden_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(adapter_forbidden_paths(child, f"{path}[{index}]"))
    return found


def item_question_no(item: JsonObject, label: str) -> int:
    raw = item.get("question_no", item.get("question"))
    if not isinstance(raw, int) or isinstance(raw, bool) or not 1 <= raw <= QUESTION_COUNT:
        raise Phase2DCacheUnavailable("cache_malformed", f"{label}.question_no must be 1..20")
    return raw


def optional_string(value: JsonValue, label: str, *, allow_empty: bool = False) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise Phase2DCacheUnavailable("cache_malformed", f"{label} must be a string")
    text = single_line(value, label)
    if not text and not allow_empty:
        raise Phase2DCacheUnavailable("cache_malformed", f"{label} must not be empty")
    return text


def single_line(value: str, label: str) -> str:
    text = value.strip()
    if "\n" in text or "\r" in text:
        raise Phase2DCacheUnavailable("cache_malformed", f"{label} must be a single-line string")
    return text


def string_list(value: JsonValue, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise Phase2DCacheUnavailable("cache_malformed", f"{label} must be a list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise Phase2DCacheUnavailable("cache_malformed", f"{label} must contain strings")
        if "\n" in item or "\r" in item:
            raise Phase2DCacheUnavailable("cache_malformed", f"{label} values must be single-line strings")
        out.append(item)
    return out


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise Phase2DCacheUnavailable("cache_malformed", f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise Phase2DCacheUnavailable("cache_malformed", f"{label} must be a JSON array")
    return value




def require_current_cache_identity(payload: JsonObject, request: Phase2DRequest) -> dict:
    from tools.subjective_sheet_lab.ocr_run_identity import identity_for_request, validate_run_identity
    from tools.subjective_sheet_lab.phase2e_stable_cache import phase2e_provider_model, phase2e_provider_prompt_version
    expected = identity_for_request(
        request, model=request.provider_model or phase2e_provider_model(),
        prompt_version=request.prompt_version or phase2e_provider_prompt_version(),
        form_id=request.form_id, preprocessing_version=request.preprocessing_version)
    try:
        identity = validate_run_identity(payload.get("identity"), expected=expected)
    except ValueError as exc:
        raise Phase2DCacheUnavailable("cache_identity_mismatch", str(exc)) from exc
    if "test_id" in payload and payload["test_id"] != identity["test_id"]:
        raise Phase2DCacheUnavailable("cache_identity_mismatch", "test identity mismatch")
    if "round" in payload and str(payload["round"]) != identity["round"]:
        raise Phase2DCacheUnavailable("cache_identity_mismatch", "round identity mismatch")
    return identity
