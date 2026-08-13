from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TypeAlias, assert_never

from tools.subjective_sheet_lab.gemini_provider_response import ResponseShapeFailure, ResponseText, response_text_result
from tools.subjective_sheet_lab.ocr_answer_mode_policy import answer_mode_for_question
from tools.subjective_sheet_lab.phase2e_stable_cache import deidentified_png_bytes

# noqa: SIZE_OK - legacy lab CLI provider; response shape parsing is split out for new work.

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

DEFAULT_MODEL: Final[str] = "gemini-2.5-flash-lite"
GEMINI_ENDPOINT: Final[str] = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
KEY_NAME: Final[str] = "GEMINI_API_KEY"
SUPPORTED_SUFFIXES: Final[set[str]] = {".png", ".jpg", ".jpeg", ".webp"}
QUESTION_RE: Final[re.Pattern[str]] = re.compile(r"q(\d{3})\.(?:png|jpe?g|webp)$", re.IGNORECASE)
CONTACT_RANGE_RE: Final[re.Pattern[str]] = re.compile(r"q(\d{3})\D+q(\d{3})", re.IGNORECASE)
JSON_BLOCK_RE: Final[re.Pattern[str]] = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
CACHE_FILE_NAME: Final[str] = "gemini_provider_cache.json"
CACHE_STATUS_KEY: Final[str] = "cache_status"
CACHE_STATUS_RECOGNIZED: Final[str] = "completed_recognized"
CACHE_STATUS_UNRESOLVED: Final[str] = "completed_unresolved"


@dataclass(frozen=True, slots=True)
class CropImage:
    question: int
    path: Path
    mime_type: str
    data_base64: str


@dataclass(frozen=True, slots=True)
class ContactImage:
    path: Path
    mime_type: str
    data_base64: str
    questions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RecognizedItem:
    question: int
    recognized: str


class GeminiProviderError(Exception):
    def __init__(self, message: str, *, reason: str = "provider_error", diagnostic: JsonObject | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.diagnostic = {} if diagnostic is None else dict(diagnostic)


def main() -> int:
    try:
        config = parse_args()
        key = read_gemini_key()
        items = recognize_from_config(config, key)
        write_recognized_json(config.out_path, items)
    except GeminiProviderError as exc:
        sys.stderr.write(f"ERROR: {exc.message}\n")
        return 2
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            sync_output_from_cache(config)
            write_error_report(config, exc)
            sys.stderr.write(f"ERROR: Gemini API quota exhausted. Wrote {error_report_path(config)}\n")
        else:
            sys.stderr.write(f"ERROR: Gemini API returned HTTP {exc.code}: {safe_http_error_text(exc)}\n")
        return 3
    except urllib.error.URLError as exc:
        sys.stderr.write(f"ERROR: Gemini API request failed: {exc.reason}\n")
        return 3
    except TimeoutError as exc:
        sys.stderr.write(f"ERROR: Gemini API request timed out: {exc}\n")
        return 3
    return 0


@dataclass(frozen=True, slots=True)
class CliConfig:
    crop_dir: Path | None
    contact_dir: Path | None
    image_files: tuple[Path, ...]
    out_path: Path
    model: str
    resume: bool
    max_calls: int | None
    test_id: str | None = None
    numeric_only: bool = False


def parse_args() -> CliConfig:
    parser = argparse.ArgumentParser(description="Recognize subjective answer crops with Gemini Vision.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--crop-dir", type=Path)
    source.add_argument("--contact-dir", type=Path)
    source.add_argument("--image-files", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--test-id", default=None)
    args = parser.parse_args()
    if args.max_calls is not None and int(args.max_calls) < 1:
        parser.error("--max-calls must be 1 or greater")
    return CliConfig(
        crop_dir=args.crop_dir,
        contact_dir=args.contact_dir,
        image_files=tuple(args.image_files or ()),
        out_path=args.out,
        model=str(args.model),
        resume=bool(args.resume),
        max_calls=int(args.max_calls) if args.max_calls is not None else None,
        test_id=str(args.test_id) if args.test_id else None,
        numeric_only=False,
    )


def read_gemini_key() -> str:
    env_path = find_env_file()
    if env_path is not None:
        values = read_env_values(env_path)
        env_file_key = values.get(KEY_NAME, "").strip()
        if env_file_key:
            return env_file_key

    environment_key = os.environ.get(KEY_NAME, "").strip()
    if environment_key:
        return environment_key

    raise GeminiProviderError(f"{KEY_NAME} is missing. Create a .env file containing {KEY_NAME}=... or set {KEY_NAME}.")


def find_env_file() -> Path | None:
    candidates = [Path.cwd(), Path(__file__).resolve().parent]
    for base in candidates:
        for path in (base, *base.parents):
            env_path = path / ".env"
            if env_path.is_file():
                return env_path
    return None


def read_env_values(path: Path) -> dict[str, str]:
    try:
        from dotenv import dotenv_values
    except ModuleNotFoundError:
        return read_env_values_fallback(path)
    loaded = dotenv_values(path)
    value = loaded.get(KEY_NAME)
    return {KEY_NAME: str(value or "")}


def read_env_values_fallback(path: Path) -> dict[str, str]:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, value = stripped.partition("=")
        if separator and name.strip() == KEY_NAME:
            return {KEY_NAME: clean_env_value(value)}
    return {}


def clean_env_value(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def load_crop_images(crop_dir: Path) -> list[CropImage]:
    if not crop_dir.is_dir():
        raise GeminiProviderError(f"crop directory not found: {crop_dir}")
    paths = sorted(path for path in crop_dir.iterdir() if path.suffix.lower() in SUPPORTED_SUFFIXES)
    crops = [crop_image_from_path(path) for path in paths if question_from_path(path) is not None]
    if not crops:
        raise GeminiProviderError(f"no q001-style crop images found in {crop_dir}")
    return crops


def crop_image_from_path(path: Path) -> CropImage:
    question = question_from_path(path)
    if question is None:
        raise GeminiProviderError(f"invalid crop filename: {path.name}")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    data_base64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return CropImage(question=question, path=path, mime_type=mime_type, data_base64=data_base64)


def question_from_path(path: Path) -> int | None:
    match = QUESTION_RE.fullmatch(path.name)
    if match is None:
        return None
    return int(match.group(1))


def recognize_from_config(config: CliConfig, api_key: str) -> list[RecognizedItem]:
    if config.crop_dir is not None:
        crops = load_crop_images(config.crop_dir)
        return recognize_crops(crops, api_key, config.model, config.numeric_only)

    contacts = load_contact_images(config)
    return recognize_contact_sheets(contacts, api_key, config)


def recognize_crops(crops: list[CropImage], api_key: str, model: str, numeric_only: bool = False) -> list[RecognizedItem]:
    payload = build_gemini_payload(crops, numeric_only)
    response = post_gemini(payload, api_key, model)
    text = extract_response_text(response)
    return parse_recognized_items(text, crops)


def build_gemini_payload(crops: list[CropImage], numeric_only: bool = False) -> dict[str, JsonValue]:
    parts: list[JsonValue] = [{"text": prompt_text(crops, numeric_only)}]
    for crop in crops:
        parts.append({"text": f"question={crop.question:03d}, filename={crop.path.name}"})
        parts.append({"inline_data": {"mime_type": crop.mime_type, "data": crop.data_base64}})
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "response_mime_type": "application/json",
        },
    }


def prompt_text(crops: list[CropImage], numeric_only: bool = False) -> str:
    questions = ", ".join(f"{crop.question}" for crop in crops)
    if numeric_only:
        return (
            "Read only the handwritten numeric answer in each crop image. "
            "Ignore boxes, borders, printed labels, file names, and all non-answer marks. "
            "Every recognized value must be an ASCII decimal integer made only of digits 0 through 9. "
            "Never output Korean choices, letters, operators, signs, fractions, equations, spaces, or explanations. "
            "Do not solve, correct, infer, normalize, or guess. If a digit sequence is not clearly readable, recognized must be ?. "
            f"Return JSON only for questions: {questions}. "
            "The JSON schema must be exactly: "
            "{\"items\":[{\"question\":1,\"recognized\":\"...\"}]}"
        )
    return (
        "Read only the handwritten math answer in each crop image. "
        "Ignore boxes, borders, printed labels, and file names. "
        "Do not solve, correct, infer, or normalize beyond transcription. "
        "If an answer is unclear, return ?. "
        "If erased, crossed-out, or overwritten traces exist but one visible digit or number is clearly final, return that digit or number. "
        "Do not return ? only because old strokes, smudges, or crossed-out marks are nearby when a final digit is clearly readable. "
        "If multiple similarly visible final candidates remain, return ?. "
        "Preserve Korean choices \u3131, \u3134, \u3137, \u3139. Preserve +, -, \u00b1, <, <=, >, >=. "
        "Use fractions like 1/2, roots like sqrt(2), and exponents like x^2. "
        f"Return JSON only for questions: {questions}. "
        "The JSON schema must be exactly: "
        "{\"items\":[{\"question\":1,\"recognized\":\"...\"}]}"
    )


def load_contact_images(config: CliConfig) -> list[ContactImage]:
    paths = contact_image_paths(config)
    contacts = [contact_image_from_path(path) for path in paths]
    if not contacts:
        raise GeminiProviderError("no contact sheet images found")
    return contacts


def contact_image_paths(config: CliConfig) -> list[Path]:
    if config.contact_dir is not None:
        if not config.contact_dir.is_dir():
            raise GeminiProviderError(f"contact directory not found: {config.contact_dir}")
        return sorted(path for path in config.contact_dir.iterdir() if path.suffix.lower() in SUPPORTED_SUFFIXES)
    return list(config.image_files)


def contact_image_from_path(path: Path) -> ContactImage:
    if not path.is_file():
        raise GeminiProviderError(f"contact sheet image not found: {path}")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise GeminiProviderError(f"unsupported contact sheet image type: {path.name}")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    data_base64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return ContactImage(path=path, mime_type=mime_type, data_base64=data_base64, questions=questions_from_contact_path(path))


def questions_from_contact_path(path: Path) -> tuple[int, ...]:
    match = CONTACT_RANGE_RE.search(path.stem)
    if match is None:
        return ()
    start = int(match.group(1))
    end = int(match.group(2))
    if start > end:
        start, end = end, start
    return tuple(range(start, end + 1))


def recognize_contact_sheets(contacts: list[ContactImage], api_key: str, config: CliConfig) -> list[RecognizedItem]:
    cached = load_cached_items(config) if config.resume else {}
    recognized_by_question = dict(cached)
    if config.resume and recognized_by_question:
        return items_for_contacts(contacts, recognized_by_question)
    pending_contacts = contacts_pending_recognition(contacts, recognized_by_question, config.resume)
    if not pending_contacts:
        return items_for_contacts(contacts, recognized_by_question)
    if config.max_calls is not None and config.max_calls < 1:
        return items_for_contacts(contacts, recognized_by_question)

    payload = build_contact_payload(pending_contacts, config.test_id, config.numeric_only)
    response = post_gemini(payload, api_key, config.model)
    text = extract_response_text(response)
    for item in parse_contact_items(text, pending_contacts):
        recognized_by_question[item.question] = item.recognized
    for question in known_contact_questions(contacts):
        recognized_by_question.setdefault(question, "?")
    write_contact_cache(config, contacts, recognized_by_question)
    return items_for_contacts(contacts, recognized_by_question)


def contacts_pending_recognition(contacts: list[ContactImage], recognized_by_question: dict[int, str], resume: bool) -> list[ContactImage]:
    if not resume:
        return contacts
    return [contact for contact in contacts if not contact.questions or not all(question in recognized_by_question for question in contact.questions)]


def eligible_second_pass_questions(
    expected_questions: Iterable[int],
    recognized_by_question: Mapping[int, str],
    *,
    low_confidence_questions: Iterable[int] = (),
) -> tuple[int, ...]:
    expected = tuple(sorted(set(expected_questions)))
    if any(question < 1 or question > 20 for question in expected):
        raise GeminiProviderError("second-pass questions must be in 1..20", reason="provider_input_rejected")
    low_confidence = set(low_confidence_questions)
    if any(question < 1 or question > 20 for question in low_confidence):
        raise GeminiProviderError("low-confidence questions must be in 1..20", reason="provider_input_rejected")
    return tuple(
        question
        for question in expected
        if question in low_confidence or not recognized_by_question.get(question, "").strip() or recognized_by_question.get(question, "").strip() == "?"
    )


def recognize_eligible_second_pass_crops(
    crop_dir: Path,
    eligible_questions: Iterable[int],
    api_key: str,
    model: str,
    *,
    numeric_only: bool = False,
) -> list[RecognizedItem]:
    questions = tuple(sorted(set(eligible_questions)))
    if not questions:
        return []
    crops = load_deidentified_second_pass_crops(crop_dir, questions)
    return recognize_crops(crops, api_key, model, numeric_only)


def load_deidentified_second_pass_crops(crop_dir: Path, questions: tuple[int, ...]) -> list[CropImage]:
    if not crop_dir.is_dir():
        raise GeminiProviderError("second-pass crop directory not found", reason="provider_input_rejected")
    crops: list[CropImage] = []
    for question in questions:
        if question < 1 or question > 20:
            raise GeminiProviderError("second-pass question must be in 1..20", reason="provider_input_rejected")
        source = crop_dir / f"q{question:03d}.png"
        if not source.is_file():
            raise GeminiProviderError("eligible second-pass crop is missing", reason="provider_input_rejected")
        try:
            data = deidentified_png_bytes(source)
        except OSError as exc:
            raise GeminiProviderError("eligible second-pass crop is not a safe PNG", reason="provider_input_rejected") from exc
        crops.append(
            CropImage(
                question=question,
                path=Path(f"answer_sheet_q{question:03d}.png"),
                mime_type="image/png",
                data_base64=base64.b64encode(data).decode("ascii"),
            )
        )
    return crops


def build_contact_payload(contacts: list[ContactImage], test_id: str | None = None, numeric_only: bool = False) -> dict[str, JsonValue]:
    parts: list[JsonValue] = [{"text": contact_prompt_text(contacts, test_id, numeric_only)}]
    for contact in contacts:
        label = question_label(contact.questions)
        parts.append({"text": f"contact_sheet={contact.path.name}, questions={label}"})
        parts.append({"inline_data": {"mime_type": contact.mime_type, "data": contact.data_base64}})
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "response_mime_type": "application/json",
        },
    }


def contact_prompt_text(contacts: list[ContactImage], test_id: str | None = None, numeric_only: bool = False) -> str:
    questions = question_label(known_contact_questions(contacts))
    if numeric_only:
        return (
            "Read only the handwritten numeric answer in each row of these contact sheet images. "
            "The large original crop is the primary evidence; the enhanced crop is only secondary reference. "
            "Ignore borders, boxes, labels, filenames, crop artifacts, and cancelled marks. "
            "Every recognized value must be an ASCII decimal integer made only of digits 0 through 9. "
            "Never output Korean choices, letters, operators, signs, fractions, equations, spaces, or explanations. "
            "Do not solve, correct, infer, normalize, or guess. If a digit sequence is unclear or variants disagree, recognized must be ?. "
            f"Return JSON only for questions: {questions}. "
            "The JSON schema must be exactly: "
            "{\"items\":[{\"question\":1,\"recognized\":\"...\"}]}"
        )
    mode_guidance = answer_mode_prompt_guidance(known_contact_questions(contacts), test_id)
    return (
        "Read only the handwritten math answers in these contact sheet images. "
        "Each row is one question. The large original crop is the primary evidence; a smaller enhanced crop may be present only as secondary reference. "
        "Ignore borders, boxes, printed labels, filenames, and crop artifacts. "
        "Do not solve, correct, infer, normalize, or guess. If ambiguous, recognized must be ?. "
        "If erased, crossed-out, or overwritten traces exist but one visible digit or number is clearly final, recognized must be that digit or number. "
        "Do not set recognized to ? only because old strokes, smudges, or crossed-out marks are nearby when a final digit is clearly readable. "
        "If multiple similarly visible final candidates remain, recognized must be ?. "
        "Preserve +, -, \u00b1, <, <=, >, >= exactly. Distinguish 0/O and 1/7. "
        "Korean choices \u3131, \u3134, \u3137, \u3139 are valid answers; do not convert them to 7, C, 4, 2, L, or Latin letters. "
        "Do not confuse x and n; if x/n is ambiguous, recognized must be ?. "
        "Do not confuse 6 and 0; if 6/0 is ambiguous, recognized must be ?. "
        "Use the original crop as the primary evidence; the enhanced crop is only a secondary reference. "
        "The enhanced crop may distort strokes or make gaps look closed or open. "
        "If original and enhanced disagree, do not guess; recognized must be ?. "
        f"{mode_guidance}"
        "Do not infer an equals sign from an arrow-like stroke. "
        "Read = only when two short parallel horizontal strokes are clearly visible. "
        "If an answer contains a variable and equals sign, such as x=2, preserve the variable and equals sign. "
        "Read equation forms such as x=2 only when the variable, equals sign, and number are all clearly visible. "
        "If an answer looks like a single digit but has a variable or equals sign before it, include those symbols. "
        "If only part of an equation is visible, write only the visible part or ?. "
        "Write fractions as 1/2, roots as sqrt(...), and exponents with ^. "
        f"Return JSON only for questions: {questions}. "
        "The JSON schema must be exactly: "
        "{\"items\":[{\"question\":1,\"recognized\":\"...\"}]}"
    )


def answer_mode_prompt_guidance(questions: tuple[int, ...], test_id: str | None) -> str:
    if test_id is None:
        return (
            "For choice-number answers, return 1, 2, 3, 4, or 5 only when a single choice number is clearly written. "
            "For answer-value answers, return the final visible number, fraction, sign, root, or expression only; do not include work. "
        )
    choice_questions = tuple(question for question in questions if answer_mode_for_question(test_id, question) == "choice_number")
    value_questions = tuple(question for question in questions if answer_mode_for_question(test_id, question) == "answer_value")
    if not choice_questions and not value_questions:
        return (
            "The test-specific answer modes are not verified. Return only clear final visible handwriting and use ? for uncertainty. "
        )
    return (
        f"Question mode hints for {test_id}: choice_number questions are {question_label(choice_questions)}; answer_value questions are {question_label(value_questions)}. "
        "For choice_number questions, return 1, 2, 3, 4, or 5 only when exactly one choice number is clearly written; do not guess a valid number from letters, equations, or expressions. "
        "For answer_value questions, return the final visible numeric value, fraction, sign, root, or expression only; do not include work or multiple candidates. "
    )


def known_contact_questions(contacts: list[ContactImage]) -> tuple[int, ...]:
    questions: list[int] = []
    for contact in contacts:
        questions.extend(contact.questions)
    return tuple(dict.fromkeys(sorted(questions)))


def question_label(questions: tuple[int, ...]) -> str:
    if not questions:
        return "all visible q-numbered rows"
    return ", ".join(str(question) for question in questions)


def parse_contact_items(text: str, contacts: list[ContactImage]) -> list[RecognizedItem]:
    payload = parse_json_text(text)
    items_value = payload.get("items")
    if not isinstance(items_value, list):
        raise GeminiProviderError("Gemini JSON did not include items list", reason="provider_malformed_items")
    recognized_by_question: dict[int, str] = {}
    for value in items_value:
        item = parse_item(value)
        recognized_by_question[item.question] = item.recognized
    questions = known_contact_questions(contacts)
    if questions:
        return [RecognizedItem(question=question, recognized=recognized_by_question[question]) for question in questions if question in recognized_by_question]
    return [RecognizedItem(question=question, recognized=recognized_by_question[question]) for question in sorted(recognized_by_question)]


def load_cached_items(config: CliConfig) -> dict[int, str]:
    path = contact_cache_path(config)
    if not path.is_file() and config.out_path.is_file():
        path = config.out_path
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    items_value = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items_value, list):
        return {}
    cached: dict[int, str] = {}
    for value in items_value:
        item = parse_item(value)
        if item.recognized and item.recognized != "?":
            cached[item.question] = item.recognized
        elif item.recognized == "?" and cache_item_status(value) == CACHE_STATUS_UNRESOLVED:
            cached[item.question] = item.recognized
    return cached


def write_contact_cache(config: CliConfig, contacts: list[ContactImage], recognized_by_question: dict[int, str]) -> None:
    path = contact_cache_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": config.model,
        "timestamp": datetime.now(UTC).isoformat(),
        "input_files": [str(contact.path) for contact in contacts],
        "items": [
            {
                "question": question,
                "recognized": completed_recognized_text(recognized),
                CACHE_STATUS_KEY: completed_cache_status(recognized),
            }
            for question, recognized in sorted(recognized_by_question.items())
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cache_item_status(value: JsonValue) -> str:
    if not isinstance(value, dict):
        return ""
    status = value.get(CACHE_STATUS_KEY)
    return status if isinstance(status, str) else ""


def completed_recognized_text(recognized: str) -> str:
    text = recognized.strip()
    return text if text else "?"


def completed_cache_status(recognized: str) -> str:
    text = completed_recognized_text(recognized)
    if text != "?":
        return CACHE_STATUS_RECOGNIZED
    return CACHE_STATUS_UNRESOLVED


def contact_cache_path(config: CliConfig) -> Path:
    return config.out_path.parent / CACHE_FILE_NAME


def items_for_contacts(contacts: list[ContactImage], recognized_by_question: dict[int, str]) -> list[RecognizedItem]:
    questions = known_contact_questions(contacts)
    if questions:
        return [RecognizedItem(question=question, recognized=recognized_by_question.get(question, "?")) for question in questions]
    return [RecognizedItem(question=question, recognized=recognized_by_question[question]) for question in sorted(recognized_by_question)]


def post_gemini(payload: dict[str, JsonValue], api_key: str, model: str) -> dict[str, JsonValue]:
    url = GEMINI_ENDPOINT.format(model=model)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        decoded = response.read().decode("utf-8")
    payload_value = json.loads(decoded)
    if not isinstance(payload_value, dict):
        raise GeminiProviderError("Gemini API response was not a JSON object")
    return payload_value


def extract_response_text(response: dict[str, JsonValue]) -> str:
    result = response_text_result(response)
    match result:
        case ResponseText(text=text):
            return text
        case ResponseShapeFailure(reason=reason, message=message, diagnostic=diagnostic):
            raise GeminiProviderError(message, reason=reason, diagnostic=diagnostic)
        case unreachable:
            assert_never(unreachable)


def parse_recognized_items(text: str, crops: list[CropImage]) -> list[RecognizedItem]:
    payload = parse_json_text(text)
    items_value = payload.get("items")
    if not isinstance(items_value, list):
        raise GeminiProviderError("Gemini JSON did not include items list", reason="provider_malformed_items")
    recognized_by_question: dict[int, str] = {}
    for value in items_value:
        item = parse_item(value)
        recognized_by_question[item.question] = item.recognized
    return [RecognizedItem(question=crop.question, recognized=recognized_by_question.get(crop.question, "?")) for crop in crops]


def parse_json_text(text: str) -> dict[str, JsonValue]:
    stripped = text.strip()
    match = JSON_BLOCK_RE.search(stripped)
    candidate = match.group(1) if match is not None else stripped
    try:
        decoded = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise GeminiProviderError(f"Gemini text was not valid JSON: {exc}", reason="provider_invalid_json") from exc
    if not isinstance(decoded, dict):
        raise GeminiProviderError("Gemini JSON root was not an object", reason="provider_malformed_items")
    return decoded


def parse_item(value: JsonValue) -> RecognizedItem:
    if not isinstance(value, dict):
        raise GeminiProviderError("Gemini item was not an object", reason="provider_malformed_items")
    question_value = value.get("question")
    recognized_value = value.get("recognized")
    if not isinstance(question_value, int):
        raise GeminiProviderError("Gemini item question was not an integer", reason="provider_malformed_items")
    if not isinstance(recognized_value, str):
        raise GeminiProviderError("Gemini item recognized value was not a string", reason="provider_malformed_items")
    return RecognizedItem(question=question_value, recognized=recognized_value.strip())


def write_recognized_json(path: Path, items: list[RecognizedItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": [{"question": item.question, "recognized": item.recognized} for item in items]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sync_output_from_cache(config: CliConfig) -> bool:
    if config.crop_dir is not None:
        return False
    try:
        cached = load_cached_items(config)
        questions: list[int] = []
        for path in contact_image_paths(config):
            questions.extend(questions_from_contact_path(path))
    except (GeminiProviderError, json.JSONDecodeError, OSError):
        return False
    if not cached or not questions:
        return False
    items = [RecognizedItem(question=question, recognized=cached.get(question, "?")) for question in dict.fromkeys(questions)]
    write_recognized_json(config.out_path, items)
    return True


def safe_http_error_text(error: urllib.error.HTTPError) -> str:
    raw = error.read().decode("utf-8", errors="replace")
    return raw[:1000]


def error_report_path(config: CliConfig) -> Path:
    return config.out_path.parent / "error_report.json"


def write_error_report(config: CliConfig, error: urllib.error.HTTPError) -> None:
    body = safe_http_error_text(error)
    report = {
        "status": "quota_exhausted",
        "http_status": 429,
        "model": config.model,
        "timestamp": datetime.now(UTC).isoformat(),
        "attempted_input_files": attempted_input_files(config),
        "message": summarize_quota_message(body),
    }
    path = error_report_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def attempted_input_files(config: CliConfig) -> list[str]:
    if config.crop_dir is not None:
        return [str(path) for path in sorted(config.crop_dir.iterdir()) if path.suffix.lower() in SUPPORTED_SUFFIXES]
    return [str(path) for path in contact_image_paths(config)]


def summarize_quota_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        match = re.search(r'"message"\s*:\s*"(.+?)"', body, flags=re.DOTALL)
        if match is not None:
            return match.group(1).splitlines()[0][:500]
        return body[:500]
    error_value = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error_value, dict):
        return body[:500]
    message_value = error_value.get("message")
    if not isinstance(message_value, str):
        return body[:500]
    return message_value.splitlines()[0][:500]


if __name__ == "__main__":
    raise SystemExit(main())
