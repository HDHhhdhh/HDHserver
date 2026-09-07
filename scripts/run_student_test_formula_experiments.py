"""Prepare full-vs-focused CUDA experiments at the packet's final GPU location."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from core.student_test_formula_profiles import FORMULA_PROFILE_DATASETS
from scripts.generate_student_test_formula_training_config import generate
from scripts.student_test_formula_dataset_contract import dataset_signature

ROOT = Path(__file__).resolve().parents[1]


def verify_packet(packet):
    manifest = json.loads((packet / "PACKET_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest["files"]:
        path = (packet / row["path"]).resolve()
        if not path.is_relative_to(packet) or not path.is_file() or path.stat().st_size != row["bytes"]:
            raise ValueError("packet path/size mismatch")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"packet checksum mismatch: {row['path']}")
    return manifest


def validate_full_control(full_train, validation, expected):
    provenance = (full_train / "provenance.jsonl").read_bytes()
    validation_manifest = json.loads((validation / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(provenance).hexdigest() != validation_manifest.get("excludedTrainingProvenanceSha256"):
        raise ValueError("full training writer provenance changed since validation exclusion")
    if not isinstance(expected, dict) or dataset_signature(full_train) != expected:
        raise ValueError("full training image/annotation control differs from the prepared experiment")


def prepare_configs(packet, runtime, work, *, max_iters=1000):
    if work.exists():
        raise ValueError("use a new work directory; existing experiment files are never overwritten")
    if work.is_relative_to(runtime / "models") or work.is_relative_to(runtime / "datasets"):
        raise ValueError("work directory must not be inside source models/data")
    packet_manifest = verify_packet(packet)
    for profile in FORMULA_PROFILE_DATASETS:
        validate_full_control(runtime / "datasets" / "aihub_education" / "formula_profiles" / "training" / profile,
                              packet / "data" / "validation" / profile,
                              packet_manifest.get("controlDatasets", {}).get(profile))
    base = runtime / "models" / "unimernet_tiny"
    experiments = []
    for strategy in ("full", "focused"):
        for profile in FORMULA_PROFILE_DATASETS:
            train = (runtime / "datasets" / "aihub_education" / "formula_profiles" / "training" / profile
                     if strategy == "full" else packet / "data" / "training" / profile)
            validation = packet / "data" / "validation" / profile
            config = work / "configs" / f"{strategy}_{profile}.yaml"
            result = generate(profile=profile, train_root=train, validation_root=validation,
                base_model_dir=base, base_weight=base / "unimernet_tiny.pth", output_config=config,
                output_dir=work / "runs" / strategy / profile, max_iters=max_iters,
                batch_size=4, accum_grad_iters=2, num_workers=0, seed=20260906)
            experiments.append({"strategy": strategy, "profile": profile, "config": str(config),
                "outputDir": result["outputDir"], "trainCount": result["trainCount"],
                "validationCount": result["validationCount"], "initialWeightSha256": result["baseWeightSha256"]})
    receipt = {"schema": "student_test_formula_experiment_plan_v1", "experiments": experiments,
               "maxIters": max_iters, "nominalSampleExposuresPerRun": max_iters * 4,
               "approxOptimizerUpdatesPerRun": max_iters // 2, "sameInitialCheckpoint": True,
               "trainingExecuted": False, "deploymentReady": False}
    with (work / "EXPERIMENT_PLAN.json").open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, default=Path(r"C:\server-ocr"))
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--max-iters", type=int, default=1000)
    parser.add_argument("--train", action="store_true", help="Explicitly run CUDA after configuration validation.")
    args = parser.parse_args()
    if args.max_iters < 1:
        raise ValueError("max-iters must be positive")
    if args.train:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("NVIDIA CUDA is required; training was not started")
    report = prepare_configs(args.packet_root.resolve(), args.runtime_root.resolve(), args.work_root.resolve(), max_iters=args.max_iters)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if args.train:
        for strategy in ("full", "focused"):
            command = [sys.executable, "-B", "-m", "scripts.train_student_test_formula_profiles"]
            for row in report["experiments"]:
                if row["strategy"] == strategy:
                    command.extend(["--config", row["config"]])
            subprocess.run(command, cwd=ROOT, check=True)
        print(json.dumps({"trainingCompleted": True, "deploymentReady": False}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
