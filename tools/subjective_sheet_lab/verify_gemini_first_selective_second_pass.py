# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations

import base64
import json
import sys
import tempfile
import urllib.error
from pathlib import Path
from typing import Final, TypeAlias
from unittest.mock import patch

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab import gemini_provider  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
MODEL: Final[str] = "gemini-2.5-flash-lite"
PNG_BYTES: Final[bytes] = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mNk+M8AAAICAYepL9lRAAAAAElFTkSuQmCC"
)


class SelectiveSecondPassVerificationError(Exception):
    pass


def main() -> int:
    results = {
        "contact_resume_stops_without_group_retry": verify_contact_resume_stops_without_group_retry(),
        "crop_only_second_pass": verify_crop_only_second_pass(),
        "second_pass_eligibility": verify_second_pass_eligibility(),
        "http_503_stops_after_one_attempt": verify_http_503_stops_after_one_attempt(),
        "actual_external_call_counts": {
            "gemini_provider": 0,
            "external_ocr_api": 0,
            "ocr_review_route": 0,
            "submit_test": 0,
            "final_submit": 0,
        },
    }
    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2))
    return 0


def verify_contact_resume_stops_without_group_retry() -> JsonObject:
    with tempfile.TemporaryDirectory(prefix="gemini_first_contact_resume_") as raw_dir:
        root = Path(raw_dir)
        contact_dir = root / "contacts"
        contact_dir.mkdir()
        for start, end in ((1, 5), (6, 10), (11, 15), (16, 20)):
            (contact_dir / f"answer_sheet_q{start:03d}_q{end:03d}.png").write_bytes(PNG_BYTES)
        config = config_for(contact_dir, root / "recognized.json")
        calls: list[JsonObject] = []

        def fake_post(payload: JsonObject, api_key: str, model: str) -> JsonObject:
            calls.append(payload)
            return response_for(tuple(question for question in range(1, 21) if question != 9))

        with patch.object(gemini_provider, "post_gemini", fake_post):
            first = gemini_provider.recognize_from_config(config, "fake-key")
            second = gemini_provider.recognize_from_config(config, "fake-key")
        if len(calls) != 1:
            raise SelectiveSecondPassVerificationError(f"contact resume made {len(calls)} provider attempts instead of one")
        if recognized_by_question(first).get(9) != "?" or recognized_by_question(second).get(9) != "?":
            raise SelectiveSecondPassVerificationError("missing question was not retained as unresolved")
    return {"first_pass_calls": 1, "resume_contact_retry_calls": 0, "q009_status": "completed_unresolved"}


def verify_crop_only_second_pass() -> JsonObject:
    with tempfile.TemporaryDirectory(prefix="gemini_first_crop_second_pass_") as raw_dir:
        crop_dir = Path(raw_dir) / "crops"
        crop_dir.mkdir()
        (crop_dir / "q009.png").write_bytes(PNG_BYTES)
        captured: list[JsonObject] = []

        def fake_post(payload: JsonObject, api_key: str, model: str) -> JsonObject:
            captured.append(payload)
            return response_for((9,))

        with patch.object(gemini_provider, "post_gemini", fake_post):
            items = gemini_provider.recognize_eligible_second_pass_crops(
                crop_dir,
                (9,),
                "fake-key",
                MODEL,
                numeric_only=True,
            )
        if [item.question for item in items] != [9]:
            raise SelectiveSecondPassVerificationError("second pass returned a question outside the eligible crop")
        rendered = json.dumps(captured[0], ensure_ascii=False)
        if "answer_sheet_q009.png" not in rendered or "contact_sheet=" in rendered or "q001" in rendered:
            raise SelectiveSecondPassVerificationError("second pass payload was not a single generic crop input")
        if any(token in rendered for token in ("C:\\", "C:/", "expected", "canonical_answer", "accepted_answers", "grading")):
            raise SelectiveSecondPassVerificationError("second pass payload leaked a forbidden token")
    return {"provider_attempts_simulated": 1, "eligible_crop_count": 1, "generic_crop_labels_only": True}


def verify_second_pass_eligibility() -> JsonObject:
    eligible = gemini_provider.eligible_second_pass_questions(
        tuple(range(1, 21)),
        {question: str(question) for question in range(1, 21) if question not in {9, 10}},
        low_confidence_questions=(11,),
    )
    if eligible != (9, 10, 11):
        raise SelectiveSecondPassVerificationError(f"eligible questions were {eligible}")
    return {"eligible_questions": list(eligible), "answer_key_used": False}


def verify_http_503_stops_after_one_attempt() -> JsonObject:
    attempts = 0

    def fake_urlopen(request, timeout: int):
        nonlocal attempts
        attempts += 1
        raise urllib.error.HTTPError(request.full_url, 503, "service unavailable", {}, None)

    with patch("urllib.request.urlopen", fake_urlopen):
        try:
            gemini_provider.post_gemini({"contents": []}, "fake-key", MODEL)
        except urllib.error.HTTPError as exc:
            if exc.code != 503:
                raise SelectiveSecondPassVerificationError(f"unexpected HTTP status {exc.code}") from exc
        else:
            raise SelectiveSecondPassVerificationError("HTTP 503 did not stop the provider call")
    if attempts != 1:
        raise SelectiveSecondPassVerificationError(f"HTTP 503 made {attempts} transport attempts")
    return {"simulated_transport_attempts": attempts, "automatic_retry": False, "resume_requires_explicit_action": True}


def config_for(contact_dir: Path, out_path: Path) -> gemini_provider.CliConfig:
    return gemini_provider.CliConfig(
        crop_dir=None,
        contact_dir=contact_dir,
        image_files=(),
        out_path=out_path,
        model=MODEL,
        resume=True,
        max_calls=1,
        test_id=None,
        numeric_only=False,
    )


def response_for(questions: tuple[int, ...]) -> JsonObject:
    text = json.dumps({"items": [{"question": question, "recognized": str(question)} for question in questions]})
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def recognized_by_question(items: list[gemini_provider.RecognizedItem]) -> dict[int, str]:
    return {item.question: item.recognized for item in items}


if __name__ == "__main__":
    raise SystemExit(main())
