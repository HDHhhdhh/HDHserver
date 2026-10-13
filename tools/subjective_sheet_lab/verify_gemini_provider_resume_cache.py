# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_gemini_provider_resume_cache.py

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab import gemini_provider  # noqa: E402
from tools.subjective_sheet_lab.review_policy_evaluator import evaluate_item  # noqa: E402

JsonValue: TypeAlias = gemini_provider.JsonValue
JsonObject: TypeAlias = dict[str, JsonValue]
PostGemini: TypeAlias = Callable[[dict[str, JsonValue], str, str], dict[str, JsonValue]]

FIXTURE_ROOT: Final[Path] = Path(r"C:\server-ocr\gemini_provider_resume_cache_verifier")
MODEL: Final[str] = "gemini-2.5-flash-lite"


class ResumeCacheVerificationError(Exception):
    pass


def main() -> int:
    explicit = verify_explicit_unresolved_advances()
    omitted = verify_omitted_response_stays_pending()
    print(json.dumps({"ok": True, "results": {"explicit_unresolved": explicit, "omitted_response": omitted}}, ensure_ascii=False, indent=2))
    return 0


def verify_explicit_unresolved_advances() -> JsonObject:
    case_dir = prepare_case_dir("explicit_unresolved")
    out_path = case_dir / "recognized.json"
    contact_dir = write_contact_fixtures(case_dir)
    calls: list[str] = []
    fake_post = fake_provider((recognized_fixture(unresolved=(9,)),), calls)
    with patched_post_gemini(fake_post):
        run_provider_once(contact_dir, out_path, max_calls=2)
        cache = read_cache(case_dir)
        require_cache_item(cache, 9, "?", "completed_unresolved")
        require_cache_item(cache, 20, "20", "completed_recognized")
        run_provider_once(contact_dir, out_path, max_calls=1)
        require_call_count(calls, 1)

    recognized = read_json_object(out_path)
    items = require_array(recognized.get("items"), "recognized.items")
    if len(items) != 20:
        raise ResumeCacheVerificationError("recognized.json must contain 20 items")
    q009_policy = evaluate_item(9, "3", "?")
    if q009_policy.status == "safe_auto_grade":
        raise ResumeCacheVerificationError("completed_unresolved must not be safe_auto_grade")
    return {"provider_calls": len(calls), "q009_cache_status": "completed_unresolved", "q009_policy": q009_policy.status}


def verify_omitted_response_stays_pending() -> JsonObject:
    case_dir = prepare_case_dir("omitted_response")
    out_path = case_dir / "recognized.json"
    contact_dir = write_contact_fixtures(case_dir)
    calls: list[str] = []
    fake_post = fake_provider(
        (
            recognized_fixture(omit=(9,)),
            ((6, "6"), (7, "7"), (8, "8"), (9, "?"), (10, "10")),
        ),
        calls,
    )
    with patched_post_gemini(fake_post):
        run_provider_once(contact_dir, out_path, max_calls=2)
        cache = read_cache(case_dir)
        require_cache_missing(cache, 9)
        run_provider_once(contact_dir, out_path, max_calls=1)
        require_last_call(calls, "q006_q010")
        cache = read_cache(case_dir)
        require_cache_item(cache, 9, "?", "completed_unresolved")

    return {"provider_calls": len(calls), "q009_initial_cache": "pending", "next_sheet": calls[-1]}


def prepare_case_dir(name: str) -> Path:
    case_dir = FIXTURE_ROOT / name
    case_dir.mkdir(parents=True, exist_ok=True)
    for path in case_dir.glob("*.json"):
        path.unlink()
    contact_dir = case_dir / "contact_sheets"
    contact_dir.mkdir(exist_ok=True)
    for path in contact_dir.glob("*.png"):
        path.unlink()
    return case_dir


def write_contact_fixtures(case_dir: Path) -> Path:
    contact_dir = case_dir / "contact_sheets"
    for start, end in ((1, 5), (6, 10), (11, 15), (16, 20)):
        path = contact_dir / f"person_04_q{start:03d}_q{end:03d}_review.png"
        path.write_bytes(b"not-sent-to-provider")
    return contact_dir


def run_provider_once(contact_dir: Path, out_path: Path, *, max_calls: int) -> None:
    config = gemini_provider.CliConfig(crop_dir=None, contact_dir=contact_dir, image_files=(), out_path=out_path, model=MODEL, resume=True, max_calls=max_calls)
    items = gemini_provider.recognize_from_config(config, "dummy-key")
    gemini_provider.write_recognized_json(out_path, items)


def fake_provider(groups: tuple[tuple[tuple[int, str], ...], ...], calls: list[str]) -> PostGemini:
    def post(payload: dict[str, JsonValue], api_key: str, model: str) -> dict[str, JsonValue]:
        calls.append(contact_label_from_payload(payload))
        index = len(calls) - 1
        if index >= len(groups):
            raise ResumeCacheVerificationError("fake provider exhausted")
        return response_for(groups[index])

    return post


def recognized_fixture(*, unresolved: tuple[int, ...] = (), omit: tuple[int, ...] = ()) -> tuple[tuple[int, str], ...]:
    omitted = set(omit)
    unresolved_questions = set(unresolved)
    return tuple((question, "?" if question in unresolved_questions else str(question)) for question in range(1, 21) if question not in omitted)


class patched_post_gemini:
    def __init__(self, replacement: PostGemini) -> None:
        self.replacement = replacement
        self.original: PostGemini | None = None

    def __enter__(self) -> None:
        self.original = gemini_provider.post_gemini
        gemini_provider.post_gemini = self.replacement

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: JsonValue) -> None:
        if self.original is None:
            raise ResumeCacheVerificationError("missing original post_gemini")
        gemini_provider.post_gemini = self.original


def response_for(items: tuple[tuple[int, str], ...]) -> JsonObject:
    text = json.dumps({"items": [{"question": question, "recognized": recognized} for question, recognized in items]}, ensure_ascii=False)
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def read_cache(case_dir: Path) -> JsonObject:
    return read_json_object(case_dir / gemini_provider.CACHE_FILE_NAME)


def read_json_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    return require_object(value, str(path))


def require_cache_item(cache: JsonObject, question: int, recognized: str, status: str) -> None:
    for item in require_array(cache.get("items"), "cache.items"):
        data = require_object(item, "cache.item")
        if data.get("question") == question:
            if data.get("recognized") != recognized:
                raise ResumeCacheVerificationError(f"q{question:03d} recognized mismatch")
            if data.get("cache_status") != status:
                raise ResumeCacheVerificationError(f"q{question:03d} cache_status mismatch")
            return
    raise ResumeCacheVerificationError(f"q{question:03d} missing from cache")


def require_cache_missing(cache: JsonObject, question: int) -> None:
    for item in require_array(cache.get("items"), "cache.items"):
        data = require_object(item, "cache.item")
        if data.get("question") == question:
            raise ResumeCacheVerificationError(f"q{question:03d} must remain pending when provider omitted it")


def require_last_call(calls: list[str], expected_fragment: str) -> None:
    if not calls:
        raise ResumeCacheVerificationError("provider was not called")
    if expected_fragment not in calls[-1]:
        raise ResumeCacheVerificationError(f"last provider call {calls[-1]} did not include {expected_fragment}")


def require_call_count(calls: list[str], expected: int) -> None:
    if len(calls) != expected:
        raise ResumeCacheVerificationError(f"provider call count {len(calls)} != {expected}")


def contact_label_from_payload(payload: JsonObject) -> str:
    contents = require_array(payload.get("contents"), "payload.contents")
    content = require_object(contents[0], "payload.contents[0]")
    parts = require_array(content.get("parts"), "payload.parts")
    for part in parts:
        data = require_object(part, "payload.part")
        text = data.get("text")
        if isinstance(text, str) and text.startswith("contact_sheet="):
            return text
    raise ResumeCacheVerificationError("contact sheet label missing from provider payload")


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ResumeCacheVerificationError(f"{label} must be object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ResumeCacheVerificationError(f"{label} must be array")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
