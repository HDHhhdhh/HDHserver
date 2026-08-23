from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import zipfile
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.storage import file_lock, save_atomic
from core.video_catalog_correction import (
    CorrectionValidationError,
    UnsafeVideoDeletion,
    apply_video_catalog_correction,
)


STORE_NAMES = ("videos.json", "updates.json", "progress.json", "watch.json")
WRITE_ORDER = ("updates.json", "progress.json", "watch.json", "videos.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, expected_type: type):
    try:
        value = json.loads(path.read_text("utf-8-sig"))
    except Exception as exc:
        raise CorrectionValidationError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, expected_type):
        expected = "array" if expected_type is list else "object"
        raise CorrectionValidationError(f"{path.name} must be an {expected}")
    return value


def _paths(root: Path) -> dict[str, Path]:
    return {name: root / name for name in STORE_NAMES}


def _port_is_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.35):
            return True
    except OSError:
        return False


def verify_backup_archive(archive: Path, root: Path, paths: dict[str, Path]) -> None:
    archive = archive.resolve()
    if not archive.is_file():
        raise CorrectionValidationError(f"backup archive not found: {archive}")
    try:
        with zipfile.ZipFile(archive, "r") as zipped:
            manifest = json.loads(zipped.read("MANIFEST.json").decode("utf-8"))
            archived_hashes = {
                name: hashlib.sha256(zipped.read(name)).hexdigest()
                for name in paths
            }
    except Exception as exc:
        raise CorrectionValidationError(f"invalid backup archive: {exc}") from exc
    if Path(str(manifest.get("root") or "")).resolve() != root.resolve():
        raise CorrectionValidationError("backup archive root does not match the apply root")
    entries = {
        str(entry.get("path") or ""): entry
        for entry in manifest.get("files", [])
        if isinstance(entry, dict)
    }
    for name, path in paths.items():
        entry = entries.get(name)
        if not entry:
            raise CorrectionValidationError(f"backup archive is missing {name}")
        expected_hash = str(entry.get("sha256") or "").lower()
        if expected_hash != archived_hashes[name].lower():
            raise CorrectionValidationError(f"backup archive content hash is invalid for {name}")
        if expected_hash != _sha256(path).lower():
            raise CorrectionValidationError(f"backup hash is stale for {name}")


def _save_store(path: Path, value: Any) -> None:
    save_atomic(path, value, compact=path.name == "progress.json")


def commit_correction_files(
    paths: dict[str, Path],
    originals: dict[str, Any],
    targets: dict[str, Any],
    *,
    save_store: Callable[[Path, Any], None] = _save_store,
) -> list[str]:
    changed_names = [name for name in WRITE_ORDER if originals[name] != targets[name]]
    attempted: list[str] = []
    try:
        for name in changed_names:
            attempted.append(name)
            save_store(paths[name], targets[name])
        for name in changed_names:
            if _load_json(paths[name], type(targets[name])) != targets[name]:
                raise RuntimeError(f"readback verification failed for {name}")
    except Exception as exc:
        rollback_errors = []
        for name in reversed(attempted):
            try:
                save_store(paths[name], originals[name])
            except Exception as rollback_exc:
                rollback_errors.append(f"{name}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                "video correction failed and rollback was incomplete: " + "; ".join(rollback_errors)
            ) from exc
        raise
    return changed_names


def run_correction(
    *,
    root: Path,
    draft_path: Path,
    apply: bool,
    backup_archive: Path | None = None,
    port: int = 8003,
    save_store: Callable[[Path, Any], None] = _save_store,
) -> dict[str, Any]:
    root = root.resolve()
    draft_path = draft_path.resolve()
    paths = _paths(root)
    draft = _load_json(draft_path, dict)
    lock_paths = sorted(paths.values(), key=lambda path: os.path.normcase(str(path.resolve())))

    if apply and root == ROOT.resolve() and _port_is_listening(port):
        raise CorrectionValidationError(
            f"refusing live correction while port {port} is listening; stop Waitress first"
        )

    with ExitStack() as stack:
        for path in lock_paths:
            stack.enter_context(file_lock(path, timeout_sec=30.0, poll_sec=0.05, stale_sec=60.0))
        originals = {
            "videos.json": _load_json(paths["videos.json"], list),
            "updates.json": _load_json(paths["updates.json"], dict),
            "progress.json": _load_json(paths["progress.json"], dict),
            "watch.json": _load_json(paths["watch.json"], dict),
        }
        result = apply_video_catalog_correction(
            current_videos=originals["videos.json"],
            draft=draft,
            updates=originals["updates.json"],
            progress=originals["progress.json"],
            watch=originals["watch.json"],
        )
        targets = {
            "videos.json": result["videos"],
            "updates.json": result["updates"],
            "progress.json": result["progress"],
            "watch.json": result["watch"],
        }
        changed_names = [name for name in WRITE_ORDER if originals[name] != targets[name]]
        if apply:
            if root == ROOT.resolve():
                if backup_archive is None:
                    raise CorrectionValidationError("live apply requires --backup-archive")
                verify_backup_archive(backup_archive, root, paths)
            changed_names = commit_correction_files(
                paths,
                originals,
                targets,
                save_store=save_store,
            )

    report = deepcopy(result["report"])
    report.update({
        "mode": "apply" if apply else "dry-run",
        "root": str(root),
        "draft": str(draft_path),
        "changedFiles": changed_names,
        "baseRows": len(draft.get("baseVideos", [])),
        "targetRows": len(draft.get("nextVideos", [])),
    })
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run or offline-apply a video catalog correction draft."
    )
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--port", type=int, default=8003)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-archive", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_correction(
            root=args.root,
            draft_path=args.draft,
            apply=args.apply,
            backup_archive=args.backup_archive,
            port=args.port,
        )
    except UnsafeVideoDeletion as exc:
        print(json.dumps({
            "ok": False,
            "error": "referenced_video_deletion",
            "references": exc.references,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3
    except (CorrectionValidationError, OSError, RuntimeError) as exc:
        print(json.dumps({
            "ok": False,
            "error": "video_correction_rejected",
            "message": str(exc),
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())