from __future__ import annotations

import datetime as dt
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from core.assistant_student_notes import AssistantStudentNoteRepository
from core.paths import STU_PATH
from core.storage import load


bp_api_assistant_notes = Blueprint("api_assistant_notes", __name__)
ADMIN_REFERER_PATHS = {"/admin", "/dh1130"}
ALL_STUDENTS_REFERER_PATHS = {"/students", "/all.html"}
ALL_STUDENTS_ALLOWED_METHODS = {"GET", "POST"}
MAX_NOTE_LENGTH = 5000
ALLOWED_NOTE_AUTHORS = ("귤", "세빈", "동훈", "하영")


def get_repository() -> AssistantStudentNoteRepository:
    return AssistantStudentNoteRepository()


def student_exists(student_id: str) -> bool:
    students = load(STU_PATH) or []
    return any(str(student.get("id") or "") == student_id for student in students if isinstance(student, dict))


def _admin_surface_allowed() -> bool:
    raw = (request.headers.get("Referer") or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except Exception:
        return False
    host = (request.host or "").lower()
    if parsed.netloc and parsed.netloc.lower() != host:
        return False
    path = parsed.path.rstrip("/") or "/"
    if path in ADMIN_REFERER_PATHS:
        return True
    return path in ALL_STUDENTS_REFERER_PATHS and request.method in ALL_STUDENTS_ALLOWED_METHODS


@bp_api_assistant_notes.before_request
def require_admin_surface():
    if not _admin_surface_allowed():
        return jsonify({"ok": False, "error": "assistant notes are not available from this surface"}), 403


def _request_body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _student_id_from(body: dict | None = None) -> str:
    source = body if isinstance(body, dict) else request.args
    return str(source.get("student_id") or "").strip()


def _validated_content(body: dict) -> tuple[str, tuple | None]:
    content = str(body.get("content") or "").strip()
    if len(content) > MAX_NOTE_LENGTH:
        return "", (jsonify({"ok": False, "error": "content too long"}), 400)
    return content, None


def _validated_author(body: dict) -> tuple[str, tuple | None]:
    author = str(body.get("author") or "").strip()
    if author not in ALLOWED_NOTE_AUTHORS:
        return "", (jsonify({"ok": False, "error": "invalid author"}), 400)
    return author, None


def _validated_pinned(body: dict) -> tuple[bool, tuple | None]:
    pinned = body.get("pinned")
    if not isinstance(pinned, bool):
        return False, (jsonify({"ok": False, "error": "pinned must be a boolean"}), 400)
    return pinned, None


def _validated_remind_on(body: dict) -> tuple[str, tuple | None]:
    remind_on = body.get("remind_on", "")
    if remind_on is None:
        remind_on = ""
    if not isinstance(remind_on, str):
        return "", (jsonify({"ok": False, "error": "remind_on must be an ISO date"}), 400)
    remind_on = remind_on.strip()
    if remind_on:
        try:
            parsed = dt.date.fromisoformat(remind_on)
        except ValueError:
            return "", (jsonify({"ok": False, "error": "remind_on must be an ISO date"}), 400)
        if parsed.isoformat() != remind_on:
            return "", (jsonify({"ok": False, "error": "remind_on must be an ISO date"}), 400)
    return remind_on, None


def _validated_completed(body: dict) -> tuple[bool, tuple | None]:
    completed = body.get("completed")
    if not isinstance(completed, bool):
        return False, (jsonify({"ok": False, "error": "completed must be a boolean"}), 400)
    return completed, None


def _validate_student(student_id: str):
    if not student_id:
        return jsonify({"ok": False, "error": "missing student_id"}), 400
    if not student_exists(student_id):
        return jsonify({"ok": False, "error": "student not found"}), 404
    return None


@bp_api_assistant_notes.get("/api/assistant-student-notes")
def list_notes():
    student_id = _student_id_from()
    error = _validate_student(student_id)
    if error:
        return error
    return jsonify({"ok": True, "notes": get_repository().list_for_student(student_id)})


@bp_api_assistant_notes.post("/api/assistant-student-notes")
def create_note():
    body = _request_body()
    student_id = _student_id_from(body)
    error = _validate_student(student_id)
    if error:
        return error
    content, content_error = _validated_content(body)
    if content_error:
        return content_error
    author, author_error = _validated_author(body)
    if author_error:
        return author_error
    remind_on, remind_error = _validated_remind_on(body)
    if remind_error:
        return remind_error
    note = get_repository().create(student_id, content, author, remind_on)
    return jsonify({"ok": True, "note": note}), 201


@bp_api_assistant_notes.patch("/api/assistant-student-notes/<int:note_id>")
def update_note(note_id: int):
    body = _request_body()
    student_id = _student_id_from(body)
    error = _validate_student(student_id)
    if error:
        return error
    content, content_error = _validated_content(body)
    if content_error:
        return content_error
    author, author_error = _validated_author(body)
    if author_error:
        return author_error
    note = get_repository().update(student_id, note_id, content, author)
    if note is None:
        return jsonify({"ok": False, "error": "note not found"}), 404
    return jsonify({"ok": True, "note": note})


@bp_api_assistant_notes.patch("/api/assistant-student-notes/<int:note_id>/pin")
def pin_note(note_id: int):
    body = _request_body()
    student_id = _student_id_from(body)
    error = _validate_student(student_id)
    if error:
        return error
    pinned, pinned_error = _validated_pinned(body)
    if pinned_error:
        return pinned_error
    note = get_repository().set_pinned(student_id, note_id, pinned)
    if note is None:
        return jsonify({"ok": False, "error": "note not found"}), 404
    return jsonify({"ok": True, "note": note})


@bp_api_assistant_notes.patch("/api/assistant-student-notes/<int:note_id>/reminder")
@bp_api_assistant_notes.patch("/api/assistant-student-notes/<int:note_id>/remind")
def remind_note(note_id: int):
    body = _request_body()
    student_id = _student_id_from(body)
    error = _validate_student(student_id)
    if error:
        return error
    remind_on, remind_error = _validated_remind_on(body)
    if remind_error:
        return remind_error
    note = get_repository().set_remind_on(student_id, note_id, remind_on)
    if note is None:
        return jsonify({"ok": False, "error": "note not found"}), 404
    return jsonify({"ok": True, "note": note})


@bp_api_assistant_notes.patch("/api/assistant-student-notes/<int:note_id>/complete")
def complete_note(note_id: int):
    body = _request_body()
    student_id = _student_id_from(body)
    error = _validate_student(student_id)
    if error:
        return error
    completed, completed_error = _validated_completed(body)
    if completed_error:
        return completed_error
    note = get_repository().set_completed(student_id, note_id, completed)
    if note is None:
        return jsonify({"ok": False, "error": "note not found"}), 404
    return jsonify({"ok": True, "note": note})


@bp_api_assistant_notes.delete("/api/assistant-student-notes/<int:note_id>")
def delete_note(note_id: int):
    body = _request_body()
    student_id = _student_id_from(body)
    error = _validate_student(student_id)
    if error:
        return error
    if not get_repository().delete(student_id, note_id):
        return jsonify({"ok": False, "error": "note not found"}), 404
    return jsonify({"ok": True})
