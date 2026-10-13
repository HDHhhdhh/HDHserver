from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypeAlias

from core.short_answer import normalize_short_answer
from core.test_answer_modes import ANSWER_VALUE, CHOICE_NUMBER, MANUAL_REVIEW, VALID_ANSWER_MODES
from tools.subjective_sheet_lab.ocr_image_quality_gate import crop_quality_warnings
from tools.subjective_sheet_lab.ocr_overwritten_ambiguity_artifact import (
    OverwrittenAmbiguityArtifactError,
    load_overwritten_ambiguity_warnings,
)
from tools.subjective_sheet_lab.ocr_payload_leak_policy import forbidden_paths, path_exposures
from tools.subjective_sheet_lab.phase2c_crop_pipeline_contracts import Phase2CResult
from tools.subjective_sheet_lab.phase2d_student_item_normalizer import normalize_student_item


JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
Recognizer: TypeAlias = Callable[[Sequence[tuple[int, Path]]], Mapping[int, str]]

QUESTION_COUNT: Final[int] = 20
ENABLED_ENV: Final[str] = "OCR_PHASE2_TEXTELLER_REVIEW_ENABLED"
PYTHON_ENV: Final[str] = "OCR_PHASE2_TEXTELLER_PYTHON"
WORKER_ENV: Final[str] = "OCR_PHASE2_TEXTELLER_WORKER"
HF_HOME_ENV: Final[str] = "OCR_PHASE2_TEXTELLER_HF_HOME"
BATCH_SIZE_ENV: Final[str] = "OCR_PHASE2_TEXTELLER_BATCH_SIZE"
MAX_TOKENS_ENV: Final[str] = "OCR_PHASE2_TEXTELLER_MAX_TOKENS"
CPU_THREADS_ENV: Final[str] = "OCR_PHASE2_TEXTELLER_CPU_THREADS"
TIMEOUT_ENV: Final[str] = "OCR_PHASE2_TEXTELLER_TIMEOUT_SECONDS"

DEFAULT_PYTHON: Final[Path] = Path("C:/server-ocr/texteller-venv/Scripts/python.exe")
DEFAULT_WORKER: Final[Path] = Path(__file__).with_name("phase2g_texteller_worker.py")
DEFAULT_HF_HOME: Final[Path] = Path("C:/server-ocr/texteller-cache/huggingface")
RESULT_PREFIX: Final[str] = "TEXTELLER_RESULT_JSON:"
WORKER_SCHEMA_VERSION: Final[str] = "phase2g_texteller_worker_v1"
TRUTHY_VALUES: Final[frozenset[str]] = frozenset(("1", "true", "yes", "on"))

LOCAL_OCR_UNVERIFIED: Final[str] = "local_ocr_unverified"
LOCAL_FORMULA_UNVERIFIED: Final[str] = "local_formula_unverified"
FORMULA_PARSE_UNSUPPORTED: Final[str] = "formula_parse_unsupported"
FORMULA_WRAPPER_REVIEW_ONLY: Final[str] = "formula_wrapper_unwrapped_review_only"
OVERLINE_SEMANTICS_REVIEW_REQUIRED: Final[str] = "overline_semantics_review_required"
CHOICE_RECOGNIZER_PENDING: Final[str] = "choice_number_recognizer_pending"
MANUAL_REVIEW_REQUIRED: Final[str] = "manual_review_required"
SOURCE: Final[str] = "phase2g_local_texteller_review"

_OUTER_COMMAND_RE: Final[re.Pattern[str]] = re.compile(r"^\\(boxed|overline)\s*\{")


@dataclass(frozen=True, slots=True)
class Phase2GRequest:
    sid: str
    test_id: str
    round_no: int
    pipeline_result: Phase2CResult
    answer_modes: tuple[str, ...]
    form_id: str = "answer_sheet_20_v1"
    preprocessing_version: str = "crop_contact_v1"


@dataclass(frozen=True, slots=True)
class Phase2GTextellerUnavailable(Exception):
    reason: str
    detail: str = ""

    def __str__(self) -> str:
        return self.detail or self.reason


def texteller_review_enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "").strip().lower() in TRUTHY_VALUES


def load_phase2g_texteller_review_payload(
    request: Phase2GRequest,
    *,
    recognizer: Recognizer | None = None,
) -> JsonObject:
    if not texteller_review_enabled():
        raise Phase2GTextellerUnavailable("feature_disabled")
    from tools.subjective_sheet_lab.ocr_run_identity import identity_for_request
    from tools.subjective_sheet_lab.ocr_review_run_payload import bind_review_payload, validate_pipeline_input
    identity = identity_for_request(request,model="texteller-local-unverified",prompt_version="local_formula_v1",form_id=request.form_id,preprocessing_version=request.preprocessing_version)
    validate_pipeline_input(request.pipeline_result,identity)
    crops = _validated_answer_value_crops(request)
    if recognizer is None:
        recognized_by_question = _run_worker(crops)
    else:
        recognized_by_question = dict(recognizer(crops))
    _validate_recognized_questions(recognized_by_question, crops)

    try:
        ambiguity_warnings = load_overwritten_ambiguity_warnings(
            request.pipeline_result.overwritten_ambiguity
        )
    except OverwrittenAmbiguityArtifactError as exc:
        raise Phase2GTextellerUnavailable("pipeline_ambiguity_invalid") from exc

    items: list[JsonObject] = []
    for question_no, answer_mode in enumerate(request.answer_modes, start=1):
        recognized = "?"
        candidates: list[str] = []
        warnings: list[str]
        if answer_mode == ANSWER_VALUE:
            recognized, candidate_warnings = review_candidate(
                recognized_by_question[question_no]
            )
            candidates = [recognized] if recognized != "?" else []
            warnings = [LOCAL_OCR_UNVERIFIED, LOCAL_FORMULA_UNVERIFIED]
            warnings.extend(candidate_warnings)
            if recognized == "?":
                warnings.append(FORMULA_PARSE_UNSUPPORTED)
        elif answer_mode == CHOICE_NUMBER:
            warnings = [CHOICE_RECOGNIZER_PENDING]
        else:
            warnings = [MANUAL_REVIEW_REQUIRED]
        warnings.extend(crop_quality_warnings(request.pipeline_result.crop_quality, question_no))
        warnings.extend(ambiguity_warnings.get(question_no, ()))
        item = normalize_student_item(
            {
                "question_no": question_no,
                "status": "review_required",
                "recognized": recognized,
                "warnings": list(dict.fromkeys(warnings)),
                "candidates": candidates,
                "final_answer": None,
                "source": None,
            },
            question_no,
            request.test_id,
            _required_single_line,
        )
        if answer_mode == ANSWER_VALUE:
            item["recognized"] = recognized_by_question[question_no]
        item["answer_mode"] = answer_mode
        items.append(item)

    payload: JsonObject = {
        "source": SOURCE,
        "test_id": request.test_id,
        "round": str(request.round_no),
        "problem_count": QUESTION_COUNT,
        "provider_call_count": 0,
        "items": items,
    }
    _validate_student_payload(payload)
    return bind_review_payload(payload,request.pipeline_result,identity)


def review_candidate(raw_latex: object) -> tuple[str, tuple[str, ...]]:
    raw = _required_single_line(raw_latex, "raw_latex")
    direct = normalize_short_answer(raw, ANSWER_VALUE)
    if direct is not None:
        return direct, ()

    expression = _strip_math_delimiters(raw)
    wrappers: list[str] = []
    for _ in range(2):
        unwrapped = _unwrap_outer_command(expression)
        if unwrapped is None:
            break
        command, expression = unwrapped
        wrappers.append(command)
    if not wrappers:
        return "?", ()
    candidate = normalize_short_answer(expression, ANSWER_VALUE)
    if candidate is None:
        return "?", ()
    warnings = [FORMULA_WRAPPER_REVIEW_ONLY]
    if "overline" in wrappers:
        warnings.append(OVERLINE_SEMANTICS_REVIEW_REQUIRED)
    return candidate, tuple(warnings)


def _strip_math_delimiters(value: str) -> str:
    text = value.strip()
    for left, right in (("\\(", "\\)"), ("\\[", "\\]"), ("$$", "$$"), ("$", "$")):
        if text.startswith(left) and text.endswith(right) and len(text) > len(left) + len(right):
            return text[len(left) : -len(right)].strip()
    return text


def _unwrap_outer_command(value: str) -> tuple[str, str] | None:
    text = value.strip()
    matched = _OUTER_COMMAND_RE.match(text)
    if matched is None:
        return None
    opening_index = matched.end() - 1
    depth = 0
    closing_index = -1
    for index in range(opening_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                closing_index = index
                break
    if closing_index < 0 or text[closing_index + 1 :].strip():
        return None
    return matched.group(1), text[opening_index + 1 : closing_index].strip()


def _validated_answer_value_crops(request: Phase2GRequest) -> list[tuple[int, Path]]:
    if not request.test_id.strip() or request.round_no < 1:
        raise Phase2GTextellerUnavailable("request_invalid")
    if len(request.answer_modes) != QUESTION_COUNT or any(
        mode not in VALID_ANSWER_MODES for mode in request.answer_modes
    ):
        raise Phase2GTextellerUnavailable("answer_modes_invalid")
    crop_dir = request.pipeline_result.crop_dir.resolve()
    crops: list[tuple[int, Path]] = []
    for question_no, answer_mode in enumerate(request.answer_modes, start=1):
        if answer_mode != ANSWER_VALUE:
            continue
        path = (crop_dir / f"q{question_no:03d}.png").resolve()
        if path.parent != crop_dir or not path.is_file():
            raise Phase2GTextellerUnavailable("crop_unavailable")
        crops.append((question_no, path))
    if not crops:
        raise Phase2GTextellerUnavailable("answer_value_crops_unavailable")
    return crops


def _validate_recognized_questions(
    recognized: Mapping[int, str], crops: Sequence[tuple[int, Path]]
) -> None:
    expected = {question_no for question_no, _ in crops}
    if set(recognized) != expected:
        raise Phase2GTextellerUnavailable("worker_output_malformed")
    for question_no, value in recognized.items():
        if (
            isinstance(question_no, bool)
            or not isinstance(question_no, int)
            or not isinstance(value, str)
            or not value.strip()
            or "\n" in value
            or "\r" in value
            or len(value) > 512
        ):
            raise Phase2GTextellerUnavailable("worker_output_malformed")


def _run_worker(crops: Sequence[tuple[int, Path]]) -> dict[int, str]:
    python_exe = Path(os.environ.get(PYTHON_ENV, str(DEFAULT_PYTHON))).resolve()
    worker_script = Path(os.environ.get(WORKER_ENV, str(DEFAULT_WORKER))).resolve()
    hf_home = Path(os.environ.get(HF_HOME_ENV, str(DEFAULT_HF_HOME))).resolve()
    if not python_exe.is_file() or not worker_script.is_file() or not hf_home.is_dir():
        raise Phase2GTextellerUnavailable("runtime_unavailable")

    request_payload = {
        "items": [
            {"question_no": question_no, "image_path": str(path)}
            for question_no, path in crops
        ],
        "hf_home": str(hf_home),
        "batch_size": _bounded_env_int(BATCH_SIZE_ENV, 4, 1, 20),
        "max_tokens": _bounded_env_int(MAX_TOKENS_ENV, 64, 1, 128),
        "cpu_threads": _bounded_env_int(CPU_THREADS_ENV, 6, 1, 32),
    }
    env = dict(os.environ)
    env.update(
        {
            "HF_HOME": str(hf_home),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [str(python_exe), str(worker_script)],
            input=json.dumps(request_payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=_bounded_env_int(TIMEOUT_ENV, 180, 10, 600),
            check=False,
            env=env,
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired as exc:
        raise Phase2GTextellerUnavailable("worker_timeout") from exc
    except OSError as exc:
        raise Phase2GTextellerUnavailable("runtime_unavailable") from exc

    worker_payload = _parse_worker_payload(completed.stdout)
    if completed.returncode != 0 or worker_payload.get("ok") is not True:
        error_code = worker_payload.get("error_code")
        reason = error_code if isinstance(error_code, str) and error_code else "worker_failed"
        raise Phase2GTextellerUnavailable(reason)
    if (
        worker_payload.get("schema_version") != WORKER_SCHEMA_VERSION
        or worker_payload.get("provider_call_count") != 0
    ):
        raise Phase2GTextellerUnavailable("worker_output_malformed")
    if forbidden_paths(worker_payload) or path_exposures(worker_payload):
        raise Phase2GTextellerUnavailable("worker_output_leak")
    raw_items = worker_payload.get("items")
    if not isinstance(raw_items, list):
        raise Phase2GTextellerUnavailable("worker_output_malformed")
    recognized: dict[int, str] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            raise Phase2GTextellerUnavailable("worker_output_malformed")
        question_no = item.get("question_no")
        raw_latex = item.get("raw_latex")
        if (
            isinstance(question_no, bool)
            or not isinstance(question_no, int)
            or question_no in recognized
            or not isinstance(raw_latex, str)
        ):
            raise Phase2GTextellerUnavailable("worker_output_malformed")
        recognized[question_no] = raw_latex
    return recognized


def _parse_worker_payload(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if not line.startswith(RESULT_PREFIX):
            continue
        try:
            payload = json.loads(line[len(RESULT_PREFIX) :])
        except json.JSONDecodeError as exc:
            raise Phase2GTextellerUnavailable("worker_output_malformed") from exc
        if isinstance(payload, dict):
            return payload
        break
    raise Phase2GTextellerUnavailable("worker_output_malformed")


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise Phase2GTextellerUnavailable("runtime_config_invalid") from exc
    if value < minimum or value > maximum:
        raise Phase2GTextellerUnavailable("runtime_config_invalid")
    return value


def _required_single_line(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise Phase2GTextellerUnavailable("worker_output_malformed", f"{label} must be a string")
    text = value.strip()
    if not text or "\n" in text or "\r" in text:
        raise Phase2GTextellerUnavailable("worker_output_malformed", f"{label} must be one line")
    return text


def _validate_student_payload(payload: JsonObject) -> None:
    if forbidden_paths(payload):
        raise Phase2GTextellerUnavailable("student_payload_forbidden_fields")
    if path_exposures(payload):
        raise Phase2GTextellerUnavailable("student_payload_path_leak")
    if payload.get("provider_call_count") != 0:
        raise Phase2GTextellerUnavailable("provider_call_contract_violation")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != QUESTION_COUNT:
        raise Phase2GTextellerUnavailable("student_payload_malformed")
    for item in items:
        if (
            not isinstance(item, dict)
            or item.get("status") != "review_required"
            or item.get("source") is not None
            or item.get("final_answer") is not None
        ):
            raise Phase2GTextellerUnavailable("unsafe_auto_grade_contract_violation")
