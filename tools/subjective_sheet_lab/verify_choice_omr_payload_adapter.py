from __future__ import annotations

import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from choice_omr_payload_adapter import (
    CHOICE_MODE,
    ChoiceOmrAdapterError,
    ChoiceOmrRequest,
    load_choice_omr_payload,
)
from ocr_payload_leak_policy import forbidden_paths, path_exposures
from ocr_review_payload_validator import PayloadMode, validate_payload

OCR_OUTPUT = Path(r"C:\server-ocr\choice_omr_v1")
MODES = (CHOICE_MODE,) * 20


def main() -> int:
    verify_clean_payload()
    verify_blank_retake_payload()
    verify_multiple_retake_payload()
    verify_non_choice_rejected()
    print("choice OMR payload adapter contract: OK")
    return 0


def verify_clean_payload() -> None:
    payload = payload_from("verify_clean")
    assert len(payload["items"]) == 20
    assert all(item["status"] == "safe_auto_grade" for item in payload["items"])
    assert [item["final_answer"] for item in payload["items"]] == [
        str((question - 1) % 5 + 1) for question in range(1, 21)
    ]
    assert_clean(payload)
    validate_payload(payload, PayloadMode.FINAL, "choice_omr_clean")


def verify_blank_retake_payload() -> None:
    payload = payload_from("verify_blank")
    assert all(item["status"] == "retake_required" for item in payload["items"])
    assert all(item["final_answer"] is None and item["source"] is None for item in payload["items"])
    assert_clean(payload)
    validate_payload(payload, PayloadMode.REVIEW, "choice_omr_blank")


def verify_multiple_retake_payload() -> None:
    payload = payload_from("verify_multiple")
    first = payload["items"][0]
    assert first["status"] == "retake_required"
    assert first["warnings"] == ["multiple_answers"]
    assert all(item["status"] == "safe_auto_grade" for item in payload["items"][1:])
    assert_clean(payload)
    validate_payload(payload, PayloadMode.REVIEW, "choice_omr_multiple")


def verify_non_choice_rejected() -> None:
    modes = list(MODES)
    modes[7] = "answer_value"
    request = ChoiceOmrRequest("fixture_choice_omr", 1, OCR_OUTPUT / "verify_clean" / "crops", tuple(modes))
    try:
        load_choice_omr_payload(request)
    except ChoiceOmrAdapterError as exc:
        assert "choice_number" in str(exc)
    else:
        raise AssertionError("non-choice OMR request was accepted")


def payload_from(case: str):
    request = ChoiceOmrRequest("fixture_choice_omr", 1, OCR_OUTPUT / case / "crops", MODES)
    return load_choice_omr_payload(request)


def assert_clean(payload) -> None:
    assert forbidden_paths(payload) == []
    assert not path_exposures(payload)


if __name__ == "__main__":
    raise SystemExit(main())
