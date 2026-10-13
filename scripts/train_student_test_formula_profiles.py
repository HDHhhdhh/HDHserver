from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Final, Sequence

from core.student_test_formula_profiles import FORMULA_PROFILE_DATASETS, formula_profile_datasets
from scripts.student_test_formula_dataset_contract import dataset_signature


ROOT: Final = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preflight and sequentially fine-tune the two CUDA UniMERNet formula profiles."
    )
    parser.add_argument("--config", type=Path, action="append", default=[])
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--single-config", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.single_config is not None and (args.config or args.preflight_only):
        parser.error("--single-config is internal and cannot be combined with parent options")
    if args.single_config is None and not args.config:
        parser.error("at least one --config is required")
    return args


def training_config_contract(path: Path) -> dict:
    path = path.resolve()
    try:
        config_text = path.read_text(encoding="utf-8")
        manifest = json.loads(path.with_suffix(path.suffix + ".manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("UniMERNet formula training config manifest is invalid") from error
    profile = str(manifest.get("profile") or "") if isinstance(manifest, dict) else ""
    if (
        profile not in FORMULA_PROFILE_DATASETS
        or manifest.get("schema") != "student_test_formula_training_config_v1"
        or tuple(manifest.get("grades") or ()) != formula_profile_datasets(profile)
        or manifest.get("device") != "cuda"
        or manifest.get("answerKeyFieldsUsed") != 0
        or manifest.get("outputConfig") != str(path)
        or manifest.get("configSha256") != _sha256_file(path)
    ):
        raise ValueError("UniMERNet formula training config manifest contract is invalid")
    max_iters = int(manifest.get("maxIters") or 0)
    if "  device: cuda\n" not in config_text or "  runner: runner_iter\n" not in config_text or max_iters < 1:
        raise ValueError("UniMERNet formula training config must use the CUDA iteration runner")
    weight = Path(str(manifest.get("baseWeight") or "")).resolve()
    if not weight.is_file():
        raise ValueError("UniMERNet base weight is missing")
    if manifest.get("baseWeightSha256") != _sha256_file(weight):
        raise ValueError("base weight is unbound or changed; regenerate the training config manifest")
    expected_splits = {
        "train": (Path(str(manifest.get("trainDataset") or "")).resolve(), int(manifest.get("trainCount") or 0)),
        "eval": (Path(str(manifest.get("validationDataset") or "")).resolve(), int(manifest.get("validationCount") or 0)),
    }
    split_rows = {}
    if expected_splits["train"][0] == expected_splits["eval"][0]:
        raise ValueError("training and validation roots must differ")
    signatures = manifest.get("datasetSignatures")
    if not isinstance(signatures, dict):
        raise ValueError("training data is unbound; regenerate the training config manifest")
    for split_name, (dataset_root, expected_count) in expected_splits.items():
        images = dataset_root / "images"
        annotation = dataset_root / "equations.txt"
        if not images.is_dir() or not annotation.is_file() or expected_count < 1:
            raise ValueError("UniMERNet formula training dataset input is missing")
        if len(annotation.read_text(encoding="utf-8").splitlines()) != expected_count:
            raise ValueError("UniMERNet formula training annotation count mismatch")
        if dataset_signature(dataset_root) != signatures.get(split_name):
            raise ValueError("UniMERNet training dataset content changed")
        split_rows[split_name] = {"count": expected_count, "images": str(images), "annotation": str(annotation)}
    return {
        "profile": profile,
        "config": str(path),
        "configManifest": str(path.with_suffix(path.suffix + ".manifest.json")),
        "maxIters": max_iters,
        "batchSize": int(manifest.get("batchSize") or 0),
        "accumGradIters": int(manifest.get("accumGradIters") or 0),
        "outputDir": str(Path(str(manifest.get("outputDir") or "")).resolve()),
        "baseWeight": str(weight),
        "splits": split_rows,
        "answerKeyFieldsUsed": 0,
    }


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cuda_status() -> dict:
    import torch

    available = bool(torch.cuda.is_available())
    devices = []
    if available:
        for index in range(torch.cuda.device_count()):
            properties = torch.cuda.get_device_properties(index)
            devices.append(
                {
                    "index": index,
                    "name": properties.name,
                    "memoryBytes": int(properties.total_memory),
                }
            )
    return {
        "torchVersion": torch.__version__,
        "torchCudaBuild": torch.version.cuda,
        "cudaAvailable": available,
        "cudaDeviceCount": len(devices),
        "devices": devices,
    }


def preflight(config_paths: Sequence[Path]) -> dict:
    configs = [training_config_contract(path) for path in config_paths]
    profiles = [item["profile"] for item in configs]
    if len(set(profiles)) != len(profiles):
        raise ValueError("UniMERNet formula training profiles must be unique")
    cuda = cuda_status()
    return {
        "schema": "student_test_formula_training_preflight_v1",
        "ready": bool(cuda["cudaAvailable"] and cuda["cudaDeviceCount"] >= 1),
        "execution": "sequential single-GPU direct jobs" if sys.platform == "win32" else "sequential single-GPU torchrun jobs",
        "configs": configs,
        "cuda": cuda,
        "answerKeyFieldsUsed": 0,
    }


def torchrun_command(config_path: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "torch.distributed.run",
        "--standalone",
        "--nproc_per_node=1",
        "--module",
        "scripts.train_student_test_formula_profiles",
        "--single-config",
        str(config_path.resolve()),
    ]


def training_command(config_path: Path, *, platform: str | None = None) -> list[str]:
    if (platform or sys.platform) == "win32":
        return [sys.executable, "-B", "-m", "scripts.train_student_test_formula_profiles",
                "--single-config", str(config_path.resolve())]
    return torchrun_command(config_path)


@contextmanager
def single_process_barrier(dist):
    """Upstream runner_iter calls barrier even with distributed:false.

    This adapter is confined to the single-config subprocess, leaves an initialized
    process group untouched, and restores the library function on every exit.
    """
    barrier = dist.barrier
    def guarded(*args, **kwargs):
        if dist.is_available() and dist.is_initialized():
            return barrier(*args, **kwargs)
        return None
    dist.barrier = guarded
    try:
        yield
    finally:
        dist.barrier = barrier


def selected_checkpoint(run_directory: Path) -> Path:
    path = run_directory / "checkpoint_best.pth"
    if not path.is_file():
        raise RuntimeError("best checkpoint is missing; latest must not be substituted")
    return path


def _setup_seeds(config) -> None:
    import numpy as np
    import torch
    import torch.backends.cudnn as cudnn
    from unimernet.common.dist_utils import get_rank

    seed = int(config.run_cfg.seed) + get_rank()
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    cudnn.benchmark = False
    cudnn.deterministic = True


def run_single_config(config_path: Path) -> None:
    if not cuda_status()["cudaAvailable"]:
        raise RuntimeError("UniMERNet formula fine-tuning requires an NVIDIA CUDA PyTorch environment")
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    import unimernet.datasets.builders  # noqa: F401
    import unimernet.common.optims  # noqa: F401 -- registers the configured LR schedule
    import unimernet.models  # noqa: F401
    import unimernet.processors  # noqa: F401
    import unimernet.runners  # noqa: F401
    import unimernet.tasks as tasks
    from unimernet.common.config import Config
    from unimernet.common.dist_utils import init_distributed_mode
    from unimernet.common.logger import setup_logger
    from unimernet.common.registry import registry
    from unimernet.common.utils import now

    contract = training_config_contract(config_path)
    config_args = argparse.Namespace(cfg_path=str(config_path.resolve()), options=None)
    cfg = Config(config_args)
    init_distributed_mode(cfg.run_cfg)
    _setup_seeds(cfg)
    setup_logger()
    cfg.pretty_print()
    task = tasks.setup_task(cfg)
    datasets = task.build_datasets(cfg)
    model = task.build_model(cfg)
    runner_class = registry.get_runner_class(cfg.run_cfg.get("runner", "runner_base"))
    if runner_class is None:
        raise RuntimeError("UniMERNet training runner is unavailable")
    runner = runner_class(cfg=cfg, job_id=now(), task=task, model=model, datasets=datasets)
    print(json.dumps({"progress": "formula_training_started", "profile": contract["profile"]}), flush=True)
    import torch.distributed as dist
    with single_process_barrier(dist):
        runner.train()
    selected = selected_checkpoint(Path(runner.output_dir))
    print(json.dumps({"progress": "formula_training_completed", "profile": contract["profile"],
                      "selection": "best_validation", "checkpoint": str(selected),
                      "checkpointSha256": _sha256_file(selected), "deploymentReady": False}), flush=True)


def main() -> int:
    args = parse_args()
    if args.single_config is not None:
        run_single_config(args.single_config)
        return 0
    report = preflight(args.config)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if args.preflight_only:
        return 0
    if not report["ready"]:
        raise RuntimeError("UniMERNet formula fine-tuning is blocked: NVIDIA CUDA is unavailable")
    for config_path in args.config:
        subprocess.run(training_command(config_path), cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
