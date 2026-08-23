"""Focused student-mobile-app verification dispatcher."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Final, Mapping, TypeAlias


ROOT: Final = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CheckValue: TypeAlias = str | int | bool | None | tuple["CheckValue", ...] | list["CheckValue"] | dict[str, "CheckValue"]
CheckResult: TypeAlias = dict[str, CheckValue]
CHECK_MODULES: Final[dict[str, str]] = {
    "config": "scripts.student_mobile_app_checks.config",
    "accounts": "scripts.student_mobile_app_checks.accounts",
    "repositories": "scripts.student_mobile_app_checks.repositories",
    "auth": "scripts.student_mobile_app_checks.auth",
    "surface": "scripts.student_mobile_app_checks.surface",
    "student-data": "scripts.student_mobile_app_checks.student_data",
    "dashboard": "scripts.student_mobile_app_checks.dashboard",
    "homework": "scripts.student_mobile_app_checks.homework",
    "notifications": "scripts.student_mobile_app_checks.notifications",
    "board": "scripts.student_mobile_app_checks.board",
    "focus": "scripts.student_mobile_app_checks.focus",
    "push-sender": "scripts.student_mobile_app_checks.push_sender",
    "push": "scripts.student_mobile_app_checks.push",
    "test-push": "scripts.student_mobile_app_checks.test_push",
    "admin-accounts": "scripts.student_mobile_app_checks.admin_accounts",
    "academy-gates": "scripts.student_mobile_app_checks.academy_gates",
    "deployment": "scripts.student_mobile_app_checks.deployment",
}
# Every plugin result is bound to the CLI selector that invoked it.  Keep this
# explicit so a forged or stale plugin cannot report a different check as
# successful, and so future modules must opt into the same result contract.
EXPECTED_RESULT_NAMES: Final[dict[str, str]] = {
    "config": "config",
    "accounts": "accounts",
    "repositories": "repositories",
    "auth": "auth",
    "surface": "surface",
    "student-data": "student-data",
    "dashboard": "dashboard",
    "homework": "homework",
    "notifications": "notifications",
    "board": "board",
    "focus": "focus",
    "push-sender": "push-sender",
    "push": "push",
    "test-push": "test-push",
    "admin-accounts": "admin-accounts",
    "academy-gates": "academy-gates",
    "deployment": "deployment",
}
SUPPORTED_CHECKS: Final[tuple[str, ...]] = tuple(CHECK_MODULES) + ("all",)
RUNTIME_FILE_NAMES: Final[tuple[str, ...]] = (
    "students.json",
    "videos.json",
    "progress.json",
    "materials.json",
    "mat_assign.json",
    "updates.json",
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
    "auth_accounts.json",
    "app.sqlite",
)


class RuntimeStateChangedError(RuntimeError):
    """Raised when a focused check mutates live runtime data."""


class StudentMobileAppCheckError(RuntimeError):
    """Raised when a focused check cannot be dispatched."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_paths() -> tuple[Path, ...]:
    paths: dict[str, Path] = {}
    for name in RUNTIME_FILE_NAMES:
        path = ROOT / name
        if path.is_file():
            paths[path.relative_to(ROOT).as_posix()] = path
    for path in ROOT.glob("app.sqlite*"):
        if path.is_file():
            paths[path.relative_to(ROOT).as_posix()] = path
    for directory_name in ("files", "data"):
        directory = ROOT / directory_name
        if directory.is_dir():
            for path in directory.rglob("*"):
                if path.is_file():
                    paths[path.relative_to(ROOT).as_posix()] = path
    return tuple(paths[key] for key in sorted(paths))


def runtime_snapshot() -> dict[str, dict[str, int | str]]:
    """Capture live runtime hashes and mtimes without importing app paths."""
    snapshot: dict[str, dict[str, int | str]] = {}
    for path in _runtime_paths():
        relative = path.relative_to(ROOT).as_posix()
        stat = path.stat()
        snapshot[relative] = {
            "sha256": _sha256(path),
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
        }
    return snapshot


def _load_result(name: str) -> CheckResult:
    module_name = CHECK_MODULES[name]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name or (exc.name and module_name.startswith(f"{exc.name}.")):
            raise StudentMobileAppCheckError(f"check module for --only {name!r} is not available: {module_name}") from exc
        raise
    runner = getattr(module, "run_checks", None)
    if not callable(runner):
        raise StudentMobileAppCheckError(f"check module {module_name} does not expose run_checks()")
    result = runner()
    if not isinstance(result, dict):
        raise StudentMobileAppCheckError(f"check module {module_name} returned a non-dict result")
    if not {"name", "assertions", "passed"}.issubset(result):
        raise StudentMobileAppCheckError(f"check module {module_name} omitted required result fields")
    expected_name = EXPECTED_RESULT_NAMES[name]
    result_name = result["name"]
    if not isinstance(result_name, str):
        raise StudentMobileAppCheckError(f"check module {module_name} returned a non-text result name")
    if result_name != expected_name:
        raise StudentMobileAppCheckError(
            f"check module {module_name} reported result name {result_name!r}; expected {expected_name!r}"
        )
    if not isinstance(result["assertions"], int) or isinstance(result["assertions"], bool):
        raise StudentMobileAppCheckError(f"check module {module_name} returned a non-integer assertion count")
    if result["assertions"] <= 0:
        raise StudentMobileAppCheckError(f"check module {module_name} returned a non-positive assertion count")
    if type(result["passed"]) is not bool:
        raise StudentMobileAppCheckError(f"check module {module_name} returned a non-boolean passed flag")
    if result["passed"] is not True:
        raise StudentMobileAppCheckError(f"check module {module_name} reported failure")
    return result


def _select_checks(name: str) -> tuple[str, ...]:
    if name == "all":
        return tuple(CHECK_MODULES)
    return (name,)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=SUPPORTED_CHECKS,
        default="all",
        help="run one focused check (all requires every Wave module to exist)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run selected checks and prove live runtime data remained unchanged."""
    args = _parser().parse_args(argv)
    selected = _select_checks(args.only)
    before = runtime_snapshot()
    after = before
    results: list[CheckResult] = []
    try:
        if args.only == "all":
            missing = [name for name in selected if not (ROOT / CHECK_MODULES[name].replace(".", "/")).with_suffix(".py").is_file()]
            if missing:
                modules = ", ".join(CHECK_MODULES[name] for name in missing)
                raise StudentMobileAppCheckError(f"--only all requires missing future check modules: {modules}")
        for name in selected:
            results.append(_load_result(name))
        after = runtime_snapshot()
        if before != after:
            raise RuntimeStateChangedError("runtime data changed during focused verification")
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK
        if after is before:
            after = runtime_snapshot()
        diff = _snapshot_diff(before, after)
        print(f"student mobile app checks FAILED: {exc}", file=sys.stderr)
        print(f"runtime diff: {json.dumps(diff, sort_keys=True)}", file=sys.stderr)
        return 1

    assertions = sum(int(result["assertions"]) for result in results)
    result_dump: Mapping[str, CheckValue] = {
        "checks": results,
        "assertions": assertions,
        "passed": True,
        "runtime_diff": {},
    }
    print(f"student mobile app checks passed: {assertions} assertions ({args.only})")
    print(json.dumps(result_dump, ensure_ascii=False, sort_keys=True, default=str))
    print("runtime diff: {}")
    return 0


def _snapshot_diff(
    before: dict[str, dict[str, int | str]],
    after: dict[str, dict[str, int | str]],
) -> dict[str, CheckValue]:
    keys = sorted(set(before) | set(after))
    return {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in keys
        if before.get(key) != after.get(key)
    }


if __name__ == "__main__":
    raise SystemExit(main())
