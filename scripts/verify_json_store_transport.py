"""Exercise the actual JSON store transport and native leases in OS temp only."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


parser = argparse.ArgumentParser()
parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
args, unittest_args = parser.parse_known_args()
sys.path.insert(0, str(Path(args.repo_root)))

runtime = tempfile.TemporaryDirectory(prefix="json-store-draft-")
RUNTIME = Path(runtime.name).resolve()
TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
assert RUNTIME.is_relative_to(TEMP_PARENT) and RUNTIME != TEMP_PARENT
IO_WRITES: list[str] = []


def _temp_path(value) -> Path | None:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None
    return Path(os.path.abspath(os.fsdecode(value)))


def audit(event, arguments):
    if event == "open":
        path = _temp_path(arguments[0])
        if path is None:
            return
        mode, flags = arguments[1], arguments[2] or 0
        writing = (isinstance(mode, str) and any(value in mode for value in "wax+")) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        if writing:
            if not path.is_relative_to(RUNTIME):
                raise AssertionError(f"non-temp write: {path}")
            IO_WRITES.append(str(path.relative_to(RUNTIME)))
        elif path.suffix in {".json", ".sqlite", ".db", ".lock", ".tmp"} and not path.is_relative_to(RUNTIME):
            raise AssertionError(f"non-temp runtime read: {path}")
    elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.utime", "os.chmod"}:
        path = _temp_path(arguments[0])
        if path is not None and not path.is_relative_to(RUNTIME):
            raise AssertionError(f"non-temp mutation: {path}")
    elif event == "os.rename":
        for value in arguments[:2]:
            path = _temp_path(value)
            if path is not None and not path.is_relative_to(RUNTIME):
                raise AssertionError(f"non-temp rename: {path}")
    elif event in {"socket.connect", "socket.bind"}:
        raise AssertionError("network use forbidden")
    elif event == "import" and arguments[0] in {"app", "core.paths"}:
        raise AssertionError("app/runtime-path import forbidden")


sys.addaudithook(audit)
module_path = Path(args.repo_root) / "core" / "json_store.py"
spec = importlib.util.spec_from_file_location("json_store_p4_draft", module_path)
draft = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = draft
spec.loader.exec_module(draft)
from core import storage


def validate_object(value):
    if not isinstance(value, dict):
        raise ValueError("object required")


def fingerprint(path):
    raw = path.read_bytes()
    stat = path.stat()
    return raw, stat.st_mtime_ns, stat.st_size, hashlib.sha256(raw).hexdigest()


def literal_revision(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class JsonStoreTransportContracts(unittest.TestCase):
    def test_data_seams_skip_unused_hashing_without_exposing_mutable_cached_values(self):
        self.seed({"unknown": {"value": "한글"}, "count": 1})
        store = draft.JsonStore(self.path, dict, validate=dict, mirror=False)
        store.read()
        with patch.object(draft, "semantic_revision", side_effect=AssertionError("unused content hash")), patch.object(draft, "file_lock", side_effect=AssertionError("owner lease cannot be reacquired")):
            data = store.read_data_locked()
            data["unknown"]["value"] = "edited"
            self.assertEqual(store.read_data_locked(), {"unknown": {"value": "한글"}, "count": 1})
            store.write_data_locked(data)
            data["unknown"]["value"] = "after commit"
            self.assertEqual(store.read_data_locked(), {"unknown": {"value": "edited"}, "count": 1})
        self.assertEqual(store.read()[0], {"unknown": {"value": "edited"}, "count": 1})
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            store.write_data_locked([])
        self.assertEqual(self.path.read_bytes(), before)
        with patch.object(Path, "read_bytes", side_effect=PermissionError("warm private read denied")):
            with self.assertRaises(draft.StoreCorrupt):
                store.read_data_locked()
        self.assertEqual(self.path.read_bytes(), before)

    def test_relative_store_path_is_frozen_before_cwd_changes(self):
        from core.stores import get_store
        first, second = RUNTIME / "cwd-first", RUNTIME / "cwd-second"
        first.mkdir()
        second.mkdir()
        (first / "extra.json").write_text('{"owner":"first"}', "utf-8")
        (second / "extra.json").write_text('{"owner":"second"}', "utf-8")
        previous = Path.cwd()
        try:
            os.chdir(first)
            direct = draft.JsonStore("extra.json", dict, mirror=False)
            registered = get_store("extra", "extra.json")
            os.chdir(second)
            self.assertEqual(direct.read()[0], {"owner": "first"})
            self.assertEqual(registered.read()[0], {"owner": "first"})
            self.assertEqual(get_store("extra", "extra.json").read()[0], {"owner": "second"})
        finally:
            os.chdir(previous)

    @unittest.skipUnless(os.name == "nt", "Windows O_EXCL deletion conflict")
    def test_windows_lock_permission_retry_is_bounded_and_never_breaks_an_owner(self):
        from core import storage
        original = os.open
        target = str(self.path) + ".lock"
        failures = [0]

        def transient(path, *args, **kwargs):
            if os.fspath(path) == target and failures[0] < 2:
                failures[0] += 1
                raise PermissionError("synthetic delete-pending conflict")
            return original(path, *args, **kwargs)

        lease = storage.file_lock(self.path, timeout_sec=.2, poll_sec=.001)
        with patch.object(os, "open", transient), patch.object(lease, "_try_break_stale_lock", side_effect=AssertionError("permission retry cannot break locks")):
            with lease:
                self.assertTrue(Path(target).exists())
        self.assertEqual(failures[0], 2)
        self.assertFalse(Path(target).exists())

        calls = [0]
        def denied(path, *args, **kwargs):
            if os.fspath(path) == target:
                calls[0] += 1
                raise PermissionError("synthetic real ACL denial")
            return original(path, *args, **kwargs)

        lease = storage.file_lock(self.path, timeout_sec=.2, poll_sec=.001)
        with patch.object(os, "open", denied), patch.object(lease, "_try_break_stale_lock", side_effect=AssertionError("ACL denial cannot break locks")):
            with self.assertRaisesRegex(PermissionError, "real ACL denial"):
                lease.acquire()
        self.assertEqual(calls[0], 4)
        self.assertFalse(Path(target).exists())

    def test_registry_is_lazy_bounded_and_preserves_required_identity_failures(self):
        from core.stores import get_store, invalidate_stores
        from core.json_store import StoreCorrupt
        folder = RUNTIME / "registry"
        folder.mkdir()
        progress = get_store("progress", folder / "progress.json")
        self.assertIs(progress, get_store("progress", folder / "progress.json"))
        self.assertEqual(progress.read()[0], {})
        self.assertEqual(list(folder.iterdir()), [])
        for name in ("students", "persons", "videos"):
            with self.assertRaises(StoreCorrupt):
                get_store(name, folder / (name + ".json")).read()
        self.assertEqual(list(folder.iterdir()), [])
        progress.write_locked({"2026-10-13": {"s1": {"v1": "done"}}}, mirror=False)
        returned = progress.read()[0]
        returned["2026-10-13"]["s1"]["v1"] = "skip"
        self.assertEqual(progress.read()[0], {"2026-10-13": {"s1": {"v1": "done"}}})
        before = progress.revision()
        for index in range(70):
            get_store("extra", folder / f"extra-{index}.json").read()
        self.assertEqual(get_store("progress", progress.path).revision(), before)
        invalidate_stores("progress")
        self.assertEqual(progress.read()[0], {"2026-10-13": {"s1": {"v1": "done"}}})

    def setUp(self):
        self.root = RUNTIME / self._testMethodName
        self.root.mkdir()
        self.path = self.root / "state.json"
        self.store = draft.JsonStore(self.path, dict, validate_object, mirror=False)
        environment = patch.dict(os.environ, {
            "DATA_MIRROR_DIR": str(self.root / "mirror"),
            "DATA_MIRROR_SNAPSHOTS": "0",
            "DATA_MIRROR_SYNC": "1",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def seed(self, value):
        self.path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_constructor_and_missing_read_never_create_defaults(self):
        factory_calls = []
        initial = {"unknown": {"keep": True}}
        def factory():
            factory_calls.append(True)
            return initial
        with patch.object(Path, "stat", side_effect=AssertionError("constructor stat")), patch.object(Path, "read_bytes", side_effect=AssertionError("constructor read")), patch.object(draft, "save_atomic", side_effect=AssertionError("constructor save")), patch.object(draft, "file_lock", side_effect=AssertionError("constructor lock")):
            store = draft.JsonStore(self.path, factory, validate_object, mirror=False)
        self.assertEqual(factory_calls, [])
        value, revision = store.read()
        self.assertEqual(value, initial)
        self.assertEqual(revision, literal_revision('{"unknown":{"keep":true}}'))
        value["unknown"]["keep"] = False
        self.assertEqual(store.read()[0], initial)
        self.assertEqual(initial, {"unknown": {"keep": True}})
        self.assertEqual(len(factory_calls), 1)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.with_suffix(".json.lock").exists())

    def test_bom_whitespace_key_order_and_semantic_revision(self):
        self.path.write_text('\ufeff{ "z": 3, "unknown": {"학생":"값"} }', encoding="utf-8")
        value, revision = self.store.read()
        self.assertEqual(value, {"z": 3, "unknown": {"학생": "값"}})
        self.assertEqual(revision, literal_revision('{"unknown":{"학생":"값"},"z":3}'))
        raw = self.path.read_bytes()
        self.path.write_text('{"unknown":{"학생":"값"},"z":3}', encoding="utf-8")
        self.assertNotEqual(self.path.read_bytes(), raw)
        self.assertEqual(self.store.revision(), revision)

    def test_defensive_reads_mutation_results_and_validator_inputs(self):
        self.seed({"known": 1, "unknown": {"nested": ["keep"]}})
        def validator(value):
            validate_object(value)
            value["validatorSideEffect"] = "must not persist"
        store = draft.JsonStore(self.path, dict, validator, mirror=False)
        read, _ = store.read()
        read["unknown"]["nested"].append("caller")
        self.assertEqual(store.read()[0], {"known": 1, "unknown": {"nested": ["keep"]}})
        result, revision = store.update(lambda current: current.update(known=2))
        self.assertEqual(revision, literal_revision('{"known":2,"unknown":{"nested":["keep"]}}'))
        result["unknown"]["nested"].append("result")
        self.assertEqual(store.read()[0], {"known": 2, "unknown": {"nested": ["keep"]}})
        self.assertNotIn("validatorSideEffect", json.loads(self.path.read_text("utf-8")))

    def test_revision_cache_does_not_reparse_an_unchanged_file(self):
        self.seed({"known": 1})
        original = Path.read_bytes
        calls = []
        def counted(path):
            if path == self.path:
                calls.append(True)
            return original(path)
        with patch.object(Path, "read_bytes", counted):
            self.assertEqual(self.store.read()[0], {"known": 1})
            for _ in range(4):
                self.assertEqual(self.store.revision(), literal_revision('{"known":1}'))
            self.assertEqual(self.store.read()[0], {"known": 1})
        self.assertEqual(len(calls), 1)

    def test_atomic_external_replace_with_preserved_mtime_refreshes_cache(self):
        self.seed({"known": "A"})
        self.assertEqual(self.store.read()[0], {"known": "A"})
        before = self.path.stat()
        other = self.root / "foreign.tmp"
        other.write_bytes(b'{"known": "B"}')
        os.utime(other, ns=(before.st_atime_ns, before.st_mtime_ns))
        other.replace(self.path)
        self.assertEqual(self.path.stat().st_size, before.st_size)
        self.assertEqual(self.path.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(self.store.read()[0], {"known": "B"})
        self.assertEqual(self.store.revision(), literal_revision('{"known":"B"}'))

    def test_external_change_during_read_retries_before_publishing_cache(self):
        self.seed({"known": "A"})
        original = Path.read_bytes
        reads = []
        def changed_after_read(path):
            raw = original(path)
            if path == self.path:
                reads.append(True)
                if len(reads) == 1:
                    other = self.root / "foreign.tmp"
                    other.write_bytes(b'{"known":"B"}')
                    other.replace(self.path)
            return raw
        with patch.object(Path, "read_bytes", changed_after_read):
            self.assertEqual(self.store.read(), ({"known": "B"}, literal_revision('{"known":"B"}')))
            self.assertEqual(self.store.read()[0], {"known": "B"})
        self.assertEqual(len(reads), 2)

    def test_unstable_reads_fail_busy_instead_of_caching_a_mixed_snapshot(self):
        self.seed({"version": 0})
        original = Path.read_bytes
        reads = []
        def always_changed(path):
            raw = original(path)
            if path == self.path:
                reads.append(True)
                other = self.root / "foreign.tmp"
                other.write_text(json.dumps({"version": len(reads)}), encoding="utf-8")
                other.replace(self.path)
            return raw
        with patch.object(Path, "read_bytes", always_changed):
            with self.assertRaises(draft.StoreBusy):
                self.store.read()
        self.assertEqual(len(reads), 3)
        self.assertEqual(self.store.read()[0], {"version": 3})

    def test_read_failure_cannot_become_missing_default_or_erase_storage(self):
        self.seed({"unknown": "keep"})
        for error in (PermissionError("fixture denied"), OSError("fixture unreadable")):
            self.store.invalidate()
            before = fingerprint(self.path)
            original = Path.read_bytes
            def denied(path):
                if path == self.path:
                    raise error
                return original(path)
            with patch.object(Path, "read_bytes", denied):
                with self.assertRaises(draft.StoreCorrupt):
                    self.store.read()
                with self.assertRaises(draft.StoreCorrupt):
                    self.store.update(lambda current: current.update(changed=True))
            self.assertEqual(fingerprint(self.path), before)

    def test_stat_failure_invalidates_cached_state_and_fails_closed(self):
        self.seed({"unknown": "keep"})
        self.store.read()
        before = fingerprint(self.path)
        original = Path.stat
        def denied(path, *args, **kwargs):
            if path == self.path:
                raise PermissionError("fixture stat denied")
            return original(path, *args, **kwargs)
        with patch.object(Path, "stat", denied):
            with self.assertRaises(draft.StoreCorrupt):
                self.store.read()
        self.assertEqual(fingerprint(self.path), before)

    def test_transient_missing_read_with_existing_metadata_is_not_an_empty_store(self):
        self.seed({"unknown": "keep"})
        before = fingerprint(self.path)
        original = Path.read_bytes
        def gone(path):
            if path == self.path:
                raise FileNotFoundError("fixture lookup race")
            return original(path)
        with patch.object(Path, "read_bytes", gone):
            with self.assertRaises(draft.StoreBusy):
                self.store.read()
        self.assertEqual(fingerprint(self.path), before)

    def test_invalid_json_encoding_and_stored_shape_never_default(self):
        for raw in (b'{"truncated":', b'\xff', b'[]', b'null'):
            self.path.write_bytes(raw)
            self.store.invalidate()
            before = fingerprint(self.path)
            with self.assertRaises(draft.StoreCorrupt):
                self.store.read()
            with self.assertRaises(draft.StoreCorrupt):
                self.store.replace({"replacement": True})
            self.assertEqual(fingerprint(self.path), before)

    def test_invalid_mutation_and_callback_failure_preserve_bytes_mtime_unknown_fields(self):
        initial = {"unknown": {"keep": [1]}}
        self.seed(initial)
        before = fingerprint(self.path)
        with self.assertRaises(ValueError):
            self.store.update(lambda _current: [])
        self.assertEqual(fingerprint(self.path), before)
        def fail(current):
            current["unknown"]["keep"].append(2)
            raise TimeoutError("domain callback failed")
        with self.assertRaises(TimeoutError) as caught:
            self.store.update(fail)
        self.assertNotIsInstance(caught.exception, draft.StoreBusy)
        self.assertEqual(fingerprint(self.path), before)
        self.assertEqual(self.store.read()[0], initial)
        self.assertFalse(Path(str(self.path) + ".lock").exists())

    def test_stale_revision_fails_before_mutator_and_before_any_save(self):
        self.seed({"version": 1})
        revision = self.store.read()[1]
        self.store.replace({"version": 2})
        before = fingerprint(self.path)
        calls = []
        with self.assertRaises(draft.RevisionConflict) as conflict:
            self.store.update(lambda value: calls.append(value), expected_revision=revision)
        self.assertEqual(conflict.exception.current_revision, literal_revision('{"version":2}'))
        self.assertEqual(calls, [])
        with self.assertRaises(draft.RevisionConflict):
            self.store.replace({"version": 3}, expected_revision=revision)
        self.assertEqual(fingerprint(self.path), before)

    def test_locked_seams_do_not_reacquire_a_native_lease(self):
        self.seed({"unknown": "keep"})
        with storage.file_lock(self.path):
            with patch.object(draft, "file_lock", side_effect=AssertionError("nested lease")):
                current, revision = self.store.read_locked()
                current["changed"] = True
                saved = self.store.write_locked(current, expected_revision=revision)
            self.assertTrue(Path(str(self.path) + ".lock").exists())
        self.assertEqual(saved, literal_revision('{"changed":true,"unknown":"keep"}'))
        self.assertEqual(self.store.read()[0], {"unknown": "keep", "changed": True})
        self.assertFalse(Path(str(self.path) + ".lock").exists())

    def test_busy_native_lease_does_not_break_a_live_owner(self):
        self.seed({"unknown": "keep"})
        before = fingerprint(self.path)
        with storage.file_lock(self.path):
            lock_path = Path(str(self.path) + ".lock")
            original_lock = lock_path.read_bytes()
            os.utime(lock_path, (1, 1))
            with self.assertRaises(draft.StoreBusy):
                self.store.update(lambda value: value.update(changed=True), timeout_sec=0.02)
            self.assertEqual(lock_path.read_bytes(), original_lock)
        self.assertEqual(fingerprint(self.path), before)

    def test_independent_instances_merge_simultaneous_updates_under_real_file_lease(self):
        self.seed({"unknown": {"keep": True}})
        workers = 8
        start = threading.Barrier(workers)
        def write(index):
            store = draft.JsonStore(self.path, dict, validate_object, mirror=False)
            store.read()
            start.wait(timeout=5)
            store.update(lambda value: value.update({str(index): index}), timeout_sec=5)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(write, range(workers)))
        expected = {"unknown": {"keep": True}, **{str(index): index for index in range(workers)}}
        self.assertEqual(self.store.read()[0], expected)
        self.assertEqual(json.loads(self.path.read_text("utf-8")), expected)

    def test_post_commit_external_write_is_not_stamped_with_our_cached_payload(self):
        self.seed({"version": "old"})
        self.store.read()
        actual_save = draft.save_atomic
        def committed_then_replaced(path, data, **kwargs):
            actual_save(path, data, **kwargs)
            path.write_text('{"version":"external"}', encoding="utf-8")
        with patch.object(draft, "save_atomic", committed_then_replaced):
            revision = self.store.replace({"version": "ours"})
        self.assertEqual(revision, literal_revision('{"version":"ours"}'))
        self.assertEqual(self.store.read(), ({"version": "external"}, literal_revision('{"version":"external"}')))

    def test_shared_mutator_result_cannot_change_the_saved_response_snapshot(self):
        self.seed({"version": "old"})
        shared = {"version": "committed", "unknown": ["keep"]}
        actual_save = draft.save_atomic
        def changed_after_commit(path, data, **kwargs):
            actual_save(path, data, **kwargs)
            shared["version"] = "external"
            shared["unknown"].append("caller")
        with patch.object(draft, "save_atomic", changed_after_commit):
            value, revision = self.store.update(lambda _current: shared)
        self.assertEqual(value, {"version": "committed", "unknown": ["keep"]})
        self.assertEqual(revision, literal_revision('{"unknown":["keep"],"version":"committed"}'))
        self.assertEqual(self.store.read()[0], value)

    def test_uncertain_save_failure_does_not_leave_a_pre_commit_cache(self):
        self.seed({"version": "old"})
        self.store.read()
        actual_save = draft.save_atomic
        def uncertain(path, data, **kwargs):
            actual_save(path, data, **kwargs)
            raise OSError("fixture error after replace")
        with patch.object(draft, "save_atomic", uncertain):
            with self.assertRaises(OSError):
                self.store.replace({"version": "committed"})
        self.assertEqual(self.store.read()[0], {"version": "committed"})

    def test_bool_mirror_and_compact_options_use_current_atomic_writer(self):
        store = draft.JsonStore(self.path, dict, validate_object, compact=True, mirror=True)
        store.replace({"학생": "값"}, mirror=False)
        self.assertFalse((self.root / "mirror").exists())
        self.assertEqual(self.path.read_bytes(), '{"학생":"값"}'.encode("utf-8"))
        store.replace({"학생": "새값"}, mirror=True)
        self.assertEqual((self.root / "mirror" / self.path.name).read_bytes(), self.path.read_bytes())
        before = fingerprint(self.path)
        with self.assertRaises(TypeError):
            store.replace({"changed": True}, mirror="async")
        self.assertEqual(fingerprint(self.path), before)

    def test_mirror_io_failure_still_leaves_a_successful_primary_commit(self):
        self.seed({"unknown": "keep"})
        with patch.object(storage, "_atomic_mirror_bytes", side_effect=OSError("fixture mirror denied")):
            revision = self.store.replace({"unknown": "keep", "changed": True}, mirror=True)
        self.assertEqual(revision, literal_revision('{"changed":true,"unknown":"keep"}'))
        self.assertEqual(self.store.read()[0], {"unknown": "keep", "changed": True})

    def test_explicit_invalidation_and_locked_reads_observe_recovery_writes(self):
        self.seed({"version": "old"})
        self.store.read()
        self.path.write_text('{"version":"restored"}', encoding="utf-8")
        self.store.invalidate()
        self.assertEqual(self.store.read()[0], {"version": "restored"})
        with storage.file_lock(self.path):
            self.assertEqual(self.store.read_locked()[0], {"version": "restored"})

    def test_nullable_json_replace_does_not_mean_mutator_noop(self):
        self.seed({"version": "old"})
        store = draft.JsonStore(self.path, dict, mirror=False)
        self.assertEqual(store.replace(None), literal_revision("null"))
        self.assertEqual(self.path.read_bytes(), b"null")
        self.assertEqual(store.read(), (None, literal_revision("null")))

    def test_draft_does_not_import_runtime_app_or_paths(self):
        self.assertNotIn("app", sys.modules)
        self.assertNotIn("core.paths", sys.modules)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    try:
        program = unittest.main(argv=[sys.argv[0], *unittest_args], verbosity=2, exit=False)
        print(f"temp-only IO guard: {len(IO_WRITES)} allowed writes; no app/paths/network")
        outcome = 0 if program.result.wasSuccessful() else 1
    finally:
        # Verify the exact absolute target before TemporaryDirectory's removal.
        assert RUNTIME.resolve().is_relative_to(TEMP_PARENT) and RUNTIME.resolve() != TEMP_PARENT
        runtime.cleanup()
    raise SystemExit(outcome)
