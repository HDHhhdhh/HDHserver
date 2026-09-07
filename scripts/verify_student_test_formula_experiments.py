from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from scripts.evaluate_student_test_formula_dataset import grade_prediction, aggregate
from scripts.run_student_test_formula_experiments import verify_packet, validate_full_control
from scripts.student_test_formula_dataset_contract import dataset_signature


def run():
    assert grade_prediction(r"\frac{1}{2}", "0.5", True) == {"numericCorrect": True, "textExact": False}
    assert grade_prediction("3", "3", False) == {"numericCorrect": False, "textExact": False}
    assert grade_prediction("4", "3", True)["numericCorrect"] is False
    assert grade_prediction("nonsense", "3", True)["numericCorrect"] is False
    assert aggregate([{"numericCorrect": True, "textExact": True, "terminated": True},
                      {"numericCorrect": False, "textExact": False, "terminated": False}])["numericAccuracy"] == .5
    with tempfile.TemporaryDirectory(prefix="free-ocr-packet-check-") as temp:
        root = Path(temp)
        (root / "safe.txt").write_bytes(b"safe")
        entry = {"path": "safe.txt", "bytes": 4, "sha256": hashlib.sha256(b"safe").hexdigest()}
        (root / "PACKET_MANIFEST.json").write_text(json.dumps({"files": [entry]}), encoding="utf-8")
        assert len(verify_packet(root)["files"]) == 1
        (root / "safe.txt").write_bytes(b"evil")
        try:
            verify_packet(root)
        except ValueError:
            pass
        else:
            raise AssertionError("same-size packet mutation accepted")
        entry["path"] = "../outside.txt"
        (root / "PACKET_MANIFEST.json").write_text(json.dumps({"files": [entry]}), encoding="utf-8")
        try:
            verify_packet(root)
        except ValueError:
            pass
        else:
            raise AssertionError("packet path escape accepted")
        train, validation = root / "train", root / "validation"
        (train / "images").mkdir(parents=True)
        validation.mkdir()
        (train / "images" / "0000000.png").write_bytes(b"test image")
        (train / "equations.txt").write_text("3\n", encoding="utf-8")
        (train / "provenance.jsonl").write_bytes(b"writer-A")
        (validation / "manifest.json").write_text(json.dumps({"excludedTrainingProvenanceSha256": hashlib.sha256(b"writer-A").hexdigest()}), encoding="utf-8")
        signature = dataset_signature(train)
        validate_full_control(train, validation, signature)
        for file, value in (("provenance.jsonl", b"writer-B"), ("images/0000000.png", b"changed image")):
            (train / "provenance.jsonl").write_bytes(b"writer-A")
            (train / file).write_bytes(value)
            try:
                validate_full_control(train, validation, signature)
            except ValueError:
                pass
            else:
                raise AssertionError("changed full training control was accepted")
    return {"passed": True, "assertions": 11}


def real_smoke():
    from scripts.evaluate_student_test_formula_dataset import evaluate
    source = Path(r"C:\server\generated\free_ocr_20260906\gpu_packet\data\validation\m3_h1")
    with tempfile.TemporaryDirectory(prefix="free-ocr-real-eval-") as temp:
        root = Path(temp)
        dataset = root / "dataset"
        (dataset / "images").mkdir(parents=True)
        labels = (source / "equations.txt").read_text(encoding="utf-8").splitlines()[:4]
        provenance = (source / "provenance.jsonl").read_text(encoding="utf-8").splitlines()[:4]
        for index in range(4):
            shutil.copyfile(source / "images" / f"{index:07d}.png", dataset / "images" / f"{index:07d}.png")
        (dataset / "equations.txt").write_text("\n".join(labels) + "\n", encoding="utf-8")
        (dataset / "provenance.jsonl").write_text("\n".join(provenance) + "\n", encoding="utf-8")
        (dataset / "manifest.json").write_text(json.dumps({"count": 4, "answerKeyFieldsUsed": 0, "numericAnswersOnly": True}), encoding="utf-8")
        report = evaluate(dataset, Path(r"C:\server-ocr\models\unimernet_m3_h1"), "unimernet_m3_h1.pth", root / "output", "cpu")
        assert report["aggregate"]["count"] == 4 and report["deploymentReady"] is False
        assert len((root / "output" / "predictions.jsonl").read_text(encoding="utf-8").splitlines()) == 4
        return {"passed": True, "realImagePredictions": 4, "purpose": "execution smoke, not accuracy evidence"}


if __name__ == "__main__":
    import sys
    print(run())
    if "--real-smoke" in sys.argv:
        print(real_smoke())
