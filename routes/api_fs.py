from __future__ import annotations

import os
import pathlib
import re
import shutil
from contextlib import contextmanager
from typing import Any, Dict

from flask import Blueprint, abort, jsonify, make_response, request, send_from_directory
from core.material_state import (
    load_material_state,
    load_material_state_locked,
    material_state_lock,
    recover_material_state_locked,
    save_material_state_locked,
)
from core.paths import FILES_DIR, MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH
from core.storage import file_lock, load

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

def _url_for_rel(rel_path: str) -> str:
    rel = rel_path.lstrip("/").replace("\\", "/")
    return f"/files/{rel}"

def _rel_from_url(url: str) -> str | None:
    try:
        u = str(url or "").strip()
        if not u: return None
        if "/files/" in u:
            return u.split("/files/", 1)[1].replace("\\", "/")
        return None
    except Exception:
        return None

def _load_mats_and_assigns():
    mats, assigns, _page_folders = load_material_state_locked(
        MAT_PATH,
        ASN_PATH,
        PAGE_FOLDERS_PATH,
    )
    if not isinstance(mats, dict): mats = {}
    if not isinstance(assigns, dict): assigns = {}
    return mats, assigns

def _save_mats_and_assigns(mats, assigns, page_folders=None):
    if page_folders is None:
        page_folders = _load_page_folders()
    save_material_state_locked(
        MAT_PATH,
        ASN_PATH,
        PAGE_FOLDERS_PATH,
        mats,
        assigns,
        page_folders,
    )


@contextmanager
def _material_state_lock():
    with material_state_lock(MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH):
        recover_material_state_locked(MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH)
        yield


def _load_page_folders() -> dict:
    value = load(PAGE_FOLDERS_PATH)
    return value if isinstance(value, dict) else {}


def _normalize_rel_path(value: Any) -> str:
    return str(value or "").strip().lstrip("/").replace("\\", "/").rstrip("/")


def _replace_rel_prefix(rel_path: Any, old_rel: Any, new_rel: Any) -> str | None:
    rel = _normalize_rel_path(rel_path)
    old = _normalize_rel_path(old_rel)
    new = _normalize_rel_path(new_rel)
    if not rel or not old:
        return None
    if rel == old:
        return new
    prefix = old + "/"
    if rel.startswith(prefix):
        suffix = rel[len(prefix):]
        return f"{new}/{suffix}" if new else suffix
    return None


def _remap_rel_path(rel_path: Any, renames: list[tuple[str, str]]) -> str | None:
    for old_rel, new_rel in renames:
        remapped = _replace_rel_prefix(rel_path, old_rel, new_rel)
        if remapped is not None:
            return remapped
    return None


def _rewrite_path_references(mats, assigns, page_folders, renames) -> None:
    normalized_renames = [
        (_normalize_rel_path(old), _normalize_rel_path(new))
        for old, new in renames
        if _normalize_rel_path(old)
    ]
    if not normalized_renames:
        return

    for mid, meta in list(mats.items()):
        if not isinstance(meta, dict):
            continue
        rel = _rel_from_url(meta.get("url"))
        remapped = _remap_rel_path(rel, normalized_renames) if rel is not None else None
        if remapped is not None:
            next_meta = dict(meta)
            next_meta["url"] = _url_for_rel(remapped)
            mats[mid] = next_meta

    for sid, values in list(assigns.items()):
        if not isinstance(values, list):
            continue
        next_values = []
        seen = set()
        for value in values:
            raw = str(value)
            prefix = ""
            rel = None
            if raw.startswith("DIR:"):
                prefix = "DIR:"
                rel = raw[4:]
            else:
                url_rel = _rel_from_url(raw)
                if url_rel is not None:
                    prefix = "/files/"
                    rel = url_rel
                else:
                    rel = raw
            remapped = _remap_rel_path(rel, normalized_renames) if rel is not None else None
            if remapped is None:
                next_value = value
            elif prefix == "DIR:":
                next_value = f"DIR:{remapped}"
            elif prefix == "/files/":
                next_value = _url_for_rel(remapped)
            else:
                next_value = remapped
            dedupe_key = str(next_value)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            next_values.append(next_value)
        assigns[sid] = next_values

    for key, value in list(page_folders.items()):
        remapped = _remap_rel_path(value, normalized_renames)
        if remapped is not None:
            page_folders[key] = remapped


def _rel_is_deleted(rel_path: Any, deleted_roots: set[str]) -> bool:
    rel = _normalize_rel_path(rel_path)
    if not rel:
        return False
    return any(rel == root or rel.startswith(root + "/") for root in deleted_roots)


def _prune_deleted_references(mats, assigns, page_folders, deleted_paths) -> None:
    deleted_roots = {
        _normalize_rel_path(value)
        for value in deleted_paths
        if _normalize_rel_path(value)
    }
    if not deleted_roots:
        return

    removed_ids = set()
    for mid, meta in list(mats.items()):
        rel = _rel_from_url(meta.get("url")) if isinstance(meta, dict) else None
        if rel is not None and _rel_is_deleted(rel, deleted_roots):
            removed_ids.add(str(mid))
            mats.pop(mid, None)

    for sid, values in list(assigns.items()):
        if not isinstance(values, list):
            continue
        next_values = []
        for value in values:
            raw = str(value)
            if raw in removed_ids:
                continue
            if raw.startswith("DIR:"):
                rel = raw[4:]
            else:
                rel = _rel_from_url(raw)
                if rel is None:
                    rel = raw
            if rel is not None and _rel_is_deleted(rel, deleted_roots):
                continue
            next_values.append(value)
        assigns[sid] = next_values

    for key, value in list(page_folders.items()):
        if _rel_is_deleted(value, deleted_roots):
            page_folders[key] = ""

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
        with file_lock(MAT_PATH):
            _ensure_dir(path)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@bp_api_fs.post("/api/fs/rename")
def api_fs_rename():
    body = request.get_json(force=True) or {}
    src = (body.get("src") or "").strip()
    new_name = (body.get("new_name") or "").strip()
    if not src or not new_name:
        return jsonify({"ok": False, "error": "src/new_name required"}), 400
    try:
        with _material_state_lock():
            abs_src = _safe_join(src)
            _reject_root_path(abs_src)
            abs_dst = abs_src.parent / _clean_filename(new_name)
            if abs_dst.exists():
                return jsonify({"ok": False, "error": "already exists"}), 400
            abs_src.rename(abs_dst)

            old_rel = _normalize_rel_path(src)
            new_rel = _rel_from_abs(abs_dst)
            mats, assigns = _load_mats_and_assigns()
            page_folders = _load_page_folders()
            _rewrite_path_references(mats, assigns, page_folders, [(old_rel, new_rel)])
            _save_mats_and_assigns(mats, assigns, page_folders)

        return jsonify({"ok": True, "path": new_rel})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@bp_api_fs.post("/api/fs/delete")
def api_fs_delete():
    body = request.get_json(force=True) or {}
    items = body.get("paths") or []
    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "error": "paths[] required"}), 400

    deleted, errors = [], []
    rel_set = set()

    with _material_state_lock():
        for rel in items:
            try:
                abs_p = _safe_join(rel)
                _reject_root_path(abs_p)
                if abs_p.is_dir():
                    shutil.rmtree(abs_p)
                elif abs_p.exists():
                    abs_p.unlink()
                deleted.append(rel)
                rel_set.add(_normalize_rel_path(rel))
            except Exception as e:
                errors.append({"path": rel, "error": str(e)})

        if rel_set:
            mats, assigns = _load_mats_and_assigns()
            page_folders = _load_page_folders()
            _prune_deleted_references(mats, assigns, page_folders, rel_set)
            _save_mats_and_assigns(mats, assigns, page_folders)

    return jsonify({"ok": True, "deleted": deleted, "errors": errors})

@bp_api_fs.post("/api/fs/move")
def api_fs_move():
    body = request.get_json(force=True) or {}
    items = body.get("paths") or []
    dst   = (body.get("dst") or "").strip()
    if not isinstance(items, list) or not items or not dst:
        return jsonify({"ok": False, "error": "paths[] and dst required"}), 400
    try:
        with _material_state_lock():
            abs_dst = _ensure_dir(dst)
            moved = []
            renames: list[tuple[str, str]] = []

            for rel in items:
                abs_src = _safe_join(rel)
                _reject_root_path(abs_src)
                target = abs_dst / abs_src.name
                if target.exists():
                    if abs_src.is_file():
                        target = abs_dst / _unique_name(abs_dst, abs_src.name)
                    else:
                        base = abs_src.name
                        i = 1
                        new = base
                        while (abs_dst / new).exists():
                            new = f"{base} ({i})"
                            i += 1
                        target = abs_dst / new
                if abs_src.is_dir() and _is_relative_to(target, abs_src):
                    raise ValueError("cannot move a folder into itself")
                shutil.move(str(abs_src), str(target))
                old_rel = _normalize_rel_path(rel)
                new_rel = _rel_from_abs(target)
                moved.append({"src": rel, "dst": new_rel})
                renames.append((old_rel, new_rel))

            if renames:
                mats, assigns = _load_mats_and_assigns()
                page_folders = _load_page_folders()
                _rewrite_path_references(mats, assigns, page_folders, renames)
                _save_mats_and_assigns(mats, assigns, page_folders)

        return jsonify({"ok": True, "moved": moved})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@bp_api_fs.post("/api/fs/upload")
def api_fs_upload():
    dst = (request.form.get("dst") or "").strip()
    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        return jsonify({"ok": False, "error": "no files"}), 400

    out = []
    try:
        with _material_state_lock():
            try:
                abs_dst = _ensure_dir(dst)
            except Exception as exc:
                return jsonify({"ok": False, "error": f"invalid dst: {exc}"}), 400

            for f in files:
                try:
                    fname = _unique_name(abs_dst, f.filename)
                    f.save(abs_dst / fname)
                    rel = (pathlib.Path(dst) / fname).as_posix() if dst else fname
                    out.append({"name": fname, "path": rel, "url": f"/files/{rel}"})
                except Exception as exc:
                    out.append({"name": f.filename, "error": str(exc)})

            new_rel_urls = []
            for item in out:
                if item.get("error"):
                    continue
                rel = _normalize_rel_path(item["path"])
                new_rel_urls.append((rel, _url_for_rel(rel)))

            if new_rel_urls:
                try:
                    _mats, assigns = _load_mats_and_assigns()
                    changed = False

                    for sid, arr in list(assigns.items()):
                        if not isinstance(arr, list):
                            continue
                        dir_tokens = [
                            _normalize_rel_path(str(value)[4:])
                            for value in arr
                            if str(value).startswith("DIR:") and _normalize_rel_path(str(value)[4:])
                        ]
                        if not dir_tokens:
                            continue
                        arr_set = set(map(str, arr))
                        for rel, url in new_rel_urls:
                            in_scope = any(rel == directory or rel.startswith(directory + "/") for directory in dir_tokens)
                            if in_scope and url not in arr_set and rel not in arr_set:
                                arr.append(url)
                                arr_set.add(url)
                                changed = True
                        assigns[sid] = arr

                    if changed:
                        _save_mats_and_assigns(
                            _mats,
                            assigns,
                            _load_page_folders(),
                        )
                except Exception as exc:
                    print("[auto-assign DIR] error:", exc, flush=True)
    except TimeoutError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "files": out})

@bp_api_fs.get("/api/fs/page-folders")
def api_fs_get_page_folders():
    _mats, _assigns, page_folders = load_material_state(
        MAT_PATH,
        ASN_PATH,
        PAGE_FOLDERS_PATH,
    )
    return jsonify(page_folders)

@bp_api_fs.post("/api/fs/page-folders")
def api_fs_set_page_folders():
    body = request.get_json(force=True) or {}
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "dict required"}), 400
    for k, v in list(body.items()):
        if v:
            try:
                _safe_join(v)
            except Exception:
                body[k] = ""
    with _material_state_lock():
        mats, assigns = _load_mats_and_assigns()
        _save_mats_and_assigns(mats, assigns, body)
    return jsonify({"ok": True})

@bp_api_fs.get("/files/<path:fname>")
def files(fname: str):
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
