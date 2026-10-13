from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from tools.subjective_sheet_lab.phase2c_crop_pipeline_commands import (
    contact_command,
    crop_command,
    overwritten_ambiguity_command,
    run_pipeline_command,
    verify_assets_command,
)
from tools.subjective_sheet_lab.phase2c_crop_pipeline_contracts import (
    CONTACT_SCRIPT,
    CONTACT_SHEET_COUNT,
    EXTRACT_SCRIPT,
    OCR_PYTHON,
    QUESTION_COUNT,
    ROUTE_UPLOAD_ROOT,
    VERIFY_ASSETS_SCRIPT,
    OVERWRITTEN_AMBIGUITY_SCRIPT,
    JsonObject,
    Phase2CPipelineError,
    Phase2CRequest,
    Phase2CResult,
)
from tools.subjective_sheet_lab.ocr_overwritten_ambiguity_artifact import (
    OverwrittenAmbiguityArtifactError,
    ensure_overwritten_ambiguity_artifact,
)


def run_phase2c_crop_pipeline(request: Phase2CRequest) -> Phase2CResult:
    ensure_pipeline_available()
    case_id = build_case_id(request)
    case_dir = ROUTE_UPLOAD_ROOT / case_id
    incoming_dir = case_dir / "incoming"
    crop_root = case_dir / "crop_benchmark_inputs" / case_id
    crop_dir = crop_root / "crops"
    review_asset_root = case_dir / "review_assets"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)
    review_asset_root.mkdir(parents=True, exist_ok=True)

    source_image = incoming_dir / f"full_sheet{image_suffix(request.original_filename)}"
    save_upload(request.image_stream, source_image)
    write_request_manifest(request, case_id, case_dir, source_image)

    run_pipeline_command(crop_command(source_image, crop_root))
    crop_quality = crop_root / "crop_quality.json"
    quality = load_crop_quality(crop_quality)
    ensure_crop_quality_ok(quality)
    crops = require_files(crop_dir, "q*.png", QUESTION_COUNT, "crop_failed", "Answer sheet image could not be cropped.")
    overwritten_ambiguity = crop_root / "overwritten_ambiguity.json"
    run_pipeline_command(overwritten_ambiguity_command(crop_dir, overwritten_ambiguity))
    ensure_overwritten_ambiguity_ok(overwritten_ambiguity)
    run_pipeline_command(contact_command(crop_dir, review_asset_root, case_id))
    asset_manifest = review_asset_root / "asset_manifest.json"
    run_pipeline_command(verify_assets_command(asset_manifest))

    contact_sheets = require_files(review_asset_root / "contact_sheets", "*.png", CONTACT_SHEET_COUNT, "contact_asset_failed", "Answer sheet review images could not be prepared.")
    debug_sheets = tuple(sorted((review_asset_root / "debug_sheets").glob("*.png")))
    asset_verification = review_asset_root / "asset_verification.json"
    if not asset_verification.is_file():
        raise Phase2CPipelineError("asset_verification_failed", "Answer sheet review images could not be verified.")
    if tuple(case_dir.rglob("recognized.json")):
        raise Phase2CPipelineError("contract_violation", "OCR review payload failed safety checks.")

    result = Phase2CResult(
        case_id=case_id,
        case_dir=case_dir,
        source_image=source_image,
        crop_root=crop_root,
        crop_dir=crop_dir,
        review_asset_root=review_asset_root,
        asset_manifest=asset_manifest,
        crop_count=len(crops),
        contact_sheet_count=len(contact_sheets),
        debug_sheet_count=len(debug_sheets),
        contact_sheets=contact_sheets,
        debug_sheets=debug_sheets,
        asset_verification=asset_verification,
        crop_quality=crop_quality,
        answer_box_source=str(quality.get("answer_box_source") or ""),
        overwritten_ambiguity=overwritten_ambiguity,
    )
    write_pipeline_result(result)
    return result


def ensure_pipeline_available() -> None:
    missing = [path for path in (OCR_PYTHON, EXTRACT_SCRIPT, CONTACT_SCRIPT, VERIFY_ASSETS_SCRIPT, OVERWRITTEN_AMBIGUITY_SCRIPT) if not path.is_file()]
    if missing:
        raise Phase2CPipelineError("pipeline_unavailable", "Answer sheet processing is unavailable.", detail=f"missing pipeline file: {missing[0]}")


def build_case_id(request: Phase2CRequest) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    sid_hash = hashlib.sha256(request.sid.encode("utf-8")).hexdigest()[:8]
    nonce = secrets.token_hex(4)
    test_slug = safe_slug(request.test_id)[:48]
    return f"phase2c_{timestamp}_{nonce}_{sid_hash}_{test_slug}_r{request.round_no}"


def safe_slug(value: str) -> str:
    chars = [char.lower() if char.isascii() and (char.isalnum() or char in {"-", "_"}) else "_" for char in value.strip()]
    slug = "_".join(part for part in "".join(chars).split("_") if part).strip("-_") or "case"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:32].strip('-_') or 'case'}_{digest}"


def image_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"


def save_upload(stream: BinaryIO, target: Path) -> None:
    try:
        stream.seek(0)
        with target.open("wb") as output:
            shutil.copyfileobj(stream, output, length=1024 * 1024)
    except OSError as exc:
        raise Phase2CPipelineError("invalid_image", "Answer sheet image could not be read.", http_status=400, detail=str(exc)) from exc


def write_request_manifest(request: Phase2CRequest, case_id: str, case_dir: Path, source_image: Path) -> None:
    payload: JsonObject = {
        "case_id": case_id,
        "created_at": datetime.now(UTC).isoformat(),
        "sid_hash": hashlib.sha256(request.sid.encode("utf-8")).hexdigest()[:12],
        "test_id": request.test_id,
        "round": str(request.round_no),
        "source_image": str(source_image),
        "content_type": request.content_type,
        "pipeline_version": "phase2c_subprocess_crop_contact_v1",
        "photo_sha256": hashlib.sha256(source_image.read_bytes()).hexdigest(),
        "form_id": "answer_sheet_20_v1",
        "preprocessing_version": "crop_contact_v1",
        "question_numbers": list(range(1,21)),
        "status": "prepared",
    }
    with (case_dir / "request_manifest.json").open("x",encoding="utf-8") as manifest:
        manifest.write(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")


def load_crop_quality(path: Path) -> JsonObject:
    if not path.is_file():
        raise Phase2CPipelineError("crop_quality_missing", "Answer sheet image could not be checked.", detail=f"missing crop quality file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise Phase2CPipelineError("crop_quality_failed", "Answer sheet image could not be checked.", detail=str(exc)) from exc
    if not isinstance(payload, dict):
        raise Phase2CPipelineError("crop_quality_failed", "Answer sheet image could not be checked.", detail="crop_quality.json must be an object")
    return payload


def ensure_crop_quality_ok(quality: JsonObject) -> None:
    failures = quality.get("failures")
    failure_text = ", ".join(str(item) for item in failures) if isinstance(failures, list) else ""
    if quality.get("answer_box_source") == "fixed_fallback" or "answer_box_detection_failed" in failure_text:
        raise Phase2CPipelineError("answer_box_detection_failed", "Answer boxes could not be detected reliably.", http_status=400, detail=failure_text)
    if quality.get("ok") is not True:
        raise Phase2CPipelineError("image_quality_failed", "Answer sheet image quality is too low for OCR review.", http_status=400, detail=failure_text)


def ensure_overwritten_ambiguity_ok(path: Path) -> None:
    try:
        ensure_overwritten_ambiguity_artifact(path)
    except OverwrittenAmbiguityArtifactError as exc:
        raise Phase2CPipelineError("crop_ambiguity_failed", "Answer sheet handwriting could not be checked safely.", detail=str(exc)) from exc


def require_files(root: Path, pattern: str, expected_count: int, error_code: str, student_message: str) -> tuple[Path, ...]:
    paths = tuple(sorted(root.glob(pattern)))
    if len(paths) != expected_count:
        raise Phase2CPipelineError(error_code, student_message, detail=f"{root} produced {len(paths)} {pattern} files, expected {expected_count}")
    return paths


def write_pipeline_result(result: Phase2CResult) -> None:
    payload = asdict(result)
    payload["case_dir"] = str(result.case_dir)
    payload["source_image"] = str(result.source_image)
    payload["crop_root"] = str(result.crop_root)
    payload["crop_dir"] = str(result.crop_dir)
    payload["review_asset_root"] = str(result.review_asset_root)
    payload["asset_manifest"] = str(result.asset_manifest)
    payload["contact_sheets"] = [str(path) for path in result.contact_sheets]
    payload["debug_sheets"] = [str(path) for path in result.debug_sheets]
    payload["asset_verification"] = str(result.asset_verification)
    payload["crop_quality"] = str(result.crop_quality)
    payload["overwritten_ambiguity"] = str(result.overwritten_ambiguity) if result.overwritten_ambiguity is not None else None
    (result.case_dir / "pipeline_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
