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
        reminded = repo.set_remind_on("student-a", first["id"], "2026-08-15")
        check(reminded is not None and reminded["remind_on"] == "2026-08-15", "setting a reminder date failed")
        completed = repo.set_completed("student-a", first["id"], True)
        check(completed is not None and completed["completed_at"], "completing a reminder failed")
        reopened = repo.set_completed("student-a", first["id"], False)
        check(reopened is not None and reopened["completed_at"] == "", "clearing completed state failed")
        check(repo.set_remind_on("student-b", first["id"], "2026-08-16") is None, "cross-student reminder must fail")
        check(repo.delete("student-b", first["id"]) is False, "cross-student delete must fail")

        reloaded = AssistantStudentNoteRepository(db_path=str(db_path)).list_for_student("student-a")
        check(any(note["content"] == "수정됨\n쉼표, 유지" for note in reloaded), "notes must persist across repository instances")

        with closing(sqlite3.connect(db_path)) as con:
            columns = {row[1] for row in con.execute("PRAGMA table_info(assistant_student_notes)")}
        check(
            {"id", "student_id", "content", "created_by", "updated_by", "pinned", "remind_on", "completed_at", "created_at", "updated_at"}.issubset(columns),
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
            check(note["remind_on"] == "" and note["completed_at"] == "", "new notes must expose empty reminder state")

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

            invalid_reminder = client.patch(
                f"/api/assistant-student-notes/{note['id']}/reminder",
                json={"student_id": "student-a", "remind_on": "2026-8-15"},
                headers=admin_headers,
            )
            check(invalid_reminder.status_code == 400, "invalid reminder date must be rejected")

            reminded = client.patch(
                f"/api/assistant-student-notes/{note['id']}/reminder",
                json={"student_id": "student-a", "remind_on": "2026-08-15"},
                headers=admin_headers,
            )
            check(reminded.status_code == 200 and reminded.get_json()["note"]["remind_on"] == "2026-08-15", "route reminder update failed")

            completed = client.patch(
                f"/api/assistant-student-notes/{note['id']}/complete",
                json={"student_id": "student-a", "completed": True},
                headers=admin_headers,
            )
            check(completed.status_code == 200 and completed.get_json()["note"]["completed_at"], "route completion failed")

            reopened = client.patch(
                f"/api/assistant-student-notes/{note['id']}/complete",
                json={"student_id": "student-a", "completed": False},
                headers=admin_headers,
            )
            check(reopened.status_code == 200 and reopened.get_json()["note"]["completed_at"] == "", "route completion clear failed")

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
    log_modal_source = (ROOT / "static/js/admin/features/logModal.js").read_text("utf-8-sig")
    notes_source = (ROOT / "static/js/admin/features/assistantStudentNotes.js").read_text("utf-8-sig")
    admin_css = (ROOT / "static/css/admin.css").read_text("utf-8-sig")
    check("assistantStudentNotes" not in tooltip_source, "student info/homework popup must not retain assistant notes")
    check("assistantStudentNotesTemplate" in log_modal_source, "main popup must mount assistant notes")
    check('id="logTitle"' not in log_modal_source and "메모 쓰레드" not in log_modal_source, "thread popup must not render the oversized student-name title")
    check(
        'class="log-header-row"' not in log_modal_source
        and 'id="logClose"' not in log_modal_source
        and "body.admin #logModal .log-card" in admin_css
        and "padding: 0 !important;" in admin_css,
        "thread popup must remove the empty white header and outer padding",
    )
    check("<h3>조교 메모</h3>" in notes_source, "assistant memo title is missing")
    check(
        "data-note-count" not in notes_source
        and "assistant-note-count" not in notes_source
        and "댓글 ${notes.length}개" not in notes_source,
        "thread popup must not render a comment-count badge",
    )
    check(
        "data-note-save-close" in notes_source
        and ">저장 후 닫기</button>" in notes_source
        and "data-note-close" in notes_source
        and ">닫기</button>" in notes_source
        and "assistant-note-heading-actions" in admin_css
        and "assistant-note-heading-button" in admin_css,
        "assistant memo heading must expose save-and-close and close actions",
    )
    check(
        "await saveNote({ closeAfter: true })" in notes_source
        and "admin:assistant-notes-close" in notes_source
        and "logModal.addEventListener('admin:assistant-notes-close', close)" in log_modal_source,
        "save-and-close must reuse comment creation and close only through the popup owner",
    )
    check("조교 메모방" not in notes_source, "legacy assistant memo title remains")
    check("data-note-remind-input" in notes_source and "assistant-note-compose-reminder" in notes_source, "confirmation-date composer is missing")

    check('data-note-list role="log"' in notes_source, "scrollable assistant comment thread is missing")
    check("댓글 등록" in notes_source and "data-note-save" in notes_source, "comment composer is missing")
    check('data-note-author="귤" aria-pressed="false">규리</button>' in notes_source, "gyuri author button label is missing")
    check(
        "content.textContent = String(note.content || '')" in notes_source,
        "note text must use safe text rendering",
    )
    check("localStorage" not in notes_source and "sessionStorage" not in notes_source, "assistant notes must not use browser storage")
    for author in ("귤", "세빈", "동훈", "하영"):
        check(f'data-note-author="{author}"' in notes_source, f"missing author button: {author}")
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
    check(
        "--assistant-note-body-font-size: 26px;" in admin_css
        and "font-size: var(--assistant-note-body-font-size);" in admin_css,
        "assistant note content and inputs must use the doubled 26px type scale",
    )
    check(
        "--assistant-note-author-font-size: 28px;" in admin_css
        and "font-size: var(--assistant-note-author-font-size);" in admin_css
        and "font-weight: 900;" in admin_css,
        "assistant note author names must stay larger and bolder at the doubled 28px scale",
    )
    check(
        "body.admin #logModal .assistant-note-heading h3" in admin_css
        and "body.admin #logModal .assistant-note-mode-button" in admin_css
        and "font-size: 24px;" in admin_css
        and "font-size: 21px;" in admin_css
        and "font-size: 22px;" in admin_css
        and "font-size: 20px;" in admin_css,
        "all assistant-note text roles must use the doubled type scale",
    )
    check(
        "font-size:72px;" not in log_modal_source
        and "font-size:40px;" not in log_modal_source
        and "font-size:48px;" not in log_modal_source
        and "font-size:32px;" not in log_modal_source,
        "thread popup must not restore the removed oversized title or close-button type scales",
    )
    check(
        "@media (max-width: 600px)" in admin_css
        and ".assistant-note-reminder-body > .assistant-note-item-content" in admin_css
        and "grid-column: 1 / -1;" in admin_css,
        "larger reminder-note text must use the full mobile card width",
    )
    check("author: selectedAuthor" in notes_source, "selected author must be included in save requests")
    check("root.dataset.noteSelectedAuthor" in notes_source, "selected author must drive the pressed author button")
    check("body.admin #logModal .assistant-student-notes" in admin_css, "assistant notes styles must be scoped to the main popup")
    check("body.admin #adminSchoolTip .assistant-student-notes" not in admin_css, "tooltip assistant-note styles must be removed")
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
    check(
        "const newestFirst = notes.slice()" in notes_source
        and "compareNewestNoteFirst(left, right)" in notes_source
        and "notes.slice().reverse()" not in notes_source,
        "existing notes must render from newest to oldest",
    )
    check(
        "remind_on" in notes_source
        and "assistant-note-reminder-info" in notes_source
        and "assistant-note-reminder-dates" in notes_source
        and "assistant-note-reminder-arrow" in notes_source,
        "saved reminder notes must render compact written-to-target dates",
    )
    check(
        "assistant-note-followup" not in notes_source
        and "assistant-note-followup" not in admin_css
        and "assistant-note-complete" not in notes_source
        and "assistant-note-complete" not in admin_css,
        "saved reminder cards must not contain inline date or completion controls",
    )
    check(
        "editButton.dataset.noteEdit" in notes_source
        and "assistant-note-edit-save" in notes_source,
        "each comment must support compact content editing",
    )
    check(
        ".assistant-note-item.has-reminder .assistant-note-action-group" in admin_css
        and ".assistant-note-reminder-body.is-stacked" in admin_css
        and "header.append(reminderInfoRow);" in notes_source
        and "reminderBody.append(authorGroup, content, actionGroup);" in notes_source
        and "header.append(reminderInfoRow, actionGroup)" not in notes_source,
        "reminder dates need their own row above the author, content, and actions",
    )
    check("assistant-note-compose-reminder" in admin_css, "confirmation-date composer style is missing")
    check("list.scrollTop = 0" in notes_source, "newest-first comment thread must stay scrolled to the top")
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
