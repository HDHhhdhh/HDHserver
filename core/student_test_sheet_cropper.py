from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from core.student_test_ocr_engine import OcrEngineError, _safe_worker_environment


@dataclass(frozen=True, slots=True)
class CropWorkerSpec:
    python_path: Path
    script_path: Path
    timeout_seconds: float = 20.0
    template_path: Path | None = None


def _inside(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise OcrEngineError("invalid_crop_path", "crop worker path escapes the asset root") from error
    return resolved


def crop_answer_sheet(
    *,
    worker: CropWorkerSpec,
    asset_root: Path,
    image_path: Path,
    output_dir: Path,
) -> dict:
    python_path = worker.python_path.resolve()
    script_path = worker.script_path.resolve()
    if not python_path.is_file() or not script_path.is_file():
        raise OcrEngineError("crop_engine_unavailable", "answer-sheet crop worker is not installed")
    validated_image = _inside(asset_root, image_path)
    validated_output = _inside(asset_root, output_dir)
    if not validated_image.is_file():
        raise OcrEngineError("missing_capture", "answer-sheet capture is missing")
    payload = {
        "schema": "student_test_sheet_crop_worker_v1",
        "imagePath": str(validated_image),
        "outputDir": str(validated_output),
    }
    worker_environment = {"STUDENT_TEST_OCR_ASSET_ROOT": str(asset_root.resolve())}
    if worker.template_path is not None:
        template_path = worker.template_path.resolve()
        if template_path.is_file():
            worker_environment["STUDENT_TEST_OCR_TEMPLATE_PATH"] = str(template_path)
    environment = _safe_worker_environment(worker_environment)
    try:
        completed = subprocess.run(
            [str(python_path), "-B", str(script_path)],
            input=json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=worker.timeout_seconds,
            check=False,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise OcrEngineError("crop_engine_timeout", "answer-sheet cropping timed out") from error
    except OSError as error:
        raise OcrEngineError("crop_engine_unavailable", "answer-sheet crop worker could not start") from error
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise OcrEngineError("invalid_crop_response", "crop worker returned an invalid response")
    try:
        response = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise OcrEngineError("invalid_crop_response", "crop worker returned invalid JSON") from error
    if completed.returncode != 0 or not isinstance(response, dict) or response.get("ok") is not True:
        code = str(response.get("error") or "crop_engine_failed") if isinstance(response, dict) else "crop_engine_failed"
        raise OcrEngineError("crop_engine_failed", code)
    items = response.get("items")
    if not isinstance(items, list) or len(items) != 20:
        raise OcrEngineError("invalid_crop_response", "crop worker did not return 20 question crops")
    for expected, item in enumerate(items, start=1):
        if not isinstance(item, dict) or item.get("questionNo") != expected:
            raise OcrEngineError("invalid_crop_response", "crop worker question order is invalid")
        path = _inside(asset_root, Path(str(item.get("imagePath") or "")))
        if not path.is_file():
            raise OcrEngineError("invalid_crop_response", "crop worker output file is missing")
        item["imagePath"] = str(path)
        recognition_path = _inside(asset_root, Path(str(item.get("recognitionImagePath") or "")))
        if not recognition_path.is_file():
            raise OcrEngineError("invalid_crop_response", "crop worker recognition image is missing")
        item["recognitionImagePath"] = str(recognition_path)
    return response
