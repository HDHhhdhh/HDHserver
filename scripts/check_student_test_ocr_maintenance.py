"""Read-only OCR retention/overdue inspection; no app import, model, or deletion."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.student_test_ocr_maintenance import StudentTestOcrMaintenance
from core.student_test_ocr_repository import StudentTestOcrRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    args = parser.parse_args()
    repository = StudentTestOcrRepository(args.db)
    if not repository.schema_ready():
        print(json.dumps({"ok": False, "code": "ocr_schema_not_initialized"}))
        return 2
    inspector = StudentTestOcrMaintenance(
        repository=repository, asset_root=args.asset_root,
        clock=lambda: dt.datetime.now(dt.timezone(dt.timedelta(hours=9))),
    )
    print(json.dumps({"ok": True, **inspector.inspect()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
