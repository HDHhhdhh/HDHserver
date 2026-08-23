from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.repair_watch_updated_at import KST, UINT32_MOD, reconstruct_wrapped_epoch_ms


def _to_int32(value: int) -> int:
    low_bits = value % UINT32_MOD
    return low_bits - UINT32_MOD if low_bits >= 2**31 else low_bits


def main() -> int:
    import routes.api_watch as api_watch

    fixed_ms = int(dt.datetime(2026, 8, 22, 12, 0, tzinfo=KST).timestamp() * 1000)
    wrapped = _to_int32(fixed_ms)
    if reconstruct_wrapped_epoch_ms(wrapped, "2026-08-22") != fixed_ms:
        raise AssertionError("Int32 watch timestamp must reconstruct uniquely inside its KST date")

    old_watch_path = api_watch.WATCH_PATH
    old_time = api_watch.time.time
    with tempfile.TemporaryDirectory(prefix="verify-watch-timestamp-") as tmpdir:
        watch_path = pathlib.Path(tmpdir) / "watch.json"
        watch_path.write_text("{}", "utf-8")
        api_watch.WATCH_PATH = watch_path
        api_watch.time.time = lambda: fixed_ms / 1000
        try:
            repaired = api_watch._save_watch_entry(
                "2026-08-22",
                "sid",
                "wrapped-mid",
                {"last": 10, "dur": 100, "completed": False, "updatedAt": wrapped},
            )
            if repaired["updatedAt"] != fixed_ms:
                raise AssertionError("server must replace Int32 watch timestamps with server epoch milliseconds")

            valid_ms = fixed_ms - 1234
            preserved = api_watch._save_watch_entry(
                "2026-08-22",
                "sid",
                "valid-mid",
                {"last": 20, "dur": 100, "completed": False, "updatedAt": valid_ms},
            )
            if preserved["updatedAt"] != valid_ms:
                raise AssertionError("server must preserve valid epoch-millisecond timestamps")

            stored = json.loads(watch_path.read_text("utf-8"))
            if stored["2026-08-22"]["sid"]["wrapped-mid"]["updatedAt"] != fixed_ms:
                raise AssertionError("corrected watch timestamp must be persisted")
        finally:
            api_watch.WATCH_PATH = old_watch_path
            api_watch.time.time = old_time

    print("watch timestamp guard checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
