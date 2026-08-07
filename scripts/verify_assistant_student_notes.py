from __future__ import annotations

import pathlib
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
    from core.assistant_student_notes import AssistantStudentNoteRepository

    with tempfile.TemporaryDirectory(prefix="verify-assistant-notes-") as tmp:
        db_path = pathlib.Path(tmp) / "app.sqlite"
        repo = AssistantStudentNoteRepository(db_path=str(db_path))

        first = repo.create("student-a", "첫 줄\n둘째 줄, 한글 메모", "귤")
        second = repo.create("student-a", "최신 메모", "귤")
        other = repo.create("student-b", "다른 학생 메모", "귤")

        notes = repo.list_for_student("student-a")
        check([note["id"] for note in notes] == [second["id"], first["id"]], "latest note must be first")
        check(all(note["student_id"] == "student-a" for note in notes), "student notes must not mix")
        check(other["id"] not in {note["id"] for note in notes}, "other student note leaked")

        check(repo.update("student-b", first["id"], "섞이면 안 됨", "세빈") is None, "cross-student update must fail")
        updated = repo.update("student-a", first["id"], "수정됨\n쉼표, 유지", "세빈")
        check(updated is not None and updated["content"] == "수정됨\n쉼표, 유지", "update failed")
        check(updated["created_by"] == "귤" and updated["updated_by"] == "세빈", "last editor must be tracked separately")
        check(repo.delete("student-b", first["id"]) is False, "cross-student delete must fail")

        reloaded = AssistantStudentNoteRepository(db_path=str(db_path)).list_for_student("student-a")
        check(any(note["content"] == "수정됨\n쉼표, 유지" for note in reloaded), "notes must persist across repository instances")

        with closing(sqlite3.connect(db_path)) as con:
            columns = {row[1] for row in con.execute("PRAGMA table_info(assistant_student_notes)")}
        check(
            {"id", "student_id", "content", "created_by", "updated_by", "created_at", "updated_at"}.issubset(columns),
            "assistant_student_notes schema is incomplete",
        )


def route_checks() -> None:
    from core.assistant_student_notes import AssistantStudentNoteRepository
    from routes import api_assistant_notes

    with tempfile.TemporaryDirectory(prefix="verify-assistant-notes-route-") as tmp:
        repo = AssistantStudentNoteRepository(db_path=str(pathlib.Path(tmp) / "app.sqlite"))
        original_factory = api_assistant_notes.get_repository
        original_student_exists = api_assistant_notes.student_exists
        api_assistant_notes.get_repository = lambda: repo
        api_assistant_notes.student_exists = lambda sid: sid in {"student-a", "student-b"}
        try:
            app = Flask(__name__)
            app.register_blueprint(api_assistant_notes.bp_api_assistant_notes)
            client = app.test_client()
            admin_headers = {"Referer": "http://localhost/admin"}

            denied = client.get("/api/assistant-student-notes?student_id=student-a")
            check(denied.status_code == 403, "request outside admin surface must return 403")
            denied_student = client.get(
                "/api/assistant-student-notes?student_id=student-a",
                headers={"Referer": "http://localhost/student/student-a"},
            )
            check(denied_student.status_code == 403, "student page request must return 403")

            empty = client.post(
                "/api/assistant-student-notes",
                json={"student_id": "student-a", "content": "   ", "author": "귤"},
                headers=admin_headers,
            )
            check(
                empty.status_code == 201 and empty.get_json()["note"]["content"] == "",
                "empty note must be saved as a blank memo",
            )

            invalid_author = client.post(
                "/api/assistant-student-notes",
                json={"student_id": "student-a", "content": "메모", "author": "기타"},
                headers=admin_headers,
            )
            check(invalid_author.status_code == 400, "unknown note author must be rejected")

            created = client.post(
                "/api/assistant-student-notes",
                json={"student_id": "student-a", "content": "한글\n쉼표, 긴 문장", "author": "귤"},
                headers=admin_headers,
            )
            check(created.status_code == 201, "note create failed")
            note = created.get_json()["note"]

            listed = client.get(
                "/api/assistant-student-notes?student_id=student-a",
                headers=admin_headers,
            )
            check(listed.status_code == 200 and listed.get_json()["notes"][0]["id"] == note["id"], "note list failed")

            wrong_student = client.patch(
                f"/api/assistant-student-notes/{note['id']}",
                json={"student_id": "student-b", "content": "잘못된 수정", "author": "세빈"},
                headers=admin_headers,
            )
            check(wrong_student.status_code == 404, "student_id and note id must be verified together")

            updated = client.patch(
                f"/api/assistant-student-notes/{note['id']}",
                json={"student_id": "student-a", "content": "수정 완료", "author": "세빈"},
                headers=admin_headers,
            )
            check(updated.status_code == 200 and updated.get_json()["note"]["updated_by"] == "세빈", "route update failed")

            deleted = client.delete(
                f"/api/assistant-student-notes/{note['id']}",
                json={"student_id": "student-a"},
                headers=admin_headers,
            )
            check(deleted.status_code == 200, "route delete failed")
        finally:
            api_assistant_notes.get_repository = original_factory
            api_assistant_notes.student_exists = original_student_exists


def source_boundary_checks() -> None:
    export_source = (ROOT / "static/js/admin/features/exportLogs.js").read_text("utf-8-sig")
    check("assistant-student-notes" not in export_source, "assistant note API must not enter CSV export code")
    check("assistantStudentNotes" not in export_source, "assistant notes must not enter export projection")

    tooltip_source = (ROOT / "static/js/admin/features/hoverTooltip.js").read_text("utf-8-sig")
    notes_source = (ROOT / "static/js/admin/features/assistantStudentNotes.js").read_text("utf-8-sig")
    admin_css = (ROOT / "static/css/admin.css").read_text("utf-8-sig")
    check("assistantStudentNotes" in tooltip_source, "student sidebar must mount assistant notes")
    check("메모 추가" not in tooltip_source and "data-note-save" in tooltip_source, "assistant memo must use one editable save field")
    check("조교 메모방" in tooltip_source, "assistant memo title is missing")
    check('data-note-author="귤" aria-pressed="false">규리</button>' in tooltip_source, "gyuri author button label is missing")
    check("textContent" in notes_source, "note text must use safe text rendering")
    check("localStorage" not in notes_source and "sessionStorage" not in notes_source, "assistant notes must not use browser storage")
    for author in ("귤", "세빈", "동훈", "하영"):
        check(f'data-note-author="{author}"' in tooltip_source, f"missing author button: {author}")
        check(f'button[data-note-author="{author}"]' in admin_css, f"missing author color style: {author}")
        check(
            f'.assistant-student-notes[data-note-color-author="{author}"] .assistant-note-input' in admin_css,
            f"missing persisted note color style: {author}",
        )
    check("author: selectedAuthor" in notes_source, "selected author must be included in save requests")
    check("root.dataset.noteSelectedAuthor" in notes_source, "selected author must drive the pressed author button")
    check("root.dataset.noteColorAuthor" in notes_source, "saved author must independently drive persisted note color")
    check("const AUTHOR_TAGS" in notes_source and "귤: '규리'" in notes_source, "author tags must include 규리")
    check("formatMemoDate(now)" in notes_source, "author tag must include the current month and day")
    check("syncAuthorTag(input, author, draftAuthor)" in notes_source, "first author click must insert a dated author tag")
    check("draftAuthor = ''" in notes_source, "loaded saved author must not suppress the first dated tag")
    check("switchesAuthor" in notes_source and "value.endsWith('\\n')" in notes_source, "author handoff must append a new tagged line")
    check("빈 내용은 저장할 수 없습니다." not in notes_source, "blank memo saves must not be blocked in the UI")
    check("마지막 저장" in notes_source and "AUTHOR_TAGS[savedAuthor]" in notes_source, "last saved date and author must be displayed")
    check("${createdBy}-${updatedBy}" not in notes_source, "author handoff trail must not be displayed")


def main() -> int:
    repository_checks()
    route_checks()
    source_boundary_checks()
    print("assistant student notes checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
