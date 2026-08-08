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
        pinned = repo.set_pinned("student-a", first["id"], True)
        check(pinned is not None and pinned["pinned"] is True, "pinning a note failed")
        check(repo.set_pinned("student-b", first["id"], True) is None, "cross-student pin must fail")
        check(repo.delete("student-b", first["id"]) is False, "cross-student delete must fail")

        reloaded = AssistantStudentNoteRepository(db_path=str(db_path)).list_for_student("student-a")
        check(any(note["content"] == "수정됨\n쉼표, 유지" for note in reloaded), "notes must persist across repository instances")

        with closing(sqlite3.connect(db_path)) as con:
            columns = {row[1] for row in con.execute("PRAGMA table_info(assistant_student_notes)")}
        check(
            {"id", "student_id", "content", "created_by", "updated_by", "pinned", "created_at", "updated_at"}.issubset(columns),
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
            empty_note = empty.get_json()["note"]

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
            listed_notes = listed.get_json()["notes"]
            check(listed.status_code == 200 and listed_notes[0]["id"] == note["id"], "note list failed")
            check(
                {item["id"] for item in listed_notes} >= {empty_note["id"], note["id"]},
                "creating a new note must not replace an existing note",
            )

            wrong_student = client.patch(
                f"/api/assistant-student-notes/{note['id']}",
                json={"student_id": "student-b", "content": "잘못된 수정", "author": "세빈"},
                headers=admin_headers,
            )
            check(wrong_student.status_code == 404, "student_id and note id must be verified together")

            wrong_delete = client.delete(
                f"/api/assistant-student-notes/{note['id']}",
                json={"student_id": "student-b"},
                headers=admin_headers,
            )
            check(wrong_delete.status_code == 404, "cross-student delete must fail")

            wrong_pin = client.patch(
                f"/api/assistant-student-notes/{note['id']}/pin",
                json={"student_id": "student-b", "pinned": True},
                headers=admin_headers,
            )
            check(wrong_pin.status_code == 404, "cross-student pin must fail")

            invalid_pin = client.patch(
                f"/api/assistant-student-notes/{note['id']}/pin",
                json={"student_id": "student-a", "pinned": "true"},
                headers=admin_headers,
            )
            check(invalid_pin.status_code == 400, "pin value must be a boolean")

            pinned = client.patch(
                f"/api/assistant-student-notes/{note['id']}/pin",
                json={"student_id": "student-a", "pinned": True},
                headers=admin_headers,
            )
            check(pinned.status_code == 200 and pinned.get_json()["note"]["pinned"] is True, "route pin failed")

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
            remaining = client.get(
                "/api/assistant-student-notes?student_id=student-a",
                headers=admin_headers,
            ).get_json()["notes"]
            check(
                all(item["id"] != note["id"] for item in remaining)
                and any(item["id"] == empty_note["id"] for item in remaining),
                "delete must remove only the requested note",
            )
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
    check("조교 메모방" in tooltip_source, "assistant memo title is missing")
    check('data-note-list role="log"' in tooltip_source, "scrollable assistant comment thread is missing")
    check("댓글 등록" in tooltip_source and "data-note-save" in tooltip_source, "comment composer is missing")
    check('data-note-author="귤" aria-pressed="false">규리</button>' in tooltip_source, "gyuri author button label is missing")
    check(
        "content.textContent = String(note.content || '')" in notes_source,
        "note text must use safe text rendering",
    )
    check("localStorage" not in notes_source and "sessionStorage" not in notes_source, "assistant notes must not use browser storage")
    for author in ("귤", "세빈", "동훈", "하영"):
        check(f'data-note-author="{author}"' in tooltip_source, f"missing author button: {author}")
        check(f'button[data-note-author="{author}"]' in admin_css, f"missing author color style: {author}")
        check(
            f'.assistant-student-notes[data-note-selected-author="{author}"] .assistant-note-input' in admin_css,
            f"missing selected-author composer color: {author}",
        )
        check(
            f'.assistant-note-item[data-note-author="{author}"]' in admin_css,
            f"missing comment author color: {author}",
        )
    check(
        ".assistant-note-item-content" in admin_css
        and "color: var(--assistant-note-item-color);" in admin_css,
        "comment content must retain its author's assigned color",
    )
    check("author: selectedAuthor" in notes_source, "selected author must be included in save requests")
    check("root.dataset.noteSelectedAuthor" in notes_source, "selected author must drive the pressed author button")
    check(
        ".assistant-note-author-buttons [data-note-author]" in notes_source,
        "author selection must not treat rendered comment cards as author buttons",
    )
    check("article.dataset.noteAuthor = author" in notes_source, "saved author must label each rendered comment")
    check("article.dataset.notePinned = pinned ? 'true' : 'false'" in notes_source, "pin state must label each rendered comment")
    check("pinButton.dataset.notePin" in notes_source and "메모 고정" in notes_source, "each comment must expose a pin control")
    check("const AUTHOR_LABELS" in notes_source and "귤: '규리'" in notes_source, "author labels must include 규리")
    check(
        "sendRequest('/api/assistant-student-notes', 'POST'" in notes_source,
        "comment registration must always create a new note",
    )
    check("currentNote" not in notes_source, "comment UI must not overwrite an existing note")
    check(
        "sendRequest(`/api/assistant-student-notes/${noteId}/pin`, 'PATCH'" in notes_source,
        "pin control must call the student-scoped pin endpoint",
    )
    check("deleteButton.dataset.noteDelete" in notes_source, "each comment must expose a delete button")
    check(
        "sendRequest(`/api/assistant-student-notes/${noteId}`, 'DELETE'" in notes_source,
        "delete button must call the student-scoped delete endpoint",
    )
    check("window.confirm('이 댓글을 삭제할까요?" in notes_source, "delete must require confirmation")
    check("notes = notes.filter((item) => Number(item.id) !== noteId)" in notes_source, "delete must remove only one comment")
    check("assistant-note-delete" in admin_css and ":disabled" in admin_css, "delete button needs scoped and pending styles")
    check("assistant-note-pin" in admin_css and ".assistant-note-item.is-pinned" in admin_css, "pinned comments need scoped styles")
    check("displayNotes = [" in notes_source and "isNotePinned(note)" in notes_source, "pinned comments must render before regular comments")
    check("notes.slice().reverse()" in notes_source, "existing notes must render from oldest to newest")
    check("list.scrollTop = list.scrollHeight" in notes_source, "comment thread must scroll to the latest note")
    check("notes = [data.note, ...notes.filter" in notes_source, "new comments must be added to the loaded thread")
    check("if (!content)" in notes_source, "blank comments must be blocked in the composer")
    check("input.value = ''" in notes_source, "the composer must stay separate from saved comments")
    check("max-height: 210px" in admin_css and "overflow-y: auto" in admin_css, "comment thread must be scrollable")
    check("white-space: pre-wrap" in admin_css, "comment line breaks must be preserved")


def main() -> int:
    repository_checks()
    route_checks()
    source_boundary_checks()
    print("assistant student notes checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
