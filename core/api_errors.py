from __future__ import annotations

from flask import current_app, request
from werkzeug.exceptions import HTTPException
from core.json_store import StoreBusy, StoreCorrupt, RevisionConflict


def wants_json_error() -> bool:
    if request.path.startswith(("/api/", "/files/")):
        return True
    return request.accept_mimetypes.best_match(("text/html", "application/json")) == "application/json"


def http_error_response(error: HTTPException):
    response = error.get_response()
    if wants_json_error():
        response.set_data(current_app.json.dumps({
            "ok": False,
            "error": str(error.code),
            "message": error.description,
        }))
        response.content_type = "application/json"
        response.headers["Cache-Control"] = "no-store"
    return response


def install_api_error_handlers(app) -> None:
    app.register_error_handler(HTTPException, http_error_response)

    def store_error(error):
        status = 500 if isinstance(error, StoreCorrupt) else 409
        code = "store_unavailable" if status == 500 else "store_busy"
        payload = {"ok": False, "error": code}
        if isinstance(error, RevisionConflict):
            payload.update(error="revision_conflict", revision=error.current_revision)
        response = app.json.response(payload)
        response.status_code = status
        response.headers["Cache-Control"] = "no-store"
        return response

    for error_type in (StoreBusy, StoreCorrupt, RevisionConflict):
        app.register_error_handler(error_type, store_error)
