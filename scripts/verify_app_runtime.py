"""Run app-import checks with synthetic stores in a fresh OS-temp process."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import importlib
import os
from pathlib import Path
import runpy
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
_ACTIVE_RUNTIME: Path | None = None


def is_active() -> bool:
    return _ACTIVE_RUNTIME is not None and Path.cwd() == _ACTIVE_RUNTIME


def configure_app(app):
    if not is_active():
        raise RuntimeError("synthetic app runtime is not active")
    app.static_folder = str(_ACTIVE_RUNTIME / "static")
    app.instance_path = str(_ACTIVE_RUNTIME / "instance")
    return app


def main() -> int:
    global _ACTIVE_RUNTIME
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("import-app", "academy-proxy"))
    mode = parser.parse_args().mode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    sys.modules["scripts.verify_app_runtime"] = sys.modules[__name__]
    violations: list[str] = []
    temporary = tempfile.TemporaryDirectory(prefix="verify-synthetic-app-")
    with temporary as tmp, ExitStack() as cleanup:
        cleanup.callback(os.chdir, Path.cwd())
        if os.name != "nt":
            cleanup.callback(temporary.cleanup)
        runtime = Path(tmp).resolve()
        os.chdir(runtime)
        tempfile.tempdir = str(runtime)
        os.environ["TMP"] = os.environ["TEMP"] = str(runtime)
        (runtime / "static/js").mkdir(parents=True)
        (runtime / "static/js/test_answer_link_map.json").write_text("{}\n", encoding="utf-8")
        for key in tuple(os.environ):
            if key.startswith(("STUDENT_APP_", "ACADEMY_ISOLATED_")):
                os.environ.pop(key)
        os.environ["DATA_DIR"] = str(runtime / "data")
        os.environ["DB_PATH"] = str(runtime / "app.sqlite")
        os.environ["AUTH_SECRET"] = "synthetic-app-verification-only"

        def resolve_path(value) -> Path | None:
            if not isinstance(value, (str, bytes, os.PathLike)):
                return None
            return Path(os.fsdecode(value)).resolve()

        def reject(event: str) -> None:
            violations.append(event)
            raise AssertionError(f"synthetic app verification attempted protected access: {event}")

        def audit(event: str, args: tuple) -> None:
            if event == "open":
                path = resolve_path(args[0])
                if path is None:
                    return
                mode_value, flags = args[1:3]
                writing = (isinstance(mode_value, str) and any(x in mode_value for x in "wax+")) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
                )
                if writing and not path.is_relative_to(runtime):
                    reject(event)
                if path.is_relative_to(ROOT):
                    relative = path.relative_to(ROOT)
                    runtime_read = bool(relative.parts) and (relative.parts[0] in {"data", "files", "instance", "_data_mirror", "_runtime_backups", "generated"} or (
                        len(relative.parts) == 1 and (path.suffix.lower() in {".json", ".sqlite", ".db"} or path.name.endswith(("-wal", "-shm", ".tmp")))
                    ))
                    if runtime_read or path == ROOT / "static/js/test_answer_link_map.json":
                        reject(event)
                elif not path.is_relative_to(runtime) and path.suffix.lower() in {".json", ".sqlite", ".db"}:
                    reject(event)
            elif event == "sqlite3.connect":
                if args[0] != ":memory:" and (str(args[0]).startswith("file:") or not resolve_path(args[0]).is_relative_to(runtime)):
                    reject(event)
            elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.truncate", "os.rename", "os.link", "os.symlink"}:
                paths = args[:2] if event in {"os.rename", "os.link", "os.symlink"} else args[:1]
                if any(resolve_path(path) is None or not resolve_path(path).is_relative_to(runtime) for path in paths):
                    reject(event)
            elif event in {"socket.connect", "socket.bind", "subprocess.Popen"}:
                reject(event)

        sys.addaudithook(audit)
        paths = importlib.import_module("core.paths")
        for key, value in tuple(vars(paths).items()):
            if isinstance(value, Path) and value.is_relative_to(ROOT):
                setattr(paths, key, runtime / value.relative_to(ROOT))
        auth = importlib.import_module("routes.api_auth")
        auth.BASE = runtime
        auth.STU_PATH = runtime / "students.json"
        auth.ACCT_PATH = runtime / "auth_accounts.json"
        _ACTIVE_RUNTIME = runtime
        try:
            module = importlib.import_module("app")
            assert Path(module.__file__).resolve() == ROOT / "app.py", "app must come from the reviewed source"
            assert callable(module.create_app), "app import must expose create_app"
            configure_app(module.app)
            if mode == "academy-proxy":
                runpy.run_path(str(ROOT / "scripts/verify_academy_proxy_network_access.py"), run_name="__main__")
        finally:
            _ACTIVE_RUNTIME = None
            assert not violations, f"caught protected-access attempts: {violations}"
        print(f"synthetic app verification passed: {mode}; protected-access attempts 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
