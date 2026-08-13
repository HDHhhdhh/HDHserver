from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path("C:/server/tools/subjective_sheet_lab")
OUT_DIR = Path("C:/server-ocr/gemini_outputs/review_ui_mock_policy")
HTML_PATH = ROOT / "review_ui_mock.html"
SAMPLE_PATHS = (
    ROOT / "review_ui_mock_sample_person02.json",
    ROOT / "review_ui_mock_sample.json",
    ROOT / "review_ui_mock_sample_jamo.json",
)
REQUIRED_WARNINGS = frozenset(
    {
        "digit_confusion_0_6",
        "variable_confusion_x_n",
        "jamo_choice_confusion",
        "equation_part_missing",
        "possible_answer_key_or_crop_mismatch",
    },
)
DATA_CHECK_WARNINGS = frozenset({"possible_answer_key_or_crop_mismatch"})
REVIEW_WARNINGS = frozenset({"digit_confusion_0_6", "variable_confusion_x_n", "jamo_choice_confusion", "equation_part_missing"})
FORBIDDEN_TEXT = ("/api/submit-test", "googleapis", "x-goog-api-key", "GEMINI_API_KEY", "AIza")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    name: str
    passed: bool
    detail: str


class ReviewUiVerificationError(Exception):
    pass


def main() -> int:
    html = HTML_PATH.read_text(encoding="utf-8-sig")
    payloads = tuple(load_json(path) for path in SAMPLE_PATHS)
    results = (
        check_html_surface(html),
        check_forbidden_text(html),
        check_required_warnings(payloads),
        check_data_check_sample(payloads),
        check_accepted_warning_policy(payloads),
    )
    write_reports(results)
    failed = tuple(result for result in results if not result.passed)
    if failed:
        raise ReviewUiVerificationError(", ".join(result.name for result in failed))
    print(json.dumps({"ok": True, "checks": len(results), "out_dir": str(OUT_DIR)}, ensure_ascii=False))
    return 0


def load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ReviewUiVerificationError(f"{path} must contain a JSON object")
    return payload


def check_html_surface(html: str) -> VerificationResult:
    required = ("dataCheckCount", "dataCheckCards", "debugDetails", "data_check_required", "renderDataCheckCard")
    missing = tuple(token for token in required if token not in html)
    return VerificationResult("html_data_check_surface", not missing, ", ".join(missing) or "ok")


def check_forbidden_text(html: str) -> VerificationResult:
    found = tuple(token for token in FORBIDDEN_TEXT if token in html)
    return VerificationResult("no_api_or_submit_strings", not found, ", ".join(found) or "ok")


def check_required_warnings(payloads: tuple[dict[str, object], ...]) -> VerificationResult:
    warnings = frozenset(warning for item in all_items(payloads) for warning in item_warnings(item))
    missing = tuple(sorted(REQUIRED_WARNINGS - warnings))
    return VerificationResult("sample_warning_coverage", not missing, ", ".join(missing) or "ok")


def check_data_check_sample(payloads: tuple[dict[str, object], ...]) -> VerificationResult:
    found = any(status_for(item) == "data_check_required" and bool(DATA_CHECK_WARNINGS.intersection(item_warnings(item))) for item in all_items(payloads))
    return VerificationResult("sample_data_check_required", found, "ok" if found else "missing data_check_required sample")


def check_accepted_warning_policy(payloads: tuple[dict[str, object], ...]) -> VerificationResult:
    matches = tuple(item for item in all_items(payloads) if raw_status(item) == "safe_auto_grade" and bool(REVIEW_WARNINGS.intersection(item_warnings(item))))
    blocked = tuple(item for item in matches if status_for(item) != "safe_auto_grade")
    return VerificationResult("accepted_warning_blocks_safe", bool(matches) and len(matches) == len(blocked), f"matches={len(matches)} blocked={len(blocked)}")


def all_items(payloads: tuple[dict[str, object], ...]) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    for payload in payloads:
        items = payload.get("items")
        if isinstance(items, list):
            output.extend(item for item in items if isinstance(item, dict))
    return tuple(output)


def item_warnings(item: dict[str, object]) -> frozenset[str]:
    warnings = item.get("warnings")
    if not isinstance(warnings, list):
        return frozenset()
    return frozenset(str(warning) for warning in warnings)


def raw_status(item: dict[str, object]) -> str:
    return str(item.get("status", "safe_auto_grade"))


def status_for(item: dict[str, object]) -> str:
    warnings = item_warnings(item)
    if raw_status(item) == "data_check_required" or item.get("review_policy") == "data_check_required" or DATA_CHECK_WARNINGS.intersection(warnings):
        return "data_check_required"
    if raw_status(item) == "safe_auto_grade" and REVIEW_WARNINGS.intersection(warnings):
        return "review_required"
    return raw_status(item)


def write_reports(results: tuple[VerificationResult, ...]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "review_ui_mock_policy.json").write_text(json.dumps({"items": [asdict(result) for result in results]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# review_ui_mock policy verification", "", "| check | passed | detail |", "|---|---:|---|"]
    for result in results:
        lines.append(f"| {result.name} | {result.passed} | {result.detail} |")
    (OUT_DIR / "review_ui_mock_policy.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
