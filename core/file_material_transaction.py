"""Path-injected filesystem plan for the material journal's prepared/commit phases."""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import stat
import uuid


class FileMaterialTransactionError(RuntimeError):
    """The filesystem intent cannot be safely applied or recovered."""


def _absolute(path) -> str:
    return os.path.normcase(str(pathlib.Path(path).resolve()))


def _relative(value) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\0" in value:
        raise FileMaterialTransactionError("invalid file transaction path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise FileMaterialTransactionError("invalid file transaction path")
    return value


def _contained(root: pathlib.Path, relative: str) -> pathlib.Path:
    path = root / _relative(relative)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise FileMaterialTransactionError("file transaction path escaped its root") from exc
    return path


def entry_identity(path) -> dict:
    info = pathlib.Path(path).lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
        raise FileMaterialTransactionError("file transaction entry must not be a link")
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or info.st_ino <= 0:
        raise FileMaterialTransactionError("file transaction entry has no stable identity")
    return {"device": info.st_dev, "inode": info.st_ino, "directory": stat.S_ISDIR(info.st_mode)}


def staging_directory(plan: dict) -> pathlib.Path | None:
    if plan["kind"] not in {"delete", "upload"}:
        return None
    return pathlib.Path(plan["filesRoot"]).parent / "instance" / f'.file-{plan["kind"]}-stage-{plan["id"]}'


def operation_paths(plan: dict, operation: dict) -> tuple[pathlib.Path, pathlib.Path]:
    files_root = pathlib.Path(plan["filesRoot"])
    staging = staging_directory(plan)
    source_root = staging if plan["kind"] == "upload" else files_root
    target_root = staging if plan["kind"] == "delete" else files_root
    return _contained(source_root, operation["source"]), _contained(target_root, operation["target"])


def directory_entries(plan: dict) -> list[dict]:
    # Legacy path-only entries carry no proof that an existing directory is ours.
    return [{"path": entry, "identity": None} if isinstance(entry, str) else entry
            for entry in plan["directories"]]


def validate_plan(plan, files_dir, store_paths) -> dict:
    if not isinstance(plan, dict) or set(plan) != {"id", "kind", "filesRoot", "stores", "operations", "directories"}:
        raise FileMaterialTransactionError("invalid file transaction plan")
    if not isinstance(plan["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", plan["id"]):
        raise FileMaterialTransactionError("invalid file transaction identity")
    if not isinstance(plan["kind"], str) or plan["kind"] not in {"rename", "move", "delete", "upload"}:
        raise FileMaterialTransactionError("invalid file transaction operation")
    if plan["filesRoot"] != _absolute(files_dir) or plan["stores"] != [_absolute(p) for p in store_paths]:
        raise FileMaterialTransactionError("file transaction belongs to different runtime paths")
    if not isinstance(plan["operations"], list) or not isinstance(plan["directories"], list):
        raise FileMaterialTransactionError("invalid file transaction entries")
    sources, targets = [], []
    for operation in plan["operations"]:
        if not isinstance(operation, dict) or set(operation) != {"source", "target", "identity"}:
            raise FileMaterialTransactionError("invalid file transaction entry")
        source, target = operation_paths(plan, operation)
        if source.resolve() == target.resolve():
            raise FileMaterialTransactionError("file transaction entry has the same source and target")
        identity = operation["identity"]
        if identity is None:
            if plan["kind"] != "upload":
                raise FileMaterialTransactionError("missing file transaction entry identity")
        elif (
            not isinstance(identity, dict) or set(identity) != {"device", "inode", "directory"}
            or type(identity["device"]) is not int or identity["device"] < 0
            or type(identity["inode"]) is not int or identity["inode"] <= 0
            or type(identity["directory"]) is not bool
        ):
            raise FileMaterialTransactionError("invalid file transaction entry identity")
        sources.append(source)
        targets.append(target)
    # Recovery may never overwrite another operation's source or an overlapping subtree.
    for paths in (sources, targets):
        for index, path in enumerate(paths):
            for other in paths[index + 1:]:
                if path == other or path in other.parents or other in path.parents:
                    raise FileMaterialTransactionError("overlapping file transaction entries")
    for source in sources:
        for target in targets:
            if source == target or source in target.parents or target in source.parents:
                raise FileMaterialTransactionError("overlapping file transaction source and target")
    directories = []
    for entry in directory_entries(plan):
        if not isinstance(entry, dict) or set(entry) != {"path", "identity"}:
            raise FileMaterialTransactionError("invalid file transaction directory")
        directory = _contained(pathlib.Path(plan["filesRoot"]), entry["path"])
        identity = entry["identity"]
        if identity is not None and (
            not isinstance(identity, dict) or set(identity) != {"device", "inode", "directory"}
            or type(identity["device"]) is not int or identity["device"] < 0
            or type(identity["inode"]) is not int or identity["inode"] <= 0
            or identity["directory"] is not True
        ):
            raise FileMaterialTransactionError("invalid file transaction directory identity")
        if directory in directories:
            raise FileMaterialTransactionError("duplicate file transaction directory")
        directories.append(directory)
    staging = staging_directory(plan)
    if staging is not None and staging.resolve() != staging.absolute():
        raise FileMaterialTransactionError("file transaction staging directory is a link")
    return plan


def make_plan(files_dir, store_paths, kind, pairs, *, directories=(), transaction_id=None) -> dict:
    plan = {
        "id": transaction_id or uuid.uuid4().hex, "kind": kind,
        "filesRoot": _absolute(files_dir), "stores": [_absolute(p) for p in store_paths],
        "operations": [{"source": source, "target": target, "identity": None} for source, target in pairs],
        "directories": [{"path": directory, "identity": None} for directory in directories],
    }
    for operation in plan["operations"]:
        if kind != "upload":
            source, _target = operation_paths(plan, operation)
            operation["identity"] = entry_identity(source)
    return validate_plan(plan, files_dir, store_paths)


def _exists(path: pathlib.Path) -> bool:
    return os.path.lexists(path)


def _require_identity(path: pathlib.Path, expected: dict) -> None:
    if entry_identity(path) != expected:
        raise FileMaterialTransactionError(f"file transaction entry was replaced: {path}")


def _verify_directories(plan: dict, *, require_present: bool = False) -> list[pathlib.Path]:
    root = pathlib.Path(plan["filesRoot"])
    owned = []
    for entry in directory_entries(plan):
        directory = _contained(root, entry["path"])
        if not _exists(directory):
            if require_present:
                raise FileMaterialTransactionError(f"created directory is missing: {directory}")
            continue
        if entry["identity"] is None:
            raise FileMaterialTransactionError(f"directory ownership was not recorded: {directory}")
        _require_identity(directory, entry["identity"])
        owned.append(directory)
    return owned


def create_planned_directories(plan: dict, record_plan) -> None:
    root = pathlib.Path(plan["filesRoot"])
    entries = sorted(directory_entries(plan), key=lambda entry: (entry["path"].count("/"), entry["path"]))
    for entry in entries:
        directory = _contained(root, entry["path"])
        if entry["identity"] is not None:
            _require_identity(directory, entry["identity"])
            continue
        # Exclusive mkdir distinguishes our creation from a directory another
        # writer created after intent. A crash before recording stays ambiguous.
        directory.mkdir()
        entry["identity"] = entry_identity(directory)
        record_plan(plan)
    _verify_directories(plan, require_present=True)


def verify_applied(plan: dict) -> None:
    _verify_directories(plan, require_present=True)
    for operation in plan["operations"]:
        source, target = operation_paths(plan, operation)
        if operation["identity"] is None or _exists(source):
            raise FileMaterialTransactionError("file transaction operation is not fully applied")
        if _exists(target):
            _require_identity(target, operation["identity"])
        elif plan["kind"] != "delete":
            raise FileMaterialTransactionError(f"committed file transaction target is missing: {target}")


def _rollback_preflight(plan: dict) -> tuple[list[tuple[pathlib.Path, pathlib.Path, dict]], list[pathlib.Path]]:
    owned_directories = _verify_directories(plan)
    actions = []
    for operation in reversed(plan["operations"]):
        source, target = operation_paths(plan, operation)
        source_exists, target_exists = _exists(source), _exists(target)
        identity = operation["identity"]
        if identity is None:
            if target_exists:
                raise FileMaterialTransactionError("unpublished upload target was created by another writer")
            continue
        if source_exists and target_exists:
            raise FileMaterialTransactionError("file transaction source and target both exist")
        if not source_exists and not target_exists:
            if plan["kind"] == "upload":
                continue
            raise FileMaterialTransactionError("file transaction source and target are both missing")
        if source_exists:
            _require_identity(source, identity)
        else:
            _require_identity(target, identity)
            if plan["kind"] != "upload" and not source.parent.is_dir():
                raise FileMaterialTransactionError(f"rollback source parent is missing: {source.parent}")
            actions.append((source, target, identity))
    # Validate every detectable conflict before the first undo. Created folders
    # may contain only entries this rollback will move/remove or owned subfolders.
    removable = set(owned_directories) | {target for _source, target, _identity in actions}
    for directory in owned_directories:
        if any(child not in removable for child in directory.iterdir()):
            raise FileMaterialTransactionError(f"created directory contains an unrelated entry: {directory}")
    return actions, owned_directories


def rollback_prepared(plan: dict) -> None:
    actions, owned_directories = _rollback_preflight(plan)
    for source, target, identity in actions:
        _require_identity(target, identity)
        if _exists(source):
            raise FileMaterialTransactionError(f"rollback source was created by another writer: {source}")
        if plan["kind"] == "upload":
            target.unlink()
        else:
            target.rename(source)
    cleanup_staging(plan)
    identities = {entry["path"]: entry["identity"] for entry in directory_entries(plan)}
    root = pathlib.Path(plan["filesRoot"])
    for directory in sorted(owned_directories, key=lambda path: len(path.parts), reverse=True):
        _require_identity(directory, identities[directory.relative_to(root).as_posix()])
        try:
            directory.rmdir()
        except OSError as exc:
            raise FileMaterialTransactionError(f"created directory cannot be safely removed: {directory}") from exc


def cleanup_staging(plan: dict) -> None:
    staging = staging_directory(plan)
    if staging is not None and staging.exists():
        shutil.rmtree(staging)
