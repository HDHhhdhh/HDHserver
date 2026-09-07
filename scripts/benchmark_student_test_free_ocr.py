"""Offline, hash-bound preprocessing/model ablation. Never grades submissions."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.benchmark_student_test_local_ocr_accuracy import (
    case_manifest, cases, choice_targets, formula_targets, benchmark_formula_kind,
    _safe_numeric_equivalent, evaluate_choice_model,
)
from scripts.student_test_ocr_evidence import validate_eval_inputs
from scripts.student_test_ocr_preprocessing import VARIANTS, prepare_crop
from scripts.student_test_unimernet_worker import load_runtime, normalized_formula
from scripts.student_test_formula_inference import bounded_prediction, generation_completed

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def rescore(rows, plan, targets):
    expected = {(m["name"], v, name, number) for m in plan["models"] for v in plan["variants"]
                for name, labels in targets.items() for number in labels}
    seen = set()
    for row in rows:
        key = (row["model"], row["variant"], row["case"], row["questionNo"])
        if key not in expected or key in seen:
            raise ValueError("unknown or duplicated prediction key")
        seen.add(key)
        if type(row.get("tokenCount")) is not int or row["tokenCount"] < 0 or type(row.get("terminated")) is not bool:
            raise ValueError("prediction termination contract is invalid")
        human = targets[row["case"]][row["questionNo"]]
        row["terminated"] = generation_completed(row["tokenCount"], plan["generation"]["maxNewTokens"], row["terminated"])
        row.update({"human": human, "kind": benchmark_formula_kind(human),
                    "numericCorrect": bool(row["terminated"] and _safe_numeric_equivalent(row["text"], human)),
                    "exactCorrect": bool(row["terminated"] and normalized_formula(row["text"]) == normalized_formula(human))})
    return rows


def summary(rows):
    result = {"evaluated": len(rows), "numericCorrect": sum(row["numericCorrect"] for row in rows),
              "exactCorrect": sum(row["exactCorrect"] for row in rows),
              "truncated": sum(not row["terminated"] for row in rows),
              "errors": sum(bool(row.get("error")) for row in rows)}
    result["numericAccuracy"] = result["numericCorrect"] / len(rows) if rows else None
    result["byKind"] = {kind: {"evaluated": len(group), "correct": sum(r["numericCorrect"] for r in group)}
        for kind in ("number", "fraction", "root", "other")
        if (group := [r for r in rows if r["kind"] == kind])}
    return result


def plan_for(args, all_cases):
    frozen = json.loads(args.input_manifest.read_text(encoding="utf-8"))
    observed = {case.name: case_manifest(case) for case in all_cases}
    choice = [name for name, row in frozen["cases"].items() if row["answerMode"] == "choice_number"]
    formula = [name for name, row in frozen["cases"].items() if row["answerMode"] == "answer_value"]
    validate_eval_inputs(frozen, observed, template_sha256=digest(args.template), choice_cases=choice, formula_cases=formula)
    model_names = [name for name, _, _ in args.model]
    if len(set(model_names)) != len(model_names):
        raise ValueError("model names must be unique")
    models = [{"name": name, "directory": str(Path(directory).resolve()), "weight": weight,
               "sha256": digest(Path(directory) / weight),
               "assets": {asset: digest(Path(directory) / asset) for asset in
                          ("config.json", "preprocessor_config.json", "tokenizer_config.json", "tokenizer.json")}}
              for name, directory, weight in args.model]
    return {"schema": "student_test_free_ocr_ablation_v1", "evidenceClass": "development_crop_ablation",
            "inputManifestSha256": digest(args.input_manifest), "inputs": observed,
            "casePaths": {c.name: {"crops": str(c.crop_dir), "transcription": str(c.transcription)} for c in all_cases},
            "template": str(args.template.resolve()), "templateSha256": digest(args.template),
            "variants": list(VARIANTS), "models": models,
            "choiceModels": [{"name": name, "checkpoint": str(Path(path).resolve()), "sha256": digest(path)} for name, path in args.choice_model],
            "generation": {"maxNewTokens": args.max_tokens, "sample": False, "truncatedCountsAsWrong": True},
            "codeSha256": {name: digest(ROOT / name) for name in (
                "scripts/student_test_ocr_preprocessing.py", "scripts/benchmark_student_test_free_ocr.py",
                "scripts/student_test_unimernet_worker.py", "scripts/student_test_formula_inference.py",
                "scripts/student_test_sheet_crop_worker.py", "scripts/benchmark_student_test_local_ocr_accuracy.py",
                "scripts/student_test_choice_worker.py", "scripts/student_test_ocr_evidence.py", "core/student_test_ocr_rules.py")},
            "choiceCases": choice, "formulaCases": formula, "providerCallCount": 0, "deploymentReady": False}


def prepare_images(plan, output):
    import cv2
    import numpy as np
    from scripts.student_test_sheet_crop_worker import fixed_boxes
    from PIL import Image, ImageDraw, ImageOps

    template = cv2.imdecode(np.fromfile(plan["template"], dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise ValueError("template decode failed")
    template = cv2.resize(template, (1600, 2200), interpolation=cv2.INTER_AREA)
    boxes = fixed_boxes()
    details = []
    for name, paths in plan["casePaths"].items():
        contact = Image.new("RGB", (960, 20 * 118), "white")
        draw = ImageDraw.Draw(contact)
        for number in range(1, 21):
            raw = cv2.imdecode(np.fromfile(str(Path(paths["crops"]) / f"q{number:03d}.png"), dtype=np.uint8), cv2.IMREAD_COLOR)
            if raw is None:
                raise ValueError("input crop decode failed")
            x, y, w, h = boxes[number]
            blank = cv2.resize(template[y:y+h, x:x+w], (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_AREA)
            for column, variant in enumerate(plan["variants"]):
                result, metadata = prepare_crop(cv2, np, raw, blank, variant)
                target = output / "prepared" / variant / name / f"q{number:03d}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                ok, encoded = cv2.imencode(".png", result)
                if not ok:
                    raise ValueError("prepared image encode failed")
                encoded.tofile(str(target))
                details.append({"case": name, "questionNo": number, "variant": variant,
                                "path": str(target), "sha256": digest(target), **metadata})
                with Image.open(target) as opened:
                    thumb = ImageOps.contain(opened.convert("RGB"), (308, 94))
                contact.paste(thumb, (column * 320 + 6, (number - 1) * 118 + 22))
                draw.text((column * 320 + 6, (number - 1) * 118 + 3), f"q{number:02d} {variant}", fill="black")
        contact.save(output / f"{name}_preprocessing.png")
    write_json(output / "prepared.json", details)
    return details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--case", nargs=3, action="append", required=True)
    parser.add_argument("--model", nargs=3, action="append", required=True, metavar=("NAME", "DIRECTORY", "WEIGHT"))
    parser.add_argument("--choice-model", nargs=2, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if not 16 <= args.max_tokens <= 256:
        raise ValueError("bounded diagnostic generation requires 16-256 tokens")
    os.environ.update({"STUDENT_TEST_OCR_DEVICE": "cpu", "NO_ALBUMENTATIONS_UPDATE": "1",
                       "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    all_cases = cases(args.case)
    output = args.output.resolve()
    if any(output == c.crop_dir or output.is_relative_to(c.crop_dir) for c in all_cases):
        raise ValueError("outputs must not be inside benchmark inputs")
    plan = plan_for(args, all_cases)
    if (output / "plan.json").exists():
        if json.loads((output / "plan.json").read_text(encoding="utf-8")) != plan:
            raise ValueError("ablation plan changed; use a new output directory")
        if not (output / "prepared.json").is_file():
            raise ValueError("preparation is incomplete; preserve this attempt and use a new output directory")
        prepared = json.loads((output / "prepared.json").read_text(encoding="utf-8"))
        if any(digest(row["path"]) != row["sha256"] for row in prepared):
            raise ValueError("prepared images changed")
    else:
        if output.exists() and any(output.iterdir()):
            raise ValueError("new ablation output must be empty")
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "plan.json", plan)
        prepared = prepare_images(plan, output)
    if args.prepare_only:
        print(json.dumps({"prepared": len(prepared), "output": str(output)}))
        return 0
    predictions = output / "predictions.jsonl"
    completed = [json.loads(line) for line in predictions.read_text(encoding="utf-8").splitlines()] if predictions.exists() else []
    done = {(r["model"], r["variant"], r["case"], r["questionNo"]) for r in completed}
    formula_cases = {c.name: c for c in all_cases if c.name in plan["formulaCases"]}
    targets = {name: formula_targets(case.transcription)[0] for name, case in formula_cases.items()}
    completed = rescore(completed, plan, targets)
    from PIL import Image
    for spec in plan["models"]:
        todo = [row for row in prepared if row["case"] in targets and row["questionNo"] in targets[row["case"]]]
        todo = [row for row in todo if (spec["name"], row["variant"], row["case"], row["questionNo"]) not in done]
        if not todo:
            continue
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="free-ocr-model-") as temp:
            torch, model, processor, device = load_runtime(Path(temp) / "runtime.yaml", Path(spec["directory"]), spec["weight"])
            torch.set_num_threads(2)
            print(json.dumps({"loaded": spec["name"], "seconds": round(time.perf_counter() - started, 3)}), flush=True)
            with predictions.open("a", encoding="utf-8") as stream:
                for item in todo:
                    started = time.perf_counter()
                    row = {"model": spec["name"], "variant": item["variant"], "case": item["case"], "questionNo": item["questionNo"]}
                    try:
                        with Image.open(item["path"]) as image:
                            row.update(bounded_prediction(torch, model, processor, device, image.convert("RGB"), args.max_tokens))
                    except Exception as error:
                        row.update({"text": "", "terminated": False, "tokenCount": 0, "error": type(error).__name__})
                    human = targets[item["case"]][item["questionNo"]]
                    row.update({"human": human, "kind": benchmark_formula_kind(human),
                                "numericCorrect": bool(row["terminated"] and _safe_numeric_equivalent(row["text"], human)),
                                "exactCorrect": bool(row["terminated"] and normalized_formula(row["text"]) == normalized_formula(human)),
                                "seconds": round(time.perf_counter() - started, 4)})
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    completed.append(row)
                    if len(completed) % 20 == 0:
                        print(json.dumps({"completed": len(completed), "model": spec["name"], "last": row["text"]}), flush=True)
            del model, processor
            gc.collect()
    choice_results = []
    for spec in plan["choiceModels"]:
        for variant in plan["variants"]:
            mapping = {c.name: (c, [(r["questionNo"], Path(r["path"])) for r in prepared if r["case"] == c.name and r["variant"] == variant])
                       for c in all_cases if c.name in plan["choiceCases"]}
            result = evaluate_choice_model(model_name=spec["name"], checkpoint_path=Path(spec["checkpoint"]),
                                          prepared_cases=mapping, confidence=.995, margin=.90)
            choice_results.append({"variant": variant, **result})
    if plan_for(args, all_cases) != plan or any(digest(r["path"]) != r["sha256"] for r in prepared):
        raise ValueError("ablation inputs changed during inference")
    expected = len(plan["models"]) * len(plan["variants"]) * sum(len(t) for t in targets.values())
    if len(completed) != expected or len({(r["model"], r["variant"], r["case"], r["questionNo"]) for r in completed}) != expected:
        raise ValueError("prediction coverage is incomplete or duplicated")
    completed = rescore(completed, plan, targets)
    rows = [{"model": spec["name"], "variant": variant, **summary([r for r in completed if r["model"] == spec["name"] and r["variant"] == variant])}
            for spec in plan["models"] for variant in plan["variants"]]
    report = {"schema": plan["schema"], "createdAt": datetime.now(timezone.utc).isoformat(),
              "planSha256": digest(output / "plan.json"), "formula": rows, "choice": choice_results,
              "predictionsSha256": digest(predictions), "providerCallCount": 0, "deploymentReady": False,
              "limitations": ["development data, not independent holdout", "bounded generation: cap-hit including forced EOS is failure", "exactCorrect is normalized text match, not structural formula equivalence",
                              "raw prediction diagnostic, not runtime consensus or whole-sheet latency"]}
    write_json(output / "report.json", report)
    print(json.dumps({"formula": rows, "output": str(output), "deploymentReady": False}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
