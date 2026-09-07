"""Temporary-only archive adversarial fixtures."""
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from scripts.student_test_gpu_archive import extract, inventory, join, pack, safe_name, sha256, split


class ArchiveTests(unittest.TestCase):
    def test_roundtrip_and_existing_destination_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "Korean.txt").write_text("수식 123\n", encoding="utf-8")
            receipt = pack(source, root / "bundle.zip")
            manifest = split(root / "bundle.zip", root / "parts", part_bytes=31)
            self.assertGreater(len(manifest["parts"]), 1)
            join(root / "parts" / "ARCHIVE_PARTS.json", root / "joined.zip")
            self.assertEqual(sha256(root / "joined.zip"), receipt["sha256"])
            extract(root / "joined.zip", root / "result", receipt["bytes"], receipt["sha256"])
            self.assertEqual((root / "result" / "Korean.txt").read_bytes(), (source / "Korean.txt").read_bytes())
            with self.assertRaises(ValueError):
                extract(root / "joined.zip", root / "result", receipt["bytes"], receipt["sha256"])
            with self.assertRaises(ValueError):
                pack(source, root / "bundle.zip")

    def test_traversal_drive_ads_reserved_collisions_and_symlink(self):
        cases = [["../escape"], ["/absolute"], ["C:/escape"], ["name:stream"], ["CON.txt"],
                 ["a/../b"], ["A.txt", "a.txt"], ["a", "a/b"], ["a./b"], ["a//b"], ["a?.txt"]]
        with self.assertRaises(ValueError):
            safe_name("a\\b")  # Windows ZipInfo creation normalizes this before serialization.
        with tempfile.TemporaryDirectory() as tmp:
            for number, names in enumerate(cases):
                with self.subTest(names=names):
                    path = Path(tmp) / f"{number}.zip"
                    with zipfile.ZipFile(path, "w") as zipper:
                        for name in names:
                            zipper.writestr(name, "untrusted")
                    with zipfile.ZipFile(path) as zipper, self.assertRaises(ValueError):
                        inventory(zipper)
            path = Path(tmp) / "link.zip"
            with zipfile.ZipFile(path, "w") as zipper:
                info = zipfile.ZipInfo("link")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zipper.writestr(info, "../outside")
            with zipfile.ZipFile(path) as zipper, self.assertRaises(ValueError):
                inventory(zipper)

    def test_corrupt_part_and_zip_stop_before_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "sample.zip"
            with zipfile.ZipFile(archive, "w") as zipper:
                zipper.writestr("a.txt", "original")
            manifest = split(archive, root / "parts", part_bytes=40)
            part = root / "parts" / manifest["parts"][0]["name"]
            part.write_bytes(b"bad")
            with self.assertRaises(ValueError):
                join(root / "parts" / "ARCHIVE_PARTS.json", root / "joined.zip")
            self.assertFalse((root / "joined.zip").exists())
            with self.assertRaises(ValueError):
                extract(archive, root / "result", archive.stat().st_size, "0" * 64)
            self.assertFalse((root / "result").exists())


if __name__ == "__main__":
    unittest.main()
