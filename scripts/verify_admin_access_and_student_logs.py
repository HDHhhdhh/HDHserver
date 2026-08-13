"""Temp-only checks for admin page access and student operation logs."""
from __future__ import annotations

import base64
import pathlib
import subprocess
import sys
import tempfile
from typing import Any

from flask import Flask
from werkzeug.security import generate_password_hash


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_admin_basic_auth_checks() -> None:
    from core.admin_basic_auth import (
        ADMIN_AUTH_CHALLENGE,
        ADMIN_PASSWORD_HASH_ENV,
        ADMIN_USERNAME_ENV,
        verify_admin_authorization,
    )
    from routes.pages import bp_pages

    username = "\uac80\uc99d\uad00\ub9ac\uc790"
    password = "temporary-test-password"
    authorization = "Basic " + base64.b64encode(
        f"{username}:{password}".encode("utf-8"),
    ).decode("ascii")
    values = {
        ADMIN_USERNAME_ENV: username,
        ADMIN_PASSWORD_HASH_ENV: generate_password_hash(password),
    }
    check(
        verify_admin_authorization(authorization, values),
        "UTF-8 administrator credentials must verify against the configured hash",
    )
    wrong_password = "Basic " + base64.b64encode(f"{username}:wrong".encode()).decode()
    wrong_username = "Basic " + base64.b64encode(f"other:{password}".encode()).decode()
    check(not verify_admin_authorization(wrong_password, values), "wrong administrator password must be rejected")
    check(not verify_admin_authorization(wrong_username, values), "wrong administrator username must be rejected")
    check(not verify_admin_authorization("Basic !!!", values), "malformed Basic credentials must be rejected")
    check(not verify_admin_authorization(authorization, {}), "missing administrator configuration must fail closed")

    app = Flask("verify-admin-page-auth", static_folder=str(ROOT / "static"), static_url_path="")
    app.config["ACADEMY_ADMIN_AUTHORIZER"] = lambda header: header == authorization
    app.register_blueprint(bp_pages)
    client = app.test_client()

    def request_page(path: str, header: str | None = None, remote: str = "127.0.0.1") -> Any:
        headers = {} if header is None else {"Authorization": header}
        return client.get(
            path,
            base_url="http://127.0.0.1:8003",
            headers=headers,
            environ_overrides={"REMOTE_ADDR": remote},
        )

    missing = request_page("/admin")
    check(
        missing.status_code == 401
        and missing.headers.get("WWW-Authenticate") == ADMIN_AUTH_CHALLENGE
        and missing.headers.get("Cache-Control") == "no-store",
        "admin page must challenge missing credentials without caching the response",
    )
    check(request_page("/admin", "Basic Zm9vOmJhcg==").status_code == 401, "bad admin credentials must fail")
    check(request_page("/admin", authorization).status_code == 200, "valid admin credentials must open the page")
    for path in ("/admin.html", "/ADMIN.HTML", "/admin.html.", "/students", "/video-manage.html"):
        check(request_page(path).status_code == 401, f"admin page alias must not bypass authentication: {path}")
    check(request_page("/demo/rh3123").status_code == 200, "admin demo route must remain public")
    check(
        request_page("/admin", remote="203.0.113.8").status_code == 401,
        "external administrator requests without credentials must be challenged",
    )
    check(
        request_page("/admin", "Basic Zm9vOmJhcg==", "203.0.113.8").status_code == 401,
        "external administrator requests with bad credentials must fail",
    )
    check(
        request_page("/admin", authorization, "203.0.113.8").status_code == 200,
        "valid administrator credentials must open the page outside the academy network",
    )
    for path in ("/students", "/tests", "/video-manage", "/school-cal", "/file-manage"):
        check(
            request_page(path, authorization, "203.0.113.8").status_code == 200,
            f"valid external administrator credentials must open the page family: {path}",
        )


def run_student_operation_log_checks() -> None:
    from core.student_logs import StudentOperationLogRepository
    from routes import api_student_logs

    with tempfile.TemporaryDirectory(prefix="verify-student-operation-logs-") as tmpdir:
        repository = StudentOperationLogRepository(
            db_path=str(pathlib.Path(tmpdir) / "student-operation-logs.sqlite"),
        )
        original_get_repository = api_student_logs.get_repository
        api_student_logs.get_repository = lambda: repository
        try:
            app = Flask("verify-student-operation-logs")
            app.register_blueprint(api_student_logs.bp_api_student_logs)
            client = app.test_client()
            admin_headers = {"Referer": "http://localhost/admin"}

            check(
                client.get("/api/student-logs").status_code == 403,
                "student logs must reject non-admin-surface reads",
            )
            check(
                client.get(
                    "/api/student-logs",
                    headers={"Referer": "https://example.test/admin"},
                ).status_code == 403,
                "student logs must reject a cross-origin admin referer",
            )
            empty = client.get("/api/student-logs", headers=admin_headers)
            check(empty.status_code == 200, "student logs admin read must succeed")
            check(empty.get_json().get("logs") == [], "student logs must start empty")

            invalid_date = client.post(
                "/api/student-logs",
                headers=admin_headers,
                json={
                    "sid": "s1",
                    "studentName": "\ud14c\uc2a4\ud2b8 \ud559\uc0dd",
                    "kind": "homework_insufficient",
                    "comment": "\ud655\uc778 \ud544\uc694",
                    "date": "2026-02-30",
                },
            )
            check(invalid_date.status_code == 400, "student logs must reject impossible calendar dates")

            created_ids: list[int] = []
            for sid, name, comment in (
                (" s1 ", " \ud14c\uc2a4\ud2b8 \ud559\uc0dd ", " \ud655\uc778   \ud544\uc694 "),
                ("s2", "\ub450 \ubc88\uc9f8 \ud559\uc0dd", "\uad50\uc7ac \ubbf8\uc81c\ucd9c"),
            ):
                created = client.post(
                    "/api/student-logs",
                    headers=admin_headers,
                    json={
                        "sid": sid,
                        "studentName": name,
                        "kind": "homework_insufficient",
                        "comment": comment,
                        "date": "2026-08-08",
                    },
                )
                created_log = (created.get_json() or {}).get("log") or {}
                check(created.status_code == 201, "student log create must return HTTP 201")
                created_ids.append(int(created_log.get("id") or 0))

            listed = (client.get("/api/student-logs", headers=admin_headers).get_json() or {}).get("logs") or []
            check(len(listed) == 2, "student log list must include every created record")
            check(listed[-1].get("sid") == "s1", "student log create must trim sid")
            check(listed[-1].get("student_name") == "\ud14c\uc2a4\ud2b8 \ud559\uc0dd", "student log create must trim name")
            check(listed[-1].get("comment") == "\ud655\uc778 \ud544\uc694", "student log create must normalize whitespace")

            deleted = client.delete(f"/api/student-logs/{created_ids[0]}", headers=admin_headers)
            check(deleted.status_code == 200, "student log single delete must succeed")
            check((deleted.get_json() or {}).get("id") == created_ids[0], "student log delete must report its id")
            remaining = (client.get("/api/student-logs", headers=admin_headers).get_json() or {}).get("logs") or []
            check(
                [int(row.get("id") or 0) for row in remaining] == [created_ids[1]],
                "student log single delete must preserve unrelated records",
            )
            check(
                client.delete(f"/api/student-logs/{created_ids[0]}", headers=admin_headers).status_code == 404,
                "student log repeat delete must report not found",
            )

            cleared = client.delete("/api/student-logs", headers=admin_headers)
            check(cleared.status_code == 200, "student log clear must succeed")
            check((cleared.get_json() or {}).get("deleted") == 1, "student log clear must report remaining rows")
            after_clear = (client.get("/api/student-logs", headers=admin_headers).get_json() or {}).get("logs") or []
            check(after_clear == [], "student log clear must remove every operation log")
        finally:
            api_student_logs.get_repository = original_get_repository


def run_student_log_demo_checks() -> None:
    primary = (ROOT / "static/js/admin/demo/fetch.js").read_text("utf-8")
    fallback = (ROOT / "static/js/admin/demo/bootstrap.js").read_text("utf-8")
    for source, label in ((primary, "primary"), (fallback, "fallback")):
        check(
            "applyStudentLogsRequest" in source and "studentLogsResult" in source,
            f"demo {label} router must intercept student-log requests",
        )

    driver = r"""
class MemoryStorage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.has(String(key)) ? this.values.get(String(key)) : null; }
  setItem(key, value) { this.values.set(String(key), String(value)); }
  removeItem(key) { this.values.delete(String(key)); }
}
const check = (condition, message) => {
  if (!condition) throw new Error(message);
};
globalThis.sessionStorage = new MemoryStorage();
const { createDemoFetch } = await import('./static/js/admin/demo/fetch.js');
let forwarded = 0;
const originalFetch = async () => {
  forwarded += 1;
  return new Response('{}', { status: 500 });
};
const root = {
  fetch: originalFetch,
  location: {
    href: 'http://localhost/demo/rh3123',
    origin: 'http://localhost',
    pathname: '/demo/rh3123',
  },
};
const demoFetch = createDemoFetch({ window: root, originalFetch });
let listed = await (await demoFetch('/api/student-logs')).json();
check(listed.ok && Array.isArray(listed.logs), 'demo student-log list failed');

const createLog = async (sid, name) => {
  const response = await demoFetch('/api/student-logs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sid,
      studentName: name,
      kind: 'homework_insufficient',
      comment: '  \\uc624\\ub2f5   \\ub178\\ud2b8 \\ubbf8\\uc81c\\ucd9c  ',
      date: '2026-06-17',
    }),
  });
  const payload = await response.json();
  check(
    response.status === 201 && payload.log?.student_name === name
      && payload.log?.comment === '\\uc624\\ub2f5 \\ub178\\ud2b8 \\ubbf8\\uc81c\\ucd9c',
    'demo student-log create contract failed',
  );
  return payload.log;
};
const first = await createLog('demo-s001', '\\uae40\\ud558\\ub298');
const second = await createLog('demo-s002', '\\ubc15\\uc9c0\\ubbfc');
listed = await (await demoFetch('/api/student-logs')).json();
check(listed.logs.length === 2, 'demo student logs did not persist');

const deleted = await demoFetch('/api/student-logs/' + first.id, { method: 'DELETE' });
check(deleted.status === 200, 'demo student-log single delete failed');
listed = await (await demoFetch('/api/student-logs')).json();
check(
  listed.logs.length === 1 && listed.logs[0].id === second.id,
  'demo student-log single delete removed the wrong rows',
);
const repeatDelete = await demoFetch('/api/student-logs/' + first.id, { method: 'DELETE' });
check(repeatDelete.status === 404, 'demo repeated single delete must return 404');

const cleared = await (await demoFetch('/api/student-logs', { method: 'DELETE' })).json();
check(cleared.ok && cleared.deleted === 1, 'demo student-log clear failed');
listed = await (await demoFetch('/api/student-logs')).json();
check(listed.logs.length === 0, 'demo student-log clear did not persist');
check(forwarded === 0, 'demo student-log request reached the live fetch implementation');
console.log('admin access and student logs demo checks passed');
"""
    process = subprocess.run(
        ["node", "--input-type=module", "-e", driver],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.stdout:
        print(process.stdout, end="")
    if process.stderr:
        print(process.stderr, end="", file=sys.stderr)
    check(process.returncode == 0, "student logs demo behavior driver failed")


def main() -> int:
    run_admin_basic_auth_checks()
    run_student_operation_log_checks()
    run_student_log_demo_checks()
    print("admin access and student operation log checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
