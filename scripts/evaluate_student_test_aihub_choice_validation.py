from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterable, Mapping, Sequence

from scripts.import_aihub_education_choice_dataset import CHOICE_LABELS, REJECT_LABEL, normalized_boxes
from scripts.import_aihub_education_formula_dataset import dataset_grade_code
from scripts.student_test_choice_worker import build_model, checkpoint_contract


SCHEMA: Final = "student_test_aihub_choice_validation_v1"
SUPPORTED_GRADES: Final = frozenset({"M_G3", "H_G1", "H_G2", "H_G3"})


@dataclass(frozen=True, slots=True)
class ValidationSample:
    path: Path
    label: str
    strict_writer: bool


class ChoiceCropDataset:
    def __init__(self, values: Sequence[ValidationSample], *, labels: Sequence[str], input_size: int):
        from torchvision import transforms

        self.values = tuple(values)
        self.labels = tuple(labels)
        self.transform = transforms.Compose([transforms.Resize((input_size, input_size)), transforms.ToTensor()])

    def __len__(self) -> int:
        return len(self.values)

    def __getitem__(self, index: int):
        from PIL import Image

        sample = self.values[index]
        with Image.open(sample.path) as opened:
            tensor = self.transform(opened.convert("L"))
        return tensor, self.labels.index(sample.label), sample.strict_writer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate one choice checkpoint on converted AI Hub grade Validation crops."
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument(
        "--training-label-root",
        action="append",
        nargs=2,
        metavar=("GRADE", "PATH"),
        default=[],
        required=True,
    )
    parser.add_argument(
        "--validation-case",
        action="append",
        nargs=3,
        metavar=("GRADE", "LABELS", "CROPS"),
        default=[],
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260829)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_output_path(path: Path) -> Path:
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists():
        raise ValueError("AI Hub choice Validation output already exists")
    probe = resolved.with_name(resolved.name + ".partial")
    if probe.exists():
        raise ValueError("AI Hub choice Validation partial output already exists")
    with probe.open("xb") as handle:
        handle.write(b"write-preflight\n")
        handle.flush()
        os.fsync(handle.fileno())
    probe.unlink()
    return resolved


def _writer_id(payload: object, relative_path: str) -> str:
    images = payload.get("Images") if isinstance(payload, dict) else None
    writer = str(images.get("make_id") or "").strip() if isinstance(images, dict) else ""
    return writer or f"missing:{relative_path}"


def _normalized_grade(value: str) -> str:
    grade = str(value or "").strip().upper()
    if grade not in SUPPORTED_GRADES:
        raise ValueError("AI Hub choice evaluation grade is unsupported")
    return grade


def choice_training_writers(roots: Sequence[tuple[str, Path]]) -> set[str]:
    writers: set[str] = set()
    seen_grades: set[str] = set()
    for raw_grade, raw_root in roots:
        grade = _normalized_grade(raw_grade)
        if grade in seen_grades:
            raise ValueError("AI Hub choice training grades must be unique")
        seen_grades.add(grade)
        root = raw_root.resolve()
        if not root.is_dir():
            raise ValueError("AI Hub choice training label root is missing")
        for path in sorted(root.rglob("*.json")):
            relative = path.relative_to(root).as_posix()
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("AI Hub choice training label is invalid") from error
            if dataset_grade_code(payload) != grade:
                raise ValueError("AI Hub choice training label grade mismatch")
            if normalized_boxes(payload):
                writers.add(_writer_id(payload, relative))
    if not writers:
        raise ValueError("AI Hub choice training writer inventory is empty")
    return writers


def discover_validation_samples(
    *,
    grade: str,
    labels_root: Path,
    crops_root: Path,
    known_training_writers: set[str],
    seed: int = 20260829,
) -> tuple[list[ValidationSample], dict]:
    grade = _normalized_grade(grade)
    labels_root = labels_root.resolve()
    crops_root = crops_root.resolve()
    if not labels_root.is_dir() or not crops_root.is_dir():
        raise ValueError("AI Hub choice Validation roots are missing")
    manifest_path = crops_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("AI Hub choice Validation crop manifest is invalid") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "student_test_aihub_choice_crops_v1"
        or manifest.get("answerKeyFieldsUsed") != 0
    ):
        raise ValueError("AI Hub choice Validation crop manifest contract is invalid")

    samples: list[ValidationSample] = []
    matched: set[str] = set()
    label_files = sorted(labels_root.rglob("*.json"))
    random.Random(seed).shuffle(label_files)
    for label_path in label_files:
        relative = label_path.relative_to(labels_root).as_posix()
        try:
            payload = json.loads(label_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("AI Hub choice Validation label is invalid") from error
        if dataset_grade_code(payload) != grade:
            raise ValueError("AI Hub choice Validation label grade mismatch")
        writer = _writer_id(payload, relative)
        boxes = normalized_boxes(payload)
        random.Random(f"{seed}:{relative}").shuffle(boxes)
        for position, box in enumerate(boxes):
            token = hashlib.sha256(f"{relative}\n{box['id']}\n{position}".encode("utf-8")).hexdigest()[:24]
            relative_crop = f"{box['label']}/{token}.png"
            crop_path = crops_root / relative_crop
            if not crop_path.is_file():
                continue
            if relative_crop in matched:
                raise ValueError("AI Hub choice Validation crop provenance is duplicated")
            matched.add(relative_crop)
            samples.append(
                ValidationSample(
                    path=crop_path,
                    label=str(box["label"]),
                    strict_writer=writer not in known_training_writers,
                )
            )

    actual = {
        path.relative_to(crops_root).as_posix()
        for label in (*CHOICE_LABELS, REJECT_LABEL)
        for path in (crops_root / label).glob("*.png")
        if path.is_file()
    }
    if matched != actual:
        raise ValueError("AI Hub choice Validation crop provenance is incomplete")
    expected_counts = {label: int((manifest.get("counts") or {}).get(label, 0)) for label in (*CHOICE_LABELS, REJECT_LABEL)}
    observed_counts = Counter(sample.label for sample in samples)
    if any(observed_counts[label] != expected_counts[label] for label in (*CHOICE_LABELS, REJECT_LABEL)):
        raise ValueError("AI Hub choice Validation crop counts do not match the manifest")
    return samples, {
        "grade": grade,
        "manifestSha256": sha256_file(manifest_path),
        "samples": len(samples),
        "strictSamples": sum(sample.strict_writer for sample in samples),
        "answerKeyFieldsUsed": 0,
    }


def empty_stats() -> dict:
    return {
        "evaluated": 0,
        "choiceEvaluated": 0,
        "rejectEvaluated": 0,
        "rawCorrect": 0,
        "choiceRawCorrect": 0,
        "rejectRawCorrect": 0,
        "acceptedAutoGrades": 0,
        "acceptedChoiceAnswers": 0,
        "wrongAutoGrades": 0,
        "perClass": {label: Counter() for label in (*CHOICE_LABELS, REJECT_LABEL)},
        "confusion": Counter(),
    }


def update_stats(stats: dict, *, human_label: str, predicted: str, score: float, margin: float, minimum: float, margin_minimum: float) -> None:
    correct = predicted == human_label
    accepted = predicted != REJECT_LABEL and score >= minimum and margin >= margin_minimum
    is_choice = human_label != REJECT_LABEL
    stats["evaluated"] += 1
    stats["choiceEvaluated" if is_choice else "rejectEvaluated"] += 1
    stats["rawCorrect"] += int(correct)
    stats["choiceRawCorrect" if is_choice else "rejectRawCorrect"] += int(correct)
    stats["acceptedAutoGrades"] += int(accepted)
    stats["acceptedChoiceAnswers"] += int(accepted and is_choice)
    stats["wrongAutoGrades"] += int(accepted and not correct)
    row = stats["perClass"][human_label]
    row["evaluated"] += 1
    row["rawCorrect"] += int(correct)
    row["accepted"] += int(accepted)
    row["wrongAutoGrades"] += int(accepted and not correct)
    stats["confusion"][(human_label, predicted)] += 1


def public_stats(stats: Mapping[str, object]) -> dict:
    evaluated = int(stats["evaluated"])
    choice = int(stats["choiceEvaluated"])
    reject = int(stats["rejectEvaluated"])
    return {
        "evaluated": evaluated,
        "choiceEvaluated": choice,
        "rejectEvaluated": reject,
        "rawAccuracy": int(stats["rawCorrect"]) / evaluated if evaluated else 0.0,
        "choiceRawAccuracy": int(stats["choiceRawCorrect"]) / choice if choice else 0.0,
        "rejectRecall": int(stats["rejectRawCorrect"]) / reject if reject else 0.0,
        "choiceCoverage": int(stats["acceptedChoiceAnswers"]) / choice if choice else 0.0,
        "acceptedAutoGrades": int(stats["acceptedAutoGrades"]),
        "wrongAutoGrades": int(stats["wrongAutoGrades"]),
        "perClass": {
            label: {key: int(value) for key, value in stats["perClass"][label].items()}
            for label in (*CHOICE_LABELS, REJECT_LABEL)
        },
        "confusion": {
            human: {predicted: int(stats["confusion"].get((human, predicted), 0)) for predicted in (*CHOICE_LABELS, REJECT_LABEL)}
            for human in (*CHOICE_LABELS, REJECT_LABEL)
        },
    }


def evaluate_samples(
    *,
    model_path: Path,
    cases: Sequence[tuple[str, Sequence[ValidationSample], Mapping[str, object]]],
    batch_size: int,
    num_workers: int,
) -> dict:
    import torch
    from torch.utils.data import DataLoader

    checkpoint = torch.load(model_path.resolve(), map_location="cpu", weights_only=False)
    model_version, labels, input_size = checkpoint_contract(checkpoint)
    model = build_model(torch, output_count=len(labels))
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    minimum = float(checkpoint.get("confidence_threshold") or 0.995)
    margin_minimum = float(checkpoint.get("margin_threshold") or 0.90)
    reports = []
    with torch.inference_mode():
        for grade, samples, source in cases:
            full = empty_stats()
            strict = empty_stats()
            loader = DataLoader(
                ChoiceCropDataset(samples, labels=labels, input_size=input_size),
                batch_size=max(1, batch_size),
                shuffle=False,
                num_workers=max(0, num_workers),
            )
            for images, targets, strict_flags in loader:
                probabilities = torch.softmax(model(images), dim=1)
                values, indices = torch.topk(probabilities, k=2, dim=1)
                for target, strict_flag, top_values, top_indices in zip(targets, strict_flags, values, indices):
                    human_label = labels[int(target)]
                    predicted = labels[int(top_indices[0])]
                    score = float(top_values[0])
                    margin = score - float(top_values[1])
                    update_stats(
                        full,
                        human_label=human_label,
                        predicted=predicted,
                        score=score,
                        margin=margin,
                        minimum=minimum,
                        margin_minimum=margin_minimum,
                    )
                    if bool(strict_flag):
                        update_stats(
                            strict,
                            human_label=human_label,
                            predicted=predicted,
                            score=score,
                            margin=margin,
                            minimum=minimum,
                            margin_minimum=margin_minimum,
                        )
            grade_report = {
                "grade": grade,
                "source": dict(source),
                "official": public_stats(full),
                "strictUnseenWriter": public_stats(strict),
            }
            reports.append(grade_report)
            print(
                json.dumps(
                    {
                        "progress": "grade_complete",
                        "grade": grade,
                        "official": {
                            key: grade_report["official"][key]
                            for key in ("evaluated", "choiceRawAccuracy", "rejectRecall", "choiceCoverage", "wrongAutoGrades")
                        },
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return {
        "modelVersion": model_version,
        "modelSha256": sha256_file(model_path.resolve()),
        "labels": list(labels),
        "inputSize": input_size,
        "confidenceThreshold": minimum,
        "marginThreshold": margin_minimum,
        "acceptanceMode": "single converted crop threshold diagnostic; runtime still requires two-variant agreement",
        "grades": reports,
    }


def main() -> int:
    args = parse_args()
    output_path = prepare_output_path(args.output)
    training_roots = [(_normalized_grade(grade), Path(path)) for grade, path in args.training_label_root]
    known_writers = choice_training_writers(training_roots)
    cases = []
    seen_grades: set[str] = set()
    for raw_grade, labels, crops in args.validation_case:
        grade = _normalized_grade(raw_grade)
        if grade in seen_grades:
            raise ValueError("AI Hub choice Validation grades must be unique")
        seen_grades.add(grade)
        samples, source = discover_validation_samples(
            grade=grade,
            labels_root=Path(labels),
            crops_root=Path(crops),
            known_training_writers=known_writers,
            seed=args.seed,
        )
        cases.append((grade, samples, source))
    report = {
        "schema": SCHEMA,
        "trainingGrades": [grade for grade, _root in training_roots],
        "trainingWriters": len(known_writers),
        **evaluate_samples(
            model_path=args.model,
            cases=cases,
            batch_size=max(1, args.batch_size),
            num_workers=max(0, args.num_workers),
        ),
        "scope": "AI Hub transcription labels only; no answer keys, providers, submission, UI, or runtime data",
        "answerKeyFieldsUsed": 0,
        "providerCallCount": 0,
        "productionStateChanged": False,
    }
    partial = output_path.with_name(output_path.name + ".partial")
    with partial.open("xb") as handle:
        handle.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, output_path)
    print(json.dumps({"output": str(output_path), "grades": len(cases)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
