from __future__ import annotations

import os
import pathlib
import re
from contextlib import contextmanager
from typing import Iterator

from flask import Blueprint, abort, g, jsonify, make_response, request, send_from_directory

from core.announcement_image_access import student_can_access_announcement_image_from_store
from core.file_material_transaction import (
    FileMaterialTransactionError,
    create_planned_directories,
    entry_identity,
    make_plan,
    operation_paths,
    staging_directory,
)
from core.material_reference_rules import (
    path_is_same_or_descendant,
    remove_material_file_references,
    rewrite_material_file_references,
)
from core.material_state import (
    MaterialStateRecoveryRequiredError,
    load_material_state_locked,
    material_state_lock,
    prepare_file_material_state_locked,
    recover_material_state_locked,
    rollback_file_material_state_if_prepared_locked,
    save_material_state_locked,
    update_prepared_file_material_state_locked,
)
from core.paths import ANNS_PATH, FILES_DIR, MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH
from core.student_public_surface_paths import resolve_raw_request_target, safe_announcement_file

bp_api_fs = Blueprint("api_fs", __name__)
FILES_ROOT = FILES_DIR.resolve()

def json_or_form() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    if request.form:
        data.update({k: v for k, v in request.form.items()})
    return data

def _safe_join(rel_path: str) -> pathlib.Path:
    rel = str(rel_path or "").lstrip("/").replace("\\", "/")
    p = (FILES_ROOT / rel).resolve()
    try:
        p.relative_to(FILES_ROOT)
    except ValueError:
        raise ValueError("unsafe path")
    return p

def _reject_root_path(p: pathlib.Path) -> None:
    if p.resolve() == FILES_ROOT:
        raise ValueError("refusing to modify files root")

def _is_relative_to(child: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False

def _rel_from_abs(p: pathlib.Path) -> str:
    rel = os.path.relpath(p.resolve(), FILES_DIR.resolve())
    if rel in (".", ".\\"):
        return ""
    return pathlib.Path(rel).as_posix()

def _scan_tree() -> dict:
    root = {"name": "", "type": "dir", "path": "", "children": []}
    idx = {"": root, ".": root}

    for dirpath, dirnames, filenames in os.walk(FILES_DIR):
        rel_dir = _rel_from_abs(pathlib.Path(dirpath))
        parent = idx[rel_dir]

        for d in sorted(dirnames):
            rel = (pathlib.Path(rel_dir) / d).as_posix() if rel_dir else d
            node = {"name": d, "type": "dir", "path": rel, "children": []}
            parent["children"].append(node)
            idx[rel] = node

        for f in sorted(filenames):
            abs_f = pathlib.Path(dirpath) / f
            rel_f = _rel_from_abs(abs_f)
            st = abs_f.stat()
            parent["children"].append({
                "name": f,
                "type": "file",
                "path": rel_f,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "url": f"/files/{rel_f}",
            })
    return root


@contextmanager
def _file_material_state_scope() -> Iterator[None]:
    # Filesystem mutations always acquire the file-tree lock before the three
    # deterministic material-state locks. Keep this order for every writer.
    with material_state_lock(MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH, files_dir=FILES_DIR):
        yield


def _load_material_state_checked_locked() -> tuple[dict, dict, dict]:
    materials, assignments, page_folders = load_material_state_locked(
        MAT_PATH,
        ASN_PATH,
        PAGE_FOLDERS_PATH,
        files_dir=FILES_DIR,
    )
    if not isinstance(materials, dict):
        raise RuntimeError("materials store must be an object")
    if not isinstance(assignments, dict):
        raise RuntimeError("assignments store must be an object")
    if not isinstance(page_folders, dict):
        raise RuntimeError("pageFolders store must be an object")
    return materials, assignments, page_folders


def _save_material_state_locked(
    materials: dict, assignments: dict, page_folders: dict,
    *, file_transaction_id: str | None = None,
) -> None:
    save_material_state_locked(
        MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH,
        materials, assignments, page_folders,
        file_transaction_id=file_transaction_id, files_dir=FILES_DIR,
    )


def _file_plan(kind: str, pairs: list[tuple[str, str]], *, directories=(), transaction_id=None) -> dict:
    try:
        return make_plan(FILES_DIR, (MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH), kind, pairs,
                         directories=directories, transaction_id=transaction_id)
    except FileMaterialTransactionError as exc:
        raise MaterialStateRecoveryRequiredError(str(exc)) from exc


@contextmanager
def _file_transaction_scope(state: tuple[dict, dict, dict], plan: dict) -> Iterator[str]:
    transaction_id = prepare_file_material_state_locked(
        MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH, *state, plan, files_dir=FILES_DIR,
    )
    try:
        yield transaction_id
    finally:
        # A durable committing marker owns forward recovery; only an intent
        # that never reached that marker may restore/remove filesystem entries.
        rollback_file_material_state_if_prepared_locked(
            MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH, transaction_id, files_dir=FILES_DIR,
        )


def _update_file_plan(plan: dict) -> None:
    update_prepared_file_material_state_locked(
        MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH, plan, files_dir=FILES_DIR,
    )


def _create_transaction_directories(plan: dict, destination: pathlib.Path) -> None:
    try:
        create_planned_directories(plan, _update_file_plan)
    except (OSError, FileMaterialTransactionError) as exc:
        raise MaterialStateRecoveryRequiredError("file transaction directory creation is incomplete") from exc
    if not destination.is_dir():
        raise FileExistsError("destination is not a directory")


def _missing_directories(directory: pathlib.Path) -> list[str]:
    missing = []
    current = directory
    while not current.exists() and current != FILES_ROOT:
        missing.append(_rel_from_abs(current))
        current = current.parent
    return missing


def _ensure_dir(rel_dir: str):
    p = _safe_join(rel_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p

SAFE_NAME_RE = re.compile(r'[^0-9A-Za-z가-힣\s\.\-\_\(\)\[\]]+')
def _clean_filename(name: str) -> str:
    name = (name or "").strip()
    name = name.replace("/", "／").replace("\\", "＼")
    name = SAFE_NAME_RE.sub("", name)
    name = name.rstrip(" .")
    return name or "파일"


def _clean_requested_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw or "/" in raw or "\\" in raw:
        raise ValueError("new_name must be one file or folder name")
    cleaned = SAFE_NAME_RE.sub("", raw).rstrip(" .")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("new_name contains no supported characters")
    return cleaned


def _validate_non_overlapping_sources(paths: list[str]) -> None:
    for index, path in enumerate(paths):
        for other in paths[index + 1:]:
            if path_is_same_or_descendant(path, other) or path_is_same_or_descendant(other, path):
                raise ValueError("paths must not overlap")


def _planned_move_target(
    destination: pathlib.Path,
    source: pathlib.Path,
    reserved_names: set[str],
) -> pathlib.Path:
    original_name = source.name
    candidate_name = original_name
    candidate_key = candidate_name.casefold()
    if not (destination / candidate_name).exists() and candidate_key not in reserved_names:
        reserved_names.add(candidate_key)
        return destination / candidate_name

    if source.is_file():
        stem, dot, extension = original_name.rpartition(".")
        if not dot:
            stem, extension = original_name, ""
        index = 1
        while True:
            suffix = f" ({index})"
            candidate_name = f"{stem}{suffix}.{extension}" if extension else f"{stem}{suffix}"
            candidate_key = candidate_name.casefold()
            if not (destination / candidate_name).exists() and candidate_key not in reserved_names:
                reserved_names.add(candidate_key)
                return destination / candidate_name
            index += 1

    index = 1
    while True:
        candidate_name = f"{original_name} ({index})"
        candidate_key = candidate_name.casefold()
        if not (destination / candidate_name).exists() and candidate_key not in reserved_names:
            reserved_names.add(candidate_key)
            return destination / candidate_name
        index += 1


def _unique_name(dst_dir: pathlib.Path, filename: str, reserved_names: set[str]) -> str:
    base = _clean_filename(filename)
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    name = base
    i = 1
    while (dst_dir / name).exists() or name.casefold() in reserved_names:
        suffix = f" ({i})"
        name = f"{stem}{suffix}.{ext}" if ext else f"{stem}{suffix}"
        i += 1
    reserved_names.add(name.casefold())
    return name

# 트리 조회
@bp_api_fs.get("/api/fs/tree")
def api_fs_tree():
    try:
        with _file_material_state_scope():
            recover_material_state_locked(MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH, files_dir=FILES_DIR)
            tree = _scan_tree()
    except (MaterialStateRecoveryRequiredError, TimeoutError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    resp = make_response(jsonify({"tree": tree}))
    resp.headers["Cache-Control"] = "no-store"
    return resp

# 폴더 생성
@bp_api_fs.post("/api/fs/folder")
def api_fs_folder():
    body = json_or_form()
    path = (body.get("path") or "").strip()
    if not path:
        return jsonify({"ok": False, "error": "path required"}), 400
    try:
        with _file_material_state_scope():
            _load_material_state_checked_locked()
            _ensure_dir(path)
        return jsonify({"ok": True})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except (MaterialStateRecoveryRequiredError, TimeoutError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except Exception as exc:
        print(f"[file-manager] folder create failed: {exc}", flush=True)
        return jsonify({"ok": False, "error": "folder create failed"}), 500

@bp_api_fs.post("/api/fs/rename")
def api_fs_rename():
    body = request.get_json(force=True) or {}
    src = str(body.get("src") or "").strip()
    new_name = str(body.get("new_name") or "").strip()
    if not src or not new_name:
        return jsonify({"ok": False, "error": "src/new_name required"}), 400

    try:
        cleaned_name = _clean_requested_name(new_name)
        with _file_material_state_scope():
            materials, assignments, page_folders = _load_material_state_checked_locked()
            abs_src = _safe_join(src)
            _reject_root_path(abs_src)
            if not abs_src.exists():
                raise FileNotFoundError("source does not exist")

            abs_dst = abs_src.parent / cleaned_name
            if abs_dst.exists():
                raise FileExistsError("already exists")

            old_rel = _rel_from_abs(abs_src)
            new_rel = _rel_from_abs(abs_dst)
            next_state = rewrite_material_file_references(
                materials,
                assignments,
                page_folders,
                [(old_rel, new_rel)],
            )

            plan = _file_plan("rename", [(old_rel, new_rel)])
            with _file_transaction_scope((materials, assignments, page_folders), plan) as transaction_id:
                abs_src.rename(abs_dst)
                _save_material_state_locked(*next_state, file_transaction_id=transaction_id)

        return jsonify({"ok": True, "path": new_rel})
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except (MaterialStateRecoveryRequiredError, TimeoutError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except Exception as exc:
        print(f"[file-manager] rename failed: {exc}", flush=True)
        return jsonify({"ok": False, "error": "rename failed"}), 500

@bp_api_fs.post("/api/fs/delete")
def api_fs_delete():
    body = request.get_json(force=True) or {}
    items = body.get("paths") or []
    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "error": "paths[] required"}), 400

    deleted: list[str] = []
    errors: list[dict] = []
    try:
        with _file_material_state_scope():
            state = _load_material_state_checked_locked()
            valid = []
            for raw_rel in items:
                try:
                    if not isinstance(raw_rel, str) or not raw_rel.strip():
                        raise ValueError("path must be a non-empty string")
                    absolute = _safe_join(raw_rel)
                    _reject_root_path(absolute)
                    valid.append((raw_rel, absolute, _rel_from_abs(absolute)))
                except Exception as exc:
                    errors.append({"path": raw_rel, "error": str(exc)})
            if valid:
                # Ancestors subsume descendant delete requests; each inode is staged once.
                existing = {relative: absolute for _raw, absolute, relative in valid if absolute.exists()}
                roots = [relative for relative in existing
                         if not any(relative != other and path_is_same_or_descendant(relative, other)
                                    for other in existing)]
                plan = _file_plan("delete", [(relative, str(index)) for index, relative in enumerate(roots)])
                failed = {}
                with _file_transaction_scope(state, plan) as transaction_id:
                    staging = staging_directory(plan)
                    if plan["operations"]:
                        staging.mkdir(parents=True, exist_ok=False)
                    successful = []
                    for operation in plan["operations"]:
                        absolute, staged = operation_paths(plan, operation)
                        try:
                            absolute.rename(staged)
                            successful.append(operation)
                        except Exception as exc:
                            failed[operation["source"]] = str(exc)
                    plan["operations"] = successful
                    _update_file_plan(plan)
                    prefixes = []
                    for raw_rel, _absolute, relative in valid:
                        failure = next((error for prefix, error in failed.items()
                                        if path_is_same_or_descendant(relative, prefix)), None)
                        if failure is not None:
                            errors.append({"path": raw_rel, "error": failure})
                        else:
                            deleted.append(raw_rel)
                            prefixes.append(relative)
                    if prefixes:
                        next_state = remove_material_file_references(*state, prefixes)
                        _save_material_state_locked(*next_state, file_transaction_id=transaction_id)
        return jsonify({"ok": True, "deleted": deleted, "errors": errors})
    except (MaterialStateRecoveryRequiredError, TimeoutError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except Exception as exc:
        print(f"[file-manager] delete failed: {exc}", flush=True)
        return jsonify({"ok": False, "error": "delete failed"}), 500


@bp_api_fs.post("/api/fs/move")
def api_fs_move():
    body = request.get_json(force=True) or {}
    items = body.get("paths")
    dst_value = body.get("dst")
    if not isinstance(items, list) or not items or not isinstance(dst_value, str):
        return jsonify({"ok": False, "error": "paths[] and dst required"}), 400
    dst = dst_value.strip()

    try:
        with _file_material_state_scope():
            materials, assignments, page_folders = _load_material_state_checked_locked()
            abs_dst = _safe_join(dst)
            planned_sources: list[tuple[str, pathlib.Path, str]] = []

            for raw_rel in items:
                if not isinstance(raw_rel, str) or not raw_rel.strip():
                    raise ValueError("every source path must be a non-empty string")
                abs_src = _safe_join(raw_rel)
                _reject_root_path(abs_src)
                if not abs_src.exists():
                    raise FileNotFoundError(f"source does not exist: {raw_rel}")
                old_rel = _rel_from_abs(abs_src)
                planned_sources.append((raw_rel, abs_src, old_rel))

            _validate_non_overlapping_sources([item[2] for item in planned_sources])
            for _raw_rel, abs_src, _old_rel in planned_sources:
                if abs_src.parent.resolve() == abs_dst.resolve():
                    raise ValueError("source is already in the destination")
                if abs_src.is_dir() and _is_relative_to(abs_dst, abs_src):
                    raise ValueError("cannot move a folder into itself")

            reserved_names: set[str] = set()
            move_plan: list[tuple[str, pathlib.Path, pathlib.Path, str, str]] = []
            replacements: list[tuple[str, str]] = []
            for raw_rel, abs_src, old_rel in planned_sources:
                target = _planned_move_target(abs_dst, abs_src, reserved_names)
                new_rel = _rel_from_abs(target)
                move_plan.append((raw_rel, abs_src, target, old_rel, new_rel))
                replacements.append((old_rel, new_rel))

            next_state = rewrite_material_file_references(
                materials,
                assignments,
                page_folders,
                replacements,
            )

            plan = _file_plan("move", replacements, directories=_missing_directories(abs_dst))
            with _file_transaction_scope((materials, assignments, page_folders), plan) as transaction_id:
                _create_transaction_directories(plan, abs_dst)
                for _raw_rel, abs_src, target, _old_rel, _new_rel in move_plan:
                    abs_src.rename(target)
                _save_material_state_locked(*next_state, file_transaction_id=transaction_id)

            moved = [
                {"src": raw_rel, "dst": new_rel}
                for raw_rel, _abs_src, _target, _old_rel, new_rel in move_plan
            ]

        return jsonify({"ok": True, "moved": moved})
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except (MaterialStateRecoveryRequiredError, TimeoutError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except Exception as exc:
        print(f"[file-manager] move failed: {exc}", flush=True)
        return jsonify({"ok": False, "error": "move failed"}), 500

@bp_api_fs.post("/api/fs/upload")
def api_fs_upload():
    dst = str(request.form.get("dst") or "").strip()
    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        return jsonify({"ok": False, "error": "no files"}), 400

    out: list[dict] = []
    try:
        with _file_material_state_scope():
            state = _load_material_state_checked_locked()
            materials, assignments, page_folders = state
            abs_dst = _safe_join(dst)
            reserved_names: set[str] = set()
            pairs = [(str(index), _rel_from_abs(abs_dst / _unique_name(abs_dst, uploaded.filename, reserved_names)))
                     for index, uploaded in enumerate(files)]
            plan = _file_plan("upload", pairs, directories=_missing_directories(abs_dst))
            with _file_transaction_scope(state, plan) as transaction_id:
                staging_directory(plan).mkdir(parents=True, exist_ok=False)
                ready = []
                for uploaded, operation in zip(files, plan["operations"]):
                    staged, target = operation_paths(plan, operation)
                    try:
                        uploaded.save(staged)
                        with staged.open("rb+") as handle:
                            os.fsync(handle.fileno())
                        operation["identity"] = entry_identity(staged)
                        ready.append(operation)
                        out.append({"name": target.name, "path": operation["target"],
                                    "url": f'/files/{operation["target"]}'})
                    except Exception as exc:
                        out.append({"name": uploaded.filename, "error": str(exc)})
                plan["operations"] = ready
                _update_file_plan(plan)
                _create_transaction_directories(plan, abs_dst)
                published = []
                for operation in ready:
                    staged, target = operation_paths(plan, operation)
                    try:
                        staged.rename(target)
                        published.append(operation)
                    except Exception as exc:
                        index = int(operation["source"])
                        out[index] = {"name": files[index].filename, "error": str(exc)}
                plan["operations"] = published
                _update_file_plan(plan)
                new_rel_urls = [(str(item["path"]), str(item["url"])) for item in out if not item.get("error")]
                for sid, tokens in list(assignments.items()):
                    if not isinstance(tokens, list):
                        continue
                    directories = [str(token)[4:].lstrip("/").replace("\\", "/")
                                   for token in tokens if str(token).startswith("DIR:")]
                    directories = [directory for directory in directories if directory]
                    token_set = set(map(str, tokens))
                    for relative, url in new_rel_urls:
                        try:
                            in_scope = any(path_is_same_or_descendant(relative, directory) for directory in directories)
                        except ValueError:
                            in_scope = False
                        if in_scope and url not in token_set and relative not in token_set:
                            tokens.append(url)
                            token_set.add(url)
                    assignments[sid] = tokens
                if published:
                    _save_material_state_locked(materials, assignments, page_folders,
                                                file_transaction_id=transaction_id)
        return jsonify({"ok": True, "files": out})
    except ValueError as exc:
        return jsonify({"ok": False, "error": f"invalid dst: {exc}"}), 400
    except (MaterialStateRecoveryRequiredError, TimeoutError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except Exception as exc:
        print(f"[file-manager] upload failed: {exc}", flush=True)
        return jsonify({"ok": False, "error": "upload failed"}), 500


@bp_api_fs.get("/files/<path:fname>")
def files(fname: str):
    if getattr(g, "student_app_public_request", False) is True:
        raw_target = resolve_raw_request_target(request.environ, request.full_path.removesuffix("?"))
        active_sid = getattr(g, "student_app_active_sid", None)
        if not isinstance(active_sid, str) or not active_sid or raw_target is None:
            abort(404)
        if not safe_announcement_file(request.path, raw_target):
            abort(404)
        if not student_can_access_announcement_image_from_store(
            ANNS_PATH, active_sid, fname
        ):
            abort(404)
    try:
        pth = _safe_join(fname)
    except ValueError:
        abort(404)
    if not pth.exists():
        abort(404)
    resp = send_from_directory(FILES_DIR, fname)
    resp.headers.update({
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    })
    return resp
