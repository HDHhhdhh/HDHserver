from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
FORMAT = "student-app-code-release/v1"
ALLOWED_ROOT_FILES = {
    ".gitignore",
    "AGENTS.md",
    "app.py",
    "requirements-student-app.txt",
}
ALLOWED_EXTENSIONS = {
    "core": {".md", ".py"},
    "routes": {".md", ".py"},
    "scripts": {".bat", ".js", ".json", ".md", ".mjs", ".ps1", ".py", ".sql", ".txt"},
    "docs": {".md", ".txt"},
    "static": {
        ".css",
        ".html",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".json",
        ".mjs",
        ".png",
        ".svg",
        ".txt",
        ".webmanifest",
        ".webp",
        ".woff2",
    },
}
DENIED_PARTS = {
    ".codex",
    ".git",
    ".omo",
    ".pytest_cache",
    "__pycache__",
    "generated",
    "output",
    "test-results",
    "venv",
}
DENIED_NAMES = {".env", "MANIFEST.json", "RELEASE-MANIFEST.json"}
DENIED_SUFFIXES = {
    ".bak",
    ".csv",
    ".db",
    ".lock",
    ".log",
    ".out",
    ".pem",
    ".sqlite",
    ".tmp",
    ".zip",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _allowed_path(relative: PurePosixPath) -> bool:
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        return False
    lowered_parts = {part.casefold() for part in relative.parts}
    if lowered_parts & {part.casefold() for part in DENIED_PARTS}:
        return False
    if relative.name.casefold() in {name.casefold() for name in DENIED_NAMES}:
        return False
    if any(relative.name.casefold().endswith(suffix) for suffix in DENIED_SUFFIXES):
        return False
    if len(relative.parts) == 1:
        return relative.name in ALLOWED_ROOT_FILES
    root = relative.parts[0]
    return root in ALLOWED_EXTENSIONS and relative.suffix.casefold() in ALLOWED_EXTENSIONS[root]


def iter_release_files(root: Path = ROOT) -> list[tuple[PurePosixPath, Path]]:
    candidates: list[Path] = []
    candidates.extend(root / name for name in sorted(ALLOWED_ROOT_FILES))
    for directory in sorted(ALLOWED_EXTENSIONS):
        base = root / directory
        if base.is_dir():
            candidates.extend(path for path in base.rglob("*") if path.is_file())
    selected: list[tuple[PurePosixPath, Path]] = []
    for path in candidates:
        if not path.exists() or path.is_symlink():
            continue
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if _allowed_path(relative):
            selected.append((relative, path))
    return sorted(set(selected), key=lambda item: item[0].as_posix())


def _removed_paths() -> list[str]:
    output = _git("diff", "--name-only", "--diff-filter=D", "--")
    removed = []
    for raw in output.splitlines():
        relative = PurePosixPath(raw.strip().replace("\\", "/"))
        if _allowed_path(relative):
            removed.append(relative.as_posix())
    return sorted(set(removed))


def build_release(output: Path) -> dict:
    files = iter_release_files()
    if not files:
        raise RuntimeError("No code files selected for release.")
    created_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    entries = []
    payloads: list[tuple[str, bytes]] = []
    for relative, path in files:
        data = path.read_bytes()
        name = relative.as_posix()
        entries.append({"path": name, "size": len(data), "sha256": _sha256(data)})
        payloads.append((name, data))
    status = _git("status", "--porcelain")
    manifest = {
        "format": FORMAT,
        "createdAt": created_at,
        "source": {
            "branch": _git("branch", "--show-current"),
            "commit": _git("rev-parse", "HEAD"),
            "dirty": bool(status),
            "dirtyPathCount": len(status.splitlines()) if status else 0,
        },
        "policy": {
            "containsRuntimeData": False,
            "containsCredentials": False,
            "deploymentDirection": "development-to-production",
        },
        "removedPaths": _removed_paths(),
        "files": entries,
    }
    manifest_data = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(temp_output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("RELEASE-MANIFEST.json", manifest_data)
        for name, data in payloads:
            archive.writestr(name, data)
    temp_output.replace(output)
    verified = verify_release(output)
    checksum_path = output.with_suffix(output.suffix + ".sha256.txt")
    checksum_path.write_text(f"{_sha256(output.read_bytes())}  {output.name}\n", encoding="ascii")
    return {**verified, "checksumPath": str(checksum_path.resolve())}


def verify_release(archive_path: Path) -> dict:
    if not archive_path.is_file():
        raise RuntimeError(f"Release archive not found: {archive_path}")
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if names.count("RELEASE-MANIFEST.json") != 1 or len(names) != len(set(names)):
            raise RuntimeError("Release archive has a missing or duplicate manifest/path.")
        manifest = json.loads(archive.read("RELEASE-MANIFEST.json"))
        if manifest.get("format") != FORMAT:
            raise RuntimeError("Unsupported release manifest format.")
        expected = {item["path"]: item for item in manifest.get("files", [])}
        actual_names = set(names) - {"RELEASE-MANIFEST.json"}
        if actual_names != set(expected):
            raise RuntimeError("Archive entries differ from the signed manifest.")
        for name in sorted(actual_names):
            relative = PurePosixPath(name)
            if not _allowed_path(relative):
                raise RuntimeError(f"Forbidden release path: {name}")
            data = archive.read(name)
            item = expected[name]
            if len(data) != item.get("size") or _sha256(data) != item.get("sha256"):
                raise RuntimeError(f"Release hash mismatch: {name}")
        for raw in manifest.get("removedPaths", []):
            if not _allowed_path(PurePosixPath(raw)):
                raise RuntimeError(f"Forbidden removed path: {raw}")
    return {
        "ok": True,
        "archive": str(archive_path.resolve()),
        "size": archive_path.stat().st_size,
        "sha256": _sha256(archive_path.read_bytes()),
        "fileCount": len(expected),
        "removedPathCount": len(manifest.get("removedPaths", [])),
        "source": manifest.get("source", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify a runtime-free student app code release.")
    parser.add_argument("--output", type=Path, help="Destination ZIP for a new release.")
    parser.add_argument("--verify-only", type=Path, help="Verify an existing release without writing.")
    args = parser.parse_args()
    if bool(args.output) == bool(args.verify_only):
        parser.error("Provide exactly one of --output or --verify-only.")
    try:
        result = build_release(args.output.resolve()) if args.output else verify_release(args.verify_only.resolve())
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
