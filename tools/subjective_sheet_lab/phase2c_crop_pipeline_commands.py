from __future__ import annotations

import subprocess
from pathlib import Path

from tools.subjective_sheet_lab.phase2c_crop_pipeline_contracts import (
    COMMAND_TIMEOUT_SECONDS,
    CONTACT_SCRIPT,
    DEFAULT_DEBUG_QUESTIONS,
    EXTRACT_SCRIPT,
    OCR_PYTHON,
    OCR_ROOT,
    OVERWRITTEN_AMBIGUITY_SCRIPT,
    VERIFY_ASSETS_SCRIPT,
    Phase2CPipelineError,
    PipelineCommand,
)


def crop_command(source_image: Path, crop_root: Path) -> PipelineCommand:
    return PipelineCommand(
        label="crop",
        error_code="crop_failed",
        student_message="Answer sheet image could not be cropped.",
        command=(
            str(OCR_PYTHON),
            str(EXTRACT_SCRIPT),
            "--image",
            str(source_image),
            "--out-dir",
            str(crop_root),
            "--strict-answer-boxes",
            "--strict-quality",
        ),
    )


def contact_command(crop_dir: Path, review_asset_root: Path, case_id: str) -> PipelineCommand:
    debug_questions = ",".join(str(question) for question in DEFAULT_DEBUG_QUESTIONS)
    return PipelineCommand(
        label="contact_assets",
        error_code="contact_asset_failed",
        student_message="Answer sheet review images could not be prepared.",
        command=(str(OCR_PYTHON), str(CONTACT_SCRIPT), "--crop-dir", str(crop_dir), "--out-dir", str(review_asset_root), "--prefix", case_id, "--debug-questions", debug_questions),
    )


def verify_assets_command(asset_manifest: Path) -> PipelineCommand:
    return PipelineCommand(
        label="asset_verification",
        error_code="asset_verification_failed",
        student_message="Answer sheet review images could not be verified.",
        command=(str(OCR_PYTHON), str(VERIFY_ASSETS_SCRIPT), "--manifest", str(asset_manifest), "--expected-debug-count", str(len(DEFAULT_DEBUG_QUESTIONS))),
    )


def overwritten_ambiguity_command(crop_dir: Path, artifact_path: Path) -> PipelineCommand:
    return PipelineCommand(
        label="overwritten_ambiguity",
        error_code="crop_ambiguity_failed",
        student_message="Answer sheet handwriting could not be checked safely.",
        command=(str(OCR_PYTHON), str(OVERWRITTEN_AMBIGUITY_SCRIPT), "--crop-dir", str(crop_dir), "--out", str(artifact_path)),
    )


def run_pipeline_command(command: PipelineCommand) -> None:
    try:
        subprocess.run(command.command, cwd=OCR_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=COMMAND_TIMEOUT_SECONDS, check=True)
    except subprocess.TimeoutExpired as exc:
        raise Phase2CPipelineError(command.error_code, command.student_message, detail=f"{command.label} timed out: {tail(exc.stdout)} {tail(exc.stderr)}") from exc
    except subprocess.CalledProcessError as exc:
        detail = f"{command.label} failed: {tail(exc.stdout)} {tail(exc.stderr)}"
        mapped = mapped_crop_error(command, detail)
        if mapped is not None:
            error_code, student_message, http_status = mapped
            raise Phase2CPipelineError(error_code, student_message, http_status=http_status, detail=detail) from exc
        raise Phase2CPipelineError(command.error_code, command.student_message, detail=detail) from exc
    except OSError as exc:
        raise Phase2CPipelineError("pipeline_unavailable", "Answer sheet processing is unavailable.", detail=str(exc)) from exc


def mapped_crop_error(command: PipelineCommand, detail: str) -> tuple[str, str, int] | None:
    if command.label != "crop":
        return None
    if "marker_detection_failed" in detail:
        return ("marker_detection_failed", "Answer sheet markers could not be detected reliably.", 400)
    if "answer_box_detection_failed" in detail:
        return ("answer_box_detection_failed", "Answer boxes could not be detected reliably.", 400)
    if "image_quality_failed" in detail:
        return ("image_quality_failed", "Answer sheet image quality is too low for OCR review.", 400)
    return None


def tail(value: str | bytes | None) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    return text[-1200:]
