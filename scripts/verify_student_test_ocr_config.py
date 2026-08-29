from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from core.student_test_formula_profiles import FORMULA_PROFILE_COMMON, FORMULA_PROFILE_UPPER
from core.student_test_ocr_config import load_student_test_ocr_config


def run() -> dict:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="student-test-ocr-config-") as temp_dir:
        root = Path(temp_dir)
        with patch.dict(os.environ, {}, clear=True):
            config = load_student_test_ocr_config(project_root=root)
        assert config.enabled is False
        assert config.db_path == (root / "app.sqlite").resolve()
        assert config.asset_root == (root / "instance" / "student-test-ocr").resolve()
        assert config.solution_pdf_root == (root / ".codex_drive_download" / "unit_answer_pdfs").resolve()
        assert config.confidence_policy.choice_paddle_minimum == 0.98
        assert config.confidence_policy.choice_digit_minimum == 0.995
        assert config.confidence_policy.require_choice_cross_engine_agreement is False
        assert config.confidence_policy.unimernet_token_minimum == 0.995
        assert config.allow_unready_models is False
        assert config.runtime_available() is False
        assertions += 10

        with patch.dict(
            os.environ,
            {
                "STUDENT_TEST_OCR_ENABLED": "true",
                "STUDENT_TEST_OCR_DEVICE": "cuda",
                "STUDENT_TEST_OCR_CHOICE_CONFIDENCE": "0.999",
                "STUDENT_TEST_OCR_FORMULA_CONFIDENCE": "0.997",
                "STUDENT_TEST_OCR_REQUIRE_SECOND_PASS": "1",
                "STUDENT_TEST_OCR_SOLUTION_PDF_ROOT": str(root / "official-solutions"),
            },
            clear=True,
        ):
            configured = load_student_test_ocr_config(project_root=root)
        assert configured.enabled is True
        assert configured.paddle_worker.environment["STUDENT_TEST_OCR_DEVICE"] == "cuda"
        assert configured.unimernet_worker.environment["STUDENT_TEST_OCR_DEVICE"] == "cuda"
        assert configured.unimernet_worker.environment["STUDENT_TEST_OCR_UNIMERNET_VARIANT_PASS"] == "1"
        assert configured.unimernet_worker_for_profile(FORMULA_PROFILE_COMMON).environment[
            "STUDENT_TEST_OCR_FORMULA_DATA_PROFILE"
        ] == FORMULA_PROFILE_COMMON
        assert configured.unimernet_worker_for_profile(FORMULA_PROFILE_UPPER).environment[
            "STUDENT_TEST_OCR_FORMULA_DATA_PROFILE"
        ] == FORMULA_PROFILE_UPPER
        assert configured.confidence_policy.choice_paddle_minimum == 0.999
        assert configured.confidence_policy.unimernet_token_minimum == 0.997
        assert configured.confidence_policy.require_unimernet_variant_agreement is True
        assert configured.solution_pdf_root == (root / "official-solutions").resolve()
        assertions += 10

        custom_choice_model = root / "pilot-models" / "choice_digit_v4.pt"
        with patch.dict(
            os.environ,
            {"STUDENT_TEST_OCR_CHOICE_MODEL_PATH": str(custom_choice_model)},
            clear=True,
        ):
            custom_choice = load_student_test_ocr_config(project_root=root)
        assert custom_choice.choice_worker.environment["STUDENT_TEST_OCR_CHOICE_MODEL_PATH"] == str(
            custom_choice_model.resolve()
        )
        assertions += 1

        runtime_root = root / "ocr-runtime"
        for path in (
            runtime_root / ".venv" / "Scripts" / "python.exe",
            runtime_root / ".venv-unimernet" / "Scripts" / "python.exe",
            runtime_root / "choice_digit_classifier_v3" / "choice_digit_v3.pt",
            runtime_root / "models" / "unimernet_tiny" / "unimernet_tiny.pth",
            runtime_root / "models" / "unimernet_m3_h1" / "unimernet_m3_h1.pth",
            runtime_root / "models" / "unimernet_m3_h1_h2_h3" / "unimernet_m3_h1_h2_h3.pth",
            runtime_root / "answer_sheet_v4" / "answer_sheet_v4_warped_reference.png",
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        for directory in (
            runtime_root / "paddlex-cache" / "official_models" / "korean_PP-OCRv5_mobile_rec",
            runtime_root / "paddlex-cache" / "official_models" / "PP-FormulaNet-S",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        scripts_dir = root / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        for filename in (
            "student_test_sheet_crop_worker.py",
            "student_test_choice_worker.py",
            "student_test_paddle_worker.py",
            "student_test_formula_worker.py",
            "student_test_unimernet_worker.py",
        ):
            (scripts_dir / filename).write_text("# fixture\n", encoding="utf-8")

        model_path = runtime_root / "choice_digit_classifier_v3" / "choice_digit_v3.pt"
        metrics_path = model_path.parent / "metrics.json"
        metrics = {
            "ok": True,
            "checkpoint": str(model_path),
            "readiness": {"status": "NO_GO"},
            "answerKeyFieldsUsed": 0,
            "providerCallCount": 0,
        }
        metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
        base_environment = {
            "STUDENT_TEST_OCR_ENABLED": "1",
            "STUDENT_TEST_OCR_RUNTIME_ROOT": str(runtime_root),
        }
        with patch.dict(os.environ, base_environment, clear=True):
            no_go = load_student_test_ocr_config(project_root=root)
        assert no_go.runtime_available() is False
        assertions += 1

        metrics["readiness"]["status"] = "GO"
        metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
        with patch.dict(os.environ, base_environment, clear=True):
            ready = load_student_test_ocr_config(project_root=root)
        assert ready.runtime_available() is True
        assertions += 1

        metrics["readiness"]["status"] = "NO_GO"
        metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                **base_environment,
                "ACADEMY_ISOLATED_SERVER_ROOT": str(root),
                "STUDENT_TEST_OCR_ALLOW_UNREADY_MODELS": "1",
            },
            clear=True,
        ):
            qa_override = load_student_test_ocr_config(project_root=root)
        assert qa_override.allow_unready_models is True
        assert qa_override.runtime_available() is True
        assertions += 2

        with patch.dict(
            os.environ,
            {**base_environment, "STUDENT_TEST_OCR_ALLOW_UNREADY_MODELS": "1"},
            clear=True,
        ):
            production_override = load_student_test_ocr_config(project_root=root)
        assert production_override.allow_unready_models is False
        assert production_override.runtime_available() is False
        assertions += 2
    return {"name": "student-test-ocr-config", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
