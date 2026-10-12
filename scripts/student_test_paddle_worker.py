from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Final, Mapping


SCHEMA: Final = "student_test_ocr_worker_v1"
ENGINE: Final = "paddle"
DEFAULT_MODEL_NAME: Final = "korean_PP-OCRv5_mobile_rec"
DEFAULT_MODEL_DIR: Final = Path(r"C:\server-ocr\paddlex-cache\official_models\korean_PP-OCRv5_mobile_rec")
DEFAULT_CACHE_DIR: Final = Path(r"C:\server-ocr\paddlex-cache")
_RUNTIME = None


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
            raise WorkerInputError("worker questions must uniquely cover 1 through 20")
        path = Path(str(raw.get("imagePath") or "")).resolve()
        if not path.is_file():
            raise WorkerInputError(f"missing image for question {number}")
        indexed[number] = path
    return [(number, indexed[number]) for number in sorted(indexed)]


def extract_recognition(result: object) -> tuple[str, float | None]:
    value = getattr(result, "json", result)
    if callable(value):
        value = value()
    if not isinstance(value, Mapping):
        return "", None
    data = value.get("res") if isinstance(value.get("res"), Mapping) else value
    text = str(data.get("rec_text") or data.get("text") or "").strip()
    raw_score = data.get("rec_score", data.get("score"))
    score = None
    if not isinstance(raw_score, bool) and isinstance(raw_score, (int, float)) and 0 <= float(raw_score) <= 1:
        score = float(raw_score)
    return text[:80], score


def load_runtime():
    cache_dir = Path(os.environ.get("STUDENT_TEST_OCR_PADDLE_CACHE_DIR", str(DEFAULT_CACHE_DIR))).resolve()
    model_dir = Path(os.environ.get("STUDENT_TEST_OCR_PADDLE_MODEL_DIR", str(DEFAULT_MODEL_DIR))).resolve()
    model_name = os.environ.get("STUDENT_TEST_OCR_PADDLE_MODEL_NAME", DEFAULT_MODEL_NAME).strip()
    device = os.environ.get("STUDENT_TEST_OCR_DEVICE", "cpu").strip() or "cpu"
    if not model_dir.is_dir():
        raise RuntimeError("Paddle recognition model directory is missing")
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(cache_dir))
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    with redirect_stdout(sys.stderr):
        from paddleocr import TextRecognition

        return TextRecognition(model_name=model_name, model_dir=str(model_dir), device=device)


def cached_runtime():
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = load_runtime()
    return _RUNTIME


def close_runtime() -> None:
    global _RUNTIME
    predictor, _RUNTIME = _RUNTIME, None
    if predictor is not None:
        with redirect_stdout(sys.stderr):
            predictor.close()


def run(items: list[tuple[int, Path]]) -> list[dict]:
    from PIL import Image, ImageFilter, ImageOps

    predictor = cached_runtime()
    with redirect_stdout(sys.stderr):
        with tempfile.TemporaryDirectory(prefix="student-test-paddle-") as temp_dir:
            paths: list[str] = []
            for index, (_number, path) in enumerate(items):
                paths.append(str(path))
                with Image.open(path) as opened:
                    variant = ImageOps.autocontrast(ImageOps.grayscale(opened)).filter(ImageFilter.MaxFilter(3))
                    variant_path = Path(temp_dir) / f"variant-{index:03d}.png"
                    variant.save(variant_path)
                paths.append(str(variant_path))
            results = predictor.predict(paths, batch_size=min(20, len(paths)))
    if not isinstance(results, list) or len(results) != len(items) * 2:
        raise RuntimeError("Paddle worker result count mismatch")
    output: list[dict] = []
    for index, (number, _path) in enumerate(items):
        text, score = extract_recognition(results[index * 2])
        variant_text, variant_score = extract_recognition(results[index * 2 + 1])
        output.append(
            {
                "questionNo": number,
                "text": text,
                "score": score,
                "variantText": variant_text,
                "variantScore": variant_score,
                "variantAgreed": bool(text and text == variant_text),
            }
        )
    return output


def emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    if sys.argv[1:] == ["--serve-jsonl"]:
        if __package__:
            from .student_test_ocr_worker_server import serve
        else:
            from student_test_ocr_worker_server import serve
        return serve(engine=ENGINE, parse_request=parse_request,
                     run=lambda items, options: run(items), close_runtime=close_runtime)
    try:
        payload = json.load(sys.stdin)
        items = parse_request(payload)
        result = run(items)
    except Exception as error:
        emit({"ok": False, "engine": ENGINE, "error": type(error).__name__})
        print(f"{ENGINE} worker failed: {error}", file=sys.stderr)
        return 1
    finally:
        close_runtime()
    emit({"ok": True, "engine": ENGINE, "items": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
