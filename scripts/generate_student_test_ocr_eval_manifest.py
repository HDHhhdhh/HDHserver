"""Pin a prior diagnostic's known input identities for a reproducible rerun."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--choice-case", action="append", default=[])
    parser.add_argument("--formula-case", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    rows = baseline["inputManifests"]
    names = [row["name"] for row in rows]
    declared = args.choice_case + args.formula_case
    if len(set(names)) != len(names) or len(set(declared)) != len(declared) or set(names) != set(declared):
        raise ValueError("declare exactly one route for every baseline case")
    manifest = {
        "schema": "student_test_ocr_eval_inputs_v1", "evidenceClass": "legacy_crop_diagnostic",
        "baselineSha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
        "templateSha256": hashlib.sha256(args.template.read_bytes()).hexdigest(),
        "cases": {row["name"]: {**row, "answerMode": "choice_number" if row["name"] in args.choice_case else "answer_value"} for row in rows},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
