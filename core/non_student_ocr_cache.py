from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

POLICY_VERSION: Final = "gemini_flash_lite_policy_d_boundary_v1"
MANIFEST_SCHEMA: Final = "gemini_accuracy_sprint_provider_input_v1"
EXTERNAL_SCOPE: Final = "deidentified_contact_sheets_only"
SHA256_PATTERN: Final = re.compile(r"^[a-f0-9]{64}$")
CASE_ID_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
TEST_ID_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
LOCAL_PATH_PATTERN: Final = re.compile(
    r"(?:[A-Za-z]:\\|file://|/(?:home|Users|server|tmp)/)",
    re.IGNORECASE,
)
MANIFEST_KEYS: Final = frozenset(
    {
        "schema",
        "model",
        "variant",
        "prompt_sha256",
        "input_package",
        "question_count",
        "contact_sha256",
        "external_scope",
        "request_sha256",
    }
)
RECOGNIZED_KEYS: Final = frozenset({"question", "recognized"})


class Candidate(TypedDict):
    value: str


class ReviewItem(TypedDict):
    question_no: int
    review_state: str
    candidate: Candidate | None
    warning: list[str]
    crop_preview: str
    candidate_source: str
    allow_edit: bool
    requires_confirmation: bool
    retake_reason: str
    resolution: str
    final_answer: None


class ReviewPayload(TypedDict):
    source: str
    auto_confirm_policy_version: str
    test_id: str
    round: str
    problem_count: int
    items: list[ReviewItem]


class ReviewResponse(TypedDict):
    provenance: str
    source: str
    cache_status: str
    provider_calls: int
    calibration_policy_version: str
    classification_counts: dict[str, int]
    payload: ReviewPayload


@dataclass(frozen=True, slots=True)
class CapturedCacheError(Exception):
    code: str
    message: str
    status_code: int

    def __str__(self) -> str:
        return self.message


def _fail(code: str, message: str, status_code: int = 400) -> None:
    raise CapturedCacheError(code, message, status_code)


def _require_mapping(value, label: str) -> dict:
    if not isinstance(value, dict):
        _fail("INVALID_CAPTURE_CONTRACT", f"{label} must be an object")
    return value


def _read_json(path: Path, label: str) -> dict:
    try:
        with path.open("r", encoding="utf-8") as source:
            return _require_mapping(json.load(source), label)
    except (OSError, json.JSONDecodeError) as error:
        raise CapturedCacheError(
            "CACHE_UNAVAILABLE",
            f"{label} is unavailable",
            503,
        ) from error


def _reject_unexpected_keys(value: dict, allowed: frozenset[str], label: str) -> None:
    unexpected = next((key for key in value if key not in allowed), None)
    if unexpected is not None:
        _fail("INVALID_CAPTURE_CONTRACT", f"{label} field is not accepted: {unexpected}")


def _verify_manifest(manifest: dict) -> None:
    _reject_unexpected_keys(manifest, MANIFEST_KEYS, "manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        _fail("INVALID_CAPTURE_CONTRACT", "manifest schema is unsupported")
    if manifest.get("external_scope") != EXTERNAL_SCOPE:
        _fail("DEIDENTIFICATION_SCOPE_REQUIRED", "deidentified contact scope is required", 403)
    if manifest.get("question_count") != 20:
        _fail("INVALID_CAPTURE_CONTRACT", "manifest must cover 20 questions")
    contact_hashes = manifest.get("contact_sha256")
    if not isinstance(contact_hashes, list) or len(contact_hashes) != 4:
        _fail("INVALID_CAPTURE_CONTRACT", "manifest must contain four contact hashes")
    hashes = [manifest.get("prompt_sha256"), *contact_hashes, manifest.get("request_sha256")]
    if not all(isinstance(value, str) and SHA256_PATTERN.fullmatch(value) for value in hashes):
        _fail("INVALID_CAPTURE_CONTRACT", "manifest hashes must be SHA-256 values")
    identity = dict(manifest)
    request_hash = identity.pop("request_sha256")
    encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    actual_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if actual_hash != request_hash:
        _fail("CACHE_IDENTITY_MISMATCH", "captured cache request identity does not match", 409)


def _parse_items(recognized: dict) -> list[ReviewItem]:
    _reject_unexpected_keys(recognized, frozenset({"items"}), "recognized cache")
    raw_items = recognized.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != 20:
        _fail("INVALID_CAPTURE_CONTRACT", "recognized cache must contain 20 items")
    parsed: list[tuple[int, str]] = []
    questions: set[int] = set()
    for raw_item in raw_items:
        item = _require_mapping(raw_item, "recognized item")
        _reject_unexpected_keys(item, RECOGNIZED_KEYS, "recognized item")
        question = item.get("question")
        if not isinstance(question, int) or isinstance(question, bool):
            _fail("INVALID_CAPTURE_CONTRACT", "recognized question must be an integer")
        if question < 1 or question > 20 or question in questions:
            _fail("INVALID_CAPTURE_CONTRACT", "recognized questions must uniquely cover 1 through 20")
        questions.add(question)
        candidate = str(item.get("recognized") or "").strip()
        if len(candidate) > 80:
            _fail("INVALID_CAPTURE_CONTRACT", f"recognized candidate is too long for q{question}")
        if LOCAL_PATH_PATTERN.search(candidate):
            _fail("LOCAL_PATH_DETECTED", f"local path detected in q{question}")
        parsed.append((question, candidate))
    parsed.sort()
    if [question for question, _candidate in parsed] != list(range(1, 21)):
        _fail("INVALID_CAPTURE_CONTRACT", "recognized questions must cover 1 through 20")
    return [_review_item(question, candidate) for question, candidate in parsed]


def _review_item(question: int, candidate: str) -> ReviewItem:
    resolved = bool(candidate and candidate != "?")
    return {
        "question_no": question,
        "review_state": "review_recommended" if resolved else "direct_input",
        "candidate": {"value": candidate} if resolved else None,
        "warning": ["teacher_confirmation_required"] if resolved else ["provider_unresolved"],
        "crop_preview": "",
        "candidate_source": "gemini_captured_cache",
        "allow_edit": True,
        "requires_confirmation": True,
        "retake_reason": "",
        "resolution": "unresolved",
        "final_answer": None,
    }


def load_captured_review(
    *,
    case_id: str,
    test_id: str,
    round_no: str,
    root: Path,
    relative_dir: Path,
) -> ReviewResponse:
    if not CASE_ID_PATTERN.fullmatch(case_id):
        _fail("INVALID_CASE_ID", "case_id is invalid")
    if not TEST_ID_PATTERN.fullmatch(test_id):
        _fail("INVALID_TEST_ID", "test_id is invalid")
    if not round_no.isdigit() or int(round_no) < 1:
        _fail("INVALID_ROUND", "round must be a positive integer")
    try:
        resolved_root = root.resolve(strict=True)
        case_dir = (resolved_root / relative_dir).resolve(strict=True)
        case_dir.relative_to(resolved_root)
    except (OSError, ValueError) as error:
        raise CapturedCacheError("CACHE_UNAVAILABLE", "captured cache directory is unavailable", 503) from error
    manifest = _read_json(case_dir / "provider_input_manifest.json", "provider input manifest")
    recognized = _read_json(case_dir / "recognized.json", "recognized cache")
    _verify_manifest(manifest)
    items = _parse_items(recognized)
    counts = {
        "AUTO_CONFIRM": 0,
        "REVIEW_RECOMMENDED": sum(item["review_state"] == "review_recommended" for item in items),
        "DIRECT_INPUT": sum(item["review_state"] == "direct_input" for item in items),
        "RETAKE_REQUIRED": 0,
    }
    payload: ReviewPayload = {
        "source": "trusted_captured_cache_review_v1",
        "auto_confirm_policy_version": POLICY_VERSION,
        "test_id": test_id,
        "round": round_no,
        "problem_count": 20,
        "items": items,
    }
    return {
        "provenance": "adult_non_student",
        "source": "trusted_server_cache",
        "cache_status": "hit",
        "provider_calls": 0,
        "calibration_policy_version": POLICY_VERSION,
        "classification_counts": counts,
        "payload": payload,
    }
