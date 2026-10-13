"""Run actual date routes and app lease hooks without importing app/runtime paths."""
from __future__ import annotations

import argparse
import ast
import datetime as dt
from pathlib import Path
from types import SimpleNamespace
import sys

from flask import Blueprint, Flask, abort, g, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.date_rules import is_iso_date_key, parse_iso_date_key
from core.request_consistency import POST_DATE_ENDPOINTS, absence_barrier_mode, request_has_invalid_scoped_date


def functions(source_root, relative, names, *, nested=False):
    tree = ast.parse((source_root / relative).read_text(encoding="utf-8"))
    if nested:
        tree = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "create_app")
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == names
    return ast.Module(body=selected, type_ignores=[])


def verify(source_root, guarded=True):
    app = Flask("date-before-barrier")
    app.config["TESTING"] = True
    effects = {"enter": 0, "exit": 0, "io": 0}

    class Lease:
        def __enter__(self):
            effects["enter"] += 1
        def __exit__(self, *args):
            effects["exit"] += 1

    def io(value=None):
        effects["io"] += 1
        return {} if value is None else value

    scope = dict(globals(), app=app, POST_DATE_ENDPOINTS=POST_DATE_ENDPOINTS,
                 absence_read_barrier=lambda **kwargs: Lease(),
                 AbsenceRecoveryRequiredError=RuntimeError)
    exec(compile(functions(source_root, "app.py", {
        "needs_absence_consistency_barrier", "wait_for_absence_transaction",
        "release_absence_transaction_barrier",
    }, nested=True), "actual-app-date-hooks", "exec"), scope)

    progress_bp = Blueprint("date_progress", __name__)
    progress = dict(globals(), bp_api_progress=progress_bp, nocache_resp=jsonify,
                    _load_progress_strict=lambda: io(), _progress_sids_from_query=lambda: [],
                    read_progress_projection=lambda **kwargs: io(),
                    _progress_for_sids=lambda *args: {}, _progress_lock=lambda: io(),
                    is_ghost_student_sid=lambda sid: False,
                    _youtube_cleanup_inputs=lambda *args: io())
    exec(compile(functions(source_root, "routes/api_progress.py", {
        "api_progress", "api_progress_patch",
    }), "actual-progress-date-route", "exec"), progress)
    app.register_blueprint(progress_bp)

    watch_bp = Blueprint("date_watch", __name__)
    watch = dict(globals(), bp_api_watch=watch_bp, nocache_resp=jsonify,
                 os=SimpleNamespace(environ={}), KOLLUS_QA_ENV="ACADEMY_ISOLATED_KOLLUS_QA",
                 _academy_request_allowed=lambda: request.headers.get("X-Academy") == "1",
                 _public_sid_matches=lambda sid: True, is_youtube_mid=lambda mid: False,
                 is_ghost_student_sid=lambda sid: False, ACADEMY_ACCESS_MESSAGE="academy",
                 load_watch_strict=lambda path: io(), WATCH_PATH="never-opened",
                 save_watch_entry=lambda *args, **kwargs: io(),
                 VALID_VIDEO_PROGRESS_STATUSES={"done", "skip", "none", "interrupted"})
    exec(compile(functions(source_root, "routes/api_watch.py", {
        "api_watch", "api_watch_status",
    }), "actual-watch-date-route", "exec"), watch)
    app.register_blueprint(watch_bp)

    bootstrap_bp = Blueprint("date_bootstrap", __name__)
    bootstrap = dict(globals(), bp_api_student_bootstrap=bootstrap_bp,
                     _projection_dependencies=lambda: SimpleNamespace(today_iso=lambda: "2026-10-01"),
                     _public_session_sid=lambda: None, _is_public_student_request=lambda: False,
                     _student_request_academy_allowed=lambda: True, nocache_resp=jsonify,
                     build_student_bootstrap_payload=lambda *args, **kwargs: (io({"academyAccessAllowed": True}), 200),
                     _finalize_public_bootstrap=lambda payload, *args: payload)
    exec(compile(functions(source_root, "routes/api_student_bootstrap.py", {
        "api_student_bootstrap",
    }), "actual-bootstrap-date-route", "exec"), bootstrap)
    app.register_blueprint(bootstrap_bp)

    attend_bp = Blueprint("date_attend", __name__)
    attendance = dict(globals(), bp_api_attend=attend_bp, _attendance_roster_for_date=lambda day: io([]),
                      ATTENDANCE_PATH="never-opened", CONTACT_PATH="never-opened",
                      _load_flag_all=lambda path: io())
    exec(compile(functions(source_root, "routes/api_attend.py", {
        "_date_key_from_query", "_norm_date", "api_attend", "api_attendance_get", "api_contact_get",
    }), "actual-attendance-date-route", "exec"), attendance)
    app.register_blueprint(attend_bp)
    client = app.test_client()

    def reset():
        effects.update(enter=0, exit=0, io=0)

    cases = 0
    for date in ("2026-02-30", "20261001", "2026-W40-4", "2026-10-01T00:00:00"):
        for method, path, body, headers in (
            ("GET", "/api/progress", None, {}),
            ("GET", "/api/student/bootstrap", None, {}),
            ("GET", "/api/attend", None, {}),
            ("POST", "/api/progress/patch", {"date": date, "sid": "qa", "progress": {}}, {}),
            ("POST", "/api/watch", {"date": date, "sid": "qa", "mid": "mid"}, {"X-Academy": "1"}),
            ("POST", "/api/watch-status", {"date": date, "sid": "qa", "mid": "mid", "status": "done"}, {"X-Academy": "1"}),
        ):
            reset()
            response = (client.get(path, query_string={"date": date, "sid": "qa"}) if method == "GET"
                        else client.post(path, json=body, headers=headers))
            if guarded:
                assert response.status_code == 400, (path, date, response.status_code)
                assert effects == {"enter": 0, "exit": 0, "io": 0}, (path, date, effects)
            else:
                assert effects["enter"] == 1 and effects["exit"] == 1, (path, effects)
                if path == "/api/student/bootstrap" and date in {"20261001", "2026-W40-4"}:
                    assert response.status_code == 200 and effects["io"] == 1
            cases += 1

        reset()
        denied = client.post("/api/watch", json={"date": date, "sid": "qa", "mid": "mid"})
        assert denied.status_code == 403 and effects["io"] == 0
        assert effects["enter"] == (0 if guarded else 1)

    reset()
    response = client.post("/api/progress/patch", data='{"date":"2026-02-30","sid":"qa","progress":{}}', content_type="text/plain")
    assert response.status_code == 400 and effects["io"] == 0
    assert effects["enter"] == (0 if guarded else 1), "force-JSON route must retain its parser semantics"

    reset()
    good = client.get("/api/progress?date=2026-10-01")
    assert good.status_code == 200 and effects == {"enter": 1, "exit": 1, "io": 1}

    # Literal classifier cases cover endpoints using transport/store fixtures in
    # their own complementary verifiers. Ignored parameters never waive a lease.
    for path, method, query, body, expected in (
        ("/api/logs/entry", "GET", {"date": "2026-02-30"}, None, True),
        ("/api/logs", "GET", {"exportTargets": '[["qa","20261001"]]'}, None, True),
        ("/api/logs/unarchived-summary", "GET", {"excludeDate": "2026-W40-4"}, None, True),
        ("/api/logs/patch-batch", "POST", {}, {"patches": [{"date": "2026-10-01"}, {"date": "2026-02-30"}]}, True),
        ("/api/updates/patch", "POST", {}, {"date": "20261001"}, True),
        ("/api/updates/self-study", "POST", {}, {"date": "2026-02-30"}, True),
        ("/api/absent/recover", "POST", {}, {"date": "2026-02-30"}, True),
        ("/api/updates", "GET", {"date": "bad-but-ignored"}, None, False),
        ("/api/today", "GET", {"date": "bad-but-ignored"}, None, False),
        ("/api/absent", "POST", {}, {"by_date": {"2026-02-30": ["qa"]}}, False),
        ("/api/kollus/lms-callback", "POST", {}, {"date": "bad-but-ignored"}, False),
        ("/api/student/bootstrap", "GET", {}, None, False),
    ):
        assert request_has_invalid_scoped_date(path, method, query, body) is expected, (path, expected)
    assert absence_barrier_mode("/api/absent", "POST") is None
    for path, method, query, expected in (
        ("/api/makeup-carryover", "GET", {}, "shared"),
        ("/api/makeup-carryover", "HEAD", {}, "shared"),
        ("/api/makeup-carryover", "POST", {}, "exclusive"),
        ("/api/updates", "GET", {}, "shared"),
        ("/api/updates", "GET", {"readOnly": "0"}, "shared"),
        ("/api/updates", "GET", {"readOnly": "false"}, "shared"),
        ("/api/updates", "GET", {"date": "2026-01-01"}, "shared"),
        ("/api/updates", "GET", {"readOnly": "1"}, "shared"),
        ("/api/updates/", "GET", {"readOnly": " TRUE "}, "shared"),
        ("/api/updates", "HEAD", {"readOnly": "yes"}, "shared"),
        ("/api/updates", "POST", {"readOnly": "1"}, "exclusive"),
        ("/api/updates/patch", "POST", {"readOnly": "1"}, "exclusive"),
        ("/api/student/bootstrap", "GET", {"readOnly": "1"}, "exclusive"),
    ):
        assert absence_barrier_mode(path, method, query) == expected, (path, method, query)
    assert absence_barrier_mode("/api/updates", "GET") == "shared", "default GET is storage-only"
    assert absence_barrier_mode("/api/updates", "GET", {"ensure": "1"}) == "exclusive"
    assert absence_barrier_mode("/api/updates", "GET", {"ensure": "1", "readOnly": "yes"}) == "shared"
    assert absence_barrier_mode("/api/updates/ensure-today", "POST") == "exclusive"
    print(f"date boundary checks passed: {cases} actual route cases; invalid inputs avoid lease/I/O; academy precedence, JSON parser, valid lease and D-04 preserved")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--expect", choices=("guarded", "vulnerable"), default="guarded")
    args = parser.parse_args()
    verify(args.source_root, args.expect == "guarded")
