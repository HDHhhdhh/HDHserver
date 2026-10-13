from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Final, Mapping

if __package__:
    from .student_test_formula_inference import MAX_FORMULA_TOKENS, bounded_prediction
else:
    from student_test_formula_inference import MAX_FORMULA_TOKENS, bounded_prediction


SCHEMA: Final = "student_test_ocr_worker_v1"
ENGINE: Final = "unimernet"
DEFAULT_MODEL_DIR: Final = Path(r"C:\server-ocr\models\unimernet_tiny")
DEFAULT_WEIGHT_FILENAME: Final = "unimernet_tiny.pth"
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


def normalized_formula(value: object) -> str:
    text = str(value or "").strip().strip("$")
    text = text.replace("\\left", "").replace("\\right", "")
    text = text.replace("\\,", "").replace("\\;", "")
    return re.sub(r"\s+", "", text)


def runtime_config_text(model_dir: Path, weight_filename: str) -> str:
    weight_path = model_dir / weight_filename
    return "\n".join(
        [
            "model:",
            "  arch: unimernet",
            "  model_type: unimernet",
            "  model_name: unimernet",
            "  tokenizer_name: nougat",
            "  model_config:",
            f"    model_name: {model_dir.as_posix()}",
            f"    max_seq_len: {MAX_FORMULA_TOKENS}",
            "  load_pretrained: False",
            "  load_finetuned: True",
            f"  finetuned: '{weight_path.as_posix()}'",
            "  tokenizer_config:",
            f"    path: {model_dir.as_posix()}",
            "datasets:",
            "  formula_rec_eval:",
            "    vis_processor:",
            "      eval:",
            "        name: formula_image_eval",
            "        image_size:",
            "          - 192",
            "          - 672",
            "run:",
            "  runner: runner_iter",
            "  task: unimernet_train",
            "  evaluate: false",
            "  report_metric: false",
            "  batch_size_train: 1",
            "  batch_size_eval: 1",
            "  num_workers: 0",
            "  device: cpu",
            "  world_size: 1",
            "  distributed: false",
            "  generate_cfg:",
            "    do_sample: false",
        ]
    ) + "\n"


def load_runtime(config_path: Path, model_dir: Path, weight_filename: str):
    if not model_dir.is_dir() or not (model_dir / weight_filename).is_file():
        raise RuntimeError("UniMERNet model files are missing")
    config_path.write_text(runtime_config_text(model_dir, weight_filename), encoding="utf-8")
    with redirect_stdout(sys.stderr):
        import torch
        from unimernet.common.config import Config
        from unimernet.processors import load_processor
        import unimernet.tasks as tasks

        args = argparse.Namespace(cfg_path=str(config_path), options=None)
        config = Config(args)
        task = tasks.setup_task(config)
        requested_device = os.environ.get("STUDENT_TEST_OCR_DEVICE", "cpu").strip().lower()
        use_cuda = requested_device.startswith("cuda") or requested_device.startswith("gpu")
        device = torch.device("cuda" if use_cuda and torch.cuda.is_available() else "cpu")
        model = task.build_model(config).to(device)
        model.eval()
        processor = load_processor("formula_image_eval", config.config.datasets.formula_rec_eval.vis_processor.eval)
    return torch, model, processor, device


def infer_prediction(torch, model, processor, device, image) -> dict:
    with redirect_stdout(sys.stderr):
        return bounded_prediction(torch, model, processor, device, image, output_scores=True)


def infer_image(torch, model, processor, device, image) -> tuple[str, float | None, float | None]:
    prediction = infer_prediction(torch, model, processor, device, image)
    return prediction["text"], prediction["tokenConfidence"], prediction["minTokenConfidence"]


def cached_runtime():
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    model_dir = Path(os.environ.get("STUDENT_TEST_OCR_UNIMERNET_MODEL_DIR", str(DEFAULT_MODEL_DIR))).resolve()
    weight_filename = os.environ.get("STUDENT_TEST_OCR_UNIMERNET_WEIGHT", DEFAULT_WEIGHT_FILENAME).strip()
    with tempfile.TemporaryDirectory(prefix="student-test-unimernet-") as temp_dir:
        config_path = Path(temp_dir) / "runtime.yaml"
        _RUNTIME = load_runtime(config_path, model_dir, weight_filename)
    return _RUNTIME


def run(items: list[tuple[int, Path]], *, options: Mapping[str, bool] | None = None) -> list[dict]:
    from PIL import Image, ImageFilter, ImageOps

    torch, model, processor, device = cached_runtime()
    use_second_pass = (options["secondPass"] if options is not None else
                       os.environ.get("STUDENT_TEST_OCR_UNIMERNET_SECOND_PASS", "").strip().lower()
                       in {"1", "true", "yes", "on"})
    use_variant_pass = (options["variantPass"] if options is not None else
                        os.environ.get("STUDENT_TEST_OCR_UNIMERNET_VARIANT_PASS", "").strip().lower()
                        in {"1", "true", "yes", "on"})
    output: list[dict] = []
    for number, path in items:
        started = time.perf_counter()
        with Image.open(path) as opened:
            original = opened.convert("RGB")
            enhanced = ImageOps.autocontrast(ImageOps.grayscale(opened)).convert("RGB")
        if use_second_pass:
            primary_image = enhanced
            variant_image = enhanced.filter(ImageFilter.UnsharpMask(radius=1.2, percent=160, threshold=2))
        else:
            primary_image = original
            variant_image = enhanced
        primary = infer_prediction(torch, model, processor, device, primary_image)
        if use_second_pass or use_variant_pass:
            variant = infer_prediction(torch, model, processor, device, variant_image)
        else:
            variant = {"text": "", "terminated": False}
        output.append({
            "questionNo": number, **primary,
            "variantText": variant["text"], "variantTerminated": variant["terminated"],
            "variantAgreed": bool(primary["terminated"] and variant["terminated"]
                                  and normalized_formula(primary["text"])
                                  and normalized_formula(primary["text"]) == normalized_formula(variant["text"])),
            "seconds": round(time.perf_counter() - started, 4),
        })
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
                     run=lambda items, options: run(items, options=options))
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
