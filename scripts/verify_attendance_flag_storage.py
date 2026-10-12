"""Execute actual attendance/contact HTTP functions with temporary storage only."""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
import tempfile
from typing import Any, Dict

from flask import Blueprint, Flask, abort, jsonify, request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.storage import file_lock, load, save_atomic
from core.date_rules import is_iso_date_key


def verify():
    names = {
        "_date_key_from_query", "_norm_date", "_load_flag_all", "_save_flag_all",
        "_patch_flag", "api_attendance_get", "api_attendance_patch",
        "api_contact_get", "api_contact_patch",
    }
    tree = ast.parse((ROOT / "routes/api_attend.py").read_text("utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == names
    with tempfile.TemporaryDirectory(prefix="attendance-store-contract-") as tmp:
        root = pathlib.Path(tmp)
        old_mirror = os.environ.get("DATA_MIRROR_DIR")
        os.environ["DATA_MIRROR_DIR"] = str(root / "mirror")
        try:
            bp = Blueprint("attendance_contract", __name__)
            scope = dict(globals(), bp_api_attend=bp,
                         ATTENDANCE_PATH=root / "attendance.json", CONTACT_PATH=root / "contact.json")
            exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROOT / "routes/api_attend.py"), "exec"), scope)
            app = Flask(__name__)
            app.register_blueprint(bp)
            client = app.test_client()
            for kind in ("attendance", "contact"):
                path = root / f"{kind}.json"
                endpoint = f"/api/{kind}/patch"
                payload = {"date": "2026-10-01", "sid": "qa", "value": True}
                assert client.post(endpoint, json=payload).status_code == 200
                assert json.loads(path.read_text("utf-8")) == {"2026-10-01": {"qa": 1}}
                path.write_text(json.dumps({"2026-09-30": {"other": 1}, "2026-10-01": {"existing": 1}}), encoding="utf-8")
                assert client.post(endpoint, json=payload).status_code == 200
                assert json.loads(path.read_text("utf-8")) == {
                    "2026-09-30": {"other": 1}, "2026-10-01": {"existing": 1, "qa": 1},
                }
                for raw in (b'{"truncated":', b'[]', b'null', b'{"2026-09-30":[]}', b'\xff'):
                    path.write_bytes(raw)
                    before = (path.stat().st_mtime_ns, hashlib.sha256(raw).hexdigest())
                    response = client.post(endpoint, json=payload)
                    assert response.status_code == 503, (kind, raw, response.status_code)
                    assert path.read_bytes() == raw
                    assert (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) == before
                path.unlink()
                path.mkdir()
                assert client.post(endpoint, json=payload).status_code == 503
                assert path.is_dir()
        finally:
            if old_mirror is None:
                os.environ.pop("DATA_MIRROR_DIR", None)
            else:
                os.environ["DATA_MIRROR_DIR"] = old_mirror
    print("attendance/contact actual HTTP checks passed: creation, narrow merge, unreadable/corrupt-store 503 and byte/mtime/hash invariance")


if __name__ == "__main__":
    verify()
