# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_digit_shape_candidate_comparison.py

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

LAB: Final[Path] = Path(__file__).resolve().parent
AMBIGUITY_JSON: Final[Path] = LAB / "ocr_q003_q018_ambiguity_manifest.json"
HIGH_PRIORITY_JSON: Final[Path] = LAB / "ocr_high_priority_mismatch_crop_quality.json"
REPORT_JSON: Final[Path] = LAB / "ocr_digit_shape_candidate_comparison.json"
REPORT_MD: Final[Path] = LAB / "ocr_digit_shape_candidate_comparison.md"
ANSWER_KEY_OR_GRADING_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
)
FILESYSTEM_PATH_TOKENS: Final[tuple[str, ...]] = (
    "crop_path",
    "C:\\",
    "C:/",
    "/c/",
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class CandidateRow:
    family: str
    question_no: int
    case_id: str
    recognized: str
    status: str
    warnings: tuple[str, ...]
    signal_flags: tuple[str, ...]
    action: str
    candidate_use: str
    auto_fill_allowed: bool


class DigitShapeCandidateComparisonError(Exception):
    pass


def main() -> int:
    rows = candidate_rows()
    output = output_json(rows)
    require_output(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(rows, output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def candidate_rows() -> tuple[CandidateRow, ...]:
    manifest = read_json_object(AMBIGUITY_JSON)
    high_priority = read_json_object(HIGH_PRIORITY_JSON)
    items = tuple(object_value(item, "items[]") for item in list_value(manifest.get("items"), "items"))
    rows = tuple(row_from_item(item) for item in items if int_value(item.get("question_no"), "question_no") in (3, 18))
    if int_value(high_priority.get("digit_shape_row_count"), "digit_shape_row_count") != 2:
        raise DigitShapeCandidateComparisonError("high-priority digit-shape row count changed")
    return rows


def row_from_item(item: JsonObject) -> CandidateRow:
    question_no = int_value(item.get("question_no"), "question_no")
    status = text_value(item.get("status"), "status")
    action = text_value(item.get("action"), "action")
    signals = text_tuple(item.get("signal_flags"), "signal_flags")
    family = family_for(question_no, signals)
    candidate_use = candidate_use_for(status, signals)
    return CandidateRow(
        family=family,
        question_no=question_no,
        case_id=text_value(item.get("case_id"), "case_id"),
        recognized=text_value(item.get("recognized"), "recognized"),
        status=status,
        warnings=text_tuple(item.get("warnings"), "warnings"),
        signal_flags=signals,
        action=action,
        candidate_use=candidate_use,
        auto_fill_allowed=bool_value(item.get("auto_confirm_allowed"), "auto_confirm_allowed"),
    )


def family_for(question_no: int, signals: tuple[str, ...]) -> str:
    match question_no:
        case 3:
            if "three_n_shape_conflict" in signals:
                return "three_n_shape_conflict"
            return "relation_only_q003"
        case 18:
            return "thirty_ninety_shape_conflict"
        case unreachable:
            assert_never(unreachable)


def candidate_use_for(status: str, signals: tuple[str, ...]) -> str:
    if status == "safe_auto_grade":
        return "safe_control_only"
    if signals:
        return "review_required_candidate_signal"
    return "review_required_policy_signal"


def output_json(rows: tuple[CandidateRow, ...]) -> JsonObject:
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "row_count": len(rows),
        "review_required_count": sum(1 for row in rows if row.status == "review_required"),
        "safe_control_count": sum(1 for row in rows if row.status == "safe_auto_grade"),
        "candidate_signal_count": sum(1 for row in rows if row.candidate_use == "review_required_candidate_signal"),
        "policy_signal_count": sum(1 for row in rows if row.candidate_use == "review_required_policy_signal"),
        "auto_fill_allowed_count": sum(1 for row in rows if row.auto_fill_allowed),
        "family_counts": family_counts(rows),
        "rows": [asdict(row) for row in rows],
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "sensitive_field_leak_count": 0,
        "next_safe_action": "Keep digit-shape candidate comparison in provider-free regression before live OCR QA.",
    }
    scan_payload = {
        key: value
        for key, value in output.items()
        if key
        not in (
            "answer_key_or_grading_field_leak_count",
            "filesystem_path_leak_count",
            "sensitive_field_leak_count",
            "next_safe_action",
        )
    }
    text = json.dumps(scan_payload, ensure_ascii=False)
    answer_key_leaks = token_leak_count(text, ANSWER_KEY_OR_GRADING_TOKENS)
    path_leaks = token_leak_count(text, FILESYSTEM_PATH_TOKENS)
    output["answer_key_or_grading_field_leak_count"] = answer_key_leaks
    output["filesystem_path_leak_count"] = path_leaks
    output["sensitive_field_leak_count"] = answer_key_leaks + path_leaks
    return output


def family_counts(rows: tuple[CandidateRow, ...]) -> JsonObject:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.family] = counts.get(row.family, 0) + 1
    return counts


def require_output(output: JsonObject) -> None:
    expected_counts: JsonObject = {
        "three_n_shape_conflict": 3,
        "relation_only_q003": 1,
        "thirty_ninety_shape_conflict": 2,
    }
    if output["row_count"] != 6 or output["review_required_count"] != 4 or output["safe_control_count"] != 2:
        raise DigitShapeCandidateComparisonError("candidate comparison coverage changed")
    if output["candidate_signal_count"] != 3 or output["policy_signal_count"] != 1:
        raise DigitShapeCandidateComparisonError("candidate signal split changed")
    if output["auto_fill_allowed_count"] != 0:
        raise DigitShapeCandidateComparisonError("candidate comparison must not allow auto-fill")
    if output["family_counts"] != expected_counts:
        raise DigitShapeCandidateComparisonError("candidate family counts changed")
    if output["answer_key_or_grading_field_leak_count"] != 0 or output["filesystem_path_leak_count"] != 0:
        raise DigitShapeCandidateComparisonError("candidate comparison leaked sensitive text")


def markdown_report(rows: tuple[CandidateRow, ...], output: JsonObject) -> str:
    lines = [
        "# OCR Digit Shape Candidate Comparison",
        "",
        "| family | q | case | OCR | status | candidate use | signals |",
        "|---|---:|---|---|---|---|---|",
    ]
    for row in rows:
        signals = ", ".join(row.signal_flags) if row.signal_flags else "-"
        lines.append(
            f"| `{row.family}` | {row.question_no} | `{row.case_id}` | `{row.recognized}` | "
            f"`{row.status}` | `{row.candidate_use}` | `{signals}` |"
        )
    lines.extend(
        (
            "",
            f"- rows: {output['row_count']}",
            f"- review-required rows: {output['review_required_count']}",
            f"- safe controls: {output['safe_control_count']}",
            f"- candidate-signal rows: {output['candidate_signal_count']}",
            f"- policy-signal rows: {output['policy_signal_count']}",
            "- auto-fill allowed rows: 0",
            "- Gemini/API calls: 0",
            "- External OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- Answer-key/grading leak count: 0",
            "- Filesystem path leak count: 0",
            "- Production default: `NO_GO`",
            "",
        )
    )
    return "\n".join(lines)


def read_json_object(path: Path) -> JsonObject:
    return object_value(json.loads(path.read_text(encoding="utf-8-sig")), path.name)


def object_value(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise DigitShapeCandidateComparisonError(f"{label} must be an object")
        case unreachable:
            assert_never(unreachable)


def list_value(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise DigitShapeCandidateComparisonError(f"{label} must be a list")
        case unreachable:
            assert_never(unreachable)


def int_value(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise DigitShapeCandidateComparisonError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def text_value(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value.strip()
        case None | bool() | int() | float() | list() | dict():
            raise DigitShapeCandidateComparisonError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def bool_value(value: JsonValue, label: str) -> bool:
    match value:
        case bool():
            return value
        case None | int() | float() | str() | list() | dict():
            raise DigitShapeCandidateComparisonError(f"{label} must be boolean")
        case unreachable:
            assert_never(unreachable)


def text_tuple(value: JsonValue, label: str) -> tuple[str, ...]:
    return tuple(text_value(item, f"{label}[]") for item in list_value(value, label))


def token_leak_count(text: str, tokens: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for token in tokens if token.lower() in lowered)


if __name__ == "__main__":
    raise SystemExit(main())
