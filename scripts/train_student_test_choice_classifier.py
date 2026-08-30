from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence


INPUT_SIZE: Final = 48
CHOICE_LABELS: Final = ("1", "2", "3", "4", "5")
REJECT_LABEL: Final = "__reject__"
LABELS: Final = (*CHOICE_LABELS, REJECT_LABEL)
MODEL_VERSION: Final = "choice_digit_v4"
ROOT: Final = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True, slots=True)
class RealCase:
    name: str
    crop_dir: Path
    transcription_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the local 1-5 choice digit reject classifier.")
    parser.add_argument("--mnist-root", type=Path, required=True)
    parser.add_argument("--emnist-root", type=Path, required=True)
    parser.add_argument("--aihub-root", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-case", nargs=3, action="append", default=[], metavar=("NAME", "CROPS", "TRANSCRIPTION"))
    parser.add_argument("--validation-case", nargs=3, action="append", default=[], metavar=("NAME", "CROPS", "TRANSCRIPTION"))
    parser.add_argument("--holdout-case", nargs=3, action="append", default=[], metavar=("NAME", "CROPS", "TRANSCRIPTION"))
    parser.add_argument("--template", type=Path)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--mnist-limit", type=int, default=30000)
    parser.add_argument("--emnist-digit-limit", type=int, default=30000)
    parser.add_argument("--emnist-reject-limit", type=int, default=20000)
    parser.add_argument("--synthetic-reject-limit", type=int, default=10000)
    parser.add_argument("--aihub-choice-limit-per-class", type=int, default=6000)
    parser.add_argument(
        "--aihub-reject-limit",
        type=int,
        default=0,
        help="Zero automatically matches the balanced AI Hub choice count.",
    )
    parser.add_argument("--confidence-threshold", type=float, default=0.995)
    parser.add_argument("--margin-threshold", type=float, default=0.90)
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--download-mnist", action="store_true")
    parser.add_argument("--download-emnist", action="store_true")
    return parser.parse_args()


def cases(values: Sequence[Sequence[str]]) -> tuple[RealCase, ...]:
    return tuple(RealCase(str(name), Path(crops).resolve(), Path(transcription).resolve()) for name, crops, transcription in values)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def case_manifest(case: RealCase) -> dict:
    crop_names = sorted(path.name for path in case.crop_dir.glob("q*.png") if path.is_file())
    return {
        "name": case.name,
        "cropCount": len(crop_names),
        "cropNameSha256": hashlib.sha256("\n".join(crop_names).encode("utf-8")).hexdigest(),
        "transcriptionSha256": sha256_file(case.transcription_path),
    }


def transcription_answers(payload: object, *, case_name: str) -> list[dict]:
    if not isinstance(payload, dict):
        raise ValueError(f"{case_name}: human transcription document is invalid")
    answers = payload.get("answers")
    if isinstance(answers, list):
        return [answer for answer in answers if isinstance(answer, dict)]
    evaluation_items = payload.get("items")
    if not isinstance(evaluation_items, list):
        raise ValueError(f"{case_name}: human transcription answers are missing")
    normalized = []
    for item in evaluation_items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "question_no": item.get("question_no"),
                "human_answer": item.get("human_answer"),
                "confidence": item.get("human_confidence"),
                "notes": item.get("notes"),
            }
        )
    return normalized


def load_real_samples(case: RealCase, *, template_gray, cv2, np) -> list[tuple[object, int, dict]]:
    from scripts.student_test_choice_worker import prepare_array_variants
    from scripts.student_test_sheet_crop_worker import fixed_boxes, recognition_crop

    payload = json.loads(case.transcription_path.read_text(encoding="utf-8-sig"))
    answers = transcription_answers(payload, case_name=case.name)
    boxes = fixed_boxes()
    samples: list[tuple[object, int, dict]] = []
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        human_confidence = str(answer.get("confidence") or "").lower()
        text = str(answer.get("human_answer") or "").strip()
        label_text = text if human_confidence == "high" and text in CHOICE_LABELS else REJECT_LABEL
        number = int(answer.get("question_no"))
        path = case.crop_dir / f"q{number:03d}.png"
        encoded = np.fromfile(str(path), dtype=np.uint8)
        raw = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
        if raw is None:
            raise ValueError(f"{case.name}: crop missing for question {number}")
        x, y, width, height = boxes[number]
        template_crop = None if template_gray is None else template_gray[y : y + height, x : x + width]
        if template_crop is not None and template_crop.shape[:2] != raw.shape[:2]:
            template_crop = cv2.resize(
                template_crop,
                (raw.shape[1], raw.shape[0]),
                interpolation=cv2.INTER_AREA,
            )
        cleaned, _density = recognition_crop(cv2, np, raw, template_crop)
        variants, density = prepare_array_variants(cv2, np, cleaned, INPUT_SIZE)
        if not variants:
            continue
        metadata = {
            "case": case.name,
            "questionNo": number,
            "label": label_text,
            "humanAnswer": text,
            "humanConfidence": human_confidence,
            "inkDensity": density,
        }
        for variant in variants:
            samples.append((variant, LABELS.index(label_text), metadata))
    return samples


class ArrayDataset:
    def __init__(self, torch, samples, *, repeats: int, augment):
        self.torch = torch
        self.samples = list(samples)
        self.repeats = repeats
        self.augment = augment

    def __len__(self):
        return len(self.samples) * self.repeats

    def __getitem__(self, index):
        from PIL import Image

        image, label, _metadata = self.samples[index % len(self.samples)]
        pil = Image.fromarray((image * 255).astype("uint8"), mode="L")
        return self.augment(pil), label


class CombinedDataset:
    def __init__(self, datasets):
        self.datasets = tuple(datasets)
        self.offsets = []
        total = 0
        for dataset in self.datasets:
            total += len(dataset)
            self.offsets.append(total)

    def __len__(self):
        return self.offsets[-1]

    def __getitem__(self, index):
        previous = 0
        for dataset, stop in zip(self.datasets, self.offsets):
            if index < stop:
                return dataset[index - previous]
            previous = stop
        raise IndexError(index)


class MappedCharacterDataset:
    def __init__(self, base, indices, transform, label_mapper, *, correct_emnist_orientation: bool = False):
        self.base = base
        self.indices = tuple(indices)
        self.transform = transform
        self.label_mapper = label_mapper
        self.correct_emnist_orientation = correct_emnist_orientation

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, index):
        from PIL import ImageOps

        image, raw_label = self.base[self.indices[index]]
        if self.correct_emnist_orientation:
            image = ImageOps.mirror(image.rotate(-90, expand=False))
        label = self.label_mapper(int(raw_label))
        if label not in LABELS:
            raise ValueError(f"public character label is unsupported: {label}")
        return self.transform(image), LABELS.index(label)


class SyntheticPairRejectDataset:
    def __init__(self, base, indices, transform, *, count: int, seed: int):
        self.base = base
        self.indices = tuple(indices)
        self.transform = transform
        self.count = max(0, int(count))
        self.seed = int(seed)

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        from PIL import Image, ImageChops

        rng = random.Random(self.seed + int(index) * 104729)
        first, _first_label = self.base[self.indices[rng.randrange(len(self.indices))]]
        second, _second_label = self.base[self.indices[rng.randrange(len(self.indices))]]
        canvas = Image.new("L", (28, 28), 0)
        for position, image in enumerate((first, second)):
            side = rng.randint(17, 22)
            glyph = image.resize((side, side))
            x_base = 0 if position == 0 else 28 - side
            x = max(0, min(28 - side, x_base + rng.randint(-3, 3)))
            y = rng.randint(2, max(2, 28 - side - 1))
            layer = Image.new("L", canvas.size, 0)
            layer.paste(glyph, (x, y))
            canvas = ImageChops.lighter(canvas, layer)
        return self.transform(canvas), LABELS.index(REJECT_LABEL)


class LabeledCropDataset:
    def __init__(self, samples, transform):
        self.samples = tuple(samples)
        self.transform = transform

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        from PIL import Image

        path, label = self.samples[index]
        with Image.open(path) as image:
            prepared = image.convert("L")
        return self.transform(prepared), LABELS.index(label)


def balanced_indices(targets, accepted_labels: Sequence[int], *, limit: int, seed: int) -> list[int]:
    accepted = tuple(int(value) for value in accepted_labels)
    groups = {label: [] for label in accepted}
    for index, raw_label in enumerate(targets):
        label = int(raw_label)
        if label in groups:
            groups[label].append(index)
    rng = random.Random(seed)
    for values in groups.values():
        rng.shuffle(values)
    if limit <= 0:
        return [index for label in accepted for index in groups[label]]
    selected: list[int] = []
    cursor = 0
    while len(selected) < limit:
        added = False
        for label in accepted:
            values = groups[label]
            if cursor < len(values) and len(selected) < limit:
                selected.append(values[cursor])
                added = True
        if not added:
            break
        cursor += 1
    return selected


def labeled_crop_inventory(root: Path) -> dict[str, list[Path]]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("AI Hub converted crop root does not exist")
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("AI Hub converted crop manifest is missing or invalid") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "student_test_aihub_choice_crops_v1"
        or manifest.get("answerKeyFieldsUsed") != 0
    ):
        raise ValueError("AI Hub converted crop manifest contract is invalid")
    grouped: dict[str, list[Path]] = {}
    for label in LABELS:
        directory = root / label
        paths = sorted(path for path in directory.glob("*.png") if path.is_file()) if directory.is_dir() else []
        grouped[label] = paths
    if not any(grouped.values()):
        raise ValueError("AI Hub converted crop root contains no labeled PNG files")
    return grouped


def pooled_labeled_crop_samples(
    roots: list[Path],
    *,
    choice_limit_per_class: int,
    reject_limit: int,
    seed: int,
) -> tuple[list[tuple[Path, str]], dict[Path, list[tuple[Path, str]]]]:
    if not roots:
        return [], {}
    resolved_roots = [root.resolve() for root in roots]
    if len(set(resolved_roots)) != len(resolved_roots):
        raise ValueError("AI Hub converted crop roots must be unique")
    grouped = {label: [] for label in LABELS}
    owner_by_path: dict[Path, Path] = {}
    for root in resolved_roots:
        inventory = labeled_crop_inventory(root)
        for label in LABELS:
            for path in inventory[label]:
                if path in owner_by_path:
                    raise ValueError("AI Hub converted crop roots must not overlap")
                grouped[label].append(path)
                owner_by_path[path] = root
    rng = random.Random(seed)
    for label in LABELS:
        rng.shuffle(grouped[label])
        if label != REJECT_LABEL and choice_limit_per_class > 0:
            grouped[label] = grouped[label][:choice_limit_per_class]
    missing_choices = [label for label in CHOICE_LABELS if not grouped[label]]
    if missing_choices:
        raise ValueError(f"pooled AI Hub crops are missing choice classes: {', '.join(missing_choices)}")
    choice_target = max(len(grouped[label]) for label in CHOICE_LABELS)
    selected: list[tuple[Path, str]] = []
    for label in CHOICE_LABELS:
        paths = grouped[label]
        selected.extend((paths[index % len(paths)], label) for index in range(choice_target))
    automatic_reject_limit = choice_target * len(CHOICE_LABELS)
    effective_reject_limit = reject_limit if reject_limit > 0 else automatic_reject_limit
    selected.extend((path, REJECT_LABEL) for path in grouped[REJECT_LABEL][:effective_reject_limit])
    rng.shuffle(selected)
    selected_by_root = {root: [] for root in resolved_roots}
    for sample in selected:
        selected_by_root[owner_by_path[sample[0]]].append(sample)
    return selected, selected_by_root


def labeled_crop_samples(
    root: Path,
    *,
    choice_limit_per_class: int,
    reject_limit: int,
    seed: int,
) -> list[tuple[Path, str]]:
    selected, _selected_by_root = pooled_labeled_crop_samples(
        [root],
        choice_limit_per_class=choice_limit_per_class,
        reject_limit=reject_limit,
        seed=seed,
    )
    return selected


def aihub_public_data(aihub_sources: Sequence[tuple[Path, Sequence[tuple[Path, str]]]]) -> dict:
    counts = {
        label: sum(
            sample_label == label
            for _root, samples in aihub_sources
            for _path, sample_label in samples
        )
        for label in LABELS
    }
    return {
        "source": "approved local conversion of AI Hub OCR data (education)",
        "roots": [
            {
                "root": str(root),
                "manifestSha256": sha256_file(root / "manifest.json"),
                "effectiveCounts": {
                    label: sum(sample_label == label for _path, sample_label in root_samples)
                    for label in LABELS
                },
                "uniqueCounts": {
                    label: len({path for path, sample_label in root_samples if sample_label == label})
                    for label in LABELS
                },
            }
            for root, root_samples in aihub_sources
        ],
        "counts": counts,
    }


def evaluate(model, samples, *, torch, np) -> list[dict]:
    rows = []
    model.eval()
    grouped: dict[tuple[str, int], list] = {}
    for image, label, metadata in samples:
        grouped.setdefault((metadata["case"], metadata["questionNo"]), []).append((image, label, metadata))
    with torch.inference_mode():
        for (_case, _number), variants in grouped.items():
            batch = torch.from_numpy(np.stack([item[0] for item in variants])[:, None, :, :]).float()
            probabilities = torch.softmax(model(batch), dim=1)
            variant_predictions = []
            for probability in probabilities:
                values, indices = torch.topk(probability, k=2)
                variant_predictions.append(int(indices[0]))
            averaged = probabilities.mean(dim=0)
            _average_values, average_indices = torch.topk(averaged, k=2)
            predicted = int(average_indices[0])
            scores = []
            margins = []
            for probability in probabilities:
                score = float(probability[predicted])
                other = float(torch.cat((probability[:predicted], probability[predicted + 1 :])).max())
                scores.append(score)
                margins.append(score - other)
            label = int(variants[0][1])
            agreed = all(item == predicted for item in variant_predictions)
            rows.append(
                {
                    **variants[0][2],
                    "humanLabel": variants[0][2]["label"],
                    "predicted": LABELS[predicted],
                    "correct": agreed and predicted == label,
                    "variantAgreed": agreed,
                    "score": min(scores),
                    "margin": min(margins),
                }
            )
    return rows


def summarize(rows: Sequence[dict], confidence: float, margin: float) -> dict:
    accepted = [
        row
        for row in rows
        if row["variantAgreed"]
        and row["predicted"] != REJECT_LABEL
        and row["score"] >= confidence
        and row["margin"] >= margin
    ]
    choice_rows = [row for row in rows if row["humanLabel"] in CHOICE_LABELS]
    reject_rows = [row for row in rows if row["humanLabel"] == REJECT_LABEL]
    accepted_choice = [row for row in accepted if row["humanLabel"] in CHOICE_LABELS]
    correct = sum(bool(row["correct"]) for row in rows)
    wrong = sum(not bool(row["correct"]) for row in accepted)
    per_class = {}
    for label in LABELS:
        label_rows = [row for row in rows if row["humanLabel"] == label]
        label_accepted = [row for row in accepted if row["humanLabel"] == label]
        per_class[label] = {
            "evaluated": len(label_rows),
            "rawCorrect": sum(bool(row["correct"]) for row in label_rows),
            "accepted": len(label_accepted),
            "wrongAutoGrades": sum(not bool(row["correct"]) for row in label_accepted),
        }
    reject_correct = sum(bool(row["correct"]) for row in reject_rows)
    return {
        "evaluated": len(rows),
        "choiceEvaluated": len(choice_rows),
        "rejectEvaluated": len(reject_rows),
        "rawAccuracy": correct / len(rows) if rows else 0.0,
        "accepted": len(accepted),
        "coverage": len(accepted_choice) / len(choice_rows) if choice_rows else 0.0,
        "rejectRecall": reject_correct / len(reject_rows) if reject_rows else 0.0,
        "wrongAutoGrades": wrong,
        "perClass": per_class,
        "rows": list(rows),
    }


def zero_error_upper_95(accepted: int, wrong: int) -> float:
    if accepted <= 0 or wrong > 0:
        return 1.0
    return 1.0 - (0.05 ** (1.0 / accepted))


def main() -> int:
    args = parse_args()
    if not 0.0 <= args.confidence_threshold <= 1.0 or not 0.0 <= args.margin_threshold <= 1.0:
        raise ValueError("confidence and margin thresholds must be between zero and one")
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)
    import cv2
    import numpy as np
    import torch
    from torch.utils.data import DataLoader
    from torchvision import datasets, transforms

    torch.manual_seed(args.seed)
    torch.set_num_threads(max(1, min(8, torch.get_num_threads())))
    template_gray = None
    if args.template:
        encoded = np.fromfile(str(args.template.resolve()), dtype=np.uint8)
        template = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE) if encoded.size else None
        if template is None:
            raise ValueError("blank answer-sheet template could not be decoded")
        template_gray = cv2.resize(template, (1600, 2200), interpolation=cv2.INTER_AREA)

    train_cases = cases(args.train_case)
    validation_cases = cases(args.validation_case)
    holdout_cases = cases(args.holdout_case)
    train_real = [item for case in train_cases for item in load_real_samples(case, template_gray=template_gray, cv2=cv2, np=np)]
    validation_real = [item for case in validation_cases for item in load_real_samples(case, template_gray=template_gray, cv2=cv2, np=np)]
    holdout_real = [item for case in holdout_cases for item in load_real_samples(case, template_gray=template_gray, cv2=cv2, np=np)]
    if not validation_real or not holdout_real:
        raise ValueError("separate validation and holdout human-transcription cases are required")

    augment = transforms.Compose(
        [
            transforms.Resize((INPUT_SIZE, INPUT_SIZE)),
            transforms.RandomAffine(10, translate=(0.10, 0.10), scale=(0.80, 1.18), shear=5, fill=0),
            transforms.RandomPerspective(distortion_scale=0.12, p=0.20, fill=0),
            transforms.RandomApply([transforms.GaussianBlur(3, sigma=(0.1, 0.7))], p=0.15),
            transforms.ToTensor(),
        ]
    )
    real_augment = transforms.Compose(
        [
            transforms.RandomAffine(8, translate=(0.08, 0.08), scale=(0.85, 1.15), shear=4, fill=0),
            transforms.RandomApply([transforms.GaussianBlur(3, sigma=(0.1, 0.8))], p=0.20),
            transforms.ToTensor(),
        ]
    )
    mnist_full = datasets.MNIST(root=str(args.mnist_root.resolve()), train=True, download=args.download_mnist)
    mnist_choice_indices = balanced_indices(
        mnist_full.targets.tolist(), range(1, 6), limit=args.mnist_limit, seed=args.seed
    )
    mnist_dataset = MappedCharacterDataset(
        mnist_full,
        mnist_choice_indices,
        augment,
        lambda label: str(label),
    )

    emnist_root = str(args.emnist_root.resolve())
    emnist_digits = datasets.EMNIST(
        root=emnist_root,
        split="digits",
        train=True,
        download=args.download_emnist,
    )
    emnist_letters = datasets.EMNIST(
        root=emnist_root,
        split="letters",
        train=True,
        download=args.download_emnist,
    )
    emnist_choice_indices = balanced_indices(
        emnist_digits.targets.tolist(), range(1, 6), limit=args.emnist_digit_limit, seed=args.seed + 1
    )
    digit_reject_limit = max(0, args.emnist_reject_limit // 2)
    letter_reject_limit = max(0, args.emnist_reject_limit - digit_reject_limit)
    emnist_digit_reject_indices = balanced_indices(
        emnist_digits.targets.tolist(), (0, 6, 7, 8, 9), limit=digit_reject_limit, seed=args.seed + 2
    )
    emnist_letter_reject_indices = balanced_indices(
        emnist_letters.targets.tolist(), range(1, 27), limit=letter_reject_limit, seed=args.seed + 3
    )
    emnist_choice_dataset = MappedCharacterDataset(
        emnist_digits,
        emnist_choice_indices,
        augment,
        lambda label: str(label),
        correct_emnist_orientation=True,
    )
    emnist_digit_reject_dataset = MappedCharacterDataset(
        emnist_digits,
        emnist_digit_reject_indices,
        augment,
        lambda _label: REJECT_LABEL,
        correct_emnist_orientation=True,
    )
    emnist_letter_reject_dataset = MappedCharacterDataset(
        emnist_letters,
        emnist_letter_reject_indices,
        augment,
        lambda _label: REJECT_LABEL,
        correct_emnist_orientation=True,
    )
    synthetic_reject_dataset = SyntheticPairRejectDataset(
        mnist_full,
        mnist_choice_indices,
        augment,
        count=args.synthetic_reject_limit,
        seed=args.seed + 4,
    )
    datasets_to_combine = [
        mnist_dataset,
        emnist_choice_dataset,
        emnist_digit_reject_dataset,
        emnist_letter_reject_dataset,
        synthetic_reject_dataset,
    ]
    aihub_sources = []
    if args.aihub_root:
        pooled_samples, samples_by_root = pooled_labeled_crop_samples(
            args.aihub_root,
            choice_limit_per_class=max(0, args.aihub_choice_limit_per_class),
            reject_limit=max(0, args.aihub_reject_limit),
            seed=args.seed + 5,
        )
        aihub_sources = [
            (aihub_root.resolve(), samples_by_root[aihub_root.resolve()])
            for aihub_root in args.aihub_root
        ]
        datasets_to_combine.append(LabeledCropDataset(pooled_samples, augment))
    if train_real:
        public_count = sum(len(dataset) for dataset in datasets_to_combine)
        repeats = max(12, min(80, public_count // max(1, len(train_real) * 8)))
        datasets_to_combine.append(ArrayDataset(torch, train_real, repeats=repeats, augment=real_augment))
    train_dataset = CombinedDataset(datasets_to_combine)
    loader = DataLoader(train_dataset, batch_size=192, shuffle=True, num_workers=0)

    from scripts.student_test_choice_worker import build_model

    model = build_model(torch, output_count=len(LABELS))
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, args.epochs))
    losses = []
    model.train()
    for epoch in range(args.epochs):
        running = 0.0
        count = 0
        for images, labels in loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = torch.nn.functional.cross_entropy(logits, labels)
            loss.backward()
            optimizer.step()
            running += float(loss.detach()) * images.shape[0]
            count += images.shape[0]
        scheduler.step()
        losses.append(running / max(1, count))
        print(f"epoch {epoch + 1}/{args.epochs}: loss={losses[-1]:.6f}", flush=True)

    validation_rows = evaluate(model, validation_real, torch=torch, np=np)
    confidence = float(args.confidence_threshold)
    margin = float(args.margin_threshold)
    holdout_rows = evaluate(model, holdout_real, torch=torch, np=np)
    validation_summary = summarize(validation_rows, confidence, margin)
    holdout_summary = summarize(holdout_rows, confidence, margin)
    human_count = len({(item[2]["case"], item[2]["questionNo"]) for item in train_real + validation_real + holdout_real})
    wrong_upper_95 = zero_error_upper_95(
        holdout_summary["accepted"],
        holdout_summary["wrongAutoGrades"],
    )
    minimum_per_choice = 20
    balanced_holdout = all(
        holdout_summary["perClass"][label]["evaluated"] >= minimum_per_choice
        for label in CHOICE_LABELS
    )
    reject_gate = bool(
        holdout_summary["rejectEvaluated"] >= 20
        and holdout_summary["rejectRecall"] >= 0.98
    )
    readiness = {
        "status": "GO" if (
            holdout_summary["wrongAutoGrades"] == 0
            and holdout_summary["coverage"] >= 0.98
            and human_count >= 250
            and wrong_upper_95 <= 0.01
            and balanced_holdout
            and reject_gate
        ) else "NO_GO",
        "minimumHumanLabeledCrops": 250,
        "minimumAutoCoverage": 0.98,
        "minimumHoldoutPerChoiceClass": minimum_per_choice,
        "minimumHoldoutRejectCrops": 20,
        "minimumRejectRecall": 0.98,
        "maximumAcceptedErrorUpper95": 0.01,
        "maximumWrongAutoGrades": 0,
        "observedHumanLabeledCrops": human_count,
        "observedHoldoutCoverage": holdout_summary["coverage"],
        "observedHoldoutAccepted": holdout_summary["accepted"],
        "observedHoldoutRejectCrops": holdout_summary["rejectEvaluated"],
        "observedRejectRecall": holdout_summary["rejectRecall"],
        "observedAcceptedErrorUpper95": wrong_upper_95,
        "observedBalancedHoldout": balanced_holdout,
        "observedWrongAutoGrades": holdout_summary["wrongAutoGrades"],
    }
    manifests = {
        "train": [case_manifest(case) for case in train_cases],
        "validation": [case_manifest(case) for case in validation_cases],
        "holdout": [case_manifest(case) for case in holdout_cases],
    }
    public_data = {
        "mnist": {
            "source": "torchvision.datasets.MNIST",
            "choiceSamples": len(mnist_dataset),
        },
        "emnist": {
            "source": "https://www.nist.gov/itl/products-and-services/emnist-dataset",
            "choiceSamples": len(emnist_choice_dataset),
            "nonChoiceDigitRejectSamples": len(emnist_digit_reject_dataset),
            "letterRejectSamples": len(emnist_letter_reject_dataset),
            "orientationCorrection": "rotate_minus_90_then_horizontal_mirror",
        },
        "syntheticReject": {
            "source": "two-choice-digit composites generated from MNIST",
            "samples": len(synthetic_reject_dataset),
        },
    }
    if aihub_sources:
        public_data["aihubEducation"] = aihub_public_data(aihub_sources)
    checkpoint = {
        "model_version": MODEL_VERSION,
        "labels": LABELS,
        "input_size": INPUT_SIZE,
        "confidence_threshold": confidence,
        "margin_threshold": margin,
        "model_state": model.state_dict(),
        "metadata": {
            "human_label_source": "human_transcription_choice_or_reject_only",
            "answer_key_fields_used": 0,
            "provider_call_count": 0,
            "trainCases": [case.name for case in train_cases],
            "validationCases": [case.name for case in validation_cases],
            "holdoutCases": [case.name for case in holdout_cases],
            "caseManifests": manifests,
            "publicData": public_data,
            "readiness": readiness,
        },
    }
    torch.save(checkpoint, args.output)
    metrics = {
        "ok": True,
        "modelVersion": MODEL_VERSION,
        "checkpoint": str(args.output),
        "epochs": args.epochs,
        "losses": losses,
        "confidenceThreshold": confidence,
        "marginThreshold": margin,
        "thresholdPolicy": "fixed_runtime_policy_not_selected_on_validation",
        "trainingSamples": len(train_dataset),
        "publicData": public_data,
        "caseManifests": manifests,
        "validation": validation_summary,
        "holdout": holdout_summary,
        "readiness": readiness,
        "answerKeyFieldsUsed": 0,
        "providerCallCount": 0,
    }
    metrics_path = args.output.with_name("metrics.json")
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checkpoint": str(args.output), "metrics": str(metrics_path), "readiness": readiness}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
