# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_q003_q018_ambiguity_manifest.py

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
Q003_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_q003_signal_audit.json"
DIGIT_SHAPE_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_priority_digit_shape_scores.json"
GENERALIZATION_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_digit_shape_generalization_matrix.json"
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_q003_q018_ambiguity_manifest.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_q003_q018_ambiguity_manifest.md"
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
class AmbiguityItem:
    key: str
    case_id: str
    question_no: int
    recognized: str
    status: str
    warnings: tuple[str, ...]
    signal_flags: tuple[str, ...]
    action: str
    safe_control: bool
    auto_confirm_allowed: bool


@dataclass(frozen=True, slots=True)
class AmbiguityManifestError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    q003 = read_json_object(Q003_JSON)
    digit_shape = read_json_object(DIGIT_SHAPE_JSON)
    generalization = read_json_object(GENERALIZATION_JSON)
    items = q003_items(q003) + q018_items(digit_shape)
    assert_manifest(items, generalization)
    output = output_json(items, generalization)
    output["sensitive_field_leak_count"] = leak_count(json.dumps(output, ensure_ascii=False))
    if output["sensitive_field_leak_count"] != 0:
        raise AmbiguityManifestError("sensitive token leaked into q003/q018 ambiguity manifest")
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(items, output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def q003_items(payload: JsonObject) -> tuple[AmbiguityItem, ...]:
    rows = tuple(require_object(value, "q003.results[]") for value in require_list(payload.get("results"), "q003.results"))
    return tuple(
        AmbiguityItem(
            key=f"q003_{require_text(row.get('interpretation'), 'q003.interpretation')}",
            case_id=require_text(row.get("case_id"), "q003.case_id"),
            question_no=3,
            recognized=require_text(row.get("probe_text"), "q003.probe_text"),
            status=require_text(row.get("status"), "q003.status"),
            warnings=read_text_tuple(row.get("warnings"), "q003.warnings"),
            signal_flags=read_text_tuple(row.get("signal_flags"), "q003.signal_flags"),
            action=action_for_status(require_text(row.get("status"), "q003.status")),
            safe_control=require_text(row.get("status"), "q003.status") == "safe_auto_grade",
            auto_confirm_allowed=False,
        )
        for row in rows
    )


def q018_items(payload: JsonObject) -> tuple[AmbiguityItem, ...]:
    rows = tuple(require_object(value, "digit_shape.results[]") for value in require_list(payload.get("results"), "digit_shape.results"))
    selected = tuple(row for row in rows if require_int(row.get("question_no"), "digit_shape.question_no") == 18)
    return tuple(q018_item(row) for row in selected)


def q018_item(row: JsonObject) -> AmbiguityItem:
    status = require_text(row.get("status"), "q018.status")
    shape = require_object(row.get("shape_summary"), "q018.shape_summary")
    return AmbiguityItem(
        key=require_text(row.get("name"), "q018.name"),
        case_id=require_text(row.get("case_id"), "q018.case_id"),
        question_no=18,
        recognized=require_text(row.get("recognized"), "q018.recognized"),
        status=status,
        warnings=read_text_tuple(row.get("warnings"), "q018.warnings"),
        signal_flags=read_text_tuple(shape.get("signal_flags"), "q018.signal_flags"),
        action=action_for_status(status),
        safe_control=status == "safe_auto_grade",
        auto_confirm_allowed=False,
    )


def action_for_status(status: str) -> str:
    if status == "safe_auto_grade":
        return "safe_control_preserved"
    return "route_to_review_required"


def assert_manifest(items: tuple[AmbiguityItem, ...], generalization: JsonObject) -> None:
    if len(items) != 6:
        raise AmbiguityManifestError(f"expected 6 ambiguity items, got {len(items)}")
    if sum(1 for item in items if item.question_no == 3) != 4:
        raise AmbiguityManifestError("q003 ambiguity item count must be 4")
    if sum(1 for item in items if item.question_no == 18) != 2:
        raise AmbiguityManifestError("q018 ambiguity item count must be 2")
    if sum(1 for item in items if item.status == "review_required") != 4:
        raise AmbiguityManifestError("review-required ambiguity item count must be 4")
    if sum(1 for item in items if item.safe_control) != 2:
        raise AmbiguityManifestError("safe control count must be 2")
    summary = require_object(generalization.get("summary"), "generalization.summary")
    require_int_value(summary.get("q003_three_n_signal_count"), 2, "q003_three_n_signal_count")
    require_int_value(summary.get("q018_leading_digit_not_nine_like_count"), 1, "q018_leading_digit_not_nine_like_count")
    require_int_value(summary.get("blank_like_row_count"), 5, "blank_like_row_count")


def output_json(items: tuple[AmbiguityItem, ...], generalization: JsonObject) -> JsonObject:
    summary = require_object(generalization.get("summary"), "generalization.summary")
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "manifest_item_count": len(items),
        "q003_item_count": 4,
        "q018_item_count": 2,
        "review_required_count": 4,
        "safe_control_count": 2,
        "auto_confirm_allowed_count": 0,
        "q003_three_n_signal_count": require_int(summary.get("q003_three_n_signal_count"), "q003_three_n_signal_count"),
        "q018_leading_digit_not_nine_like_count": require_int(summary.get("q018_leading_digit_not_nine_like_count"), "q018_leading_digit_not_nine_like_count"),
        "blank_like_control_count": require_int(summary.get("blank_like_row_count"), "blank_like_row_count"),
        "items": [asdict(item) for item in items],
        "filesystem_path_leak_count": 0,
    }


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), path.name)


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise AmbiguityManifestError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_list(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise AmbiguityManifestError(f"{label} must be a list")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise AmbiguityManifestError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_text(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value.strip()
        case None | bool() | int() | float() | list() | dict():
            raise AmbiguityManifestError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def read_text_tuple(value: JsonValue, label: str) -> tuple[str, ...]:
    return tuple(require_text(raw_value, f"{label}[]") for raw_value in require_list(value, label))


def require_int_value(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int(value, label)
    if actual != expected:
        raise AmbiguityManifestError(f"{label} expected {expected}, got {actual}")


def markdown_report(items: tuple[AmbiguityItem, ...], output: JsonObject) -> str:
    lines = ["# OCR q003/q018 Ambiguity Manifest", "", "| q | Case | OCR | Status | Action | Signals |", "|---:|---|---|---|---|---|"]
    for item in items:
        signals = ", ".join(item.signal_flags) if item.signal_flags else "-"
        lines.append(f"| {item.question_no} | `{item.case_id}` | `{item.recognized}` | `{item.status}` | `{item.action}` | `{signals}` |")
    lines.extend(
        (
            "",
            f"- manifest items: {output['manifest_item_count']}",
            f"- review-required items: {output['review_required_count']}",
            f"- safe controls: {output['safe_control_count']}",
            "- auto-confirm allowed: 0",
            "- Gemini/API calls: 0",
            "- External OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
        )
    )
    return "\n".join(lines) + "\n"


def leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)


if __name__ == "__main__":
    raise SystemExit(main())
