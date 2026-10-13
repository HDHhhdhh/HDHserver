"""Watch corruption and narrow-write oracle using pre-import OS-temp fixtures."""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True
import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import tempfile
import time
from types import ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DATE, SID, MID = "2026-10-01", "007", "mid-1"
MS = 1_790_804_400_000
SECRET = "watch-storage-fixture-secret"
UNAVAILABLE = {"ok": False, "error": "watch_store_unavailable"}


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def fingerprint(path):
    try:
        value = path.read_bytes()
    except FileNotFoundError:
        return None
    return path.stat().st_mtime_ns, len(value), hashlib.sha256(value).hexdigest(), value


def main(source_root=ROOT, *, guarded=True):
    source_root = Path(source_root).resolve()
    sys.path.insert(0, str(source_root))
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="watch-storage-safety-") as raw:
        base = Path(raw).resolve()
        os.environ["DATA_MIRROR_DIR"] = str(base / "mirror")
        os.environ["DATA_MIRROR_SNAPSHOTS"] = "0"
        paths = ModuleType("core.paths")
        for name, filename in {
            "WATCH_PATH": "watch.json", "PRG_PATH": "progress.json",
            "STU_PATH": "students.json", "VID_PATH": "videos.json",
        }.items():
            setattr(paths, name, base / filename)
        notifications = []
        notification_module = ModuleType("core.progress_notifications")
        notification_module.progress_notification_snapshot = lambda *a, **k: notifications.append("snapshot")
        notification_module.commit_progress_notifications = lambda *a, **k: notifications.append("commit") or 0
        sys.modules["core.paths"] = paths
        sys.modules["core.progress_notifications"] = notification_module
        operations = []

        def inside(path):
            resolved = Path(os.fsdecode(path)).resolve()
            assert resolved == base or base in resolved.parents, f"mutation outside fixture: {resolved}"
            return resolved

        def audit(event, arguments):
            if event == "open":
                path, mode, flags = arguments
                if not isinstance(path, (str, bytes, os.PathLike)):
                    return
                resolved = Path(os.fsdecode(path)).resolve()
                writing = (
                    isinstance(mode, str) and any(value in mode for value in ("w", "a", "x", "+"))
                ) or (flags and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                if writing:
                    inside(path)
                    operations.append(str(resolved.relative_to(base)))
                if source_root in resolved.parents and (
                    resolved.suffix in (".json", ".sqlite", ".db")
                    or any(value in resolved.parts for value in (
                        "data", "files", "instance", "_data_mirror", "_runtime_backups",
                    ))
                ):
                    raise AssertionError(f"production runtime access: {resolved}")
            elif event in ("os.remove", "os.rmdir", "os.mkdir"):
                inside(arguments[0])
            elif event == "os.rename":
                inside(arguments[0])
                inside(arguments[1])
            elif event in ("socket.connect", "socket.bind"):
                raise AssertionError("network access forbidden")
            elif event == "import" and arguments[0] in ("app", "core.paths"):
                raise AssertionError("live app or path initializer execution forbidden")

        sys.addaudithook(audit)
        from flask import Flask, g, request
        from core import watch_progress_writer as writer
        from core.progress_store import reset_progress_cache
        from routes import api_watch as watch, api_kollus as kollus

        for module, filename in (
            (writer, "core/watch_progress_writer.py"),
            (watch, "routes/api_watch.py"), (kollus, "routes/api_kollus.py"),
        ):
            assert Path(module.__file__).resolve() == source_root / filename, module.__file__
        assert sys.modules["core.paths"] is paths and "app" not in sys.modules
        watch.academy_network_allowed = lambda: request.headers.get("X-Academy") == "1"
        watch.ip_allowed = lambda address: address == "academy-ip"
        kollus._callback_secret = lambda: SECRET
        paths.STU_PATH.write_bytes(encode([{"id": SID}]))
        paths.VID_PATH.write_bytes(encode([{"mid": MID}]))
        updates, absent = base / "updates.json", base / "absent.json"
        updates.write_bytes(encode({"sentinel": {"sid-z": {"videos": ["keep"]}}}))
        absent.write_bytes(encode({"by_date": {}}))
        stores = (paths.WATCH_PATH, paths.PRG_PATH, paths.STU_PATH, paths.VID_PATH, updates, absent)
        app = Flask("watch-storage-safety")
        app.config["PROPAGATE_EXCEPTIONS"] = False
        app.logger.disabled = True

        @app.before_request
        def public_session():
            if request.headers.get("X-Public") == "1":
                g.student_app_public_request = True
                g.student_app_client_ip = request.headers.get("X-Client-IP")
                g.student_app_active_sid = request.headers.get("X-Active-SID")

        app.register_blueprint(watch.bp_api_watch)
        app.register_blueprint(kollus.bp_api_kollus)
        client = app.test_client()
        academy = {"X-Academy": "1"}
        incoming = {"last": 90, "dur": 100, "completed": False, "updatedAt": MS}
        body = {"date": DATE, "sid": SID, "mid": MID, **incoming}
        progress_seed = {
            "2026-09-30": {"sid-z": {"other": "skip", "legacy": {"note": "보존"}}},
            DATE: {SID: {"untouched": "skip", "__manualProgressMids": {"untouched": True}}},
        }
        start = int(dt.datetime(2026, 10, 1, 12, tzinfo=dt.timezone(dt.timedelta(hours=9))).timestamp())
        callback = {
            "sid": SID, "media_content_key": MID, "start_at": start,
            "last_play_at": 90, "duration": 100, "playtime_percent": 90,
        }
        good_watch = {"2026-09-30": {"sid-z": {"keep": {
            "last": 80, "dur": 100, "completed": False, "updatedAt": MS,
        }}}}
        cases = {
            "missing": None, "malformed": b'{"sentinel":',
            "root_array": b'[{"historical":"keep"}]', "root_string": b'"valuable legacy"',
            "root_null": b"null", "root_number": b"7", "bad_utf8": b"\xff\xfe" + encode(good_watch),
            "permission_error": encode(good_watch), "os_error": encode(good_watch),
        }
        for kind, value in (("array", ["valuable"]), ("string", "valuable"), ("null", None)):
            cases["date_" + kind] = encode({DATE: value, "untouched": good_watch})
            cases["sid_" + kind] = encode({DATE: {SID: value, "sid-z": {"keep": {"last": 1}}}, "untouched": good_watch})
            cases["mid_" + kind] = encode({DATE: {SID: {MID: value, "legacy": {"keep": True}}}, "untouched": good_watch})

        def reset(watch_bytes=b"{}", progress=None):
            if paths.WATCH_PATH.exists():
                paths.WATCH_PATH.unlink()
            if watch_bytes is not None:
                paths.WATCH_PATH.write_bytes(watch_bytes)
            paths.PRG_PATH.write_bytes(encode(progress_seed if progress is None else progress))
            reset_progress_cache()
            notifications.clear()
            operations.clear()

        original_read = Path.read_bytes
        error_type = PermissionError

        def read_error(path, *args, **kwargs):
            if path.resolve() == paths.WATCH_PATH:
                raise error_type("deterministic watch read failure")
            return original_read(path, *args, **kwargs)

        def call(entrypoint):
            if entrypoint in ("writer", "get_entry"):
                try:
                    value = (
                        writer.save_watch_entry(paths.WATCH_PATH, DATE, SID, MID, incoming, now_ms=MS)
                        if entrypoint == "writer" else writer.get_watch_entry(paths.WATCH_PATH, DATE, SID, MID)
                    )
                    return "success", value
                except Exception as exc:
                    return type(exc).__name__, None
            if entrypoint == "watch":
                response = client.post("/api/watch", json=body, headers=academy)
            elif entrypoint == "callback":
                response = client.post("/api/kollus/lms-callback", json=callback, headers={"X-Kollus-Secret": SECRET})
            elif entrypoint == "status":
                response = client.post("/api/watch-status", json={"date": DATE, "sid": SID, "mid": MID, "status": "interrupted"}, headers=academy)
            elif entrypoint == "latest":
                response = client.get(f"/api/watch/latest?sid={SID}&date={DATE}")
            else:
                response = client.get("/api/watch")
            return response.status_code, response.get_json(silent=True)

        observed = {}
        for entrypoint in ("writer", "get_entry", "watch", "callback", "status", "latest", "get_watch"):
            for name, watch_bytes in cases.items():
                reset(watch_bytes)
                before = {path: fingerprint(path) for path in stores}
                error_type = PermissionError if name == "permission_error" else OSError
                failure = patch.object(Path, "read_bytes", read_error) if name in ("permission_error", "os_error") else contextlib.nullcontext()
                with failure:
                    outcome, payload = call(entrypoint)
                changed = [path.name for path, old in before.items() if fingerprint(path) != old]
                row = {"entrypoint": entrypoint, "case": name, "outcome": outcome, "changed": changed, "notifications": list(notifications)}
                observed[entrypoint, name] = row
                nested = name.startswith(("date_", "sid_", "mid_"))
                should_block = name != "missing" and not (nested and entrypoint in ("latest", "get_watch"))
                if guarded and should_block:
                    expected = outcome == "WatchStoreReadError" if entrypoint in ("writer", "get_entry") else outcome == 503 and payload == UNAVAILABLE
                    assert expected and not changed and not notifications, row
                    assert not list(base.glob("*.lock")) and not list(base.glob("*.tmp")), row
                if name == "missing":
                    expected = "success" if entrypoint in ("writer", "get_entry") else 200
                    assert outcome == expected, row
                    if entrypoint in ("get_entry", "latest", "get_watch"):
                        assert not changed and not notifications, row
                    if entrypoint == "writer":
                        assert payload == {"last": 90, "dur": 100, "completed": True, "updatedAt": MS}
        if not guarded:
            for entrypoint in ("watch", "callback"):
                for name in ("root_array", "bad_utf8", "permission_error", "os_error", "date_array", "sid_array", "mid_array"):
                    row = observed[entrypoint, name]
                    assert row["outcome"] == 200 and row["changed"] == ["watch.json", "progress.json"] and row["notifications"], row
            row = observed["status", "malformed"]
            assert row["outcome"] == 200 and row["changed"] == ["progress.json"] and row["notifications"], row
        print(f"[PASS] {len(observed)} storage cases; {'503/no-write/no-notification' if guarded else 'vulnerable overwrite negative control observed'}")

        original = {
            "__meta": {"note": "한글 metadata", "unknown": [1, 2]},
            "2026-09-29": {"legacy-sid": ["leave unrelated malformed branch alone"]},
            DATE: {"7": {MID: {"last": 20, "dur": 100, "completed": False, "updatedAt": MS + 9, "futureField": {"keep": ["yes"]}},
                         "other-mid": "untouched legacy string", "__sidMeta": {"keep": True}},
                   "sid-z": {"old-mid": {"last": 5, "dur": 100, "completed": False, "updatedAt": MS, "unknown": "keep"}}},
        }
        reset(b"\xef\xbb\xbf" + encode(original))
        actual = writer.save_watch_entry(paths.WATCH_PATH, DATE, SID, MID, {"last": 10, "dur": 50, "completed": False, "updatedAt": MS}, now_ms=MS)
        stored = json.loads(paths.WATCH_PATH.read_text("utf-8-sig"))
        known = {"last": 20, "dur": 100, "completed": False, "updatedAt": MS + 9}
        expected = json.loads(encode(original))
        expected[DATE]["7"][MID] = {"futureField": {"keep": ["yes"]}, **known} if guarded else known
        assert stored == expected and actual == known and SID not in stored[DATE]
        print("[PASS] BOM, numeric SID alias, narrow sibling preservation and target unknown-field oracle")

        def no_write(label, run, status, expected_payload=None):
            reset(cases["bad_utf8"])
            before = {path: fingerprint(path) for path in stores}
            response = run()
            assert response.status_code == status, (label, response.status_code, response.get_json(silent=True))
            if expected_payload is not None:
                assert response.get_json() == expected_payload, label
            assert all(fingerprint(path) == old for path, old in before.items()), label
            assert not operations and not notifications, (label, operations, notifications)

        for invalid in ("2026-02-30", "20261001", "2026-10-01T00:00:00"):
            no_write("invalid watch date", lambda value=invalid: client.post("/api/watch", json={**body, "date": value}, headers=academy), 400, {"ok": False, "error": "bad date"})
            no_write("invalid status date", lambda value=invalid: client.post("/api/watch-status", json={"date": value, "sid": SID, "mid": MID, "status": "done"}, headers=academy), 400, {"ok": False, "error": "bad date"})
        no_write("outside academy", lambda: client.post("/api/watch", json=body), 403)
        no_write("public SID mismatch", lambda: client.post("/api/watch", json={**body, "sid": "sid-z"}, headers={"X-Public": "1", "X-Client-IP": "academy-ip", "X-Active-SID": SID}), 403)
        no_write("public raw GET", lambda: client.get("/api/watch", headers={"X-Public": "1"}), 404)
        no_write("callback missing secret", lambda: client.post("/api/kollus/lms-callback", json=callback), 403)
        no_write("zero-progress callback", lambda: client.post("/api/kollus/lms-callback", json={**callback, "last_play_at": 0, "playtime_percent": 0}, headers={"X-Kollus-Secret": SECRET}), 200, {"ok": True, "ignored": True})
        print("[PASS] date validation, academy/public SID restrictions and callback early-return contracts")

        for manual in ("none", "skip", "interrupted"):
            state = {DATE: {SID: {MID: manual, "__manualProgressMids": {MID: True}, "unknown": {"keep": True}}}}
            reset(progress=state)
            before_updates = fingerprint(updates)
            response = client.post("/api/watch", json=body, headers=academy)
            assert response.status_code == 200 and response.get_json()["progress"][MID] == manual
            assert response.get_json()["progress"]["unknown"] == {"keep": True}
            assert fingerprint(updates) == before_updates
        for last, status in ((4, ""), (5, "interrupted"), (89, "interrupted"), (90, "done")):
            reset(progress={})
            response = client.post("/api/watch", json={**body, "last": last}, headers=academy)
            assert response.status_code == 200 and response.get_json()["progress"].get(MID, "") == status
        reset(progress={})
        wrapped = writer.save_watch_entry(paths.WATCH_PATH, DATE, SID, "wrapped", {"last": 1, "dur": 100, "updatedAt": 667_934_656}, now_ms=MS)
        valid = writer.save_watch_entry(paths.WATCH_PATH, DATE, SID, "valid", {"last": 1, "dur": 100, "updatedAt": MS - 1234}, now_ms=MS)
        assert wrapped["updatedAt"] == MS and valid["updatedAt"] == MS - 1234
        writer.save_watch_entry(paths.WATCH_PATH, DATE, SID, MID, incoming, now_ms=MS)
        stale = writer.save_watch_entry(paths.WATCH_PATH, DATE, SID, MID, {"last": 5, "dur": 50, "completed": False, "updatedAt": MS - 1}, now_ms=MS)
        assert stale == {"last": 90, "dur": 100, "completed": True, "updatedAt": MS}
        promoted = client.post("/api/watch-status", json={"date": DATE, "sid": SID, "mid": MID, "status": "interrupted"}, headers=academy)
        assert promoted.status_code == 200 and promoted.get_json()["progress"][MID] == "done"
        print("[PASS] manual white/skip/interrupted ownership, 5/90 thresholds, millisecond repair/preservation and sticky completion")

        issued = str(int(time.time()))
        encoded_sid = base64.urlsafe_b64encode(SID.encode()).decode().rstrip("=")
        signature = hmac.new(SECRET.encode(), f"{SID}\n{MID}\n{issued}".encode(), hashlib.sha256).hexdigest()
        token = f"v1.{encoded_sid}.{issued}.{signature}"
        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
        no_write("tampered signed callback", lambda: client.post("/api/kollus/lms-callback", json={**callback, "uservalue0": tampered}), 403)
        with patch.object(kollus, "_callback_secret", lambda: ""):
            no_write("unconfigured callback secret", lambda: client.post("/api/kollus/lms-callback", json={**callback, "uservalue0": token}), 403)
        reset(progress={})
        protected_updates = fingerprint(updates)
        signed = client.post("/api/kollus/lms-callback", json={**callback, "uservalue0": token})
        assert signed.status_code == 200 and signed.get_json()["sid"] == SID and signed.get_json()["date"] == DATE
        assert signed.get_json()["watch"]["completed"] is True and signed.get_json()["progress"][MID] == "done"
        assert fingerprint(updates) == protected_updates
        assert sys.modules["core.paths"] is paths and "app" not in sys.modules
        print("[PASS] independent signed-token input, tamper/unset-secret rejection, KST callback projection and assignment invariance")
    print("watch storage safety checks passed; all runtime I/O stayed in OS temporary fixtures")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--expect", choices=("guarded", "vulnerable"), default="guarded")
    args = parser.parse_args()
    raise SystemExit(main(args.source_root, guarded=args.expect == "guarded"))
