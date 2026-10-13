# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_q015_q016_relation_operator_manifest.py

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

LAB: Final[Path] = Path(__file__).resolve().parent
PRIORITY_JSON: Final[Path] = LAB / "ocr_accuracy_improvement_priorities.json"
REPORT_JSON: Final[Path] = LAB / "ocr_q015_q016_relation_operator_manifest.json"
REPORT_MD: Final[Path] = LAB / "ocr_q015_q016_relation_operator_manifest.md"
CASE_ID: Final[str] = "person_02_same_contact"
FORBIDDEN_OUTPUT_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
    "crop_path",
    "C:\\",
    "C:/",
    "/c/",
)


@dataclass(frozen=True, slots=True)
class RelationOperatorItem:
    case_id: str
    question_no: int
    recognized: str
    human_answer: str
    status: str
    confidence: str
    warnings: tuple[str, ...]
    action: str
    auto_confirm_allowed: bool


@dataclass(frozen=True, slots=True)
class RelationOperatorManifestError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    priority = read_json_object(PRIORITY_JSON)
    items = manifest_items(priority)
    assert_manifest(items)
    output = output_json(items)
    if leak_count(json.dumps(output, ensure_ascii=False)) != 0:
        raise RelationOperatorManifestError("sensitive token leaked into q015/q016 relation manifest")
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(items, output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def manifest_items(priority: JsonObject) -> tuple[RelationOperatorItem, ...]:
    rows = tuple(require_object(value, "priorities.top_row_priorities[]") for value in require_list(priority.get("top_row_priorities"), "priorities.top_row_priorities"))
    selected = tuple(row for row in rows if row_key(row) in {(CASE_ID, 15), (CASE_ID, 16)})
    if len(selected) != 2:
        raise RelationOperatorManifestError(f"expected two person_02 q015/q016 priority rows, got {len(selected)}")
    return tuple(relation_item(row) for row in sorted(selected, key=lambda item: require_int(item.get("question_no"), "question_no")))


def relation_item(row: JsonObject) -> RelationOperatorItem:
    question_no = require_int(row.get("question_no"), "question_no")
    warnings = warnings_for_question(question_no)
    return RelationOperatorItem(
        case_id=require_text(row.get("case_id"), "case_id"),
        question_no=question_no,
        recognized=require_text(row.get("recognized"), "recognized"),
        human_answer=require_text(row.get("human_answer"), "human_answer"),
        status=require_text(row.get("policy_status"), "policy_status"),
        confidence=require_text(row.get("confidence"), "confidence"),
        warnings=warnings,
        action="route_to_review_required",
        auto_confirm_allowed=False,
    )


def warnings_for_question(question_no: int) -> tuple[str, ...]:
    match question_no:
        case 15:
            return ("relation_symbol_confusion", "expression_operator_confusion")
        case 16:
            return ("arrow_equal_confusion", "relation_symbol_confusion")
        case int():
            raise RelationOperatorManifestError(f"unsupported relation question {question_no}")
        case unreachable:
            assert_never(unreachable)


def row_key(row: JsonObject) -> tuple[str, int]:
    return require_text(row.get("case_id"), "case_id"), require_int(row.get("question_no"), "question_no")


def assert_manifest(items: tuple[RelationOperatorItem, ...]) -> None:
    expected_pairs = {
        15: ("-1<=x<=5", "-1<x<5"),
        16: ("y=3", "y→3"),
    }
    if len(items) != 2:
        raise RelationOperatorManifestError(f"expected 2 relation items, got {len(items)}")
    for item in items:
        recognized, human = expected_pairs[item.question_no]
        if item.recognized != recognized or item.human_answer != human:
            raise RelationOperatorManifestError(f"q{item.question_no:03d} relation pair changed")
        if item.status != "review_required":
            raise RelationOperatorManifestError(f"q{item.question_no:03d} must remain review_required")
        if item.confidence != "high":
            raise RelationOperatorManifestError(f"q{item.question_no:03d} must remain high-confidence evidence")
        if item.auto_confirm_allowed:
            raise RelationOperatorManifestError(f"q{item.question_no:03d} must not auto-confirm")


def output_json(items: tuple[RelationOperatorItem, ...]) -> JsonObject:
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "manifest_item_count": len(items),
        "review_required_count": len(items),
        "safe_control_count": 0,
        "auto_confirm_allowed_count": 0,
        "relation_symbol_confusion_count": 2,
        "expression_operator_confusion_count": 1,
        "arrow_equal_confusion_count": 1,
        "high_confidence_mismatch_count": 2,
        "items": [asdict(item) for item in items],
        "filesystem_path_leak_count": 0,
        "sensitive_field_leak_count": 0,
    }


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), path.name)


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise RelationOperatorManifestError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_list(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise RelationOperatorManifestError(f"{label} must be a list")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise RelationOperatorManifestError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_text(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value.strip()
        case None | bool() | int() | float() | list() | dict():
            raise RelationOperatorManifestError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def markdown_report(items: tuple[RelationOperatorItem, ...], output: JsonObject) -> str:
    lines = [
        "# OCR q015/q016 Relation Operator Manifest",
        "",
        "| q | Case | OCR | Human transcription | Status | Warnings |",
        "|---:|---|---|---|---|---|",
    ]
    for item in items:
        lines.append(
            f"| {item.question_no} | `{item.case_id}` | `{item.recognized}` | "
            f"`{item.human_answer}` | `{item.status}` | `{', '.join(item.warnings)}` |"
        )
    lines.extend(
        (
            "",
            f"- manifest items: {output['manifest_item_count']}",
            f"- review-required items: {output['review_required_count']}",
            "- auto-confirm allowed: 0",
            "- Gemini/API calls: 0",
            "- External OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- answer-key/grading/path leak count: 0",
        )
    )
    return "\n".join(lines) + "\n"


def leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)


if __name__ == "__main__":
    raise SystemExit(main())
