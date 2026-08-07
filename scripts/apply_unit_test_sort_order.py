from __future__ import annotations

import csv
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "tests-config.json"
CSV_PATH = ROOT / "generated" / "unit_test_catalog_all.csv"


def csv_order_map(path: Path) -> dict[str, int]:
    rows = list(csv.DictReader(path.open("r", encoding="utf-8-sig", newline="")))
    order: dict[str, int] = {}
    for index, row in enumerate(rows, start=1):
        source_id = str(row.get("id") or "").strip()
        if source_id and source_id not in order:
            order[source_id] = index
    return order


def source_id_for(test: dict) -> str:
    source_id = str(test.get("sourceId") or test.get("source_id") or "").strip()
    if source_id:
        return source_id
    test_id = str(test.get("id") or "").strip()
    for suffix in ("_r1", "_r2", "_r3"):
        if test_id.endswith(suffix):
            return test_id[: -len(suffix)]
    return test_id


def main() -> int:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"missing CSV order source: {CSV_PATH}")

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    categories = cfg.get("categories") if isinstance(cfg, dict) else None
    unit = categories.get("UNIT") if isinstance(categories, dict) else None
    tests = unit.get("tests") if isinstance(unit, dict) else None
    if not isinstance(tests, list):
        raise ValueError("tests-config.json has no categories.UNIT.tests list")

    order = csv_order_map(CSV_PATH)
    matched = 0
    missing = 0
    for fallback_index, test in enumerate(tests, start=1):
        if not isinstance(test, dict):
            continue
        source_id = source_id_for(test)
        sort_order = order.get(source_id)
        if sort_order is None:
            missing += 1
            if "sortOrder" not in test:
                test["sortOrder"] = fallback_index
            continue
        test["sourceId"] = source_id
        test["sortOrder"] = sort_order
        test["sourceOrder"] = sort_order
        matched += 1

    tmp_path = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    tmp_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, CONFIG_PATH)

    print(f"UNIT tests matched to CSV order: {matched}")
    print(f"UNIT tests missing CSV order: {missing}")
    print(f"CSV source rows: {len(order)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
