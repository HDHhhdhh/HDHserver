from __future__ import annotations

import datetime as dt
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Mapping, Sequence

from core.student_test_formula_profiles import FORMULA_PROFILE_DATASETS
from core.student_test_ocr_engine import OcrCrop, OcrEngineError
from core.student_test_ocr_repository import (
    StudentTestOcrConflictError,
    StudentTestOcrRepository,
)
from core.student_test_ocr_rules import (
    ANSWER_VALUE,
    CHOICE_NUMBER,
    classify_sheet_recognition,
)


JOB_SCHEMA = "student_test_ocr_job_v1"


class OcrJobPayloadError(ValueError):
    pass


def validate_job_payload(payload: object) -> dict:
    required = {
        "schema",
        "submissionRevision",
        "catalogRevision",
        "answerModes",
        "formulaProfile",
        "captureRelativePath",
        "cropOutputRelativeDir",
        "cropExpiresAt",
    }
    if not isinstance(payload, dict) or set(payload) != required or payload.get("schema") != JOB_SCHEMA:
        raise OcrJobPayloadError("invalid OCR job payload")
    revision = payload.get("submissionRevision")
    catalog_revision = str(payload.get("catalogRevision") or "").strip()
    modes = payload.get("answerModes")
    formula_profile = payload.get("formulaProfile")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise OcrJobPayloadError("invalid OCR submission revision")
    if not catalog_revision or len(catalog_revision) > 160:
        raise OcrJobPayloadError("invalid test catalog revision")
    if not isinstance(modes, list) or len(modes) != 20 or any(mode not in {CHOICE_NUMBER, ANSWER_VALUE} for mode in modes):
        raise OcrJobPayloadError("invalid OCR answer modes")
    if ANSWER_VALUE in modes:
        if formula_profile not in FORMULA_PROFILE_DATASETS:
            raise OcrJobPayloadError("invalid OCR formula profile")
    elif formula_profile is not None:
        raise OcrJobPayloadError("choice-only OCR job must not select a formula profile")
    for key in ("captureRelativePath", "cropOutputRelativeDir"):
        value = str(payload.get(key) or "").replace("\\", "/").strip("/")
        if not value or ".." in value.split("/"):
            raise OcrJobPayloadError(f"invalid {key}")
    if not str(payload.get("cropExpiresAt") or "").strip():
        raise OcrJobPayloadError("invalid crop expiry")
    return {
        "submissionRevision": revision,
        "catalogRevision": catalog_revision,
        "answerModes": tuple(modes),
        "formulaProfile": formula_profile,
        "captureRelativePath": str(payload["captureRelativePath"]).replace("\\", "/").strip("/"),
        "cropOutputRelativeDir": str(payload["cropOutputRelativeDir"]).replace("\\", "/").strip("/"),
        "cropExpiresAt": str(payload["cropExpiresAt"]).strip(),
    }


def _safe_asset_path(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise OcrJobPayloadError("OCR job asset path escapes its root") from error
    return candidate


def _decision_with_crop_quality(
    answer_modes: Sequence[str],
    recognition: Mapping[str, object],
    crop_items: Sequence[Mapping[str, object]],
) -> dict:
    recognized_items = recognition.get("items")
    if not isinstance(recognized_items, list) or len(recognized_items) != 20 or len(crop_items) != 20:
        raise OcrJobPayloadError("OCR engine result is incomplete")
    indexed = {item.get("questionNo"): item for item in recognized_items if isinstance(item, dict)}
    candidates: list[dict] = []
    for question_no, crop_item in enumerate(crop_items, start=1):
        item = indexed.get(question_no)
        if not isinstance(item, dict) or crop_item.get("questionNo") != question_no:
            raise OcrJobPayloadError("OCR engine question order is invalid")
        warnings = crop_item.get("blockingWarnings")
        if not isinstance(warnings, list):
            warnings = crop_item.get("warnings")
        warnings = warnings if isinstance(warnings, list) else []
        candidates.append(
            {
                "questionNo": question_no,
                "rawAnswer": item.get("rawAnswer") or "",
                "confidence": item.get("confidence"),
                "confident": item.get("recognitionState") == "confident" and not warnings,
            }
        )
    return classify_sheet_recognition(answer_modes, candidates)


class StudentTestOcrJobRunner:
    def __init__(
        self,
        *,
        repository: StudentTestOcrRepository,
        asset_root: Path,
        cropper: Callable[..., dict],
        recognizer: Callable[..., dict],
        clock: Callable[[], dt.datetime],
        lease_seconds: int = 180,
    ):
        self.repository = repository
        self.asset_root = asset_root.resolve()
        self.cropper = cropper
        self.recognizer = recognizer
        self.clock = clock
        self.lease_seconds = lease_seconds
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="student-test-ocr-job")
        self._guard = threading.Lock()
        self._active: Future | None = None

    def _now(self) -> dt.datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("OCR job clock must return timezone-aware datetimes")
        return value

    @staticmethod
    def _cleanup_generated(items: Sequence[Mapping[str, object]]) -> None:
        parents: set[Path] = set()
        for item in items:
            for key in ("imagePath", "recognitionImagePath"):
                path = Path(str(item.get(key) or ""))
                parents.add(path.parent)
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        for parent in sorted(parents, key=lambda path: len(path.parts), reverse=True):
            try:
                parent.rmdir()
            except OSError:
                pass

    def run_one(self) -> dict | None:
        now = self._now()
        now_text = now.isoformat(timespec="seconds")
        lease_token = uuid.uuid4().hex
        lease_expires = (now + dt.timedelta(seconds=self.lease_seconds)).isoformat(timespec="seconds")
        job = self.repository.lease_next_job(
            lease_token=lease_token,
            now=now_text,
            lease_expires_at=lease_expires,
        )
        if job is None:
            return None
        generated_items: list[dict] = []
        try:
            payload = validate_job_payload(job["payload"])
            capture_path = _safe_asset_path(self.asset_root, payload["captureRelativePath"])
            output_relative = f"{payload['cropOutputRelativeDir']}/attempt-{int(job['attempts'])}"
            output_dir = _safe_asset_path(self.asset_root, output_relative)
            crop_response = self.cropper(
                asset_root=self.asset_root,
                image_path=capture_path,
                output_dir=output_dir,
            )
            raw_crop_items = crop_response.get("items")
            if not isinstance(raw_crop_items, list) or len(raw_crop_items) != 20:
                raise OcrJobPayloadError("crop worker did not return 20 items")
            generated_items = [dict(item) for item in raw_crop_items if isinstance(item, dict)]
            if len(generated_items) != 20:
                raise OcrJobPayloadError("crop worker item contract is invalid")
            quality = crop_response.get("quality")
            quality = quality if isinstance(quality, dict) else {"ok": False, "failures": ["quality_missing"]}
            crops = [
                OcrCrop(
                    question_no=question_no,
                    answer_mode=payload["answerModes"][question_no - 1],
                    image_path=Path(
                        str(generated_items[question_no - 1].get("recognitionImagePath") or "")
                    ),
                )
                for question_no in range(1, 21)
            ]
            if quality.get("ok") is True:
                recognition = self.recognizer(
                    crops=crops,
                    asset_root=self.asset_root,
                    formula_profile=payload["formulaProfile"],
                )
                decision = _decision_with_crop_quality(payload["answerModes"], recognition, generated_items)
            else:
                decision = classify_sheet_recognition(
                    payload["answerModes"],
                    [
                        {"questionNo": number, "rawAnswer": "", "confidence": None, "confident": False}
                        for number in range(1, 21)
                    ],
                )
            crop_assets: list[dict] = []
            for question_no, item in enumerate(generated_items, start=1):
                path = _safe_asset_path(self.asset_root, Path(str(item["imagePath"])))
                relative = path.relative_to(self.asset_root).as_posix()
                decision_item = decision["items"][question_no - 1]
                decision_item["cropRelativePath"] = relative
                decision_item["cropExpiresAt"] = payload["cropExpiresAt"]
                crop_assets.append(
                    {
                        "id": uuid.uuid4().hex,
                        "questionNo": question_no,
                        "kind": "student_crop",
                        "relativePath": relative,
                        "expiresAt": payload["cropExpiresAt"],
                        "createdAt": now_text,
                    }
                )
            committed = self.repository.finish_job_with_recognition(
                job["id"],
                lease_token=lease_token,
                submission_id=job["submission_id"],
                decision=decision,
                assets=crop_assets,
                expected_revision=payload["submissionRevision"],
                now=now_text,
            )
            return {"jobId": job["id"], "state": "succeeded", "submission": committed["submission"]}
        except Exception as error:
            self._cleanup_generated(generated_items)
            code = getattr(error, "code", "ocr_job_failed")
            try:
                self.repository.finish_job(
                    job["id"],
                    lease_token=lease_token,
                    succeeded=False,
                    result=None,
                    error_code=str(code),
                    now=self._now().isoformat(timespec="seconds"),
                )
            except StudentTestOcrConflictError:
                pass
            return {"jobId": job["id"], "state": "failed", "errorCode": str(code)}

    def run_until_empty(self, *, maximum_jobs: int = 100) -> list[dict]:
        results: list[dict] = []
        for _ in range(maximum_jobs):
            result = self.run_one()
            if result is None:
                break
            results.append(result)
        return results

    def wake(self) -> Future:
        with self._guard:
            if self._active is None or self._active.done():
                self._active = self._executor.submit(self.run_until_empty)
            return self._active

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
