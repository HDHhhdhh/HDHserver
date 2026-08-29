from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
from collections import Counter
from pathlib import Path

from core.student_test_formula_profiles import FORMULA_PROFILE_DATASETS, formula_profile_datasets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build one natural-ratio UniMERNet dataset from converted AI Hub grade roots."
    )
    parser.add_argument("--profile", required=True, choices=sorted(FORMULA_PROFILE_DATASETS))
    parser.add_argument(
        "--grade-root",
        action="append",
        nargs=2,
        metavar=("GRADE", "PATH"),
        default=[],
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260829)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_grade_root(grade: str, root: Path) -> tuple[dict, list[dict]]:
    resolved = root.resolve()
    manifest_path = resolved / "manifest.json"
    samples_path = resolved / "samples.jsonl"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        lines = samples_path.read_text(encoding="utf-8").splitlines()
        samples = [json.loads(line) for line in lines if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"converted formula root is invalid for {grade}") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "student_test_aihub_formula_crops_v1"
        or manifest.get("grade") != grade
        or manifest.get("answerKeyFieldsUsed") != 0
        or manifest.get("count") != len(samples)
    ):
        raise ValueError(f"converted formula manifest contract is invalid for {grade}")
    validated: list[dict] = []
    for sample in samples:
        if not isinstance(sample, dict) or sample.get("grade") != grade:
            raise ValueError(f"converted formula sample contract is invalid for {grade}")
        relative = Path(str(sample.get("image") or ""))
        equation = str(sample.get("equation") or "").strip()
        source = (resolved / relative).resolve()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not equation
            or not source.is_relative_to(resolved)
            or not source.is_file()
        ):
            raise ValueError(f"converted formula sample path is invalid for {grade}")
        validated.append({**sample, "sourcePath": source})
    return manifest, validated


def build_profile(
    *,
    profile: str,
    grade_roots: dict[str, Path],
    output_root: Path,
    seed: int = 20260829,
) -> dict:
    required_grades = formula_profile_datasets(profile)
    normalized_roots = {str(grade).strip().upper(): Path(path) for grade, path in grade_roots.items()}
    if set(normalized_roots) != set(required_grades):
        raise ValueError("formula profile requires its exact grade roots")
    output_root = output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError("formula profile output must be empty")
    image_output = output_root / "images"
    image_output.mkdir(parents=True, exist_ok=True)
    all_samples: list[dict] = []
    source_manifests: list[dict] = []
    for grade in required_grades:
        root = normalized_roots[grade].resolve()
        manifest, samples = _load_grade_root(grade, root)
        all_samples.extend(samples)
        source_manifests.append(
            {
                "grade": grade,
                "root": str(root),
                "manifestSha256": sha256_file(root / "manifest.json"),
                "count": len(samples),
            }
        )
    random.Random(seed).shuffle(all_samples)
    grade_counts: Counter = Counter()
    writer_hashes: set[str] = set()
    provenance_lines: list[str] = []
    equations: list[str] = []
    link_counts: Counter = Counter()
    for index, sample in enumerate(all_samples):
        target = image_output / f"{index:07d}.png"
        try:
            os.link(sample["sourcePath"], target)
            link_counts["hardlinked"] += 1
        except OSError:
            shutil.copy2(sample["sourcePath"], target)
            link_counts["copied"] += 1
        grade = str(sample["grade"])
        grade_counts[grade] += 1
        writer_hashes.add(str(sample.get("writerHash") or ""))
        equations.append(str(sample["equation"]))
        provenance_lines.append(
            json.dumps(
                {
                    "index": index,
                    "grade": grade,
                    "writerHash": sample.get("writerHash"),
                    "sourceHash": sample.get("sourceHash"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    (output_root / "equations.txt").write_text("\n".join(equations) + ("\n" if equations else ""), encoding="utf-8")
    (output_root / "provenance.jsonl").write_text(
        "\n".join(provenance_lines) + ("\n" if provenance_lines else ""),
        encoding="utf-8",
    )
    summary = {
        "schema": "student_test_formula_profile_dataset_v1",
        "profile": profile,
        "grades": list(required_grades),
        "selection": "natural grade ratio; writer caps applied in source conversion",
        "selectionSeed": int(seed),
        "count": len(all_samples),
        "countsByGrade": {grade: grade_counts[grade] for grade in required_grades},
        "selectedWriters": len(writer_hashes - {""}),
        "materialization": dict(sorted(link_counts.items())),
        "sources": source_manifests,
        "answerKeyFieldsUsed": 0,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    args = parse_args()
    roots: dict[str, Path] = {}
    for grade, raw_path in args.grade_root:
        normalized = str(grade).strip().upper()
        if normalized in roots:
            raise ValueError("formula profile grade roots must be unique")
        roots[normalized] = Path(raw_path)
    summary = build_profile(
        profile=args.profile,
        grade_roots=roots,
        output_root=args.output,
        seed=args.seed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
