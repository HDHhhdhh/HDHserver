"""Report student identity problems from an explicit, read-only JSON file."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


def report(path: Path) -> dict:
    rows = json.loads(path.read_text("utf-8-sig"))
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("students must be an array of objects")
    identifiers = Counter(str(row.get("id") or "").strip() for row in rows)
    return {
        "rows": len(rows),
        "missingIDs": identifiers.get("", 0),
        "duplicateIDs": {sid: count for sid, count in identifiers.items() if sid and count > 1},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--students", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(report(args.students), ensure_ascii=False, indent=2))
