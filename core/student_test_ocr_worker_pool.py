"""Owned, lazy local OCR children. No model loading or runtime writes in this module."""
from __future__ import annotations

import atexit
import json
import queue
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from core.student_test_ocr_engine import (
    MAX_WORKER_STDOUT_BYTES, WORKER_SCHEMA, OcrCrop, OcrEngineError, WorkerSpec,
    _safe_worker_environment,
)
from scripts.student_test_ocr_worker_server import MAX_REQUEST_BYTES, TRANSPORT_SCHEMA

OPTION_ENV = {"STUDENT_TEST_OCR_UNIMERNET_SECOND_PASS": "secondPass",
              "STUDENT_TEST_OCR_UNIMERNET_VARIANT_PASS": "variantPass"}
MAX_STDERR_BYTES = 4096


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OcrEngineError("ocr_engine_timeout", "local OCR worker timed out")
    return remaining


def _signature(path: Path) -> tuple:
    resolved = path.resolve()
    stat = resolved.stat()
    return str(resolved), stat.st_size, stat.st_mtime_ns, stat.st_ino


def _model_signatures(environment: dict[str, str]) -> tuple:
    signatures = []
    choice = environment.get("STUDENT_TEST_OCR_CHOICE_MODEL_PATH")
    if choice:
        signatures.append(_signature(Path(choice)))
    unimernet = environment.get("STUDENT_TEST_OCR_UNIMERNET_MODEL_DIR")
    if unimernet:
        root = Path(unimernet)
        weight = environment.get("STUDENT_TEST_OCR_UNIMERNET_WEIGHT", "unimernet_tiny.pth")
        for name in (weight, "config.json", "preprocessor_config.json", "tokenizer_config.json", "tokenizer.json"):
            signatures.append(_signature(root / name))
    for key in ("STUDENT_TEST_OCR_PADDLE_MODEL_DIR", "STUDENT_TEST_OCR_FORMULA_MODEL_DIR"):
        value = environment.get(key)
        if value:
            root = Path(value).resolve()
            if not root.is_dir():
                raise OSError("OCR model directory is unavailable")
            signatures.append(_signature(root))
            signatures.extend(_signature(path) for path in sorted(root.rglob("*")) if path.is_file())
    return tuple(signatures)


class _Child:
    def __init__(self, command: list[str], environment: dict[str, str]):
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.responses: queue.Queue = queue.Queue(maxsize=2)
        self.stderr = bytearray()
        self.poisoned = False
        self._close_guard = threading.Lock()
        self._closed = False
        threading.Thread(target=self._read_stdout, name="ocr-worker-stdout", daemon=True).start()
        threading.Thread(target=self._read_stderr, name="ocr-worker-stderr", daemon=True).start()

    def _post(self, kind: str, value: object = None) -> None:
        try:
            self.responses.put_nowait((kind, value))
        except queue.Full:
            self.poisoned = True

    def _read_stdout(self) -> None:
        try:
            while True:
                line = self.process.stdout.readline(MAX_WORKER_STDOUT_BYTES + 1)
                if not line:
                    self._post("eof")
                    return
                if len(line) > MAX_WORKER_STDOUT_BYTES or not line.endswith(b"\n"):
                    self.poisoned = True
                    self._post("invalid")
                    return
                self._post("line", line)
                if self.poisoned:
                    return
        except (OSError, ValueError):
            self._post("eof")

    def _read_stderr(self) -> None:
        try:
            while True:
                chunk = self.process.stderr.read(4096)
                if not chunk:
                    return
                self.stderr.extend(chunk)
                del self.stderr[:-MAX_STDERR_BYTES]
        except (OSError, ValueError):
            return

    def exchange(self, data: bytes, deadline: float) -> bytes:
        if self.poisoned or not self.responses.empty() or self.process.poll() is not None:
            raise OcrEngineError("invalid_worker_response", "OCR worker emitted unsolicited output or exited")
        written: queue.Queue = queue.Queue(maxsize=1)

        def write_request() -> None:
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
                written.put_nowait(None)
            except (OSError, ValueError) as error:
                written.put_nowait(error)

        threading.Thread(target=write_request, name="ocr-worker-stdin", daemon=True).start()
        try:
            error = written.get(timeout=_remaining(deadline))
            if error is not None:
                raise OcrEngineError("ocr_engine_failed", "OCR worker request could not be written") from error
            kind, value = self.responses.get(timeout=_remaining(deadline))
        except queue.Empty as error:
            raise OcrEngineError("ocr_engine_timeout", "local OCR worker timed out") from error
        _remaining(deadline)
        if kind == "eof":
            raise OcrEngineError("ocr_engine_failed", "OCR worker exited without a response")
        if kind != "line" or self.poisoned:
            raise OcrEngineError("invalid_worker_response", "OCR worker response exceeded its framing limit")
        return value

    def close(self) -> None:
        with self._close_guard:
            if self._closed:
                return
            self._closed = True
            if self.process.poll() is None:
                try:
                    self.process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass


@dataclass
class _Slot:
    lock: threading.Lock = field(default_factory=threading.Lock)
    key: tuple | None = None
    child: _Child | None = None


class ResidentWorkerPool:
    """One lazy child per engine; switching a UniMERNet profile replaces its child."""
    def __init__(self):
        self._guard = threading.Lock()
        self._slots: dict[str, _Slot] = {}
        self._closed = False
        atexit.register(self.shutdown)

    def run(self, spec: WorkerSpec, crops: Sequence[OcrCrop]) -> dict:
        started = time.perf_counter()
        deadline = time.monotonic() + spec.timeout_seconds
        try:
            signatures = (_signature(spec.python_path), _signature(spec.script_path))
            helper = spec.script_path.with_name("student_test_ocr_worker_server.py")
            if helper.is_file():
                signatures += (_signature(helper),)
            generation = spec.script_path.with_name("student_test_formula_inference.py")
            if spec.engine == "unimernet" and generation.is_file():
                signatures += (_signature(generation),)
        except OSError as error:
            raise OcrEngineError("ocr_engine_unavailable", f"{spec.engine} worker is not installed") from error
        environment = _safe_worker_environment(spec.environment)
        options = {option: str(environment.pop(name, "")).strip().lower() in {"1", "true", "yes", "on"}
                   for name, option in OPTION_ENV.items()}
        try:
            model_signatures = _model_signatures(environment)
        except OSError as error:
            raise OcrEngineError("ocr_engine_unavailable", "OCR model files are not installed") from error
        key = (signatures, model_signatures, spec.arguments, tuple(sorted(environment.items())))
        request_id = uuid.uuid4().hex
        payload = {"schema": WORKER_SCHEMA, "items": [
            {"questionNo": crop.question_no, "imagePath": str(crop.image_path)} for crop in crops]}
        data = (json.dumps({"schema": TRANSPORT_SCHEMA, "requestId": request_id,
                           "payload": payload, "options": options}, ensure_ascii=True,
                          separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        if len(data) > MAX_REQUEST_BYTES:
            raise OcrEngineError("invalid_crop_set", "OCR worker request is too large")
        with self._guard:
            if self._closed:
                raise OcrEngineError("ocr_engine_unavailable", "OCR worker pool is closed")
            slot = self._slots.setdefault(spec.engine, _Slot())
        if not slot.lock.acquire(timeout=_remaining(deadline)):
            # This request does not own the busy child and must not terminate it.
            raise OcrEngineError("ocr_engine_timeout", f"{spec.engine} worker queue timed out")
        try:
            with self._guard:
                if self._closed:
                    raise OcrEngineError("ocr_engine_unavailable", "OCR worker pool is closed")
                if slot.child is not None and slot.key != key:
                    slot.child.close()
                    slot.child = None
                if slot.child is None:
                    try:
                        slot.child = _Child([str(spec.python_path.resolve()), "-B",
                                             str(spec.script_path.resolve()), *spec.arguments,
                                             "--serve-jsonl"], environment)
                    except OSError as error:
                        raise OcrEngineError("ocr_engine_unavailable", "OCR worker could not start") from error
                    slot.key = key
                child = slot.child
            line = child.exchange(data, deadline)
            try:
                envelope = json.loads(line.decode("utf-8"), object_pairs_hook=_strict_object,
                                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (ValueError, UnicodeError) as error:
                raise OcrEngineError("invalid_worker_response", "OCR worker returned invalid JSON") from error
            if (not isinstance(envelope, dict) or set(envelope) != {"schema", "requestId", "response"}
                    or envelope.get("schema") != TRANSPORT_SCHEMA or envelope.get("requestId") != request_id):
                raise OcrEngineError("invalid_worker_response", "OCR worker response identity is invalid")
            response = envelope.get("response")
            if not isinstance(response, dict) or response.get("engine") != spec.engine:
                raise OcrEngineError("invalid_worker_response", "OCR worker response contract is invalid")
            if response.get("ok") is not True:
                raise OcrEngineError("ocr_engine_failed", f"{spec.engine} worker failed")
            items = response.get("items")
            expected = {crop.question_no for crop in crops}
            if (not isinstance(items, list) or len(items) != len(crops)
                    or any(not isinstance(item, dict) or type(item.get("questionNo")) is not int for item in items)
                    or {item["questionNo"] for item in items} != expected):
                raise OcrEngineError("invalid_worker_response", "OCR worker question coverage is invalid")
            try:
                unchanged = _model_signatures(environment) == model_signatures
            except OSError:
                unchanged = False
            if not unchanged:
                raise OcrEngineError("ocr_engine_unavailable", "OCR model files changed during the request")
            response["wallSeconds"] = round(time.perf_counter() - started, 4)
            return response
        except Exception:
            if slot.child is not None:
                slot.child.close()
                slot.child = None
                slot.key = None
            raise
        finally:
            slot.lock.release()

    def shutdown(self) -> None:
        with self._guard:
            if self._closed:
                return
            self._closed = True
            children = [slot.child for slot in self._slots.values() if slot.child is not None]
        for child in children:
            child.close()
