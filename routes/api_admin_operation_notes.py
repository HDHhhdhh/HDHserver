from __future__ import annotations

from typing import Final
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from core.admin_operation_notes import AdminOperationNoteId, AdminOperationNoteRepository


bp_api_admin_operation_notes = Blueprint("api_admin_operation_notes", __name__)
ADMIN_REFERER_PATHS: Final = frozenset({"/admin", "/dh1130"})
MAX_NOTE_LENGTH: Final = 300


def get_repository() -> AdminOperationNoteRepository:
    return AdminOperationNoteRepository()


def _admin_surface_allowed() -> bool:
    raw = (request.headers.get("Referer") or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    host = (request.host or "").lower()
    if parsed.netloc and parsed.netloc.lower() != host:
        return False
    return (parsed.path.rstrip("/") or "/") in ADMIN_REFERER_PATHS


@bp_api_admin_operation_notes.before_request
def require_admin_surface():
    if not _admin_surface_allowed():
        return jsonify({"ok": False, "error": "operation notes are only available from the admin page"}), 403


@bp_api_admin_operation_notes.get("/api/admin-operation-notes")
def list_notes():
    return jsonify({"ok": True, "notes": get_repository().list_all()})


@bp_api_admin_operation_notes.post("/api/admin-operation-notes")
def create_note():
    match request.get_json(silent=True):
        case {"content": str(raw_content)}:
            content = " ".join(raw_content.split())
        case _:
            return jsonify({"ok": False, "error": "content must be text"}), 400

    if not content:
        return jsonify({"ok": False, "error": "content is required"}), 400
    if len(content) > MAX_NOTE_LENGTH:
        return jsonify({"ok": False, "error": "content too long"}), 400

    note = get_repository().create(content)
    return jsonify({"ok": True, "note": note}), 201


@bp_api_admin_operation_notes.delete("/api/admin-operation-notes/<int:note_id>")
def delete_note(note_id: int):
    if not get_repository().delete(AdminOperationNoteId(note_id)):
        return jsonify({"ok": False, "error": "note not found"}), 404
    return jsonify({"ok": True, "deleted": True, "id": note_id})
