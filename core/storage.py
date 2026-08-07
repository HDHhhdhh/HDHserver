from __future__ import annotations

import datetime as dt
import filecmp
import errno
import json
import logging
import os
import pathlib
import re
import shutil
import time
import uuid
from typing import Any

from flask import jsonify, make_response

log = logging.getLogger(__name__)


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
        return {} if str(path).endswith(".json") else None


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


def _mirror_copy(path) -> None:
    """
    Best-effort mirror copy for redundancy.
    - Never raises: primary save should remain authoritative.
    - Copies JSON file to mirror root with same filename.
    - Also writes timestamped snapshot for rollback.
    """
    try:
        src = pathlib.Path(path)
        if src.suffix.lower() != ".json":
            return

        mirror_root = _resolve_mirror_root(src)
        if mirror_root is None:
            return

        mirror_root.mkdir(parents=True, exist_ok=True)
        mirror_file = mirror_root / src.name
        snap_dir = mirror_root / "_snapshots" / src.stem
        snap_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(src, mirror_file)

        # Snapshot controls (all optional env vars):
        # - DATA_MIRROR_SNAPSHOTS=0              => disable snapshots
        # - DATA_MIRROR_MAX_SNAPS_PER_FILE=96    => keep only newest N snapshots/file
        # - DATA_MIRROR_SNAPSHOT_MIN_SEC=300     => min interval seconds between snapshots
        snapshot_flag = os.environ.get("DATA_MIRROR_SNAPSHOTS", "1").strip().lower()
        snapshots_enabled = snapshot_flag not in {"0", "false", "off", "no"}
        if not snapshots_enabled:
            return

        max_keep = _env_int("DATA_MIRROR_MAX_SNAPS_PER_FILE", 96, min_value=0)
        min_sec = _env_int("DATA_MIRROR_SNAPSHOT_MIN_SEC", 300, min_value=0)

        latest = None
        try:
            cands = list(snap_dir.glob(f"{src.stem}.*.json"))
            if cands:
                latest = max(cands, key=lambda p: p.stat().st_mtime)
        except Exception:
            latest = None

        should_snapshot = True
        if latest is not None:
            try:
                age_sec = max(0.0, time.time() - latest.stat().st_mtime)
                if min_sec > 0 and age_sec < float(min_sec):
                    should_snapshot = False
                elif latest.stat().st_size == src.stat().st_size and filecmp.cmp(latest, src, shallow=False):
                    should_snapshot = False
            except Exception:
                pass

        if should_snapshot:
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            snap_file = snap_dir / f"{src.stem}.{stamp}.json"
            shutil.copy2(src, snap_file)

        _prune_snapshots(snap_dir, src.stem, max_keep=max_keep)
    except Exception:
        # mirror is redundancy only; ignore failures
        return


def save_atomic(path, obj: Any, *, compact: bool = False) -> None:
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

    last_err = None
    for _ in range(10):
        try:
            os.replace(tmp, path)
            _mirror_copy(path)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(0.03)  # 30ms
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

        if time.time() - float(st.st_mtime) < self.stale_sec:
            return

        txt = self._read_lock_text()
        pid = None
        try:
            m = re.search(r"\bpid=(\d+)\b", txt)
            if m:
                pid = int(m.group(1))
        except Exception:
            pid = None

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
        while True:
            try:
                token = uuid.uuid4().hex
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                self._fd = fd
                self._token = token
                os.write(fd, f"pid={os.getpid()} time={time.time()} token={token}".encode("utf-8"))
                return
            except FileExistsError:
                self._try_break_stale_lock()
                if time.time() > deadline:
                    raise TimeoutError(f"lock timeout: {self.lock_path}")
                time.sleep(self.poll_sec)

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
            if token:
                txt = self._read_lock_text()
                if f"token={token}" not in txt:
                    return
            try:
                os.remove(self.lock_path)
            except FileNotFoundError:
                pass
        except Exception:
            pass

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
