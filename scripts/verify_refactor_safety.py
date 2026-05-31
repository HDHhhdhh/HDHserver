from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import py_compile
import re
import subprocess
import sys
import urllib.parse
from typing import Iterable


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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
    ok = run_js_checks() and ok
    if args.smoke:
        ok = run_smoke_checks() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
