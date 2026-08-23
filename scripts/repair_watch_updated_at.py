from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KST = dt.timezone(dt.timedelta(hours=9))
INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1
UINT32_MOD = 2**32


def reconstruct_wrapped_epoch_ms(value: int, date_key: str) -> int | None:
    if value == 0 or value < INT32_MIN or value > INT32_MAX:
        return None
    try:
        day = dt.date.fromisoformat(date_key)
    except ValueError:
        return None
    start = int(dt.datetime.combine(day, dt.time.min, tzinfo=KST).timestamp() * 1000)
    end = int(dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, tzinfo=KST).timestamp() * 1000)
    low_bits = value & 0xFFFFFFFF
    multiplier = max(0, (start - low_bits + UINT32_MOD - 1) // UINT32_MOD)
    candidate = low_bits + multiplier * UINT32_MOD
    return candidate if start <= candidate < end else None


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair Int32-wrapped watch updatedAt values for one KST date.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--path", type=pathlib.Path)
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    args = parser.parse_args()

    if args.apply and not args.backup_confirmed:
        parser.error("--apply requires --backup-confirmed")
    if args.apply and not args.expected_sha256:
        parser.error("--apply requires --expected-sha256")

    from core.paths import WATCH_PATH
    from core.storage import file_lock, load, save_atomic

    path = (args.path or WATCH_PATH).resolve()
    with file_lock(path):
        if args.expected_sha256 and _sha256(path) != args.expected_sha256.strip().upper():
            raise RuntimeError("watch.json changed after the expected fingerprint was captured")
        data = load(path)
        if not isinstance(data, dict):
            raise RuntimeError("watch store must be an object")
        by_date = data.get(args.date)
        if not isinstance(by_date, dict):
            raise RuntimeError("target date is missing from watch store")

        repaired = 0
        unresolved = 0
        for by_sid in by_date.values():
            if not isinstance(by_sid, dict):
                continue
            for record in by_sid.values():
                if not isinstance(record, dict):
                    continue
                try:
                    updated_at = int(record.get("updatedAt") or 0)
                except Exception:
                    continue
                if updated_at == 0 or updated_at < INT32_MIN or updated_at > INT32_MAX:
                    continue
                candidate = reconstruct_wrapped_epoch_ms(updated_at, args.date)
                if candidate is None:
                    unresolved += 1
                    continue
                repaired += 1
                if args.apply:
                    record["updatedAt"] = candidate

        if args.apply and repaired:
            save_atomic(path, data)

    print(json.dumps({
        "date": args.date,
        "repaired": repaired,
        "unresolved": unresolved,
        "applied": args.apply,
        "sha256": _sha256(path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
