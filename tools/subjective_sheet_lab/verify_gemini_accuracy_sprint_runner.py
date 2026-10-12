# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# Run: C:\server-ocr\.venv\Scripts\python.exe tools\subjective_sheet_lab\verify_gemini_accuracy_sprint_runner.py
"""Offline contract checks for the Gemini accuracy-sprint runner."""

from __future__ import annotations

import json
from pathlib import Path

from gemini_accuracy_sprint_runner import ContactSheet, build_prompt, build_request_payload, parse_response


def main() -> int:
    prompt = build_prompt("E", (1, 2, 3, 4, 5))
    forbidden_prompt = ("student", "sid", "answer key", "expected", "canonical", "local path", "full sheet")
    assert all(term not in prompt.casefold() for term in forbidden_prompt)

    sheet = ContactSheet(group=1, questions=(1, 2, 3, 4, 5), png_bytes=b"png-bytes")
    payload = build_request_payload(prompt, (sheet,))
    serialized = json.dumps(payload, ensure_ascii=False)
    forbidden_payload = ("C:\\", "expected", "canonical_answer", "accepted_answers", "grading", "student", "sid")
    assert all(term.casefold() not in serialized.casefold() for term in forbidden_payload)
    assert "inlineData" in serialized
    assert "request_sha256" not in serialized

    parsed = parse_response('{"items":[{"question":1,"recognized":"2"}]}', tuple(range(1, 21)))
    assert len(parsed) == 20
    assert parsed[0]["recognized"] == "2"
    assert parsed[1]["recognized"] == "?"

    malformed = parse_response('{"items":[{"question":1,"recognized":"\\ud800"}]}', tuple(range(1, 21)))
    assert malformed[0]["recognized"] == "?"

    source = Path(__file__).with_name("gemini_accuracy_sprint_runner.py").read_text(encoding="utf-8")
    assert "urllib" not in source
    assert "dotenv" not in source
    print("PASS: gemini_accuracy_sprint_runner offline contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
