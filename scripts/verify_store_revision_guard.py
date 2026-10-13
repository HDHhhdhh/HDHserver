"""Registered actual route tests with guarded OS-temp persistence; no app import.
Every runtime operation is guarded to an OS TemporaryDirectory.
"""
from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import unittest
from urllib.parse import parse_qs, urlparse, urlencode, urlsplit

from flask import Blueprint, Flask, current_app, jsonify, make_response, request

TODAY = "2026-10-13"
NEXT_DAY = "2026-10-14"
ARGS = None
STORAGE = None
VIDEO_SOURCES = None


def revision(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def fingerprint(path):
    value = path.read_bytes()
    return path.stat().st_mtime_ns, len(value), hashlib.sha256(value).hexdigest(), value


def source_ast(path, injected):
    import importlib.util
    spec = importlib.util.spec_from_file_location("fixture_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.__dict__.update(injected)
    return module.__dict__


def real_date(value):
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        return False
    try:
        return dt.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


@contextmanager
def fixture(kind, rows=None):
    with __import__("tempfile").TemporaryDirectory(prefix="p3-child-fixture-") as temporary:
        root = Path(temporary).resolve()
        path = root / ("videos.json" if kind == "video" else "extra_attend.json")
        roster = root / "students.json"
        weekend = root / "weekend_slots.json"
        path.write_text(json.dumps(catalog() if kind == "video" and rows is None else rows, ensure_ascii=False), "utf-8")
        roster.write_text('[{"id":"a"},{"id":"b"},{"id":"base"}]', "utf-8")
        weekend.write_text('{}', "utf-8")
        events = []
        observation = {}
        saves = []

        def guard(target):
            actual = Path(target).resolve()
            if not actual.is_relative_to(root):
                raise AssertionError("non-temporary runtime path: " + str(actual))
            return actual

        def load(target):
            return STORAGE["load"](guard(target))

        def save(target, value, **kwargs):
            actual = guard(target)
            saves.append(actual.name)
            return STORAGE["save_atomic"](actual, value, **kwargs)

        @contextmanager
        def locked(target, **kwargs):
            actual = guard(target)
            if observation.get("lock_requested") is not None:
                observation["lock_requested"].set()
            with STORAGE["file_lock"](actual, **kwargs):
                yield

        injected = {"Blueprint": Blueprint, "current_app": current_app, "jsonify": jsonify, "make_response": make_response, "request": request, "hashlib": hashlib, "json": json, "os": os, "re": re, "dt": dt, "urlparse": urlparse, "parse_qs": parse_qs, "VID_PATH": path, "EXTRA_PATH": path, "STU_PATH": roster, "WEEKEND_SLOTS_PATH": weekend, "load": load, "save_atomic": save, "file_lock": locked, "is_iso_date_key": real_date, "is_ghost_student_sid": lambda sid: str(sid).startswith("ghost-"), "GHOST_STUDENT_WRITE_ERROR": "ghost_student_write_blocked", "enqueue_current_schedule_changes": lambda sids: events.append(("notify", sorted(sids))), "is_youtube_mid": VIDEO_SOURCES["is_youtube_mid"], "parse_youtube_url": VIDEO_SOURCES["parse_youtube_url"]}
        namespace = source_ast(ARGS.draft_root / "routes" / ("api_videos.py" if kind == "video" else "api_schedule_overrides.py"), injected)
        app = Flask("p3-draft-" + kind)
        app.logger.disabled = True
        if kind == "extra":
            namespace["_today_kst_iso"] = lambda: TODAY
            namespace["configure_schedule_override_assignment_hooks"](app, initialize_today=lambda **kwargs: events.append(("initialize", deepcopy(kwargs))), reconcile=lambda *args, **kwargs: events.append(("reconcile", deepcopy(kwargs))))
        app.register_blueprint(namespace["bp_api_videos"] if kind == "video" else namespace["bp_api_schedule_overrides"])
        old_env = {key: os.environ.get(key) for key in ("DATA_MIRROR_DIR", "DATA_MIRROR_SNAPSHOTS", "JSON_STORE_REVISION_MODE")}
        os.environ["DATA_MIRROR_DIR"] = str(root / "mirror")
        os.environ["DATA_MIRROR_SNAPSHOTS"] = "0"
        os.environ["JSON_STORE_REVISION_MODE"] = "soft"
        try:
            yield path, roster, weekend, app, namespace, events, observation, saves
        finally:
            for key, old in old_env.items():
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old


def catalog():
    return [{"id": 1, "mid": "mid-a", "title": "합성 영상", "url": "https://v.kr.kollus.com/player?mid=mid-a&token=old", "unknown": {"keep": [7, "한글"]}}]


class RevisionAndDeltaTests(unittest.TestCase):
    def test_video_corrupt_store_blocks_get_and_post_without_mutation(self):
        for raw in (b'{', b'{}', b'[null]', b'[{"id":1},{"id":1}]', b'\xff'):
            with fixture("video") as (path, _roster, _weekend, app, _ns, _events, _obs, saves):
                path.write_bytes(raw)
                before = fingerprint(path)
                client = app.test_client()
                self.assertEqual(client.get("/api/videos").status_code, 503)
                self.assertEqual(client.post("/api/videos", json=catalog()).status_code, 503)
                self.assertEqual(fingerprint(path), before)
                self.assertEqual(saves, [])

    def test_video_soft_204_and_matching_revision_preserve_unknown_fields(self):
        with fixture("video") as (path, _roster, _weekend, app, _ns, _events, _obs, _saves):
            client = app.test_client()
            get = client.get("/api/videos")
            self.assertEqual(get.get_json(), catalog())
            self.assertEqual(get.headers["X-Store-Revision"], revision(catalog()))
            self.assertEqual(get.headers["X-Video-Providers"], "kollus,youtube")
            edited = catalog()
            edited[0]["title"] = "soft edit"
            soft = client.post("/api/videos", json=edited)
            self.assertEqual((soft.status_code, soft.data), (204, b""))
            self.assertEqual(soft.headers["X-Store-Revision"], revision(edited))
            edited[0]["url"] = "https://v.kr.kollus.com/player?mid=mid-a&token=new"
            matched = client.post("/api/videos", json=edited, headers={"If-Match": '"' + soft.headers["X-Store-Revision"] + '"'})
            self.assertEqual((matched.status_code, matched.data), (204, b""))
            self.assertEqual(json.loads(path.read_text("utf-8")), edited)
            self.assertEqual(matched.headers["X-Store-Revision"], revision(edited))

    def test_video_missing_malformed_stale_and_mid_guards_do_not_write(self):
        with fixture("video") as (path, _roster, _weekend, app, _ns, _events, _obs, _saves):
            os.environ["JSON_STORE_REVISION_MODE"] = "strict"
            client = app.test_client()
            before = fingerprint(path)
            edited = catalog()
            edited[0]["title"] = "must not save"
            for header in ({}, {"If-Match": "*"}, {"If-Match": "W/\"" + revision(catalog()) + "\""}, {"If-Match": "junk"}):
                response = client.post("/api/videos", json=edited, headers=header)
                self.assertEqual(response.status_code, 428)
                self.assertEqual(fingerprint(path), before)
            stale = client.post("/api/videos", json=edited, headers={"If-Match": "a" * 64})
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(stale.get_json()["error"], "video_catalog_revision_conflict")
            self.assertEqual(fingerprint(path), before)
            changed_mid = catalog()
            changed_mid[0]["url"] = "https://v.kr.kollus.com/player?mid=other"
            protected = client.post("/api/videos", json=changed_mid)
            self.assertEqual(protected.status_code, 409)
            self.assertEqual(protected.get_json()["error"], "video_catalog_identity_change_blocked")
            removed = client.post("/api/videos", json=[])
            self.assertEqual(removed.status_code, 409)
            self.assertEqual(removed.get_json()["removedIds"], ["1"])
            self.assertEqual(fingerprint(path), before)

    def test_video_compares_revision_after_real_vid_lock_wait(self):
        with fixture("video") as (path, _roster, _weekend, app, _ns, _events, observation, _saves):
            original = revision(catalog())
            requested = threading.Event()
            finished = threading.Event()
            observation["lock_requested"] = requested
            response_box = []
            incoming = catalog()
            incoming[0]["title"] = "stale writer"

            def worker():
                response_box.append(app.test_client().post("/api/videos", json=incoming, headers={"If-Match": original}))
                finished.set()

            with ThreadPoolExecutor(max_workers=1) as executor:
                with STORAGE["file_lock"](path):
                    future = executor.submit(worker)
                    self.assertTrue(requested.wait(2))
                    self.assertFalse(finished.wait(0.05))
                    current = catalog()
                    current[0]["title"] = "external writer under same lease"
                    STORAGE["save_atomic"](path, current)
                    before_reject = fingerprint(path)
                future.result(timeout=4)
            self.assertEqual(response_box[0].status_code, 409)
            self.assertEqual(fingerprint(path), before_reject)

    def test_legacy_extra_replacement_body_and_response_are_unchanged(self):
        initial = {NEXT_DAY: ["base"], "unknown": {"keep": 7}, "2026-11-01": ["retired"]}
        with fixture("extra", initial) as (path, _roster, _weekend, app, _ns, events, _obs, _saves):
            get = app.test_client().get("/api/extra-attend")
            self.assertEqual(get.get_json(), initial)
            self.assertEqual(get.headers["X-Extra-Attend-Patch-Modes"], "replace,delta")
            response = app.test_client().patch("/api/extra-attend", json={"dates": {NEXT_DAY: ["a", "a", 2, ""]}})
            self.assertEqual(response.get_json(), {"ok": True, "dates": {NEXT_DAY: ["a", "2"]}, "changedDates": [NEXT_DAY]})
            self.assertEqual(json.loads(path.read_text("utf-8")), {NEXT_DAY: ["a", "2"], "unknown": {"keep": 7}, "2026-11-01": ["retired"]})
            self.assertFalse(any(event[0] == "initialize" for event in events))

    def test_extra_delta_late_concurrent_sids_and_legacy_values_survive(self):
        initial = {NEXT_DAY: ["base", 2], "unknown": {"keep": 7}, "2026-11-01": ["retired"]}
        with fixture("extra", initial) as (path, _roster, _weekend, app, _ns, _events, _obs, _saves):
            baseline_a = app.test_client().get("/api/extra-attend").get_json()
            baseline_b = deepcopy(baseline_a)
            self.assertEqual(baseline_a, baseline_b)
            barrier = threading.Barrier(2)
            def worker(sid):
                barrier.wait(timeout=3)
                return app.test_client().patch("/api/extra-attend", json={"deltas": {NEXT_DAY: {sid: True}}})
            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(worker, ("a", "b")))
            self.assertEqual([response.status_code for response in responses], [200, 200])
            stored = json.loads(path.read_text("utf-8"))
            self.assertEqual(stored[NEXT_DAY][:2], ["base", 2])
            self.assertEqual(set(stored[NEXT_DAY][2:]), {"a", "b"})
            self.assertEqual(stored["unknown"], {"keep": 7})
            response = app.test_client().patch("/api/extra-attend", json={"deltas": {NEXT_DAY: {"base": False}}})
            self.assertEqual(set(response.get_json()["dates"][NEXT_DAY]), {2, "a", "b"})
            self.assertEqual(json.loads(path.read_text("utf-8"))["2026-11-01"], ["retired"])

    def test_extra_bad_delta_never_locks_writes_or_notifies(self):
        with fixture("extra", {NEXT_DAY: ["base"]}) as (path, roster, weekend, app, _ns, events, observation, saves):
            before = tuple(fingerprint(item) for item in (path, roster, weekend))
            lock_called = threading.Event()
            observation["lock_requested"] = lock_called
            invalid = ({"deltas": {}}, {"deltas": {"2026-02-30": {"a": True}}}, {"deltas": {NEXT_DAY: []}}, {"deltas": {NEXT_DAY: {"a": "true"}}}, {"deltas": {NEXT_DAY: {"a": 0}}}, {"deltas": {NEXT_DAY: {"a": None}}}, {"deltas": {NEXT_DAY: {"": True}}}, {"deltas": {NEXT_DAY: {"a": True}}, "date": NEXT_DAY, "sids": []})
            for body in invalid:
                self.assertEqual(app.test_client().patch("/api/extra-attend", json=body).status_code, 400)
            self.assertEqual(app.test_client().patch("/api/extra-attend", json={"deltas": {NEXT_DAY: {"ghost-qa": False}}}).status_code, 403)
            self.assertEqual(tuple(fingerprint(item) for item in (path, roster, weekend)), before)
            self.assertFalse(lock_called.is_set())
            self.assertEqual((saves, events), ([], []))

    def test_extra_corrupt_addressed_day_has_no_commit_or_hook(self):
        for value in ([], None, {NEXT_DAY: {"unknown": "keep"}}):
            with fixture("extra", value) as (path, _roster, _weekend, app, _ns, events, _obs, saves):
                before = fingerprint(path)
                response = app.test_client().patch("/api/extra-attend", json={"deltas": {NEXT_DAY: {"a": True}}})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(fingerprint(path), before)
                self.assertEqual((saves, events), ([], []))

    def test_today_empty_delta_replays_initializer_without_primary_write(self):
        with fixture("extra", {TODAY: ["base"]}) as (path, _roster, _weekend, app, _ns, events, _obs, saves):
            before = fingerprint(path)
            for _ in range(2):
                response = app.test_client().patch("/api/extra-attend", json={"deltas": {TODAY: {}}})
                self.assertEqual(response.get_json(), {"ok": True, "dates": {TODAY: ["base"]}, "changedDates": []})
            self.assertEqual(fingerprint(path), before)
            self.assertEqual(saves, [])
            self.assertEqual(sum(event[0] == "initialize" for event in events), 2)
            self.assertEqual([event[1] for event in events if event[0] == "notify"], [[], []])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--draft-root", type=Path, default=Path(__file__).resolve().parents[1])
    ARGS, remaining = parser.parse_known_args()
    import sys
    sys.path.insert(0, str(ARGS.source_root))
    # core.storage only defines functions; it has no app/core.paths import.
    STORAGE = {"__name__": "audit_storage"}
    exec(compile((ARGS.source_root / "core/storage.py").read_text("utf-8-sig"), "core/storage.py", "exec"), STORAGE)
    STORAGE["log"].disabled = True
    VIDEO_SOURCES = source_ast(ARGS.source_root / "core/video_sources.py", {"re": re, "parse_qs": parse_qs, "urlencode": urlencode, "urlsplit": urlsplit})
    unittest.main(argv=["verify_store_revision_guard", *remaining], verbosity=2)
