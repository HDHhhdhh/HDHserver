from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Mapping

from core.student_test_formula_profiles import (
    FORMULA_PROFILE_COMMON,
    FORMULA_PROFILE_DATASETS,
    FORMULA_PROFILE_UPPER,
)
from core.student_test_ocr_engine import ConfidencePolicy, WorkerSpec
from core.student_test_sheet_cropper import CropWorkerSpec
from core.runtime_server_guard import is_verified_isolated_server_root
from core.student_test_ocr_readiness import UNIMERNET_ASSETS, deployment_artifacts, deployment_evidence_reasons


TRUTHY: Final = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True, slots=True)
class StudentTestOcrConfig:
    enabled: bool
    db_path: Path
    asset_root: Path
    solution_pdf_root: Path
    crop_worker: CropWorkerSpec
    choice_worker: WorkerSpec
    paddle_worker: WorkerSpec
    formula_worker: WorkerSpec
    unimernet_worker: WorkerSpec
    unimernet_profile_workers: Mapping[str, WorkerSpec]
    confidence_policy: ConfidencePolicy
    token_ttl_seconds: int = 600
    allow_unready_models: bool = False
    deployment_evidence_path: Path | None = None
    maintenance_enabled: bool = False
    maintenance_interval_seconds: float = 300.0

    def unimernet_worker_for_profile(self, profile: object) -> WorkerSpec:
        normalized = str(profile or "").strip()
        worker = self.unimernet_profile_workers.get(normalized)
        if worker is None:
            raise ValueError("subjective OCR model profile is unavailable")
        return worker

    def readiness_report(self) -> dict:
        """Installation and quality are independent; this method never enables OCR."""
        choice_model_path = Path(
            self.choice_worker.environment.get("STUDENT_TEST_OCR_CHOICE_MODEL_PATH", "")
        )
        paddle_model_dir = Path(
            self.paddle_worker.environment.get("STUDENT_TEST_OCR_PADDLE_MODEL_DIR", "")
        )
        formula_model_dir = Path(
            self.formula_worker.environment.get("STUDENT_TEST_OCR_FORMULA_MODEL_DIR", "")
        )
        unimernet_model_dir = Path(
            self.unimernet_worker.environment.get("STUDENT_TEST_OCR_UNIMERNET_MODEL_DIR", "")
        )
        unimernet_weight = self.unimernet_worker.environment.get(
            "STUDENT_TEST_OCR_UNIMERNET_WEIGHT",
            "unimernet_tiny.pth",
        )
        profile_model_files: tuple[Path, ...] = ()
        profile_model_directories: tuple[Path, ...] = ()
        if set(self.unimernet_profile_workers) != set(FORMULA_PROFILE_DATASETS):
            return {"installed": False, "deploymentReady": False, "reasons": ["formula_profiles_incomplete"]}
        for worker in self.unimernet_profile_workers.values():
            model_dir = Path(worker.environment.get("STUDENT_TEST_OCR_UNIMERNET_MODEL_DIR", ""))
            weight = worker.environment.get("STUDENT_TEST_OCR_UNIMERNET_WEIGHT", "").strip()
            if not weight:
                return {"installed": False, "deploymentReady": False, "reasons": ["formula_weight_missing"]}
            profile_model_files += (worker.python_path, worker.script_path, model_dir / weight)
            profile_model_files += tuple(model_dir / name for name in UNIMERNET_ASSETS)
            profile_model_directories += (model_dir,)
        required_files = (
            self.crop_worker.python_path,
            self.crop_worker.script_path,
            self.choice_worker.python_path,
            self.choice_worker.script_path,
            self.paddle_worker.python_path,
            self.paddle_worker.script_path,
            self.formula_worker.python_path,
            self.formula_worker.script_path,
            self.unimernet_worker.python_path,
            self.unimernet_worker.script_path,
            self.unimernet_worker.script_path.with_name("student_test_formula_inference.py"),
            self.unimernet_worker.script_path.with_name("student_test_ocr_worker_server.py"),
            choice_model_path,
            unimernet_model_dir / unimernet_weight,
        ) + profile_model_files + tuple(unimernet_model_dir / name for name in UNIMERNET_ASSETS)
        if self.crop_worker.template_path is not None:
            required_files += (self.crop_worker.template_path,)
        required_directories = (
            paddle_model_dir,
            formula_model_dir,
            unimernet_model_dir,
            *profile_model_directories,
        )
        if not all(path.is_file() for path in required_files) or not all(
            path.is_dir() for path in required_directories
        ):
            return {"installed": False, "deploymentReady": False, "reasons": ["runtime_assets_missing"]}
        reasons = []
        metrics_path = choice_model_path.parent / "metrics.json"
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            checkpoint = Path(str(metrics.get("checkpoint") or "")).resolve()
            readiness = metrics.get("readiness")
        except (OSError, ValueError, TypeError, AttributeError):
            metrics, checkpoint, readiness = {}, None, None
        if not (
            metrics.get("ok") is True
            and isinstance(readiness, dict)
            and readiness.get("status") == "GO"
            and metrics.get("answerKeyFieldsUsed") == 0
            and metrics.get("providerCallCount") == 0
            and checkpoint == choice_model_path.resolve()
        ):
            reasons.append("choice_training_gate_not_met")
        artifacts = deployment_artifacts(
            required_files=required_files, code_root=Path(__file__).resolve().parents[1],
            model_directories=(paddle_model_dir, formula_model_dir),
        )
        if self.deployment_evidence_path is None:
            reasons.append("deployment_evidence_missing_or_unreadable")
        else:
            reasons.extend(deployment_evidence_reasons(
                self.deployment_evidence_path, artifacts=artifacts,
                policy=asdict(self.confidence_policy), profiles=tuple(FORMULA_PROFILE_DATASETS),
            ))
        return {"installed": True, "deploymentReady": not reasons, "reasons": reasons}

    def runtime_available(self) -> bool:
        readiness = self.readiness_report()
        return bool(readiness["installed"] and (readiness["deploymentReady"] or self.allow_unready_models))


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUTHY


def _float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if minimum <= value <= maximum else default


def load_student_test_ocr_config(*, project_root: Path | None = None) -> StudentTestOcrConfig:
    root = (project_root or Path(__file__).resolve().parents[1]).resolve()
    allow_unready_models = bool(
        _truthy("STUDENT_TEST_OCR_ALLOW_UNREADY_MODELS") and is_verified_isolated_server_root(code_root=root)
    )
    runtime_root = Path(os.environ.get("STUDENT_TEST_OCR_RUNTIME_ROOT", r"C:\server-ocr")).resolve()
    server_python = runtime_root / ".venv" / "Scripts" / "python.exe"
    unimernet_python = runtime_root / ".venv-unimernet" / "Scripts" / "python.exe"
    device = os.environ.get("STUDENT_TEST_OCR_DEVICE", "cpu").strip() or "cpu"
    choice_model_path = Path(
        os.environ.get(
            "STUDENT_TEST_OCR_CHOICE_MODEL_PATH",
            str(runtime_root / "choice_digit_classifier_v3" / "choice_digit_v3.pt"),
        )
    ).resolve()
    paddle_environment = {
        "STUDENT_TEST_OCR_DEVICE": device,
        "STUDENT_TEST_OCR_PADDLE_CACHE_DIR": str(runtime_root / "paddlex-cache"),
        "STUDENT_TEST_OCR_PADDLE_MODEL_DIR": str(
            runtime_root / "paddlex-cache" / "official_models" / "korean_PP-OCRv5_mobile_rec"
        ),
    }
    choice_environment = {
        "STUDENT_TEST_OCR_CHOICE_MODEL_PATH": str(choice_model_path),
    }
    formula_environment = {
        "STUDENT_TEST_OCR_DEVICE": device,
        "STUDENT_TEST_OCR_FORMULA_CACHE_DIR": str(runtime_root / "paddlex-cache"),
        "STUDENT_TEST_OCR_FORMULA_MODEL_DIR": str(
            runtime_root / "paddlex-cache" / "official_models" / "PP-FormulaNet-S"
        ),
        "STUDENT_TEST_OCR_FORMULA_MODEL_NAME": "PP-FormulaNet-S",
    }
    unimernet_environment = {
        "STUDENT_TEST_OCR_DEVICE": device,
        "STUDENT_TEST_OCR_UNIMERNET_MODEL_DIR": str(runtime_root / "models" / "unimernet_tiny"),
        "STUDENT_TEST_OCR_UNIMERNET_WEIGHT": "unimernet_tiny.pth",
        "STUDENT_TEST_OCR_UNIMERNET_VARIANT_PASS": "1" if _truthy("STUDENT_TEST_OCR_REQUIRE_SECOND_PASS") else "0",
    }
    common_unimernet_environment = {
        **unimernet_environment,
        "STUDENT_TEST_OCR_UNIMERNET_MODEL_DIR": str(
            Path(
                os.environ.get(
                    "STUDENT_TEST_OCR_UNIMERNET_M3_H1_MODEL_DIR",
                    str(runtime_root / "models" / "unimernet_m3_h1"),
                )
            ).resolve()
        ),
        "STUDENT_TEST_OCR_UNIMERNET_WEIGHT": os.environ.get(
            "STUDENT_TEST_OCR_UNIMERNET_M3_H1_WEIGHT",
            "unimernet_m3_h1.pth",
        ).strip(),
        "STUDENT_TEST_OCR_FORMULA_DATA_PROFILE": FORMULA_PROFILE_COMMON,
    }
    upper_unimernet_environment = {
        **unimernet_environment,
        "STUDENT_TEST_OCR_UNIMERNET_MODEL_DIR": str(
            Path(
                os.environ.get(
                    "STUDENT_TEST_OCR_UNIMERNET_M3_H1_H2_H3_MODEL_DIR",
                    str(runtime_root / "models" / "unimernet_m3_h1_h2_h3"),
                )
            ).resolve()
        ),
        "STUDENT_TEST_OCR_UNIMERNET_WEIGHT": os.environ.get(
            "STUDENT_TEST_OCR_UNIMERNET_M3_H1_H2_H3_WEIGHT",
            "unimernet_m3_h1_h2_h3.pth",
        ).strip(),
        "STUDENT_TEST_OCR_FORMULA_DATA_PROFILE": FORMULA_PROFILE_UPPER,
    }
    return StudentTestOcrConfig(
        enabled=_truthy("STUDENT_TEST_OCR_ENABLED"),
        db_path=Path(os.environ.get("DB_PATH", str(root / "app.sqlite"))).resolve(),
        asset_root=Path(
            os.environ.get("STUDENT_TEST_OCR_ASSET_ROOT", str(root / "instance" / "student-test-ocr"))
        ).absolute(),
        solution_pdf_root=Path(
            os.environ.get(
                "STUDENT_TEST_OCR_SOLUTION_PDF_ROOT",
                str(root / ".codex_drive_download" / "unit_answer_pdfs"),
            )
        ).resolve(),
        crop_worker=CropWorkerSpec(
            python_path=unimernet_python,
            script_path=root / "scripts" / "student_test_sheet_crop_worker.py",
            timeout_seconds=_float("STUDENT_TEST_OCR_CROP_TIMEOUT", 20.0, 5.0, 60.0),
            template_path=Path(
                os.environ.get(
                    "STUDENT_TEST_OCR_TEMPLATE_PATH",
                    str(runtime_root / "answer_sheet_v4" / "answer_sheet_v4_warped_reference.png"),
                )
            ).resolve(),
        ),
        choice_worker=WorkerSpec(
            engine="choice_digit",
            python_path=unimernet_python,
            script_path=root / "scripts" / "student_test_choice_worker.py",
            timeout_seconds=_float("STUDENT_TEST_OCR_CHOICE_TIMEOUT", 20.0, 5.0, 60.0),
            environment=choice_environment,
        ),
        paddle_worker=WorkerSpec(
            engine="paddle",
            python_path=server_python,
            script_path=root / "scripts" / "student_test_paddle_worker.py",
            timeout_seconds=_float("STUDENT_TEST_OCR_PADDLE_TIMEOUT", 45.0, 10.0, 120.0),
            environment=paddle_environment,
        ),
        formula_worker=WorkerSpec(
            engine="formula",
            python_path=server_python,
            script_path=root / "scripts" / "student_test_formula_worker.py",
            timeout_seconds=_float("STUDENT_TEST_OCR_FORMULA_TIMEOUT", 45.0, 10.0, 120.0),
            environment=formula_environment,
        ),
        unimernet_worker=WorkerSpec(
            engine="unimernet",
            python_path=unimernet_python,
            script_path=root / "scripts" / "student_test_unimernet_worker.py",
            timeout_seconds=_float("STUDENT_TEST_OCR_UNIMERNET_TIMEOUT", 55.0, 10.0, 120.0),
            environment=unimernet_environment,
        ),
        unimernet_profile_workers={
            FORMULA_PROFILE_COMMON: WorkerSpec(
                engine="unimernet",
                python_path=unimernet_python,
                script_path=root / "scripts" / "student_test_unimernet_worker.py",
                timeout_seconds=_float("STUDENT_TEST_OCR_UNIMERNET_TIMEOUT", 55.0, 10.0, 120.0),
                environment=common_unimernet_environment,
            ),
            FORMULA_PROFILE_UPPER: WorkerSpec(
                engine="unimernet",
                python_path=unimernet_python,
                script_path=root / "scripts" / "student_test_unimernet_worker.py",
                timeout_seconds=_float("STUDENT_TEST_OCR_UNIMERNET_TIMEOUT", 55.0, 10.0, 120.0),
                environment=upper_unimernet_environment,
            ),
        },
        confidence_policy=ConfidencePolicy(
            choice_digit_minimum=_float("STUDENT_TEST_OCR_CHOICE_DIGIT_CONFIDENCE", 0.995, 0.0, 1.0),
            choice_digit_margin_minimum=_float("STUDENT_TEST_OCR_CHOICE_DIGIT_MARGIN", 0.90, 0.0, 1.0),
            choice_paddle_minimum=_float("STUDENT_TEST_OCR_CHOICE_CONFIDENCE", 0.98, 0.0, 1.0),
            unimernet_token_minimum=_float("STUDENT_TEST_OCR_FORMULA_CONFIDENCE", 0.995, 0.0, 1.0),
            require_choice_cross_engine_agreement=False,
            require_paddle_variant_agreement=True,
            require_formula_cross_engine_agreement=True,
            require_unimernet_variant_agreement=_truthy("STUDENT_TEST_OCR_REQUIRE_SECOND_PASS"),
        ),
        allow_unready_models=allow_unready_models,
        deployment_evidence_path=Path(os.environ.get(
            "STUDENT_TEST_OCR_DEPLOYMENT_EVIDENCE", str(runtime_root / "deployment_evidence.json")
        )).resolve(),
        maintenance_enabled=_truthy("STUDENT_TEST_OCR_MAINTENANCE_ENABLED"),
        maintenance_interval_seconds=_float("STUDENT_TEST_OCR_MAINTENANCE_INTERVAL", 300.0, 60.0, 3600.0),
    )
