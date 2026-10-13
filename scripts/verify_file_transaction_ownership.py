"""Independent OS-temp oracle for directory ownership and rollback preflight."""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import pathlib
import sys
import tempfile
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_file_transaction_crash import (
    CRASH_EXIT, STORE_NAMES, check, install_baseline_sources, install_paths, invoke,
)
from scripts.verify_file_transaction_routes import post_operation, route_fixture


def filesystem_snapshot(root):
    files = root / "files"
    snapshot = {}
    for path in [files, *sorted(files.rglob("*"))]:
        info = path.lstat()
        relative = path.relative_to(files).as_posix()
        content = None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot[relative] = (info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, content)
    return snapshot


def metadata_snapshot(root):
    return {name: (path.stat().st_mtime_ns, path.read_bytes())
            for name in STORE_NAMES for path in [root / name]}


def inode(path):
    info = path.lstat()
    return info.st_dev, info.st_ino


def run_ambiguity_cases(expect_regressions=False):
    cases = ("not-created", "replaced-created", "multi-operation", "foreign-child", "mkdir-record-gap")
    for case in cases:
        with route_fixture() as (root, state, _content, client, _api_fs, _app):
            fault = "intent" if case == "not-created" else "directory-created" if case == "mkdir-record-gap" else "before-commit"
            invoke(root, "--worker", "move", fault, expected_exit=CRASH_EXIT)
            destination = root / "files" / "보관"
            preserved = None
            if case == "not-created":
                check(not destination.exists(), "intent fixture must crash before destination creation")
                destination.mkdir()
                foreign = destination
            elif case == "replaced-created":
                preserved = root / "original-created-directory"
                destination.rename(preserved)
                original_inode = inode(preserved)
                destination.mkdir()
                check(inode(destination) != original_inode, "replacement destination must have a different inode")
                for path in list(preserved.iterdir()):
                    path.rename(destination / path.name)
                foreign = destination
            elif case == "multi-operation":
                preserved = root / "original-moved-directory"
                (destination / "교재").rename(preserved)
                (destination / "교재").mkdir()
                (destination / "교재" / "alien.txt").write_bytes(b"foreign-content")
                foreign = destination / "교재"
            elif case == "foreign-child":
                (destination / "alien.txt").write_bytes(b"foreign-content")
                foreign = destination / "alien.txt"
            else:
                check(destination.is_dir(), "mkdir fault must occur after directory creation")
                foreign = destination

            files_before, stores_before = filesystem_snapshot(root), metadata_snapshot(root)
            journal = root / "material_state_transaction.json"
            journal_before = journal.read_bytes()
            foreign_before = inode(foreign)
            preserved_before = inode(preserved) if preserved is not None else None
            read = client.get("/api/materials")
            check(read.status_code == 200 and read.get_json() == state[0], "material read must remain available")
            check(metadata_snapshot(root) == stores_before, "ambiguous recovery must not rewrite any primary store")

            if expect_regressions:
                if case in {"not-created", "replaced-created", "mkdir-record-gap"}:
                    check(not foreign.exists() and not journal.exists()
                          and read.headers.get("X-Material-State-Degraded") is None,
                          f"{case}: baseline must reproduce deletion of an unproven directory and its journal")
                else:
                    check(read.headers.get("X-Material-State-Degraded") == "1" and journal.read_bytes() == journal_before,
                          "baseline ambiguity must keep degraded read and journal")
                    check(filesystem_snapshot(root) != files_before and (root / "files" / "루트.txt").exists(),
                          f"{case}: baseline must reproduce a detectable conflict after partial rollback")
                print(f"REPRO {case}: actual route and external directory/file observer")
                continue

            check(read.headers.get("X-Material-State-Degraded") == "1", f"{case}: ambiguity must degrade reads")
            check(filesystem_snapshot(root) == files_before and inode(foreign) == foreign_before
                  and journal.read_bytes() == journal_before, f"{case}: preflight must make no filesystem/journal change")
            if preserved is not None:
                check(inode(preserved) == preserved_before, "preserved original inode must remain untouched")
            assignments = client.get("/api/mat-assign")
            check(assignments.status_code == 200 and assignments.get_json() == state[1]
                  and assignments.headers.get("X-Material-State-Degraded") == "1", "assignment read must use literal last-good")
            check(client.get("/api/fs/tree").status_code == 503, "tree recovery must fail closed on ambiguity")
            for operation in ("rename", "move", "delete", "upload"):
                check(post_operation(client, operation).status_code == 503, "ambiguous recovery must block every file writer")
            check(client.post("/api/mat-assign", json={"overwrite": []},
                              headers={"If-Match": assignments.headers["X-Material-State-Revision"]}).status_code == 503,
                  "ambiguous recovery must block metadata writers")
            check(filesystem_snapshot(root) == files_before and metadata_snapshot(root) == stores_before
                  and journal.read_bytes() == journal_before, "all blocked requests must leave exact bytes/identities unchanged")
            print(f"PASS {case}: degraded read, all writes blocked, filesystem/store/journal invariant")
    return len(cases)


def run_nested_owned_rollback():
    with route_fixture() as (root, state, _content, client, api_fs, _app):
        files_before, stores_before = filesystem_snapshot(root), metadata_snapshot(root)
        def fail_before_commit(*_args, **_kwargs):
            raise RuntimeError("injected nested pre-commit failure")
        with patch.object(api_fs, "_save_material_state_locked", fail_before_commit):
            response = client.post("/api/fs/move", json={"paths": ["교재", "루트.txt"], "dst": "보관/안쪽/깊은"})
        check(response.status_code == 500, "nested fixture must reach its injected pre-commit failure")
        # Moving entries changes their parent's mtime; compare identities/content and directory membership.
        after = filesystem_snapshot(root)
        check({key: value[:3] + value[4:] for key, value in after.items()}
              == {key: value[:3] + value[4:] for key, value in files_before.items()},
              "nested rollback must restore all original file/directory identities and content")
        check(metadata_snapshot(root) == stores_before and not (root / "files" / "보관").exists()
              and not (root / "material_state_transaction.json").exists(), "owned nested directories must be safely removed")
        read = client.get("/api/materials")
        check(read.status_code == 200 and read.get_json() == state[0]
              and read.headers.get("X-Material-State-Degraded") is None, "healthy nested rollback must remain undegraded")
        print("PASS nested-owned: captured directory identities allow complete rollback")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-regressions", action="store_true")
    parser.add_argument("--baseline-source-root", type=pathlib.Path)
    args = parser.parse_args()
    logging.getLogger("core.storage").setLevel(logging.ERROR)
    if args.baseline_source_root:
        check(args.expect_regressions, "historical source is only for the negative control")
        os.environ["FILE_TRANSACTION_BASELINE_SOURCE_ROOT"] = str(args.baseline_source_root.resolve())
    with tempfile.TemporaryDirectory(prefix="file-ownership-import-") as temporary:
        install_paths(pathlib.Path(temporary))
        install_baseline_sources(include_routes=True)
        import routes.api_fs  # noqa: F401 -- load only after temp path injection
        count = run_ambiguity_cases(args.expect_regressions)
        if not args.expect_regressions:
            run_nested_owned_rollback()
            count += 1
    print(f"{'REPRO' if args.expect_regressions else 'PASS'} file ownership/preflight: {count} scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
