from __future__ import annotations

import os
import pathlib
import re
import shutil
import uuid
from contextlib import contextmanager
from typing import Iterator

from flask import Blueprint, abort, g, jsonify, make_response, request, send_from_directory

from core.announcement_image_access import student_can_access_announcement_image_from_store
from core.material_reference_rules import (
    path_is_same_or_descendant,
    remove_material_file_references,
    rewrite_material_file_references,
)
from core.material_state import (
    MaterialStateRecoveryRequiredError,
    load_material_state_locked,
    material_state_journal_path,
    material_state_lock,
    save_material_state_locked,
)
from core.paths import ANNS_PATH, FILES_DIR, MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH
from core.student_public_surface_paths import resolve_raw_request_target, safe_announcement_file
from core.storage import file_lock

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
    with file_lock(FILES_DIR):
        with material_state_lock(MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH):
            yield


def _load_material_state_checked_locked() -> tuple[dict, dict, dict]:
    materials, assignments, page_folders = load_material_state_locked(
        MAT_PATH,
        ASN_PATH,
        PAGE_FOLDERS_PATH,
    )
    if not isinstance(materials, dict):
        raise RuntimeError("materials store must be an object")
    if not isinstance(assignments, dict):
        raise RuntimeError("assignments store must be an object")
    if not isinstance(page_folders, dict):
        raise RuntimeError("pageFolders store must be an object")
    return materials, assignments, page_folders


def _save_material_state_locked(
    materials: dict,
    assignments: dict,
    page_folders: dict,
) -> None:
    save_material_state_locked(
        MAT_PATH,
        ASN_PATH,
        PAGE_FOLDERS_PATH,
        materials,
        assignments,
        page_folders,
    )


def _material_commit_started() -> bool:
    return material_state_journal_path(MAT_PATH).exists()


def _rollback_completed_moves(completed: list[tuple[pathlib.Path, pathlib.Path]]) -> None:
    for source, target in reversed(completed):
        try:
            if target.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
        except Exception as exc:
            print(f"[file-manager] rollback failed: {target} -> {source}: {exc}", flush=True)


def _remove_staging_dir(path: pathlib.Path | None) -> None:
    if path is None:
        return
    try:
        if path.exists():
            shutil.rmtree(path)
    except Exception as exc:
        print(f"[file-manager] staging cleanup failed: {path}: {exc}", flush=True)


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


def _unique_name(dst_dir: pathlib.Path, filename: str) -> str:
    base = _clean_filename(filename)
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    name = base
    i = 1
    while (dst_dir / name).exists():
        suffix = f" ({i})"
        name = f"{stem}{suffix}.{ext}" if ext else f"{stem}{suffix}"
        i += 1
    return name

# 트리 조회
@bp_api_fs.get("/api/fs/tree")
def api_fs_tree():
    with file_lock(FILES_DIR):
        tree = _scan_tree()
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

            abs_src.rename(abs_dst)
            try:
                _save_material_state_locked(*next_state)
            except Exception:
                if not _material_commit_started():
                    _rollback_completed_moves([(abs_src, abs_dst)])
                raise

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
    staging_dir: pathlib.Path | None = None
    staged_moves: list[tuple[pathlib.Path, pathlib.Path]] = []

    try:
        with _file_material_state_scope():
            materials, assignments, page_folders = _load_material_state_checked_locked()
            deleted_prefixes: list[str] = []

            for raw_rel in items:
                try:
                    if not isinstance(raw_rel, str) or not raw_rel.strip():
                        raise ValueError("path must be a non-empty string")
                    abs_path = _safe_join(raw_rel)
                    _reject_root_path(abs_path)
                    canonical_rel = _rel_from_abs(abs_path)

                    if abs_path.exists():
                        if staging_dir is None:
                            staging_dir = (
                                pathlib.Path(FILES_DIR).parent
                                / f".file-delete-stage-{uuid.uuid4().hex}"
                            )
                            staging_dir.mkdir(parents=True, exist_ok=False)
                        staged_path = staging_dir / str(len(staged_moves))
                        shutil.move(str(abs_path), str(staged_path))
                        staged_moves.append((abs_path, staged_path))

                    deleted.append(raw_rel)
                    deleted_prefixes.append(canonical_rel)
                except Exception as exc:
                    errors.append({"path": raw_rel, "error": str(exc)})

            if deleted_prefixes:
                try:
                    next_state = remove_material_file_references(
                        materials,
                        assignments,
                        page_folders,
                        deleted_prefixes,
                    )
                    _save_material_state_locked(*next_state)
                except Exception:
                    if not _material_commit_started():
                        _rollback_completed_moves(staged_moves)
                    raise

            _remove_staging_dir(staging_dir)

        return jsonify({"ok": True, "deleted": deleted, "errors": errors})
    except (MaterialStateRecoveryRequiredError, TimeoutError) as exc:
        _rollback_completed_moves(staged_moves)
        _remove_staging_dir(staging_dir)
        return jsonify({"ok": False, "error": str(exc)}), 503
    except Exception as exc:
        if _material_commit_started():
            # The journal contains the forward state; startup/next mutation can
            # finish it, so staged deleted content must not be restored.
            _remove_staging_dir(staging_dir)
        else:
            _rollback_completed_moves(staged_moves)
            _remove_staging_dir(staging_dir)
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

    completed_moves: list[tuple[pathlib.Path, pathlib.Path]] = []
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

            abs_dst.mkdir(parents=True, exist_ok=True)
            try:
                for _raw_rel, abs_src, target, _old_rel, _new_rel in move_plan:
                    shutil.move(str(abs_src), str(target))
                    completed_moves.append((abs_src, target))
            except Exception:
                _rollback_completed_moves(completed_moves)
                raise

            try:
                _save_material_state_locked(*next_state)
            except Exception:
                if not _material_commit_started():
                    _rollback_completed_moves(completed_moves)
                raise

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
    uploaded_paths: list[pathlib.Path] = []
    try:
        with _file_material_state_scope():
            materials, assignments, page_folders = _load_material_state_checked_locked()
            abs_dst = _ensure_dir(dst)

            for uploaded_file in files:
                try:
                    filename = _unique_name(abs_dst, uploaded_file.filename)
                    target = abs_dst / filename
                    uploaded_file.save(target)
                    uploaded_paths.append(target)
                    relative = _rel_from_abs(target)
                    out.append({
                        "name": filename,
                        "path": relative,
                        "url": f"/files/{relative}",
                    })
                except Exception as exc:
                    out.append({"name": uploaded_file.filename, "error": str(exc)})

            new_rel_urls = [
                (str(item["path"]), str(item["url"]))
                for item in out
                if not item.get("error")
            ]
            assignments_changed = False
            if new_rel_urls:
                for sid, tokens in list(assignments.items()):
                    if not isinstance(tokens, list):
                        continue

                    directory_tokens: list[str] = []
                    for token in tokens:
                        text_token = str(token)
                        if not text_token.startswith("DIR:"):
                            continue
                        directory = text_token[4:].lstrip("/").replace("\\", "/")
                        if directory:
                            directory_tokens.append(directory)
                    if not directory_tokens:
                        continue

                    token_set = set(map(str, tokens))
                    for relative, url in new_rel_urls:
                        try:
                            in_scope = any(
                                path_is_same_or_descendant(relative, directory)
                                for directory in directory_tokens
                            )
                        except ValueError:
                            in_scope = False
                        if not in_scope or url in token_set or relative in token_set:
                            continue
                        tokens.append(url)
                        token_set.add(url)
                        assignments_changed = True

                    assignments[sid] = tokens

            if assignments_changed:
                _save_material_state_locked(materials, assignments, page_folders)

        return jsonify({"ok": True, "files": out})
    except ValueError as exc:
        for uploaded_path in uploaded_paths:
            try:
                uploaded_path.unlink(missing_ok=True)
            except OSError:
                pass
        return jsonify({"ok": False, "error": f"invalid dst: {exc}"}), 400
    except (MaterialStateRecoveryRequiredError, TimeoutError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except Exception as exc:
        if not _material_commit_started():
            for uploaded_path in uploaded_paths:
                try:
                    uploaded_path.unlink(missing_ok=True)
                except OSError:
                    pass
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
