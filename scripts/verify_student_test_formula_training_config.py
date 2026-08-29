from __future__ import annotations

import json
import tempfile
from pathlib import Path

from core.student_test_formula_profiles import FORMULA_PROFILE_COMMON
from scripts.generate_student_test_formula_training_config import generate


def _dataset(root: Path) -> None:
    (root / "images").mkdir(parents=True)
    (root / "images" / "0000000.png").write_bytes(b"fixture")
    (root / "equations.txt").write_text("1/2\n", encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "student_test_formula_profile_dataset_v1",
                "profile": FORMULA_PROFILE_COMMON,
                "grades": ["M_G3", "H_G1"],
                "count": 1,
                "answerKeyFieldsUsed": 0,
            }
        ),
        encoding="utf-8",
    )


def run() -> dict:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="formula-training-config-") as temp_dir:
        root = Path(temp_dir)
        train = root / "train"
        validation = root / "validation"
        _dataset(train)
        _dataset(validation)
        model = root / "model"
        model.mkdir()
        weight = model / "unimernet_tiny.pth"
        weight.write_bytes(b"weight")
        config = root / "configs" / "m3_h1.yaml"
        summary = generate(
            profile=FORMULA_PROFILE_COMMON,
            train_root=train,
            validation_root=validation,
            base_model_dir=model,
            base_weight=weight,
            output_config=config,
            output_dir=root / "outputs",
            max_iters=120,
            batch_size=2,
            accum_grad_iters=4,
            num_workers=0,
            seed=17,
        )
        text = config.read_text(encoding="utf-8")
        assert summary["grades"] == ["M_G3", "H_G1"] and summary["device"] == "cuda"
        assert "load_finetuned: true" in text and weight.resolve().as_posix() in text
        assert "device: cuda" in text and "distributed: false" in text
        assert "batch_size_train: 2" in text and "accum_grad_iters: 4" in text
        assert "answerKey" not in text
        manifest = json.loads(config.with_suffix(".yaml.manifest.json").read_text(encoding="utf-8"))
        assert manifest["answerKeyFieldsUsed"] == 0 and manifest["maxIters"] == 120
        assertions += 6
    return {"name": "student-test-formula-training-config", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
