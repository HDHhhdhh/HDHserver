# /// script
# requires-python = ">=3.11"
# dependencies = ["flask>=2"]
# ///
# How to run:
#   python scripts/verify_admin_operation_notes.py

from __future__ import annotations

import pathlib
import re
import sqlite3
import sys
import tempfile
from contextlib import closing

from flask import Flask


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def repository_checks() -> None:
    from core.admin_operation_notes import AdminOperationNoteRepository

    with tempfile.TemporaryDirectory(prefix="verify-admin-operation-notes-") as tmp:
        db_path = pathlib.Path(tmp) / "app.sqlite"
        repository = AdminOperationNoteRepository(db_path=str(db_path))

        first = repository.create("상담 답변 확인")
        second = repository.create("보강 일정 점검")

        notes = repository.list_all()
        check([note["id"] for note in notes] == [second["id"], first["id"]], "newest note must be first")
        check(notes[0]["content"] == "보강 일정 점검", "stored content changed")

        reloaded = AdminOperationNoteRepository(db_path=str(db_path)).list_all()
        check([note["id"] for note in reloaded] == [second["id"], first["id"]], "notes must persist")
        check(repository.delete(first["id"]) is True, "existing note delete failed")
        check(repository.delete(first["id"]) is False, "missing note delete must report false")

        with closing(sqlite3.connect(db_path)) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(admin_operation_notes)")}
        check({"id", "content", "created_at"}.issubset(columns), "admin_operation_notes schema is incomplete")


def route_checks() -> None:
    from core.admin_operation_notes import AdminOperationNoteRepository
    from routes import api_admin_operation_notes

    with tempfile.TemporaryDirectory(prefix="verify-admin-operation-notes-route-") as tmp:
        repository = AdminOperationNoteRepository(db_path=str(pathlib.Path(tmp) / "app.sqlite"))
        original_factory = api_admin_operation_notes.get_repository
        api_admin_operation_notes.get_repository = lambda: repository
        try:
            app = Flask(__name__)
            app.register_blueprint(api_admin_operation_notes.bp_api_admin_operation_notes)
            client = app.test_client()
            admin_headers = {"Referer": "http://localhost/admin"}

            denied = client.get("/api/admin-operation-notes")
            check(denied.status_code == 403, "request outside the admin surface must return 403")
            cross_origin = client.get(
                "/api/admin-operation-notes",
                headers={"Referer": "http://example.com/admin"},
            )
            check(cross_origin.status_code == 403, "cross-origin referer must return 403")

            empty = client.post(
                "/api/admin-operation-notes",
                json={"content": "   "},
                headers=admin_headers,
            )
            check(empty.status_code == 400, "blank operation note must be rejected")
            invalid_type = client.post(
                "/api/admin-operation-notes",
                json={"content": ["not", "text"]},
                headers=admin_headers,
            )
            check(invalid_type.status_code == 400, "non-text operation note must be rejected")
            too_long = client.post(
                "/api/admin-operation-notes",
                json={"content": "가" * 301},
                headers=admin_headers,
            )
            check(too_long.status_code == 400, "overlong operation note must be rejected")

            created = client.post(
                "/api/admin-operation-notes",
                json={"content": "  보강\n일정   점검  "},
                headers=admin_headers,
            )
            check(created.status_code == 201, "operation note create failed")
            note = created.get_json()["note"]
            check(note["content"] == "보강 일정 점검", "operation note whitespace normalization failed")

            listed = client.get("/api/admin-operation-notes", headers=admin_headers)
            check(listed.status_code == 200, "operation note list failed")
            check(listed.get_json()["notes"][0]["id"] == note["id"], "created note is missing from list")

            deleted = client.delete(f"/api/admin-operation-notes/{note['id']}", headers=admin_headers)
            check(deleted.status_code == 200, "operation note delete failed")
            missing = client.delete(f"/api/admin-operation-notes/{note['id']}", headers=admin_headers)
            check(missing.status_code == 404, "missing operation note delete must return 404")
        finally:
            api_admin_operation_notes.get_repository = original_factory


def source_contract_checks() -> None:
    html = (ROOT / "static/admin.html").read_text("utf-8-sig")
    css = (ROOT / "static/css/admin.css").read_text("utf-8-sig")
    main_source = (ROOT / "static/js/admin/main.js").read_text("utf-8-sig")
    feature_source = (ROOT / "static/js/admin/features/adminOperationNotes.js").read_text("utf-8-sig")
    demo_source = (ROOT / "static/js/admin/demo/fetch.js").read_text("utf-8-sig")
    demo_bootstrap_source = (ROOT / "static/js/admin/demo/bootstrap.js").read_text("utf-8-sig")
    demo_contract_source = (ROOT / "static/js/admin/demo/operationNotesContract.js").read_text("utf-8-sig")

    for element_id in (
        "adminOperationNotes",
        "adminOperationNoteForm",
        "adminOperationNoteInput",
        "adminOperationNoteList",
    ):
        check(f'id="{element_id}"' in html, f"missing admin operation note element: {element_id}")
    check("initAdminOperationNotes" in main_source, "admin operation notes must initialize from main.js")
    check("textContent" in feature_source, "operation note content must render with textContent")
    check("localStorage" not in feature_source and "sessionStorage" not in feature_source, "live notes must use server persistence")
    check("method: 'DELETE'" in feature_source, "operation note remove action is missing")
    check(
        "applyOperationNotesRequest" in demo_source
        and "applyOperationNotesRequest" in demo_bootstrap_source
        and "/api/admin-operation-notes" in demo_contract_source,
        "demo API parity must use the shared operation-note contract",
    )
    placement = re.search(r"body\.admin \.admin-operation-notes\s*\{(?P<body>.*?)\}", css, re.S)
    check(
        placement is not None
        and "grid-column: 3" in placement.group("body")
        and "--admin-note-responsive-height: 250px" in placement.group("body"),
        "memo card must occupy only center column 3 and own its compact height token",
    )
    responsive = re.search(
        r"@media \(max-width: 1500px\).*?body\.admin \.admin-operation-notes\s*\{(?P<body>.*?)\}",
        css,
        re.S,
    )
    check(
        responsive is not None
        and "height: var(--admin-note-responsive-height)" in responsive.group("body")
        and "max-height: var(--admin-note-responsive-height)" in responsive.group("body"),
        "responsive memo card must remain bounded so its list scrolls internally",
    )


def main() -> int:
    repository_checks()
    route_checks()
    source_contract_checks()
    print("admin operation notes checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
