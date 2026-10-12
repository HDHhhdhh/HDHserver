"""Bounded provider attempts and immutable, identity-bound checkpoints (lab only)."""
from __future__ import annotations
import base64
import hashlib
import json
import re
import time
import urllib.error
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from .ocr_run_identity import RECOGNITION_SCHEMA, validate_run_identity, build_run_identity, canonical_json

RAW_SINK = ContextVar("ocr_raw_sink", default=None)
LAST_SESSION = ContextVar("ocr_last_session", default=None)


def capture_raw(value: object) -> None:
    sink = RAW_SINK.get()
    if sink is not None:
        sink(value)


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): _redact(v) for k, v in value.items()
                if str(k).lower() not in {"headers", "api_key", "x-goog-api-key", "authorization", "key"}}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        if value.lstrip().startswith(("{","[")):
            try:
                decoded = json.loads(value)
            except (ValueError,TypeError):
                pass
            else:
                if isinstance(decoded,(dict,list)):
                    return json.dumps(_redact(decoded),ensure_ascii=False)
        value = re.sub(r"AIza[0-9A-Za-z_-]+", "<redacted-secret>", value)
        value = re.sub(r'(?i)((?:api[_-]?key|x-goog-api-key|authorization)\s*[=:]\s*)[^\s,;]+',
                       r'\1<redacted-secret>', value)
        value = re.sub(r"(?i)(?:[a-z]:[\\/]|file://)[^\s\"<>]+", "<redacted-path>", value)
        return value
    return value


def _write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        json.dump(_redact(value), out, ensure_ascii=False, indent=2)
        out.write("\n")


def config_identity(config) -> dict:
    from . import gemini_provider as provider
    if config.source_image is None or config.test_id is None:
        raise provider.GeminiProviderError("source image and test identity are required", reason="run_identity_missing")
    try:
        expected = build_run_identity(Path(config.source_image).read_bytes(), test_id=config.test_id,
                                  round_no=config.round_no, form_id=config.form_id, model=config.model,
                                  prompt_version=config.prompt_version,
                                  preprocessing_version=config.preprocessing_version)
        return validate_run_identity(config.identity, expected=expected) if config.identity is not None else expected
    except (ValueError, OSError) as exc:
        raise provider.GeminiProviderError("invalid run identity", reason="run_identity_invalid") from exc


def _signature(images) -> str:
    parts = [{"questions": list(getattr(image, "questions", (getattr(image, "question", None),))),
              "sha256": hashlib.sha256(base64.b64decode(image.data_base64)).hexdigest()}
             for image in images]
    return hashlib.sha256(canonical_json(parts).encode("utf-8")).hexdigest()


def _item_json(item) -> dict:
    return {"question": item.question, "recognized": item.recognized,
            "candidates": list(item.candidates), "uncertainty": item.uncertainty,
            "needs_review": item.needs_review}


class ProviderSession:
    def __init__(self, config, *, transport=None, sleeper=time.sleep):
        from . import gemini_provider as provider
        self.p = provider
        self.config = config
        self.identity = config_identity(config)
        if type(config.max_calls) is not int or config.max_calls < 0:
            raise provider.GeminiProviderError("explicit nonnegative max_calls is required", reason="provider_budget_missing")
        if type(config.max_retries) is not int or not 0 <= config.max_retries <= 5 or not 0 <= config.backoff_seconds <= 30:
            raise provider.GeminiProviderError("retry/backoff limit is invalid", reason="provider_retry_invalid")
        self.transport = transport or provider.post_gemini
        self.sleeper = sleeper
        self.calls = 0
        self.images = 0
        self.items = {}
        self.completed = {}
        self.input_manifest = None
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + "_" + uuid.uuid4().hex[:8]
        self.run_dir = config.out_path.parent / ("provider_run_" + self.run_id)
        self.raw_number = 0
        self.last_raw_call = -1
        self.error = None
        LAST_SESSION.set(self)
        if config.resume:
            self._load()

    def _load(self):
        # Read old cache only to identify its format; never reuse unversioned results.
        legacy = self.config.out_path.parent / self.p.CACHE_FILE_NAME
        paths = sorted(self.config.out_path.parent.glob("gemini_provider_cache.v1.*.json"))
        if not paths:
            if legacy.is_file():
                self.error = "legacy_cache_not_reused"
            return
        match = None
        mismatch = False
        for path in paths:
            value = json.loads(path.read_text(encoding="utf-8"))
            try:
                validate_run_identity(value.get("identity"), expected=self.identity)
            except ValueError:
                mismatch = True
                continue
            if value.get("schema") != RECOGNITION_SCHEMA:
                continue
            match = value
        if match is None:
            if mismatch:
                raise self.p.GeminiProviderError("cache belongs to a different run", reason="cache_identity_mismatch")
            return
        self.input_manifest = match.get("input_manifest")
        if not isinstance(self.input_manifest, list):
            raise self.p.GeminiProviderError("cache lacks full input manifest", reason="cache_manifest_missing")
        items = match.get("items")
        requests = match.get("requests")
        if not isinstance(items, list) or not isinstance(requests, list):
            raise self.p.GeminiProviderError("cache checkpoint is malformed", reason="cache_malformed")
        for raw in items:
            item = self.p.parse_item(raw)
            if item.question in self.items:
                raise self.p.GeminiProviderError("duplicate cached question", reason="cache_malformed")
            self.items[item.question] = item
        covered = set()
        for request in requests:
            numbers = request.get("questions") if isinstance(request, dict) else None
            if not isinstance(numbers, list) or any(type(n) is not int or n not in range(1,21) for n in numbers):
                raise self.p.GeminiProviderError("invalid completed request", reason="cache_malformed")
            if covered.intersection(numbers) or not set(numbers).issubset(self.items):
                raise self.p.GeminiProviderError("invalid cached request coverage", reason="cache_malformed")
            covered.update(numbers)
            self.completed[tuple(numbers)] = request["input_sha256"]
        if covered != set(self.items):
            raise self.p.GeminiProviderError("cache items lack completed request evidence", reason="cache_malformed")

    def raw(self, value):
        self.raw_number += 1
        _write_new(self.run_dir / f"raw_{self.calls:03d}_{self.raw_number:03d}.json",
                   {"schema": "ocr.provider.raw.v1", "attempt": self.calls, "response": value})
        self.last_raw_call = self.calls

    def diagnostic(self, reason):
        self.error = reason
        _write_new(self.run_dir / f"diagnostic_{uuid.uuid4().hex[:8]}.json",
                   {"identity": self.identity, "reason": reason, "http_attempts": self.calls,
                    "images_sent": self.images, "completed_questions": sorted(self.items),
                    "completed_requests": len(self.completed)})

    def request(self, payload, image_count):
        retry = 0
        while True:
            if self.calls >= self.config.max_calls:
                self.diagnostic("provider_budget_exhausted")
                raise self.p.GeminiProviderError("provider call budget exhausted", reason="provider_budget_exhausted",
                                                 diagnostic=self.counts())
            self.assert_source_unchanged()
            self.calls += 1
            self.images += image_count
            token = RAW_SINK.set(self.raw)
            try:
                response = self.transport(payload, "", self.config.model) if self.transport is not self.p.post_gemini else self.transport(payload, self.api_key, self.config.model)
                if self.last_raw_call != self.calls:
                    self.raw(response)
                return response
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                code = exc.code if isinstance(exc, urllib.error.HTTPError) else None
                body = ""
                if isinstance(exc, urllib.error.HTTPError):
                    try:
                        data = exc.read()
                        body = data.decode("utf-8",errors="replace") if isinstance(data,bytes) else ""
                    except (OSError, AttributeError):
                        body = ""
                self.raw({"error": "http_error" if code else "transport_error", "status": code, "body": body})
                self.diagnostic("provider_quota" if code == 429 else "provider_transport_error")
                if code == 429 or (code is not None and code != 503) or retry >= self.config.max_retries:
                    raise
                if self.calls >= self.config.max_calls:
                    raise self.p.GeminiProviderError("retry exceeds call budget", reason="provider_budget_exhausted", diagnostic=self.counts()) from exc
                self.sleeper(min(30, self.config.backoff_seconds * (2 ** retry)))
                retry += 1
            finally:
                RAW_SINK.reset(token)

    def assert_source_unchanged(self):
        try:
            digest = hashlib.sha256(Path(self.config.source_image).read_bytes()).hexdigest()
        except OSError as exc:
            raise self.p.GeminiProviderError("source image unavailable", reason="provider_input_changed") from exc
        if digest != self.identity["photo_sha256"]:
            raise self.p.GeminiProviderError("source changed during run", reason="provider_input_changed")

    def counts(self):
        return {"provider_calls": self.calls, "image_count": self.images, "completed_questions": len(self.items)}

    def checkpoint(self):
        value = {"schema": RECOGNITION_SCHEMA, "identity": self.identity,
                 "input_manifest": self.input_manifest,
                 "requests": [{"questions": list(numbers), "input_sha256": fingerprint}
                              for numbers, fingerprint in self.completed.items()],
                 "items": [_item_json(item) for _, item in sorted(self.items.items())],
                 "diagnostics": self.counts()}
        _write_new(self.config.out_path.parent / f"gemini_provider_cache.v1.{self.run_id}.{self.calls:03d}.json", value)

    def recognize(self, images, api_key, *, contacts):
        self.api_key = api_key
        numbers = [number for image in images for number in (image.questions if contacts else (image.question,))]
        if any(type(n) is not int for n in numbers) or sorted(numbers) != list(range(1,21)):
            raise self.p.GeminiProviderError("input images must cover 1 through 20 exactly once", reason="provider_input_coverage")
        if self.config.numeric_only and set(self.config.answer_modes) != {"choice_number"}:
            raise self.p.GeminiProviderError("numeric_only requires explicit choice-number-only modes", reason="numeric_only_scope_invalid")
        size = self.config.contact_batch_size if contacts else self.config.crop_batch_size
        if type(size) is not int or not 1 <= size <= 20:
            raise self.p.GeminiProviderError("request batch size is invalid", reason="provider_input_contract")
        units = [images[offset:offset+size] for offset in range(0,len(images),size)]
        manifest = [{"questions":[n for image in unit for n in (image.questions if contacts else (image.question,))],
                     "input_sha256":_signature(unit)} for unit in units]
        if self.input_manifest is not None and canonical_json(self.input_manifest) != canonical_json(manifest):
            raise self.p.GeminiProviderError("request partition or pending input changed", reason="cache_identity_mismatch")
        self.input_manifest = manifest
        self.assert_source_unchanged()
        for unit in units:
            questions = tuple(number for image in unit for number in (image.questions if contacts else (image.question,)))
            signature = _signature(unit)
            if set(questions).issubset(self.items):
                matching = [(q,s) for q,s in self.completed.items() if set(q).issubset(questions)]
                if set(n for q,_ in matching for n in q) == set(questions):
                    if len(matching) == 1 and matching[0][0] == questions and matching[0][1] == signature:
                        continue
                    raise self.p.GeminiProviderError("cached request image/unit changed", reason="cache_identity_mismatch")
            payload = (self.p.build_contact_payload(unit, self.config.test_id, self.config.numeric_only)
                       if contacts else self.p.build_gemini_payload(unit, self.config.numeric_only))
            try:
                response = self.request(payload, len(unit))
                self.assert_source_unchanged()
                text = self.p.extract_response_text(response)
                parsed = self.p.parse_contact_items(text, unit) if contacts else self.p.parse_recognized_items(text, unit)
            except self.p.GeminiProviderError as exc:
                self.diagnostic(exc.reason)
                raise
            for item in parsed:
                if item.question in self.items:
                    raise self.p.GeminiProviderError("duplicate cached/provider question", reason="provider_duplicate_question")
                self.items[item.question] = item
            self.completed[questions] = signature
            self.checkpoint()
        self.assert_source_unchanged()
        self.diagnostic("completed_with_unresolved" if any(not item.recognized.strip() or "?" in item.recognized for item in self.items.values()) else "completed")
        return [self.items[n] for n in range(1,21)]
