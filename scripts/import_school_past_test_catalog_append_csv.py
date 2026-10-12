from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "tests-config.json"
CSV_PATH = ROOT / "generated" / "school_past_test_catalog.csv"

CATEGORY_LABELS = {
    "REVIEW": "복습 테스트",
    "UNIT": "단원평가",
    "SCHOOL_PAST": "학군지 기출",
    "ILSAN_PAST": "일산 기출",
}

REQUIRED_FIELDS = (
    "id",
    "subject",
    "difficulty",
    "term",
    "examTerm",
    "round",
    "name",
    "problems",
    "source_order",
)


def get_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name)
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


def parse_answers(row: dict[str, str], problems: int, row_no: int) -> list[str]:
    answers_json = get_value(row, "answers_json", "answersJson")
    if answers_json:
        try:
            parsed = json.loads(answers_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"row {row_no}: invalid answers_json") from exc
        if not isinstance(parsed, list):
            raise ValueError(f"row {row_no}: answers_json must be a list")
        values = [str(value or "").strip() for value in parsed]
    else:
        values = [part for part in re.split(r"[\s,]+", get_value(row, "answers")) if part]

    if len(values) > problems:
        return values[:problems]
    return values + ([""] * (problems - len(values)))


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
        if not isinstance(category.get("tests"), list):
            category["tests"] = []

    return categories


def build_generated_tests(csv_path: Path) -> list[dict[str, Any]]:
    generated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{csv_path} has no headers")
        missing = [field for field in REQUIRED_FIELDS if field not in reader.fieldnames]
        if missing:
            raise ValueError(f"{csv_path} missing required headers: {', '.join(missing)}")

        for source_index, row in enumerate(reader, start=1):
            row_no = source_index + 1
            test_id = get_value(row, "id")
            if not test_id:
                raise ValueError(f"row {row_no}: missing id")
            if test_id in seen_ids:
                raise ValueError(f"duplicate test id in CSV: {test_id}")
            seen_ids.add(test_id)

            name = get_value(row, "name")
            subject = get_value(row, "subject")
            difficulty = get_value(row, "difficulty")
            term = get_value(row, "term")
            exam_term = get_value(row, "examTerm", "exam_term")
            round_no = get_value(row, "round") or "1"
            problems = parse_int(get_value(row, "problems"), 0, row_no, "problems")
            source_order = parse_int(get_value(row, "source_order", "sourceOrder"), source_index, row_no, "source_order")
            answer_key = parse_answers(row, problems, row_no)

            for field_name, value in (
                ("name", name),
                ("subject", subject),
                ("difficulty", difficulty),
                ("term", term),
                ("examTerm", exam_term),
                ("round", round_no),
            ):
                if not value:
                    raise ValueError(f"row {row_no}: missing {field_name}")

            generated.append(
                {
                    "id": test_id,
                    "sourceId": test_id,
                    "category": "SCHOOL_PAST",
                    "name": name,
                    "problems": problems,
                    "curriculum": subject,
                    "difficulty": difficulty,
                    "term": term,
                    "examTerm": exam_term,
                    "sortOrder": source_order,
                    "sourceOrder": source_order,
                    "round": round_no,
                    "answerKeys": {round_no: answer_key},
                    "answerKey": answer_key,
                    "sourceFiles": {
                        "problemFile": get_value(row, "problem_file"),
                        "solutionFile": get_value(row, "solution_file"),
                        "problemFileId": get_value(row, "problem_file_id"),
                        "solutionFileId": get_value(row, "solution_file_id"),
                    },
                }
            )

    return generated


def merge_tests(existing_tests: list[Any], generated: list[dict[str, Any]]) -> tuple[list[Any], int, int, int]:
    generated_by_id = {test["id"]: test for test in generated}
    existing_generated_ids: set[str] = set()
    merged: list[Any] = []
    added = 0
    updated = 0
    preserved = 0

    for test in existing_tests:
        test_id = test.get("id") if isinstance(test, dict) else None
        replacement = generated_by_id.get(str(test_id or ""))
        if replacement is None:
            merged.append(test)
            preserved += 1
            continue

        existing_generated_ids.add(replacement["id"])
        if isinstance(test, dict):
            merged_test = dict(test)
            merged_test.update(replacement)
            if isinstance(test.get("answerKeys"), dict) and isinstance(replacement.get("answerKeys"), dict):
                merged_test["answerKeys"] = {**test["answerKeys"], **replacement["answerKeys"]}
            if isinstance(test.get("sourceFiles"), dict) and isinstance(replacement.get("sourceFiles"), dict):
                merged_test["sourceFiles"] = {**test["sourceFiles"], **replacement["sourceFiles"]}
            merged.append(merged_test)
        else:
            merged.append(replacement)
        updated += 1

    for test in generated:
        if test["id"] in existing_generated_ids:
            continue
        merged.append(test)
        added += 1

    return merged, added, updated, preserved


def write_json_atomic(path: Path, data: Any) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def require_backup_for_live_config_write(config_path: Path, backup_confirmed: bool, parser: argparse.ArgumentParser) -> None:
    if same_path(config_path, CONFIG_PATH) and not backup_confirmed:
        parser.error(
            "refusing to update live tests-config.json without --backup-confirmed; "
            "run python scripts/backup_runtime_data.py first or pass --config <temp path>"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append SCHOOL_PAST tests from CSV into tests-config.json.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument("--backup-confirmed", action="store_true", help=(
        "Required when writing the repo tests-config.json after running backup_runtime_data.py."
    ))
    args = parser.parse_args(argv)

    require_backup_for_live_config_write(args.config, args.backup_confirmed, parser)

    if not args.csv.exists():
        raise FileNotFoundError(f"source CSV not found: {args.csv}")

    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if not isinstance(cfg, dict):
        raise ValueError(f"{args.config} must contain a JSON object")

    categories = ensure_category_scaffolding(cfg)
    school_category = categories["SCHOOL_PAST"]
    school_tests = school_category.get("tests", [])

    generated = build_generated_tests(args.csv)
    merged, added, updated, preserved = merge_tests(school_tests, generated)
    school_category["tests"] = merged

    write_json_atomic(args.config, cfg)
    print(f"SCHOOL_PAST tests added: {added}")
    print(f"SCHOOL_PAST tests updated: {updated}")
    print(f"SCHOOL_PAST tests preserved: {preserved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
