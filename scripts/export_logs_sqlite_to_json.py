"""Export a standalone native SQLite snapshot without touching its source."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.date_rules import is_iso_date_key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.database.resolve(strict=True)
    output = args.output.absolute()
    if output.exists() or output.resolve() == source:
        parser.error("Output must be a new file")
    if any(Path(str(source) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        parser.error("Use a verified standalone native backup without sidecars")
    result = {}
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        for date, sid, raw in connection.execute("SELECT date,sid,entry_json FROM logs ORDER BY date,sid"):
            entry = json.loads(raw)
            if not is_iso_date_key(date) or not isinstance(sid, str) or not sid.strip() or not isinstance(entry, dict):
                raise ValueError("Invalid class-log row; export refused")
            result.setdefault(date, {})[sid] = entry
    # Keep storage markers for dual-mode restore; public HTTP projections strip them.
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    with output.open("x", encoding="utf-8", newline="") as handle:
        handle.write(payload)
    print(json.dumps({"dates": len(result), "rows": sum(len(day) for day in result.values()),
                      "source_runtime_modified": False, "storage_markers_preserved": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
