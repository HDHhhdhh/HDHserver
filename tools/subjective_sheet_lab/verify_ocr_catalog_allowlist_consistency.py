from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
TESTS_CONFIG: Final[Path] = ROOT / "tests-config.json"
ROUTE_FILE: Final[Path] = ROOT / "routes" / "api_tests.py"
STUDENT_JS: Final[Path] = ROOT / "static" / "js" / "student.js"
REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_catalog_allowlist_consistency.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_catalog_allowlist_consistency.md")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class CatalogAllowlistConsistencyError(Exception):
    pass


def main() -> int:
    tests = catalog_tests()
    unit_ids = [item["id"] for item in tests if is_unit_eligible(item)]
    training_ids = [item["id"] for item in tests if is_training_pack_eligible(item)]
    route_source = ROUTE_FILE.read_text(encoding="utf-8-sig")
    student_source = STUDENT_JS.read_text(encoding="utf-8-sig")
    failures = consistency_failures(route_source, student_source)
    if failures:
        raise CatalogAllowlistConsistencyError("\n".join(failures))
    output = {
        "ok": True,
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "unit_regex_eligible": len(unit_ids),
        "training_pack_eligible": len(training_ids),
        "explicit_route_allowlist": explicit_route_allowlist(route_source),
        "explicit_client_allowlist": explicit_client_allowlist(student_source),
        "unit_by_curriculum": counts_by_prefix(unit_ids, ("daesu", "mijeok1", "mijeok2", "gongsu1", "gongsu2")),
        "training_pack_ids": training_ids,
        "route_catalog_rounds": {"UNIT": [1, 2, 3], "TRAINING_PACK": [1, 2]},
        "client_patterns": ["^t_unit_[a-z0-9_]+_r[123]$", "^t_training_pack_[a-z0-9_]+_r[12]$"],
    }
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def catalog_tests() -> list[JsonObject]:
    payload = json.loads(TESTS_CONFIG.read_text(encoding="utf-8-sig"))
    categories = payload.get("categories") if isinstance(payload, dict) else None
    if not isinstance(categories, dict):
        raise CatalogAllowlistConsistencyError("tests-config.json missing categories")
    tests: list[JsonObject] = []
    for category_key, raw_category in categories.items():
        category = raw_category if isinstance(raw_category, dict) else {}
        for raw_test in category.get("tests", []):
            if isinstance(raw_test, dict) and isinstance(raw_test.get("id"), str):
                item = dict(raw_test)
                item["categoryKey"] = str(category_key)
                tests.append(item)
    return tests


def is_unit_eligible(item: JsonObject) -> bool:
    return item.get("categoryKey") == "UNIT" and regex_eligible(str(item.get("id") or ""), r"^t_unit_[a-z0-9_]+_r[123]$") and has_problem_round(item, {1, 2, 3})


def is_training_pack_eligible(item: JsonObject) -> bool:
    return item.get("categoryKey") == "TRAINING_PACK" and regex_eligible(str(item.get("id") or ""), r"^t_training_pack_[a-z0-9_]+_r[12]$") and has_problem_round(item, {1, 2})


def regex_eligible(value: str, pattern: str) -> bool:
    return re.match(pattern, value, re.IGNORECASE) is not None


def has_problem_round(item: JsonObject, rounds: set[int]) -> bool:
    try:
        return int(str(item.get("problems") or "")) == 20 and int(str(item.get("round") or "")) in rounds
    except ValueError:
        return False


def explicit_route_allowlist(source: str) -> list[str]:
    values = set(re.findall(r'OCR_PHASE2A_REVIEW_TEST_ID\s*=\s*"(t_[^"]+)"', source))
    block = re.search(r"OCR_PHASE2A_REVIEW_ALLOWED_TESTS:.*?=\s*\{(?P<body>.*?)\}", source, re.DOTALL)
    values.update(re.findall(r'"(t_[^"]+)"', block.group("body") if block else ""))
    return sorted(values)


def explicit_client_allowlist(source: str) -> list[str]:
    block = re.search(r"const OCR_PHASE1_ALLOWED_TEST_IDS = new Set\(\[(?P<body>.*?)\]\);", source, re.DOTALL)
    return sorted(set(re.findall(r"'(t_[^']+)'", block.group("body") if block else "")))


def consistency_failures(route_source: str, student_source: str) -> list[str]:
    checks = {
        "route_unit_rounds": "OCR_PHASE2A_UNIT_REVIEW_ROUNDS: Final[frozenset[int]] = frozenset((1, 2, 3))" in route_source,
        "route_training_rounds": 'allowed_rounds = frozenset((1, 2)) if category_key == "TRAINING_PACK"' in route_source,
        "route_problem_count": "problems != 20" in route_source,
        "client_unit_pattern": r"^t_unit_[a-z0-9_]+_r[123]$" in student_source,
        "client_training_pattern": r"^t_training_pack_[a-z0-9_]+_r[12]$" in student_source,
    }
    return [name for name, passed in checks.items() if not passed]


def counts_by_prefix(test_ids: list[str], prefixes: tuple[str, ...]) -> dict[str, int]:
    return {prefix: sum(1 for test_id in test_ids if f"t_unit_{prefix}_" in test_id) for prefix in prefixes}


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Catalog Allowlist Consistency",
        "",
        "- provider calls: 0",
        "- submit-test calls: 0",
        "",
        f"- UNIT eligible ids: {output['unit_regex_eligible']}",
        f"- TRAINING_PACK eligible ids: {output['training_pack_eligible']}",
        f"- explicit route allowlist: {', '.join(output['explicit_route_allowlist'])}",
        f"- explicit client allowlist: {', '.join(output['explicit_client_allowlist'])}",
        "",
        "## UNIT By Curriculum",
        "",
    ]
    for key, value in dict(output["unit_by_curriculum"]).items():
        lines.append(f"- {key}: {value}")
    lines.extend(("", "## Training Pack", ""))
    for test_id in list(output["training_pack_ids"]):
        lines.append(f"- `{test_id}`")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
