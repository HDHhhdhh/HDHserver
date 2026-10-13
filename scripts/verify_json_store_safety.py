"""Strict storage checks use only temporary files and injected failures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import storage


class StrictJsonReadTests(unittest.TestCase):
    def test_missing_defaults_and_existing_json_shapes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(storage.load(root / "missing.json"), {})
            self.assertIsNone(storage.load(root / "missing.txt"))
            self.assertEqual(list(root.iterdir()), [])
            for value in ({"unknown": {"keep": "한글"}}, [1, False, "한글"], 0, None):
                path = root / "shape.json"
                path.write_text(json.dumps(value, ensure_ascii=False), "utf-8-sig")
                self.assertEqual(storage.load(path), value)

    def test_io_decode_errors_raise_and_do_not_mutate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "store.json"
            path.write_text('{"keep":"한글"}', "utf-8")
            before = (path.stat().st_mtime_ns, path.read_bytes(), hashlib.sha256(path.read_bytes()).hexdigest())
            for error in (PermissionError("denied"), OSError("read failure"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")):
                with self.subTest(error=type(error).__name__), patch.object(Path, "read_text", side_effect=error):
                    with self.assertRaises(type(error)):
                        storage.load(path)
                self.assertEqual((path.stat().st_mtime_ns, path.read_bytes(), hashlib.sha256(path.read_bytes()).hexdigest()), before)
            path.write_text("{broken", "utf-8")
            with self.assertRaises(json.JSONDecodeError):
                storage.load(path)
            self.assertEqual(path.read_text("utf-8"), "{broken")

    def test_primary_commit_survives_internal_mirror_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "store.json"
            with patch.dict("os.environ", {"DATA_MIRROR_DIR": str(root / "mirror"), "DATA_MIRROR_SYNC": "1"}), patch.object(storage.shutil, "copy2", side_effect=PermissionError("mirror unavailable")):
                storage.save_atomic(path, {"committed": True, "unknown": "한글"})
            self.assertEqual(json.loads(path.read_text("utf-8")), {"committed": True, "unknown": "한글"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
