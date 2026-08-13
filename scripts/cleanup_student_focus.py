"""Bounded retention cleanup for raw student focus transitions."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_app_config import load_student_app_config
from core.student_focus_repository import FocusNotInitializedError, StudentFocusRepository


RAW_RETENTION_SECONDS = 30 * 24 * 60 * 60


def run_once(*, repository: StudentFocusRepository, now: float, limit: int) -> dict[str, int]:
    return repository.cleanup(now=now, raw_before=now - RAW_RETENTION_SECONDS, limit=limit)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one bounded cleanup pass")
    parser.add_argument("--limit", type=int, default=500)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.once or not 1 <= args.limit <= 5_000:
        print(json.dumps({"ok": False, "code": "invalid_arguments"}, sort_keys=True))
        return 2
    config = load_student_app_config()
    if not config.public_enabled or not config.focus_enabled:
        print(json.dumps({"ok": True, "disabled": True, "markedUnknown": 0, "eventsDeleted": 0}, sort_keys=True))
        return 0
    repository = StudentFocusRepository(Path(os.environ.get("STUDENT_APP_DB_PATH", ROOT / "app.sqlite")))
    try:
        result = run_once(repository=repository, now=time.time(), limit=args.limit)
    except FocusNotInitializedError:
        print(json.dumps({"ok": False, "code": "focus_unavailable"}, sort_keys=True))
        return 3
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("RAW_RETENTION_SECONDS", "run_once")
