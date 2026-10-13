"""Build new, public-only expanded GPU inputs. No model load, training or runtime access."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import shutil

from PIL import Image

from core.student_test_formula_profiles import formula_profile_datasets
from scripts.build_student_test_formula_profile_dataset import sha256_file
from scripts.student_test_formula_dataset_contract import dataset_signature
from scripts.student_test_formula_expansion_selection import selection_kind

PROFILES = ("m3_h1", "m3_h1_h2_h3")
SEED = 20260907
# Approved 2026-09-06 packet fingerprints, not a new hash baseline computed at intake.
FROZEN_SIGNATURES = {
    "m3_h1": {
        "count": 1459,
        "annotationSha256": "c584b121ced9bb55f96260b05b632e0c039271843d1b8c534e0e3207e2eb5aea",
        "imagesSha256": "d8094d2982d7f7cbab934f2f1c04b1e5c5c32d1b9bdc5cfad36da6aa90de6ba7",
        "provenanceSha256": "d994c40fdea5b3f3086bb26309446143b528b5e601a9232ad86a20d08b36b808",
        "manifestSha256": "85dcd494bbd9ba8cf0306e114635042a68d1c88be458d01ac939a132bef4c0d4",
    },
    "m3_h1_h2_h3": {
        "count": 1473,
        "annotationSha256": "55058cba3275f8a38c47bb099c87eed6e39f64a872d9d0b13b474499c547c1a8",
        "imagesSha256": "b9fa4f99340eedb6f07fd103ee2af60157f20b7cf9614cd77deb2a77e0e43153",
        "provenanceSha256": "14c705f97244e8a1fd132b4f75b7e9127575d24a73bec496ff159d5f81273fc2",
        "manifestSha256": "cc358e9e519035988b2c72ad7a0cdd4d62859ca8cdf1c14aedcfcb867bf05d07",
    },
}
VISUAL_QUARANTINE = {
    "03aa1e9292342b7b16def84eb85df1cf49538b5c269c54df5a889d19acd9dbc0":
        "2026-09-07 training-only visual spot check: image shows raised 6 and trailing equals; transcription lacks exponent marker/equals. Excluded, not relabeled."
}


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def load_rows(root):
    signature = dataset_signature(root)
    labels = (root / "equations.txt").read_text(encoding="utf-8").splitlines()
    provenance = [json.loads(line) for line in (root / "provenance.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if (len(provenance) != len(labels) or manifest.get("answerKeyFieldsUsed") != 0
            or manifest.get("count") != len(labels)):
        raise ValueError("source dataset contract mismatch")
    rows = []
    for index, (label, prov) in enumerate(zip(labels, provenance)):
        if prov.get("index") != index or not all(prov.get(key) for key in ("grade", "writerHash", "sourceHash")):
            raise ValueError("incomplete source provenance")
        image = root / "images" / f"{index:07d}.png"
        rows.append({**prov, "label": label, "image": image, "imageSha256": sha256_file(image)})
    return rows, {**signature, "provenanceSha256": sha256_file(root / "provenance.jsonl"),
                  "manifestSha256": sha256_file(root / "manifest.json")}


def verify_frozen(root):
    for profile, expected in FROZEN_SIGNATURES.items():
        actual = load_rows(root / profile)[1]
        if actual != expected:
            raise ValueError(f"approved frozen validation changed: {profile}; actual={actual}; expected={expected}")


def materialize(rows, output, profile, kind, source_signature):
    (output / "images").mkdir(parents=True, exist_ok=False)
    rows = list(rows)
    random.Random(SEED).shuffle(rows)
    with (output / "equations.txt").open("x", encoding="utf-8", newline="\n") as labels, \
            (output / "provenance.jsonl").open("x", encoding="utf-8", newline="\n") as provenance:
        for index, row in enumerate(rows):
            with Image.open(row["image"]) as image:
                image.verify()
            destination = output / "images" / f"{index:07d}.png"
            shutil.copyfile(row["image"], destination)
            if sha256_file(destination) != row["imageSha256"]:
                raise ValueError("image copy hash mismatch")
            labels.write(row["label"] + "\n")
            provenance.write(json.dumps({"index": index, "grade": row["grade"], "writerHash": row["writerHash"],
                "sourceHash": row["sourceHash"], "sourceIndex": row["index"], "sourceImageSha256": row["imageSha256"],
                "selectionKind": row["selectionKind"], "transcriptionUnchanged": True}, ensure_ascii=False) + "\n")
    manifest = {"schema": "student_test_formula_profile_dataset_v1", "profile": profile,
        "grades": list(formula_profile_datasets(profile)), "count": len(rows),
        "countsByGrade": dict(Counter(row["grade"] for row in rows)),
        "countsByKind": dict(Counter(row["selectionKind"] for row in rows)),
        "selectedWriters": len({(row["grade"], row["writerHash"]) for row in rows}),
        "selection": kind, "selectionSeed": SEED, "transcriptionsRewritten": 0,
        "sourceSignature": source_signature, "answerKeyFieldsUsed": 0,
        "includesStudentPhotos": False, "deploymentReady": False}
    write_json(output / "manifest.json", manifest)
    return {**manifest, "signature": dataset_signature(output)}


def prepare(full_root, frozen_root, output):
    full_root, frozen_root, output = full_root.resolve(), frozen_root.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(full_root) or output.is_relative_to(frozen_root):
        raise ValueError("output must be new and outside source datasets")
    verify_frozen(frozen_root / "validation")
    source = full_root / "m3_h1_h2_h3"
    rows, source_signature = load_rows(source)
    validation = {}
    val_writers, val_sources, val_images = set(), set(), set()
    for profile in PROFILES:
        val_rows, signature = load_rows(frozen_root / "validation" / profile)
        if len(val_rows) != {"m3_h1": 1459, "m3_h1_h2_h3": 1473}[profile]:
            raise ValueError("frozen validation denominator changed")
        validation[profile] = {"rows": val_rows, "signature": signature}
        val_writers.update((r["grade"], r["writerHash"]) for r in val_rows)
        val_sources.update(r["sourceHash"] for r in val_rows)
        val_images.update(r["imageSha256"] for r in val_rows)
    image_labels = defaultdict(set)
    for row in rows:
        image_labels[row["imageSha256"]].add(row["label"])
    selected, excluded = [], []
    seen = set()
    for row in rows:
        kind = selection_kind(row["label"])
        if row["imageSha256"] in VISUAL_QUARANTINE:
            reason = "visualTranscriptionMismatch"
        elif (row["grade"], row["writerHash"]) in val_writers:
            reason = "validationWriterOverlap"
        elif row["sourceHash"] in val_sources:
            reason = "validationSourceOverlap"
        elif row["imageSha256"] in val_images:
            reason = "validationImageOverlap"
        elif len(image_labels[row["imageSha256"]]) > 1:
            reason = "conflictingDuplicateImage"
        elif row["imageSha256"] in seen:
            reason = "duplicateImage"
        elif kind is None:
            reason = "outsideCompleteFormulaGrammar"
        else:
            reason = None
        if reason:
            excluded.append({"sourceIndex": row["index"], "grade": row["grade"], "reason": reason,
                             "imageSha256": row["imageSha256"]})
        else:
            seen.add(row["imageSha256"])
            selected.append({**row, "selectionKind": kind})
    output.mkdir(parents=True, exist_ok=False)
    profiles = {}
    for profile in PROFILES:
        grades = set(formula_profile_datasets(profile))
        expanded = [r for r in selected if r["grade"] in grades]
        focused = [r for r in expanded if r["selectionKind"] == "focused"]
        if not focused or len(expanded) <= len(focused):
            raise ValueError("expanded pool did not add complete formulas")
        destination = output / "validation" / profile
        shutil.copytree(frozen_root / "validation" / profile, destination)
        for row in validation[profile]["rows"]:
            with Image.open(row["image"]) as image:
                image.verify()
        if load_rows(destination)[1] != validation[profile]["signature"]:
            raise ValueError("frozen validation bytes changed")
        profiles[profile] = {
            "focused": materialize(focused, output / "training" / "focused" / profile, profile,
                                   "short numeric answer grammar plus representation aliases", source_signature),
            "expanded": materialize(expanded, output / "training" / "expanded" / profile, profile,
                                    "focused plus complete short numeric-bearing formulas; original transcription", source_signature),
            "validation": validation[profile]["signature"],
            "phaseAMicrobatches": max(1000, math.ceil(3 * len(expanded) / 4 / 1000) * 1000),
            "phaseBMicrobatches": max(1000, math.ceil(2 * len(focused) / 4 / 1000) * 1000),
        }
    if load_rows(source)[1] != source_signature:
        raise ValueError("source changed during preparation")
    for profile in PROFILES:
        if load_rows(frozen_root / "validation" / profile)[1] != validation[profile]["signature"]:
            raise ValueError("source validation changed during preparation")
    audit = {"sourceRoot": str(source), "sourceSignature": source_signature, "sourceCount": len(rows),
             "excludedCounts": dict(Counter(row["reason"] for row in excluded)), "excluded": excluded,
             "trainingValidationSeparation": ["grade-scoped writer hash", "source hash", "exact image SHA-256"],
             "identityIndependenceNotProven": True, "imagesVerified": True, "sourceUnchanged": True,
             "originalWriterCap": 200, "originalRawDatasetNotIncluded": True,
             "visualQuarantine": VISUAL_QUARANTINE, "allTranscriptionsVisuallyVerified": False}
    write_json(output / "SELECTION_AUDIT.json", audit)
    summary = {"schema": "student_test_formula_expansion_inputs_v1", "createdAt": datetime.now(timezone.utc).isoformat(),
               "seed": SEED, "batchSize": 4, "accumGradIters": 2, "profiles": profiles,
               "strategies": {"focused_control": ["focused", "focused"], "expanded_curriculum": ["expanded", "focused"]},
               "stageBoundary": "phase A final/latest with verified actual iteration; reset optimizer and LR in both arms",
               "trainingExecutionsPlanned": 8, "trainingExecuted": False, "providerCallCount": 0,
               "deploymentReady": False, "validationRole": "reused public development validation, NOT unseen holdout"}
    write_json(output / "EXPANSION_INPUTS.json", summary)
    return {"output": str(output), "profiles": {p: {"focused": v["focused"]["count"], "expanded": v["expanded"]["count"],
             "phaseA": v["phaseAMicrobatches"], "phaseB": v["phaseBMicrobatches"]} for p, v in profiles.items()},
            "excludedCounts": audit["excludedCounts"], "trainingExecuted": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-root", type=Path, required=True)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.full_root, args.frozen_root, args.output), ensure_ascii=False, indent=2))
