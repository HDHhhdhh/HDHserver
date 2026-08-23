from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.migrate_today_order_store import (
    TodayOrderConflictError,
    migrate_today_order_store,
)


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_source_contract() -> None:
    paths_source = (ROOT / "core" / "paths.py").read_text(encoding="utf-8")
    route_source = (ROOT / "routes" / "api_todaymeta.py").read_text(encoding="utf-8")
    basic_source = (ROOT / "routes" / "api_basic.py").read_text(encoding="utf-8")
    safety_source = (ROOT / "scripts" / "verify_refactor_safety.py").read_text(encoding="utf-8")
    deploy_source = (ROOT / "scripts" / "apply_student_app_production.ps1").read_text(encoding="utf-8")
    migration_source = (ROOT / "scripts" / "migrate_today_order_store.py").read_text(encoding="utf-8")

    assert 'TODAY_ORDER_PATH = ensure_json(DATA_DIR / "today_order.json", {})' in paths_source
    assert 'TODAY_ORDER_PATH = ensure_json(BASE / "today_order.json", {})' not in paths_source
    assert "from core.paths import TODAY_ORDER_PATH" in route_source
    assert "p = TODAY_ORDER_PATH" in route_source
    assert 'DATA_DIR / "today_order.json"' not in route_source
    assert "TODAY_ORDER_PATH" not in basic_source
    assert '"data/today_order.json"' in safety_source
    assert "'data/today_order.json'" in deploy_source
    assert "'today_order.json'," not in deploy_source
    assert '"--backup-confirmed"' in migration_source
    assert "live apply requires --backup-confirmed" in migration_source


def main() -> int:
    _verify_source_contract()

    with tempfile.TemporaryDirectory(prefix="verify-today-order-migration-") as tmp:
        root = Path(tmp)
        legacy = root / "today_order.json"
        canonical = root / "data" / "today_order.json"
        backup_dir = root / "backups"
        legacy_value = {
            "2026-08-20": ["sid-a"],
            "2026-08-21": ["sid-common"],
        }
        canonical_value = {
            "2026-08-21": ["sid-common"],
            "2026-08-22": ["sid-b"],
        }
        _write(legacy, legacy_value)
        _write(canonical, canonical_value)
        before = {"legacy": legacy.read_bytes(), "canonical": canonical.read_bytes()}

        dry = migrate_today_order_store(legacy, canonical, backup_dir, apply=False)
        assert dry == {
            "legacyDates": 2,
            "canonicalDates": 2,
            "legacyOnlyDates": 1,
            "canonicalOnlyDates": 1,
            "matchingCommonDates": 1,
            "conflictingDates": 0,
            "applied": False,
            "legacyArchived": False,
        }
        assert legacy.read_bytes() == before["legacy"]
        assert canonical.read_bytes() == before["canonical"]
        assert not backup_dir.exists()

        applied = migrate_today_order_store(legacy, canonical, backup_dir, apply=True)
        assert applied["applied"] is True
        assert applied["legacyArchived"] is True
        assert not legacy.exists()
        assert _read(canonical) == {
            "2026-08-21": ["sid-common"],
            "2026-08-22": ["sid-b"],
            "2026-08-20": ["sid-a"],
        }
        archive = Path(applied["archive"])
        assert archive.is_file()
        assert archive.read_bytes() == before["legacy"]

        repeated = migrate_today_order_store(legacy, canonical, backup_dir, apply=True)
        assert repeated["applied"] is True
        assert repeated["legacyArchived"] is False
        assert _read(canonical)["2026-08-20"] == ["sid-a"]

    with tempfile.TemporaryDirectory(prefix="verify-today-order-conflict-") as tmp:
        root = Path(tmp)
        legacy = root / "today_order.json"
        canonical = root / "data" / "today_order.json"
        backup_dir = root / "backups"
        _write(legacy, {"2026-08-23": ["legacy"]})
        _write(canonical, {"2026-08-23": ["canonical"]})
        before = (legacy.read_bytes(), canonical.read_bytes())
        for apply in (False, True):
            try:
                migrate_today_order_store(legacy, canonical, backup_dir, apply=apply)
            except TodayOrderConflictError:
                pass
            else:
                raise AssertionError("conflicting today-order dates must fail closed")
            assert (legacy.read_bytes(), canonical.read_bytes()) == before
            assert not backup_dir.exists()

        try:
            migrate_today_order_store(canonical, canonical, backup_dir, apply=True)
        except ValueError as exc:
            assert "paths must differ" in str(exc)
        else:
            raise AssertionError("same legacy/canonical path must be rejected")

    print("today-order store migration checks passed: dry-run, merge, archive, conflict, canonical path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())