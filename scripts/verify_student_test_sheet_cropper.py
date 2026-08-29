from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from core.student_test_sheet_cropper import CropWorkerSpec, crop_answer_sheet


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts" / "student_test_sheet_crop_worker.py"
OCR_PYTHON = Path(r"C:\server-ocr\.venv-unimernet\Scripts\python.exe")
REFERENCE = Path(r"C:\server-ocr\answer_sheet_v3\answer_sheet_v3_preview.png")


def run() -> dict:
    assertions = 0
    if not OCR_PYTHON.is_file() or not REFERENCE.is_file():
        return {"name": "student-test-sheet-cropper", "assertions": 0, "passed": True, "skipped": True}
    with tempfile.TemporaryDirectory(prefix="student-test-sheet-cropper-") as temp_dir:
        asset_root = Path(temp_dir)
        capture = asset_root / "capture.png"
        shutil.copyfile(REFERENCE, capture)
        output = asset_root / "crops"
        response = crop_answer_sheet(
            worker=CropWorkerSpec(OCR_PYTHON, WORKER),
            asset_root=asset_root,
            image_path=capture,
            output_dir=output,
        )
        assert response["ok"] is True and len(response["items"]) == 20
        assert [item["questionNo"] for item in response["items"]] == list(range(1, 21))
        assert all(Path(item["imagePath"]).is_file() for item in response["items"])
        assert all(Path(item["recognitionImagePath"]).is_file() for item in response["items"])
        assert isinstance(response["quality"]["failures"], list)
        assert response["quality"]["answerBoxSource"] in {"detected", "detected_grid_repaired"}
        assert all(isinstance(item["blockingWarnings"], list) for item in response["items"])
        assertions += 7
        json.dumps(response, ensure_ascii=True)
        assertions += 1
    return {"name": "student-test-sheet-cropper", "assertions": assertions, "passed": True, "skipped": False}


if __name__ == "__main__":
    result = run()
    print(
        f"{result['name']} passed: {result['assertions']} assertions"
        + (" (skipped: local OCR runtime missing)" if result.get("skipped") else "")
    )
