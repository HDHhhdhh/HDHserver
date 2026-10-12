"""OS-temp byte fixtures for release bindings, not OCR accuracy or deployment proof."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import student_test_ocr_config as config_module
from core.student_test_ocr_readiness import (
    RELEASE_CODE_FILES, deployment_artifacts, deployment_evidence_reasons,
)

# Literal oracle: do not derive expected scope from RELEASE_CODE_FILES.
EXPECTED_RELEASE_FILES = (
    "app.py", "routes/api_student_test_ocr.py", "routes/pages.py",
    "core/student_test_ocr_config.py", "core/student_test_ocr_engine.py",
    "core/student_test_ocr_rules.py", "core/student_test_formula_profiles.py",
    "core/student_test_ocr_readiness.py", "core/student_test_ocr_job_runner.py",
    "core/student_test_ocr_context.py", "core/student_test_ocr_service.py",
    "core/student_test_ocr_repository.py", "core/student_test_ocr_worker_pool.py",
    "core/student_test_ocr_assets.py", "core/student_test_ocr_maintenance.py",
    "core/student_test_sheet_cropper.py", "core/student_test_ocr_eligibility.py",
    "core/student_test_solution_crop.py",
    "static/student-test-capture.html", "static/js/student-test-capture.js",
    "static/js/student-test-capture-geometry.js", "static/css/student-test-ocr.css",
    "static/js/shared/api.js", "static/js/student-test-ocr-launcher.js", "static/student.html",
)
EXPECTED_MODEL_ASSETS = (
    "config.json", "preprocessor_config.json", "tokenizer_config.json", "tokenizer.json",
)
MUTATION_TARGETS = (
    "static/student-test-capture.html", "static/js/student-test-capture.js",
    "static/js/student-test-capture-geometry.js", "static/css/student-test-ocr.css",
    "static/js/shared/api.js", "static/js/student-test-ocr-launcher.js", "static/student.html",
    "routes/pages.py", "core/student_test_sheet_cropper.py", "routes/api_student_test_ocr.py",
)


class ReleaseArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ocr-release-artifacts-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.code, self.runtime = self.root / "code", self.root / "runtime"
        for name in EXPECTED_RELEASE_FILES:
            self.write(self.code / name, ("literal-code-fixture:" + name).encode())
        self.required = [self.runtime / "python.exe", self.runtime / "weights/choice.bin",
                         self.runtime / "template/blank.png", self.code / "scripts/worker.py"]
        for item in self.required:
            self.write(item, ("literal-runtime-fixture:" + item.name).encode())
        self.model_dirs = (self.runtime / "paddle", self.runtime / "formula")
        self.model_files = []
        for directory in self.model_dirs:
            for name in ("config.json", "nested/model.bin", "nested/tokenizer.json"):
                item = directory / name
                self.write(item, (directory.name + ":" + name).encode())
                self.model_files.append(item)
        self.artifacts = deployment_artifacts(required_files=tuple(self.required),
            code_root=self.code, model_directories=self.model_dirs)
        # GO-shaped parser fixture only: no actual release approval or camera evidence.
        self.policy = {"threshold": 0.995}
        route = {"evaluated": 300, "accepted": 299, "wrongAccepted": 0,
                 "kinds": {"number": 200, "fraction": 50, "root": 50}}
        self.evidence = {
            "schema": "student_test_ocr_deployment_evidence_v1", "status": "GO",
            "evidenceClass": "independent_v4_camera_holdout", "policy": self.policy,
            "holdout": {"writerDisjoint": True, "labelsCheckedAgainstImages": True,
                "lockedBeforeEvaluation": True, "notUsedForTuning": True,
                "writerClusterReviewPassed": True, "manifestSha256": "a" * 64},
            "routes": {"choice": {**route, "rejectEvaluated": 20, "rejectCorrect": 20,
                "perChoiceClass": {label: 60 for label in "12345"}},
                "m3_h1": deepcopy(route), "m3_h1_h2_h3": deepcopy(route)},
            "sheetMetrics": {"p90Seconds": 25, "firstCaptureSuccessRate": 0.95,
                "fullRetakeRate": 0.03, "pendingRate": 0.01},
            "artifactSha256": {key: self.sha(path) for key, path in self.artifacts.items()},
        }
        self.evidence_path = self.root / "synthetic-evidence.json"

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def reasons(self, evidence=None):
        self.evidence_path.write_text(json.dumps(evidence or self.evidence), encoding="utf-8")
        return deployment_evidence_reasons(self.evidence_path, artifacts=self.artifacts,
            policy=self.policy, profiles=("m3_h1", "m3_h1_h2_h3"))

    def test_literal_release_scope_and_no_duplicates(self):
        self.assertEqual(set(RELEASE_CODE_FILES), set(EXPECTED_RELEASE_FILES))
        self.assertEqual(len(RELEASE_CODE_FILES), len(set(RELEASE_CODE_FILES)))
        expected = {str(path.resolve()) for path in self.required + self.model_files}
        expected.update(str((self.code / name).resolve()) for name in EXPECTED_RELEASE_FILES)
        self.assertEqual(set(self.artifacts), expected)

    def test_independent_hash_fixture_matches_contract(self):
        self.assertEqual(self.reasons(), [])
        self.assertTrue(all(path.is_relative_to(self.root) for path in self.artifacts.values()))

    def test_frontend_transform_transport_route_and_crop_mutations_block(self):
        self.assertEqual(self.reasons(), [])
        for name in MUTATION_TARGETS:
            with self.subTest(path=name):
                path = self.code / name
                original = path.read_bytes()
                path.write_bytes(original + b":changed")
                self.assertEqual(self.reasons(), ["artifact_changed:" + str(path.resolve())])
                path.write_bytes(original)
                self.assertEqual(self.reasons(), [])

    def test_pre_frontend_evidence_map_is_incomplete(self):
        candidate = deepcopy(self.evidence)
        for name in EXPECTED_RELEASE_FILES:
            if name.startswith("static/"):
                candidate["artifactSha256"].pop(str((self.code / name).resolve()))
        self.assertEqual(self.reasons(candidate), ["artifact_evidence_incomplete"])

    def test_missing_bound_source_is_unavailable(self):
        path = self.code / "static/js/student-test-capture-geometry.js"
        path.unlink()
        self.assertEqual(self.reasons(), ["artifact_unavailable:" + str(path.resolve())])

    def test_runtime_and_nested_model_files_remain_bound(self):
        for path in self.required + self.model_files:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b":changed")
                self.assertEqual(self.reasons(), ["artifact_changed:" + str(path.resolve())])
                path.write_bytes(original)

    def test_required_duplicates_deduplicate_without_mutating_inputs(self):
        required = [*self.required, self.required[0]]
        before = list(required)
        result = deployment_artifacts(required_files=required, code_root=self.code,
                                      model_directories=self.model_dirs)
        self.assertEqual(result, self.artifacts)
        self.assertEqual(required, before)

    def config_fixture(self):
        runtime_names = [
            ".venv/Scripts/python.exe", ".venv-unimernet/Scripts/python.exe",
            "choice_digit_classifier_v3/choice_digit_v3.pt",
            "models/unimernet_tiny/unimernet_tiny.pth",
            "models/unimernet_m3_h1/unimernet_m3_h1.pth",
            "models/unimernet_m3_h1_h2_h3/unimernet_m3_h1_h2_h3.pth",
            "answer_sheet_v4/answer_sheet_v4_warped_reference.png",
        ]
        for model in ("unimernet_tiny", "unimernet_m3_h1", "unimernet_m3_h1_h2_h3"):
            runtime_names += ["models/" + model + "/" + name for name in EXPECTED_MODEL_ASSETS]
        tree_names = [
            "paddlex-cache/official_models/korean_PP-OCRv5_mobile_rec/model.bin",
            "paddlex-cache/official_models/korean_PP-OCRv5_mobile_rec/nested/tokenizer.json",
            "paddlex-cache/official_models/PP-FormulaNet-S/model.bin",
            "paddlex-cache/official_models/PP-FormulaNet-S/nested/settings.json",
        ]
        worker_names = [
            "scripts/student_test_sheet_crop_worker.py", "scripts/student_test_choice_worker.py",
            "scripts/student_test_paddle_worker.py", "scripts/student_test_formula_worker.py",
            "scripts/student_test_unimernet_worker.py", "scripts/student_test_formula_inference.py",
            "scripts/student_test_ocr_worker_server.py",
        ]
        for name in runtime_names + tree_names:
            self.write(self.runtime / name, ("config-runtime-fixture:" + name).encode())
        for name in worker_names:
            self.write(self.code / name, ("config-worker-fixture:" + name).encode())
        model_path = self.runtime / "choice_digit_classifier_v3/choice_digit_v3.pt"
        (model_path.parent / "metrics.json").write_text(json.dumps({"ok": True,
            "checkpoint": str(model_path), "readiness": {"status": "NO_GO"},
            "answerKeyFieldsUsed": 0, "providerCallCount": 0}), encoding="utf-8")
        environment = {"STUDENT_TEST_OCR_RUNTIME_ROOT": str(self.runtime),
            "STUDENT_TEST_OCR_DEPLOYMENT_EVIDENCE": str(self.root / "unreviewed.json"),
            "DB_PATH": str(self.root / "never-opened.sqlite")}
        with patch.dict(os.environ, environment, clear=True):
            config = config_module.load_student_test_ocr_config(project_root=self.code)
        expected = {str((self.runtime / name).resolve()) for name in runtime_names + tree_names}
        expected.update(str((self.code / name).resolve()) for name in worker_names + list(EXPECTED_RELEASE_FILES))
        return config, expected

    def test_actual_config_submits_full_literal_artifact_scope(self):
        config, expected = self.config_fixture()
        calls = []
        def observe(path, *, artifacts, policy, profiles):
            calls.append((path, dict(artifacts), dict(policy), tuple(profiles)))
            return ["synthetic_release_unreviewed"]
        with patch.object(config_module, "__file__", str(self.code / "core/student_test_ocr_config.py")), \
                patch.object(config_module, "deployment_evidence_reasons", side_effect=observe):
            result = config.readiness_report()
        self.assertEqual(len(calls), 1)
        path, artifacts, policy, profiles = calls[0]
        self.assertEqual(set(artifacts), expected)
        self.assertTrue(all(value.is_relative_to(self.root) and value.is_file() for value in artifacts.values()))
        self.assertEqual(path, self.root / "unreviewed.json")
        self.assertEqual(set(profiles), {"m3_h1", "m3_h1_h2_h3"})
        self.assertEqual(policy["choice_digit_minimum"], 0.995)
        self.assertEqual(policy["choice_digit_margin_minimum"], 0.90)
        self.assertEqual(result, {"installed": True, "deploymentReady": False,
            "reasons": ["choice_training_gate_not_met", "synthetic_release_unreviewed"]})
        self.assertFalse(config.enabled)
        self.assertFalse(config.maintenance_enabled)
        self.assertFalse(config.db_path.exists())
        self.assertFalse(config.asset_root.exists())

    def test_actual_config_missing_profile_tokenizer_stops_before_review(self):
        config, _ = self.config_fixture()
        missing = self.runtime / "models/unimernet_m3_h1/tokenizer.json"
        missing.unlink()
        with patch.object(config_module, "deployment_evidence_reasons") as review:
            result = config.readiness_report()
        review.assert_not_called()
        self.assertEqual(result, {"installed": False, "deploymentReady": False,
                                 "reasons": ["runtime_assets_missing"]})
        self.assertFalse(config.db_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
