from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.short_answer import normalize_short_answer
from core.test_answer_modes import ANSWER_VALUE
from tools.subjective_sheet_lab.ocr_payload_leak_policy import forbidden_paths, path_exposures


class HumanEvalError(ValueError):
    pass


def evaluate_against_human_transcription(
    pilot_payload: dict[str, Any], human_payload: dict[str, Any]
) -> dict[str, Any]:
    if pilot_payload.get("provider_calls") != 0:
        raise HumanEvalError("local pilot must report zero provider calls")
    pilot_items = _items_by_question(pilot_payload.get("items"), "pilot items")
    human_items = _human_items_by_question(human_payload.get("answers"))

    compared = 0
    exact_matches = 0
    unresolved = 0
    out_of_scope = 0
    low_confidence = 0
    rows: list[dict[str, Any]] = []
    for question_no, pilot_item in sorted(pilot_items.items()):
        human_item = human_items.get(question_no)
        if human_item is None:
            raise HumanEvalError(f"human transcription missing q{question_no:03d}")
        confidence = human_item.get("confidence")
        human_answer = human_item.get("human_answer")
        if confidence != "high":
            low_confidence += 1
            rows.append({"question": question_no, "evaluation": "human_low_confidence"})
            continue
        human_normalized = normalize_short_answer(human_answer, ANSWER_VALUE)
        if human_normalized is None:
            out_of_scope += 1
            rows.append({"question": question_no, "evaluation": "outside_supported_scope"})
            continue
        recognized = pilot_item.get("recognized")
        recognized_normalized = normalize_short_answer(recognized, ANSWER_VALUE)
        compared += 1
        if recognized_normalized is None:
            unresolved += 1
            evaluation = "review_required_unresolved"
        elif recognized_normalized == human_normalized:
            exact_matches += 1
            evaluation = "exact_match_review_only"
        else:
            evaluation = "mismatch_review_required"
        rows.append({"question": question_no, "evaluation": evaluation})

    report: dict[str, Any] = {
        "source": "pp_formulanet_s_local_human_eval",
        "developer_lab_only": True,
        "student_facing": False,
        "provider_calls": 0,
        "unsafe_auto_grade_count": 0,
        "summary": {
            "selected_crops": len(pilot_items),
            "high_confidence_in_scope": compared,
            "exact_matches": exact_matches,
            "unresolved": unresolved,
            "mismatches": compared - exact_matches - unresolved,
            "outside_supported_scope": out_of_scope,
            "human_low_confidence": low_confidence,
            "exact_match_percent": round(100.0 * exact_matches / compared, 2)
            if compared
            else None,
        },
        "items": rows,
    }
    _validate_report(report)
    return report


def write_report(report: dict[str, Any], output_path: Path) -> None:
    _validate_report(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _items_by_question(value: Any, label: str) -> dict[int, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise HumanEvalError(f"{label} must be a non-empty list")
    result: dict[int, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise HumanEvalError(f"{label} contains a non-object")
        question_no = item.get("question")
        if not isinstance(question_no, int) or not 1 <= question_no <= 20:
            raise HumanEvalError(f"{label} has an invalid question")
        if question_no in result:
            raise HumanEvalError(f"{label} has duplicate q{question_no:03d}")
        if item.get("status") != "review_required":
            raise HumanEvalError("pilot result must remain review_required")
        result[question_no] = item
    return result


def _human_items_by_question(value: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise HumanEvalError("human answers must be a non-empty list")
    result: dict[int, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise HumanEvalError("human answers contains a non-object")
        question_no = item.get("question_no")
        if not isinstance(question_no, int) or not 1 <= question_no <= 20:
            raise HumanEvalError("human answers has an invalid question")
        if question_no in result:
            raise HumanEvalError(f"human answers has duplicate q{question_no:03d}")
        result[question_no] = item
    return result


def _validate_report(report: dict[str, Any]) -> None:
    if forbidden_paths(report):
        raise HumanEvalError("human eval contains forbidden fields")
    if path_exposures(report):
        raise HumanEvalError("human eval exposes a local path")
    if report.get("provider_calls") != 0:
        raise HumanEvalError("human eval must report zero provider calls")
    if report.get("unsafe_auto_grade_count") != 0:
        raise HumanEvalError("local pilot cannot produce unsafe auto-grades")


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HumanEvalError(f"JSON root must be an object: {path.name}")
    return value


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare a blind local formula pilot with human transcription only."
    )
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--human-transcription", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    report = evaluate_against_human_transcription(
        _read_json_object(args.pilot), _read_json_object(args.human_transcription)
    )
    write_report(report, args.out)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HumanEvalError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from None
