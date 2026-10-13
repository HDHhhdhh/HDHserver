"""Atomic file persistence; callers own read-modify-write serialization.

Hold the canonical <path>.lock across load, merge and save. Multi-store writers
must keep their domain coordinator and lock order from core/AGENTS.md; a generic
file lock cannot replace identity, material or absence journal transactions.
"""
from __future__ import annotations

import atexit
import datetime as dt
import errno
import json
import logging
import os
import pathlib
import re
import stat
import threading
import time
import uuid
from typing import Any

from flask import jsonify, make_response

from core.mirror_queue import MirrorJob, MirrorQueue
from core.json_revision import json_revision

log = logging.getLogger(__name__)


_LOCAL_LOCK_TOKENS_GUARD = threading.Lock()
_LOCAL_LOCK_TOKENS: dict[str, str] = {}


def _local_lock_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _register_local_lock_token(path: str, token: str) -> None:
    with _LOCAL_LOCK_TOKENS_GUARD:
        _LOCAL_LOCK_TOKENS[_local_lock_key(path)] = token


def _unregister_local_lock_token(path: str, token: str) -> None:
    key = _local_lock_key(path)
    with _LOCAL_LOCK_TOKENS_GUARD:
        if _LOCAL_LOCK_TOKENS.get(key) == token:
            _LOCAL_LOCK_TOKENS.pop(key, None)


def _is_active_local_lock_token(path: str, token: str) -> bool:
    if not token:
        return False
    with _LOCAL_LOCK_TOKENS_GUARD:
        return _LOCAL_LOCK_TOKENS.get(_local_lock_key(path)) == token


def utc_now_isoz() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def load(path) -> Any:
    try:
        # Accept UTF-8 with or without BOM to avoid silently returning {}
        # when files are saved by editors/tools that prepend BOM.
        return json.loads(path.read_text("utf-8-sig"))
    except FileNotFoundError:
        return {} if str(path).endswith(".json") else None
    except json.JSONDecodeError:
        log.exception("JSON decode failed for %s", path)
        raise
    except Exception:
        log.exception("JSON load failed for %s", path)
        raise


def _resolve_mirror_root(path) -> pathlib.Path | None:
    """
    Mirror root resolution order:
    1) DATA_MIRROR_DIR env (can point outside project)
    2) <project>/_data_mirror (safe default)
    """
    env_dir = os.environ.get("DATA_MIRROR_DIR", "").strip()
    if env_dir:
        try:
            return pathlib.Path(env_dir)
        except Exception:
            return None

    try:
        p = pathlib.Path(path)
        return p.resolve().parent / "_data_mirror"
    except Exception:
        return None


def _env_int(name: str, default: int, min_value: int = 0) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except Exception:
        return default
    return max(min_value, v)


def _prune_snapshots(snap_dir: pathlib.Path, stem: str, max_keep: int) -> None:
    if max_keep < 0:
        return
    files = sorted(
        snap_dir.glob(f"{stem}.*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[max_keep:]:
        try:
            old.unlink()
        except Exception:
            pass


_MIRROR_QUEUE: MirrorQueue | None = None
_MIRROR_QUEUE_GUARD = threading.Lock()
_MIRROR_ATEXIT_REGISTERED = False


def _atomic_mirror_bytes(path: pathlib.Path, job: MirrorJob) -> None:
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(job.data)
        os.chmod(tmp, stat.S_IMODE(job.mode))
        os.utime(tmp, ns=(job.atime_ns, job.mtime_ns))
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _write_mirror_job(job: MirrorJob) -> None:
    job.mirror_file.parent.mkdir(parents=True, exist_ok=True)
    # Serialize destination publication across processes without ever reading
    # the primary again. A newer copied primary mtime fences older queued jobs.
    with file_lock(job.mirror_file, timeout_sec=5.0):
        try:
            destination = job.mirror_file.stat()
            if job.inode and (destination.st_dev, destination.st_ino) == (job.device, job.inode):
                return  # Captured primary inode, including a later hardlink alias.
            if destination.st_mtime_ns > job.mtime_ns:
                return
        except FileNotFoundError:
            pass
        _write_mirror_payload(job)


def _write_mirror_payload(job: MirrorJob) -> None:
    job.mirror_file.parent.mkdir(parents=True, exist_ok=True)
    job.snapshot_dir.mkdir(parents=True, exist_ok=True)
    _atomic_mirror_bytes(job.mirror_file, job)
    if not job.snapshots_enabled:
        return
    latest = None
    try:
        candidates = list(job.snapshot_dir.glob(f"{job.stem}.*.json"))
        if candidates:
            latest = max(candidates, key=lambda path: path.stat().st_mtime)
    except Exception:
        pass
    should_snapshot = True
    if latest is not None:
        try:
            age_sec = max(0.0, time.time() - latest.stat().st_mtime)
            if job.min_sec > 0 and age_sec < float(job.min_sec):
                should_snapshot = False
            elif latest.stat().st_size == len(job.data) and latest.read_bytes() == job.data:
                should_snapshot = False
        except Exception:
            pass
    if should_snapshot:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        _atomic_mirror_bytes(job.snapshot_dir / f"{job.stem}.{stamp}.json", job)
    _prune_snapshots(job.snapshot_dir, job.stem, max_keep=job.max_keep)


def _get_mirror_queue() -> MirrorQueue:
    global _MIRROR_QUEUE, _MIRROR_ATEXIT_REGISTERED
    with _MIRROR_QUEUE_GUARD:
        if _MIRROR_QUEUE is None:
            _MIRROR_QUEUE = MirrorQueue(lambda job: _write_mirror_job(job))
        if not _MIRROR_ATEXIT_REGISTERED:
            atexit.register(shutdown_mirrors)
            _MIRROR_ATEXIT_REGISTERED = True
        return _MIRROR_QUEUE


def drain_mirrors(timeout_sec: float = 5.0) -> bool:
    queue = _MIRROR_QUEUE
    return queue is None or queue.drain(timeout_sec)


def shutdown_mirrors(timeout_sec: float = 5.0) -> bool:
    queue = _MIRROR_QUEUE
    return queue is None or queue.shutdown(timeout_sec)


def _submit_committed_mirror(path, data: bytes, metadata, mirror) -> None:
    src = pathlib.Path(path)
    primary = src.resolve()
    mirror_root = _resolve_mirror_root(src)
    if mirror_root is None:
        return
    # Freeze relative destinations and policy now, before the worker can run.
    mirror_root = mirror_root.resolve()
    mirror_file = mirror_root / src.name
    if os.path.normcase(str(mirror_file)) == os.path.normcase(str(primary)):
        return  # Keep the old copy2 SameFileError exclusion; never mirror onto primary.
    snapshots = os.environ.get("DATA_MIRROR_SNAPSHOTS", "1").strip().lower() not in {"0", "false", "off", "no"}
    job = MirrorJob(str(primary), mirror_file,
                    mirror_root / "_snapshots" / src.stem, src.stem, data,
                    metadata.st_atime_ns, metadata.st_mtime_ns, metadata.st_mode,
                    metadata.st_dev, metadata.st_ino,
                    snapshots, _env_int("DATA_MIRROR_MAX_SNAPS_PER_FILE", 96),
                    _env_int("DATA_MIRROR_SNAPSHOT_MIN_SEC", 300))
    synchronous = mirror == "sync" or os.environ.get("DATA_MIRROR_SYNC", "").strip() == "1"
    _get_mirror_queue().submit(job, synchronous=synchronous)


def save_atomic(path, obj: Any, *, compact: bool = False, mirror: bool | str = "async") -> None:
    """
    원자적 쓰기(임시파일 → 교체).
    Windows에서 WinError 32(다른 프로세스가 파일 사용 중) 뜨는 케이스가 있어:
    - tmp 파일명을 고유하게 만들고
    - os.replace를 짧게 몇 번 재시도
    """
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    if compact:
        serialized = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    else:
        serialized = json.dumps(obj, ensure_ascii=False, indent=2)
    tmp.write_text(serialized, "utf-8")
    mirror_data = mirror_metadata = None
    if mirror and path.suffix.lower() == ".json":
        try:
            # Private tmp bytes include the exact Windows newline translation.
            # Never re-read the primary after another mirror=False save.
            mirror_data, mirror_metadata = tmp.read_bytes(), tmp.stat()
        except Exception:
            log.exception("Mirror capture failed for %s", path)

    last_err = None
    for _ in range(10):
        try:
            os.replace(tmp, path)
            if mirror_data is not None:
                try:
                    _submit_committed_mirror(path, mirror_data, mirror_metadata, mirror)
                except Exception:
                    log.exception("Mirror enqueue failed for %s", path)
            return
        except OSError as e:
            last_err = e
            time.sleep(0.03)

    # 실패 시 tmp 정리 시도
    try:
        if tmp.exists():
            tmp.unlink()
    except Exception:
        pass

    if last_err:
        raise last_err


class InterProcessFileLock:
    """Create/remove lock file for cross-process JSON read-modify-write."""

    def __init__(
        self,
        lock_path: str,
        timeout_sec: float = 15.0,
        poll_sec: float = 0.05,
        stale_sec: float = 30.0,
    ):
        self.lock_path = lock_path
        self.timeout_sec = timeout_sec
        self.poll_sec = poll_sec
        self.stale_sec = stale_sec
        self._fd = None
        self._token = ""

    @staticmethod
    def _pid_alive_windows(pid: int) -> bool:
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            kernel32.WaitForSingleObject.restype = ctypes.c_uint
            kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel32.GetExitCodeProcess.restype = ctypes.c_int
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int

            process_query_limited_information = 0x1000
            synchronize = 0x00100000
            handle = kernel32.OpenProcess(
                synchronize | process_query_limited_information,
                False,
                int(pid),
            )
            if not handle:
                # ERROR_ACCESS_DENIED means a process exists but cannot be queried.
                return ctypes.get_last_error() == 5

            try:
                wait_object_0 = 0x00000000
                wait_timeout = 0x00000102
                rc = kernel32.WaitForSingleObject(handle, 0)
                if rc == wait_timeout:
                    return True
                if rc == wait_object_0:
                    return False

                still_active = 259
                exit_code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == still_active
                return True
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False

    @classmethod
    def _pid_alive(cls, pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        if os.name == "nt":
            return cls._pid_alive_windows(pid)
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as e:
            return getattr(e, "errno", None) == errno.EPERM
        except Exception:
            return False

    def _read_lock_text(self) -> str:
        try:
            with open(self.lock_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""

    def _try_break_stale_lock(self) -> None:
        try:
            st = os.stat(self.lock_path)
        except FileNotFoundError:
            return
        except Exception:
            return

        age_sec = max(0.0, time.time() - float(st.st_mtime))

        txt = self._read_lock_text()
        pid = None
        token = ""
        try:
            m = re.search(r"\bpid=(\d+)\b", txt)
            if m:
                pid = int(m.group(1))
            token_match = re.search(r"\btoken=([A-Za-z0-9_-]+)\b", txt)
            if token_match:
                token = token_match.group(1)
        except Exception:
            pid = None
            token = ""

        if pid == os.getpid():
            if _is_active_local_lock_token(self.lock_path, token):
                return
            # A same-process lock can survive a transient Windows sharing
            # violation during release.  Give a just-created lock enough time
            # to register its token, then recover only when no live local
            # owner exists.  Genuine long-running local locks remain protected
            # by the active-token registry above.
            local_orphan_grace_sec = max(1.0, self.poll_sec * 10)
            if age_sec < local_orphan_grace_sec:
                return
        else:
            if age_sec < self.stale_sec:
                return
            if pid is not None and self._pid_alive(pid):
                return

        try:
            os.remove(self.lock_path)
            log.warning("Removed stale lock file: %s", self.lock_path)
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def acquire(self) -> None:
        deadline = time.time() + self.timeout_sec
        permission_retries = 0
        while True:
            try:
                token = uuid.uuid4().hex
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            except FileExistsError:
                self._try_break_stale_lock()
                if time.time() > deadline:
                    raise TimeoutError(f"lock timeout: {self.lock_path}")
                time.sleep(self.poll_sec)
            except PermissionError as exc:
                # Windows can expose delete-pending O_EXCL conflicts as EACCES.
                # Never break a lock for this error, and retain real ACL failures.
                if os.name != "nt" or getattr(exc, "winerror", None) not in {None, 5, 32, 33}:
                    raise
                if permission_retries >= 3 or time.time() >= deadline:
                    raise
                permission_retries += 1
                time.sleep(self.poll_sec)
            else:
                self._fd = fd
                self._token = token
                os.write(fd, f"pid={os.getpid()} time={time.time()} token={token}".encode("utf-8"))
                _register_local_lock_token(self.lock_path, token)
                return

    def release(self) -> None:
        token = self._token
        try:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
            self._fd = None
            self._token = ""
            deadline = time.time() + max(0.2, self.poll_sec * 5)
            last_error: OSError | None = None
            while True:
                try:
                    with open(self.lock_path, "r", encoding="utf-8", errors="ignore") as handle:
                        txt = handle.read()
                except FileNotFoundError:
                    return
                except OSError as exc:
                    last_error = exc
                else:
                    if token and f"token={token}" not in txt:
                        return
                    try:
                        os.remove(self.lock_path)
                        return
                    except FileNotFoundError:
                        return
                    except OSError as exc:
                        last_error = exc

                if time.time() >= deadline:
                    log.warning("Failed to release owned lock file %s: %s", self.lock_path, last_error)
                    return
                time.sleep(self.poll_sec)
        except Exception:
            pass
        finally:
            _unregister_local_lock_token(self.lock_path, token)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()


def file_lock(
    path,
    timeout_sec: float = 15.0,
    poll_sec: float = 0.05,
    stale_sec: float = 30.0,
) -> InterProcessFileLock:
    """Lock helper bound to a target path."""
    pp = str(getattr(path, "__fspath__", lambda: str(path))())
    return InterProcessFileLock(
        pp + ".lock",
        timeout_sec=timeout_sec,
        poll_sec=poll_sec,
        stale_sec=stale_sec,
    )


def nocache_resp(payload):
    resp = make_response(jsonify(payload))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp
