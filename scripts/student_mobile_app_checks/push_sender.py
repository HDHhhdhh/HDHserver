"""Focused, network-free contract checks for the student Push sender."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.student_mobile_app_checks.push_sender_cases import run_checks


def main() -> int:
    """Run checks as a standalone command with no network side effects."""

    try:
        result = run_checks()
    except AssertionError as exc:
        print(f"push-sender checks failed: {exc}", file=sys.stderr)
        return 1
    print(f"push-sender checks passed: {result['assertions']} assertions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
