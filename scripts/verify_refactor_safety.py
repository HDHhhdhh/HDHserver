from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import py_compile
import re
import subprocess
import sys
import tempfile
import urllib.parse
from typing import Callable, Iterable


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PYTHON_FILES = [
    ROOT / "app.py",
    *sorted((ROOT / "routes").glob("*.py")),
    *sorted((ROOT / "core").glob("*.py")),
    ROOT / "scripts/verify_refactor_safety.py",
]

JS_CHECK_FILES = [
    ROOT / "static/js/admin/main.js",
    ROOT / "static/js/admin/features/logModal.js",
    ROOT / "static/js/admin/features/today.js",
    ROOT / "static/js/admin/features/today.state.js",
    ROOT / "static/js/admin/features/today.render.js",
    ROOT / "static/js/admin/features/testModal.js",
    ROOT / "static/js/admin/features/videoModal.js",
    ROOT / "static/js/student.js",
    ROOT / "static/js/shared/api.js",
]

CORE_IMPORT_RUNTIME_FILES = [
    "students.json",
    "videos.json",
    "progress.json",
    "materials.json",
    "mat_assign.json",
    "updates.json",
    "today_order.json",
    "extra_attend.json",
    "logs.json",
    "tests.json",
    "absent.json",
    "clinic.json",
    "school_calendar.json",
    "announcements.json",
    "announce_status.json",
    "weekend_slots.json",
    "watch.json",
    "attendance.json",
    "contact.json",
    "arrive_time.json",
    "tests-config.json",
    "page_folders.json",
    "auth.json",
]

RUNTIME_ROOT_SUFFIXES = {
    ".json",
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
    ".db",
    ".db-wal",
    ".db-shm",
    ".csv",
    ".tmp",
}
RUNTIME_DIRS = ("data", "files", "instance")
SKIP_DIR_NAMES = {".git", ".pytest_cache", "__pycache__", "venv", "_data_mirror", "_runtime_backups"}
SQLITE_TRANSIENT_SUFFIXES = (".sqlite-wal", ".sqlite-shm", ".db-wal", ".db-shm")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def rel(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_runtime_paths() -> Iterable[pathlib.Path]:
    seen: set[pathlib.Path] = set()

    for path in ROOT.iterdir():
        if path.is_file() and path.suffix.lower() in RUNTIME_ROOT_SUFFIXES:
            seen.add(path)
            yield path

    for name in CORE_IMPORT_RUNTIME_FILES:
        path = ROOT / name
        if path not in seen:
            seen.add(path)
            yield path

    for dirname in RUNTIME_DIRS:
        base = ROOT / dirname
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_dir():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.relative_to(ROOT).parts):
                continue
            if path not in seen:
                seen.add(path)
                yield path


def runtime_fingerprints() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for path in iter_runtime_paths():
        out[rel(path)] = sha256_file(path) if path.exists() and path.is_file() else None
    return out


def runtime_diff_keys(before: dict[str, str | None], after: dict[str, str | None]) -> list[str]:
    return [
        key
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]


def is_sqlite_transient_sidecar(path: str) -> bool:
    return path.lower().endswith(SQLITE_TRANSIENT_SUFFIXES)


def print_runtime_diff(before: dict[str, str | None], after: dict[str, str | None]) -> None:
    for key in runtime_diff_keys(before, after):
        print(f"runtime changed: {key}", file=sys.stderr)


def run_python_compile() -> bool:
    ok = True
    for path in PYTHON_FILES:
        try:
            py_compile.compile(str(path), doraise=True)
            print(f"py_compile ok: {rel(path)}")
        except Exception as exc:
            ok = False
            print(f"py_compile failed: {rel(path)}: {exc}", file=sys.stderr)
    return ok


def run_node_check(path: pathlib.Path) -> bool:
    cmd = ["node", "--check", rel(path)]
    print("$ " + " ".join(cmd))
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    except FileNotFoundError:
        print("node not found", file=sys.stderr)
        return False
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode == 0


def run_js_checks() -> bool:
    return all(run_node_check(path) for path in JS_CHECK_FILES)


def _assert_unit(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_log_rules_unit_checks() -> None:
    from core.log_rules import log_entry_conflicts_with_base, merge_log_entry_safe

    current = {
        "notes": "keep notes",
        "homeworkTable": [{"book": "A", "this": "1", "next": "2"}],
        "done": True,
    }
    merged = merge_log_entry_safe(current, {"notes": "", "homeworkTable": []})
    _assert_unit(merged["notes"] == "keep notes", "empty notes must not erase existing notes")
    _assert_unit(merged["homeworkTable"] == current["homeworkTable"], "empty homeworkTable must not erase rows")
    _assert_unit(merged["done"] is True, "existing done state must be preserved")

    cleared = merge_log_entry_safe(current, {"__clear": ["notes"]})
    _assert_unit("notes" not in cleared, "__clear must explicitly remove notes")

    _assert_unit(
        log_entry_conflicts_with_base({"notes": "newer"}, {"notes": "base"}),
        "notes mismatch must be a log conflict",
    )


def run_progress_rule_unit_checks() -> None:
    from core.progress_rules import (
        PROGRESS_ALL_STUDENTS_META_KEY,
        PROGRESS_MANUAL_META_KEY,
        WATCH_AUTO_PROGRESS_META_KEY,
        merge_progress_day_sid,
        merge_watch_entry,
        watch_auto_status,
    )

    manual = {
        "m1": "none",
        "m2": "skip",
        "m4": "interrupted",
        PROGRESS_MANUAL_META_KEY: {"m1": True, "m2": True, "m4": True},
    }
    merged = merge_progress_day_sid(manual, {"m1": "done", "m2": "done", "m4": "done"}, source="auto")
    _assert_unit(merged.get("m1") == "none", "auto watch must not overwrite manual white")
    _assert_unit(merged.get("m2") == "skip", "auto watch must not overwrite manual skip")
    _assert_unit(merged.get("m4") == "interrupted", "auto watch must not overwrite manual interrupted")

    legacy_auto = merge_progress_day_sid({"m3": "interrupted"}, {"m3": "done"}, source="auto")
    _assert_unit(legacy_auto.get("m3") == "done", "legacy auto interrupted may upgrade to done")

    auto_started = merge_progress_day_sid({}, {"m5": "interrupted"}, source="auto")
    _assert_unit(auto_started.get("m5") == "interrupted", "auto watch should create interrupted")
    _assert_unit(
        auto_started.get(WATCH_AUTO_PROGRESS_META_KEY, {}).get("m5") == "interrupted",
        "auto watch should mark its own interrupted status",
    )

    auto_done = merge_progress_day_sid(auto_started, {"m5": "done"}, source="auto")
    _assert_unit(auto_done.get("m5") == "done", "auto interrupted should advance to done")
    _assert_unit(
        auto_done.get(WATCH_AUTO_PROGRESS_META_KEY, {}).get("m5") == "done",
        "auto watch should advance its marker to done",
    )

    auto_clear = merge_progress_day_sid(auto_started, {"m5": ""}, source="auto")
    _assert_unit("m5" not in auto_clear, "auto empty update should clear non-done auto progress")
    _assert_unit(
        WATCH_AUTO_PROGRESS_META_KEY not in auto_clear,
        "auto clear should remove empty auto progress metadata",
    )

    auto_done_preserved = merge_progress_day_sid(auto_done, {"m5": ""}, source="auto")
    _assert_unit(auto_done_preserved.get("m5") == "done", "auto empty update must not downgrade done")

    manual_clear = merge_progress_day_sid(auto_done, {"m5": ""})
    _assert_unit("m5" not in manual_clear, "manual empty update should clear progress")
    _assert_unit(
        WATCH_AUTO_PROGRESS_META_KEY not in manual_clear,
        "manual clear should remove stale auto metadata",
    )

    all_students = merge_progress_day_sid({}, {"m6": "done"}, source="allStudents")
    _assert_unit(all_students.get("m6") == "done", "all-students progress should set status")
    _assert_unit(
        all_students.get(PROGRESS_ALL_STUDENTS_META_KEY, {}).get("m6") is True,
        "all-students progress should mark metadata",
    )

    _assert_unit(watch_auto_status({"last": 4, "dur": 100}) == "", "watch under threshold is not progress")
    _assert_unit(
        watch_auto_status({"last": 5, "dur": 100}) == "interrupted",
        "watch interrupted threshold should be shared",
    )
    _assert_unit(
        watch_auto_status({"last": 90, "dur": 100}) == "done",
        "watch done threshold should be shared",
    )
    _assert_unit(
        watch_auto_status({"last": 1, "dur": 0}) == "interrupted",
        "watch with unknown duration and position should still count as started",
    )

    merged_watch = merge_watch_entry(
        {"last": 80, "dur": 100, "completed": False, "updatedAt": 10},
        {"last": 70, "dur": 120, "completed": False, "updatedAt": 20},
    )
    _assert_unit(merged_watch["last"] == 80, "watch merge must keep furthest position")
    _assert_unit(merged_watch["dur"] == 120, "watch merge must keep longest duration")
    _assert_unit(merged_watch["updatedAt"] == 20, "watch merge must keep newest timestamp")


def run_video_completion_unit_checks() -> None:
    import routes.api_basic as api_basic

    date = "2026-06-06"
    student = {
        "id": "s1",
        "curriculum": "ALG",
        "subCurriculum": "BASE",
        "autoVideoAssignCount": 2,
    }
    videos = [
        {"mid": "m1", "curriculum": "ALG", "subCurriculum": "BASE", "chapter": "1"},
        {"mid": "m2", "curriculum": "ALG", "subCurriculum": "BASE", "chapter": "2"},
    ]
    completed_progress = {
        "2026-06-05": {
            "s1": {
                "m1": "done",
                "m2": "skip",
            },
        },
    }
    latest = api_basic._build_latest_status_by_sid(completed_progress)

    _assert_unit(
        api_basic._course_videos_completed(videos, "s1", latest),
        "green done plus red skip video progress must finish the course",
    )

    updates = {date: {"s1": {"videos": ["m1"], "source": "auto"}}}
    fixed = api_basic._ensure_today_auto_assign(
        updates,
        [student],
        videos,
        completed_progress,
        date_key=date,
        watch={},
    )
    _assert_unit(
        api_basic._sid_lookup(fixed.get(date, {}), "s1") is None,
        "completed course must clear existing auto video assignment",
    )

    manual_updates = {date: {"s1": {"videos": ["m1"], "source": "manual"}}}
    fixed_manual = api_basic._ensure_today_auto_assign(
        manual_updates,
        [student],
        videos,
        completed_progress,
        date_key=date,
        watch={},
    )
    _assert_unit(
        api_basic._sid_lookup(fixed_manual.get(date, {}), "s1"),
        "completed course must preserve explicit manual video assignment",
    )


def run_video_completion_source_checks() -> None:
    admin_chat_py = (ROOT / "core/admin_chat.py").read_text("utf-8")
    video_modal_js = (ROOT / "static/js/admin/features/videoModal.js").read_text("utf-8")
    log_modal_js = (ROOT / "static/js/admin/features/logModal.js").read_text("utf-8")

    for path, source in [
        ("static/js/admin/features/videoModal.js", video_modal_js),
        ("static/js/admin/features/logModal.js", log_modal_js),
    ]:
        _assert_unit(
            "VIDEO_PROGRESS_FINISHED_STATUSES = new Set(['done', 'skip'])" in source,
            f"{path} must define green/red finished video progress statuses",
        )
        _assert_unit(
            "function isFinishedVideoProgressStatus" in source,
            f"{path} must use a named finished progress predicate",
        )

    _assert_unit(
        "mids.every(mid => isFinishedVideoProgressStatus(latest[mid]))" in video_modal_js,
        "video modal course completion must count green done plus red skip",
    )
    _assert_unit(
        "cells.every(cell => isFinishedVideoProgressStatus(cell.dataset.state))" in log_modal_js,
        "log modal cleanup must count green done plus red skip",
    )
    _assert_unit(
        "초록(done) 또는 빨강(skip)" in admin_chat_py and "자동 영상 배정은 멈춥니다" in admin_chat_py,
        "admin chatbot video-progress knowledge must mention green/red completion and stopped auto assignment",
    )


def run_watch_route_progress_unit_checks() -> None:
    from core.progress_rules import PROGRESS_MANUAL_META_KEY, WATCH_AUTO_PROGRESS_META_KEY
    import routes.api_basic as api_basic
    import routes.api_watch as api_watch

    temp_base = ROOT / "tmp"
    temp_base.mkdir(exist_ok=True)
    old_basic_progress = api_basic.PRG_PATH
    old_watch_progress = api_watch.PRG_PATH

    with tempfile.TemporaryDirectory(prefix="verify-watch-progress-", dir=temp_base) as tmpdir:
        progress_path = pathlib.Path(tmpdir) / "progress.json"
        progress_path.write_text("{}", "utf-8")

        api_basic.PRG_PATH = progress_path
        api_watch.PRG_PATH = progress_path
        try:
            merged = api_watch._save_progress_status("2026-06-06", "007", "m1", "interrupted")
            _assert_unit(merged.get("m1") == "interrupted", "watch route should save auto interrupted")
            _assert_unit(
                merged.get(WATCH_AUTO_PROGRESS_META_KEY, {}).get("m1") == "interrupted",
                "watch route should persist auto interrupted metadata",
            )

            merged = api_watch._save_progress_status("2026-06-06", "007", "m1", "done")
            _assert_unit(merged.get("m1") == "done", "watch route should advance auto interrupted to done")

            current = json.loads(progress_path.read_text("utf-8-sig"))
            current["2026-06-06"]["007"].update({
                "m2": "none",
                PROGRESS_MANUAL_META_KEY: {"m2": True},
            })
            progress_path.write_text(json.dumps(current, ensure_ascii=False), "utf-8")

            merged = api_watch._save_progress_status("2026-06-06", "007", "m2", "done")
            _assert_unit(merged.get("m2") == "none", "watch route must not overwrite manual white")
        finally:
            api_basic.PRG_PATH = old_basic_progress
            api_watch.PRG_PATH = old_watch_progress


def run_log_repository_unit_checks() -> None:
    from core.log_repository import LogRepository
    from core.log_rules import log_entry_conflicts_with_base, merge_log_entry_safe

    temp_base = ROOT / "tmp"
    temp_base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="verify-logrepo-", dir=temp_base) as tmpdir:
        tmp = pathlib.Path(tmpdir)
        logs_path = tmp / "logs.json"
        db_path = tmp / "app.sqlite"
        logs_path.write_text("{}", "utf-8")

        repo = LogRepository(
            logs_path=logs_path,
            db_path=str(db_path),
            merge_entry=merge_log_entry_safe,
            entry_conflicts=log_entry_conflicts_with_base,
        )

        date = "2026-06-03"
        sid = "s1"
        base = {"notes": "base", "homeworkTable": []}
        repo.patch_entry(date, sid, base, {})

        con = repo._connect()
        try:
            repo._ensure_schema(con)
            repo._sqlite_upsert_entry(con, date, sid, {"notes": "sqlite changed", "homeworkTable": []})
        finally:
            con.close()

        result = repo.patch_entry(date, sid, {"notes": "incoming"}, base)
        _assert_unit(result.sqlite_base_conflict, "sqlite base conflict must be reported")
        _assert_unit(not result.sqlite_ok, "sqlite conflict must not be reported as synced")
        _assert_unit(result.merged.get("notes") == "incoming", "json side should still merge non-conflicting patch")

        con = repo._connect()
        try:
            repo._ensure_schema(con)
            sqlite_after = repo._sqlite_get_entry(con, date, sid)
        finally:
            con.close()
        _assert_unit(sqlite_after.get("notes") == "sqlite changed", "sqlite conflict row must not be overwritten")

        alias_date = "2026-06-04"
        logs_path.write_text(
            json.dumps({alias_date: {"7": {"notes": "json alias"}}}, ensure_ascii=False),
            "utf-8",
        )
        alias_entry = repo.read_entry(alias_date, "007")
        _assert_unit(alias_entry.entry.get("notes") == "json alias", "json fallback must use sid aliases")

        merge_date = "2026-06-05"
        logs_path.write_text(
            json.dumps(
                {merge_date: {sid: {"notes": "json notes", "homeworkTable": [{"book": "B"}]}}},
                ensure_ascii=False,
            ),
            "utf-8",
        )
        con = repo._connect()
        try:
            repo._ensure_schema(con)
            repo._sqlite_upsert_entry(con, merge_date, sid, {"done": True})
        finally:
            con.close()
        merged_entry = repo.read_entry(merge_date, sid).entry
        _assert_unit(merged_entry.get("done") is True, "sqlite field must be preserved on fallback merge")
        _assert_unit(merged_entry.get("notes") == "json notes", "missing sqlite notes should be filled from json")

        import core.log_repository as log_repository_module

        fail_date = "2026-06-06"
        fail_logs_path = tmp / "logs-fail.json"
        fail_db_path = tmp / "app-fail.sqlite"
        fail_logs_path.write_text("{}", "utf-8")
        fail_repo = LogRepository(
            logs_path=fail_logs_path,
            db_path=str(fail_db_path),
            merge_entry=merge_log_entry_safe,
            entry_conflicts=log_entry_conflicts_with_base,
        )

        class JsonSaveFailure(RuntimeError):
            pass

        original_save_atomic = log_repository_module.save_atomic

        def failing_save_atomic(_path, _data):
            raise JsonSaveFailure(r"C:\runtime\logs.json write failed")

        log_repository_module.save_atomic = failing_save_atomic
        try:
            failed_json = fail_repo.patch_entry(fail_date, sid, {"notes": "sqlite committed"}, {})
        finally:
            log_repository_module.save_atomic = original_save_atomic

        _assert_unit(failed_json.sqlite_ok, "sqlite commit should still be reported when json save fails")
        _assert_unit(failed_json.json_ok is False, "json save failure must be surfaced")
        _assert_unit(failed_json.json_error is not None, "json save failure must keep an internal error")

        con = fail_repo._connect()
        try:
            fail_repo._ensure_schema(con)
            sqlite_failed_json = fail_repo._sqlite_get_entry(con, fail_date, sid)
        finally:
            con.close()
        _assert_unit(
            sqlite_failed_json.get("notes") == "sqlite committed",
            "sqlite row must remain committed when legacy json save fails",
        )

        from flask import Flask
        from routes import api_basic
        from types import SimpleNamespace

        class FakeLogRepository:
            def patch_entry(self, _date, _sid, _entry, _base):
                return SimpleNamespace(
                    merged={"notes": "saved"},
                    sqlite_ok=True,
                    sqlite_error=None,
                    sqlite_base_conflict=False,
                    json_conflict_entry=None,
                    json_ok=False,
                    json_error=JsonSaveFailure(r"C:\runtime\logs.json write failed"),
                )

        original_get_log_repository = api_basic.get_log_repository
        api_basic.get_log_repository = lambda: FakeLogRepository()
        try:
            app = Flask("verify-logrepo-json-warning")
            with app.test_request_context(
                "/api/logs/patch",
                method="POST",
                json={"date": fail_date, "sid": sid, "entry": {"notes": "saved"}},
            ):
                response = api_basic.api_logs_patch()
        finally:
            api_basic.get_log_repository = original_get_log_repository

        status_code = response[1] if isinstance(response, tuple) else response.status_code
        response_obj = response[0] if isinstance(response, tuple) else response
        payload = json.loads(response_obj.get_data(as_text=True))
        _assert_unit(status_code == 200, "json failure after sqlite success must keep compatible HTTP 200")
        _assert_unit(payload.get("ok") is True, "json failure after sqlite success must keep ok:true")
        _assert_unit(payload.get("sqlite") is True, "json failure response must keep sqlite:true")
        _assert_unit(payload.get("json") is False, "json failure response must expose json:false")
        warning = str(payload.get("warning") or "")
        _assert_unit(warning, "json failure response must include a sanitized warning")
        _assert_unit("C:" not in warning and "runtime" not in warning, "warning must not expose raw local paths")
        _assert_unit(payload.get("entry", {}).get("notes") == "saved", "entry response shape must be preserved")

        class FakeConflictJsonFailureRepository:
            def patch_entry(self, _date, _sid, _entry, _base):
                return SimpleNamespace(
                    merged={"notes": "unsaved"},
                    sqlite_ok=False,
                    sqlite_error=None,
                    sqlite_base_conflict=True,
                    json_conflict_entry=None,
                    json_ok=False,
                    json_error=JsonSaveFailure(r"C:\runtime\logs.json write failed"),
                )

        api_basic.get_log_repository = lambda: FakeConflictJsonFailureRepository()
        try:
            app = Flask("verify-logrepo-conflict-json-failure")
            with app.test_request_context(
                "/api/logs/patch",
                method="POST",
                json={"date": fail_date, "sid": sid, "entry": {"notes": "unsaved"}},
            ):
                response = api_basic.api_logs_patch()
        finally:
            api_basic.get_log_repository = original_get_log_repository

        status_code = response[1] if isinstance(response, tuple) else response.status_code
        response_obj = response[0] if isinstance(response, tuple) else response
        payload = json.loads(response_obj.get_data(as_text=True))
        _assert_unit(status_code == 409, "sqlite conflict plus json failure must not return success")
        _assert_unit(payload.get("ok") is False, "sqlite conflict plus json failure must return ok:false")
        _assert_unit(payload.get("sqlite") is False, "sqlite conflict plus json failure must expose sqlite:false")
        _assert_unit(payload.get("json") is False, "sqlite conflict plus json failure must expose json:false")
        error = str(payload.get("error") or "")
        _assert_unit(error, "sqlite conflict plus json failure must include an error")
        _assert_unit("C:" not in error and "runtime" not in error, "conflict json failure error must not expose raw local paths")


def run_student_assigned_tests_unit_checks() -> None:
    from routes.api_basic import _student_assigned_tests_for_date

    sid = "s1"
    prev_date = "2026-05-30"
    date = "2026-05-31"
    old_label = "테스트 / 대수 / 기존"
    new_label = "테스트 / 대수 / 신규"
    daily_label = "테스트 / 대수 / 일일메타"
    stale_daily_label = "테스트 / 대수 / stale-daily"
    skipped_label = "테스트 / 대수 / 제외"

    progress = {
        prev_date: {
            sid: {
                "tests": {
                    old_label: "assigned",
                    new_label: "skip",
                    skipped_label: "skip",
                },
            },
        },
        date: {
            sid: {
                "tests": {
                    old_label: "assigned",
                    new_label: "assigned",
                    daily_label: "assigned",
                    skipped_label: "skip",
                },
            },
        },
    }
    logs = {
        date: {
            sid: {
                "assignedTests": [
                    {"label": old_label, "name": "기존", "status": "assigned"},
                    {"label": new_label, "name": "신규", "status": "assigned"},
                    {"label": daily_label, "name": "일일메타", "status": "assigned"},
                    {"label": skipped_label, "name": "제외", "status": "skip"},
                ],
                "testAssignmentDailyTests": [
                    {"label": old_label, "name": "기존", "status": "assigned"},
                    {"label": daily_label, "name": "일일메타", "status": "assigned"},
                    {"label": stale_daily_label, "name": "stale-daily", "status": "assigned"},
                ],
            },
        },
    }

    items = _student_assigned_tests_for_date(progress, logs, date, sid, logs)
    labels = [item.get("label") for item in items]
    _assert_unit(daily_label in labels, "daily test metadata must still be shown")
    _assert_unit(new_label in labels, "new assigned test after previous skip must be shown")
    _assert_unit(stale_daily_label not in labels, "stale daily metadata absent from current progress must not be shown")
    _assert_unit(old_label not in labels, "previously active test must not be resurrected as today's test")
    _assert_unit(skipped_label not in labels, "current skip test must not be shown")

    no_daily_logs = {
        date: {
            sid: {
                "assignedTests": logs[date][sid]["assignedTests"],
            },
        },
    }
    no_daily_items = _student_assigned_tests_for_date(progress, no_daily_logs, date, sid, no_daily_logs)
    no_daily_labels = [item.get("label") for item in no_daily_items]
    _assert_unit(
        no_daily_labels == [new_label, daily_label],
        "without daily metadata, only newly active tests should be shown",
    )

    previous_log_only_label = "테스트 / 대수 / 이전 로그"
    progress_with_log_history = {
        date: {
            sid: {
                "tests": {
                    previous_log_only_label: "assigned",
                    new_label: "assigned",
                },
            },
        },
    }
    logs_with_history = {
        prev_date: {
            sid: {
                "assignedTests": [
                    {"label": previous_log_only_label, "name": "이전 로그", "status": "assigned"},
                ],
            },
        },
        date: {
            sid: {
                "assignedTests": [
                    {"label": previous_log_only_label, "name": "이전 로그", "status": "assigned"},
                    {"label": new_label, "name": "신규", "status": "assigned"},
                ],
            },
        },
    }
    log_history_items = _student_assigned_tests_for_date(
        progress_with_log_history,
        {date: logs_with_history[date]},
        date,
        sid,
        logs_with_history,
    )
    log_history_labels = [item.get("label") for item in log_history_items]
    _assert_unit(
        log_history_labels == [new_label],
        "previous log-only assignments must block resurfacing on the student page",
    )

    completed_label = "REVIEW / ALG / high / 7 / completed"
    current_reassigned_label = "UNIT / ALG / Lv.5 / 2 / reassigned"
    progress_with_completed_history = {
        prev_date: {
            sid: {
                "tests": {
                    completed_label: "done",
                    current_reassigned_label: "done",
                },
            },
        },
        date: {
            sid: {
                "tests": {
                    completed_label: "done",
                    current_reassigned_label: "assigned",
                },
            },
        },
    }
    logs_with_completed_history = {
        prev_date: {
            sid: {
                "assignedTests": [
                    {"label": completed_label, "name": "completed", "status": "done"},
                    {"label": current_reassigned_label, "name": "reassigned", "status": "done"},
                ],
            },
        },
        date: {
            sid: {
                "assignedTests": [
                    {"label": completed_label, "name": "completed", "status": "done"},
                    {"label": current_reassigned_label, "name": "reassigned", "status": "assigned"},
                ],
            },
        },
    }
    completed_history_items = _student_assigned_tests_for_date(
        progress_with_completed_history,
        {date: logs_with_completed_history[date]},
        date,
        sid,
        logs_with_completed_history,
    )
    completed_history_labels = [item.get("label") for item in completed_history_items]
    _assert_unit(
        completed_label not in completed_history_labels,
        "completed tests must not load on the student page",
    )
    _assert_unit(
        current_reassigned_label in completed_history_labels,
        "today's assigned test must load even when the same label was completed before",
    )


def run_admin_chat_contract_source_checks() -> None:
    admin_chat_py = (ROOT / "core/admin_chat.py").read_text("utf-8")

    required_groups = [
        (
            "row data-date fallback contract",
            ["tr.dataset.date", "getAdminDate()"],
        ),
        (
            "assignedTests bootstrap authority contract",
            ["assignedTests는 top-level 배열", "progress[date][sid].tests", "authoritative", "메타데이터/폴백"],
        ),
        (
            "test answer link sync contract",
            [
                "sourceFiles.solutionFileId",
                "static/js/test_answer_link_map.json",
                "assignedTests[].answerUrl",
                "Drive explanation",
            ],
        ),
        (
            "logs patch json warning contract",
            ["json:false", "warning", "SQLite", "legacy logs.json"],
        ),
    ]

    for label, snippets in required_groups:
        missing = [snippet for snippet in snippets if snippet not in admin_chat_py]
        _assert_unit(not missing, f"admin chat docs must describe {label}; missing: {', '.join(missing)}")


def run_admin_wave_b_source_checks() -> None:
    state_js = (ROOT / "static/js/admin/core/state.js").read_text("utf-8")
    main_js = (ROOT / "static/js/admin/main.js").read_text("utf-8")
    today_js = (ROOT / "static/js/admin/features/today.render.js").read_text("utf-8")

    _assert_unit(
        "import { ensureOk } from '../../shared/api.js';" in state_js,
        "admin bootstrap strict helper must reuse shared ensureOk",
    )
    _assert_unit(
        "async function getCriticalJson(url, label)" in state_js,
        "admin bootstrap must have a narrow strict GET helper",
    )
    _assert_unit(
        "api.getOr('/api/updates', {})" not in state_js,
        "critical /api/updates bootstrap GET must not use silent fallback",
    )
    _assert_unit(
        "api.getOr(`/api/logs?date=${encodeURIComponent(today)}`, {})" not in state_js,
        "critical /api/logs bootstrap GET must not use silent fallback",
    )
    _assert_unit(
        "api.getOr(`/api/progress?date=${encodeURIComponent(today)}`, {})" not in state_js,
        "critical /api/progress bootstrap GET must not use silent fallback",
    )
    for optional_call in [
        "api.getOr('/api/materials', {})",
        "api.getOr('/api/mat-assign', {})",
        "api.getOr('/api/extra-attend', {})",
        "api.getOr('/api/absent', {})",
        "api.getOr('/api/school-calendar', {})",
        "api.getOr('/api/tests-config', { categories: {} })",
    ]:
        _assert_unit(optional_call in state_js, f"optional bootstrap fallback must remain: {optional_call}")
    for critical_call in [
        "getCriticalJson('/api/updates'",
        "getCriticalJson(`/api/logs?date=${encodeURIComponent(today)}`",
        "getCriticalJson(`/api/progress?date=${encodeURIComponent(today)}`",
    ]:
        _assert_unit(critical_call in state_js, f"critical bootstrap call must be strict: {critical_call}")

    _assert_unit("try {\n  await bootstrap();" in main_js, "main bootstrap failure must be caught explicitly")
    _assert_unit(
        "alert('관리자 초기 데이터를 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.');" in main_js,
        "main bootstrap failure must be visible to the admin",
    )

    marker = "// Homework completion is the single visible homework flag."
    start = today_js.index(marker)
    end = today_js.index("  });", start)
    homework_block = today_js[start:end]
    for snippet in [
        "const prevChecked = isHwChecked(dateKey, sid);",
        "const prevHw = tr.dataset.hw;",
        "const prevHwRequest = tr.dataset.hwRequest;",
        "const prevHwRequestAt = tr.dataset.hwRequestAt;",
        "const requestChecked = requestInput?.checked;",
        "const requestDisabled = requestInput?.disabled;",
        "const requestPillOn = requestPill?.dataset?.on;",
        "const prevPillOn = pill?.dataset?.on;",
        "restoreDatasetValue('hw', prevHw);",
        "restoreDatasetValue('hwRequest', prevHwRequest);",
        "restoreDatasetValue('hwRequestAt', prevHwRequestAt);",
        "hc.checked = prevChecked;",
        "requestInput.checked = requestChecked;",
        "requestInput.disabled = requestDisabled;",
        "requestPill.dataset.on = requestPillOn;",
        "pill.dataset.on = prevPillOn;",
    ]:
        _assert_unit(snippet in homework_block, f"homework failure rollback must preserve: {snippet}")
    catch_index = homework_block.index("catch (e)")
    mutation_index = homework_block.index("tr.dataset.hw = checked ? '1' : '';")
    return_index = homework_block.index("return;", catch_index)
    reload_index = homework_block.index("await loadTodayAndRender();", catch_index)
    _assert_unit(catch_index < reload_index < return_index < mutation_index, "homework failure path must reload and return before success mutation")


def run_admin_wave_b_behavior_checks() -> None:
    driver = r"""
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const ok = (condition, message) => {
  if (!condition) throw new Error(message);
};
const moduleUrl = (relPath, tag) => {
  const url = pathToFileURL(path.join(process.cwd(), relPath));
  url.searchParams.set('waveb', tag);
  return url.href;
};
const response = (payload, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  statusText: status === 200 ? 'OK' : 'ERROR',
  json: async () => payload,
  text: async () => typeof payload === 'string' ? payload : JSON.stringify(payload),
});
const payloadFor = (url) => {
  const value = String(url);
  if (value === '/api/students') return [];
  if (value === '/api/videos') return [];
  if (value === '/api/materials') return { optional: 'materials' };
  if (value === '/api/updates') return { strict: 'updates' };
  if (value === '/api/mat-assign') return {};
  if (value === '/api/extra-attend') return {};
  if (value.startsWith('/api/logs?date=')) return { strict: 'logs' };
  if (value === '/api/absent') return {};
  if (value.startsWith('/api/progress?date=')) return { strict: 'progress' };
  if (value === '/api/school-calendar') return {};
  if (value === '/api/tests-config') return { categories: {} };
  return {};
};

globalThis.window = globalThis;
window.addEventListener = () => {};
globalThis.sessionStorage = {
  getItem: () => null,
  setItem: () => {},
};

const stateModule = await import(moduleUrl('static/js/admin/core/state.js', 'bootstrap'));

let calls = [];
globalThis.fetch = async (url) => {
  calls.push(String(url));
  if (String(url) === '/api/updates') return response('updates down', 503);
  return response(payloadFor(url));
};
let strictFailed = false;
try {
  await stateModule.bootstrap();
} catch (err) {
  strictFailed = true;
  ok(String(err?.message || '').includes('admin bootstrap /api/updates'), 'strict bootstrap error keeps label');
}
ok(strictFailed, 'critical bootstrap failure must reject');
ok(calls.includes('/api/updates'), 'critical updates endpoint was requested');

globalThis.fetch = async (url) => {
  if (String(url) === '/api/materials') throw new Error('materials offline');
  return response(payloadFor(url));
};
await stateModule.bootstrap();
ok(Object.keys(stateModule.state.materials || {}).length === 0, 'optional materials failure keeps fallback');
ok(stateModule.state.updates?.strict === 'updates', 'strict updates success is preserved');
ok(stateModule.state.logs?.strict === 'logs', 'strict logs success is preserved');
ok(stateModule.state.progress?.strict === 'progress', 'strict progress success is preserved');

const alerts = [];
const dispatches = [];
const loggedErrors = [];
console.error = (...args) => loggedErrors.push(args);
const host = {
  _listeners: {},
  addEventListener(type, callback) {
    this._listeners[type] = callback;
  },
};
globalThis.alert = (message) => alerts.push(String(message));
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};
globalThis.document = {
  _todayDocClickBound: false,
  activeElement: null,
  defaultView: globalThis,
  body: { appendChild: () => {} },
  head: { appendChild: () => {} },
  createElement: () => ({ style: {}, dataset: {}, remove: () => {} }),
  getElementById: (id) => id === 'todayWrap' ? host : null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  dispatchEvent: (event) => dispatches.push(event.type),
};
window.state = stateModule.state;
stateModule.state.logs = {
  '2026-06-05': {
    s1: { hwChecked: false, hwCheckRequested: true, hwCheckRequestedAt: 'prev-request' },
  },
};

const todayRender = await import(moduleUrl('static/js/admin/features/today.render.js', 'rollback'));
let reloads = 0;
todayRender.bindTodayTableEvents(async () => {
  reloads += 1;
});
ok(typeof host._listeners.change === 'function', 'today change handler was bound');

const toggledClasses = [];
const requestInput = { checked: true, disabled: false };
const requestPill = { dataset: { on: '1' } };
const completionPill = { dataset: { on: '0' } };
const tr = {
  dataset: {
    sid: 's1',
    date: '2026-06-05',
    hw: '',
    hwRequest: '1',
    hwRequestAt: 'prev-request',
    att: '',
  },
  classList: {
    toggle: (name, value) => toggledClasses.push([name, value]),
  },
  querySelector(selector) {
    if (selector === '.hwRequestChk') return requestInput;
    if (selector === '.homework-request-toggle') return requestPill;
    return null;
  },
};
const hc = {
  checked: true,
  closest(selector) {
    if (selector === '.hwCheckChk') return this;
    if (selector === 'tr[data-sid][data-date]') return tr;
    if (selector === '.c') return completionPill;
    return null;
  },
};
let patchBody = null;
globalThis.fetch = async (url, init = {}) => {
  if (String(url) === '/api/logs/patch') {
    patchBody = JSON.parse(String(init.body || '{}'));
    return response('patch failed', 500);
  }
  return response(payloadFor(url));
};

await host._listeners.change({ target: hc });

ok(patchBody?.date === '2026-06-05', 'homework save uses row date');
ok(patchBody?.sid === 's1', 'homework save uses row sid');
ok(patchBody?.entry?.hwChecked === true, 'homework save attempted checked state');
ok(hc.checked === false, 'checkbox restored to previous checked state');
ok(tr.dataset.hw === '', 'row hw dataset restored');
ok(tr.dataset.hwRequest === '1', 'row request dataset restored');
ok(tr.dataset.hwRequestAt === 'prev-request', 'row request timestamp restored');
ok(requestInput.checked === true, 'request checkbox checked state restored');
ok(requestInput.disabled === false, 'request checkbox disabled state restored');
ok(requestPill.dataset.on === '1', 'request pill restored');
ok(completionPill.dataset.on === '0', 'completion pill restored');
ok(alerts.some((message) => message.includes('숙제 체크 저장 실패')), 'failure alert shown');
ok(reloads === 1, 'failure path reloads once');
ok(toggledClasses.length > 0, 'row visuals resynced');
ok(loggedErrors.length > 0, 'failure path logs the remote error');
"""
    cmd = ["node", "--input-type=module", "-e", driver]
    print("$ node --input-type=module -e <admin-wave-b-driver>")
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin Wave B behavior driver failed")


def run_admin_test_modal_assignment_source_checks() -> None:
    test_modal_js = (ROOT / "static/js/admin/features/testModal.js").read_text("utf-8")
    patch_start = test_modal_js.index("async function patchLogAssignment")
    patch_end = test_modal_js.index("async function saveModal", patch_start)
    patch_block = test_modal_js[patch_start:patch_end]
    save_start = patch_end
    save_end = test_modal_js.index("function bindEventsOnce", save_start)
    save_block = test_modal_js[save_start:save_end]

    _assert_unit(
        ".catch(() => ({}))" not in patch_block,
        "test assignment latest log read must not silently fall back to an empty entry",
    )
    _assert_unit(
        "fetchLatestLogEntryForAssignment(editingDate, editingSid)" in save_block,
        "test assignment save must preflight latest log before progress patch",
    )
    _assert_unit(
        save_block.index("fetchLatestLogEntryForAssignment(editingDate, editingSid)") <
        save_block.index("fetchJSONSafe('/api/progress/patch'"),
        "latest log preflight must happen before /api/progress/patch",
    )


def run_admin_test_modal_assignment_behavior_checks() -> None:
    driver = r"""
import { pathToFileURL } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';

const ok = (condition, message) => {
  if (!condition) throw new Error(message);
};
const response = (payload, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => typeof payload === 'string' ? payload : JSON.stringify(payload),
});
const sourcePath = path.join(process.cwd(), 'static/js/admin/features/testModal.js');
const source = fs.readFileSync(sourcePath, 'utf8')
  .replace("import { $, CT, toast } from '../core/utils.js';", "const CT = { 'Content-Type': 'application/json' }; const $ = (id) => globalThis.__elements?.[id] || null; const toast = (msg) => globalThis.__toasts.push(String(msg));")
  .replace("import { state } from '../core/state.js';", "const state = globalThis.__state;")
  .replace("import { getAdminDate } from '../core/adminDate.js';", "const getAdminDate = () => '2026-06-05';");
const harness = `
export function __setHarnessState(input) {
  editingDate = input.editingDate;
  editingSid = input.editingSid;
  activeStudent = input.activeStudent || { id: input.editingSid, name: '학생', curriculum: '대수', level: '중' };
  activeSubject = input.activeSubject || '대수';
  activeCategory = input.activeCategory || 'UNIT';
  activeDifficulty = input.activeDifficulty || 'Lv.3';
  activeRound = input.activeRound || '1';
  activeTerm = input.activeTerm || '기말고사';
  activeCatalog = input.activeCatalog || [];
  catalogByKey = new Map(activeCatalog.map(test => [test._key, test]));
  initialTestMap = input.initialTestMap || {};
  selectedStatuses = new Map(input.selectedStatuses || []);
  selectedKeys = new Set(Array.from(selectedStatuses.keys()));
  testSelectionTouched = input.testSelectionTouched !== false;
  defaultExclusionsApplied = !!input.defaultExclusionsApplied;
}
export { patchLogAssignment as __patchLogAssignment, saveModal as __saveModal };
`;
const moduleSource = `${source}\n${harness}\n//# sourceURL=logModalCarriedReapplyHarness.js`;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(moduleSource).toString('base64')}`;

globalThis.window = globalThis;
globalThis.__toasts = [];
globalThis.__elements = { testAppendNotes: { checked: true } };
globalThis.__state = {
  progress: {},
  logs: {},
  testsConfig: {},
  schoolCal: {},
};
globalThis.localStorage = { getItem: () => null };
globalThis.document = { dispatchEvent: () => {} };
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};

const mod = await import(moduleUrl);
const existingLabel = '단원평가 / 대수 / Lv.3 / 1회 / 기존';
const newLabel = '단원평가 / 대수 / Lv.3 / 1회 / 신규';
const existingTest = {
  id: 'existing-id',
  name: '기존',
  categoryKey: 'UNIT',
  curriculum: '대수',
  difficulty: 'Lv.3',
  round: '1',
  _key: existingLabel,
};
const newTest = {
  id: 'new-id',
  name: '신규',
  categoryKey: 'UNIT',
  curriculum: '대수',
  difficulty: 'Lv.3',
  round: '1',
  _key: newLabel,
};

let calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url).startsWith('/api/logs/entry?')) return response('latest log unavailable', 503);
  if (String(url) === '/api/progress/patch') return response({ progress: { tests: { [newLabel]: 'assigned' } } });
  if (String(url) === '/api/logs/patch') return response({ entry: { saved: true } });
  return response({});
};
mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeCatalog: [existingTest, newTest],
  initialTestMap: {},
  selectedStatuses: [[newLabel, 'assigned']],
});
let failed = false;
try {
  await mod.__saveModal({ showPopup: false, refresh: false });
} catch (err) {
  failed = true;
  ok(String(err?.message || '').includes('/api/logs/entry'), 'failed latest log read stays visible');
}
ok(failed, 'failed latest log read aborts saveModal');
ok(!calls.some(call => call.url === '/api/progress/patch'), 'failed latest log read must not call /api/progress/patch');
ok(!calls.some(call => call.url === '/api/logs/patch'), 'failed latest log read must not call /api/logs/patch');

calls = [];
const latestEntry = {
  notes: '상담 시작\n\n이전 배정 블록',
  testAssignmentNote: '이전 배정 블록',
  testAssignmentDailyTests: [
    { label: existingLabel, name: '기존', status: 'assigned', source: 'latest-entry' },
  ],
  assignedTests: [
    { label: existingLabel, name: '기존', status: 'assigned' },
  ],
};
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url).startsWith('/api/logs/entry?')) return response({ ok: true, entry: latestEntry });
  if (String(url) === '/api/progress/patch') return response({ progress: { tests: { [existingLabel]: 'assigned', [newLabel]: 'assigned' } } });
  if (String(url) === '/api/logs/patch') return response({ entry: { saved: true } });
  return response({});
};
mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeCatalog: [existingTest, newTest],
  initialTestMap: { [existingLabel]: 'assigned' },
  selectedStatuses: [[existingLabel, 'assigned'], [newLabel, 'assigned']],
});
await mod.__saveModal({ showPopup: false, refresh: false });
const entryIndex = calls.findIndex(call => call.url.startsWith('/api/logs/entry?'));
const progressIndex = calls.findIndex(call => call.url === '/api/progress/patch');
const logPatch = calls.find(call => call.url === '/api/logs/patch');
ok(entryIndex >= 0 && progressIndex >= 0 && entryIndex < progressIndex, 'latest log read precedes progress patch');
ok(logPatch, '/api/logs/patch is called after successful latest log read');
ok(logPatch.body?.date === '2026-06-05', 'log patch keeps date payload');
ok(logPatch.body?.sid === 's1', 'log patch keeps sid payload');
ok(Array.isArray(logPatch.body?.entry?.assignedTests) && logPatch.body.entry.assignedTests.length === 2, 'assignedTests remain in log patch');
const dailyItems = logPatch.body?.entry?.testAssignmentDailyTests || [];
ok(Array.isArray(dailyItems) && dailyItems.length === 1, 'daily assignment metadata from latest entry is preserved');
ok(dailyItems.some(item => item.label === existingLabel && item.source === 'latest-entry'), 'existing daily metadata comes from latest entry');
ok(String(logPatch.body?.entry?.testAssignmentNote || '').includes('기존'), 'assignment note includes existing item');
ok(String(logPatch.body?.entry?.notes || '').includes('상담 시작'), 'notes are rebuilt from latest entry');
ok(logPatch.body?.base?.notes === latestEntry.notes, 'base notes use latest entry');
const clear = logPatch.body?.__clear || [];
ok(!clear.includes('testAssignmentDailyTests'), 'daily metadata is not cleared on success');
ok(!clear.includes('testAssignmentNote'), 'assignment note is not cleared on success');
"""
    cmd = ["node", "--input-type=module", "-e", driver]
    print("$ node --input-type=module -e <admin-test-modal-assignment-driver>")
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin test modal assignment behavior driver failed")


def run_admin_video_modal_preflight_source_checks() -> None:
    video_modal_js = (ROOT / "static/js/admin/features/videoModal.js").read_text("utf-8")
    patch_start = video_modal_js.index("async function patchExtraVideoLogAssignment")
    patch_end = video_modal_js.index("function buildVideoAssignmentHtml", patch_start)
    patch_block = video_modal_js[patch_start:patch_end]
    save_start = video_modal_js.index("async function saveVideoAssignmentForCurrent")
    save_end = video_modal_js.index("window.saveVideoAssignmentPopup", save_start)
    save_block = video_modal_js[save_start:save_end]

    _assert_unit(
        "async function fetchLatestExtraVideoLogEntry" in video_modal_js,
        "video assignment must have a strict latest log entry helper",
    )
    _assert_unit(
        "latestEntry" in patch_block and "await getJSON(`/api/logs/entry?${q}`)" not in patch_block,
        "extra video log patch must consume the preflight entry instead of silently re-reading",
    )
    _assert_unit(
        "const latestLogEntry = await fetchLatestExtraVideoLogEntry(today, sid);" in save_block,
        "video assignment save must preflight latest log before updates patch",
    )
    _assert_unit(
        save_block.index("fetchLatestExtraVideoLogEntry(today, sid)") <
        save_block.index("fetch('/api/updates/patch'"),
        "latest log preflight must happen before /api/updates/patch",
    )
    _assert_unit(
        "await patchExtraVideoLogAssignment(today, sid, selected, latestLogEntry);" in save_block,
        "extra video log patch must receive the same latest entry used for preflight",
    )
    for snippet in [
        "fetch('/api/updates/patch'",
        "body: JSON.stringify(selected.length",
        "? { date: today, sid, entry: { videos: selected, source } }",
        ": { date: today, sid, remove: true })",
        "fetch('/api/updates', { cache: 'no-store' })",
        "body.base = { notes: prevNotes.trim() };",
    ]:
        _assert_unit(snippet in save_block or snippet in patch_block, f"video assignment source shape must remain: {snippet}")


def _run_admin_video_modal_preflight_driver(scenario: str) -> None:
    driver = r"""
import fs from 'node:fs';
import path from 'node:path';

const scenario = process.argv[1];
const ok = (condition, message) => {
  if (!condition) throw new Error(message);
};
const response = (payload, status = 200, options = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  statusText: status === 200 ? 'OK' : 'ERROR',
  json: async () => {
    if (options.badJson) throw new Error('bad json');
    return payload;
  },
  text: async () => typeof payload === 'string' ? payload : JSON.stringify(payload),
});
const callRecord = (url, init = {}) => ({
  url: String(url),
  method: init.method || 'GET',
  cache: init.cache || '',
  body: init.body ? JSON.parse(String(init.body)) : null,
});
const sourcePath = path.join(process.cwd(), 'static/js/admin/features/videoModal.js');
const source = fs.readFileSync(sourcePath, 'utf8')
  .replace("import { $, CT, toast } from '../core/utils.js';", "const CT = { 'Content-Type': 'application/json' }; const $ = (id) => globalThis.__elements?.[id] || null; const toast = (msg) => globalThis.__toasts.push(String(msg));")
  .replace("import { state } from '../core/state.js';", "const state = globalThis.__state;")
  .replace("import { getAdminDate } from '../core/adminDate.js';", "const getAdminDate = () => globalThis.__adminDate || '2026-06-05';")
  .replace("import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from '../../shared/search.js';", "const applySearchPlaceholder = () => {}; const matchesSearchKey = () => true; const searchKeyForText = (value) => String(value || '').toLowerCase();");
const harness = `
export function __setHarnessState(input) {
  editingSid = input.sid || 's1';
  editingVideoDate = input.date || '2026-06-05';
  activeVideoSelectionDirty = input.dirty !== false;
  activeAssignmentManual = input.assignmentManual === true;
  activePrimaryVideoMids = new Set((input.primaryVideoMids || []).map(String));
  state.updates = input.updates || {};
  state.logs = input.logs || {};
  state.videos = input.videos || state.videos || [];
}
export function __initHarness() {
  initVideoModal();
}
export async function __saveHarness(options = {}) {
  return window.saveVideoAssignmentPopup(options);
}
`;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(`${source}\n${harness}`).toString('base64')}`;

const makeClassList = () => ({
  add: () => {},
  remove: () => {},
  toggle: () => {},
});
const makeElement = (id) => ({
  id,
  style: {},
  dataset: {},
  textContent: '',
  innerHTML: '',
  disabled: false,
  classList: makeClassList(),
  listeners: {},
  addEventListener(type, callback) {
    this.listeners[type] = callback;
  },
  appendChild: () => {},
  remove: () => {},
  querySelector: () => null,
  querySelectorAll: () => [],
  closest: () => null,
});

globalThis.window = globalThis;
window.addEventListener = () => {};
window.visualViewport = { addEventListener: () => {} };
window.devicePixelRatio = 1;
window.innerWidth = 1280;
window.innerHeight = 900;
window.setTimeout = () => 1;
window.clearTimeout = () => {};
globalThis.requestAnimationFrame = (callback) => callback();
globalThis.__adminDate = '2026-06-05';
globalThis.__toasts = [];
globalThis.__dispatches = [];
globalThis.__checkboxes = [{ value: 'extra-1', checked: true }];
globalThis.__elements = {
  vidModal: makeElement('vidModal'),
  mTitle: makeElement('mTitle'),
  chkZone: makeElement('chkZone'),
  mSave: makeElement('mSave'),
  vidSavePopup: makeElement('vidSavePopup'),
  autoAssignCountToggle: makeElement('autoAssignCountToggle'),
  autoAssignCountLabel: makeElement('autoAssignCountLabel'),
};
globalThis.__state = {
  students: [{ id: 's1', name: '학생', curriculum: '정규', subCurriculum: '기본' }],
  videos: [
    { mid: 'course-1', title: '정규 영상', chapter: '1', curriculum: '정규', subCurriculum: '기본' },
    { mid: 'extra-1', title: '확장 영상', chapter: '7', curriculum: '심화', subCurriculum: '문제풀이' },
  ],
  updates: {},
  logs: {},
};
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};
globalThis.document = {
  documentElement: { style: { setProperty: () => {} } },
  head: { appendChild: () => {} },
  body: { appendChild: () => {}, insertAdjacentHTML: () => {}, addEventListener: () => {} },
  createElement: (tag) => ({ ...makeElement(tag), tagName: String(tag).toUpperCase() }),
  getElementById: (id) => globalThis.__elements[id] || null,
  querySelector: () => null,
  querySelectorAll: (selector) => {
    if (selector === '#chkZone input[type="checkbox"]:checked') {
      return globalThis.__checkboxes.filter((checkbox) => checkbox.checked);
    }
    if (selector === '#chkZone input[type="checkbox"]') return globalThis.__checkboxes;
    return [];
  },
  addEventListener: () => {},
  dispatchEvent: (event) => globalThis.__dispatches.push(event.type),
};

const mod = await import(moduleUrl);
mod.__initHarness();

const configureHarness = () => {
  globalThis.__checkboxes = [{ value: 'extra-1', checked: true }];
  mod.__setHarnessState({
    date: '2026-06-05',
    sid: 's1',
    dirty: true,
    assignmentManual: false,
    primaryVideoMids: ['course-1'],
    videos: globalThis.__state.videos,
    updates: {},
    logs: {},
  });
};

if (scenario === 'failures') {
  const cases = [
    {
      name: 'non-ok',
      latest: async () => response('latest unavailable', 503),
    },
    {
      name: 'fetch reject',
      latest: async () => { throw new Error('network down'); },
    },
    {
      name: 'bad json',
      latest: async () => response('', 200, { badJson: true }),
    },
  ];
  for (const testCase of cases) {
    configureHarness();
    const calls = [];
    globalThis.fetch = async (url, init = {}) => {
      calls.push(callRecord(url, init));
      const value = String(url);
      if (value.startsWith('/api/logs/entry?')) return testCase.latest();
      if (value === '/api/updates/patch') return response({ ok: true });
      if (value === '/api/updates') return response({ ok: true, updates: {} });
      if (value === '/api/logs/patch') return response({ ok: true, entry: { saved: true } });
      return response({});
    };
    let failed = false;
    try {
      await mod.__saveHarness({ showPopup: false, refresh: false, manual: true });
    } catch (err) {
      failed = true;
      ok(String(err?.message || '').includes('/api/logs/entry'), `${testCase.name} failure names latest log entry`);
    }
    ok(failed, `${testCase.name} latest log read aborts save`);
    ok(!calls.some((call) => call.url === '/api/updates/patch'), `${testCase.name} must not call /api/updates/patch`);
    ok(!calls.some((call) => call.url === '/api/logs/patch'), `${testCase.name} must not call /api/logs/patch`);
  }
  console.log('videoModal preflight failures PASS');
} else if (scenario === 'happy') {
  configureHarness();
  const calls = [];
  const latestEntry = {
    notes: '상담 유지\n\n[커리 외 영상]\n- 이전 영상',
    extraVideoAssignmentNote: '[커리 외 영상]\n- 이전 영상',
    assignedExtraVideos: [{ mid: 'old-extra', title: '이전 영상' }],
  };
  globalThis.fetch = async (url, init = {}) => {
    calls.push(callRecord(url, init));
    const value = String(url);
    if (value.startsWith('/api/logs/entry?')) return response({ ok: true, entry: latestEntry });
    if (value === '/api/updates/patch') return response({ ok: true });
    if (value === '/api/updates') {
      return response({ ok: true, updates: { '2026-06-05': { s1: { videos: ['extra-1'], source: 'manual' } } } });
    }
    if (value === '/api/logs/patch') return response({ ok: true, entry: { saved: true } });
    return response({});
  };
  await mod.__saveHarness({ showPopup: false, refresh: false, manual: true });
  const latestIndex = calls.findIndex((call) => call.url.startsWith('/api/logs/entry?'));
  const updatesPatchIndex = calls.findIndex((call) => call.url === '/api/updates/patch');
  const updatesReload = calls.find((call) => call.url === '/api/updates' && call.method === 'GET');
  const logPatchIndex = calls.findIndex((call) => call.url === '/api/logs/patch');
  const updatesPatch = calls[updatesPatchIndex];
  const logPatch = calls[logPatchIndex];
  ok(latestIndex >= 0, 'latest log entry is read');
  ok(updatesPatchIndex >= 0, '/api/updates/patch is called');
  ok(logPatchIndex >= 0, '/api/logs/patch is called');
  ok(latestIndex < updatesPatchIndex, 'latest log preflight precedes updates patch');
  ok(updatesPatchIndex < logPatchIndex, 'updates patch still precedes log patch after preflight');
  ok(calls[latestIndex].cache === 'no-store', 'latest log entry read keeps no-store cache');
  ok(updatesReload?.cache === 'no-store', 'updates reload keeps no-store cache');
  ok(updatesPatch.body?.date === '2026-06-05', 'updates patch keeps date');
  ok(updatesPatch.body?.sid === 's1', 'updates patch keeps sid');
  ok(Array.isArray(updatesPatch.body?.entry?.videos), 'updates patch keeps videos payload');
  ok(updatesPatch.body.entry.videos[0] === 'extra-1', 'updates patch keeps selected video');
  ok(updatesPatch.body.entry.source === 'manual', 'updates patch keeps source');
  ok(logPatch.body?.date === '2026-06-05', 'log patch keeps date');
  ok(logPatch.body?.sid === 's1', 'log patch keeps sid');
  ok(Array.isArray(logPatch.body?.entry?.assignedExtraVideos), 'log patch keeps assigned extra videos');
  ok(logPatch.body.entry.assignedExtraVideos[0]?.mid === 'extra-1', 'log patch writes selected extra video metadata');
  ok(String(logPatch.body.entry.extraVideoAssignmentNote || '').includes('확장 영상'), 'log note metadata includes selected extra video');
  ok(String(logPatch.body.entry.notes || '').includes('상담 유지'), 'rebuilt notes preserve latest entry notes');
  ok(String(logPatch.body.entry.notes || '').includes('확장 영상'), 'rebuilt notes include new extra video block');
  ok(logPatch.body?.base?.notes === latestEntry.notes, 'base notes use latest entry');
  console.log('videoModal preflight happy PASS');
} else {
  throw new Error(`unknown scenario: ${scenario}`);
}
"""
    cmd = ["node", "--input-type=module", "-e", driver, scenario]
    print(f"$ node --input-type=module -e <admin-video-modal-preflight-{scenario}-driver>")
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, f"admin video modal preflight {scenario} driver failed")


def run_admin_video_modal_preflight_failure_behavior_checks() -> None:
    _run_admin_video_modal_preflight_driver("failures")


def run_admin_video_modal_preflight_happy_behavior_checks() -> None:
    _run_admin_video_modal_preflight_driver("happy")


def run_admin_log_modal_carried_reapply_source_checks() -> None:
    log_modal_js = (ROOT / "static/js/admin/features/logModal.js").read_text("utf-8")
    helper_start = log_modal_js.index("async function fetchLatestCarriedTestLogEntry")
    helper_end = log_modal_js.index("async function fetchJSONCached", helper_start)
    helper_block = log_modal_js[helper_start:helper_end]
    reapply_start = log_modal_js.index("async function reapplyCarriedTestAssignmentForCurrent")
    reapply_end = log_modal_js.index("logSave.addEventListener", reapply_start)
    reapply_block = log_modal_js[reapply_start:reapply_end]

    _assert_unit(
        "async function fetchLatestCarriedTestLogEntry" in log_modal_js,
        "logModal carried reapply must have a strict latest log helper",
    )
    _assert_unit(
        "fetch(`/api/logs/entry?${q}`" in helper_block and "{ cache: 'no-store' }" in helper_block,
        "carried reapply latest log helper must keep /api/logs/entry no-store fetch shape",
    )
    _assert_unit(
        "fetch('/api/logs'" not in helper_block,
        "carried reapply strict helper must not fall back to broad /api/logs",
    )
    _assert_unit(
        ".catch(() => fallbackEntry)" not in reapply_block and "fallbackEntry" not in reapply_block,
        "carried reapply latest log read must not silently fall back to stale state.logs",
    )
    _assert_unit(
        "const latestEntry = await fetchLatestCarriedTestLogEntry(today, sid);" in reapply_block,
        "carried reapply must preflight strict latest log entry before patch",
    )
    for snippet in [
        "Array.isArray(latestEntry.assignedTests)",
        "Array.isArray(latestEntry[TEST_ASSIGN_DAILY_ITEMS_KEY])",
        "appendCarriedAssignmentNote(latestEntry.notes || '', noteBlock)",
        "base: { notes: latestEntry.notes || '' }",
        "await patchLogEntry(",
    ]:
        _assert_unit(snippet in reapply_block, f"carried reapply must keep latest-entry merge/base flow: {snippet}")


def _run_admin_log_modal_carried_reapply_driver(scenario: str) -> None:
    driver = r"""
import fs from 'node:fs';
import path from 'node:path';

const scenario = process.argv[1];
const ok = (condition, message) => {
  if (!condition) throw new Error(message);
};
const response = (payload, status = 200, options = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => {
    if (options.badJson) throw new Error('bad json');
    return payload;
  },
  text: async () => typeof payload === 'string' ? payload : JSON.stringify(payload),
});
const callRecord = (url, init = {}) => ({
  url: String(url),
  method: init.method || 'GET',
  cache: init.cache || '',
  body: init.body ? JSON.parse(String(init.body)) : null,
});
const makeClassList = () => ({
  add: () => {},
  remove: () => {},
  toggle: () => false,
  contains: () => false,
});
const makeElement = (id) => ({
  id,
  style: {},
  dataset: {},
  value: '',
  textContent: '',
  innerHTML: '',
  disabled: false,
  scrollTop: 0,
  classList: makeClassList(),
  listeners: {},
  addEventListener(type, callback) {
    this.listeners[type] = callback;
  },
  appendChild: () => {},
  remove: () => {},
  insertAdjacentHTML: () => {},
  querySelector: () => null,
  querySelectorAll: () => [],
  closest: () => null,
});
const ensureElement = (id) => globalThis.__elements[id] || (globalThis.__elements[id] = makeElement(id));
const installModalElements = () => {
  for (const id of ['logModal', 'logTitle', 'logNotes', 'logSave', 'logClose', 'logProgress', 'logCompleteBtn', 'hwBody', 'hwAddRow']) {
    ensureElement(id);
  }
};
globalThis.__installLogModalHarnessElements = installModalElements;

globalThis.window = globalThis;
window.addEventListener = () => {};
window.__logModalHarnessReapply = null;
window.hideStudentTooltip = () => {};
window.hideStudentPopupBackdrop = () => {};
globalThis.__toasts = [];
globalThis.__alerts = [];
globalThis.__dispatches = [];
globalThis.__elements = {};
globalThis.__adminDate = '2026-06-06';
globalThis.__state = {
  students: [],
  videos: [],
  logs: {},
  progress: {},
  absentByDate: {},
};
globalThis.alert = (message) => globalThis.__alerts.push(String(message));
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};
globalThis.requestAnimationFrame = (callback) => callback();
globalThis.setTimeout = () => 1;
globalThis.clearTimeout = () => {};
globalThis.document = {
  documentElement: { style: { setProperty: () => {} } },
  head: { appendChild: () => {} },
  body: {
    appendChild: () => {},
    addEventListener: () => {},
    insertAdjacentHTML: () => installModalElements(),
  },
  createElement: (tag) => ({ ...makeElement(tag), tagName: String(tag).toUpperCase() }),
  getElementById: (id) => globalThis.__elements[id] || null,
  querySelector: () => null,
  querySelectorAll: (selector) => {
    if (selector === '#logProgress .progress-cell[data-mid]') return [];
    if (selector === '#logProgress .progress-cell') return [];
    if (selector === '#hwBody .hwBook') return [];
    return [];
  },
  addEventListener: () => {},
  dispatchEvent: (event) => globalThis.__dispatches.push(event.type),
};

const sourcePath = path.join(process.cwd(), 'static/js/admin/features/logModal.js');
let source = fs.readFileSync(sourcePath, 'utf8')
  .replace("import { $, toast, postJSON } from '../core/utils.js';", "const $ = (id) => globalThis.__elements?.[id] || null; const toast = (msg) => globalThis.__toasts.push(String(msg)); const postJSON = async () => ({});")
  .replace("import { state } from '../core/state.js';", "const state = globalThis.__state;")
  .replace("import { getAdminDate } from '../core/adminDate.js';", "const getAdminDate = () => globalThis.__adminDate || '2026-06-06';")
  .replace("import { initTestModal } from './testModal.js';", "const initTestModal = () => {};");
source = source.replace(
  "  logSave.addEventListener('click', async () => {",
  "  window.__logModalHarnessReapply = reapplyCarriedTestAssignmentForCurrent;\n\n  logSave.addEventListener('click', async () => {",
);
const harness = `
export function __setHarnessState(input) {
  editingLogDate = input.date || '2026-06-06';
  editingLogSid = input.sid || 's1';
  logModalReady = true;
  logModalCarriedTestAssignment = input.carried || null;
  logModalSnapshot = input.snapshot || { notes: '', homeworkTable: [] };
  logModalServerSnapshot = input.serverSnapshot || { notes: '', homeworkTable: [] };
  state.logs = input.logs || {};
  state.progress = input.progress || {};
  state.absentByDate = input.absentByDate || {};
}
export function __initHarness() {
  globalThis.__installLogModalHarnessElements();
  initLogModal();
}
export async function __reapplyHarness() {
  if (typeof window.__logModalHarnessReapply !== 'function') throw new Error('reapply harness not installed');
  return await window.__logModalHarnessReapply();
}
`;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(`${source}\n${harness}`).toString('base64')}`;
let mod;
try {
  mod = await import(moduleUrl);
  mod.__initHarness();
} catch (err) {
  console.error(`HARNESS_INIT_ERROR: ${err?.name || 'Error'}: ${err?.message || err}`);
  process.exit(1);
}

const existingLabel = '단원평가 / 대수 / 1회 / 기존';
const carriedLabel = '단원평가 / 대수 / 2회 / 결석보강';
const staleLabel = '단원평가 / 대수 / stale';
const latestEntry = {
  notes: '최신 상담 메모',
  assignedTests: [
    { label: existingLabel, name: '기존', status: 'assigned', latest: true },
  ],
  testAssignmentDailyTests: [
    { label: existingLabel, name: '기존', status: 'assigned', source: 'latest-entry' },
  ],
};
const carried = {
  sourceDate: '2026-06-05',
  items: [
    {
      label: carriedLabel,
      name: '결석보강',
      status: 'assigned',
      categoryLabel: '단원평가',
      curriculum: '대수',
      round: '2',
    },
  ],
};
const staleLogs = {
  '2026-06-06': {
    s1: {
      notes: '오래된 로컬 메모',
      assignedTests: [{ label: staleLabel, name: 'stale', status: 'assigned' }],
      testAssignmentDailyTests: [{ label: staleLabel, name: 'stale', status: 'assigned' }],
    },
  },
};

const configureHarness = () => {
  globalThis.__toasts = [];
  globalThis.__alerts = [];
  mod.__setHarnessState({
    date: '2026-06-06',
    sid: 's1',
    carried,
    logs: JSON.parse(JSON.stringify(staleLogs)),
  });
};

if (scenario === 'failures') {
  const cases = [
    { name: 'non-ok', latest: async () => response({ ok: false, error: 'latest unavailable' }, 503) },
    { name: 'fetch reject', latest: async () => { throw new Error('network down'); } },
    { name: 'bad json', latest: async () => response('', 200, { badJson: true }) },
    { name: 'ok false', latest: async () => response({ ok: false, error: 'logical failure' }, 200) },
  ];
  for (const testCase of cases) {
    configureHarness();
    const calls = [];
    globalThis.fetch = async (url, init = {}) => {
      calls.push(callRecord(url, init));
      const value = String(url);
      if (value.startsWith('/api/logs/entry?')) return testCase.latest();
      if (value === '/api/logs') return response({ '2026-06-06': { s1: latestEntry } });
      if (value === '/api/logs/patch') return response({ ok: true, entry: { saved: true } });
      return response({});
    };
    let failed = false;
    try {
      await mod.__reapplyHarness();
    } catch (err) {
      failed = true;
      ok(String(err?.message || '').includes('/api/logs/entry'), `${testCase.name} failure names latest log entry`);
    }
    ok(failed, `${testCase.name} latest log read aborts carried reapply`);
    ok(!calls.some((call) => call.url === '/api/logs'), `${testCase.name} must not fall back to broad /api/logs`);
    ok(!calls.some((call) => call.url === '/api/logs/patch'), `${testCase.name} must not call /api/logs/patch`);
  }
  console.log('logModal carried reapply failures PASS');
} else if (scenario === 'happy') {
  configureHarness();
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push(callRecord(url, init));
    const value = String(url);
    if (value.startsWith('/api/logs/entry?')) return response({ ok: true, entry: latestEntry });
    if (value === '/api/logs/patch') return response({ ok: true, entry: { saved: true, marker: 'returned' } });
    return response({});
  };
  await mod.__reapplyHarness();
  const latestIndex = calls.findIndex((call) => call.url.startsWith('/api/logs/entry?'));
  const patchIndex = calls.findIndex((call) => call.url === '/api/logs/patch');
  const latestCall = calls[latestIndex];
  const logPatch = calls[patchIndex];
  ok(latestIndex >= 0, 'latest log entry is read');
  ok(patchIndex >= 0, '/api/logs/patch is called');
  ok(latestIndex < patchIndex, 'latest log read precedes log patch');
  ok(latestCall.cache === 'no-store', 'latest log read keeps no-store cache');
  ok(logPatch.body?.date === '2026-06-06', 'log patch keeps date');
  ok(logPatch.body?.sid === 's1', 'log patch keeps sid');
  ok(Array.isArray(logPatch.body?.entry?.assignedTests), 'log patch keeps assignedTests metadata');
  ok(logPatch.body.entry.assignedTests.some((item) => item.label === existingLabel && item.latest === true), 'assignedTests use latest entry metadata');
  ok(logPatch.body.entry.assignedTests.some((item) => item.label === carriedLabel), 'assignedTests include carried item');
  const dailyItems = logPatch.body.entry.testAssignmentDailyTests || [];
  ok(dailyItems.some((item) => item.label === existingLabel && item.source === 'latest-entry'), 'daily metadata uses latest entry');
  ok(dailyItems.some((item) => item.label === carriedLabel), 'daily metadata includes carried item');
  ok(String(logPatch.body.entry.testAssignmentNote || '').includes('결석보강'), 'testAssignmentNote includes carried item');
  ok(String(logPatch.body.entry.notes || '').includes('최신 상담 메모'), 'notes preserve latest entry notes');
  ok(String(logPatch.body.entry.notes || '').includes('결석보강'), 'notes include carried note block');
  ok(!String(logPatch.body.entry.notes || '').includes('오래된 로컬 메모'), 'notes do not use stale local fallback');
  ok(logPatch.body?.base?.notes === latestEntry.notes, 'base notes use latest entry');
  ok(globalThis.__state.logs['2026-06-06'].s1.marker === 'returned', 'returned saved entry updates state');
  console.log('logModal carried reapply happy PASS');
} else {
  throw new Error(`unknown scenario: ${scenario}`);
}
"""
    cmd = ["node", "--input-type=module", "-e", driver, scenario]
    print(f"$ node --input-type=module -e <admin-log-modal-carried-reapply-{scenario}-driver>")
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, f"admin log modal carried reapply {scenario} driver failed")


def run_admin_log_modal_carried_reapply_failure_behavior_checks() -> None:
    _run_admin_log_modal_carried_reapply_driver("failures")


def run_admin_log_modal_carried_reapply_happy_behavior_checks() -> None:
    _run_admin_log_modal_carried_reapply_driver("happy")


def run_admin_weekend_slot_behavior_checks() -> None:
    driver = r"""
import fs from 'node:fs';
import path from 'node:path';

const ok = (condition, message) => {
  if (!condition) throw new Error(message);
};
const response = (payload, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => payload,
  text: async () => typeof payload === 'string' ? payload : JSON.stringify(payload),
});
const loadStateModule = async (tag) => {
  const sourcePath = path.join(process.cwd(), 'static/js/admin/features/today.state.js');
  const source = fs.readFileSync(sourcePath, 'utf8')
    .replace("import { state } from '../core/state.js';", "const state = globalThis.__state;")
    .replace("import { getAdminDate } from '../core/adminDate.js';", "const getAdminDate = () => '2026-06-06';")
    .replace("import { isSelfStudyScheduledForDate } from '../../shared/selfStudy.js';", "const isSelfStudyScheduledForDate = () => false;");
  return import(`data:text/javascript;base64,${Buffer.from(`${source}\nconst __tag = ${JSON.stringify(tag)};\nexport { __tag };`).toString('base64')}`);
};

globalThis.window = globalThis;
globalThis.localStorage = { getItem: () => null, setItem: () => {} };
globalThis.__state = {
  students: [],
  extra: {},
  logs: {},
  absentSlotsByDate: {},
};

let calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && !init.method) return response({ '2026-06-06': { other: [1] } }, 503);
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return response({ ok: true });
  if (String(url) === '/api/today_order') return response({});
  return response({});
};
const stateGetNonOk = await loadStateModule('weekend-get-non-ok');
let getNonOkRejected = false;
try {
  await stateGetNonOk.saveWeekendSlotsFromLabel('s1', '토2', '2026-06-06');
} catch (err) {
  getNonOkRejected = true;
  ok(String(err?.message || '').includes('/api/weekend-slots'), 'GET non-ok error names weekend slots endpoint');
}
ok(getNonOkRejected, 'weekend slots GET non-ok rejects');
ok(!calls.some(call => call.url === '/api/weekend-slots' && call.method === 'POST'), 'weekend slots GET non-ok must not POST');

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && !init.method) throw new Error('offline');
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return response({ ok: true });
  if (String(url) === '/api/today_order') return response({});
  return response({});
};
const stateGetReject = await loadStateModule('weekend-get-reject');
let getRejectRejected = false;
try {
  await stateGetReject.saveWeekendSlotsFromLabel('s1', '토2', '2026-06-06');
} catch {
  getRejectRejected = true;
}
ok(getRejectRejected, 'weekend slots GET rejection rejects');
ok(!calls.some(call => call.url === '/api/weekend-slots' && call.method === 'POST'), 'weekend slots GET rejection must not POST');

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && !init.method) return {
    ok: true,
    status: 200,
    json: async () => { throw new Error('bad json'); },
    text: async () => '',
  };
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return response({ ok: true });
  if (String(url) === '/api/today_order') return response({});
  return response({});
};
const stateGetBadJson = await loadStateModule('weekend-get-bad-json');
let getBadJsonRejected = false;
try {
  await stateGetBadJson.saveWeekendSlotsFromLabel('s1', '토2', '2026-06-06');
} catch (err) {
  getBadJsonRejected = true;
  ok(String(err?.message || '').includes('/api/weekend-slots'), 'GET bad JSON error names weekend slots endpoint');
}
ok(getBadJsonRejected, 'weekend slots GET bad JSON rejects');
ok(!calls.some(call => call.url === '/api/weekend-slots' && call.method === 'POST'), 'weekend slots GET bad JSON must not POST');

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && !init.method) return response({ '2026-06-06': { other: [1] } });
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return response('save failed', 500);
  if (String(url) === '/api/today_order') return response({ '2026-06-06': ['other'] });
  return response({});
};
const statePostNonOk = await loadStateModule('weekend-post-non-ok');
let postNonOkRejected = false;
try {
  await statePostNonOk.saveWeekendSlotsFromLabel('s1', '토2', '2026-06-06');
} catch (err) {
  postNonOkRejected = true;
  ok(String(err?.message || '').includes('/api/weekend-slots'), 'POST non-ok error names weekend slots endpoint');
}
ok(postNonOkRejected, 'weekend slots POST non-ok rejects');
ok(!calls.some(call => call.url === '/api/today_order'), 'weekend slots POST non-ok must not clear today order');

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && !init.method) return response({ '2026-06-06': { other: [1] } });
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return response({ ok: true });
  if (String(url) === '/api/today_order' && !init.method) return response({ '2026-06-06': ['s1'] });
  if (String(url) === '/api/today_order' && init.method === 'POST') return response({ ok: true });
  return response({});
};
const stateSuccess = await loadStateModule('weekend-success');
await stateSuccess.saveWeekendSlotsFromLabel('s1', '토2', '2026-06-06');
const weekendPost = calls.find(call => call.url === '/api/weekend-slots' && call.method === 'POST');
ok(weekendPost, 'weekend slots success posts');
ok(Array.isArray(weekendPost.body?.['2026-06-06']?.s1), 'weekend slots success writes sid slots');
ok(weekendPost.body['2026-06-06'].s1[0] === 2, 'weekend slots success keeps parsed slot');
ok(Array.isArray(weekendPost.body['2026-06-06'].other), 'weekend slots success preserves same-day existing sid');
const orderIndex = calls.findIndex(call => call.url === '/api/today_order');
const postIndex = calls.findIndex(call => call.url === '/api/weekend-slots' && call.method === 'POST');
ok(postIndex >= 0 && orderIndex > postIndex, 'today order clears only after weekend slots POST success');

const loadRenderModule = async () => {
  const sourcePath = path.join(process.cwd(), 'static/js/admin/features/today.render.js');
  const source = fs.readFileSync(sourcePath, 'utf8')
    .replace("import { $, toast } from '../core/utils.js';", "const $ = (id) => id === 'todayWrap' ? globalThis.__host : null; const toast = (msg) => globalThis.__toasts.push(String(msg));")
    .replace("import { getAdminDate, getRealToday } from '../core/adminDate.js';", "const getAdminDate = () => '2026-06-06'; const getRealToday = () => '2026-06-06';")
    .replace("import { state } from '../core/state.js';", "const state = globalThis.__state;")
    .replace(/import \{[\s\S]*?\}\s+from '\.\/today\.state\.js';/, `const yoilOf = () => '토';
const labelFor = () => '토1';
const plannedTimeFor = () => '';
const plannedTimeBase = () => '13:00';
const getArriveOverride = () => '';
const setArriveOverride = (...args) => globalThis.__arriveOverrides.push(args);
const isAttended = () => false;
const setAttended = () => {};
const isContacted = () => false;
const setContacted = () => {};
const isSelfStudy = () => false;
const setSelfStudyRemote = async () => {};
const isHwChecked = () => false;
const setHomeworkCheckedRemote = async () => {};
const isHwCheckRequested = () => false;
const setHomeworkCheckRequestedRemote = async () => {};
const hwCheckRequestedAt = () => '';
const getLeaveTime = () => '';
const setLeaveTimeRemote = async () => {};
const saveWeekendSlotsFromLabel = (...args) => globalThis.__saveWeekendSlotsFromLabel(...args);
const saveOrder = async () => {};
const nowHHMM = () => '13:00';
const nowISO = () => '2026-06-06T00:00:00.000Z';
const patchLog = async () => {};
const truthy = value => value === true || value === 'true' || value === 1 || value === '1';`);
  return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
};

const dispatches = [];
const alerts = [];
globalThis.__toasts = [];
globalThis.__arriveOverrides = [];
globalThis.alert = (message) => alerts.push(String(message));
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};
globalThis.document = {
  _todayDocClickBound: false,
  activeElement: null,
  defaultView: globalThis,
  head: { appendChild: () => {} },
  body: { appendChild: () => {} },
  createElement: () => ({ style: {}, dataset: {}, appendChild: () => {}, remove: () => {}, querySelector: () => null }),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  dispatchEvent: (event) => dispatches.push(event.type),
};
const host = {
  _listeners: {},
  addEventListener(type, callback) {
    (this._listeners[type] ||= []).push(callback);
  },
};
globalThis.__host = host;
globalThis.__saveWeekendSlotsCalls = [];
globalThis.__saveWeekendSlotsFromLabel = async (...args) => {
  globalThis.__saveWeekendSlotsCalls.push(args);
  throw new Error('weekend slot save failed');
};
const renderModule = await loadRenderModule();
let reloads = 0;
renderModule.bindTodayTableEvents(async () => {
  reloads += 1;
});
ok(Array.isArray(host._listeners.focusout) && host._listeners.focusout.length > 0, 'today focusout handler was bound');
const tr = {
  dataset: { sid: 's1', date: '2026-06-06' },
  querySelector: () => null,
};
const slotLabel = {
  textContent: '토2(보강)',
  dataset: { orig: '토1' },
  style: {},
  closest(selector) {
    if (selector === '.slotLabel') return this;
    if (selector === 'tr[data-sid][data-date]') return tr;
    return null;
  },
};
let focusoutRejected = false;
try {
  for (const listener of host._listeners.focusout) {
    await listener({ target: slotLabel });
  }
} catch {
  focusoutRejected = true;
}
ok(!focusoutRejected, 'slot label save failure is handled');
ok(globalThis.__saveWeekendSlotsCalls.length === 1, 'slot label attempts exactly one weekend slot save');
ok(globalThis.__saveWeekendSlotsCalls[0][0] === 's1', 'slot label save uses row sid');
ok(globalThis.__saveWeekendSlotsCalls[0][1] === '토2', 'slot label save uses cleaned label');
ok(globalThis.__saveWeekendSlotsCalls[0][2] === '2026-06-06', 'slot label save uses row date');
ok(slotLabel.textContent === '토1', 'slot label text rolls back on failed save');
ok(slotLabel.dataset.orig === '토1', 'slot label dataset.orig rolls back on failed save');
ok(alerts.length + globalThis.__toasts.length > 0, 'slot label save failure is visible');
ok(dispatches.length === 0, 'slot label failed save does not dispatch attendance update');
ok(reloads === 0, 'slot label failed save does not reload today table');
"""
    cmd = ["node", "--input-type=module", "-e", driver]
    print("$ node --input-type=module -e <admin-weekend-slot-driver>")
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin weekend slot behavior driver failed")


def run_unit_checks() -> bool:
    checks = [
        run_log_rules_unit_checks,
        run_progress_rule_unit_checks,
        run_video_completion_unit_checks,
        run_video_completion_source_checks,
        run_watch_route_progress_unit_checks,
        run_log_repository_unit_checks,
        run_student_assigned_tests_unit_checks,
        run_admin_chat_contract_source_checks,
        run_admin_wave_b_source_checks,
        run_admin_wave_b_behavior_checks,
        run_admin_test_modal_assignment_source_checks,
        run_admin_test_modal_assignment_behavior_checks,
        run_admin_video_modal_preflight_source_checks,
        run_admin_video_modal_preflight_failure_behavior_checks,
        run_admin_video_modal_preflight_happy_behavior_checks,
        run_admin_log_modal_carried_reapply_source_checks,
        run_admin_log_modal_carried_reapply_failure_behavior_checks,
        run_admin_log_modal_carried_reapply_happy_behavior_checks,
        run_admin_weekend_slot_behavior_checks,
    ]
    ok = True
    for check in checks:
        try:
            check()
            print(f"unit ok: {check.__name__}")
        except Exception as exc:
            ok = False
            print(f"unit failed: {check.__name__}: {exc}", file=sys.stderr)
    return ok


def run_selected_checks(checks: Iterable[Callable[[], None]]) -> bool:
    ok = True
    for check in checks:
        try:
            check()
            print(f"unit ok: {check.__name__}")
        except Exception as exc:
            ok = False
            print(f"unit failed: {check.__name__}: {exc}", file=sys.stderr)
    return ok


def load_json(name: str, fallback):
    path = ROOT / name
    try:
        return json.loads(path.read_text("utf-8-sig"))
    except Exception:
        return fallback


def first_date_sid(mapping: object) -> tuple[str, str]:
    if not isinstance(mapping, dict):
        return "", ""
    for date, day in mapping.items():
        date_s = str(date)
        if not DATE_RE.match(date_s) or not isinstance(day, dict):
            continue
        for sid, entry in day.items():
            if str(sid).startswith("__"):
                continue
            if isinstance(entry, dict):
                return date_s, str(sid)
    return "", ""


def first_date(mapping: object) -> str:
    if not isinstance(mapping, dict):
        return ""
    for date, day in mapping.items():
        date_s = str(date)
        if DATE_RE.match(date_s) and isinstance(day, dict):
            return date_s
    return ""


def first_student_sid() -> str:
    students = load_json("students.json", [])
    if not isinstance(students, list):
        return ""
    for student in students:
        if isinstance(student, dict) and student.get("id") is not None:
            sid = str(student.get("id")).strip()
            if sid:
                return sid
    return ""


def smoke_candidate() -> tuple[str, str]:
    for name in ("logs.json", "progress.json", "watch.json"):
        date, sid = first_date_sid(load_json(name, {}))
        if date and sid:
            return date, sid

    date = (
        first_date(load_json("attendance.json", {}))
        or first_date(load_json("contact.json", {}))
        or first_date(load_json("arrive_time.json", {}))
        or "2000-01-01"
    )
    return date, first_student_sid()


def import_smoke_is_safe() -> bool:
    missing = [name for name in CORE_IMPORT_RUNTIME_FILES if not (ROOT / name).exists()]
    if missing:
        print("Skipping smoke: importing app could create missing runtime JSON files:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        return False
    if not (ROOT / "data").exists():
        print("Skipping smoke: importing api_todaymeta could create data/.", file=sys.stderr)
        return False
    return True


def smoke_paths(date: str, sid: str) -> list[tuple[str, str]]:
    qs = urllib.parse.urlencode({"date": date, "sid": sid})
    date_qs = urllib.parse.urlencode({"date": date})
    paths: list[tuple[str, str]] = [
        ("progress date/sid", f"/api/progress?{qs}"),
        ("attendance date", f"/api/attendance?{date_qs}"),
        ("contact date", f"/api/contact?{date_qs}"),
        ("arrive-time date", f"/arrive-time?{date_qs}"),
    ]

    if sid:
        paths.append(("watch latest date/sid", f"/api/watch/latest?{qs}"))

    return paths


def run_smoke_checks() -> bool:
    if not import_smoke_is_safe():
        return False

    before = runtime_fingerprints()
    sys.path.insert(0, str(ROOT))
    from app import app  # noqa: PLC0415

    date, sid = smoke_candidate()
    print(f"smoke candidate: date={date} sid={sid}")
    client = app.test_client()

    ok = True
    for label, path in smoke_paths(date, sid):
        resp = client.get(path)
        print(f"GET {path} -> {resp.status_code} ({label})")
        if resp.status_code != 200:
            ok = False

    print("Skipped GET /api/logs/entry because it may touch SQLite WAL/schema state.")
    print("Skipped GET /api/logs because it may touch SQLite WAL/schema state.")
    print("Skipped GET /api/updates because it can auto-write updates.json.")
    print("Skipped today's /api/student/bootstrap because it can auto-write updates.json.")

    after = runtime_fingerprints()
    changed = runtime_diff_keys(before, after)
    if changed and all(is_sqlite_transient_sidecar(key) for key in changed):
        for key in changed:
            print(f"runtime sqlite sidecar changed (allowed): {key}", file=sys.stderr)
        print("runtime fingerprints unchanged except allowed SQLite sidecars")
    elif changed:
        print_runtime_diff(before, after)
        return False
    else:
        print("runtime fingerprints unchanged after smoke checks")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Run safe refactor verification checks.")
    parser.add_argument("--smoke", action="store_true", help="Run safe GET smoke checks with runtime fingerprints.")
    parser.add_argument(
        "--only-video-modal-preflight-source",
        action="store_true",
        help="Run only video modal latest-entry preflight source checks.",
    )
    parser.add_argument(
        "--only-video-modal-preflight-failures",
        action="store_true",
        help="Run only video modal latest-entry failure behavior checks.",
    )
    parser.add_argument(
        "--only-video-modal-preflight-happy",
        action="store_true",
        help="Run only video modal latest-entry happy behavior checks.",
    )
    parser.add_argument(
        "--only-log-modal-carried-reapply-source",
        action="store_true",
        help="Run only log modal carried reapply source checks.",
    )
    parser.add_argument(
        "--only-log-modal-carried-reapply-failures",
        action="store_true",
        help="Run only log modal carried reapply latest-entry failure checks.",
    )
    parser.add_argument(
        "--only-log-modal-carried-reapply-happy",
        action="store_true",
        help="Run only log modal carried reapply happy behavior checks.",
    )
    parser.add_argument(
        "--only-admin-chat-contract-docs",
        action="store_true",
        help="Run only admin chatbot contract documentation source checks.",
    )
    args = parser.parse_args()

    selected_checks = []
    if args.only_admin_chat_contract_docs:
        selected_checks.append(run_admin_chat_contract_source_checks)
    if args.only_video_modal_preflight_source:
        selected_checks.append(run_admin_video_modal_preflight_source_checks)
    if args.only_video_modal_preflight_failures:
        selected_checks.append(run_admin_video_modal_preflight_failure_behavior_checks)
    if args.only_video_modal_preflight_happy:
        selected_checks.append(run_admin_video_modal_preflight_happy_behavior_checks)
    if args.only_log_modal_carried_reapply_source:
        selected_checks.append(run_admin_log_modal_carried_reapply_source_checks)
    if args.only_log_modal_carried_reapply_failures:
        selected_checks.append(run_admin_log_modal_carried_reapply_failure_behavior_checks)
    if args.only_log_modal_carried_reapply_happy:
        selected_checks.append(run_admin_log_modal_carried_reapply_happy_behavior_checks)
    if selected_checks:
        return 0 if run_selected_checks(selected_checks) else 1

    ok = True
    ok = run_python_compile() and ok
    ok = run_unit_checks() and ok
    ok = run_js_checks() and ok
    if args.smoke:
        ok = run_smoke_checks() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
