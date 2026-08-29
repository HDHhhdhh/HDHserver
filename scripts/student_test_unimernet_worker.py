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


SCHEMA: Final = "student_test_ocr_worker_v1"
ENGINE: Final = "unimernet"
DEFAULT_MODEL_DIR: Final = Path(r"C:\server-ocr\models\unimernet_tiny")
DEFAULT_WEIGHT_FILENAME: Final = "unimernet_tiny.pth"


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
            "    max_seq_len: 1536",
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


def infer_image(torch, model, processor, device, image) -> tuple[str, float | None, float | None]:
    prepared = processor(image).unsqueeze(0).to(device)
    if prepared.shape[1] == 1:
        prepared = prepared.repeat(1, 3, 1, 1)
    with redirect_stdout(sys.stderr), torch.inference_mode(), model.maybe_autocast():
        generated = model.model.model.generate(
            pixel_values=prepared,
            max_new_tokens=model.max_seq_len,
            decoder_start_token_id=model.tokenizer.tokenizer.bos_token_id,
            do_sample=False,
            return_dict_in_generate=True,
            output_scores=True,
        )
    token_ids = generated.sequences[:, 1:]
    text = str(model.tokenizer.token2str(token_ids)[0]).strip()[:160]
    probabilities: list[float] = []
    for index, logits in enumerate(generated.scores):
        if index >= token_ids.shape[1]:
            break
        chosen = token_ids[:, index].unsqueeze(-1)
        probability = torch.softmax(logits, dim=-1).gather(1, chosen).squeeze(-1)
        probabilities.append(float(probability[0].detach().cpu()))
    if not probabilities:
        return text, None, None
    mean_log = sum(float(torch.log(torch.tensor(max(value, 1e-12)))) for value in probabilities) / len(probabilities)
    token_confidence = float(torch.exp(torch.tensor(mean_log)))
    return text, token_confidence, min(probabilities)


def run(items: list[tuple[int, Path]]) -> list[dict]:
    from PIL import Image, ImageFilter, ImageOps

    model_dir = Path(os.environ.get("STUDENT_TEST_OCR_UNIMERNET_MODEL_DIR", str(DEFAULT_MODEL_DIR))).resolve()
    weight_filename = os.environ.get("STUDENT_TEST_OCR_UNIMERNET_WEIGHT", DEFAULT_WEIGHT_FILENAME).strip()
    with tempfile.TemporaryDirectory(prefix="student-test-unimernet-") as temp_dir:
        config_path = Path(temp_dir) / "runtime.yaml"
        torch, model, processor, device = load_runtime(config_path, model_dir, weight_filename)
        output: list[dict] = []
        for number, path in items:
            started = time.perf_counter()
            with Image.open(path) as opened:
                original = opened.convert("RGB")
                enhanced = ImageOps.autocontrast(ImageOps.grayscale(opened)).convert("RGB")
            use_second_pass = os.environ.get("STUDENT_TEST_OCR_UNIMERNET_SECOND_PASS", "").strip().lower() in {
                "1", "true", "yes", "on"
            }
            use_variant_pass = os.environ.get("STUDENT_TEST_OCR_UNIMERNET_VARIANT_PASS", "").strip().lower() in {
                "1", "true", "yes", "on"
            }
            if use_second_pass:
                primary_image = enhanced
                variant_image = enhanced.filter(ImageFilter.UnsharpMask(radius=1.2, percent=160, threshold=2))
            else:
                primary_image = original
                variant_image = enhanced
            primary, token_confidence, min_token_confidence = infer_image(
                torch,
                model,
                processor,
                device,
                primary_image,
            )
            if use_second_pass or use_variant_pass:
                variant, _variant_confidence, _variant_minimum = infer_image(
                    torch,
                    model,
                    processor,
                    device,
                    variant_image,
                )
            else:
                variant = ""
            output.append(
                {
                    "questionNo": number,
                    "text": primary,
                    "tokenConfidence": token_confidence,
                    "minTokenConfidence": min_token_confidence,
                    "variantText": variant,
                    "variantAgreed": bool(
                        variant and normalized_formula(primary) and normalized_formula(primary) == normalized_formula(variant)
                    ),
                    "seconds": round(time.perf_counter() - started, 4),
                }
            )
        return output


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
