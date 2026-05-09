# app.py — Flask 2.x / Python 3.10+
from __future__ import annotations

import ipaddress
import re

from flask import Flask, request, abort, render_template_string
from werkzeug.middleware.proxy_fix import ProxyFix

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


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # ─────────────────────────────────────────────
    # ✅ 학생 사이트(/student) — 학원 네트워크만 허용 (IPv4 + IPv6)
    #
    # iPad는 IPv6 우선이라 /64 하나로는 자주 새는 케이스가 있음.
    # 네가 준 prefix(2a09:bac2:46d9:....) 기준으로 /48로 커버 범위를 넓힘.
    # ─────────────────────────────────────────────
    ALLOWED = [
        ipaddress.ip_network("110.14.147.14/32"),
        ipaddress.ip_network("192.168.0.0/16"),

        # ✅ 학원 회선 IPv6 (앞 3블록 고정)
        # - /64로 하면 4번째 블록이 바뀌는 순간 또 막힘
        # - /48은 범위가 넓어지지만 여전히 "해당 통신사/회선 블록" 안에만 묶임
        ipaddress.ip_network("2a09:bac2:46d9::/48"),
    ]

    def _clean_ip(s: str) -> str:
        s = (s or "").strip()
        s = s.strip().strip(".")  # 끝 '.' 같은 잡문자 제거
        # IPv6 zone id 제거 (예: fe80::1%en0)
        s = re.sub(r"%[0-9A-Za-z_.-]+$", "", s)
        # [IPv6] 형태 제거
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1]
        return s

    def _client_ip() -> str:
        # ProxyFix 사용 중이면 X-Forwarded-For가 들어올 수 있음
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return _clean_ip(xff.split(",")[0])
        return _clean_ip(request.remote_addr or "")

    def ip_allowed(ip_str: str) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        return any(ip in net for net in ALLOWED)

    @app.before_request
    def block_student_outside():
        p = (request.path or "")

        # ✅ /student 또는 /student/... 만 막기 ( /students 는 제외 )
        if p == "/student" or p.startswith("/student/"):
            ip_str = _client_ip()

            if not ip_allowed(ip_str):
                # ✅ 다음에 또 터지면 이 로그 한 줄로 바로 원인 확정 가능
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
        <h1>학원 와이파이만 시청 가능합니다</h1>
        <p>해당 콘텐츠는 학원 내부 네트워크에서만 이용할 수 있습니다.</p>
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
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8003, debug=True)
