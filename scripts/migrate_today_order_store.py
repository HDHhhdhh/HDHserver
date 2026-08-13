from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.storage import file_lock, save_atomic


class TodayOrderConflictError(RuntimeError):
    pass


def _read_order_map(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON store: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"today-order store must be an object: {path}")

    result: dict[str, list[str]] = {}
    for date, order in value.items():
        if not isinstance(date, str) or not isinstance(order, list):
            raise ValueError(f"invalid today-order entry in: {path}")
        result[date] = [str(sid) for sid in order]
    return result


def _build_plan(legacy: dict[str, list[str]], canonical: dict[str, list[str]]) -> dict[str, Any]:
    common = set(legacy).intersection(canonical)
    conflicts = sorted(date for date in common if legacy[date] != canonical[date])
    merged = dict(canonical)
    for date, order in legacy.items():
        merged.setdefault(date, order)
    return {
        "legacyDates": len(legacy),
        "canonicalDates": len(canonical),
        "legacyOnlyDates": len(set(legacy).difference(canonical)),
        "canonicalOnlyDates": len(set(canonical).difference(legacy)),
        "matchingCommonDates": len(common) - len(conflicts),
        "conflictingDates": len(conflicts),
        "merged": merged,
    }


@contextmanager
def _lock_paths(*paths: Path):
    with ExitStack() as stack:
        for path in sorted(paths, key=lambda item: os.path.normcase(str(item.resolve()))):
            stack.enter_context(file_lock(path))
        yield


def migrate_today_order_store(
    legacy_path: Path,
    canonical_path: Path,
    backup_dir: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    legacy_path = Path(legacy_path)
    canonical_path = Path(canonical_path)
    backup_dir = Path(backup_dir)

    def inspect() -> tuple[dict[str, Any], dict[str, list[str]], dict[str, list[str]]]:
        legacy = _read_order_map(legacy_path)
        canonical = _read_order_map(canonical_path)
        plan = _build_plan(legacy, canonical)
        if plan["conflictingDates"]:
            raise TodayOrderConflictError(
                f"refusing to merge {plan['conflictingDates']} conflicting date(s)"
            )
        return plan, legacy, canonical

    if not apply:
        plan, _legacy, _canonical = inspect()
        return {key: value for key, value in plan.items() if key != "merged"} | {
            "applied": False,
            "legacyArchived": False,
        }

    with _lock_paths(legacy_path, canonical_path):
        plan, legacy, _canonical = inspect()
        archived_path: Path | None = None
        if legacy_path.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            archived_path = backup_dir / f"today_order-legacy-{stamp}.json"
            shutil.copy2(legacy_path, archived_path)

        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        save_atomic(canonical_path, plan["merged"])

        if legacy_path.exists():
            legacy_path.unlink()

    return {key: value for key, value in plan.items() if key != "merged"} | {
        "applied": True,
        "legacyArchived": archived_path is not None,
        "archive": str(archived_path) if archived_path is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consolidate the legacy root today_order.json into data/today_order.json.",
    )
    parser.add_argument("--apply", action="store_true", help="Write the canonical store and archive the legacy file.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    data_dir = (args.data_dir or Path(os.environ.get("DATA_DIR", root / "data"))).resolve()
    backup_dir = (args.backup_dir or root / "_runtime_backups").resolve()

    try:
        result = migrate_today_order_store(
            root / "today_order.json",
            data_dir / "today_order.json",
            backup_dir,
            apply=args.apply,
        )
    except (TodayOrderConflictError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    result["ok"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
