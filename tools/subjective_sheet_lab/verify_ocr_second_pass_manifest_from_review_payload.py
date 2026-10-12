# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_second_pass_manifest_from_review_payload.py

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_preprocess_variants import require_cv2  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_visible_digit_second_pass_eligibility import (  # noqa: E402
    GeometrySignals,
    eligibility,
    geometry_signals,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

PAYLOAD_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/gangyuhyun849_live_review_payload_cache_replay_20260703.json"
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_second_pass_manifest_from_review_payload.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_second_pass_manifest_from_review_payload.md"
TARGET_QUESTIONS: Final[frozenset[int]] = frozenset((16, 17))
FORBIDDEN_OUTPUT_TOKENS: Final[tuple[str, ...]] = ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "grading", "C:\\", "C:/", "/c/")


@dataclass(frozen=True, slots=True)
class ReviewItem:
    question_no: int
    status: str
    recognized: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ManifestCandidate:
    question_no: int
    recognized: str
    status: str
    warnings: tuple[str, ...]
    visible_digit_candidate_count: int
    crossed_neighbor_count: int
    action: str
    auto_confirm_allowed: bool


@dataclass(frozen=True, slots=True)
class BlockedReview:
    question_no: int
    recognized: str
    status: str
    warnings: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ManifestParts:
    items: tuple[ReviewItem, ...]
    candidates: tuple[ManifestCandidate, ...]
    blocked_reviews: tuple[BlockedReview, ...]
    safe_ignored: int


class SecondPassManifestError(Exception):
    pass


def main() -> int:
    require_cv2()
    items = review_items(read_json(PAYLOAD_JSON))
    candidate_list: list[ManifestCandidate] = []
    blocked_review_list: list[BlockedReview] = []
    safe_ignored = 0
    for item in items:
        if item.status == "review_required":
            candidate = candidate_for_review(item)
            if candidate is None:
                blocked_review_list.append(blocked_review(item))
            else:
                candidate_list.append(candidate)
        else:
            safe_ignored += 1
    parts = ManifestParts(items, tuple(candidate_list), tuple(blocked_review_list), safe_ignored)
    assert_manifest(parts)
    output = output_json(parts)
    output["sensitive_field_leak_count"] = leak_count(json.dumps(output, ensure_ascii=False))
    if output["sensitive_field_leak_count"] != 0:
        raise SecondPassManifestError("sensitive token leaked into manifest output")
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(parts), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def candidate_for_review(item: ReviewItem) -> ManifestCandidate | None:
    if item.question_no not in TARGET_QUESTIONS:
        return None
    geometry = geometry_signals(require_cv2(), item.question_no)
    eligible, _reason = eligibility(item.recognized, item.status, item.warnings, geometry)
    if not eligible:
        return None
    return ManifestCandidate(
        question_no=item.question_no,
        recognized=item.recognized,
        status=item.status,
        warnings=item.warnings,
        visible_digit_candidate_count=geometry.visible_digit_candidate_count,
        crossed_neighbor_count=geometry.crossed_neighbor_count,
        action="USER_APPROVAL_REQUIRED",
        auto_confirm_allowed=False,
    )


def blocked_review(item: ReviewItem) -> BlockedReview:
    if item.question_no not in TARGET_QUESTIONS:
        reason = "not_visible_digit_second_pass_target"
    else:
        geometry = geometry_signals(require_cv2(), item.question_no)
        _eligible, reason = eligibility(item.recognized, item.status, item.warnings, geometry)
    return BlockedReview(item.question_no, item.recognized, item.status, item.warnings, reason)


def output_json(parts: ManifestParts) -> JsonObject:
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "payload_name": PAYLOAD_JSON.name,
        "review_payload_item_count": len(parts.items),
        "candidate_count": len(parts.candidates),
        "blocked_review_required_count": len(parts.blocked_reviews),
        "safe_ignored_count": parts.safe_ignored,
        "auto_confirm_allowed_count": sum(1 for candidate in parts.candidates if candidate.auto_confirm_allowed),
        "manifest_status": "USER_APPROVAL_REQUIRED",
        "candidates": [asdict(candidate) for candidate in parts.candidates],
        "blocked_reviews": [asdict(review) for review in parts.blocked_reviews],
    }


def assert_manifest(parts: ManifestParts) -> None:
    if len(parts.items) != 20:
        raise SecondPassManifestError(f"expected 20 review items, got {len(parts.items)}")
    if [candidate.question_no for candidate in parts.candidates] != [16, 17]:
        raise SecondPassManifestError("second-pass manifest must contain q016 and q017 only")
    if [review.question_no for review in parts.blocked_reviews] != [9, 14]:
        raise SecondPassManifestError("blocked review-required controls must be q009 and q014")
    if parts.safe_ignored != 16:
        raise SecondPassManifestError(f"expected 16 safe ignored items, got {parts.safe_ignored}")
    if any(candidate.auto_confirm_allowed for candidate in parts.candidates):
        raise SecondPassManifestError("second-pass manifest must not auto-confirm")


def review_items(payload: JsonObject) -> tuple[ReviewItem, ...]:
    review_payload = require_object(payload.get("review_payload"), "review_payload")
    raw_items = review_payload.get("items")
    if not isinstance(raw_items, list):
        raise SecondPassManifestError("review_payload.items must be a list")
    return tuple(parse_item(raw_item) for raw_item in raw_items)


def parse_item(raw_item: JsonValue) -> ReviewItem:
    item = require_object(raw_item, "review_payload.items[]")
    question_no = require_int(item.get("question_no"), "question_no")
    status = require_text(item.get("status"), "status")
    recognized = require_text(item.get("recognized"), "recognized")
    warnings = require_text_tuple(item.get("warnings"), "warnings")
    return ReviewItem(question_no, status, recognized, warnings)


def read_json(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    return require_object(value, path.name)


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise SecondPassManifestError(f"{label} must be a JSON object")
    return value


def require_int(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SecondPassManifestError(f"{label} must be an integer")
    return value


def require_text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise SecondPassManifestError(f"{label} must be text")
    return value.strip()


def require_text_tuple(value: JsonValue, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SecondPassManifestError(f"{label} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SecondPassManifestError(f"{label} entries must be text")
        result.append(item)
    return tuple(result)


def markdown_report(parts: ManifestParts) -> str:
    lines = ["# OCR Second-Pass Manifest From Review Payload", "", "| q | Recognized | Status | Visible | Crossed | Action |", "|---:|---|---|---:|---:|---|"]
    for candidate in parts.candidates:
        lines.append(
            f"| {candidate.question_no} | `{candidate.recognized}` | `{candidate.status}` | "
            f"{candidate.visible_digit_candidate_count} | {candidate.crossed_neighbor_count} | `{candidate.action}` |"
        )
    lines.extend(("", f"- blocked review-required controls: {len(parts.blocked_reviews)}", f"- safe ignored: {parts.safe_ignored}", "- auto-confirm: 0"))
    lines.extend(("- Gemini/API calls: 0", "- External OCR API calls: 0", "- `/api/submit-test` calls: 0", "- `#tsSubmit` clicks: 0"))
    return "\n".join(lines) + "\n"


def leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)


if __name__ == "__main__":
    raise SystemExit(main())
