from __future__ import annotations

import argparse
import html
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs

from gemini_key_setup import KEY_NAME, SERVER_ENV_PATH, MissingKeyError, write_env_key

HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 18765
MAX_BODY_BYTES: Final[int] = 16384


def main() -> int:
    config = parse_args()
    run_server(config.port)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open a local browser form to save GEMINI_API_KEY to C:\\server\\.env.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args()


def run_server(port: int) -> None:
    token = secrets.token_urlsafe(24)
    handler = make_handler(SERVER_ENV_PATH, token)
    server = ThreadingHTTPServer((HOST, port), handler)
    print(f"Open http://{HOST}:{port}/ in your browser to save {KEY_NAME}.")
    server.serve_forever()


def make_handler(env_path: Path, token: str) -> type[BaseHTTPRequestHandler]:
    class KeySetupHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/":
                self.send_error(404)
                return
            self.send_html(200, form_html(token, ""))

        def do_POST(self) -> None:
            if self.path != "/save":
                self.send_error(404)
                return
            fields = self.read_form()
            if fields.get("token", [""])[0] != token:
                self.send_html(403, form_html(token, "Invalid form token."))
                return
            try:
                write_env_key(env_path, fields.get("api_key", [""])[0])
            except MissingKeyError:
                self.send_html(400, form_html(token, "API key is empty."))
                return
            self.send_html(200, saved_html(env_path))

        def read_form(self) -> dict[str, list[str]]:
            length_header = self.headers.get("Content-Length", "0")
            try:
                length = int(length_header)
            except ValueError:
                length = 0
            body = self.rfile.read(min(length, MAX_BODY_BYTES)).decode("utf-8", errors="replace")
            return parse_qs(body, keep_blank_values=True)

        def send_html(self, status: int, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return KeySetupHandler


def form_html(token: str, message: str) -> str:
    escaped_message = html.escape(message)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>Gemini API Key Setup</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 40px; max-width: 620px; }}
    label, input, button {{ font-size: 16px; }}
    input {{ width: 100%; box-sizing: border-box; padding: 10px; margin: 8px 0 14px; }}
    button {{ padding: 9px 14px; }}
    .msg {{ color: #b00020; min-height: 24px; }}
  </style>
</head>
<body>
  <h1>Gemini API Key Setup</h1>
  <form method="post" action="/save" autocomplete="off">
    <input type="hidden" name="token" value="{html.escape(token)}">
    <label for="api_key">Gemini API Key</label>
    <input id="api_key" name="api_key" type="password" autofocus required>
    <button type="submit">Save</button>
  </form>
  <p class="msg">{escaped_message}</p>
</body>
</html>"""


def saved_html(env_path: Path) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><title>Saved</title></head>
<body>
  <h1>{KEY_NAME} saved to {html.escape(str(env_path))}</h1>
  <p>키 값은 표시하지 않습니다. 이 탭은 닫아도 됩니다.</p>
</body>
</html>"""


if __name__ == "__main__":
    raise SystemExit(main())
