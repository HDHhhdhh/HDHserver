from __future__ import annotations

import io
import tarfile
import tempfile
import zipfile
from pathlib import Path

from scripts.unpack_aihub_split_archive import extract_direct_zip, reassemble_and_extract


def _tar_parts(zip_bytes: bytes, target: Path, *, chunk_size: int = 31) -> None:
    with tarfile.open(target, "w") as archive:
        for offset in range(0, len(zip_bytes), chunk_size):
            payload = zip_bytes[offset : offset + chunk_size]
            info = tarfile.TarInfo(f"nested/dataset.zip.part{offset}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def _raises(callback) -> None:
    try:
        callback()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def run() -> dict:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="aihub-unpack-") as temp_dir:
        root = Path(temp_dir)
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("labels/a.json", '{"ok":true}\n')
            archive.writestr("labels/b.json", '{"ok":false}\n')
        tar_path = root / "download.tar"
        _tar_parts(memory.getvalue(), tar_path)
        summary = reassemble_and_extract(
            archive_path=tar_path,
            zip_path=root / "dataset.zip",
            extract_root=root / "extracted",
        )
        assert summary["partCount"] > 1 and summary["embeddedZip"] == "dataset.zip"
        assert summary["reusedZip"] is False
        assert summary["extractedFiles"] == 2 and summary["zipBytes"] == len(memory.getvalue())
        assert (root / "extracted" / "labels" / "a.json").read_text(encoding="utf-8") == '{"ok":true}\n'
        reused = reassemble_and_extract(
            archive_path=tar_path,
            zip_path=root / "dataset.zip",
            extract_root=root / "extracted",
        )
        assert reused["reusedZip"] is True and reused["reusedExtractedFiles"] == 2
        assertions += 5

        direct_root = root / "direct-extracted"
        direct_zip = root / "direct.zip"
        direct_zip.write_bytes(memory.getvalue())
        direct = extract_direct_zip(zip_path=direct_zip, extract_root=direct_root)
        assert direct["schema"] == "aihub_direct_zip_unpack_v1"
        assert direct["partCount"] == 1 and direct["reusedZip"] is True
        assert direct["extractedFiles"] == 2 and direct["writtenFiles"] == 2
        assert (direct_root / "labels" / "b.json").read_text(encoding="utf-8") == '{"ok":false}\n'
        direct_reused = extract_direct_zip(zip_path=direct_zip, extract_root=direct_root)
        assert direct_reused["reusedExtractedFiles"] == 2 and direct_reused["writtenFiles"] == 0
        assertions += 5

        broken_tar = root / "broken.tar"
        with tarfile.open(broken_tar, "w") as archive:
            info = tarfile.TarInfo("dataset.zip.part4")
            info.size = 3
            archive.addfile(info, io.BytesIO(b"bad"))
        _raises(
            lambda: reassemble_and_extract(
                archive_path=broken_tar,
                zip_path=root / "broken.zip",
                extract_root=root / "broken-extracted",
            )
        )
        assertions += 1

        unsafe_memory = io.BytesIO()
        with zipfile.ZipFile(unsafe_memory, "w") as archive:
            archive.writestr("../escape.txt", "bad")
        unsafe_tar = root / "unsafe.tar"
        _tar_parts(unsafe_memory.getvalue(), unsafe_tar)
        _raises(
            lambda: reassemble_and_extract(
                archive_path=unsafe_tar,
                zip_path=root / "unsafe.zip",
                extract_root=root / "unsafe-extracted",
            )
        )
        assert not (root / "escape.txt").exists()
        assertions += 2


        unsafe_direct = root / "unsafe-direct.zip"
        unsafe_direct.write_bytes(unsafe_memory.getvalue())
        _raises(lambda: extract_direct_zip(zip_path=unsafe_direct, extract_root=root / "unsafe-direct-extracted"))
        assert not (root / "escape.txt").exists()
        assertions += 2
    return {"name": "aihub-split-archive-unpack", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
