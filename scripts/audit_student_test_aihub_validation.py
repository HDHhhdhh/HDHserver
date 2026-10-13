from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Final, Iterable, Mapping

from core.student_test_formula_profiles import FORMULA_PROFILE_DATASETS
from scripts.import_aihub_education_choice_dataset import (
    CHOICE_LABELS,
    REJECT_LABEL,
    normalized_boxes,
)
from scripts.import_aihub_education_formula_dataset import (
    SUPPORTED_GRADES,
    dataset_grade_code,
    formula_kind,
    normalized_formula_boxes,
)


SCHEMA: Final = "student_test_aihub_grade_validation_audit_v1"
CHOICE_CLASSES: Final = (*CHOICE_LABELS, REJECT_LABEL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit AI Hub Training/Validation label integrity and report grade-wise "
            "writer-disjoint evaluation inventory."
        )
    )
    parser.add_argument(
        "--training-root",
        action="append",
        nargs=2,
        metavar=("GRADE", "LABEL_ROOT"),
        required=True,
    )
    parser.add_argument(
        "--validation-root",
        action="append",
        nargs=2,
        metavar=("GRADE", "LABEL_ROOT"),
        required=True,
    )
    return parser.parse_args()


def _grade_roots(values: Iterable[Iterable[str]], *, label: str) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for raw_grade, raw_root in values:
        grade = str(raw_grade or "").strip().upper()
        root = Path(raw_root).resolve()
        if grade not in SUPPORTED_GRADES or grade in roots or not root.is_dir():
            raise ValueError(f"AI Hub {label} grade roots are invalid")
        roots[grade] = root
    if set(roots) != set(SUPPORTED_GRADES):
        raise ValueError(f"AI Hub {label} roots must contain M_G3, H_G1, H_G2, and H_G3 exactly once")
    return roots


def _writer_id(payload: object, relative_path: str) -> str:
    images = payload.get("Images") if isinstance(payload, dict) else None
    writer = str(images.get("make_id") or "").strip() if isinstance(images, dict) else ""
    return writer or f"missing:{relative_path}"


def _image_identifier(payload: object) -> str:
    images = payload.get("Images") if isinstance(payload, dict) else None
    return str(images.get("identifier") or "").strip() if isinstance(images, dict) else ""


def _empty_choice_counter() -> Counter:
    return Counter({label: 0 for label in CHOICE_CLASSES})


def _empty_formula_counter() -> Counter:
    return Counter({kind: 0 for kind in ("number", "fraction", "root", "other")})


def _ordered_choice_counts(values: Mapping[str, int]) -> dict[str, int]:
    return {label: int(values.get(label, 0)) for label in CHOICE_CLASSES}


def _ordered_formula_counts(values: Mapping[str, int]) -> dict[str, int]:
    return {kind: int(values.get(kind, 0)) for kind in ("number", "fraction", "root", "other")}


def split_inventory(*, grade: str, root: Path) -> dict:
    root = root.resolve()
    if grade not in SUPPORTED_GRADES or not root.is_dir():
        raise ValueError("AI Hub split inventory input is invalid")
    label_files = sorted(root.rglob("*.json"))
    invalid_json = 0
    grade_mismatches = 0
    identifiers: set[str] = set()
    writers: set[str] = set()
    choice_writers: set[str] = set()
    formula_writers: set[str] = set()
    choice_counts = _empty_choice_counter()
    formula_kinds = _empty_formula_counter()
    records: list[dict] = []
    for path in label_files:
        relative = path.relative_to(root).as_posix()
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            invalid_json += 1
            continue
        if dataset_grade_code(payload) != grade:
            grade_mismatches += 1
            continue
        writer = _writer_id(payload, relative)
        identifier = _image_identifier(payload)
        choices = normalized_boxes(payload)
        formulas = normalized_formula_boxes(payload)
        record_choice_counts = _empty_choice_counter()
        record_formula_kinds = _empty_formula_counter()
        record_choice_counts.update(box["label"] for box in choices)
        record_formula_kinds.update(formula_kind(box["equation"]) for box in formulas)
        writers.add(writer)
        if identifier:
            identifiers.add(identifier)
        if choices:
            choice_writers.add(writer)
            choice_counts.update(record_choice_counts)
        if formulas:
            formula_writers.add(writer)
            formula_kinds.update(record_formula_kinds)
        records.append(
            {
                "writer": writer,
                "identifier": identifier,
                "choiceCounts": record_choice_counts,
                "formulaKinds": record_formula_kinds,
            }
        )
    return {
        "grade": grade,
        "labelFiles": len(label_files),
        "validGradeFiles": len(records),
        "invalidJson": invalid_json,
        "gradeMismatches": grade_mismatches,
        "identifiers": identifiers,
        "writers": writers,
        "choiceWriters": choice_writers,
        "formulaWriters": formula_writers,
        "choiceCounts": choice_counts,
        "formulaKinds": formula_kinds,
        "records": records,
    }


def _public_inventory(inventory: Mapping[str, object]) -> dict:
    choice_counts = inventory["choiceCounts"]
    formula_kinds = inventory["formulaKinds"]
    return {
        "labelFiles": int(inventory["labelFiles"]),
        "validGradeFiles": int(inventory["validGradeFiles"]),
        "invalidJson": int(inventory["invalidJson"]),
        "gradeMismatches": int(inventory["gradeMismatches"]),
        "identifiers": len(inventory["identifiers"]),
        "writers": len(inventory["writers"]),
        "choiceWriters": len(inventory["choiceWriters"]),
        "choiceCounts": _ordered_choice_counts(choice_counts),
        "formulaWriters": len(inventory["formulaWriters"]),
        "formulaBoxes": sum(int(value) for value in formula_kinds.values()),
        "formulaKinds": _ordered_formula_counts(formula_kinds),
    }


def _strict_counts(records: Iterable[Mapping[str, object]], *, known_writers: set[str], field: str) -> tuple[set[str], Counter]:
    selected_writers: set[str] = set()
    counts: Counter = Counter()
    for record in records:
        writer = str(record["writer"])
        values = record[field]
        if writer in known_writers or not any(int(value) for value in values.values()):
            continue
        selected_writers.add(writer)
        counts.update(values)
    return selected_writers, counts


def audit_validation(
    *,
    training_roots: Mapping[str, Path],
    validation_roots: Mapping[str, Path],
) -> dict:
    if set(training_roots) != set(SUPPORTED_GRADES) or set(validation_roots) != set(SUPPORTED_GRADES):
        raise ValueError("AI Hub validation audit requires all four supported grades")
    training = {
        grade: split_inventory(grade=grade, root=Path(training_roots[grade]))
        for grade in sorted(SUPPORTED_GRADES)
    }
    validation = {
        grade: split_inventory(grade=grade, root=Path(validation_roots[grade]))
        for grade in sorted(SUPPORTED_GRADES)
    }
    all_training_identifiers = set().union(*(item["identifiers"] for item in training.values()))
    all_choice_training_writers = set().union(*(item["choiceWriters"] for item in training.values()))
    profile_formula_writers = {
        profile: set().union(*(training[grade]["formulaWriters"] for grade in grades))
        for profile, grades in FORMULA_PROFILE_DATASETS.items()
    }
    rows = []
    for grade in ("M_G3", "H_G1", "H_G2", "H_G3"):
        train_item = training[grade]
        validation_item = validation[grade]
        strict_choice_writers, strict_choice_counts = _strict_counts(
            validation_item["records"],
            known_writers=all_choice_training_writers,
            field="choiceCounts",
        )
        identifier_overlap = validation_item["identifiers"] & all_training_identifiers
        choice_writer_overlap = validation_item["choiceWriters"] & all_choice_training_writers
        profile_rows = {}
        for profile, grades in FORMULA_PROFILE_DATASETS.items():
            applicable = grade in grades
            known_formula_writers = profile_formula_writers[profile]
            strict_formula_writers, strict_formula_kinds = _strict_counts(
                validation_item["records"],
                known_writers=known_formula_writers,
                field="formulaKinds",
            )
            profile_rows[profile] = {
                "applicable": applicable,
                "trainingFormulaWriters": len(known_formula_writers),
                "validationWriterOverlap": len(validation_item["formulaWriters"] & known_formula_writers),
                "strictFormulaWriters": len(strict_formula_writers),
                "strictFormulaBoxes": sum(strict_formula_kinds.values()),
                "strictFormulaKinds": _ordered_formula_counts(strict_formula_kinds),
            }
        minimum_choice_class = min(int(strict_choice_counts.get(label, 0)) for label in CHOICE_LABELS)
        integrity_passed = bool(
            train_item["invalidJson"] == 0
            and train_item["gradeMismatches"] == 0
            and validation_item["invalidJson"] == 0
            and validation_item["gradeMismatches"] == 0
            and not identifier_overlap
        )
        rows.append(
            {
                "grade": grade,
                "training": _public_inventory(train_item),
                "validation": _public_inventory(validation_item),
                "leakage": {
                    "identifierOverlap": len(identifier_overlap),
                    "choiceWriterOverlap": len(choice_writer_overlap),
                },
                "strictChoice": {
                    "writers": len(strict_choice_writers),
                    "counts": _ordered_choice_counts(strict_choice_counts),
                    "minimumPerChoiceClass": minimum_choice_class,
                    "hasAtLeast20PerChoiceClass": minimum_choice_class >= 20,
                },
                "formulaProfiles": profile_rows,
                "sourceIntegrity": "PASS" if integrity_passed else "FAIL",
                "answerKeyFieldsUsed": 0,
            }
        )
    return {
        "schema": SCHEMA,
        "trainingGrades": ["M_G3", "H_G1", "H_G2", "H_G3"],
        "choiceTrainingWriters": len(all_choice_training_writers),
        "formulaProfileTrainingWriters": {
            profile: len(writers) for profile, writers in profile_formula_writers.items()
        },
        "grades": rows,
        "overallSourceIntegrity": "PASS" if all(row["sourceIntegrity"] == "PASS" for row in rows) else "FAIL",
        "scope": "label_and_split_only_no_model_accuracy",
        "answerKeyFieldsUsed": 0,
    }


def main() -> int:
    args = parse_args()
    summary = audit_validation(
        training_roots=_grade_roots(args.training_root, label="training"),
        validation_roots=_grade_roots(args.validation_root, label="validation"),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
