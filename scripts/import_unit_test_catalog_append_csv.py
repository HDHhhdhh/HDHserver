from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "tests-config.json"
CSV_PATH = ROOT / "generated" / "unit_test_catalog_new_subjects.csv"

CATEGORY_LABELS = {
    "REVIEW": "복습 테스트",
    "UNIT": "단원평가",
    "SCHOOL_PAST": "학군지 기출",
    "ILSAN_PAST": "일산 기출",
}

HEADER_ALIASES = {
    "id": ("id", "source_id", "sourceId"),
    "category": ("분류", "category"),
    "subject": ("과목", "subject", "curriculum"),
    "difficulty": ("난이도", "difficulty", "level"),
    "round": ("회차", "round"),
    "name": ("시험명", "name", "test_name", "testName"),
    "problems": ("문항수", "problems", "problem_count", "problemCount"),
    "answers1": ("1회차정답", "answers1", "answer1", "answer_key_1", "answerKey1"),
    "answers2": ("2회차정답", "answers2", "answer2", "answer_key_2", "answerKey2"),
    "answers3": ("3회차정답", "answers3", "answer3", "answer_key_3", "answerKey3"),
}


def get_value(row: dict[str, str], field: str) -> str:
    for header in HEADER_ALIASES[field]:
        value = row.get(header)
        if value is not None:
            return str(value).strip()
    return ""


def parse_int(value: str, default: int, row_no: int, field: str) -> int:
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"row {row_no}: invalid {field}: {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"row {row_no}: {field} must be non-negative")
    return parsed


def parse_answers(text: str, problems: int) -> list[str]:
    parts = [part for part in re.split(r"[\s,]+", text or "") if part]
    if len(parts) > problems:
        return parts[:problems]
    return parts + ([""] * (problems - len(parts)))


def normalize_category(value: str) -> str:
    raw = str(value or "").strip()
    upper = raw.upper()
    labels = {
        "복습 테스트": "REVIEW",
        "복습테스트": "REVIEW",
        "단원평가": "UNIT",
        "학군지 기출": "SCHOOL_PAST",
        "학군지기출": "SCHOOL_PAST",
        "학교별 기출": "SCHOOL_PAST",
        "학교별기출": "SCHOOL_PAST",
        "일산 기출": "ILSAN_PAST",
        "일산기출": "ILSAN_PAST",
    }
    return upper if upper in CATEGORY_LABELS else labels.get(raw, "UNIT")


def ensure_category_scaffolding(cfg: dict[str, Any]) -> dict[str, Any]:
    categories = cfg.setdefault("categories", {})
    if not isinstance(categories, dict):
        categories = {}
        cfg["categories"] = categories

    for category_id, label in CATEGORY_LABELS.items():
        category = categories.setdefault(category_id, {})
        if not isinstance(category, dict):
            category = {}
            categories[category_id] = category
        category.setdefault("label", label)
        tests = category.setdefault("tests", [])
        if not isinstance(tests, list):
            category["tests"] = []

    return categories


def build_generated_tests(csv_path: Path) -> list[dict[str, Any]]:
    generated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for source_order, row in enumerate(reader, start=1):
            row_no = source_order + 1
            source_id = get_value(row, "id")
            if not source_id:
                raise ValueError(f"row {row_no}: missing required id")

            name = get_value(row, "name")
            if not name:
                raise ValueError(f"row {row_no}: missing required 시험명/name")

            problems = parse_int(get_value(row, "problems"), 20, row_no, "문항수/problems")
            category = normalize_category(get_value(row, "category"))
            subject = get_value(row, "subject")
            difficulty = get_value(row, "difficulty")
            source_round = get_value(row, "round")

            for round_no in ("1", "2", "3"):
                test_id = f"{source_id}_r{round_no}"
                if test_id in seen_ids:
                    raise ValueError(f"duplicate generated test id in CSV: {test_id}")
                seen_ids.add(test_id)

                answer_key = parse_answers(get_value(row, f"answers{round_no}"), problems)
                generated.append(
                    {
                        "id": test_id,
                        "sourceId": source_id,
                        "category": category,
                        "name": name,
                        "problems": problems,
                        "curriculum": subject,
                        "difficulty": difficulty,
                        "sourceRound": source_round,
                        "sortOrder": source_order,
                        "sourceOrder": source_order,
                        "round": round_no,
                        "answerKeys": {round_no: answer_key},
                        "answerKey": answer_key,
                    }
                )

    return generated


def merge_unit_tests(unit_tests: list[Any], generated: list[dict[str, Any]]) -> tuple[list[Any], int, int, int]:
    generated_by_id = {test["id"]: test for test in generated}
    existing_generated_ids = set()
    merged: list[Any] = []
    updated = 0
    preserved = 0

    for test in unit_tests:
        test_id = test.get("id") if isinstance(test, dict) else None
        replacement = generated_by_id.get(test_id)
        if replacement is None:
            merged.append(test)
            preserved += 1
            continue

        existing_generated_ids.add(test_id)
        if isinstance(test, dict):
            merged_test = dict(test)
            merged_test.update(replacement)
            merged.append(merged_test)
        else:
            merged.append(replacement)
        updated += 1

    added = 0
    for test in generated:
        if test["id"] not in existing_generated_ids:
            merged.append(test)
            added += 1

    return merged, added, updated, preserved


def write_json_atomic(path: Path, data: Any) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def main() -> int:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"source CSV not found: {CSV_PATH}")

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(cfg, dict):
        raise ValueError(f"{CONFIG_PATH} must contain a JSON object")

    categories = ensure_category_scaffolding(cfg)
    unit_category = categories["UNIT"]
    unit_tests = unit_category.get("tests", [])
    if not isinstance(unit_tests, list):
        unit_tests = []

    generated = build_generated_tests(CSV_PATH)
    merged, added, updated, preserved = merge_unit_tests(unit_tests, generated)
    unit_category["tests"] = merged

    write_json_atomic(CONFIG_PATH, cfg)
    print(f"UNIT tests added: {added}")
    print(f"UNIT tests updated: {updated}")
    print(f"UNIT tests preserved: {preserved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
