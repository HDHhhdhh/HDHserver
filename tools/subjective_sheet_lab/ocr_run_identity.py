"""Versioned, key-free identity shared by preparation, provider, cache and review."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path

IDENTITY_SCHEMA = "ocr.run.identity.v1"
RECOGNITION_SCHEMA = "ocr.recognition.cache.v1"
REVIEW_SCHEMA = "ocr.review.run.v1"
FORM_ID = "answer_sheet_20_v1"
PREPROCESSING_VERSION = "crop_contact_v1"
PROMPT_VERSION = "image_candidates_v2"
QUESTIONS = tuple(range(1, 21))
FIELDS = frozenset({"schema", "photo_sha256", "test_id", "round", "form_id", "model",
                    "prompt_version", "preprocessing_version", "question_numbers", "identity_sha256"})


class RunIdentityError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", value):
        raise RunIdentityError(f"{field} must be a nonempty safe identifier")
    return value


def build_run_identity(photo_bytes: bytes, *, test_id: str, round_no: str | int,
                       form_id: str, model: str, prompt_version: str,
                       preprocessing_version: str,
                       question_numbers: Iterable[int] = QUESTIONS) -> dict:
    if not isinstance(photo_bytes, bytes) or not photo_bytes:
        raise RunIdentityError("source photograph bytes are required")
    if isinstance(round_no, bool) or not isinstance(round_no, (int, str)):
        raise RunIdentityError("round must be a positive decimal integer")
    round_text = str(round_no)
    if not re.fullmatch(r"[1-9][0-9]*", round_text):
        raise RunIdentityError("round must be a positive decimal integer")
    numbers = list(question_numbers)
    if any(type(number) is not int for number in numbers) or numbers != list(QUESTIONS):
        raise RunIdentityError("question_numbers must be ordered 1 through 20 exactly once")
    data = {"schema": IDENTITY_SCHEMA, "photo_sha256": hashlib.sha256(photo_bytes).hexdigest(),
            "test_id": _text(test_id, "test_id"), "round": round_text,
            "form_id": _text(form_id, "form_id"), "model": _text(model, "model"),
            "prompt_version": _text(prompt_version, "prompt_version"),
            "preprocessing_version": _text(preprocessing_version, "preprocessing_version"),
            "question_numbers": numbers}
    data["identity_sha256"] = hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
    return data


def validate_run_identity(value: object, *, expected: dict | None = None) -> dict:
    if not isinstance(value, dict) or set(value) != FIELDS or value.get("schema") != IDENTITY_SCHEMA:
        raise RunIdentityError("versioned run identity is missing or unsupported")
    if not re.fullmatch(r"[a-f0-9]{64}", str(value.get("photo_sha256", ""))):
        raise RunIdentityError("photo_sha256 must be SHA-256")
    for field in ("test_id", "form_id", "model", "prompt_version", "preprocessing_version"):
        _text(value[field], field)
    if not isinstance(value["round"], str) or not re.fullmatch(r"[1-9][0-9]*", value["round"]):
        raise RunIdentityError("round must be canonical positive decimal text")
    numbers = value["question_numbers"]
    if not isinstance(numbers, list) or any(type(number) is not int for number in numbers) or numbers != list(QUESTIONS):
        raise RunIdentityError("question_numbers must be ordered 1 through 20 exactly once")
    unsigned = {key: child for key, child in value.items() if key != "identity_sha256"}
    digest = hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()
    if value.get("identity_sha256") != digest:
        raise RunIdentityError("run identity checksum mismatch")
    if expected is not None:
        checked = validate_run_identity(expected)
        if canonical_json(value) != canonical_json(checked):
            raise RunIdentityError("cache identity does not match the current photograph/run")
    return dict(value)


def identity_for_request(request: object, *, model: str, prompt_version: str,
                         form_id: str = FORM_ID,
                         preprocessing_version: str = PREPROCESSING_VERSION) -> dict:
    image = Path(request.pipeline_result.source_image)
    return build_run_identity(image.read_bytes(), test_id=request.test_id,
                              round_no=request.round_no, form_id=form_id,
                              model=model, prompt_version=prompt_version,
                              preprocessing_version=preprocessing_version)
