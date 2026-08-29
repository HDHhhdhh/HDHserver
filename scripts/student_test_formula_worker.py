from __future__ import annotations

import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Final, Mapping


SCHEMA: Final = "student_test_ocr_worker_v1"
ENGINE: Final = "formula"
DEFAULT_MODEL_NAME: Final = "PP-FormulaNet-S"
DEFAULT_MODEL_DIR: Final = Path(r"C:\server-ocr\paddlex-cache\official_models\PP-FormulaNet-S")
DEFAULT_CACHE_DIR: Final = Path(r"C:\server-ocr\paddlex-cache")


class WorkerInputError(ValueError):
    pass


def parse_request(payload: object) -> list[tuple[int, Path]]:
    if not isinstance(payload, dict) or set(payload) != {"schema", "items"} or payload.get("schema") != SCHEMA:
        raise WorkerInputError("invalid worker request schema")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 20:
        raise WorkerInputError("worker request must contain 1 through 20 items")
    indexed: dict[int, Path] = {}
    for raw in raw_items:
        if not isinstance(raw, dict) or set(raw) != {"questionNo", "imagePath"}:
            raise WorkerInputError("worker item contract is invalid")
        number = raw.get("questionNo")
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 20 or number in indexed:
            raise WorkerInputError("worker questions must be unique and between 1 and 20")
        path = Path(str(raw.get("imagePath") or "")).resolve()
        if not path.is_file():
            raise WorkerInputError(f"missing image for question {number}")
        indexed[number] = path
    return [(number, indexed[number]) for number in sorted(indexed)]


def extract_formula(result: object) -> str:
    value = getattr(result, "json", result)
    if callable(value):
        value = value()
    if not isinstance(value, Mapping):
        return ""
    data = value.get("res") if isinstance(value.get("res"), Mapping) else value
    return str(data.get("rec_formula") or data.get("formula") or data.get("text") or "").strip()[:160]


def run(items: list[tuple[int, Path]]) -> list[dict]:
    cache_dir = Path(os.environ.get("STUDENT_TEST_OCR_FORMULA_CACHE_DIR", str(DEFAULT_CACHE_DIR))).resolve()
    model_dir = Path(os.environ.get("STUDENT_TEST_OCR_FORMULA_MODEL_DIR", str(DEFAULT_MODEL_DIR))).resolve()
    model_name = os.environ.get("STUDENT_TEST_OCR_FORMULA_MODEL_NAME", DEFAULT_MODEL_NAME).strip()
    device = os.environ.get("STUDENT_TEST_OCR_DEVICE", "cpu").strip() or "cpu"
    if not model_dir.is_dir():
        raise RuntimeError("formula recognition model directory is missing")
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(cache_dir))
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    with redirect_stdout(sys.stderr):
        from paddleocr import FormulaRecognition

        predictor = FormulaRecognition(model_name=model_name, model_dir=str(model_dir), device=device)
        try:
            results = predictor.predict([str(path) for _number, path in items], batch_size=min(20, len(items)))
        finally:
            predictor.close()
    if not isinstance(results, list) or len(results) != len(items):
        raise RuntimeError("formula worker result count mismatch")
    return [
        {"questionNo": number, "text": extract_formula(result)}
        for (number, _path), result in zip(items, results)
    ]


def emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        items = parse_request(payload)
        result = run(items)
    except Exception as error:
        emit({"ok": False, "engine": ENGINE, "error": type(error).__name__})
        print(f"{ENGINE} worker failed: {error}", file=sys.stderr)
        return 1
    emit({"ok": True, "engine": ENGINE, "items": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
