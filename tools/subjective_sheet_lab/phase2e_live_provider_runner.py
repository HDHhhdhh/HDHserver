from __future__ import annotations

import json
import re
import urllib.error
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from tools.subjective_sheet_lab.ocr_answer_mode_policy import (
    ANSWER_VALUE_LETTER_CONFUSION_WARNING,
    answer_mode_auto_grade_warning,
    answer_mode_for_question,
    contains_letter,
)
from tools.subjective_sheet_lab.ocr_erased_overwritten_policy import normalize_review_item_for_safety
from tools.subjective_sheet_lab.ocr_image_quality_gate import crop_quality_warnings
from tools.subjective_sheet_lab.ocr_overwritten_ambiguity_artifact import (
    OverwrittenAmbiguityArtifactError,
    load_overwritten_ambiguity_warnings,
)
from tools.subjective_sheet_lab.ocr_payload_leak_policy import forbidden_paths, path_exposures
from tools.subjective_sheet_lab.phase2d_student_item_normalizer import normalize_review_item_for_answer_mode
from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import (
    QUESTION_COUNT,
    JsonObject,
    JsonValue,
    Phase2EFeatureFlags,
    Phase2ERequest,
    Phase2EResult,
    Phase2EStatus,
)
from tools.subjective_sheet_lab.phase2e_provider_error_diagnostics import (
    ProviderErrorDiagnostic,
    safe_case_id,
    try_write_provider_error_diagnostic,
)
from tools.subjective_sheet_lab.phase2e_stable_cache import (
    CONTACT_GROUPS,
    StableOcrCacheRequest,
    deidentified_png_bytes,
    phase2e_cache_root,
    phase2e_provider_model,
    phase2e_provider_prompt_version,
    safe_cache_segment,
    stable_recognized_path_or_none,
)
ARROW_OPERATOR_TOKENS: Final[tuple[str, ...]] = ("->", "→", "=>")
RELATION_OPERATOR_TOKENS: Final[tuple[str, ...]] = ("=", "<", ">", "<=", ">=")
NUMERIC_ONLY_RE: Final[re.Pattern[str]] = re.compile(r"^\d+$")
SIMPLE_NUMERIC_ANSWER_RE: Final[re.Pattern[str]] = re.compile(r"[-+]?\d+(?:/\d+|\.\d+)?")


class ProviderRecognizedItem(Protocol):
    question: int
    recognized: str


@dataclass(frozen=True, slots=True)
class Phase2EProviderOutputError(Exception):
    reason: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class ProviderInputContractError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def run_phase2e_live_provider(request: Phase2ERequest, flags: Phase2EFeatureFlags) -> Phase2EResult:
    from tools.subjective_sheet_lab.ocr_provider_session import LAST_SESSION
    LAST_SESSION.set(None)
    from tools.subjective_sheet_lab.ocr_review_run_payload import validate_pipeline_input
    try:
        validate_pipeline_input(request.pipeline_result,provider_run_identity(request))
    except (ValueError,OSError):
        return provider_error_result(request,flags,"pipeline_identity_mismatch",phase2e_recognized_path(request),False,False)
    recognized_path = phase2e_recognized_path(request)
    try:
        provider_contacts = materialize_deidentified_provider_contacts(
            request.pipeline_result.contact_sheets,
            recognized_path.parent / "provider_input",
        )
        contact_dir = provider_contacts[0].parent
    except ProviderInputContractError:
        return provider_error_result(request, flags, "provider_input_rejected", recognized_path, False, False)

    try:
        from tools.subjective_sheet_lab.gemini_provider import (
            CliConfig,
            GeminiProviderError,
            read_gemini_key,
            recognize_from_config,
        )
    except ImportError:
        return provider_error_result(request, flags, "provider_adapter_unavailable", recognized_path, False, False)

    try:
        api_key = read_gemini_key()
        config = CliConfig(
            crop_dir=None,
            contact_dir=contact_dir,
            image_files=(),
            out_path=recognized_path,
            model=phase2e_provider_model(),
            resume=False,
            max_calls=flags.max_provider_calls_per_request,
            test_id=request.test_id,
            source_image=request.pipeline_result.source_image, round_no=str(request.round_no),
            form_id=request.request_metadata.get("form_id", "answer_sheet_20_v1"),
            prompt_version=phase2e_provider_prompt_version(),
            preprocessing_version=request.request_metadata.get("preprocessing_version", "crop_contact_v1"),
            contact_batch_size=4,
            answer_modes=tuple(answer_mode_for_question(request.test_id,n) for n in range(1,21)),
            numeric_only=numeric_only_requested(request),
        )
        provider_items = provider_items_to_json(recognize_from_config(config, api_key))
        review_payload = review_payload_from_provider_items(provider_items, request, identity=LAST_SESSION.get().identity)
        write_phase2e_recognized_json(recognized_path, provider_items, identity=review_payload["identity"])
    except GeminiProviderError as exc:
        attempted = bool(LAST_SESSION.get() and LAST_SESSION.get().calls)
        reason = exc.reason if exc.reason != "provider_error" else provider_error_reason(exc.message)
        return provider_error_result(request, flags, reason, recognized_path, attempted, False, exc.diagnostic)
    except urllib.error.HTTPError as exc:
        quota = exc.code == 429
        reason = "provider_quota_or_rate_limited" if quota else f"provider_http_{exc.code}"
        return provider_error_result(request, flags, reason, recognized_path, True, quota)
    except urllib.error.URLError:
        return provider_error_result(request, flags, "provider_network_error", recognized_path, True, False)
    except TimeoutError:
        return provider_error_result(request, flags, "provider_timeout", recognized_path, True, False)
    except json.JSONDecodeError:
        return provider_error_result(request, flags, "provider_invalid_json", recognized_path, True, False)
    except OSError:
        return provider_error_result(request, flags, "provider_local_io_error", recognized_path, True, False)
    except Phase2EProviderOutputError as exc:
        return provider_error_result(request, flags, exc.reason, recognized_path, True, False)

    return Phase2EResult(
        status=Phase2EStatus.LIVE_CALL_SUCCEEDED,
        reason="recognized_cache_written",
        provider_call_attempted=True,
        provider_call_count=LAST_SESSION.get().calls if LAST_SESSION.get() else 0,
        max_provider_calls=flags.max_provider_calls_per_request,
        cache_write_enabled=flags.cache_write_enabled,
        contact_sheet_count=request.pipeline_result.contact_sheet_count,
        crop_count=request.pipeline_result.crop_count,
        review_payload=review_payload,
        recognized_path=recognized_path,
    )


def provider_error_result(
    request: Phase2ERequest,
    flags: Phase2EFeatureFlags,
    reason: str,
    recognized_path: Path,
    attempted: bool,
    quota_or_rate_limited: bool,
    provider_response_shape: JsonObject | None = None,
) -> Phase2EResult:
    from tools.subjective_sheet_lab.ocr_provider_session import LAST_SESSION
    session = LAST_SESSION.get()
    actual_calls = session.calls if session is not None and session.config.out_path == recognized_path else 0
    attempted = actual_calls > 0
    try_write_provider_error_diagnostic(
        ProviderErrorDiagnostic(
            request=request,
            flags=flags,
            reason=reason,
            recognized_path=recognized_path,
            attempted=attempted,
            quota_or_rate_limited=quota_or_rate_limited,
            provider_response_shape=provider_response_shape,
        )
    )
    return Phase2EResult(
        status=Phase2EStatus.PROVIDER_ERROR,
        reason=reason,
        provider_call_attempted=attempted,
        provider_call_count=actual_calls,
        max_provider_calls=flags.max_provider_calls_per_request,
        cache_write_enabled=flags.cache_write_enabled,
        contact_sheet_count=request.pipeline_result.contact_sheet_count,
        crop_count=request.pipeline_result.crop_count,
        recognized_path=recognized_path,
        quota_or_rate_limited=quota_or_rate_limited,
    )


def provider_error_reason(message: str) -> str:
    lowered = message.lower()
    if "gemini_api_key" in lowered and "missing" in lowered:
        return "provider_key_unavailable"
    if "json" in lowered:
        return "provider_invalid_json"
    if "missing questions" in lowered:
        return "provider_missing_questions"
    return "provider_error"


def provider_error_may_have_called(message: str) -> bool:
    lowered = message.lower()
    no_call_markers = (
        "gemini_api_key is missing",
        "contact directory not found",
        "contact sheet image not found",
        "unsupported contact sheet image type",
        "no contact sheet images found",
    )
    return not any(marker in lowered for marker in no_call_markers)


def phase2e_recognized_path(request: Phase2ERequest) -> Path:
    cache_root = phase2e_variant_cache_root(request)
    stable_path = stable_recognized_path_or_none(
        StableOcrCacheRequest(
            sid=request.sid,
            test_id=request.test_id,
            round_no=request.round_no,
            source_image=request.pipeline_result.source_image,
            form_id=request.request_metadata.get("form_id","answer_sheet_20_v1"),
            preprocessing_version=request.request_metadata.get("preprocessing_version","crop_contact_v1"),
            cache_root=cache_root,
        )
    )
    if stable_path is not None:
        return stable_path
    case_id = safe_case_id(request.pipeline_result.case_id)
    return cache_root / case_id / "recognized.json"


def phase2e_variant_cache_root(request: Phase2ERequest) -> Path:
    variant = str(request.request_metadata.get("cache_variant") or "").strip()
    if not variant:
        return phase2e_cache_root()
    return phase2e_cache_root() / safe_cache_segment(variant)


def materialize_deidentified_provider_contacts(contact_sheets: tuple[Path, ...], destination: Path) -> tuple[Path, ...]:
    if len(contact_sheets) != len(CONTACT_GROUPS):
        raise ProviderInputContractError("provider input requires exactly four contact sheets")
    try:
        destination.mkdir(parents=True, exist_ok=True)
        aliases: list[Path] = []
        for (start, end), source in zip(CONTACT_GROUPS, contact_sheets, strict=True):
            if source.suffix.lower() != ".png" or not source.is_file():
                raise ProviderInputContractError("provider input accepts only existing PNG contact sheets")
            target = destination / f"answer_sheet_q{start:03d}_q{end:03d}.png"
            data = deidentified_png_bytes(source)
            if target.exists():
                if target.read_bytes() != data:
                    raise ProviderInputContractError("existing provider input is preserved")
            else:
                with target.open("xb") as image_out:
                    image_out.write(data)
            aliases.append(target)
    except OSError as exc:
        raise ProviderInputContractError("provider input could not be deidentified") from exc
    return tuple(aliases)


def provider_items_to_json(items: Sequence[ProviderRecognizedItem]) -> list[JsonObject]:
    return [{"question": item.question, "recognized": item.recognized,
             "candidates": list(getattr(item,"candidates",())),
             "uncertainty": getattr(item,"uncertainty","unverified"),
             "needs_review": getattr(item,"needs_review",True)} for item in items]


def numeric_only_requested(request: Phase2ERequest) -> bool:
    return str(request.request_metadata.get("numeric_only") or "").strip() == "1"


def numeric_only_provider_items(items: list[JsonObject]) -> list[JsonObject]:
    # Preserve the transcript; numeric-only scope is checked before any provider attempt.
    return [dict(item) for item in items]


def review_payload_from_provider_items(items: list[JsonObject], request: Phase2ERequest, *, identity: dict | None = None) -> JsonObject:
    from tools.subjective_sheet_lab.ocr_run_identity import validate_run_identity
    identity = validate_run_identity(identity) if identity is not None else provider_run_identity(request)
    by_question: dict[int, JsonObject] = {}
    ambiguity_warnings = pipeline_ambiguity_warnings(request)
    for index, item in enumerate(items, start=1):
        question_no = item_question_no(item, f"items[{index}]")
        if question_no in by_question:
            raise Phase2EProviderOutputError("provider_duplicate_question", f"duplicate question {question_no}")
        by_question[question_no] = provider_review_item(
            question_no,
            item.get("recognized") if isinstance(item.get("recognized"),str) else recognized_text(item.get("recognized"), f"items[{index}].recognized"),
            request,
            ambiguity_warnings,
        )
        from tools.subjective_sheet_lab.gemini_provider import parse_item
        parsed = parse_item(item)
        by_question[question_no]["candidates"] = list(parsed.candidates)
        by_question[question_no]["uncertainty"] = parsed.uncertainty
        by_question[question_no]["needs_review"] = parsed.needs_review
        by_question[question_no]["identity_sha256"] = identity["identity_sha256"]
        by_question[question_no]["review_history"] = []
        crop = request.pipeline_result.crop_dir / f"q{question_no:03d}.png"
        if crop.is_file():
            import base64, hashlib
            data = deidentified_png_bytes(crop)
            by_question[question_no]["crop_preview"] = "data:image/png;base64,"+base64.b64encode(data).decode("ascii")
            by_question[question_no]["crop_sha256"] = hashlib.sha256(data).hexdigest()


    missing = [number for number in range(1, QUESTION_COUNT + 1) if number not in by_question]
    if missing:
        raise Phase2EProviderOutputError("provider_missing_questions", f"missing questions: {missing}")

    payload: JsonObject = {
        "schema": "ocr.review.run.v1",
        "identity": identity,
        "source": "phase2e_gemini_live",
        "test_id": request.test_id,
        "round": str(request.round_no),
        "problem_count": QUESTION_COUNT,
        "items": [by_question[number] for number in range(1, QUESTION_COUNT + 1)],
    }
    leaks = forbidden_paths(payload)
    if leaks:
        raise Phase2EProviderOutputError("provider_forbidden_fields", ", ".join(leaks))
    if path_exposures(payload):
        raise Phase2EProviderOutputError("provider_path_leak", "student payload contains filesystem paths")
    return payload


def pipeline_ambiguity_warnings(request: Phase2ERequest) -> dict[int, tuple[str, ...]]:
    try:
        return load_overwritten_ambiguity_warnings(request.pipeline_result.overwritten_ambiguity)
    except OverwrittenAmbiguityArtifactError as exc:
        raise Phase2EProviderOutputError("pipeline_ambiguity_invalid", str(exc)) from exc


def provider_review_item(question_no: int, recognized: str, request: Phase2ERequest, ambiguity_warnings: dict[int, tuple[str, ...]]) -> JsonObject:
    warnings = provider_warnings(question_no, recognized, request, ambiguity_warnings)
    item: JsonObject = {
        "question_no": question_no,
        "status": "review_required",
        "recognized": recognized,
        "warnings": warnings,
        "candidates": provider_candidates(question_no, recognized, request),
        "final_answer": None,
        "source": None,
    }
    safe_item = normalize_review_item_for_safety(item)
    return normalize_review_item_for_answer_mode(safe_item, request.test_id)


def provider_candidates(question_no: int, recognized: str, request: Phase2ERequest) -> list[JsonValue]:
    text = recognized.strip()
    if text in {"", "?"}:
        return []
    mode = answer_mode_for_question(request.test_id, question_no)
    if mode == "choice_number":
        return [text] if text in {"1", "2", "3", "4", "5"} else []
    if mode == "answer_value":
        return [text] if SIMPLE_NUMERIC_ANSWER_RE.fullmatch(text) else []
    return []


def provider_warnings(question_no: int, recognized: str, request: Phase2ERequest, ambiguity_warnings: dict[int, tuple[str, ...]]) -> list[JsonValue]:
    warnings = relation_operator_warnings(recognized)
    mode_warning = answer_mode_auto_grade_warning(question_no, recognized, request.test_id)
    if mode_warning is not None:
        warnings.append(mode_warning)
    warnings.extend(crop_quality_warnings(request.pipeline_result.crop_quality, question_no))
    warnings.extend(ambiguity_warnings.get(question_no, ()))
    if answer_mode_for_question(request.test_id, question_no) != "choice_number" and contains_letter(recognized):
        warnings.append(ANSWER_VALUE_LETTER_CONFUSION_WARNING)
    return warnings


def relation_operator_warnings(recognized: str) -> list[JsonValue]:
    if any(token in recognized for token in ARROW_OPERATOR_TOKENS):
        return ["arrow_equal_confusion"]
    if any(token in recognized for token in RELATION_OPERATOR_TOKENS):
        return ["relation_symbol_confusion"]
    return []


def item_question_no(item: JsonObject, label: str) -> int:
    raw = item.get("question")
    if not isinstance(raw, int) or isinstance(raw, bool) or not 1 <= raw <= QUESTION_COUNT:
        raise Phase2EProviderOutputError("provider_malformed_question", f"{label}.question must be 1..20")
    return raw


def recognized_text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise Phase2EProviderOutputError("provider_malformed_recognized", f"{label} must be a string")
    text = value.strip()
    return text or "?"


def write_phase2e_recognized_json(path: Path, items: list[JsonObject], *, identity: dict) -> None:
    from tools.subjective_sheet_lab.ocr_run_identity import RECOGNITION_SCHEMA, validate_run_identity
    checked = validate_run_identity(identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x",encoding="utf-8") as output:
        output.write(json.dumps({"schema":RECOGNITION_SCHEMA,"identity":checked,"items":items},ensure_ascii=False,indent=2)+"\n")






def provider_run_identity(request: Phase2ERequest) -> dict:
    from tools.subjective_sheet_lab.ocr_run_identity import identity_for_request
    return identity_for_request(request, model=phase2e_provider_model(),
        prompt_version=phase2e_provider_prompt_version(),
        form_id=request.request_metadata.get("form_id","answer_sheet_20_v1"),
        preprocessing_version=request.request_metadata.get("preprocessing_version","crop_contact_v1"))
