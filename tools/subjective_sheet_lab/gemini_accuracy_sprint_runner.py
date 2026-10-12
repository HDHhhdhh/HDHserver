# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx2[http2,brotli,zstd]==2.7.0", "Pillow>=12.0"]
# ///
#
# Run one bounded variant:
# C:\server-ocr\.venv\Scripts\python.exe tools\subjective_sheet_lab\gemini_accuracy_sprint_runner.py --case-id <local-id> --contact-dir <dir> --human-transcription <file> --sprint-root C:\server-ocr\gemini_accuracy_sprint_outputs\screen_20260720 --variant A --execute
"""Bounded, deidentified Gemini contact-sheet benchmark runner.

This runner never reads answer keys, never sends local paths or identifiers, and
never writes outside its new sprint output root. It has no retry loop: each
execution can make at most one provider request.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import socket
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

import httpx2
from PIL import Image

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
PromptVariant: TypeAlias = Literal["A", "B", "C", "D", "E", "G", "H"]

MODEL: Final[str] = "gemini-2.5-flash"
ENDPOINT: Final[str] = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
QUESTION_COUNT: Final[int] = 20
VARIANTS: Final[tuple[PromptVariant, ...]] = ("A", "B", "C", "D")
LIMITS: Final[httpx2.Limits] = httpx2.Limits(max_connections=200, max_keepalive_connections=40, keepalive_expiry=30.0)
TIMEOUT: Final[httpx2.Timeout] = httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)
SOCKET_OPTIONS: Final[list[tuple[int, int, int]]] = [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]


class SprintError(Exception):
    """Raised for a bounded sprint failure without exposing sensitive content."""


@dataclass(frozen=True, slots=True)
class ContactSheet:
    group: int
    questions: tuple[int, ...]
    png_bytes: bytes


@dataclass(frozen=True, slots=True)
class Config:
    case_id: str
    contact_dir: Path
    human_path: Path
    sprint_root: Path
    variant: PromptVariant
    model: str
    budget: int
    execute: bool


def main() -> int:
    try:
        config = parse_args()
        result = run(config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except SprintError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Run one deidentified Gemini contact-sheet benchmark variant.")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--contact-dir", required=True, type=Path)
    parser.add_argument("--human-transcription", required=True, type=Path)
    parser.add_argument("--sprint-root", required=True, type=Path)
    parser.add_argument("--variant", required=True, choices=VARIANTS)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--budget", type=int, default=10)
    parser.add_argument("--execute", action="store_true", help="Allow exactly one provider request after all local gates pass.")
    args = parser.parse_args()
    if args.budget < 1:
        parser.error("--budget must be positive")
    return Config(str(args.case_id), args.contact_dir.resolve(), args.human_transcription.resolve(), args.sprint_root.resolve(), cast(PromptVariant, args.variant), str(args.model), int(args.budget), bool(args.execute))


def run(config: Config) -> JsonObject:
    sheets = load_sheets(config.contact_dir)
    human = load_human(config.human_path)
    prompt = build_prompt(config.variant, tuple(range(1, QUESTION_COUNT + 1)))
    payload = build_request_payload(prompt, sheets)
    identity = request_identity(config, sheets, prompt)
    out_dir = config.sprint_root / safe_segment(config.case_id) / config.variant
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / "recognized.json"
    manifest_path = out_dir / "provider_input_manifest.json"
    if cache_path.is_file() and manifest_matches(manifest_path, identity):
        recognized = load_recognized(cache_path)
        write_json(cache_path, {"items": recognized})
        evaluation = evaluate(recognized, human)
        write_json(out_dir / "evaluation.json", evaluation)
        return {"ok": True, "cache_status": "hit", "provider_calls_this_run": 0, "evaluation": evaluation}

    write_json(manifest_path, identity)
    if not config.execute:
        return {"ok": True, "cache_status": "miss_dry_run", "provider_calls_this_run": 0, "provider_input_manifest": "written"}

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SprintError("GEMINI_API_KEY is missing from this process environment")
    reserve_call(config, identity)
    response_text, receipt = call_provider(config.model, key, payload)
    write_json(out_dir / "provider_receipt.json", receipt)
    if receipt["http_status"] != 200:
        write_json(out_dir / "provider_error.json", receipt)
        raise SprintError(f"provider HTTP {receipt['http_status']}; sprint stopped without retry")
    recognized = parse_response(response_text, tuple(range(1, QUESTION_COUNT + 1)))
    write_json(cache_path, {"items": recognized})
    evaluation = evaluate(recognized, human)
    write_json(out_dir / "evaluation.json", evaluation)
    return {"ok": True, "cache_status": "miss_provider_called", "provider_calls_this_run": 1, "evaluation": evaluation}


def load_sheets(contact_dir: Path) -> tuple[ContactSheet, ...]:
    paths = sorted(path for path in contact_dir.iterdir() if path.suffix.casefold() == ".png") if contact_dir.is_dir() else []
    if len(paths) != 4:
        raise SprintError("contact directory must contain exactly four PNG sheets")
    sheets: list[ContactSheet] = []
    for group, path in enumerate(paths, start=1):
        with Image.open(path) as image:
            flattened = image.convert("RGB")
            buffer = io.BytesIO()
            flattened.save(buffer, format="PNG", optimize=True)
        start = (group - 1) * 5 + 1
        sheets.append(ContactSheet(group, tuple(range(start, start + 5)), buffer.getvalue()))
    return tuple(sheets)


def build_prompt(variant: PromptVariant, questions: tuple[int, ...]) -> str:
    rows = ", ".join(str(question) for question in questions)
    shared = f"Transcribe only the visible handwritten math response for rows {rows}. Return JSON only: {{\"items\":[{{\"question\":1,\"recognized\":\"...\"}}]}}. Include every row once. Use ? when evidence is unclear. Do not solve or infer missing content."
    additions: dict[PromptVariant, str] = {
        "A": " Preserve visible characters exactly.",
        "B": " Use numeric-only constraints for numeric-answer rows; do not solve or normalize values.",
        "C": " Preserve signs, fractions as a/b, roots as sqrt(...), exponents with ^, equality, and parentheses.",
        "D": " Perform a silent structured self-check for row count and JSON shape, then return JSON only.",
        "E": " Each row has an original view and an enhanced view. Treat the original as primary; use the enhanced view only to clarify a visible mark.",
        "G": " Keep the response concise and transcription-only.",
        "H": " Distinguish 0 from 6, x from n, signs, jamo choices, fractions, erased marks, and multiple marks. Prefer ? over guessing.",
    }
    return shared + additions[variant]


def build_request_payload(prompt: str, sheets: tuple[ContactSheet, ...]) -> JsonObject:
    parts: list[JsonObject] = [{"text": prompt}]
    for sheet in sheets:
        first, last = sheet.questions[0], sheet.questions[-1]
        parts.append({"text": f"Deidentified contact group {sheet.group}: rows {first}-{last}."})
        parts.append({"inlineData": {"mimeType": "image/png", "data": base64.b64encode(sheet.png_bytes).decode("ascii")}})
    return {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"temperature": 0, "maxOutputTokens": 1024, "responseMimeType": "application/json"}}


def request_identity(config: Config, sheets: tuple[ContactSheet, ...], prompt: str) -> JsonObject:
    identity: JsonObject = {"schema": "gemini_accuracy_sprint_provider_input_v1", "model": config.model, "variant": config.variant, "prompt_sha256": digest(prompt.encode("utf-8")), "input_package": "P1_deidentified_four_contact_sheets", "question_count": QUESTION_COUNT, "contact_sha256": [digest(sheet.png_bytes) for sheet in sheets], "external_scope": "deidentified_contact_sheets_only"}
    identity["request_sha256"] = digest(json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return identity


def call_provider(model: str, key: str, payload: JsonObject) -> tuple[str, JsonObject]:
    started = time.perf_counter()
    transport = httpx2.HTTPTransport(http2=True, retries=0, limits=LIMITS, socket_options=SOCKET_OPTIONS)
    with httpx2.Client(transport=transport, timeout=TIMEOUT, follow_redirects=True, trust_env=False, headers={"x-goog-api-key": key, "content-type": "application/json"}) as client:
        try:
            response = client.post(ENDPOINT.format(model=model), json=payload)
        except httpx2.HTTPError as error:
            return "", {"http_status": 0, "error_kind": type(error).__name__, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1), "usage_metadata": {}}
    receipt: JsonObject = {"http_status": response.status_code, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1), "http_version": response.http_version, "usage_metadata": {}}
    if response.status_code != 200:
        return "", receipt
    try:
        payload_json = require_object(json.loads(response.text), "provider response")
        candidates = require_list(payload_json.get("candidates"), "candidates")
        candidate = require_object(candidates[0] if candidates else None, "candidate")
        content = require_object(candidate.get("content"), "content")
        parts = require_list(content.get("parts"), "parts")
        part = require_object(parts[0] if parts else None, "part")
        text = require_text(part.get("text"), "response text")
        receipt["usage_metadata"] = sanitize_usage(payload_json.get("usageMetadata"))
        return text, receipt
    except SprintError as error:
        receipt["parse_error"] = str(error)
        return "", receipt | {"http_status": 502}


def parse_response(text: str, questions: tuple[int, ...]) -> list[JsonObject]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    root = require_object(json.loads(cleaned), "provider JSON")
    raw_items = require_list(root.get("items"), "items")
    found: dict[int, str] = {}
    for raw in raw_items:
        item = require_object(raw, "item")
        question = item.get("question")
        if not isinstance(question, int) or isinstance(question, bool) or question not in questions or question in found:
            raise SprintError("provider JSON has invalid or duplicate question")
        found[question] = sanitize_recognized_text(require_text(item.get("recognized"), "recognized"))
    return [{"question": question, "recognized": found.get(question, "?")} for question in questions]


def load_human(path: Path) -> dict[int, tuple[str, str]]:
    root = require_object(read_json(path), "human transcription")
    rows = require_list(root.get("answers"), "answers")
    output: dict[int, tuple[str, str]] = {}
    for raw in rows:
        item = require_object(raw, "human row")
        question = item.get("question_no")
        if not isinstance(question, int) or isinstance(question, bool) or not 1 <= question <= QUESTION_COUNT:
            raise SprintError("human transcription question must be 1..20")
        output[question] = (require_text(item.get("human_answer"), "human answer"), require_text(item.get("confidence"), "human confidence"))
    if len(output) != QUESTION_COUNT:
        raise SprintError("human transcription must contain 20 questions")
    return output


def load_recognized(path: Path) -> list[JsonObject]:
    root = require_object(read_json(path), "recognized")
    return parse_response(json.dumps(root, ensure_ascii=False), tuple(range(1, QUESTION_COUNT + 1)))


def evaluate(recognized: list[JsonObject], human: dict[int, tuple[str, str]]) -> JsonObject:
    rows: list[JsonObject] = []
    for item in recognized:
        question = cast(int, item["question"])
        value = cast(str, item["recognized"])
        human_value, confidence = human[question]
        match = confidence.casefold() != "low" and normalize(value) == normalize(human_value) and value != "?"
        labels = taxonomy(value, human_value, match)
        rows.append({"question": question, "recognized": value, "human_confidence": confidence, "match_to_human": match, "failure_taxonomy": labels})
    evaluated = [row for row in rows if cast(str, row["human_confidence"]).casefold() != "low"]
    matched = sum(1 for row in evaluated if row["match_to_human"])
    coverage = sum(1 for row in rows if row["recognized"] != "?")
    missing = QUESTION_COUNT - coverage
    return {"total": QUESTION_COUNT, "ocr_evaluated_total": len(evaluated), "exact_or_normalized_match": matched, "ocr_vs_human_accuracy_pct": round((matched / len(evaluated)) * 100, 2) if evaluated else 0.0, "candidate_coverage": coverage, "missing": missing, "teacher_correction_proxy": QUESTION_COUNT - matched, "safe_auto_grade": 0, "wrong_safe_auto_grade": 0, "rows": rows, "cost": "cost_not_available"}


def taxonomy(recognized: str, human: str, match: bool) -> list[str]:
    if recognized == "?":
        return ["missing"]
    if match:
        return []
    markers = (("-", "minus"), ("/", "fraction"), (".", "decimal"), ("sqrt", "root"), ("^", "superscript"), ("=", "equal"), ("(", "parenthesis"))
    labels = [label for marker, label in markers if marker in recognized or marker in human]
    if {"0", "6"}.issubset(set(recognized + human)):
        labels.append("0_6")
    if {"x", "n"}.issubset(set(normalize(recognized) + normalize(human))):
        labels.append("x_n")
    return labels or ["transcription_mismatch"]


def reserve_call(config: Config, identity: JsonObject) -> None:
    ledger_path = config.sprint_root / "sprint_ledger.json"
    ledger = require_object(read_json(ledger_path), "ledger") if ledger_path.is_file() else {"schema": "gemini_accuracy_sprint_ledger_v1", "budget": config.budget, "requests": []}
    requests = require_list(ledger.get("requests"), "ledger requests")
    if len(requests) >= config.budget:
        raise SprintError("provider budget exhausted before request")
    requests.append({"case_id": config.case_id, "variant": config.variant, "model": config.model, "input_identity": identity["request_sha256"], "requested_at": now_utc()})
    ledger["requests"] = requests
    ledger["budget"] = config.budget
    write_json(ledger_path, ledger)


def manifest_matches(path: Path, identity: JsonObject) -> bool:
    return path.is_file() and read_json(path) == identity


def read_json(path: Path) -> JsonValue:
    try:
        return cast(JsonValue, json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, json.JSONDecodeError) as error:
        raise SprintError(f"cannot read local artifact {path.name}") from error


def write_json(path: Path, value: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise SprintError(f"{label} must be an object")
    return cast(JsonObject, value)


def require_list(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise SprintError(f"{label} must be a list")
    return value


def require_text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise SprintError(f"{label} must be text")
    return value.strip()


def sanitize_usage(value: JsonValue) -> JsonObject:
    source = value if isinstance(value, dict) else {}
    allowed = ("promptTokenCount", "candidatesTokenCount", "totalTokenCount", "thoughtsTokenCount")
    return {key: int(source[key]) for key in allowed if isinstance(source.get(key), int) and not isinstance(source.get(key), bool)}


def normalize(value: str) -> str:
    compact = re.sub(r"\s+", "", value).casefold().replace("\\sqrt", "sqrt")
    compact = re.sub(r"sqrt\{([^{}]+)\}", r"sqrt(\1)", compact)
    return re.sub(r"sqrt(?![({])([a-z0-9]+)", r"sqrt(\1)", compact)


def sanitize_recognized_text(value: str) -> str:
    cleaned = value.encode("utf-8", "replace").decode("utf-8")
    return "?" if "\ufffd" in cleaned else cleaned


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "case"


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
