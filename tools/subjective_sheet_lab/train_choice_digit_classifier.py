from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias

import numpy as np
import torch
from torch import Tensor, nn
from torch.utils.data import DataLoader, Dataset, Subset
from torchvision import datasets, transforms
from torchvision.transforms import functional as TF

from choice_digit_classifier import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_MARGIN_THRESHOLD,
    LABELS,
    LABEL_TO_INDEX,
    ChoiceDigitNet,
    checkpoint_payload,
    predict_path,
    prepare_digit,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

OCR_ROOT: Final[Path] = Path(r"C:\server-ocr")
FORBIDDEN_LABEL_FIELDS: Final[frozenset[str]] = frozenset(
    {"expected", "canonical_answer", "accepted_answers", "correct", "score", "answer_key", "answerKeys"}
)
HUMAN_SOURCE_PATTERNS: Final[tuple[str, ...]] = (
    "crop_benchmark_inputs/*/human_transcription.json",
    "gemini_outputs/*/human_transcription.json",
)
BLANK_CASE: Final[str] = "answer_sheet_v3_blank_smoke"


class ChoiceDigitTrainingError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class HumanCrop:
    case: str
    question_no: int
    label: str
    crop_path: Path
    human_source: Path


@dataclass(frozen=True, slots=True)
class FoldPrediction:
    case: str
    question_no: int
    human_label: str
    predicted: str | None
    confidence: float
    margin: float
    reason: str


@dataclass(frozen=True, slots=True)
class Config:
    ocr_root: Path
    output_dir: Path
    mnist_root: Path
    download_mnist: bool
    skip_mnist: bool
    seed: int
    mnist_epochs: int
    fold_epochs: int
    final_epochs: int
    samples_per_label: int
    batch_size: int


class BalancedRealDataset(Dataset[tuple[Tensor, int]]):
    def __init__(self, records: tuple[HumanCrop, ...], samples_per_label: int, seed: int) -> None:
        self.by_label = {label: tuple(item for item in records if item.label == label) for label in LABELS}
        missing = [label for label, items in self.by_label.items() if not items]
        if missing:
            raise ChoiceDigitTrainingError(f"training split lacks label(s): {', '.join(missing)}")
        self.samples_per_label = samples_per_label
        self.seed = seed

    def __len__(self) -> int:
        return self.samples_per_label * len(LABELS)

    def __getitem__(self, index: int) -> tuple[Tensor, int]:
        label_index = index % len(LABELS)
        label = LABELS[label_index]
        choices = self.by_label[label]
        rng = random.Random(self.seed * 1_000_003 + index + random.randrange(1_000_000))
        record = choices[rng.randrange(len(choices))]
        first_variant = "otsu" if rng.random() < 0.5 else "adaptive"
        prepared = prepare_digit(record.crop_path, first_variant)
        if prepared.tensor is None:
            prepared = prepare_digit(record.crop_path, "adaptive" if first_variant == "otsu" else "otsu")
        if prepared.tensor is None:
            raise ChoiceDigitTrainingError(
                f"human-labeled crop failed preprocessing: {record.case} q{record.question_no:03d}"
            )
        return augment_tensor(prepared.tensor, rng), label_index


def augment_tensor(tensor: Tensor, rng: random.Random) -> Tensor:
    output = TF.affine(
        tensor,
        angle=rng.uniform(-10.0, 10.0),
        translate=[rng.randint(-5, 5), rng.randint(-4, 4)],
        scale=rng.uniform(0.88, 1.12),
        shear=[rng.uniform(-5.0, 5.0), 0.0],
        fill=0.0,
    )
    if rng.random() < 0.2:
        output = torch.clamp(output + torch.randn_like(output) * rng.uniform(0.01, 0.05), 0.0, 1.0)
    if rng.random() < 0.15:
        sigma = rng.uniform(0.1, 1.2)
        output = TF.gaussian_blur(output, [3, 3], sigma=[sigma, sigma])
    return output


def main() -> int:
    config = parse_args()
    seed_everything(config.seed)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    records, source_hashes = discover_human_crops(config.ocr_root)
    blank_crops = discover_blank_crops(config.ocr_root)
    if len(records) < 50 or len({item.case for item in records}) < 4:
        raise ChoiceDigitTrainingError("at least 50 human-labeled crops across four cases are required")
    probe_preprocessing(records)

    base_model = ChoiceDigitNet()
    mnist_metrics: dict[str, JsonValue] = {"used": False}
    if not config.skip_mnist:
        base_model, mnist_metrics = pretrain_mnist(base_model, config)

    folds = run_leave_one_case_out(base_model, records, config)
    threshold, margin_threshold, calibration = calibrate_acceptance(folds)
    final_model = copy.deepcopy(base_model)
    fine_tune(final_model, records, config.final_epochs, config.samples_per_label, config.seed + 9000)
    blank_metrics = evaluate_blank_crops(final_model, blank_crops, threshold, margin_threshold)

    label_counts = Counter(item.label for item in records)
    case_counts = Counter(item.case for item in records)
    raw_accuracy = accuracy(folds)
    accepted_rows = accepted_with(folds, threshold, margin_threshold)
    wrong_auto = sum(item.predicted != item.human_label for item in accepted_rows)
    auto_coverage = len(accepted_rows) / len(folds) if folds else 0.0
    readiness = {
        "status": (
            "GO"
            if raw_accuracy >= 0.995
            and wrong_auto == 0
            and auto_coverage >= 0.98
            and len(records) >= 250
            and blank_metrics["false_accepted"] == 0
            else "NO_GO"
        ),
        "minimum_raw_accuracy": 0.995,
        "maximum_wrong_auto_grades": 0,
        "minimum_auto_coverage": 0.98,
        "minimum_human_labeled_crops": 250,
        "observed_raw_accuracy": round(raw_accuracy, 6),
        "observed_wrong_auto_grades": int(wrong_auto),
        "observed_auto_coverage": round(auto_coverage, 6),
        "observed_human_labeled_crops": len(records),
    }

    metadata: dict[str, JsonValue] = {
        "human_label_source": "human_transcription_only",
        "answer_key_fields_used": 0,
        "provider_call_count": 0,
        "human_labeled_crop_count": len(records),
        "case_count": len(case_counts),
        "label_counts": dict(sorted(label_counts.items())),
        "case_counts": dict(sorted(case_counts.items())),
        "readiness": readiness,
    }
    checkpoint_path = config.output_dir / "choice_digit_v1.pt"
    torch.save(
        checkpoint_payload(
            final_model,
            confidence_threshold=threshold,
            margin_threshold=margin_threshold,
            metadata=metadata,
        ),
        checkpoint_path,
    )

    report = {
        "ok": True,
        "model_version": "choice_digit_v1",
        "checkpoint": checkpoint_path.name,
        "label_contract": list(LABELS),
        "human_label_source": "human_transcription_only",
        "answer_key_fields_used": 0,
        "provider_call_count": 0,
        "source_hashes": source_hashes,
        "human_labeled_crop_count": len(records),
        "case_counts": dict(sorted(case_counts.items())),
        "label_counts": dict(sorted(label_counts.items())),
        "mnist_pretraining": mnist_metrics,
        "leave_one_case_out": {
            "evaluated": len(folds),
            "raw_accuracy": round(raw_accuracy, 6),
            "predictions": [asdict(item) for item in folds],
        },
        "acceptance_calibration": calibration,
        "blank_probe_final_model": blank_metrics,
        "readiness": readiness,
        "production_route_modified": False,
        "submit_flow_touched": False,
    }
    metrics_path = config.output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "checkpoint": str(checkpoint_path),
                "metrics": str(metrics_path),
                "readiness": readiness,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Train and group-validate the 1..5 handwritten choice digit classifier.")
    parser.add_argument("--ocr-root", type=Path, default=OCR_ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mnist-root", type=Path)
    parser.add_argument("--download-mnist", action="store_true")
    parser.add_argument("--skip-mnist", action="store_true")
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--mnist-epochs", type=int, default=1)
    parser.add_argument("--fold-epochs", type=int, default=8)
    parser.add_argument("--final-epochs", type=int, default=12)
    parser.add_argument("--samples-per-label", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    ocr_root = args.ocr_root.resolve()
    return Config(
        ocr_root=ocr_root,
        output_dir=args.output_dir.resolve(),
        mnist_root=(args.mnist_root or ocr_root / "datasets" / "mnist").resolve(),
        download_mnist=bool(args.download_mnist),
        skip_mnist=bool(args.skip_mnist),
        seed=args.seed,
        mnist_epochs=args.mnist_epochs,
        fold_epochs=args.fold_epochs,
        final_epochs=args.final_epochs,
        samples_per_label=args.samples_per_label,
        batch_size=args.batch_size,
    )


def discover_human_crops(ocr_root: Path) -> tuple[tuple[HumanCrop, ...], dict[str, str]]:
    sources: list[Path] = []
    for pattern in HUMAN_SOURCE_PATTERNS:
        sources.extend(ocr_root.glob(pattern))
    records_by_crop: dict[Path, HumanCrop] = {}
    source_hashes: dict[str, str] = {}
    for source in sorted(set(sources)):
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ChoiceDigitTrainingError(f"human transcription must be an object: {source}")
        forbidden = forbidden_paths(payload)
        if forbidden:
            raise ChoiceDigitTrainingError(f"forbidden answer-key field in human transcription: {forbidden[0]}")
        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, list):
            raise ChoiceDigitTrainingError(f"human transcription has no answers list: {source}")
        case = source.parent.name.removesuffix("_same_contact")
        crop_dir = ocr_root / "crop_benchmark_inputs" / case / "crops"
        if not crop_dir.is_dir():
            continue
        source_hashes[case] = hashlib.sha256(source.read_bytes()).hexdigest()
        for raw in raw_answers:
            if not isinstance(raw, dict):
                raise ChoiceDigitTrainingError(f"malformed human transcription row: {source}")
            label = str(raw.get("human_answer", "")).strip()
            confidence = str(raw.get("confidence", "high")).strip().casefold()
            if label not in LABELS or confidence == "low":
                continue
            question = int(raw.get("question_no", 0))
            crop = (crop_dir / f"q{question:03d}.png").resolve()
            if question not in range(1, 21) or not crop.is_file():
                raise ChoiceDigitTrainingError(f"missing crop for {case} q{question:03d}")
            record = HumanCrop(case, question, label, crop, source.resolve())
            previous = records_by_crop.get(crop)
            if previous is not None and previous.label != label:
                raise ChoiceDigitTrainingError(f"conflicting human labels for {case} q{question:03d}")
            records_by_crop[crop] = record
    ordered = tuple(sorted(records_by_crop.values(), key=lambda item: (item.case, item.question_no)))
    return ordered, dict(sorted(source_hashes.items()))


def discover_blank_crops(ocr_root: Path) -> tuple[Path, ...]:
    crop_dir = ocr_root / "crop_benchmark_inputs" / BLANK_CASE / "crops"
    return tuple(sorted(crop_dir.glob("q*.png"))) if crop_dir.is_dir() else ()


def forbidden_paths(value: JsonValue, path: str = "$") -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_LABEL_FIELDS:
                found.append(child_path)
            found.extend(forbidden_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(forbidden_paths(child, f"{path}[{index}]"))
    return tuple(found)


def probe_preprocessing(records: tuple[HumanCrop, ...]) -> None:
    failures = []
    for item in records:
        if all(prepare_digit(item.crop_path, variant).tensor is None for variant in ("otsu", "adaptive")):
            failures.append(f"{item.case}:q{item.question_no:03d}")
    if failures:
        raise ChoiceDigitTrainingError(f"human-labeled crops rejected by both preprocessors: {', '.join(failures[:10])}")


def pretrain_mnist(model: ChoiceDigitNet, config: Config) -> tuple[ChoiceDigitNet, dict[str, JsonValue]]:
    transform = transforms.Compose(
        [
            transforms.Resize((36, 36)),
            transforms.Pad(6),
            transforms.RandomAffine(10, translate=(0.08, 0.08), scale=(0.88, 1.12), shear=5),
            transforms.ToTensor(),
        ]
    )
    dataset = datasets.MNIST(config.mnist_root, train=True, download=config.download_mnist, transform=transform)
    by_label: dict[int, list[int]] = defaultdict(list)
    for index, raw_label in enumerate(dataset.targets.tolist()):
        label = str(int(raw_label))
        if label in LABELS and len(by_label[int(label)]) < 600:
            by_label[int(label)].append(index)
    if any(len(by_label[int(label)]) < 500 for label in LABELS):
        raise ChoiceDigitTrainingError("MNIST data is unavailable or incomplete; rerun with --download-mnist")
    indices = [index for label in LABELS for index in by_label[int(label)]]
    subset = Subset(dataset, indices)

    class RemappedMnist(Dataset[tuple[Tensor, int]]):
        def __len__(self) -> int:
            return len(subset)

        def __getitem__(self, index: int) -> tuple[Tensor, int]:
            image, label = subset[index]
            return image, LABEL_TO_INDEX[str(int(label))]

    losses = train_epochs(model, RemappedMnist(), config.mnist_epochs, config.batch_size, 1e-3)
    return model, {
        "used": True,
        "samples": len(subset),
        "epochs": config.mnist_epochs,
        "final_loss": round(losses[-1], 6),
    }


def run_leave_one_case_out(
    base_model: ChoiceDigitNet, records: tuple[HumanCrop, ...], config: Config
) -> tuple[FoldPrediction, ...]:
    output: list[FoldPrediction] = []
    for fold_index, holdout in enumerate(sorted({item.case for item in records})):
        train_records = tuple(item for item in records if item.case != holdout)
        holdout_records = tuple(item for item in records if item.case == holdout)
        model = copy.deepcopy(base_model)
        fine_tune(model, train_records, config.fold_epochs, config.samples_per_label, config.seed + fold_index * 100)
        for item in holdout_records:
            prediction = predict_path(model, item.crop_path, confidence_threshold=0.0, margin_threshold=0.0)
            output.append(
                FoldPrediction(
                    item.case,
                    item.question_no,
                    item.label,
                    prediction.label,
                    round(prediction.confidence, 8),
                    round(prediction.margin, 8),
                    prediction.reason,
                )
            )
    return tuple(output)


def fine_tune(
    model: ChoiceDigitNet,
    records: tuple[HumanCrop, ...],
    epochs: int,
    samples_per_label: int,
    seed: int,
) -> None:
    train_epochs(model, BalancedRealDataset(records, samples_per_label, seed), epochs, 80, 3e-4)


def train_epochs(
    model: nn.Module,
    dataset: Dataset[tuple[Tensor, int]],
    epochs: int,
    batch_size: int,
    learning_rate: float,
) -> list[float]:
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=0)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss(label_smoothing=0.03)
    history: list[float] = []
    for _ in range(epochs):
        model.train()
        total_loss, total = 0.0, 0
        for inputs, labels in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(inputs), labels)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach()) * len(inputs)
            total += len(inputs)
        history.append(total_loss / max(1, total))
    return history


def calibrate_acceptance(rows: tuple[FoldPrediction, ...]) -> tuple[float, float, dict[str, JsonValue]]:
    best = (0, 1.0, 1.0)
    for confidence in np.linspace(0.75, 0.995, 50):
        for margin in np.linspace(0.25, 0.9, 27):
            accepted = accepted_with(rows, float(confidence), float(margin))
            if any(item.predicted != item.human_label for item in accepted):
                continue
            candidate = (len(accepted), -float(confidence), -float(margin))
            incumbent = (best[0], -best[1], -best[2])
            if candidate > incumbent:
                best = (len(accepted), float(confidence), float(margin))
    threshold = max(best[1], DEFAULT_CONFIDENCE_THRESHOLD)
    margin_threshold = max(best[2], DEFAULT_MARGIN_THRESHOLD)
    accepted = accepted_with(rows, threshold, margin_threshold)
    wrong = sum(item.predicted != item.human_label for item in accepted)
    return threshold, margin_threshold, {
        "confidence_threshold": round(threshold, 6),
        "margin_threshold": round(margin_threshold, 6),
        "accepted": len(accepted),
        "evaluated": len(rows),
        "coverage": round(len(accepted) / len(rows), 6) if rows else 0.0,
        "wrong_auto_grades": int(wrong),
        "zero_error_search_accepted_before_floor": best[0],
    }


def accepted_with(
    rows: tuple[FoldPrediction, ...], confidence: float, margin: float
) -> tuple[FoldPrediction, ...]:
    return tuple(
        item
        for item in rows
        if item.predicted is not None and item.confidence >= confidence and item.margin >= margin
    )


def evaluate_blank_crops(
    model: ChoiceDigitNet, crops: tuple[Path, ...], confidence: float, margin: float
) -> dict[str, JsonValue]:
    statuses = Counter(
        predict_path(model, path, confidence_threshold=confidence, margin_threshold=margin).status
        for path in crops
    )
    return {
        "evaluated": len(crops),
        "blank": statuses.get("blank", 0),
        "false_accepted": statuses.get("accepted", 0),
        "blank_rejection_rate": round(statuses.get("blank", 0) / len(crops), 6) if crops else 0.0,
        "status_counts": dict(sorted(statuses.items())),
    }


def accuracy(rows: tuple[FoldPrediction, ...]) -> float:
    return sum(item.predicted == item.human_label for item in rows) / len(rows) if rows else 0.0


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(max(1, min(8, torch.get_num_threads())))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ChoiceDigitTrainingError as exc:
        print(
            json.dumps(
                {"ok": False, "error": "choice_digit_training_failed", "message": str(exc)},
                ensure_ascii=False,
            )
        )
        raise SystemExit(2)
