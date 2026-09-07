"""Input identity checks for local OCR diagnostics, separate from model execution."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence


def validate_eval_inputs(
    manifest: object,
    observed: Mapping[str, dict],
    *,
    template_sha256: str,
    choice_cases: Sequence[str],
    formula_cases: Sequence[str],
) -> None:
    if not isinstance(manifest, dict) or manifest.get("schema") != "student_test_ocr_eval_inputs_v1":
        raise ValueError("evaluation requires a frozen input manifest")
    if manifest.get("templateSha256") != template_sha256:
        raise ValueError("evaluation template changed")
    records = manifest.get("cases")
    if not isinstance(records, dict) or set(records) != set(observed):
        raise ValueError("evaluation case coverage changed")
    fingerprints = set()
    for name, actual in observed.items():
        expected = records[name]
        if not isinstance(expected, dict) or any(expected.get(key) != actual.get(key) for key in (
            "cropContentSha256", "humanTranscriptionSha256", "cropCount"
        )):
            raise ValueError(f"evaluation crop/transcription binding changed: {name}")
        if actual["cropContentSha256"] in fingerprints:
            raise ValueError("same crop set cannot count as multiple independent cases")
        fingerprints.add(actual["cropContentSha256"])
        role = "choice_number" if name in choice_cases else "answer_value"
        if name not in (*choice_cases, *formula_cases) or expected.get("answerMode") != role:
            raise ValueError(f"evaluation route must be declared before reading labels: {name}")


def check_transcription_source(payload: dict, crop_dir: Path) -> None:
    """Legacy transcriptions may declare crop paths; never substitute another case."""
    sources = payload.get("visual_sources")
    if not isinstance(sources, list):
        return
    declared = [Path(p).resolve() for p in sources if isinstance(p, str) and Path(p).name == "crops"]
    if declared and crop_dir.resolve() not in declared:
        raise ValueError("crop directory disagrees with transcription visual_sources")
