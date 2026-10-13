from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
TESTS_CONFIG: Final[Path] = ROOT / "tests-config.json"
STUDENT_JS: Final[Path] = ROOT / "static" / "js" / "student.js"
REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_answer_mode_coverage.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_answer_mode_coverage.md")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class AnswerModeCoverageError(Exception):
    pass


def main() -> int:
    eligible = eligible_test_ids()
    mode_ids = answer_mode_test_ids()
    explicit_ids = explicit_client_allowlist()
    explicit_missing = sorted(test_id for test_id in explicit_ids if test_id not in mode_ids)
    missing = sorted(test_id for test_id in eligible if test_id not in mode_ids)
    output = {
        "ok": True,
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "eligible_test_count": len(eligible),
        "answer_mode_table_count": len(mode_ids),
        "missing_answer_mode_count": len(missing),
        "explicit_client_allowlist_missing_answer_mode": explicit_missing,
        "covered_test_ids": sorted(mode_ids),
        "missing_answer_mode_sample": missing[:50],
        "policy": "Missing answer-mode tables must route to review/blocked behavior and must not infer from answer keys.",
    }
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def eligible_test_ids() -> set[str]:
    payload = json.loads(TESTS_CONFIG.read_text(encoding="utf-8-sig"))
    categories = payload.get("categories") if isinstance(payload, dict) else None
    if not isinstance(categories, dict):
        raise AnswerModeCoverageError("tests-config.json missing categories")
    ids: set[str] = set()
    for category_key, raw_category in categories.items():
        category = raw_category if isinstance(raw_category, dict) else {}
        for raw_test in category.get("tests", []):
            if isinstance(raw_test, dict) and test_is_eligible(str(category_key), raw_test):
                ids.add(str(raw_test.get("id")))
    return ids


def test_is_eligible(category_key: str, item: JsonObject) -> bool:
    test_id = str(item.get("id") or "")
    try:
        problem_count = int(str(item.get("problems") or ""))
        round_no = int(str(item.get("round") or ""))
    except ValueError:
        return False
    if problem_count != 20:
        return False
    if category_key == "UNIT":
        return re.match(r"^t_unit_[a-z0-9_]+_r[123]$", test_id, re.IGNORECASE) is not None and round_no in {1, 2, 3}
    if category_key == "TRAINING_PACK":
        return re.match(r"^t_training_pack_[a-z0-9_]+_r[12]$", test_id, re.IGNORECASE) is not None and round_no in {1, 2}
    return False


def answer_mode_test_ids() -> set[str]:
    source = STUDENT_JS.read_text(encoding="utf-8-sig")
    block = re.search(r"const OCR_PHASE1_ANSWER_MODE_BY_TEST_ID = \{(?P<body>.*?)\n\s*\};", source, re.DOTALL)
    return set(re.findall(r"\b(t_[a-z0-9_]+)\s*:", block.group("body") if block else ""))


def explicit_client_allowlist() -> set[str]:
    source = STUDENT_JS.read_text(encoding="utf-8-sig")
    block = re.search(r"const OCR_PHASE1_ALLOWED_TEST_IDS = new Set\(\[(?P<body>.*?)\]\);", source, re.DOTALL)
    return set(re.findall(r"'(t_[^']+)'", block.group("body") if block else ""))


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Answer Mode Coverage",
        "",
        "- provider calls: 0",
        "- submit-test calls: 0",
        f"- OCR-eligible test count: {output['eligible_test_count']}",
        f"- answer-mode table count: {output['answer_mode_table_count']}",
        f"- missing answer-mode count: {output['missing_answer_mode_count']}",
        "",
        "## Explicit Client Allowlist Missing Answer Mode",
        "",
    ]
    explicit_missing = list(output["explicit_client_allowlist_missing_answer_mode"])
    lines.extend(f"- `{test_id}`" for test_id in explicit_missing)
    lines.extend(("", "## Covered", ""))
    lines.extend(f"- `{test_id}`" for test_id in list(output["covered_test_ids"]))
    lines.extend(("", "## Missing Sample", ""))
    lines.extend(f"- `{test_id}`" for test_id in list(output["missing_answer_mode_sample"]))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
