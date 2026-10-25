from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import socket
import shutil
import sqlite3
import tempfile
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", "venv", "_data_mirror", "_runtime_backups", "isolated-design-server"}
ROOT_DATA_SUFFIXES = {
    ".json",
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
    ".db",
    ".db-wal",
    ".db-shm",
    ".csv",
    ".tmp",
}
DATA_DIRS = {"data", "files", "instance"}
VAPID_PRIVATE_PATH = "instance/student-app-vapid-private.pem"
TEST_PUSH_APPROVAL_PATH = "instance/student-test-push-approval.json"


def is_excluded_secret(path: Path, root: Path) -> bool:
    """Keep credentials and one-time approval capabilities out of archives."""
    relative = path.relative_to(root).as_posix()
    return any(
        relative == prefix or relative.startswith(f"{prefix}.")
        for prefix in (VAPID_PRIVATE_PATH, TEST_PUSH_APPROVAL_PATH)
    )


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
      for chunk in iter(lambda: f.read(1024 * 1024), b""):
          h.update(chunk)
    return h.hexdigest()


def iter_runtime_files(root: Path):
    for path in sorted(root.iterdir()):
        if path.is_file() and path.suffix.lower() in ROOT_DATA_SUFFIXES:
            yield path

    for dirname in DATA_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_dir():
                continue
            if any(part in DEFAULT_SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            if is_excluded_secret(path, root):
                continue
            yield path


def _signature(path: Path) -> tuple:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino


def _require_quiescent(root: Path) -> None:
    source_root = Path(__file__).resolve().parents[1]
    port = 8003 if root.resolve() == source_root else 8004 if (root / ".academy-isolated-server.json").exists() else None
    if port is not None:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Backup requires an approved maintenance stop first (port {port} is active). No server was stopped.")
    candidates = list(root.glob("*.lock"))
    candidates.extend(path for path in root.glob("*_transaction.json") if path.is_file())
    for dirname in DATA_DIRS:
        base = root / dirname
        if base.exists():
            candidates.extend(path for path in base.rglob("*") if path.is_file()
                              and not any(part in DEFAULT_SKIP_DIRS for part in path.relative_to(root).parts)
                              # Dependency manifests remain in the archive, not the active-lock gate.
                              and not (path.name == "yarn.lock" and "node_modules" in path.relative_to(root).parts)
                              and (path.name.endswith(".lock") or path.name == "pending.json"))
    if candidates:
        raise RuntimeError("Backup refused: an active/stale lock or pending transaction needs review first.")


def verify_archive(archive: Path) -> dict:
    """Read archived bytes, not current runtime files; never restore into runtime."""
    with zipfile.ZipFile(archive) as zf:
        manifest = json.loads(zf.read("MANIFEST.json"))
        expected = {item["path"] for item in manifest["files"]}
        if len(expected) != len(manifest["files"]) or set(zf.namelist()) != expected | {"MANIFEST.json"}:
            raise ValueError("backup manifest membership mismatch")
        for item in manifest["files"]:
            digest = hashlib.sha256()
            count = 0
            with zf.open(item["path"]) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    count += len(chunk)
                    digest.update(chunk)
            if count != item["size"] or digest.hexdigest() != item["sha256"]:
                raise ValueError(f"backup checksum mismatch: {item['path']}")
    return manifest


def make_backup(out_dir: Path) -> Path:
    root = ROOT.resolve()
    _require_quiescent(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"runtime-data-{utc_stamp()}-{uuid.uuid4().hex[:8]}.zip"
    partial = archive.with_suffix(".partial")
    paths = list(iter_runtime_files(root))
    before = {path: _signature(path) for path in paths}
    manifest = {
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "root": str(ROOT),
        "files": [],
        "snapshotMode": "quiescent-sqlite-backup-v1",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="runtime-backup-snapshot-") as tmp:
            with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for index, path in enumerate(paths):
                    if path.name.endswith(("-wal", "-shm")):
                        continue  # Committed WAL content is folded into the native backup.
                    if path.is_symlink() or not path.resolve().is_relative_to(root):
                        raise ValueError("backup source escaped runtime root")
                    source = path
                    if path.suffix.lower() in {".sqlite", ".db"}:
                        source = Path(tmp) / f"database-{index}.sqlite"
                        # Even mode=ro can create WAL/SHM beside a closed WAL
                        # database. Stage quiescent bytes first so SQLite never
                        # opens the runtime source; final signatures still reject
                        # any source change while these copies were collected.
                        staged = Path(tmp) / f"source-{index}.sqlite"
                        shutil.copyfile(path, staged)
                        wal = path.with_name(path.name + "-wal")
                        if wal.exists():
                            if wal.is_symlink() or not wal.resolve().is_relative_to(root):
                                raise ValueError("backup WAL escaped runtime root")
                            shutil.copyfile(wal, staged.with_name(staged.name + "-wal"))
                        origin = sqlite3.connect(f"{staged.as_uri()}?mode=ro", uri=True)
                        target = sqlite3.connect(source)
                        try:
                            origin.backup(target)
                            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                                raise ValueError("SQLite backup failed integrity check")
                        finally:
                            target.close()
                            origin.close()
                    digest = hashlib.sha256()
                    size = 0
                    rel = path.relative_to(root).as_posix()
                    with source.open("rb") as stream, zf.open(rel, "w") as dest:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            dest.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    manifest["files"].append({"path": rel, "size": size,
                                               "mtime": int(path.stat().st_mtime), "sha256": digest.hexdigest()})
                zf.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        _require_quiescent(root)
        after = {path: _signature(path) for path in iter_runtime_files(root)}
        if before != after:
            changed = sorted(path.relative_to(root).as_posix() for path in before.keys() | after.keys()
                             if before.get(path) != after.get(path))
            raise RuntimeError("Runtime changed during backup; archive was not published. "
                               "Retry after quiescing all writers. Changed: " + ", ".join(changed[:8]))
        verify_archive(partial)
        partial.replace(archive)
    except BaseException:
        # This exact file was created by this invocation, never an older backup.
        partial.unlink(missing_ok=True)
        raise
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a zip backup of local runtime data.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(os.environ.get("RUNTIME_BACKUP_DIR", ROOT / "_runtime_backups")),
        help="Backup destination directory. Prefer an external or synced drive.",
    )
    args = parser.parse_args()
    archive = make_backup(args.out)
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
