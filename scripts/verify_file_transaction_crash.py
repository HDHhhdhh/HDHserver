"""OS-temp actual-route/process-crash oracle; never import production paths."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import importlib
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CRASH_EXIT = 86
STORE_NAMES = ("materials.json", "mat_assign.json", "page_folders.json")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def install_paths(root):
    module = types.ModuleType("core.paths")
    for name, path in {
        "BASE": root, "FILES_DIR": root / "files",
        "ANNS_PATH": root / "announcements.json", "MAT_PATH": root / STORE_NAMES[0],
        "ASN_PATH": root / STORE_NAMES[1], "PAGE_FOLDERS_PATH": root / STORE_NAMES[2],
    }.items():
        setattr(module, name, path)
    sys.modules["core.paths"] = module
    os.environ["DATA_MIRROR_DIR"] = str(root / "_data_mirror")
    os.environ["DATA_MIRROR_SNAPSHOTS"] = "0"


def install_baseline_sources(include_routes=False):
    baseline = os.environ.get("FILE_TRANSACTION_BASELINE_SOURCE_ROOT")
    if not baseline:
        return
    names = ("core.material_state", "routes.api_fs") if include_routes else ("core.material_state",)
    plan_path = pathlib.Path(baseline) / "core" / "file_material_transaction.py"
    if plan_path.exists():
        names = ("core.file_material_transaction",) + names
    for name in names:
        package, leaf = name.rsplit(".", 1)
        parent = importlib.import_module(package)
        path = pathlib.Path(baseline) / package / (leaf + ".py")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        setattr(parent, leaf, module)
        spec.loader.exec_module(module)


def fixture(root):
    content = {
        "교재/단원/a.pdf": b"alpha", "교재/단원/b.pdf": b"beta",
        "교재실/keep.pdf": b"sibling", "루트.txt": b"root",
    }
    for relative, value in content.items():
        path = root / "files" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    state = (
        {"a": {"url": "/files/교재/단원/a.pdf?x=1#p", "unknown": {"keep": True}},
         "sibling": {"url": "/files/교재실/keep.pdf"}, "legacy": "keep"},
        {"s1": ["a", "/files/교재/단원/a.pdf", "교재/단원/b.pdf", "DIR:교재",
                "DIR:교재실", {"opaque": "keep"}], "other": {"unknown": True}},
        {"page": "교재/단원", "sibling": "교재실", "opaque": {"keep": True}},
    )
    for name, value in zip(STORE_NAMES, state):
        (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return state, content


def store_fingerprint(root):
    return {name: (len(data), hashlib.sha256(data).hexdigest())
            for name in STORE_NAMES for data in [(root / name).read_bytes()]}


def tree_content(root):
    return {path.relative_to(root / "files").as_posix(): path.read_bytes()
            for path in (root / "files").rglob("*") if path.is_file()}


def staging_paths(root):
    return list(root.glob(".file-*-stage-*")) + list((root / "instance").glob(".file-*-stage-*"))


def expected_after(operation, state, content):
    expected = copy.deepcopy(state)
    files = dict(content)
    if operation in {"rename", "move"}:
        prefix = "수학 교재" if operation == "rename" else "보관/교재"
        expected[0]["a"]["url"] = f"/files/{prefix}/단원/a.pdf?x=1#p"
        expected[1]["s1"] = ["a", f"/files/{prefix}/단원/a.pdf", f"{prefix}/단원/b.pdf",
                               f"DIR:{prefix}", "DIR:교재실", {"opaque": "keep"}]
        expected[2]["page"] = f"{prefix}/단원"
        for name in ("교재/단원/a.pdf", "교재/단원/b.pdf"):
            files[prefix + name[len("교재"):]] = files.pop(name)
        if operation == "move":
            files["보관/루트.txt"] = files.pop("루트.txt")
    elif operation == "delete":
        del expected[0]["a"]
        expected[1]["s1"] = ["DIR:교재실", {"opaque": "keep"}]
        expected[2]["page"] = ""
        for name in ("교재/단원/a.pdf", "교재/단원/b.pdf", "루트.txt"):
            del files[name]
    elif operation == "upload":
        files["교재/신규/첫째.pdf"] = b"first-upload"
        files["교재/신규/둘째.pdf"] = b"second-upload"
        expected[1]["s1"].extend(["/files/교재/신규/첫째.pdf", "/files/교재/신규/둘째.pdf"])
    return expected, files


def route_worker(root, operation, fault):
    install_paths(root)
    install_baseline_sources(include_routes=True)
    from flask import Flask
    import routes.api_fs as api_fs
    import core.material_state as material_state

    if fault == "before-commit":
        api_fs._save_material_state_locked = lambda *_a, **_k: os._exit(CRASH_EXIT)
    elif fault.startswith("store-"):
        wanted = int(fault.split("-")[1])
        original_save = material_state.save_atomic
        counter = 0

        def crash_after_store(path, value, **kwargs):
            nonlocal counter
            original_save(path, value, **kwargs)
            counter += 1
            if counter == wanted:
                os._exit(CRASH_EXIT)
        material_state.save_atomic = crash_after_store
    elif fault in {"intent", "commit-marker", "last-good", "ready-upload"}:
        original_write = material_state._write_journal_atomic
        last_good_writes = 0

        def crash_after_journal(path, payload):
            nonlocal last_good_writes
            original_write(path, payload)
            if path.name == "material_state_last_good.json":
                last_good_writes += 1
                if fault == "last-good" and last_good_writes == 2:
                    os._exit(CRASH_EXIT)
            if path.name != "material_state_transaction.json":
                return
            if fault == "intent" and payload.get("phase") == "prepared":
                os._exit(CRASH_EXIT)
            if fault == "commit-marker" and payload.get("phase") == "committing":
                os._exit(CRASH_EXIT)
            operations = payload.get("fileTransaction", {}).get("operations", [])
            if fault == "ready-upload" and operations and all(op["identity"] is not None for op in operations):
                os._exit(CRASH_EXIT)
        material_state._write_journal_atomic = crash_after_journal
    elif fault == "first-filesystem":
        original_rename = pathlib.Path.rename

        def crash_after_rename(path, target):
            result = original_rename(path, target)
            os._exit(CRASH_EXIT)
            return result
        pathlib.Path.rename = crash_after_rename
    elif fault == "directory-created":
        original_mkdir = pathlib.Path.mkdir

        def mkdir_then_crash(path, *args, **kwargs):
            result = original_mkdir(path, *args, **kwargs)
            try:
                path.resolve().relative_to((root / "files").resolve())
            except ValueError:
                return result
            if path.resolve() != (root / "files").resolve():
                os._exit(CRASH_EXIT)
            return result
        pathlib.Path.mkdir = mkdir_then_crash
    elif fault == "partial-upload":
        from werkzeug.datastructures import FileStorage

        def partial_upload(_uploaded, destination, *_a, **_k):
            pathlib.Path(destination).write_bytes(b"partial-upload-fixture")
            os._exit(CRASH_EXIT)
        FileStorage.save = partial_upload
    elif fault == "before-clear":
        material_state._clear_journal = lambda *_a, **_k: os._exit(CRASH_EXIT)

    app = Flask("file-transaction-crash-fixture")
    app.register_blueprint(api_fs.bp_api_fs)
    client = app.test_client()
    if operation == "rename":
        response = client.post("/api/fs/rename", json={"src": "교재", "new_name": "수학 교재"})
    elif operation == "move":
        response = client.post("/api/fs/move", json={"paths": ["교재", "루트.txt"], "dst": "보관"})
    elif operation == "delete":
        response = client.post("/api/fs/delete", json={"paths": ["교재", "루트.txt"]})
    elif operation == "upload":
        response = client.post("/api/fs/upload", data={"dst": "교재/신규", "files": [
            (io.BytesIO(b"first-upload"), "첫째.pdf"), (io.BytesIO(b"second-upload"), "둘째.pdf")
        ]}, content_type="multipart/form-data")
    else:
        raise AssertionError(operation)
    check(response.status_code == 200, f"{operation} returned {response.status_code}: {response.get_json()}")
    if operation == "upload":
        check(not any(item.get("error") for item in response.get_json()["files"]),
              f"upload returned per-file errors: {response.get_json()}")


def recover_worker(root, fault=None):
    install_paths(root)
    install_baseline_sources()
    import core.material_state as material_state
    if fault == "rollback-first":
        original_rename = pathlib.Path.rename
        original_unlink = pathlib.Path.unlink

        def rename_then_crash(path, target):
            original_rename(path, target)
            os._exit(CRASH_EXIT)

        def unlink_then_crash(path, *args, **kwargs):
            result = original_unlink(path, *args, **kwargs)
            if "files" in path.parts:
                os._exit(CRASH_EXIT)
            return result
        pathlib.Path.rename = rename_then_crash
        pathlib.Path.unlink = unlink_then_crash
    elif fault == "forward-second":
        original_save = material_state.save_atomic
        count = 0

        def save_then_crash(path, value, **kwargs):
            nonlocal count
            original_save(path, value, **kwargs)
            count += 1
            if count == 2:
                os._exit(CRASH_EXIT)
        material_state.save_atomic = save_then_crash
    material_state.recover_material_state_if_needed(*(root / name for name in STORE_NAMES))


def invoke(root, mode, *args, expected_exit=0):
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    command = [sys.executable, str(__file__), mode, str(root), *args]
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", env=environment) as child:
        stdout, stderr = child.communicate(timeout=30)
        check(child.returncode == expected_exit, f"worker {args} exit {child.returncode}: {stdout}\n{stderr}")
        if child.returncode == CRASH_EXIT:
            # Only our known-dead temp child owns these leases. Age them rather
            # than deleting them, so the real storage stale-lock path is exercised.
            for lock in root.glob("*.lock"):
                owner = re.search(r"pid=([0-9]+)", lock.read_text(encoding="utf-8"))
                check(owner is not None and int(owner[1]) == child.pid, "unexpected fixture lease owner")
                stale = time.time() - 60
                os.utime(lock, (stale, stale))


def run_crash_matrix(expect_gap):
    common_faults = ("intent", "first-filesystem", "before-commit", "commit-marker",
                     "store-1", "store-2", "store-3", "last-good", "before-clear", "none")
    for operation in ("rename", "move", "delete", "upload"):
        faults = ("before-commit",) if expect_gap else common_faults
        if operation == "upload" and not expect_gap:
            faults += ("partial-upload", "ready-upload")
        for fault in faults:
            with tempfile.TemporaryDirectory(prefix="file-transaction-crash-") as temporary:
                root = pathlib.Path(temporary)
                state, content = fixture(root)
                original = store_fingerprint(root)
                invoke(root, "--worker", operation, fault,
                       expected_exit=0 if fault == "none" else CRASH_EXIT)
                invoke(root, "--recover-worker")
                actual = tuple(json.loads((root / name).read_text(encoding="utf-8")) for name in STORE_NAMES)
                if expect_gap:
                    check(actual == state and store_fingerprint(root) == original,
                          "baseline gap must leave metadata at its original bytes")
                    check(tree_content(root) != content, "baseline gap must change the live file fixture")
                    check(not (root / "material_state_transaction.json").exists(),
                          "baseline crash must leave no recoverable material journal")
                    print(f"REPRO {operation}: changed files + original 3 stores + no recovery journal")
                    continue
                if fault in {"intent", "first-filesystem", "before-commit", "partial-upload", "ready-upload"}:
                    check(actual == state and store_fingerprint(root) == original,
                          f"{operation} prepared crash must leave exact original store bytes")
                    check(tree_content(root) == content, f"{operation} prepared crash must restore every file")
                else:
                    expected_state, expected_files = expected_after(operation, state, content)
                    check(actual == expected_state, f"{operation}/{fault} must converge to literal metadata")
                    check(tree_content(root) == expected_files, f"{operation}/{fault} must preserve exact file bytes")
                check(not (root / "material_state_transaction.json").exists(), "recovery must clear the journal")
                check(not staging_paths(root), "recovery must clean owned staging directories")
                invoke(root, "--recover-worker")
                check(tuple(json.loads((root / n).read_text(encoding="utf-8")) for n in STORE_NAMES) == actual,
                      "a second fresh-process recovery must be idempotent")
                print(f"PASS {operation}/{fault}: actual route, abrupt process exit, fresh-process recovery")


def run_repeated_recovery():
    for operation in ("rename", "move", "delete", "upload"):
        for initial, recovery in (("before-commit", "rollback-first"), ("store-1", "forward-second")):
            with tempfile.TemporaryDirectory(prefix="file-transaction-recovery-") as temporary:
                root = pathlib.Path(temporary)
                state, content = fixture(root)
                original = store_fingerprint(root)
                invoke(root, "--worker", operation, initial, expected_exit=CRASH_EXIT)
                invoke(root, "--recover-worker", recovery, expected_exit=CRASH_EXIT)
                invoke(root, "--recover-worker")
                actual = tuple(json.loads((root / name).read_text(encoding="utf-8")) for name in STORE_NAMES)
                if initial == "before-commit":
                    check(actual == state and store_fingerprint(root) == original and tree_content(root) == content,
                          f"{operation}: interrupted rollback must restore literal files and exact JSON bytes")
                else:
                    expected_state, expected_files = expected_after(operation, state, content)
                    check(actual == expected_state and tree_content(root) == expected_files,
                          f"{operation}: interrupted forward recovery must converge to literal state")
                check(not (root / "material_state_transaction.json").exists(), "repeated recovery must clear intent")
                check(not staging_paths(root), "repeated recovery must clean staging")
                print(f"PASS {operation}/{recovery}: crash during recovery, second process completes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-gap", action="store_true")
    parser.add_argument("--baseline-source-root", type=pathlib.Path)
    parser.add_argument("--worker", type=pathlib.Path)
    parser.add_argument("--recover-worker", type=pathlib.Path)
    parser.add_argument("operation", nargs="?")
    parser.add_argument("fault", nargs="?")
    args = parser.parse_args()
    if args.baseline_source_root:
        check(args.expect_gap, "historical source override is only for the negative control")
        os.environ["FILE_TRANSACTION_BASELINE_SOURCE_ROOT"] = str(args.baseline_source_root.resolve())
    if args.worker:
        route_worker(args.worker, args.operation, args.fault)
    elif args.recover_worker:
        recover_worker(args.recover_worker, args.operation)
    else:
        run_crash_matrix(args.expect_gap)
        if not args.expect_gap:
            run_repeated_recovery()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
