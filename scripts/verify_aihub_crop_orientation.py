"""Temporary synthetic geometry regressions; no app, datasets, or API calls."""
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageOps

from scripts.import_aihub_education_choice_dataset import annotation_image, convert as choice_convert, ink_square
from scripts.import_aihub_education_formula_dataset import convert as formula_convert


class OrientationChecks(unittest.TestCase):
    def image(self):
        image = Image.new("RGB", (120, 80), "white")
        ImageDraw.Draw(image).rectangle((12, 8, 36, 30), fill="black")
        return image

    def test_all_eight_orientations_follow_exif_pixel_mapping(self):
        transforms = {1: None, 2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
                      4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
                      6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}
        for orientation, transform in transforms.items():
            with self.subTest(orientation=orientation):
                source = self.image()
                source.getexif()[274] = orientation
                expected = source.transpose(transform) if transform is not None else source.copy()
                actual, _, observed = annotation_image(source, {"Images": {"width": expected.width, "height": expected.height}})
                self.assertEqual(observed, orientation)
                self.assertEqual(actual.size, expected.size)
                self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_raw_annotation_frame_preserved_and_mismatch_rejected(self):
        source = self.image()
        source.getexif()[274] = 6
        actual, frame, _ = annotation_image(source, {"Images": {"width": 120, "height": 80}})
        self.assertEqual(frame, "raw_annotation_frame")
        self.assertEqual(actual.tobytes(), source.tobytes())
        with self.assertRaises(ValueError):
            annotation_image(source, {"Images": {"width": 121, "height": 80}})

    def test_no_metadata_preserves_unrotated_pixels(self):
        source = self.image()
        actual, frame, _ = annotation_image(source, {})
        self.assertEqual(frame, "unchanged")
        self.assertEqual(actual.tobytes(), source.tobytes())

    def test_actual_importers_crop_upright_frame_and_preserve_source(self):
        import hashlib
        with tempfile.TemporaryDirectory(prefix="ocr-orientation-") as temporary:
            root = Path(temporary)
            labels, images = root / "labels", root / "images"
            labels.mkdir()
            images.mkdir()
            upright = self.image()
            raw = upright.transpose(Image.Transpose.ROTATE_90)
            raw.getexif()[274] = 6
            source = images / "page.png"
            raw.save(source, exif=raw.getexif())
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            payload = {"Dataset": {"label_path": "OCR(edu)/H/G2"},
                       "Images": {"identifier": "page", "type": "png", "width": 120, "height": 80, "make_id": "fixture"},
                       "Bbox": [{"id": 1, "type": 2, "data": "1", "x": [10, 40], "y": [6, 34]}]}
            (labels / "page.json").write_text(json.dumps(payload), encoding="utf-8")
            f = formula_convert(grade="H_G2", labels_root=labels, images_root=images, output_root=root / "formula", padding_ratio=0)
            c = choice_convert(labels_root=labels, images_root=images, output_root=root / "choice", padding_ratio=0,
                               choice_limit=0, reject_limit=0, minimum_side=1)
            self.assertEqual(f["count"], 1)
            self.assertEqual(c["counts"]["1"], 1)
            self.assertEqual(f["imageCoordinateFrames"], {"exif_upright": 1})
            expected = ImageOps.autocontrast(ImageOps.grayscale(upright.crop((10, 6, 41, 35)))).convert("RGB")
            with Image.open(next((root / "formula/images").glob("*.png"))) as actual:
                self.assertEqual(actual.tobytes(), expected.tobytes())
            expected_choice = ink_square(upright, (10, 6, 41, 35))
            with Image.open(next((root / "choice/1").glob("*.png"))) as actual:
                self.assertEqual(actual.tobytes(), expected_choice.tobytes())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            with self.assertRaises(ValueError):
                formula_convert(grade="H_G2", labels_root=labels, images_root=images, output_root=root / "formula")
            with self.assertRaises(ValueError):
                choice_convert(labels_root=labels, images_root=images, output_root=root / "choice", padding_ratio=0,
                               choice_limit=0, reject_limit=0, minimum_side=1)


if __name__ == "__main__":
    unittest.main()
