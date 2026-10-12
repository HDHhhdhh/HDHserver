# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_q015_q016_relation_gate_lock_report.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypeAlias, TypedDict

LAB: Final[Path] = Path(__file__).resolve().parent
MANIFEST_JSON: Final[Path] = LAB / "ocr_q015_q016_relation_operator_manifest.json"
EXTENDED_GATE_JSON: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_extended.json"
LOCK_REPORT_MD: Final[Path] = LAB / "ocr_q015_q016_relation_gate_lock_report.md"
REPORT_JSON: Final[Path] = LAB / "ocr_q015_q016_relation_gate_lock_verification.json"
REPORT_MD: Final[Path] = LAB / "ocr_q015_q016_relation_gate_lock_verification.md"

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class Verification(TypedDict):
    ok: bool
    student_facing: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    production_default: str
    manifest_item_count: int
    extended_gate_count: int
    relation_review_required_count: int
    relation_auto_confirm_count: int
    lock_report_mentions_q015: bool
    lock_report_mentions_q016: bool
    sensitive_field_leak_count: int
    filesystem_path_leak_count: int


class GateLockVerificationError(Exception):
    pass


def main() -> int:
    verification = build_verification()
    REPORT_JSON.write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(verification), encoding="utf-8")
    print(json.dumps(verification, ensure_ascii=False, indent=2))
    return 0


def build_verification() -> Verification:
    manifest = require_object(read_json(MANIFEST_JSON), "manifest")
    gate = require_object(read_json(EXTENDED_GATE_JSON), "extended gate")
    report = LOCK_REPORT_MD.read_text(encoding="utf-8")
    manifest_item_count = require_int(manifest.get("manifest_item_count"), "manifest.manifest_item_count")
    review_count = require_int(gate.get("q015_q016_relation_review_required_count"), "gate.q015_q016_relation_review_required_count")
    auto_confirm_count = require_int(gate.get("q015_q016_relation_auto_confirm_count"), "gate.q015_q016_relation_auto_confirm_count")
    verify_counts(manifest_item_count, review_count, auto_confirm_count)
    mentions_q015 = "person_02_same_contact` | 15" in report and "-1<=x<=5" in report and "-1<x<5" in report
    mentions_q016 = "person_02_same_contact` | 16" in report and "y=3" in report and "y→3" in report
    if not mentions_q015 or not mentions_q016:
        raise GateLockVerificationError("gate lock report does not mention both q015 and q016 evidence rows")
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "manifest_item_count": manifest_item_count,
        "extended_gate_count": require_int(gate.get("extended_gate_count"), "gate.extended_gate_count"),
        "relation_review_required_count": review_count,
        "relation_auto_confirm_count": auto_confirm_count,
        "lock_report_mentions_q015": mentions_q015,
        "lock_report_mentions_q016": mentions_q016,
        "sensitive_field_leak_count": sensitive_leak_count(report),
        "filesystem_path_leak_count": filesystem_path_leak_count(report),
    }


def verify_counts(manifest_item_count: int, review_count: int, auto_confirm_count: int) -> None:
    if manifest_item_count != 2:
        raise GateLockVerificationError(f"expected 2 manifest items, got {manifest_item_count}")
    if review_count != 2:
        raise GateLockVerificationError(f"expected 2 review-required relation rows, got {review_count}")
    if auto_confirm_count != 0:
        raise GateLockVerificationError(f"expected 0 auto-confirm rows, got {auto_confirm_count}")


def markdown_report(verification: Verification) -> str:
    lines = [
        "# OCR q015/q016 Relation Gate Lock Verification",
        "",
        "- ok: true",
        f"- extended provider-free gate count: {verification['extended_gate_count']}",
        f"- manifest item count: {verification['manifest_item_count']}",
        f"- relation review-required count: {verification['relation_review_required_count']}",
        f"- relation auto-confirm count: {verification['relation_auto_confirm_count']}",
        f"- report mentions q015: {verification['lock_report_mentions_q015']}",
        f"- report mentions q016: {verification['lock_report_mentions_q016']}",
        f"- Gemini/API calls: {verification['provider_call_count']}",
        f"- external OCR API calls: {verification['external_ocr_api_call_count']}",
        f"- `/api/submit-test` calls: {verification['submit_test_call_count']}",
        f"- `#tsSubmit` clicks: {verification['ts_submit_click_count']}",
        f"- sensitive-field leak count: {verification['sensitive_field_leak_count']}",
        f"- filesystem path leak count: {verification['filesystem_path_leak_count']}",
        "",
    ]
    return "\n".join(lines)


def sensitive_leak_count(text: str) -> int:
    forbidden = ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect")
    return sum(text.count(token) for token in forbidden)


def filesystem_path_leak_count(text: str) -> int:
    return text.count("C:\\") + text.count("C:/")


def read_json(path: Path) -> JsonValue:
    return json.loads(path.read_text(encoding="utf-8"))


def require_object(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise GateLockVerificationError(f"{label} must be a JSON object")
    return value


def require_int(value: JsonValue, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise GateLockVerificationError(f"{label} must be an integer")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
