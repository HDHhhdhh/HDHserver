"""Prepare paired public-Training inputs only. Does not train, infer or access runtime."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import stat

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from scripts.student_test_formula_dataset_contract import dataset_signature
from scripts.student_test_formula_expansion_selection import focused_label

SOURCE_URL = (
    "https://www.aihub.or.kr/aihubdata/data/view.do?"
    "aihubDataSe=data&currMenu=115&dataSetSn=71300&topMenu=100"
)
AUDIT_SHA256 = "59a213514af94b7b0b3bcb078e0a6beaca221b29dcbc3758e0dee043433cdd3f"
LICENSE_REFERENCE = "docs/STUDENT_TEST_OCR_PUBLIC_DATA.md#공개-데이터-선택표"

# These are the selected public Training bytes, not approval of arbitrary input folders.
# The selection audit is historical separation evidence, not a new identity/license audit.
APPROVED_TRAINING = {
    "m3_h1": {
        "count": 967,
        "grades": ["M_G3", "H_G1"],
        "manifestSha256": "4c24b68db9e01cd53831a139dbf3405e589e969e2e40ed3719533515d38f686b",
        "provenanceSha256": "20a6f2807f763e668f1b157d6259057234a54d116375164d5953cdb242081349",
        "annotationSha256": "018fc996c9d62d9b698eb0b360edd2de9f0c8b811eb77106ec0bcdd774235ca5",
        "imagesSha256": "b94ac0512dcd7375fc8344e5c5fcf5f40f7e87af85218b0f8c2fe22254058032",
    },
    "m3_h1_h2_h3": {
        "count": 1757,
        "grades": ["M_G3", "H_G1", "H_G2", "H_G3"],
        "manifestSha256": "210b650ee9fe25ae5964917960a4b792449f895d13030b33f526cf349b90aab5",
        "provenanceSha256": "82d3d7181845db1a6c6971f77b959ea8ab00cf8a3c211215cf40b5d0a6f1e90f",
        "annotationSha256": "b2666d9f2522e9e08e8c9a133c1e2c3e47727c39c5dcfa61e37a4b66e9d6931c",
        "imagesSha256": "b6433afe2f817b14cceef817e34099d49916d6101fd09acd07c5056d4aa02163",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(path: Path, *, existing: bool = True) -> Path:
    """Inspect the unreduced path first; resolve() alone would hide linked ancestors."""
    for component in path.parts:
        if component == path.anchor:
            continue
        if (component == ".." or ":" in component
                or component.endswith((" ", ".")) or any(ord(value) < 32 for value in component)):
            raise ValueError("traversal, alternate streams and ambiguous paths are not allowed")
    path = Path(os.path.abspath(os.fspath(path)))
    for candidate in (path, *path.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0) & 0x400):
            raise ValueError("links and reparse points are not allowed")
    if existing and not path.exists():
        raise ValueError("required input is missing")
    return path.resolve(strict=existing)


def json_object(path: Path) -> dict:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def source_contract(source: Path, audit_path: Path, profile: str) -> tuple[dict, list[dict]]:
    source, audit_path = safe_path(source), safe_path(audit_path)
    if profile not in APPROVED_TRAINING or not source.is_dir() or not audit_path.is_file():
        raise ValueError("approved public Training profile is required")
    expected = APPROVED_TRAINING[profile]
    if sha256(audit_path) != AUDIT_SHA256:
        raise ValueError("historical selection audit differs from approved bytes")
    audit = json_object(audit_path)
    audit_bytes = sha256(audit_path)
    files = {}
    directories = set()
    for path in source.rglob("*"):
        safe_path(path)
        if path.is_file():
            files[path.relative_to(source).as_posix()] = path
        elif path.is_dir():
            directories.add(path.relative_to(source).as_posix())
        else:
            raise ValueError("special source entry is not allowed")
    names = {f"images/{index:07d}.png" for index in range(expected["count"])}
    if set(files) != names | {"equations.txt", "provenance.jsonl", "manifest.json"} or directories != {"images"}:
        raise ValueError("source inventory does not match approved Training")
    manifest = json_object(files["manifest.json"])
    if (manifest.get("schema") != "student_test_formula_profile_dataset_v1"
            or manifest.get("profile") != profile or manifest.get("grades") != expected["grades"]
            or manifest.get("count") != expected["count"]
            or manifest.get("answerKeyFieldsUsed") != 0
            or manifest.get("includesStudentPhotos") is not False
            or manifest.get("deploymentReady") is not False
            or manifest.get("dataRole", "training") != "training"
            or manifest.get("sourceSignature") != audit.get("sourceSignature")
            or audit.get("sourceUnchanged") is not True
            or audit.get("identityIndependenceNotProven") is not True
            or audit.get("trainingValidationSeparation") != [
                "grade-scoped writer hash", "source hash", "exact image SHA-256"]):
        raise ValueError("public Training provenance contract failed")
    observed = {
        **dataset_signature(source),
        "manifestSha256": sha256(files["manifest.json"]),
        "provenanceSha256": sha256(files["provenance.jsonl"]),
    }
    if any(observed.get(key) != expected[key] for key in (
            "count", "manifestSha256", "provenanceSha256", "annotationSha256", "imagesSha256")):
        raise ValueError("source is not an audited Training allowlist member")
    labels = files["equations.txt"].read_text(encoding="utf-8").splitlines()
    lines = files["provenance.jsonl"].read_text(encoding="utf-8").splitlines()
    if len(lines) != len(labels) or any(not focused_label(label) for label in labels):
        raise ValueError("focused labels/provenance coverage failed")
    rows = []
    for index, line in enumerate(lines):
        row = json.loads(line)
        path = files[f"images/{index:07d}.png"]
        image_sha = sha256(path)
        if (not isinstance(row, dict) or row.get("index") != index
                or row.get("grade") not in expected["grades"]
                or not isinstance(row.get("writerHash"), str) or not row["writerHash"]
                or not isinstance(row.get("sourceHash"), str) or len(row["sourceHash"]) != 64
                or row.get("sourceImageSha256") != image_sha
                or row.get("transcriptionUnchanged") is not True
                or row.get("selectionKind") != "focused"):
            raise ValueError("source row/image binding failed")
        with Image.open(path) as image:
            if image.format != "PNG" or not 1 <= image.width <= 4096 or not 1 <= image.height <= 4096:
                raise ValueError("source image bounds/format failed")
            image.verify()
        rows.append({**row, "inputImageSha256": image_sha})
    if sha256(audit_path) != audit_bytes:
        raise ValueError("audit changed during source validation")
    return {
        "profile": profile, "grades": expected["grades"], "sourceSignature": observed,
        "sourceRoot": str(source), "selectionAudit": {
            "path": str(audit_path), "sha256": audit_bytes,
            "role": "historical selection audit; separation not re-executed",
        },
        "sourceReference": SOURCE_URL,
        "licenseReference": LICENSE_REFERENCE,
        "licenseReview": "existing source-policy reference only; no new legal verification",
        "answerKeyFieldsUsed": 0, "includesStudentPhotos": False,
    }, rows


def camera_image(source: Path, *, seed: int, index: int, image_sha: str) -> tuple[Image.Image, dict]:
    derived = hashlib.sha256(f"{seed}:{index}:{image_sha}".encode("ascii")).digest()
    rng = random.Random(int.from_bytes(derived, "big"))
    with Image.open(source) as opened:
        if opened.mode in ("RGBA", "LA") or "transparency" in opened.info:
            rgba = opened.convert("RGBA")
            image = Image.new("RGBA", rgba.size, "white")
            image.alpha_composite(rgba)
            image = image.convert("RGB")
        else:
            image = opened.convert("RGB")
    padding = math.ceil(max(image.size) * 0.12) + 8
    image = ImageOps.expand(image, border=padding, fill="white")
    width, height = image.size
    jitter = max(1, math.ceil(min(width, height) * 0.012))
    offsets = [rng.uniform(0.0, jitter) for _ in range(8)]
    quad = [-offsets[0], -offsets[1], -offsets[2], height + offsets[3],
            width + offsets[4], height + offsets[5], width + offsets[6], -offsets[7]]
    image = image.transform(image.size, Image.Transform.QUAD, quad,
                            resample=Image.Resampling.BICUBIC, fillcolor="white")
    angle = rng.uniform(-2.0, 2.0)
    image = image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    brightness, contrast = rng.uniform(0.95, 1.05), rng.uniform(0.95, 1.05)
    blur = rng.uniform(0.0, 0.45)
    image = ImageEnhance.Brightness(image).enhance(brightness)
    image = ImageEnhance.Contrast(image).enhance(contrast)
    image = image.filter(ImageFilter.GaussianBlur(blur))
    return image, {
        "seed": seed, "derivedSeedSha256": derived.hex(), "paddingPixels": padding,
        "perspectiveSourceQuad": quad, "rotationDegrees": angle,
        "brightnessFactor": brightness, "contrastFactor": contrast, "blurRadius": blur,
        "rotationExpand": True, "fill": "white", "outputSize": list(image.size),
        "visualReadabilityAudit": "pending; bounded transforms do not prove label preservation",
    }


def write_new_json(path: Path, value: dict) -> None:
    safe_path(path, existing=False)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def copy_new(source: Path, target: Path) -> None:
    safe_path(source)
    safe_path(target, existing=False)
    with source.open("rb") as original, target.open("xb") as copied:
        shutil.copyfileobj(original, copied)


def prepare(source: Path, audit_path: Path, output: Path, *, profile: str, seed: int = 20261004) -> dict:
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an unsigned 32-bit integer")
    source, audit_path = safe_path(source), safe_path(audit_path)
    output = safe_path(output, existing=False)
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("fresh output outside source is required")
    contract, rows = source_contract(source, audit_path, profile)
    output.mkdir(parents=True, exist_ok=False)
    parent_identity = hashlib.sha256(
        json.dumps(contract["sourceSignature"], sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    outputs = {}
    for arm in ("control", "camera_aug"):
        destination = output / arm
        (destination / "images").mkdir(parents=True, exist_ok=False)
        copy_new(source / "equations.txt", destination / "equations.txt")
        with (destination / "provenance.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for index, row in enumerate(rows):
                original = safe_path(source / "images" / f"{index:07d}.png")
                target = safe_path(destination / "images" / f"{index:07d}.png", existing=False)
                if sha256(original) != row["inputImageSha256"]:
                    raise ValueError("source image changed during preparation")
                if arm == "control":
                    copy_new(original, target)
                    parameters = {"transform": "none", "byteIdenticalToParent": True}
                else:
                    image, parameters = camera_image(original, seed=seed, index=index,
                                                       image_sha=row["inputImageSha256"])
                    try:
                        with target.open("xb") as image_stream:
                            image.save(image_stream, format="PNG")
                    finally:
                        image.close()
                output_sha = sha256(target)
                if arm == "control" and output_sha != row["inputImageSha256"]:
                    raise ValueError("control copy differs from source")
                stream.write(json.dumps({
                    **row, "parentDatasetId": parent_identity, "parentIndex": index,
                    "parentImageSha256": row["inputImageSha256"], "outputImageSha256": output_sha,
                    "arm": arm, "dataRole": "training", "syntheticCameraAugmentation": arm == "camera_aug",
                    "transformParameters": parameters,
                }, ensure_ascii=False) + "\n")
        if sha256(destination / "equations.txt") != contract["sourceSignature"]["annotationSha256"]:
            raise ValueError("annotation bytes changed")
        observed = dataset_signature(destination)
        manifest = {
            "schema": "student_test_formula_profile_dataset_v1", "profile": profile,
            "grades": contract["grades"], "count": len(rows), "dataRole": "training",
            "numericAnswersOnly": True, "countsByGrade": dict(Counter(row["grade"] for row in rows)),
            "sourceSignature": contract["sourceSignature"], "parentDatasetId": parent_identity,
            "selectedWriters": len({(row["grade"], row["writerHash"]) for row in rows}),
            "writerIdentityScope": "grade-scoped; cross-grade identity independence unproven",
            "arm": arm, "selectionSeed": seed, "oneImagePerOriginal": True,
            "transcriptionBytesUnchanged": True, "transcriptionsRewritten": 0,
            "augmentationVisualAudit": "pending" if arm == "camera_aug" else "not applicable",
            "evidenceClass": "synthetic_public_training_preparation",
            "answerKeyFieldsUsed": 0, "includesStudentPhotos": False,
            "sourceReference": contract["sourceReference"], "licenseReference": contract["licenseReference"],
            "licenseReview": contract["licenseReview"], "selectionAudit": contract["selectionAudit"],
            "trainingExecuted": False, "evaluationExecuted": False, "inferenceExecuted": False,
            "providerCallCount": 0, "deploymentReady": False,
            "limitations": [
                "Not real-camera, calibration, release holdout or deployment evidence",
                "Visual readability/label preservation must be audited before training",
                "Historical writer/source/exact-image separation was not re-executed",
                "No new source-license or independent-writer verification",
            ],
        }
        write_new_json(destination / "manifest.json", manifest)
        outputs[arm] = {
            "root": str(destination), "count": len(rows),
            "signature": {**observed, "provenanceSha256": sha256(destination / "provenance.jsonl"),
                          "manifestSha256": sha256(destination / "manifest.json")},
        }
    # A changed input invalidates this attempt. Keep its files, without a success receipt.
    after, _ = source_contract(source, audit_path, profile)
    if after != contract:
        raise ValueError("source changed during paired preparation")
    receipt = {
        "schema": "student_test_camera_augmentation_preparation_v1", "profile": profile, "seed": seed,
        "source": contract, "arms": outputs,
        "pairedComparison": "same source/count/order/annotation; image transform is the only changed factor",
        "augmentationVisualAudit": "pending", "trainingAllowed": False,
        "trainingExecuted": False, "evaluationExecuted": False, "inferenceExecuted": False,
        "providerCallCount": 0, "deploymentReady": False,
    }
    write_new_json(output / "AUGMENTATION_PREPARATION.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--selection-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=sorted(APPROVED_TRAINING), required=True)
    parser.add_argument("--seed", type=int, default=20261004)
    args = parser.parse_args()
    receipt = prepare(args.source, args.selection_audit, args.output, profile=args.profile, seed=args.seed)
    print(json.dumps({"output": str(args.output.resolve()), "profile": args.profile,
                      "counts": {arm: row["count"] for arm, row in receipt["arms"].items()},
                      "trainingExecuted": False, "providerCallCount": 0, "deploymentReady": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
