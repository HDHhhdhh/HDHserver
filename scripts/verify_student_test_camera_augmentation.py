"""Independent OS-temp fixtures. No models, production imports, HTTP or actual dataset writes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

from scripts import prepare_student_test_camera_augmentation as augmentation


def fixture_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class CameraAugmentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ocr-camera-augmentation-test-")
        self.root = Path(self.temp.name)
        self.source = self.root / "audited-training"
        (self.source / "images").mkdir(parents=True)
        annotation = b"1\n\\frac{1}{2}\n\\sqrt{2}\n"
        (self.source / "equations.txt").write_bytes(annotation)
        rows = []
        image_digest = hashlib.sha256()
        for index in range(3):
            name = f"{index:07d}.png"
            image = Image.new("RGB", (64 + index, 32 + index), "white")
            ImageDraw.Draw(image).rectangle((1, 1, image.width - 2, image.height - 2), outline="black", width=2)
            image.save(self.source / "images" / name)
            image.close()
            image_sha = fixture_hash(self.source / "images" / name)
            image_digest.update(name.encode("ascii") + b"\0")
            image_digest.update(bytes.fromhex(image_sha))
            rows.append({
                "index": index, "grade": ["M_G3", "H_G1", "H_G1"][index],
                "writerHash": ["writer-A", "writer-B", "writer-C"][index],
                "sourceHash": str(index + 1) * 64, "sourceIndex": index + 11,
                "sourceImageSha256": image_sha, "selectionKind": "focused",
                "transcriptionUnchanged": True,
            })
        (self.source / "provenance.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        parent_signature = {
            "count": 29, "annotationSha256": "a" * 64, "imagesSha256": "b" * 64,
            "provenanceSha256": "c" * 64, "manifestSha256": "d" * 64,
        }
        self.manifest = {
            "schema": "student_test_formula_profile_dataset_v1", "profile": "m3_h1",
            "grades": ["M_G3", "H_G1"], "count": 3, "answerKeyFieldsUsed": 0,
            "includesStudentPhotos": False, "deploymentReady": False,
            "sourceSignature": parent_signature,
        }
        fixture_json(self.source / "manifest.json", self.manifest)
        self.audit = self.root / "SELECTION_AUDIT.json"
        self.audit_value = {
            "sourceSignature": parent_signature, "sourceUnchanged": True,
            "identityIndependenceNotProven": True,
            "trainingValidationSeparation": [
                "grade-scoped writer hash", "source hash", "exact image SHA-256"],
        }
        fixture_json(self.audit, self.audit_value)
        self.expected = {
            "count": 3, "grades": ["M_G3", "H_G1"],
            "annotationSha256": hashlib.sha256(annotation).hexdigest(),
            "imagesSha256": image_digest.hexdigest(),
            "provenanceSha256": fixture_hash(self.source / "provenance.jsonl"),
            "manifestSha256": fixture_hash(self.source / "manifest.json"),
        }
        self.allowlist = mock.patch.dict(augmentation.APPROVED_TRAINING, {"m3_h1": self.expected}, clear=True)
        self.allowlist.start()
        self.audit_hash_patch = mock.patch.object(augmentation, "AUDIT_SHA256", fixture_hash(self.audit))
        self.audit_hash_patch.start()
        self.before = self.inventory(self.source)

    def tearDown(self):
        self.audit_hash_patch.stop()
        self.allowlist.stop()
        self.temp.cleanup()

    @staticmethod
    def inventory(root):
        return {path.relative_to(root).as_posix(): fixture_hash(path)
                for path in root.rglob("*") if path.is_file()}

    def run_prepare(self, name="paired", seed=20261004):
        return augmentation.prepare(self.source, self.audit, self.root / name, profile="m3_h1", seed=seed)

    def assert_source_unchanged(self):
        self.assertEqual(self.inventory(self.source), self.before)

    def test_fixed_count_annotations_control_and_parent_binding(self):
        receipt = self.run_prepare()
        self.assertEqual(set(receipt["arms"]), {"control", "camera_aug"})
        for arm in ("control", "camera_aug"):
            output = self.root / "paired" / arm
            self.assertEqual((output / "equations.txt").read_bytes(), b"1\n\\frac{1}{2}\n\\sqrt{2}\n")
            self.assertEqual(sorted(path.name for path in (output / "images").iterdir()),
                             ["0000000.png", "0000001.png", "0000002.png"])
            rows = [json.loads(line) for line in (output / "provenance.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 3)
            for index, row in enumerate(rows):
                original = self.source / "images" / f"{index:07d}.png"
                result = output / "images" / f"{index:07d}.png"
                self.assertEqual(row["parentIndex"], index)
                self.assertEqual(row["parentImageSha256"], fixture_hash(original))
                self.assertEqual(row["outputImageSha256"], fixture_hash(result))
                self.assertEqual(row["writerHash"], ["writer-A", "writer-B", "writer-C"][index])
                self.assertEqual(row["dataRole"], "training")
                if arm == "control":
                    self.assertEqual(result.read_bytes(), original.read_bytes())
                else:
                    self.assertNotEqual(result.read_bytes(), original.read_bytes())
        self.assert_source_unchanged()

    def test_deterministic_same_seed_and_changed_seed(self):
        self.run_prepare("one", seed=12)
        self.run_prepare("two", seed=12)
        self.run_prepare("three", seed=13)
        first = self.inventory(self.root / "one" / "camera_aug")
        self.assertEqual(first, self.inventory(self.root / "two" / "camera_aug"))
        self.assertNotEqual(first["images/0000000.png"],
                            self.inventory(self.root / "three" / "camera_aug")["images/0000000.png"])
        first_control = self.inventory(self.root / "one" / "control")
        changed_seed_control = self.inventory(self.root / "three" / "control")
        first_control.pop("manifest.json")
        changed_seed_control.pop("manifest.json")
        self.assertEqual(first_control, changed_seed_control)
        self.assert_source_unchanged()

    def test_bounds_padding_and_no_clipped_fixture_border(self):
        self.run_prepare()
        root = self.root / "paired" / "camera_aug"
        rows = [json.loads(line) for line in (root / "provenance.jsonl").read_text(encoding="utf-8").splitlines()]
        for row in rows:
            parameters = row["transformParameters"]
            self.assertLessEqual(abs(parameters["rotationDegrees"]), 2)
            self.assertTrue(0.95 <= parameters["brightnessFactor"] <= 1.05)
            self.assertTrue(0.95 <= parameters["contrastFactor"] <= 1.05)
            self.assertTrue(0 <= parameters["blurRadius"] <= 0.45)
            self.assertTrue(parameters["rotationExpand"])
            with Image.open(root / "images" / f'{row["index"]:07d}.png') as image:
                self.assertGreater(image.width, 64 + row["index"])
                self.assertGreater(image.height, 32 + row["index"])
                bbox = image.convert("L").point(lambda value: 255 if value < 80 else 0).getbbox()
                self.assertIsNotNone(bbox)
                self.assertGreaterEqual(bbox[0], 3)
                self.assertGreaterEqual(bbox[1], 3)
                self.assertLessEqual(bbox[2], image.width - 3)
                self.assertLessEqual(bbox[3], image.height - 3)

    def test_preparation_is_not_camera_evaluation_or_training_approval(self):
        receipt = self.run_prepare()
        self.assertFalse(receipt["trainingAllowed"])
        self.assertFalse(receipt["trainingExecuted"])
        self.assertFalse(receipt["evaluationExecuted"])
        self.assertFalse(receipt["inferenceExecuted"])
        self.assertFalse(receipt["deploymentReady"])
        self.assertEqual(receipt["providerCallCount"], 0)
        self.assertEqual(receipt["augmentationVisualAudit"], "pending")
        for arm in ("control", "camera_aug"):
            manifest = json.loads((self.root / "paired" / arm / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["includesStudentPhotos"])
            self.assertEqual(manifest["evidenceClass"], "synthetic_public_training_preparation")
            self.assertIn("Historical writer/source/exact-image separation was not re-executed",
                          manifest["limitations"])

    def test_unapproved_bytes_and_audit_rejected_before_output(self):
        (self.source / "equations.txt").write_bytes(b"2\n\\frac{1}{2}\n\\sqrt{2}\n")
        with self.assertRaises(ValueError):
            self.run_prepare()
        self.assertFalse((self.root / "paired").exists())
        (self.source / "equations.txt").write_bytes(b"1\n\\frac{1}{2}\n\\sqrt{2}\n")
        self.audit.write_text("{}\n")
        with self.assertRaises(ValueError):
            self.run_prepare()
        self.assertFalse((self.root / "paired").exists())

    def test_declared_validation_holdout_or_student_photos_rejected(self):
        for update in ({"dataRole": "validation"}, {"dataRole": "release_holdout"},
                       {"includesStudentPhotos": True}, {"answerKeyFieldsUsed": 1}):
            manifest = {**self.manifest, **update}
            fixture_json(self.source / "manifest.json", manifest)
            self.expected["manifestSha256"] = fixture_hash(self.source / "manifest.json")
            with self.assertRaises(ValueError):
                self.run_prepare()
            self.assertFalse((self.root / "paired").exists())

    def test_extra_unknown_missing_and_image_binding_rejected(self):
        extra = self.source / "unknown.json"
        extra.write_text("{}")
        with self.assertRaises(ValueError):
            self.run_prepare()
        extra.unlink()
        provenance = self.source / "provenance.jsonl"
        rows = [json.loads(line) for line in provenance.read_text(encoding="utf-8").splitlines()]
        rows[0]["sourceImageSha256"] = "0" * 64
        provenance.write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.expected["provenanceSha256"] = fixture_hash(provenance)
        with self.assertRaises(ValueError):
            self.run_prepare()
        self.assertFalse((self.root / "paired").exists())

    def test_missing_image_or_unsupported_label_rejected(self):
        first = self.source / "images" / "0000000.png"
        before = first.read_bytes()
        first.unlink()
        with self.assertRaises(ValueError):
            self.run_prepare()
        first.write_bytes(before)
        annotation = self.source / "equations.txt"
        annotation.write_bytes(b"x+y\n\\frac{1}{2}\n\\sqrt{2}\n")
        self.expected["annotationSha256"] = fixture_hash(annotation)
        with self.assertRaises(ValueError):
            self.run_prepare()
        self.assertFalse((self.root / "paired").exists())

    def test_duplicate_manifest_key_rejected(self):
        manifest = self.source / "manifest.json"
        manifest.write_text('{"profile":"m3_h1","profile":"m3_h1"}\n', encoding="utf-8")
        self.expected["manifestSha256"] = fixture_hash(manifest)
        with self.assertRaises(ValueError):
            self.run_prepare()
        self.assertFalse((self.root / "paired").exists())

    def test_existing_or_nested_output_preserved(self):
        existing = self.root / "existing"
        existing.mkdir()
        marker = existing / "keep.txt"
        marker.write_bytes(b"user-owned")
        for output in (existing, self.source / "nested"):
            with self.assertRaises(ValueError):
                augmentation.prepare(self.source, self.audit, output, profile="m3_h1")
        self.assertEqual(marker.read_bytes(), b"user-owned")
        self.assertFalse((self.source / "nested").exists())
        self.assert_source_unchanged()

    def test_seed_and_path_rejections(self):
        for seed in (True, -1, 2**32, 2.5):
            with self.assertRaises(ValueError):
                self.run_prepare(seed=seed)
        for output in (self.root / "a" / ".." / "escape", self.root / "alternate:stream"):
            with self.assertRaises(ValueError):
                augmentation.prepare(self.source, self.audit, output, profile="m3_h1")
        self.assertFalse((self.root / "paired").exists())

    def test_changed_source_during_transform_has_no_success_receipt(self):
        original_transform = augmentation.camera_image
        def change_source(*args, **kwargs):
            result = original_transform(*args, **kwargs)
            (self.source / "equations.txt").write_bytes(b"2\n\\frac{1}{2}\n\\sqrt{2}\n")
            return result
        with mock.patch.object(augmentation, "camera_image", side_effect=change_source):
            with self.assertRaises(ValueError):
                self.run_prepare()
        self.assertFalse((self.root / "paired" / "AUGMENTATION_PREPARATION.json").exists())
        self.assertTrue((self.root / "paired" / "control" / "images" / "0000000.png").exists())

    def test_linked_input_or_output_ancestor_rejected(self):
        link = self.root / "linked"
        try:
            link.symlink_to(self.source, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"OS cannot create test symlink: {type(error).__name__}")
        with self.assertRaises(ValueError):
            augmentation.prepare(link, self.audit, self.root / "paired", profile="m3_h1")
        with self.assertRaises(ValueError):
            augmentation.prepare(self.source, self.audit, link / "output", profile="m3_h1")
        self.assertFalse((self.root / "paired").exists())
        self.assert_source_unchanged()


if __name__ == "__main__":
    unittest.main(verbosity=2)
