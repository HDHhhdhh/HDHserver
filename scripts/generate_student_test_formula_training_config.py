from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from core.student_test_formula_profiles import FORMULA_PROFILE_DATASETS, formula_profile_datasets
from scripts.student_test_formula_dataset_contract import dataset_signature


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a CUDA UniMERNet fine-tuning config for one student-test formula profile."
    )
    parser.add_argument("--profile", required=True, choices=sorted(FORMULA_PROFILE_DATASETS))
    parser.add_argument("--train-dataset", type=Path, required=True)
    parser.add_argument("--validation-dataset", type=Path, required=True)
    parser.add_argument("--base-model-dir", type=Path, required=True)
    parser.add_argument("--base-weight", type=Path, required=True)
    parser.add_argument("--output-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-iters", type=int, default=5000)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--accum-grad-iters", type=int, default=2)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260829)
    return parser.parse_args()


def _quoted(path: Path) -> str:
    return json.dumps(path.resolve().as_posix(), ensure_ascii=False)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_manifest(root: Path, profile: str) -> dict:
    root = root.resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("formula profile dataset manifest is unavailable") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "student_test_formula_profile_dataset_v1"
        or manifest.get("profile") != profile
        or tuple(manifest.get("grades") or ()) != formula_profile_datasets(profile)
        or manifest.get("answerKeyFieldsUsed") != 0
        or not (root / "images").is_dir()
        or not (root / "equations.txt").is_file()
    ):
        raise ValueError("formula profile dataset contract is invalid")
    return manifest


def training_config_text(
    *,
    train_root: Path,
    validation_root: Path,
    base_model_dir: Path,
    base_weight: Path,
    output_dir: Path,
    max_iters: int,
    batch_size: int,
    accum_grad_iters: int,
    num_workers: int,
    seed: int,
) -> str:
    warmup_steps = min(250, max(1, max_iters // 20))
    inner_epoch = min(1000, max_iters)
    return f"""model:
  arch: unimernet
  model_type: unimernet
  model_name: unimernet
  tokenizer_name: nougat
  model_config:
    model_name: {_quoted(base_model_dir)}
    max_seq_len: 1536
  load_pretrained: false
  load_finetuned: true
  finetuned: {_quoted(base_weight)}
  tokenizer_config:
    path: {_quoted(base_model_dir)}
datasets:
  formula_rec_train:
    sample_ratio: 1
    vis_processor:
      train:
        name: formula_image_train
        image_size: [192, 672]
    text_processor:
      train:
        name: blip_caption
        max_words: 1536
    build_info:
      images: {_quoted(train_root / 'images')}
      annotation: {_quoted(train_root / 'equations.txt')}
  formula_rec_eval:
    vis_processor:
      eval:
        name: formula_image_eval
        image_size: [192, 672]
    text_processor:
      eval:
        name: blip_caption
        max_words: 1536
    build_info:
      images: {_quoted(validation_root / 'images')}
      annotation: {_quoted(validation_root / 'equations.txt')}
run:
  runner: runner_iter
  task: unimernet_train
  lr_sched: linear_warmup_cosine_lr
  init_lr: 1.0e-5
  min_lr: 1.0e-7
  warmup_lr: 1.0e-6
  weight_decay: 0.01
  batch_size_train: {batch_size}
  batch_size_eval: {batch_size}
  accum_grad_iters: {accum_grad_iters}
  num_workers: {num_workers}
  warmup_steps: {warmup_steps}
  iters_per_inner_epoch: {inner_epoch}
  max_iters: {max_iters}
  milestone: [1]
  seed: {seed}
  output_dir: {_quoted(output_dir)}
  amp: true
  resume_ckpt_path: null
  evaluate: false
  train_splits: [train]
  valid_splits: [eval]
  device: cuda
  world_size: 1
  dist_url: env://
  distributed: false
  distributed_type: ddp
  generate_cfg:
    temperature: 0.0
"""


def generate(
    *,
    profile: str,
    train_root: Path,
    validation_root: Path,
    base_model_dir: Path,
    base_weight: Path,
    output_config: Path,
    output_dir: Path,
    max_iters: int = 5000,
    batch_size: int = 4,
    accum_grad_iters: int = 2,
    num_workers: int = 0,
    seed: int = 20260829,
) -> dict:
    formula_profile_datasets(profile)
    train_root = train_root.resolve()
    validation_root = validation_root.resolve()
    base_model_dir = base_model_dir.resolve()
    base_weight = base_weight.resolve()
    output_config = output_config.resolve()
    output_dir = output_dir.resolve()
    train_manifest = _profile_manifest(train_root, profile)
    validation_manifest = _profile_manifest(validation_root, profile)
    if not base_model_dir.is_dir() or not base_weight.is_file():
        raise ValueError("UniMERNet base model and weight must exist")
    if max_iters < 1 or batch_size < 1 or accum_grad_iters < 1 or num_workers < 0:
        raise ValueError("UniMERNet training parameters are invalid")
    if train_root == validation_root:
        raise ValueError("training and validation roots must differ")
    signatures = {"train": dataset_signature(train_root), "eval": dataset_signature(validation_root)}
    if signatures["train"]["count"] != train_manifest.get("count") or signatures["eval"]["count"] != validation_manifest.get("count"):
        raise ValueError("formula manifest count disagrees with actual images")
    text = training_config_text(
        train_root=train_root,
        validation_root=validation_root,
        base_model_dir=base_model_dir,
        base_weight=base_weight,
        output_dir=output_dir,
        max_iters=max_iters,
        batch_size=batch_size,
        accum_grad_iters=accum_grad_iters,
        num_workers=num_workers,
        seed=seed,
    )
    output_config.parent.mkdir(parents=True, exist_ok=True)
    output_config.write_text(text, encoding="utf-8")
    summary = {
        "schema": "student_test_formula_training_config_v1",
        "profile": profile,
        "grades": list(formula_profile_datasets(profile)),
        "trainCount": int(train_manifest.get("count") or 0),
        "validationCount": int(validation_manifest.get("count") or 0),
        "trainDataset": str(train_root),
        "validationDataset": str(validation_root),
        "baseModelDir": str(base_model_dir),
        "baseWeight": str(base_weight),
        "baseWeightSha256": _sha256_file(base_weight),
        "datasetSignatures": signatures,
        "validationEvidence": "official_split_diagnostic_not_camera_holdout",
        "returnCheckpointSelection": "best_validation; never silently substitute latest",
        "outputConfig": str(output_config),
        "outputDir": str(output_dir),
        "device": "cuda",
        "maxIters": max_iters,
        "batchSize": batch_size,
        "accumGradIters": accum_grad_iters,
        "numWorkers": num_workers,
        "configSha256": _sha256_file(output_config),
        "answerKeyFieldsUsed": 0,
    }
    output_config.with_suffix(output_config.suffix + ".manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    args = parse_args()
    summary = generate(
        profile=args.profile,
        train_root=args.train_dataset,
        validation_root=args.validation_dataset,
        base_model_dir=args.base_model_dir,
        base_weight=args.base_weight,
        output_config=args.output_config,
        output_dir=args.output_dir,
        max_iters=max(1, args.max_iters),
        batch_size=max(1, args.batch_size),
        accum_grad_iters=max(1, args.accum_grad_iters),
        num_workers=max(0, args.num_workers),
        seed=args.seed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
