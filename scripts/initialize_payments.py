"""Initialize tuition tables only during an approved, backed-up maintenance window."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.payment_repository import PaymentRepository
from core.payment_rules import PaymentError
from scripts.backup_runtime_data import verify_archive


def require_stopped(root):
    isolated = root / ".academy-isolated-server.json"
    port = 8003
    if isolated.exists():
        marker = json.loads(isolated.read_text(encoding="utf-8"))
        if marker.get("format") != "academy-isolated-server/v1" or Path(marker.get("isolatedRoot", "")).resolve() != root:
            raise RuntimeError("Invalid isolated runtime marker")
        port = 8004
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Approved maintenance stop required first (port {port} is active). No process was stopped.")


def initialize(root, backup):
    require_stopped(root)
    database = root / "app.sqlite"
    if not database.is_file():
        raise RuntimeError("Existing app.sqlite is required. Do not create a replacement runtime database.")
    manifest = verify_archive(backup)
    if Path(manifest.get("root", "")).resolve() != root or manifest.get("snapshotMode") != "quiescent-sqlite-backup-v1":
        raise RuntimeError("Backup must be a verified native snapshot of this exact runtime root")
    created = dt.datetime.fromisoformat(manifest["createdAt"].replace("Z", "+00:00"))
    age = (dt.datetime.now(dt.timezone.utc) - created).total_seconds()
    if not 0 <= age <= 900 or not any(item["path"] == "app.sqlite" for item in manifest["files"]):
        raise RuntimeError("A fresh backup containing app.sqlite is required (within 15 minutes)")
    require_stopped(root)
    PaymentRepository(database).initialize()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    root = ROOT.resolve()
    if not args.apply:
        try:
            PaymentRepository(root / "app.sqlite").overview()
            initialized = True
        except PaymentError:
            initialized = False
        print(json.dumps({"dryRun": True, "database": str(root / "app.sqlite"), "initialized": initialized,
            "tables": ["payment_schema", "payment_accounts", "payment_operations"], "importsAttendance": False}, ensure_ascii=False))
        return 0
    if args.confirm != "INITIALIZE_PAYMENT_LEDGER_V1" or args.backup is None:
        parser.error("--apply requires --backup and --confirm INITIALIZE_PAYMENT_LEDGER_V1")
    initialize(root, args.backup.resolve())
    print("Payment ledger initialized. Existing attendance and other tables were preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
