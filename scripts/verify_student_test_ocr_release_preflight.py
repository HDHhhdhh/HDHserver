"""Literal saved-output and CLI fixtures; no OCR, holdout or live service execution."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from core.student_test_ocr_engine import ConfidencePolicy

from scripts import check_student_test_ocr_release as release
from scripts import student_test_camera_dataset as camera
from scripts import verify_student_test_camera_dataset as fixtures


class ReleasePreflightTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CameraDatasetTests("test_twenty_mixed_slots_each_photo_course_not_student_grade")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.frozen, self.sha, self.rows, self.run = self.fixture.scoring()
        self.frozen_path = self.root / "frozen/FROZEN_LABELS.json"
        self.predictions = self.root / "predictions.jsonl"
        self.run_path = self.root / "RUN.json"
        self.save()

    def save(self):
        self.frozen_path.write_bytes(camera.encoded(self.frozen))
        self.sha = camera.digest(self.frozen_path)
        self.run["frozenLabelsSha256"] = self.sha
        self.predictions.write_text("".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf-8")
        self.run_path.write_bytes(camera.encoded(self.run))

    def review(self):
        return release.review_saved_camera(self.frozen_path, self.predictions, self.run_path)

    def test_routes_split_choices_before_profile_and_first_photo_only(self):
        result = self.review()
        self.assertEqual(result["fixedDenominator"], 40)
        self.assertEqual(result["routes"]["choice"]["denominator"], 10)
        self.assertEqual(result["routes"]["m3_h1"]["denominator"], 30)
        self.assertEqual(result["choiceTargetClasses"], {str(n): 2 for n in range(1, 6)})
        self.assertEqual(result["formulaKinds"], {"m3_h1": {"fraction": 30}})
        first = result["firstCaptureDiagnostic"]
        self.assertEqual(first["denominator"], 1)
        self.assertEqual(first["predictedAllTwentyAccepted"], 1)
        self.assertTrue(first["secondPhotographExcluded"])
        self.assertFalse(result["deploymentReady"])
        self.assertIn("not_measured", result["pendingAfterRecapture"])

    def test_second_photo_acceptance_cannot_change_first_photo_metric(self):
        for row in self.rows[20:]: row["autoAccepted"] = False
        self.save()
        result = self.review()
        self.assertEqual(result["firstCaptureDiagnostic"]["predictedAllTwentyAccepted"], 1)
        self.assertEqual(result["routes"]["choice"]["autoAccepted"], 5)

    def test_first_photo_uncertainty_count_and_wrong_accept_not_success_proof(self):
        self.rows[0]["text"] = "5"  # Confident wrong number must remain falseAccepted.
        for row in self.rows[1:5]: row["autoAccepted"] = False
        self.save()
        result = self.review()
        self.assertEqual(result["routes"]["choice"]["falseAccepted"], 1)
        self.assertEqual(result["firstCaptureDiagnostic"]["predictedUncertaintyFourOrMore"], 1)
        self.assertFalse(result["deploymentReady"])

    def test_cap64_eos_failure_stays_in_denominator(self):
        self.rows[5]["tokenCount"] = 64
        self.save()
        result = self.review()
        formula = result["routes"]["m3_h1"]
        self.assertEqual(formula["denominator"], 30)
        self.assertEqual(formula["generationFailures"], 1)
        self.assertEqual(formula["numericFailures"], 1)
        self.assertEqual(formula["falseAccepted"], 1)

    def test_missing_duplicate_model_changed_and_snapshot_changed_rejected(self):
        original = deepcopy(self.rows)
        for kind in ("missing", "duplicate", "model"):
            self.rows = deepcopy(original)
            if kind == "missing": self.rows.pop()
            elif kind == "duplicate": self.rows[1]["sampleId"] = self.rows[0]["sampleId"]
            else: self.rows[0]["modelSha256"] = "9" * 64
            self.save()
            with self.assertRaises(ValueError): self.review()
        self.rows = original
        self.save()
        Path(self.frozen["samples"][0]["cropPath"]).write_bytes(b"changed snapshot")
        with self.assertRaises(ValueError): self.review()

    def test_legacy_ordinal_missing_is_not_guessed_from_photo_id(self):
        for row in self.frozen["samples"]: row.pop("captureOrdinal")
        self.save()
        result = self.review()
        self.assertEqual(result["firstCaptureDiagnostic"]["status"], "unverified_capture_ordinal_missing")
        self.assertNotIn("denominator", result["firstCaptureDiagnostic"])

    def test_bad_photo_pair_ordinals_or_half_paper_rejected(self):
        original = deepcopy(self.frozen)
        original_rows = deepcopy(self.rows)
        for kind in ("both-one", "both-two", "half", "writer", "split", "mixed-unknown"):
            self.frozen, self.rows = deepcopy(original), deepcopy(original_rows)
            if kind == "half":
                self.frozen["samples"] = self.frozen["samples"][:20]
                self.rows = self.rows[:20]
                self.frozen["counts"].update(photos=1, slots=20)
            else:
                for row in self.frozen["samples"]:
                    if kind == "both-one": row["captureOrdinal"] = 1
                    elif kind == "both-two": row["captureOrdinal"] = 2
                    elif row["photoId"] == "P2":
                        if kind == "writer": row["writerId"] = "W002"
                        elif kind == "split": row["split"] = "calibration"
                        else: row.pop("captureOrdinal")
            self.save()
            with self.assertRaises(ValueError): self.review()

    def test_kind_mapping_uses_human_transcription_not_model_prediction(self):
        for row in self.frozen["samples"]:
            if row["questionNo"] == 6:
                row.update(transcription="(1+sqrt(2))/3", expressionKind="two_term")
        for row in self.rows:
            if row["sampleId"].endswith(":06"): row["text"] = "3"
        self.save()
        result = self.review()
        self.assertEqual(result["formulaKinds"]["m3_h1"], {"fraction": 30, "root": 2})
        self.assertEqual(result["routes"]["m3_h1"]["falseAccepted"], 2)

    def test_crop_only_latency_and_successful_contract_can_never_make_go(self):
        self.run["latency"] = {"scope": "crop_inference_only", "photoSeconds": {"P1": .1, "P2": .2}}
        self.save()
        with patch.object(release, "load_student_test_ocr_config") as loader:
            config = loader.return_value
            config.readiness_report.return_value = {"installed": True, "deploymentReady": True, "reasons": []}
            config.enabled = config.maintenance_enabled = config.allow_unready_models = False
            config.confidence_policy = ConfidencePolicy()
            result = release.inspect_release(project_root=self.root,
                camera_paths=(self.frozen_path, self.predictions, self.run_path))
        self.assertFalse(result["deploymentReady"])
        self.assertEqual(result["status"], "NO_GO_PREPARATION_ONLY")
        self.assertEqual(result["cameraReview"]["reportedLatency"]["scope"], "crop_inference_only")
        self.assertTrue(any("end-to-end" in gate for gate in result["unverifiedReleaseGates"]))
        self.assertEqual(result["providerCallCount"], 0)
        self.assertFalse(result["rolloutAuthorized"])

    def test_frozen_duplicate_missing_and_outside_crop_cannot_change_denominator(self):
        original = deepcopy(self.frozen)
        for change in ("duplicate", "missing", "outside", "count"):
            self.frozen = deepcopy(original)
            if change == "duplicate": self.frozen["samples"].append(deepcopy(self.frozen["samples"][0]))
            elif change == "missing": self.frozen["samples"].pop()
            elif change == "outside": self.frozen["samples"][0]["cropPath"] = str(self.root / "outside.png")
            else: self.frozen["counts"]["slots"] = 39
            self.save()
            with self.assertRaises(ValueError): self.review()

    def test_cli_zero_exit_means_preparation_not_go_no_operational_writes(self):
        output = self.root / "preflight-output"
        environment = {**os.environ, "STUDENT_TEST_OCR_RUNTIME_ROOT": str(self.root / "missing-runtime"),
            "DB_PATH": str(self.root / "must-not-open.sqlite"), "PYTHONUTF8": "1"}
        command = [sys.executable, "-B", "-m", "scripts.check_student_test_ocr_release",
            "--project-root", str(self.root), "--output", str(output)]
        proc = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = camera.load_json((output / "RELEASE_PREFLIGHT.json").read_bytes())
        self.assertEqual(report["status"], "NO_GO_PREPARATION_ONLY")
        self.assertFalse(report["deploymentReady"])
        self.assertEqual(report["cameraReview"]["status"], "not_supplied")
        self.assertFalse((self.root / "must-not-open.sqlite").exists())
        self.assertFalse((self.root / "instance").exists())
        self.assertFalse((self.root / "missing-runtime").exists())
        before = (output / "RELEASE_PREFLIGHT.json").read_bytes()
        retry = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertNotEqual(retry.returncode, 0)
        self.assertEqual((output / "RELEASE_PREFLIGHT.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
