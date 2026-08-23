from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.storage import file_lock, save_atomic


KST = dt.timezone(dt.timedelta(hours=9))
DEFAULT_UPDATES_PATH = ROOT / "updates.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _canonical_date(value: str) -> str:
    parsed = dt.date.fromisoformat(str(value or "").strip())
    return parsed.isoformat()


def remove_future_auto_assignments(updates: dict, *, today: str) -> dict:
    """Remove only identifiable future source:auto snapshots in place."""
    today = _canonical_date(today)
    affected_dates: list[str] = []
    removed = 0
    preserved = {"manual": 0, "selfStudy": 0, "legacyArray": 0, "other": 0}

    for raw_date in list(updates):
        try:
            date_key = _canonical_date(str(raw_date))
        except ValueError:
            continue
        if date_key <= today:
            continue

        day = updates.get(raw_date)
        if not isinstance(day, dict):
            preserved["other"] += 1
            continue

        date_removed = 0
        for sid in list(day):
            entry = day.get(sid)
            if isinstance(entry, list):
                preserved["legacyArray"] += 1
                continue
            if not isinstance(entry, dict):
                preserved["other"] += 1
                continue

            source = str(entry.get("source") or "").strip().casefold()
            if source == "auto":
                day.pop(sid, None)
                removed += 1
                date_removed += 1
            elif source == "manual":
                preserved["manual"] += 1
            elif source == "selfstudy":
                preserved["selfStudy"] += 1
            else:
                preserved["other"] += 1

        if date_removed:
            affected_dates.append(date_key)
        if not day:
            updates.pop(raw_date, None)

    return {
        "today": today,
        "removedAuto": removed,
        "affectedDates": sorted(set(affected_dates)),
        "preservedFuture": preserved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove pre-generated future source:auto video assignments.",
    )
    parser.add_argument("--path", type=Path, default=DEFAULT_UPDATES_PATH)
    parser.add_argument(
        "--today",
        default=dt.datetime.now(KST).date().isoformat(),
        help="KST cutoff date (YYYY-MM-DD); defaults to the current KST date.",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    args = parser.parse_args()

    path = args.path.resolve()
    if not path.exists():
        parser.error(f"updates file does not exist: {path}")
    if args.apply and path == DEFAULT_UPDATES_PATH.resolve() and not args.backup_confirmed:
        parser.error("live apply requires --backup-confirmed")

    before_sha = _sha256(path)
    with file_lock(path):
        updates = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(updates, dict):
            raise ValueError("updates root must be an object")
        summary = remove_future_auto_assignments(updates, today=args.today)
        if args.apply and summary["removedAuto"]:
            save_atomic(path, updates)

    summary.update({
        "mode": "apply" if args.apply else "dry-run",
        "path": str(path),
        "beforeSha256": before_sha,
        "afterSha256": _sha256(path),
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
