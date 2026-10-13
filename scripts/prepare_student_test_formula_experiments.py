"""Create additive, public-data-only short-answer GPU experiment inputs."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from core.student_test_formula_profiles import FORMULA_PROFILE_DATASETS
from scripts.build_student_test_formula_profile_dataset import build_profile
from scripts.student_test_formula_dataset_contract import dataset_signature


def audit_profile(root):
    from PIL import Image
    rows = [json.loads(line) for line in (root / "provenance.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    signature = dataset_signature(root)
    for path in (root / "images").glob("*.png"):
        with Image.open(path) as image:
            image.verify()
    if len(rows) != signature["count"]:
        raise ValueError("provenance/image count mismatch")
    return {"count": signature["count"], "writers": len({r["writerHash"] for r in rows}),
            "grades": dict(Counter(r["grade"] for r in rows)), "signature": signature,
            "decodedImages": signature["count"], "filter": manifest["filtered"],
            "writerScope": "grade-scoped supplied writerHash; not verified personal identity"}


def prepare(source_root, output):
    source_root, output = source_root.resolve(), output.resolve()
    if output == source_root or output.is_relative_to(source_root):
        raise ValueError("experiments must be outside source data")
    if output.exists() and any(output.iterdir()):
        raise ValueError("experiment output must be empty")
    report = {"schema": "student_test_formula_experiment_inputs_v1", "providerCallCount": 0,
              "deploymentReady": False, "trainingExecuted": False, "profiles": {}}
    for profile, grades in FORMULA_PROFILE_DATASETS.items():
        roots = lambda split: {grade: source_root / "formula_converted" / split / grade for grade in grades}
        train = output / "training" / profile
        validation = output / "validation" / profile
        full_train = source_root / "formula_profiles" / "training" / profile
        build_profile(profile=profile, grade_roots=roots("training"), output_root=train, numeric_answers_only=True)
        build_profile(profile=profile, grade_roots=roots("validation"), output_root=validation,
                      numeric_answers_only=True, exclude_writers_from=full_train)
        train_audit, valid_audit = audit_profile(train), audit_profile(validation)
        train_writers = {json.loads(line)["writerHash"] for line in (full_train / "provenance.jsonl").read_text(encoding="utf-8").splitlines()}
        valid_writers = {json.loads(line)["writerHash"] for line in (validation / "provenance.jsonl").read_text(encoding="utf-8").splitlines()}
        if train_writers & valid_writers:
            raise ValueError("validation writer exclusion failed")
        report["profiles"][profile] = {"focusedTraining": train_audit, "numericValidation": valid_audit,
            "fullTrainingControl": str(full_train), "excludedAgainst": "entire original training profile",
            "missingValidationGrades": [grade for grade in grades if not valid_audit["grades"].get(grade)],
            "warning": "Few writers; development validation only. Do not claim unseen-grade or camera accuracy."}
        print(json.dumps({"prepared": profile, "training": train_audit["count"], "validation": valid_audit["count"],
                          "validationWriters": valid_audit["writers"]}), flush=True)
    with (output / "EXPERIMENT_INPUTS.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.source_root, args.output)
    print(json.dumps({"ok": True, "output": str(args.output.resolve()), "trainingExecuted": report["trainingExecuted"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
