from __future__ import annotations

import os
import pathlib
import re
import shutil
from typing import Any, Dict

from flask import Blueprint, abort, jsonify, make_response, request, send_from_directory
from werkzeug.utils import secure_filename

from core.paths import FILES_DIR, MAT_PATH, ASN_PATH, PAGE_FOLDERS_PATH
from core.storage import load, save_atomic

bp_api_fs = Blueprint("api_fs", __name__)

def json_or_form() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    if request.form:
        data.update({k: v for k, v in request.form.items()})
    return data

def _safe_join(rel_path: str) -> pathlib.Path:
    p = (FILES_DIR / rel_path).resolve()
    if not str(p).startswith(str(FILES_DIR.resolve())):
        raise ValueError("unsafe path")
    return p

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
    mats = load(MAT_PATH)
    if not isinstance(mats, dict): mats = {}
    assigns = load(ASN_PATH)
    if not isinstance(assigns, dict): assigns = {}
    return mats, assigns

def _save_mats_and_assigns(mats, assigns):
    save_atomic(MAT_PATH, mats)
    save_atomic(ASN_PATH, assigns)

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
        abs_src = _safe_join(src)
        abs_dst = abs_src.parent / secure_filename(new_name)
        if abs_dst.exists():
            return jsonify({"ok": False, "error": "already exists"}), 400
        abs_src.rename(abs_dst)

        old_rel = src.replace("\\", "/")
        new_rel = _rel_from_abs(abs_dst)

        mats, assigns = _load_mats_and_assigns()
        old_url = _url_for_rel(old_rel)
        new_url = _url_for_rel(new_rel)

        for mid, meta in list(mats.items()):
            if isinstance(meta, dict) and meta.get("url") == old_url:
                meta["url"] = new_url
                mats[mid] = meta

        for sid, arr in list(assigns.items()):
            if not isinstance(arr, list):
                continue
            changed = False
            for i, v in enumerate(arr):
                sval = str(v)
                if sval == old_url:
                    arr[i] = new_url; changed = True
                elif sval.lstrip("/").replace("\\", "/") == old_rel:
                    arr[i] = new_rel; changed = True
            if changed:
                assigns[sid] = arr

        _save_mats_and_assigns(mats, assigns)

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

    for rel in items:
        try:
            abs_p = _safe_join(rel)
            if abs_p.is_dir():
                shutil.rmtree(abs_p)
            elif abs_p.exists():
                abs_p.unlink()
            deleted.append(rel)
            rel_set.add(rel.replace("\\", "/"))
        except Exception as e:
            errors.append({"path": rel, "error": str(e)})

    if rel_set:
        mats, assigns = _load_mats_and_assigns()

        ids_to_remove = []
        for mid, meta in list(mats.items()):
            url = (meta or {}).get("url")
            rel = _rel_from_url(url)
            if rel and rel in rel_set:
                ids_to_remove.append(str(mid))

        for mid in ids_to_remove:
            mats.pop(mid, None)

        for sid, arr in list(assigns.items()):
            if not isinstance(arr, list):
                continue
            new_arr = []
            for v in arr:
                sval = str(v)
                if sval in ids_to_remove:
                    continue
                rel = _rel_from_url(sval) or sval.lstrip("/").replace("\\", "/")
                if rel in rel_set:
                    continue
                new_arr.append(v)
            assigns[sid] = new_arr

        _save_mats_and_assigns(mats, assigns)

    return jsonify({"ok": True, "deleted": deleted, "errors": errors})

@bp_api_fs.post("/api/fs/move")
def api_fs_move():
    body = request.get_json(force=True) or {}
    items = body.get("paths") or []
    dst   = (body.get("dst") or "").strip()
    if not items or not dst:
        return jsonify({"ok": False, "error": "paths[] and dst required"}), 400
    try:
        abs_dst = _ensure_dir(dst)
        moved = []
        renames: list[tuple[str, str]] = []

        for rel in items:
            abs_src = _safe_join(rel)
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
            shutil.move(str(abs_src), str(target))
            old_rel = rel.replace("\\", "/")
            new_rel = _rel_from_abs(target)
            moved.append({"src": rel, "dst": new_rel})
            renames.append((old_rel, new_rel))

        if renames:
            mats, assigns = _load_mats_and_assigns()
            for old_rel, new_rel in renames:
                old_url = _url_for_rel(old_rel)
                new_url = _url_for_rel(new_rel)

                for mid, meta in list(mats.items()):
                    if isinstance(meta, dict) and meta.get("url") == old_url:
                        meta["url"] = new_url
                        mats[mid] = meta

                for sid, arr in list(assigns.items()):
                    if not isinstance(arr, list):
                        continue
                    changed = False
                    for i, v in enumerate(arr):
                        sval = str(v)
                        if sval == old_url:
                            arr[i] = new_url; changed = True
                        elif sval.lstrip("/").replace("\\", "/") == old_rel:
                            arr[i] = new_rel; changed = True
                    if changed:
                        assigns[sid] = arr

            _save_mats_and_assigns(mats, assigns)

        return jsonify({"ok": True, "moved": moved})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@bp_api_fs.post("/api/fs/upload")
def api_fs_upload():
    dst = (request.form.get("dst") or "").strip()
    try:
        abs_dst = _ensure_dir(dst)
    except Exception as e:
        return jsonify({"ok": False, "error": f"invalid dst: {e}"}), 400

    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        return jsonify({"ok": False, "error": "no files"}), 400

    out = []
    for f in files:
        try:
            fname = _unique_name(abs_dst, f.filename)
            f.save(abs_dst / fname)
            rel = (pathlib.Path(dst) / fname).as_posix() if dst else fname
            out.append({"name": fname, "path": rel, "url": f"/files/{rel}"})
        except Exception as e:
            out.append({"name": f.filename, "error": str(e)})

    try:
        new_rel_urls = []
        for it in out:
            if it.get("error"):
                continue
            rel = str(it["path"]).lstrip("/").replace("\\", "/")
            url = f"/files/{rel}"
            new_rel_urls.append((rel, url))

        if new_rel_urls:
            mats, assigns = _load_mats_and_assigns()
            changed = False

            for sid, arr in list(assigns.items()):
                if not isinstance(arr, list):
                    continue

                dir_tokens = []
                for v in arr:
                    s = str(v)
                    if s.startswith("DIR:"):
                        d = s[4:].lstrip("/").replace("\\", "/")
                        if d:
                            dir_tokens.append(d)
                if not dir_tokens:
                    continue

                arr_set = set(map(str, arr))
                for rel, url in new_rel_urls:
                    in_scope = any(rel == d or rel.startswith(d + "/") for d in dir_tokens)
                    if not in_scope:
                        continue
                    if (url not in arr_set) and (rel not in arr_set):
                        arr.append(url)
                        arr_set.add(url)
                        changed = True

                assigns[sid] = arr

            if changed:
                save_atomic(ASN_PATH, assigns)
    except Exception as e:
        print("[auto-assign DIR] error:", e, flush=True)

    return jsonify({"ok": True, "files": out})

@bp_api_fs.get("/api/fs/page-folders")
def api_fs_get_page_folders():
    return jsonify(load(PAGE_FOLDERS_PATH))

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
    save_atomic(PAGE_FOLDERS_PATH, body)
    return jsonify({"ok": True})

@bp_api_fs.get("/files/<path:fname>")
def files(fname: str):
    pth = FILES_DIR / fname
    if not pth.exists():
        abort(404)
    resp = send_from_directory(FILES_DIR, fname)
    resp.headers.update({
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    })
    return resp
