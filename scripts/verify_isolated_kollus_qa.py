"""Verify the bounded native-player QA exception without live runtime access."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SID = "QAHUBNATIVE1002"
MID = "3FWqGfJP"
OTHER_SID = "qa-other"
OTHER_MID = "qa_other_001"
FLAG = "ACADEMY_ISOLATED_KOLLUS_QA"
DAY = "2026-10-02"
STAMP = "2026-10-02T01:02:03.123000+00:00"
MS = 1_790_899_200_123
CHECKS = 0
_IO_SCOPE = {"base": None}


def same(actual, expected, label):
    global CHECKS
    assert actual == expected, f"{label}: {actual!r} != {expected!r}"
    CHECKS += 1


def _under(path, base):
    return path == base or path.is_relative_to(base)


def _audit(event, args):
    base = _IO_SCOPE["base"]
    if base is None:
        return
    if event == "import" and args[0] == "app":
        raise AssertionError("live app import is forbidden")
    if event == "sqlite3.connect":
        raw = args[0]
        if raw != ":memory:":
            assert _under(Path(raw).resolve(), base), "SQLite outside OS temp"
    if event == "open":
        raw, mode, flags = args
        if isinstance(raw, int):
            return
        path = Path(raw).resolve()
        writing = any(c in (mode or "") for c in "wax+") or bool(
            flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        )
        if _under(path, base):
            return
        assert not writing, f"write outside OS temp: {path}"
        if _under(path, ROOT):
            assert path.suffix in {".py", ".pyc"}, f"live runtime read: {path}"
    elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.rename"}:
        values = args[:2] if event == "os.rename" else args[:1]
        for raw in values:
            assert _under(Path(raw).resolve(), base), f"filesystem mutation outside OS temp: {raw}"


sys.addaudithook(_audit)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(base):
    return {
        str(path.relative_to(base)): (
            path.stat().st_mtime_ns, path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in base.rglob("*") if path.is_file()
    }


def context(base):
    source = base / "source"
    root = source / "instance" / "isolated-design-server" / "app"
    return {
        "code_root": root,
        "environ": {FLAG: "1", "ACADEMY_ISOLATED_SERVER_ROOT": str(root)},
        "marker": {"format": "academy-isolated-server/v1", "isolatedRoot": str(root), "sourceRoot": str(source)},
        "receipt": {"format": "academy-isolated-design-server/v1", "port": 8004,
                    "codeRoot": str(root), "sourceRoot": str(source), "listenerProcessId": 4242,
                    "listenerStartTimeUtc": STAMP, "liveRuntimeCopied": False, "kollusVideoQaEnabled": True},
        "pid": 4242, "process_started_at": STAMP, "remote_addr": "127.0.0.1",
        "public_request": False, "origin": "http://127.0.0.1:8004", "fetch_site": "same-origin",
    }


def pure_context_oracle(helper, base):
    original = context(base)
    same(helper.validate_qa_context(**original), True, "fully bounded context")
    for origin, site in [("", ""), ("http://127.0.0.1:8004", "none")]:
        fixture = deepcopy(original)
        fixture.update(origin=origin, fetch_site=site)
        same(helper.validate_qa_context(**fixture), True, "optional same-origin headers")
    negatives = [
        ("environ", FLAG, None), ("environ", FLAG, "0"), ("environ", FLAG, "true"),
        ("environ", "ACADEMY_ISOLATED_SERVER_ROOT", str(base / "wrong")),
        ("marker", "format", "wrong"), ("marker", "isolatedRoot", str(base)),
        ("marker", "sourceRoot", str(base / "different-source")),
        ("receipt", "format", "wrong"), ("receipt", "port", 8003),
        ("receipt", "port", "8004"), ("receipt", "port", True),
        ("receipt", "liveRuntimeCopied", True), ("receipt", "liveRuntimeCopied", None),
        ("receipt", "kollusVideoQaEnabled", False), ("receipt", "kollusVideoQaEnabled", "true"),
        ("receipt", "codeRoot", str(base / "wrong")), ("receipt", "sourceRoot", str(base)),
        ("receipt", "listenerProcessId", 4243), ("receipt", "listenerProcessId", "4242"),
        ("receipt", "listenerStartTimeUtc", "2026-10-02T01:02:03.125000+00:00"),
        ("receipt", "listenerStartTimeUtc", "2026-10-02T01:02:03.123000"),
        ("receipt", "listenerStartTimeUtc", "invalid"),
    ]
    for owner, key, value in negatives:
        fixture = deepcopy(original)
        fixture[owner][key] = value
        same(helper.validate_qa_context(**fixture), False, f"closed {owner}.{key}={value!r}")
    for key, value in [
        ("code_root", base / "other-copy"), ("code_root", ROOT),
        ("receipt", None), ("marker", []), ("pid", 4243),
        ("process_started_at", "invalid"), ("process_started_at", "2026-10-02T01:02:03.123000"),
        ("remote_addr", "192.168.0.5"), ("remote_addr", "203.0.113.2"),
        ("remote_addr", "invalid"), ("public_request", True),
        ("origin", "http://localhost:8004"), ("origin", "http://127.0.0.1:8003"),
        ("origin", "https://example.test"), ("fetch_site", "cross-site"),
        ("fetch_site", "same-site"),
    ]:
        fixture = deepcopy(original)
        fixture[key] = value
        same(helper.validate_qa_context(**fixture), False, f"closed context {key}")
    fixture = deepcopy(original)
    fixture["receipt"]["listenerStartTimeUtc"] = "2026-10-02T01:02:03.123999+00:00"
    same(helper.validate_qa_context(**fixture), True, "sub-millisecond Windows timestamp rounding")
    same(original, context(base), "context input immutable")


@contextmanager
def fixture_modules(base):
    from flask import Flask

    fixture = context(base)
    root = fixture["code_root"]
    (root / "core").mkdir(parents=True)
    environment = {
        FLAG: "1", "ACADEMY_ISOLATED_SERVER_ROOT": str(root),
        "DATA_DIR": str(root / "data"), "DATA_MIRROR_DIR": str(root / "mirror"),
        "DB_PATH": str(root / "app.sqlite"), "STUDENT_APP_DB_PATH": str(root / "app.sqlite"),
        "KOLLUS_CALLBACK_SECRET": "", "STUDENT_APP_PUBLIC_ENABLED": "0", "TRUST_PROXY_HEADERS": "0",
    }
    paths = types.ModuleType("core.paths")
    paths.__file__ = str(root / "core" / "paths.py")
    helper = types.ModuleType("core.isolated_kollus_qa")
    helper.__file__ = str(root / "core" / "isolated_kollus_qa.py")
    hooks = types.ModuleType("core.student_notification_hooks")
    hooks.runtime_repository = lambda: None
    hooks.enqueue_progress_milestones = lambda *a, **kw: 0
    with patch.dict(os.environ, environment):
        exec(compile((ROOT / "core/paths.py").read_text("utf-8"), paths.__file__, "exec"), paths.__dict__)
        same(all(_under(p.resolve(), base) for p in vars(paths).values() if isinstance(p, Path)), True, "all declared runtime paths are temp")
        exec(compile((ROOT / "core/isolated_kollus_qa.py").read_text("utf-8"), helper.__file__, "exec"), helper.__dict__)
        same((helper.QA_SID, helper.QA_MID, helper.ENV), (SID, MID, FLAG), "fixed approved QA identity")
        fixture["receipt"]["listenerProcessId"] = os.getpid()
        write_json(root / ".academy-isolated-server.json", fixture["marker"])
        write_json(root.parent / "server.json", fixture["receipt"])
        with patch.dict(sys.modules, {"core.paths": paths, "core.isolated_kollus_qa": helper, "core.student_notification_hooks": hooks}), patch.object(helper, "_process_started_at", lambda: STAMP):
            # These are actual blueprints; neither their app nor a network server is imported.
            modules = [importlib.import_module("routes." + name) for name in ("api_kollus", "api_watch", "api_student_bootstrap")]
            for module in modules:
                importlib.reload(module)
            app = Flask("isolated-kollus-qa-verifier")
            for module in modules:
                app.register_blueprint(getattr(module, "bp_" + module.__name__.split(".")[-1]))
            yield helper, paths, modules, app, fixture


def wrapper_oracle(helper, app, root):
    from flask import g, request

    with app.test_request_context("/api/get-url", base_url="http://127.0.0.1:8004", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}):
        same(helper.isolated_kollus_qa_allowed(SID, MID, request), True, "actual marker/receipt wrapper")
        for sid, mid in [(OTHER_SID, MID), (SID, OTHER_MID), ("", MID), (SID, "")]:
            before = fingerprint(root.parent)
            same(helper.isolated_kollus_qa_allowed(sid, mid, request), False, "exact pair only")
            same(fingerprint(root.parent), before, "wrong pair is read-only")
        g.student_app_public_request = True
        same(helper.isolated_kollus_qa_allowed(SID, MID, request), False, "wrapper public denied")
    for host in ["http://localhost:8004", "http://127.0.0.1:8003"]:
        with app.test_request_context("/", base_url=host):
            same(helper.isolated_kollus_qa_allowed(SID, MID, request), False, "wrapper exact host")
    with app.test_request_context("/", base_url="http://127.0.0.1:8004"), patch.dict(os.environ, {FLAG: "0"}), patch.object(Path, "read_text", side_effect=AssertionError("OFF must not read context files")), patch.object(helper, "_process_started_at", side_effect=AssertionError("OFF must not inspect process")):
        same(helper.isolated_kollus_qa_allowed(SID, MID, request), False, "default OFF fast path")


def route_oracle(helper, paths, modules, app, base):
    from flask import g

    kollus, watch, bootstrap = modules
    paths_by_name = {"students": paths.STU_PATH, "videos": paths.VID_PATH, "watch": paths.WATCH_PATH,
                     "progress": paths.PRG_PATH, "updates": paths.UPD_PATH}
    fixtures = {
        "students": [{"id": SID, "curriculum": "QA", "subCurriculum": "BASE"}, {"id": OTHER_SID}],
        "videos": [{"mid": MID, "title": "QA native", "curriculum": "QA", "subCurriculum": "BASE", "localPlaybackQaAllowed": True}, {"mid": OTHER_MID, "title": "Other", "localPlaybackQaAllowed": True}],
        "watch": {"2026-10-01": {OTHER_SID: {OTHER_MID: {"last": 4, "dur": 100, "completed": False, "updatedAt": MS, "unknown": "keep"}}}},
        "progress": {"2026-10-01": {OTHER_SID: {OTHER_MID: "none", "unknown": "keep"}}},
        "updates": {DAY: {SID: {"source": "auto", "videos": [MID], "unknown": {"keep": True}}}},
    }
    for name, value in fixtures.items():
        write_json(paths_by_name[name], value)
    policy = {"public": False}

    @app.before_request
    def public_fixture():
        g.student_app_public_request = policy["public"]
        g.student_app_active_sid = SID
        g.student_app_client_ip = "127.0.0.1"

    client = app.test_client()
    def get(url, **kw):
        return client.get(url, base_url="http://127.0.0.1:8004", **kw)
    def post(body, **kw):
        return client.post("/api/watch", json=body, base_url="http://127.0.0.1:8004", **kw)
    def payload(**changes):
        return {"date": DAY, "sid": SID, "mid": MID, "last": 5, "dur": 100, "completed": False, "updatedAt": MS, **changes}

    before = fingerprint(base)
    url = get(f"/api/get-url?sid={SID}&mid={MID}")
    same(url.status_code, 200, "QA get-url accepted")
    parsed = urlsplit(url.get_data(as_text=True))
    same((parsed.scheme, parsed.netloc, parsed.path), ("https", "v.kr.kollus.com", "/" + MID), "actual provider URL target")
    same(parse_qs(parsed.query), {}, "QA provider URL has no SID/uservalue/callback token")
    with patch.object(kollus, "isolated_kollus_qa_allowed", side_effect=[True, False]) as grant:
        raced_url = get(f"/api/get-url?sid={SID}&mid={MID}")
        same(raced_url.status_code, 200, "QA authorization remains request-local")
        same(parse_qs(urlsplit(raced_url.get_data(as_text=True)).query), {}, "receipt race cannot disclose QA SID")
        same(grant.call_count, 1, "QA grant is evaluated once per playback request")
    same(fingerprint(base), before, "get-url is storage-only")
    for sid, mid in [(OTHER_SID, MID), (SID, OTHER_MID), ("", MID)]:
        same(get(f"/api/get-url?sid={sid}&mid={mid}").status_code, 403, "get-url wrong pair")
        same(post(payload(sid=sid, mid=mid)).status_code, 403, "watch wrong pair")
        same(fingerprint(base), before, "wrong pair leaves all temp stores unchanged")
    with patch.dict(os.environ, {FLAG: "0"}):
        same(get(f"/api/get-url?sid={SID}&mid={MID}").status_code, 403, "OFF preserves academy get-url rejection")
        same(post(payload()).status_code, 403, "OFF preserves academy watch rejection")
    policy["public"] = True
    same(get(f"/api/get-url?sid={SID}&mid={MID}").status_code, 403, "public get-url cannot use QA grant")
    same(post(payload()).status_code, 403, "public watch cannot use QA grant")
    policy["public"] = False
    same(fingerprint(base), before, "OFF/public negatives are byte/mtime/SHA invariant")
    same(get("/api/kollus/lms-callback").status_code, 403, "QA callback stays disabled")
    first = post(payload())
    same(first.status_code, 200, "QA watch 5 percent")
    same(first.get_json()["progress"][MID], "interrupted", "actual writer creates automatic interrupted")
    done = post(payload(last=90, completed=True, updatedAt=MS + 100))
    same(done.status_code, 200, "QA watch completion")
    same(done.get_json()["progress"][MID], "done", "actual writer creates done")
    same(read_json(paths.WATCH_PATH)[DAY][SID][MID]["updatedAt"], MS + 100, "valid epoch milliseconds preserved")
    progress = read_json(paths.PRG_PATH)
    progress[DAY][SID] = {MID: "none", "__manualProgressMids": {MID: True}, "unknown": {"keep": True}}
    write_json(paths.PRG_PATH, progress)
    watch_data = read_json(paths.WATCH_PATH)
    watch_data[DAY][SID][MID]["unknown"] = {"keep": True}
    write_json(paths.WATCH_PATH, watch_data)
    again = post(payload(last=95, completed=True, updatedAt=MS + 200))
    same(again.status_code, 200, "observation after manual white")
    expected_manual = {MID: "none", "__manualProgressMids": {MID: True}, "unknown": {"keep": True}}
    same(read_json(paths.PRG_PATH)[DAY][SID], expected_manual, "manual white and unknown metadata survive writer")
    same(read_json(paths.WATCH_PATH)[DAY][SID][MID]["unknown"], {"keep": True}, "watch unknown fields survive")
    same(read_json(paths.WATCH_PATH)["2026-10-01"], fixtures["watch"]["2026-10-01"], "other watch SID/date preserved")
    same(read_json(paths.PRG_PATH)["2026-10-01"], fixtures["progress"]["2026-10-01"], "other progress SID/date preserved")
    same(read_json(paths.UPD_PATH), fixtures["updates"], "assignment snapshot never refilled or changed")
    stable = fingerprint(base)
    for body, options, code in [(payload(date="2026-02-30"), {}, 400), (payload(), {"headers": {"Origin": "https://example.test"}}, 403), (payload(), {"environ_overrides": {"REMOTE_ADDR": "203.0.113.5"}}, 403)]:
        same(post(body, **options).status_code, code, "invalid date/origin/peer denied")
        same(fingerprint(base), stable, "negative write is byte/mtime/SHA invariant")

    projected = {"ok": True, "date": DAY, "students": [{"id": SID}], "student": {"id": SID},
                 "videos": [{"mid": MID, "title": "QA", "playbackRestricted": True, "localPlaybackQaAllowed": True, "unknown": {"keep": True}},
                            {"mid": OTHER_MID, "title": "Other", "playbackRestricted": True, "localPlaybackQaAllowed": True, "unknown": 7}],
                 "reviewVideos": [{"mid": OTHER_MID, "title": "Review", "localPlaybackQaAllowed": True}],
                 "assignedTests": [{"id": "test-a", "title": "Title only"}], "materials": {"m": {"title": "Material"}},
                 "academyAccessAllowed": False, "outsideAcademyBlocked": True, "networkBlocked": True,
                 "unknown": {"keep": True}}
    inputs = deepcopy(projected)
    deps = types.SimpleNamespace(today_iso=lambda: DAY, load_progress=lambda: {})
    def project(_deps, **kw):
        same(kw["academy_allowed_resolver"](), False, "real academy stays false during QA bootstrap")
        return deepcopy(projected), 200
    with patch.object(bootstrap, "_projection_dependencies", lambda: deps), patch.object(bootstrap, "build_student_bootstrap_payload", project):
        body = get(f"/api/student/bootstrap?sid={SID}&date={DAY}").get_json()
        expected = deepcopy(projected)
        expected["videos"][0]["localPlaybackQaAllowed"] = True
        expected["videos"][0]["playbackRestricted"] = False
        expected["videos"][1].pop("localPlaybackQaAllowed")
        expected["reviewVideos"][0].pop("localPlaybackQaAllowed")
        same(body, expected, "only exact assigned QA video receives reserved grant; other payload unchanged")
        with patch.dict(os.environ, {FLAG: "0"}):
            body = get(f"/api/student/bootstrap?sid={SID}&date={DAY}").get_json()
        expected["videos"][0].pop("localPlaybackQaAllowed")
        expected["videos"][0]["playbackRestricted"] = True
        same(body, expected, "OFF removes catalog-injected reserved flags without granting academy")
    same(projected, inputs, "bootstrap input immutable")
    same(fingerprint(base), stable, "bootstrap permission postprocessing performs no store writes")


def main():
    global CHECKS
    CHECKS = 0
    with tempfile.TemporaryDirectory(prefix="verify-isolated-kollus-qa-") as directory:
        base = Path(directory).resolve()
        _IO_SCOPE["base"] = base
        try:
            with fixture_modules(base) as (helper, paths, modules, app, fixture):
                pure_context_oracle(helper, base)
                wrapper_oracle(helper, app, fixture["code_root"])
                route_oracle(helper, paths, modules, app, base)
        finally:
            _IO_SCOPE["base"] = None
    print(f"isolated Kollus QA: {CHECKS} assertions passed; actual dedicated routes, guarded OS-temp I/O, no live app/network server")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
