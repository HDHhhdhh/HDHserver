# /// script
# requires-python = ">=3.11"
# dependencies = ["flask"]
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_submit_test_offset_guard.py

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

from flask import Flask

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import api_basic, api_tests  # noqa: E402

TEST_ID: Final = "t_unit_daesu_01_lv3_r1"
ANSWER_KEY: Final = [
    "5", "4", "4", "3", "4",
    "2", "4", "12", "3", "9",
    "64", "42", "3", "4", "12",
    "5", "3", "30", "4", "16",
]
SHIFTED_ANSWERS: Final = [
    "4", "4", "3", "4", "2",
    "4", "12", "3", "9", "64",
    "42", "3", "4", "12", "5",
    "85", "3", "70", "4", "16",
]


class SubmitOffsetGuardVerificationError(Exception):
    pass


class FailingLogRepository:
    def append_record(self, *_args, **_kwargs):
        raise SubmitOffsetGuardVerificationError("submit route tried to save logs before offset guard returned")


def test_config():
    return {
        "categories": {
            "UNIT": {
                "label": "UNIT",
                "tests": [
                    {
                        "id": TEST_ID,
                        "name": "Daesu Jisu1 Lv3 R1",
                        "problems": 20,
                        "round": "1",
                        "answerKeys": {"1": ANSWER_KEY},
                    }
                ],
            }
        }
    }


def fail_save_atomic(*_args, **_kwargs):
    raise SubmitOffsetGuardVerificationError("submit route tried to save tests.json before offset guard returned")


def fail_mark_done(*_args, **_kwargs):
    raise SubmitOffsetGuardVerificationError("submit route tried to mark assignment done before offset guard returned")


def call_submit_with_shifted_answers() -> tuple[int, dict]:
    app = Flask(__name__)
    original_load_tests_cfg = api_tests._load_tests_cfg
    original_save_atomic = api_tests.save_atomic
    original_mark_done = api_tests._mark_submitted_assignment_done
    original_get_log_repository = api_basic.get_log_repository
    api_tests._load_tests_cfg = test_config
    api_tests.save_atomic = fail_save_atomic
    api_tests._mark_submitted_assignment_done = fail_mark_done
    api_basic.get_log_repository = lambda: FailingLogRepository()
    try:
        with app.test_request_context(
            "/api/submit-test",
            method="POST",
            json={
                "sid": "offset_guard_probe_849",
                "testId": TEST_ID,
                "round": 1,
                "answersText": "\n".join(SHIFTED_ANSWERS),
                "memo": "offset guard verifier",
                "answerSource": "ocr_review",
                "ocrReview": True,
            },
        ):
            result = api_tests.submit_test()
    finally:
        api_tests._load_tests_cfg = original_load_tests_cfg
        api_tests.save_atomic = original_save_atomic
        api_tests._mark_submitted_assignment_done = original_mark_done
        api_basic.get_log_repository = original_get_log_repository

    response, status = result
    payload = response.get_json()
    if not isinstance(payload, dict):
        raise SubmitOffsetGuardVerificationError("submit route returned non-object JSON")
    return int(status), payload


def assert_guard_blocks_shifted_answers() -> None:
    answers = api_tests._parse_answer_spec("\n".join(SHIFTED_ANSWERS), 20)
    correct, _total, _wrong, _pct = api_tests._grade_answers(answers, ANSWER_KEY)
    if correct != 4:
        raise SubmitOffsetGuardVerificationError(f"fixture should reproduce 4/20 direct score, got {correct}/20")
    if not api_tests._detect_shifted_answer_mapping(answers, ANSWER_KEY, correct):
        raise SubmitOffsetGuardVerificationError("offset guard did not detect the shifted fixture")

    status, payload = call_submit_with_shifted_answers()
    if status != 409:
        raise SubmitOffsetGuardVerificationError(f"expected HTTP 409, got {status}: {payload}")
    if payload.get("errorCode") != "possible_answer_offset":
        raise SubmitOffsetGuardVerificationError(f"expected possible_answer_offset, got {payload}")
    if payload.get("fallbackAllowed") is not False:
        raise SubmitOffsetGuardVerificationError("offset guard must disable client fallback")


def main() -> int:
    assert_guard_blocks_shifted_answers()
    print(json.dumps({
        "ok": True,
        "shifted_fixture_direct_score": "4/20",
        "submit_route_status": 409,
        "errorCode": "possible_answer_offset",
        "fallbackAllowed": False,
        "runtimeWrites": 0,
        "geminiCalls": 0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
