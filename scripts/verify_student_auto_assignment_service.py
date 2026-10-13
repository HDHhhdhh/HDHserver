from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.absence_transaction import (  # noqa: E402
    absence_consistency_barrier,
    absence_transaction_scope,
)
from core.storage import file_lock, save_atomic  # noqa: E402
from core.update_assignment_store import (  # noqa: E402
    UpdateAssignmentStoreError,
    load_updates_strict,
    save_updates_strict,
    updates_lock,
)
from routes.student_auto_assignment_service import (  # noqa: E402
    StudentAutoAssignmentServiceDependencies,
    load_updates_with_auto_assign,
    reconcile_self_study_assignment,
)


DATE = "2026-06-06"
SID = "007"


def fingerprint(path: Path) -> tuple[int, str]:
    content = path.read_bytes()
    return len(content), hashlib.sha256(content).hexdigest()


def write_literal(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


class FixtureLogRepository:
    def __init__(self, runtime: "FixtureRuntime") -> None:
        self.runtime = runtime

    def read_logs(self, date_key: str, sid: str | None = None):
        event = (
            ("read_logs", date_key, self.runtime.lock_depth)
            if sid is None
            else (
                "read_logs_for_sid",
                date_key,
                sid,
                self.runtime.lock_depth,
            )
        )
        self.runtime.events.append(event)
        return deepcopy(self.runtime.logs)


class FixtureRuntime:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.paths = {
            name: root / f"{name}.json"
            for name in (
                "updates",
                "students",
                "videos",
                "extra",
                "watch",
                "weekend",
                "progress",
                "absent",
            )
        }
        self.logs = {DATE: {}}
        self.events: list[tuple] = []
        self.lock_depth = 0
        self.max_lock_depth = 0
        self.save_count = 0
        self.fail_save = False
        self.slow_updates_load = False
        self._gate = threading.Lock()

    def seed(self, updates: dict | None = None) -> None:
        fixtures = {
            "updates": updates
            if updates is not None
            else {
                "2026-06-05": {
                    "other": {
                        "videos": ["legacy"],
                        "source": "manual",
                        "unknown": {"keep": True},
                    }
                }
            },
            "students": [
                {
                    "id": SID,
                    "curriculum": "ALG",
                    "subCurriculum": "BASE",
                    "autoVideoAssignCount": 2,
                    "day1": "토1",
                }
            ],
            "videos": [
                {
                    "mid": "m2",
                    "chapter": "2",
                    "curriculum": "ALG",
                    "subCurriculum": "BASE",
                },
                {
                    "mid": "other-course",
                    "chapter": "0",
                    "curriculum": "OTHER",
                    "subCurriculum": "BASE",
                },
                {
                    "mid": "m1",
                    "chapter": "1",
                    "curriculum": "ALG",
                    "subCurriculum": "BASE",
                },
            ],
            "extra": {},
            "watch": {},
            "weekend": {},
            "progress": {},
            "absent": {
                "by_date": {},
                "by_student": {},
                "by_slot": {},
            },
        }
        for name, value in fixtures.items():
            write_literal(self.paths[name], value)
        self.events.clear()
        self.lock_depth = 0
        self.max_lock_depth = 0
        self.save_count = 0
        self.fail_save = False
        self.slow_updates_load = False

    def load(self, path: Path):
        name = next(
            key for key, candidate in self.paths.items() if candidate == path
        )
        self.events.append(("load", name, self.lock_depth))
        if name == "updates" and self.slow_updates_load:
            time.sleep(0.04)
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, path: Path, value) -> None:
        assert path == self.paths["updates"]
        self.events.append(("save", "updates", self.lock_depth))
        assert self.lock_depth == 1
        if self.fail_save:
            raise OSError("injected save failure")
        write_literal(path, value)
        self.save_count += 1

    def load_progress(self) -> dict:
        self.events.append(("load_progress", self.lock_depth))
        return json.loads(
            self.paths["progress"].read_text(encoding="utf-8")
        )

    def load_absent(self) -> dict:
        self.events.append(("load_absent", self.lock_depth))
        return json.loads(
            self.paths["absent"].read_text(encoding="utf-8")
        )

    def get_log_repository(self) -> FixtureLogRepository:
        self.events.append(("get_log_repository", self.lock_depth))
        return FixtureLogRepository(self)

    @contextmanager
    def updates_lock(self):
        with self._gate:
            self.lock_depth += 1
            self.max_lock_depth = max(
                self.max_lock_depth,
                self.lock_depth,
            )
            self.events.append(("lock_enter", self.lock_depth))
            try:
                yield
            finally:
                self.events.append(("lock_exit", self.lock_depth))
                self.lock_depth -= 1

    def student_is_registered(
        self,
        _student: dict,
        sid: str,
        date_key: str,
        *,
        extra=None,
    ) -> bool:
        self.events.append(
            ("student_is_registered", sid, date_key, self.lock_depth)
        )
        return sid == SID and date_key == DATE and isinstance(extra, dict)

    def on_auto_pick(self, sid: str, picked: list[str]) -> None:
        self.events.append(
            ("pick", sid, tuple(picked), self.lock_depth)
        )

    def absence_barrier(self):
        return absence_consistency_barrier(
            absent_path=self.paths["absent"],
            journal_dir=self.root / "absence-journal",
            lock_timeout_sec=5.0,
        )

    def dependencies(self) -> StudentAutoAssignmentServiceDependencies:
        return StudentAutoAssignmentServiceDependencies(
            updates_path=self.paths["updates"],
            students_path=self.paths["students"],
            videos_path=self.paths["videos"],
            extra_path=self.paths["extra"],
            watch_path=self.paths["watch"],
            weekend_slots_path=self.paths["weekend"],
            load=self.load,
            load_updates=self.load,
            save_updates=self.save,
            load_progress=self.load_progress,
            load_absent=self.load_absent,
            get_log_repository=self.get_log_repository,
            absence_barrier=self.absence_barrier,
            updates_lock=self.updates_lock,
            today_iso=lambda: DATE,
            student_is_registered=self.student_is_registered,
            on_auto_pick=self.on_auto_pick,
        )


def expected_created_updates() -> dict:
    return {
        "2026-06-05": {
            "other": {
                "videos": ["legacy"],
                "source": "manual",
                "unknown": {"keep": True},
            }
        },
        DATE: {
            SID: {
                "videos": ["m1", "m2"],
                "source": "auto",
            }
        },
    }


def run_today_creation_and_idempotency(runtime: FixtureRuntime) -> None:
    runtime.seed()
    result = load_updates_with_auto_assign(runtime.dependencies())
    assert result == expected_created_updates()
    assert json.loads(
        runtime.paths["updates"].read_text(encoding="utf-8")
    ) == expected_created_updates()
    assert runtime.save_count == 1
    assert runtime.max_lock_depth == 1
    assert runtime.events == [
        ("load", "students", 0),
        ("load", "videos", 0),
        ("load_progress", 0),
        ("load", "watch", 0),
        ("get_log_repository", 0),
        ("read_logs", DATE, 0),
        ("load", "extra", 0),
        ("load_absent", 0),
        ("load", "weekend", 0),
        ("lock_enter", 1),
        ("load", "updates", 1),
        ("student_is_registered", SID, DATE, 1),
        ("pick", SID, ("m1", "m2"), 1),
        ("save", "updates", 1),
        ("lock_exit", 1),
    ]

    before = fingerprint(runtime.paths["updates"])
    runtime.events.clear()
    repeated = load_updates_with_auto_assign(runtime.dependencies())
    assert repeated == expected_created_updates()
    assert fingerprint(runtime.paths["updates"]) == before
    assert runtime.save_count == 1
    assert not any(event[0] in {"pick", "save"} for event in runtime.events)


def run_non_today_storage_only(runtime: FixtureRuntime) -> None:
    runtime.seed()
    before = fingerprint(runtime.paths["updates"])
    dependencies = runtime.dependencies()
    result = load_updates_with_auto_assign(
        dependencies,
        date_key="2026-06-07",
    )
    assert result == {
        "2026-06-05": {
            "other": {
                "videos": ["legacy"],
                "source": "manual",
                "unknown": {"keep": True},
            }
        }
    }
    assert runtime.events == [("load", "updates", 0)]
    assert fingerprint(runtime.paths["updates"]) == before
    assert runtime.save_count == 0


def run_failed_save_invariance(runtime: FixtureRuntime) -> None:
    runtime.seed()
    before_bytes = runtime.paths["updates"].read_bytes()
    before_fingerprint = fingerprint(runtime.paths["updates"])
    runtime.fail_save = True
    try:
        load_updates_with_auto_assign(runtime.dependencies())
    except OSError as exc:
        assert str(exc) == "injected save failure"
    else:
        raise AssertionError("injected assignment save failure was hidden")
    assert runtime.paths["updates"].read_bytes() == before_bytes
    assert fingerprint(runtime.paths["updates"]) == before_fingerprint
    assert runtime.lock_depth == 0
    assert runtime.save_count == 0
    assert ("lock_exit", 1) in runtime.events


def run_unreadable_updates_fail_closed(runtime: FixtureRuntime) -> None:
    runtime.seed()
    broken = b"\xff\xfeBROKEN-UPDATES"
    runtime.paths["updates"].write_bytes(broken)
    before = fingerprint(runtime.paths["updates"])
    dependencies = replace(
        runtime.dependencies(),
        load_updates=load_updates_strict,
    )

    try:
        load_updates_with_auto_assign(dependencies)
    except UpdateAssignmentStoreError as exc:
        assert str(exc).startswith("updates store read failed")
    else:
        raise AssertionError("unreadable updates store did not fail closed")

    assert runtime.paths["updates"].read_bytes() == broken
    assert fingerprint(runtime.paths["updates"]) == before
    assert runtime.save_count == 0
    assert ("lock_exit", 1) in runtime.events


def run_concurrent_creation(runtime: FixtureRuntime) -> None:
    runtime.seed(updates={})
    runtime.slow_updates_load = True
    dependencies = runtime.dependencies()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _index: load_updates_with_auto_assign(dependencies),
                range(2),
            )
        )
    expected = {
        DATE: {
            SID: {
                "videos": ["m1", "m2"],
                "source": "auto",
            }
        }
    }
    assert results == [expected, expected]
    assert json.loads(
        runtime.paths["updates"].read_text(encoding="utf-8")
    ) == expected
    assert runtime.save_count == 1
    assert runtime.max_lock_depth == 1
    assert sum(event[0] == "lock_enter" for event in runtime.events) == 2
    assert sum(event[0] == "save" for event in runtime.events) == 1


def _run_absence_assignment_race(
    runtime: FixtureRuntime,
    *,
    protected: bool,
) -> tuple[dict, dict]:
    runtime.seed(
        updates={
            DATE: {
                SID: {
                    "videos": ["m1"],
                    "source": "auto",
                }
            }
        }
    )
    label = "protected" if protected else "unprotected-control"
    carryover_path = runtime.root / f"makeup_carryover-{label}.json"
    journal_dir = runtime.root / f"absence-journal-race-{label}"
    write_literal(carryover_path, {})

    absence_locked = threading.Event()
    allow_absence_commit = threading.Event()
    service_barrier_attempted = threading.Event()
    stale_absence_loaded = threading.Event()

    def unexpected_repository_factory():
        raise AssertionError("race fixture unexpectedly requested log recovery")

    def commit_absence() -> None:
        with absence_transaction_scope(
            absent_path=runtime.paths["absent"],
            carryover_path=carryover_path,
            updates_path=runtime.paths["updates"],
            progress_path=runtime.paths["progress"],
            log_repository_factory=unexpected_repository_factory,
            journal_dir=journal_dir,
            lock_timeout_sec=5.0,
        ):
            with file_lock(runtime.paths["updates"], timeout_sec=5.0):
                absence_locked.set()
                if not allow_absence_commit.wait(timeout=5.0):
                    raise AssertionError("absence race fixture was not released")

                updates = load_updates_strict(runtime.paths["updates"])
                day = updates.get(DATE)
                if isinstance(day, dict):
                    day.pop(SID, None)
                    if not day:
                        updates.pop(DATE, None)
                save_updates_strict(runtime.paths["updates"], updates)

                absent = json.loads(
                    runtime.paths["absent"].read_text(encoding="utf-8")
                )
                absent.setdefault("by_date", {})[DATE] = [SID]
                absent.setdefault("by_student", {})[SID] = DATE
                absent.setdefault("by_slot", {})[DATE] = {SID: [1]}
                save_atomic(runtime.paths["absent"], absent)

    @contextmanager
    def observed_absence_barrier():
        service_barrier_attempted.set()
        with absence_consistency_barrier(
            absent_path=runtime.paths["absent"],
            journal_dir=journal_dir,
            lock_timeout_sec=5.0,
        ):
            yield

    @contextmanager
    def unprotected_barrier():
        yield

    def observed_load_absent() -> dict:
        absent = runtime.load_absent()
        stale_absence_loaded.set()
        return absent

    dependencies = replace(
        runtime.dependencies(),
        load_updates=load_updates_strict,
        save_updates=save_updates_strict,
        load_absent=observed_load_absent,
        absence_barrier=(
            observed_absence_barrier
            if protected
            else unprotected_barrier
        ),
        updates_lock=lambda: updates_lock(runtime.paths["updates"]),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        absence_future = pool.submit(commit_absence)
        assert absence_locked.wait(timeout=5.0)
        service_future = pool.submit(
            load_updates_with_auto_assign,
            dependencies,
        )
        try:
            if protected:
                assert service_barrier_attempted.wait(timeout=5.0)
                assert not stale_absence_loaded.is_set()
            else:
                assert stale_absence_loaded.wait(timeout=5.0)
            assert not service_future.done()
        finally:
            allow_absence_commit.set()

        absence_future.result(timeout=5.0)
        service_result = service_future.result(timeout=5.0)

    final_updates = json.loads(
        runtime.paths["updates"].read_text(encoding="utf-8")
    )
    assert any(event[0] == "load_absent" for event in runtime.events)
    absent_after = json.loads(
        runtime.paths["absent"].read_text(encoding="utf-8")
    )
    assert SID in absent_after["by_date"][DATE]
    return final_updates, service_result


def run_absence_commit_barrier_serialization(
    runtime: FixtureRuntime,
) -> None:
    control_updates, control_result = _run_absence_assignment_race(
        runtime,
        protected=False,
    )
    assert SID in control_updates.get(DATE, {})
    assert SID in control_result.get(DATE, {})

    protected_updates, protected_result = _run_absence_assignment_race(
        runtime,
        protected=True,
    )
    assert SID not in protected_updates.get(DATE, {})
    assert SID not in protected_result.get(DATE, {})


def run_six_video_cap_for_new_snapshots_only(
    runtime: FixtureRuntime,
) -> None:
    runtime.seed(updates={})
    capped_student = {
        "id": SID,
        "curriculum": "ALG",
        "subCurriculum": "BASE",
        "autoVideoAssignCount": 10,
        "day1": "토1",
    }
    capped_videos = [
        {
            "mid": f"m{index}",
            "chapter": str(index),
            "curriculum": "ALG",
            "subCurriculum": "BASE",
        }
        for index in range(1, 9)
    ]
    write_literal(runtime.paths["students"], [capped_student])
    write_literal(runtime.paths["videos"], capped_videos)

    created = load_updates_with_auto_assign(runtime.dependencies())
    expected_created = {
        DATE: {
            SID: {
                "videos": [f"m{index}" for index in range(1, 7)],
                "source": "auto",
            }
        }
    }
    assert created == expected_created
    assert json.loads(
        runtime.paths["students"].read_text(encoding="utf-8")
    ) == [capped_student]
    assert runtime.save_count == 1

    existing_assignment = {
        "videos": [f"m{index}" for index in range(1, 9)],
        "source": "auto",
        "unknown": {"keep": True},
    }
    runtime.seed(updates={DATE: {SID: existing_assignment}})
    write_literal(runtime.paths["students"], [capped_student])
    write_literal(runtime.paths["videos"], capped_videos)
    before_bytes = runtime.paths["updates"].read_bytes()
    before_fingerprint = fingerprint(runtime.paths["updates"])

    unchanged = load_updates_with_auto_assign(runtime.dependencies())
    assert unchanged == {DATE: {SID: existing_assignment}}
    assert runtime.paths["updates"].read_bytes() == before_bytes
    assert fingerprint(runtime.paths["updates"]) == before_fingerprint
    assert runtime.save_count == 0


def run_future_history_is_ignored(runtime: FixtureRuntime) -> None:
    runtime.seed(updates={})
    write_literal(
        runtime.paths["progress"],
        {"2026-06-07": {SID: {"m1": "done"}}},
    )
    write_literal(
        runtime.paths["watch"],
        {"2026-06-08": {SID: {"m2": {"completed": True}}}},
    )

    result = load_updates_with_auto_assign(runtime.dependencies())
    assert result == {
        DATE: {
            SID: {
                "videos": ["m1", "m2"],
                "source": "auto",
            }
        }
    }
    assert runtime.save_count == 1


def run_future_auto_cleanup(runtime: FixtureRuntime) -> None:
    today_manual = {
        "videos": ["m1"],
        "source": "manual",
        "unknown": {"keep": True},
    }
    runtime.seed(
        updates={
            DATE: {SID: today_manual},
            "2026-06-07": {
                "future-auto": {
                    "videos": ["m2"],
                    "source": "auto",
                },
                "future-manual": {
                    "videos": ["m2"],
                    "source": "manual",
                },
                "future-self-study": {
                    "videos": ["m1"],
                    "source": "selfStudy",
                },
                "future-legacy": ["m2"],
                "future-other": {
                    "videos": ["m2"],
                    "source": "migration",
                },
            },
            "2026-06-08": {
                "future-auto-only": {
                    "videos": ["m1"],
                    "source": "auto",
                },
            },
        }
    )
    expected = {
        DATE: {SID: today_manual},
        "2026-06-07": {
            "future-manual": {
                "videos": ["m2"],
                "source": "manual",
            },
            "future-self-study": {
                "videos": ["m1"],
                "source": "selfStudy",
            },
            "future-legacy": ["m2"],
            "future-other": {
                "videos": ["m2"],
                "source": "migration",
            },
        },
    }

    result = load_updates_with_auto_assign(runtime.dependencies())
    assert result == expected
    assert json.loads(
        runtime.paths["updates"].read_text(encoding="utf-8")
    ) == expected
    assert runtime.save_count == 1


def run_self_study_reconcile(runtime: FixtureRuntime) -> None:
    runtime.seed(
        updates={
            DATE: {
                SID: {
                    "videos": ["m3"],
                    "source": "auto",
                }
            }
        }
    )
    runtime.logs = {DATE: {SID: {"selfStudy": True}}}
    write_literal(
        runtime.paths["progress"],
        {
            "2026-06-05": {
                SID: {
                    "m1": "done",
                    "m2": "interrupted",
                }
            }
        },
    )
    payload, status = reconcile_self_study_assignment(
        runtime.dependencies(),
        date=DATE,
        sid=SID,
        has_requested_videos=False,
        requested_videos=[],
        append_requested_videos=False,
    )
    expected_assignment = {
        "videos": ["m1"],
        "source": "selfStudy",
    }
    assert status == 200
    assert payload == {"ok": True, "assignment": expected_assignment}
    assert json.loads(
        runtime.paths["updates"].read_text(encoding="utf-8")
    ) == {DATE: {SID: expected_assignment}}
    assert runtime.save_count == 1

    before = fingerprint(runtime.paths["updates"])
    runtime.events.clear()
    rejected, rejected_status = reconcile_self_study_assignment(
        runtime.dependencies(),
        date=DATE,
        sid=SID,
        has_requested_videos=True,
        requested_videos=["m2"],
        append_requested_videos=True,
    )
    assert rejected_status == 409
    assert rejected == {
        "ok": False,
        "error": "video is not eligible for self-study review",
        "invalidVideos": ["m2"],
    }
    assert fingerprint(runtime.paths["updates"]) == before
    assert not any(event[0] in {"lock_enter", "save"} for event in runtime.events)


def main() -> int:
    source = (
        ROOT / "routes/student_auto_assignment_service.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "from flask",
        "import flask",
        "core.paths",
        "routes.api_basic",
    ):
        assert forbidden not in source, (
            f"auto-assignment service imported runtime owner: {forbidden}"
        )

    api_basic_path = ROOT / "routes/api_basic.py"
    api_tree = ast.parse(
        api_basic_path.read_text(encoding="utf-8"),
        filename=str(api_basic_path),
    )
    wrappers = {
        node.name: node
        for node in api_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        in {
            "_ensure_today_auto_assign",
            "_load_updates_with_auto_assign",
            "reconcile_self_study_assignment_for_updates",
        }
    }
    assert set(wrappers) == {
        "_ensure_today_auto_assign",
        "_load_updates_with_auto_assign",
        "reconcile_self_study_assignment_for_updates",
    }
    expected_calls = {
        "_ensure_today_auto_assign": "_service_ensure_today_auto_assign",
        "_load_updates_with_auto_assign": (
            "_service_load_updates_with_auto_assign"
        ),
        "reconcile_self_study_assignment_for_updates": (
            "_service_reconcile_self_study_assignment"
        ),
    }
    for wrapper_name, service_call in expected_calls.items():
        wrapper = wrappers[wrapper_name]
        referenced_names = {
            node.id
            for node in ast.walk(wrapper)
            if isinstance(node, ast.Name)
        }
        assert service_call in referenced_names
        assert not {
            "load",
            "save_atomic",
            "_updates_lock",
        }.intersection(referenced_names), (
            f"{wrapper_name} still owns runtime storage orchestration"
        )

    with tempfile.TemporaryDirectory(
        prefix="student-auto-assignment-service-"
    ) as temp_dir:
        runtime = FixtureRuntime(Path(temp_dir))
        run_today_creation_and_idempotency(runtime)
        run_non_today_storage_only(runtime)
        run_failed_save_invariance(runtime)
        run_unreadable_updates_fail_closed(runtime)
        run_concurrent_creation(runtime)
        run_absence_commit_barrier_serialization(runtime)
        run_six_video_cap_for_new_snapshots_only(runtime)
        run_future_history_is_ignored(runtime)
        run_future_auto_cleanup(runtime)
        run_self_study_reconcile(runtime)

    print(
        "student auto-assignment service passed: literal temp-store result, "
        "lock ordering, idempotency, failed-save and unreadable-store hash "
        "invariance, concurrent single commit, absence-race control/barrier, and "
        "six-video new-snapshot cap, existing-snapshot "
        "invariance, future-history cutoff, future-auto cleanup, and self-study "
        "no-write rejection"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
