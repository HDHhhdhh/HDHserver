from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import pathlib
import py_compile
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from typing import Callable, Final, Iterable


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
    ROOT / "static/js/admin/features/exportLogs.js",
    ROOT / "static/js/admin/features/logModal.js",
    ROOT / "static/js/admin/features/today.js",
    ROOT / "static/js/admin/features/today.state.js",
    ROOT / "static/js/admin/features/today.render.js",
    ROOT / "static/js/admin/features/testModal.js",
    ROOT / "static/js/admin/features/videoModal.js",
    ROOT / "static/js/student.js",
    ROOT / "static/js/shared/api.js",
    ROOT / "scripts/verify_student_material_access_scope.js",
]

REFACTOR_CONTRACT_EVIDENCE: Final[tuple[tuple[int, str, tuple[str, ...], tuple[str, ...]], ...]] = (
    (
        1,
        "log repository fallback fills only missing JSON entries",
        ("run_log_repository_unit_checks",),
        (
            "sqlite field must be preserved on fallback merge",
            "json fallback must not overwrite existing sqlite homeworkTable",
            "read_logs json fallback must fill missing date/sid entries",
        ),
    ),
    (
        2,
        "log routes delegate to LogRepository without path leaks",
        ("run_log_repository_unit_checks",),
        (
            "log entry route must return 200 for a missing sid",
            "bad log patch date must return bad date error",
            "warning must not expose raw local paths",
        ),
    ),
    (
        3,
        "manual and auto progress merge predicates stay explicit",
        ("run_progress_rule_unit_checks",),
        (
            "auto watch must not overwrite manual white",
            "auto watch must not overwrite manual skip",
            "auto watch must not overwrite manual interrupted",
            "auto done should mark its own done status",
        ),
    ),
    (
        4,
        "watch routes use progress rules and preserve manual state",
        ("run_watch_route_progress_unit_checks",),
        (
            "watch route must not overwrite manual white",
            "watch-status route should reject bad status",
            "watch-status route should promote interrupted to done when watch is done",
        ),
    ),
    (
        5,
        "student bootstrap assignedTests contract and chatbot docs stay aligned",
        ("run_student_bootstrap_unit_checks", "run_admin_chat_contract_source_checks"),
        (
            "assignedTests bootstrap authority contract must keep assignedTests as a top-level array",
            "student bootstrap must not resurrect previous assigned tests",
            "student bootstrap missing sid must return missing sid",
            "assignedTests bootstrap authority contract",
        ),
    ),
    (
        6,
        "admin today row actions prefer row data-date before selected date",
        ("run_admin_wave_b_source_checks", "run_admin_wave_b_behavior_checks", "run_admin_chat_contract_source_checks"),
        (
            "homework save uses row date",
            "contact save uses row date before selected admin date",
            "contact save falls back to selected admin date only when row date is missing",
            "row data-date fallback contract",
        ),
    ),
    (
        7,
        "log modal latest-entry and save policy remain merge safe",
        (
            "run_admin_log_modal_carried_reapply_source_checks",
            "run_admin_log_modal_carried_reapply_happy_behavior_checks",
            "run_admin_log_modal_save_policy_source_checks",
            "run_admin_log_modal_save_policy_behavior_checks",
        ),
        (
            "carried reapply latest log read must not silently fall back to stale state.logs",
            "notes do not use stale local fallback",
            "manual white is persisted as none",
            "returned manual white progress updates local state",
        ),
    ),
    (
        8,
        "video modal assignment policy preserves manual source and row date",
        ("run_admin_video_modal_preflight_source_checks", "run_admin_video_modal_assignment_policy_behavior_checks"),
        (
            "activeAssignmentManual = source === 'manual';",
            "manual assignment remains checked when course progress is complete",
            "manual save preserves manual source",
            "force-empty save records a manual clear so auto assignment does not resurrect it",
        ),
    ),
    (
        9,
        "test modal persistence bridge keeps progress tests authoritative",
        ("run_admin_test_modal_persistence_bridge_source_checks", "run_admin_test_modal_assignment_behavior_checks"),
        (
            "test modal save must build /api/progress/patch body through the persistence bridge",
            "progress patch preserves existing test authority",
            "assignedTests remain in log patch",
            "daily metadata is not cleared on success",
        ),
    ),
    (
        10,
        "admin JSON wrapper keeps strict critical loads and optional fallbacks",
        ("run_admin_api_wrapper_usage_source_checks", "run_admin_wave_b_behavior_checks"),
        (
            "admin bootstrap critical helper must delegate to api.getStrict",
            "strict bootstrap error keeps label",
            "optional materials failure keeps fallback",
        ),
    ),
    (
        11,
        "answer-link precedence stays direct, config, then generated map",
        ("run_student_answer_link_precedence_unit_checks", "run_student_bootstrap_unit_checks"),
        (
            "assignment direct answerUrl must win over config and generated map",
            "config sourceFiles.solutionFileId must resolve to a Drive answerUrl before generated map",
            "generated answer-link map must remain the fallback for UNIT assignments",
        ),
    ),
    (
        12,
        "student page preserves assigned-test answer rendering and access gating",
        ("run_student_answer_link_render_source_checks", "run_student_bootstrap_unit_checks"),
        (
            "student assigned-test render block must preserve answer-link behavior",
            "restricted student bootstrap must strip answerUrl",
            "restricted student bootstrap must mark answerRestricted",
        ),
    ),
    (
        13,
        "catalog scripts use temp outputs and guard live files",
        ("run_catalog_script_safety_source_checks", "run_catalog_script_temp_file_behavior_checks"),
        (
            "review temp import must preserve solutionFileId metadata",
            "unit answer-link temp output must contain Drive answerUrl",
            "catalog safety temp checks must not modify live file",
        ),
    ),
)

SMOKE_GUARD_SNIPPETS: Final[tuple[str, ...]] = (
    "before = runtime_fingerprints()",
    "after = runtime_fingerprints()",
    "runtime_diff_keys(before, after)",
    "all(is_sqlite_transient_sidecar(key) for key in changed)",
    "Skipped GET /api/logs/entry because it may touch SQLite WAL/schema state.",
    "Skipped GET /api/logs because it may touch SQLite WAL/schema state.",
    "Skipped GET /api/updates because it can auto-write updates.json.",
    "Skipped today's /api/student/bootstrap because it can auto-write updates.json.",
)

FRONTEND_EVIDENCE_TASKS: Final[tuple[int, ...]] = (6, 7, 8, 9, 12, 14, 15, 16)
FRONTEND_EVIDENCE_INVENTORY = ROOT / ".omo/evidence/task-18-frontend-evidence-inventory.json"
FRONTEND_EVIDENCE_SERVER_STOP = ROOT / ".omo/evidence/task-18-server-stop.txt"

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


def run_student_material_access_scope_checks() -> None:
    cmd = ["node", "scripts/verify_student_material_access_scope.js"]
    print("$ " + " ".join(cmd))
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "student material access scope contract failed")


def run_academy_proxy_network_access_checks() -> None:
    cmd = [sys.executable, "scripts/verify_academy_proxy_network_access.py"]
    print("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "academy proxy network access contract failed")


def _assert_unit(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_app_import_smoke_checks() -> None:
    import importlib

    if not import_smoke_is_safe(report=False):
        print("app import smoke skipped because importing app could create runtime files")
        return

    app_module = importlib.import_module("app")
    _assert_unit(hasattr(app_module, "create_app"), "app import must expose create_app")


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

    auto_done_created = merge_progress_day_sid({}, {"m7": "done"}, source="auto")
    _assert_unit(auto_done_created.get("m7") == "done", "auto done should create done progress")
    _assert_unit(
        auto_done_created.get(WATCH_AUTO_PROGRESS_META_KEY, {}).get("m7") == "done",
        "auto done should mark its own done status",
    )

    manual_none = {"m8": "none", PROGRESS_MANUAL_META_KEY: {"m8": True}}
    auto_done_manual_none = merge_progress_day_sid(manual_none, {"m8": "done"}, source="auto")
    _assert_unit(auto_done_manual_none.get("m8") == "none", "auto done must not overwrite manual none")

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


def run_progress_batch_sids_unit_checks() -> None:
    from flask import Flask
    import routes.api_basic as api_basic

    progress_fixture = {
        "2026-06-01": {
            "s1": {"m1": "done"},
            "s2": {"m2": "interrupted"},
            "s3": {"m3": "skip"},
        },
        "2026-06-02": {
            "s2": {"m4": "done"},
            "s4": {"m5": "done"},
        },
    }

    original_loader = api_basic._load_progress_strict
    api_basic._load_progress_strict = lambda: progress_fixture
    try:
        app = Flask("verify-progress-batch-sids")
        app.register_blueprint(api_basic.bp_api_basic)
        client = app.test_client()

        response = client.get("/api/progress?sids=s1,s2")
        payload = response.get_json() or {}
        _assert_unit(response.status_code == 200, "batch progress fixture route must return 200")
        _assert_unit(
            payload == {
                "2026-06-01": {
                    "s1": {"m1": "done"},
                    "s2": {"m2": "interrupted"},
                },
                "2026-06-02": {
                    "s2": {"m4": "done"},
                },
            },
            "batch progress sids must return only requested students across history",
        )

        repeated_sids = client.get("/api/progress?sids=s1&sids=s2")
        _assert_unit(
            repeated_sids.get_json() == payload,
            "batch progress must accept repeated sids query keys",
        )

        repeated_sid = client.get("/api/progress?sid=s1&sid=s2")
        _assert_unit(
            repeated_sid.get_json() == payload,
            "batch progress must accept repeated sid query keys",
        )

        dated = client.get("/api/progress?date=2026-06-01&sids=s1,s3")
        dated_payload = dated.get_json() or {}
        _assert_unit(
            dated_payload == {
                "2026-06-01": {
                    "s1": {"m1": "done"},
                    "s3": {"m3": "skip"},
                },
            },
            "batch progress sids must compose with date filtering",
        )

        dated_repeated_sid = client.get("/api/progress?date=2026-06-01&sid=s1&sid=s3")
        _assert_unit(
            dated_repeated_sid.get_json() == dated_payload,
            "batch progress repeated sid keys must compose with date filtering",
        )

        single = client.get("/api/progress?date=2026-06-01&sid=s1")
        single_payload = single.get_json() or {}
        _assert_unit(
            single_payload == {"2026-06-01": {"s1": {"m1": "done"}}},
            "existing date+sid progress shape must stay unchanged",
        )

        single_history = client.get("/api/progress?sid=s2")
        _assert_unit(
            single_history.get_json() == {
                "2026-06-01": {"s2": {"m2": "interrupted"}},
                "2026-06-02": {"s2": {"m4": "done"}},
            },
            "existing single sid progress shape must stay unchanged",
        )

        full = client.get("/api/progress")
        _assert_unit(full.get_json() == progress_fixture, "no-query progress route must still return the full map")

        invalid = client.get("/api/progress?date=bad&sids=s1,s2")
        invalid_payload = invalid.get_json() or {}
        _assert_unit(invalid.status_code == 400, "batch progress must preserve invalid date rejection")
        _assert_unit(invalid_payload.get("error") == "bad date", "invalid date error message must stay stable")
    finally:
        api_basic._load_progress_strict = original_loader


def run_progress_read_cache_unit_checks() -> None:
    import routes.api_basic as api_basic

    original_path = api_basic.PRG_PATH
    original_signature = api_basic._PROGRESS_CACHE_SIGNATURE
    original_data = api_basic._PROGRESS_CACHE_DATA

    with tempfile.TemporaryDirectory(prefix="verify-progress-cache-") as tmp:
        progress_path = pathlib.Path(tmp) / "progress.json"
        progress_path.write_text('{"2026-06-01":{"s1":{"m1":"done"}}}', encoding="utf-8")
        try:
            api_basic.PRG_PATH = progress_path
            api_basic._PROGRESS_CACHE_SIGNATURE = None
            api_basic._PROGRESS_CACHE_DATA = None

            first = api_basic._load_progress_strict()
            second = api_basic._load_progress_strict()
            _assert_unit(first is second, "progress read cache must reuse data while file signature is unchanged")

            progress_path.write_text(
                '{"2026-06-02":{"s2":{"m2":"interrupted"},"s3":{"m3":"skip"}}}',
                encoding="utf-8",
            )
            now_ns = time.time_ns()
            os.utime(progress_path, ns=(now_ns, now_ns))

            third = api_basic._load_progress_strict()
            _assert_unit(third is not first, "progress read cache must reload after progress.json changes")
            _assert_unit(
                third == {"2026-06-02": {"s2": {"m2": "interrupted"}, "s3": {"m3": "skip"}}},
                "progress read cache must return the new file contents after reload",
            )
        finally:
            api_basic.PRG_PATH = original_path
            api_basic._PROGRESS_CACHE_SIGNATURE = original_signature
            api_basic._PROGRESS_CACHE_DATA = original_data


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
    from flask import Flask
    import routes.api_basic as api_basic
    import routes.api_watch as api_watch

    temp_base = ROOT / "tmp"
    temp_base.mkdir(exist_ok=True)
    old_basic_progress = api_basic.PRG_PATH
    old_watch_progress = api_watch.PRG_PATH
    old_watch_path = api_watch.WATCH_PATH
    old_network_allowed = api_watch.academy_network_allowed

    with tempfile.TemporaryDirectory(prefix="verify-watch-progress-", dir=temp_base) as tmpdir:
        progress_path = pathlib.Path(tmpdir) / "progress.json"
        watch_path = pathlib.Path(tmpdir) / "watch.json"
        progress_path.write_text("{}", "utf-8")
        watch_path.write_text("{}", "utf-8")

        api_basic.PRG_PATH = progress_path
        api_watch.PRG_PATH = progress_path
        api_watch.WATCH_PATH = watch_path
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

            app = Flask("verify_watch_status")
            app.register_blueprint(api_watch.bp_api_watch)
            client = app.test_client()

            api_watch.academy_network_allowed = lambda: True
            res = client.post(
                "/api/watch-status",
                json={"date": "2026-06-06", "sid": "007", "mid": "m2", "status": "done"},
            )
            _assert_unit(res.status_code == 200, "watch-status route should accept valid auto status")
            body = res.get_json() or {}
            _assert_unit(
                body.get("progress", {}).get("m2") == "none",
                "watch-status route must not overwrite manual white",
            )

            res = client.post(
                "/api/watch-status",
                json={"date": "2026-06-06", "sid": "007", "mid": "m9", "status": "bogus"},
            )
            _assert_unit(res.status_code == 400, "watch-status route should reject bad status")
            _assert_unit(
                (res.get_json() or {}).get("error") == "bad status",
                "bad status error should be stable",
            )

            api_watch.academy_network_allowed = lambda: False
            res = client.post(
                "/api/watch-status",
                json={"date": "2026-06-06", "sid": "007", "mid": "m9", "status": "done"},
            )
            _assert_unit(res.status_code == 403, "watch-status route should reject disallowed networks")
            _assert_unit(
                (res.get_json() or {}).get("error") == "academy_network_required",
                "watch-status network error should be stable",
            )

            api_watch.academy_network_allowed = lambda: True
            watch_path.write_text(
                json.dumps(
                    {
                        "2026-06-06": {
                            "007": {
                                "m3": {
                                    "last": 95,
                                    "dur": 100,
                                    "completed": False,
                                    "updatedAt": 1,
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                "utf-8",
            )
            res = client.post(
                "/api/watch-status",
                json={"date": "2026-06-06", "sid": "007", "mid": "m3", "status": "interrupted"},
            )
            _assert_unit(res.status_code == 200, "watch-status route should accept interrupted status")
            body = res.get_json() or {}
            _assert_unit(
                body.get("progress", {}).get("m3") == "done",
                "watch-status route should promote interrupted to done when watch is done",
            )
        finally:
            api_basic.PRG_PATH = old_basic_progress
            api_watch.PRG_PATH = old_watch_progress
            api_watch.WATCH_PATH = old_watch_path
            api_watch.academy_network_allowed = old_network_allowed


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
                {
                    merge_date: {
                        sid: {"notes": "json notes", "homeworkTable": [{"book": "B"}]},
                        "s2": {"notes": "json only"},
                    },
                },
                ensure_ascii=False,
            ),
            "utf-8",
        )
        con = repo._connect()
        try:
            repo._ensure_schema(con)
            repo._sqlite_upsert_entry(
                con,
                merge_date,
                sid,
                {"done": True, "homeworkTable": [{"book": "sqlite"}]},
            )
        finally:
            con.close()
        merged_entry = repo.read_entry(merge_date, sid).entry
        _assert_unit(merged_entry.get("done") is True, "sqlite field must be preserved on fallback merge")
        _assert_unit(merged_entry.get("notes") == "json notes", "missing sqlite notes should be filled from json")
        _assert_unit(
            merged_entry.get("homeworkTable") == [{"book": "sqlite"}],
            "json fallback must not overwrite existing sqlite homeworkTable",
        )
        merged_logs = repo.read_logs(merge_date, "")
        merged_log_entry = merged_logs[merge_date][sid]
        _assert_unit(
            merged_log_entry.get("homeworkTable") == [{"book": "sqlite"}],
            "read_logs json fallback must not overwrite existing sqlite homeworkTable",
        )
        _assert_unit(
            merged_logs[merge_date]["s2"].get("notes") == "json only",
            "read_logs json fallback must fill missing date/sid entries",
        )

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

        class FakeReadLogRepository:
            def read_entry(self, _date, _sid):
                return SimpleNamespace(source="json", entry={})

        route_app = Flask("verify-log-entry-route")
        route_app.register_blueprint(api_basic.bp_api_basic)
        route_client = route_app.test_client()

        original_get_log_repository = api_basic.get_log_repository
        api_basic.get_log_repository = lambda: FakeReadLogRepository()
        try:
            response = route_client.get("/api/logs/entry?date=2026-06-06&sid=__missing__")
        finally:
            api_basic.get_log_repository = original_get_log_repository

        payload = response.get_json()
        response_text = response.get_data(as_text=True)
        _assert_unit(response.status_code == 200, "log entry route must return 200 for a missing sid")
        _assert_unit(payload.get("ok") is True, "log entry route must keep ok:true")
        _assert_unit(isinstance(payload.get("entry"), dict), "log entry route must return an object entry")
        _assert_unit("C:" not in response_text and str(ROOT) not in response_text, "log entry route must not expose raw local paths")

        response = route_client.post(
            "/api/logs/patch",
            json={"date": "bad-date", "sid": sid, "entry": {"notes": "bad date"}},
        )
        payload = response.get_json()
        _assert_unit(response.status_code == 400, "bad log patch date must return HTTP 400")
        _assert_unit(payload.get("ok") is False, "bad log patch date must return ok:false")
        _assert_unit(payload.get("error") == "bad date", "bad log patch date must return bad date error")

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
    _assert_unit(old_label in labels, "current assigned test must show even when it was active before today")
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
        no_daily_labels == [old_label, new_label, daily_label],
        "without daily metadata, all current active assigned tests should be shown",
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
        log_history_labels == [previous_log_only_label, new_label],
        "current assigned tests must show even when prior log metadata had the same label",
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


def run_absence_test_assignment_transition_unit_checks() -> None:
    import routes.api_attend as api_attend

    sid = "s1"
    date = "2026-06-07"
    assigned_label = "단원평가 / 대수 / Lv.3 / 1회차 / 결석전배정"
    distributed_label = "학군지 기출 / 대수 / 상 / 기말고사 / 2회차 / 압구정고"
    completed_label = "복습 테스트 / 대수 / 상 / 3회차 / 완료"
    skipped_label = "단원평가 / 대수 / Lv.3 / 2회차 / 제외"

    _assert_unit(
        api_attend._absence_test_status_value("assigned") == "interrupted",
        "absence must turn assigned tests into 배부/interrupted",
    )
    _assert_unit(
        api_attend._absence_test_status_value({"status": "assigned", "memo": "keep"}) == {
            "status": "interrupted",
            "memo": "keep",
        },
        "absence must preserve dict test status metadata while changing assigned to 배부",
    )
    _assert_unit(
        api_attend._absence_test_status_value("interrupted") == "interrupted",
        "absence must keep existing 배부/interrupted tests",
    )
    _assert_unit(api_attend._absence_test_status_value("done") == "done", "absence must preserve completed tests")
    _assert_unit(api_attend._absence_test_status_value("skip") == "skip", "absence must preserve excluded tests")

    entry = {
        "notes": "상담 메모\n\n[테스트 배정]\n- 기존 블록",
        "testAssignmentNote": "[테스트 배정]\n- 기존 블록",
        "testAssignmentDailyTests": [
            {"label": assigned_label, "name": "결석전배정", "status": "assigned"},
            {"label": distributed_label, "name": "압구정고", "status": "interrupted"},
            {"label": completed_label, "name": "완료", "status": "done"},
            {"label": skipped_label, "name": "제외", "status": "skip"},
        ],
        "assignedTests": [
            {"label": assigned_label, "name": "결석전배정", "status": "assigned"},
            {"label": completed_label, "name": "완료", "status": "done"},
        ],
    }
    next_entry, changed = api_attend._cleared_assignment_log_entry(entry, sid)
    _assert_unit(changed, "absence log transition should report a change")
    next_daily = {item["label"]: item["status"] for item in next_entry["testAssignmentDailyTests"]}
    next_assigned = {item["label"]: item["status"] for item in next_entry["assignedTests"]}
    _assert_unit(next_daily[assigned_label] == "interrupted", "absence must turn daily assigned log tests into 배부")
    _assert_unit(next_daily[distributed_label] == "interrupted", "absence must preserve daily 배부 log tests")
    _assert_unit(next_daily[completed_label] == "done", "absence must preserve daily completed log tests")
    _assert_unit(next_daily[skipped_label] == "skip", "absence must preserve daily excluded log tests")
    _assert_unit(next_assigned[assigned_label] == "interrupted", "absence must turn cumulative assigned log tests into 배부")
    _assert_unit(next_assigned[completed_label] == "done", "absence must preserve cumulative completed log tests")
    _assert_unit("[테스트 배정]" not in str(next_entry.get("notes") or ""), "absence must still remove generated note blocks")


def run_student_answer_link_precedence_unit_checks() -> None:
    import routes.api_basic as api_basic

    direct_url = "https://direct.example/assignment"
    map_url = "https://map.example/unit-round-2"
    config_file_id = "CONFIG_SOLUTION_FILE_ID"
    config_drive_url = f"https://drive.google.com/file/d/{config_file_id}/view?usp=drivesdk"

    config = {
        "categories": {
            "REVIEW": {
                "tests": [
                    {
                        "id": "review-direct",
                        "name": "Direct precedence",
                        "round": "1",
                        "sourceFiles": {"solutionFileId": config_file_id},
                    },
                    {
                        "id": "review-config",
                        "name": "Config file id",
                        "round": "1",
                        "sourceFiles": {"solutionFileId": config_file_id},
                    },
                ],
            },
        },
    }
    link_map = {
        "review-direct": {"1": {"answerUrl": "https://map.example/should-not-win"}},
        "review-config": {"1": {"answerUrl": "https://map.example/should-not-win"}},
        "unit-map": {"2": {"answerUrl": map_url}},
    }

    original_config_loader = api_basic._load_tests_config_for_answer_links
    original_map_loader = api_basic._load_test_answer_link_map
    try:
        api_basic._load_tests_config_for_answer_links = lambda: config
        api_basic._load_test_answer_link_map = lambda: link_map

        direct_item = {
            "id": "review-direct",
            "category": "REVIEW",
            "name": "Direct precedence",
            "round": "1",
            "answerUrl": direct_url,
        }
        _assert_unit(
            api_basic._test_assignment_answer_url(direct_item) == direct_url,
            "assignment direct answerUrl must win over config and generated map",
        )

        config_item = {
            "id": "review-config",
            "category": "REVIEW",
            "name": "Config file id",
            "round": "1",
        }
        _assert_unit(
            api_basic._test_assignment_answer_url(config_item) == config_drive_url,
            "config sourceFiles.solutionFileId must resolve to a Drive answerUrl before generated map",
        )

        map_item = {
            "id": "unit-map_r2",
            "category": "UNIT",
            "name": "Generated map",
            "round": "2",
        }
        _assert_unit(
            api_basic._test_assignment_answer_url(map_item) == map_url,
            "generated answer-link map must remain the fallback for UNIT assignments",
        )

        missing_item = {
            "id": "unit-missing",
            "category": "UNIT",
            "name": "Missing metadata",
            "round": "1",
        }
        _assert_unit(
            api_basic._test_assignment_answer_url(missing_item) == "",
            "missing answer metadata must leave answerUrl absent",
        )

        restricted = api_basic._academy_restricted_assigned_tests(
            [{
                "label": "T",
                "answerUrl": direct_url,
                "sourceFiles": {"solutionFileId": "x", "other": "kept"},
            }],
            academy_allowed=False,
        )
        _assert_unit(len(restricted) == 1, "restricted assigned test must remain visible")
        _assert_unit("answerUrl" not in restricted[0], "restricted assigned test must strip answerUrl")
        _assert_unit(restricted[0].get("answerRestricted") is True, "restricted assigned test must mark answerRestricted")
        _assert_unit(
            restricted[0].get("sourceFiles") == {"other": "kept"},
            "restricted assigned test must strip sourceFiles solution ids while preserving unrelated metadata",
        )
    finally:
        api_basic._load_tests_config_for_answer_links = original_config_loader
        api_basic._load_test_answer_link_map = original_map_loader


def run_student_bootstrap_unit_checks() -> None:
    from flask import Flask
    from types import SimpleNamespace
    import routes.api_basic as api_basic

    run_student_assigned_tests_unit_checks()

    sid = "s1"
    prev_date = "2026-05-30"
    date = "2026-05-31"
    old_label = "테스트 / 대수 / 기존"
    new_label = "테스트 / 대수 / 신규"
    skipped_label = "테스트 / 대수 / 제외"
    stale_daily_label = "테스트 / 대수 / stale-daily"
    config_file_id = "BOOTSTRAP_SOLUTION_FILE_ID"
    config_drive_url = f"https://drive.google.com/file/d/{config_file_id}/view?usp=drivesdk"
    answer_link_test_meta = {
        "id": "review-config",
        "category": "REVIEW",
        "round": "1",
        "sourceFiles": {"solutionFileId": config_file_id},
    }
    log_entry = {
        "assignedTests": [
            {"label": old_label, "name": "기존", "status": "assigned"},
            {"label": new_label, "name": "신규", "status": "assigned"},
            {"label": skipped_label, "name": "제외", "status": "skip"},
        ],
        "testAssignmentDailyTests": [
            {"label": old_label, "name": "기존", "status": "assigned"},
            {"label": new_label, "name": "신규", "status": "assigned"},
            {"label": stale_daily_label, "name": "stale-daily", "status": "assigned"},
        ],
    }
    log_entry["assignedTests"][1].update(answer_link_test_meta)
    log_entry["testAssignmentDailyTests"][1].update(answer_link_test_meta)
    tests_config = {
        "categories": {
            "REVIEW": {
                "tests": [
                    {
                        "id": "review-config",
                        "name": new_label,
                        "round": "1",
                        "sourceFiles": {"solutionFileId": config_file_id},
                    },
                ],
            },
        },
    }
    logs_all = {
        prev_date: {
            sid: {
                "assignedTests": [
                    {"label": old_label, "name": "기존", "status": "assigned"},
                ],
            },
        },
        date: {sid: log_entry},
    }
    progress = {
        prev_date: {
            sid: {
                "tests": {
                    old_label: "assigned",
                },
            },
        },
        date: {
            sid: {
                "tests": {
                    old_label: "assigned",
                    new_label: "assigned",
                    skipped_label: "skip",
                },
            },
        },
    }

    class FakeLogRepository:
        def read_entry(self, _date, _sid):
            return SimpleNamespace(entry=log_entry)

        def read_json_map(self):
            return logs_all

    def fake_load(path):
        if path == api_basic.STU_PATH:
            return [{"id": sid, "name": "학생1", "day1": "일 13:00"}]
        if path == api_basic.PRG_PATH:
            return progress
        if path == api_basic.VID_PATH:
            return []
        if path == api_basic.UPD_PATH:
            return {}
        if path == api_basic.ASN_PATH:
            return {}
        if path == api_basic.MAT_PATH:
            return {}
        return {}

    original_load = api_basic.load
    original_load_absent = api_basic.load_absent
    original_get_log_repository = api_basic.get_log_repository
    original_academy_network_allowed = api_basic.academy_network_allowed
    original_student_is_registered_on_date = api_basic._student_is_registered_on_date
    original_config_loader = api_basic._load_tests_config_for_answer_links
    original_map_loader = api_basic._load_test_answer_link_map

    api_basic.load = fake_load
    api_basic.load_absent = lambda: {"by_date": {}, "by_student": {}}
    api_basic.get_log_repository = lambda: FakeLogRepository()
    api_basic.academy_network_allowed = lambda: True
    api_basic._student_is_registered_on_date = lambda _student, _sid, _date: True
    api_basic._load_tests_config_for_answer_links = lambda: tests_config
    api_basic._load_test_answer_link_map = lambda: {
        "review-config": {"1": {"answerUrl": "https://map.example/should-not-win"}}
    }
    try:
        app = Flask("verify-student-bootstrap-assigned-tests")
        app.register_blueprint(api_basic.bp_api_basic)
        client = app.test_client()

        response = client.get(f"/api/student/bootstrap?date={date}&sid={sid}")
        payload = response.get_json() or {}
        response_text = response.get_data(as_text=True)

        _assert_unit(response.status_code == 200, "student bootstrap fixture route must return 200")
        _assert_unit(payload.get("ok") is True, "student bootstrap fixture route must return ok:true")
        _assert_unit(
            isinstance(payload.get("assignedTests"), list),
            "assignedTests bootstrap authority contract must keep assignedTests as a top-level array",
        )
        labels = [item.get("label") for item in payload.get("assignedTests") or []]
        _assert_unit(
            labels == [old_label, new_label],
            "student bootstrap must expose all current active assigned tests, even if active before today",
        )
        _assert_unit(skipped_label not in labels, "student bootstrap must not expose current skipped tests")
        _assert_unit(stale_daily_label not in labels, "student bootstrap must suppress stale daily metadata")
        _assert_unit(
            payload["assignedTests"][1].get("answerUrl") == config_drive_url,
            "student bootstrap must resolve Drive answerUrl from config sourceFiles.solutionFileId",
        )
        _assert_unit("C:" not in response_text and str(ROOT) not in response_text, "student bootstrap must not expose raw local paths")

        api_basic.academy_network_allowed = lambda: False
        restricted_response = client.get(f"/api/student/bootstrap?date={date}&sid={sid}")
        restricted_payload = restricted_response.get_json() or {}
        restricted_items = restricted_payload.get("assignedTests") or []
        _assert_unit(restricted_response.status_code == 200, "restricted student bootstrap fixture route must return 200")
        _assert_unit(restricted_payload.get("ok") is True, "restricted student bootstrap fixture route must return ok:true")
        _assert_unit(len(restricted_items) == 2, "restricted student bootstrap must keep all active assigned tests visible")
        restricted_new_item = next((item for item in restricted_items if item.get("label") == new_label), {})
        _assert_unit("answerUrl" not in restricted_new_item, "restricted student bootstrap must strip answerUrl")
        _assert_unit(restricted_new_item.get("answerRestricted") is True, "restricted student bootstrap must mark answerRestricted")
        _assert_unit(
            "solutionFileId" not in (restricted_new_item.get("sourceFiles") or {}),
            "restricted student bootstrap must strip nested solution file ids",
        )

        missing_response = client.get(f"/api/student/bootstrap?date={date}")
        missing_payload = missing_response.get_json() or {}
        _assert_unit(missing_response.status_code == 400, "student bootstrap missing sid must return HTTP 400")
        _assert_unit(missing_payload.get("error") == "missing sid", "student bootstrap missing sid must return missing sid")
    finally:
        api_basic.load = original_load
        api_basic.load_absent = original_load_absent
        api_basic.get_log_repository = original_get_log_repository
        api_basic.academy_network_allowed = original_academy_network_allowed
        api_basic._student_is_registered_on_date = original_student_is_registered_on_date
        api_basic._load_tests_config_for_answer_links = original_config_loader
        api_basic._load_test_answer_link_map = original_map_loader


def run_student_answer_link_render_source_checks() -> None:
    student_js = (ROOT / "static/js/student.js").read_text("utf-8")
    render_start = student_js.index("function renderAssignedTests()")
    render_end = student_js.index("async function recoverStudentSid", render_start)
    render_block = student_js[render_start:render_end]

    for snippet in [
        "function assignedTestAnswerUrl(test)",
        "function isAssignedTestAnswerRestricted(test, answerUrl)",
        "function canOpenAssignedTestAnswer(answerUrl)",
        "function createAssignedTestActionElement(canOpenAnswerUrl, answerUrl)",
    ]:
        _assert_unit(snippet in student_js, f"student assigned-test answer rendering must keep helper seam: {snippet}")

    for snippet in [
        "const answerUrl = assignedTestAnswerUrl(test);",
        "const answerRestricted = isAssignedTestAnswerRestricted(test, answerUrl);",
        "const canOpenAnswerUrl = canOpenAssignedTestAnswer(answerUrl);",
        "const btn = createAssignedTestActionElement(canOpenAnswerUrl, answerUrl);",
        "if (answerUrl) btn.dataset.answerUrl = answerUrl;",
        "if (answerRestricted) btn.dataset.answerRestricted = '1';",
        "showAcademyOnlyNotice();",
    ]:
        _assert_unit(snippet in render_block, f"student assigned-test render block must preserve answer-link behavior: {snippet}")


def run_catalog_script_safety_source_checks() -> None:
    link_map_py = (ROOT / "scripts/build_unit_test_answer_link_map_from_gdown.py").read_text("utf-8")
    review_py = (ROOT / "scripts/import_review_test_catalog_append_csv.py").read_text("utf-8")
    school_py = (ROOT / "scripts/import_school_past_test_catalog_append_csv.py").read_text("utf-8")

    for label, source in (("review", review_py), ("school-past", school_py)):
        for snippet in [
            "argparse.ArgumentParser",
            'parser.add_argument("--config"',
            'parser.add_argument("--csv"',
            'parser.add_argument("--backup-confirmed"',
            "def require_backup_for_live_config_write(",
            "def main(argv: list[str] | None = None)",
        ]:
            _assert_unit(snippet in source, f"{label} import script must keep safe temp/live-write CLI seam: {snippet}")

    for snippet in [
        'parser.add_argument("--backup-confirmed"',
        "def require_backup_for_live_output(",
        "require_backup_for_live_output(args.output, args.backup_confirmed, parser)",
    ]:
        _assert_unit(snippet in link_map_py, f"unit answer-link map script must guard live output writes: {snippet}")


def _assert_cli_exits_with_code(command, argv: list[str], expected_code: int, label: str) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            command(argv)
    except SystemExit as exc:
        _assert_unit(exc.code == expected_code, f"{label} must exit {expected_code}; got {exc.code}")
        _assert_unit(stderr.getvalue(), f"{label} must explain the CLI rejection on stderr")
        return
    raise AssertionError(f"{label} must reject the command")


def run_catalog_script_temp_file_behavior_checks() -> None:
    import scripts.build_unit_test_answer_link_map_from_gdown as unit_links
    import scripts.import_review_test_catalog_append_csv as review_import
    import scripts.import_school_past_test_catalog_append_csv as school_import

    def fingerprint(path: pathlib.Path) -> bytes | None:
        return path.read_bytes() if path.exists() else None

    live_config = ROOT / "tests-config.json"
    live_map = ROOT / "static/js/test_answer_link_map.json"
    live_before = {
        live_config: fingerprint(live_config),
        live_map: fingerprint(live_map),
    }

    temp_base = ROOT / "tmp"
    temp_base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="verify-catalog-safety-", dir=temp_base) as tmpdir:
        tmp = pathlib.Path(tmpdir)
        config_path = tmp / "tests-config.json"
        config_path.write_text(json.dumps({"categories": {}}, ensure_ascii=False), encoding="utf-8")

        review_csv = tmp / "review.csv"
        review_csv.write_text(
            "\n".join([
                "id,subject,difficulty,round,name,problems,answers,source_order,problem_file_id,solution_file_id",
                "review-temp,MATH,중,1,Review Temp,2,A B,7,PROBLEM_REVIEW,SOLUTION_REVIEW",
                "",
            ]),
            encoding="utf-8",
        )
        _assert_unit(
            review_import.main(["--config", str(config_path), "--csv", str(review_csv)]) == 0,
            "review import must support temp config/csv without live backup flag",
        )
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        review_tests = cfg.get("categories", {}).get("REVIEW", {}).get("tests", [])
        _assert_unit(len(review_tests) == 1, "review temp import must add one REVIEW test")
        _assert_unit(
            review_tests[0].get("sourceFiles", {}).get("solutionFileId") == "SOLUTION_REVIEW",
            "review temp import must preserve solutionFileId metadata",
        )

        school_csv = tmp / "school.csv"
        school_csv.write_text(
            "\n".join([
                "id,subject,difficulty,term,examTerm,round,name,problems,source_order,answers,problem_file_id,solution_file_id",
                "school-temp,MATH,중,2026-1,midterm,1,School Temp,2,9,A B,PROBLEM_SCHOOL,SOLUTION_SCHOOL",
                "",
            ]),
            encoding="utf-8",
        )
        _assert_unit(
            school_import.main(["--config", str(config_path), "--csv", str(school_csv)]) == 0,
            "school-past import must support temp config/csv without live backup flag",
        )
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        school_tests = cfg.get("categories", {}).get("SCHOOL_PAST", {}).get("tests", [])
        _assert_unit(len(school_tests) == 1, "school temp import must add one SCHOOL_PAST test")
        _assert_unit(
            school_tests[0].get("sourceFiles", {}).get("solutionFileId") == "SOLUTION_SCHOOL",
            "school temp import must preserve solutionFileId metadata",
        )
        _assert_unit(not config_path.with_name(config_path.name + ".tmp").exists(), "temp config atomic sidecar must be cleaned")

        unit_config = tmp / "unit-config.json"
        unit_config.write_text(
            json.dumps(
                {
                    "categories": {
                        "UNIT": {
                            "tests": [
                                {
                                    "id": "unit-source_r1",
                                    "sourceId": "unit-source",
                                    "curriculum": "MATH",
                                    "difficulty": "Lv.3",
                                    "name": "Algebra",
                                }
                            ]
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        output_path = tmp / "test_answer_link_map.json"
        issues_path = tmp / "issues.json"
        original_iter = unit_links.iter_drive_answer_files
        try:
            unit_links.iter_drive_answer_files = lambda _folder_id: [
                {"subject": "MATH", "level": "Lv.3", "round": "1", "name": "Algebra", "title": "Algebra 1", "fileId": "FILE1"},
                {"subject": "MATH", "level": "Lv.3", "round": "2", "name": "Algebra", "title": "Algebra 2", "fileId": "FILE2"},
                {"subject": "MATH", "level": "Lv.3", "round": "3", "name": "Algebra", "title": "Algebra 3", "fileId": "FILE3"},
            ]
            _assert_unit(
                unit_links.main([
                    "--folder-id",
                    "fake-folder",
                    "--config",
                    str(unit_config),
                    "--output",
                    str(output_path),
                    "--issues",
                    str(issues_path),
                ]) == 0,
                "unit answer-link map script must support temp config/output without live backup flag",
            )
        finally:
            unit_links.iter_drive_answer_files = original_iter

        link_map = json.loads(output_path.read_text(encoding="utf-8"))
        _assert_unit(
            link_map.get("unit-source", {}).get("1", {}).get("answerUrl")
            == "https://drive.google.com/file/d/FILE1/view?usp=drivesdk",
            "unit answer-link temp output must contain Drive answerUrl",
        )
        _assert_unit(issues_path.exists(), "unit answer-link temp issues file must be written when requested")

        for func, label in ((review_import.main, "review"), (school_import.main, "school-past")):
            _assert_cli_exits_with_code(
                func,
                [],
                2,
                f"{label} live import guard without backup confirmation",
            )

        _assert_cli_exits_with_code(
            unit_links.main,
            ["--folder-id", "fake-folder", "--config", str(unit_config)],
            2,
            "unit link-map live output guard without backup confirmation",
        )

    for path, before in live_before.items():
        _assert_unit(fingerprint(path) == before, f"catalog safety temp checks must not modify live file: {path}")


def _strip_css_comments_preserve_lines(source: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda match: "\n" * match.group(0).count("\n"), source, flags=re.S)


def _split_css_selector_list(selector: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(selector):
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(selector[start:index].strip())
            start = index + 1
    parts.append(selector[start:].strip())
    return [part for part in parts if part]


def _iter_css_selectors(source: str) -> Iterable[tuple[int, str]]:
    css = _strip_css_comments_preserve_lines(source)
    for match in re.finditer(r"([^{}]+)\{", css):
        selector_group = match.group(1).strip()
        if not selector_group or selector_group.startswith("@"):
            continue
        line_no = css.count("\n", 0, match.start(1)) + 1
        for selector in _split_css_selector_list(selector_group):
            if selector and not selector.startswith("@"):
                yield line_no, " ".join(selector.split())


def _admin_css_selector_is_scoped(selector: str) -> bool:
    stable_roots = (
        "body.admin",
        "html body.admin",
        ".admin-shell",
        ".admin-workspace",
        "#adminChatPanel",
        "#logModal",
        "#vidModal",
        "#testModal",
        "#extraModal",
        "#selectionModal",
        "#absentRegisterModal",
        "#manualMakeupModal",
    )
    return selector.startswith(stable_roots)


def _student_css_selector_is_scoped(selector: str) -> bool:
    stable_roots = (
        "body.student-page",
        "html body.student-page",
        ".student-shell",
        "#assignedTestsPanel",
        "#announceModal",
        "#announceHistoryModal",
        "#testSubmitModal",
    )
    return selector.startswith(stable_roots)


def run_admin_css_scope_source_checks() -> None:
    admin_css = (ROOT / "static/css/admin.css").read_text(encoding="utf-8")
    _assert_unit(
        any(font in admin_css for font in ("Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic")),
        "admin.css must preserve Korean-capable font stack",
    )
    _assert_unit("body.admin body.admin" not in admin_css, "admin.css must not contain duplicate body.admin scope")
    _assert_unit("body.admin /*" not in admin_css, "admin.css must not place section comments inside selectors")
    offenders = [
        f"{line_no}: {selector}"
        for line_no, selector in _iter_css_selectors(admin_css)
        if not _admin_css_selector_is_scoped(selector)
    ]
    _assert_unit(
        not offenders,
        "admin.css has unscoped selectors:\n" + "\n".join(offenders[:80]),
    )


def run_student_css_scope_source_checks() -> None:
    student_css = (ROOT / "static/css/student.css").read_text(encoding="utf-8")
    _assert_unit(
        any(font in student_css for font in ("Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic")),
        "student.css must preserve Korean-capable font stack",
    )
    _assert_unit(
        "body.student-page body.student-page" not in student_css,
        "student.css must not contain duplicate body.student-page scope",
    )
    _assert_unit(
        "body.student-page /*" not in student_css,
        "student.css must not place section comments inside selectors",
    )
    _assert_unit(
        "body.student-page #assignedTestsPanel" in student_css,
        "student.css must explicitly scope the assigned tests panel",
    )
    _assert_unit(
        "body.student-page #announceModal" in student_css,
        "student.css must explicitly scope the announcement modal",
    )
    _assert_unit(
        "body.student-page #announceHistoryModal" in student_css,
        "student.css must explicitly scope the announcement history modal",
    )
    offenders = [
        f"{line_no}: {selector}"
        for line_no, selector in _iter_css_selectors(student_css)
        if not _student_css_selector_is_scoped(selector)
    ]
    _assert_unit(
        not offenders,
        "student.css has unscoped selectors:\n" + "\n".join(offenders[:80]),
    )


def run_shared_css_scope_source_checks() -> None:
    main_css = (ROOT / "static/css/main.css").read_text(encoding="utf-8")
    style_css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
    combined = main_css + "\n" + style_css
    _assert_unit(
        any(font in main_css for font in ("Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic")),
        "main.css must preserve Korean-capable font stack",
    )
    _assert_unit(
        any(font in style_css for font in ("Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic")),
        "style.css must preserve Korean-capable font stack",
    )
    _assert_unit(
        all(font in combined for font in ("--font-ui:", "--font-display:")),
        "shared CSS must expose shared font tokens",
    )
    first_root_end = style_css.index("}\n\n/* ========== body")
    first_root = style_css[:first_root_end]
    _assert_unit("--font-ui:" in first_root, "style.css must keep shared font tokens in the first root block")
    _assert_unit("--font-display:" in first_root, "style.css must keep shared display font token in the first root block")
    _assert_unit(
        style_css.count("--font-ui:") == 1,
        "style.css must not redeclare --font-ui in a later root block",
    )
    _assert_unit(
        style_css.count("--font-display:") == 1,
        "style.css must not redeclare --font-display in a later root block",
    )
    _assert_unit("font-family: var(--font-ui)" in style_css, "style.css body/control fonts must use --font-ui")
    _assert_unit("body.all-page" in style_css, "style.css must keep all-page scoped containment")
    _assert_unit("body.all-page #allWrap" in style_css, "style.css must keep all-students table containment")
    _assert_unit("body.all-page #yoilModal" in style_css, "style.css must keep all-page modal containment")


def run_refactor_contract_evidence_source_checks() -> None:
    script_source = (ROOT / "scripts/verify_refactor_safety.py").read_text("utf-8")
    unit_start = script_source.rfind("def run_unit_checks()")
    selected_start = script_source.rfind("def run_selected_checks")
    unit_block = script_source[unit_start:selected_start]
    smoke_start = script_source.rfind("def run_smoke_checks()")
    main_start = script_source.rfind("def main()")
    smoke_block = script_source[smoke_start:main_start]

    task_numbers = [task for task, _label, _helpers, _snippets in REFACTOR_CONTRACT_EVIDENCE]
    _assert_unit(
        task_numbers == list(range(1, 14)),
        "refactor contract evidence registry must cover Tasks 1-13 exactly once and in order",
    )

    for task, label, helper_names, assertion_snippets in REFACTOR_CONTRACT_EVIDENCE:
        _assert_unit(helper_names, f"Task {task} {label} must name at least one evidence helper")
        _assert_unit(assertion_snippets, f"Task {task} {label} must name at least one assertion snippet")
        for helper_name in helper_names:
            _assert_unit(
                f"def {helper_name}(" in script_source,
                f"Task {task} {label} helper must be defined: {helper_name}",
            )
            _assert_unit(
                f"        {helper_name}," in unit_block,
                f"Task {task} {label} helper must run in the full safety suite: {helper_name}",
            )
        for snippet in assertion_snippets:
            _assert_unit(
                snippet in script_source,
                f"Task {task} {label} must keep named assertion/evidence snippet: {snippet}",
            )

    for snippet in SMOKE_GUARD_SNIPPETS:
        _assert_unit(
            snippet in smoke_block,
            f"smoke fingerprinting and safe-skip guard must remain intact: {snippet}",
        )


def run_frontend_evidence_inventory_checks() -> None:
    evidence_dir = ROOT / ".omo/evidence"
    _assert_unit(evidence_dir.exists(), "frontend evidence directory must exist")

    for task in FRONTEND_EVIDENCE_TASKS:
        files = sorted(evidence_dir.glob(f"task-{task}-*"))
        _assert_unit(files, f"frontend Task {task} must have at least one evidence artifact")
        _assert_unit(
            any(path.suffix.lower() == ".png" and path.stat().st_size > 0 for path in files),
            f"frontend Task {task} must have a nonblank screenshot artifact",
        )

    _assert_unit(
        FRONTEND_EVIDENCE_INVENTORY.exists(),
        "Task 18 must write a frontend evidence inventory with URL, viewport, date, and pass/fail observations",
    )
    _assert_unit(
        FRONTEND_EVIDENCE_SERVER_STOP.exists(),
        "Task 18 must write a server cleanup receipt",
    )

    inventory = json.loads(FRONTEND_EVIDENCE_INVENTORY.read_text(encoding="utf-8-sig"))
    _assert_unit(inventory.get("ok") is True, "frontend evidence inventory must mark ok:true")
    tasks = inventory.get("tasks")
    _assert_unit(isinstance(tasks, list), "frontend evidence inventory must contain a tasks list")
    seen_tasks: set[int] = set()
    for entry in tasks:
        _assert_unit(isinstance(entry, dict), "frontend evidence task entry must be an object")
        task_id = entry.get("task")
        _assert_unit(isinstance(task_id, int), "frontend evidence task entry must name an integer task")
        seen_tasks.add(task_id)
        _assert_unit(entry.get("targetUrl") or entry.get("targetUrls"), f"Task {task_id} evidence must record target URL")
        _assert_unit(entry.get("viewports"), f"Task {task_id} evidence must record viewport data")
        _assert_unit(entry.get("passFail"), f"Task {task_id} evidence must record pass/fail observation")
        if task_id in {6, 7, 8, 9, 12, 15, 16}:
            _assert_unit(entry.get("selectedDate"), f"Task {task_id} evidence must record selected date")
        screenshots = entry.get("screenshots")
        _assert_unit(isinstance(screenshots, list) and screenshots, f"Task {task_id} evidence must list screenshots")
        for screenshot in screenshots:
            _assert_unit(isinstance(screenshot, str), f"Task {task_id} screenshot path must be a string")
            screenshot_path = ROOT / screenshot
            _assert_unit(screenshot_path.exists(), f"Task {task_id} screenshot must exist: {screenshot}")
            _assert_unit(screenshot_path.stat().st_size > 0, f"Task {task_id} screenshot must be nonblank: {screenshot}")

    _assert_unit(
        seen_tasks == set(FRONTEND_EVIDENCE_TASKS),
        "frontend evidence inventory must cover tasks 6, 7, 8, 9, 12, 14, 15, and 16 exactly",
    )

    cleanup_receipt = FRONTEND_EVIDENCE_SERVER_STOP.read_text(encoding="utf-8-sig").lower()
    for snippet in ("port", "pid", "no listen"):
        _assert_unit(snippet in cleanup_receipt, f"server cleanup receipt must record {snippet}")


def run_admin_chat_contract_source_checks() -> None:
    admin_chat_py = (ROOT / "core/admin_chat.py").read_text("utf-8")
    refactor_notes_md = (ROOT / "scripts/refactor_notes_logs_progress.md").read_text("utf-8")

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

    required_note_groups = [
        (
            "assigned test answer-link notes",
            [
                "progress[date][sid].tests",
                "assignedTests[].answerUrl",
                "sourceFiles.solutionFileId",
                "static/js/test_answer_link_map.json",
            ],
        ),
        (
            "catalog writer safety notes",
            ["--backup-confirmed", "--config", "--csv", "--output", "--issues"],
        ),
    ]
    for label, snippets in required_note_groups:
        missing = [snippet for snippet in snippets if snippet not in refactor_notes_md]
        _assert_unit(not missing, f"refactor notes must describe {label}; missing: {', '.join(missing)}")


def run_admin_calendar_test_completion_source_checks() -> None:
    calendar_js = (ROOT / "static/js/admin/features/calendar.js").read_text("utf-8-sig")
    hover_tooltip_js = (ROOT / "static/js/admin/features/hoverTooltip.js").read_text("utf-8")
    today_render_js = (ROOT / "static/js/admin/features/today.render.js").read_text("utf-8")
    admin_chat_py = (ROOT / "core/admin_chat.py").read_text("utf-8")

    for snippet in [
        "const examSubjectForRow = (row) => String(",
        "subject: subjectName,",
        "const key = `${row.kind}|${row.school}|${row.subject}|${row.start}|${row.end}`;",
        "const subject = String(row.subject || '').trim() || '수학';",
        "const title = `${shortSchool}${gradeToken ? gradeToken : ''} ${subject}`;",
    ]:
        _assert_unit(snippet in calendar_js, f"calendar exam events must preserve row subject: {snippet}")

    _assert_unit(
        "const examSubject = phase || '수학';" in hover_tooltip_js
        and "pill(`${examSubject} 시험일`, exam.math || '-', { big: true })" in hover_tooltip_js,
        "admin hover tooltip must label exam dates with the row phase subject",
    )

    homework_start = today_render_js.index("if (homeworkLeaveBtn)")
    homework_end = today_render_js.index("const docBtn = e.target.closest('.btn-doc');", homework_start)
    homework_block = today_render_js[homework_start:homework_end]
    _assert_unit(
        "completeAssignedTestsForRecordCleanup" not in homework_block,
        "숙검하원 must preserve assigned tests until record cleanup",
    )
    _assert_unit(
        "done: true," in homework_block and "leaveTime: t," in homework_block and "leaveAt," in homework_block,
        "숙검하원 log patch must still mark the leave without test-completion metadata",
    )

    leave_start = today_render_js.index("const leaveBtn = e.target.closest('.markLeave');")
    leave_end = today_render_js.index("const undoBtn = e.target.closest('.undoDone');", leave_start)
    leave_block = today_render_js[leave_start:leave_end]
    _assert_unit(
        "completeAssignedTestsForRecordCleanup" not in leave_block,
        "하원 must preserve assigned tests until record cleanup",
    )
    _assert_unit(
        "done: true," in leave_block and "leaveTime: t," in leave_block and "leaveAt: nowISO()," in leave_block,
        "하원 log patch must still mark the leave without test-completion metadata",
    )

    record_cleanup_start = today_render_js.index("const undoBtn = e.target.closest('.undoDone');")
    record_cleanup_end = today_render_js.index("    });", record_cleanup_start)
    record_cleanup_block = today_render_js[record_cleanup_start:record_cleanup_end]
    _assert_unit(
        "const testPatch = await completeAssignedTestsForRecordCleanup(date, sid);" in record_cleanup_block
        and "await patchLog(date, sid, { ...testPatch, archived: true });" in record_cleanup_block,
        "기록 정리 must remain the path that completes assigned tests",
    )
    _assert_unit(
        "하원/숙검하원은 테스트 배정 상태를 유지" in admin_chat_py
        and "기록 정리만 결석 학생을 제외한 assigned 테스트를 done" in admin_chat_py,
        "admin chatbot docs must describe assigned-test completion only on record cleanup",
    )


def run_admin_wave_b_source_checks() -> None:
    state_js = (ROOT / "static/js/admin/core/state.js").read_text("utf-8")
    main_js = (ROOT / "static/js/admin/main.js").read_text("utf-8")
    today_js = (ROOT / "static/js/admin/features/today.render.js").read_text("utf-8")

    _assert_unit(
        "return await api.getStrict(url, label);" in state_js,
        "admin bootstrap strict helper must use the admin API wrapper",
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

    for snippet in [
        "const dateKey = rowDateKey(tr);",
        "await patchArriveTimeRemote(dateKey, sid, txt);",
        "await setLeaveTimeRemote(dateKey, sid, txt);",
        "await patchFlagRemote('att', dateKey, sid, checked);",
        "await patchFlagRemote('contact', dateKey, sid, checked);",
        "targets.push({ dateKey, sid });",
        "await patchLog(target.dateKey, target.sid, {",
        "const absenceSlots = rowSlotsForAbsence(dateKey, sid, tr);",
        "setAttended(dateKey, sid, false);",
        "setContacted(dateKey, sid, false);",
    ]:
        _assert_unit(snippet in today_js, f"today row-date action path must preserve row date source: {snippet}")


def run_admin_api_wrapper_usage_source_checks() -> None:
    shared_api_js = (ROOT / "static/js/shared/api.js").read_text("utf-8")
    admin_api_js = (ROOT / "static/js/admin/core/api.js").read_text("utf-8")
    state_js = (ROOT / "static/js/admin/core/state.js").read_text("utf-8")

    _assert_unit(
        "export async function fetchJsonChecked(url, label = 'request', init = {})" in shared_api_js,
        "shared API helper must expose strict JSON fetch with request labels",
    )
    _assert_unit(
        "await ensureOk(response, label);" in shared_api_js,
        "strict shared JSON helper must preserve ensureOk error labels",
    )
    _assert_unit(
        "import { fetchJson, fetchJsonChecked, fetchJsonOr, sendJson } from '../../shared/api.js';" in admin_api_js,
        "admin API wrapper must import the strict JSON helper",
    )
    _assert_unit(
        "getStrict: (url, label, init) => fetchJsonChecked(url, label, init)," in admin_api_js,
        "admin API wrapper must expose api.getStrict",
    )
    _assert_unit(
        "import { ensureOk } from '../../shared/api.js';" not in state_js,
        "admin bootstrap should consume strict JSON through core/api.js, not direct shared imports",
    )
    _assert_unit(
        "const response = await fetch(url);" not in state_js,
        "admin bootstrap should not open-code critical JSON fetch",
    )
    _assert_unit(
        "return await api.getStrict(url, label);" in state_js,
        "admin bootstrap critical helper must delegate to api.getStrict",
    )


def run_admin_progress_batch_source_checks() -> None:
    today_js = (ROOT / "static/js/admin/features/today.js").read_text("utf-8")
    export_logs_js = (ROOT / "static/js/admin/features/exportLogs.js").read_text("utf-8")

    batch_start = today_js.index("async function loadProgressHistoryForSidBatch")
    batch_end = today_js.index("async function ensureProgressHistoryForSids", batch_start)
    today_batch_block = today_js[batch_start:batch_end]
    _assert_unit(
        "new URLSearchParams({ sids: chunk.join(',') })" in today_batch_block,
        "today progress history batch loader must request /api/progress with sids",
    )
    _assert_unit(
        "mergeDateSidMap(state.progress, data);" in today_batch_block,
        "today progress history batch loader must merge date/sid maps without replacing all progress",
    )

    ensure_start = today_js.index("async function ensureProgressHistoryForSids")
    ensure_end = today_js.index("async function refreshStudentsIfNeeded", ensure_start)
    ensure_block = today_js[ensure_start:ensure_end]
    _assert_unit(
        "const loadedBatch = await loadProgressHistoryForSidBatch(pending);" in ensure_block,
        "today progress history must try batch loading before full-history fallback",
    )
    _assert_unit(
        ensure_block.index("loadProgressHistoryForSidBatch(pending)") < ensure_block.index("loadAllProgressHistoryOnce"),
        "today progress history full-load fallback must remain after the batch attempt",
    )

    roster_start = export_logs_js.index("async function ensureRosterProgressHistory")
    roster_end = export_logs_js.index("async function exportRosterCsv", roster_start)
    roster_block = export_logs_js[roster_start:roster_end]
    _assert_unit(
        "new URLSearchParams({ sids: chunk.join(',') })" in roster_block,
        "roster export progress history must use batch sids loading",
    )
    _assert_unit(
        "fetch(`/api/progress?sid=${encodeURIComponent(sid)}`" in roster_block,
        "roster export progress history must preserve single-sid fallback on batch failure",
    )


def run_all_page_progress_lazy_source_checks() -> None:
    state_js = (ROOT / "static/js/all/core/state.js").read_text("utf-8")
    table_js = (ROOT / "static/js/all/features/table.js").read_text("utf-8")
    hover_js = (ROOT / "static/js/all/features/hoverTooltip.js").read_text("utf-8")

    load_all_start = state_js.index("export async function loadAll()")
    load_all_end = state_js.index("export async function ensureProgressForSid", load_all_start)
    load_all_block = state_js[load_all_start:load_all_end]
    _assert_unit(
        "/api/progress" not in load_all_block,
        "all-students bootstrap must not download full progress history",
    )
    _assert_unit(
        "getJSONOr('/api/progress'" not in state_js and 'getJSONOr("/api/progress"' not in state_js,
        "all-students state must not keep a full-progress fallback",
    )
    _assert_unit(
        "export async function ensureProgressForSid" in state_js,
        "all-students state must expose lazy per-student progress loading",
    )
    _assert_unit(
        "new URLSearchParams({ sid: key })" in state_js,
        "lazy all-students progress loading must request one sid",
    )
    _assert_unit(
        "mergeDateSidMap(state.progress || {}, progress)" in state_js,
        "lazy all-students progress loading must merge without replacing existing progress",
    )

    _assert_unit(
        "import { ensureProgressForSid, state } from '../core/state.js';" in table_js,
        "all-students mini progress popup must import lazy progress loading",
    )
    _assert_unit(
        "await ensureProgressForSid(sid);" in table_js,
        "all-students mini progress popup must load progress for the selected sid",
    )
    _assert_unit(
        "import { ensureProgressForSid } from '../core/state.js';" in hover_js,
        "all-students hover tooltip must import lazy progress loading",
    )
    _assert_unit(
        "await ensureProgressForSid(stu.id);" in hover_js,
        "all-students hover tooltip must load progress for the hovered student",
    )


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
  getItem: (key) => key === 'adminSelectedDate' ? '2026-06-07' : null,
  setItem: () => {},
};
globalThis.localStorage = {
  _values: new Map(),
  getItem(key) {
    return this._values.has(key) ? this._values.get(key) : null;
  },
  setItem(key, value) {
    this._values.set(key, String(value));
  },
  removeItem(key) {
    this._values.delete(key);
  },
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
    if (selector === 'tr[data-sid]') return tr;
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

const contactCalls = [];
const makeRow = (dataset) => ({
  dataset: { ...dataset },
  classList: { toggle: () => {} },
  querySelector: () => null,
});
const makeContactToggle = (row) => ({
  checked: true,
  closest(selector) {
    if (selector === '.contactChk') return this;
    if (selector === 'tr[data-sid]') return row;
    if (selector === 'tr[data-sid][data-date]') {
      return Object.prototype.hasOwnProperty.call(row.dataset, 'date') ? row : null;
    }
    if (selector === '.c') return { dataset: {} };
    return null;
  },
});
globalThis.fetch = async (url, init = {}) => {
  if (String(url) === '/api/contact/patch') {
    contactCalls.push(JSON.parse(String(init.body || '{}')));
    return response({ ok: true });
  }
  return response(payloadFor(url));
};

await host._listeners.change({
  target: makeContactToggle(makeRow({ sid: 's2', date: '2026-06-05', contact: '' })),
});
let lastContactCall = contactCalls[contactCalls.length - 1];
ok(lastContactCall?.date === '2026-06-05', 'contact save uses row date before selected admin date');
ok(lastContactCall?.sid === 's2', 'contact save uses row sid');

await host._listeners.change({
  target: makeContactToggle(makeRow({ sid: 's3', contact: '' })),
});
lastContactCall = contactCalls[contactCalls.length - 1];
ok(lastContactCall?.date === '2026-06-07', 'contact save falls back to selected admin date only when row date is missing');
ok(lastContactCall?.sid === 's3', 'contact fallback save still uses row sid');
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
    _assert_unit(
        "function nextExcludedStatusOf" in test_modal_js,
        "test assignment modal must define a right-click none/제외 toggle helper",
    )
    _assert_unit(
        "dragTarget = dragButton === 2 ? nextExcludedStatusOf(startStatus) : nextStatusOf(startStatus);" in test_modal_js,
        "right-drag must toggle rows between none and 제외 instead of forcing 제외",
    )
    _assert_unit(
        "applyTestRowStatus(row, nextExcludedStatusOf(statusForKey(key)))" in test_modal_js,
        "right-click must toggle 제외 back to none",
    )


def run_admin_test_modal_persistence_bridge_source_checks() -> None:
    test_modal_js = (ROOT / "static/js/admin/features/testModal.js").read_text("utf-8")
    bridge_start = test_modal_js.find("function buildLogAssignmentPatchBody")
    _assert_unit(
        bridge_start >= 0,
        "test modal save must define a persistence bridge before saveModal",
    )
    bridge_end = test_modal_js.index("function bindEventsOnce", bridge_start)
    bridge_block = test_modal_js[bridge_start:bridge_end]
    save_start = test_modal_js.index("async function saveModal")
    save_end = test_modal_js.index("function bindEventsOnce", save_start)
    save_block = test_modal_js[save_start:save_end]

    required_helpers = [
        "function collectTestStatusPatch",
        "function hasAnyAssignedTestStatus",
        "function ensureProgressEntryForTestSave",
        "function buildTestProgressPatchBody",
        "function applyTestProgressPatchResult",
        "function buildLogAssignmentPatchBody",
    ]
    for helper in required_helpers:
        _assert_unit(helper in bridge_block, f"test modal persistence bridge must define {helper}")

    _assert_unit(
        "body: JSON.stringify(buildTestProgressPatchBody(editingDate, editingSid, patchTests, hasAnyTestStatus))"
        in save_block,
        "test modal save must build /api/progress/patch body through the persistence bridge",
    )
    _assert_unit(
        "const body = buildLogAssignmentPatchBody(editingDate, editingSid, patchEntry, clear, entry, notesChanged)"
        in bridge_block,
        "test modal log metadata patch must use a dedicated payload bridge",
    )
    _assert_unit(
        "applyTestProgressPatchResult(editingDate, editingSid, progressRes)" in save_block,
        "test modal save must apply progress patch results through the persistence bridge",
    )


def run_admin_test_modal_assignment_behavior_checks() -> None:
    driver = r"""
import fs from 'node:fs';
import path from 'node:path';

Error.stackTraceLimit = 0;

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
export {
  patchLogAssignment as __patchLogAssignment,
  saveModal as __saveModal,
  nextStatusOf as __nextStatusOf,
  nextExcludedStatusOf as __nextExcludedStatusOf,
};
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
	ok(mod.__nextStatusOf('') === 'assigned', 'left-click none becomes 배정/assigned');
	ok(mod.__nextStatusOf('assigned') === 'interrupted', 'left-click 배정/assigned becomes 배부/interrupted');
	ok(mod.__nextStatusOf('interrupted') === 'done', 'left-click 배부/interrupted becomes 완료/done');
	ok(mod.__nextStatusOf('done') === '', 'left-click 완료/done becomes none');
	ok(mod.__nextStatusOf('skip') === 'assigned', 'left-click 제외/skip returns to the normal 배정 cycle');
	ok(mod.__nextExcludedStatusOf('') === 'skip', 'right-click none becomes 제외/skip');
	ok(mod.__nextExcludedStatusOf('skip') === '', 'right-click 제외/skip becomes none');
	ok(mod.__nextExcludedStatusOf('assigned') === 'skip', 'right-click assigned enters 제외/skip');
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
    { label: existingLabel, name: '기존', status: 'interrupted', source: 'latest-entry' },
  ],
  assignedTests: [
    { label: existingLabel, name: '기존', status: 'interrupted' },
  ],
};
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url).startsWith('/api/logs/entry?')) return response({ ok: true, entry: latestEntry });
  if (String(url) === '/api/progress/patch') return response({ progress: { tests: { [existingLabel]: 'interrupted', [newLabel]: 'interrupted' } } });
  if (String(url) === '/api/logs/patch') return response({ entry: { saved: true } });
  return response({});
};
mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeCatalog: [existingTest, newTest],
  initialTestMap: { [existingLabel]: 'interrupted' },
  selectedStatuses: [[existingLabel, 'interrupted'], [newLabel, 'interrupted']],
});
await mod.__saveModal({ showPopup: false, refresh: false });
const entryIndex = calls.findIndex(call => call.url.startsWith('/api/logs/entry?'));
const progressIndex = calls.findIndex(call => call.url === '/api/progress/patch');
const progressPatch = calls.find(call => call.url === '/api/progress/patch');
const logPatch = calls.find(call => call.url === '/api/logs/patch');
ok(entryIndex >= 0 && progressIndex >= 0 && entryIndex < progressIndex, 'latest log read precedes progress patch');
ok(progressPatch.body?.date === '2026-06-05', 'progress patch keeps date payload');
ok(progressPatch.body?.sid === 's1', 'progress patch keeps sid payload');
ok(progressPatch.body?.progress?.tests?.[existingLabel] === 'interrupted', 'progress patch preserves existing test authority');
ok(progressPatch.body?.progress?.tests?.[newLabel] === 'interrupted', 'progress patch writes new test authority');
ok(progressPatch.body?.progress?.__testsClearedAt === '', 'active progress patch does not set clear marker');
ok(logPatch, '/api/logs/patch is called after successful latest log read');
ok(logPatch.body?.date === '2026-06-05', 'log patch keeps date payload');
ok(logPatch.body?.sid === 's1', 'log patch keeps sid payload');
ok(Array.isArray(logPatch.body?.entry?.assignedTests) && logPatch.body.entry.assignedTests.length === 2, 'assignedTests remain in log patch');
ok(!Object.prototype.hasOwnProperty.call(logPatch.body?.entry || {}, 'tests'), 'log patch does not write authoritative tests');
const dailyItems = logPatch.body?.entry?.testAssignmentDailyTests || [];
ok(Array.isArray(dailyItems) && dailyItems.length === 2, 'daily assignment metadata keeps latest entry and new distribution');
ok(dailyItems.some(item => item.label === existingLabel && item.source === 'latest-entry'), 'existing daily metadata comes from latest entry');
ok(dailyItems.some(item => item.label === newLabel), 'new daily distribution metadata is appended');
ok(String(logPatch.body?.entry?.testAssignmentNote || '').includes('기존'), 'assignment note includes existing item');
ok(String(logPatch.body?.entry?.testAssignmentNote || '').includes('신규'), 'assignment note includes new item');
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
        "body: JSON.stringify(buildVideoAssignmentPatchBody(today, sid, selected, source))",
        "fetch('/api/updates', { cache: 'no-store' })",
        "body.base = { notes: prevNotes.trim() };",
    ]:
        _assert_unit(snippet in save_block or snippet in patch_block, f"video assignment source shape must remain: {snippet}")
    for snippet in [
        "function latestAutoAssignStatusForSid",
        "function applyWatchStatusForAutoAssign",
        "function blockedMidsForAutoAssign",
        "function shouldClearCompletedAutoAssignment",
        "function resolveVideoAssignmentSaveSource",
        "options.forceEmpty === true",
        "function applyVideoAssignmentState",
        "function buildVideoAssignmentPatchBody",
        "return { date: day, sid, entry: { videos: selected, source } };",
        "return { date: day, sid, remove: true };",
        "activeAssignmentManual = source === 'manual';",
    ]:
        _assert_unit(snippet in video_modal_js, f"video assignment policy helper must remain: {snippet}")


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


def run_admin_video_modal_assignment_policy_behavior_checks() -> None:
    driver = r"""
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

Error.stackTraceLimit = 0;

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
  focus: () => {},
  querySelector: () => null,
  querySelectorAll: () => [],
  closest: () => null,
  getBoundingClientRect: () => ({ top: 0, height: 100 }),
});
const ensureElement = (id) => globalThis.__elements[id] || (globalThis.__elements[id] = makeElement(id));
const installVideoElements = () => {
  for (const id of ['vidModal', 'mTitle', 'chkZone', 'mSave', 'vidSavePopup', 'autoAssignCountToggle', 'autoAssignCountLabel']) {
    ensureElement(id);
  }
};
const makeRow = (sid = '007', date = '2026-06-06') => ({
  dataset: { sid, date },
  closest(selector) {
    return selector === 'tr[data-sid]' ? this : null;
  },
});
const selectedCheckboxes = () => globalThis.__checkboxes.filter((checkbox) => checkbox.checked);

globalThis.window = globalThis;
window.addEventListener = () => {};
window.visualViewport = { addEventListener: () => {} };
window.devicePixelRatio = 1;
window.innerWidth = 1280;
window.innerHeight = 900;
window.setTimeout = () => 1;
window.clearTimeout = () => {};
globalThis.requestAnimationFrame = (callback) => callback();
globalThis.alert = (message) => globalThis.__alerts.push(String(message));
globalThis.__adminDate = '2026-06-07';
globalThis.__alerts = [];
globalThis.__toasts = [];
globalThis.__dispatches = [];
globalThis.__checkboxes = [];
globalThis.__elements = {};
globalThis.__state = {
  students: [],
  videos: [],
  updates: {},
  logs: {},
  progress: {},
  extra: {},
  absentByDate: {},
};
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};
globalThis.document = {
  documentElement: { style: { setProperty: () => {} } },
  head: {
    appendChild(el) {
      if (el?.id) globalThis.__elements[el.id] = el;
    },
  },
  body: {
    appendChild(el) {
      if (el?.id) globalThis.__elements[el.id] = el;
    },
    insertAdjacentHTML: () => installVideoElements(),
    addEventListener: () => {},
  },
  createElement: (tag) => ({ ...makeElement(tag), tagName: String(tag).toUpperCase() }),
  getElementById: (id) => globalThis.__elements[id] || null,
  querySelector: (selector) => {
    if (selector === '#chkZone input[type="checkbox"]:checked') return selectedCheckboxes()[0] || null;
    if (selector === '#chkZone') return globalThis.__elements.chkZone || null;
    return null;
  },
  querySelectorAll: (selector) => {
    if (selector === '#chkZone input[type="checkbox"]:checked') return selectedCheckboxes();
    if (selector === '#chkZone input[type="checkbox"]') return globalThis.__checkboxes;
    return [];
  },
  addEventListener: () => {},
  dispatchEvent: (event) => globalThis.__dispatches.push(event.type),
};
installVideoElements();

const sourcePath = path.join(process.cwd(), 'static/js/admin/features/videoModal.js');
let source = fs.readFileSync(sourcePath, 'utf8')
  .replace("import { $, CT, toast } from '../core/utils.js';", "const CT = { 'Content-Type': 'application/json' }; const $ = (id) => globalThis.__elements?.[id] || null; const toast = (msg) => globalThis.__toasts.push(String(msg));")
  .replace("import { state } from '../core/state.js';", "const state = globalThis.__state;")
  .replace("import { getAdminDate } from '../core/adminDate.js';", "const getAdminDate = () => globalThis.__adminDate || '2026-06-07';")
  .replace("import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from '../../shared/search.js';", "const applySearchPlaceholder = () => {}; const matchesSearchKey = () => true; const searchKeyForText = (value) => String(value || '').toLowerCase();");
const harness = `
export function __initHarness() {
  initVideoModal();
}
export function __setHarnessState(input) {
  editingSid = input.sid || '007';
  editingVideoDate = input.date || '2026-06-06';
  activeVideoSelectionDirty = input.dirty === true;
  activeAssignmentManual = input.assignmentManual === true;
  activePrimaryVideoMids = new Set((input.primaryVideoMids || []).map(String));
  activeVideoList = input.activeVideoList || [];
  activeBlockedMids = input.activeBlockedMids || {};
  activeAllowAutoAssign = input.allowAutoAssign === true;
  activeAutoGenerated = input.autoGenerated === true;
  activeExtraVideoSearchOpen = false;
  activeExtraSubject = '';
  activeExtraSubCurriculum = '';
  activeExtraQuery = '';
  activeVideoNoteHtml = '';
  state.students = input.students || [];
  state.videos = input.videos || [];
  state.updates = input.updates || {};
  state.logs = input.logs || {};
  state.progress = input.progress || {};
  state.extra = input.extra || {};
  state.absentByDate = input.absentByDate || {};
}
export async function __openHarness(row) {
  if (typeof window.openVideoAssignmentPopupForRow !== 'function') throw new Error('open harness not installed');
  return window.openVideoAssignmentPopupForRow(row);
}
export async function __saveHarness(options = {}) {
  if (typeof window.saveVideoAssignmentPopup !== 'function') throw new Error('save harness not installed');
  return window.saveVideoAssignmentPopup(options);
}
`;
const moduleDir = fs.mkdtempSync(path.join(os.tmpdir(), 'video-modal-assignment-policy-'));
const modulePath = path.join(moduleDir, 'videoModal-harness.mjs');
fs.writeFileSync(modulePath, `${source}\n${harness}`, 'utf8');
let mod;
try {
  mod = await import(pathToFileURL(modulePath).href);
} finally {
  try { fs.rmSync(moduleDir, { recursive: true, force: true }); } catch {}
}
mod.__initHarness();

const students = [{ id: '007', name: '학생7', curriculum: 'ALG', subCurriculum: 'BASE', day1: '토 13:00' }];
const videos = [
  { mid: 'm1', title: '일차함수', chapter: '1', curriculum: 'ALG', subCurriculum: 'BASE' },
  { mid: 'm2', title: '이차함수', chapter: '2', curriculum: 'ALG', subCurriculum: 'BASE' },
  { mid: 'extra-1', title: '확장 영상', chapter: '7', curriculum: 'ALG', subCurriculum: 'EXTRA' },
];

let calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  const value = String(url);
  if (value === '/api/updates') {
    return response({ ok: true, updates: { '2026-06-06': { '007': { videos: ['m1'], source: 'manual' } } } });
  }
  if (value.startsWith('/api/logs/entry?')) return response({ ok: true, entry: {} });
  if (value === '/api/extra-attend') return response({ ok: true, extra: { '2026-06-06': [] } });
  if (value.startsWith('/api/watch/latest?')) return response({ ok: true, watch: { m2: { last: 100, dur: 100, completed: true } } });
  if (value === '/api/updates/patch') return response({ ok: true });
  return response({ ok: true });
};
mod.__setHarnessState({
  sid: '007',
  date: '2026-06-06',
  students,
  videos,
  updates: {},
  progress: { '2026-06-06': { '007': { m1: 'done', m2: 'skip' } } },
});
await mod.__openHarness(makeRow());
const openHtml = globalThis.__elements.chkZone.innerHTML;
ok(openHtml.includes('value="m1" checked'), 'manual assignment remains checked when course progress is complete');
ok(!calls.some((call) => call.url === '/api/updates/patch'), 'manual completed assignment open must not auto-overwrite updates');

calls = [];
globalThis.__checkboxes = [{ value: 'extra-1', checked: true }];
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  const value = String(url);
  if (value.startsWith('/api/logs/entry?')) {
    return response({ ok: true, entry: { notes: '상담 유지', extraVideoAssignmentNote: '', assignedExtraVideos: [] } });
  }
  if (value === '/api/updates/patch') return response({ ok: true });
  if (value === '/api/updates') {
    return response({ ok: true, updates: { '2026-06-06': { '007': { videos: ['extra-1'], source: 'manual' } } } });
  }
  if (value === '/api/logs/patch') return response({ ok: true, entry: { saved: true } });
  return response({ ok: true });
};
mod.__setHarnessState({
  sid: '007',
  date: '2026-06-06',
  dirty: false,
  assignmentManual: true,
  primaryVideoMids: ['m1', 'm2'],
  students,
  videos,
});
await mod.__saveHarness({ showPopup: false, refresh: false });
let latestRead = calls.find((call) => call.url.startsWith('/api/logs/entry?'));
let latestParams = new URLSearchParams(latestRead.url.split('?')[1]);
let updatesPatch = calls.find((call) => call.url === '/api/updates/patch');
ok(latestParams.get('date') === '2026-06-06', 'latest log preflight uses editingVideoDate before selected admin date');
ok(latestParams.get('sid') === '007', 'latest log preflight uses editing sid');
ok(updatesPatch.body?.date === '2026-06-06', 'manual save uses editingVideoDate before selected admin date');
ok(updatesPatch.body?.sid === '007', 'manual save keeps sid');
ok(updatesPatch.body?.entry?.source === 'manual', 'manual save preserves manual source');
ok(updatesPatch.body?.entry?.videos?.[0] === 'extra-1', 'manual save keeps selected video');

calls = [];
globalThis.__checkboxes = [{ value: 'm1', checked: true }];
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  const value = String(url);
  if (value.startsWith('/api/logs/entry?')) return response({ ok: true, entry: {} });
  if (value === '/api/updates/patch') return response({ ok: true });
  if (value === '/api/updates') {
    return response({ ok: true, updates: { '2026-06-06': { '007': { videos: [], source: 'manual' } } } });
  }
  if (value === '/api/logs/patch') return response({ ok: true, entry: { saved: true } });
  return response({ ok: true });
};
mod.__setHarnessState({
  sid: '007',
  date: '2026-06-06',
  dirty: false,
  assignmentManual: false,
  primaryVideoMids: ['m1', 'm2'],
  students,
  videos,
  updates: { '2026-06-06': { '007': { videos: ['m1'], source: 'auto' } } },
});
await mod.__saveHarness({ showPopup: false, refresh: false, forceEmpty: true });
updatesPatch = calls.find((call) => call.url === '/api/updates/patch');
ok(updatesPatch.body?.date === '2026-06-06', 'force-empty save uses editingVideoDate');
ok(updatesPatch.body?.sid === '007', 'force-empty save keeps sid');
ok(Array.isArray(updatesPatch.body?.entry?.videos), 'force-empty save sends an explicit videos array');
ok(updatesPatch.body.entry.videos.length === 0, 'force-empty save sends an empty videos array');
ok(updatesPatch.body.entry.source === 'manual', 'force-empty save records a manual clear so auto assignment does not resurrect it');
ok(!Object.prototype.hasOwnProperty.call(updatesPatch.body, 'remove'), 'force-empty save must not use remove:true');

console.log('videoModal assignment policy PASS');
"""
    cmd = ["node", "--input-type=module", "-e", driver]
    print("$ node --input-type=module -e <admin-video-modal-assignment-policy-driver>")
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin video modal assignment policy driver failed")


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


def run_admin_log_modal_save_policy_source_checks() -> None:
    log_modal_js = (ROOT / "static/js/admin/features/logModal.js").read_text("utf-8")
    save_start = log_modal_js.index("async function saveBase")
    save_end = log_modal_js.index("async function saveRecordPopupForCurrent", save_start)
    save_block = log_modal_js[save_start:save_end]

    save_snippets = [
        "const changedProg = collectChangedProgressPatch();",
        "await saveChangedProgressPatch(today, sid, changedProg);",
        "const oldTotal = collectPriorProgressByMid(today, sid);",
        "const summary = summarizeProgressPatch(changedProg, oldTotal);",
        "const { entry, clearKeys, base, contentChanged } = buildLogSavePatch",
        "contentChanged ? { base } : {}",
        "await patchLogEntry(today, sid, entry, clearKeys",
        "applyLogSaveResult({ date: today, sid, entry, clearKeys, returned, doneFlag, prevDone });",
        "setLogModalSnapshots(notesNow, hwRows);",
    ]
    for snippet in save_snippets:
        _assert_unit(snippet in save_block, f"logModal save policy must keep merge-safe step: {snippet}")

    for snippet in [
        "async function saveChangedProgressPatch(date, sid, changedProg)",
        "await patchProgressEntry(date, sid, changedProg)",
        "function buildLogSavePatch",
        "clearKeys.push('notes')",
        "clearKeys.push('homework', 'homeworkTable')",
        "function applyLogSaveResult",
        "if (!doneFlag && prevDone) next.done = true",
        "function setLogModalSnapshots",
    ]:
        _assert_unit(snippet in log_modal_js, f"logModal helper policy must keep merge-safe step: {snippet}")


def run_admin_log_modal_save_policy_behavior_checks() -> None:
    driver = r"""
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

Error.stackTraceLimit = 0;

const ok = (condition, message) => {
  if (!condition) throw new Error(message);
};
const response = (payload, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => payload,
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
  append: () => {},
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
  globalThis.__elements.hwBody.querySelectorAll = (selector) => selector === '.hwItem' ? globalThis.__hwItems : [];
};
globalThis.__installModalElements = installModalElements;

globalThis.window = globalThis;
window.addEventListener = () => {};
window.hideStudentTooltip = () => {};
window.hideStudentPopupBackdrop = () => {};
globalThis.__elements = {};
globalThis.__toasts = [];
globalThis.__alerts = [];
globalThis.__dispatches = [];
globalThis.__progressCells = [];
globalThis.__hwItems = [];
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
    if (selector === '#logProgress .progress-cell[data-mid]') return globalThis.__progressCells;
    if (selector === '#logProgress .progress-cell') return globalThis.__progressCells;
    if (selector === '#hwBody .hwBook') return [];
    return [];
  },
  addEventListener: () => {},
  dispatchEvent: (event) => globalThis.__dispatches.push(event.type),
};

const makeProgressCell = ({ mid, initial, state, explicitNone = '', cleared = '' }) => ({
  dataset: {
    mid: String(mid),
    initial: String(initial),
    state: String(state),
    explicitNone,
    cleared,
  },
});

const sourcePath = path.join(process.cwd(), 'static/js/admin/features/logModal.js');
let source = fs.readFileSync(sourcePath, 'utf8')
  .replace("import { $, toast, postJSON } from '../core/utils.js';", "const $ = (id) => globalThis.__elements?.[id] || null; const toast = (msg) => globalThis.__toasts.push(String(msg)); const postJSON = async () => ({});")
  .replace("import { state } from '../core/state.js';", "const state = globalThis.__state;")
  .replace("import { getAdminDate } from '../core/adminDate.js';", "const getAdminDate = () => globalThis.__adminDate || '2026-06-06';")
  .replace("import { initTestModal } from './testModal.js';", "const initTestModal = () => {};");
const harness = `
export function __initHarness() {
  globalThis.__installModalElements();
  initLogModal();
}
export function __setHarnessState(input) {
  editingLogDate = input.date || '2026-06-06';
  editingLogSid = input.sid || 's1';
  logModalReady = true;
  logModalCarriedTestAssignment = input.carried || null;
  logModalSnapshot = input.snapshot || { notes: '', homeworkTable: [] };
  logModalServerSnapshot = input.serverSnapshot || { notes: '', homeworkTable: [] };
  state.logs = input.logs || {};
  state.progress = input.progress || {};
  state.videos = input.videos || [];
  globalThis.__progressCells = input.progressCells || [];
  globalThis.__hwItems = input.hwItems || [];
  if ($('logNotes')) $('logNotes').value = input.notesValue || '';
}
export async function __saveHarness() {
  if (typeof window.saveRecordPopup !== 'function') throw new Error('save harness not installed');
  return await window.saveRecordPopup();
}
`;
const moduleDir = fs.mkdtempSync(path.join(os.tmpdir(), 'log-modal-save-policy-'));
const modulePath = path.join(moduleDir, 'logModal-harness.mjs');
fs.writeFileSync(modulePath, `${source}\n${harness}`, 'utf8');
let mod;
try {
  mod = await import(pathToFileURL(modulePath).href);
} catch (err) {
  console.error(`module import threw: ${err?.message || err}`);
  throw err;
} finally {
  try { fs.rmSync(moduleDir, { recursive: true, force: true }); } catch {}
}
mod.__initHarness();

let calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  const value = String(url);
  if (value === '/api/progress/patch') {
    return response({ ok: true, progress: { m1: 'none', __manualProgressMids: { m1: true } } });
  }
  if (value === '/api/logs/patch') return response({ ok: true, entry: { saved: true } });
  if (value === '/api/updates/patch') return response({ ok: true });
  return response({ ok: true });
};
mod.__setHarnessState({
  date: '2026-06-06',
  sid: 's1',
  notesValue: 'keep notes',
  snapshot: { notes: 'keep notes', homeworkTable: [] },
  serverSnapshot: { notes: 'keep notes', homeworkTable: [] },
  progress: { '2026-06-06': { s1: { m1: 'done' } } },
  videos: [{ mid: 'm1', chapter: 1 }],
  progressCells: [makeProgressCell({ mid: 'm1', initial: 'done', state: 'none', explicitNone: '1', cleared: '1' })],
});
try {
  await mod.__saveHarness();
} catch (err) {
  console.error(`manual-white save threw: ${err?.message || err}`);
  process.exit(1);
}
const progressPatch = calls.find((call) => call.url === '/api/progress/patch');
ok(progressPatch, 'manual white save must call /api/progress/patch');
ok(progressPatch.body?.date === '2026-06-06', 'progress patch keeps date');
ok(progressPatch.body?.sid === 's1', 'progress patch keeps sid');
ok(progressPatch.body?.progress?.m1 === 'none', 'manual white is persisted as none');
ok(!calls.some((call) => call.url === '/api/logs/patch'), 'unchanged notes/homework do not call /api/logs/patch');
ok(globalThis.__state.progress['2026-06-06'].s1.m1 === 'none', 'returned manual white progress updates local state');
ok(globalThis.__state.progress['2026-06-06'].s1.__manualProgressMids?.m1 === true, 'returned manual meta is preserved locally');

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  const value = String(url);
  if (value === '/api/logs/patch') return response({ ok: true, entry: { saved: true } });
  if (value === '/api/progress/patch') return response({ ok: true, progress: {} });
  return response({ ok: true });
};
mod.__setHarnessState({
  date: '2026-06-06',
  sid: 's1',
  notesValue: '',
  snapshot: { notes: 'server keep', homeworkTable: [] },
  serverSnapshot: { notes: 'server keep', homeworkTable: [] },
  progress: { '2026-06-06': { s1: {} } },
  videos: [],
  progressCells: [],
});
try {
  await mod.__saveHarness();
} catch (err) {
  console.error(`blank-notes save threw: ${err?.message || err}`);
  process.exit(1);
}
const logPatch = calls.find((call) => call.url === '/api/logs/patch');
ok(logPatch, 'blank changed notes must call /api/logs/patch');
ok(logPatch.body?.date === '2026-06-06', 'log patch keeps date');
ok(logPatch.body?.sid === 's1', 'log patch keeps sid');
ok(Array.isArray(logPatch.body?.__clear), 'blank changed notes use explicit __clear');
ok(logPatch.body.__clear.includes('notes'), 'blank changed notes explicitly clear notes');
ok(!Object.prototype.hasOwnProperty.call(logPatch.body?.entry || {}, 'notes'), 'blank changed notes do not send notes empty string');
ok(logPatch.body?.base?.notes === 'server keep', 'blank changed notes include latest server base');

console.log('logModal save policy PASS');
"""
    cmd = ["node", "--input-type=module", "-e", driver]
    print("$ node --input-type=module -e <admin-log-modal-save-policy-driver>")
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin log modal save policy driver failed")


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

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && !init.method) return response({});
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return response({ ok: true });
  if (String(url) === '/api/today_order' && !init.method) return response({});
  if (String(url) === '/api/today_order' && init.method === 'POST') return response({ ok: true });
  return response({});
};
const stateSlot3Save = await loadStateModule('weekend-slot3-save');
await stateSlot3Save.saveWeekendSlotsFromLabel('s1', '토3', '2026-06-06');
const weekendPost3 = calls.find(call => call.url === '/api/weekend-slots' && call.method === 'POST');
ok(weekendPost3.body['2026-06-06'].s1[0] === 3, 'weekend slot label save keeps slot 3');

globalThis.__state.students = [{ id: 's1', day1: '토1', day2: '토2' }];
const stateLabelSpace = await loadStateModule('weekend-label-space');
ok(stateLabelSpace.labelFor('2026-06-06', 's1') === '토1 토2', 'combined slot label uses user-facing space separator');

calls = [];
globalThis.__state = {
  students: [{ id: 's1', day1: '토' }],
  extra: {},
  logs: {},
  absentSlotsByDate: {},
};
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && !init.method) return response({ '2026-06-06': { s1: [3] } });
  return response({});
};
const stateSlot3Label = await loadStateModule('weekend-slot3-label');
await stateSlot3Label.loadWeekendSlots();
ok(stateSlot3Label.labelFor('2026-06-06', 's1') === '토3', 'weekend slot 3 remains visible in labels');
ok(globalThis.__state.weekendSlots?.['2026-06-06']?.s1?.[0] === 3, 'loadWeekendSlots publishes state.weekendSlots');
ok(globalThis.window.weekendSlots?.['2026-06-06']?.s1?.[0] === 3, 'loadWeekendSlots publishes window.weekendSlots');

calls = [];
globalThis.__state = {
  students: [{ id: 's1', day1: '토' }],
  extra: { '2026-06-06': ['s1'] },
  logs: {},
  absentSlotsByDate: { '2026-06-06': { s1: [1, 2] } },
};
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && !init.method) return response({ '2026-06-06': { s1: [1] } });
  return response({});
};
const stateExtraAbsentSlot = await loadStateModule('weekend-extra-absent-visible');
await stateExtraAbsentSlot.loadWeekendSlots();
ok(
  stateExtraAbsentSlot.labelFor('2026-06-06', 's1') === '토1',
  'extra attendance saved slot label remains visible despite same-day absent slots',
);

const loadRenderModule = async () => {
  const sourcePath = path.join(process.cwd(), 'static/js/admin/features/today.render.js');
  const source = fs.readFileSync(sourcePath, 'utf8')
    .replace("import { $, toast } from '../core/utils.js';", "const $ = (id) => globalThis.__elements?.[id] || null; const toast = (msg) => globalThis.__toasts.push(String(msg));")
    .replace("import { getAdminDate, getRealToday } from '../core/adminDate.js';", "const getAdminDate = () => '2026-06-06'; const getRealToday = () => '2026-06-06';")
    .replace("import { state } from '../core/state.js';", "const state = globalThis.__state;")
    .replace(/import \{[\s\S]*?\}\s+from '\.\/today\.state\.js';/, `const yoilOf = () => '토';
const labelFor = () => '토1';
const plannedTimeFor = () => '';
const plannedTimeBase = () => '13:00';
const getArriveOverride = () => '';
const setArriveOverride = (...args) => globalThis.__arriveOverrides.push(args);
const parseSlotsFromText = (txt) => Array.from(new Set((String(txt || '').match(/[1-3]/g) || []).map(n => parseInt(n, 10))));
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
globalThis.__elements = { todayWrap: host };
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
    if (selector === 'tr[data-sid]') return tr;
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

const doneHost = {
  _listeners: {},
  _html: '',
  set innerHTML(value) { this._html = String(value); },
  get innerHTML() { return this._html; },
  addEventListener(type, callback) {
    (this._listeners[type] ||= []).push(callback);
  },
};
globalThis.__elements.doneWrap = doneHost;
globalThis.__state.students = [
  { id: 's1', name: '김주말', curriculum: '공통수학', subCurriculum: '', school: '토요고' },
];
globalThis.__saveWeekendSlotsCalls = [];
globalThis.__saveWeekendSlotsFromLabel = async (...args) => {
  globalThis.__saveWeekendSlotsCalls.push(args);
};
renderModule.renderDone([['s1', { done: true }, '2026-06-06']]);
ok(doneHost.innerHTML.includes('class="slotLabel"'), 'done slot label renders with editable marker');
ok(doneHost.innerHTML.includes('contenteditable="true"'), 'done slot label is contenteditable');
ok(Array.isArray(doneHost._listeners.focusout) && doneHost._listeners.focusout.length > 0, 'done focusout handler was bound');
const doneTr = {
  dataset: { sid: 's1', date: '2026-06-06' },
  querySelector: () => null,
};
const doneSlotLabel = {
  textContent: '토1 토2',
  dataset: { orig: '토1' },
  style: {},
  closest(selector) {
    if (selector === '.slotLabel') return this;
    if (selector === 'tr[data-sid]') return doneTr;
    if (selector === 'tr[data-sid][data-date]') return doneTr;
    return null;
  },
};
for (const listener of doneHost._listeners.focusout) {
  await listener({ target: doneSlotLabel });
}
ok(globalThis.__saveWeekendSlotsCalls.length === 1, 'done slot label attempts exactly one weekend slot save');
ok(globalThis.__saveWeekendSlotsCalls[0][0] === 's1', 'done slot label save uses row sid');
ok(globalThis.__saveWeekendSlotsCalls[0][1] === '토1 토2', 'done slot label save keeps user-entered combined slots');
ok(globalThis.__saveWeekendSlotsCalls[0][2] === '2026-06-06', 'done slot label save uses row date');
ok(doneSlotLabel.dataset.orig === '토1 토2', 'done slot label dataset.orig updates after save');
"""
    cmd = ["node", "--input-type=module", "-e", driver]
    print("$ node --input-type=module -e <admin-weekend-slot-driver>")
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin weekend slot behavior driver failed")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print("admin weekend slot behavior driver captured expected negative-path stderr")


def run_unit_checks() -> bool:
    checks = [
        run_app_import_smoke_checks,
        run_log_rules_unit_checks,
        run_progress_rule_unit_checks,
        run_progress_batch_sids_unit_checks,
        run_progress_read_cache_unit_checks,
        run_video_completion_unit_checks,
        run_video_completion_source_checks,
        run_watch_route_progress_unit_checks,
        run_log_repository_unit_checks,
        run_student_answer_link_precedence_unit_checks,
        run_student_bootstrap_unit_checks,
        run_student_material_access_scope_checks,
        run_academy_proxy_network_access_checks,
        run_absence_test_assignment_transition_unit_checks,
        run_student_answer_link_render_source_checks,
        run_catalog_script_safety_source_checks,
        run_catalog_script_temp_file_behavior_checks,
        run_admin_css_scope_source_checks,
        run_student_css_scope_source_checks,
        run_shared_css_scope_source_checks,
        run_refactor_contract_evidence_source_checks,
        run_frontend_evidence_inventory_checks,
        run_admin_chat_contract_source_checks,
        run_admin_calendar_test_completion_source_checks,
        run_admin_wave_b_source_checks,
        run_admin_api_wrapper_usage_source_checks,
        run_admin_progress_batch_source_checks,
        run_all_page_progress_lazy_source_checks,
        run_admin_wave_b_behavior_checks,
        run_admin_test_modal_assignment_source_checks,
        run_admin_test_modal_persistence_bridge_source_checks,
        run_admin_test_modal_assignment_behavior_checks,
        run_admin_video_modal_preflight_source_checks,
        run_admin_video_modal_preflight_failure_behavior_checks,
        run_admin_video_modal_preflight_happy_behavior_checks,
        run_admin_video_modal_assignment_policy_behavior_checks,
        run_admin_log_modal_carried_reapply_source_checks,
        run_admin_log_modal_carried_reapply_failure_behavior_checks,
        run_admin_log_modal_carried_reapply_happy_behavior_checks,
        run_admin_log_modal_save_policy_source_checks,
        run_admin_log_modal_save_policy_behavior_checks,
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


def import_smoke_is_safe(*, report: bool = True) -> bool:
    missing = [name for name in CORE_IMPORT_RUNTIME_FILES if not (ROOT / name).exists()]
    if missing:
        if report:
            print("Skipping smoke: importing app could create missing runtime JSON files:", file=sys.stderr)
            for name in missing:
                print(f"  - {name}", file=sys.stderr)
        return False
    if not (ROOT / "data").exists():
        if report:
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
        "--only-admin-weekend-slot-behavior",
        action="store_true",
        help="Run only admin weekend slot label behavior checks.",
    )
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
        "--only-video-modal-assignment-policy",
        action="store_true",
        help="Run only video modal assignment policy behavior checks.",
    )
    parser.add_argument(
        "--only-test-modal-persistence-bridge-source",
        action="store_true",
        help="Run only test modal persistence bridge source checks.",
    )
    parser.add_argument(
        "--only-admin-api-wrapper-usage-source",
        action="store_true",
        help="Run only admin API wrapper usage source checks.",
    )
    parser.add_argument(
        "--only-student-answer-link-precedence",
        action="store_true",
        help="Run only student assigned-test answer-link precedence checks.",
    )
    parser.add_argument(
        "--only-student-answer-link-render-source",
        action="store_true",
        help="Run only student assigned-test answer-link render source checks.",
    )
    parser.add_argument(
        "--only-catalog-script-safety-source",
        action="store_true",
        help="Run only test catalog script safety source checks.",
    )
    parser.add_argument(
        "--only-catalog-script-temp-behavior",
        action="store_true",
        help="Run only test catalog script temp-file behavior checks.",
    )
    parser.add_argument(
        "--only-admin-css-scope",
        action="store_true",
        help="Run only admin stylesheet scope source checks.",
    )
    parser.add_argument(
        "--only-student-css-scope",
        action="store_true",
        help="Run only student stylesheet scope source checks.",
    )
    parser.add_argument(
        "--only-shared-css-scope",
        action="store_true",
        help="Run only shared legacy stylesheet scope source checks.",
    )
    parser.add_argument(
        "--only-refactor-contract-evidence",
        action="store_true",
        help="Run only refactor contract evidence registry source checks.",
    )
    parser.add_argument(
        "--only-frontend-evidence-inventory",
        action="store_true",
        help="Run only frontend browser evidence inventory checks.",
    )
    parser.add_argument(
        "--only-admin-calendar-test-completion-source",
        action="store_true",
        help="Run only admin calendar subject and test completion source checks.",
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
        "--only-log-modal-save-policy-source",
        action="store_true",
        help="Run only log modal save policy source checks.",
    )
    parser.add_argument(
        "--only-log-modal-save-policy-behavior",
        action="store_true",
        help="Run only log modal save policy behavior checks.",
    )
    parser.add_argument(
        "--only-admin-chat-contract-docs",
        action="store_true",
        help="Run only admin chatbot contract documentation source checks.",
    )
    args = parser.parse_args()

    selected_checks = []
    if args.only_admin_weekend_slot_behavior:
        selected_checks.append(run_admin_weekend_slot_behavior_checks)
    if args.only_admin_chat_contract_docs:
        selected_checks.append(run_admin_chat_contract_source_checks)
    if args.only_admin_calendar_test_completion_source:
        selected_checks.append(run_admin_calendar_test_completion_source_checks)
    if args.only_video_modal_preflight_source:
        selected_checks.append(run_admin_video_modal_preflight_source_checks)
    if args.only_video_modal_preflight_failures:
        selected_checks.append(run_admin_video_modal_preflight_failure_behavior_checks)
    if args.only_video_modal_preflight_happy:
        selected_checks.append(run_admin_video_modal_preflight_happy_behavior_checks)
    if args.only_video_modal_assignment_policy:
        selected_checks.append(run_admin_video_modal_assignment_policy_behavior_checks)
    if args.only_test_modal_persistence_bridge_source:
        selected_checks.append(run_admin_test_modal_persistence_bridge_source_checks)
    if args.only_admin_api_wrapper_usage_source:
        selected_checks.append(run_admin_api_wrapper_usage_source_checks)
    if args.only_student_answer_link_precedence:
        selected_checks.append(run_student_answer_link_precedence_unit_checks)
    if args.only_student_answer_link_render_source:
        selected_checks.append(run_student_answer_link_render_source_checks)
    if args.only_catalog_script_safety_source:
        selected_checks.append(run_catalog_script_safety_source_checks)
    if args.only_catalog_script_temp_behavior:
        selected_checks.append(run_catalog_script_temp_file_behavior_checks)
    if args.only_admin_css_scope:
        selected_checks.append(run_admin_css_scope_source_checks)
    if args.only_student_css_scope:
        selected_checks.append(run_student_css_scope_source_checks)
    if args.only_shared_css_scope:
        selected_checks.append(run_shared_css_scope_source_checks)
    if args.only_refactor_contract_evidence:
        selected_checks.append(run_refactor_contract_evidence_source_checks)
    if args.only_frontend_evidence_inventory:
        selected_checks.append(run_frontend_evidence_inventory_checks)
    if args.only_log_modal_carried_reapply_source:
        selected_checks.append(run_admin_log_modal_carried_reapply_source_checks)
    if args.only_log_modal_carried_reapply_failures:
        selected_checks.append(run_admin_log_modal_carried_reapply_failure_behavior_checks)
    if args.only_log_modal_carried_reapply_happy:
        selected_checks.append(run_admin_log_modal_carried_reapply_happy_behavior_checks)
    if args.only_log_modal_save_policy_source:
        selected_checks.append(run_admin_log_modal_save_policy_source_checks)
    if args.only_log_modal_save_policy_behavior:
        selected_checks.append(run_admin_log_modal_save_policy_behavior_checks)
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
