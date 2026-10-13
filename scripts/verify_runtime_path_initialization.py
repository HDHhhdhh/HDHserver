"""Verify paths initialization using temporary code and runtime roots only."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "core/paths.py").read_text(encoding="utf-8")

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def initialize(root):
    source_path = root / "core/paths.py"
    source_path.parent.mkdir()
    source_path.write_text(SOURCE, encoding="utf-8")
    namespace = {"__file__": str(source_path), "__name__": "temporary_runtime_paths"}
    with patch.dict(os.environ, {"DATA_DIR": str(root / "data")}):
        exec(compile(SOURCE, str(source_path), "exec"), namespace)
    assert namespace["STU_PATH"] == root / "students.json"
    assert not (root / "files").exists(), "import must not create runtime directories"
    assert not (root / "data").exists(), "import must not create the data directory"
    assert not (root / "videos.json").exists(), "import must not create missing stores"
    namespace["initialize_runtime_paths"]()
    return namespace

def verify():
    with tempfile.TemporaryDirectory(prefix="verify-runtime-paths-") as temporary:
        base = Path(temporary)
        legacy = base / "legacy"
        legacy.mkdir()
        initialize(legacy)
        assert (legacy / "students.json").read_bytes() == b"[]"
        assert not (legacy / "persons.json").exists()

        existing = base / "existing"
        existing.mkdir()
        (existing / "students.json").write_bytes(b'[{"id":"kept","unknown":{"keep":true}}]')
        before = digest(existing / "students.json")
        initialize(existing)
        assert digest(existing / "students.json") == before

        for label, relative, content in (
            ("directory", "persons.json", b'{"persons":[]}'),
            ("corrupt-directory", "persons.json", b"{broken"),
            ("journal", "instance/person_identity_transactions/pending.json", b'{"pending":true}'),
        ):
            fixture = base / label
            fixture.mkdir()
            marker = fixture / relative
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_bytes(content)
            before = digest(marker)
            initialize(fixture)
            assert not (fixture / "students.json").exists(), label
            assert digest(marker) == before, label
        print("runtime-path initialization checks passed: legacy create, existing-byte preservation, 3 configured missing-store cases")

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    verify()
