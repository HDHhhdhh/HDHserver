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
from typing import Iterable


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


def run_unit_checks() -> bool:
    checks = [
        run_log_rules_unit_checks,
        run_progress_rule_unit_checks,
        run_watch_route_progress_unit_checks,
        run_log_repository_unit_checks,
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
    args = parser.parse_args()

    ok = True
    ok = run_python_compile() and ok
    ok = run_unit_checks() and ok
    ok = run_js_checks() and ok
    if args.smoke:
        ok = run_smoke_checks() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
