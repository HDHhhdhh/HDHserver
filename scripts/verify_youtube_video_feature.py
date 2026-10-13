"""Synthetic-only YouTube/overlay route and rule regression; never imports live paths."""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATE = "2026-09-13"
VIDEO_ID = "NSorUwxBPGg"
LIST_ID = "PL0dm9k63r76anfvN8b2EPD1r_dbu_dat8"


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class YouTubeFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="verify-youtube-video-")
        cls.root = Path(cls.temp.name)
        paths = types.ModuleType("core.paths")
        paths.BASE = cls.root
        paths.DATA_DIR = cls.root / "data"
        paths.FILES_DIR = cls.root / "files"
        paths.DATA_DIR.mkdir()
        paths.FILES_DIR.mkdir()
        # Discover names as text only; executing core.paths would initialize live stores.
        names = re.findall(r"^([A-Z_]+_PATH)\s*=", (ROOT / "core/paths.py").read_text("utf-8"), re.M)
        for name in names:
            setattr(paths, name, cls.root / f"{name.lower()}.json")
        sys.modules["core.paths"] = paths
        cls.paths = paths
        os.environ["DATA_MIRROR_DIR"] = str(cls.root / "mirror")
        os.environ["DB_PATH"] = str(cls.root / "app.sqlite")
        from flask import Flask, g
        from core.absence_transaction import absence_consistency_barrier
        from routes import api_videos, api_students, api_kollus, api_watch, api_progress
        cls.videos_api, cls.students_api = api_videos, api_students
        cls.kollus_api, cls.watch_api, cls.progress_api = api_kollus, api_watch, api_progress
        app = Flask("youtube-feature-temp")
        for blueprint in (api_videos.bp_api_videos, api_students.bp_api_students,
                          api_kollus.bp_api_kollus, api_watch.bp_api_watch, api_progress.bp_api_progress):
            app.register_blueprint(blueprint)

        @app.before_request
        def enter_barrier():
            lease = absence_consistency_barrier(absent_path=paths.ABS_PATH)
            lease.__enter__()
            g.test_lease = lease

        @app.teardown_request
        def exit_barrier(error):
            lease = getattr(g, "test_lease", None)
            if lease:
                lease.__exit__(None, None, None)

        cls.app = app

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        from core.progress_store import reset_progress_cache
        from core.video_sources import parse_youtube_url
        self.client = self.app.test_client()
        self.video = {"id": 101, "curriculum": "기하", "subCurriculum": "기출엄선", "chapter": 1,
                      "title": "기하 영상", **parse_youtube_url(f"https://youtu.be/{VIDEO_ID}?t=1m30s", catalog_id=101)}
        self.playlist = {"id": 102, "curriculum": "기하", "subCurriculum": "기출엄선", "chapter": 2,
                         "title": "기하 묶음", **parse_youtube_url(f"https://www.youtube.com/playlist?list={LIST_ID}", catalog_id=102)}
        self.kollus = {"id": 1, "mid": "kollus-one", "url": "https://v.kr.kollus.com/kollus-one",
                       "curriculum": "기하", "subCurriculum": "APEX", "chapter": 1, "title": "기존 과정"}
        self.catalog = [self.kollus, self.video, self.playlist]
        for name in vars(self.paths):
            if name.endswith("_PATH") and name not in {"PERSONS_PATH", "PERSON_IDENTITY_JOURNAL_PATH"}:
                write(getattr(self.paths, name), {})
        write(self.paths.STU_PATH, [{"id": "s1", "name": "QA 학생", "curriculum": "기하", "subCurriculum": "APEX"},
                                    {"id": "s2", "curriculum": "기하", "subCurriculum": "APEX"}])
        write(self.paths.VID_PATH, self.catalog)
        write(self.paths.UPD_PATH, {DATE: {"s1": {"videos": [self.video["mid"], self.playlist["mid"], "kollus-one"], "source": "auto"}}})
        write(self.paths.LOGS_PATH, {DATE: {"s1": {"done": True, "archived": False, "notes": "유지"}}})
        write(self.paths.PRG_PATH, {DATE: {"s1": {"tests": {"기존 시험": "assigned"}, "unknown": {"keep": True}}}, "2026-09-12": {"s2": {"other": "done"}}})
        reset_progress_cache()
        self.progress_api._notification_progress_snapshot = lambda *_: None
        self.progress_api._notification_progress_commit = lambda *_: 0
        self.kollus_api._academy_request_allowed = lambda: True
        self.watch_api._academy_request_allowed = lambda: True
        self.students_api.enqueue_current_schedule_changes = lambda *_: None

    def test_url_forms_identity_start_and_negatives(self):
        from core.video_sources import parse_youtube_url, youtube_embed_url
        for url in (f"https://youtu.be/{VIDEO_ID}?t=90", f"https://www.youtube.com/watch?v={VIDEO_ID}&list={LIST_ID}&t=1m30s",
                    f"https://m.youtube.com/shorts/{VIDEO_ID}?start=90", f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}#t=90"):
            source = parse_youtube_url(url, catalog_id=101)
            self.assertEqual(source, {"provider": "youtube", "youtubeKind": "video", "youtubeId": VIDEO_ID,
                                      "mid": f"ytv_{VIDEO_ID}_r101", "youtubeStart": 90,
                                      "url": f"https://www.youtube.com/watch?v={VIDEO_ID}&t=90"})
        self.assertEqual(youtube_embed_url(self.video), f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}?autoplay=0&playsinline=1&rel=0&start=90")
        self.assertIn("/embed/videoseries?autoplay=0", youtube_embed_url(self.playlist))
        for url in ("https://youtube.com.evil.invalid/watch?v=" + VIDEO_ID, "javascript:alert(1)", "https://example.com/youtube.com/watch?v=" + VIDEO_ID):
            self.assertIsNone(parse_youtube_url(url))
        for url in (f"https://youtube.com/live/{VIDEO_ID}", "https://youtube.com/watch?v=bad", f"https://u:p@youtube.com/watch?v={VIDEO_ID}",
                    f"https://youtube.com/watch?v={VIDEO_ID}&v={VIDEO_ID}", f"https://youtube.com/watch?v={VIDEO_ID}&t=bad"):
            with self.assertRaises(ValueError):
                parse_youtube_url(url)

    def test_catalog_normalization_duplicate_and_identity_guards(self):
        response = self.client.get("/api/videos")
        self.assertEqual(response.headers["X-Video-Providers"], "kollus,youtube")
        self.assertTrue(self.client.get("/api/video-capabilities").json["youtubeRecordCleanup"])
        before = self.paths.VID_PATH.read_bytes()
        duplicate = {**self.video, "id": 103, "url": f"https://youtube.com/watch?v={VIDEO_ID}&t=4"}
        self.assertEqual(self.client.post("/api/videos", json=[*self.catalog, duplicate]).status_code, 400)
        self.assertEqual(self.paths.VID_PATH.read_bytes(), before)
        changed = copy.deepcopy(self.catalog)
        changed[1]["url"] = "https://youtu.be/05dQDtpsae8"
        self.assertEqual(self.client.post("/api/videos", json=changed).status_code, 409)
        self.assertEqual(self.paths.VID_PATH.read_bytes(), before)
        changed[1] = {**self.video, "title": "수정 제목", "url": f"https://youtube.com/watch?v={VIDEO_ID}&t=15"}
        self.assertEqual(self.client.post("/api/videos", json=changed).status_code, 204)
        self.assertEqual(json.loads(self.paths.VID_PATH.read_text("utf-8"))[1]["youtubeStart"], 15)
        duplicate["subCurriculum"] = "APEX"
        self.assertEqual(self.client.post("/api/videos", json=[*changed, duplicate]).status_code, 204)
        rows = json.loads(self.paths.VID_PATH.read_text("utf-8"))
        self.assertNotEqual(rows[1]["mid"], rows[-1]["mid"], "Different catalog lessons must not share a progress key")
        from core.video_catalog_correction import build_correction_draft
        self.assertEqual(build_correction_draft(rows, rows, created_at=DATE)["baseVideos"], rows)

    def test_overlay_update_is_sid_only_no_assignment_hook(self):
        snapshots = {p: p.read_bytes() for p in (self.paths.UPD_PATH, self.paths.PRG_PATH, self.paths.LOGS_PATH)}
        for value in ("true", 1, None, {}, []):
            response = self.client.post("/api/update", json={"id": "s1", "field": "gichulSelectionEnabled", "value": value})
            self.assertEqual(response.status_code, 400)
        for value in (True, False):
            response = self.client.post("/api/update", json={"id": "s1", "field": "gichulSelectionEnabled", "value": value})
            self.assertEqual(response.status_code, 200)
            rows = json.loads(self.paths.STU_PATH.read_text("utf-8"))
            self.assertIs(rows[0]["gichulSelectionEnabled"], value)
            self.assertEqual(rows[0]["subCurriculum"], "APEX")
            self.assertNotIn("gichulSelectionEnabled", rows[1])
            self.assertTrue(all(p.read_bytes() == data for p, data in snapshots.items()))

    def test_overlay_identity_journal_keeps_other_sid_and_profile(self):
        from scripts.verify_person_identity_routes import literal_identity_fixture
        with tempfile.TemporaryDirectory(dir=self.root) as directory_name:
            directory_path = Path(directory_name)
            persons, students = literal_identity_fixture()
            person_path, student_path = directory_path / "persons.json", directory_path / "students.json"
            write(person_path, persons)
            write(student_path, students)
            with patch.object(self.students_api, "PERSONS_PATH", person_path), patch.object(self.students_api, "STU_PATH", student_path), patch.object(self.students_api, "PERSON_IDENTITY_JOURNAL_PATH", directory_path / "pending.json"):
                response = self.client.post("/api/update", json={"id": "소망101", "field": "gichulSelectionEnabled", "value": True})
                self.assertEqual(response.status_code, 200, response.text)
                rows = json.loads(student_path.read_text("utf-8"))
                self.assertEqual(rows[0], {**students[0], "gichulSelectionEnabled": True})
                self.assertEqual(rows[1], students[1])
                self.assertEqual(json.loads(person_path.read_text("utf-8"))["persons"], persons["persons"])
                before = student_path.read_bytes()
                response = self.client.post("/api/update", json={"id": "소망101", "field": "gichulSelectionEnabled", "value": "true"})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(student_path.read_bytes(), before)

    def test_overlay_automatic_scope_snapshot_and_review(self):
        from core.student_video_projection import student_review_video_projection, filter_auto_assignment_for_current_curriculum
        from scripts.verify_student_auto_assignment_service import FixtureRuntime, DATE as AUTO_DATE, SID, write_literal
        from routes.student_auto_assignment_service import load_updates_with_auto_assign
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            runtime = FixtureRuntime(Path(folder))
            runtime.seed()
            student = {"id": SID, "curriculum": "기하", "subCurriculum": "APEX", "gichulSelectionEnabled": True, "autoVideoAssignCount": 2, "day1": "토1"}
            write_literal(runtime.paths["students"], [student])
            write_literal(runtime.paths["videos"], self.catalog)
            # An unfinished base course is deliberately ignored for new picks.
            result = load_updates_with_auto_assign(runtime.dependencies())
            self.assertEqual(result[AUTO_DATE][SID], {"videos": [self.video["mid"], self.playlist["mid"]], "source": "auto"})
            before = runtime.paths["updates"].read_bytes()
            student["gichulSelectionEnabled"] = False
            write_literal(runtime.paths["students"], [student])
            load_updates_with_auto_assign(runtime.dependencies())
            self.assertEqual(runtime.paths["updates"].read_bytes(), before)
            self.assertEqual(filter_auto_assignment_for_current_curriculum(result[AUTO_DATE][SID], student, self.catalog), result[AUTO_DATE][SID])
            write_literal(runtime.paths["updates"], {AUTO_DATE: {SID: {"videos": ["kollus-one"], "source": "auto"}}})
            before = runtime.paths["updates"].read_bytes()
            student["gichulSelectionEnabled"] = True
            write_literal(runtime.paths["students"], [student])
            load_updates_with_auto_assign(runtime.dependencies())
            self.assertEqual(runtime.paths["updates"].read_bytes(), before)
            progress = {"2026-06-05": {SID: {"kollus-one": "done", self.video["mid"]: "done", self.playlist["mid"]: "interrupted", "other-course": "done"}}}
            extra = {**self.kollus, "mid": "other-course", "subCurriculum": "A:Ble"}
            reviews = student_review_video_projection(student, [*self.catalog, extra], progress, {}, AUTO_DATE, [], False)
            self.assertEqual({row["mid"] for row in reviews}, {"kollus-one", self.video["mid"]})
            self.assertTrue(all("url" not in row and "youtubeId" not in row and row["playbackRestricted"] for row in reviews))

    def test_academy_playback_does_not_read_or_write_watch(self):
        before = {p: p.read_bytes() for p in (self.paths.WATCH_PATH, self.paths.PRG_PATH)}
        with patch.object(self.kollus_api, "load_progress_strict", side_effect=AssertionError("YouTube read watch progress")):
            for row in (self.video, self.playlist):
                response = self.client.get("/api/get-url", query_string={"sid": "s1", "mid": row["mid"]})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Video-Provider"], "youtube")
                self.assertIn("autoplay=0", response.text)
                self.assertNotIn("X-Video-Watch-State", response.headers)
        self.kollus_api._academy_request_allowed = lambda: False
        self.assertEqual(self.client.get("/api/get-url", query_string={"sid": "s1", "mid": self.video["mid"]}).status_code, 403)
        for endpoint in ("/api/watch", "/api/watch-status"):
            self.assertEqual(self.client.post(endpoint, json={"date": DATE, "sid": "s1", "mid": self.video["mid"], "last": 500, "dur": 500, "status": "done"}).status_code, 400)
        response = self.client.post("/api/progress/patch", json={"date": DATE, "sid": "s1", "source": "auto", "progress": {self.video["mid"]: "done"}})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))

    def test_record_cleanup_precise_statuses_retry_and_independent_units(self):
        from core.video_sources import youtube_record_cleanup_patch
        mids = [self.video["mid"], self.playlist["mid"], "kollus-one"]
        for status in ("done", "interrupted", "skip"):
            self.assertEqual(youtube_record_cleanup_patch(mids, {mids[0]: status}, self.catalog), {mids[1]: "done"})
        self.assertEqual(youtube_record_cleanup_patch([mids[1]], {mids[0]: "none"}, self.catalog), {mids[1]: "done"})
        frozen = {p: p.read_bytes() for p in (self.paths.UPD_PATH, self.paths.WATCH_PATH, self.paths.LOGS_PATH)}
        command = {"date": DATE, "sid": "s1", "completeAssignedYouTube": True, "progress": {"tests": {"기존 시험": "done"}}}
        response = self.client.post("/api/progress/patch", json=command)
        self.assertEqual(response.status_code, 200, response.text)
        entry = response.json["progress"]
        self.assertEqual(entry[mids[0]], "done")
        self.assertEqual(entry[mids[1]], "done")
        self.assertNotIn("kollus-one", entry)
        self.assertEqual(entry["tests"], {"기존 시험": "done"})
        self.assertEqual(entry["unknown"], {"keep": True})
        self.assertNotIn("__videoWatchCycles", entry)
        self.assertEqual(self.client.post("/api/progress/patch", json=command).json["progress"], entry)
        self.assertTrue(all(p.read_bytes() == data for p, data in frozen.items()))
        stored = json.loads(self.paths.PRG_PATH.read_text("utf-8"))
        self.assertEqual(stored["2026-09-12"], {"s2": {"other": "done"}})

    def test_cleanup_stale_absent_and_failure_fail_closed(self):
        command = {"date": DATE, "sid": "s1", "completeAssignedYouTube": True, "progress": {}}
        before = self.paths.PRG_PATH.read_bytes()
        for entry in ({"done": False}, {"done": True, "archived": True}, None):
            write(self.paths.LOGS_PATH, {DATE: {"s1": entry}})
            self.assertEqual(self.client.post("/api/progress/patch", json=command).status_code, 409)
            self.assertEqual(self.paths.PRG_PATH.read_bytes(), before)
        write(self.paths.LOGS_PATH, {DATE: {"s1": {"done": True}}})
        write(self.paths.ABS_PATH, {"by_date": {DATE: ["s1"]}})
        self.assertEqual(self.client.post("/api/progress/patch", json=command).status_code, 409)
        write(self.paths.ABS_PATH, {})
        with patch.object(self.progress_api, "_save_progress_strict", side_effect=OSError("injected write failure")):
            self.assertEqual(self.client.post("/api/progress/patch", json=command).status_code, 500)
        self.assertEqual(self.paths.PRG_PATH.read_bytes(), before)
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda _: self.app.test_client().post("/api/progress/patch", json=command).status_code, range(2)))
        self.assertEqual(codes, [200, 200])

    def test_cleanup_numeric_sid_preserves_authoritative_manual_state(self):
        write(self.paths.LOGS_PATH, {DATE: {"007": {"done": True}}})
        write(self.paths.UPD_PATH, {DATE: {"7": {"videos": [self.video["mid"], self.playlist["mid"]], "source": "manual"}}})
        write(self.paths.PRG_PATH, {DATE: {"7": {self.video["mid"]: "interrupted"}}})
        command = {"date": DATE, "sid": "007", "completeAssignedYouTube": True, "progress": {}}
        response = self.client.post("/api/progress/patch", json=command)
        self.assertEqual(response.status_code, 200, response.text)
        stored = json.loads(self.paths.PRG_PATH.read_text("utf-8"))
        self.assertEqual(set(stored[DATE]), {"7"})
        self.assertEqual(stored[DATE]["7"][self.video["mid"]], "interrupted")
        self.assertEqual(stored[DATE]["7"][self.playlist["mid"]], "done")


if __name__ == "__main__":
    unittest.main(verbosity=2)
