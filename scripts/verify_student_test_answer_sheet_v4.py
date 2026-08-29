from __future__ import annotations

import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(r"C:\server-ocr")
PREVIEW = RUNTIME / "answer_sheet_v4" / "answer_sheet_v4_preview.png"
TEMPLATE = RUNTIME / "answer_sheet_v4" / "answer_sheet_v4_warped_reference.png"
OCR_PYTHON = RUNTIME / ".venv-unimernet" / "Scripts" / "python.exe"
WORKER = ROOT / "scripts" / "student_test_sheet_crop_worker.py"


def run() -> dict:
    if not all(path.is_file() for path in (PREVIEW, TEMPLATE, OCR_PYTHON, WORKER)):
        return {"name": "student-test-answer-sheet-v4", "assertions": 0, "passed": True, "skipped": True}
    from core.student_test_sheet_cropper import CropWorkerSpec, crop_answer_sheet

    assertions = 0
    with tempfile.TemporaryDirectory(prefix="student-test-answer-sheet-v4-") as temp_dir:
        root = Path(temp_dir)
        capture = root / "capture.png"
        capture.write_bytes(PREVIEW.read_bytes())
        response = crop_answer_sheet(
            worker=CropWorkerSpec(OCR_PYTHON, WORKER, template_path=TEMPLATE),
            asset_root=root,
            image_path=capture,
            output_dir=root / "crops",
        )
        assert response["quality"]["markerMode"] == "aruco_4x4_50"
        assert response["quality"]["templateApplied"] is True
        assert response["quality"]["answerBoxSource"] in {"detected", "detected_grid_repaired"}
        assert len(response["items"]) == 20
        assert all(Path(item["recognitionImagePath"]).is_file() for item in response["items"])
        json.dumps(response, ensure_ascii=True)
        assertions += 6
    return {"name": "student-test-answer-sheet-v4", "assertions": assertions, "passed": True, "skipped": False}


if __name__ == "__main__":
    result = run()
    print(
        f"{result['name']} passed: {result['assertions']} assertions"
        + (" (skipped: local v4 asset missing)" if result.get("skipped") else "")
    )
