"""Actual storage/queue modules, only OS-temp synthetic JSON and threads."""
from pathlib import Path
import argparse
import importlib.util
import json
import os
import multiprocessing
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--source-root', '--draft-root', dest='draft_root', default=str(Path(__file__).resolve().parents[1]))
parser.add_argument('--sync-child')
args, test_args = parser.parse_known_args()
root = Path(args.draft_root).resolve()
sys.path.insert(0, str(root))
sys.dont_write_bytecode = True
queue_path = root / 'core/mirror_queue.py'
storage_path = root / 'core/storage.py'
from core import mirror_queue as queue_module


def load_storage():
    spec = importlib.util.spec_from_file_location('_verify_mirror_storage', storage_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sync_child(child_directory):
    child_root = Path(child_directory).resolve()
    assert child_root.name.startswith('p4-mirror-fixture-')
    assert Path(tempfile.gettempdir()).resolve() in child_root.parents
    os.environ.update(DATA_MIRROR_DIR=str(child_root / 'mirror'), DATA_MIRROR_SYNC='1', DATA_MIRROR_SNAPSHOTS='0')
    child_storage = load_storage()
    child_storage.save_atomic(child_root / 'fixture.json', {'version': 'cross-process sync wins'})
    assert child_storage.shutdown_mirrors(1)
    assert json.loads((child_root / 'mirror/fixture.json').read_text('utf-8')) == {'version': 'cross-process sync wins'}


def held_destination_child(child_directory, entered, release):
    child_root = Path(child_directory).resolve()
    assert child_root.name.startswith('p4-mirror-fixture-')
    assert Path(tempfile.gettempdir()).resolve() in child_root.parents
    child_storage = load_storage()
    with child_storage.file_lock(child_root / 'mirror/fixture.json', timeout_sec=1):
        entered.set()
        if not release.wait(4):
            raise AssertionError('OS-temp destination lease was not released')


if args.sync_child:
    sync_child(args.sync_child)
    raise SystemExit(0)


class AsyncMirrorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='p4-mirror-fixture-')
        self.base = Path(self.temporary.name).resolve()
        self.storage = load_storage()
        self.releases = []
        self.atexit_calls = []
        self.env = patch.dict(os.environ, {
            'DATA_MIRROR_DIR': str(self.base / 'mirror'), 'DATA_MIRROR_SYNC': '',
            'DATA_MIRROR_SNAPSHOTS': '0', 'DATA_MIRROR_SNAPSHOT_MIN_SEC': '0',
            'DATA_MIRROR_MAX_SNAPS_PER_FILE': '96',
        })
        self.env.start()
        self.registration = patch.object(self.storage.atexit, 'register', side_effect=self.atexit_calls.append)
        self.registration.start()
        self.original_write_bytes = Path.write_bytes
        self.original_write_text = Path.write_text
        self.original_replace = os.replace

        def checked(path):
            resolved = Path(path).resolve()
            if self.base != resolved and self.base not in resolved.parents:
                raise AssertionError('fixture write escaped OS-temp root: ' + str(resolved))

        def write_bytes(path, data):
            checked(path)
            return self.original_write_bytes(path, data)

        def write_text(path, *values, **keywords):
            checked(path)
            return self.original_write_text(path, *values, **keywords)

        def replace(src, dest):
            checked(src)
            checked(dest)
            return self.original_replace(src, dest)

        self.write_bytes_patch = patch.object(Path, 'write_bytes', write_bytes)
        self.write_text_patch = patch.object(Path, 'write_text', write_text)
        self.replace_patch = patch.object(os, 'replace', replace)
        self.write_bytes_patch.start()
        self.write_text_patch.start()
        self.replace_patch.start()

    def tearDown(self):
        for event in self.releases:
            event.set()
        if not self.storage.shutdown_mirrors(2.0):
            raise AssertionError('fixture worker must stop before OS-temp cleanup')
        self.replace_patch.stop()
        self.write_text_patch.stop()
        self.write_bytes_patch.stop()
        self.registration.stop()
        self.env.stop()
        self.temporary.cleanup()

    def source(self, name='fixture.json'):
        return self.base / name

    def mirrored(self, name='fixture.json', directory='mirror'):
        return self.base / directory / name

    def block_worker(self, name='fixture.json'):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = self.storage._write_mirror_job
        calls = []

        def writer(job):
            calls.append(job)
            if Path(job.source).name == name and not entered.is_set():
                entered.set()
                if not release.wait(3.0):
                    raise AssertionError('fixture block was not released')
            original(job)

        adapter = patch.object(self.storage, '_write_mirror_job', side_effect=writer)
        adapter.start()
        self.addCleanup(adapter.stop)
        return entered, release, calls

    def test_primary_ack_bytes_coalescing_dirty_replay_and_mirror_false_privacy(self):
        path = self.source()
        entered, release, calls = self.block_worker()
        first = {'한글': '첫째', 'nested': {'x': [1, 2]}}
        self.storage.save_atomic(path, first)
        self.assertTrue(entered.wait(1))
        self.assertEqual(json.loads(path.read_text('utf-8')), first)
        for version in ['둘째', '셋째', '마지막 공개']:
            start = time.monotonic()
            self.storage.save_atomic(path, {'한글': version})
            self.assertLess(time.monotonic() - start, .5, 'blocked worker must not hold primary acknowledgement')
        approved = path.read_bytes()
        self.storage.save_atomic(path, {'privateAuth': 'SYNTHETIC-DO-NOT-MIRROR'}, mirror=False)
        release.set()
        self.assertTrue(self.storage.drain_mirrors(1))
        self.assertEqual(self.mirrored().read_bytes(), approved)
        self.assertEqual(len(calls), 2, 'one in-flight job plus one coalesced dirty replay')
        self.assertNotIn(b'SYNTHETIC-DO-NOT-MIRROR', b''.join(job.data for job in calls))
        self.assertEqual(self.storage._MIRROR_QUEUE.status()['worker_starts'], 1)
        self.assertTrue(self.storage._MIRROR_QUEUE.status()['daemon'])
        self.assertEqual(self.storage._MIRROR_QUEUE.status()['lanes'], 0)

    def test_windows_newline_and_compact_byte_parity(self):
        for compact in [False, True]:
            value = {'학생': '가나다', 'rows': [1, 2], 'literal': '한줄\n둘째'}
            reference = self.source('reference.json')
            serialized = json.dumps(value, ensure_ascii=False, separators=(',', ':')) if compact else json.dumps(value, ensure_ascii=False, indent=2)
            reference.write_text(serialized, 'utf-8')
            self.storage.save_atomic(self.source(), value, compact=compact)
            self.assertTrue(self.storage.drain_mirrors(1))
            self.assertEqual(self.source().read_bytes(), reference.read_bytes())
            self.assertEqual(self.mirrored().read_bytes(), reference.read_bytes())
            if os.name == 'nt' and not compact:
                self.assertIn(b'\r\n', self.mirrored().read_bytes())

    def test_destination_and_snapshot_policy_are_captured(self):
        entered, release, _calls = self.block_worker('block.json')
        self.storage.save_atomic(self.source('block.json'), {'blocking': True})
        self.assertTrue(entered.wait(1))
        os.environ.update(DATA_MIRROR_DIR=str(self.base / 'first'), DATA_MIRROR_SNAPSHOTS='1')
        self.storage.save_atomic(self.source(), {'version': 'first'})
        first = self.source().read_bytes()
        os.environ.update(DATA_MIRROR_DIR=str(self.base / 'second'), DATA_MIRROR_SNAPSHOTS='0')
        self.storage.save_atomic(self.source(), {'version': 'second'})
        second = self.source().read_bytes()
        os.environ.update(DATA_MIRROR_DIR=str(self.base / 'third'), DATA_MIRROR_SNAPSHOTS='1')
        release.set()
        self.assertTrue(self.storage.drain_mirrors(1))
        self.assertEqual(self.mirrored(directory='first').read_bytes(), first)
        self.assertEqual(self.mirrored(directory='second').read_bytes(), second)
        self.assertEqual(len(list((self.base / 'first/_snapshots/fixture').glob('*.json'))), 1)
        self.assertEqual(len(list((self.base / 'second/_snapshots/fixture').glob('*.json'))), 0)
        self.assertFalse((self.base / 'third').exists())

    def test_sync_overtakes_older_queued_job(self):
        entered, release, calls = self.block_worker('block.json')
        self.storage.save_atomic(self.source('block.json'), {'blocking': True})
        self.assertTrue(entered.wait(1))
        self.storage.save_atomic(self.source(), {'version': 'queued old'})
        os.environ['DATA_MIRROR_SYNC'] = '1'
        self.storage.save_atomic(self.source(), {'version': 'synchronous latest'})
        expected = self.source().read_bytes()
        self.assertEqual(self.mirrored().read_bytes(), expected)
        os.environ['DATA_MIRROR_SYNC'] = ''
        release.set()
        self.assertTrue(self.storage.drain_mirrors(1))
        self.assertEqual(self.mirrored().read_bytes(), expected)
        self.assertEqual(sum(Path(job.source).name == 'fixture.json' for job in calls), 1)

    def test_sync_waits_inflight_writer_then_cannot_be_overwritten(self):
        entered, release, _calls = self.block_worker()
        self.storage.save_atomic(self.source(), {'version': 'old flight'})
        self.assertTrue(entered.wait(1))
        errors = []
        os.environ['DATA_MIRROR_SYNC'] = '1'

        def save():
            try:
                self.storage.save_atomic(self.source(), {'version': 'sync wins'})
            except Exception as error:
                errors.append(error)

        caller = threading.Thread(target=save)
        caller.start()
        deadline = time.monotonic() + 1
        while json.loads(self.source().read_text('utf-8')).get('version') != 'sync wins' and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertTrue(caller.is_alive(), 'sync publication waits for already active target writer')
        release.set()
        caller.join(1)
        self.assertFalse(caller.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(self.storage.drain_mirrors(1))
        self.assertEqual(json.loads(self.mirrored().read_text('utf-8')), {'version': 'sync wins'})

    def test_worker_never_reads_corrupt_deleted_or_rolled_back_primary(self):
        entered, release, _calls = self.block_worker('block.json')
        self.storage.save_atomic(self.source('block.json'), {'blocking': True})
        self.assertTrue(entered.wait(1))
        expected = {}
        for name, operation in [('corrupt.json', 'corrupt'), ('deleted.json', 'delete'), ('rollback.json', 'rollback')]:
            path = self.source(name)
            self.storage.save_atomic(path, {'approved': name})
            expected[name] = path.read_bytes()
            if operation == 'delete':
                path.unlink()
            else:
                path.write_bytes(b'not JSON anymore' if operation == 'corrupt' else b'{"manualRollback":"unmirrored"}')
        release.set()
        self.assertTrue(self.storage.drain_mirrors(1))
        for name, approved in expected.items():
            self.assertEqual(self.mirrored(name).read_bytes(), approved)
        self.assertFalse(self.source('deleted.json').exists())

    def test_snapshot_spacing_dedup_pruning_and_off_policy(self):
        os.environ.update(DATA_MIRROR_SYNC='1', DATA_MIRROR_SNAPSHOTS='1', DATA_MIRROR_SNAPSHOT_MIN_SEC='300')
        path = self.source()
        snapshots = self.base / 'mirror/_snapshots/fixture'
        self.storage.save_atomic(path, {'version': 'one'})
        self.assertEqual(len(list(snapshots.glob('*.json'))), 1)
        self.storage.save_atomic(path, {'version': 'two'})
        self.assertEqual(len(list(snapshots.glob('*.json'))), 1, 'spacing uses copied primary mtime')
        os.environ['DATA_MIRROR_SNAPSHOT_MIN_SEC'] = '0'
        self.storage.save_atomic(path, {'version': 'one'})
        self.assertEqual(len(list(snapshots.glob('*.json'))), 1, 'byte-identical latest snapshot deduplicates')
        os.environ['DATA_MIRROR_MAX_SNAPS_PER_FILE'] = '2'
        for version in ['two', 'three', 'four']:
            self.storage.save_atomic(path, {'version': version})
        self.assertEqual(len(list(snapshots.glob('*.json'))), 2)
        self.assertIn(path.read_bytes(), [snapshot.read_bytes() for snapshot in snapshots.glob('*.json')])
        os.environ.update(DATA_MIRROR_SNAPSHOTS='0', DATA_MIRROR_MAX_SNAPS_PER_FILE='0')
        self.storage.save_atomic(path, {'version': 'off'})
        self.assertEqual(len(list(snapshots.glob('*.json'))), 2, 'snapshot-off retains pre-existing snapshots')
        os.environ['DATA_MIRROR_SNAPSHOTS'] = '1'
        self.storage.save_atomic(path, {'version': 'prune all'})
        self.assertEqual(len(list(snapshots.glob('*.json'))), 0)

    def test_mirror_failure_and_capture_failure_preserve_primary_success(self):
        os.environ['DATA_MIRROR_SYNC'] = '1'
        self.storage.save_atomic(self.source(), {'version': 'safe old mirror'})
        old = self.mirrored().read_bytes()
        with self.assertLogs(queue_module.log, level='ERROR'), patch.object(self.storage, '_atomic_mirror_bytes', side_effect=PermissionError('synthetic mirror failure')):
            self.storage.save_atomic(self.source(), {'version': 'primary survives'})
        self.assertEqual(json.loads(self.source().read_text('utf-8')), {'version': 'primary survives'})
        self.assertEqual(self.mirrored().read_bytes(), old)
        original_read = Path.read_bytes

        def reject_tmp(path):
            if path.suffix == '.tmp':
                raise PermissionError('synthetic mirror capture failure')
            return original_read(path)

        with self.assertLogs(self.storage.log, level='ERROR'), patch.object(Path, 'read_bytes', reject_tmp):
            self.storage.save_atomic(self.source(), {'version': 'capture failure primary survives'})
        self.assertEqual(json.loads(self.source().read_text('utf-8')), {'version': 'capture failure primary survives'})
        self.assertEqual(self.mirrored().read_bytes(), old)
        self.storage.save_atomic(self.source(), {'version': 'mirror recovers'})
        self.assertEqual(self.mirrored().read_bytes(), self.source().read_bytes())

    def test_exclusion_lazy_creation_and_bounded_shutdown(self):
        self.storage.save_atomic(self.source(), {'excluded': True}, mirror=False)
        self.assertIsNone(self.storage._MIRROR_QUEUE)
        self.assertEqual(self.atexit_calls, [])
        self.assertFalse(self.mirrored().exists())
        entered, release, _calls = self.block_worker()
        self.storage.save_atomic(self.source(), {'queued': True})
        self.assertTrue(entered.wait(1))
        self.assertEqual(len(self.atexit_calls), 1)
        self.assertEqual(self.atexit_calls[0].__defaults__, (5.0,))
        start = time.monotonic()
        self.assertFalse(self.storage.shutdown_mirrors(.05))
        self.assertLess(time.monotonic() - start, .3)
        self.storage.save_atomic(self.source(), {'afterShutdownPrimary': True})
        release.set()
        self.assertTrue(self.storage.shutdown_mirrors(1))
        self.assertEqual(json.loads(self.source().read_text('utf-8')), {'afterShutdownPrimary': True})
        self.assertEqual(json.loads(self.mirrored().read_text('utf-8')), {'queued': True})

    def test_same_primary_destination_is_excluded(self):
        os.environ['DATA_MIRROR_DIR'] = str(self.base)
        self.storage.save_atomic(self.source(), {'primary': 'must never become an old mirror'})
        self.assertIsNone(self.storage._MIRROR_QUEUE)
        self.assertFalse((self.base / '_snapshots').exists())
        self.storage.save_atomic(self.source(), {'private': 'later'}, mirror=False)
        self.assertEqual(json.loads(self.source().read_text('utf-8')), {'private': 'later'})

    def test_cross_process_sync_fences_older_daemon_publication(self):
        entered, release, _calls = self.block_worker()
        self.storage.save_atomic(self.source(), {'version': 'old queued daemon job'})
        self.assertTrue(entered.wait(1))
        child = multiprocessing.get_context('spawn').Process(target=sync_child, args=(str(self.base),))
        child.start()
        child.join(5)
        if child.is_alive():
            child.terminate()
            child.join(1)
            self.fail('OS-temp sync child did not stop')
        self.assertEqual(child.exitcode, 0)
        expected = self.source().read_bytes()
        self.assertEqual(self.mirrored().read_bytes(), expected)
        release.set()
        self.assertTrue(self.storage.drain_mirrors(1))
        self.assertEqual(self.mirrored().read_bytes(), expected)
        self.assertEqual(json.loads(expected), {'version': 'cross-process sync wins'})

    def test_source_lease_is_not_reacquired_by_async_or_sync_mirroring(self):
        path = self.source()
        for synchronous in [False, True]:
            os.environ['DATA_MIRROR_SYNC'] = '1' if synchronous else ''
            with self.storage.file_lock(path, timeout_sec=.2):
                self.storage.save_atomic(path, {'synchronous': synchronous})
                self.assertTrue(self.storage.drain_mirrors(.5), 'worker must not wait for the original lease')
                self.assertEqual(self.mirrored().read_bytes(), path.read_bytes())

    def test_cross_process_destination_lease_does_not_block_primary_ack(self):
        self.mirrored().parent.mkdir(parents=True, exist_ok=True)
        context = multiprocessing.get_context('spawn')
        entered, release = context.Event(), context.Event()
        child = context.Process(target=held_destination_child, args=(str(self.base), entered, release))
        child.start()
        try:
            self.assertTrue(entered.wait(2), 'OS-temp child must acquire the destination lease')
            for version in ['first while destination locked', 'latest while destination locked']:
                start = time.monotonic()
                self.storage.save_atomic(self.source(), {'version': version})
                self.assertLess(time.monotonic() - start, .5)
            expected = self.source().read_bytes()
            self.assertFalse(self.storage.drain_mirrors(.03))
            self.assertFalse(self.mirrored().exists(), 'publication must respect the other PID lease')
        finally:
            release.set()
            child.join(3)
            if child.is_alive():
                child.terminate()
                child.join(1)
        self.assertEqual(child.exitcode, 0)
        self.assertTrue(self.storage.drain_mirrors(1))
        self.assertEqual(self.mirrored().read_bytes(), expected)

    def test_hardlink_to_captured_primary_is_excluded_without_primary_read(self):
        entered, release, _calls = self.block_worker('block.json')
        self.storage.save_atomic(self.source('block.json'), {'blocking': True})
        self.assertTrue(entered.wait(1))
        self.storage.save_atomic(self.source(), {'approved': 'same physical inode'})
        expected = self.source().read_bytes()
        self.mirrored().parent.mkdir(parents=True, exist_ok=True)
        self.mirrored().hardlink_to(self.source())
        original_read = Path.read_bytes

        def no_primary_read(path):
            if path.resolve() == self.source():
                raise AssertionError('worker read primary after commit')
            return original_read(path)

        with patch.object(Path, 'read_bytes', no_primary_read):
            release.set()
            self.assertTrue(self.storage.drain_mirrors(1))
        self.assertTrue(self.mirrored().samefile(self.source()), 'alias is excluded instead of re-replaced')
        self.assertEqual(self.source().read_bytes(), expected)
        self.assertFalse(list((self.base / 'mirror/_snapshots/fixture').glob('*.json')))


if __name__ == '__main__':
    unittest.main(argv=[__file__, *test_args])
