# /// script
# requires-python = ">=3.11"
# dependencies = ["flask"]
# ///
#
# --- How to run ---
# python scripts\verify_admin_tests_record_details.py

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path
from typing import Final

from flask import Flask

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.storage import save_atomic  # noqa: E402
from routes import api_basic, api_tests  # noqa: E402
from scripts.admin_tests_record_detail_fixtures import (  # noqa: E402
    ANSWER_URL,
    EXPECTED_DETAILS,
    FORBIDDEN_DETAIL_KEYS,
    STORED_WRONG_DETAIL_MARKERS,
    TEST_ID,
    EmptyLogRepository,
    legacy_answers_text_record,
    legacy_test_record,
    local_test_config,
    test_record,
)


class AdminTestRecordDetailsVerificationError(Exception):
    pass


def assert_admin_record_detail_contract() -> dict[str, bool | int | float | str | list[dict[str, str | int]]]:
    app = Flask(__name__)
    app.register_blueprint(api_tests.bp_api_tests)

    original_tests_path = api_tests.TESTS_PATH
    original_logs_path = api_tests.LOGS_PATH
    original_students_path = api_tests.STU_PATH
    original_load_tests_cfg = api_tests._load_tests_cfg
    original_academy_network_allowed = api_tests.academy_network_allowed
    original_get_log_repository = api_basic.get_log_repository
    original_answer_config_loader = api_basic._load_tests_config_for_answer_links
    original_answer_map_loader = api_basic._load_test_answer_link_map

    with tempfile.TemporaryDirectory() as directory:
        temp_root = Path(directory)
        today = dt.date.today().isoformat()
        api_tests.TESTS_PATH = temp_root / "tests.json"
        api_tests.LOGS_PATH = temp_root / "logs.json"
        api_tests.STU_PATH = temp_root / "students.json"
        api_tests._load_tests_cfg = local_test_config
        api_tests.academy_network_allowed = lambda: True
        api_basic.get_log_repository = EmptyLogRepository
        api_basic._load_tests_config_for_answer_links = local_test_config
        api_basic._load_test_answer_link_map = lambda: {}
        try:
            save_atomic(
                api_tests.STU_PATH,
                [
                    {"id": "qa001", "name": "QA Student", "level": "중"},
                    {"id": "qa002", "name": "Legacy Student", "level": "상"},
                    {"id": "qa003", "name": "Legacy Answers Text Student", "level": "하"},
                ],
            )
            save_atomic(api_tests.LOGS_PATH, {})
            save_atomic(
                api_tests.TESTS_PATH,
                {
                    today: {
                        "qa001": [test_record(f"{today}T00:00:00Z")],
                        "qa002": [legacy_test_record(f"{today}T01:00:00Z")],
                        "qa003": [legacy_answers_text_record(f"{today}T02:00:00Z")],
                    },
                },
            )

            client = app.test_client()
            public_payload = client.get("/api/tests").get_json()
            detail_payload = client.get(f"/api/tests-records?test_id={TEST_ID}&recent_days=3650").get_json()
            api_tests.academy_network_allowed = lambda: False
            restricted_detail_payload = client.get(f"/api/tests-records?test_id={TEST_ID}&recent_days=3650").get_json()
        finally:
            api_tests.TESTS_PATH = original_tests_path
            api_tests.LOGS_PATH = original_logs_path
            api_tests.STU_PATH = original_students_path
            api_tests._load_tests_cfg = original_load_tests_cfg
            api_tests.academy_network_allowed = original_academy_network_allowed
            api_basic.get_log_repository = original_get_log_repository
            api_basic._load_tests_config_for_answer_links = original_answer_config_loader
            api_basic._load_test_answer_link_map = original_answer_map_loader

    public_text = json.dumps(public_payload, ensure_ascii=False)
    public_leaked_keys = [key for key in ("submittedAnswers", "answersText", "wrongDetails") if key in public_text]
    if public_leaked_keys:
        raise AdminTestRecordDetailsVerificationError(f"/api/tests leaked internal answer fields: {public_leaked_keys}")
    public_leaked_values = [marker for marker in STORED_WRONG_DETAIL_MARKERS if marker in public_text]
    if public_leaked_values:
        raise AdminTestRecordDetailsVerificationError(
            f"/api/tests leaked stored raw wrongDetails values: {public_leaked_values}"
        )
    if not isinstance(detail_payload, dict):
        raise AdminTestRecordDetailsVerificationError("/api/tests-records returned non-object JSON")
    if not isinstance(restricted_detail_payload, dict):
        raise AdminTestRecordDetailsVerificationError("restricted /api/tests-records returned non-object JSON")
    records = detail_payload.get("records")
    if not isinstance(records, list):
        raise AdminTestRecordDetailsVerificationError("/api/tests-records missing records list")
    qa_record = next((item for item in records if isinstance(item, dict) and item.get("sid") == "qa001"), None)
    legacy_record = next((item for item in records if isinstance(item, dict) and item.get("sid") == "qa002"), None)
    legacy_answers_text = next((item for item in records if isinstance(item, dict) and item.get("sid") == "qa003"), None)
    if not isinstance(qa_record, dict):
        raise AdminTestRecordDetailsVerificationError("QA record missing from admin detail response")
    if not isinstance(legacy_record, dict):
        raise AdminTestRecordDetailsVerificationError("legacy record missing from admin detail response")
    if not isinstance(legacy_answers_text, dict):
        raise AdminTestRecordDetailsVerificationError("legacy answersText record missing from admin detail response")
    detail_text = json.dumps(detail_payload, ensure_ascii=False)
    leaked_keys = [key for key in FORBIDDEN_DETAIL_KEYS if key in detail_text]
    if leaked_keys:
        raise AdminTestRecordDetailsVerificationError(f"/api/tests-records leaked internal keys: {leaked_keys}")
    detail_leaked_values = [marker for marker in STORED_WRONG_DETAIL_MARKERS if marker in detail_text]
    if detail_leaked_values:
        raise AdminTestRecordDetailsVerificationError(
            f"/api/tests-records leaked stored raw wrongDetails values: {detail_leaked_values}"
        )
    if detail_payload.get("answerUrl") != ANSWER_URL:
        raise AdminTestRecordDetailsVerificationError(f"admin answerUrl mismatch: {detail_payload}")
    if restricted_detail_payload.get("answerUrl") != "":
        raise AdminTestRecordDetailsVerificationError(
            f"restricted admin answerUrl was not hidden: {restricted_detail_payload}"
        )
    if qa_record.get("wrong") != [1, 2]:
        raise AdminTestRecordDetailsVerificationError(f"wrong list was not normalized: {qa_record}")
    if qa_record.get("wrongDetails") != list(EXPECTED_DETAILS):
        raise AdminTestRecordDetailsVerificationError(f"wrongDetails mismatch: {qa_record}")
    if legacy_record.get("wrong") != [3] or legacy_record.get("wrongDetails") != []:
        raise AdminTestRecordDetailsVerificationError(f"legacy wrongDetails fallback mismatch: {legacy_record}")
    if legacy_answers_text.get("wrongDetails") != list(EXPECTED_DETAILS):
        raise AdminTestRecordDetailsVerificationError(
            f"legacy answersText wrongDetails mismatch: {legacy_answers_text}"
        )
    return {
        "publicSubmittedAnswersLeak": False,
        "publicAnswersTextLeak": False,
        "publicWrongDetailsLeak": False,
        "publicRawWrongDetailsValueLeak": False,
        "adminSensitiveFieldLeak": False,
        "adminRawWrongDetailsValueLeak": False,
        "adminAnswerUrl": detail_payload["answerUrl"],
        "restrictedAnswerUrlHidden": True,
        "adminWrongDetails": qa_record["wrongDetails"],
        "legacyWrongDetailsFallback": True,
        "legacyAnswersTextWrongDetails": True,
        "runtimeWrites": 0,
    }


def main() -> int:
    result = assert_admin_record_detail_contract()
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
