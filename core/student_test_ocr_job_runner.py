from __future__ import annotations

import datetime as dt
import math
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Mapping, Sequence

from core.student_test_formula_profiles import FORMULA_PROFILE_DATASETS
from core.student_test_ocr_engine import OcrCrop
from core.student_test_ocr_repository import (
    StudentTestOcrConflictError,
    StudentTestOcrRepository,
)
from core.student_test_ocr_rules import (
    ANSWER_VALUE,
    CHOICE_NUMBER,
    classify_sheet_recognition,
    normalize_recognized_answer,
)


JOB_SCHEMA = "student_test_ocr_job_v1"
QUESTION_JOB_SCHEMA = "student_test_ocr_question_job_v1"


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
    question_job = isinstance(payload, dict) and payload.get("schema") == QUESTION_JOB_SCHEMA
    if question_job:
        required |= {"questionNo", "captureAssetId", "cropCreatedAt"}
    if not isinstance(payload, dict) or set(payload) != required or payload.get("schema") not in {JOB_SCHEMA, QUESTION_JOB_SCHEMA}:
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
    if question_job:
        number = payload.get("questionNo")
        if type(number) is not int or not 1 <= number <= 20 or modes[number - 1] != ANSWER_VALUE:
            raise OcrJobPayloadError("invalid recapture question")
        if not all(isinstance(payload[key], str) and 0 < len(payload[key]) <= 160 for key in ("captureAssetId", "cropCreatedAt")):
            raise OcrJobPayloadError("invalid recapture asset")
    return {
        "schema": payload["schema"],
        **({key: payload[key] for key in ("questionNo", "captureAssetId", "cropCreatedAt")} if question_job else {}),
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
        on_recognition_committed: Callable[[dict], dict] | None = None,
        recapture_recognizer: Callable[..., dict] | None = None,
        before_recognition: Callable[[dict, Mapping[str, object]], object] | None = None,
    ):
        self.repository = repository
        self.asset_root = asset_root.resolve()
        self.cropper = cropper
        self.recognizer = recognizer
        self.clock = clock
        self.lease_seconds = lease_seconds
        self.on_recognition_committed = on_recognition_committed
        self.recapture_recognizer = recapture_recognizer
        self.before_recognition = before_recognition
        if (not isinstance(lease_seconds, (int, float)) or isinstance(lease_seconds, bool)
                or not math.isfinite(lease_seconds) or lease_seconds <= 0):
            raise ValueError("OCR lease must be positive")
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="student-test-ocr-job")
        self._guard = threading.Lock()
        self._active: Future | None = None
        self._wake_requested = False
        self._closed = False
        self._recovery_timer: threading.Timer | None = None
        self._recovery_interval = 0.0

    def _now(self) -> dt.datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("OCR job clock must return timezone-aware datetimes")
        return value.astimezone(dt.timezone(dt.timedelta(hours=9)))

    def _check_context(self, job: dict) -> None:
        expiry = dt.datetime.fromisoformat(str(job["payload"].get("cropExpiresAt") or ""))
        if expiry.tzinfo is None or expiry.utcoffset() is None or expiry <= self._now():
            raise StudentTestOcrConflictError("capture_expired", "OCR capture retention expired")
        if self.before_recognition is not None:
            submission = self.repository.get(job["submission_id"])
            if submission is None:
                raise OcrJobPayloadError("OCR submission disappeared")
            self.before_recognition(submission, job["payload"])

    def _heartbeat(self, job_id: str, token: str, stop: threading.Event, lost: threading.Event) -> None:
        interval = max(0.05, min(30.0, self.lease_seconds / 3))
        while not stop.wait(interval):
            now = self._now()
            try:
                renewed = self.repository.renew_job_lease(
                    job_id, lease_token=token, now=now.isoformat(timespec="seconds"),
                    lease_expires_at=(now + dt.timedelta(seconds=self.lease_seconds)).isoformat(timespec="seconds"),
                )
                if not renewed:
                    lost.set()
                    return
            except Exception:
                lost.set()
                return

    def _after_commit(self, job: dict, submission: dict) -> dict:
        result = {"jobId": job["id"], "state": "succeeded", "submission": submission}
        if self.on_recognition_committed is not None:
            try:
                result["submission"] = self.on_recognition_committed(submission)
            except Exception as error:
                result["gradingErrorCode"] = str(getattr(error, "code", "grading_failed"))
        return result

    def _run_question(self, job: dict, payload: dict, token: str, lost: threading.Event) -> dict:
        if self.recapture_recognizer is None:
            raise OcrJobPayloadError("question recognizer is unavailable")
        path = _safe_asset_path(self.asset_root, payload["captureRelativePath"])
        if not path.is_file():
            raise OcrJobPayloadError("question image is missing")
        recognized = self.recapture_recognizer(
            question_no=payload["questionNo"], image_path=path, asset_root=self.asset_root,
            formula_profile=payload["formulaProfile"],
        )
        if (not isinstance(recognized, Mapping) or type(recognized.get("questionNo")) is not int
                or recognized.get("questionNo") != payload["questionNo"]):
            raise OcrJobPayloadError("question response is invalid")
        self._check_context(job)
        if lost.is_set():
            raise StudentTestOcrConflictError("lease_conflict", "OCR job lease changed")
        saved = self.repository.record_answer_value_recapture(
            job["submission_id"], question_no=payload["questionNo"], raw_answer=recognized.get("rawAnswer"),
            confident=recognized.get("confident") is True and bool(normalize_recognized_answer(ANSWER_VALUE, recognized.get("rawAnswer"))),
            confidence=recognized.get("confidence"),
            asset_id=payload["captureAssetId"], crop_relpath=payload["captureRelativePath"],
            crop_expires_at=payload["cropExpiresAt"], asset_created_at=payload["cropCreatedAt"],
            expected_revision=payload["submissionRevision"], now=self._now().isoformat(timespec="seconds"),
            job_id=job["id"], lease_token=token,
        )
        return self._after_commit(job, saved)

    def _cleanup_generated(self, items: Sequence[Mapping[str, object]], output_dir: Path | None) -> None:
        if output_dir is None or not output_dir.is_relative_to(self.asset_root):
            return
        parents: set[Path] = set()
        for item in items:
            for key in ("imagePath", "recognitionImagePath"):
                if not item.get(key):
                    continue
                path = Path(str(item[key])).resolve()
                if not path.is_relative_to(output_dir):
                    continue
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
        with self._guard:
            if self._closed:
                return None
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
        lease_stop = threading.Event()
        lease_lost = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat, args=(job["id"], lease_token, lease_stop, lease_lost),
            daemon=True, name="student-test-ocr-lease",
        )
        heartbeat.start()
        generated_items: list[dict] = []
        output_dir: Path | None = None
        try:
            payload = validate_job_payload(job["payload"])
            self._check_context(job)
            if payload["schema"] == QUESTION_JOB_SCHEMA:
                return self._run_question(job, payload, lease_token, lease_lost)
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
            for number, item in enumerate(generated_items, 1):
                if item.get("questionNo") != number:
                    raise OcrJobPayloadError("crop worker question order is invalid")
                for key in ("imagePath", "recognitionImagePath"):
                    path = Path(str(item.get(key) or "")).resolve()
                    if not path.is_relative_to(output_dir) or not path.is_file():
                        raise OcrJobPayloadError("crop worker returned an invalid output path")
            quality = crop_response.get("quality")
            quality = quality if isinstance(quality, dict) else {"ok": False, "failures": ["quality_missing"]}
            crops = [
                OcrCrop(
                    question_no=question_no,
                    answer_mode=payload["answerModes"][question_no - 1],
                    image_path=Path(
                        str(generated_items[question_no - 1].get(
                            "imagePath" if payload["answerModes"][question_no - 1] == ANSWER_VALUE else "recognitionImagePath"
                        ) or "")
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
            self._check_context(job)
            if lease_lost.is_set():
                raise StudentTestOcrConflictError("lease_conflict", "OCR job lease changed")
            committed = self.repository.finish_job_with_recognition(
                job["id"],
                lease_token=lease_token,
                submission_id=job["submission_id"],
                decision=decision,
                assets=crop_assets,
                expected_revision=payload["submissionRevision"],
                now=self._now().isoformat(timespec="seconds"),
            )
        except Exception as error:
            self._cleanup_generated(generated_items, output_dir)
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
        finally:
            lease_stop.set()
            heartbeat.join(timeout=5)
        # Committed review crops must survive a later grading failure. Recognition-only
        # intermediates have no retention row, so remove them immediately after use.
        for item in generated_items:
            if item["recognitionImagePath"] != item["imagePath"]:
                try:
                    Path(item["recognitionImagePath"]).unlink(missing_ok=True)
                except OSError:
                    pass
        return self._after_commit(job, committed["submission"])

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
            if self._closed:
                raise RuntimeError("OCR runner is closed")
            self._wake_requested = True
            if self._active is None:
                self._active = self._executor.submit(self._drain)
            return self._active

    def recover_grading(self) -> None:
        cursor = ""
        while self.on_recognition_committed is not None:
            with self._guard:
                if self._closed:
                    return
            page = self.repository.list_ready_to_grade(after_id=cursor)
            if not page:
                return
            for submission in page:
                with self._guard:
                    if self._closed:
                        return
                cursor = submission["id"]
                try:
                    self.on_recognition_committed(submission)
                except Exception:
                    # Keep committed recognition/crops; retry only grading on a later recovery tick.
                    pass
            if len(page) < 100:
                return

    def _drain(self) -> list[dict]:
        results = []
        try:
            while True:
                with self._guard:
                    self._wake_requested = False
                batch = self.run_until_empty()
                results.extend(batch)
                self.recover_grading()
                with self._guard:
                    if not self._closed and (self._wake_requested or len(batch) >= 100):
                        continue
                    self._active = None
                    return results
        except BaseException:
            with self._guard:
                self._active = None
            raise

    def _recovery_tick(self) -> None:
        try:
            if self.repository.has_recovery_work(now=self._now().isoformat(timespec="seconds")):
                self.wake()
        except Exception:
            pass
        finally:
            with self._guard:
                if not self._closed and self._recovery_interval:
                    self._recovery_timer = threading.Timer(self._recovery_interval, self._recovery_tick)
                    self._recovery_timer.daemon = True
                    self._recovery_timer.start()

    def start_recovery(self, *, interval_seconds: float = 5.0) -> None:
        if not 0.05 <= interval_seconds <= 60:
            raise ValueError("invalid OCR recovery interval")
        with self._guard:
            if self._closed or self._recovery_interval:
                return
            self._recovery_interval = interval_seconds
        self.wake()
        self._recovery_tick()

    def shutdown(self) -> None:
        with self._guard:
            self._closed = True
            timer = self._recovery_timer
            if timer is not None:
                timer.cancel()
        if timer is not None and timer is not threading.current_thread():
            timer.join(timeout=5)
        self._executor.shutdown(wait=True, cancel_futures=False)
