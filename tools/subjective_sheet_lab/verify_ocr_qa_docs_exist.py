# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_qa_docs_exist.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

LAB: Final[Path] = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class QaDocSpec:
    path: Path
    required_phrases: tuple[str, ...]


class QaDocVerificationError(Exception):
    def __init__(self, failures: tuple[str, ...]) -> None:
        self.failures = failures
        super().__init__("\n".join(failures))


class QaDocSummary(TypedDict):
    ok: bool
    checked_count: int
    provider_call_count: int
    submit_test_call_count: int
    documents: list[str]


DOCS: Final[tuple[QaDocSpec, ...]] = (
    QaDocSpec(
        LAB / "OCR_QA_START_HERE.md",
        (
            "Gemini/API provider calls: 0 by default",
            "Production default: NO-GO",
            "Read In This Order",
        ),
    ),
    QaDocSpec(
        LAB / "tomorrow_ocr_manual_qa_checklist.md",
        (
            "Gemini/API",
            "/api/submit-test",
            "#tsSubmit",
        ),
    ),
    QaDocSpec(
        LAB / "ocr_live_call_authorization_templates.md",
        (
            "provider call budget",
            "API key/.env",
        ),
    ),
    QaDocSpec(
        LAB / "ocr_unit_representative_sample_plan.md",
        (
            "UNIT",
            "provider",
        ),
    ),
    QaDocSpec(
        LAB / "ocr_retake_photo_guidance.md",
        (
            "retake",
            "crop",
        ),
    ),
    QaDocSpec(
        LAB / "ocr_status_glossary_for_ops.md",
        (
            "safe_auto_grade",
            "review_required",
            "retake_required",
        ),
    ),
    QaDocSpec(
        LAB / "ocr_production_no_go_todo_board.md",
        (
            "NO-GO",
            "provider",
        ),
    ),
    QaDocSpec(
        LAB / "ocr_production_no_go_one_page.md",
        (
            "Production remains **NO-GO**",
            "`/api/submit-test` remains manual only",
        ),
    ),
    QaDocSpec(
        LAB / "ocr_preflight_inclusion_audit.md",
        (
            "updated",
            "provider-free check list only",
        ),
    ),
    QaDocSpec(
        LAB / "ocr_next_action_queue.md",
        (
            "Manual Needed",
            "Live Approval Needed",
            "Provider-Free Possible",
        ),
    ),
)


def main() -> int:
    failures = verify_docs(DOCS)
    if failures:
        raise QaDocVerificationError(failures)
    print(json.dumps(summary(DOCS), ensure_ascii=False, indent=2))
    return 0


def verify_docs(specs: tuple[QaDocSpec, ...]) -> tuple[str, ...]:
    failures: list[str] = []
    for spec in specs:
        if not spec.path.is_file():
            failures.append(f"missing document: {relative_name(spec.path)}")
            continue
        text = spec.path.read_text(encoding="utf-8")
        for phrase in spec.required_phrases:
            if phrase not in text:
                failures.append(f"missing phrase in {relative_name(spec.path)}: {phrase}")
    return tuple(failures)


def summary(specs: tuple[QaDocSpec, ...]) -> QaDocSummary:
    return {
        "ok": True,
        "checked_count": len(specs),
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "documents": [relative_name(spec.path) for spec in specs],
    }


def relative_name(path: Path) -> str:
    return path.relative_to(LAB).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
