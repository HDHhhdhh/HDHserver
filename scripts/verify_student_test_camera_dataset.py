"""Independent literal, byte-contract fixtures; no camera/OCR/production data used."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import stat
import unittest
from unittest.mock import patch

from scripts import student_test_camera_dataset as camera
from scripts import prepare_student_test_camera_collection as collection


class CameraDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ocr-camera-contract-")
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.now = datetime.now(timezone.utc) - timedelta(minutes=2)
        self.intake = {"schema": "student_test_camera_intake_v1",
            "permissions": {"confirmed": True, "deidentified": True, "reference": "consent-record-01", "retentionReference": "retention-policy-01"},
            "review": {"reviewerId": "ReviewerA", "actualHandwriting": True,
                "blindTo": ["writingPrompts", "answerKeys", "modelOutputs"], "completedAt": self.now.isoformat()},
            "template": {key: self.ref(key, ("template-" + key).encode()) for key in ("pdf", "coordinates", "warpedReference")},
            "photos": []}
        for ordinal in (1, 2):
            original = self.ref(f"photo-{ordinal}", f"photo-{ordinal}".encode())
            questions, bindings = [], []
            for no in range(1, 21):
                crop = self.ref(f"crops/{ordinal}/{no}.png", f"independent-bytes-{ordinal}-{no}".encode())
                bindings.append({"questionNo": no, "cropSha256": crop["sha256"], "transform": {"fixtureCoordinates": [no, 0, 1, 1]}})
                questions.append({"questionNo": no, "answerMode": "choice_number" if no <= 5 else "answer_value",
                    "expressionKind": "integer" if no <= 5 else "fraction", "legibility": "readable",
                    "transcription": str(no) if no <= 5 else "1/2", "crop": crop})
            receipt = {"schema": "student_test_camera_crop_receipt_v1", "parentPhotoSha256": original["sha256"],
                "templateCoordinatesSha256": self.intake["template"]["coordinates"]["sha256"],
                "cropperCodeSha256": "a" * 64, "questions": bindings}
            receipt_ref = self.ref(f"receipt-{ordinal}.json", json.dumps(receipt).encode())
            self.intake["photos"].append({"writerId": "W001", "sheetId": "W001_A", "photoId": f"P{ordinal}",
                "captureOrdinal": ordinal, "studentGrade": "H_G2", "testCourse": "공통수학1", "split": "development",
                "original": original, "cropReceipt": receipt_ref, "questions": questions})

    def ref(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    def frozen(self):
        source = self.root / "INTAKE.json"
        source.write_bytes(camera.encoded(self.intake))
        out = self.root / "frozen"
        summary = camera.freeze(source, out)
        return camera.load_json((out / "FROZEN_LABELS.json").read_bytes()), summary["frozenLabelsSha256"]

    def scoring(self):
        frozen, sha = self.frozen()
        rows = [{"sampleId": r["sampleId"], "cropSha256": r["cropSha256"], "text": r["transcription"],
            "autoAccepted": True, "tokenCount": 4, "eosSeen": True, "modelSha256": "1" * 64,
            "modelRoute": "choice_number" if r["answerMode"] == "choice_number" else r["formulaProfile"]} for r in frozen["samples"]]
        run = {"schema": "student_test_camera_prediction_run_v1", "split": "development",
            "frozenLabelsSha256": sha, "executedAt": datetime.now(timezone.utc).isoformat(),
            "modelBindings": {route: {"checkpointSha256": "1" * 64, "architectureSha256": "4" * 64, "tokenizerSha256": "5" * 64} for route in ("choice_number", "m3_h1")},
            "inferenceCodeSha256": "2" * 64, "acceptancePolicySha256": "3" * 64,
            "providerCallCount": 0, "deploymentReady": False}
        return frozen, sha, rows, run

    def test_twenty_mixed_slots_each_photo_course_not_student_grade(self):
        result = camera.validate_intake(self.intake, self.root)
        self.assertEqual(result["counts"], {"writers": 1, "sheets": 1, "photos": 2, "slots": 40})
        self.assertEqual({r["formulaProfile"] for r in result["samples"]}, {"m3_h1"})
        self.assertEqual(sum(r["answerMode"] == "choice_number" for r in result["samples"]), 10)

    def test_permission_review_and_future_time_fail_closed(self):
        for key in ("confirmed", "deidentified"):
            item = deepcopy(self.intake)
            item["permissions"][key] = False
            with self.assertRaises(ValueError): camera.validate_intake(item, self.root)
        for value in ([], ["answerKeys", "modelOutputs"]):
            item = deepcopy(self.intake)
            item["review"]["blindTo"] = value
            with self.assertRaises(ValueError): camera.validate_intake(item, self.root)
        self.intake["review"]["completedAt"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError): camera.validate_intake(self.intake, self.root)

    def test_prompt_answer_key_model_output_never_become_intake(self):
        for key in ("answerKey", "correctAnswer", "writingPrompt", "modelOutput", "prediction"):
            item = deepcopy(self.intake)
            item["photos"][0]["questions"][0][key] = "3"
            with self.assertRaises(ValueError): camera.validate_intake(item, self.root)

    def test_blank_ambiguous_unsupported_stay_in_denominator(self):
        for status in ("blank", "ambiguous", "unsupported"):
            for photo in self.intake["photos"]:
                photo["questions"][5].update(legibility=status, transcription="")
            result = camera.validate_intake(self.intake, self.root)
            self.assertEqual(result["counts"]["slots"], 40)
            self.assertEqual(sum(r["supportedTarget"] for r in result["samples"]), 38)

    def test_readable_symbolic_text_not_numeric_or_safe_acceptance(self):
        for photo in self.intake["photos"]:
            photo["questions"][5].update(transcription="x", expressionKind="other")
        frozen, sha, rows, run = self.scoring()
        report = camera.score_saved(frozen, rows, run, sha)
        self.assertEqual(report["textExact"], 40)
        self.assertEqual(report["numericCorrect"], 38)
        self.assertEqual(report["falseAccepted"], 2)

    def test_question_missing_duplicate_or_boolean_rejected(self):
        for change in ("missing", "duplicate", "bool"):
            item = deepcopy(self.intake)
            if change == "missing": item["photos"][0]["questions"].pop()
            elif change == "duplicate": item["photos"][0]["questions"][1]["questionNo"] = 1
            else: item["photos"][0]["questions"][0]["questionNo"] = True
            with self.assertRaises(ValueError): camera.validate_intake(item, self.root)

    def test_writer_split_and_duplicate_photo_or_same_paper_labels_rejected(self):
        for key, value in (("split", "calibration"), ("writerId", "W002"), ("photoId", "P1"), ("captureOrdinal", 1)):
            item = deepcopy(self.intake)
            item["photos"][1][key] = value
            with self.assertRaises(ValueError): camera.validate_intake(item, self.root)
        self.intake["photos"][1]["questions"][5]["transcription"] = "2/3"
        with self.assertRaises(ValueError): camera.validate_intake(self.intake, self.root)

    def test_original_crop_and_receipt_hash_change_rejected(self):
        for ref in (self.intake["photos"][0]["original"], self.intake["photos"][0]["questions"][0]["crop"], self.intake["photos"][0]["cropReceipt"]):
            target = self.root / ref["path"]
            before = target.read_bytes()
            target.write_bytes(before + b"tampered")
            with self.assertRaises(ValueError): camera.validate_intake(self.intake, self.root)
            target.write_bytes(before)

    def test_unsafe_path_and_reparse_rejected(self):
        for name in ("../outside", "C:/outside", "crops/../pdf", "pdf:stream", "crops/CON.png", "pdf."):
            with self.assertRaises(ValueError): camera.asset(self.root, {"path": name, "sha256": "a" * 64})
        fake = type("Info", (), {"st_file_attributes": 0x400, "st_mode": stat.S_IFDIR})()
        with patch.object(Path, "lstat", return_value=fake):
            with self.assertRaises(ValueError): camera._plain(self.root)

    def test_json_duplicate_and_nonfinite_rejected(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError): camera.load_json(raw)

    def test_freeze_hides_labels_and_preserves_source_no_overwrite(self):
        frozen, _ = self.frozen()
        inputs = camera.load_json((self.root / "frozen/MODEL_INPUTS.json").read_bytes())
        self.assertEqual(len(inputs["samples"]), 40)
        for row in inputs["samples"]:
            self.assertNotIn("transcription", row)
            self.assertNotIn("expressionKind", row)
            self.assertNotIn("studentGrade", row)
        self.assertEqual(frozen["counts"]["slots"], 40)
        self.assertTrue(all("frozen" in row["cropPath"] for row in inputs["samples"]))
        source_crop = self.root / self.intake["photos"][0]["questions"][0]["crop"]["path"]
        source_crop.write_bytes(b"source changed after freeze")
        self.assertEqual(Path(inputs["samples"][0]["cropPath"]).read_bytes(), b"independent-bytes-1-1")
        with self.assertRaises(ValueError): camera.freeze(self.root / "INTAKE.json", self.root / "frozen")

    def test_fixed_numeric_text_cap_eos_false_acceptance(self):
        frozen, sha, rows, run = self.scoring()
        rows[5]["text"] = "0.5"
        rows[6]["tokenCount"] = 64  # EOS at cap is still a generation failure.
        report = camera.score_saved(frozen, rows, run, sha)
        self.assertEqual(report["denominator"], 40)
        self.assertEqual(report["numericCorrect"], 39)
        self.assertEqual(report["textExact"], 38)
        self.assertEqual(report["numericFailures"], 1)
        self.assertEqual(report["generationFailures"], 1)
        self.assertEqual(report["falseAccepted"], 1)
        self.assertEqual(report["coverage"], 1)
        self.assertEqual(report["firstPassPhotos"]["allTwentySafelyAccepted"], 1)

    def test_missing_duplicate_unknown_hash_and_eos_metadata_rejected(self):
        frozen, sha, rows, run = self.scoring()
        bad = deepcopy(rows); bad.pop()
        with self.assertRaises(ValueError): camera.score_saved(frozen, bad, run, sha)
        for update in ({"sampleId": "P1:01"}, {"sampleId": "unknown"}, {"cropSha256": "0" * 64}, {"eosSeen": None}):
            bad = deepcopy(rows); bad[5].update(update)
            with self.assertRaises(ValueError): camera.score_saved(frozen, bad, run, sha)

    def test_uncertainty_firstpass_and_latency_not_pending_inference(self):
        frozen, sha, rows, run = self.scoring()
        for index in (0, 1, 2, 3, 20, 21): rows[index]["autoAccepted"] = False
        run["latency"] = {"scope": "crop_inference_only", "photoSeconds": {"P1": 1.5, "P2": 2.0}}
        report = camera.score_saved(frozen, rows, run, sha)
        self.assertEqual(report["firstPassPhotos"]["retakeFourOrMore"], 1)
        self.assertEqual(report["firstPassPhotos"]["supplementOneToThree"], 1)
        self.assertEqual(report["latency"]["p90Seconds"], 2.0)
        self.assertIn("not_measured", report["pendingAfterRecapture"])

    def test_score_timestamp_offsets_release_and_code_gates(self):
        frozen, sha, rows, run = self.scoring()
        run["executedAt"] = (camera._aware(frozen["frozenAt"]) - timedelta(seconds=1)).astimezone(timezone(timedelta(hours=9))).isoformat()
        with self.assertRaises(ValueError): camera.score_saved(frozen, rows, run, sha)
        run["executedAt"] = datetime.now(timezone.utc).isoformat()
        frozen["normalizerCodeSha256"] = "0" * 64
        with self.assertRaises(ValueError): camera.score_saved(frozen, rows, run, sha)

    def test_holdout_cannot_export_and_model_route_cannot_change(self):
        frozen, sha, rows, run = self.scoring()
        rows[5]["modelRoute"] = "m3_h1_h2_h3"
        with self.assertRaises(ValueError): camera.score_saved(frozen, rows, run, sha)
        for photo in self.intake["photos"]: photo["split"] = "release_holdout"
        source = self.root / "release.json"
        source.write_bytes(camera.encoded(self.intake))
        out = self.root / "release-output"
        with self.assertRaises(ValueError): camera.freeze(source, out)
        self.assertFalse(out.exists())

    def test_changed_crop_between_validation_and_copy_has_no_success_labels(self):
        source = self.root / "race-intake.json"
        source.write_bytes(camera.encoded(self.intake))
        original = camera.validate_intake
        def change_after_validation(*args, **kwargs):
            result = original(*args, **kwargs)
            ref = self.intake["photos"][0]["questions"][0]["crop"]
            (self.root / ref["path"]).write_bytes(b"changed during freeze")
            return result
        with patch.object(camera, "validate_intake", side_effect=change_after_validation):
            with self.assertRaises(ValueError): camera.freeze(source, self.root / "race-output")
        self.assertFalse((self.root / "race-output/FROZEN_LABELS.json").exists())

    def test_template_copy_fault_never_claims_unchanged(self):
        template_root = self.root / "templates"
        template_root.mkdir()
        hashes = {}
        for name in collection.V4:
            path = template_root / name
            path.write_bytes(name.encode())
            hashes[name] = camera.digest(path)
        real_copy = collection.shutil.copyfile
        def broken_copy(source, target):
            real_copy(source, target)
            Path(target).write_bytes(b"faulted-copy")
        out = self.root / "failed-kit"
        with patch.dict(collection.V4, hashes, clear=True), patch.object(collection.shutil, "copyfile", side_effect=broken_copy):
            with self.assertRaises(ValueError): collection.prepare(template_root, out)
        self.assertFalse((out / "KIT_MANIFEST.json").exists())

    def test_collection_kit_no_generated_ground_truth_and_same_template_bytes(self):
        templates = {name: camera.digest(self.root / key) for key, name in (("pdf", "answer_sheet_v4.pdf"),
            ("coordinates", "answer_sheet_v4_coordinates.json"), ("warpedReference", "answer_sheet_v4_warped_reference.png"))}
        template_root = self.root / "v4"
        template_root.mkdir()
        for key, name in (("pdf", "answer_sheet_v4.pdf"), ("coordinates", "answer_sheet_v4_coordinates.json"), ("warpedReference", "answer_sheet_v4_warped_reference.png")):
            (template_root / name).write_bytes((self.root / key).read_bytes())
        out = self.root / "kit"
        with patch.dict(collection.V4, templates, clear=True): collection.prepare(template_root, out)
        intake = camera.load_json((out / "INTAKE_TEMPLATE.json").read_bytes())
        self.assertEqual(len(intake["photos"]), 48)
        self.assertTrue(all(q["transcription"] == "" and q["legibility"] == "UNREVIEWED" for p in intake["photos"] for q in p["questions"]))
        self.assertFalse(intake["permissions"]["confirmed"])
        self.assertEqual(len(list((out / "writer_guides").iterdir())), 24)
        self.assertNotEqual((out / "writer_guides/W001.txt").read_bytes(), (out / "writer_guides/W002.txt").read_bytes())
        self.assertEqual((out / "template/answer_sheet_v4.pdf").read_bytes(), (template_root / "answer_sheet_v4.pdf").read_bytes())
        with self.assertRaises(ValueError): camera.validate_intake(intake, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
