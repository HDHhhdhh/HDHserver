from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

DEFAULT_MODEL: Final[str] = "gemini-2.5-flash-lite"
GEMINI_ENDPOINT: Final[str] = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
KEY_NAME: Final[str] = "GEMINI_API_KEY"
SUPPORTED_SUFFIXES: Final[set[str]] = {".png", ".jpg", ".jpeg", ".webp"}
QUESTION_RE: Final[re.Pattern[str]] = re.compile(r"q(\d{3})\.(?:png|jpe?g|webp)$", re.IGNORECASE)
CONTACT_RANGE_RE: Final[re.Pattern[str]] = re.compile(r"q(\d{3})\D+q(\d{3})", re.IGNORECASE)
JSON_BLOCK_RE: Final[re.Pattern[str]] = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
MAX_RETRY_ATTEMPTS: Final[int] = 2
RETRY_BACKOFF_SECONDS: Final[float] = 4.0
CACHE_FILE_NAME: Final[str] = "gemini_provider_cache.json"


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
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


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
        return recognize_crops(crops, api_key, config.model)

    contacts = load_contact_images(config)
    return recognize_contact_sheets(contacts, api_key, config)


def recognize_crops(crops: list[CropImage], api_key: str, model: str) -> list[RecognizedItem]:
    payload = build_gemini_payload(crops)
    response = post_gemini(payload, api_key, model)
    text = extract_response_text(response)
    return parse_recognized_items(text, crops)


def build_gemini_payload(crops: list[CropImage]) -> dict[str, JsonValue]:
    parts: list[JsonValue] = [{"text": prompt_text(crops)}]
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


def prompt_text(crops: list[CropImage]) -> str:
    questions = ", ".join(f"{crop.question}" for crop in crops)
    return (
        "Read only the handwritten math answer in each crop image. "
        "Ignore boxes, borders, printed labels, and file names. "
        "Do not solve, correct, infer, or normalize beyond transcription. "
        "If an answer is unclear, return ?. "
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
    calls_made = 0

    for contact in contacts:
        questions = contact.questions
        if config.resume and questions and all(question in recognized_by_question for question in questions):
            continue
        if config.max_calls is not None and calls_made >= config.max_calls:
            break

        payload = build_contact_payload([contact])
        response = post_gemini(payload, api_key, config.model)
        text = extract_response_text(response)
        for item in parse_contact_items(text, [contact]):
            recognized_by_question[item.question] = item.recognized
        calls_made += 1
        write_contact_cache(config, contacts, recognized_by_question)

    return items_for_contacts(contacts, recognized_by_question)


def build_contact_payload(contacts: list[ContactImage]) -> dict[str, JsonValue]:
    parts: list[JsonValue] = [{"text": contact_prompt_text(contacts)}]
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


def contact_prompt_text(contacts: list[ContactImage]) -> str:
    questions = question_label(known_contact_questions(contacts))
    return (
        "Read only the handwritten math answers in these contact sheet images. "
        "Each row is one question and may show original and enhanced versions of the same answer; use both views together. "
        "Ignore borders, boxes, printed labels, filenames, and crop artifacts. "
        "Do not solve, correct, infer, normalize, or guess. If ambiguous, recognized must be ?. "
        "Preserve +, -, \u00b1, <, <=, >, >= exactly. Distinguish 0/O and 1/7. "
        "Korean choices \u3131, \u3134, \u3137, \u3139 are valid answers; do not convert them to 7, C, 4, 2, L, or Latin letters. "
        "Do not confuse x and n; if x/n is ambiguous, recognized must be ?. "
        "Do not confuse 6 and 0; if 6/0 is ambiguous, recognized must be ?. "
        "Use the original crop as the primary evidence; the enhanced crop is only a secondary reference. "
        "The enhanced crop may distort strokes or make gaps look closed or open. "
        "If original and enhanced disagree, do not guess; recognized must be ?. "
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
        raise GeminiProviderError("Gemini JSON did not include items list")
    recognized_by_question: dict[int, str] = {}
    for value in items_value:
        item = parse_item(value)
        recognized_by_question[item.question] = item.recognized
    questions = known_contact_questions(contacts)
    if questions:
        return [RecognizedItem(question=question, recognized=recognized_by_question.get(question, "?")) for question in questions]
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
    return cached


def write_contact_cache(config: CliConfig, contacts: list[ContactImage], recognized_by_question: dict[int, str]) -> None:
    path = contact_cache_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": config.model,
        "timestamp": datetime.now(UTC).isoformat(),
        "input_files": [str(contact.path) for contact in contacts],
        "items": [
            {"question": item.question, "recognized": item.recognized}
            for item in items_for_contacts(contacts, recognized_by_question)
            if item.recognized and item.recognized != "?"
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    for attempt in range(MAX_RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                decoded = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 503 or attempt >= MAX_RETRY_ATTEMPTS:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    payload_value = json.loads(decoded)
    if not isinstance(payload_value, dict):
        raise GeminiProviderError("Gemini API response was not a JSON object")
    return payload_value


def extract_response_text(response: dict[str, JsonValue]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise GeminiProviderError("Gemini API response did not include candidates")
    first = candidates[0]
    if not isinstance(first, dict):
        raise GeminiProviderError("Gemini API candidate was not an object")
    content = first.get("content")
    if not isinstance(content, dict):
        raise GeminiProviderError("Gemini API candidate did not include content")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise GeminiProviderError("Gemini API content did not include parts")
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            value = part.get("text")
            if isinstance(value, str):
                texts.append(value)
    if not texts:
        raise GeminiProviderError("Gemini API response did not include text")
    return "\n".join(texts)


def parse_recognized_items(text: str, crops: list[CropImage]) -> list[RecognizedItem]:
    payload = parse_json_text(text)
    items_value = payload.get("items")
    if not isinstance(items_value, list):
        raise GeminiProviderError("Gemini JSON did not include items list")
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
        raise GeminiProviderError(f"Gemini text was not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise GeminiProviderError("Gemini JSON root was not an object")
    return decoded


def parse_item(value: JsonValue) -> RecognizedItem:
    if not isinstance(value, dict):
        raise GeminiProviderError("Gemini item was not an object")
    question_value = value.get("question")
    recognized_value = value.get("recognized")
    if not isinstance(question_value, int):
        raise GeminiProviderError("Gemini item question was not an integer")
    if not isinstance(recognized_value, str):
        raise GeminiProviderError("Gemini item recognized value was not a string")
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
