from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
import pathlib
import py_compile
import re
import socket
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
    ROOT / "scripts/admin_tests_record_detail_fixtures.py",
    ROOT / "scripts/verify_admin_tests_record_details.py",
    ROOT / "scripts/verify_retired_test_submission.py",
    ROOT / "scripts/verify_assistant_student_notes.py",
]

PYTHON_311_FILES = [
    ROOT / "app.py",
    *sorted((ROOT / "routes").rglob("*.py")),
    *sorted((ROOT / "core").rglob("*.py")),
    *sorted((ROOT / "scripts").rglob("*.py")),
]

JS_CHECK_FILES = [
    ROOT / "static/js/admin/main.js",
    ROOT / "static/js/all/main.js",
    ROOT / "static/js/admin/core/adminDate.js",
    ROOT / "static/js/admin/core/saveConflict.js",
    ROOT / "static/js/admin/demo/bootstrap.js",
    ROOT / "static/js/admin/demo/fetch.js",
    ROOT / "static/js/admin/demo/assistantStudentNotesContract.js",
    ROOT / "static/js/admin/demo/testConfigContract.js",
    ROOT / "static/js/admin/features/assistantStudentNotes.js",
    ROOT / "static/js/admin/features/absentRecovery.js",
    ROOT / "static/js/admin/features/absentRegister.js",
    ROOT / "static/js/admin/features/calendar.js",
    ROOT / "static/js/admin/features/exportLogFormat.js",
    ROOT / "static/js/admin/features/exportLogs.js",
    ROOT / "static/js/admin/features/extraModal.js",
    ROOT / "static/js/admin/features/logModal.js",
    ROOT / "static/js/admin/features/today.js",
    ROOT / "static/js/admin/features/todayDoneSummary.js",
    ROOT / "static/js/admin/features/today.state.js",
    ROOT / "static/js/admin/features/today.render.js",
    ROOT / "static/js/admin/features/testModal.js",
    ROOT / "static/js/admin/features/videoModal.js",
    ROOT / "static/js/student-app-push.js",
    ROOT / "static/js/student-app.js",
    ROOT / "static/js/student/bootstrapState.js",
    ROOT / "static/js/student/watchState.js",
    ROOT / "static/js/student/playback.js",
    ROOT / "static/js/student/reviewPlaylist.js",
    ROOT / "static/js/student/announcementState.js",
    ROOT / "static/js/student/testPresentation.js",
    ROOT / "static/js/student.js",
    ROOT / "static/js/tests.js",
    ROOT / "static/js/tests/catalogState.js",
    ROOT / "static/js/tests/catalogEditorState.js",
    ROOT / "static/js/tests/catalogStatisticsState.js",
    ROOT / "static/js/file-manage.js",
    ROOT / "static/js/shared/api.js",
    ROOT / "static/js/shared/testRecordData.js",
    ROOT / "static/js/shared/testRecordDetails.js",
    ROOT / "scripts/verify_student_material_access_scope.js",
    ROOT / "scripts/verify_student_announcement_state.mjs",
    ROOT / "scripts/verify_student_bootstrap_state.mjs",
    ROOT / "scripts/verify_student_playback.mjs",
    ROOT / "scripts/verify_student_review_playlist.mjs",
    ROOT / "scripts/verify_student_test_presentation.mjs",
    ROOT / "scripts/verify_student_watch_autosave.mjs",
    ROOT / "scripts/verify_student_watch_timestamp.mjs",
    ROOT / "scripts/verify_student_submission_retirement_and_assignment.js",
    ROOT / "scripts/verify_admin_tests_record_details_ui.js",
    ROOT / "scripts/verify_admin_tests_record_detail_answer_link_ui.js",
    ROOT / "scripts/verify_admin_date_session_storage.mjs",
    ROOT / "scripts/verify_test_catalog_state.mjs",
    ROOT / "scripts/verify_test_catalog_editor_state.mjs",
    ROOT / "scripts/verify_test_catalog_statistics_state.mjs",
    ROOT / "scripts/verify_tests_stylesheet_extraction.mjs",
    ROOT / "scripts/verify_admin_css_inventory.mjs",
    ROOT / "scripts/verify_test_catalog_search_and_sort.mjs",
    ROOT / "scripts/verify_hover_tooltip_performance.mjs",
    ROOT / "scripts/verify_admin_latency_contracts.mjs",
    ROOT / "scripts/verify_export_log_format.mjs",
    ROOT / "scripts/verify_extra_attendance_merge.mjs",
    ROOT / "scripts/verify_absence_recovery_sort.mjs",
    ROOT / "scripts/verify_phase16_demo_contract.mjs",
    ROOT / "scripts/verify_legacy_consumer_cleanup.mjs",
    ROOT / "scripts/verify_today_unarchived_done.mjs",
    ROOT / "scripts/verify_record_cleanup_test_status.mjs",
    ROOT / "scripts/verify_admin_assistant_notes_demo.mjs",
    ROOT / "scripts/student_mobile_app_checks/pwa-flow.mjs",
    ROOT / "scripts/student_mobile_app_checks/shell.mjs",
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
        "student bootstrap assignedTests contract stays aligned",
        ("run_student_bootstrap_unit_checks", "run_refactor_notes_contract_source_checks"),
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
        ("run_admin_wave_b_source_checks", "run_admin_wave_b_behavior_checks"),
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
        (
            "run_admin_test_modal_persistence_bridge_source_checks",
            "run_admin_test_modal_assignment_behavior_checks",
            "run_retired_test_submission_assignment_boundary_checks",
        ),
        (
            "test modal save must build /api/progress/patch body through the persistence bridge",
            "progress patch preserves existing test authority",
            "assignedTests remain in log patch",
            "daily metadata is not cleared on success",
            "adminAssignmentPreserved",
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
    (
        14,
        "admin test records compute wrong-answer details without raw answer leakage",
        (
            "run_admin_tests_record_detail_contract_checks",
            "run_admin_tests_record_detail_ui_checks",
            "run_admin_tests_record_detail_answer_link_ui_checks",
        ),
        (
            "publicSubmittedAnswersLeak",
            "publicAnswersTextLeak",
            "publicWrongDetailsLeak",
            "publicRawWrongDetailsValueLeak",
            "adminSensitiveFieldLeak",
            "adminRawWrongDetailsValueLeak",
            "adminAnswerUrl",
            "restrictedAnswerUrlHidden",
            "adminWrongDetails",
            "legacyWrongDetailsFallback",
            "legacyAnswersTextWrongDetails",
            "runtimeWrites",
            "wrongDetailLists",
            "escapedStudentAnswer",
            "answerLinkEscaped",
            "restrictedDetailAnswerUrlFallbackHidden",
            "apiDetailAnswerUrlWins",
            "mobileCssContract",
        ),
    ),
)

SMOKE_GUARD_SNIPPETS: Final[tuple[str, ...]] = (
    "before = runtime_fingerprints()",
    "before_sqlite = sqlite_runtime_metadata()",
    "after = runtime_fingerprints()",
    "after_sqlite = sqlite_runtime_metadata()",
    "runtime_diff_keys(before, after)",
    "sqlite_change_observations(before_sqlite, after_sqlite)",
    "sqlite_change_observations_are_safe(sqlite_changes)",
    "if include_log_gets:",
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
    "data/today_order.json",
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
SQLITE_MAIN_SUFFIXES = (".sqlite", ".db")
SQLITE_OBSERVED_SUFFIXES = SQLITE_MAIN_SUFFIXES + SQLITE_TRANSIENT_SUFFIXES
UNREADABLE_RUNTIME_DIGEST = "<metadata-only>"

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


def runtime_file_fingerprint(path: pathlib.Path) -> str:
    """Hash readable runtime files and fall back to non-secret metadata."""
    try:
        return sha256_file(path)
    except PermissionError:
        stat = path.stat()
        return f"{UNREADABLE_RUNTIME_DIGEST}:{stat.st_mtime_ns}:{stat.st_size}"


def verification_temporary_directory(prefix: str) -> tempfile.TemporaryDirectory[str]:
    """Create an auto-cleaned fixture directory without relying on legacy ROOT/tmp ACLs."""
    return tempfile.TemporaryDirectory(prefix=f".{prefix}", dir=ROOT)


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
        try:
            out[rel(path)] = runtime_file_fingerprint(path) if path.exists() and path.is_file() else None
        except FileNotFoundError:
            # A live SQLite sidecar can disappear between enumeration and hashing.
            out[rel(path)] = None
    return out


def _is_sqlite_observed_path(path: pathlib.Path | str) -> bool:
    return str(path).lower().endswith(SQLITE_OBSERVED_SUFFIXES)


def iter_sqlite_runtime_paths(root: pathlib.Path = ROOT) -> Iterable[pathlib.Path]:
    seen: set[pathlib.Path] = set()

    for path in root.iterdir():
        if path.is_file() and _is_sqlite_observed_path(path):
            seen.add(path)
            yield path

    for dirname in RUNTIME_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if any(part in SKIP_DIR_NAMES for part in path.relative_to(root).parts):
                continue
            if path.is_file() and _is_sqlite_observed_path(path) and path not in seen:
                seen.add(path)
                yield path


def _sqlite_file_metadata(path: pathlib.Path) -> dict[str, int | str]:
    with path.open("rb") as stream:
        stat = os.fstat(stream.fileno())
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "sha256": digest.hexdigest(),
    }


def _runtime_file_metadata(path: pathlib.Path) -> dict[str, int | str]:
    try:
        return _sqlite_file_metadata(path)
    except PermissionError:
        stat = path.stat()
        return {
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
            "sha256": UNREADABLE_RUNTIME_DIGEST,
        }


def sqlite_runtime_metadata(root: pathlib.Path = ROOT) -> dict[str, dict[str, int | str]]:
    observations: dict[str, dict[str, int | str]] = {}
    for path in iter_sqlite_runtime_paths(root):
        try:
            observations[path.relative_to(root).as_posix()] = _sqlite_file_metadata(path)
        except FileNotFoundError:
            # A sidecar can disappear while a live SQLite connection checkpoints.
            continue
    return observations


def runtime_metadata_fingerprints() -> dict[str, dict[str, int | str]]:
    """Observe runtime content, size, and mtime without importing application paths."""
    observations: dict[str, dict[str, int | str]] = {}
    for path in iter_runtime_paths():
        try:
            observations[rel(path)] = _runtime_file_metadata(path)
        except FileNotFoundError:
            continue
    return observations


def _local_runtime_service_is_active(port: int = 8003) -> bool:
    """Return whether the live local service can be a concurrent runtime writer."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def sqlite_change_observations(
    before: dict[str, dict[str, int | str]],
    after: dict[str, dict[str, int | str]],
) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for key in sorted(set(before) | set(after)):
        before_item = before.get(key)
        after_item = after.get(key)
        if before_item == after_item:
            continue
        if before_item is None:
            change = "created"
            changed_fields = ["existence"]
        elif after_item is None:
            change = "deleted"
            changed_fields = ["existence"]
        else:
            change = "modified"
            changed_fields = [
                field
                for field in ("mtime_ns", "size", "sha256")
                if before_item.get(field) != after_item.get(field)
            ]
        observations.append({
            "path": key,
            "change": change,
            "changedFields": changed_fields,
            "allowed": is_sqlite_transient_sidecar(key),
        })
    return observations


def sqlite_change_observations_are_safe(observations: Iterable[dict[str, object]]) -> bool:
    return all(observation.get("allowed") is True for observation in observations)


def print_sqlite_change_observations(observations: Iterable[dict[str, object]]) -> None:
    for observation in observations:
        print(
            "sqlite file observation: " + json.dumps(observation, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )


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


def _run_captured(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
    )


def run_python_compile() -> bool:
    ok = True
    with verification_temporary_directory("verify-pycompile-") as tmpdir:
        temp_root = pathlib.Path(tmpdir)
        for index, path in enumerate(PYTHON_FILES):
            try:
                py_compile.compile(
                    str(path),
                    cfile=str(temp_root / f"{index:04d}.pyc"),
                    doraise=True,
                )
                print(f"py_compile ok: {rel(path)}")
            except Exception as exc:
                ok = False
                print(f"py_compile failed: {rel(path)}: {exc}", file=sys.stderr)
    return ok


def run_python311_syntax_checks() -> bool:
    """Match the repository CI parser without relying on the local Python version."""
    ok = True
    checked = 0
    for path in PYTHON_311_FILES:
        checked += 1
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path), feature_version=(3, 11))
        except (SyntaxError, UnicodeError) as exc:
            ok = False
            line = getattr(exc, "lineno", None)
            location = f":{line}" if isinstance(line, int) and line > 0 else ""
            print(
                f"python 3.11 syntax failed: {rel(path)}{location}: {type(exc).__name__}",
                file=sys.stderr,
            )
    if ok:
        print(f"python 3.11 syntax ok: {checked} files")
    return ok


def run_node_check(path: pathlib.Path) -> bool:
    cmd = ["node", "--check", rel(path)]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
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


def run_admin_date_session_storage_checks() -> None:
    cmd = ["node", "scripts/verify_admin_date_session_storage.mjs"]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin selected-date sessionStorage contract failed")


def run_admin_css_inventory_checks() -> None:
    cmd = ["node", "scripts/verify_admin_css_inventory.mjs"]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin CSS ownership inventory contract failed")


def run_test_catalog_search_sort_checks() -> None:
    state_cmd = ["node", "scripts/verify_test_catalog_state.mjs"]
    print("$ " + " ".join(state_cmd))
    try:
        proc = _run_captured(state_cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "test catalog state oracle failed")

    editor_state_cmd = ["node", "scripts/verify_test_catalog_editor_state.mjs"]
    print("$ " + " ".join(editor_state_cmd))
    proc = _run_captured(editor_state_cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "test catalog editor state oracle failed")

    statistics_state_cmd = ["node", "scripts/verify_test_catalog_statistics_state.mjs"]
    print("$ " + " ".join(statistics_state_cmd))
    proc = _run_captured(statistics_state_cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "test catalog statistics state oracle failed")

    stylesheet_cmd = ["node", "scripts/verify_tests_stylesheet_extraction.mjs"]
    print("$ " + " ".join(stylesheet_cmd))
    proc = _run_captured(stylesheet_cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "test page stylesheet extraction oracle failed")

    node_cmd = ["node", "scripts/verify_test_catalog_search_and_sort.mjs"]
    print("$ " + " ".join(node_cmd))
    try:
        proc = _run_captured(node_cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "test catalog search and ordering contract failed")

    python_cmd = [sys.executable, "scripts/verify_tests_config_write_safety.py"]
    print("$ " + " ".join(python_cmd))
    proc = _run_captured(python_cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "test catalog revision/write safety contract failed")


def run_hover_tooltip_performance_checks() -> None:
    cmd = ["node", "scripts/verify_hover_tooltip_performance.mjs"]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin hover tooltip performance/accessibility contract failed")


def run_admin_latency_contract_checks() -> None:
    cmd = ["node", "scripts/verify_admin_latency_contracts.mjs"]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin latency/save-conflict contract failed")


def run_export_log_format_checks() -> None:
    commands = [
        (["node", "scripts/verify_export_log_format.mjs"], "export log format contract failed"),
        (["node", "scripts/verify_extra_attendance_merge.mjs"], "extra attendance merge contract failed"),
        (["node", "scripts/verify_roster_export_logic.js"], "roster export regression contract failed"),
    ]
    for cmd, failure_message in commands:
        print("$ " + " ".join(cmd))
        try:
            proc = _run_captured(cmd)
        except FileNotFoundError:
            raise AssertionError("node not found") from None
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        _assert_unit(proc.returncode == 0, failure_message)


def run_today_order_store_migration_checks() -> None:
    cmd = [sys.executable, "scripts/verify_today_order_store_migration.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "today-order store migration contract failed")


def run_today_completion_checks() -> None:
    today_order_driver = r"""
import json
import os
import pathlib
import tempfile

from flask import Flask

with tempfile.TemporaryDirectory(prefix="verify-today-order-") as tmpdir:
    os.environ["DATA_DIR"] = tmpdir
    import routes.api_todaymeta as todaymeta

    app = Flask("verify-today-order")
    app.register_blueprint(todaymeta.bp_api_todaymeta)
    client = app.test_client()
    path = pathlib.Path(tmpdir) / "today_order.json"

    for retired_path in (
        "/api/_legacy/attendance",
        "/api/_legacy/contact",
        "/api/_legacy/arrive-time",
    ):
        assert client.get(retired_path).status_code == 404
        assert client.post(retired_path, json={}).status_code == 404

    assert client.post("/api/today_order", json={"2026-08-13": ["overwrite"]}).status_code == 405
    for date_key, order in {
        "2026-08-13": ["keep"],
        "2026-08-14": ["old"],
    }.items():
        seeded = client.patch("/api/today_order", json={"date": date_key, "order": order})
        assert seeded.status_code == 200
    patched = client.patch("/api/today_order", json={
        "date": "2026-08-14",
        "order": [" a ", "a", "b", ""],
    })
    assert patched.status_code == 200
    assert patched.get_json()["order"] == ["a", "b"]
    stored = json.loads(path.read_text("utf-8"))
    assert stored["2026-08-13"] == ["keep"]
    assert stored["2026-08-14"] == ["a", "b"]

    deleted = client.delete("/api/today_order?date=2026-08-14")
    assert deleted.status_code == 200 and deleted.get_json()["cleared"] is True
    repeated = client.delete("/api/today_order?date=2026-08-14")
    assert repeated.status_code == 200 and repeated.get_json()["cleared"] is False
    assert json.loads(path.read_text("utf-8")) == {"2026-08-13": ["keep"]}
    assert client.patch("/api/today_order", json={"date": "2026-02-31", "order": []}).status_code == 400

    path.write_text("{broken", "utf-8")
    blocked = client.patch("/api/today_order", json={"date": "2026-08-14", "order": ["x"]})
    assert blocked.status_code == 409
    assert path.read_text("utf-8") == "{broken"

print("today order date-scoped mutation checks passed")
"""
    arrive_time_driver = r"""
import json
import pathlib
import tempfile

from flask import Flask
import routes.api_arrive_time as arrive_time

with tempfile.TemporaryDirectory(prefix="verify-arrive-time-route-") as tmpdir:
    path = pathlib.Path(tmpdir) / "arrive_time.json"
    arrive_time.ARRIVE_TIME_PATH = path

    app = Flask("verify-arrive-time-route")
    app.register_blueprint(arrive_time.bp_api_arrive_time)
    client = app.test_client()
    date_key = "2026-08-23"

    assert client.get(f"/api/arrive-time?date={date_key}").status_code == 200
    assert client.post("/api/arrive-time", json={date_key: {"sid-a": "15:00"}}).status_code == 200
    patched = client.post(
        "/api/arrive-time/patch",
        json={"date": date_key, "sid": "sid-a", "value": "16:30"},
    )
    assert patched.status_code == 200
    assert client.get(f"/api/arrive-time?date={date_key}").get_json() == {"sid-a": "16:30"}
    assert json.loads(path.read_text("utf-8"))[date_key] == {"sid-a": "16:30"}

    before = path.read_bytes()
    assert client.get(f"/arrive-time?date={date_key}").status_code == 404
    assert client.post("/arrive-time", json={date_key: {"sid-a": "overwrite"}}).status_code == 404
    assert client.post(
        "/arrive-time/patch",
        json={"date": date_key, "sid": "sid-a", "value": "overwrite"},
    ).status_code == 404
    assert path.read_bytes() == before

print("canonical arrive-time route checks passed")
"""
    attendance_contact_driver = r"""
import json
import pathlib
import tempfile

from flask import Flask
import routes.api_attend as attend

with tempfile.TemporaryDirectory(prefix="verify-attendance-contact-routes-") as tmpdir:
    root = pathlib.Path(tmpdir)
    attend.ATTENDANCE_PATH = root / "attendance.json"
    attend.CONTACT_PATH = root / "contact.json"
    attend.STU_PATH = root / "students.json"
    attend.EXTRA_PATH = root / "extra_attend.json"
    attend.MAKEUP_CARRYOVER_PATH = root / "makeup_carryover.json"

    date_key = "2026-08-23"
    attend.STU_PATH.write_text(json.dumps([
        {"id": "regular", "name": "Regular", "day1": "일1"},
        {"id": "extra-only", "name": "Extra", "day1": "월1"},
        {"id": "makeup-only", "name": "Makeup", "day1": "월1"},
        {"id": "absent-makeup", "name": "Absent makeup", "day1": "월1"},
        {"id": "idle", "name": "Idle", "day1": "월1"},
    ]), encoding="utf-8")
    attend.EXTRA_PATH.write_text(json.dumps({date_key: ["extra-only"]}), encoding="utf-8")
    attend.MAKEUP_CARRYOVER_PATH.write_text(json.dumps({
        "by_absence": {
            "2026-08-01": {
                "makeup-only|1": {
                    "scheduledMakeup": {
                        "originalAbsenceId": "absence|2026-08-01|makeup-only|1",
                        "studentId": "makeup-only",
                        "makeupDate": date_key,
                        "makeupTimes": [1],
                        "status": "scheduled",
                    },
                },
                "absent-makeup|2": {
                    "scheduledMakeup": {
                        "originalAbsenceId": "absence|2026-08-01|absent-makeup|2",
                        "studentId": "absent-makeup",
                        "makeupDate": date_key,
                        "makeupTimes": [2],
                        "status": "scheduled",
                    },
                },
            },
        },
    }), encoding="utf-8")
    attend.load_absent = lambda: {
        "by_date": {date_key: ["absent-makeup"]},
        "by_student": {},
        "by_slot": {},
    }

    app = Flask("verify-attendance-contact-routes")
    app.register_blueprint(attend.bp_api_attend)
    client = app.test_client()

    roster = client.get(f"/api/attend?date={date_key}")
    assert roster.status_code == 200
    assert [row["id"] for row in roster.get_json()] == ["regular", "extra-only", "makeup-only"]

    for base_path, patch_path, store_path in (
        ("/api/attendance", "/api/attendance/patch", attend.ATTENDANCE_PATH),
        ("/api/contact", "/api/contact/patch", attend.CONTACT_PATH),
    ):
        assert client.get(f"{base_path}?date={date_key}").get_json() == {}
        assert client.post(base_path, json={date_key: {"sid-a": 1}}).status_code == 405
        assert not store_path.exists()

        saved = client.post(
            patch_path,
            json={"date": date_key, "sid": "sid-a", "value": True},
        )
        assert saved.status_code == 200
        assert client.get(f"{base_path}?date={date_key}").get_json() == {"sid-a": 1}

        before = store_path.read_bytes()
        retired = client.post(
            base_path,
            json={"date": date_key, "map": {"sid-b": 1}, "replace": True},
        )
        assert retired.status_code == 405
        assert store_path.read_bytes() == before

        cleared = client.post(
            patch_path,
            json={"date": date_key, "sid": "sid-a", "value": False},
        )
        assert cleared.status_code == 200
        assert client.get(f"{base_path}?date={date_key}").get_json() == {}

print("attendance/contact GET-only base route checks passed")
"""
    updates_route_driver = r"""
import pathlib
import tempfile

from flask import Flask
import routes.api_updates as updates

with tempfile.TemporaryDirectory(prefix="verify-updates-base-route-") as tmpdir:
    path = pathlib.Path(tmpdir) / "updates.json"
    updates.UPD_PATH = path

    app = Flask("verify-updates-base-route")
    app.register_blueprint(updates.bp_api_updates)
    client = app.test_client()

    read_only = client.get("/api/updates?readOnly=1")
    assert read_only.status_code == 200
    assert read_only.get_json() == {}
    assert not path.exists()

    retired = client.post(
        "/api/updates",
        json={"2026-08-23": {"sid-a": {"videos": ["mid-a"], "source": "manual"}}},
    )
    assert retired.status_code == 405
    assert not path.exists()

print("updates GET-only base route checks passed")
"""
    command_groups = [
        ([sys.executable, "-X", "utf8", "-c", today_order_driver], "date-scoped today order contract failed"),
        ([sys.executable, "-X", "utf8", "-c", arrive_time_driver], "canonical arrive-time route contract failed"),
        ([sys.executable, "-X", "utf8", "-c", attendance_contact_driver], "attendance/contact route contract failed"),
        ([sys.executable, "-X", "utf8", "-c", updates_route_driver], "updates base route contract failed"),
    ]
    commands = [
        (["node", "scripts/verify_absence_recovery_sort.mjs"], "absence recovery convergence contract failed"),
        (["node", "scripts/verify_makeup_schedule_links.mjs"], "makeup schedule roster-link contract failed"),
        (["node", "scripts/verify_phase16_demo_contract.mjs"], "Phase16 demo isolation contract failed"),
        (["node", "scripts/verify_admin_assistant_notes_demo.mjs"], "assistant student notes demo contract failed"),
        (["node", "scripts/verify_today_unarchived_done.mjs"], "all-date unarchived done projection failed"),
        (["node", "scripts/verify_record_cleanup_test_status.mjs"], "record cleanup latest-state and rendered-date contract failed"),
    ]
    for cmd, failure_message in [*command_groups, *commands]:
        print("$ " + " ".join(cmd))
        try:
            proc = _run_captured(cmd)
        except FileNotFoundError:
            raise AssertionError("node not found") from None
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        _assert_unit(proc.returncode == 0, failure_message)


def run_legacy_consumer_cleanup_checks() -> None:
    cmd = ["node", "scripts/verify_legacy_consumer_cleanup.mjs"]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "legacy consumer cleanup contract failed")


def run_person_identity_checks() -> None:
    commands = (
        ([sys.executable, "scripts/verify_person_identity.py"], "person identity rule/store contract failed"),
        ([sys.executable, "scripts/verify_person_identity_routes.py"], "person identity route contract failed"),
        (["node", "scripts/verify_admin_white_review_pending.mjs"], "admin white-review pending contract failed"),
    )
    for cmd, failure_message in commands:
        print("$ " + " ".join(cmd))
        proc = _run_captured(cmd)
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        _assert_unit(proc.returncode == 0, failure_message)


def run_file_reference_route_checks() -> None:
    cmd = [sys.executable, "scripts/verify_file_reference_routes.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "material/file reference integrity contract failed")


def run_school_calendar_revision_checks() -> None:
    commands = (
        (
            [sys.executable, "scripts/verify_school_calendar_revision.py"],
            "school calendar revision route contract failed",
        ),
        (
            ["node", "scripts/verify_school_calendar_state.mjs"],
            "school calendar editable-state projection contract failed",
        ),
        (
            ["node", "scripts/verify_school_calendar_save_queue.mjs"],
            "school calendar serialized browser queue contract failed",
        ),
    )
    for cmd, failure_message in commands:
        print("$ " + " ".join(cmd))
        proc = _run_captured(cmd)
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        _assert_unit(proc.returncode == 0, failure_message)

def run_student_material_access_scope_checks() -> None:
    cmd = ["node", "scripts/verify_student_material_access_scope.js"]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "student material access scope contract failed")


def run_student_bootstrap_state_checks() -> None:
    cmd = ["node", "scripts/verify_student_bootstrap_state.mjs"]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "student bootstrap browser-state contract failed")


def run_student_announcement_state_checks() -> None:
    commands = (
        (
            ["node", "scripts/verify_student_announcement_state.mjs"],
            "student announcement state contract failed",
        ),
        (
            ["node", "scripts/verify_student_mobile_app.mjs", "--only", "board,notifications"],
            "student announcement board and notification integration contracts failed",
        ),
    )
    for cmd, failure_message in commands:
        print("$ " + " ".join(cmd))
        try:
            proc = _run_captured(cmd)
        except FileNotFoundError:
            raise AssertionError("node not found") from None
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        _assert_unit(proc.returncode == 0, failure_message)


def run_student_test_presentation_checks() -> None:
    commands = (
        (
            ["node", "scripts/verify_student_test_presentation.mjs"],
            "student test presentation contract failed",
        ),
        (
            ["node", "scripts/verify_student_answer_mobile.js"],
            "student answer mobile presentation contract failed",
        ),
    )
    for cmd, failure_message in commands:
        print("$ " + " ".join(cmd))
        try:
            proc = _run_captured(cmd)
        except FileNotFoundError:
            raise AssertionError("node not found") from None
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        _assert_unit(proc.returncode == 0, failure_message)


def run_video_manage_id_checks() -> None:
    cmd = ["node", "scripts/verify_video_manage_ids.mjs"]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "video manager ID allocation contract failed")


def run_progress_route_checks() -> None:
    cmd = [sys.executable, "scripts/verify_progress_routes.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "progress route boundary contract failed")


def run_updates_route_checks() -> None:
    cmd = [sys.executable, "scripts/verify_updates_routes.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "updates route boundary contract failed")


def run_student_bootstrap_route_checks() -> None:
    cmd = [sys.executable, "scripts/verify_student_bootstrap_routes.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(
        proc.returncode == 0,
        "student bootstrap route boundary contract failed",
    )


def run_student_video_assignment_rule_checks() -> None:
    cmd = [
        sys.executable,
        "scripts/verify_student_video_assignment_rules.py",
    ]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(
        proc.returncode == 0,
        "student video assignment pure-rule contract failed",
    )


def run_student_auto_assignment_service_checks() -> None:
    cmd = [
        sys.executable,
        "scripts/verify_student_auto_assignment_service.py",
    ]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(
        proc.returncode == 0,
        "student auto-assignment runtime service contract failed",
    )


def run_log_route_checks() -> None:
    cmd = [sys.executable, "scripts/verify_log_routes.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "log route boundary contract failed")


def run_material_route_checks() -> None:
    cmd = [sys.executable, "scripts/verify_material_routes.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "material route boundary contract failed")


def run_schedule_override_route_checks() -> None:
    cmd = [sys.executable, "scripts/verify_schedule_override_routes.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "schedule override route boundary contract failed")


def run_video_mid_change_guard_checks() -> None:
    cmd = [sys.executable, "scripts/verify_video_mid_change_guard.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "video MID change guard contract failed")


def run_video_catalog_correction_checks() -> None:
    cmd = [sys.executable, "scripts/verify_video_catalog_correction.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "offline video catalog correction contract failed")


def run_mobile_touch_target_checks() -> None:
    cmd = ["node", "scripts/verify_mobile_touch_targets.mjs"]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "mobile touch target contract failed")


def run_student_submission_retirement_and_assignment_checks() -> None:
    cmd = ["node", "scripts/verify_student_submission_retirement_and_assignment.js"]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "student submission-retirement and admin assignment contract failed")


def run_academy_proxy_network_access_checks() -> None:
    cmd = [sys.executable, "scripts/verify_academy_proxy_network_access.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "academy proxy network access contract failed")


def run_test_answer_mode_contract_checks() -> None:
    cmd = [sys.executable, "scripts/verify_test_answer_modes.py"]
    print("$ " + " ".join(cmd))
    proc = _run_captured(cmd)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "test answer mode contract failed")


def run_student_test_ocr_contract_checks() -> None:
    commands = (
        ([sys.executable, "-m", "scripts.verify_student_test_ocr_foundation"], "OCR foundation"),
        ([sys.executable, "-m", "scripts.verify_student_test_ocr_repository"], "OCR repository"),
        ([sys.executable, "-m", "scripts.verify_student_test_ocr_eligibility"], "OCR eligibility"),
        ([sys.executable, "-m", "scripts.verify_student_test_ocr_assets"], "OCR assets"),
        ([sys.executable, "-m", "scripts.verify_student_test_sheet_cropper"], "OCR sheet cropper"),
        ([sys.executable, "-m", "scripts.verify_student_test_ocr_config"], "OCR config"),
        ([sys.executable, "-m", "scripts.verify_student_test_ocr_engine"], "OCR engine"),
        ([sys.executable, "-m", "scripts.verify_student_test_ocr_worker_contracts"], "OCR workers"),
        ([sys.executable, "-m", "scripts.verify_student_test_choice_training"], "OCR choice training"),
        ([sys.executable, "-m", "scripts.verify_student_test_aihub_validation"], "OCR AI Hub validation audit"),
        ([sys.executable, "-m", "scripts.verify_student_test_aihub_choice_validation"], "OCR AI Hub choice validation"),
        ([sys.executable, "-m", "scripts.verify_student_test_local_ocr_accuracy"], "OCR local accuracy benchmark"),
        ([sys.executable, "-m", "scripts.verify_student_test_formula_training_config"], "OCR formula training config"),
        ([sys.executable, "-m", "scripts.verify_student_test_formula_profile_training"], "OCR formula profile training"),
        ([sys.executable, "-m", "scripts.verify_aihub_split_archive_unpack"], "OCR AI Hub archive unpack"),
        ([sys.executable, "-m", "scripts.verify_student_test_ocr_job_runner"], "OCR job runner"),
        ([sys.executable, "-m", "scripts.verify_student_test_solution_crop"], "OCR solution crop"),
        ([sys.executable, "-m", "scripts.verify_student_test_ocr_service"], "OCR service"),
        ([sys.executable, "-m", "scripts.verify_student_test_ocr_routes"], "OCR routes"),
        (["node", "scripts/verify_student_test_ocr_frontend.mjs"], "OCR student frontend"),
        (["node", "scripts/verify_student_test_ocr_admin.mjs"], "OCR admin frontend"),
    )
    for cmd, label in commands:
        print("$ " + " ".join(cmd))
        proc = _run_captured(cmd)
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        _assert_unit(proc.returncode == 0, f"{label} contract failed")


def _assert_unit(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_smoke_sqlite_observation_unit_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-smoke-sqlite-") as tmpdir:
        tmp = pathlib.Path(tmpdir)
        main_db = tmp / "app.sqlite"
        wal = tmp / "app.sqlite-wal"
        shm = tmp / "app.sqlite-shm"
        main_db.write_bytes(b"main-database")
        wal.write_bytes(b"wal-before")

        before_sidecar = sqlite_runtime_metadata(tmp)
        wal_stat = wal.stat()
        wal.write_bytes(b"wal-after")
        os.utime(wal, ns=(wal_stat.st_atime_ns, wal_stat.st_mtime_ns + 2_000_000_000))
        after_sidecar = sqlite_runtime_metadata(tmp)
        sidecar_changes = sqlite_change_observations(before_sidecar, after_sidecar)
        _assert_unit(
            sidecar_changes == [{
                "path": "app.sqlite-wal",
                "change": "modified",
                "changedFields": ["mtime_ns", "size", "sha256"],
                "allowed": True,
            }],
            f"WAL content changes must produce one structured allowed observation: {sidecar_changes}",
        )
        _assert_unit(
            sqlite_change_observations_are_safe(sidecar_changes),
            "WAL/SHM-only changes must be allowed",
        )

        before_main_touch = sqlite_runtime_metadata(tmp)
        main_stat = main_db.stat()
        os.utime(
            main_db,
            ns=(main_stat.st_atime_ns, main_stat.st_mtime_ns + 2_000_000_000),
        )
        after_main_touch = sqlite_runtime_metadata(tmp)
        main_changes = sqlite_change_observations(before_main_touch, after_main_touch)
        _assert_unit(
            main_changes == [{
                "path": "app.sqlite",
                "change": "modified",
                "changedFields": ["mtime_ns"],
                "allowed": False,
            }],
            f"main DB mtime-only changes must be detected without a hash/size change: {main_changes}",
        )
        _assert_unit(
            not sqlite_change_observations_are_safe(main_changes),
            "main .sqlite/.db metadata changes must fail smoke safety",
        )

        before_create = sqlite_runtime_metadata(tmp)
        shm.write_bytes(b"shm")
        after_create = sqlite_runtime_metadata(tmp)
        created_changes = sqlite_change_observations(before_create, after_create)
        _assert_unit(
            created_changes == [{
                "path": "app.sqlite-shm",
                "change": "created",
                "changedFields": ["existence"],
                "allowed": True,
            }],
            f"created SHM sidecars must be detected: {created_changes}",
        )

        before_delete = after_create
        shm.unlink()
        after_delete = sqlite_runtime_metadata(tmp)
        deleted_changes = sqlite_change_observations(before_delete, after_delete)
        _assert_unit(
            deleted_changes == [{
                "path": "app.sqlite-shm",
                "change": "deleted",
                "changedFields": ["existence"],
                "allowed": True,
            }],
            f"deleted SHM sidecars must be detected: {deleted_changes}",
        )
        _assert_unit(
            set(created_changes[0]) == {"path", "change", "changedFields", "allowed"},
            "structured observations must not expose before/after file or runtime record values",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            print_sqlite_change_observations(created_changes)
        prefix = "sqlite file observation: "
        rendered = stderr.getvalue().strip()
        _assert_unit(rendered.startswith(prefix), "SQLite change output must use a structured observation prefix")
        _assert_unit(
            json.loads(rendered[len(prefix):]) == created_changes[0],
            "SQLite change output must contain only the redacted structured observation",
        )

        protected = tmp / "protected-runtime.pem"
        protected.write_bytes(b"private fixture")
        original_open = pathlib.Path.open

        def deny_protected_open(path, *args, **kwargs):
            if path == protected:
                raise PermissionError("fixture is metadata-only")
            return original_open(path, *args, **kwargs)

        pathlib.Path.open = deny_protected_open
        try:
            protected_metadata = _runtime_file_metadata(protected)
            protected_fingerprint = runtime_file_fingerprint(protected)
        finally:
            pathlib.Path.open = original_open
        _assert_unit(
            protected_metadata["sha256"] == UNREADABLE_RUNTIME_DIGEST
            and protected_metadata["size"] == len(b"private fixture"),
            "runtime observers must use metadata for access-restricted files",
        )
        _assert_unit(
            protected_fingerprint.startswith(f"{UNREADABLE_RUNTIME_DIGEST}:")
            and protected_fingerprint.endswith(f":{len(b'private fixture')}"),
            "runtime smoke fingerprints must not require access-restricted file contents",
        )

    expected_log_paths = [
        ("log entry date/sid", "/api/logs/entry?date=2026-06-06&sid=student-1"),
        ("logs date/sid", "/api/logs?date=2026-06-06&sid=student-1"),
    ]
    _assert_unit(
        smoke_log_paths("2026-06-06", "student-1") == expected_log_paths,
        "opt-in smoke must wire both exact date/SID log GETs",
    )
    _assert_unit(
        smoke_log_paths("2026-06-06", "") == []
        and smoke_log_paths("bad-date", "student-1") == [],
        "opt-in log GET smoke must never widen an invalid or empty candidate",
    )
    _assert_unit(
        all("/api/logs" not in path for _label, path in smoke_paths("2026-06-06", "student-1")),
        "default smoke paths must continue to exclude both log GETs",
    )

    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    smoke_start = source.rfind("def run_smoke_checks(")
    main_start = source.rfind("def main()")
    smoke_block = source[smoke_start:main_start]
    main_block = source[main_start:]
    for snippet in (
        '"--smoke-log-gets"',
        "if args.smoke_log_gets and not args.smoke:",
        'parser.error("--smoke-log-gets requires --smoke")',
        "run_smoke_checks(include_log_gets=args.smoke_log_gets)",
    ):
        _assert_unit(snippet in main_block, f"log GET smoke CLI wiring must remain explicit: {snippet}")
    _assert_unit(
        "if include_log_gets:" in smoke_block
        and "log_paths = smoke_log_paths(date, sid)" in smoke_block
        and "if not log_paths:" in smoke_block
        and "ok = _run_smoke_gets(client, log_paths) and ok" in smoke_block
        and "Skipped GET /api/logs/entry because it may touch SQLite WAL/schema state." in smoke_block
        and "Skipped GET /api/logs because it may touch SQLite WAL/schema state." in smoke_block,
        "default smoke must skip risky log GETs unless the explicit opt-in is enabled",
    )


def run_app_import_smoke_checks() -> None:
    import importlib

    if not import_smoke_is_safe(report=False):
        print("app import smoke skipped because importing app could create runtime files")
        return

    app_module = importlib.import_module("app")
    _assert_unit(hasattr(app_module, "create_app"), "app import must expose create_app")


def run_log_rules_unit_checks() -> None:
    from core.log_rules import (
        latest_homework_books_by_student,
        log_entry_conflicts_with_base,
        merge_log_entry_safe,
        normalize_sleeping_homework_books,
    )

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
    _assert_unit(
        normalize_sleeping_homework_books([" 라이트쎈 ", "라이트 쎈", "", None, "APEX"])
        == ["라이트쎈", "APEX"],
        "sleeping homework books must be trimmed and deduplicated",
    )
    _assert_unit(
        not log_entry_conflicts_with_base(
            {"sleepingHomeworkBooks": ["라이트쎈"]},
            {"sleepingHomeworkBooks": [" 라이트쎈 "]},
        ),
        "equivalent sleeping homework books must not conflict",
    )
    _assert_unit(
        log_entry_conflicts_with_base(
            {"sleepingHomeworkBooks": ["라이트쎈"]},
            {"sleepingHomeworkBooks": []},
        ),
        "concurrent sleeping homework book changes must conflict",
    )

    linked_books = latest_homework_books_by_student({
        "2026-07-18": {
            "s1": {"homeworkTable": [{"book": "old book"}]},
            "s2": {"homeworkTable": [{"book": "keep me"}]},
        },
        "2026-07-20": {
            "s1": {
                "homeworkTable": [
                    {"book": "new book"},
                    {"book": " new book "},
                    {"book": "deleted", "_deleted": True},
                ],
            },
        },
    })
    _assert_unit(
        linked_books == {"s1": ["new book"], "s2": ["keep me"]},
        "all-students homework books must use each student's latest registered log books",
    )


def run_all_students_linked_books_and_log_popup_source_checks() -> None:
    table_js = (ROOT / "static/js/all/features/table.js").read_text("utf-8")
    hover_js = (ROOT / "static/js/all/features/hoverTooltip.js").read_text("utf-8")
    state_js = (ROOT / "static/js/all/core/state.js").read_text("utf-8")
    main_js = (ROOT / "static/js/all/main.js").read_text("utf-8")
    record_popup_js = (ROOT / "static/js/all/features/studentRecordPopup.js").read_text("utf-8")
    admin_hover_js = (ROOT / "static/js/admin/features/hoverTooltip.js").read_text("utf-8")
    log_modal_js = (ROOT / "static/js/admin/features/logModal.js").read_text("utf-8")
    video_modal_js = (ROOT / "static/js/admin/features/videoModal.js").read_text("utf-8")
    student_work_light_css = (ROOT / "static/css/student-work-light.css").read_text("utf-8")
    add_student_js = (ROOT / "static/js/all/features/addStudent.js").read_text("utf-8")
    esc_close_js = (ROOT / "static/js/all/features/escClose.js").read_text("utf-8")

    _assert_unit(
        "export function loadHomeworkBooks" in state_js
        and "getJSON('/api/homework-books')" in state_js
        and "homeworkBooksRequest" in state_js
        and "loadAll({ waitForHomeworkBooks: false })" in main_js
        and "void loadHomeworkBooks().then" in main_js
        and "renderHomeworkBooks();" in main_js,
        "all-students bootstrap must start one non-blocking linked-homework-books load and render its result",
    )
    _assert_unit(
        "state.homeworkBooksBySid" in table_js and "subBookInput" not in table_js,
        "all-students table must render linked homework books without legacy sub-book inputs",
    )
    _assert_unit(
        "col.col-level      { width:7%; }" in table_js
        and "col.col-docs       { width:15%; }" in table_js
        and ".levelSelect{" in table_js
        and "padding-left:5px;" in table_js
        and "padding-right:14px;" in table_js,
        "all-students level select must keep the two-character middle-high label visible",
    )
    _assert_unit(
        "state.homeworkBooksBySid" in hover_js and "stu.subBook" not in hover_js,
        "all-students hover tooltip must render the same linked homework books",
    )
    _assert_unit(
        "accessMode: 'all-students-readonly'" in table_js
        and "window.openStudentPopupsForRow(row" in table_js
        and "window.openRecordPopupForRow(row" not in table_js,
        "the all-students counseling action must use the shared admin unified popup launcher",
    )
    _assert_unit(
        "studentRecordPopup.js" not in main_js
        and "initAllStudentsRecordPopup(state)" not in main_js
        and re.search(
            r"import\((['\"])\./studentRecordPopup\.js(?:\?[^'\"]*)?\1\)",
            table_js,
        )
        and "await initAllStudentsRecordPopup(state)" in table_js,
        "all-students startup must defer the admin popup module graph until the counseling action",
    )
    _assert_unit(
        "function focusAllStudentSearch()" in esc_close_js
        and "document.getElementById('allStudentSearchInput')" in esc_close_js
        and "input.dispatchEvent(new Event('input', { bubbles: true }))" in esc_close_js
        and "input.focus({ preventScroll: true })" in esc_close_js
        and "if (!hadOpenTarget)" in esc_close_js
        and "requestAnimationFrame(focusAllStudentSearch)" in esc_close_js,
        "Escape must clear and focus the all-students search only when no popup has priority",
    )
    _assert_unit(
        "ADMIN_POPUP_STYLESHEETS" in record_popup_js
        and "'/css/main.css?v=20260417a'" in record_popup_js
        and "'/css/admin.css?v=20260527chat'" in record_popup_js
        and "document.body.classList.add('admin')" in record_popup_js
        and "allStudentsBaseStyleSuspended" in record_popup_js
        and "document.body.classList.remove('all-page')" in record_popup_js
        and "releaseAdminPopupSkin" in record_popup_js,
        "all-students popups must temporarily use the exact admin stylesheet stack and release it after close",
    )
    _assert_unit(
        "initializationPromise" in record_popup_js
        and "initializeAllStudentsRecordPopup().catch" in record_popup_js
        and "installReadOnlyAssignmentGuard" in record_popup_js
        and "#vidModal.student-work-layout .vid-row" in record_popup_js
        and "#vidModal.student-work-layout .vid-exclude-high-btn" in record_popup_js
        and "#testModal.student-work-layout .test-save-btn" in record_popup_js
        and "activeVideoAccessMode === 'all-students-readonly'" in video_modal_js
        and "patchVideoProgressEntry(today, sid, progressPatch)" in video_modal_js,
        "all-students popup initialization must be single-flight, block assignments, and save only video progress state",
    )
    _assert_unit(
        "initHoverTooltip as initAdminHoverTooltip" in record_popup_js
        and "initAdminHoverTooltip();" in record_popup_js
        and "initVideoModal();" in record_popup_js
        and "#todayWrap, #doneWrap, #allWrap" in admin_hover_js,
        "all-students record popup must initialize the shared admin tooltip and assignment popups",
    )
    _assert_unit(
        "adminState.homeworkBooksBySid = allState.homeworkBooksBySid" in record_popup_js
        and "state.homeworkBooksBySid" in admin_hover_js
        and "stu.subBook" not in admin_hover_js,
        "the shared admin tooltip must preserve linked homework books on the all-students page",
    )
    _assert_unit(
        "return scheduleEntries.filter(entry => !normalizeSubjectKey(entry?.phase));" in admin_hover_js
        and "student-tooltip-exam-info" in admin_hover_js
        and "escHtml(exam.note || '-')" in admin_hover_js,
        "student tooltip must show school-calendar exam information for subject-neutral schedules",
    )
    _assert_unit(
        'id="tooltipHomeworkActions"' in admin_hover_js
        and "선택한 운영일 기준" not in admin_hover_js
        and "complete.textContent = '숙검 완료';" in log_modal_js
        and "addRow.textContent = '교재 추가';" in log_modal_js
        and "reorderRows.textContent = '교재 순서';" in log_modal_js
        and "removeRow.textContent = '교재 제거';" in log_modal_js
        and 'id="hwRemoveRow"' in log_modal_js
        and 'id="hwReorderRows"' in log_modal_js
        and "actionHost.append(complete);" in log_modal_js
        and log_modal_js.index("actionHost.append(complete);") < log_modal_js.index("actionHost.append(addRow);") < log_modal_js.index("actionHost.append(reorderRows);") < log_modal_js.index("actionHost.append(removeRow);")
        and "if (save) save.hidden = true;" in log_modal_js
        and not re.search(
            r"#hwRemoveRow\s*,?[^{}]*\{[^{}]*display\s*:\s*none",
            student_work_light_css,
        ),
        "tooltip homework header must expose compact complete/add/reorder/remove actions in order and hide the separate save control",
    )
    _assert_unit(
        "const itemLabel = `${index + 1}번째 교재${book ? ` ${book}` : ''}`;" in log_modal_js
        and "canonicalEditor.setAttribute('aria-label', `${index + 1}번째 숙제 상세`);" in log_modal_js
        and "moveUp.setAttribute('aria-label', `${itemLabel} 위로 이동`);" in log_modal_js
        and "moveDown.setAttribute('aria-label', `${itemLabel} 아래로 이동`);" in log_modal_js,
        "homework reorder controls must keep unique position-aware labels and refresh canonical row numbering",
    )
    _assert_unit(
        'class="hw-del-btn"' not in log_modal_js
        and "function setHomeworkRemoveSelection(active)" in log_modal_js
        and "function removeHomeworkRow(item)" in log_modal_js
        and "button.hw-del-btn, button.hw-remove-choice" in log_modal_js
        and "setHomeworkRemoveSelection(!homeworkRemoveSelectionActive);" in log_modal_js
        and "ensureMinimumHomeworkRows(2);" in log_modal_js
        and "removeLastHomeworkRow" not in log_modal_js
        and "canonicalHomework.removedAssignmentIds.add(assignmentId);" in log_modal_js
        and ".hw-remove-choice" in student_work_light_css
        and "#hwBody.is-remove-selecting .hwItem" in student_work_light_css,
        "homework removal must let the user choose a row, preserve canonical deletion, and restore the two default slots",
    )
    _assert_unit(
        "bubble.style.left = `${clamped}%`;" in log_modal_js
        and "bubble.style.transform = `translateX(${-clamped}%)`;" in log_modal_js
        and "#adminSchoolTip .pctBubble{ max-width:100%; box-sizing:border-box;" in log_modal_js,
        "homework progress bubbles must stay inside the tooltip at both range endpoints",
    )
    _assert_unit(
        ".student-tooltip-homework-host" in log_modal_js
        and "overflow-y:auto;" in log_modal_js
        and ".student-tooltip-homework-actions button" in log_modal_js
        and "height:20px !important;" in log_modal_js
        and "#adminSchoolTip .hw-actions{ display:none !important; }" in log_modal_js
        and "display:flex !important;" in video_modal_js
        and "flex-direction:column !important;" in video_modal_js
        and "overflow:hidden !important;" in video_modal_js,
        "student tooltip must keep exam information fixed while only the compact homework area scrolls",
    )
    _assert_unit(
        "all-students-readonly" in log_modal_js
        and "isContextMenuOnlyAccess" in log_modal_js
        and "applyReadOnlyRecordAccess" in log_modal_js
        and "window.openStudentPopupsForRow = openStudentPopupsForRow" in log_modal_js,
        "admin unified popup launcher must preserve read-only records and context-menu-only progress edits",
    )
    _assert_unit(
        "studentPopupMobileNav" in video_modal_js
        and "data-student-popup-active" in video_modal_js
        and "@media (max-width: 900px)" in video_modal_js,
        "the shared unified popup layout must keep all four surfaces accessible on compact and tablet screens",
    )
    _assert_unit(
        "ns_sb1" not in add_student_js and "subBook1" not in add_student_js,
        "new students must not recreate the retired legacy sub-book fields",
    )


def run_progress_rule_unit_checks() -> None:
    from core.progress_rules import (
        PROGRESS_ALL_STUDENTS_META_KEY,
        PROGRESS_MANUAL_META_KEY,
        TEST_ASSIGN_CHANGE_ORDER_META_KEY,
        TEST_ASSIGN_TOUCHED_KEYS_META_KEY,
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

    unit_label = "단원평가 / 대수 / Lv.5 / 1회차 / 단원"
    school_label = "학군지 기출 / 대수 / 중상 / 기말고사 / 학군지"
    first_test_batch = merge_progress_day_sid(
        {},
        {
            "tests": {unit_label: "assigned", school_label: "assigned"},
            TEST_ASSIGN_TOUCHED_KEYS_META_KEY: [unit_label, school_label],
        },
    )
    first_order = first_test_batch.get(TEST_ASSIGN_CHANGE_ORDER_META_KEY, {})
    _assert_unit(
        first_order.get(unit_label) == first_order.get(school_label) == 1,
        "tests changed in one save must share one assignment-change order",
    )
    school_reassigned = merge_progress_day_sid(
        first_test_batch,
        {
            "tests": {unit_label: "assigned", school_label: "assigned"},
            TEST_ASSIGN_TOUCHED_KEYS_META_KEY: [school_label],
        },
    )
    reassigned_order = school_reassigned.get(TEST_ASSIGN_CHANGE_ORDER_META_KEY, {})
    _assert_unit(
        reassigned_order.get(unit_label) == 1 and reassigned_order.get(school_label) == 2,
        "reassigning an unchanged existing test must make only that test newest",
    )
    unit_completed = merge_progress_day_sid(
        school_reassigned,
        {"tests": {unit_label: "done", school_label: "assigned"}},
    )
    completed_order = unit_completed.get(TEST_ASSIGN_CHANGE_ORDER_META_KEY, {})
    _assert_unit(
        completed_order.get(unit_label) == 3 and completed_order.get(school_label) == 2,
        "a later completion change must outrank an in-progress assignment",
    )
    unit_removed = merge_progress_day_sid(
        unit_completed,
        {"tests": {unit_label: "", school_label: "assigned"}},
    )
    _assert_unit(
        unit_label not in unit_removed.get(TEST_ASSIGN_CHANGE_ORDER_META_KEY, {}),
        "removed tests must not retain stale assignment-change ordering metadata",
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


def run_student_previous_video_review_rule_unit_checks() -> None:
    """Exercise the pure pre-date review-state projection with adversarial fixtures."""
    from copy import deepcopy

    from core.video_review_rules import resolve_video_review_states_before_date

    sid_keys = ("s1", "007", "7")
    progress = {
        "2026-05-30": {
            "s1": {
                "m1": "done",
                "m2": "interrupted",
                "m3": "skip",
                "m4": "none",
                "m9": "none",
                "m15": "none",
                "m16": "skip",
                "m10": "interrupted",
                "m11": "done",
                "m14": "interrupted",
                "m-later-skip": "done",
                "m-malformed": {"nested": "bad"},
                "tests": {"unit-1": "done"},
                "__manualProgressMids": {"m9": True, "m15": True, "m16": True},
            },
            "7": {"m7": "done"},
            "s1-malformed": "not-a-day-map",
        },
        "2026-05-31": {
            "s1": {"m1": "none", "m2": "done", "m-later-skip": "skip"},
            "7": {"m9": "skip"},
        },
        "2026-06-01": {"s1": {"m-current": "done"}},
        "2026-02-30": {"s1": {"m-invalid": "done"}},
        "not-a-date": {"s1": {"m-invalid-key": "done"}},
        "__metadata": {"s1": {"m-meta": "done"}},
        "2026-05-29": "malformed-day",
    }
    watch = {
        "2026-05-30": {
            "s1": {
                "m1": {"last": 100, "dur": 100},
                "m2": {"last": 100, "dur": 100},
                "m8": {"last": 10, "dur": 100},
                "m9": {"last": 100, "dur": 100},
                "m10": {"last": 10, "dur": 100},
                "m11": {"last": 4, "dur": 100},
                "m12": {"last": 5, "dur": 100},
                "m13": {"last": 4, "dur": 100},
                "m14": {"last": 100, "dur": 100},
                "m-malformed": {"last": 100, "dur": 100},
                "m-watch-malformed": "not-a-watch-entry",
            },
            "7": {"m7": {"last": 4, "dur": 100}},
        },
        "2026-05-31": {
            "s1": {
                "m8": {"last": 90, "dur": 100},
                "m9": {"last": 90, "dur": 100},
                "m15": {"last": 100, "dur": 100},
                "m16": {"last": 100, "dur": 100},
                "m10": {"last": 90, "dur": 100},
                "m11": {"last": 90, "dur": 100},
            },
            "7": {"m7": {"last": 100, "dur": 100}},
        },
        "2026-06-01": {"s1": {"m-future": {"last": 100, "dur": 100}}},
        "2026-02-30": {"s1": {"m-invalid": {"last": 100, "dur": 100}}},
        "__metadata": {"s1": {"m-meta": {"last": 100, "dur": 100}}},
    }
    progress_before = deepcopy(progress)
    watch_before = deepcopy(watch)

    result = resolve_video_review_states_before_date(
        progress,
        watch,
        sid_keys=sid_keys,
        before_date="2026-06-01",
    )
    _assert_unit(
        result == {
            "m2": {"status": "done", "eventDate": "2026-05-31"},
            "m8": {"status": "done", "eventDate": "2026-05-31"},
            "m10": {"status": "done", "eventDate": "2026-05-31"},
            "m11": {"status": "done", "eventDate": "2026-05-31"},
            "m12": {"status": "interrupted", "eventDate": "2026-05-30"},
            "m14": {"status": "interrupted", "eventDate": "2026-05-30"},
        },
        "pre-date review resolver must apply strict cutoffs and latest authoritative statuses",
    )
    _assert_unit("m1" not in result, "later none must remove an older done review")
    _assert_unit("m-later-skip" not in result, "later skip must remove an older done review")
    _assert_unit("m3" not in result and "m4" not in result, "skip/none are never review members")
    _assert_unit("m9" not in result, "same-day progress presence must block a watch fallback")
    _assert_unit("m15" not in result and "m16" not in result, "manual white/skip overrides must survive later watch-only updates")
    _assert_unit("m13" not in result, "watch below five percent must not qualify")
    _assert_unit("m-current" not in result and "m-future" not in result, "same-day/future events are excluded")
    _assert_unit("m-invalid" not in result and "m-meta" not in result, "invalid and metadata dates are excluded")
    _assert_unit("m-malformed" not in result and "m-watch-malformed" not in result, "malformed progress/watch values are excluded")

    canonical_skip = resolve_video_review_states_before_date(
        {"2026-05-30": {"007": {"m-alias": "skip"}, "7": {"m-alias": "done"}}},
        {},
        sid_keys=("007", "7"),
        before_date="2026-06-01",
    )
    _assert_unit("m-alias" not in canonical_skip, "canonical skip must not be overridden by a fallback alias")

    canonical_none = resolve_video_review_states_before_date(
        {"2026-05-30": {"007": {"m-alias": "none"}, "7": {"m-alias": "done"}}},
        {},
        sid_keys=("007", "7"),
        before_date="2026-06-01",
    )
    _assert_unit("m-alias" not in canonical_none, "canonical none must not be overridden by a fallback alias")

    canonical_done = resolve_video_review_states_before_date(
        {"2026-05-30": {"007": {"m-alias": "done"}, "7": {"m-alias": "none"}}},
        {},
        sid_keys=("007", "7"),
        before_date="2026-06-01",
    )
    _assert_unit(
        canonical_done.get("m-alias") == {"status": "done", "eventDate": "2026-05-30"},
        "canonical done must not be cleared by a fallback alias",
    )

    alias_fallback = resolve_video_review_states_before_date(
        {"2026-05-30": {"7": {"m-alias": "done"}}},
        {},
        sid_keys=("007", "7"),
        before_date="2026-06-01",
    )
    _assert_unit(
        alias_fallback.get("m-alias") == {"status": "done", "eventDate": "2026-05-30"},
        "a fallback alias must remain usable when the canonical SID map is absent",
    )

    canonical_progress_clear = resolve_video_review_states_before_date(
        {"2026-05-30": {"007": {"m-alias": "none"}}},
        {"2026-05-30": {"7": {"m-alias": {"last": 100, "dur": 100}}}},
        sid_keys=("007", "7"),
        before_date="2026-06-01",
    )
    _assert_unit(
        "m-alias" not in canonical_progress_clear,
        "canonical progress presence must block a watch fallback alias",
    )

    malformed_watch = resolve_video_review_states_before_date(
        {},
        {"2026-05-30": {"007": {"m-watch": {"completed": "false", "last": 0, "dur": 0}}}},
        sid_keys=("007", "7"),
        before_date="2026-06-01",
    )
    _assert_unit("m-watch" not in malformed_watch, "watch completed string false must not qualify as done")

    boolean_watch = resolve_video_review_states_before_date(
        {},
        {"2026-05-30": {"007": {"m-watch": {"completed": True, "last": 0, "dur": 0}}}},
        sid_keys=("007", "7"),
        before_date="2026-06-01",
    )
    _assert_unit(
        boolean_watch.get("m-watch") == {"status": "done", "eventDate": "2026-05-30"},
        "actual boolean watch completion must qualify as done",
    )

    ratio_watch = resolve_video_review_states_before_date(
        {},
        {
            "2026-05-30": {
                "007": {
                    "m-interrupted": {"completed": "false", "last": 5, "dur": 100},
                    "m-done": {"completed": "false", "last": 90, "dur": 100},
                },
            },
        },
        sid_keys=("007", "7"),
        before_date="2026-06-01",
    )
    _assert_unit(
        ratio_watch == {
            "m-interrupted": {"status": "interrupted", "eventDate": "2026-05-30"},
            "m-done": {"status": "done", "eventDate": "2026-05-30"},
        },
        "ratio thresholds must remain authoritative when completion metadata is malformed",
    )

    _assert_unit(progress == progress_before, "resolver must not mutate progress inputs")
    _assert_unit(watch == watch_before, "resolver must not mutate watch inputs")


def run_progress_batch_sids_unit_checks() -> None:
    from flask import Flask
    import routes.api_basic as api_basic
    import routes.api_progress as api_progress

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

    original_loader = api_progress._load_progress_strict
    api_progress._load_progress_strict = lambda: progress_fixture
    try:
        app = Flask("verify-progress-batch-sids")
        app.register_blueprint(api_basic.bp_api_basic)
        app.register_blueprint(api_progress.bp_api_progress)
        client = app.test_client()

        progress_rules = [rule for rule in app.url_map.iter_rules() if rule.rule == "/api/progress"]
        _assert_unit(len(progress_rules) == 1, "progress GET must have one registered owner")
        _assert_unit(
            progress_rules[0].endpoint == "api_progress.api_progress",
            "progress GET must be owned by the dedicated progress blueprint",
        )

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
        api_progress._load_progress_strict = original_loader


def run_progress_read_cache_unit_checks() -> None:
    import core.progress_store as progress_store
    import routes.api_basic as api_basic

    original_path = api_basic.PRG_PATH

    with tempfile.TemporaryDirectory(prefix="verify-progress-cache-") as tmp:
        progress_path = pathlib.Path(tmp) / "progress.json"
        progress_path.write_text('{"2026-06-01":{"s1":{"m1":"done"}}}', encoding="utf-8")
        try:
            api_basic.PRG_PATH = progress_path
            progress_store.reset_progress_cache()

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

            import concurrent.futures

            class SlowProgressPath:
                def __init__(self, path: pathlib.Path):
                    self.path = path
                    self.read_count = 0

                def stat(self):
                    return self.path.stat()

                def read_text(self, encoding: str):
                    self.read_count += 1
                    time.sleep(0.05)
                    return self.path.read_text(encoding=encoding)

            slow_path = SlowProgressPath(progress_path)
            api_basic.PRG_PATH = slow_path
            progress_store.reset_progress_cache()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                concurrent_reads = list(pool.map(lambda _: api_basic._load_progress_strict(), range(2)))
            _assert_unit(
                slow_path.read_count == 1 and concurrent_reads[0] is concurrent_reads[1],
                "concurrent cold progress reads must share one JSON parse",
            )

            api_basic.PRG_PATH = progress_path
            saved = {"2026-06-03": {"s4": {"tests": {"unit-1": "assigned"}}}}
            progress_store.save_progress_strict(progress_path, saved)
            saved_text = progress_path.read_text(encoding="utf-8")
            _assert_unit("\n" not in saved_text, "progress writes must use compact JSON on the hot path")
            _assert_unit(
                api_basic._load_progress_strict() is saved,
                "progress writes must publish the saved object to the read cache",
            )
        finally:
            api_basic.PRG_PATH = original_path
            progress_store.reset_progress_cache()


def run_video_completion_unit_checks() -> None:
    from core.progress_rules import PROGRESS_MANUAL_META_KEY
    import routes.api_basic as api_basic

    date = "2026-06-06"
    student = {
        "id": "s1",
        "curriculum": "ALG",
        "subCurriculum": "BASE",
        "autoVideoAssignCount": 2,
        "day1": "토1",
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
        "blue done plus red skip video progress must finish the course",
    )

    reopened_progress = {
        "2026-06-04": {"007": {"m1": "done"}},
        "2026-06-05": {
            "7": {
                "m1": "interrupted",
                PROGRESS_MANUAL_META_KEY: {"m1": True},
            },
        },
    }
    reopened_watch = {
        "2026-06-04": {"007": {"m1": {"last": 100, "dur": 100, "completed": True}}},
    }
    reopened_blocked = api_basic._build_auto_assignment_blocked_by_sid(
        reopened_progress,
        reopened_watch,
    )
    _assert_unit(
        "m1" not in api_basic._blocked_mids_for_sid(reopened_blocked, "007")
        and "m1" not in api_basic._blocked_mids_for_sid(reopened_blocked, "7"),
        "a later manual interrupted state must reopen a completed video for every numeric SID alias",
    )

    reopened_none_progress = {
        "2026-06-04": {"s1": {"m1": "done"}},
        "2026-06-05": {
            "s1": {
                "m1": "none",
                PROGRESS_MANUAL_META_KEY: {"m1": True},
            },
        },
    }
    reopened_none_watch = {
        "2026-06-04": {"s1": {"m1": {"last": 100, "dur": 100, "completed": True}}},
    }
    _assert_unit(
        "m1" not in api_basic._blocked_mids_for_sid(
            api_basic._build_auto_assignment_blocked_by_sid(reopened_none_progress, reopened_none_watch),
            "s1",
        ),
        "a later manual white state must reopen a completed video despite historical completed watch data",
    )

    automatic_interrupted = {
        "2026-06-04": {"s1": {"m1": "done"}},
        "2026-06-05": {"s1": {"m1": "interrupted"}},
    }
    _assert_unit(
        "m1" in api_basic._blocked_mids_for_sid(
            api_basic._build_auto_assignment_blocked_by_sid(automatic_interrupted, {}),
            "s1",
        ),
        "an unmarked interrupted state must not silently reopen a completed video",
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
        api_basic._sid_lookup(fixed.get(date, {}), "s1") == {"videos": ["m1"], "source": "auto"},
        "completed progress must preserve the date-bound automatic video snapshot",
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

    review_videos = [
        {"mid": f"m{chapter}", "curriculum": "ALG", "subCurriculum": "BASE", "chapter": str(chapter)}
        for chapter in range(1, 8)
    ]
    auto_new_progress = {date: {"s1": {"videos": ["m5", "m6", "m7"], "source": "auto"}}}
    self_study_progress = {
        "2026-06-05": {
            "s1": {"m1": "done", "m2": "done", "m3": "done", "m4": "done"},
        },
    }
    self_study_daily = api_basic._ensure_today_auto_assign(
        auto_new_progress,
        [student],
        review_videos,
        self_study_progress,
        date_key=date,
        watch={},
        logs={date: {"s1": {"selfStudy": True}}},
    )
    _assert_unit(
        api_basic._sid_lookup(self_study_daily.get(date, {}), "s1") == {
            "videos": ["m2", "m3", "m4"],
            "source": "selfStudy",
        },
        "daily self-study must replace auto new progress with the previous three videos",
    )

    scheduled_self_study_student = {
        **student,
        "day1": "토",
        "selfStudyDays": {"day1": True},
    }
    previous_progress = {
        "2026-06-05": {
            "s1": {"m1": "done", "m2": "done", "m3": "done", "m4": "done"},
        },
    }
    self_study_scheduled = api_basic._ensure_today_auto_assign(
        {},
        [scheduled_self_study_student],
        review_videos,
        previous_progress,
        date_key=date,
        watch={},
        logs={date: {}},
    )
    _assert_unit(
        api_basic._sid_lookup(self_study_scheduled.get(date, {}), "s1") == {
            "videos": ["m2", "m3", "m4"],
            "source": "selfStudy",
        },
        "scheduled self-study must receive the three videos before the next automatic progress video",
    )


def run_video_completion_source_checks() -> None:
    video_modal_js = (ROOT / "static/js/admin/features/videoModal.js").read_text("utf-8")
    log_modal_js = (ROOT / "static/js/admin/features/logModal.js").read_text("utf-8")

    _assert_unit(
        "VIDEO_PROGRESS_FINISHED_STATUSES = new Set(['done', 'skip'])" in video_modal_js,
        "video modal must define green/red finished video progress statuses",
    )
    _assert_unit(
        "function isFinishedVideoProgressStatus" in video_modal_js,
        "video modal must use a named finished progress predicate",
    )

    _assert_unit(
        "mids.every(mid => isFinishedVideoProgressStatus(latest[mid]))" in video_modal_js,
        "video modal course completion must count green done plus red skip",
    )
    _assert_unit(
        "clearVideoAssignmentForDateSid" not in log_modal_js
        and "allProgressDone" not in log_modal_js,
        "log save must not delete a dated video snapshot when every row is finished",
    )


def run_video_assignment_snapshot_unit_checks() -> None:
    from core.progress_rules import PROGRESS_MANUAL_META_KEY
    import routes.api_basic as api_basic
    from core.update_assignment_rules import remove_future_auto_assignments

    date = "2026-06-06"  # Saturday
    videos = [
        {"mid": f"m{index}", "curriculum": "ALG", "subCurriculum": "BASE", "chapter": str(index)}
        for index in range(1, 8)
    ]
    scheduled = {
        "id": "scheduled",
        "curriculum": "ALG",
        "subCurriculum": "BASE",
        "autoVideoAssignCount": 2,
        "day1": "토1",
    }
    not_today = {**scheduled, "id": "not-today", "day1": "월1"}
    makeup = {**scheduled, "id": "makeup", "day1": "월1"}
    consecutive_initial = {**scheduled, "id": "consecutive-initial", "day2": "토2"}
    empty_absent = {"by_date": {}, "by_student": {}, "by_slot": {}}

    created = api_basic._ensure_today_auto_assign(
        {},
        [scheduled, not_today, makeup, consecutive_initial],
        videos,
        {},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={date: ["makeup"]},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        api_basic._sid_lookup(created[date], "scheduled")["videos"] == ["m1", "m2"],
        "date initialization assigns the configured count to a Today student",
    )
    _assert_unit(
        api_basic._sid_lookup(created[date], "makeup")["videos"] == ["m1", "m2"],
        "makeup registration makes an extra student eligible for initial assignment",
    )
    makeup_consecutive = {}
    api_basic._ensure_today_auto_assign(
        makeup_consecutive,
        [makeup],
        videos,
        {},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={date: ["makeup"]},
        absent=empty_absent,
        weekend_slots={date: {"makeup": [1, 2]}},
    )
    _assert_unit(
        api_basic._sid_lookup(makeup_consecutive[date], "makeup")["videos"] == ["m1", "m2", "m3", "m4"],
        "makeup registration doubles the configured count across consecutive slots",
    )
    _assert_unit(
        api_basic._sid_lookup(created[date], "not-today") is None,
        "non-Today students never receive automatic video assignments",
    )
    _assert_unit(
        len(api_basic._sid_lookup(created[date], "consecutive-initial")["videos"]) == 4,
        "date initialization doubles the configured count for consecutive classes",
    )

    partial_absence_initial = {}
    api_basic._ensure_today_auto_assign(
        partial_absence_initial,
        [consecutive_initial],
        videos,
        {},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent={
            "by_date": {},
            "by_student": {},
            "by_slot": {date: {"consecutive-initial": [2]}},
        },
        weekend_slots={},
    )
    _assert_unit(
        api_basic._sid_lookup(partial_absence_initial[date], "consecutive-initial")["videos"] == ["m1", "m2"],
        "a slot absence removes the consecutive multiplier during initial assignment",
    )

    weekend_initial = {}
    api_basic._ensure_today_auto_assign(
        weekend_initial,
        [scheduled],
        videos,
        {},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={date: {"scheduled": [1, 2]}},
    )
    _assert_unit(
        api_basic._sid_lookup(weekend_initial[date], "scheduled")["videos"] == ["m1", "m2", "m3", "m4"],
        "date-specific consecutive slots double the configured count",
    )

    absent_updates = {}
    api_basic._ensure_today_auto_assign(
        absent_updates,
        [scheduled],
        videos,
        {},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent={"by_date": {date: ["scheduled"]}, "by_student": {}},
        weekend_slots={},
    )
    _assert_unit(
        api_basic._sid_lookup(absent_updates[date], "scheduled") is None,
        "absent students are excluded from date initialization",
    )

    done_log_updates = {}
    api_basic._ensure_today_auto_assign(
        done_log_updates,
        [scheduled],
        videos,
        {},
        date_key=date,
        watch={},
        logs={date: {"scheduled": {"done": True}}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        api_basic._sid_lookup(done_log_updates[date], "scheduled") is None,
        "students with a completed class log are excluded from date initialization",
    )

    blocked_updates = {}
    api_basic._ensure_today_auto_assign(
        blocked_updates,
        [scheduled],
        videos,
        {"2026-06-05": {"scheduled": {"m1": "done", "m2": "skip"}}},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        api_basic._sid_lookup(blocked_updates[date], "scheduled")["videos"] == ["m3", "m4"],
        "finished progress statuses block candidates during initial assignment",
    )

    watch_blocked_updates = {}
    api_basic._ensure_today_auto_assign(
        watch_blocked_updates,
        [scheduled],
        videos,
        {},
        date_key=date,
        watch={"2026-06-05": {"scheduled": {"m1": {"completed": True}}}},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        api_basic._sid_lookup(watch_blocked_updates[date], "scheduled")["videos"] == ["m2", "m3"],
        "completed watch history blocks candidates during initial assignment",
    )

    future_history_updates = {}
    api_basic._ensure_today_auto_assign(
        future_history_updates,
        [scheduled],
        videos,
        {"2026-06-07": {"scheduled": {"m1": "done"}}},
        date_key=date,
        watch={"2026-06-08": {"scheduled": {"m2": {"completed": True}}}},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        api_basic._sid_lookup(future_history_updates[date], "scheduled")["videos"] == ["m1", "m2"],
        "future progress and watch records never block today's initial candidates",
    )

    manual_clear_updates = {}
    api_basic._ensure_today_auto_assign(
        manual_clear_updates,
        [scheduled],
        videos,
        {
            "2026-06-05": {
                "scheduled": {
                    "m1": "done",
                    "m2": "none",
                    PROGRESS_MANUAL_META_KEY: {"m2": True},
                }
            }
        },
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        api_basic._sid_lookup(manual_clear_updates[date], "scheduled")["videos"] == ["m2", "m3"],
        "manual white progress can make a previously blocked candidate eligible again",
    )

    stable_snapshot = {
        "videos": ["m1", "m2"],
        "source": "auto",
        "note": "keep metadata",
    }
    stable_updates = {date: {"scheduled": stable_snapshot}}
    after_progress = api_basic._ensure_today_auto_assign(
        stable_updates,
        [scheduled],
        videos,
        {date: {"scheduled": {"m1": "done"}}},
        date_key=date,
        watch={date: {"scheduled": {"m2": {"completed": True}}}},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        after_progress[date]["scheduled"] == {
            "videos": ["m1", "m2"],
            "source": "auto",
            "note": "keep metadata",
        },
        "normal assignment hydration preserves the original daily snapshot",
    )

    curriculum_change_videos = [
        {"mid": "able-1", "curriculum": "CALC1", "subCurriculum": "A:Ble", "chapter": "1"},
        {"mid": "able-2", "curriculum": "CALC1", "subCurriculum": "A:Ble", "chapter": "2"},
        {"mid": "apex-1", "curriculum": "CALC1", "subCurriculum": "APEX", "chapter": "1"},
        {"mid": "apex-2", "curriculum": "CALC1", "subCurriculum": "APEX", "chapter": "2"},
        {"mid": "apex-3", "curriculum": "CALC1", "subCurriculum": "APEX", "chapter": "3"},
        {"mid": "outside-1", "curriculum": "OTHER", "subCurriculum": "APEX", "chapter": "1"},
    ]
    apex_student = {
        **scheduled,
        "id": "apex-current",
        "curriculum": "CALC1",
        "subCurriculum": "APEX",
    }
    stale_previous_curriculum = {
        date: {
            "apex-current": {
                "videos": ["able-1", "outside-1"],
                "source": "auto",
                "note": "keep auto metadata",
            }
        }
    }
    api_basic._ensure_today_auto_assign(
        stale_previous_curriculum,
        [apex_student],
        curriculum_change_videos,
        {},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        stale_previous_curriculum[date]["apex-current"] == {
            "videos": ["apex-1", "apex-2"],
            "source": "auto",
            "note": "keep auto metadata",
        },
        "curriculum changes rebase automatic snapshots onto the exact current curriculum only",
    )

    mixed_curriculum_snapshot = {
        date: {
            "apex-current": {
                "videos": ["apex-1", "able-1", "apex-2"],
                "source": "auto",
                "note": "preserve valid slots",
            }
        }
    }
    api_basic._ensure_today_auto_assign(
        mixed_curriculum_snapshot,
        [apex_student],
        curriculum_change_videos,
        {date: {"apex-current": {"apex-1": "done"}}},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        mixed_curriculum_snapshot[date]["apex-current"] == {
            "videos": ["apex-1", "apex-2", "apex-3"],
            "source": "auto",
            "note": "preserve valid slots",
        },
        "curriculum rebase keeps valid completed slots and replaces only stale slots without resizing",
    )

    manual_cross_curriculum = {
        date: {
            "apex-current": {
                "videos": ["able-1", "outside-1"],
                "source": "manual",
            }
        }
    }
    api_basic._ensure_today_auto_assign(
        manual_cross_curriculum,
        [apex_student],
        curriculum_change_videos,
        {},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        manual_cross_curriculum[date]["apex-current"] == {
            "videos": ["able-1", "outside-1"],
            "source": "manual",
        },
        "manual cross-curriculum additions remain independent from automatic curriculum rebasing",
    )

    inactive_apex_student = {
        **apex_student,
        "id": "apex-not-today",
        "day1": "월1",
    }
    inactive_stale_auto = {
        date: {
            "apex-not-today": {
                "videos": ["apex-1", "able-1"],
                "source": "auto",
                "note": "inactive metadata",
            }
        }
    }
    api_basic._ensure_today_auto_assign(
        inactive_stale_auto,
        [inactive_apex_student],
        curriculum_change_videos,
        {},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        inactive_stale_auto[date]["apex-not-today"] == {
            "videos": ["apex-1"],
            "source": "auto",
            "note": "inactive metadata",
        },
        "inactive automatic snapshots drop previous-curriculum MIDs without assigning new work",
    )

    makeup_snapshot = {"videos": ["m5"], "source": "auto", "note": "makeup snapshot"}
    makeup_stable_updates = {date: {"makeup": dict(makeup_snapshot)}}
    api_basic._ensure_today_auto_assign(
        makeup_stable_updates,
        [makeup],
        videos,
        {},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={date: ["makeup"]},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        makeup_stable_updates[date]["makeup"] == makeup_snapshot,
        "makeup registration does not re-pick an existing automatic snapshot",
    )

    completed_snapshot = {"videos": ["m1", "m2"], "source": "auto"}
    completed_updates = {date: {"scheduled": dict(completed_snapshot)}}
    completed = api_basic._ensure_today_auto_assign(
        completed_updates,
        [scheduled],
        videos[:2],
        {date: {"scheduled": {"m1": "done", "m2": "skip"}}},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        api_basic._sid_lookup(completed.get(date, {}), "scheduled") == completed_snapshot,
        "course completion preserves the already-created automatic snapshot",
    )

    completed_without_snapshot = {}
    api_basic._ensure_today_auto_assign(
        completed_without_snapshot,
        [scheduled],
        videos[:2],
        {date: {"scheduled": {"m1": "done", "m2": "skip"}}},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        api_basic._sid_lookup(completed_without_snapshot[date], "scheduled") is None,
        "course completion blocks a first assignment when no snapshot exists",
    )

    manual_empty = {date: {"scheduled": {"videos": [], "source": "manual"}}}
    api_basic._ensure_today_auto_assign(
        manual_empty,
        [scheduled],
        videos,
        {},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        manual_empty[date]["scheduled"] == {"videos": [], "source": "manual"},
        "an explicit empty manual assignment is not resurrected",
    )

    self_study = {date: {"scheduled": {"videos": ["m1"], "source": "selfStudy"}}}
    api_basic._ensure_today_auto_assign(
        self_study,
        [scheduled],
        videos,
        {},
        date_key=date,
        watch={},
        logs={date: {"scheduled": {"selfStudy": True}}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        self_study[date]["scheduled"] == {"videos": ["m1"], "source": "selfStudy"},
        "self-study assignments remain protected from automatic reconciliation",
    )

    self_study_unscheduled = {
        **scheduled,
        "id": "self-study-unscheduled",
        "day1": "월1",
    }
    self_study_auto = {
        date: {
            "self-study-unscheduled": {
                "videos": ["m3"],
                "source": "auto",
            },
        },
    }
    api_basic._ensure_today_auto_assign(
        self_study_auto,
        [self_study_unscheduled],
        videos,
        {"2026-06-05": {"self-study-unscheduled": {"m1": "done", "m2": "interrupted"}}},
        date_key=date,
        watch={},
        logs={date: {"self-study-unscheduled": {"selfStudy": True}}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        self_study_auto[date]["self-study-unscheduled"] == {
            "videos": ["m1"],
            "source": "selfStudy",
        },
        "self-study must reconcile an existing automatic snapshot with completed videos only",
    )

    scheduled_self_study = {
        **scheduled,
        "id": "self-study-scheduled",
        "day1": "토1",
        "selfStudyDays": ["day1"],
    }
    scheduled_self_study_updates = {
        date: {
            "self-study-scheduled": {
                "videos": ["m3"],
                "source": "auto",
            },
        },
    }
    api_basic._ensure_today_auto_assign(
        scheduled_self_study_updates,
        [scheduled_self_study],
        videos,
        {"2026-06-05": {"self-study-scheduled": {"m1": "done", "m2": "interrupted"}}},
        date_key=date,
        watch={},
        logs={date: {}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        scheduled_self_study_updates[date]["self-study-scheduled"] == {
            "videos": ["m1"],
            "source": "selfStudy",
        },
        "scheduled self-study must use the same completed-only review path without a daily log flag",
    )

    self_study_no_history = {
        date: {
            "self-study-unscheduled": {
                "videos": ["m3"],
                "source": "auto",
            },
        },
    }
    api_basic._ensure_today_auto_assign(
        self_study_no_history,
        [self_study_unscheduled],
        videos,
        {},
        date_key=date,
        watch={},
        logs={date: {"self-study-unscheduled": {"selfStudy": True}}},
        extra={},
        absent=empty_absent,
        weekend_slots={},
    )
    _assert_unit(
        api_basic._sid_lookup(self_study_no_history[date], "self-study-unscheduled") is None,
        "self-study must cancel an automatic assignment when no eligible review anchor exists",
    )

    self_study_absent = {
        date: {
            "self-study-unscheduled": {
                "videos": ["m3"],
                "source": "auto",
            },
        },
    }
    api_basic._ensure_today_auto_assign(
        self_study_absent,
        [self_study_unscheduled],
        videos,
        {},
        date_key=date,
        watch={},
        logs={date: {"self-study-unscheduled": {"selfStudy": True}}},
        extra={},
        absent={"by_date": {date: ["self-study-unscheduled"]}, "by_student": {}},
        weekend_slots={},
    )
    _assert_unit(
        self_study_absent[date]["self-study-unscheduled"] == {
            "videos": ["m3"],
            "source": "auto",
        },
        "absence must keep automatic reconciliation disabled even when self-study is selected",
    )

    consecutive_student = {**scheduled, "id": "consecutive"}
    consecutive_updates = {
        date: {"consecutive": {"videos": ["m1", "m2"], "source": "auto", "custom": "keep"}}
    }
    weekend_slots = {date: {"consecutive": [1, 2]}}
    expanded = api_basic._expand_consecutive_auto_assignment_in_updates(
        consecutive_updates,
        date,
        "consecutive",
        [consecutive_student],
        videos,
        {date: {"consecutive": {"m2": "done"}}},
        watch={},
        weekend_slots=weekend_slots,
    )
    _assert_unit(
        not expanded
        and consecutive_updates[date]["consecutive"] == {
            "videos": ["m1", "m2"],
            "source": "auto",
            "custom": "keep",
        },
        "consecutive slot changes must preserve an existing automatic snapshot",
    )
    reversed_slots = {
        date: {"consecutive": {"videos": ["m1", "m2"], "source": "auto", "custom": "keep"}}
    }
    _assert_unit(
        not api_basic._expand_consecutive_auto_assignment_in_updates(
            reversed_slots,
            date,
            "consecutive",
            [consecutive_student],
            videos,
            {},
            watch={},
            weekend_slots={date: {"consecutive": [1]}},
        )
        and reversed_slots[date]["consecutive"]["videos"] == ["m1", "m2"],
        "leaving a consecutive block must not shrink the existing snapshot",
    )

    cleanup_fixture = {
        "2026-06-06": {"today-auto": {"videos": ["m1"], "source": "auto"}},
        "2026-06-07": {
            "future-auto": {"videos": ["m2"], "source": "auto"},
            "future-manual": {"videos": ["m3"], "source": "manual"},
            "future-self-study": {"videos": ["m4"], "source": "selfStudy"},
        },
        "2026-06-08": {"future-auto-only": {"videos": ["m5"], "source": "auto"}},
    }
    cleanup_summary = remove_future_auto_assignments(cleanup_fixture, today=date)
    _assert_unit(
        cleanup_summary["removedAuto"] == 2
        and cleanup_summary["affectedDates"] == ["2026-06-07", "2026-06-08"],
        "future automatic cleanup reports only named source:auto removals",
    )
    _assert_unit(
        cleanup_fixture == {
            "2026-06-06": {"today-auto": {"videos": ["m1"], "source": "auto"}},
            "2026-06-07": {
                "future-manual": {"videos": ["m3"], "source": "manual"},
                "future-self-study": {"videos": ["m4"], "source": "selfStudy"},
            },
        },
        "future automatic cleanup preserves today, manual, and self-study assignments and removes empty dates",
    )

    return


def run_video_assignment_route_hook_unit_checks() -> None:
    from flask import Flask
    import routes.api_basic as api_basic
    import routes.api_fs as api_fs
    import routes.api_logs as api_logs
    import routes.api_materials as api_materials
    import routes.api_schedule_overrides as api_schedule_overrides
    import routes.api_students as api_students
    import routes.api_updates as api_updates

    extra_path = object()
    weekend_path = object()
    students_path = object()
    updates_path = object()
    store = {"extra": {}, "weekend": {}, "students": [], "updates": {}}
    init_calls = []
    expand_calls = []
    notification_calls = []
    lock_events = []
    student_io_events = []
    lock_state = {"depth": 0, "path": None}
    original = {
        "EXTRA_PATH": api_basic.EXTRA_PATH,
        "WEEKEND_SLOTS_PATH": api_basic.WEEKEND_SLOTS_PATH,
        "STU_PATH": api_basic.STU_PATH,
        "UPD_PATH": api_basic.UPD_PATH,
        "load": api_basic.load,
        "save_atomic": api_basic.save_atomic,
        "load_updates_strict": api_basic.load_updates_strict,
        "save_updates_strict": api_basic.save_updates_strict,
        "absence_barrier": api_basic._auto_assignment_absence_barrier,
        "_load_updates_with_auto_assign": api_basic._load_updates_with_auto_assign,
        "_reconcile_consecutive_auto_assignment": api_basic._reconcile_consecutive_auto_assignment,
        "_today_kst_iso": api_basic._today_kst_iso,
    }
    student_original = {
        "STU_PATH": api_students.STU_PATH,
        "load": api_students.load,
        "save_atomic": api_students.save_atomic,
        "file_lock": api_students.file_lock,
        "_today_kst_iso": api_students._today_kst_iso,
        "enqueue_current_schedule_changes": api_students.enqueue_current_schedule_changes,
        "_person_identity_configured": api_students._person_identity_configured,
    }
    schedule_original = {
        "EXTRA_PATH": api_schedule_overrides.EXTRA_PATH,
        "WEEKEND_SLOTS_PATH": api_schedule_overrides.WEEKEND_SLOTS_PATH,
        "STU_PATH": api_schedule_overrides.STU_PATH,
        "load": api_schedule_overrides.load,
        "save_atomic": api_schedule_overrides.save_atomic,
        "file_lock": api_schedule_overrides.file_lock,
        "_today_kst_iso": api_schedule_overrides._today_kst_iso,
        "enqueue_current_schedule_changes": api_schedule_overrides.enqueue_current_schedule_changes,
    }
    updates_original = {
        "UPD_PATH": api_updates.UPD_PATH,
        "load_updates_strict": api_updates.load_updates_strict,
        "save_updates_strict": api_updates.save_updates_strict,
    }

    def fake_load(path):
        if path is extra_path:
            _assert_unit(lock_state["depth"] == 1, "extra-attend read occurs inside the file lock")
            return store["extra"]
        if path is weekend_path:
            _assert_unit(lock_state["depth"] == 1, "weekend slot read occurs inside the file lock")
            return store["weekend"]
        if path is students_path:
            student_io_events.append(("load", lock_state["depth"]))
            return store["students"]
        if path is updates_path:
            return store["updates"]
        return {}

    def fake_save(path, value, **kwargs):
        if path is extra_path:
            _assert_unit(lock_state["depth"] == 1, "extra-attend save occurs inside the file lock")
            store["extra"] = value
        elif path is weekend_path:
            _assert_unit(lock_state["depth"] == 1, "weekend slot save occurs inside the file lock")
            store["weekend"] = value
        elif path is students_path:
            student_io_events.append(("save", lock_state["depth"]))
            store["students"] = value
        elif path is updates_path:
            store["updates"] = value

    @contextlib.contextmanager
    def fake_file_lock(path):
        _assert_unit(
            path in {extra_path, weekend_path, students_path},
            "route locks its own storage path",
        )
        if path is extra_path:
            label = "extra"
        elif path is weekend_path:
            label = "weekend"
        else:
            label = "students"
        lock_events.append(("enter", label))
        lock_state["depth"] += 1
        lock_state["path"] = path
        try:
            yield
        finally:
            lock_state["depth"] -= 1
            lock_state["path"] = None
            lock_events.append(("exit", label))

    try:
        api_basic.EXTRA_PATH = extra_path
        api_basic.WEEKEND_SLOTS_PATH = weekend_path
        api_schedule_overrides.EXTRA_PATH = extra_path
        api_schedule_overrides.WEEKEND_SLOTS_PATH = weekend_path
        api_schedule_overrides.STU_PATH = students_path
        api_basic.STU_PATH = students_path
        api_students.STU_PATH = students_path
        api_basic.UPD_PATH = updates_path
        api_updates.UPD_PATH = updates_path
        store["students"] = [
            {"id": "s1", "day1": "토1", "curriculum": "ALG", "subCurriculum": "BASE"},
            {"id": "s2", "day1": "토1", "curriculum": "ALG", "subCurriculum": "BASE"},
        ]
        api_basic.load = fake_load
        api_basic.save_atomic = fake_save
        api_basic.load_updates_strict = fake_load
        api_basic.save_updates_strict = fake_save
        api_basic._auto_assignment_absence_barrier = (
            lambda: contextlib.nullcontext()
        )
        api_updates.load_updates_strict = fake_load
        api_updates.save_updates_strict = fake_save
        api_students.load = fake_load
        api_students.save_atomic = fake_save
        api_students.file_lock = fake_file_lock
        api_schedule_overrides.load = fake_load
        api_schedule_overrides.save_atomic = fake_save
        api_schedule_overrides.file_lock = fake_file_lock
        api_basic._today_kst_iso = lambda: "2026-06-06"
        api_students._today_kst_iso = lambda: "2026-06-06"
        api_schedule_overrides._today_kst_iso = lambda: "2026-06-06"
        store["updates"] = {
            "2026-06-07": {"s1": {"videos": ["m1"], "source": "manual"}},
        }
        _assert_unit(
            original["_load_updates_with_auto_assign"](date_key="2026-06-07") == store["updates"],
            "a non-today automatic-assignment load is storage-only",
        )
        api_basic._load_updates_with_auto_assign = lambda **kwargs: init_calls.append(kwargs) or {}
        api_basic._reconcile_consecutive_auto_assignment = lambda *args, **kwargs: expand_calls.append((args, kwargs)) or False
        api_students.enqueue_current_schedule_changes = lambda sids: notification_calls.append(set(sids))
        api_schedule_overrides.enqueue_current_schedule_changes = lambda sids: notification_calls.append(set(sids))
        api_students._person_identity_configured = lambda: False

        app = Flask(__name__)
        api_schedule_overrides.configure_schedule_override_assignment_hooks(
            app,
            initialize_today=api_basic.initialize_auto_assignment_for_schedule_change,
            reconcile=api_basic.reconcile_auto_assignment_for_schedule_change,
        )
        api_students.configure_student_identity_assignment_hooks(
            app,
            initialize_today=api_basic.initialize_auto_assignment_for_student_identity_change,
            reconcile_today=api_basic.reconcile_auto_assignment_for_student_identity_change,
        )
        api_updates.configure_updates_assignment_hooks(
            app,
            initialize_today=api_basic.initialize_auto_assignment_for_updates_read,
            reconcile_self_study=api_basic.reconcile_self_study_assignment_for_updates,
        )
        app.register_blueprint(api_basic.bp_api_basic)
        app.register_blueprint(api_updates.bp_api_updates)
        app.register_blueprint(api_students.bp_api_students)
        app.register_blueprint(api_fs.bp_api_fs)
        app.register_blueprint(api_logs.bp_api_logs)
        app.register_blueprint(api_materials.bp_api_materials)
        app.register_blueprint(api_schedule_overrides.bp_api_schedule_overrides)
        client = app.test_client()
        date = "2026-06-06"

        store["updates"] = {date: {"s1": {"videos": ["m1"], "source": "auto"}}}
        init_calls.clear()
        response = client.get("/api/updates?readOnly=1")
        _assert_unit(response.status_code == 200 and response.get_json() == store["updates"], "read-only updates fetch returns the stable snapshot")
        _assert_unit(not init_calls, "read-only updates fetch never invokes automatic assignment")
        response = client.get("/api/updates")
        _assert_unit(response.status_code == 200 and init_calls, "the normal updates fetch keeps the date-boundary initializer")
        init_calls.clear()

        _assert_unit(client.get("/api/students").status_code == 200, "student collection GET remains available")
        _assert_unit(client.post("/api/students", json=[]).status_code == 405, "retired whole-student POST stays disabled")
        _assert_unit(client.post("/api/materials", json={}).status_code == 405, "retired whole-material POST stays disabled")
        _assert_unit(client.post("/api/logs", json={}).status_code == 405, "retired base log POST stays disabled")
        _assert_unit(client.get("/api/fs/page-folders").status_code == 404, "retired page-folder GET stays unavailable")
        _assert_unit(client.post("/api/fs/page-folders", json={}).status_code == 404, "retired page-folder POST stays unavailable")

        lock_events.clear()
        student_io_events.clear()
        response = client.post("/api/add-student", json={"name": "잠금학생"})
        added_sid = str((response.get_json() or {}).get("id") or "")
        _assert_unit(response.status_code == 200 and added_sid, "student add keeps its response contract")
        _assert_unit(
            lock_events == [("enter", "students"), ("exit", "students")]
            and student_io_events == [("load", 1), ("save", 1)],
            "student add holds the student-store lock across read and save",
        )
        _assert_unit(
            any(str(row.get("id")) == added_sid for row in store["students"]),
            "student add persists the new row",
        )

        lock_events.clear()
        student_io_events.clear()
        response = client.delete(f"/api/students/{added_sid}")
        _assert_unit(response.status_code == 204, "student delete keeps its response contract")
        _assert_unit(
            lock_events == [("enter", "students"), ("exit", "students")]
            and student_io_events == [("load", 1), ("save", 1)],
            "student delete holds the student-store lock across read and save",
        )
        _assert_unit(
            all(str(row.get("id")) != added_sid for row in store["students"]),
            "student delete removes only the selected row",
        )

        other_date = "2026-06-07"
        store["extra"] = {other_date: ["other"]}
        lock_events.clear()
        response = client.patch("/api/extra-attend", json={"date": date, "sids": ["s1"]})
        _assert_unit(response.status_code == 200, "date-scoped extra-attend patch succeeds")
        _assert_unit(
            lock_events == [("enter", "extra"), ("exit", "extra")],
            "extra-attend read-merge-write holds one file lock",
        )
        _assert_unit(store["extra"][other_date] == ["other"], "extra-attend patch preserves another date")
        _assert_unit(store["extra"][date] == ["s1"], "extra-attend patch stores only the requested date")
        _assert_unit(
            [call.get("date_key") for call in init_calls] == [date],
            "new makeup registration initializes that date exactly once",
        )
        _assert_unit(notification_calls[-1] == {"s1"}, "extra-attend patch notifies the changed student")

        init_calls.clear()
        response = client.patch("/api/extra-attend", json={"date": date, "sids": ["s1", "s1"]})
        _assert_unit(
            response.status_code == 200
            and [call.get("date_key") for call in init_calls] == [date],
            "unchanged makeup retry replays the idempotent today initializer",
        )

        init_calls.clear()
        response = client.patch("/api/extra-attend", json={"date": date, "sids": []})
        _assert_unit(response.status_code == 200 and date not in store["extra"], "empty date patch removes only that date")
        _assert_unit(
            [call.get("date_key") for call in init_calls] == [date],
            "removing a makeup registration rechecks that date without touching other dates",
        )
        _assert_unit(store["extra"][other_date] == ["other"], "makeup removal preserves unrelated dates")
        init_calls.clear()
        response = client.patch("/api/extra-attend", json={"date": other_date, "sids": ["s1"]})
        _assert_unit(response.status_code == 200 and not init_calls, "future makeup registration never initializes an automatic snapshot")
        _assert_unit(client.post("/api/extra-attend", json={date: ["s1"]}).status_code == 405, "unsafe whole-map POST is disabled")
        _assert_unit(
            client.patch("/api/extra-attend", json={"date": "2026-02-30", "sids": ["s1"]}).status_code == 400,
            "extra-attend patch rejects impossible dates",
        )
        _assert_unit(
            client.patch("/api/extra-attend", json={"date": date, "sids": ["ghost-outside-test"]}).status_code == 403,
            "extra-attend patch rejects the read-only ghost student",
        )

        store["weekend"] = {date: {"other": [1]}}
        lock_events.clear()
        response = client.post("/api/weekend-slots", json={date: {"s1": [1, 2], "s2": None}})
        _assert_unit(response.status_code == 204, "weekend-slots hook request succeeds")
        _assert_unit(
            lock_events == [("enter", "weekend"), ("exit", "weekend")],
            "weekend slot read-merge-write holds one file lock",
        )
        _assert_unit(store["weekend"][date]["other"] == [1], "student-scoped weekend patch preserves another student's slots")
        _assert_unit(store["weekend"][date]["s1"] == [1, 2], "student-scoped weekend patch stores the requested slots")
        _assert_unit("s2" not in store["weekend"][date], "empty weekend patch explicitly removes only its target student")
        _assert_unit(
            [args[:2] for args, _ in expand_calls] == [(date, "s1"), (date, "s2")],
            "weekend slot writes reconcile every affected student",
        )

        expand_calls.clear()
        init_calls.clear()
        lock_events.clear()
        student_io_events.clear()
        response = client.post(
            "/api/update",
            json={"id": "s1", "field": "day2", "value": "토2"},
        )
        _assert_unit(response.status_code == 200, "schedule update hook request succeeds")
        _assert_unit(
            lock_events == [("enter", "students"), ("exit", "students")]
            and student_io_events == [("load", 1), ("save", 1)],
            "student field update holds the student-store lock across read and save",
        )
        _assert_unit(
            expand_calls and expand_calls[-1][0][:2] == (date, "s1"),
            "regular schedule edits reconcile the current student",
        )
        _assert_unit(init_calls and init_calls[-1].get("students") == store["students"], "schedule edits initialize newly eligible students")

        init_calls.clear()
        expand_calls.clear()
        response = client.post(
            "/api/update",
            json={"id": "s1", "field": "subCurriculum", "value": "APEX"},
        )
        _assert_unit(response.status_code == 200, "curriculum update hook request succeeds")
        _assert_unit(
            init_calls and init_calls[-1].get("students") == store["students"],
            "curriculum edits immediately rebase today's automatic snapshot",
        )
        _assert_unit(not expand_calls, "curriculum edits do not invoke schedule-only consecutive reconciliation")

        init_calls.clear()
        expand_calls.clear()
        response = client.post(
            "/api/update",
            json={"id": "s1", "field": "autoVideoAssignCount", "value": 10},
        )
        _assert_unit(response.status_code == 200, "auto assignment count update hook request succeeds")
        _assert_unit(store["students"][0]["autoVideoAssignCount"] == 6, "count update clamps the student setting to the approved cap")
        _assert_unit(
            not init_calls and not expand_calls,
            "count updates persist only the setting and never initialize or reconcile assignments",
        )
    finally:
        for name, value in original.items():
            setattr(api_basic, name, value)
        for name, value in student_original.items():
            setattr(api_students, name, value)
        for name, value in schedule_original.items():
            setattr(api_schedule_overrides, name, value)
        for name, value in updates_original.items():
            setattr(api_updates, name, value)

def run_auto_assignment_progress_reconcile_unit_checks() -> None:
    from copy import deepcopy
    from flask import Flask

    import routes.api_basic as api_basic
    import routes.api_progress as api_progress

    date = "2026-06-06"
    sid = "progress-hook"
    students_path = object()
    videos_path = object()
    weekend_path = object()
    updates_path = object()
    state = {
        "students": [{
            "id": sid,
            "curriculum": "ALG",
            "subCurriculum": "BASE",
            "autoVideoAssignCount": 2,
        }],
        "videos": [
            {"mid": f"m{index}", "curriculum": "ALG", "subCurriculum": "BASE", "chapter": str(index)}
            for index in range(1, 6)
        ],
        "weekend": {},
        "updates": {
            "2026-06-05": {
                sid: {"videos": ["m1", "m2"], "source": "auto", "note": "past"},
            },
            date: {
                sid: {"videos": ["m1", "m2"], "source": "auto", "note": "keep"},
            },
            "2026-06-07": {
                sid: {"videos": ["m1", "m2"], "source": "auto", "note": "future"},
            },
            "2026-06-08": {
                sid: {"videos": ["m1", "m2"], "source": "manual"},
            },
            "2026-06-09": {
                sid: {"videos": ["m1", "m2"], "source": "selfStudy"},
            },
            "2026-06-10": {
                sid: ["m1", "m2"],
            },
            "2026-06-11": {},
        },
        "save_count": 0,
    }
    progress = {date: {sid: {"m1": "done", "m2": "skip"}}}

    original = {
        "STU_PATH": api_basic.STU_PATH,
        "VID_PATH": api_basic.VID_PATH,
        "WEEKEND_SLOTS_PATH": api_basic.WEEKEND_SLOTS_PATH,
        "UPD_PATH": api_basic.UPD_PATH,
        "load": api_basic.load,
        "save_atomic": api_basic.save_atomic,
        "updates_lock": api_basic._updates_lock,
        "load_progress": api_basic._load_progress_strict,
        "reconcile": api_basic._reconcile_auto_assignment_after_progress,
    }
    progress_original = {
        "load_progress": api_progress._load_progress_strict,
        "save_progress": api_progress._save_progress_strict,
        "progress_lock": api_progress._progress_lock,
        "notification_snapshot": api_progress._notification_progress_snapshot,
        "notification_commit": api_progress._notification_progress_commit,
    }

    def fake_load(path):
        if path is students_path:
            return deepcopy(state["students"])
        if path is videos_path:
            return deepcopy(state["videos"])
        if path is weekend_path:
            return deepcopy(state["weekend"])
        if path is updates_path:
            return deepcopy(state["updates"])
        return {}

    def fake_save(path, value, **_kwargs):
        if path is updates_path:
            state["updates"] = deepcopy(value)
            state["save_count"] += 1

    try:
        api_basic.STU_PATH = students_path
        api_basic.VID_PATH = videos_path
        api_basic.WEEKEND_SLOTS_PATH = weekend_path
        api_basic.UPD_PATH = updates_path
        api_basic.load = fake_load
        api_basic.save_atomic = fake_save
        api_basic._updates_lock = lambda: contextlib.nullcontext()

        baseline_updates = deepcopy(state["updates"])
        changed = api_basic._reconcile_auto_assignment_after_progress(
            date,
            sid,
            progress=progress,
            watch={},
        )
        _assert_unit(
            not changed
            and state["updates"] == baseline_updates
            and state["save_count"] == 0,
            "progress reconciliation is a no-op and never rewrites automatic snapshots",
        )

        progress_store = {"value": {}}
        reconcile_calls = []

        def stable_save_progress(value, *_args, **_kwargs):
            progress_store["value"] = deepcopy(value)

        api_progress._load_progress_strict = lambda *_args, **_kwargs: deepcopy(progress_store["value"])
        api_progress._save_progress_strict = stable_save_progress
        api_progress._progress_lock = lambda: contextlib.nullcontext()
        api_progress._notification_progress_snapshot = lambda *_args, **_kwargs: None
        api_progress._notification_progress_commit = lambda *_args, **_kwargs: 0
        api_basic._reconcile_auto_assignment_after_progress = (
            lambda *args, **kwargs: reconcile_calls.append((args, kwargs)) or True
        )

        app = Flask("verify-auto-assignment-snapshot-immutability")
        app.register_blueprint(api_basic.bp_api_basic)
        app.register_blueprint(api_progress.bp_api_progress)
        client = app.test_client()
        for mid, status in (("m1", "done"), ("m2", "skip"), ("m3", "interrupted")):
            response = client.post(
                "/api/progress/patch",
                json={"date": date, "sid": sid, "progress": {mid: status}},
            )
            _assert_unit(response.status_code == 200, f"progress patch should persist {status}")

        _assert_unit(
            not reconcile_calls,
            "progress writes must never call an automatic-assignment refill hook",
        )
        return
    finally:
        api_basic.STU_PATH = original["STU_PATH"]
        api_basic.VID_PATH = original["VID_PATH"]
        api_basic.WEEKEND_SLOTS_PATH = original["WEEKEND_SLOTS_PATH"]
        api_basic.UPD_PATH = original["UPD_PATH"]
        api_basic.load = original["load"]
        api_basic.save_atomic = original["save_atomic"]
        api_basic._updates_lock = original["updates_lock"]
        api_basic._load_progress_strict = original["load_progress"]
        api_basic._reconcile_auto_assignment_after_progress = original["reconcile"]
        api_progress._load_progress_strict = progress_original["load_progress"]
        api_progress._save_progress_strict = progress_original["save_progress"]
        api_progress._progress_lock = progress_original["progress_lock"]
        api_progress._notification_progress_snapshot = progress_original["notification_snapshot"]
        api_progress._notification_progress_commit = progress_original["notification_commit"]



def run_self_study_assignment_route_unit_checks() -> None:
    from copy import deepcopy
    from flask import Flask

    import routes.api_basic as api_basic
    import routes.api_updates as api_updates

    date = "2026-06-06"
    sid = "self-study-route"
    students_path = object()
    videos_path = object()
    watch_path = object()
    updates_path = object()
    state = {
        "students": [{
            "id": sid,
            "curriculum": "ALG",
            "subCurriculum": "BASE",
            "autoVideoAssignCount": 2,
            "day1": "월1",
        }],
        "videos": [
            {"mid": f"m{index}", "curriculum": "ALG", "subCurriculum": "BASE", "chapter": str(index)}
            for index in range(1, 4)
        ],
        "watch": {},
        "updates": {date: {sid: {"videos": ["m3"], "source": "auto"}}},
        "progress": {"2026-06-05": {sid: {"m1": "done", "m2": "interrupted"}}},
        "absent": {"by_date": {}, "by_student": {}},
    }

    original = {
        "STU_PATH": api_basic.STU_PATH,
        "VID_PATH": api_basic.VID_PATH,
        "WATCH_PATH": api_basic.WATCH_PATH,
        "UPD_PATH": api_basic.UPD_PATH,
        "load": api_basic.load,
        "save_atomic": api_basic.save_atomic,
        "load_updates_strict": api_basic.load_updates_strict,
        "save_updates_strict": api_basic.save_updates_strict,
        "absence_barrier": api_basic._auto_assignment_absence_barrier,
        "load_absent": api_basic.load_absent,
        "_load_progress_strict": api_basic._load_progress_strict,
        "get_log_repository": api_basic.get_log_repository,
        "updates_lock": api_basic._updates_lock,
    }

    def fake_load(path):
        if path is students_path:
            return deepcopy(state["students"])
        if path is videos_path:
            return deepcopy(state["videos"])
        if path is watch_path:
            return deepcopy(state["watch"])
        if path is updates_path:
            return deepcopy(state["updates"])
        return {}

    def fake_save(path, value, **_kwargs):
        if path is updates_path:
            state["updates"] = deepcopy(value)

    class FakeLogRepository:
        def read_logs(self, _date, _sid):
            return {_date: {_sid: {"selfStudy": True}}}

    try:
        api_basic.STU_PATH = students_path
        api_basic.VID_PATH = videos_path
        api_basic.WATCH_PATH = watch_path
        api_basic.UPD_PATH = updates_path
        api_basic.load = fake_load
        api_basic.save_atomic = fake_save
        api_basic.load_updates_strict = fake_load
        api_basic.save_updates_strict = fake_save
        api_basic._auto_assignment_absence_barrier = (
            lambda: contextlib.nullcontext()
        )
        api_basic.load_absent = lambda: deepcopy(state["absent"])
        api_basic._load_progress_strict = lambda *_args, **_kwargs: deepcopy(state["progress"])
        api_basic.get_log_repository = lambda: FakeLogRepository()
        api_basic._updates_lock = lambda: contextlib.nullcontext()

        app = Flask("verify-self-study-assignment-route")
        api_updates.configure_updates_assignment_hooks(
            app,
            initialize_today=api_basic.initialize_auto_assignment_for_updates_read,
            reconcile_self_study=api_basic.reconcile_self_study_assignment_for_updates,
        )
        app.register_blueprint(api_updates.bp_api_updates)
        client = app.test_client()

        response = client.post("/api/updates/self-study", json={"date": date, "sid": sid})
        payload = response.get_json() or {}
        _assert_unit(response.status_code == 200 and payload.get("ok") is True, "self-study assignment route must return success")
        _assert_unit(
            payload.get("assignment") == {"videos": ["m1"], "source": "selfStudy"}
            and state["updates"][date][sid] == payload["assignment"],
            "self-study route must replace an automatic snapshot with completed review videos only",
        )

        state["updates"] = {date: {sid: {"videos": ["m1"], "source": "selfStudy"}}}
        response = client.post(
            "/api/updates/self-study",
            json={"date": date, "sid": sid, "videos": ["m1"], "append": True},
        )
        payload = response.get_json() or {}
        _assert_unit(
            response.status_code == 200
            and payload.get("assignment") == {"videos": ["m1"], "source": "selfStudy"}
            and state["updates"][date][sid] == payload["assignment"],
            "self-study route must append an eligible completed review video without duplicates",
        )

        persisted = deepcopy(state["updates"])
        response = client.post(
            "/api/updates/self-study",
            json={"date": date, "sid": sid, "videos": ["m2"], "append": True},
        )
        payload = response.get_json() or {}
        _assert_unit(
            response.status_code == 409
            and payload.get("error") == "video is not eligible for self-study review"
            and state["updates"] == persisted,
            "self-study route must reject an interrupted orange video",
        )

        response = client.post(
            "/api/updates/self-study",
            json={"date": date, "sid": sid, "videos": ["m3"], "append": True},
        )
        payload = response.get_json() or {}
        _assert_unit(
            response.status_code == 409
            and payload.get("error") == "video is not eligible for self-study review"
            and state["updates"] == persisted,
            "self-study route must reject a video without completed prior progress",
        )

        response = client.post(
            "/api/updates/self-study",
            json={"date": date, "sid": sid, "videos": "m2"},
        )
        _assert_unit(response.status_code == 400, "self-study route must reject non-array video selections")

        state["updates"] = {date: {sid: {"videos": ["m3"], "source": "auto"}}}
        persisted = deepcopy(state["updates"])
        state["absent"] = {"by_date": {date: [sid]}, "by_student": {}}
        response = client.post("/api/updates/self-study", json={"date": date, "sid": sid})
        payload = response.get_json() or {}
        _assert_unit(
            response.status_code == 409
            and payload.get("error") == "student is absent"
            and state["updates"] == persisted,
            "self-study route must keep absence blocked without mutating the assignment",
        )

        state["absent"] = {"by_date": {}, "by_student": {}}
        state["progress"] = {}
        state["updates"] = {date: {sid: {"videos": ["m3"], "source": "auto"}}}
        response = client.post("/api/updates/self-study", json={"date": date, "sid": sid})
        payload = response.get_json() or {}
        _assert_unit(
            response.status_code == 200
            and payload.get("assignment") is None
            and sid not in state["updates"].get(date, {}),
            "self-study route must remove the automatic snapshot when no review video is eligible",
        )
        response = client.post("/api/updates/self-study", json={"date": date, "sid": sid})
        payload = response.get_json() or {}
        _assert_unit(
            response.status_code == 200
            and payload.get("assignment") is None
            and sid not in state["updates"].get(date, {}),
            "repeated self-study reconciliation must not resurrect a cancelled automatic snapshot",
        )
    finally:
        for name, value in original.items():
            setattr(api_basic, name, value)


def run_video_assignment_boundary_source_checks() -> None:
    today_js = (ROOT / "static/js/admin/features/today.js").read_text("utf-8")
    video_modal_js = (ROOT / "static/js/admin/features/videoModal.js").read_text("utf-8")
    export_logs_js = (ROOT / "static/js/admin/features/exportLogs.js").read_text("utf-8")

    _assert_unit(
        "async function refreshUpdatesAtAssignmentBoundary" in today_js,
        "today refresh must centralize date-boundary assignment hydration",
    )
    _assert_unit(
        "const boundary = reason === 'date' || realDate !== lastAutoAssignmentBoundaryDate;" in today_js,
        "today refresh must initialize assignments only for a real/date-change boundary",
    )
    _assert_unit(
        "const updates = await api.get('/api/updates', { cache: 'no-store' });" in today_js,
        "date-boundary refresh must use the normal initializing updates endpoint",
    )
    _assert_unit(
        "document.addEventListener('admin:date-change', () => loadTodayAndRender({ force: true, reason: 'date' }));" in today_js,
        "admin date changes must enter the assignment boundary path",
    )
    _assert_unit(
        "hydrateUpdates({ readOnly: true })" in video_modal_js
        and "'/api/updates?readOnly=1'" in video_modal_js,
        "video progress popup hydration must use a read-only updates snapshot",
    )
    _assert_unit(
        "'/api/updates?readOnly=1'" in export_logs_js,
        "roster export updates hydration must not initialize or re-pick videos",
    )


def run_self_study_video_assignment_source_checks() -> None:
    api_basic_py = (ROOT / "routes/api_basic.py").read_text("utf-8")
    bootstrap_projection_py = (
        ROOT / "routes/student_bootstrap_projection.py"
    ).read_text("utf-8")
    student_video_projection_py = (
        ROOT / "core/student_video_projection.py"
    ).read_text("utf-8")
    auto_assignment_service_py = (
        ROOT / "routes/student_auto_assignment_service.py"
    ).read_text("utf-8")
    api_updates_py = (ROOT / "routes/api_updates.py").read_text("utf-8")
    update_rules_py = (ROOT / "core/update_assignment_rules.py").read_text("utf-8")
    today_state_js = (ROOT / "static/js/admin/features/today.state.js").read_text("utf-8")
    export_logs_js = (ROOT / "static/js/admin/features/exportLogs.js").read_text("utf-8")
    video_modal_js = (ROOT / "static/js/admin/features/videoModal.js").read_text("utf-8")
    bootstrap_state_js = (
        ROOT / "static/js/student/bootstrapState.js"
    ).read_text("utf-8")
    review_playlist_js = (
        ROOT / "static/js/student/reviewPlaylist.js"
    ).read_text("utf-8")

    _assert_unit(
        "@bp_api_updates.post(\"/api/updates/self-study\")" in api_updates_py
        and "@bp_api_basic.post(\"/api/updates/self-study\")" not in api_basic_py,
        "self-study review assignment must have a dedicated updates endpoint",
    )
    _assert_unit(
        "SELF_STUDY_VIDEO_ASSIGN_SOURCE = \"selfStudy\"" in update_rules_py,
        "self-study review assignment must remain distinguishable from new automatic progress",
    )
    _assert_unit(
        "def student_eligible_review_video_mids" in student_video_projection_py
        and "video is not eligible for self-study review"
        in auto_assignment_service_py,
        "self-study review registration must be server-authorized by prior progress",
    )
    _assert_unit(
        "student_is_self_study_on_date" in auto_assignment_service_py
        and "_service_reconcile_self_study_assignment" in api_basic_py,
        "scheduled self-study must use the same backend automatic assignment path",
    )
    _assert_unit(
        "if student_absent_on_date(absent, date_key, sid):"
        in auto_assignment_service_py
        and "if student_is_self_study_on_date(logs, date_key, sid, student):"
        in auto_assignment_service_py,
        "self-study auto reconciliation must allow explicit self-study while keeping absence first",
    )
    _assert_unit(
        "if (not registered_today and not self_study_day) or absent_today:"
        in bootstrap_projection_py,
        "student bootstrap must allow self-study on a non-scheduled date but keep absence blocked",
    )
    student_js = (ROOT / "static/js/student.js").read_text("utf-8")
    _assert_unit(
        "|| isAbsentOnStudentDate() || isArchivedOnStudentDate();" in student_js,
        "student review surface must keep the absence/archive guard",
    )
    _assert_unit(
        "selfStudy: bootstrap.selfStudy === true" in bootstrap_state_js
        and "function registerReviewVideos" in student_js
        and "reviewPlaylistController.hydrate(reviewVideosCache.map(item => item.mid))"
        in student_js
        and "reviewPlaylistController.registerSelected()" in student_js
        and "if (!authorized.has(mid) || registered.includes(mid)) return false;"
        in review_playlist_js
        and "storage.setItem(currentStorageKey(), JSON.stringify(registered));"
        in review_playlist_js
        and "previousVideosRegister" in student_js,
        "student self-study review rows must register in the server-authorized local playlist",
    )
    review_surface_start = student_js.find("function reviewSurfaceBlocked()")
    review_surface_end = student_js.find("\n  }", review_surface_start)
    review_surface_body = student_js[review_surface_start:review_surface_end] if review_surface_start >= 0 else ""
    _assert_unit(
        review_surface_start >= 0 and "selfStudy" not in review_surface_body,
        "student review surface must not add a self-study block",
    )
    _assert_unit(
        "await assignSelfStudyReviewVideos(dateKey, sid);" in today_state_js,
        "today self-study toggle must immediately replace the automatic assignment",
    )
    _assert_unit(
        "'/api/updates/self-study'" in today_state_js,
        "today self-study toggle must use the dedicated assignment endpoint",
    )
    _assert_unit(
        "!truthy((logsDay[String(stu?.id)] || {}).selfStudy)" in export_logs_js,
        "roster export must remove self-study students",
    )
    _assert_unit(
        "isSelfStudyScheduledForDate(stu, today)" in video_modal_js,
        "video modal must not create new automatic progress for scheduled self-study",
    )


def run_watch_route_progress_unit_checks() -> None:
    from core.progress_rules import PROGRESS_MANUAL_META_KEY, WATCH_AUTO_PROGRESS_META_KEY
    import core.watch_progress_writer as watch_writer
    from flask import Flask
    import routes.api_basic as api_basic
    import routes.api_watch as api_watch

    watch_source = (ROOT / "routes/api_watch.py").read_text("utf-8")
    kollus_source = (ROOT / "routes/api_kollus.py").read_text("utf-8")
    _assert_unit(
        "from routes.api_basic import" not in watch_source,
        "watch route must not import private helpers from api_basic",
    )
    _assert_unit(
        "from routes.api_watch import" not in kollus_source,
        "Kollus route must not import private writers from api_watch",
    )
    _assert_unit(
        "from core.watch_progress_writer import" in watch_source
        and "from core.watch_progress_writer import" in kollus_source,
        "watch and Kollus routes must share the public watch/progress writer",
    )

    old_basic_progress = api_basic.PRG_PATH
    old_watch_progress = api_watch.PRG_PATH
    old_watch_path = api_watch.WATCH_PATH
    old_watch_students = api_watch.STU_PATH
    old_watch_videos = api_watch.VID_PATH
    old_network_allowed = api_watch.academy_network_allowed
    old_reconcile = api_basic._reconcile_auto_assignment_after_progress
    reconcile_calls = []

    with verification_temporary_directory("verify-watch-progress-") as tmpdir:
        progress_path = pathlib.Path(tmpdir) / "progress.json"
        watch_path = pathlib.Path(tmpdir) / "watch.json"
        students_path = pathlib.Path(tmpdir) / "students.json"
        videos_path = pathlib.Path(tmpdir) / "videos.json"
        progress_path.write_text("{}", "utf-8")
        watch_path.write_text("{}", "utf-8")
        students_path.write_text("[]", "utf-8")
        videos_path.write_text("[]", "utf-8")

        api_basic.PRG_PATH = progress_path
        api_watch.PRG_PATH = progress_path
        api_watch.WATCH_PATH = watch_path
        api_watch.STU_PATH = students_path
        api_watch.VID_PATH = videos_path
        api_basic._reconcile_auto_assignment_after_progress = (
            lambda *args, **kwargs: reconcile_calls.append((args, kwargs)) or True
        )
        try:
            merged = watch_writer.save_progress_status(
                progress_path, students_path, videos_path, "2026-06-06", "007", "m1", "interrupted"
            )
            _assert_unit(merged.get("m1") == "interrupted", "watch route should save auto interrupted")
            _assert_unit(
                merged.get(WATCH_AUTO_PROGRESS_META_KEY, {}).get("m1") == "interrupted",
                "watch route should persist auto interrupted metadata",
            )

            merged = watch_writer.save_progress_status(
                progress_path, students_path, videos_path, "2026-06-06", "007", "m1", "done"
            )
            _assert_unit(merged.get("m1") == "done", "watch route should advance auto interrupted to done")
            _assert_unit(
                not reconcile_calls,
                "watch completion must persist progress without refilling automatic assignments",
            )



            current = json.loads(progress_path.read_text("utf-8-sig"))
            current["2026-06-06"]["007"].update({
                "m2": "none",
                "m5": "skip",
                "m6": "interrupted",
                PROGRESS_MANUAL_META_KEY: {"m2": True, "m5": True, "m6": True},
            })
            progress_path.write_text(json.dumps(current, ensure_ascii=False), "utf-8")

            for mid, expected in (("m2", "none"), ("m5", "skip"), ("m6", "interrupted")):
                merged = watch_writer.save_progress_status(
                    progress_path, students_path, videos_path, "2026-06-06", "007", mid, "done"
                )
                _assert_unit(
                    merged.get(mid) == expected,
                    f"watch writer must not overwrite manual {expected}",
                )

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
            api_watch.STU_PATH = old_watch_students
            api_watch.VID_PATH = old_watch_videos
            api_watch.academy_network_allowed = old_network_allowed
            api_basic._reconcile_auto_assignment_after_progress = old_reconcile


def run_video_progress_integration_matrix_checks() -> None:
    from scripts.verify_video_progress_matrix import main as verify_video_progress_matrix

    _assert_unit(
        verify_video_progress_matrix() == 0,
        "watch and Kollus temp-route integration matrix must pass",
    )
    for script, failure_message in (
        (
            "scripts/verify_student_watch_timestamp.mjs",
            "student watch millisecond timestamp checks failed",
        ),
        (
            "scripts/verify_student_watch_autosave.mjs",
            "student watch state, debounce, and flush behavior checks failed",
        ),
        (
            "scripts/verify_student_playback.mjs",
            "student playback URL, active-MID bridge, and failure behavior checks failed",
        ),
        (
            "scripts/verify_student_review_playlist.mjs",
            "student review playlist storage, selection, and bootstrap-prune checks failed",
        ),
    ):
        cmd = ["node", script]
        print("$ " + " ".join(cmd))
        try:
            proc = _run_captured(cmd)
        except FileNotFoundError:
            raise AssertionError("node not found") from None
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        _assert_unit(proc.returncode == 0, failure_message)


def run_absence_makeup_integration_matrix_checks() -> None:
    from scripts.verify_absence_makeup_matrix import main as verify_absence_makeup_matrix

    _assert_unit(
        verify_absence_makeup_matrix() == 0,
        "absence and makeup temp-route integration matrix must pass or report only approved limitations",
    )


def run_log_repository_unit_checks() -> None:
    from core.log_repository import LogRepository
    from core.log_rules import log_entry_conflicts_with_base, merge_log_entry_safe

    with verification_temporary_directory("verify-logrepo-") as tmpdir:
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

        summary_logs_path = tmp / "logs-summary.json"
        summary_db_path = tmp / "app-summary.sqlite"
        summary_logs_path.write_text(
            json.dumps(
                {
                    "2026-06-01": {
                        "s1": {"done": True, "marker": "json-old"},
                        "s2": {"done": "true", "marker": "json-excluded"},
                    },
                    "2026-06-03": {"s1": {"done": 1, "hwChecked": True, "notes": "private"}},
                    "2026-06-04": {"archived": {"done": True, "archived": True}},
                    "2026-06-10": {"  s3  ": {"done": True}},
                    "2026-99-99": {"future-bad": {"done": True}},
                    "not-a-date": {"bad": {"done": True}},
                },
                ensure_ascii=False,
            ),
            "utf-8",
        )
        summary_repo = LogRepository(
            logs_path=summary_logs_path,
            db_path=str(summary_db_path),
            merge_entry=merge_log_entry_safe,
            entry_conflicts=log_entry_conflicts_with_base,
            today_key=lambda: "2026-06-10",
        )
        con = summary_repo._connect()
        try:
            summary_repo._ensure_schema(con)
            summary_repo._sqlite_upsert_entry(
                con, "2026-06-02", "s1", {"done": True, "marker": "sqlite-middle"},
            )
            summary_repo._sqlite_upsert_entry(
                con, "2026-06-05", "s2", {"done": True, "selfStudy": True, "notes": "private"},
            )
        finally:
            con.close()

        unarchived_summary = summary_repo.summarize_unarchived_done("2026-06-01")
        latest_rows = {row["sid"]: row for row in unarchived_summary.get("rows", [])}
        _assert_unit(set(latest_rows) == {"s1", "s2", "s3"}, "summary rows must include every unarchived student once")
        _assert_unit(latest_rows["s1"]["date"] == "2026-06-03", "summary must keep the latest date per sid")
        _assert_unit(
            latest_rows["s1"]["entry"] == {"done": True, "archived": False, "hwChecked": True},
            "summary rows must project only render-safe JSON booleans",
        )
        _assert_unit(latest_rows["s2"]["date"] == "2026-06-05", "newer SQLite rows must win by date")
        _assert_unit(
            latest_rows["s2"]["entry"] == {"done": True, "archived": False, "selfStudy": True},
            "summary rows must not expose SQLite notes or unrelated metadata",
        )
        _assert_unit(latest_rows["s3"]["sid"] == "s3", "summary SIDs must be trimmed before dedupe/actions")
        _assert_unit(unarchived_summary.get("rowsAvailable") is True, "healthy dual-store summary must be authoritative")
        _assert_unit(unarchived_summary.get("total") == 3, "excludeDate must affect stale counts only")
        _assert_unit(unarchived_summary.get("students") == 2, "stale summary student count must stay distinct")
        _assert_unit(
            all(row.get("date") != "not-a-date" for row in unarchived_summary.get("rows", [])),
            "malformed dates must not enter latest rows",
        )
        _assert_unit(
            all(row.get("date") != "2026-99-99" for row in unarchived_summary.get("rows", [])),
            "impossible calendar dates must not enter latest rows",
        )

        fallback_logs_path = tmp / "logs-summary-fallback.json"
        fallback_logs_path.write_text(
            json.dumps({"2026-06-07": {"fallback": {"done": True, "notes": "private"}}}),
            "utf-8",
        )
        fallback_repo = LogRepository(logs_path=fallback_logs_path, db_path=str(tmp / "missing.sqlite"))
        fallback_repo._connect = lambda: (_ for _ in ()).throw(RuntimeError("sqlite unavailable"))
        with contextlib.redirect_stdout(io.StringIO()):
            fallback_summary = fallback_repo.summarize_unarchived_done()
        _assert_unit(fallback_summary.get("rowsAvailable") is True, "valid JSON fallback remains authoritative")
        _assert_unit(
            fallback_summary.get("rows") == [{
                "date": "2026-06-07",
                "sid": "fallback",
                "entry": {"done": True, "archived": False},
            }],
            "SQLite degradation must use the minimal JSON projection without leaked notes",
        )

        fallback_logs_path.write_text("{broken", "utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            degraded_summary = fallback_repo.summarize_unarchived_done()
        _assert_unit(degraded_summary.get("rowsAvailable") is False, "dual-source failure must be non-authoritative")
        _assert_unit("rows" not in degraded_summary, "degraded summary must not erase valid local done rows")

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
        expected_stdout = io.StringIO()
        expected_stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(expected_stdout), contextlib.redirect_stderr(expected_stderr):
                failed_json = fail_repo.patch_entry(fail_date, sid, {"notes": "sqlite committed"}, {})
        finally:
            log_repository_module.save_atomic = original_save_atomic

        expected_failure_output = expected_stdout.getvalue() + expected_stderr.getvalue()
        _assert_unit(
            "[logs] json PATCH failed:" in expected_failure_output,
            "json save failure must still be logged internally",
        )
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
        from routes import api_logs
        from types import SimpleNamespace

        class FakeReadLogRepository:
            def read_entry(self, _date, _sid):
                return SimpleNamespace(source="json", entry={})

        route_app = Flask("verify-log-entry-route")
        route_app.register_blueprint(api_logs.bp_api_logs)
        route_client = route_app.test_client()

        original_get_log_repository = api_logs.get_log_repository
        api_logs.get_log_repository = lambda: FakeReadLogRepository()
        try:
            response = route_client.get("/api/logs/entry?date=2026-06-06&sid=__missing__")
        finally:
            api_logs.get_log_repository = original_get_log_repository

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

        class FakeBatchLogRepository:
            def __init__(self, *, sqlite_ok=True):
                self.sqlite_ok = sqlite_ok
                self.calls = []

            def legacy_post(self, incoming):
                self.calls.append(incoming)
                return SimpleNamespace(
                    sqlite_ok=self.sqlite_ok,
                    sqlite_error=RuntimeError(r"C:\runtime\app.sqlite failed") if not self.sqlite_ok else None,
                )

        fake_batch_repo = FakeBatchLogRepository()
        api_logs.get_log_repository = lambda: fake_batch_repo
        try:
            batch_response = route_client.post(
                "/api/logs/patch-batch",
                json={"patches": [
                    {
                        "date": "2026-06-06",
                        "sid": "student-a",
                        "entry": {"done": True, "leaveTime": "14:00"},
                        "__clear": ["archived"],
                    },
                    {
                        "date": "2026-06-05",
                        "sid": "student-b",
                        "entry": {"archived": True},
                    },
                ]},
            )
            duplicate_response = route_client.post(
                "/api/logs/patch-batch",
                json={"patches": [
                    {"date": "2026-06-06", "sid": "student-a", "entry": {"done": True}},
                    {"date": "2026-06-06", "sid": "student-a", "entry": {"archived": True}},
                ]},
            )
        finally:
            api_logs.get_log_repository = original_get_log_repository

        batch_payload = batch_response.get_json()
        _assert_unit(batch_response.status_code == 200, "batch log patch must return HTTP 200")
        _assert_unit(batch_payload.get("ok") is True, "batch log patch must return ok:true")
        _assert_unit(batch_payload.get("count") == 2, "batch log patch must report its unique target count")
        _assert_unit(len(fake_batch_repo.calls) == 1, "batch log patch must invoke one repository save")
        saved_batch = fake_batch_repo.calls[0]
        _assert_unit(
            saved_batch["2026-06-06"]["student-a"].get("__clear") == ["archived"],
            "batch log patch must preserve clear keys inside the merge entry",
        )
        _assert_unit(
            saved_batch["2026-06-05"]["student-b"].get("archived") is True,
            "batch log patch must preserve each date/sid entry",
        )
        _assert_unit(duplicate_response.status_code == 400, "duplicate batch target must fail before writing")
        _assert_unit(len(fake_batch_repo.calls) == 1, "duplicate batch target must not invoke the repository")

        failing_batch_repo = FakeBatchLogRepository(sqlite_ok=False)
        api_logs.get_log_repository = lambda: failing_batch_repo
        try:
            batch_failure = route_client.post(
                "/api/logs/patch-batch",
                json={"patches": [{
                    "date": "2026-06-06",
                    "sid": "student-a",
                    "entry": {"done": True},
                }]},
            )
        finally:
            api_logs.get_log_repository = original_get_log_repository

        batch_failure_text = batch_failure.get_data(as_text=True)
        _assert_unit(batch_failure.status_code == 409, "batch sqlite failure must return HTTP 409")
        _assert_unit(
            "C:" not in batch_failure_text and "runtime" not in batch_failure_text,
            "batch sqlite failure must not expose local paths",
        )

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

        api_logs.get_log_repository = lambda: FakeLogRepository()
        try:
            app = Flask("verify-logrepo-json-warning")
            with app.test_request_context(
                "/api/logs/patch",
                method="POST",
                json={"date": fail_date, "sid": sid, "entry": {"notes": "saved"}},
            ):
                response = api_logs.api_logs_patch()
        finally:
            api_logs.get_log_repository = original_get_log_repository

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

        api_logs.get_log_repository = lambda: FakeConflictJsonFailureRepository()
        try:
            app = Flask("verify-logrepo-conflict-json-failure")
            with app.test_request_context(
                "/api/logs/patch",
                method="POST",
                json={"date": fail_date, "sid": sid, "entry": {"notes": "unsaved"}},
            ):
                response = api_logs.api_logs_patch()
        finally:
            api_logs.get_log_repository = original_get_log_repository

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


def run_legacy_test_record_cache_unit_checks() -> None:
    import datetime as dt

    from routes import api_basic, api_tests

    original_tests_path = api_tests.TESTS_PATH
    original_logs_path = api_tests.LOGS_PATH
    original_get_log_repository = api_basic.get_log_repository
    original_load = api_tests.load

    def reset_cache() -> None:
        with api_tests._LEGACY_TEST_RECORD_CACHE_LOCK:
            api_tests._LEGACY_TEST_RECORD_CACHE = None

    def record(name: str, *, created_at: str = "", score: str = "8/10", memo: str = "") -> dict:
        return {
            "name": name,
            "score": score,
            "createdAt": created_at,
            "memo": memo,
            "wrong": [2],
            "testMeta": {"type": "UNIT", "curriculum": "수학"},
        }

    with verification_temporary_directory("verify-test-record-cache-") as tmpdir:
        tmp = pathlib.Path(tmpdir)
        tests_path = tmp / "tests.json"
        logs_path = tmp / "logs.json"
        date_one = "2026-06-01"
        date_two = "2026-06-02"
        duplicate_name = "단원 / 캐시 회귀"
        tests_path.write_text(
            json.dumps({date_one: {"s1": [record(duplicate_name, memo="durable")]}}, ensure_ascii=False),
            "utf-8",
        )
        logs_path.write_text(
            json.dumps(
                {
                    date_one: {
                        "s1": {"tests": [record(duplicate_name, memo="legacy duplicate")]},
                        "bad": {"tests": [record("zero", score="1/0"), {"score": "1/2"}]},
                    },
                    date_two: {"s1": {"tests": [record(duplicate_name)]}},
                    "not-a-date": {"s2": {"tests": [record("invalid date")]}},
                },
                ensure_ascii=False,
            ),
            "utf-8",
        )
        api_tests.TESTS_PATH = tests_path
        api_tests.LOGS_PATH = logs_path

        load_calls = 0

        class CountingLogRepository:
            def read_json_map(self):
                nonlocal load_calls
                load_calls += 1
                return json.loads(logs_path.read_text("utf-8"))

        api_basic.get_log_repository = CountingLogRepository
        reset_cache()
        try:
            start = dt.date.fromisoformat(date_one)
            end = dt.date.fromisoformat(date_two)
            first = list(api_tests._iter_test_records(start, end))
            duplicate_rows = [row for row in first if row.get("name") == duplicate_name]
            _assert_unit(
                len(first) == 2,
                "malformed, invalid-date, and zero-total legacy records must remain excluded",
            )
            _assert_unit(
                len(duplicate_rows) == 2,
                "same blank-createdAt test on different dates must remain two attempts",
            )
            _assert_unit(
                [row.get("day").isoformat() for row in duplicate_rows] == [date_one, date_two],
                "durable-first order and cross-date legacy fallback must stay stable",
            )
            _assert_unit(
                duplicate_rows[0].get("memo") == "durable",
                "same-day durable test records must remain authoritative over legacy duplicates",
            )
            _assert_unit(
                len(list(api_tests._iter_test_records(start, start))) == 1,
                "test record date bounds must remain inclusive",
            )

            duplicate_rows[-1]["meta"]["type"] = "POISONED"
            second = list(api_tests._iter_test_records(start, end))
            _assert_unit(load_calls == 1, "unchanged legacy logs must be projected once across requests")
            _assert_unit(
                all(row.get("meta", {}).get("type") == "UNIT" for row in second),
                "cached legacy test candidates must return defensive copies",
            )

            replacement = tmp / "logs-replacement.json"
            replacement.write_text(
                json.dumps(
                    {
                        date_two: {
                            "s1": {"tests": [record(duplicate_name)]},
                            "s2": {"tests": [record("단원 / 교체 감지", created_at="2026-06-02T12:00:00Z")]},
                        }
                    },
                    ensure_ascii=False,
                ),
                "utf-8",
            )
            os.replace(replacement, logs_path)
            after_replace = list(api_tests._iter_test_records(start, end))
            _assert_unit(load_calls == 2, "atomic logs replacement must invalidate legacy test candidates")
            _assert_unit(
                any(row.get("name") == "단원 / 교체 감지" for row in after_replace),
                "cache reload must expose records from the replaced logs file",
            )

            reset_cache()
            fallback_failures = 0

            class FailingLogRepository:
                def read_json_map(self):
                    raise RuntimeError("synthetic repository read failure")

            def fail_logs_load_once(path):
                nonlocal fallback_failures
                if pathlib.Path(path) == logs_path and fallback_failures == 0:
                    fallback_failures += 1
                    raise RuntimeError("synthetic fallback read failure")
                return original_load(path)

            api_basic.get_log_repository = FailingLogRepository
            api_tests.load = fail_logs_load_once
            try:
                list(api_tests._iter_test_records(start, end))
                _assert_unit(False, "failed legacy reads must remain visible")
            except RuntimeError as exc:
                _assert_unit(
                    "synthetic fallback read failure" in str(exc),
                    "legacy read failure must not be replaced by stale cached data",
                )
            recovered = list(api_tests._iter_test_records(start, end))
            _assert_unit(
                any(row.get("name") == "단원 / 교체 감지" for row in recovered),
                "a failed legacy read must not become sticky",
            )

            api_tests.load = original_load
            reset_cache()
            unstable_calls = 0

            class ReplacingLogRepository:
                def read_json_map(self):
                    nonlocal unstable_calls
                    unstable_calls += 1
                    snapshot = json.loads(logs_path.read_text("utf-8"))
                    if unstable_calls == 1:
                        next_path = tmp / "logs-concurrent-replacement.json"
                        next_path.write_text(
                            json.dumps(
                                {date_two: {"s3": {"tests": [record("단원 / 안정 재시도")]}}},
                                ensure_ascii=False,
                            ),
                            "utf-8",
                        )
                        os.replace(next_path, logs_path)
                    return snapshot

            api_basic.get_log_repository = ReplacingLogRepository
            first_unstable = list(api_tests._iter_test_records(start, end))
            second_stable = list(api_tests._iter_test_records(start, end))
            _assert_unit(
                unstable_calls == 2,
                "a signature change during legacy projection must force a stable reload",
            )
            _assert_unit(
                any(row.get("name") == "단원 / 교체 감지" for row in first_unstable)
                and any(row.get("name") == "단원 / 안정 재시도" for row in second_stable),
                "unstable reads may serve their snapshot but must not cache it under the replacement signature",
            )
        finally:
            api_tests.TESTS_PATH = original_tests_path
            api_tests.LOGS_PATH = original_logs_path
            api_basic.get_log_repository = original_get_log_repository
            api_tests.load = original_load
            reset_cache()


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
    import core.absence_assignment_cleanup as cleanup
    import routes.api_attend as api_attend
    from flask import Flask
    from core.progress_rules import TEST_ASSIGN_CHANGE_ORDER_META_KEY

    cleanup_source = (ROOT / "core/absence_assignment_cleanup.py").read_text("utf-8")
    transaction_source = (ROOT / "core/absence_transaction.py").read_text("utf-8")
    app_source = (ROOT / "app.py").read_text("utf-8")
    attendance_source = (ROOT / "routes/api_attend.py").read_text("utf-8")
    makeup_source = (ROOT / "routes/api_makeup_carryover.py").read_text("utf-8")
    sync_source = (ROOT / "scripts/sync_makeup_sheet_additive.py").read_text("utf-8")
    _assert_unit(
        "from routes.api_attend import" not in makeup_source
        and "from routes.api_attend import" not in sync_source,
        "makeup sync consumers must not import attendance private cleanup helpers",
    )
    _assert_unit(
        all(
            "from routes.absence_assignment_cleanup import" in source
            for source in (attendance_source, makeup_source, sync_source)
        ),
        "absence writers must share the public transaction adapter",
    )
    _assert_unit(
        all(
            "absence_write_scope" in source
            and "commit_new_absences_locked" in source
            and "clear_assignments_for_new_absences(" not in source
            for source in (attendance_source, makeup_source, sync_source)
        ),
        "live absence writers must use one journal transaction instead of legacy partial cleanup",
    )
    _assert_unit(
        "from routes." not in cleanup_source
        and "from routes." not in transaction_source,
        "core absence planning and transaction modules must stay independent from Flask routes",
    )
    _assert_unit(
        "recover_pending_absence_transactions()" in app_source
        and "absence_read_barrier()" in app_source
        and 'path in {"/api/absent", "/api/makeup-sheet-sync"}' in app_source,
        "app startup recovery and request barrier must protect absence-related stores without re-locking owners",
    )
    _assert_unit(
        all(
            f'"{path}"' in app_source
            for path in (
                "/api/watch",
                "/api/watch-status",
                "/api/kollus/lms-callback",
            )
        ),
        "watch, direct progress, and Kollus callback writes must wait for absence consistency",
    )
    _assert_unit(
        "external_admin_api_auth_required(" in app_source
        and "student_app_public_request" in app_source
        and '"WWW-Authenticate": ADMIN_AUTH_CHALLENGE' in app_source,
        "off-academy administrator APIs must require Basic auth without replacing public student gates",
    )
    _assert_unit(
        "recover_material_state_if_needed(" in app_source
        and 'app.config["MATERIAL_STATE_WRITES_DEGRADED"]' in app_source,
        "material recovery failure must degrade file/material writes without preventing app startup",
    )

    sid = "s1"
    date = "2026-06-07"
    assigned_label = "단원평가 / 대수 / Lv.3 / 1회차 / 결석전배정"
    distributed_label = "학군지 기출 / 대수 / 상 / 기말고사 / 2회차 / 압구정고"
    completed_label = "복습 테스트 / 대수 / 상 / 3회차 / 완료"
    skipped_label = "단원평가 / 대수 / Lv.3 / 2회차 / 제외"

    _assert_unit(
        cleanup.absence_test_status_value("assigned") == "interrupted",
        "absence must turn assigned tests into 배부/interrupted",
    )
    _assert_unit(
        cleanup.absence_test_status_value({"status": "assigned", "memo": "keep"}) == {
            "status": "interrupted",
            "memo": "keep",
        },
        "absence must preserve dict test status metadata while changing assigned to 배부",
    )
    _assert_unit(
        cleanup.absence_test_status_value("interrupted") == "interrupted",
        "absence must keep existing 배부/interrupted tests",
    )
    _assert_unit(cleanup.absence_test_status_value("done") == "done", "absence must preserve completed tests")
    _assert_unit(cleanup.absence_test_status_value("skip") == "skip", "absence must preserve excluded tests")

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
    next_entry, changed = cleanup.cleared_assignment_log_entry(entry, sid)
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

    with tempfile.TemporaryDirectory(prefix="verify-absence-test-order-") as tmpdir:
        progress_path = pathlib.Path(tmpdir) / "progress.json"
        progress_path.write_text(
            json.dumps({
                date: {
                    sid: {
                        "tests": {
                            assigned_label: "assigned",
                            distributed_label: "interrupted",
                        },
                        TEST_ASSIGN_CHANGE_ORDER_META_KEY: {
                            assigned_label: 3,
                            distributed_label: 4,
                        },
                    },
                },
            }, ensure_ascii=False),
            "utf-8",
        )
        cleanup.clear_absence_progress_tests({(date, sid)}, progress_path=progress_path)
        progress_after = json.loads(progress_path.read_text("utf-8"))
        progress_entry = progress_after[date][sid]
        _assert_unit(
            progress_entry["tests"][assigned_label] == "interrupted",
            "absence progress transition must turn assigned into interrupted",
        )
        _assert_unit(
            progress_entry[TEST_ASSIGN_CHANGE_ORDER_META_KEY][assigned_label] == 5
            and progress_entry[TEST_ASSIGN_CHANGE_ORDER_META_KEY][distributed_label] == 4,
            "absence progress transition must make only the changed test newest",
        )

    with tempfile.TemporaryDirectory(prefix="verify-absence-cleanup-service-") as tmpdir:
        base = pathlib.Path(tmpdir)
        updates_path = base / "updates.json"
        progress_path = base / "progress.json"
        updates_path.write_text(
            json.dumps({
                date: {
                    sid: {"videos": ["m1"], "source": "auto"},
                    "keep-sid": {"videos": ["m2"], "source": "manual"},
                },
                "2026-06-08": {sid: {"videos": ["m3"], "source": "auto"}},
            }),
            "utf-8",
        )
        progress_path.write_text(
            json.dumps({
                date: {sid: {"tests": {assigned_label: "assigned"}}},
                "2026-06-08": {sid: {"tests": {assigned_label: "assigned"}}},
            }, ensure_ascii=False),
            "utf-8",
        )

        class ReadResult:
            def __init__(self, entry):
                self.entry = entry

        class FakeLogRepository:
            def __init__(self):
                self.entries = {
                    (date, sid): {
                        "assignedTests": [
                            {"label": assigned_label, "status": "assigned", "memo": "keep"},
                        ],
                        "notes": "상담 메모",
                    },
                    ("2026-06-08", sid): {"notes": "다른 날짜"},
                }

            def read_entry(self, date_key, student_id):
                return ReadResult(json.loads(json.dumps(
                    self.entries.get((date_key, student_id), {}),
                    ensure_ascii=False,
                )))

            def transform_entries(self, pairs, transform):
                for pair in pairs:
                    current = self.entries.get(pair, {})
                    next_entry, changed = transform(current, pair[1])
                    if changed:
                        self.entries[pair] = next_entry

        repository = FakeLogRepository()
        factory_calls = []

        def repository_factory():
            factory_calls.append(True)
            return repository

        cleanup.clear_assignments_for_new_absences(
            {(date, sid)},
            updates_path=updates_path,
            progress_path=progress_path,
            log_repository_factory=repository_factory,
        )
        updates_after = json.loads(updates_path.read_text("utf-8"))
        progress_after = json.loads(progress_path.read_text("utf-8"))
        log_after = repository.entries[(date, sid)]
        _assert_unit(sid not in updates_after[date], "absence cleanup removes only the new date/SID video assignment")
        _assert_unit(
            updates_after[date]["keep-sid"]["videos"] == ["m2"]
            and updates_after["2026-06-08"][sid]["videos"] == ["m3"],
            "absence cleanup preserves other students and dates",
        )
        _assert_unit(
            progress_after[date][sid]["tests"][assigned_label] == "interrupted"
            and progress_after["2026-06-08"][sid]["tests"][assigned_label] == "assigned",
            "absence cleanup changes only the new date/SID assigned test",
        )
        _assert_unit(
            log_after["assignedTests"][0]["status"] == "interrupted"
            and log_after["assignedTests"][0]["memo"] == "keep"
            and log_after["testAssignmentAbsenceCarryover"]["assignedTests"][0]["label"] == assigned_label,
            "absence cleanup preserves test metadata and records the carryover before clearing",
        )
        _assert_unit(
            repository.entries[("2026-06-08", sid)] == {"notes": "다른 날짜"}
            and len(factory_calls) == 2,
            "absence cleanup preserves other log dates and the legacy two-repository-call sequence",
        )

    runtime_absent = {
        "by_date": {
            date: [sid, "keep-sid"],
            "2026-06-08": [sid, "other-date"],
        },
        "by_student": {sid: date, "keep-sid": date, "other-date": "2026-06-08"},
        "by_slot": {
            date: {sid: [1, 2], "keep-sid": [2]},
            "2026-06-08": {sid: [1], "other-date": [2]},
        },
    }
    notifications: list[tuple[str, ...]] = []
    locked_saves: list[bool] = []
    original_abs_path = api_attend.ABS_PATH
    original_load_absent = api_attend.load_absent
    original_save_absent = api_attend.save_absent
    original_enqueue = api_attend.enqueue_current_schedule_changes

    with tempfile.TemporaryDirectory(prefix="verify-absence-recover-") as tmpdir:
        api_attend.ABS_PATH = pathlib.Path(tmpdir) / "absent.json"
        api_attend.load_absent = lambda: json.loads(json.dumps(runtime_absent))

        def save_absent_fixture(payload, *, locked=False):
            locked_saves.append(bool(locked))
            runtime_absent.clear()
            runtime_absent.update(json.loads(json.dumps(payload)))

        api_attend.save_absent = save_absent_fixture
        api_attend.enqueue_current_schedule_changes = lambda sids: notifications.append(tuple(sids)) or 0
        try:
            app = Flask("verify-absence-recover-route")
            app.register_blueprint(api_attend.bp_api_attend)
            client = app.test_client()
            response = client.post("/api/absent/recover", json={"date": date, "sids": [sid, sid]})
            payload = response.get_json() or {}
            _assert_unit(response.status_code == 200, "narrow absence recovery must return HTTP 200")
            _assert_unit(payload["by_date"][date] == ["keep-sid"], "recovery removes only the selected date/sid")
            _assert_unit(payload["by_date"]["2026-06-08"] == [sid, "other-date"], "other-date absence rows survive")
            _assert_unit(sid not in payload["by_student"], "matching by_student mapping is removed")
            _assert_unit(payload["by_slot"][date] == {"keep-sid": [2]}, "matching by_slot mapping is removed")
            _assert_unit(payload["by_slot"]["2026-06-08"][sid] == [1], "other-date slot mapping survives")
            _assert_unit(notifications == [(sid,)], "recovery notification projection deduplicates selected SIDs")
            _assert_unit(locked_saves == [True], "narrow recovery must save while holding the shared absence lock")

            repeat = client.post("/api/absent/recover", json={"date": date, "sids": [sid]})
            _assert_unit(repeat.status_code == 200, "narrow absence recovery must be idempotent")
            _assert_unit((repeat.get_json() or {}).get("by_date", {}).get(date) == ["keep-sid"], "retry keeps canonical state")
            _assert_unit(
                client.post("/api/absent/recover", json={"date": "bad", "sids": [sid]}).status_code == 400,
                "recovery rejects invalid dates",
            )
            _assert_unit(
                client.post("/api/absent/recover", json={"date": date, "sids": []}).status_code == 400,
                "recovery rejects empty SID selections",
            )
            _assert_unit(
                client.post("/api/absent", json=runtime_absent).status_code == 428,
                "whole-map absence writes require a revision",
            )
            current = client.get("/api/absent")
            revision = current.headers.get("X-Absence-Revision")
            _assert_unit(bool(revision), "absence GET must expose a no-store revision")
            _assert_unit(
                client.post("/api/absent", json=runtime_absent, headers={"If-Match": "stale"}).status_code == 409,
                "stale whole-map absence writes must fail closed",
            )
            accepted = client.post("/api/absent", json=runtime_absent, headers={"If-Match": revision})
            _assert_unit(accepted.status_code == 200, "current-revision absence write must succeed")
            _assert_unit(locked_saves[-1] is True, "accepted whole-map writes must save under the shared lock")
        finally:
            api_attend.ABS_PATH = original_abs_path
            api_attend.load_absent = original_load_absent
            api_attend.save_absent = original_save_absent
            api_attend.enqueue_current_schedule_changes = original_enqueue

    from scripts.verify_absence_transaction import main as verify_absence_transaction
    from scripts.verify_makeup_sheet_route_safety import main as verify_makeup_sheet_route

    _assert_unit(
        verify_absence_transaction() == 0,
        "absence transaction failure injection and crash recovery checks must pass",
    )
    _assert_unit(
        verify_makeup_sheet_route() == 0,
        "makeup sheet route must delegate one atomic transaction before notifications",
    )


def run_test_shared_service_checks() -> None:
    from scripts.verify_test_shared_services import main as verify_test_shared_services

    _assert_unit(
        verify_test_shared_services() == 0,
        "test lock and answer-link shared-service checks must pass",
    )


def run_announcement_image_access_checks() -> None:
    from scripts.verify_announcement_image_access import main as verify_image_access

    _assert_unit(
        verify_image_access() == 0,
        "announcement image pure/store access matrix must pass",
    )
    for check_name in ("student-data", "academy-gates"):
        cmd = [
            sys.executable,
            "scripts/verify_student_mobile_app.py",
            "--only",
            check_name,
        ]
        print("$ " + " ".join(cmd))
        proc = _run_captured(cmd)
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        _assert_unit(
            proc.returncode == 0,
            f"announcement image actual-route check failed: {check_name}",
        )

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


def run_student_previous_video_review_bootstrap_unit_checks() -> None:
    """Exercise the shared core projection with isolated in-memory fixtures."""
    from copy import deepcopy

    from core import student_schedule_rules as schedule_rules
    from core import student_video_assignment_rules as assignment_rules
    from core import student_video_projection as video_projection
    from routes.student_bootstrap_projection import (
        StudentBootstrapProjectionDependencies,
        build_student_bootstrap_payload,
    )

    projection_py = (
        ROOT / "routes/student_bootstrap_projection.py"
    ).read_text("utf-8")

    namespace = {
        "_blocked_mids_for_sid": video_projection.blocked_mids_for_sid,
        "_chap_num": video_projection.chapter_number,
        "_academy_restricted_student_videos": video_projection.academy_restricted_student_videos,
        "_student_completion_videos": video_projection.student_completion_videos,
        "_student_primary_video_mids": video_projection.student_primary_video_mids,
        "_student_review_states_before_date": video_projection.student_review_states_before_date,
        "_student_review_states_through_date": video_projection.student_review_states_through_date,
        "_student_current_curriculum_videos": video_projection.student_current_curriculum_videos,
        "_student_eligible_review_video_mids": video_projection.student_eligible_review_video_mids,
        "_filter_self_study_assignment_for_response": video_projection.filter_self_study_assignment_for_response,
        "_filter_auto_assignment_for_current_curriculum": video_projection.filter_auto_assignment_for_current_curriculum,
        "_student_review_video_projection": video_projection.student_review_video_projection,
        "_self_study_review_video_mids": assignment_rules.self_study_review_video_mids,
        "_student_absent_on_date": schedule_rules.student_absent_on_date,
    }

    student = {
        "id": "007",
        "curriculum": "ALG",
        "subCurriculum": "BASE",
    }
    videos = [
        {
            "mid": "m1",
            "title": "One",
            "chapter": "1",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
            "url": "https://video.example/m1",
            "eventDate": "must-not-leak",
            "unknownField": {"keep": True},
        },
        {
            "mid": "m2",
            "title": "Two duplicate later",
            "chapter": "2",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
        },
        {
            "mid": "m2",
            "title": "Two duplicate first",
            "chapter": "2",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
        },
        {
            "mid": "m3",
            "title": "Three",
            "chapter": "3",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
        },
        {
            "mid": "m5",
            "title": "Five",
            "chapter": "5",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
            "link": "https://video.example/m5",
            "src": "https://video.example/m5-src",
            "playUrl": "https://video.example/m5-play",
            "stream_url": "https://video.example/m5-stream",
            "embed_url": "https://video.example/m5-embed",
            "progress": {"raw": "must-not-leak"},
            "watch": {"raw": "must-not-leak"},
        },
        {
            "mid": "m-orange",
            "title": "Watching",
            "chapter": "8",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
        },
        {
            "mid": "m-skip",
            "title": "Skipped",
            "chapter": "6",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
        },
        {
            "mid": "m4",
            "title": "Other sub-curriculum",
            "chapter": "4",
            "curriculum": "ALG",
            "subCurriculum": "OTHER",
        },
        {
            "mid": "m-old",
            "title": "Old course",
            "chapter": "9",
            "curriculum": "OLD",
            "subCurriculum": "BASE",
        },
    ]
    progress = {
        "2026-05-29": {
            "007": {
                "m1": "done",
                "m2": "interrupted",
                "m-old": "done",
                "m-deleted": "done",
                "m-skip": "skip",
                "__manualProgressMids": {"m-white": True},
            },
        },
        "2026-05-30": {"7": {"m2": "done", "m3": "done"}},
        "2026-05-31": {"007": {"m4": "done", "m-current": "done", "m-orange": "interrupted"}},
        "2026-06-02": {"007": {"m5": "done"}},
        "malformed": {"007": {"m3": "done"}},
    }
    watch = {
        "2026-05-29": {
            "007": {
                "m1": {"last": 100, "dur": 100},
                "m-white": {"last": 100, "dur": 100},
                "m-below": {"last": 4, "dur": 100},
            },
        },
        "2026-05-30": {"7": {"m5": {"last": 100, "dur": 100}}},
        "2026-05-31": {"007": {"m3": {"last": 100, "dur": 100}}},
        "2026-06-02": {"007": {"m2": {"last": 100, "dur": 100}}},
    }
    progress_before = deepcopy(progress)
    watch_before = deepcopy(watch)

    projection = namespace["_student_review_video_projection"](
        student,
        videos,
        progress,
        watch,
        "2026-06-01",
        {"m1"},
        True,
    )
    _assert_unit(
        [item.get("mid") for item in projection] == ["m2", "m3", "m5"],
        "current-curriculum review projection must sort by chapter then MID ascending",
    )
    _assert_unit(
        {item.get("mid"): item.get("reviewStatus") for item in projection}
        == {"m5": "done", "m3": "done", "m2": "done"},
        "review projection must expose only completed blue statuses",
    )
    _assert_unit("m1" not in {item.get("mid") for item in projection}, "current assignment MID must be excluded")
    _assert_unit(
        "m4" not in {item.get("mid") for item in projection}
        and "m-old" not in {item.get("mid") for item in projection},
        "other sub-curriculum and other curriculum videos must stay out of the review chooser",
    )
    _assert_unit("m-skip" not in {item.get("mid") for item in projection}, "skip MID must be excluded")
    _assert_unit("m-orange" not in {item.get("mid") for item in projection}, "interrupted orange MID must be excluded")
    _assert_unit("m-deleted" not in {item.get("mid") for item in projection}, "deleted MID must be excluded")
    _assert_unit(all("eventDate" not in item for item in projection), "review item must hide eventDate")
    _assert_unit(
        all("progress" not in item and "watch" not in item for item in projection),
        "review item must not expose raw progress/watch maps",
    )
    m2_item = next(item for item in projection if item.get("mid") == "m2")
    _assert_unit(
        m2_item.get("title") == "Two duplicate later",
        "duplicate catalog selection must keep one canonical MID projection",
    )

    restricted = namespace["_student_review_video_projection"](
        student,
        videos,
        progress,
        watch,
        "2026-06-01",
        set(),
        False,
    )
    blocked_keys = {
        "url", "link", "src", "source", "playUrl", "play_url", "streamUrl", "stream_url",
        "embedUrl", "embed_url",
    }
    _assert_unit(
        restricted and all(not blocked_keys.intersection(item) and item.get("playbackRestricted") is True for item in restricted),
        "outside-academy review projection must strip playback fields last",
    )

    missing_sub_student = {"id": "007", "curriculum": "ALG", "subCurriculum": "MISSING"}
    missing_sub_projection = namespace["_student_review_video_projection"](
        missing_sub_student,
        videos,
        {"2026-05-30": {"007": {"m4": "done"}}},
        {},
        "2026-06-01",
        set(),
        True,
    )
    _assert_unit(
        missing_sub_projection == [],
        "a missing exact sub-curriculum must not fall back to another sub-curriculum in video review",
    )
    missing_sub_eligible = namespace["_student_eligible_review_video_mids"](
        missing_sub_student,
        videos,
        {"2026-05-30": {"007": {"m4": "done"}}},
        {},
        "2026-06-01",
    )
    _assert_unit(
        missing_sub_eligible == set(),
        "review registration authorization must not fall back to another sub-curriculum",
    )

    eligible_mids = namespace["_student_eligible_review_video_mids"](
        student,
        videos,
        progress,
        watch,
        "2026-06-01",
    )
    _assert_unit(
        eligible_mids == {"m1", "m2", "m3", "m5"},
        "review registration authorization must allow only completed blue videos in the exact current curriculum",
    )

    mijeok_student = {"id": "007", "curriculum": "미적분1", "subCurriculum": "APEX"}
    mijeok_videos = [
        {"mid": "mijeok1-apex", "curriculum": "미적분1", "subCurriculum": "APEX", "chapter": "1"},
        {"mid": "mijeok1-able", "curriculum": "미적분1", "subCurriculum": "A:Ble", "chapter": "2"},
        {"mid": "mijeok2-apex", "curriculum": "미적분2", "subCurriculum": "APEX", "chapter": "3"},
    ]
    mijeok_projection = namespace["_student_review_video_projection"](
        mijeok_student,
        mijeok_videos,
        {"2026-05-30": {"007": {
            "mijeok1-apex": "done",
            "mijeok1-able": "done",
            "mijeok2-apex": "done",
        }}},
        {},
        "2026-06-01",
        set(),
        True,
    )
    _assert_unit(
        [item.get("mid") for item in mijeok_projection] == ["mijeok1-apex"],
        "a 미적분1/APEX student must see only 미적분1/APEX completed videos in video review",
    )

    assignment = {
        "videos": ["m1", "m5", "m-unwatched"],
        "source": "selfStudy",
        "futureField": {"keep": "yes"},
    }
    assignment_before = deepcopy(assignment)
    filtered = namespace["_filter_self_study_assignment_for_response"](assignment, {"m1", "m5"})
    _assert_unit(filtered == {"videos": ["m1", "m5"], "source": "selfStudy", "futureField": {"keep": "yes"}}, "self-study response must preserve unknown fields")
    _assert_unit(assignment == assignment_before, "self-study response filter must not mutate persisted assignment")
    legacy = namespace["_filter_self_study_assignment_for_response"](["m5", "m-unwatched"], {"m5"})
    _assert_unit(legacy == ["m5"], "legacy self-study list must filter unwatched MIDs")

    mids = [
        {"mid": f"m{index}", "chapter": str(index), "curriculum": "ALG", "subCurriculum": "BASE"}
        for index in range(1, 7)
    ]
    _assert_unit(
        namespace["_self_study_review_video_mids"](
            mids,
            ["m6"],
            [],
            {"m1", "m3", "m5"},
        ) == ["m1", "m3", "m5"],
        "self-study auto replacement must choose the last three eligible videos before the anchor",
    )
    _assert_unit(
        namespace["_self_study_review_video_mids"](mids, [], [], set()) == [],
        "self-study must persist no auto review assignment without an eligible anchor/history",
    )
    _assert_unit(progress == progress_before and watch == watch_before, "bootstrap fixtures must remain immutable")

    _assert_unit(projection_py.count('"reviewVideos": []') >= 2, "ghost and course-blocked bootstrap shapes must return empty review arrays")
    _assert_unit(
        "if not absent_today and not archived:" in projection_py,
        "absent and archived bootstrap shapes must return empty review arrays",
    )

    from types import SimpleNamespace

    route_namespace = dict(namespace)
    route_namespace.update({
        "DATE_RE": DATE_RE,
        "ACADEMY_ACCESS_MESSAGE": "academy-only",
        "STUDENT_COURSE_BLOCK_MESSAGE": "course-blocked",
        "SELF_STUDY_VIDEO_ASSIGN_SOURCE": "selfStudy",
        "STU_PATH": "fixture-students",
        "VID_PATH": "fixture-videos",
        "PRG_PATH": "fixture-progress",
        "UPD_PATH": "fixture-updates",
        "ASN_PATH": "fixture-assigns",
        "MAT_PATH": "fixture-materials",
        "WATCH_PATH": "fixture-watch",
    })

    route_namespace["_today_kst_iso"] = lambda: "2026-06-01"
    route_namespace["_build_latest_status_by_sid"] = lambda _progress: {}
    route_namespace["_student_dashboard_enabled"] = lambda: False
    route_namespace["_course_videos_completed"] = lambda *_args: False
    route_namespace["_student_homework_book_names_from_log"] = lambda _entry: []
    route_namespace["_assigned_material_list"] = lambda value: value.get("materials", []) if isinstance(value, dict) else []
    route_namespace["_filter_materials_for_assignment"] = lambda materials, _assigned: materials if isinstance(materials, dict) else {}
    route_namespace["_student_assigned_tests_for_date"] = lambda *_args: []
    route_namespace["_filter_assigned_tests_for_student_curriculum"] = lambda items, _student: items
    route_namespace["_academy_restricted_assigned_tests"] = lambda items, _allowed: items

    base_date = "2026-06-01"
    base_sid = "007"
    base_student = {
        "id": base_sid,
        "name": "Fixture Student",
        "curriculum": "ALG",
        "subCurriculum": "BASE",
        "day1": "월 13:00",
    }
    base_videos = [
        {"mid": "m1", "title": "Assigned", "chapter": "1", "curriculum": "ALG", "subCurriculum": "BASE", "url": "https://v/m1"},
        {"mid": "m2", "title": "Interrupted", "chapter": "2", "curriculum": "ALG", "subCurriculum": "BASE", "url": "https://v/m2"},
        {"mid": "m3", "title": "Three", "chapter": "3", "curriculum": "ALG", "subCurriculum": "BASE", "url": "https://v/m3"},
        {"mid": "m5", "title": "Five", "chapter": "5", "curriculum": "ALG", "subCurriculum": "BASE", "url": "https://v/m5"},
        {"mid": "m-skip", "title": "Skipped", "chapter": "6", "curriculum": "ALG", "subCurriculum": "BASE"},
        {"mid": "m-current", "title": "Current", "chapter": "7", "curriculum": "ALG", "subCurriculum": "BASE"},
        {"mid": "m4", "title": "Fallback only", "chapter": "4", "curriculum": "ALG", "subCurriculum": "OTHER"},
        {"mid": "m-old", "title": "Old course", "chapter": "8", "curriculum": "OLD", "subCurriculum": "BASE"},
    ]
    base_progress = {
        "2026-05-29": {base_sid: {"m1": "done", "m2": "interrupted", "m-old": "done", "m-deleted": "done", "m-skip": "done"}},
        "2026-05-30": {"7": {"m3": "done"}},
        base_date: {base_sid: {"m-current": "done", "m-skip": "skip"}},
        "2026-06-02": {base_sid: {"m5": "done"}},
    }
    base_watch = {"2026-05-30": {"7": {"m5": {"last": 100, "dur": 100}}}}
    route_namespace["_build_auto_assignment_blocked_by_sid"] = lambda _progress, _watch: {base_sid: {"m1", "m-current"}}

    def make_route_state() -> dict:
        return {
            "date": base_date,
            "sid": base_sid,
            "student": deepcopy(base_student),
            "videos": deepcopy(base_videos),
            "progress": deepcopy(base_progress),
            "watch": deepcopy(base_watch),
            "updates": {base_date: {base_sid: {"videos": ["m1"], "source": "auto"}}},
            "materials": {},
            "assigns": {},
            "absent": {"by_date": {}, "by_student": {}},
            "log_entry": {},
            "academy_allowed": True,
            "registered": True,
            "log_reads": 0,
        }

    route_state = make_route_state()
    route_namespace["_load_material_state_for_read"] = lambda: (
        deepcopy(route_state["materials"]),
        deepcopy(route_state["assigns"]),
        {},
        False,
    )


    def fixture_load(path):
        if path == route_namespace["STU_PATH"]:
            return [deepcopy(route_state["student"])]
        if path == route_namespace["VID_PATH"]:
            return deepcopy(route_state["videos"])
        if path == route_namespace["UPD_PATH"]:
            return deepcopy(route_state["updates"])
        if path == route_namespace["WATCH_PATH"]:
            return deepcopy(route_state["watch"])
        if path == route_namespace["ASN_PATH"]:
            return deepcopy(route_state["assigns"])
        if path == route_namespace["MAT_PATH"]:
            return deepcopy(route_state["materials"])
        return {}

    class FixtureRepository:
        def read_entry(self, _date: str, _sid: str):
            route_state["log_reads"] += 1
            return SimpleNamespace(entry=deepcopy(route_state["log_entry"]))

        def read_json_map(self):
            return {route_state["date"]: {route_state["sid"]: deepcopy(route_state["log_entry"])}}

    route_namespace["load"] = fixture_load
    route_namespace["load_absent"] = lambda: deepcopy(route_state["absent"])
    route_namespace["_load_progress_strict"] = lambda *_args, **_kwargs: deepcopy(route_state["progress"])
    route_namespace["get_log_repository"] = lambda: FixtureRepository()
    route_namespace["academy_network_allowed"] = lambda: bool(route_state["academy_allowed"])
    route_namespace["_student_is_registered_on_date"] = lambda *_args, **_kwargs: bool(route_state["registered"])
    route_namespace["_student_is_self_study_on_date"] = lambda _logs, _date, _sid, _student: bool(route_state["log_entry"].get("selfStudy"))
    route_namespace["_load_updates_with_auto_assign"] = lambda **_kwargs: deepcopy(route_state["updates"])
    route_namespace["_active_student_alias_sid"] = lambda *_args: None

    dependencies = StudentBootstrapProjectionDependencies(
        students_path=route_namespace["STU_PATH"],
        videos_path=route_namespace["VID_PATH"],
        updates_path=route_namespace["UPD_PATH"],
        watch_path=route_namespace["WATCH_PATH"],
        load=fixture_load,
        load_absent=lambda: deepcopy(route_state["absent"]),
        load_progress=lambda: deepcopy(route_state["progress"]),
        load_material_state=lambda: route_namespace[
            "_load_material_state_for_read"
        ](),
        get_log_repository=lambda: FixtureRepository(),
        homework_books_from_log=lambda entry: route_namespace[
            "_student_homework_book_names_from_log"
        ](entry),
        student_is_registered=lambda *args, **kwargs: route_namespace[
            "_student_is_registered_on_date"
        ](*args, **kwargs),
        student_is_self_study=lambda *args, **kwargs: route_namespace[
            "_student_is_self_study_on_date"
        ](*args, **kwargs),
        student_absent=lambda *args, **kwargs: route_namespace[
            "_student_absent_on_date"
        ](*args, **kwargs),
        active_alias_sid=lambda *args, **kwargs: route_namespace[
            "_active_student_alias_sid"
        ](*args, **kwargs),
        dashboard_enabled=lambda: route_namespace[
            "_student_dashboard_enabled"
        ](),
        dashboard_projection=lambda **_kwargs: {},
        build_latest_status=lambda progress_value: route_namespace[
            "_build_latest_status_by_sid"
        ](progress_value),
        student_completion_videos=lambda student_value, videos_value: route_namespace[
            "_student_completion_videos"
        ](student_value, videos_value),
        course_videos_completed=lambda *args, **kwargs: route_namespace[
            "_course_videos_completed"
        ](*args, **kwargs),
        load_updates_with_auto_assign=lambda **kwargs: route_namespace[
            "_load_updates_with_auto_assign"
        ](**kwargs),
        build_auto_blocked=lambda progress_value, watch_value: route_namespace[
            "_build_auto_assignment_blocked_by_sid"
        ](progress_value, watch_value),
        blocked_mids=route_namespace["_blocked_mids_for_sid"],
        eligible_review_mids=route_namespace[
            "_student_eligible_review_video_mids"
        ],
        filter_self_study_assignment=route_namespace[
            "_filter_self_study_assignment_for_response"
        ],
        filter_auto_assignment=route_namespace[
            "_filter_auto_assignment_for_current_curriculum"
        ],
        review_states_through_date=route_namespace[
            "_student_review_states_through_date"
        ],
        student_primary_video_mids=route_namespace[
            "_student_primary_video_mids"
        ],
        academy_restricted_videos=route_namespace[
            "_academy_restricted_student_videos"
        ],
        review_video_projection=route_namespace[
            "_student_review_video_projection"
        ],
        assigned_material_list=route_namespace["_assigned_material_list"],
        filter_materials=route_namespace["_filter_materials_for_assignment"],
        assigned_tests=route_namespace["_student_assigned_tests_for_date"],
        filter_tests_for_curriculum=route_namespace[
            "_filter_assigned_tests_for_student_curriculum"
        ],
        academy_restricted_tests=route_namespace[
            "_academy_restricted_assigned_tests"
        ],
        today_iso=lambda: route_namespace["_today_kst_iso"](),
        dashboard_course_block_message="course-blocked",
    )

    def invoke_route(sid: str = base_sid) -> tuple[dict, int]:
        return build_student_bootstrap_payload(
            dependencies,
            sid=sid,
            date=route_state["date"],
            public_request=False,
            academy_allowed_resolver=lambda: bool(
                route_state["academy_allowed"]
            ),
        )

    def assert_success_shape(label: str, payload: dict, status: int = 200) -> None:
        _assert_unit(status == 200 and payload.get("ok") is True, f"{label} route response must be successful")
        _assert_unit(isinstance(payload.get("reviewVideos"), list), f"{label} success shape must contain reviewVideos array")

    regular_persisted = deepcopy(route_state["updates"])
    regular_payload, regular_status = invoke_route()
    assert_success_shape("regular", regular_payload, regular_status)
    regular_review = regular_payload["reviewVideos"]
    regular_review_mids = {item.get("mid") for item in regular_review}
    regular_videos_by_mid = {item.get("mid"): item for item in regular_payload["videos"]}
    _assert_unit(
        regular_videos_by_mid.get("m1", {}).get("todayAutoAssignmentStatus") == "done",
        "actual bootstrap route must retain today's completed automatic assignment with blue status",
    )
    _assert_unit(
        "m-current" in regular_review_mids,
        "actual bootstrap route must include every current-date completed MID in video review",
    )
    _assert_unit(
        "m-skip" not in regular_review_mids,
        "actual bootstrap route must exclude skip review MID",
    )
    _assert_unit(
        [item.get("mid") for item in regular_review] == ["m3", "m5", "m-current"],
        "actual bootstrap route must expose current-curriculum review videos in ascending chapter order",
    )
    _assert_unit(
        [item.get("reviewStatus") for item in regular_review] == ["done", "done", "done"],
        "actual bootstrap route must expose completed blue review status only",
    )
    _assert_unit(
        "m1" not in regular_review_mids
        and "m-current" in regular_review_mids
        and "m2" not in regular_review_mids
        and "m-skip" not in regular_review_mids
        and "m-old" not in {item.get("mid") for item in regular_review}
        and "m-deleted" not in {item.get("mid") for item in regular_review},
        "actual bootstrap route must keep today's completed assignment out of review while other completed MIDs remain eligible",
    )
    _assert_unit(
        all(
            item.get("reviewStatus") == "done"
            and "eventDate" not in item
            and "progress" not in item
            and "watch" not in item
            for item in regular_review
        ),
        "actual bootstrap route must expose only the public review schema",
    )
    _assert_unit(regular_payload["updates"] == regular_persisted, "regular assignment response must remain unchanged")
    _assert_unit(route_state["log_reads"] == 1, "bootstrap route must reuse one date-log read")

    route_state = make_route_state()
    route_state["updates"] = {base_date: {base_sid: {"videos": ["m-current"], "source": "auto"}}}
    current_done_payload, current_done_status = invoke_route()
    _assert_unit(current_done_status == 200, "current-date completed assignment bootstrap must succeed")
    current_done_playlist = {item.get("mid") for item in current_done_payload["videos"]}
    current_done_review = {item.get("mid") for item in current_done_payload["reviewVideos"]}
    current_done_video = next(
        (item for item in current_done_payload["videos"] if item.get("mid") == "m-current"),
        {},
    )
    _assert_unit(
        "m-current" in current_done_playlist
        and "m-current" not in current_done_review
        and current_done_video.get("todayAutoAssignmentStatus") == "done",
        "current-date completed automatic assignment must remain in the playlist with blue status",
    )

    route_namespace["_today_kst_iso"] = lambda: "2099-01-01"
    historical_done_payload, historical_done_status = invoke_route()
    _assert_unit(historical_done_status == 200, "historical completed assignment bootstrap must succeed")
    _assert_unit(
        "m-current" not in {item.get("mid") for item in historical_done_payload["videos"]}
        and "m-current" in {item.get("mid") for item in historical_done_payload["reviewVideos"]},
        "historical completed automatic assignment must keep the existing review-only projection",
    )
    route_namespace["_today_kst_iso"] = lambda: base_date

    route_state["academy_allowed"] = False
    restricted_payload, restricted_status = invoke_route()
    assert_success_shape("restricted", restricted_payload, restricted_status)
    restricted_keys = {"url", "link", "src", "source", "playUrl", "play_url", "streamUrl", "stream_url", "embedUrl", "embed_url"}
    _assert_unit(
        restricted_payload["reviewVideos"]
        and all(not restricted_keys.intersection(item) and item.get("playbackRestricted") is True for item in restricted_payload["reviewVideos"]),
        "actual bootstrap route must apply restricted playback stripping after review projection",
    )

    route_state = make_route_state()
    route_state["updates"] = {
        base_date: {
            base_sid: {
                "videos": ["m2", "m4", "m-old"],
                "source": "auto",
                "unknown": {"keep": True},
            },
        },
    }
    stale_auto_persisted = deepcopy(route_state["updates"])
    stale_auto_payload, stale_auto_status = invoke_route()
    assert_success_shape("stale auto curriculum", stale_auto_payload, stale_auto_status)
    _assert_unit(
        stale_auto_payload["updates"][base_date][base_sid] == {
            "videos": ["m2"],
            "source": "auto",
            "unknown": {"keep": True},
        }
        and [item.get("mid") for item in stale_auto_payload["videos"]] == ["m2"],
        "student bootstrap must expose only current-curriculum MIDs from an automatic assignment",
    )
    _assert_unit(
        route_state["updates"] == stale_auto_persisted,
        "student bootstrap automatic curriculum filtering must not rewrite historical snapshots",
    )

    route_state = make_route_state()
    route_state["updates"] = {
        base_date: {
            base_sid: {
                "videos": ["m2", "m4", "m-old"],
                "source": "manual",
                "unknown": {"keep": True},
            },
        },
    }
    manual_extra_payload, manual_extra_status = invoke_route()
    assert_success_shape("manual cross curriculum", manual_extra_payload, manual_extra_status)
    _assert_unit(
        manual_extra_payload["updates"][base_date][base_sid]["videos"] == ["m2", "m4", "m-old"]
        and {item.get("mid") for item in manual_extra_payload["videos"]} == {"m2", "m4", "m-old"},
        "student bootstrap must preserve explicit manual cross-curriculum video additions",
    )

    route_state = make_route_state()
    route_state["log_entry"] = {"selfStudy": True}
    route_state["updates"] = {
        base_date: {
            base_sid: {
                "videos": ["m1", "unwatched"],
                "source": "selfStudy",
                "unknown": {"keep": True},
            },
        },
    }
    self_study_persisted = deepcopy(route_state["updates"])
    self_study_payload, self_study_status = invoke_route()
    assert_success_shape("selfStudy manual", self_study_payload, self_study_status)
    _assert_unit(
        self_study_payload["updates"][base_date][base_sid]["videos"] == ["m1"]
        and self_study_payload["updates"][base_date][base_sid]["unknown"] == {"keep": True}
        and [item.get("mid") for item in self_study_payload["videos"]] == [],
        "actual bootstrap route must filter unwatched self-study response videos while preserving unknown fields",
    )
    _assert_unit(route_state["updates"] == self_study_persisted, "self-study response filtering must not mutate persisted updates")
    _assert_unit("m1" in {item.get("mid") for item in self_study_payload["reviewVideos"]}, "self-study completed assignment MID must remain available in review")

    route_state = make_route_state()
    route_state["log_entry"] = {"selfStudy": True}
    route_state["updates"] = {base_date: {base_sid: ["m1", "unwatched"]}}
    legacy_persisted = deepcopy(route_state["updates"])
    legacy_payload, legacy_status = invoke_route()
    assert_success_shape("selfStudy legacy", legacy_payload, legacy_status)
    _assert_unit(legacy_payload["updates"][base_date][base_sid] == ["m1"], "legacy self-study assignment must be filtered in response")
    _assert_unit(route_state["updates"] == legacy_persisted, "legacy self-study response filter must preserve persisted snapshot")

    route_state = make_route_state()
    route_state["registered"] = False
    route_state["log_entry"] = {"selfStudy": True}
    route_state["updates"] = {
        base_date: {
            base_sid: {
                "videos": ["m1"],
                "source": "selfStudy",
            },
        },
    }
    unscheduled_self_study_payload, unscheduled_self_study_status = invoke_route()
    assert_success_shape("unscheduled selfStudy", unscheduled_self_study_payload, unscheduled_self_study_status)
    _assert_unit(
        unscheduled_self_study_payload.get("courseBlocked") is not True
        and unscheduled_self_study_payload.get("selfStudy") is True
        and [item.get("mid") for item in unscheduled_self_study_payload["videos"]] == []
        and unscheduled_self_study_payload["reviewVideos"],
        "self-study on a non-scheduled date must open the student page and expose assigned/review videos",
    )

    route_state = make_route_state()
    route_state["registered"] = False
    route_state["log_entry"] = {"selfStudy": True}
    route_state["absent"]["by_date"][base_date] = [base_sid]
    route_state["updates"] = {
        base_date: {
            base_sid: {
                "videos": ["m1"],
                "source": "selfStudy",
            },
        },
    }
    absent_self_study_payload, absent_self_study_status = invoke_route()
    assert_success_shape("absent selfStudy", absent_self_study_payload, absent_self_study_status)
    _assert_unit(
        absent_self_study_payload.get("courseBlocked") is True
        and absent_self_study_payload.get("selfStudy") is True
        and absent_self_study_payload["videos"] == []
        and absent_self_study_payload["reviewVideos"] == [],
        "absence must remain fully blocked even when self-study is selected",
    )

    route_state = make_route_state()
    route_state["absent"]["by_date"][base_date] = [base_sid]
    absent_payload, absent_status = invoke_route()
    assert_success_shape("absent", absent_payload, absent_status)
    _assert_unit(absent_payload["reviewVideos"] == [], "absent student bootstrap must return empty reviewVideos")

    route_state = make_route_state()
    route_state["log_entry"] = {"archived": True}
    archived_payload, archived_status = invoke_route()
    assert_success_shape("archived", archived_payload, archived_status)
    _assert_unit(archived_payload["reviewVideos"] == [], "archived student bootstrap must return empty reviewVideos")

    route_state = make_route_state()
    route_state["registered"] = False
    blocked_payload, blocked_status = invoke_route()
    assert_success_shape("courseBlocked", blocked_payload, blocked_status)
    _assert_unit(blocked_payload.get("courseBlocked") is True and blocked_payload["reviewVideos"] == [], "course-blocked bootstrap must return empty reviewVideos")

    route_state = make_route_state()
    ghost_payload, ghost_status = invoke_route("ghost-outside-test")
    assert_success_shape("ghost", ghost_payload, ghost_status)
    _assert_unit(ghost_payload.get("ghostStudent") is True and ghost_payload["reviewVideos"] == [], "ghost bootstrap must return empty reviewVideos")

    route_state = make_route_state()
    route_state["student"]["subCurriculum"] = "MISSING"
    route_state["videos"] = [{"mid": "fallback", "title": "Fallback", "chapter": "4", "curriculum": "ALG", "subCurriculum": "OTHER", "url": "https://v/fallback"}]
    route_state["progress"] = {"2026-05-30": {"7": {"fallback": "done"}}}
    route_state["updates"] = {base_date: {base_sid: []}}
    missing_sub_payload, missing_sub_status = invoke_route()
    assert_success_shape("missing sub-curriculum", missing_sub_payload, missing_sub_status)
    _assert_unit(
        missing_sub_payload["reviewVideos"] == [],
        "actual bootstrap route must not expose another sub-curriculum when the exact current one is absent",
    )


def run_student_bootstrap_unit_checks() -> None:
    from flask import Flask
    from types import SimpleNamespace
    import routes.api_basic as api_basic
    import routes.api_student_bootstrap as api_student_bootstrap

    run_student_assigned_tests_unit_checks()

    sid = "s1"
    prev_date = "2026-05-30"
    date = "2026-05-31"
    old_label = "테스트 / 대수 / 기존"
    new_label = "테스트 / 대수 / 신규"
    stale_curriculum_label = "테스트 / 수학1 / 이전 커리큘럼"
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
    log_entry["assignedTests"].append({
        "label": stale_curriculum_label,
        "name": "이전 커리큘럼",
        "status": "assigned",
        "curriculum": "수학1",
    })
    log_entry["testAssignmentDailyTests"].append({
        "label": stale_curriculum_label,
        "name": "이전 커리큘럼",
        "status": "assigned",
        "curriculum": "수학1",
    })
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

    progress[date][sid]["tests"][stale_curriculum_label] = "assigned"

    class FakeLogRepository:
        def read_entry(self, _date, _sid):
            return SimpleNamespace(entry=log_entry)

        def read_json_map(self):
            return logs_all

    def fake_load(path):
        if path == api_basic.STU_PATH:
            return [{"id": sid, "name": "학생1", "curriculum": "대수", "day1": "일 13:00"}]
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
    original_academy_network_allowed = (
        api_student_bootstrap.academy_network_allowed
    )
    original_student_is_registered_on_date = api_basic._student_is_registered_on_date
    original_progress_loader = api_basic._load_progress_strict
    original_material_state_loader = api_basic._load_material_state_for_read
    original_config_loader = api_basic._load_tests_config_for_answer_links
    original_map_loader = api_basic._load_test_answer_link_map

    api_basic.load = fake_load
    api_basic.load_absent = lambda: {"by_date": {}, "by_student": {}}
    api_basic.get_log_repository = lambda: FakeLogRepository()
    api_student_bootstrap.academy_network_allowed = lambda: True
    api_basic._student_is_registered_on_date = lambda *_args, **_kwargs: True
    api_basic._load_progress_strict = lambda *_args, **_kwargs: progress
    api_basic._load_material_state_for_read = lambda: ({}, {}, {}, False)
    api_basic._load_tests_config_for_answer_links = lambda: tests_config
    api_basic._load_test_answer_link_map = lambda: {
        "review-config": {"1": {"answerUrl": "https://map.example/should-not-win"}}
    }
    try:
        app = Flask("verify-student-bootstrap-assigned-tests")
        api_student_bootstrap.configure_student_bootstrap_projection(
            app,
            api_basic.create_student_bootstrap_projection_dependencies(),
        )
        app.register_blueprint(api_basic.bp_api_basic)
        app.register_blueprint(
            api_student_bootstrap.bp_api_student_bootstrap
        )
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
        _assert_unit(
            stale_curriculum_label not in labels,
            "student bootstrap must hide active assignments from a previous curriculum without deleting them",
        )
        _assert_unit(stale_daily_label not in labels, "student bootstrap must suppress stale daily metadata")
        _assert_unit(
            payload["assignedTests"][1].get("answerUrl") == config_drive_url,
            "student bootstrap must resolve Drive answerUrl from config sourceFiles.solutionFileId",
        )
        _assert_unit("C:" not in response_text and str(ROOT) not in response_text, "student bootstrap must not expose raw local paths")

        api_student_bootstrap.academy_network_allowed = lambda: False
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
        api_student_bootstrap.academy_network_allowed = (
            original_academy_network_allowed
        )
        api_basic._student_is_registered_on_date = original_student_is_registered_on_date
        api_basic._load_progress_strict = original_progress_loader
        api_basic._load_material_state_for_read = original_material_state_loader
        api_basic._load_tests_config_for_answer_links = original_config_loader
        api_basic._load_test_answer_link_map = original_map_loader


def run_retired_test_submission_surface_checks() -> None:
    """Regression guard: student test submission is intentionally retired."""
    from flask import Flask
    from routes import api_tests, pages  # noqa: PLC0415

    original_tests_path = api_tests.TESTS_PATH
    with tempfile.TemporaryDirectory(prefix="retired-test-submission-") as tmp:
        tests_path = pathlib.Path(tmp) / "tests.json"
        tests_path.write_text(
            json.dumps({"2026-08-23": [{"sid": "history-sid", "score": "3/5"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        api_tests.TESTS_PATH = tests_path
        try:
            app = Flask(
                "verify-retired-test-submission-surface",
                static_folder=str(ROOT / "static"),
                static_url_path="",
            )
            app.register_blueprint(api_tests.bp_api_tests)
            app.register_blueprint(pages.bp_pages)
            client = app.test_client()
            before = tests_path.read_bytes()

            _assert_unit(client.get("/api/tests").status_code == 200, "historical test records must remain readable")
            _assert_unit(tests_path.read_bytes() == before, "historical test record read must not rewrite storage")
            _assert_unit(client.post("/api/tests", json={"sid": "history-sid"}).status_code == 405, "test history endpoint must be GET-only")
            _assert_unit(tests_path.read_bytes() == before, "rejected test history write must not change storage")

            registered_rules = {rule.rule for rule in app.url_map.iter_rules()}
            for route in ("/api/submit-test", "/api/ocr-test-sheet", "/api/ocr-test-sheet-review"):
                _assert_unit(route not in registered_rules, f"retired submission route is still registered: {route}")
                response = client.post(route, json={"sid": "history-sid"})
                _assert_unit(response.status_code in {404, 405}, f"retired submission route is unexpectedly callable: {route}")
                _assert_unit(tests_path.read_bytes() == before, f"retired route must not change storage: {route}")

            _assert_unit(client.get("/student-test/history-sid").status_code == 404, "retired student-test page alias must stay absent")
            _assert_unit(client.get("/student/history-sid").status_code == 200, "canonical student page must remain available")
        finally:
            api_tests.TESTS_PATH = original_tests_path

    student_html = (ROOT / "static/student.html").read_text(encoding="utf-8")
    student_js = (ROOT / "static/js/student.js").read_text(encoding="utf-8")
    api_tests_source = (ROOT / "routes/api_tests.py").read_text(encoding="utf-8")
    pages_source = (ROOT / "routes/pages.py").read_text(encoding="utf-8")
    app_config_source = (ROOT / "core/student_app_config.py").read_text(encoding="utf-8")
    log_repository_source = (ROOT / "core/log_repository.py").read_text(encoding="utf-8")

    for retired_id in ("openTestSubmit", "testSubmitModal", "testAnswerPreviewModal"):
        _assert_unit(retired_id not in student_html, f"retired submission HTML remains: {retired_id}")
    for retired_client in (
        "openAssignedTestSubmit",
        "openAssignedTestAnswerLink",
        "/api/submit-test",
        "/api/ocr-test-sheet",
        "testSubmissionBlocked",
    ):
        _assert_unit(retired_client not in student_js, f"retired submission client remains: {retired_client}")
    for retired_route in (
        '@bp_api_tests.post("/api/submit-test")',
        '@bp_api_tests.post("/api/ocr-test-sheet")',
        '@bp_api_tests.post("/api/ocr-test-sheet-review")',
    ):
        _assert_unit(retired_route not in api_tests_source, f"retired API decorator remains: {retired_route}")
    _assert_unit('@bp_api_tests.get("/api/tests")' in api_tests_source, "historical test endpoint must remain readable")
    _assert_unit('@bp_api_tests.post("/api/tests")' not in api_tests_source, "historical test endpoint must not accept writes")
    _assert_unit('@bp_pages.get("/student-test/<sid>")' not in pages_source, "retired student-test page alias remains")
    _assert_unit('/api/submit-test' not in app_config_source, "public student allowlist still exposes test submission")
    _assert_unit("def append_record(" not in log_repository_source, "submission-only log append API remains")

def run_admin_tests_record_detail_contract_checks() -> None:
    cmd = [sys.executable, "scripts/verify_admin_tests_record_details.py"]
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("python not found")
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin test record detail contract failed")
    if proc.stdout:
        print(proc.stdout, end="")


def run_admin_tests_record_detail_ui_checks() -> None:
    cmd = ["node", "scripts/verify_admin_tests_record_details_ui.js"]
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin test record detail UI contract failed")
    if proc.stdout:
        print(proc.stdout, end="")


def run_admin_tests_record_detail_answer_link_ui_checks() -> None:
    cmd = ["node", "scripts/verify_admin_tests_record_detail_answer_link_ui.js"]
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin test record detail answer-link UI contract failed")
    if proc.stdout:
        print(proc.stdout, end="")


def run_retired_test_submission_assignment_boundary_checks() -> None:
    cmd = [sys.executable, "scripts/verify_retired_test_submission.py"]
    proc = _run_captured(cmd)
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "retired submission and preserved assignment-boundary contract failed")
    if proc.stdout:
        print(proc.stdout, end="")


def run_student_answer_link_render_source_checks() -> None:
    student_js = (ROOT / "static/js/student.js").read_text("utf-8")
    presentation_js = (ROOT / "static/js/student/testPresentation.js").read_text("utf-8")
    render_start = student_js.index("function renderAssignedTests()")
    render_end = student_js.index("async function recoverStudentSid", render_start)
    render_block = student_js[render_start:render_end]

    for snippet in [
        "function answerUrl(test)",
        "function isAnswerRestricted(test, resolvedAnswerUrl, academyAccessAllowed)",
        "function canOpenAnswer(resolvedAnswerUrl, academyAccessAllowed)",
        "function viewModel(test, { academyAccessAllowed = false } = {})",
    ]:
        _assert_unit(snippet in presentation_js, f"student test presentation must keep answer helper seam: {snippet}")

    for snippet in [
        "const view = assignedTestViewModel(test, { academyAccessAllowed });",
        "const btn = createAssignedTestActionElement(view.canOpenAnswerUrl, view.answerUrl);",
        "if (view.answerUrl) btn.dataset.answerUrl = view.answerUrl;",
        "if (view.answerRestricted) btn.dataset.answerRestricted = '1';",
        "btn.addEventListener('click', showAcademyOnlyNotice);",
    ]:
        _assert_unit(snippet in render_block, f"student assigned-test render block must preserve answer-link behavior: {snippet}")


def run_unit_test_answer_material_contract_checks() -> None:
    """Keep assigned-test answer materials working without submission grading."""
    from routes import api_basic, api_tests  # noqa: PLC0415

    test = {
        "id": "fixture-unit-test-r2",
        "sourceId": "fixture-unit-source",
        "name": "합성 단원평가 Lv.3",
        "curriculum": "합성수학",
        "difficulty": "Lv.3",
        "round": "2",
        "problems": 3,
        "answerKeys": {"2": ["3", "2", "1"]},
    }
    cfg = {"categories": {"UNIT": {"label": "단원평가", "tests": [test]}}}
    expected_answer_url = "https://drive.google.com/file/d/fixture-unit-solution/view?usp=drivesdk"
    link_map = {test["sourceId"]: {test["round"]: {"answerUrl": expected_answer_url}}}

    api_tests_source = (ROOT / "routes/api_tests.py").read_text(encoding="utf-8")
    _assert_unit("def _grade_answers(" not in api_tests_source, "student submission grading helper must stay removed")
    _assert_unit('/api/submit-test' not in api_tests_source, "student submission route must stay removed")

    test_def = api_tests._find_test_def_by_id(cfg, test["id"])
    _assert_unit(isinstance(test_def, dict), "historical record detail lookup must still find UNIT definitions")
    key = api_tests._get_answer_key_for_round(test_def, test["problems"], 2)
    _assert_unit(key == ["3", "2", "1"], "historical record details must retain answer-key lookup")

    assigned_item = {
        "categoryLabel": "단원평가",
        "curriculum": test["curriculum"],
        "difficulty": test["difficulty"],
        "round": "2회차",
        "name": test["name"],
    }
    original_config_loader = api_basic._load_tests_config_for_answer_links
    original_map_loader = api_basic._load_test_answer_link_map
    api_basic._load_tests_config_for_answer_links = lambda: cfg
    api_basic._load_test_answer_link_map = lambda: link_map
    try:
        _assert_unit(
            api_basic._test_assignment_answer_url(assigned_item) == expected_answer_url,
            "assigned UNIT tests must still resolve the server-projected answer link",
        )
    finally:
        api_basic._load_tests_config_for_answer_links = original_config_loader
        api_basic._load_test_answer_link_map = original_map_loader

def run_unit_test_answer_material_readiness_checks() -> None:
    """Opt-in validation for UNIT answer materials; no submission or grading."""
    from routes import api_basic, api_tests  # noqa: PLC0415

    cfg = api_tests._load_tests_cfg()
    categories = cfg.get("categories") if isinstance(cfg, dict) else {}
    unit_category = categories.get("UNIT") if isinstance(categories, dict) else {}
    unit_tests = unit_category.get("tests") if isinstance(unit_category, dict) else []
    _assert_unit(isinstance(unit_tests, list) and unit_tests, "tests-config UNIT category must contain tests")

    api_tests_source = (ROOT / "routes/api_tests.py").read_text(encoding="utf-8")
    _assert_unit("def _grade_answers(" not in api_tests_source, "student submission grading helper must stay removed")
    _assert_unit('/api/submit-test' not in api_tests_source, "student submission route must stay removed")

    for test in unit_tests:
        _assert_unit(isinstance(test, dict), "UNIT test entry must be an object")
        test_id = str(test.get("id") or "").strip()
        source_id = str(test.get("sourceId") or test.get("source_id") or "").strip()
        _assert_unit(test_id, "UNIT test must have id")
        _assert_unit(source_id, f"UNIT test must have sourceId: {test_id}")
        answer_link_status = str(
            test.get("answerLinkStatus") or test.get("answer_link_status") or ""
        ).strip().casefold()
        _assert_unit(answer_link_status in {"", "missing"}, f"UNIT answerLinkStatus must be empty or missing: {test_id}")

        round_match = re.search(r"\d+", str(test.get("round") or "1"))
        round_no = int(round_match.group(0)) if round_match else 1
        assigned_item = {
            "categoryLabel": "단원평가",
            "curriculum": test.get("curriculum"),
            "difficulty": test.get("difficulty"),
            "round": f"{round_no}회차",
            "name": test.get("name"),
        }
        answer_url = api_basic._test_assignment_answer_url(assigned_item)
        if answer_link_status == "missing":
            _assert_unit(not answer_url, f"UNIT missing answer link must fail closed: {test_id}")
        else:
            _assert_unit(answer_url, f"UNIT assignment must resolve answerUrl: {test_id}")

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

    with verification_temporary_directory("verify-catalog-safety-") as tmpdir:
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
            normalized = " ".join(selector.split())
            is_keyframe_step = normalized in {"from", "to"} or bool(
                re.fullmatch(r"\d+(?:\.\d+)?%", normalized)
            )
            if normalized and not normalized.startswith("@") and not is_keyframe_step:
                yield line_no, normalized


def _admin_css_selector_is_scoped(selector: str) -> bool:
    stable_roots = (
        "body.admin",
        "html body.admin",
        ".admin-shell",
        ".admin-workspace",
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
    )
    return selector.startswith(stable_roots)


def run_admin_css_scope_source_checks() -> None:
    admin_css = (ROOT / "static/css/admin.css").read_text(encoding="utf-8")
    normalized_css = re.sub(r"\s+", " ", admin_css)
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
    _assert_unit(
        "@media (max-width: 640px) { body.admin .makeup-planner-head { align-items: stretch; flex-direction: column;"
        in normalized_css,
        "mobile makeup planner heading must stack instead of overflowing the viewport",
    )
    _assert_unit(
        "body.admin .makeup-planner input[type=\"search\"] { width: 100%; min-width: 0; height: 44px;"
        in normalized_css,
        "mobile makeup planner search must fit the viewport with a 44px target",
    )
    _assert_unit(
        "@media (max-width: 1024px) { body.admin :where( button, a.btn, input:not([type=\"checkbox\"]):not([type=\"radio\"]), select ) { min-height: 44px !important;"
        in normalized_css,
        "mobile and tablet admin controls must keep a 44px touch target",
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
    smoke_start = script_source.rfind("def run_smoke_checks(")
    main_start = script_source.rfind("def main()")
    smoke_block = script_source[smoke_start:main_start]

    task_numbers = [task for task, _label, _helpers, _snippets in REFACTOR_CONTRACT_EVIDENCE]
    _assert_unit(
        task_numbers == list(range(1, 15)),
        "refactor contract evidence registry must cover Tasks 1-14 exactly once and in order",
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


def run_verifier_execution_policy_source_checks() -> None:
    """Keep ignored local artifacts strict but opt-in for reproducible defaults."""
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    default_start = source.index("\ndef run_unit_checks() -> bool:\n") + 1
    default_end = source.index("\ndef run_selected_checks(", default_start)
    default_block = source[default_start:default_end]
    _assert_unit(
        "run_frontend_evidence_inventory_checks," not in default_block,
        "ignored frontend browser evidence must not be required by the default safety suite",
    )
    _assert_unit(
        'if args.only_frontend_evidence_inventory:' in source
        and "selected_checks.append(run_frontend_evidence_inventory_checks)" in source,
        "strict frontend evidence validation must remain available through its explicit selector",
    )
    _assert_unit(
        "run_unit_test_answer_material_readiness_checks," not in default_block
        and "run_unit_test_answer_material_contract_checks," in default_block,
        "the default suite must use a synthetic UNIT answer-material contract instead of ignored tests-config runtime data",
    )
    _assert_unit(
        'if args.only_unit_test_answer_material_readiness:' in source
        and "selected_checks.append(run_unit_test_answer_material_readiness_checks)" in source,
        "live UNIT answer-material readiness must remain available through its explicit selector",
    )
    _assert_unit(
        "ast.parse(source, filename=str(path), feature_version=(3, 11))" in source
        and "ok = run_python311_syntax_checks() and ok" in source,
        "the default verifier must enforce the Python 3.11 CI syntax boundary",
    )


def run_student_mobile_result_contract_checks() -> None:
    cmd = ["node", "--test", "scripts/student_mobile_app_checks/result-contract.test.mjs"]
    print("$ " + " ".join(cmd))
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found") from None
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "student mobile JavaScript result contract failed")


def run_student_mobile_pwa_flow_checks() -> None:
    """Exercise the real student-app install-guide boot and interaction contract."""
    cmd = ["node", "scripts/student_mobile_app_checks/pwa-flow.mjs"]
    print("$ " + " ".join(cmd))
    with tempfile.TemporaryDirectory(prefix="verify-student-install-guide-") as tmpdir:
        evidence = pathlib.Path(tmpdir) / "pwa-flow-check.json"
        env = os.environ.copy()
        env["STUDENT_APP_PWA_FLOW_EVIDENCE"] = str(evidence)
        try:
            proc = _run_captured(cmd, env=env)
        except FileNotFoundError:
            raise AssertionError("node not found") from None
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        _assert_unit(proc.returncode == 0, "student install-guide PWA flow failed")
        _assert_unit(evidence.is_file(), "student install-guide PWA flow did not write its temp receipt")
        receipt = json.loads(evidence.read_text(encoding="utf-8"))
        _assert_unit(receipt.get("suite") == "student-mobile-app-pwa-flow", "student install-guide receipt identity mismatch")
        _assert_unit(
            isinstance(receipt.get("checks"), int) and receipt["checks"] >= 16,
            "student install-guide receipt must contain the full current contract",
        )


def _execute_student_mobile_deployment_checker(
    checker: Callable[[], dict[str, object]],
    *,
    expected_name: str,
    minimum_assertions: int,
    runtime_observer: Callable[[], object] = runtime_metadata_fingerprints,
    allow_concurrent_runtime_changes: bool = False,
    required_runtime_isolation: str = "",
) -> int:
    """Validate one receipt and restore process globals even when its checker fails."""
    from scripts import backup_runtime_data

    original_environment = os.environ.copy()
    original_backup_root = backup_runtime_data.ROOT
    original_cwd = pathlib.Path.cwd()
    runtime_before = runtime_observer()
    result: dict[str, object] | None = None
    failure: BaseException | None = None
    failure_traceback = None
    observer_failure: BaseException | None = None
    environment_changed = False
    backup_root_changed = False
    cwd_changed = False
    runtime_changed = False
    runtime_allowed_changes: list[str] = []
    runtime_disallowed_changes: list[str] = []
    try:
        result = checker()
    except BaseException as exc:  # restore shared verifier state before propagating any failure
        failure = exc
        failure_traceback = exc.__traceback__
    finally:
        try:
            environment_changed = os.environ != original_environment
            backup_root_changed = backup_runtime_data.ROOT != original_backup_root
            cwd_changed = pathlib.Path.cwd() != original_cwd
            runtime_after = runtime_observer()
            if isinstance(runtime_before, dict) and isinstance(runtime_after, dict):
                runtime_change_paths = runtime_diff_keys(runtime_before, runtime_after)
                runtime_allowed_changes = [
                    path for path in runtime_change_paths if is_sqlite_transient_sidecar(path)
                ]
                runtime_disallowed_changes = [
                    path for path in runtime_change_paths if not is_sqlite_transient_sidecar(path)
                ]
                runtime_changed = bool(runtime_disallowed_changes)
            else:
                runtime_changed = runtime_after != runtime_before
        except BaseException as exc:
            observer_failure = exc
        finally:
            os.environ.clear()
            os.environ.update(original_environment)
            backup_runtime_data.ROOT = original_backup_root
            if pathlib.Path.cwd() != original_cwd:
                os.chdir(original_cwd)

    if observer_failure is not None:
        invariant_error = AssertionError(
            "student deployment runtime observer failed after shared verifier state was restored"
        )
        if failure is not None:
            raise invariant_error from failure
        raise invariant_error from observer_failure

    if runtime_allowed_changes:
        print(
            "student deployment runtime observer allowed concurrent SQLite sidecar churn: "
            + ", ".join(runtime_allowed_changes)
        )

    isolated_runtime_receipt = (
        allow_concurrent_runtime_changes
        and bool(required_runtime_isolation)
        and failure is None
        and isinstance(result, dict)
        and result.get("name") == expected_name
        and result.get("passed") is True
        and result.get("runtimeIsolation") == required_runtime_isolation
    )
    if runtime_changed and runtime_disallowed_changes and isolated_runtime_receipt:
        print(
            "student deployment checker observed concurrent live-runtime writes: "
            + ", ".join(runtime_disallowed_changes)
        )
        runtime_disallowed_changes = []
        runtime_changed = False

    if environment_changed or backup_root_changed or cwd_changed or runtime_changed:
        changed = []
        if environment_changed:
            changed.append("process environment")
        if backup_root_changed:
            changed.append("backup runtime root")
        if cwd_changed:
            changed.append("working directory")
        if runtime_changed:
            detail = ", ".join(runtime_disallowed_changes) or "unclassified observer state"
            changed.append(f"runtime metadata/content ({detail})")
        invariant_error = AssertionError(
            "student deployment checker changed shared verifier state; restored: " + ", ".join(changed)
        )
        if failure is not None:
            raise invariant_error from failure
        raise invariant_error
    if failure is not None:
        raise failure.with_traceback(failure_traceback)

    _assert_unit(isinstance(result, dict), "student deployment checker returned a non-object receipt")
    _assert_unit(result.get("name") == expected_name, "student deployment receipt identity mismatch")
    _assert_unit(result.get("passed") is True, "student deployment contract did not pass")
    assertions = result.get("assertions")
    _assert_unit(
        isinstance(assertions, int) and not isinstance(assertions, bool) and assertions >= minimum_assertions,
        "student deployment receipt must contain the full current contract",
    )
    return assertions


def run_student_mobile_deployment_guard_unit_checks() -> None:
    """Adversarially prove receipt validation and exception-path state restoration."""
    from scripts import backup_runtime_data

    original_environment = os.environ.copy()
    original_backup_root = backup_runtime_data.ROOT
    original_cwd = pathlib.Path.cwd()

    def stable_runtime_observer() -> dict:
        """Keep receipt/state unit cases independent from live server writes."""
        return {}

    _assert_unit(
        _execute_student_mobile_deployment_checker(
            lambda: {"name": "deployment-fixture", "assertions": 3, "passed": True},
            expected_name="deployment-fixture",
            minimum_assertions=3,
            runtime_observer=stable_runtime_observer,
        ) == 3,
        "student deployment guard rejected a valid receipt",
    )
    invalid_receipts = (
        {"name": "wrong", "assertions": 3, "passed": True},
        {"name": "deployment-fixture", "assertions": 0, "passed": True},
        {"name": "deployment-fixture", "assertions": True, "passed": True},
        {"name": "deployment-fixture", "assertions": 3, "passed": False},
    )
    for receipt in invalid_receipts:
        try:
            _execute_student_mobile_deployment_checker(
                lambda receipt=receipt: receipt,
                expected_name="deployment-fixture",
                minimum_assertions=3,
                runtime_observer=stable_runtime_observer,
            )
        except AssertionError:
            continue
        raise AssertionError(f"student deployment guard accepted invalid receipt: {receipt}")

    def dirty_failure() -> dict[str, object]:
        os.environ["ACADEMY_PHASE14_GUARD_FIXTURE"] = "mutated"
        backup_runtime_data.ROOT = ROOT / "phase14-invalid-runtime-root"
        raise RuntimeError("injected deployment checker failure")

    try:
        _execute_student_mobile_deployment_checker(
            dirty_failure,
            expected_name="deployment-fixture",
            minimum_assertions=3,
            runtime_observer=stable_runtime_observer,
        )
    except AssertionError as exc:
        _assert_unit("shared verifier state; restored" in str(exc), "deployment guard hid state restoration failure")
    else:
        raise AssertionError("deployment guard accepted checker state leakage")
    _assert_unit(os.environ == original_environment, "deployment guard did not restore the process environment")
    _assert_unit(backup_runtime_data.ROOT == original_backup_root, "deployment guard did not restore the backup root")

    observations = iter(({"runtime": 1}, {"runtime": 2}))
    try:
        _execute_student_mobile_deployment_checker(
            lambda: {"name": "deployment-fixture", "assertions": 3, "passed": True},
            expected_name="deployment-fixture",
            minimum_assertions=3,
            runtime_observer=lambda: next(observations),
        )
    except AssertionError as exc:
        _assert_unit("runtime metadata/content" in str(exc), "deployment guard hid runtime mutation")
    else:
        raise AssertionError("deployment guard accepted runtime mutation")

    sidecar_observations = iter((
        {"app.sqlite-wal": {"mtime_ns": 1, "size": 10, "sha256": "before"}},
        {"app.sqlite-wal": {"mtime_ns": 2, "size": 12, "sha256": "after"}},
    ))
    with contextlib.redirect_stdout(io.StringIO()):
        sidecar_result = _execute_student_mobile_deployment_checker(
            lambda: {"name": "deployment-fixture", "assertions": 3, "passed": True},
            expected_name="deployment-fixture",
            minimum_assertions=3,
            runtime_observer=lambda: next(sidecar_observations),
        )
    _assert_unit(sidecar_result == 3, "deployment guard must allow concurrent SQLite WAL/SHM churn")

    isolation = "temporary fixtures and dry-run subprocesses only"
    concurrent_observations = iter((
        {"progress.json": {"mtime_ns": 1, "size": 10, "sha256": "before"}},
        {"progress.json": {"mtime_ns": 2, "size": 12, "sha256": "after"}},
    ))
    with contextlib.redirect_stdout(io.StringIO()):
        concurrent_result = _execute_student_mobile_deployment_checker(
            lambda: {
                "name": "deployment-fixture",
                "assertions": 3,
                "passed": True,
                "runtimeIsolation": isolation,
            },
            expected_name="deployment-fixture",
            minimum_assertions=3,
            runtime_observer=lambda: next(concurrent_observations),
            allow_concurrent_runtime_changes=True,
            required_runtime_isolation=isolation,
        )
    _assert_unit(
        concurrent_result == 3,
        "isolated deployment guard must tolerate concurrent live-runtime writes",
    )

    unproven_observations = iter((
        {"watch.json": {"mtime_ns": 1, "size": 10, "sha256": "before"}},
        {"watch.json": {"mtime_ns": 2, "size": 12, "sha256": "after"}},
    ))
    try:
        _execute_student_mobile_deployment_checker(
            lambda: {"name": "deployment-fixture", "assertions": 3, "passed": True},
            expected_name="deployment-fixture",
            minimum_assertions=3,
            runtime_observer=lambda: next(unproven_observations),
            allow_concurrent_runtime_changes=True,
            required_runtime_isolation=isolation,
        )
    except AssertionError as exc:
        _assert_unit("watch.json" in str(exc), "deployment guard hid an unproven runtime change")
    else:
        raise AssertionError("deployment guard accepted concurrent runtime changes without isolation proof")

    observer_calls = [0]

    def failing_observer() -> object:
        observer_calls[0] += 1
        if observer_calls[0] == 2:
            raise PermissionError("injected runtime observation failure")
        return {"runtime": 1}

    def dirty_success() -> dict[str, object]:
        os.environ["ACADEMY_PHASE14_GUARD_FIXTURE"] = "mutated"
        backup_runtime_data.ROOT = ROOT / "phase14-invalid-runtime-root"
        os.chdir(ROOT.parent if original_cwd != ROOT.parent else ROOT)
        return {"name": "deployment-fixture", "assertions": 3, "passed": True}

    try:
        _execute_student_mobile_deployment_checker(
            dirty_success,
            expected_name="deployment-fixture",
            minimum_assertions=3,
            runtime_observer=failing_observer,
        )
    except AssertionError as exc:
        _assert_unit("runtime observer failed" in str(exc), "deployment guard hid observer failure")
    else:
        raise AssertionError("deployment guard accepted a failed post-run observer")
    _assert_unit(os.environ == original_environment, "observer failure left the process environment dirty")
    _assert_unit(backup_runtime_data.ROOT == original_backup_root, "observer failure left the backup root dirty")
    _assert_unit(pathlib.Path.cwd() == original_cwd, "observer failure left the working directory dirty")


def run_student_mobile_deployment_contract_checks() -> None:
    """Run isolated fixtures; runtime stores are fingerprinted read-only for mutation detection."""
    from scripts.student_mobile_app_checks import deployment

    full_windows_contract = os.name == "nt"
    checker = deployment.run_checks if full_windows_contract else deployment.run_portable_checks
    assertions = _execute_student_mobile_deployment_checker(
        checker,
        expected_name="deployment" if full_windows_contract else "deployment-portable",
        minimum_assertions=118 if full_windows_contract else 92,
        allow_concurrent_runtime_changes=_local_runtime_service_is_active(),
        required_runtime_isolation=deployment.RUNTIME_ISOLATION,
    )
    mode = "windows-full" if full_windows_contract else "portable-static"
    print(f"student mobile deployment contract ({mode}): {assertions} assertions passed; process state restored")


def run_student_mobile_python_result_contract_checks() -> None:
    from types import ModuleType

    from scripts import verify_student_mobile_app as dispatcher

    module_name = "scripts.student_mobile_app_checks._dispatcher_contract_fixture"
    module = ModuleType(module_name)
    original = dispatcher.CHECK_MODULES["config"]
    dispatcher.CHECK_MODULES["config"] = module_name
    sys.modules[module_name] = module
    try:
        invalid = (
            {"name": "wrong", "assertions": 1, "passed": True},
            {"name": "config", "assertions": 0, "passed": True},
            {"name": "config", "assertions": True, "passed": True},
            {"name": "config", "assertions": 1, "passed": False},
        )
        for receipt in invalid:
            module.run_checks = lambda receipt=receipt: receipt
            try:
                dispatcher._load_result("config")
            except dispatcher.StudentMobileAppCheckError:
                continue
            raise AssertionError(f"Python dispatcher accepted invalid receipt: {receipt}")
        module.run_checks = lambda: {"name": "config", "assertions": 1, "passed": True}
        accepted = dispatcher._load_result("config")
        _assert_unit(accepted["assertions"] == 1, "Python dispatcher rejected a valid bound receipt")
        sidecar_diff = dispatcher._snapshot_diff(
            {"app.sqlite-wal": {"mtime_ns": 1, "size": 10, "sha256": "before"}},
            {"app.sqlite-wal": {"mtime_ns": 2, "size": 12, "sha256": "after"}},
        )
        _assert_unit(
            dispatcher._disallowed_snapshot_diff(sidecar_diff) == {},
            "student mobile dispatcher must allow concurrent SQLite WAL/SHM churn",
        )
        main_db_diff = dispatcher._snapshot_diff(
            {"app.sqlite": {"mtime_ns": 1, "size": 10, "sha256": "before"}},
            {"app.sqlite": {"mtime_ns": 2, "size": 10, "sha256": "before"}},
        )
        _assert_unit(
            set(dispatcher._disallowed_snapshot_diff(main_db_diff)) == {"app.sqlite"},
            "student mobile dispatcher must still reject main SQLite database changes",
        )
        isolated_receipt = [{
            "name": "academy-gates",
            "assertions": 1,
            "passed": True,
            "runtimeIsolation": dispatcher.EXPECTED_RUNTIME_ISOLATION["academy-gates"],
        }]
        _assert_unit(
            dispatcher._isolated_results_allow_concurrent_runtime_changes(
                ("academy-gates",), isolated_receipt, service_active=True
            ),
            "student mobile dispatcher must tolerate live-service writes for a verified isolated receipt",
        )
        _assert_unit(
            not dispatcher._isolated_results_allow_concurrent_runtime_changes(
                ("academy-gates",), isolated_receipt, service_active=False
            ),
            "student mobile dispatcher must not waive runtime changes while the service is stopped",
        )
        tampered_receipt = [dict(isolated_receipt[0], runtimeIsolation="unverified")]
        _assert_unit(
            not dispatcher._isolated_results_allow_concurrent_runtime_changes(
                ("academy-gates",), tampered_receipt, service_active=True
            ),
            "student mobile dispatcher must require the exact per-check isolation contract",
        )
    finally:
        dispatcher.CHECK_MODULES["config"] = original
        sys.modules.pop(module_name, None)


def run_refactor_notes_contract_source_checks() -> None:
    refactor_pointer_md = (ROOT / "scripts/refactor_notes_logs_progress.md").read_text("utf-8")
    functions_md = (ROOT / "docs/PROJECT_FUNCTIONS_AND_LOGIC.md").read_text("utf-8")
    root_agents_md = (ROOT / "AGENTS.md").read_text("utf-8")
    scripts_agents_md = (ROOT / "scripts/AGENTS.md").read_text("utf-8")

    for snippet in [
        "../docs/history/REFACTOR_NOTES_LOGS_PROGRESS_LEGACY.md",
        "SERVER_RULES_INDEX.md#rule-log-001",
        "SERVER_RULES_INDEX.md#rule-progress-001",
    ]:
        _assert_unit(
            snippet in refactor_pointer_md,
            f"legacy refactor-note pointer must resolve through canonical documentation: {snippet}",
        )

    required_canonical_groups = [
        (
            "assigned test answer-link notes",
            functions_md,
            [
                "progress[date][sid].tests",
                "assignedTests[].answerUrl",
                "sourceFiles.solutionFileId",
                "static/js/test_answer_link_map.json",
            ],
        ),
        (
            "catalog writer safety notes",
            scripts_agents_md,
            ["--backup-confirmed", "--config", "--csv", "--output", "--issues"],
        ),
        (
            "opt-in log GET smoke safety notes",
            root_agents_md,
            [
                "--smoke --smoke-log-gets",
                "python scripts/backup_runtime_data.py",
                "`mtime_ns`, size, and SHA-256",
                "including an mtime-only change",
            ],
        ),
    ]
    for label, canonical_text, snippets in required_canonical_groups:
        missing = [snippet for snippet in snippets if snippet not in canonical_text]
        _assert_unit(
            not missing,
            f"canonical documentation must describe {label}; missing: {', '.join(missing)}",
        )


def run_admin_calendar_test_completion_source_checks() -> None:
    calendar_js = (ROOT / "static/js/admin/features/calendar.js").read_text("utf-8-sig")
    hover_tooltip_js = (ROOT / "static/js/admin/features/hoverTooltip.js").read_text("utf-8")
    today_render_js = (ROOT / "static/js/admin/features/today.render.js").read_text("utf-8")

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
        and "const subjectExamTimingKind = classifySubjectExamTiming(exam.math);" in hover_tooltip_js
        and "`${examSubject} ${subjectExamTimingKind === 'date' ? '시험일' : '시험 기간'}`" in hover_tooltip_js,
        "admin hover tooltip must label each row's subject and distinguish exam dates from ranges",
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

    _assert_unit(
        "await patchLogsBatch(targets.map(target => ({" in homework_block
        and "await patchLog(" not in homework_block
        and "await loadTodayAndRender({ force: true });" not in homework_block,
        "숙검하원 must use one batch log write and avoid force-refreshing unrelated data",
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
        "api.getOr('/api/absent', {})",
        "api.getOr('/api/school-calendar', {})",
    ]:
        _assert_unit(optional_call in state_js, f"optional bootstrap fallback must remain: {optional_call}")
    bootstrap_start = state_js.index("export async function bootstrap()")
    bootstrap_block = state_js[bootstrap_start:]
    for deferred_url in [
        "/api/materials",
        "/api/mat-assign",
        "/api/extra-attend",
        "/api/tests-config",
    ]:
        _assert_unit(
            deferred_url not in bootstrap_block,
            f"noncritical endpoint must not block the first admin render: {deferred_url}",
        )
    for compatibility_default in [
        "materials: {}",
        "assigns: {}",
        "extra: {}",
        "testsConfig: { categories: {} }",
    ]:
        _assert_unit(
            compatibility_default in state_js,
            f"deferred bootstrap state must retain its compatibility default: {compatibility_default}",
        )
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
        "await patchLogsBatch(targets.map(target => ({",
        "date: target.dateKey,",
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

    load_all_start = state_js.index("export async function loadAll(")
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
        "ensureProgressForSid" not in table_js,
        "all-students table must not retain the removed mini progress popup loader",
    )
    _assert_unit(
        "window.openStudentPopupsForRow(row" in table_js
        and "accessMode: 'all-students-readonly'" in table_js,
        "all-students row action must open the shared unified popup set with read-only counseling access",
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
        proc = _run_captured(cmd)
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
    required_ui_contracts = [
        ('id="testDifficultyOverride"', "test modal must render the 레벨 설정 button"),
        ('id="testLevelSettingOptions"', "test modal must render the Lv.3-Lv.6 level picker"),
        ("const difficulties = allDifficulties;", "normal difficulty selector must keep every category level visible"),
        ("field: STUDENT_TEST_LEVEL_DEFAULTS_FIELD", "student level setting must patch only the student default field"),
        ("sendJson('/api/update'", "student level setting must use the single-field student API"),
        ("const TEST_KEYBOARD_STATUS_ORDER = ['', 'interrupted', 'assigned', 'done', 'skip'];", "keyboard status cycle must remain white-orange-green-blue-red"),
        ("if (e.ctrlKey || e.metaKey) {", "Ctrl/Cmd-click multi-selection must remain wired"),
        ("function activeStudentCurriculumSubject()", "test modal must derive the opening subject from the active student curriculum"),
        ("function restorePreferredInitialTestView(requiredSubject = activeStudentCurriculumSubject())", "test modal must bind recent-view restoration to the curriculum subject"),
        ("const storedView = readRecentTestView(editingSid, curriculumSubject);", "stored recent view must be filtered by the curriculum subject"),
        ("const recentAssignment = latestAssignmentTestFromHistory(curriculumSubject);", "recent assignment priority must be filtered by the curriculum subject"),
        ("function restorePreferredCategoryTestView(categoryKey, requiredSubject = activeSubject)", "category tabs must restore category-scoped recent assignment details"),
        ("if (!restorePreferredCategoryTestView(activeCategory, activeSubject))", "category tab changes must prefer category-scoped assignment history before defaults"),
        ("function invalidateStudentWorkFetchCache(url)", "test assignment saves must invalidate shared student-popup hydration cache entries"),
        ("if (curriculumSubject && subject !== curriculumSubject) return null;", "cross-subject recent views must be rejected"),
        ("TEST_RECENT_VIEW_STORAGE_PREFIX", "recent popup view must remain student-scoped in browser storage"),
        ("const TEST_ASSIGN_CHANGE_ORDER_KEY = '__testAssignmentChangeOrder';", "test modal must read authoritative per-test change ordering"),
        ("const TEST_ASSIGN_TOUCHED_KEYS_KEY = '__testAssignmentTouchedKeys';", "test modal must identify explicit reassignments in full-map patches"),
        ("activeCatalog = collectCatalog(state.testsConfig).filter(test =>", "test modal catalog must be limited to the current curriculum subject"),
        ("subjectSel.disabled = true;", "test modal subject selector must remain locked to the current curriculum"),
        ("function centerTestRowInScroller(row, scroller)", "test modal must define exact-row scroll centering"),
    ]
    for snippet, message in required_ui_contracts:
        _assert_unit(snippet in test_modal_js, message)

    _assert_unit(
        "function showTestSaveSuccess()" in test_modal_js
        and "window.showStudentPopupSaveResult('저장 완료')" in test_modal_js
        and save_block.count("showTestSaveSuccess();") == 2
        and "변경된 테스트 배정이 없습니다" not in save_block
        and "toast('테스트 배정 저장됨')" not in save_block,
        "test saves with or without assignment changes must reuse the video popup's save-complete graphic",
    )
    _assert_unit(
        save_block.index("applyTestProgressPatchResult(editingDate, editingSid, progressRes)")
        < save_block.rindex("showTestSaveSuccess();")
        < save_block.index("await patchLogAssignment(items, appendToNotes, newlyAddedItems, latestLogEntry)"),
        "changed test saves must show completion after authoritative progress persistence without waiting for compatibility-log I/O",
    )

    restore_start = test_modal_js.index("function restorePreferredInitialTestView")
    restore_end = test_modal_js.index("function restorePreferredCategoryTestView", restore_start)
    restore_block = test_modal_js[restore_start:restore_end]
    _assert_unit(
        restore_block.index("const recentAssignment = latestAssignmentTestFromHistory(curriculumSubject);") <
        restore_block.index("const storedView = readRecentTestView(editingSid, curriculumSubject);"),
        "popup open must prefer same-subject assignment history over the browser's recent view",
    )

    open_start = test_modal_js.index("async function openModalForRow")
    open_end = test_modal_js.index("function selectedAssignmentObjects", open_start)
    open_block = test_modal_js[open_start:open_end]
    _assert_unit(
        open_block.index("const curriculumSubject = activeStudentCurriculumSubject();") <
        open_block.index("activeSubject = curriculumSubject || normalizeSubject(activeStudent.curriculum);") <
        open_block.index("syncSelectedFromProgress();") <
        open_block.index("restorePreferredInitialTestView(curriculumSubject)") <
        open_block.index("activeCategory = chooseInitialCategory();"),
        "popup open must lock the curriculum subject before same-subject recent view/history and defaults",
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
  .replace("import { getAdminDate } from '../core/adminDate.js';", "const getAdminDate = () => '2026-06-05';")
  .replace("import { createUnitTestDisplayNameResolver } from '../../shared/testCatalogDisplay.js';", "const createUnitTestDisplayNameResolver = () => (test) => String(test?.name || '');");
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
  touchedTestKeys = new Set(input.touchedTestKeys || []);
  testChangeOrderByKey = input.testChangeOrderByKey || {};
  pendingCenteredTestKey = '';
  testSelectionTouched = input.testSelectionTouched !== false;
}
export {
  patchLogAssignment as __patchLogAssignment,
  saveModal as __saveModal,
  nextStatusOf as __nextStatusOf,
  nextExcludedStatusOf as __nextExcludedStatusOf,
  restorePreferredInitialTestView as __restorePreferredInitialTestView,
  restorePreferredCategoryTestView as __restorePreferredCategoryTestView,
  latestAssignmentTestFromHistory as __latestAssignmentTestFromHistory,
  centerTestRowInScroller as __centerTestRowInScroller,
  currentTestView as __currentTestView,
  studentTestLevelDefault as __studentTestLevelDefault,
};
	`;
const moduleSource = `${source}\n${harness}\n//# sourceURL=logModalCarriedReapplyHarness.js`;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(moduleSource).toString('base64')}`;

globalThis.window = globalThis;
globalThis.__toasts = [];
globalThis.__saveResults = [];
globalThis.showStudentPopupSaveResult = (message) => globalThis.__saveResults.push(String(message));
globalThis.__elements = { testAppendNotes: { checked: true } };
globalThis.__state = {
  progress: {},
  logs: {},
  testsConfig: {},
  schoolCal: {},
};
globalThis.__studentWorkFetchCache = new Map();
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
globalThis.document = { dispatchEvent: () => {} };
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};

	const mod = await import(moduleUrl);
	mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeCatalog: [],
  initialTestMap: {},
  selectedStatuses: [],
  testSelectionTouched: false,
});
await mod.__saveModal({ refresh: false });
ok(globalThis.__saveResults.join('|') === '저장 완료', 'unchanged test save still shows the shared save-complete graphic');
	globalThis.__saveResults = [];
	ok(mod.__nextStatusOf('') === 'assigned', 'left-click none becomes 배정/assigned');
	ok(mod.__nextStatusOf('assigned') === 'interrupted', 'left-click 배정/assigned becomes 배부/interrupted');
	ok(mod.__nextStatusOf('interrupted') === 'done', 'left-click 배부/interrupted becomes 완료/done');
	ok(mod.__nextStatusOf('done') === '', 'left-click 완료/done becomes none');
	ok(mod.__nextStatusOf('skip') === 'assigned', 'left-click 제외/skip returns to the normal 배정 cycle');
	ok(mod.__nextExcludedStatusOf('') === 'skip', 'right-click none becomes 제외/skip');
	ok(mod.__nextExcludedStatusOf('skip') === '', 'right-click 제외/skip becomes none');
	ok(mod.__nextExcludedStatusOf('assigned') === 'skip', 'right-click assigned enters 제외/skip');
	const scrollingHost = {
  scrollHeight: 1000,
  clientHeight: 400,
  scrollTop: 100,
  getBoundingClientRect: () => ({ top: 50, height: 400 }),
};
const centeredRow = { getBoundingClientRect: () => ({ top: 500, height: 40 }) };
ok(mod.__centerTestRowInScroller(centeredRow, scrollingHost) === true, 'overflowing test list centers the requested row');
ok(scrollingHost.scrollTop === 370, 'row center is aligned to the scroll viewport center');
const shortHost = {
  scrollHeight: 300,
  clientHeight: 400,
  scrollTop: 27,
  getBoundingClientRect: () => ({ top: 0, height: 400 }),
};
ok(mod.__centerTestRowInScroller(centeredRow, shortHost) === false, 'non-scrolling test list skips centering');
ok(shortHost.scrollTop === 27, 'non-scrolling list keeps its existing position');
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
const storedViewLabel = '단원평가 / 미적분2 / Lv.5 / 3회 / 저장 보기';
const curriculumAssignmentLabel = '단원평가 / 미적분2 / Lv.4 / 2회 / 최근 배정';
const staleOtherSubjectLabel = '단원평가 / 대수 / Lv.6 / 4회 / 다른 과목 최근 배정';
const storedViewTest = {
  id: 'stored-view',
  name: '저장 보기',
  categoryKey: 'UNIT',
  curriculum: '미적분2',
  difficulty: 'Lv.5',
  round: '3',
  _key: storedViewLabel,
};
const curriculumAssignmentTest = {
  id: 'curriculum-assignment',
  name: '최근 배정',
  categoryKey: 'UNIT',
  curriculum: '미적분2',
  difficulty: 'Lv.4',
  round: '2',
  _key: curriculumAssignmentLabel,
};
const staleOtherSubjectTest = {
  id: 'other-subject-assignment',
  name: '다른 과목 최근 배정',
  categoryKey: 'UNIT',
  curriculum: '대수',
  difficulty: 'Lv.6',
  round: '4',
  _key: staleOtherSubjectLabel,
};
const curriculumStudent = {
  id: 's1',
  name: '학생',
  curriculum: '미적분2',
  level: '중',
  testLevelDefaults: { UNIT: { 미적분2: 'Lv.5' } },
};
const recentViewStorageKey = 'admin.testAssignment.recentView.v1:s1';
globalThis.localStorage.setItem(recentViewStorageKey, JSON.stringify({
  categoryKey: 'UNIT',
  subject: '미적분2',
  difficulty: 'Lv.5',
  round: '3',
}));
mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeStudent: curriculumStudent,
  activeSubject: '미적분2',
  activeCatalog: [storedViewTest, curriculumAssignmentTest, staleOtherSubjectTest],
  initialTestMap: {
    [storedViewLabel]: 'done',
    [curriculumAssignmentLabel]: 'interrupted',
    [staleOtherSubjectLabel]: 'assigned',
  },
  selectedStatuses: [
    [storedViewLabel, 'done'],
    [curriculumAssignmentLabel, 'interrupted'],
    [staleOtherSubjectLabel, 'assigned'],
  ],
  testChangeOrderByKey: {
    [storedViewLabel]: 10,
    [curriculumAssignmentLabel]: 20,
    [staleOtherSubjectLabel]: 30,
  },
});
ok(mod.__studentTestLevelDefault('UNIT', '미적분2') === 'Lv.5', 'student UNIT subject default overrides management rules');
ok(mod.__restorePreferredInitialTestView() === 'assignment', 'same-curriculum assignment history has first priority over the stored view');
let restoredView = mod.__currentTestView();
ok(restoredView.subject === '미적분2' && restoredView.difficulty === 'Lv.4' && restoredView.round === '2', 'assignment history restores level and round without changing the curriculum subject');

const unitRecentLabel = '단원평가 / 미적분2 / Lv.5 / 1회 / 단원 최근 배정';
const schoolRecentLabel = '학군지 기출 / 미적분2 / 중상 / 중간고사 / 1회 / 학군지 최근 배정';
const unitDefaultLabel = '단원평가 / 미적분2 / Lv.6 / 1회 / 기존 기본 보기';
const unitRecentTest = {
  id: 'unit-recent',
  name: '단원 최근 배정',
  categoryKey: 'UNIT',
  curriculum: '미적분2',
  difficulty: 'Lv.5',
  round: '1',
  _key: unitRecentLabel,
};
const schoolRecentTest = {
  id: 'school-recent',
  name: '학군지 최근 배정',
  categoryKey: 'SCHOOL_PAST',
  curriculum: '미적분2',
  difficulty: '중상',
  term: '중간고사',
  round: '1',
  _key: schoolRecentLabel,
};
const unitDefaultTest = {
  id: 'unit-default',
  name: '기존 기본 보기',
  categoryKey: 'UNIT',
  curriculum: '미적분2',
  difficulty: 'Lv.6',
  round: '1',
  _key: unitDefaultLabel,
};
globalThis.localStorage.setItem(recentViewStorageKey, JSON.stringify({
  categoryKey: 'UNIT',
  subject: '미적분2',
  difficulty: 'Lv.6',
  round: '1',
}));
mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeStudent: curriculumStudent,
  activeSubject: '미적분2',
  activeCatalog: [unitDefaultTest, unitRecentTest, schoolRecentTest],
  initialTestMap: {
    [unitRecentLabel]: 'assigned',
    [schoolRecentLabel]: 'assigned',
  },
  selectedStatuses: [
    [unitRecentLabel, 'assigned'],
    [schoolRecentLabel, 'assigned'],
  ],
  testChangeOrderByKey: {
    [unitRecentLabel]: 10,
    [schoolRecentLabel]: 20,
  },
});
ok(mod.__restorePreferredInitialTestView() === 'assignment', 'the most recently assigned category opens before an older stored category view');
restoredView = mod.__currentTestView();
ok(restoredView.categoryKey === 'SCHOOL_PAST' && restoredView.difficulty === '중상' && restoredView.term === '중간고사', 'school-past opens first when it was assigned after UNIT');
ok(mod.__restorePreferredCategoryTestView('UNIT', '미적분2') === 'assignment', 'UNIT tab restores its own latest assignment');
restoredView = mod.__currentTestView();
ok(restoredView.categoryKey === 'UNIT' && restoredView.difficulty === 'Lv.5' && restoredView.round === '1', 'UNIT tab restores Lv.5 1회차 instead of the Lv.6 default');

mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeStudent: curriculumStudent,
  activeSubject: '미적분2',
  activeCatalog: [unitRecentTest, schoolRecentTest],
  initialTestMap: {
    [unitRecentLabel]: 'assigned',
    [schoolRecentLabel]: 'assigned',
  },
  selectedStatuses: [
    [unitRecentLabel, 'assigned'],
    [schoolRecentLabel, 'assigned'],
  ],
  testChangeOrderByKey: {
    [unitRecentLabel]: 30,
    [schoolRecentLabel]: 30,
  },
});
ok(mod.__restorePreferredInitialTestView() === 'assignment', 'same-save test assignments still restore assignment history');
restoredView = mod.__currentTestView();
ok(restoredView.categoryKey === 'UNIT', 'UNIT opens first when multiple categories share the same save order');

globalThis.localStorage.setItem(recentViewStorageKey, JSON.stringify({
  categoryKey: 'UNIT',
  subject: '대수',
  difficulty: 'Lv.6',
  round: '4',
}));
mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeStudent: curriculumStudent,
  activeSubject: '미적분2',
  activeCatalog: [storedViewTest, curriculumAssignmentTest, staleOtherSubjectTest],
  initialTestMap: {
    [curriculumAssignmentLabel]: 'interrupted',
    [staleOtherSubjectLabel]: 'assigned',
  },
  selectedStatuses: [
    [curriculumAssignmentLabel, 'interrupted'],
    [staleOtherSubjectLabel, 'assigned'],
  ],
  testChangeOrderByKey: {
    [curriculumAssignmentLabel]: 20,
    [staleOtherSubjectLabel]: 30,
  },
});
ok(mod.__restorePreferredInitialTestView() === 'assignment', 'cross-subject stored view falls back to same-curriculum assignment history');
restoredView = mod.__currentTestView();
ok(restoredView.subject === '미적분2' && restoredView.difficulty === 'Lv.4' && restoredView.round === '2', 'newer other-subject history cannot replace the curriculum subject');

mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeStudent: curriculumStudent,
  activeSubject: '미적분2',
  activeCatalog: [staleOtherSubjectTest],
  initialTestMap: { [staleOtherSubjectLabel]: 'assigned' },
  selectedStatuses: [[staleOtherSubjectLabel, 'assigned']],
});
ok(mod.__restorePreferredInitialTestView() === '', 'cross-subject recent state is ignored when no same-subject history exists');
restoredView = mod.__currentTestView();
ok(restoredView.subject === '미적분2', 'popup keeps the student curriculum subject when all recent state belongs to another subject');
globalThis.localStorage.removeItem(recentViewStorageKey);

mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeCatalog: [existingTest, newTest],
  initialTestMap: {},
  selectedStatuses: [[newLabel, 'assigned']],
  touchedTestKeys: [newLabel],
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
  if (String(url) === '/api/progress/patch') return response({ progress: {
    tests: { [existingLabel]: 'interrupted', [newLabel]: 'interrupted' },
    __testAssignmentChangeOrder: { [existingLabel]: 1, [newLabel]: 2 },
  } });
  if (String(url) === '/api/logs/patch') return response({ entry: { saved: true } });
  return response({});
};
mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeCatalog: [existingTest, newTest],
  initialTestMap: { [existingLabel]: 'interrupted' },
  selectedStatuses: [[existingLabel, 'interrupted'], [newLabel, 'interrupted']],
  touchedTestKeys: [newLabel],
});
globalThis.__studentWorkFetchCache.set('/api/progress?sid=s1', { ts: Date.now(), promise: Promise.resolve({ stale: true }) });
globalThis.__studentWorkFetchCache.set('/api/logs?sid=s1', { ts: Date.now(), promise: Promise.resolve({ stale: true }) });
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
ok(
  progressPatch.body?.progress?.__testAssignmentTouchedKeys?.length === 1
  && progressPatch.body.progress.__testAssignmentTouchedKeys[0] === newLabel,
  'progress patch marks only the explicitly assigned/reassigned test as newest',
);
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
ok(!globalThis.__studentWorkFetchCache.has('/api/progress?sid=s1'), 'successful progress save invalidates the shared progress cache');
ok(!globalThis.__studentWorkFetchCache.has('/api/logs?sid=s1'), 'successful log save invalidates the shared log cache');

const feedbackOrder = [];
globalThis.__saveResults = [];
globalThis.showStudentPopupSaveResult = (message) => {
  globalThis.__saveResults.push(String(message));
  feedbackOrder.push('feedback');
};
globalThis.fetch = async (url, init = {}) => {
  const value = String(url);
  feedbackOrder.push(value);
  if (value.startsWith('/api/logs/entry?')) return response({ ok: true, entry: latestEntry });
  if (value === '/api/progress/patch') return response({ progress: { tests: { [newLabel]: 'assigned' } } });
  if (value === '/api/logs/patch') return response({ entry: { saved: true } });
  return response({});
};
mod.__setHarnessState({
  editingDate: '2026-06-05',
  editingSid: 's1',
  activeCatalog: [newTest],
  initialTestMap: {},
  selectedStatuses: [[newLabel, 'assigned']],
  touchedTestKeys: [newLabel],
});
await mod.__saveModal({ refresh: false });
const feedbackIndex = feedbackOrder.indexOf('feedback');
ok(globalThis.__saveResults.join('|') === '저장 완료', 'changed test save shows the shared save-complete graphic');
ok(
  feedbackOrder.indexOf('/api/progress/patch') < feedbackIndex
  && feedbackIndex < feedbackOrder.indexOf('/api/logs/patch'),
  'save-complete graphic appears after authoritative progress persistence and before compatibility-log I/O',
);
"""
    cmd = ["node", "--input-type=module", "-e", driver]
    print("$ node --input-type=module -e <admin-test-modal-assignment-driver>")
    try:
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin test modal assignment behavior driver failed")


def run_admin_video_modal_preflight_source_checks() -> None:
    video_modal_js = (ROOT / "static/js/admin/features/videoModal.js").read_text("utf-8")
    hydration_start = video_modal_js.index("async function hydrateProgressMaybe")
    hydration_end = video_modal_js.index("async function hydrateForVideoModal", hydration_start)
    hydration_block = video_modal_js[hydration_start:hydration_end]
    patch_start = video_modal_js.index("async function patchExtraVideoLogAssignment")
    patch_end = video_modal_js.index("function buildVideoAssignmentHtml", patch_start)
    patch_block = video_modal_js[patch_start:patch_end]
    save_start = video_modal_js.index("async function saveVideoAssignmentForCurrent")
    save_end = video_modal_js.index("window.saveVideoAssignmentPopup", save_start)
    save_block = video_modal_js[save_start:save_end]
    updates_patch_start = video_modal_js.index("async function patchVideoAssignmentEntry")
    updates_patch_end = video_modal_js.index("function updateVideoRowPresentation", updates_patch_start)
    updates_patch_block = video_modal_js[updates_patch_start:updates_patch_end]

    _assert_unit(
        "window.showStudentPopupSaveResult = showSavePopup;" in video_modal_js
        and "window.hideStudentPopupSaveResult = hideSavePopup;" in video_modal_js,
        "video modal must expose its save-result graphic for the other student popups",
    )

    _assert_unit(
        "async function fetchLatestExtraVideoLogEntry" in video_modal_js,
        "video assignment must have a strict latest log entry helper",
    )
    _assert_unit(
        "function isHighDifficultyVideo" in video_modal_js
        and "startsWith('[고] ')" in video_modal_js
        and "function highDifficultyVideosForStudent" in video_modal_js
        and "videoCurriculum(video).toLowerCase() === curriculumKey" in video_modal_js
        and "videoSubCurriculum(video).toLowerCase() === 'apex'" in video_modal_js
        and 'id="excludeHighDifficultyVideos"' in video_modal_js
        and "data-high-difficulty=" in video_modal_js
        and "isHighDifficultyVideo(v) ? '1' : '0'" in video_modal_js,
        "video popup must identify exact [고] title-prefix videos in the student's subject APEX catalog and expose the bulk exclude control",
    )
    _assert_unit(
        "function toggleHighDifficultyVideosForStudent" in video_modal_js
        and "targets.every(({ stateValue }) => stateValue === 'skip')" in video_modal_js
        and "? 'none'" in video_modal_js
        and ": 'skip';" in video_modal_js
        and "applyVideoRowState(row, nextState);" in video_modal_js
        and "else setActiveVideoProgressState(mid, nextState);" in video_modal_js
        and "기본(흰색) 상태" in video_modal_js
        and "저장 버튼을 눌러 적용하세요" in video_modal_js,
        "high-difficulty bulk action must toggle visible and hidden APEX matches between excluded and white while keeping save explicit",
    )
    _assert_unit(
        "new URLSearchParams({ sid: sidKey })" in hydration_block
        and "new URLSearchParams({ date: dateKey, sid: sidKey })" not in hydration_block
        and "delete day[sidKey];" in hydration_block
        and "state.progress[progressDate][sidKey] = entry;" in hydration_block
        and "hydrateProgressMaybe(today, sid)" in video_modal_js,
        "video popup open must refresh the selected student's full progress history without replacing other students",
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
        save_block.index("patchVideoAssignmentEntry("),
        "latest log preflight must happen before /api/updates/patch",
    )
    _assert_unit(
        "await patchExtraVideoLogAssignment(today, sid, selected, latestLogEntry);" in save_block,
        "extra video log patch must receive the same latest entry used for preflight",
    )
    for snippet in [
        "patchVideoAssignmentEntry(",
        "buildVideoAssignmentPatchBody(today, sid, selected, source)",
        "fetch('/api/updates?readOnly=1', { cache: 'no-store' })",
        "body.base = { notes: prevNotes.trim() };",
    ]:
        _assert_unit(snippet in save_block or snippet in patch_block, f"video assignment source shape must remain: {snippet}")
    _assert_unit(
        "fetch('/api/updates/patch'" in updates_patch_block
        and "classifySaveConflict(data, '영상 배정')" in updates_patch_block
        and "conflict.retryable && attempt < delays.length" in updates_patch_block,
        "video assignment transport must retry only classified transient lock conflicts",
    )
    for snippet in [
        "function latestAutoAssignStatusForSid",
        "function applyWatchStatusForAutoAssign",
        "function blockedMidsForAutoAssign",
        "function resolveVideoAssignmentSaveSource",
        "options.forceEmpty === true",
        "function applyVideoAssignmentState",
        "function buildVideoAssignmentPatchBody",
        "return { date: day, sid, entry: { videos: selected, source } };",
        "return { date: day, sid, remove: true };",
        "activeAssignmentManual = source === 'manual';",
    ]:
        _assert_unit(snippet in video_modal_js, f"video assignment policy helper must remain: {snippet}")


def run_admin_student_popup_scroll_source_checks() -> None:
    video_modal_js = (ROOT / "static/js/admin/features/videoModal.js").read_text("utf-8")
    skip_style_start = video_modal_js.index('#vidModal .vid-row[data-state="skip"]')
    assigned_style_start = video_modal_js.index('#vidModal .vid-row[data-state="assigned"]')
    done_style_start = video_modal_js.index('#vidModal .vid-row[data-state="done"]', assigned_style_start)
    interrupted_style_start = video_modal_js.index('#vidModal .vid-row[data-state="interrupted"]', done_style_start)
    scroll_target_style_start = video_modal_js.index('#vidModal .vid-row.is-scroll-target', interrupted_style_start)
    assigned_style = video_modal_js[assigned_style_start:done_style_start]
    skip_style = video_modal_js[skip_style_start:assigned_style_start]
    done_style = video_modal_js[done_style_start:interrupted_style_start]
    interrupted_style = video_modal_js[interrupted_style_start:scroll_target_style_start]
    assigned_scroll_start = video_modal_js.index("function scrollVideoPopupToFirstAssigned()")
    assigned_scroll_end = video_modal_js.index("function ensureModal()", assigned_scroll_start)
    assigned_scroll_block = video_modal_js[assigned_scroll_start:assigned_scroll_end]

    _assert_unit(
        "let studentPopupScrollPosition = null;" in video_modal_js,
        "student popup must keep a scroll position while the root scroll lock is active",
    )
    _assert_unit(
        "x: window.scrollX || 0" in video_modal_js
        and "y: window.scrollY || 0" in video_modal_js,
        "student popup scroll lock must capture both document scroll axes",
    )
    _assert_unit(
        "const scrollPosition = studentPopupScrollPosition;" in video_modal_js
        and "studentPopupScrollPosition = null;" in video_modal_js
        and "window.scrollTo(scrollPosition.x, scrollPosition.y);" in video_modal_js,
        "student popup close must restore and clear the captured document scroll position",
    )
    _assert_unit(
        "box-shadow:inset 3px 0 0 #10b981;" in assigned_style
        and "box-shadow:inset" not in done_style
        and "box-shadow:inset" not in interrupted_style,
        "only the green assigned video row may keep the thick left status accent",
    )
    _assert_unit(
        "border-color:#fb7185;" in skip_style
        and "background:#fff8f9;" in skip_style
        and "color:#be123c;" in skip_style
        and "border-color:#60a5fa;" in done_style
        and "background:#f7faff;" in done_style
        and "color:#1d4ed8;" in done_style
        and "border-color:#fb923c;" in interrupted_style
        and "background:#fffaf5;" in interrupted_style
        and "color:#c2410c;" in interrupted_style
        and "border-color:#34d399;" in assigned_style
        and "background:#ecfdf5;" in assigned_style,
        "non-green video states must restore saturated hue cues on high-lightness surfaces while assigned green keeps the strongest accent",
    )

    _assert_unit(
        "function nextExcludedVideoState(stateValue)" in video_modal_js
        and ": 'none';\n}\n\nfunction nextExcludedVideoState" in video_modal_js
        and "if (e.button !== 0 && e.button !== 2) return;" in video_modal_js
        and "dragTargetState = dragButton === 2" in video_modal_js
        and "? nextExcludedVideoState(startState)" in video_modal_js
        and "applyVideoDragRange(row);" in video_modal_js
        and "if (dragActive && dragButton === 2) suppressContextOnce = true;" in video_modal_js
        and "applyVideoRowState(row, nextExcludedVideoState(row.dataset.state || 'none'));" in video_modal_js,
        "video popup right-click drag must toggle a contiguous range between excluded and none without a duplicate context action",
    )
    _assert_unit(
        "const VIDEO_KEYBOARD_STATUS_ORDER = ['none', 'interrupted', 'assigned', 'done', 'skip'];" in video_modal_js
        and "function nextKeyboardVideoState(stateValue, direction = 1)" in video_modal_js
        and "function applyKeyboardVideoStatusToSelection(direction)" in video_modal_js
        and "if (e.ctrlKey || e.metaKey) return;" in video_modal_js
        and "if (e.ctrlKey || e.metaKey) {" in video_modal_js
        and "toggleVideoMultiSelection(row);" in video_modal_js
        and "if (e.shiftKey) addVideoMultiSelectionRange(row);" in video_modal_js
        and "function videoMultiSelectionRangeMids(rows, anchorMid, targetMid)" in video_modal_js
        and "activeVideoMultiSelectionAnchorMid = mid;" in video_modal_js
        and "activeVideoMultiSelectionAnchorMid = '';" in video_modal_js
        and ": nextVideoRowState(startState);" in video_modal_js
        and "data-selection=\"${multiSelected ? 'selected' : 'none'}\"" in video_modal_js
        and "applyKeyboardVideoStatusToSelection(e.key === 'ArrowRight' ? 1 : -1)" in video_modal_js,
        "video popup must support Ctrl/Cmd multi-selection, Ctrl/Cmd+Shift range selection, keyboard status changes, and orange/blue drag transitions",
    )

    _assert_unit(
        "function scrollVideoPopupToFirstAssigned()" in video_modal_js
        and "#chkZone .vid-row[data-state=" in assigned_scroll_block
        and "assigned" in assigned_scroll_block
        and "requestAnimationFrame(scrollVideoPopupToFirstAssigned);" in video_modal_js,
        "video popup open must scroll to the first green assigned row",
    )
    _assert_unit(
        "if (active === 'video') requestAnimationFrame(scrollVideoPopupToFirstAssigned);" in video_modal_js,
        "mobile video tab activation must re-center the first green assigned row after the hidden layout becomes visible",
    )


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
  .replace("import { classifySaveConflict } from '../core/saveConflict.js';", "const classifySaveConflict = (data, label) => ({ retryable: data?.retryable === true, message: data?.error || `${label} 저장 충돌` });")
  .replace("import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from '../../shared/search.js';", "const applySearchPlaceholder = () => {}; const matchesSearchKey = () => true; const searchKeyForText = (value) => String(value || '').toLowerCase();")
  .replace("import { isSelfStudyScheduledForDate } from '../../shared/selfStudy.js';", "const isSelfStudyScheduledForDate = () => false;");
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
  const updatesReload = calls.find((call) => call.url.startsWith('/api/updates') && call.method === 'GET');
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
        proc = _run_captured(cmd)
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
  for (const id of ['vidModal', 'mTitle', 'chkZone', 'mSave', 'vidSavePopup', 'autoAssignCountToggle', 'autoAssignCountLabel', 'vidSelectionMeta']) {
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
const makeVideoSelectionRow = (mid) => {
  const classes = new Set();
  return {
    dataset: { mid: String(mid), selection: 'none' },
    attributes: {},
    classList: {
      toggle(name, force) {
        if (force) classes.add(name);
        else classes.delete(name);
        return !!force;
      },
      contains: (name) => classes.has(name),
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
    closest(selector) {
      return selector === '.vid-row' ? this : null;
    },
  };
};
globalThis.__makeVideoSelectionRow = makeVideoSelectionRow;

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
globalThis.__videoRows = [];
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
  documentElement: { style: { setProperty: () => {} }, classList: makeClassList(), dataset: {} },
  head: {
    appendChild(el) {
      if (el?.id) globalThis.__elements[el.id] = el;
    },
  },
  body: {
    classList: makeClassList(),
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
    if (selector === '#chkZone .vid-row[data-mid]') return globalThis.__videoRows;
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
  .replace("import { classifySaveConflict } from '../core/saveConflict.js';", "const classifySaveConflict = (data, label) => ({ retryable: data?.retryable === true, message: data?.error || `${label} 저장 충돌` });")
  .replace("import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from '../../shared/search.js';", "const applySearchPlaceholder = () => {}; const matchesSearchKey = () => true; const searchKeyForText = (value) => String(value || '').toLowerCase();")
  .replace("import { isSelfStudyScheduledForDate } from '../../shared/selfStudy.js';", "const isSelfStudyScheduledForDate = () => false;");
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
  state.absentSlotsByDate = input.absentSlotsByDate || {};
}
export async function __openHarness(row) {
  if (typeof window.openVideoAssignmentPopupForRow !== 'function') throw new Error('open harness not installed');
  return window.openVideoAssignmentPopupForRow(row);
}
export function __closeHarness() {
  if (typeof window.closeVideoAssignmentPopup !== 'function') throw new Error('close harness not installed');
  window.closeVideoAssignmentPopup();
}
export function __blockedMidsHarness() {
  return { ...activeBlockedMids };
}
export async function __saveHarness(options = {}) {
  if (typeof window.saveVideoAssignmentPopup !== 'function') throw new Error('save harness not installed');
  return window.saveVideoAssignmentPopup(options);
}
export function __effectiveAutoAssignCountHarness(stu, date) {
  return effectiveAutoAssignCountForStudent(stu, date);
}
export function __renderAutoAssignControlHarness(stu, date) {
  editingVideoDate = date;
  renderAutoAssignControl(stu);
  return globalThis.__elements.autoAssignCountToggle.innerHTML;
}
export function __videoMultiSelectionRangeMidsHarness(mids, anchorMid, targetMid) {
  const rows = (mids || []).map(mid => ({ dataset: { mid: String(mid) } }));
  return videoMultiSelectionRangeMids(rows, anchorMid, targetMid);
}
export function __videoMultiSelectionClickHarness(mids, clicks) {
  resetVideoMultiSelectionState();
  globalThis.__videoRows = (mids || []).map(globalThis.__makeVideoSelectionRow);
  globalThis.__elements.vidSelectionMeta.textContent = '';
  const clickHandler = globalThis.__elements.chkZone.listeners.click;
  if (typeof clickHandler !== 'function') throw new Error('video row click handler is missing');
  for (const click of (clicks || [])) {
    const row = globalThis.__videoRows.find(candidate => candidate.dataset.mid === String(click.mid));
    if (!row) continue;
    clickHandler({
      target: row,
      ctrlKey: click.ctrl === true,
      metaKey: click.meta === true,
      shiftKey: click.shift === true,
      preventDefault: () => {},
      stopPropagation: () => {},
    });
  }
  return {
    selected: (mids || []).map(String).filter(mid => activeVideoMultiSelectedMids.has(mid)),
    anchor: activeVideoMultiSelectionAnchorMid,
    meta: globalThis.__elements.vidSelectionMeta.textContent,
    rows: globalThis.__videoRows.map(row => ({
      mid: row.dataset.mid,
      selection: row.dataset.selection,
      ariaSelected: row.attributes['aria-selected'] || '',
      selectedClass: row.classList.contains('is-multi-selected'),
    })),
  };
}
export function __pickAutoVideosHarness(videos, blocked, count) {
  return pickAutoVideos(videos, blocked, count);
}
export function __currentCurriculumVideosHarness(stu, videos) {
  return currentCurriculumVideosForStudent(stu, videos).map(video => String(video.mid));
}
export async function __saveAutoAssignCountHarness(count) {
  return saveAutoAssignCountForCurrent(count);
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

ok(
  mod.__videoMultiSelectionRangeMidsHarness(['m1', 'm2', 'm3', 'm4'], 'm2', 'm4').join('|') === 'm2|m3|m4',
  'Ctrl+Shift range selection includes both endpoints in forward DOM order'
);
ok(
  mod.__videoMultiSelectionRangeMidsHarness(['m1', 'm2', 'm3', 'm4'], 'm4', 'm2').join('|') === 'm2|m3|m4',
  'Ctrl+Shift range selection supports a reverse anchor and target'
);
ok(
  mod.__videoMultiSelectionRangeMidsHarness(['m1', 'm2', 'm3'], 'stale-mid', 'm2').join('|') === 'm2',
  'Ctrl+Shift range selection falls back to the target when the anchor is not visible'
);
ok(
  mod.__videoMultiSelectionRangeMidsHarness(['m1', 'm2', 'm3'], 'm1', 'missing-mid').length === 0,
  'Ctrl+Shift range selection ignores a target outside the visible rows'
);
const forwardRange = mod.__videoMultiSelectionClickHarness(
  ['m1', 'm2', 'm3', 'm4', 'm5'],
  [{ mid: 'm2', ctrl: true }, { mid: 'm5', ctrl: true, shift: true }]
);
ok(forwardRange.selected.join('|') === 'm2|m3|m4|m5', 'actual Ctrl+Shift click selects the inclusive forward row range');
ok(forwardRange.anchor === 'm2', 'range selection preserves the original Ctrl-click anchor');
ok(forwardRange.meta.startsWith('선택 4개'), 'range selection updates the visible selection count');
ok(
  forwardRange.rows.filter(row => row.selectedClass && row.selection === 'selected' && row.ariaSelected === 'true').length === 4,
  'range selection updates class, data-selection, and aria-selected on every selected row'
);
const additiveReverseRange = mod.__videoMultiSelectionClickHarness(
  ['m1', 'm2', 'm3', 'm4', 'm5'],
  [{ mid: 'm1', ctrl: true }, { mid: 'm5', ctrl: true }, { mid: 'm3', ctrl: true, shift: true }]
);
ok(
  additiveReverseRange.selected.join('|') === 'm1|m3|m4|m5',
  'Ctrl+Shift click adds a reverse range without clearing prior disjoint selections'
);
const noAnchorRange = mod.__videoMultiSelectionClickHarness(
  ['m1', 'm2', 'm3'],
  [{ mid: 'm2', ctrl: true, shift: true }]
);
ok(
  noAnchorRange.selected.join('|') === 'm2' && noAnchorRange.anchor === 'm2',
  'Ctrl+Shift click without a visible anchor selects the target and establishes a new anchor'
);

const students = [{ id: '007', name: '학생7', curriculum: 'ALG', subCurriculum: 'BASE', day1: '토 13:00' }];
const videos = [
  { mid: 'm1', title: '일차함수', chapter: '1', curriculum: 'ALG', subCurriculum: 'BASE' },
  { mid: 'm2', title: '이차함수', chapter: '2', curriculum: 'ALG', subCurriculum: 'BASE' },
  { mid: 'extra-1', title: '확장 영상', chapter: '7', curriculum: 'ALG', subCurriculum: 'EXTRA' },
];
const curriculumScopeVideos = [
  { mid: 'able-1', title: '이전 A:ble 영상', chapter: '1', curriculum: 'CALC1', subCurriculum: 'A:Ble' },
  { mid: 'apex-2', title: '현재 APEX 2', chapter: '2', curriculum: 'CALC1', subCurriculum: 'APEX' },
  { mid: 'apex-1', title: '현재 APEX 1', chapter: '1', curriculum: 'calc1', subCurriculum: 'apex' },
  { mid: 'outside-1', title: '커리 외 영상', chapter: '1', curriculum: 'OTHER', subCurriculum: 'APEX' },
];
const apexStudent = {
  id: 'apex-current',
  name: 'APEX 학생',
  curriculum: 'CALC1',
  subCurriculum: 'APEX',
  autoVideoAssignCount: 2,
  day1: '금1',
};
ok(
  mod.__currentCurriculumVideosHarness(apexStudent, curriculumScopeVideos).join('|') === 'apex-1|apex-2',
  'automatic candidates contain only the exact current curriculum in chapter order'
);
ok(
  mod.__currentCurriculumVideosHarness(apexStudent, curriculumScopeVideos.filter(video => video.subCurriculum !== 'APEX' && video.subCurriculum !== 'apex')).length === 0,
  'an empty APEX catalog never falls back to previous A:ble videos'
);

const regularStudent = { autoVideoAssignCount: 2, day1: '금1', day2: '월2' };
const consecutiveStudent = { autoVideoAssignCount: 2, day1: '금1', day2: '금2' };
const compactConsecutiveStudent = { autoVideoAssignCount: 3, day1: '금1금2' };
const nonConsecutiveStudent = { autoVideoAssignCount: 3, day1: '금1', day2: '금3' };
const maxConsecutiveStudent = { autoVideoAssignCount: 6, day1: '금1', day2: '금2' };
ok(mod.__effectiveAutoAssignCountHarness(regularStudent, '2026-06-05') === 2, 'regular class keeps configured auto assignment count');
ok(mod.__effectiveAutoAssignCountHarness(consecutiveStudent, '2026-06-05') === 4, 'two configured videos become four for consecutive classes');
ok(mod.__effectiveAutoAssignCountHarness(compactConsecutiveStudent, '2026-06-05') === 6, 'three configured videos become six for compact consecutive class labels');
ok(mod.__effectiveAutoAssignCountHarness(nonConsecutiveStudent, '2026-06-05') === 3, 'non-consecutive slots do not increase auto assignment count');
ok(mod.__effectiveAutoAssignCountHarness(maxConsecutiveStudent, '2026-06-05') === 12, 'six configured videos become twelve for consecutive classes');
const partialAbsentStudent = { id: 'partial', autoVideoAssignCount: 2, day1: consecutiveStudent.day1, day2: consecutiveStudent.day2 };
mod.__setHarnessState({ absentSlotsByDate: { '2026-06-05': { partial: [2] } } });
ok(mod.__effectiveAutoAssignCountHarness(partialAbsentStudent, '2026-06-05') === 2, 'slot absence does not alter the daily cap');
mod.__renderAutoAssignControlHarness(partialAbsentStudent, '2026-06-05');
ok(globalThis.__elements.autoAssignCountLabel.textContent === '2\uac1c', 'slot absence renders the configured count without a consecutive label');
const autoAssignControlHtml = mod.__renderAutoAssignControlHarness(consecutiveStudent, '2026-06-05');
ok(globalThis.__elements.autoAssignCountLabel.textContent === '2개 설정 · 연강 자동 4개', 'consecutive classes render the doubled effective count');
ok(!autoAssignControlHtml.includes('type="range"'), 'auto assignment count no longer uses a range control');
ok((autoAssignControlHtml.match(/class="auto-count-btn/g) || []).length === 6, 'auto assignment count renders six choice buttons');
ok(autoAssignControlHtml.includes('data-count="1"') && autoAssignControlHtml.includes('data-count="6"'), 'auto assignment buttons support one through six');
ok(/data-count="2" aria-pressed="true"/.test(autoAssignControlHtml), 'configured count button exposes its selected state');
ok(autoAssignControlHtml.includes('border-radius:999px'), 'auto assignment choices preserve the original pill button shape');
ok(autoAssignControlHtml.includes('1개') && autoAssignControlHtml.includes('6개'), 'auto assignment choices preserve the original count labels');
ok(/data-count="2" aria-pressed="true"[\s\S]*background:#2563eb/.test(autoAssignControlHtml), 'configured count button preserves the original selected fill');
ok(
  source.includes('#vidModal .auto-count-btn')
    && source.includes('min-height:30px !important')
    && source.includes('border-radius:999px !important'),
  'popup layout overrides the global admin button normalization with the original computed pill dimensions'
);
ok(source.includes('@media (max-width: 900px)'), 'tablet-width unified popups use the readable single-card layout');

let calls = [];
const boundaryVideos = Array.from({ length: 12 }, (_, index) => ({
  mid: `boundary-${index + 1}`,
  title: `경계 영상 ${index + 1}`,
  chapter: String(index + 1),
  curriculum: 'ALG',
  subCurriculum: 'BASE',
}));
ok(mod.__pickAutoVideosHarness(boundaryVideos, {}, 12).length === 12, 'effective consecutive count is not reclamped to the six-setting maximum');
globalThis.__checkboxes = boundaryVideos.map(video => ({
  value: video.mid,
  checked: false,
  closest: () => null,
}));
mod.__setHarnessState({
  sid: 'boundary-student',
  date: '2026-06-05',
  students: [{
    id: 'boundary-student',
    curriculum: 'ALG',
    subCurriculum: 'BASE',
    autoVideoAssignCount: 2,
    day1: '금1',
    day2: '금2',
  }],
  videos: boundaryVideos,
  primaryVideoMids: boundaryVideos.map(video => video.mid),
  activeVideoList: boundaryVideos,
  activeBlockedMids: {},
  allowAutoAssign: true,
  autoGenerated: true,
});
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  return response({ ok: true });
};
await mod.__saveAutoAssignCountHarness(6);
const countUpdate = calls.find(call => call.url === '/api/update');
const boundaryPatch = calls.find(call => call.url === '/api/updates/patch');
ok(countUpdate?.body?.value === 6, 'button selection persists the configured maximum of six');
ok(!boundaryPatch, 'button selection never writes an assignment from the browser');
ok(
  !calls.some(call => call.url === '/api/updates?readOnly=1'),
  'button selection never reads or refreshes a future automatic snapshot'
);
ok(
  globalThis.__checkboxes.every(checkbox => checkbox.checked === false),
  'button selection leaves the opened assignment unchanged'
);

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  const value = String(url);
  if (value === '/api/updates' || value === '/api/updates?readOnly=1') {
    return response({ ok: true, updates: { '2026-06-05': { 'auto-existing': { videos: ['boundary-1', 'boundary-2'], source: 'auto' } } } });
  }
  if (value.startsWith('/api/logs/entry?')) return response({ ok: true, entry: {} });
  if (value === '/api/extra-attend') return response({ ok: true, extra: { '2026-06-05': [] } });
  if (value === '/api/progress?sid=auto-existing') {
    return response({
      '2026-06-01': { 'auto-existing': { 'boundary-1': 'done' } },
      '2026-06-05': { 'auto-existing': { 'boundary-2': 'assigned' } },
    });
  }
  if (value.startsWith('/api/watch/latest?')) return response({ ok: true, watch: {} });
  if (value === '/api/updates/patch') return response({ ok: true });
  return response({ ok: true });
};
mod.__setHarnessState({
  sid: 'auto-existing',
  date: '2026-06-05',
  students: [{
    id: 'auto-existing',
    curriculum: 'ALG',
    subCurriculum: 'BASE',
    autoVideoAssignCount: 2,
    day1: '금1',
    day2: '금2',
  }],
  videos: boundaryVideos,
  updates: {},
});
await mod.__openHarness(makeRow('auto-existing', '2026-06-05'));
const existingAutoRefreshPatch = calls.find(call => call.url === '/api/updates/patch');
ok(!existingAutoRefreshPatch, 'opening an existing automatic assignment is read-only');
ok(calls.some(call => call.url === '/api/progress?sid=auto-existing'), 'popup loads the student-wide progress history without a date filter');
ok(mod.__blockedMidsHarness()['boundary-1'] === true, 'past completed video remains blocked after opening the popup');
ok(globalThis.__elements.chkZone.innerHTML.includes('value="boundary-1" checked'), 'existing automatic assignment keeps its first video checked');
ok(globalThis.__elements.chkZone.innerHTML.includes('value="boundary-2" checked'), 'existing automatic assignment keeps its second video checked');

mod.__closeHarness();
calls = [];
await mod.__openHarness(makeRow('auto-existing', '2026-06-05'));
ok(calls.some(call => call.url === '/api/progress?sid=auto-existing'), 'reopening reloads the same student-wide progress history');
ok(!calls.some(call => call.url.startsWith('/api/progress?date=')), 'reopening never narrows auto-assignment history to only the popup date');
ok(mod.__blockedMidsHarness()['boundary-1'] === true, 'reopening does not reset the past completed-video blocklist');
ok(globalThis.__elements.chkZone.innerHTML.includes('value="boundary-1" checked'), 'reopening keeps the persisted first automatic video checked');
ok(globalThis.__elements.chkZone.innerHTML.includes('value="boundary-2" checked'), 'reopening keeps the persisted second automatic video checked');
ok(!calls.some(call => call.url === '/api/updates/patch'), 'reopening an existing automatic assignment remains read-only');

calls = [];
globalThis.__checkboxes = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  const value = String(url);
  if (value === '/api/updates?readOnly=1') {
    return response({ ok: true, updates: {
      '2026-06-05': {
        'apex-current': { videos: ['apex-1', 'able-1'], source: 'auto' },
      },
    } });
  }
  if (value.startsWith('/api/logs/entry?')) return response({ ok: true, entry: {} });
  if (value === '/api/extra-attend') return response({ ok: true, extra: { '2026-06-05': [] } });
  if (value === '/api/progress?sid=apex-current') return response({});
  if (value.startsWith('/api/watch/latest?')) return response({ ok: true, watch: {} });
  return response({ ok: true });
};
mod.__setHarnessState({
  sid: 'apex-current',
  date: '2026-06-05',
  students: [apexStudent],
  videos: curriculumScopeVideos,
  updates: {},
  progress: {},
});
await mod.__openHarness(makeRow('apex-current', '2026-06-05'));
const staleAutoCurriculumHtml = globalThis.__elements.chkZone.innerHTML;
ok(staleAutoCurriculumHtml.includes('value="apex-1" checked'), 'current APEX automatic video remains selected');
ok(!staleAutoCurriculumHtml.includes('value="able-1"'), 'stale automatic A:ble video is not presented as a cross-curriculum extra');
ok(!calls.some(call => call.url === '/api/updates/patch'), 'filtering a stale automatic snapshot on open remains read-only');

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  const value = String(url);
  if (value === '/api/updates?readOnly=1') {
    return response({ ok: true, updates: {
      '2026-06-05': {
        'apex-current': { videos: ['able-1', 'outside-1'], source: 'manual' },
      },
    } });
  }
  if (value.startsWith('/api/logs/entry?')) return response({ ok: true, entry: {} });
  if (value === '/api/extra-attend') return response({ ok: true, extra: { '2026-06-05': [] } });
  if (value === '/api/progress?sid=apex-current') return response({});
  if (value.startsWith('/api/watch/latest?')) return response({ ok: true, watch: {} });
  return response({ ok: true });
};
mod.__setHarnessState({
  sid: 'apex-current',
  date: '2026-06-05',
  students: [apexStudent],
  videos: curriculumScopeVideos,
  updates: {},
  progress: {},
});
await mod.__openHarness(makeRow('apex-current', '2026-06-05'));
const manualCrossCurriculumHtml = globalThis.__elements.chkZone.innerHTML;
ok(manualCrossCurriculumHtml.includes('value="able-1" checked'), 'manual A:ble addition remains visible for an APEX student');
ok(manualCrossCurriculumHtml.includes('value="outside-1" checked'), 'manual cross-subject addition remains visible and independent from automatic filtering');

calls = [];
const apexEmptyVideos = curriculumScopeVideos.filter(video => video.mid === 'able-1' || video.mid === 'outside-1');
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  const value = String(url);
  if (value === '/api/updates?readOnly=1') {
    return response({ ok: true, updates: {
      '2026-06-05': {
        'apex-current': { videos: ['able-1'], source: 'auto' },
      },
    } });
  }
  if (value.startsWith('/api/logs/entry?')) return response({ ok: true, entry: {} });
  if (value === '/api/extra-attend') return response({ ok: true, extra: { '2026-06-05': [] } });
  if (value === '/api/progress?sid=apex-current') return response({});
  if (value.startsWith('/api/watch/latest?')) return response({ ok: true, watch: {} });
  return response({ ok: true });
};
mod.__setHarnessState({
  sid: 'apex-current',
  date: '2026-06-05',
  students: [apexStudent],
  videos: apexEmptyVideos,
  updates: {},
  progress: {},
});
await mod.__openHarness(makeRow('apex-current', '2026-06-05'));
ok(!globalThis.__elements.chkZone.innerHTML.includes('value="able-1"'), 'empty APEX popup never falls back to an A:ble row');
calls = [];
await mod.__saveAutoAssignCountHarness(2);
const emptyApexPatch = calls.find(call => call.url === '/api/updates/patch');
ok(!emptyApexPatch, 'changing auto count never removes or rewrites today\'s stale snapshot');
ok(calls.some(call => call.url === '/api/update'), 'changing auto count still persists the future daily cap');

calls = [];
globalThis.__checkboxes = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  const value = String(url);
  if (value === '/api/updates?readOnly=1') {
    return response({ ok: true, updates: { '2026-06-06': {} } });
  }
  if (value.startsWith('/api/logs/entry?')) return response({ ok: true, entry: {} });
  if (value === '/api/extra-attend') return response({ ok: true, extra: { '2026-06-06': [] } });
  if (value === '/api/progress') return response({ ok: true, progress: {} });
  return response({ ok: true });
};
mod.__setHarnessState({
  sid: '007',
  date: '2026-06-06',
  students,
  videos,
  updates: {},
  progress: {},
});
await mod.__openHarness(makeRow());
const emptyAssignmentHtml = globalThis.__elements.chkZone.innerHTML;
ok(!emptyAssignmentHtml.includes(' checked'), 'opening a student with no snapshot does not invent checked videos');
ok(!calls.some((call) => call.url === '/api/updates/patch'), 'opening a student with no snapshot never writes an assignment');

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push(callRecord(url, init));
  const value = String(url);
  if (value === '/api/updates' || value === '/api/updates?readOnly=1') {
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
  if (value === '/api/updates' || value === '/api/updates?readOnly=1') {
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
  if (value === '/api/updates' || value === '/api/updates?readOnly=1') {
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
        proc = _run_captured(cmd)
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
  .replace("import { classifySaveConflict } from '../core/saveConflict.js';", "const classifySaveConflict = (data, label) => ({ retryable: data?.retryable === true, message: data?.error || `${label} 저장 충돌` });")
  .replace(/import \{ initTestModal \} from '\.\/testModal\.js\?v=[^']+';/, "const initTestModal = () => {};");
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
        proc = _run_captured(cmd)
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
        "const sleepingHomeworkBooks = collectSleepingHomeworkBooks();",
        "setLogModalSnapshots(notesNow, hwRows, sleepingHomeworkBooks);",
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
        "const HOMEWORK_SLEEPING_BOOKS_KEY = 'sleepingHomeworkBooks';",
        "function syncHomeworkSleepingControls()",
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
  .replace("import { classifySaveConflict } from '../core/saveConflict.js';", "const classifySaveConflict = (data, label) => ({ retryable: data?.retryable === true, message: data?.error || `${label} 저장 충돌` });")
  .replace(/import \{ initTestModal \} from '\.\/testModal\.js\?v=[^']+';/, "const initTestModal = () => {};");
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
        proc = _run_captured(cmd)
    except FileNotFoundError:
        raise AssertionError("node not found")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    _assert_unit(proc.returncode == 0, "admin log modal save policy driver failed")


def run_admin_weekend_slot_behavior_checks() -> None:
    calendar_source = (ROOT / "static/js/admin/features/calendar.js").read_text(encoding="utf-8")
    extra_source = (ROOT / "static/js/admin/features/extraModal.js").read_text(encoding="utf-8")
    demo_source = (ROOT / "static/js/admin/demo/fetch.js").read_text(encoding="utf-8")
    _assert_unit(
        "saveWeekendSlotsPatch" in calendar_source
        and "JSON.stringify({ [dateStr]: perDate })" not in calendar_source,
        "calendar weekend slot writers use student-scoped patches",
    )
    _assert_unit(
        "saveWeekendSlotsPatch" in extra_source
        and "JSON.stringify({ [today]: perDay })" not in extra_source,
        "extra-attendance modal uses student-scoped weekend patches",
    )
    _assert_unit(
        "mergeWeekendSlotsPatch(store, body)" in demo_source,
        "admin demo mirrors the live nested weekend-slot patch contract",
    )
    _assert_unit(
        "{ date: today, sids: selectedIds }" in extra_source
        and "{ method: 'PATCH' }" in extra_source
        and "JSON.stringify(state.extra)" not in extra_source,
        "extra-attendance modal saves only its frozen date",
    )
    _assert_unit(
        "patchExtraAttendDates" in calendar_source
        and "postJson('/api/extra-attend'" not in calendar_source
        and "postMakeupCarryoverSnapshot(next, revision)" in calendar_source
        and "X-Makeup-Carryover-Revision" in calendar_source,
        "calendar uses date-scoped extra-attend patches and revision-guarded makeup writes",
    )
    _assert_unit(
        "method === 'PATCH'" in demo_source
        and "const rawDates = body?.dates" in demo_source
        and "makeup_revision_conflict" in demo_source,
        "admin demo mirrors extra-attend patches and makeup revision conflicts",
    )

    from scripts.verify_makeup_schedule_links import test_makeup_revision_guard
    test_makeup_revision_guard()

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
const sunday = '2026-07-05';
globalThis.__state = {
  students: [{ id: 's1', day1: '일1', day2: '일2' }],
  extra: {},
  logs: {},
  absentSlotsByDate: {},
};
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && !init.method) return response({ [sunday]: { s1: [1, 2], other: [1] } });
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return response('', 204);
  if (String(url).startsWith('/api/today_order') && init.method === 'DELETE') return response({ ok: true, cleared: true });
  return response({});
};
const stateSuccess = await loadStateModule('weekend-student-patch');
await stateSuccess.loadWeekendSlots();
calls = [];
await stateSuccess.saveWeekendSlotsFromLabel('s1', '일2', sunday);
const weekendPost = calls.find(call => call.url === '/api/weekend-slots' && call.method === 'POST');
ok(weekendPost, 'weekend slots success posts');
ok(JSON.stringify(weekendPost.body?.[sunday]) === JSON.stringify({ s1: [2] }), 'inline slot edit posts only the edited student');
ok(!calls.some(call => call.url === '/api/weekend-slots' && call.method === 'GET'), 'inline slot edit does not perform a stale whole-map GET');
ok(stateSuccess.labelFor(sunday, 's1') === '일2', '일1·일2 can narrow to 일2 immediately');
ok(globalThis.__state.weekendSlots?.[sunday]?.other?.[0] === 1, 'local student patch preserves another student');
const orderIndex = calls.findIndex(call => call.url.startsWith('/api/today_order') && call.method === 'DELETE');
const postIndex = calls.findIndex(call => call.url === '/api/weekend-slots' && call.method === 'POST');
ok(postIndex >= 0 && orderIndex > postIndex, 'today order clears only after weekend slots POST success');

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return response('save failed', 500);
  if (String(url).startsWith('/api/today_order')) return response({ ok: true, cleared: false });
  return response({});
};
const statePostNonOk = await loadStateModule('weekend-post-non-ok');
let postNonOkRejected = false;
try {
  await statePostNonOk.saveWeekendSlotsFromLabel('s1', '일2', sunday);
} catch (err) {
  postNonOkRejected = true;
  ok(String(err?.message || '').includes('/api/weekend-slots'), 'POST non-ok error names weekend slots endpoint');
}
ok(postNonOkRejected, 'weekend slots POST non-ok rejects');
ok(!calls.some(call => call.url.startsWith('/api/today_order')), 'weekend slots POST non-ok must not clear today order');

calls = [];
let resolveStaleLoad;
globalThis.__state = {
  students: [{ id: 's1', day1: '일1', day2: '일2' }],
  extra: {},
  logs: {},
  absentSlotsByDate: {},
};
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && !init.method) return new Promise(resolve => { resolveStaleLoad = resolve; });
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return response('', 204);
  if (String(url).startsWith('/api/today_order') && init.method === 'DELETE') return response({ ok: true, cleared: true });
  return response({});
};
const stateStaleLoad = await loadStateModule('weekend-stale-load');
const staleLoad = stateStaleLoad.loadWeekendSlots();
ok(typeof resolveStaleLoad === 'function', 'stale weekend load is pending before the inline edit');
await stateStaleLoad.saveWeekendSlotsFromLabel('s1', '일1', sunday);
resolveStaleLoad(response({ [sunday]: { s1: [1, 2] } }));
await staleLoad;
ok(stateStaleLoad.labelFor(sunday, 's1') === '일1', 'a load started before save cannot restore stale 일1·일2 after the 일1 edit');

calls = [];
const pendingPostResolvers = [];
globalThis.__state = {
  students: [{ id: 's1', day1: '일1', day2: '일2' }],
  extra: {},
  logs: {},
  absentSlotsByDate: {},
};
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return new Promise(resolve => pendingPostResolvers.push(resolve));
  if (String(url).startsWith('/api/today_order') && init.method === 'DELETE') return response({ ok: true, cleared: true });
  return response({});
};
const stateQueuedSaves = await loadStateModule('weekend-queued-saves');
const firstSave = stateQueuedSaves.saveWeekendSlotsFromLabel('s1', '일1', sunday);
const secondSave = stateQueuedSaves.saveWeekendSlotsFromLabel('s1', '일2', sunday);
await new Promise(resolve => setImmediate(resolve));
ok(pendingPostResolvers.length === 1, 'overlapping slot edits serialize the first POST');
pendingPostResolvers[0](response('', 204));
await new Promise(resolve => setImmediate(resolve));
ok(pendingPostResolvers.length === 2, 'the second slot POST starts only after the first commits');
pendingPostResolvers[1](response('', 204));
await Promise.all([firstSave, secondSave]);
const queuedPosts = calls.filter(call => call.url === '/api/weekend-slots' && call.method === 'POST');
ok(queuedPosts[0].body[sunday].s1[0] === 1, 'first queued edit keeps its requested slot');
ok(queuedPosts[1].body[sunday].s1[0] === 2, 'second queued edit keeps its requested slot');
ok(stateQueuedSaves.labelFor(sunday, 's1') === '일2', 'last inline edit remains authoritative');

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return response('', 204);
  if (String(url).startsWith('/api/today_order') && init.method === 'DELETE') return response({ error: 'busy' }, 503);
  if (String(url) === '/api/today_order' && !init.method) return response({ '2026-06-07': ['keep'] });
  return response({});
};
const statePartialOrder = await loadStateModule('weekend-partial-order-reset');
const originalWarn = console.warn;
console.warn = () => {};
let partialOrderResult;
try {
  partialOrderResult = await statePartialOrder.saveWeekendSlotsFromLabel('s1', '일2', sunday);
} finally {
  console.warn = originalWarn;
}
ok(partialOrderResult?.saved === true, 'weekend slot save remains committed when order reset fails');
ok(partialOrderResult?.orderReset === false, 'weekend slot save reports partial order-reset failure');
ok(calls.some(call => call.url === '/api/weekend-slots' && call.method === 'POST'), 'partial result follows a committed slot POST');

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/today_order' && init.method === 'PATCH') {
    return response({ ok: true, date: init.body ? JSON.parse(String(init.body)).date : '', order: ['s2', 's1'] });
  }
  return response({});
};
const stateOrderPatch = await loadStateModule('today-order-patch');
const savedOrder = await stateOrderPatch.saveOrder('2026-06-06', ['s2', 's1', 's2']);
ok(JSON.stringify(savedOrder) === JSON.stringify(['s2', 's1']), 'saveOrder returns the canonical date-scoped order');
ok(calls.length === 1 && calls[0].method === 'PATCH', 'saveOrder uses one PATCH without whole-map GET/POST');
ok(calls[0].body?.date === '2026-06-06', 'saveOrder PATCH binds the selected date');

calls = [];
let currentWeekendSlots = { '2026-07-05': { s1: [1] } };
globalThis.__state = {
  students: [{ id: 's1', day1: '일2' }],
  extra: {},
  logs: {},
  absentSlotsByDate: { '2026-07-05': { s1: [2] } },
};
globalThis.fetch = async (url, init = {}) => {
  const call = { url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null };
  calls.push(call);
  if (String(url) === '/api/weekend-slots' && !init.method) return response(currentWeekendSlots);
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') {
    currentWeekendSlots = { ...currentWeekendSlots, ...call.body };
    return response('', 204);
  }
  if (String(url).startsWith('/api/today_order') && init.method === 'DELETE') return response({ ok: true, cleared: true });
  return response({});
};
const stateWidenCompact = await loadStateModule('weekend-widen-compact-label');
await stateWidenCompact.loadWeekendSlots();
ok(stateWidenCompact.labelFor('2026-07-05', 's1') === '일1', 'saved 일1 override is visible before widening');
await stateWidenCompact.saveWeekendSlotsFromLabel('s1', '일1일2', '2026-07-05');
const weekendWidenPost = calls.find(call => call.url === '/api/weekend-slots' && call.method === 'POST');
ok(
  JSON.stringify(weekendWidenPost?.body?.['2026-07-05']?.s1) === JSON.stringify([1, 2]),
  'compact 일1일2 edit posts explicit [1,2] override',
);
ok(
  stateWidenCompact.labelFor('2026-07-05', 's1') === '일1 일2',
  'compact 일1일2 edit reloads as combined visible label despite stale absent slot',
);

calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
  if (String(url) === '/api/weekend-slots' && !init.method) return response({});
  if (String(url) === '/api/weekend-slots' && init.method === 'POST') return response({ ok: true });
  if (String(url).startsWith('/api/today_order') && init.method === 'DELETE') return response({ ok: true, cleared: false });
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
    .replace("import { decorateStudentTestRecordButtons } from '../../shared/testRecordDetails.js';", "const decorateStudentTestRecordButtons = async () => {};")
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
        proc = _run_captured(cmd)
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
        run_smoke_sqlite_observation_unit_checks,
        run_admin_date_session_storage_checks,
        run_test_catalog_search_sort_checks,
        run_hover_tooltip_performance_checks,
        run_admin_latency_contract_checks,
        run_export_log_format_checks,
        run_today_completion_checks,
        run_legacy_consumer_cleanup_checks,
        run_person_identity_checks,
        run_file_reference_route_checks,
        run_school_calendar_revision_checks,
        run_today_order_store_migration_checks,
        run_app_import_smoke_checks,
        run_log_rules_unit_checks,
        run_all_students_linked_books_and_log_popup_source_checks,
        run_progress_rule_unit_checks,
        run_student_previous_video_review_rule_unit_checks,
        run_progress_batch_sids_unit_checks,
        run_progress_read_cache_unit_checks,
        run_progress_route_checks,
        run_updates_route_checks,
        run_student_auto_assignment_service_checks,
        run_student_video_assignment_rule_checks,
        run_video_completion_unit_checks,
        run_video_assignment_snapshot_unit_checks,
        run_video_assignment_route_hook_unit_checks,
        run_auto_assignment_progress_reconcile_unit_checks,
        run_self_study_assignment_route_unit_checks,
        run_video_assignment_boundary_source_checks,
        run_video_completion_source_checks,
        run_self_study_video_assignment_source_checks,
        run_watch_route_progress_unit_checks,
        run_video_progress_integration_matrix_checks,
        run_log_route_checks,
        run_log_repository_unit_checks,
        run_material_route_checks,
        run_schedule_override_route_checks,
        run_legacy_test_record_cache_unit_checks,
        run_test_shared_service_checks,
        run_announcement_image_access_checks,
        run_student_answer_link_precedence_unit_checks,
        run_student_bootstrap_route_checks,
        run_student_bootstrap_state_checks,
        run_student_announcement_state_checks,
        run_student_test_presentation_checks,
        run_student_previous_video_review_bootstrap_unit_checks,
        run_student_bootstrap_unit_checks,
        run_retired_test_submission_surface_checks,
        run_admin_tests_record_detail_contract_checks,
        run_admin_tests_record_detail_ui_checks,
        run_admin_tests_record_detail_answer_link_ui_checks,
        run_retired_test_submission_assignment_boundary_checks,
        run_student_material_access_scope_checks,
        run_video_manage_id_checks,
        run_video_mid_change_guard_checks,
        run_video_catalog_correction_checks,
        run_mobile_touch_target_checks,
        run_student_submission_retirement_and_assignment_checks,
        run_academy_proxy_network_access_checks,
        run_test_answer_mode_contract_checks,
        run_student_test_ocr_contract_checks,
        run_absence_test_assignment_transition_unit_checks,
        run_absence_makeup_integration_matrix_checks,
        run_student_answer_link_render_source_checks,
        run_unit_test_answer_material_contract_checks,
        run_catalog_script_safety_source_checks,
        run_catalog_script_temp_file_behavior_checks,
        run_admin_css_inventory_checks,
        run_admin_css_scope_source_checks,
        run_student_css_scope_source_checks,
        run_shared_css_scope_source_checks,
        run_refactor_contract_evidence_source_checks,
        run_verifier_execution_policy_source_checks,
        run_student_mobile_result_contract_checks,
        run_student_mobile_pwa_flow_checks,
        run_student_mobile_deployment_guard_unit_checks,
        run_student_mobile_deployment_contract_checks,
        run_student_mobile_python_result_contract_checks,
        run_refactor_notes_contract_source_checks,
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
        run_admin_student_popup_scroll_source_checks,
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
        ("arrive-time date", f"/api/arrive-time?{date_qs}"),
    ]

    if sid:
        paths.append(("watch latest date/sid", f"/api/watch/latest?{qs}"))

    return paths


def smoke_log_paths(date: str, sid: str) -> list[tuple[str, str]]:
    date = str(date or "").strip()
    sid = str(sid or "").strip()
    if not DATE_RE.fullmatch(date) or not sid:
        return []
    qs = urllib.parse.urlencode({"date": date, "sid": sid})
    return [
        ("log entry date/sid", f"/api/logs/entry?{qs}"),
        ("logs date/sid", f"/api/logs?{qs}"),
    ]


def _run_smoke_gets(client, paths: Iterable[tuple[str, str]]) -> bool:
    ok = True
    for label, path in paths:
        resp = client.get(path)
        endpoint = path.partition("?")[0]
        print(f"GET {endpoint} -> {resp.status_code} ({label}; query values redacted)")
        if resp.status_code != 200:
            ok = False
    return ok


def run_smoke_checks(*, include_log_gets: bool = False) -> bool:
    if not import_smoke_is_safe():
        return False

    before = runtime_fingerprints()
    before_sqlite = sqlite_runtime_metadata()
    sys.path.insert(0, str(ROOT))
    from app import app  # noqa: PLC0415

    date, sid = smoke_candidate()
    print("smoke candidate selected (date/SID values redacted)")
    client = app.test_client()

    ok = _run_smoke_gets(client, smoke_paths(date, sid))
    if include_log_gets:
        log_paths = smoke_log_paths(date, sid)
        if not log_paths:
            print(
                "Cannot run explicitly enabled log GET smoke checks without a valid date and nonempty SID candidate.",
                file=sys.stderr,
            )
            ok = False
        else:
            print("Running explicitly enabled log GET smoke checks; response bodies are not inspected or printed.")
            ok = _run_smoke_gets(client, log_paths) and ok
    else:
        print("Skipped GET /api/logs/entry because it may touch SQLite WAL/schema state.")
        print("Skipped GET /api/logs because it may touch SQLite WAL/schema state.")
    print("Skipped GET /api/updates because it can auto-write updates.json.")
    print("Skipped today's /api/student/bootstrap because it can auto-write updates.json.")

    after = runtime_fingerprints()
    after_sqlite = sqlite_runtime_metadata()
    changed = runtime_diff_keys(before, after)
    sqlite_changes = sqlite_change_observations(before_sqlite, after_sqlite)
    print_sqlite_change_observations(sqlite_changes)
    disallowed_runtime_changes = [key for key in changed if not is_sqlite_transient_sidecar(key)]
    if disallowed_runtime_changes:
        print_runtime_diff(before, after)
        return False
    if not sqlite_change_observations_are_safe(sqlite_changes):
        print("main SQLite file metadata changed during smoke checks", file=sys.stderr)
        return False
    if changed or sqlite_changes:
        print("runtime fingerprints unchanged except allowed SQLite sidecars")
    else:
        print("runtime fingerprints unchanged after smoke checks")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Run safe refactor verification checks.")
    parser.add_argument("--smoke", action="store_true", help="Run safe GET smoke checks with runtime fingerprints.")
    parser.add_argument(
        "--smoke-log-gets",
        action="store_true",
        help="With --smoke, opt in to risky log GETs that may touch SQLite WAL/schema state.",
    )
    parser.add_argument(
        "--only-admin-date-session-storage",
        action="store_true",
        help="Run only admin selected-date sessionStorage and date-bar behavior checks.",
    )
    parser.add_argument(
        "--only-test-catalog-search-sort",
        action="store_true",
        help="Run only test catalog search and group-local ordering checks.",
    )
    parser.add_argument(
        "--only-hover-tooltip-performance",
        action="store_true",
        help="Run only admin hover tooltip large-roster performance checks.",
    )
    parser.add_argument(
        "--only-hover-tooltip-accessibility",
        action="store_true",
        help="Run only responsive keyboard/ARIA hover tooltip checks.",
    )
    parser.add_argument(
        "--only-export-log-format",
        action="store_true",
        help="Run only class-log export format customization and roster regression checks.",
    )
    parser.add_argument(
        "--only-today-completion",
        action="store_true",
        help="Run only absence recovery convergence and all-date unarchived done checks.",
    )
    parser.add_argument(
        "--only-student-install-guide",
        action="store_true",
        help="Run only the student-app install-guide boot and interaction flow checks.",
    )
    parser.add_argument(
        "--only-student-mobile-deployment",
        action="store_true",
        help="Run only temp-only student-app deployment and rollback contract checks.",
    )
    parser.add_argument(
        "--only-legacy-test-record-cache",
        action="store_true",
        help="Run only legacy logs test-record projection cache checks.",
    )
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
        "--only-admin-student-popup-scroll-source",
        action="store_true",
        help="Run only administrator student popup scroll restoration source checks.",
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
        "--only-retired-test-submission-surface",
        action="store_true",
        help="Run only retired student test-submission surface checks.",
    )
    parser.add_argument(
        "--only-admin-tests-record-details",
        action="store_true",
        help="Run only admin test-record wrong-answer detail contract checks.",
    )
    parser.add_argument(
        "--only-unit-test-answer-material-contract",
        action="store_true",
        help="Run only the synthetic UNIT answer-material contract checks.",
    )
    parser.add_argument(
        "--only-unit-test-answer-material-readiness",
        action="store_true",
        help="Run only live UNIT catalog answer-material readiness checks.",
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
    args = parser.parse_args()
    if args.smoke_log_gets and not args.smoke:
        parser.error("--smoke-log-gets requires --smoke")

    selected_checks = []
    if args.only_admin_date_session_storage:
        selected_checks.append(run_admin_date_session_storage_checks)
    if args.only_test_catalog_search_sort:
        selected_checks.append(run_test_catalog_search_sort_checks)
    if args.only_hover_tooltip_performance or args.only_hover_tooltip_accessibility:
        selected_checks.append(run_hover_tooltip_performance_checks)
    if args.only_export_log_format:
        selected_checks.append(run_export_log_format_checks)
    if args.only_today_completion:
        selected_checks.append(run_today_completion_checks)
    if args.only_student_install_guide:
        selected_checks.append(run_student_mobile_pwa_flow_checks)
    if args.only_student_mobile_deployment:
        selected_checks.append(run_student_mobile_deployment_guard_unit_checks)
        selected_checks.append(run_student_mobile_deployment_contract_checks)
    if args.only_legacy_test_record_cache:
        selected_checks.append(run_legacy_test_record_cache_unit_checks)
    if args.only_admin_weekend_slot_behavior:
        selected_checks.append(run_admin_weekend_slot_behavior_checks)
    if args.only_admin_calendar_test_completion_source:
        selected_checks.append(run_admin_calendar_test_completion_source_checks)
    if args.only_video_modal_preflight_source:
        selected_checks.append(run_admin_video_modal_preflight_source_checks)
    if args.only_admin_student_popup_scroll_source:
        selected_checks.append(run_admin_student_popup_scroll_source_checks)
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
    if args.only_retired_test_submission_surface:
        selected_checks.append(run_retired_test_submission_surface_checks)
    if args.only_admin_tests_record_details:
        selected_checks.append(run_admin_tests_record_detail_contract_checks)
        selected_checks.append(run_admin_tests_record_detail_ui_checks)
        selected_checks.append(run_admin_tests_record_detail_answer_link_ui_checks)
    if args.only_unit_test_answer_material_contract:
        selected_checks.append(run_unit_test_answer_material_contract_checks)
    if args.only_unit_test_answer_material_readiness:
        selected_checks.append(run_unit_test_answer_material_readiness_checks)
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
    ok = run_python311_syntax_checks() and ok
    ok = run_unit_checks() and ok
    ok = run_js_checks() and ok
    if args.smoke:
        ok = run_smoke_checks(include_log_gets=args.smoke_log_gets) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
