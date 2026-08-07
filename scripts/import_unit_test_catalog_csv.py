from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "tests-config.json"
CSV_PATH = ROOT / "generated" / "unit_test_catalog.csv"

CATEGORY_LABELS = {
    "REVIEW": "복습 테스트",
    "UNIT": "단원평가",
    "SCHOOL_PAST": "학군지 기출",
    "ILSAN_PAST": "일산 기출",
}


def parse_answers(text: str, problems: int) -> list[str]:
    parts = str(text or "").replace(",", " ").split()
    parts = [part.strip() for part in parts if part.strip()]
    if len(parts) > problems:
        parts = parts[:problems]
    if len(parts) < problems:
        parts.extend([""] * (problems - len(parts)))
    return parts


def round_answers(row: dict[str, str], round_no: str, problems: int) -> list[str]:
    value = row.get(f"{round_no}회차정답") or row.get(f"answers{round_no}") or row.get(f"answer{round_no}") or ""
    return parse_answers(value, problems)


def _test_ids(tests: object) -> set[str]:
    if not isinstance(tests, list):
        return set()
    return {
        str(test.get("id")).strip()
        for test in tests
        if isinstance(test, dict) and str(test.get("id") or "").strip()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replace UNIT tests from a CSV source.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument(
        "--backup-confirmed",
        action="store_true",
        help="Confirm that a runtime backup was created before writing the live config.",
    )
    parser.add_argument(
        "--allow-unit-removal",
        action="store_true",
        help="Explicitly allow existing UNIT test IDs missing from the CSV to be removed.",
    )
    args = parser.parse_args(argv)
    config_path = args.config.resolve()
    csv_path = args.csv.resolve()
    if config_path == CONFIG_PATH.resolve() and not args.backup_confirmed:
        parser.error("live tests-config.json writes require --backup-confirmed")

    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(cfg, dict):
        cfg = {}
    categories = cfg.setdefault("categories", {})
    if not isinstance(categories, dict):
        categories = {}
        cfg["categories"] = categories
    for key, label in CATEGORY_LABELS.items():
        cat = categories.setdefault(key, {})
        if not isinstance(cat, dict):
            cat = {}
            categories[key] = cat
        cat.setdefault("label", label)
        cat.setdefault("tests", [])

    unit_category = categories.get("UNIT")
    previous_unit_tests = unit_category.get("tests", []) if isinstance(unit_category, dict) else []
    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8-sig", newline="")))
    unit_tests = []
    seen_ids: set[str] = set()
    for idx, row in enumerate(rows):
        source_order = idx + 1
        name = str(row.get("시험명") or row.get("name") or "").strip()
        if not name:
            continue
        problems = int(str(row.get("문항수") or row.get("problems") or 20).strip() or 20)
        source_id = str(row.get("id") or f"t_unit_import_{idx + 1:03d}").strip()
        for round_no in ("1", "2", "3"):
            answer_key = round_answers(row, round_no, problems)
            test_id = f"{source_id}_r{round_no}"
            if test_id in seen_ids:
                raise ValueError(f"duplicate generated test id: {test_id}")
            seen_ids.add(test_id)
            unit_tests.append({
                "id": test_id,
                "sourceId": source_id,
                "name": name,
                "problems": problems,
                "curriculum": str(row.get("과목") or row.get("subject") or "").strip(),
                "difficulty": str(row.get("난이도") or row.get("difficulty") or "").strip(),
                "sortOrder": source_order,
                "sourceOrder": source_order,
                "round": round_no,
                "answerKeys": {round_no: answer_key},
                "answerKey": answer_key,
            })

    previous_by_id = {
        str(test.get("id")).strip(): test
        for test in previous_unit_tests
        if isinstance(test, dict) and str(test.get("id") or "").strip()
    }
    for index, generated_test in enumerate(unit_tests):
        previous_test = previous_by_id.get(str(generated_test.get("id") or "").strip())
        if isinstance(previous_test, dict):
            merged_test = dict(previous_test)
            merged_test.update(generated_test)
            unit_tests[index] = merged_test

    unit_cat = categories.setdefault("UNIT", {})
    if not isinstance(unit_cat, dict):
        unit_cat = {}
        categories["UNIT"] = unit_cat
    unit_cat["label"] = "단원평가"
    missing_ids = _test_ids(previous_unit_tests) - _test_ids(unit_tests)
    if missing_ids and not args.allow_unit_removal:
        sample = ", ".join(sorted(missing_ids)[:10])
        raise SystemExit(
            "refusing UNIT catalog replacement: "
            f"{len(missing_ids)} existing test IDs are missing from the CSV "
            f"(sample: {sample}); use --allow-unit-removal only for an intentional removal"
        )
    unit_cat["tests"] = unit_tests

    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, config_path)
    print(f"UNIT tests replaced: {len(unit_tests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
