from __future__ import annotations

import json
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.train_student_test_formula_profiles import preflight, torchrun_command, training_config_contract
from scripts.student_test_formula_dataset_contract import dataset_signature
from scripts.train_student_test_formula_profiles import training_command, single_process_barrier, selected_checkpoint


def run() -> dict:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="formula-profile-train-") as temp_dir:
        root = Path(temp_dir)
        train = root / "train"
        validation = root / "validation"
        model = root / "model"
        for dataset, count in ((train, 2), (validation, 1)):
            (dataset / "images").mkdir(parents=True)
            for index in range(count):
                (dataset / "images" / f"{index:07d}.png").write_bytes(b"fixture")
            (dataset / "equations.txt").write_text("\n".join("x" for _ in range(count)) + "\n", encoding="utf-8")
        model.mkdir()
        weight = model / "unimernet_tiny.pth"
        weight.write_bytes(b"weight")
        config = root / "m3_h1.yaml"
        config.write_text(
            f"""model:
  finetuned: {weight.as_posix()}
datasets:
  formula_rec_train:
    build_info:
      images: {(train / 'images').as_posix()}
      annotation: {(train / 'equations.txt').as_posix()}
  formula_rec_eval:
    build_info:
      images: {(validation / 'images').as_posix()}
      annotation: {(validation / 'equations.txt').as_posix()}
run:
  runner: runner_iter
  device: cuda
  max_iters: 10
  batch_size_train: 2
  accum_grad_iters: 1
  output_dir: {(root / 'output').as_posix()}
""",
            encoding="utf-8",
        )
        config.with_suffix(".yaml.manifest.json").write_text(
            json.dumps(
                {
                    "schema": "student_test_formula_training_config_v1",
                    "profile": "m3_h1",
                    "grades": ["M_G3", "H_G1"],
                    "trainCount": 2,
                    "validationCount": 1,
                    "trainDataset": str(train.resolve()),
                    "validationDataset": str(validation.resolve()),
                    "baseWeight": str(weight.resolve()),
                    "baseWeightSha256": hashlib.sha256(weight.read_bytes()).hexdigest(),
                    "datasetSignatures": {"train": dataset_signature(train), "eval": dataset_signature(validation)},
                    "outputConfig": str(config.resolve()),
                    "outputDir": str((root / "output").resolve()),
                    "device": "cuda",
                    "maxIters": 10,
                    "batchSize": 2,
                    "accumGradIters": 1,
                    "numWorkers": 0,
                    "configSha256": hashlib.sha256(config.read_bytes()).hexdigest(),
                    "answerKeyFieldsUsed": 0,
                }
            ),
            encoding="utf-8",
        )
        contract = training_config_contract(config)
        assert contract["profile"] == "m3_h1" and contract["splits"]["train"]["count"] == 2
        assert contract["splits"]["eval"]["count"] == 1 and contract["answerKeyFieldsUsed"] == 0
        assertions += 2
        image = train / "images" / "0000001.png"
        image.unlink()
        try:
            training_config_contract(config)
        except ValueError:
            pass
        else:
            raise AssertionError("missing training image was accepted")
        image.write_bytes(b"changed-image")
        try:
            training_config_contract(config)
        except ValueError:
            pass
        else:
            raise AssertionError("changed training image was accepted")
        image.write_bytes(b"fixture")
        assertions += 2
        with patch(
            "scripts.train_student_test_formula_profiles.cuda_status",
            return_value={
                "torchVersion": "fixture",
                "torchCudaBuild": "fixture",
                "cudaAvailable": True,
                "cudaDeviceCount": 1,
                "devices": [{"index": 0, "name": "fixture", "memoryBytes": 1}],
            },
        ):
            report = preflight([config])
        import sys
        assert report["execution"] == ("sequential single-GPU direct jobs" if sys.platform == "win32" else "sequential single-GPU torchrun jobs")
        assert report["ready"] is True and report["cuda"]["cudaDeviceCount"] == 1
        assertions += 2
        command = torchrun_command(config)
        assert command[-3:] == ["scripts.train_student_test_formula_profiles", "--single-config", str(config.resolve())]
        assert "--nproc_per_node=1" in command and "--standalone" in command
        assertions += 2
        assert "torch.distributed.run" not in training_command(config, platform="win32")
        assert "torch.distributed.run" in training_command(config, platform="linux")
        from types import SimpleNamespace
        calls = []
        dist = SimpleNamespace(is_available=lambda: True, is_initialized=lambda: False,
                               barrier=lambda: calls.append("barrier"))
        original = dist.barrier
        with single_process_barrier(dist):
            dist.barrier()
            assert not calls
            dist.is_initialized = lambda: True
            dist.barrier()
        assert calls == ["barrier"] and dist.barrier is original
        (root / "checkpoint_latest.pth").write_bytes(b"latest")
        try:
            selected_checkpoint(root)
        except RuntimeError:
            pass
        else:
            raise AssertionError("latest silently replaced best")
        (root / "checkpoint_best.pth").write_bytes(b"best")
        assert selected_checkpoint(root).name == "checkpoint_best.pth"
        assertions += 6
    return {"name": "student-test-formula-profile-training", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
