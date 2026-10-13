"""Bundle additive public experiment data and a minimal code snapshot, no weights."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from scripts.student_test_formula_dataset_contract import dataset_signature

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "core/__init__.py", "core/student_test_ocr_rules.py", "core/student_test_formula_profiles.py",
    "scripts/build_student_test_formula_profile_dataset.py", "scripts/generate_student_test_formula_training_config.py",
    "scripts/student_test_formula_dataset_contract.py", "scripts/train_student_test_formula_profiles.py",
    "scripts/student_test_unimernet_worker.py", "scripts/student_test_formula_inference.py",
    "scripts/evaluate_student_test_formula_dataset.py", "scripts/run_student_test_formula_experiments.py",
    "scripts/verify_student_test_formula_training_config.py", "scripts/verify_student_test_formula_profile_training.py",
)


def build(packet, archive, data_source=None):
    packet, archive = packet.resolve(), archive.resolve()
    if data_source is not None:
        if packet.exists():
            raise ValueError("copied-data packet must use a new directory")
        def materialize(source, target):
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
            return target
        shutil.copytree(data_source.resolve(), packet / "data", copy_function=materialize)
    if not (packet / "data" / "EXPERIMENT_INPUTS.json").is_file():
        raise ValueError("prepared public-data experiment inputs are required")
    if archive.exists() or archive.is_relative_to(packet) or (packet / "code").exists() or (packet / "PACKET_MANIFEST.json").exists():
        raise ValueError("packet code/archive must be new and archive must be outside packet")
    for name in SOURCES:
        target = packet / "code" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    shutil.copyfile(ROOT / "docs" / "STUDENT_TEST_FREE_OCR_GPU_PROMPT.md", packet / "GPU_PROMPT.md")
    files = []
    for path in sorted(packet.rglob("*")):
        if path.is_file():
            files.append({"path": path.relative_to(packet).as_posix(), "bytes": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    inputs = json.loads((packet / "data" / "EXPERIMENT_INPUTS.json").read_text(encoding="utf-8"))
    controls = {profile: dataset_signature(Path(row["fullTrainingControl"])) for profile, row in inputs["profiles"].items()}
    manifest = {"schema": "student_test_free_gpu_packet_v1", "files": files, "controlDatasets": controls, "includesStudentPhotos": False,
                "includesRuntimeDatabase": False, "includesModelWeights": False, "providerCallCount": 0,
                "deploymentReady": False}
    with (packet / "PACKET_MANIFEST.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(packet.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(packet).as_posix())
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None or len(zipped.namelist()) != len(files) + 1:
            raise ValueError("packet archive verification failed")
    receipt = {"archive": str(archive), "bytes": archive.stat().st_size,
               "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "files": len(files) + 1,
               "archiveVerified": True, "trainingExecuted": False, "deploymentReady": False}
    with archive.with_suffix(".receipt.json").open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--data-source", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.packet, args.archive, args.data_source)))
