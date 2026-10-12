from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Final, TypeAlias

from tools.subjective_sheet_lab.run_deidentified_student_crop_gemini_qa import require_metadata_free_png

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

QUESTION_COUNT: Final[int] = 20
PATH_RE: Final[re.Pattern[str]] = re.compile(r"(?:[A-Za-z]:[\\/]|server-ocr|/Users/|/home/)", re.IGNORECASE)
FORBIDDEN_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r'"(?:expected|canonical_answer|accepted_answers|grading|answer_key)"\s*:',
    re.IGNORECASE,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True, type=Path)
    args = parser.parse_args()
    case_dir = args.case_dir.resolve()

    crops = sorted((case_dir / "deidentified_pack" / "crops").glob("answer_sheet_q*.png"))
    contacts = sorted((case_dir / "deidentified_pack" / "contact_sheets").glob("answer_sheet_q*_q*.png"))
    require(len(crops) == QUESTION_COUNT, "crop count must be 20")
    require(len(contacts) == 4, "contact-sheet count must be 4")
    for path in (*crops, *contacts):
        require_metadata_free_png(path)
    pack_dir = case_dir / "deidentified_pack"
    require(not any(path.name.lower().startswith("full_sheet") for path in pack_dir.rglob("*")), "full sheet entered provider pack")

    gate = read_object(case_dir / "deidentification_gate.json")
    visual = read_object(case_dir / "visual_deidentification_audit.json")
    require(gate.get("classification") == "PASS_DEIDENTIFICATION_GATE", "deidentification gate did not pass")
    require(visual.get("classification") == "PASS_VISUAL_DEIDENTIFICATION_AUDIT", "visual gate did not pass")

    recognized = read_object(case_dir / "recognized.json")
    recognized_items = require_twenty_items(recognized, "recognized")
    require(unique_questions(recognized_items, "question") == set(range(1, 21)), "recognized question contract mismatch")
    for item in recognized_items:
        require(item.get("status") == "review_required", "recognized item was not review_required")
        require(item.get("safe_auto_grade") is False, "recognized item was safe-auto-graded")
        require(item.get("final_answer") is None, "recognized item created final_answer")
        require(item.get("completion_status") in {"completed_recognized", "completed_unresolved", "pending"}, "completion status invalid")

    review = read_object(case_dir / "review_payload.json")
    review_items = require_twenty_items(review, "review payload")
    require(unique_questions(review_items, "question_no") == set(range(1, 21)), "review question contract mismatch")
    candidate_count = 0
    for item in review_items:
        require(item.get("status") == "review_required", "review item status must be review_required")
        require(item.get("final_answer") is None, "review item created final_answer")
        candidates = item.get("candidates")
        require(isinstance(candidates, list), "review candidates must be a list")
        require(item.get("direct_input_allowed") is True, "review item lacks direct-input action")
        candidate_count += int(bool(candidates))
    require(candidate_count == 15, "partial-fill candidate count must be 15")
    for question_no in (16, 17, 18):
        item = next(item for item in review_items if item["question_no"] == question_no)
        require(item.get("candidates") == [], f"q{question_no:03d} must remain direct-input only")

    evaluation = read_object(case_dir / "evaluation_summary.json")
    require(evaluation.get("ocr_vs_human_matched") == 17, "OCR-vs-human match count changed")
    require(evaluation.get("recognized_count") == 20, "recognized count changed")
    require(evaluation.get("high_confidence_matched") == 17, "high-confidence match count changed")
    require(evaluation.get("high_confidence_count") == 18, "high-confidence denominator changed")
    require(evaluation.get("wrong_safe_auto_grade") == 0, "wrong safe-auto-grade must be zero")
    require(evaluation.get("second_pass_disagreement") is True, "second-pass disagreement guard missing")

    provider = read_object(case_dir / "provider_summary.json")
    call_count = provider.get("provider_call_count")
    require(isinstance(call_count, int) and not isinstance(call_count, bool) and 0 <= call_count <= 5, "provider budget invalid")
    require(provider.get("retry_count") == 0, "unexpected provider retry")

    scanned = [
        case_dir / "recognized.json",
        case_dir / "review_payload.json",
        case_dir / "deidentification_gate.json",
        case_dir / "visual_deidentification_audit.json",
        case_dir / "deidentified_pack" / "transmission_manifest.json",
    ]
    for path in scanned:
        text = path.read_text(encoding="utf-8-sig")
        require(PATH_RE.search(text) is None, f"path leak in {path.name}")
        require(FORBIDDEN_KEY_RE.search(text) is None, f"forbidden field in {path.name}")

    print(
        json.dumps(
            {
                "ok": True,
                "crop_count": len(crops),
                "contact_sheet_count": len(contacts),
                "recognized_count": 20,
                "review_item_count": 20,
                "candidate_count": candidate_count,
                "wrong_safe_auto_grade": 0,
                "provider_call_count": call_count,
                "path_or_forbidden_field_hits": 0,
            },
            sort_keys=True,
        )
    )
    return 0


def read_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"{path.name} must be an object")
    return value


def require_twenty_items(payload: JsonObject, label: str) -> list[JsonObject]:
    items = payload.get("items")
    require(isinstance(items, list) and len(items) == QUESTION_COUNT, f"{label} must contain 20 items")
    require(all(isinstance(item, dict) for item in items), f"{label} items must be objects")
    return items  # type: ignore[return-value]


def unique_questions(items: list[JsonObject], key: str) -> set[int]:
    values = {item.get(key) for item in items}
    require(all(isinstance(value, int) and not isinstance(value, bool) for value in values), f"{key} values must be integers")
    return values  # type: ignore[return-value]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())
