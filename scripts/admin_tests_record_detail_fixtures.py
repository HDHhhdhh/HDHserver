from __future__ import annotations

from typing import Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

TEST_ID: Final = "admin_detail_contract_test"
ANSWER_URL: Final = "https://answers.example/admin-detail-contract.pdf"
ANSWER_KEY: Final = ["5", "4", "3", "2"]
SUBMITTED_ANSWERS: Final = ["1", "2", "3", "2"]
EXPECTED_DETAILS: Final = (
    {"questionNo": 1, "myAnswer": "1", "correctAnswer": "5"},
    {"questionNo": 2, "myAnswer": "2", "correctAnswer": "4"},
)
LEGACY_ANSWERS_TEXT: Final = "1\n2\n3\n2"
STORED_WRONG_DETAILS: Final = [{"questionNo": 1, "myAnswer": "raw", "correctAnswer": "secret"}]
STORED_WRONG_DETAIL_MARKERS: Final = ("raw", "secret")
FORBIDDEN_DETAIL_KEYS: Final = (
    "submittedAnswers",
    "answersText",
    "answerKeys",
    "canonical_answer",
    "accepted_answers",
    "expected",
    "grading",
)


class EmptyLogRepository:
    def read_json_map(self) -> dict[str, JsonValue]:
        return {}


def local_test_config() -> dict[str, JsonValue]:
    return {
        "categories": {
            "UNIT": {
                "label": "UNIT",
                "tests": [
                    {
                        "id": TEST_ID,
                        "name": "Admin Detail Contract",
                        "problems": 4,
                        "round": "1",
                        "answerUrl": ANSWER_URL,
                        "answerKeys": {"1": ANSWER_KEY},
                    },
                ],
            },
        },
    }


def test_record(created_at: str) -> dict[str, JsonValue]:
    return {
        "testId": TEST_ID,
        "round": 1,
        "name": "Admin Detail Contract",
        "score": "2/4",
        "wrong": ["1", "2"],
        "memo": "",
        "pct": 50,
        "createdAt": created_at,
        "type": "UNIT",
        "curriculum": "QA",
        "testName": "Admin Detail Contract",
        "unitName": "Admin Detail Contract",
        "testLevel": 3,
        "difficulty": "Lv.3",
        "term": "",
        "sourceId": "",
        "testMeta": {
            "type": "UNIT",
            "curriculum": "QA",
            "test_name": "Admin Detail Contract",
            "unit_name": "Admin Detail Contract",
            "test_level": 3,
            "round": "1",
        },
        "submittedAnswers": SUBMITTED_ANSWERS,
        "wrongDetails": STORED_WRONG_DETAILS,
    }


def legacy_test_record(created_at: str) -> dict[str, JsonValue]:
    record = test_record(created_at)
    record["score"] = "3/4"
    record["wrong"] = ["3"]
    record["pct"] = 75
    record.pop("submittedAnswers", None)
    return record


def legacy_answers_text_record(created_at: str) -> dict[str, JsonValue]:
    record = test_record(created_at)
    record.pop("submittedAnswers", None)
    record["answersText"] = LEGACY_ANSWERS_TEXT
    return record
