from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.runtime_server_guard import (
    is_network_server_command,
    is_production_server_command,
    refuse_concurrent_live_server,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    production = [
        "waitress-serve.exe",
        "--listen=0.0.0.0:8003",
        "--threads=16",
        "app:app",
    ]
    loopback_shadow = [
        "waitress-serve.exe",
        "--listen=127.0.0.1:8003",
        "app:app",
    ]
    qa_waitress = [
        "waitress-serve.exe",
        "--listen=127.0.0.1:8004",
        "--threads=8",
        "app:app",
    ]
    qa_flask = [
        "python.exe",
        "-c",
        "from app import create_app; app = create_app(); app.run(host='127.0.0.1', port=8004)",
    ]
    test_client = [
        "python.exe",
        "-c",
        "from app import create_app; client = create_app().test_client()",
    ]

    check(is_network_server_command(production), "production Waitress was not classified as a server")
    check(is_production_server_command(production), "production Waitress contract was not recognized")
    check(is_network_server_command(loopback_shadow), "loopback shadow Waitress was not detected")
    check(not is_production_server_command(loopback_shadow), "loopback shadow was treated as production")
    check(is_network_server_command(qa_waitress), "port 8004 Waitress was not detected")
    check(is_network_server_command(qa_flask), "Flask app.run server was not detected")
    check(not is_network_server_command(test_client), "test_client import was treated as a network server")

    refuse_concurrent_live_server(production, listener_probe=lambda: True)
    refuse_concurrent_live_server(qa_waitress, listener_probe=lambda: False)
    refuse_concurrent_live_server(test_client, listener_probe=lambda: True)

    blocked = False
    try:
        refuse_concurrent_live_server(qa_waitress, listener_probe=lambda: True)
    except RuntimeError as exc:
        blocked = "already listening" in str(exc)
    check(blocked, "concurrent live-runtime QA server was not rejected")

    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    guard_call = app_source.index("    refuse_concurrent_live_server()")
    recovery_call = app_source.index("    recovered_absence_transaction = recover_pending_absence_transactions()")
    check(guard_call < recovery_call, "runtime server guard must run before startup recovery writes")

    print("runtime server singleton guard checks: OK")


if __name__ == "__main__":
    main()
