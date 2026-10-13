"""External observations for backup integrity and absence read sharing; temp only."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import backup_runtime_data as backup
from core.absence_transaction import absence_consistency_barrier
from core.request_consistency import absence_barrier_mode


def backup_checks():
    with tempfile.TemporaryDirectory(prefix="verify-native-backup-") as tmp:
        root = Path(tmp) / "runtime"
        root.mkdir()
        logs = root / "logs.json"
        logs.write_text('{"한글": "보존"}', "utf-8")
        db = root / "app.sqlite"
        with closing(sqlite3.connect(db)) as con:
            con.execute("CREATE TABLE proof (value TEXT)")
            con.execute("INSERT INTO proof VALUES ('persisted')")
            con.commit()
        out = Path(tmp) / "backups"
        with patch.object(backup, "ROOT", root):
            archive = backup.make_backup(out)
            manifest = backup.verify_archive(archive)
            with zipfile.ZipFile(archive) as zf:
                restored = Path(tmp) / "restored.sqlite"
                restored.write_bytes(zf.read("app.sqlite"))
                assert zf.read("logs.json") == logs.read_bytes()
                for item in manifest["files"]:
                    assert hashlib.sha256(zf.read(item["path"])).hexdigest() == item["sha256"]
            with closing(sqlite3.connect(restored)) as con:
                assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert con.execute("SELECT value FROM proof").fetchone()[0] == "persisted"
            # Mutate during compression, before stability validation.
            original_open = zipfile.ZipFile.open
            def mutate_on_manifest(zf, name, *args, **kwargs):
                if getattr(name, "filename", name) == "MANIFEST.json" and (args[0] if args else kwargs.get("mode", "r")) == 'w':
                    logs.write_text('{"concurrent": true}', "utf-8")
                return original_open(zf, name, *args, **kwargs)
            with patch.object(zipfile.ZipFile, "open", mutate_on_manifest):
                try:
                    backup.make_backup(out)
                    raise AssertionError("changing runtime was accepted")
                except RuntimeError as error:
                    assert "changed during backup" in str(error)
            assert list(out.glob("*.zip")) == [archive]
            assert not list(out.glob("*.partial"))
            (root / "logs.json.lock").write_text("held", "utf-8")
            try:
                backup.make_backup(out)
                raise AssertionError("active lock was accepted")
            except RuntimeError as error:
                assert "lock" in str(error)
        wal_root = Path(tmp) / "wal-runtime"
        wal_root.mkdir()
        with closing(sqlite3.connect(wal_root / "app.sqlite")) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE proof (value TEXT)")
            writer.execute("INSERT INTO proof VALUES ('wal-committed')")
            writer.commit()
            with patch.object(backup, "ROOT", wal_root):
                wal_archive = backup.make_backup(Path(tmp) / "wal-backups")
            with zipfile.ZipFile(wal_archive) as zf:
                assert not any(name.endswith(("-wal", "-shm")) for name in zf.namelist())
                restored = Path(tmp) / "restored-wal.sqlite"
                restored.write_bytes(zf.read("app.sqlite"))
            with closing(sqlite3.connect(restored)) as reader:
                assert reader.execute("SELECT value FROM proof").fetchone()[0] == "wal-committed"
        closed_wal_root = Path(tmp) / "closed-wal-runtime"
        closed_wal_root.mkdir()
        with closing(sqlite3.connect(closed_wal_root / "app.sqlite")) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE proof (value TEXT)")
            writer.execute("INSERT INTO proof VALUES ('closed-wal')")
            writer.commit()
        original_files = {p.name: p.read_bytes() for p in closed_wal_root.iterdir()}
        assert set(original_files) == {"app.sqlite"}
        with patch.object(backup, "ROOT", closed_wal_root):
            closed_archive = backup.make_backup(Path(tmp) / "closed-wal-backups")
        assert {p.name: p.read_bytes() for p in closed_wal_root.iterdir()} == original_files, "backup must not create runtime WAL/SHM itself"
        with zipfile.ZipFile(closed_archive) as zf:
            restored = Path(tmp) / "restored-closed-wal.sqlite"
            restored.write_bytes(zf.read("app.sqlite"))
        with closing(sqlite3.connect(restored)) as reader:
            assert reader.execute("SELECT value FROM proof").fetchone()[0] == "closed-wal"
    print("backup proof: native SQLite restore, archived-byte hashes, WAL/closed-WAL source invariance, concurrent change refusal, no false success")


def consistency_checks():
    for url in ("/api/tests/quick-printer-export", "/api/tests/quick-printer-export/preview"):
        assert absence_barrier_mode(url, "POST") == "exclusive"
    assert absence_barrier_mode("/api/arrive-time/missing-leave-summary", "GET") == "shared"
    assert absence_barrier_mode("/api/updates", "GET") == "shared"
    assert absence_barrier_mode("/api/updates", "GET", {"ensure": "1"}) == "exclusive"
    assert absence_barrier_mode("/api/updates/ensure-today", "POST") == "exclusive"
    assert absence_barrier_mode("/api/student/bootstrap", "GET") == "exclusive"
    assert absence_barrier_mode("/api/absent", "POST") is None
    with tempfile.TemporaryDirectory(prefix="verify-read-cohort-") as tmp:
        absent = Path(tmp) / "absent.json"
        release = threading.Event()
        first = threading.Event()
        second = threading.Event()
        writer = threading.Event()
        def read(entered):
            with absence_consistency_barrier(absent_path=absent, shared=True):
                entered.set()
                assert release.wait(5)
        def write():
            with absence_consistency_barrier(absent_path=absent):
                writer.set()
        with ThreadPoolExecutor(max_workers=3) as pool:
            a = pool.submit(read, first)
            assert first.wait(2)
            b = pool.submit(read, second)
            try:
                assert second.wait(0.5), "independent readers serialized"
                c = pool.submit(write)
                assert not writer.wait(0.15), "writer entered during active readers"
                child = subprocess.run([sys.executable, "-c", "from core.absence_transaction import absence_consistency_barrier; import sys\ntry:\n with absence_consistency_barrier(absent_path=sys.argv[1], lock_timeout_sec=0.1): print('UNSAFE')\nexcept TimeoutError: print('BLOCKED')", str(absent)], cwd=ROOT, text=True, capture_output=True, timeout=5)
                assert child.returncode == 0 and child.stdout.strip() == "BLOCKED", child.stderr
            finally:
                release.set()
            a.result(); b.result(); c.result()
            assert writer.is_set()
    print("absence proof: simultaneous readers, writer exclusion, print/warning coverage, no mutating-GET upgrade")


def main():
    backup_checks()
    consistency_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
