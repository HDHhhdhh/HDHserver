"""Temp-only regression checks for file-manager path reference updates."""
from __future__ import annotations

import copy
import io
import json
import pathlib
import sys
import tempfile

from flask import Flask


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_material_reference_rule_checks() -> None:
    from core.material_reference_rules import (
        normalize_relative_file_path,
        remove_material_file_references,
        rewrite_material_file_references,
    )

    materials = {
        "m1": {
            "url": "/files/교재/단원/문제.pdf?download=1#page",
            "title": "문제",
            "unknown": {"keep": True},
        },
        "m-sibling": {"url": "/files/교재실/보존.pdf"},
        "m-external": {"url": "https://example.com/files/교재/외부.pdf"},
        "legacy": "keep",
    }
    assignments = {
        "s1": [
            "m1",
            "/files/교재/단원/문제.pdf?download=1#page",
            "교재/단원/문제.pdf",
            "DIR:교재",
            "DIR:교재실",
            {"unknown": "keep"},
        ],
        "unknown": {"keep": True},
    }
    page_folders = {
        "materials": "교재/단원",
        "sibling": "교재실",
        "unknown": {"keep": True},
    }
    before = copy.deepcopy((materials, assignments, page_folders))

    rewritten = rewrite_material_file_references(
        materials,
        assignments,
        page_folders,
        [("교재", "수학 교재")],
    )
    check(
        rewritten[0]["m1"]["url"]
        == "/files/수학 교재/단원/문제.pdf?download=1#page",
        "rename rules must preserve URL query/fragment while rewriting descendants",
    )
    check(
        rewritten[0]["m-sibling"] == materials["m-sibling"]
        and rewritten[0]["m-external"] == materials["m-external"],
        "rename rules must use segment boundaries and ignore external URLs",
    )
    check(
        rewritten[1]["s1"]
        == [
            "m1",
            "/files/수학 교재/단원/문제.pdf?download=1#page",
            "수학 교재/단원/문제.pdf",
            "DIR:수학 교재",
            "DIR:교재실",
            {"unknown": "keep"},
        ],
        "rename rules must preserve IDs/unknown tokens and rewrite URL, relative, and DIR tokens",
    )
    check(
        rewritten[2]
        == {
            "materials": "수학 교재/단원",
            "sibling": "교재실",
            "unknown": {"keep": True},
        },
        "rename rules must update only matching page-folder values",
    )
    check(
        (materials, assignments, page_folders) == before,
        "pure rename rules must leave every input unchanged",
    )

    removed = remove_material_file_references(
        *rewritten,
        ["수학 교재/단원"],
    )
    check(
        set(removed[0]) == {"m-sibling", "m-external", "legacy"},
        "delete rules must remove only material rows under the deleted subtree",
    )
    check(
        removed[1]["s1"]
        == ["DIR:수학 교재", "DIR:교재실", {"unknown": "keep"}],
        "delete rules must remove descendant IDs/paths but preserve parent and sibling DIR tokens",
    )
    check(
        removed[2]["materials"] == ""
        and removed[2]["sibling"] == "교재실"
        and removed[2]["unknown"] == {"keep": True},
        "delete rules must clear only page-folder values inside the deleted subtree",
    )
    check(
        (materials, assignments, page_folders) == before,
        "pure delete rules must leave every input unchanged",
    )

    try:
        normalize_relative_file_path("../escape")
    except ValueError:
        pass
    else:
        raise AssertionError("relative reference rules must reject parent traversal")


def run_material_state_recovery_checks() -> None:
    from core.material_state import (
        material_state_journal_path,
        MaterialStateRecoveryRequiredError,
        load_material_state,
        material_state_lock,
        recover_material_state_if_needed,
        save_material_state_locked,
    )
    from core.storage import save_atomic

    with tempfile.TemporaryDirectory(prefix="material-state-recovery-") as tmpdir:
        root = pathlib.Path(tmpdir)
        material_path = root / "materials.json"
        assignment_path = root / "assignments.json"
        page_path = root / "page_folders.json"
        before = (
            {"old": {"url": "/files/old.pdf"}},
            {"s1": ["old"]},
            {"materials": "old"},
        )
        after = (
            {"new": {"url": "/files/new.pdf"}},
            {"s1": ["new"]},
            {"materials": "new"},
        )
        for path, value in zip(
            (material_path, assignment_path, page_path),
            before,
        ):
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

        calls = {"count": 0}

        def fail_second_write(path: pathlib.Path, value: object) -> None:
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("injected second-store failure")
            save_atomic(path, value, mirror=False)

        with material_state_lock(material_path, assignment_path, page_path):
            try:
                save_material_state_locked(
                    material_path,
                    assignment_path,
                    page_path,
                    *after,
                    _target_writer=fail_second_write,
                )
            except RuntimeError as exc:
                check("injected" in str(exc), "failure injection must reach the coordinator")
            else:
                raise AssertionError("material-state failure injection must abort the first commit")

        journal_path = material_state_journal_path(material_path)
        check(journal_path.exists(), "partial three-store commit must retain its recovery journal")
        check(
            recover_material_state_if_needed(
                material_path,
                assignment_path,
                page_path,
            ),
            "the next material-state boundary must recover a pending journal",
        )
        check(not journal_path.exists(), "successful material-state recovery must clear its journal")
        for path, expected in zip(
            (material_path, assignment_path, page_path),
            after,
        ):
            check(
                json.loads(path.read_text(encoding="utf-8")) == expected,
                "material-state recovery must converge every store to the journal target",
            )

        unaffected_before = (assignment_path.read_bytes(), page_path.read_bytes())
        material_path.write_text("{broken", encoding="utf-8")
        try:
            load_material_state(
                material_path,
                assignment_path,
                page_path,
            )
        except MaterialStateRecoveryRequiredError:
            pass
        else:
            raise AssertionError("malformed primary material JSON must require recovery")
        check(
            unaffected_before == (assignment_path.read_bytes(), page_path.read_bytes()),
            "strict material reads must not rewrite sibling stores after malformed JSON",
        )

def run_material_assignment_route_checks() -> None:
    import routes.api_materials as api_materials
    from core.material_state import material_state_journal_path

    original_paths = (
        api_materials.MAT_PATH,
        api_materials.ASN_PATH,
        api_materials.PAGE_FOLDERS_PATH,
    )

    def write_json(path: pathlib.Path, value: object) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    try:
        with tempfile.TemporaryDirectory(prefix="material-assignment-route-") as tmpdir:
            root = pathlib.Path(tmpdir)
            material_path = root / "materials.json"
            assignment_path = root / "mat_assign.json"
            page_path = root / "page_folders.json"
            write_json(material_path, {"m1": {"url": "/files/m1.pdf", "unknown": True}})
            write_json(assignment_path, {"s1": ["m1"]})
            write_json(page_path, {"materials": "교재", "unknown": {"keep": True}})
            api_materials.MAT_PATH = material_path
            api_materials.ASN_PATH = assignment_path
            api_materials.PAGE_FOLDERS_PATH = page_path

            app = Flask("verify-material-assignment-route")
            app.register_blueprint(api_materials.bp_api_materials)
            client = app.test_client()

            initial = client.get("/api/mat-assign")
            initial_revision = initial.headers.get("X-Material-State-Revision") or ""
            check(
                initial.status_code == 200
                and initial.get_json() == {"s1": ["m1"]}
                and len(initial_revision) == 64,
                "material assignment GET must expose one coherent revisioned snapshot",
            )

            missing_revision = client.post("/api/mat-assign", json={"s1": ["m1", "m2"]})
            check(
                missing_revision.status_code == 428
                and json.loads(assignment_path.read_text(encoding="utf-8")) == {"s1": ["m1"]},
                "whole assignment writes without a revision must fail before mutation",
            )

            updated = client.post(
                "/api/mat-assign",
                json={"s1": ["m1", "m2"]},
                headers={"If-Match": initial_revision},
            )
            updated_revision = updated.headers.get("X-Material-State-Revision") or ""
            check(
                updated.status_code == 204
                and updated_revision
                and updated_revision != initial_revision
                and json.loads(assignment_path.read_text(encoding="utf-8")) == {"s1": ["m1", "m2"]},
                "a current assignment revision must commit and return the next revision",
            )
            check(
                json.loads(material_path.read_text(encoding="utf-8"))
                == {"m1": {"url": "/files/m1.pdf", "unknown": True}}
                and json.loads(page_path.read_text(encoding="utf-8"))
                == {"materials": "교재", "unknown": {"keep": True}},
                "assignment-only writes must preserve materials, page folders, and unknown fields",
            )

            stale = client.post(
                "/api/mat-assign",
                json={"s1": ["stale-overwrite"]},
                headers={"If-Match": initial_revision},
            )
            check(
                stale.status_code == 409
                and stale.headers.get("X-Material-State-Revision") == updated_revision
                and json.loads(assignment_path.read_text(encoding="utf-8")) == {"s1": ["m1", "m2"]},
                "a stale whole-map writer must receive 409 without overwriting newer state",
            )

            journal_path = material_state_journal_path(material_path)
            journal_path.write_text("{broken", encoding="utf-8")
            primary_before = (
                material_path.read_bytes(),
                assignment_path.read_bytes(),
                page_path.read_bytes(),
            )
            degraded_read = client.get("/api/mat-assign")
            check(
                degraded_read.status_code == 200
                and degraded_read.headers.get("X-Material-State-Degraded") == "1"
                and degraded_read.get_json() == {"s1": ["m1", "m2"]},
                "a damaged pending journal must keep assignment reads available from last-good",
            )
            degraded_write = client.post(
                "/api/mat-assign",
                json={"s1": ["must-not-write"]},
                headers={"If-Match": updated_revision},
            )
            check(
                degraded_write.status_code == 503
                and primary_before
                == (
                    material_path.read_bytes(),
                    assignment_path.read_bytes(),
                    page_path.read_bytes(),
                ),
                "a damaged pending journal must disable only material writes without mutating primaries",
            )
    finally:
        (
            api_materials.MAT_PATH,
            api_materials.ASN_PATH,
            api_materials.PAGE_FOLDERS_PATH,
        ) = original_paths

def run_file_reference_route_checks() -> None:
    import routes.api_fs as api_fs

    original = {
        "FILES_DIR": api_fs.FILES_DIR,
        "FILES_ROOT": api_fs.FILES_ROOT,
        "MAT_PATH": api_fs.MAT_PATH,
        "ASN_PATH": api_fs.ASN_PATH,
        "PAGE_FOLDERS_PATH": api_fs.PAGE_FOLDERS_PATH,
        "save_material_state": api_fs._save_material_state_locked,
    }

    def write_json(path: pathlib.Path, value: object) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def read_json(path: pathlib.Path):
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        with tempfile.TemporaryDirectory(prefix="file-reference-route-") as tmpdir:
            root = pathlib.Path(tmpdir)
            files_dir = root / "files"
            files_dir.mkdir()
            mat_path = root / "materials.json"
            assign_path = root / "mat_assign.json"
            page_path = root / "page_folders.json"
            api_fs.FILES_DIR = files_dir
            api_fs.FILES_ROOT = files_dir.resolve()
            api_fs.MAT_PATH = mat_path
            api_fs.ASN_PATH = assign_path
            api_fs.PAGE_FOLDERS_PATH = page_path

            source_file = files_dir / "\uad50\uc7ac" / "\ub2e8\uc6d0" / "\ubb38\uc81c.pdf"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("fixture", encoding="utf-8")
            write_json(
                mat_path,
                {
                    "m1": {
                        "url": "/files/\uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf",
                        "title": "\ubb38\uc81c",
                        "unknown": {"keep": True},
                    },
                    "m-sibling": {"url": "/files/\uad50\uc7ac\uc2e4/\ubcf4\uc874.pdf"},
                    "m-external": {"url": "https://example.com/files/\uad50\uc7ac/\uc678\ubd80.pdf"},
                },
            )
            write_json(
                assign_path,
                {
                    "s1": [
                        "m1",
                        "/files/\uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf",
                        "\uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf",
                        "DIR:\uad50\uc7ac",
                        "/files/\uad50\uc7ac\uc2e4/\ubcf4\uc874.pdf",
                        "DIR:\uad50\uc7ac\uc2e4",
                        {"unknown": "keep"},
                    ],
                    "unknown": {"keep": True},
                },
            )
            write_json(
                page_path,
                {
                    "materials": "\uad50\uc7ac/\ub2e8\uc6d0",
                    "sibling": "\uad50\uc7ac\uc2e4",
                    "unknown": {"keep": True},
                },
            )

            app = Flask("verify-file-reference-routes")
            app.register_blueprint(api_fs.bp_api_fs)
            client = app.test_client()

            response = client.post(
                "/api/fs/rename",
                json={"src": "\uad50\uc7ac", "new_name": "\uc218\ud559 \uad50\uc7ac"},
            )
            check(response.status_code == 200, "folder rename must accept a safe Korean name")
            check(
                (files_dir / "\uc218\ud559 \uad50\uc7ac" / "\ub2e8\uc6d0" / "\ubb38\uc81c.pdf").exists(),
                "folder rename must preserve nested files",
            )
            renamed_materials = read_json(mat_path)
            check(
                renamed_materials["m1"]["url"] == "/files/\uc218\ud559 \uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf"
                and renamed_materials["m1"]["unknown"] == {"keep": True}
                and renamed_materials["m-sibling"]["url"] == "/files/\uad50\uc7ac\uc2e4/\ubcf4\uc874.pdf"
                and renamed_materials["m-external"]["url"] == "https://example.com/files/\uad50\uc7ac/\uc678\ubd80.pdf",
                "folder rename must rewrite descendants while preserving unknown, sibling, and external metadata",
            )
            check(
                read_json(assign_path)["s1"]
                == [
                    "m1",
                    "/files/\uc218\ud559 \uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf",
                    "\uc218\ud559 \uad50\uc7ac/\ub2e8\uc6d0/\ubb38\uc81c.pdf",
                    "DIR:\uc218\ud559 \uad50\uc7ac",
                    "/files/\uad50\uc7ac\uc2e4/\ubcf4\uc874.pdf",
                    "DIR:\uad50\uc7ac\uc2e4",
                    {"unknown": "keep"},
                ],
                "folder rename must rewrite URL, relative, and directory assignment tokens",
            )
            check(
                read_json(page_path)
                == {
                    "materials": "\uc218\ud559 \uad50\uc7ac/\ub2e8\uc6d0",
                    "sibling": "\uad50\uc7ac\uc2e4",
                    "unknown": {"keep": True},
                },
                "folder rename must rewrite only matching page-folder descendants",
            )

            response = client.post(
                "/api/fs/delete",
                json={"paths": ["\uc218\ud559 \uad50\uc7ac/\ub2e8\uc6d0"]},
            )
            check(response.status_code == 200, "nested folder delete must succeed")
            check(
                set(read_json(mat_path)) == {"m-sibling", "m-external"},
                "folder delete must remove only descendant material metadata",
            )
            check(
                read_json(assign_path)["s1"]
                == [
                    "DIR:\uc218\ud559 \uad50\uc7ac",
                    "/files/\uad50\uc7ac\uc2e4/\ubcf4\uc874.pdf",
                    "DIR:\uad50\uc7ac\uc2e4",
                    {"unknown": "keep"},
                ],
                "folder delete must remove descendant IDs and paths but preserve parent, sibling, and unknown tokens",
            )
            check(
                read_json(page_path)
                == {
                    "materials": "",
                    "sibling": "\uad50\uc7ac\uc2e4",
                    "unknown": {"keep": True},
                },
                "folder delete must clear only page-folder references to the deleted subtree",
            )

            move_file = files_dir / "\uc790\ub8cc" / "\ud558\uc704" / "\uc774\ub3d9.pdf"
            move_file.parent.mkdir(parents=True)
            move_file.write_text("fixture", encoding="utf-8")
            write_json(mat_path, {"m2": {"url": "/files/\uc790\ub8cc/\ud558\uc704/\uc774\ub3d9.pdf"}})
            write_json(assign_path, {"s2": ["DIR:\uc790\ub8cc", "/files/\uc790\ub8cc/\ud558\uc704/\uc774\ub3d9.pdf"]})
            write_json(page_path, {"materials": "\uc790\ub8cc/\ud558\uc704"})

            response = client.post(
                "/api/fs/move",
                json={"paths": ["\uc790\ub8cc"], "dst": "\ubcf4\uad00"},
            )
            check(response.status_code == 200, "folder move must succeed")
            check(
                (files_dir / "\ubcf4\uad00" / "\uc790\ub8cc" / "\ud558\uc704" / "\uc774\ub3d9.pdf").exists()
                and read_json(mat_path)["m2"]["url"] == "/files/\ubcf4\uad00/\uc790\ub8cc/\ud558\uc704/\uc774\ub3d9.pdf"
                and read_json(assign_path)["s2"]
                == ["DIR:\ubcf4\uad00/\uc790\ub8cc", "/files/\ubcf4\uad00/\uc790\ub8cc/\ud558\uc704/\uc774\ub3d9.pdf"]
                and read_json(page_path) == {"materials": "\ubcf4\uad00/\uc790\ub8cc/\ud558\uc704"},
                "folder move must rewrite every descendant reference",
            )

            root_move = client.post(
                "/api/fs/move",
                json={"paths": ["\ubcf4\uad00/\uc790\ub8cc"], "dst": ""},
            )
            check(root_move.status_code == 200, "the file-manager root move contract must accept an empty destination")
            check(
                (files_dir / "\uc790\ub8cc" / "\ud558\uc704" / "\uc774\ub3d9.pdf").exists()
                and read_json(mat_path)["m2"]["url"] == "/files/\uc790\ub8cc/\ud558\uc704/\uc774\ub3d9.pdf"
                and read_json(assign_path)["s2"]
                == ["DIR:\uc790\ub8cc", "/files/\uc790\ub8cc/\ud558\uc704/\uc774\ub3d9.pdf"]
                and read_json(page_path) == {"materials": "\uc790\ub8cc/\ud558\uc704"},
                "moving to root must rewrite every descendant reference back to its root-relative path",
            )

            scalar_paths = client.post(
                "/api/fs/move",
                json={"paths": "\uc790\ub8cc", "dst": "\ub2e4\ub978\uacf3"},
            )
            check(scalar_paths.status_code == 400, "folder move must reject a scalar paths payload")

            overlap_file = files_dir / "\uacb9\uce68" / "\ud558\uc704" / "\ud30c\uc77c.txt"
            overlap_file.parent.mkdir(parents=True)
            overlap_file.write_text("keep", encoding="utf-8")
            stores_before_overlap = (
                mat_path.read_bytes(),
                assign_path.read_bytes(),
                page_path.read_bytes(),
            )
            overlap = client.post(
                "/api/fs/move",
                json={
                    "paths": ["\uacb9\uce68", "\uacb9\uce68/\ud558\uc704"],
                    "dst": "\uacb9\uce68\ubaa9\uc801\uc9c0",
                },
            )
            check(overlap.status_code == 400, "overlapping move sources must fail before mutation")
            check(
                overlap_file.exists() and not (files_dir / "\uacb9\uce68\ubaa9\uc801\uc9c0").exists(),
                "overlapping move rejection must leave the file tree unchanged",
            )
            check(
                stores_before_overlap
                == (mat_path.read_bytes(), assign_path.read_bytes(), page_path.read_bytes()),
                "overlapping move rejection must leave all reference stores unchanged",
            )

            invalid_name_file = files_dir / "\uc774\ub984\ubcf4\uc874.txt"
            invalid_name_file.write_text("keep", encoding="utf-8")
            invalid_rename = client.post(
                "/api/fs/rename",
                json={"src": "\uc774\ub984\ubcf4\uc874.txt", "new_name": "../\ud0c8\ucd9c.txt"},
            )
            check(
                invalid_rename.status_code == 400 and invalid_name_file.exists(),
                "rename must reject separators and traversal without touching the source",
            )

            rollback_file = files_dir / "\ub864\ubc31" / "\uc6d0\ubcf8.txt"
            rollback_file.parent.mkdir(parents=True)
            rollback_file.write_text("rollback", encoding="utf-8")
            rollback_state = (
                {"rollback": {"url": "/files/\ub864\ubc31/\uc6d0\ubcf8.txt"}},
                {"s-rollback": ["rollback", "/files/\ub864\ubc31/\uc6d0\ubcf8.txt"]},
                {"materials": "\ub864\ubc31"},
            )
            write_json(mat_path, rollback_state[0])
            write_json(assign_path, rollback_state[1])
            write_json(page_path, rollback_state[2])

            def fail_before_material_journal(*_args, **_kwargs):
                raise RuntimeError("injected pre-journal save failure")

            try:
                api_fs._save_material_state_locked = fail_before_material_journal
                failed_rename = client.post(
                    "/api/fs/rename",
                    json={"src": "\ub864\ubc31", "new_name": "\ub864\ubc31\uc2e0\uaddc"},
                )
            finally:
                api_fs._save_material_state_locked = original["save_material_state"]

            check(failed_rename.status_code == 500, "pre-journal rename failure must surface as a server failure")
            check(
                rollback_file.exists() and not (files_dir / "\ub864\ubc31\uc2e0\uaddc").exists(),
                "pre-journal rename failure must roll the filesystem back",
            )
            check(
                read_json(mat_path) == rollback_state[0]
                and read_json(assign_path) == rollback_state[1]
                and read_json(page_path) == rollback_state[2],
                "pre-journal rename failure must leave all reference stores unchanged",
            )

            try:
                api_fs._save_material_state_locked = fail_before_material_journal
                failed_delete = client.post(
                    "/api/fs/delete",
                    json={"paths": ["\ub864\ubc31/\uc6d0\ubcf8.txt"]},
                )
            finally:
                api_fs._save_material_state_locked = original["save_material_state"]

            check(failed_delete.status_code == 500, "pre-journal delete failure must surface as a server failure")
            check(rollback_file.exists(), "pre-journal delete failure must restore staged content")
            check(
                read_json(mat_path) == rollback_state[0]
                and read_json(assign_path) == rollback_state[1]
                and read_json(page_path) == rollback_state[2],
                "pre-journal delete failure must leave all reference stores unchanged",
            )
            check(
                not list(root.glob(".file-delete-stage-*")),
                "delete rollback must remove every temporary staging directory",
            )

            malformed_file = files_dir / "\uc190\uc0c1\uc800\uc7a5\uc18c.txt"
            malformed_file.write_text("keep", encoding="utf-8")
            write_json(mat_path, [])
            malformed_before = mat_path.read_bytes()
            malformed_delete = client.post(
                "/api/fs/delete",
                json={"paths": ["\uc190\uc0c1\uc800\uc7a5\uc18c.txt"]},
            )
            check(
                malformed_delete.status_code == 503
                and malformed_file.exists()
                and mat_path.read_bytes() == malformed_before,
                "malformed material state must fail closed before deleting files",
            )

            upload_materials = {"keep": {"url": "https://example.com/keep", "unknown": True}}
            upload_assignments = {"s-upload": ["DIR:\uc5c5\ub85c\ub4dc"]}
            upload_pages = {"materials": "\uc5c5\ub85c\ub4dc", "unknown": {"keep": True}}
            write_json(mat_path, upload_materials)
            write_json(assign_path, upload_assignments)
            write_json(page_path, upload_pages)
            upload = client.post(
                "/api/fs/upload",
                data={
                    "dst": "\uc5c5\ub85c\ub4dc",
                    "files": (io.BytesIO(b"upload"), "\uc0c8 \ud30c\uc77c.pdf"),
                },
                content_type="multipart/form-data",
            )
            upload_payload = upload.get_json() or {}
            check(
                upload.status_code == 200
                and upload_payload.get("files")
                and upload_payload["files"][0]["path"] == "\uc5c5\ub85c\ub4dc/\uc0c8 \ud30c\uc77c.pdf"
                and (files_dir / "\uc5c5\ub85c\ub4dc" / "\uc0c8 \ud30c\uc77c.pdf").exists(),
                "upload must preserve a safe Korean filename",
            )
            check(
                read_json(assign_path)["s-upload"]
                == ["DIR:\uc5c5\ub85c\ub4dc", "/files/\uc5c5\ub85c\ub4dc/\uc0c8 \ud30c\uc77c.pdf"],
                "upload must add successful files to matching DIR assignments",
            )
            check(
                read_json(mat_path) == upload_materials
                and read_json(page_path) == upload_pages,
                "upload auto-assignment must preserve unrelated material and page-folder state",
            )
    finally:
        for name, value in original.items():
            setattr(api_fs, name, value)


def run_file_manager_client_contract_checks() -> None:
    source = (ROOT / "static/js/file-manage.js").read_text(encoding="utf-8")
    html = (ROOT / "static/file-manage.html").read_text(encoding="utf-8")
    check(
        source.count("const snapshot = await getAssignSnapshot();") >= 2
        and 'headers["If-Match"] = revision' in source
        and 'r.headers.get("X-Material-State-Revision")' in source,
        "file-manager assignment mutations must re-read and conditionally save one revisioned snapshot",
    )
    check(
        'if (revision) headers["If-Match"] = revision;' in source,
        "the newly loaded file-manager client must remain compatible with the currently running old backend",
    )
    check(
        'r.status===409' in source
        and "다른 화면에서 배정 또는 파일 정보가 변경되었습니다." in source
        and 'r.status===503' in source,
        "file-manager must explain stale conflicts and material-state write degradation",
    )
    check(
        'await jpost("/api/mat-assign", assigns)' not in source
        and 'const cur = await jget("/api/mat-assign")' not in source,
        "legacy unversioned whole-map assignment writes must stay retired",
    )
    check(
        "/js/file-manage.js?v=20260824a" in html,
        "file-manager HTML must load the revision-aware client without a stale browser cache",
    )

def main() -> int:
    run_material_reference_rule_checks()
    run_material_state_recovery_checks()
    run_material_assignment_route_checks()
    run_file_reference_route_checks()
    run_file_manager_client_contract_checks()
    print("material reference rules, recovery, and file routes passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
