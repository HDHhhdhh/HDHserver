"""Evaluate a formula checkpoint on immutable public-data crops, without answer keys."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from core.student_test_ocr_rules import answer_values_equivalent, canonicalize_answer_text
from scripts.student_test_formula_dataset_contract import dataset_signature
from scripts.student_test_formula_inference import bounded_prediction
from scripts.student_test_unimernet_worker import load_runtime, normalized_formula


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def grade_prediction(text, target, terminated):
    try:
        numeric = terminated and answer_values_equivalent(canonicalize_answer_text(text), canonicalize_answer_text(target))
    except (ValueError, ArithmeticError):
        numeric = False
    return {"numericCorrect": bool(numeric), "textExact": bool(terminated and normalized_formula(text) == normalized_formula(target))}


def aggregate(rows):
    return {"count": len(rows), "numericCorrect": sum(r["numericCorrect"] for r in rows),
            "textExact": sum(r["textExact"] for r in rows), "truncated": sum(not r["terminated"] for r in rows),
            "numericAccuracy": sum(r["numericCorrect"] for r in rows) / len(rows) if rows else None}


def evaluate(dataset, model_dir, weight, output, device, max_tokens=64):
    import torch
    from PIL import Image
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA evaluation requested but unavailable; no silent CPU fallback")
    dataset, model_dir, output = dataset.resolve(), model_dir.resolve(), output.resolve()
    if output.is_relative_to(dataset) or output.is_relative_to(model_dir):
        raise ValueError("evaluation output must be outside inputs")
    if output.exists():
        raise ValueError("evaluation output already exists")
    before = dataset_signature(dataset)
    labels = (dataset / "equations.txt").read_text(encoding="utf-8").splitlines()
    provenance = [json.loads(line) for line in (dataset / "provenance.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(provenance) != len(labels) or any(r.get("index") != i for i, r in enumerate(provenance)):
        raise ValueError("provenance index/label coverage mismatch")
    source_manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    if source_manifest.get("answerKeyFieldsUsed") != 0 or not source_manifest.get("numericAnswersOnly"):
        raise ValueError("expected key-free numeric-answer dataset")
    model_hash = sha256(model_dir / weight)
    bound_metadata = {str(path): sha256(path) for path in (
        dataset / "provenance.jsonl", dataset / "manifest.json",
        *(model_dir / name for name in ("config.json", "preprocessor_config.json", "tokenizer_config.json", "tokenizer.json")),
        Path(__file__), Path(__file__).parent / "student_test_formula_inference.py",
        Path(__file__).parent / "student_test_unimernet_worker.py",
        Path(__file__).resolve().parents[1] / "core" / "student_test_ocr_rules.py",
    )}
    output.mkdir(parents=True)
    os.environ.update({"STUDENT_TEST_OCR_DEVICE": device, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "NO_ALBUMENTATIONS_UPDATE": "1"})
    rows = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="formula-public-eval-") as temp:
        torch, model, processor, actual_device = load_runtime(Path(temp) / "runtime.yaml", model_dir, weight)
        if device == "cpu":
            torch.set_num_threads(2)
        with (output / "predictions.jsonl").open("x", encoding="utf-8") as stream:
            for index, target in enumerate(labels):
                with Image.open(dataset / "images" / f"{index:07d}.png") as image:
                    prediction = bounded_prediction(torch, model, processor, actual_device, image.convert("RGB"), max_tokens)
                row = {"index": index, "grade": provenance[index]["grade"], "writerHash": provenance[index]["writerHash"],
                       **prediction, **grade_prediction(prediction["text"], target, prediction["terminated"])}
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                rows.append(row)
                if len(rows) % 100 == 0:
                    print(json.dumps({"evaluated": len(rows), "total": len(labels)}), flush=True)
    if dataset_signature(dataset) != before or sha256(model_dir / weight) != model_hash or any(sha256(path) != value for path, value in bound_metadata.items()):
        raise ValueError("evaluation input changed")
    by_grade, by_writer = defaultdict(list), defaultdict(list)
    for row in rows:
        by_grade[row["grade"]].append(row)
        by_writer[row["writerHash"]].append(row)
    report = {"schema": "student_test_formula_public_eval_v1", "datasetSignature": before,
              "modelSha256": model_hash, "metadataAndCodeSha256": bound_metadata, "maxTokens": max_tokens, "seconds": time.perf_counter() - started,
              "aggregate": aggregate(rows), "byGrade": {k: aggregate(v) for k, v in by_grade.items()},
              "byWriter": {k: aggregate(v) for k, v in by_writer.items()}, "writerCount": len(by_writer),
              "predictionsSha256": sha256(output / "predictions.jsonl"), "providerCallCount": 0,
              "deploymentReady": False, "evidenceClass": "public_data_development_validation",
              "limitations": ["grade-scoped writer hashes", "no H_G3 validation when supplied split has none", "not camera/rollout evidence"]}
    with (output / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--weight", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    report = evaluate(args.dataset, args.model_dir, args.weight, args.output, args.device)
    print(json.dumps({"aggregate": report["aggregate"], "deploymentReady": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
