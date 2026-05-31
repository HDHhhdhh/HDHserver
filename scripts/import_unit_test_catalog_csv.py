from __future__ import annotations

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


def main() -> int:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
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

    rows = list(csv.DictReader(CSV_PATH.open("r", encoding="utf-8-sig", newline="")))
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

    unit_cat = categories.setdefault("UNIT", {})
    if not isinstance(unit_cat, dict):
        unit_cat = {}
        categories["UNIT"] = unit_cat
    unit_cat["label"] = "단원평가"
    unit_cat["tests"] = unit_tests

    tmp_path = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    tmp_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, CONFIG_PATH)
    print(f"UNIT tests replaced: {len(unit_tests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
