# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_gemini_provider_contact_batching.py

from __future__ import annotations

import base64
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab import gemini_provider  # noqa: E402
from tools.subjective_sheet_lab.gemini_provider import CliConfig, RecognizedItem  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
PostGemini: TypeAlias = Callable[[dict[str, JsonValue], str, str], dict[str, JsonValue]]

FIXTURE_ROOT: Final[Path] = Path(r"C:\tmp\gemini_provider_contact_batching")
ALLOWED_TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
QUESTION_COUNT: Final[int] = 20
CONTACT_RANGES: Final[tuple[tuple[int, int], ...]] = ((1, 5), (6, 10), (11, 15), (16, 20))
PNG_BYTES: Final[bytes] = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=")


class ContactBatchingVerificationError(Exception):
    pass


def main() -> int:
    contact_dir = write_contact_fixtures()
    calls: list[JsonObject] = []
    original_post: PostGemini = gemini_provider.post_gemini
    gemini_provider.post_gemini = fake_post_gemini(calls)
    try:
        items = gemini_provider.recognize_from_config(config_for(contact_dir), "fake-key")
    finally:
        gemini_provider.post_gemini = original_post

    assert_single_full_contact_call(calls)
    assert_complete_items(items)
    print(json.dumps({"ok": True, "provider_calls": len(calls), "recognized_items": len(items)}, ensure_ascii=False, indent=2))
    return 0


def write_contact_fixtures() -> Path:
    contact_dir = FIXTURE_ROOT / "contact_sheets"
    contact_dir.mkdir(parents=True, exist_ok=True)
    for start, end in CONTACT_RANGES:
        (contact_dir / f"contact_q{start:03d}_q{end:03d}.png").write_bytes(PNG_BYTES)
    return contact_dir


def config_for(contact_dir: Path) -> CliConfig:
    return CliConfig(
        crop_dir=None,
        contact_dir=contact_dir,
        image_files=(),
        out_path=FIXTURE_ROOT / "recognized.json",
        model="fake-model",
        resume=False,
        max_calls=1,
        test_id=ALLOWED_TEST_ID,
    )


def fake_post_gemini(calls: list[JsonObject]) -> PostGemini:
    def post(payload: dict[str, JsonValue], api_key: str, model: str) -> dict[str, JsonValue]:
        calls.append(payload)
        items = [{"question": question, "recognized": str(question)} for question in range(1, QUESTION_COUNT + 1)]
        return {"candidates": [{"content": {"parts": [{"text": json.dumps({"items": items}, ensure_ascii=False)}]}}]}

    return post


def assert_single_full_contact_call(calls: list[JsonObject]) -> None:
    if len(calls) != 1:
        raise ContactBatchingVerificationError(f"expected one provider call, got {len(calls)}")
    parts = require_parts(calls[0])
    inline_count = sum(1 for part in parts if isinstance(part, dict) and "inline_data" in part)
    if inline_count != len(CONTACT_RANGES):
        raise ContactBatchingVerificationError(f"expected {len(CONTACT_RANGES)} contact images in one call, got {inline_count}")
    prompt = "\n".join(str(part.get("text")) for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str))
    if "Return JSON only for questions: 1, 2, 3" not in prompt or "18, 19, 20" not in prompt:
        raise ContactBatchingVerificationError("prompt did not cover q001-q020")
    if "one visible digit or number is clearly final" not in prompt:
        raise ContactBatchingVerificationError("prompt missing visible-digit final policy")
    if "Do not set recognized to ? only because old strokes" not in prompt:
        raise ContactBatchingVerificationError("prompt missing nearby-old-strokes final digit policy")
    if f"Question mode hints for {ALLOWED_TEST_ID}" not in prompt:
        raise ContactBatchingVerificationError("prompt missing test-specific answer mode hints")
    if "choice_number questions are 1, 3, 5, 9, 13, 14, 17, 19" not in prompt:
        raise ContactBatchingVerificationError("prompt missing choice-number question list")
    if "answer_value questions are 2, 4, 6, 7, 8, 10, 11, 12, 15, 16, 18, 20" not in prompt:
        raise ContactBatchingVerificationError("prompt missing answer-value question list")


def require_parts(payload: JsonObject) -> list[JsonValue]:
    contents = payload.get("contents")
    if not isinstance(contents, list) or not contents:
        raise ContactBatchingVerificationError("payload missing contents")
    first = contents[0]
    if not isinstance(first, dict):
        raise ContactBatchingVerificationError("payload content must be object")
    parts = first.get("parts")
    if not isinstance(parts, list):
        raise ContactBatchingVerificationError("payload missing parts")
    return parts


def assert_complete_items(items: list[RecognizedItem]) -> None:
    recognized = {item.question: item.recognized for item in items}
    if sorted(recognized) != list(range(1, QUESTION_COUNT + 1)):
        raise ContactBatchingVerificationError(f"recognized questions are incomplete: {sorted(recognized)}")
    unresolved = [question for question, value in recognized.items() if value == "?"]
    if unresolved:
        raise ContactBatchingVerificationError(f"unexpected unresolved questions: {unresolved}")


if __name__ == "__main__":
    raise SystemExit(main())
