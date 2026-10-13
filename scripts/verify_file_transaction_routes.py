"""Temp actual-route boundaries for filesystem/material journal recovery."""
from __future__ import annotations

import io
import json
import logging
import pathlib
import sys
import tempfile
import threading
from contextlib import contextmanager
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_file_transaction_crash import (
    CRASH_EXIT, STORE_NAMES, check, expected_after, fixture, install_paths, invoke,
    staging_paths, store_fingerprint, tree_content,
)


def post_operation(client, operation):
    if operation == "rename":
        return client.post("/api/fs/rename", json={"src": "교재", "new_name": "수학 교재"})
    if operation == "move":
        return client.post("/api/fs/move", json={"paths": ["교재", "루트.txt"], "dst": "보관"})
    if operation == "delete":
        return client.post("/api/fs/delete", json={"paths": ["교재", "루트.txt"]})
    return client.post("/api/fs/upload", data={"dst": "교재/신규", "files": [
        (io.BytesIO(b"first-upload"), "첫째.pdf"), (io.BytesIO(b"second-upload"), "둘째.pdf"),
    ]}, content_type="multipart/form-data")


@contextmanager
def route_fixture():
    with tempfile.TemporaryDirectory(prefix="file-transaction-routes-") as temporary:
        root = pathlib.Path(temporary)
        state, content = fixture(root)
        install_paths(root)
        from flask import Flask
        from routes import api_fs, api_materials
        app = Flask("verify-file-transaction-boundary")
        app.logger.setLevel(logging.CRITICAL)
        app.register_blueprint(api_fs.bp_api_fs)
        app.register_blueprint(api_materials.bp_api_materials)
        common = {"MAT_PATH": root / STORE_NAMES[0], "ASN_PATH": root / STORE_NAMES[1],
                  "PAGE_FOLDERS_PATH": root / STORE_NAMES[2]}
        with patch.multiple(api_fs, **common, FILES_DIR=root / "files", FILES_ROOT=(root / "files").resolve()):
            with patch.multiple(api_materials, **common):
                yield root, state, content, app.test_client(), api_fs, app


def read_state(root):
    return tuple(json.loads((root / name).read_text(encoding="utf-8")) for name in STORE_NAMES)


def assert_clean(root):
    check(not (root / "material_state_transaction.json").exists(), "successful boundary must clear its journal")
    check(not staging_paths(root), "successful boundary must clean its staging")


def run_route_matrix():
    logging.getLogger("core.storage").setLevel(logging.ERROR)
    cases = 0
    for operation in ("rename", "move", "delete", "upload"):
        with route_fixture() as (root, state, content, client, api_fs, _app):
            original = store_fingerprint(root)
            def before_commit(*_args, **_kwargs):
                raise RuntimeError("injected pre-commit failure")
            with patch.object(api_fs, "_save_material_state_locked", before_commit):
                response = post_operation(client, operation)
            check(response.status_code == 500, f"{operation}: pre-commit exception must surface")
            check(store_fingerprint(root) == original and tree_content(root) == content,
                  f"{operation}: synchronous pre-commit failure must restore exact files and JSON bytes")
            assert_clean(root)
            cases += 1

        for failure_type in (RuntimeError, "recovery-required"):
            with route_fixture() as (root, state, content, client, _api_fs, _app):
                import core.material_state as material_state
                original_save = material_state.save_atomic
                calls = 0
                def fail_second(path, value, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        error = (material_state.MaterialStateRecoveryRequiredError
                                 if failure_type == "recovery-required" else failure_type)
                        raise error("injected committed second-store failure")
                    original_save(path, value, **kwargs)
                with patch.object(material_state, "save_atomic", fail_second):
                    response = post_operation(client, operation)
                check(response.status_code == (503 if failure_type == "recovery-required" else 500),
                      f"{operation}: committed error status must remain classified")
                check((root / "material_state_transaction.json").exists(), "committed failure must retain forward intent")
                expected_state, expected_files = expected_after(operation, state, content)
                check(tree_content(root) == expected_files, "committed failure must not undo filesystem changes")
                materials = client.get("/api/materials")
                assignments = client.get("/api/mat-assign")
                check(materials.status_code == 200 and materials.get_json() == expected_state[0],
                      "material GET must finish pending file/metadata commit")
                check(assignments.status_code == 200 and assignments.get_json() == expected_state[1]
                      and assignments.headers["X-Material-State-Revision"] == materials.headers["X-Material-State-Revision"],
                      "both GETs must expose a coherent recovered revision")
                check(read_state(root) == expected_state and tree_content(root) == expected_files,
                      "read recovery must converge to the independent literal state")
                assert_clean(root)
                cases += 1

        for damaged in ("store", "journal"):
            with route_fixture() as (root, _state, content, client, _api_fs, _app):
                source = root / (STORE_NAMES[0] if damaged == "store" else "material_state_transaction.json")
                source.write_text("{damaged", encoding="utf-8")
                original = store_fingerprint(root)
                journal = source.read_bytes()
                response = post_operation(client, operation)
                check(response.status_code == 503, f"{operation}: damaged {damaged} must block writes")
                check(store_fingerprint(root) == original and tree_content(root) == content and source.read_bytes() == journal,
                      "damaged state must preserve exact JSON, journal, and file bytes")
                cases += 1

    for operation in ("rename", "move", "delete", "upload"):
        with route_fixture() as (root, state, content, client, api_fs, _app):
            original = store_fingerprint(root)
            original_save = api_fs._save_material_state_locked
            def corrupt_before_commit(*args, **kwargs):
                (root / STORE_NAMES[0]).write_text("{damaged-after-intent", encoding="utf-8")
                return original_save(*args, **kwargs)
            with patch.object(api_fs, "_save_material_state_locked", corrupt_before_commit):
                response = post_operation(client, operation)
            check(response.status_code == 503, "store corruption after intent must still block commit")
            check((root / STORE_NAMES[0]).read_bytes() == b"{damaged-after-intent"
                  and all(store_fingerprint(root)[name] == original[name] for name in STORE_NAMES[1:])
                  and tree_content(root) == content,
                  "late corruption must preserve damaged bytes, untouched siblings, and original files")
            assert_clean(root)
            read = client.get("/api/materials")
            check(read.status_code == 200 and read.headers.get("X-Material-State-Degraded") == "1"
                  and read.get_json() == state[0], "late store corruption must retain last-good read availability")
            cases += 1

    for phase_fault in ("before-commit", "store-1"):
        for boundary in ("/api/fs/tree", "/api/materials", "/api/mat-assign"):
            with route_fixture() as (root, state, content, client, _api_fs, _app):
                invoke(root, "--worker", "move", phase_fault, expected_exit=CRASH_EXIT)
                response = client.get(boundary)
                check(response.status_code == 200, "ordinary GET must recover a pending file transaction")
                expected_state, expected_files = (state, content) if phase_fault == "before-commit" else expected_after("move", state, content)
                check(read_state(root) == expected_state and tree_content(root) == expected_files,
                      "tree/material read boundary must apply the prepared-versus-committed policy")
                assert_clean(root)
                cases += 1

    with route_fixture() as (root, state, content, client, _api_fs, _app):
        original_rename = pathlib.Path.rename
        def refuse_root_file(path, target):
            if path == root / "files" / "루트.txt":
                raise PermissionError("injected single delete failure")
            return original_rename(path, target)
        with patch.object(pathlib.Path, "rename", refuse_root_file):
            response = post_operation(client, "delete")
        check(response.status_code == 200 and response.get_json()["deleted"] == ["교재"]
              and len(response.get_json()["errors"]) == 1, "delete must retain per-item partial success")
        expected_state, expected_files = expected_after("delete", state, content)
        expected_files["루트.txt"] = content["루트.txt"]
        check(read_state(root) == expected_state and tree_content(root) == expected_files,
              "delete must remove only successful references/files")
        assert_clean(root)
        cases += 1

    with route_fixture() as (root, state, content, client, _api_fs, _app):
        from werkzeug.datastructures import FileStorage
        original_save = FileStorage.save
        def fail_partial_stream(uploaded, destination, *args, **kwargs):
            if uploaded.filename == "첫째.pdf":
                pathlib.Path(destination).write_bytes(b"partial-failure")
                raise OSError("injected partial upload")
            return original_save(uploaded, destination, *args, **kwargs)
        with patch.object(FileStorage, "save", fail_partial_stream):
            response = post_operation(client, "upload")
        payload = response.get_json()
        check(response.status_code == 200 and "error" in payload["files"][0] and "error" not in payload["files"][1],
              "upload must retain per-file partial success")
        expected_state, expected_files = expected_after("upload", state, content)
        expected_state[1]["s1"].remove("/files/교재/신규/첫째.pdf")
        del expected_files["교재/신규/첫째.pdf"]
        check(read_state(root) == expected_state and tree_content(root) == expected_files,
              "failed partial upload must publish no file and create no assignment")
        assert_clean(root)
        cases += 1

    for fault in ("before-commit", "none"):
        with route_fixture() as (root, state, content, client, _api_fs, _app):
            # An upload still needs a filesystem commit when no DIR assignment matches.
            for name, value in zip(STORE_NAMES, state):
                if name == "mat_assign.json":
                    value["s1"] = ["a", {"opaque": "keep"}]
                    (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            original = store_fingerprint(root)
            invoke(root, "--worker", "upload", fault, expected_exit=CRASH_EXIT if fault != "none" else 0)
            client.get("/api/materials")
            check(read_state(root) == state, "upload without DIR membership must preserve every metadata field")
            expected_files = content if fault == "before-commit" else expected_after("upload", state, content)[1]
            check(tree_content(root) == expected_files, "upload without DIR membership must recover/publish exact files")
            if fault == "before-commit":
                check(store_fingerprint(root) == original, "prepared unassigned upload must preserve JSON bytes")
            assert_clean(root)
            cases += 1

    for modification in ("malformed", "root", "stores", "traversal", "identity", "phase"):
        with route_fixture() as (root, state, content, client, _api_fs, _app):
            invoke(root, "--worker", "rename", "before-commit", expected_exit=CRASH_EXIT)
            journal = root / "material_state_transaction.json"
            payload = json.loads(journal.read_text(encoding="utf-8"))
            if modification == "malformed":
                journal.write_text("{malformed", encoding="utf-8")
            else:
                if modification == "root":
                    payload["fileTransaction"]["filesRoot"] = str(root.parent)
                elif modification == "stores":
                    payload["fileTransaction"]["stores"][0] = str(root / "other.json")
                elif modification == "traversal":
                    payload["fileTransaction"]["operations"][0]["target"] = "../outside"
                elif modification == "identity":
                    # Retain the original inode elsewhere, so replacement cannot reuse it.
                    (root / "files" / "수학 교재").rename(root / "original-preserved")
                    (root / "files" / "수학 교재").mkdir()
                    (root / "files" / "수학 교재" / "alien.txt").write_bytes(b"unrelated-content")
                else:
                    payload["phase"] = []
                journal.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            original, files_before, intent = store_fingerprint(root), tree_content(root), journal.read_bytes()
            read = client.get("/api/materials")
            check(read.status_code == 200 and read.headers.get("X-Material-State-Degraded") == "1"
                  and read.get_json() == state[0], "invalid/conflicting file intent must use last-good read")
            for operation in ("rename", "move", "delete", "upload"):
                check(post_operation(client, operation).status_code == 503, "invalid/conflicting file intent must block every writer")
            assignments = client.get("/api/mat-assign")
            write = client.post("/api/mat-assign", json={"overwrite": []},
                                headers={"If-Match": assignments.headers["X-Material-State-Revision"]})
            check(write.status_code == 503, "invalid file intent must also block material component replacement")
            check(store_fingerprint(root) == original and tree_content(root) == files_before and journal.read_bytes() == intent,
                  "degraded reads/blocked writes must preserve all primary, journal, and unrelated file bytes")
            cases += 1

    with route_fixture() as (root, state, _content, client, _api_fs, app):
        from core.storage import file_lock
        started, finished = threading.Event(), threading.Event()
        replies, errors = [], []
        def reader():
            try:
                started.set()
                replies.append(app.test_client().get("/api/materials"))
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()
        with file_lock(root / "files"):
            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            check(started.wait(2), "material reader must start")
            check(not finished.wait(0.15), "material read must wait on an externally held file-tree lease")
            check(not any((root / (name + ".lock")).exists() for name in STORE_NAMES),
                  "reader may not acquire metadata locks before the file-tree lock")
        thread.join(timeout=3)
        check(not thread.is_alive() and not errors and replies[0].status_code == 200 and replies[0].get_json() == state[0],
              "blocked material reader must finish normally after the file-tree lease is released")
        cases += 1

    print(f"PASS file transaction route boundaries: {cases} fixture scenarios")
    return cases


def main():
    run_route_matrix()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
