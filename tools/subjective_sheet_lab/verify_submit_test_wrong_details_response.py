# /// script
# requires-python = ">=3.11"
# dependencies = ["flask"]
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_submit_test_wrong_details_response.py

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
ANSWER_KEY: Final = ["5", "4", "4", "3"]
SUBMITTED_ANSWERS: Final = ["5", "1", "4", "2"]


class WrongDetailsVerificationError(Exception):
    pass


class DummyLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, _exc_type, _exc, _tb) -> bool:
        return False


class CapturingLogRepository:
    def append_record(self, *_args, **_kwargs) -> bool:
        return True


def test_config() -> dict:
    return {
        "categories": {
            "UNIT": {
                "label": "UNIT",
                "tests": [
                    {
                        "id": TEST_ID,
                        "name": "Daesu Jisu1 Lv3 R1",
                        "problems": 4,
                        "round": "1",
                        "answerKeys": {"1": ANSWER_KEY},
                    },
                ],
            },
        },
    }


def call_submit_without_runtime_writes() -> dict:
    app = Flask(__name__)
    original_load_tests_cfg = api_tests._load_tests_cfg
    original_load = api_tests.load
    original_save_atomic = api_tests.save_atomic
    original_tests_lock = api_tests._tests_lock
    original_progress = api_tests._submit_assignment_progress_status_result
    original_get_log_repository = api_basic.get_log_repository
    api_tests._load_tests_cfg = test_config
    api_tests.load = lambda _path: {}
    api_tests.save_atomic = lambda *_args, **_kwargs: None
    api_tests._tests_lock = lambda: DummyLock()
    api_tests._submit_assignment_progress_status_result = lambda *_args, **_kwargs: {"completed": False}
    api_basic.get_log_repository = lambda: CapturingLogRepository()
    try:
        with app.test_request_context(
            "/api/submit-test",
            method="POST",
            json={
                "sid": "wrong_details_probe_849",
                "testId": TEST_ID,
                "round": 1,
                "answersText": "\n".join(SUBMITTED_ANSWERS),
                "memo": "wrong details verifier",
            },
        ):
            response = api_tests.submit_test()
    finally:
        api_tests._load_tests_cfg = original_load_tests_cfg
        api_tests.load = original_load
        api_tests.save_atomic = original_save_atomic
        api_tests._tests_lock = original_tests_lock
        api_tests._submit_assignment_progress_status_result = original_progress
        api_basic.get_log_repository = original_get_log_repository

    payload = response.get_json()
    if not isinstance(payload, dict):
        raise WrongDetailsVerificationError("submit route returned non-object JSON")
    return payload


def main() -> int:
    payload = call_submit_without_runtime_writes()
    expected = [
        {"questionNo": 2, "myAnswer": "1", "correctAnswer": "4"},
        {"questionNo": 4, "myAnswer": "2", "correctAnswer": "3"},
    ]
    if payload.get("score") != "2/4":
        raise WrongDetailsVerificationError(f"unexpected score: {payload}")
    if payload.get("wrong") != [2, 4]:
        raise WrongDetailsVerificationError(f"unexpected wrong list: {payload}")
    if payload.get("wrongDetails") != expected:
        raise WrongDetailsVerificationError(f"unexpected wrongDetails: {payload}")
    print(json.dumps({"ok": True, "wrongDetails": expected, "runtimeWrites": 0}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
