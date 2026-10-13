from __future__ import annotations

import json
import tempfile
from pathlib import Path

from texteller_human_benchmark import REVIEW_REQUIRED, run_benchmark


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="texteller-benchmark-verify-") as raw_tmp:
        root = Path(raw_tmp)
        crop_root = root / "crops"
        human_root = root / "human"
        case_id = "case_alpha"
        crop_dir = crop_root / case_id / "crops"
        human_dir = human_root / f"{case_id}_same_contact"
        crop_dir.mkdir(parents=True)
        human_dir.mkdir(parents=True)

        human_rows = []
        raw_outputs = []
        for question_no in range(1, 21):
            (crop_dir / f"q{question_no:03d}.png").write_bytes(b"fake-image")
            human_answer = str((question_no % 5) + 1)
            human_rows.append(
                {
                    "question_no": question_no,
                    "human_answer": human_answer,
                    "confidence": "high",
                }
            )
            raw_outputs.append(f"\\[{human_answer}\\]")
        raw_outputs[0] = "?"
        raw_outputs[1] = "\\[5\\]"
        (human_dir / "human_transcription.json").write_text(
            json.dumps({"answers": human_rows}), encoding="utf-8"
        )

        payload = run_benchmark(
            [case_id],
            crop_root=crop_root,
            human_root=human_root,
            recognizer=lambda paths: raw_outputs[: len(paths)],
        )
        assert payload["provider_calls"] == 0
        assert payload["unsafe_auto_grade_count"] == 0
        assert payload["problem_count"] == 20
        assert payload["summary"] == {
            "high_confidence_in_scope": 20,
            "exact_matches": 18,
            "unresolved": 1,
            "mismatches": 1,
            "outside_supported_scope": 0,
            "human_low_confidence": 0,
            "exact_match_percent": 90.0,
        }
        assert all(item["status"] == REVIEW_REQUIRED for item in payload["items"])
        assert str(root) not in str(payload)

    print("texteller human benchmark: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
