from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, abort
from werkzeug.exceptions import Unauthorized

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.api_errors import install_api_error_handlers


def run_checks() -> None:
    app = Flask("verify-api-error-format")
    install_api_error_handlers(app)

    @app.get("/api/protected")
    def protected():
        error = Unauthorized()
        response = error.get_response()
        response.headers["WWW-Authenticate"] = 'Basic realm="fixture"'
        error.response = response
        raise error

    @app.get("/api/code/<int:code>")
    def code_error(code):
        abort(code)

    @app.get("/page/blocked")
    def page_error():
        abort(403)

    @app.get("/api/only-get")
    def only_get():
        return {"ok": True}

    client = app.test_client()
    for path, expected in [("/api/missing", 404), ("/files/missing", 404)] + [
        (f"/api/code/{code}", code) for code in (400, 403, 409, 413, 428, 500, 503)
    ]:
        response = client.get(path)
        assert response.status_code == expected, (path, response.status_code)
        assert response.is_json and response.get_json()["ok"] is False, path
        assert response.get_json()["error"] == str(expected), path
        assert response.headers["Cache-Control"] == "no-store", path
    response = client.get("/api/protected")
    assert response.status_code == 401 and response.is_json
    assert response.headers["WWW-Authenticate"] == 'Basic realm="fixture"'
    response = client.post("/api/only-get")
    assert response.status_code == 405 and response.is_json
    assert "GET" in response.headers["Allow"]
    assert client.get("/page/blocked").content_type.startswith("text/html")
    assert client.get("/page/blocked", headers={"Accept": "application/json"}).is_json
    assert client.get("/page/blocked", headers={"Accept": "application/json;q=0,text/html"}).content_type.startswith("text/html")
    print("API errors: JSON status/header contracts and HTML pages preserved")


if __name__ == "__main__":
    run_checks()
