# app.py — Flask 2.x / Python 3.10+
from __future__ import annotations

import os
from urllib.parse import urlparse

from flask import Flask, g, request, abort, jsonify, make_response, render_template_string
from werkzeug.middleware.proxy_fix import ProxyFix

from core.admin_basic_auth import (
    ADMIN_AUTH_CHALLENGE,
    external_admin_api_auth_required,
    verify_admin_authorization,
)
from core.material_state import (
    MaterialStateRecoveryRequiredError,
    recover_material_state_if_needed,
)
from core.paths import ASN_PATH, MAT_PATH, PAGE_FOLDERS_PATH
from core.runtime_server_guard import refuse_concurrent_live_server

from core.network_access import (
    academy_network_allowed,
    client_ip_from_request,
    ip_allowed,
)
from core.student_app_config import load_student_app_config
from core.student_public_surface import (
    BOARD_ROUTE_METHODS,
    FOCUS_ROUTE_METHODS,
    HOMEWORK_ROUTE_METHODS,
    PUSH_ROUTE_METHODS,
    install_student_public_surface,
    register_student_app_domain,
)
from routes.pages import bp_pages
from routes.api_basic import bp_api_basic
from routes.api_attend import bp_api_attend
from routes.api_announcements import bp_api_announcements
from routes.api_arrive_time import bp_api_arrive_time
from routes.api_tests import bp_api_tests
from routes.api_watch import bp_api_watch
from routes.api_fs import bp_api_fs
from routes.api_kollus import bp_api_kollus
from routes.api_auth import bp_api_auth
from routes.api_todaymeta import bp_api_todaymeta
from routes.api_makeup_carryover import bp_api_makeup_carryover
from routes.api_student_app_auth import bp_api_student_app_auth
from routes.api_student_accounts import bp_api_student_accounts
from routes.api_student_push import bp_api_student_push
from routes.api_student_homework import bp_api_student_homework, bp_api_student_homework_admin
from routes.api_student_board import bp_api_student_board
from routes.api_student_focus import bp_api_student_focus, bp_api_student_focus_admin
from routes.api_assistant_notes import bp_api_assistant_notes
from routes.api_admin_operation_notes import bp_api_admin_operation_notes
from routes.api_student_logs import bp_api_student_logs
from routes.api_non_student_ocr import bp_api_non_student_ocr
from routes.absence_assignment_cleanup import (
    AbsenceRecoveryRequiredError,
    absence_read_barrier,
    recover_pending_absence_transactions,
)


def create_app() -> Flask:
    refuse_concurrent_live_server()

    recovered_absence_transaction = recover_pending_absence_transactions()
    if recovered_absence_transaction:
        print(
            f"[absence-transaction] recovered {recovered_absence_transaction}",
            flush=True,
        )

    material_state_recovery_error = ""
    try:
        recovered_material_state = recover_material_state_if_needed(
            MAT_PATH,
            ASN_PATH,
            PAGE_FOLDERS_PATH,
        )
    except MaterialStateRecoveryRequiredError as exc:
        material_state_recovery_error = str(exc)
        print(
            f"[material-state] writes degraded; recovery required: {exc}",
            flush=True,
        )
    except Exception as exc:
        material_state_recovery_error = f"{type(exc).__name__}: {exc}"
        print(
            f"[material-state] writes degraded; startup check failed: {exc}",
            flush=True,
        )
    else:
        if recovered_material_state:
            print("[material-state] recovered pending transaction", flush=True)

    app = Flask(__name__, static_folder="static", static_url_path="")
    app.json.ensure_ascii = False
    app.config["MATERIAL_STATE_WRITES_DEGRADED"] = bool(material_state_recovery_error)
    student_app_config = load_student_app_config()
    install_student_public_surface(
        app,
        config=student_app_config,
        auth_blueprint=bp_api_student_app_auth,
    )
    if student_app_config.public_enabled:
        register_student_app_domain(app, bp_api_student_push, PUSH_ROUTE_METHODS)
        register_student_app_domain(app, bp_api_student_board, BOARD_ROUTE_METHODS)
        if student_app_config.homework_enabled:
            register_student_app_domain(app, bp_api_student_homework, HOMEWORK_ROUTE_METHODS)
        if student_app_config.focus_enabled:
            register_student_app_domain(app, bp_api_student_focus, FOCUS_ROUTE_METHODS)
    trust_proxy_headers = os.environ.get("TRUST_PROXY_HEADERS", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if trust_proxy_headers:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    @app.before_request
    def require_external_admin_api_auth():
        public_request = getattr(g, "student_app_public_request", False) is True
        student_scoped = bool(str(request.args.get("sid") or "").strip())
        if not external_admin_api_auth_required(
            request.path,
            request,
            method=request.method,
            public_request=public_request,
            student_scoped=student_scoped,
        ):
            return None
        verifier = app.config.get("ACADEMY_ADMIN_AUTHORIZER")
        if not callable(verifier):
            verifier = verify_admin_authorization
        if verifier(request.headers.get("Authorization")):
            return None
        response = make_response(jsonify({"ok": False, "code": "admin_auth_required"}), 401)
        response.headers.update({"WWW-Authenticate": ADMIN_AUTH_CHALLENGE, "Cache-Control": "no-store"})
        return response

    def needs_absence_consistency_barrier() -> bool:
        path = str(request.path or "").rstrip("/") or "/"
        if request.method == "POST" and path in {"/api/absent", "/api/makeup-sheet-sync"}:
            return False
        exact_paths = {
            "/api/absent",
            "/api/absent/recover",
            "/api/attend",
            "/api/homework-books",
            "/api/kollus/lms-callback",
            "/api/makeup-carryover",
            "/api/student/bootstrap",
            "/api/tests-records",
            "/api/tests-stats",
            "/api/today",
            "/api/watch",
            "/api/watch-status",
        }
        prefixes = (
            "/api/admin/student-homework",
            "/api/logs",
            "/api/mobile/student/homework",
            "/api/progress",
            "/api/updates",
        )
        return path in exact_paths or path.startswith(prefixes)

    @app.before_request
    def wait_for_absence_transaction():
        if not needs_absence_consistency_barrier():
            return
        barrier = absence_read_barrier()
        try:
            barrier.__enter__()
        except (AbsenceRecoveryRequiredError, TimeoutError) as exc:
            abort(503, description=f"Absence transaction unavailable: {exc}")
        g.absence_consistency_barrier = barrier

    @app.teardown_request
    def release_absence_transaction_barrier(exc):
        barrier = getattr(g, "absence_consistency_barrier", None)
        if barrier is not None:
            barrier.__exit__(
                type(exc) if exc is not None else None,
                exc,
                exc.__traceback__ if exc is not None else None,
            )

    @app.before_request
    def block_cross_origin_writes():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return

        host = (request.host or "").lower()
        for header in ("Origin", "Referer"):
            raw = (request.headers.get(header) or "").strip()
            if not raw:
                continue
            try:
                parsed = urlparse(raw)
            except Exception:
                abort(403)
            if parsed.netloc and parsed.netloc.lower() != host:
                abort(403)

    @app.before_request
    def block_academy_only_answer_files():
        p = (request.path or "")
        if p != "/js/test_answer_link_map.json":
            return
        if getattr(g, "student_app_public_request", False) is True:
            if not ip_allowed(getattr(g, "student_app_client_ip", "")):
                abort(404)
            return
        if not academy_network_allowed():
            ip_str = client_ip_from_request()
            print(f"[BLOCK] path={p} ip={ip_str} xff={request.headers.get('X-Forwarded-For')} remote={request.remote_addr}")
            abort(403)

    BLOCK_HTML = """
    <!doctype html>
    <html lang="ko">
    <head>
      <meta charset="utf-8">
      <title>접속 제한</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <style>
        body{
          margin:0; height:100vh;
          display:flex; align-items:center; justify-content:center;
          background:#0f172a; color:#e5e7eb;
          font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial;
        }
        .card{
          background:#020617;
          border:1px solid #334155;
          border-radius:14px;
          padding:28px 26px;
          max-width:380px;
          text-align:center;
          box-shadow:0 20px 40px rgba(0,0,0,.45);
        }
        h1{ font-size:18px; margin:0 0 10px; }
        p{ font-size:14px; opacity:.85; margin:0; line-height:1.45; }
      </style>
    </head>
    <body>
      <div class="card">
        <h1>학원 Wi-Fi 전용 콘텐츠입니다</h1>
        <p>영상 재생과 테스트 답지는 학원 Wi-Fi에서만 볼 수 있습니다.</p>
      </div>
    </body>
    </html>
    """

    @app.errorhandler(403)
    def forbidden(_):
        return render_template_string(BLOCK_HTML), 403

    # Blueprints
    app.register_blueprint(bp_pages)
    app.register_blueprint(bp_api_basic)
    app.register_blueprint(bp_api_attend)
    app.register_blueprint(bp_api_arrive_time)
    app.register_blueprint(bp_api_announcements)
    app.register_blueprint(bp_api_tests)
    app.register_blueprint(bp_api_watch)
    app.register_blueprint(bp_api_fs)
    app.register_blueprint(bp_api_kollus)
    app.register_blueprint(bp_api_auth)
    app.register_blueprint(bp_api_todaymeta)
    app.register_blueprint(bp_api_makeup_carryover)
    app.register_blueprint(bp_api_assistant_notes)
    app.register_blueprint(bp_api_admin_operation_notes)
    app.register_blueprint(bp_api_student_logs)
    app.register_blueprint(bp_api_non_student_ocr)
    app.register_blueprint(bp_api_student_accounts)
    if student_app_config.homework_enabled:
        app.register_blueprint(bp_api_student_homework_admin)
    app.register_blueprint(bp_api_student_focus_admin)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8003, debug=True)
