"""Strict JSONL transport for local OCR scripts; prediction code stays in each worker."""
from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from typing import Callable

TRANSPORT_SCHEMA = "student_test_ocr_worker_transport_v1"
MAX_REQUEST_BYTES = 100_000


def _reject_constant(value: str):
    raise ValueError(f"invalid JSON constant: {value}")


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def serve(*, engine: str, parse_request: Callable, run: Callable,
          close_runtime: Callable | None = None) -> int:
    try:
        while True:
            line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            if not line:
                return 0
            request_id = ""
            try:
                if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
                    raise ValueError("worker request exceeds its framing limit")
                envelope = json.loads(line.decode("utf-8"), object_pairs_hook=_strict_object,
                                      parse_constant=_reject_constant)
                if not isinstance(envelope, dict) or set(envelope) != {"schema", "requestId", "payload", "options"}:
                    raise ValueError("invalid worker transport envelope")
                request_id = envelope.get("requestId")
                if (envelope.get("schema") != TRANSPORT_SCHEMA or not isinstance(request_id, str)
                        or len(request_id) != 32 or any(c not in "0123456789abcdef" for c in request_id)):
                    raise ValueError("invalid worker transport identity")
                options = envelope.get("options")
                if (not isinstance(options, dict) or set(options) != {"secondPass", "variantPass"}
                        or any(type(value) is not bool for value in options.values())
                        or (engine != "unimernet" and any(options.values()))):
                    raise ValueError("invalid worker request options")
                with redirect_stdout(sys.stderr):
                    items = parse_request(envelope["payload"])
                    result = run(items, options)
                response = {"ok": True, "engine": engine, "items": result}
                emitted = json.dumps({"schema": TRANSPORT_SCHEMA, "requestId": request_id,
                                      "response": response}, ensure_ascii=True,
                                     separators=(",", ":"), allow_nan=False)
                sys.stdout.write(emitted + "\n")
                sys.stdout.flush()
            except Exception as error:
                response = {"ok": False, "engine": engine, "error": type(error).__name__}
                sys.stdout.write(json.dumps({"schema": TRANSPORT_SCHEMA, "requestId": request_id,
                                            "response": response}, ensure_ascii=True,
                                           separators=(",", ":")) + "\n")
                sys.stdout.flush()
                print(f"{engine} resident worker failed: {error}", file=sys.stderr)
                return 1
    finally:
        if close_runtime is not None:
            with redirect_stdout(sys.stderr):
                close_runtime()
