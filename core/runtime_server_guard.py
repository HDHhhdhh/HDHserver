from __future__ import annotations

import re
import socket
import sys
from collections.abc import Callable, Sequence


PRODUCTION_PORT = 8003
_APP_TARGET_RE = re.compile(r"(?:^|[\s\"'])app:app(?:$|[\s\"'])", re.IGNORECASE)


def command_text(arguments: Sequence[object] | None = None) -> str:
    if arguments is None:
        arguments = getattr(sys, "orig_argv", None) or sys.argv
    return " ".join(str(value or "") for value in arguments).strip()


def is_network_server_command(arguments: Sequence[object] | None = None) -> bool:
    text = command_text(arguments)
    lowered = text.lower()
    return bool(
        ("waitress-serve" in lowered and _APP_TARGET_RE.search(text))
        or (re.search(r"(?:^|[\\/\s])flask(?:\.exe)?(?:\s|$)", lowered) and re.search(r"(?:^|\s)run(?:\s|$)", lowered))
        or re.search(r"\bapp\s*\.\s*run\s*\(", text)
    )


def is_production_server_command(arguments: Sequence[object] | None = None) -> bool:
    text = command_text(arguments)
    lowered = text.lower()
    return bool(
        "waitress-serve" in lowered
        and _APP_TARGET_RE.search(text)
        and re.search(r"--listen=0\.0\.0\.0:8003(?:\s|$)", lowered)
    )


def production_listener_reachable(*, timeout_seconds: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PRODUCTION_PORT), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def refuse_concurrent_live_server(
    arguments: Sequence[object] | None = None,
    *,
    listener_probe: Callable[[], bool] = production_listener_reachable,
) -> None:
    if not is_network_server_command(arguments):
        return
    if is_production_server_command(arguments):
        return
    if not listener_probe():
        return
    raise RuntimeError(
        "Production Waitress is already listening on port 8003. "
        "Do not start another app server against the live C:\\server runtime; "
        "use the running server for read-only QA or stop production before isolated server work."
    )
