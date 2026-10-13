from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

with patch.dict(os.environ, {"AUTH_SECRET": "", "MASTER_PW": "short", "ALLOW_EPHEMERAL_AUTH_SECRET": ""}):
    from routes import api_auth


def run_checks() -> None:
    assert api_auth.AUTH_SECRET_IS_EPHEMERAL is True
    with patch.dict(os.environ, {"ALLOW_EPHEMERAL_AUTH_SECRET": ""}):
        try:
            api_auth.validate_auth_startup()
        except RuntimeError as error:
            assert "refusing to start" in str(error)
        else:
            raise AssertionError("missing persistent secret must refuse startup")
    with patch.dict(os.environ, {"ALLOW_EPHEMERAL_AUTH_SECRET": "1"}):
        api_auth.validate_auth_startup()
    with patch.object(api_auth, "AUTH_SECRET_IS_EPHEMERAL", False), patch.dict(os.environ, {"ALLOW_EPHEMERAL_AUTH_SECRET": ""}):
        api_auth.validate_auth_startup()
    # The approved short master password must not change the startup outcome.
    assert api_auth.MASTER_PW == "short"
    source = ast.parse((ROOT / "app.py").read_text("utf-8-sig"))
    create = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "create_app")
    assert ast.unparse(create.body[0]) == "refuse_concurrent_live_server()"
    assert ast.unparse(create.body[1]) == "validate_auth_startup()"
    assert "initialize_runtime_paths" in ast.unparse(create.body[2:])
    subprocess.run([sys.executable, "-B", "-m", "scripts.verify_app_runtime", "auth-startup"], cwd=ROOT, check=True)
    print("Auth startup: ephemeral refusal, explicit temp allowance, persistent secret and approved master password preserved before runtime initialization")


if __name__ == "__main__":
    run_checks()
