from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", "venv", "_data_mirror", "_runtime_backups"}
ROOT_DATA_SUFFIXES = {".json", ".sqlite", ".db", ".csv"}
DATA_DIRS = {"data", "files", "instance"}


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
            yield path


def make_backup(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"runtime-data-{utc_stamp()}.zip"
    manifest = {
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "root": str(ROOT),
        "files": [],
    }

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in iter_runtime_files(ROOT):
            rel = path.relative_to(ROOT).as_posix()
            zf.write(path, rel)
            stat = path.stat()
            manifest["files"].append({
                "path": rel,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "sha256": sha256_file(path),
            })
        zf.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))

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
