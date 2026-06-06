# app.py — Flask 2.x / Python 3.10+
from __future__ import annotations

from urllib.parse import urlparse

from flask import Flask, request, abort, render_template_string
from werkzeug.middleware.proxy_fix import ProxyFix

from core.network_access import (
    academy_network_allowed,
    client_ip_from_request,
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
from routes.api_admin_chat import bp_api_admin_chat


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

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
        if p in {"/js/test_answer_link_map.json", "/js/test_answer_link_map.js"} and not academy_network_allowed():
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
    app.register_blueprint(bp_api_admin_chat)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8003, debug=True)
