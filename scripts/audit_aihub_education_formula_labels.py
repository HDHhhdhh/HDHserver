from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.import_aihub_education_formula_dataset import (
    SUPPORTED_GRADES,
    dataset_grade_code,
    formula_kind,
    normalized_formula_boxes,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit formula annotations without reading AI Hub images.")
    parser.add_argument(
        "--grade-root",
        action="append",
        nargs=2,
        metavar=("GRADE", "LABEL_ROOT"),
        required=True,
    )
    parser.add_argument("--max-per-writer", type=int, default=200)
    return parser.parse_args()


def audit_grade(*, grade: str, labels_root: Path, max_per_writer: int = 200) -> dict:
    normalized_grade = str(grade or "").strip().upper()
    labels_root = labels_root.resolve()
    if normalized_grade not in SUPPORTED_GRADES or not labels_root.is_dir():
        raise ValueError("AI Hub formula label audit input is invalid")
    writer_counts: Counter = Counter()
    kinds: Counter = Counter()
    selected_kinds: Counter = Counter()
    selected = 0
    invalid_json = 0
    grade_mismatches = 0
    label_files = sorted(labels_root.rglob("*.json"))
    for label_path in label_files:
        try:
            payload = json.loads(label_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            invalid_json += 1
            continue
        if dataset_grade_code(payload) != normalized_grade:
            grade_mismatches += 1
            continue
        images = payload.get("Images") if isinstance(payload, dict) else None
        writer = str(images.get("make_id") or "").strip() if isinstance(images, dict) else ""
        if not writer:
            writer = f"missing:{label_path.relative_to(labels_root).as_posix()}"
        for box in normalized_formula_boxes(payload):
            kind = formula_kind(box["equation"])
            kinds[kind] += 1
            if max_per_writer <= 0 or writer_counts[writer] < max_per_writer:
                writer_counts[writer] += 1
                selected_kinds[kind] += 1
                selected += 1
    return {
        "grade": normalized_grade,
        "labelFiles": len(label_files),
        "formulaBoxes": sum(kinds.values()),
        "formulaKinds": dict(sorted(kinds.items())),
        "writers": len(writer_counts),
        "maximumPerWriter": max(0, int(max_per_writer)),
        "selectedAfterWriterCap": selected,
        "selectedKinds": dict(sorted(selected_kinds.items())),
        "invalidJson": invalid_json,
        "gradeMismatches": grade_mismatches,
        "answerKeyFieldsUsed": 0,
    }


def main() -> int:
    args = parse_args()
    seen: set[str] = set()
    rows = []
    for grade, raw_root in args.grade_root:
        normalized = str(grade).strip().upper()
        if normalized in seen:
            raise ValueError("AI Hub formula audit grades must be unique")
        seen.add(normalized)
        rows.append(
            audit_grade(
                grade=normalized,
                labels_root=Path(raw_root),
                max_per_writer=max(0, args.max_per_writer),
            )
        )
    print(json.dumps({"schema": "student_test_aihub_formula_label_audit_v1", "grades": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
