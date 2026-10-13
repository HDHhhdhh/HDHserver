from __future__ import annotations

import datetime as dt
import ipaddress
import json
import os
from pathlib import Path

from flask import g, request


QA_SID = "QAHUBNATIVE1002"
QA_MID = "3FWqGfJP"
ENV = "ACADEMY_ISOLATED_KOLLUS_QA"


def _same_path(value, expected: Path) -> bool:
    return isinstance(value, str) and bool(value) and os.path.normcase(str(Path(value).resolve())) == os.path.normcase(str(expected.resolve()))


def _utc_stamp(value) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError("missing process timestamp")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("process timestamp must include timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_qa_context(*, code_root, environ, receipt, marker, pid,
                        process_started_at, remote_addr, public_request,
                        origin="", fetch_site="") -> bool:
    try:
        if environ.get(ENV) != "1" or public_request:
            return False
        if not isinstance(receipt, dict) or not isinstance(marker, dict):
            return False
        root = Path(code_root).resolve()
        source = Path(marker["sourceRoot"]).resolve()
        if root == source or root != (source / "instance" / "isolated-design-server" / "app").resolve():
            return False
        if not _same_path(environ.get("ACADEMY_ISOLATED_SERVER_ROOT"), root):
            return False
        if marker.get("format") != "academy-isolated-server/v1" or not _same_path(marker.get("isolatedRoot"), root):
            return False
        if receipt.get("format") != "academy-isolated-design-server/v1":
            return False
        if type(receipt.get("port")) is not int or receipt["port"] != 8004:
            return False
        if receipt.get("liveRuntimeCopied") is not False:
            return False
        if receipt.get("kollusVideoQaEnabled") is not True:
            return False
        if not _same_path(receipt.get("sourceRoot"), source) or not _same_path(receipt.get("codeRoot"), root):
            return False
        if type(pid) is not int or pid <= 0 or type(receipt.get("listenerProcessId")) is not int or receipt["listenerProcessId"] != pid:
            return False
        if abs((_utc_stamp(receipt.get("listenerStartTimeUtc")) - _utc_stamp(process_started_at)).total_seconds()) > 0.001:
            return False
        if not ipaddress.ip_address(remote_addr).is_loopback:
            return False
        return origin in ("", "http://127.0.0.1:8004") and fetch_site in ("", "same-origin", "none")
    except (KeyError, TypeError, ValueError, OSError, OverflowError):
        return False


def _process_started_at() -> str:
    if os.name != "nt":
        raise OSError("managed QA process identity requires Windows")
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    times = [wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(kernel.GetCurrentProcess(), *(ctypes.byref(value) for value in times)):
        raise OSError(ctypes.get_last_error())
    ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    return dt.datetime.fromtimestamp((ticks - 116444736000000000) / 10_000_000, dt.timezone.utc).isoformat()


def isolated_kollus_qa_allowed(sid, mid, req=None) -> bool:
    if os.environ.get(ENV) != "1" or sid != QA_SID or mid != QA_MID:
        return False
    req = request if req is None else req
    if req.host != "127.0.0.1:8004":
        return False
    root = Path(__file__).resolve().parents[1]
    # Read only the copied root's own marker and its manager receipt.
    if not _same_path(os.environ.get("ACADEMY_ISOLATED_SERVER_ROOT"), root):
        return False
    try:
        marker = json.loads((root / ".academy-isolated-server.json").read_text(encoding="utf-8-sig"))
        receipt = json.loads((root.parent / "server.json").read_text(encoding="utf-8-sig"))
        return validate_qa_context(
            code_root=root, environ=os.environ, receipt=receipt, marker=marker,
            pid=os.getpid(), process_started_at=_process_started_at(),
            remote_addr=req.remote_addr, public_request=getattr(g, "student_app_public_request", False) is True,
            origin=req.headers.get("Origin", ""), fetch_site=req.headers.get("Sec-Fetch-Site", ""),
        )
    except (OSError, ValueError, TypeError):
        return False
