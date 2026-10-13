# /// script
# requires-python = ">=3.11"
# ///
#
# Regression guard for the intentionally retired student test-submission flow.

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[1]


class RetiredTestSubmissionVerificationError(Exception):
    pass


def assert_student_test_submission_is_retired() -> dict[str, object]:
    api_source = (ROOT / "routes/api_tests.py").read_text(encoding="utf-8")
    student_source = (ROOT / "static/js/student.js").read_text(encoding="utf-8")
    student_html = (ROOT / "static/student.html").read_text(encoding="utf-8")
    admin_source = (ROOT / "static/js/admin/features/testModal.js").read_text(encoding="utf-8")

    retired_api_markers = (
        '@bp_api_tests.post("/api/submit-test")',
        '@bp_api_tests.post("/api/ocr-test-sheet")',
        '@bp_api_tests.post("/api/ocr-test-sheet-review")',
        "def _matching_submitted_assignment_labels(",
        "def _grade_answers(",
    )
    retired_client_markers = (
        "openAssignedTestSubmit",
        "openAssignedTestAnswerLink",
        "testSubmissionBlocked",
        "/api/submit-test",
        "/api/ocr-test-sheet",
    )
    retired_html_markers = ("openTestSubmit", "testSubmitModal", "testAnswerPreviewModal")
    preserved_assignment_markers = (
        "function roundOptionsFor(",
        "function unitTestsForRound(",
        "data-round=",
        "assignedTests",
    )

    remaining = [marker for marker in retired_api_markers if marker in api_source]
    remaining += [marker for marker in retired_client_markers if marker in student_source]
    remaining += [marker for marker in retired_html_markers if marker in student_html]
    if remaining:
        raise RetiredTestSubmissionVerificationError(f"retired submission surface remains: {remaining}")

    missing_assignment = [marker for marker in preserved_assignment_markers if marker not in admin_source]
    if missing_assignment:
        raise RetiredTestSubmissionVerificationError(
            f"admin test-assignment round behavior was removed with submission: {missing_assignment}"
        )

    return {
        "submissionRetired": True,
        "adminAssignmentPreserved": True,
        "checkedRetiredMarkers": len(retired_api_markers) + len(retired_client_markers) + len(retired_html_markers),
    }


def main() -> int:
    result = assert_student_test_submission_is_retired()
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())