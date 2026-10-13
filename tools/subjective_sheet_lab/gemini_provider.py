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

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0,str(_REPO_ROOT))

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
    candidates: tuple[str, ...] = ()
    uncertainty: str = "unverified"
    needs_review: bool = True


class GeminiProviderError(Exception):
    def __init__(self, message: str, *, reason: str = "provider_error", diagnostic: JsonObject | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.diagnostic = {} if diagnostic is None else dict(diagnostic)


def main() -> int:
    from tools.subjective_sheet_lab.ocr_provider_session import LAST_SESSION, config_identity
    try:
        config = parse_args()
        config_identity(config)
        if config.max_calls == 0:
            raise GeminiProviderError("live calls require an explicit positive budget", reason="provider_budget_exhausted")
        if config.out_path.exists():
            raise GeminiProviderError("output already exists; choose a fresh output file", reason="output_preservation")
        key = read_gemini_key()
        items = recognize_from_config(config, key)
        session = LAST_SESSION.get()
        write_recognized_json(config.out_path, items, identity=session.identity)
    except GeminiProviderError as exc:
        sys.stderr.write(f"ERROR: {exc.reason}\n")
        return 2
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        # Session preserves immutable raw/error/partial checkpoints without paths or headers.
        sys.stderr.write("ERROR: provider transport failed; see this run's diagnostics\n")
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
    source_image: Path | None = None
    round_no: str = "1"
    form_id: str = "answer_sheet_20_v1"
    prompt_version: str = "image_candidates_v2"
    preprocessing_version: str = "crop_contact_v1"
    identity: dict | None = None
    max_retries: int = 0
    backoff_seconds: float = 0.25
    contact_batch_size: int = 1
    crop_batch_size: int = 5
    answer_modes: tuple[str, ...] = ()


def parse_args() -> CliConfig:
    parser = argparse.ArgumentParser(description="Recognize subjective answer crops with Gemini Vision.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--crop-dir", type=Path)
    source.add_argument("--contact-dir", type=Path)
    source.add_argument("--image-files", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--source-image", required=True, type=Path)
    parser.add_argument("--round", required=True)
    parser.add_argument("--form-id", default="answer_sheet_20_v1")
    parser.add_argument("--prompt-version", default="image_candidates_v2")
    parser.add_argument("--preprocessing-version", default="crop_contact_v1")
    parser.add_argument("--max-retries", type=int, default=0)
    parser.add_argument("--backoff-seconds", type=float, default=0.25)
    parser.add_argument("--test-id", required=True)
    args = parser.parse_args()
    if args.max_calls is not None and int(args.max_calls) < 0:
        parser.error("--max-calls must be nonnegative")
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
        source_image=args.source_image, round_no=args.round, form_id=args.form_id,
        prompt_version=args.prompt_version, preprocessing_version=args.preprocessing_version,
        max_retries=args.max_retries, backoff_seconds=args.backoff_seconds,
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


def recognize_from_config(config: CliConfig, api_key: str, *, transport=None, sleeper=None) -> list[RecognizedItem]:
    from tools.subjective_sheet_lab.ocr_provider_session import ProviderSession
    if config.out_path.exists() and not config.resume:
        raise GeminiProviderError("existing output is preserved", reason="output_preservation")
    kwargs = {"transport": transport}
    if sleeper is not None:
        kwargs["sleeper"] = sleeper
    session = ProviderSession(config, **kwargs)
    if config.crop_dir is not None:
        return session.recognize(load_crop_images(config.crop_dir), api_key, contacts=False)
    return session.recognize(load_contact_images(config), api_key, contacts=True)


def recognize_crops(crops: list[CropImage], api_key: str, model: str, numeric_only: bool = False,
                    *, config: CliConfig | None = None, transport=None) -> list[RecognizedItem]:
    if config is None:
        raise GeminiProviderError("crop calls require identity and budget configuration", reason="run_identity_missing")
    from tools.subjective_sheet_lab.ocr_provider_session import ProviderSession
    return ProviderSession(config, transport=transport).recognize(crops, api_key, contacts=False)


def build_gemini_payload(crops: list[CropImage], numeric_only: bool = False) -> dict[str, JsonValue]:
    parts: list[JsonValue] = [{"text": prompt_text(crops, numeric_only) + candidate_prompt()}]
    for crop in crops:
        parts.append({"text": f"question={crop.question:03d}"})
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


def recognize_contact_sheets(contacts: list[ContactImage], api_key: str, config: CliConfig,
                             *, transport=None) -> list[RecognizedItem]:
    from tools.subjective_sheet_lab.ocr_provider_session import ProviderSession
    return ProviderSession(config, transport=transport).recognize(contacts, api_key, contacts=True)


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
    parts: list[JsonValue] = [{"text": contact_prompt_text(contacts, test_id, numeric_only) + candidate_prompt()}]
    for contact in contacts:
        label = question_label(contact.questions)
        parts.append({"text": f"contact_sheet=answer_rows, questions={label}"})
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
    return strict_recognized_items(text, known_contact_questions(contacts))


def load_cached_items(config: CliConfig) -> dict[int, str]:
    from tools.subjective_sheet_lab.ocr_provider_session import ProviderSession
    session = ProviderSession(config)
    return {number:item.recognized for number,item in session.items.items()}


def write_contact_cache(config: CliConfig, contacts: list[ContactImage], recognized_by_question: dict[int, str]) -> None:
    raise GeminiProviderError("unbound cache writes are retired; use ProviderSession", reason="cache_identity_missing")


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
    if set(recognized_by_question) != set(questions):
        raise GeminiProviderError("missing/extra recognized questions", reason="provider_question_coverage")
    return [RecognizedItem(question=n, recognized=recognized_by_question[n]) for n in questions]


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
    from tools.subjective_sheet_lab.ocr_provider_session import capture_raw
    capture_raw(decoded)
    try:
        payload_value = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise GeminiProviderError("invalid HTTP response JSON", reason="provider_invalid_json") from exc
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
    return strict_recognized_items(text, tuple(crop.question for crop in crops))


def parse_json_text(text: str) -> dict[str, JsonValue]:
    stripped = text.strip()
    match = JSON_BLOCK_RE.search(stripped)
    candidate = match.group(1) if match is not None else stripped
    try:
        decoded = json.loads(candidate, object_pairs_hook=unique_json_object)
    except json.JSONDecodeError as exc:
        raise GeminiProviderError(f"Gemini text was not valid JSON: {exc}", reason="provider_invalid_json") from exc
    if not isinstance(decoded, dict):
        raise GeminiProviderError("Gemini JSON root was not an object", reason="provider_malformed_items")
    return decoded


def parse_item(value: JsonValue) -> RecognizedItem:
    allowed = {"question", "recognized", "candidates", "uncertainty", "needs_review"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise GeminiProviderError("provider item has forbidden or unknown fields", reason="provider_malformed_items")
    question = value.get("question")
    recognized = value.get("recognized")
    if type(question) is not int or not 1 <= question <= 20:
        raise GeminiProviderError("question must be an integer in 1..20", reason="provider_question_coverage")
    if not isinstance(recognized, str) or len(recognized) > 200:
        raise GeminiProviderError("recognized must be bounded raw text", reason="provider_malformed_items")
    from tools.subjective_sheet_lab.ocr_payload_leak_policy import path_exposures
    if path_exposures({"recognized": recognized, "candidates": value.get("candidates", [])}):
        raise GeminiProviderError("local path in provider output", reason="provider_path_leak")
    raw_candidates = value.get("candidates", [])
    if not isinstance(raw_candidates, list) or any(not isinstance(v,str) for v in raw_candidates):
        raise GeminiProviderError("candidates must be image-based text values", reason="provider_malformed_items")
    candidates = []
    for candidate in raw_candidates:
        clean = candidate.strip()
        if clean and "?" not in clean and "\n" not in clean and "\r" not in clean and clean not in candidates:
            candidates.append(clean)
    uncertainty = value.get("uncertainty", "unverified")
    needs_review = value.get("needs_review", True)
    if not isinstance(uncertainty,str) or not isinstance(needs_review,bool):
        raise GeminiProviderError("uncertainty contract is invalid", reason="provider_malformed_items")
    return RecognizedItem(question, recognized, tuple(candidates[:5]), uncertainty,
                          needs_review or not recognized.strip() or "?" in recognized or uncertainty not in {"none","clear"})


def write_recognized_json(path: Path, items: list[RecognizedItem], *, identity: dict | None = None) -> None:
    from tools.subjective_sheet_lab.ocr_run_identity import RECOGNITION_SCHEMA, validate_run_identity
    from tools.subjective_sheet_lab.ocr_provider_session import LAST_SESSION, _item_json
    checked = validate_run_identity(identity)
    if sorted(item.question for item in items) != list(range(1,21)):
        raise GeminiProviderError("recognized output requires 20 unique questions", reason="provider_question_coverage")
    path.parent.mkdir(parents=True, exist_ok=True)
    session = LAST_SESSION.get()
    payload = {"schema": RECOGNITION_SCHEMA, "identity": checked,
               "items": [_item_json(item) for item in items],
               "diagnostics": session.counts() if session is not None else {}}
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(payload, ensure_ascii=False, indent=2)+"\n")


def sync_output_from_cache(config: CliConfig) -> bool:
    # Partial checkpoints are immutable and explicitly partial, never final recognized output.
    from tools.subjective_sheet_lab.ocr_provider_session import LAST_SESSION
    session = LAST_SESSION.get()
    return bool(session is not None and session.items)


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



def unique_json_object(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise GeminiProviderError("duplicate JSON key", reason="provider_invalid_json")
        result[key] = value
    return result


def candidate_prompt() -> str:
    return (" Preserve recognized as the visible transcription. Optional candidates must be at most five distinct "
            "image-supported interpretations, never guesses or answers obtained by solving. "
            "Never use an answer key. Include uncertainty (clear, ambiguous, unreadable) and needs_review boolean. "
            "Do not invent alternatives to fill five slots. Return only items with question, recognized, "
            "candidates, uncertainty, needs_review.")

def strict_recognized_items(text: str, questions: tuple[int, ...]) -> list[RecognizedItem]:
    payload = parse_json_text(text)
    if set(payload) != {"items"} or not isinstance(payload.get("items"), list):
        raise GeminiProviderError("provider JSON requires only items", reason="provider_malformed_items")
    seen = {}
    for raw in payload["items"]:
        item = parse_item(raw)
        if item.question in seen:
            raise GeminiProviderError("duplicate provider question", reason="provider_duplicate_question")
        seen[item.question] = item
    if set(seen) != set(questions) or len(seen) != len(questions):
        raise GeminiProviderError("provider question set is incomplete or contains extras", reason="provider_question_coverage")
    return [seen[number] for number in questions]

if __name__ == "__main__":
    raise SystemExit(main())
