"""Temp-only contracts for the session-bound student board."""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask, g, request

from core.student_board_projection import project_student_board, student_board_announcement_visible
from core.student_push_authority import _visible_announcement
from routes.api_student_board import StudentBoardApiDependencies, create_blueprint


NOW = dt.datetime(2026, 8, 9, 4, 0, tzinfo=dt.timezone.utc)


def _ann(identifier: str, *, kind: str = "announcement", targets=None, created="2026-08-09T03:00:00Z", expires="2026-08-10T03:00:00Z", **extra):
    return {
        "id": identifier,
        "kind": kind,
        "title": f"title-{identifier}",
        "content": f"content-{identifier}",
        "targetSids": targets or ["sid-a"],
        "createdAt": created,
        "expiresAt": expires,
        **extra,
    }


def _fixture():
    rows = [
        _ann("own"),
        _ann("foreign", targets=["sid-b"]),
        _ann("future", created="2026-08-09T05:00:00Z"),
        _ann("expired", expires="2026-08-09T04:00:00Z"),
        _ann("draft", status="draft"),
        _ann("deleted", deleted=True),
        _ann("survey-ok", kind="survey", survey={"status": "public", "questions": [{"id": "q1"}]}),
        _ann("survey-draft", kind="survey", survey={"status": "draft", "questions": [{"id": "q1"}]}),
        _ann("video-ok", kind="video", videoMid="video_mid_1", images=[{
            "path": "announcements/thumb.png", "url": "https://evil.example/SECRET"
        }]),
        _ann("video-bad", kind="video", videoMid="missing_mid"),
    ]
    return rows, {"sid-a": {"own": {"acked": True}}}, [{
        "mid": "video_mid_1", "title": "catalog", "url": "SECRET_PLAYBACK_MARKER", "curriculum": "SECRET_INTERNAL"
    }]


def _app(rows, statuses, videos):
    app = Flask(__name__)
    deps = StudentBoardApiDependencies(lambda: rows, lambda: statuses, lambda: videos, lambda: NOW)
    app.register_blueprint(create_blueprint(deps))

    @app.before_request
    def _surface():
        g.student_app_public_request = request.headers.get("X-Public", "1") == "1"
        g.student_app_active_sid = request.headers.get("X-Sid", "sid-a")
        g.student_app_client_ip = request.headers.get("X-Client-IP", "203.0.113.9")

    return app


def _json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _admin_video_contract() -> int:
    import routes.api_announcements as announcements

    checks = 0
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        students = root / "students.json"
        videos = root / "videos.json"
        statuses = root / "announcement_status.json"
        students.write_text('[{"id":"sid-a","name":"A"}]', encoding="utf-8")
        videos.write_text('[{"mid":"video_mid_1","url":"SECRET"}]', encoding="utf-8")
        statuses.write_text('{}', encoding="utf-8")
        old_students, old_videos, old_statuses = announcements.STU_PATH, announcements.VID_PATH, announcements.ANN_STATUS_PATH
        announcements.STU_PATH, announcements.VID_PATH, announcements.ANN_STATUS_PATH = students, videos, statuses
        try:
            app = Flask(__name__)
            base = {"kind": "video", "title": "Video", "content": "Watch", "targetSids": ["sid-a"]}
            with app.test_request_context("/"):
                valid, error = announcements._announcement_from_body({**base, "videoMid": "video_mid_1"})
                assert error is None and valid["videoMid"] == "video_mid_1" and "url" not in valid
                checks += 1
                invalid, error = announcements._announcement_from_body({**base, "videoMid": "missing_mid"})
                assert invalid is None and error[1] == 400
                checks += 1
                summary = announcements._summary_for_admin([valid])
                assert summary[0].get("kind") == "video" and summary[0].get("videoMid") == "video_mid_1"
                assert "SECRET" not in _json_text(summary)
                checks += 2
        finally:
            announcements.STU_PATH, announcements.VID_PATH, announcements.ANN_STATUS_PATH = old_students, old_videos, old_statuses
    return checks


def run_checks():
    checks = 0
    rows, statuses, videos = _fixture()
    client = _app(rows, statuses, videos).test_client()

    response = client.get("/api/mobile/student/board")
    payload = response.get_json()
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    checks += 1
    ids = [item["id"] for item in payload["items"]]
    assert ids == ["video-ok", "survey-ok", "own"]
    checks += 1
    assert not {"foreign", "future", "expired", "draft", "deleted", "survey-draft", "video-bad"}.intersection(ids)
    checks += 1
    own = next(item for item in payload["items"] if item["id"] == "own")
    assert own["read"] is True and set(own) == {
        "id", "type", "kind", "title", "content", "createdAt", "expiresAt", "read",
        "notificationEventId", "images", "requireCompletion",
    }
    checks += 1
    video = next(item for item in payload["items"] if item["type"] == "video")
    assert video["locked"] is True and video["thumbnail"] == "/files/announcements/thumb.png"
    checks += 1
    assert not any(marker in _json_text(payload) for marker in ("SECRET", "curriculum", "targetSids", "sid-a"))
    checks += 1

    notice = client.get("/api/mobile/student/board?type=notice").get_json()
    video_page = client.get("/api/mobile/student/board?type=video").get_json()
    assert all(item["type"] == "notice" for item in notice["items"])
    assert [item["id"] for item in video_page["items"]] == ["video-ok"]
    checks += 2
    academy = client.get("/api/mobile/student/board?type=video", headers={"X-Client-IP": "192.168.1.20"}).get_json()
    assert academy["items"][0]["locked"] is False and "url" not in _json_text(academy).lower()
    checks += 1

    assert client.get("/api/mobile/student/board?sid=sid-b").status_code == 400
    assert client.get("/api/mobile/student/board?type=all&type=video").status_code == 400
    assert client.get("/api/mobile/student/board?cursor=").status_code == 400
    assert client.get("/api/mobile/student/board?cursor=not-base64").status_code == 400
    checks += 4
    assert client.get("/api/mobile/student/board", headers={"X-Sid": ""}).status_code == 401
    assert client.get("/api/mobile/student/board", headers={"X-Public": "0"}).status_code == 404
    checks += 2

    paged_rows = [_ann(f"item-{index:03d}", created=f"2026-08-09T03:{59 - index % 60:02d}:00Z") for index in range(70)]
    paged_client = _app(paged_rows, {}, []).test_client()
    first = paged_client.get("/api/mobile/student/board?type=notice").get_json()
    second = paged_client.get(f"/api/mobile/student/board?type=notice&cursor={first['nextCursor']}").get_json()
    assert len(first["items"]) == 50 and len(second["items"]) == 20
    assert not {item["id"] for item in first["items"]}.intersection(item["id"] for item in second["items"])
    checks += 2
    assert paged_client.get(f"/api/mobile/student/board?type=video&cursor={first['nextCursor']}").status_code == 400
    checks += 1

    removed = [row for row in rows if row["id"] != "own"]
    assert "own" not in [item["id"] for item in project_student_board(removed, statuses, videos, sid="sid-a", now=NOW)["items"]]
    checks += 1
    for row in rows:
        if row["id"] in {"own", "draft", "deleted", "survey-ok", "survey-draft"}:
            expected = student_board_announcement_visible(row, "sid-a", NOW)
            assert _visible_announcement([row], row["id"], "sid-a", NOW) is expected
            checks += 1

    checks += _admin_video_contract()
    return {"name": "board", "assertions": checks, "passed": True}


if __name__ == "__main__":
    print(json.dumps(run_checks(), ensure_ascii=False))
