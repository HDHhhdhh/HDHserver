from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_video_progress_matrix import isolated_routes, read_json, write_json, SECRET
from core.progress_store import reset_progress_cache
from core.student_video_projection import build_auto_assignment_blocked_by_sid
from core.video_review_rules import resolve_video_review_states_before_date
from core.video_watch_cycles import latest_watch_projection
from routes import api_progress

DATE = "2026-09-12"
SID = "sid-a"
MID = "kol-manual"
TOKEN = "fresh_watch_cycle_0001"
NEXT = "fresh_watch_cycle_0002"


def main() -> int:
    from core.video_catalog_correction import apply_video_catalog_correction, build_correction_draft
    before_catalog = [{"id": 1, "mid": "cycle-old", "url": "https://v.kr.kollus.com/cycle-old"}]
    after_catalog = [{"id": 1, "mid": "cycle-new", "url": "https://v.kr.kollus.com/cycle-new"}]
    cycle = {"token": TOKEN, "startedAt": 1789200000000, "watch": {"last": 0, "dur": 0, "completed": False, "updatedAt": 1789200000000}}
    old_progress = {DATE: {SID: {"cycle-old": "none", "__autoWatchProgressMids": {"cycle-old": "none"}, "__videoWatchCycles": {"cycle-old": cycle}}}}
    draft = build_correction_draft(before_catalog, after_catalog, created_at="2026-09-12T12:00:00Z")
    corrected = apply_video_catalog_correction(current_videos=before_catalog, draft=draft, updates={}, progress=old_progress, watch={})
    assert corrected["progress"][DATE][SID]["cycle-new"] == "none"
    assert corrected["progress"][DATE][SID]["__autoWatchProgressMids"] == {"cycle-new": "none"}
    assert corrected["progress"][DATE][SID]["__videoWatchCycles"] == {"cycle-new": cycle}
    with isolated_routes() as env:
        paths, writer, watch, kollus = (env[key] for key in ("paths", "writer", "watch", "kollus"))
        with patch.multiple(api_progress, PRG_PATH=paths["progress"], STU_PATH=paths["students"], VID_PATH=paths["videos"],
                            is_ghost_student_sid=lambda sid: False,
                            _notification_progress_snapshot=lambda *_: {}, _notification_progress_commit=lambda *_: 0):
            app = Flask("fresh-watch-cycle")
            app.register_blueprint(api_progress.bp_api_progress)
            app.register_blueprint(watch.bp_api_watch)
            app.register_blueprint(kollus.bp_api_kollus)
            client = app.test_client()
            history = {"2026-09-11": {SID: {MID: "done"}}, DATE: {SID: {
                MID: "none", "untouched": "skip", "legacy": {"keep": True},
                "__manualProgressMids": {MID: True, "untouched": True},
            }}}
            old_watch = {DATE: {SID: {MID: {"last": 100, "dur": 100, "completed": True, "updatedAt": 1789000000000}}}}
            write_json(paths["progress"], history)
            write_json(paths["watch"], old_watch)
            reset_progress_cache()
            unchanged_updates = paths["updates"].read_bytes()

            def rearm(token=TOKEN, base="", **overrides):
                body = {"date": DATE, "sid": SID, "progress": {MID: "none"},
                        "resumeAutoWatch": {MID: {"token": token, "baseToken": base}}, **overrides}
                return client.post("/api/progress/patch", json=body)

            def observe(last, token=TOKEN, **overrides):
                body = {"date": DATE, "sid": SID, "mid": MID, "last": last, "dur": 100,
                        "completed": last >= 90, "updatedAt": 1789200000000, "cycleToken": token, **overrides}
                return client.post("/api/watch", json=body, headers={"X-Academy": "1"})

            armed = rearm()
            assert armed.status_code == 200, armed.get_json()
            with patch.object(kollus, "academy_network_allowed", lambda: True):
                playback_url = client.get(f"/api/get-url?sid={SID}&mid={MID}")
            assert playback_url.status_code == 200
            assert json.loads(playback_url.headers["X-Video-Watch-State"])["cycleToken"] == TOKEN
            assert "uservalue0=v2." in playback_url.get_data(as_text=True)
            entry = armed.get_json()["progress"]
            assert entry[MID] == "none" and MID not in entry["__manualProgressMids"]
            assert entry["__autoWatchProgressMids"][MID] == "none"
            assert entry["legacy"] == {"keep": True} and entry["untouched"] == "skip"
            assert read_json(paths["watch"]) == old_watch
            latest = client.get(f"/api/watch/latest?sid={SID}&date={DATE}").get_json()["watch"][MID]
            assert latest["last"] == 0 and latest["completed"] is False and latest["cycleToken"] == TOKEN
            assert MID not in build_auto_assignment_blocked_by_sid(read_json(paths["progress"]), old_watch).get(SID, set())
            before_stale = paths["progress"].read_bytes()
            assert observe(100, token="").status_code == 409
            assert paths["progress"].read_bytes() == before_stale
            assert client.post("/api/progress/patch", json={"date": DATE, "sid": SID, "source": "auto", "progress": {MID: "done"}}).status_code == 409
            assert paths["progress"].read_bytes() == before_stale
            assert observe(4).get_json()["progress"][MID] == "none"
            assert observe(5).get_json()["progress"][MID] == "interrupted"
            assert observe(90).get_json()["progress"][MID] == "done"
            done_bytes = paths["progress"].read_bytes()
            assert rearm().get_json()["progress"][MID] == "done"
            assert paths["progress"].read_bytes() == done_bytes, "retry reset an already completed generation"
            assert rearm(NEXT, TOKEN).get_json()["progress"][MID] == "none"
            before_stale = paths["progress"].read_bytes()
            assert rearm().status_code == 409, "older admin save must fail closed"
            assert observe(100, TOKEN).status_code == 409
            assert paths["progress"].read_bytes() == before_stale

            # Literal ownership negatives, even with valid fresh player observations.
            for state in ("none", "interrupted", "skip"):
                client.post("/api/progress/patch", json={"date": DATE, "sid": SID, "progress": {MID: state}})
                assert observe(100, NEXT).get_json()["progress"][MID] == state
            token3 = "fresh_watch_cycle_0003"
            assert rearm(token3, NEXT).status_code == 200

            # Signed provider sessions remain supported; older/unscoped sessions cannot complete a new cycle.
            import time
            now = str(int(time.time()))
            def callback(token, last=95, pct=95):
                return client.post("/api/kollus/lms-callback", json={"uservalue0": token,
                    # The provider sends epoch seconds; a date string falls back
                    # to real today and makes this fixture fail after September 12.
                    "media_content_key": MID, "start_at": 1_789_182_000, "last_play_at": last,
                    "duration": 100, "playtime_percent": pct}, headers={"X-Kollus-Secret": SECRET})
            stale_token = kollus._encode_callback_token(SECRET, SID, MID, now)
            assert callback(stale_token).get_json()["progress"][MID] == "none"
            signed = kollus._encode_callback_token(SECRET, SID, MID, now, token3)
            assert callback(signed, last=0, pct=5).get_json()["progress"][MID] == "interrupted"
            assert callback(signed).get_json()["progress"][MID] == "done"
            assert kollus._decode_callback_session(signed.replace(token3, NEXT), MID, SECRET)[1] is False

            token4 = "fresh_watch_cycle_0004"
            assert rearm(token4, token3).status_code == 200
            assert observe(10, token4, date="2026-09-13").get_json()["progress"][MID] == "interrupted"
            data = read_json(paths["progress"])
            latest = latest_watch_projection(read_json(paths["watch"]), data, SID, "2026-09-13")[MID]
            assert latest["last"] == 10 and latest["cycleToken"] == token4 and not latest["completed"]
            assert latest_watch_projection(old_watch, data, SID, "2026-09-11").get(MID) is None
            states = resolve_video_review_states_before_date(data, read_json(paths["watch"]), sid_keys=[SID], before_date="2026-09-14")
            assert states[MID]["status"] == "interrupted"

            # Reject malformed/source-confused commands and failed persistence without changing any bytes.
            before_failure = paths["progress"].read_bytes()
            for body in ({"resumeAutoWatch": []}, {"resumeAutoWatch": {MID: {"token": "short", "baseToken": ""}}},
                         {"source": "auto"}, {"source": "allStudents"}, {"date": "2026-02-30"},
                         {"progress": {MID: "done"}}):
                assert rearm(**body).status_code == 400
                assert paths["progress"].read_bytes() == before_failure
            with patch.object(api_progress, "_save_progress_strict", side_effect=OSError("fixture failure")):
                assert rearm("fresh_watch_cycle_0005", token4).status_code == 500
            assert paths["progress"].read_bytes() == before_failure
            assert paths["updates"].read_bytes() == unchanged_updates
            assert read_json(paths["progress"])["2026-09-11"] == history["2026-09-11"]
            reset_progress_cache()  # restart-equivalent disk read, not a memory-only success
            persisted = client.get(f"/api/progress?sid={SID}&date={DATE}")
            assert persisted.headers["X-Video-Watch-Cycles"] == "1"
            assert persisted.get_json()[DATE][SID]["__videoWatchCycles"][MID]["token"] == token4
            barrier = Barrier(2)
            def concurrent_rearm(token):
                barrier.wait(timeout=5)
                with app.test_client() as other:
                    result = other.post("/api/progress/patch", json={"date": DATE, "sid": SID, "progress": {},
                        "resumeAutoWatch": {MID: {"token": token, "baseToken": token4}}})
                    return token, result.status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(concurrent_rearm, ["concurrent_cycle_00001", "concurrent_cycle_00002"]))
            assert sorted(status for _, status in results) == [200, 409]
            winner = next(token for token, status in results if status == 200)
            assert read_json(paths["progress"])[DATE][SID]["__videoWatchCycles"][MID]["token"] == winner
    print("fresh-watch rearm: route/ownership/history/generation/retry/callback/date/failure/disk gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
