from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Mapping, Sequence

from core.student_test_ocr_rules import (
    ANSWER_VALUE,
    CHOICE_NUMBER,
    OcrRuleError,
    answer_values_equivalent,
    canonicalize_answer_text,
    classify_sheet_recognition,
    normalize_recognized_answer,
    numeric_answer_value,
)


WORKER_SCHEMA: Final = "student_test_ocr_worker_v1"
MAX_WORKER_STDOUT_BYTES: Final = 1_000_000
SAFE_ENV_NAMES: Final = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "USERPROFILE",
        "USERNAME",
        "HOMEDRIVE",
        "HOMEPATH",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
    }
)


@dataclass(frozen=True, slots=True)
class OcrEngineError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    engine: str
    python_path: Path
    script_path: Path
    timeout_seconds: float = 60.0
    arguments: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OcrCrop:
    question_no: int
    answer_mode: str
    image_path: Path


@dataclass(frozen=True, slots=True)
class ConfidencePolicy:
    choice_digit_minimum: float = 0.995
    choice_digit_margin_minimum: float = 0.90
    choice_paddle_minimum: float = 0.98
    unimernet_token_minimum: float = 0.995
    require_choice_cross_engine_agreement: bool = True
    require_paddle_variant_agreement: bool = True
    require_formula_cross_engine_agreement: bool = True
    require_unimernet_variant_agreement: bool = False
    enable_adaptive_formula_second_pass: bool = True
    maximum_adaptive_formula_crops: int = 3


def _fail(code: str, message: str) -> None:
    raise OcrEngineError(code, message)


def _safe_worker_environment(overrides: Mapping[str, str]) -> dict[str, str]:
    environment = {name: value for name, value in os.environ.items() if name.upper() in SAFE_ENV_NAMES}
    for name, value in overrides.items():
        upper = str(name).upper()
        if any(fragment in upper for fragment in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            _fail("unsafe_worker_environment", "secrets cannot be forwarded to a local OCR worker")
        environment[str(name)] = str(value)
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    environment.setdefault("PYTHONUTF8", "1")
    return environment


def _validated_crops(crops: Sequence[OcrCrop], asset_root: Path) -> tuple[OcrCrop, ...]:
    if len(crops) != 20:
        _fail("invalid_crop_set", "OCR engine requires exactly 20 question crops")
    root = asset_root.resolve()
    indexed: dict[int, OcrCrop] = {}
    for crop in crops:
        if not 1 <= crop.question_no <= 20 or crop.question_no in indexed:
            _fail("invalid_crop_set", "OCR crops must uniquely cover questions 1 through 20")
        if crop.answer_mode not in {CHOICE_NUMBER, ANSWER_VALUE}:
            _fail("invalid_crop_set", "OCR crop answer mode is unsupported")
        path = crop.image_path.resolve()
        try:
            path.relative_to(root)
        except ValueError:
            _fail("invalid_crop_path", "OCR crop path escapes the asset root")
        if not path.is_file():
            _fail("missing_crop", f"OCR crop is missing for question {crop.question_no}")
        indexed[crop.question_no] = OcrCrop(crop.question_no, crop.answer_mode, path)
    return tuple(indexed[number] for number in range(1, 21))


def run_json_worker(spec: WorkerSpec, crops: Sequence[OcrCrop]) -> dict:
    python_path = spec.python_path.resolve()
    script_path = spec.script_path.resolve()
    if not python_path.is_file() or not script_path.is_file():
        _fail("ocr_engine_unavailable", f"{spec.engine} worker is not installed")
    payload = {
        "schema": WORKER_SCHEMA,
        "items": [
            {"questionNo": crop.question_no, "imagePath": str(crop.image_path)}
            for crop in crops
        ],
    }
    command = [str(python_path), "-B", str(script_path), *spec.arguments]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=spec.timeout_seconds,
            check=False,
            env=_safe_worker_environment(spec.environment),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise OcrEngineError("ocr_engine_timeout", f"{spec.engine} worker timed out") from error
    except OSError as error:
        raise OcrEngineError("ocr_engine_unavailable", f"{spec.engine} worker could not start") from error
    if len(completed.stdout.encode("utf-8", errors="ignore")) > MAX_WORKER_STDOUT_BYTES:
        _fail("invalid_worker_response", f"{spec.engine} worker response is too large")
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1][:240] if completed.stderr.strip() else "worker failed"
        _fail("ocr_engine_failed", f"{spec.engine}: {detail}")
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        _fail("invalid_worker_response", f"{spec.engine} worker must return one JSON line")
    try:
        response = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise OcrEngineError("invalid_worker_response", f"{spec.engine} worker returned invalid JSON") from error
    if not isinstance(response, dict) or response.get("ok") is not True or response.get("engine") != spec.engine:
        _fail("invalid_worker_response", f"{spec.engine} worker response contract is invalid")
    response["wallSeconds"] = round(time.perf_counter() - started, 4)
    return response


def _index_worker_items(
    response: Mapping[str, object],
    engine: str,
    expected_numbers: Sequence[int] = tuple(range(1, 21)),
) -> dict[int, dict]:
    raw_items = response.get("items")
    expected = set(expected_numbers)
    if not isinstance(raw_items, list) or len(raw_items) != len(expected):
        _fail("invalid_worker_response", f"{engine} worker returned the wrong item count")
    indexed: dict[int, dict] = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            _fail("invalid_worker_response", f"{engine} worker item is invalid")
        number = raw.get("questionNo")
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 20 or number in indexed:
            _fail("invalid_worker_response", f"{engine} worker question coverage is invalid")
        indexed[number] = dict(raw)
    if set(indexed) != expected:
        _fail("invalid_worker_response", f"{engine} worker question coverage is incomplete")
    return indexed


def _valid_numeric_answer(value: object) -> bool:
    try:
        numeric_answer_value(value)
        return True
    except OcrRuleError:
        return False


def _build_legacy_candidate(
    crop: OcrCrop,
    paddle: Mapping[str, object],
    unimernet: Mapping[str, object],
    policy: ConfidencePolicy,
) -> dict:
    paddle_text = str(paddle.get("text") or "")
    paddle_score = paddle.get("score")
    if isinstance(paddle_score, bool) or not isinstance(paddle_score, (int, float)):
        paddle_score = None
    else:
        paddle_score = float(paddle_score)
    unimernet_text = str(unimernet.get("text") or "")
    variant_text = str(unimernet.get("variantText") or "")
    variant_agreed = unimernet.get("variantAgreed") is True
    token_confidence = unimernet.get("tokenConfidence")
    if isinstance(token_confidence, bool) or not isinstance(token_confidence, (int, float)):
        token_confidence = None
    else:
        token_confidence = float(token_confidence)

    if crop.answer_mode == CHOICE_NUMBER:
        primary = normalize_recognized_answer(CHOICE_NUMBER, paddle_text)
        cross = normalize_recognized_answer(CHOICE_NUMBER, unimernet_text)
        confident = bool(primary and paddle_score is not None and paddle_score >= policy.choice_paddle_minimum)
        if policy.require_choice_cross_engine_agreement:
            confident = confident and primary == cross and token_confidence is not None and (
                token_confidence >= policy.unimernet_token_minimum
            ) and (
                variant_agreed or not policy.require_unimernet_variant_agreement
            )
        raw_answer = paddle_text
        confidence = paddle_score
    else:
        primary = canonicalize_answer_text(unimernet_text)
        variant = canonicalize_answer_text(variant_text)
        confident = bool(
            primary
            and _valid_numeric_answer(primary)
            and token_confidence is not None
            and token_confidence >= policy.unimernet_token_minimum
        )
        if policy.require_unimernet_variant_agreement:
            confident = confident and variant_agreed and answer_values_equivalent(primary, variant)
        paddle_numeric = canonicalize_answer_text(paddle_text)
        if confident and _valid_numeric_answer(paddle_numeric):
            confident = answer_values_equivalent(primary, paddle_numeric)
        raw_answer = unimernet_text
        confidence = token_confidence

    return {
        "questionNo": crop.question_no,
        "rawAnswer": raw_answer,
        "confidence": confidence,
        "confident": confident,
    }


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if 0 <= parsed <= 1 else None


def _build_choice_candidate(
    crop: OcrCrop,
    paddle: Mapping[str, object],
    digit: Mapping[str, object],
    policy: ConfidencePolicy,
) -> dict:
    paddle_text = str(paddle.get("text") or "")
    paddle_value = normalize_recognized_answer(CHOICE_NUMBER, paddle_text)
    paddle_score = _number(paddle.get("score"))
    paddle_variant = normalize_recognized_answer(CHOICE_NUMBER, paddle.get("variantText"))
    paddle_variant_score = _number(paddle.get("variantScore"))
    paddle_stable = bool(
        paddle.get("variantAgreed") is True
        and paddle_value
        and paddle_value == paddle_variant
        and paddle_variant_score is not None
        and paddle_variant_score >= policy.choice_paddle_minimum
    )

    digit_value = normalize_recognized_answer(CHOICE_NUMBER, digit.get("text"))
    digit_score = _number(digit.get("score"))
    digit_margin = _number(digit.get("margin"))
    digit_stable = bool(
        digit.get("variantAgreed") is True
        and digit_value
        and digit_score is not None
        and digit_score >= policy.choice_digit_minimum
        and digit_margin is not None
        and digit_margin >= policy.choice_digit_margin_minimum
    )

    confident = digit_stable
    if policy.require_choice_cross_engine_agreement:
        confident = confident and bool(
            paddle_value
            and paddle_score is not None
            and paddle_score >= policy.choice_paddle_minimum
            and (paddle_stable or not policy.require_paddle_variant_agreement)
            and paddle_value == digit_value
        )
    return {
        "questionNo": crop.question_no,
        "rawAnswer": digit_value,
        "confidence": digit_score,
        "confident": confident,
    }


def _build_answer_candidate(
    crop: OcrCrop,
    paddle: Mapping[str, object],
    unimernet: Mapping[str, object],
    formula: Mapping[str, object],
    policy: ConfidencePolicy,
) -> dict:
    primary_text = str(unimernet.get("text") or "")
    primary = canonicalize_answer_text(primary_text)
    token_confidence = _number(unimernet.get("tokenConfidence"))
    variant = canonicalize_answer_text(unimernet.get("variantText"))
    variant_agreed = unimernet.get("variantAgreed") is True
    confident = bool(
        primary
        and _valid_numeric_answer(primary)
        and token_confidence is not None
        and token_confidence >= policy.unimernet_token_minimum
    )
    if policy.require_unimernet_variant_agreement:
        confident = confident and variant_agreed and answer_values_equivalent(primary, variant)

    supporters = 0
    # A second view of the same model is a stability check, not another engine.
    paddle_numeric = canonicalize_answer_text(paddle.get("text"))
    if _valid_numeric_answer(paddle_numeric) and answer_values_equivalent(primary, paddle_numeric):
        supporters += 1
    formula_numeric = canonicalize_answer_text(formula.get("text"))
    if _valid_numeric_answer(formula_numeric) and answer_values_equivalent(primary, formula_numeric):
        supporters += 1
    if policy.require_formula_cross_engine_agreement:
        confident = confident and supporters >= 1
    return {
        "questionNo": crop.question_no,
        "rawAnswer": primary_text,
        "confidence": token_confidence,
        "confident": confident,
    }


def _second_pass_worker(spec: WorkerSpec) -> WorkerSpec:
    environment = dict(spec.environment)
    environment["STUDENT_TEST_OCR_UNIMERNET_SECOND_PASS"] = "1"
    return replace(spec, environment=environment)


def recognize_sheet(
    *,
    crops: Sequence[OcrCrop],
    asset_root: Path,
    paddle_worker: WorkerSpec,
    unimernet_worker: WorkerSpec,
    choice_worker: WorkerSpec | None = None,
    formula_worker: WorkerSpec | None = None,
    policy: ConfidencePolicy | None = None,
) -> dict:
    validated = _validated_crops(crops, asset_root)
    selected_policy = policy or ConfidencePolicy()
    started = time.perf_counter()
    second_response: dict | None = None
    if choice_worker is None or formula_worker is None:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="student-test-ocr-engine") as pool:
            paddle_future = pool.submit(run_json_worker, paddle_worker, validated)
            unimernet_future = pool.submit(run_json_worker, unimernet_worker, validated)
            paddle_response = paddle_future.result()
            unimernet_response = unimernet_future.result()
        paddle_items = _index_worker_items(paddle_response, "paddle")
        unimernet_items = _index_worker_items(unimernet_response, "unimernet")
        candidates = [
            _build_legacy_candidate(
                crop,
                paddle_items[crop.question_no],
                unimernet_items[crop.question_no],
                selected_policy,
            )
            for crop in validated
        ]
        worker_timings = {
            "paddle": {"wallSeconds": paddle_response["wallSeconds"]},
            "unimernet": {"wallSeconds": unimernet_response["wallSeconds"]},
        }
    else:
        choice_crops = tuple(crop for crop in validated if crop.answer_mode == CHOICE_NUMBER)
        answer_crops = tuple(crop for crop in validated if crop.answer_mode == ANSWER_VALUE)
        if not answer_crops and not selected_policy.require_choice_cross_engine_agreement:
            response = run_json_worker(choice_worker, choice_crops)
            items = _index_worker_items(response, "choice_digit", [crop.question_no for crop in choice_crops])
            candidates = [_build_choice_candidate(crop, {}, items[crop.question_no], selected_policy) for crop in choice_crops]
            return {
                **classify_sheet_recognition([crop.answer_mode for crop in validated], candidates),
                "engineSeconds": round(time.perf_counter() - started, 4),
                "workers": {"choice_digit": {"wallSeconds": response["wallSeconds"]}},
            }
        maximum_workers = 2 + int(bool(choice_crops)) + int(bool(answer_crops))
        with ThreadPoolExecutor(max_workers=maximum_workers, thread_name_prefix="student-test-ocr-engine") as pool:
            paddle_future = pool.submit(run_json_worker, paddle_worker, validated)
            choice_future = pool.submit(run_json_worker, choice_worker, choice_crops) if choice_crops else None
            formula_future = pool.submit(run_json_worker, formula_worker, answer_crops) if answer_crops else None
            unimernet_future = pool.submit(run_json_worker, unimernet_worker, answer_crops) if answer_crops else None
            paddle_response = paddle_future.result()
            choice_response = choice_future.result() if choice_future else None
            formula_response = formula_future.result() if formula_future else None
            unimernet_response = unimernet_future.result() if unimernet_future else None
        paddle_items = _index_worker_items(paddle_response, "paddle")
        choice_items = (
            _index_worker_items(choice_response, "choice_digit", [crop.question_no for crop in choice_crops])
            if choice_response is not None
            else {}
        )
        formula_items = (
            _index_worker_items(formula_response, "formula", [crop.question_no for crop in answer_crops])
            if formula_response is not None
            else {}
        )
        unimernet_items = (
            _index_worker_items(unimernet_response, "unimernet", [crop.question_no for crop in answer_crops])
            if unimernet_response is not None
            else {}
        )
        candidates = []
        for crop in validated:
            if crop.answer_mode == CHOICE_NUMBER:
                candidates.append(
                    _build_choice_candidate(
                        crop,
                        paddle_items[crop.question_no],
                        choice_items[crop.question_no],
                        selected_policy,
                    )
                )
            else:
                candidates.append(
                    _build_answer_candidate(
                        crop,
                        paddle_items[crop.question_no],
                        unimernet_items[crop.question_no],
                        formula_items[crop.question_no],
                        selected_policy,
                    )
                )
        worker_timings = {"paddle": {"wallSeconds": paddle_response["wallSeconds"]}}
        if choice_response is not None:
            worker_timings["choice_digit"] = {"wallSeconds": choice_response["wallSeconds"]}
        if formula_response is not None:
            worker_timings["formula"] = {"wallSeconds": formula_response["wallSeconds"]}
        if unimernet_response is not None:
            worker_timings["unimernet"] = {"wallSeconds": unimernet_response["wallSeconds"]}
        uncertain_answer_crops = tuple(
            crop
            for crop, candidate in zip(validated, candidates)
            if crop.answer_mode == ANSWER_VALUE and candidate.get("confident") is not True
        )
        if (
            selected_policy.enable_adaptive_formula_second_pass
            and 1 <= len(uncertain_answer_crops) <= selected_policy.maximum_adaptive_formula_crops
        ):
            second_response = run_json_worker(_second_pass_worker(unimernet_worker), uncertain_answer_crops)
            second_items = _index_worker_items(
                second_response,
                "unimernet",
                [crop.question_no for crop in uncertain_answer_crops],
            )
            candidate_index = {crop.question_no: index for index, crop in enumerate(validated)}
            for crop in uncertain_answer_crops:
                candidates[candidate_index[crop.question_no]] = _build_answer_candidate(
                    crop,
                    paddle_items[crop.question_no],
                    second_items[crop.question_no],
                    formula_items[crop.question_no],
                    selected_policy,
                )
            worker_timings["unimernet_second_pass"] = {"wallSeconds": second_response["wallSeconds"]}
    decision = classify_sheet_recognition([crop.answer_mode for crop in validated], candidates)
    return {
        **decision,
        "engineSeconds": round(time.perf_counter() - started, 4),
        "workers": worker_timings,
    }


def recognize_answer_value_crop(
    *,
    question_no: int,
    image_path: Path,
    asset_root: Path,
    paddle_worker: WorkerSpec,
    unimernet_worker: WorkerSpec,
    formula_worker: WorkerSpec | None = None,
    policy: ConfidencePolicy | None = None,
) -> dict:
    crop = OcrCrop(question_no, ANSWER_VALUE, image_path)
    root = asset_root.resolve()
    path = image_path.resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise OcrEngineError("invalid_crop_path", "question crop path escapes the asset root") from error
    if not 1 <= question_no <= 20 or not path.is_file():
        _fail("invalid_crop_set", "question recapture is invalid")
    selected_policy = policy or ConfidencePolicy()
    started = time.perf_counter()
    second_response: dict | None = None
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="student-test-ocr-recapture") as pool:
        paddle_future = pool.submit(run_json_worker, paddle_worker, (crop,))
        unimernet_future = pool.submit(run_json_worker, unimernet_worker, (crop,))
        formula_future = pool.submit(run_json_worker, formula_worker, (crop,)) if formula_worker else None
        paddle_response = paddle_future.result()
        unimernet_response = unimernet_future.result()
        formula_response = formula_future.result() if formula_future else None
    paddle_items = paddle_response.get("items")
    unimernet_items = unimernet_response.get("items")
    if (
        not isinstance(paddle_items, list)
        or len(paddle_items) != 1
        or not isinstance(paddle_items[0], dict)
        or paddle_items[0].get("questionNo") != question_no
        or not isinstance(unimernet_items, list)
        or len(unimernet_items) != 1
        or not isinstance(unimernet_items[0], dict)
        or unimernet_items[0].get("questionNo") != question_no
    ):
        _fail("invalid_worker_response", "question recapture worker response is invalid")
    if formula_response is None:
        candidate = _build_legacy_candidate(crop, paddle_items[0], unimernet_items[0], selected_policy)
    else:
        formula_items = formula_response.get("items")
        if (
            not isinstance(formula_items, list)
            or len(formula_items) != 1
            or not isinstance(formula_items[0], dict)
            or formula_items[0].get("questionNo") != question_no
        ):
            _fail("invalid_worker_response", "question recapture formula response is invalid")
        candidate = _build_answer_candidate(
            crop,
            paddle_items[0],
            unimernet_items[0],
            formula_items[0],
            selected_policy,
        )
        if selected_policy.enable_adaptive_formula_second_pass and candidate.get("confident") is not True:
            second_response = run_json_worker(_second_pass_worker(unimernet_worker), (crop,))
            second_items = _index_worker_items(second_response, "unimernet", (question_no,))
            candidate = _build_answer_candidate(
                crop,
                paddle_items[0],
                second_items[question_no],
                formula_items[0],
                selected_policy,
            )
    workers = {
        "paddle": {"wallSeconds": paddle_response["wallSeconds"]},
        "unimernet": {"wallSeconds": unimernet_response["wallSeconds"]},
    }
    if formula_response is not None:
        workers["formula"] = {"wallSeconds": formula_response["wallSeconds"]}
    if second_response is not None:
        workers["unimernet_second_pass"] = {"wallSeconds": second_response["wallSeconds"]}
    return {
        **candidate,
        "engineSeconds": round(time.perf_counter() - started, 4),
        "workers": workers,
    }
