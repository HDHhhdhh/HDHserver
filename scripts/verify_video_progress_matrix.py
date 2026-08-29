from __future__ import annotations

import copy
import datetime as dt
import json
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile

from flask import Flask, g, request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATE = "2026-08-24"
VALID_MS = 1_787_500_000_000
SECRET = "matrix-secret-" + ("k" * 48)
KST = dt.timezone(dt.timedelta(hours=9))


class Matrix:
    def __init__(self) -> None:
        self.passed = 0

    def check(self, case_id: str, condition: bool, detail: str) -> None:
        if not condition:
            raise AssertionError(f"{case_id}: {detail}")
        self.passed += 1
        print(f"[PASS] {case_id} - {detail}")


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


def read_json(path: Path):
    if not path.exists():
        return {}
    return json.loads(path.read_text("utf-8-sig"))


@contextmanager
def isolated_routes():
    import core.watch_progress_writer as writer
    import routes.api_kollus as kollus
    import routes.api_watch as watch

    with tempfile.TemporaryDirectory(prefix="verify-video-progress-matrix-") as raw:
        base = Path(raw)
        paths = {
            "watch": base / "watch.json",
            "progress": base / "progress.json",
            "students": base / "students.json",
            "videos": base / "videos.json",
            "updates": base / "updates.json",
        }
        write_json(paths["watch"], {})
        write_json(paths["progress"], {})
        write_json(
            paths["students"],
            [
                {"id": "sid-a", "curriculum": "대수"},
                {"id": "sid-b", "curriculum": "대수"},
            ],
        )
        mids = [
            "kol-0000",
            "kol-0004",
            "kol-0005",
            "kol-0090",
            "kol-last",
            "kol-unknown-duration",
            "kol-stale",
            "kol-manual",
        ]
        write_json(
            paths["videos"],
            [{"id": index + 1, "mid": mid, "curriculum": "대수"} for index, mid in enumerate(mids)],
        )
        write_json(paths["updates"], {"sentinel": {"sid-a": {"videos": ["untouched"]}}})

        originals = [
            (watch, "WATCH_PATH", watch.WATCH_PATH),
            (watch, "PRG_PATH", watch.PRG_PATH),
            (watch, "STU_PATH", watch.STU_PATH),
            (watch, "VID_PATH", watch.VID_PATH),
            (watch, "academy_network_allowed", watch.academy_network_allowed),
            (watch, "ip_allowed", watch.ip_allowed),
            (watch, "is_ghost_student_sid", watch.is_ghost_student_sid),
            (kollus, "WATCH_PATH", kollus.WATCH_PATH),
            (kollus, "PRG_PATH", kollus.PRG_PATH),
            (kollus, "STU_PATH", kollus.STU_PATH),
            (kollus, "VID_PATH", kollus.VID_PATH),
            (kollus, "_callback_secret", kollus._callback_secret),
        ]
        watch.WATCH_PATH = paths["watch"]
        watch.PRG_PATH = paths["progress"]
        watch.STU_PATH = paths["students"]
        watch.VID_PATH = paths["videos"]
        watch.academy_network_allowed = lambda: request.headers.get("X-Academy") == "1"
        watch.ip_allowed = lambda client_ip: client_ip == "academy-ip"
        watch.is_ghost_student_sid = lambda sid: str(sid) == "ghost"
        kollus.WATCH_PATH = paths["watch"]
        kollus.PRG_PATH = paths["progress"]
        kollus.STU_PATH = paths["students"]
        kollus.VID_PATH = paths["videos"]
        kollus._callback_secret = lambda: SECRET

        app = Flask("verify-video-progress-matrix")

        @app.before_request
        def install_public_context():
            if request.headers.get("X-Public") == "1":
                g.student_app_public_request = True
                g.student_app_client_ip = request.headers.get("X-Client-IP")
                g.student_app_active_sid = request.headers.get("X-Active-SID")

        app.register_blueprint(watch.bp_api_watch)
        app.register_blueprint(kollus.bp_api_kollus)
        try:
            yield {
                "client": app.test_client(),
                "paths": paths,
                "writer": writer,
                "watch": watch,
                "kollus": kollus,
            }
        finally:
            for module, name, value in reversed(originals):
                setattr(module, name, value)


def watch_payload(mid: str, *, last=0, dur=100, completed=False, sid="sid-a", date=DATE, updated_at=VALID_MS):
    return {
        "date": date,
        "sid": sid,
        "mid": mid,
        "last": last,
        "dur": dur,
        "completed": completed,
        "updatedAt": updated_at,
    }


def callback_body(
    mid: str,
    *,
    sid: str = "sid-a",
    last=0,
    dur=100,
    pct=0,
    play_time=0,
    real_playtime=0,
    start_at=1_787_390_000,
):
    return {
        "json_data": {
            "uservalues": {"uservalue0": sid},
            "content_info": {
                "media_content_key": mid,
                "start_at": start_at,
                "last_play_at": last,
                "duration": dur,
                "playtime_percent": pct,
                "playtime": play_time,
                "real_playtime": real_playtime,
            },
        }
    }


def run_browser_and_writer_cases(matrix: Matrix, env: dict) -> None:
    client = env["client"]
    paths = env["paths"]
    writer = env["writer"]
    academy = {"X-Academy": "1"}
    updates_before = paths["updates"].read_bytes()

    response = client.post("/api/watch", json=watch_payload("web-under", last=4), headers=academy)
    matrix.check("W01", response.status_code == 200 and response.get_json()["progress"] == {}, "under 5 percent stores watch without progress")

    response = client.post("/api/watch", json=watch_payload("web-start", last=5), headers=academy)
    body = response.get_json()
    matrix.check(
        "W02",
        response.status_code == 200
        and body["progress"]["web-start"] == "interrupted"
        and body["progress"]["__autoWatchProgressMids"]["web-start"] == "interrupted",
        "5 percent creates auto interrupted with ownership metadata",
    )

    response = client.post("/api/watch", json=watch_payload("web-done", last=90), headers=academy)
    body = response.get_json()
    matrix.check(
        "W03",
        response.status_code == 200 and body["watch"]["completed"] is True and body["progress"]["web-done"] == "done",
        "90 percent creates sticky done",
    )

    response = client.post(
        "/api/watch",
        json=watch_payload("web-completed-event", last=1, completed=True),
        headers=academy,
    )
    matrix.check("W04", response.get_json()["progress"]["web-completed-event"] == "done", "explicit completion event creates done")

    response = client.post(
        "/api/watch",
        json=watch_payload("web-unknown-duration", last=1, dur=0),
        headers=academy,
    )
    matrix.check("W05", response.get_json()["progress"]["web-unknown-duration"] == "interrupted", "positive position with unknown duration counts as started")

    client.post(
        "/api/watch",
        json=watch_payload("web-stale", last=95, dur=100, updated_at=VALID_MS + 200),
        headers=academy,
    )
    response = client.post(
        "/api/watch",
        json=watch_payload("web-stale", last=10, dur=80, updated_at=VALID_MS + 100),
        headers=academy,
    )
    merged = response.get_json()["watch"]
    matrix.check(
        "W06",
        merged == {"last": 95, "dur": 100, "completed": True, "updatedAt": VALID_MS + 200},
        "stale or reverse playback cannot regress watch state",
    )

    write_json(
        paths["watch"],
        {
            **read_json(paths["watch"]),
            "2026-08-25": {
                "7": {
                    "alias-mid": {
                        "last": 20,
                        "dur": 100,
                        "completed": False,
                        "updatedAt": VALID_MS,
                    }
                }
            },
        },
    )
    writer.save_watch_entry(
        paths["watch"],
        "2026-08-25",
        "007",
        "alias-mid",
        {"last": 30, "dur": 100, "completed": False, "updatedAt": VALID_MS + 1},
    )
    alias_day = read_json(paths["watch"])["2026-08-25"]
    matrix.check(
        "W07",
        set(alias_day) == {"7"} and alias_day["7"]["alias-mid"]["last"] == 30,
        "leading-zero SID writes merge into the numeric compatibility alias",
    )

    writer.save_watch_entry(
        paths["watch"],
        "2026-08-26",
        "sid-a",
        "isolate-a",
        {"last": 10, "dur": 100, "completed": False, "updatedAt": VALID_MS},
    )
    writer.save_watch_entry(
        paths["watch"],
        "2026-08-26",
        "sid-b",
        "isolate-b",
        {"last": 20, "dur": 100, "completed": False, "updatedAt": VALID_MS},
    )
    isolated = read_json(paths["watch"])["2026-08-26"]
    matrix.check(
        "W08",
        isolated["sid-a"]["isolate-a"]["last"] == 10
        and isolated["sid-b"]["isolate-b"]["last"] == 20
        and "isolate-b" not in isolated["sid-a"],
        "date SID and MID records remain isolated",
    )

    before_bad_watch = paths["watch"].read_bytes()
    before_bad_progress = paths["progress"].read_bytes()
    bad = client.post("/api/watch", json=watch_payload("bad-number", last="bad"), headers=academy)
    missing = client.post("/api/watch", json=watch_payload("", last=1), headers=academy)
    impossible_watch = client.post(
        "/api/watch",
        json=watch_payload("bad-date", date="2026-02-30", last=20),
        headers=academy,
    )
    impossible_status = client.post(
        "/api/watch-status",
        json={
            "date": "2026-02-30",
            "sid": "sid-a",
            "mid": "bad-date-status",
            "status": "done",
        },
        headers=academy,
    )
    impossible_latest = client.get(
        "/api/watch/latest?sid=sid-a&date=2026-02-30"
    )
    matrix.check(
        "W09",
        bad.status_code == 400
        and missing.status_code == 400
        and impossible_watch.status_code == 400
        and impossible_status.status_code == 400
        and impossible_latest.status_code == 400
        and impossible_watch.get_json() == {"ok": False, "error": "bad date"}
        and impossible_status.get_json() == {"ok": False, "error": "bad date"}
        and impossible_latest.get_json() == {"ok": False, "error": "bad date"}
        and paths["watch"].read_bytes() == before_bad_watch
        and paths["progress"].read_bytes() == before_bad_progress,
        "invalid numeric, identity, and impossible-date inputs fail before persistence",
    )

    blocked = client.post("/api/watch", json=watch_payload("blocked", last=20))
    matrix.check("W10", blocked.status_code == 403 and blocked.get_json()["error"] == "academy_network_required", "outside-academy write is blocked")

    ghost = client.post("/api/watch", json=watch_payload("ghost-mid", last=20, sid="ghost"), headers=academy)
    matrix.check("W11", ghost.status_code == 403, "ghost student write is blocked")

    public_headers = {"X-Public": "1", "X-Client-IP": "academy-ip", "X-Active-SID": "sid-a"}
    mismatch = client.post(
        "/api/watch",
        json=watch_payload("public-mismatch", last=20, sid="sid-b"),
        headers=public_headers,
    )
    accepted = client.post(
        "/api/watch",
        json=watch_payload("public-match", last=20, sid="sid-a"),
        headers=public_headers,
    )
    matrix.check("W12", mismatch.status_code == 403 and accepted.status_code == 200, "public session binds writes to its active SID")

    raw_public = client.get("/api/watch", headers=public_headers)
    raw_local = client.get("/api/watch")
    matrix.check("W13", raw_public.status_code == 404 and raw_local.status_code == 200, "public GET hides raw multi-student watch store")

    writer.save_watch_entry(
        paths["watch"],
        "2026-08-20",
        "latest-sid",
        "latest-mid",
        {"last": 70, "dur": 100, "completed": False, "updatedAt": VALID_MS + 10},
    )
    writer.save_watch_entry(
        paths["watch"],
        "2026-08-21",
        "latest-sid",
        "latest-mid",
        {"last": 60, "dur": 100, "completed": True, "updatedAt": VALID_MS},
    )
    latest = client.get("/api/watch/latest?sid=latest-sid").get_json()["watch"]["latest-mid"]
    dated = client.get("/api/watch/latest?sid=latest-sid&date=2026-08-20").get_json()["watch"]["latest-mid"]
    matrix.check(
        "W14",
        latest["completed"] is True and dated["completed"] is False and dated["last"] == 70,
        "latest projection ranks completion and honors an explicit date filter",
    )

    manual_date = "2026-08-30"
    manual_states = {
        "manual-none": "none",
        "manual-skip": "skip",
        "manual-interrupted": "interrupted",
        "manual-done": "done",
    }
    progress = read_json(paths["progress"])
    progress[manual_date] = {
        "sid-a": {
            **manual_states,
            "__manualProgressMids": {mid: True for mid in manual_states},
        }
    }
    write_json(paths["progress"], progress)
    kept = {}
    for mid, expected in manual_states.items():
        response = client.post(
            "/api/watch-status",
            json={"date": manual_date, "sid": "sid-a", "mid": mid, "status": "done"},
            headers=academy,
        )
        kept[mid] = response.get_json()["progress"].get(mid)
    matrix.check("W15", kept == manual_states, "auto watch status preserves every explicit manual state")

    writer.save_progress_status(
        paths["progress"], paths["students"], paths["videos"], manual_date, "sid-a", "auto-clear", "interrupted"
    )
    cleared = client.post(
        "/api/watch-status",
        json={"date": manual_date, "sid": "sid-a", "mid": "auto-clear", "status": ""},
        headers=academy,
    ).get_json()["progress"]
    writer.save_progress_status(
        paths["progress"], paths["students"], paths["videos"], manual_date, "sid-a", "auto-done", "done"
    )
    kept_done = client.post(
        "/api/watch-status",
        json={"date": manual_date, "sid": "sid-a", "mid": "auto-done", "status": ""},
        headers=academy,
    ).get_json()["progress"]
    matrix.check(
        "W16",
        "auto-clear" not in cleared and kept_done["auto-done"] == "done",
        "empty auto status clears only auto incomplete and never downgrades done",
    )

    writer.save_watch_entry(
        paths["watch"],
        manual_date,
        "sid-a",
        "status-promote",
        {"last": 95, "dur": 100, "completed": False, "updatedAt": VALID_MS},
    )
    promoted = client.post(
        "/api/watch-status",
        json={"date": manual_date, "sid": "sid-a", "mid": "status-promote", "status": "interrupted"},
        headers=academy,
    )
    matrix.check("W17", promoted.get_json()["progress"]["status-promote"] == "done", "compatibility status endpoint promotes interrupted when watch is done")

    bad_status = client.post(
        "/api/watch-status",
        json={"date": manual_date, "sid": "sid-a", "mid": "bad-status", "status": "bogus"},
        headers=academy,
    )
    blocked_status = client.post(
        "/api/watch-status",
        json={"date": manual_date, "sid": "sid-a", "mid": "blocked-status", "status": "done"},
    )
    matrix.check("W18", bad_status.status_code == 400 and blocked_status.status_code == 403, "compatibility endpoint rejects bad status and outside-academy writes")

    repaired = writer.save_watch_entry(
        paths["watch"],
        DATE,
        "sid-a",
        "timestamp-repair",
        {"last": 1, "dur": 100, "completed": False, "updatedAt": 667_934_656},
        now_ms=VALID_MS + 999,
    )
    preserved = writer.save_watch_entry(
        paths["watch"],
        DATE,
        "sid-a",
        "timestamp-valid",
        {"last": 1, "dur": 100, "completed": False, "updatedAt": VALID_MS - 1},
        now_ms=VALID_MS + 999,
    )
    matrix.check(
        "W19",
        repaired["updatedAt"] == VALID_MS + 999 and preserved["updatedAt"] == VALID_MS - 1,
        "server repairs legacy timestamps and preserves valid epoch milliseconds",
    )

    original_snapshot = writer.progress_notification_snapshot
    original_commit = writer.commit_progress_notifications
    original_save = writer.save_progress_strict
    events = []

    def snapshot(progress_value, sid, **_kwargs):
        events.append(("snapshot", copy.deepcopy(progress_value)))
        return ("repository", "scope", len(events))

    def commit(before, after, sid):
        stored = read_json(paths["progress"])
        assert stored["2026-08-31"]["sid-a"]["notify-mid"] == "done"
        events.append(("commit", before, after, sid))
        return 1

    writer.progress_notification_snapshot = snapshot
    writer.commit_progress_notifications = commit
    try:
        writer.save_progress_status(
            paths["progress"], paths["students"], paths["videos"], "2026-08-31", "sid-a", "notify-mid", "done"
        )
        successful_order = [item[0] for item in events]
        commit_count = successful_order.count("commit")

        def fail_save(_path, _value):
            raise OSError("synthetic progress save failure")

        writer.save_progress_strict = fail_save
        try:
            writer.save_progress_status(
                paths["progress"], paths["students"], paths["videos"], "2026-09-01", "sid-a", "notify-fail", "done"
            )
        except OSError:
            pass
        else:
            raise AssertionError("synthetic progress save failure did not fire")
        matrix.check(
            "W20",
            successful_order == ["snapshot", "snapshot", "commit"]
            and [item[0] for item in events].count("commit") == commit_count,
            "progress notifications run only after a successful persisted commit",
        )
    finally:
        writer.progress_notification_snapshot = original_snapshot
        writer.commit_progress_notifications = original_commit
        writer.save_progress_strict = original_save

    matrix.check("W21", paths["updates"].read_bytes() == updates_before, "watch writes never resize or refill assignment snapshots")


def run_kollus_cases(matrix: Matrix, env: dict) -> None:
    client = env["client"]
    paths = env["paths"]
    kollus = env["kollus"]
    headers = {"X-Kollus-Secret": SECRET}

    before = paths["watch"].read_bytes()
    ignored = client.post("/api/kollus/lms-callback", json=callback_body("kol-0000"), headers=headers)
    matrix.check(
        "K01",
        ignored.status_code == 200 and ignored.get_json()["ignored"] is True and paths["watch"].read_bytes() == before,
        "zero-progress callback is acknowledged without persistence",
    )

    under = client.post(
        "/api/kollus/lms-callback",
        json=callback_body("kol-0004", last=4, pct=4),
        headers=headers,
    )
    matrix.check(
        "K02",
        under.status_code == 200 and under.get_json()["watch"]["last"] == 4 and under.get_json()["progress"] == {},
        "Kollus under 5 percent stores watch without progress",
    )

    started = client.post(
        "/api/kollus/lms-callback",
        json=callback_body("kol-0005", last=5, pct=5),
        headers=headers,
    )
    matrix.check("K03", started.get_json()["progress"]["kol-0005"] == "interrupted", "Kollus 5 percent creates interrupted")

    percent_done = client.post(
        "/api/kollus/lms-callback",
        json=callback_body("kol-0090", last=10, pct=90),
        headers=headers,
    )
    matrix.check(
        "K04",
        percent_done.get_json()["watch"]["completed"] is True
        and percent_done.get_json()["progress"]["kol-0090"] == "done",
        "Kollus 90 percent flag creates done",
    )

    position_done = client.post(
        "/api/kollus/lms-callback",
        json=callback_body("kol-last", last=90, pct=0),
        headers=headers,
    )
    matrix.check("K05", position_done.get_json()["progress"]["kol-last"] == "done", "Kollus last/duration ratio also creates done")

    unknown_duration = client.post(
        "/api/kollus/lms-callback",
        json=callback_body("kol-unknown-duration", last=0, dur=0, play_time=1),
        headers=headers,
    )
    matrix.check(
        "K06",
        unknown_duration.get_json()["watch"]["last"] == 0
        and unknown_duration.get_json()["progress"]["kol-unknown-duration"] == "interrupted",
        "Kollus positive play time with unknown duration counts as started",
    )

    client.post(
        "/api/kollus/lms-callback",
        json=callback_body("kol-stale", last=90, pct=90),
        headers=headers,
    )
    stale = client.post(
        "/api/kollus/lms-callback",
        json=callback_body("kol-stale", last=5, pct=5),
        headers=headers,
    ).get_json()
    matrix.check(
        "K07",
        stale["watch"]["last"] == 90
        and stale["watch"]["completed"] is True
        and stale["progress"]["kol-stale"] == "done",
        "later stale Kollus callback cannot regress completed watch or progress",
    )

    callback_date = dt.datetime.fromtimestamp(1_787_390_000, tz=KST).date().isoformat()
    progress = read_json(paths["progress"])
    progress.setdefault(callback_date, {}).setdefault("sid-a", {}).update(
        {
            "kol-manual": "none",
            "__manualProgressMids": {"kol-manual": True},
        }
    )
    write_json(paths["progress"], progress)
    manual = client.post(
        "/api/kollus/lms-callback",
        json=callback_body("kol-manual", last=90, pct=90),
        headers=headers,
    )
    matrix.check("K08", manual.get_json()["progress"]["kol-manual"] == "none", "Kollus completion preserves manual white")

    unknown_sid = client.post(
        "/api/kollus/lms-callback",
        json=callback_body("kol-0005", sid="unknown", last=5, pct=5),
        headers=headers,
    )
    unknown_mid = client.post(
        "/api/kollus/lms-callback",
        json=callback_body("unknown-mid", last=5, pct=5),
        headers=headers,
    )
    bad_mid = client.post(
        "/api/kollus/lms-callback",
        json=callback_body("!", last=5, pct=5),
        headers=headers,
    )
    missing = client.post(
        "/api/kollus/lms-callback",
        json={"sid": "sid-a"},
        headers=headers,
    )
    matrix.check(
        "K09",
        (unknown_sid.status_code, unknown_mid.status_code, bad_mid.status_code, missing.status_code)
        == (404, 404, 400, 400),
        "Kollus callback rejects unknown or malformed identities",
    )

    original_secret = kollus._callback_secret
    kollus._callback_secret = lambda: ""
    try:
        unconfigured = client.post(
            "/api/kollus/lms-callback",
            json=callback_body("kol-0005", last=5, pct=5),
            headers=headers,
        )
    finally:
        kollus._callback_secret = original_secret
    matrix.check("K10", unconfigured.status_code == 403, "Kollus callback fails closed when secret is unset")

    start_at = 1_787_390_000
    dated = client.post(
        "/api/kollus/lms-callback",
        json=callback_body("kol-0005", last=6, pct=6, start_at=start_at),
        headers=headers,
    ).get_json()
    expected_date = dt.datetime.fromtimestamp(start_at, tz=KST).date().isoformat()
    matrix.check("K11", dated["date"] == expected_date, "Kollus callback date is derived in KST")


def main() -> int:
    matrix = Matrix()
    with isolated_routes() as env:
        run_browser_and_writer_cases(matrix, env)
        run_kollus_cases(matrix, env)

    from scripts.verify_kollus_callback_auth import main as verify_callback_auth

    matrix.check("K12", verify_callback_auth() == 0, "signed tampered expired static-secret and unset-secret auth matrix passes")
    print(f"video progress integration matrix: {matrix.passed}/{matrix.passed} cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
