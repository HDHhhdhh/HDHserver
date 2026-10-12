from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final


RESULT_PREFIX: Final[str] = "TEXTELLER_RESULT_JSON:"
SCHEMA_VERSION: Final[str] = "phase2g_texteller_worker_v1"
MODEL_NAME: Final[str] = "OleehyO/TexTeller"
MAX_REQUEST_BYTES: Final[int] = 128 * 1024
MAX_IMAGE_COUNT: Final[int] = 20


class WorkerInputError(ValueError):
    pass


def _positive_int(value: Any, label: str, maximum: int) -> int:
    if isinstance(value, bool):
        raise WorkerInputError(f"{label}_invalid")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise WorkerInputError(f"{label}_invalid") from exc
    if parsed < 1 or parsed > maximum:
        raise WorkerInputError(f"{label}_invalid")
    return parsed


def _read_request() -> tuple[list[tuple[int, Path]], Path, int, int, int]:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        raise WorkerInputError("request_size_invalid")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerInputError("request_json_invalid") from exc
    if not isinstance(payload, dict):
        raise WorkerInputError("request_root_invalid")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= MAX_IMAGE_COUNT:
        raise WorkerInputError("request_items_invalid")
    items: list[tuple[int, Path]] = []
    seen: set[int] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise WorkerInputError("request_item_invalid")
        question_no = _positive_int(raw_item.get("question_no"), "question_no", MAX_IMAGE_COUNT)
        image_path = raw_item.get("image_path")
        if not isinstance(image_path, str) or not image_path.strip():
            raise WorkerInputError("image_path_invalid")
        path = Path(image_path).resolve()
        if question_no in seen or not path.is_file() or path.suffix.lower() != ".png":
            raise WorkerInputError("request_item_invalid")
        seen.add(question_no)
        items.append((question_no, path))

    hf_home_raw = payload.get("hf_home")
    if not isinstance(hf_home_raw, str) or not hf_home_raw.strip():
        raise WorkerInputError("hf_home_invalid")
    hf_home = Path(hf_home_raw).resolve()
    if not hf_home.is_dir():
        raise WorkerInputError("hf_home_unavailable")
    batch_size = _positive_int(payload.get("batch_size", 4), "batch_size", 20)
    max_tokens = _positive_int(payload.get("max_tokens", 64), "max_tokens", 128)
    cpu_threads = _positive_int(payload.get("cpu_threads", 6), "cpu_threads", 32)
    return items, hf_home, batch_size, max_tokens, cpu_threads


def _single_line(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "?"
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:512]


def _recognize(
    items: list[tuple[int, Path]],
    hf_home: Path,
    batch_size: int,
    max_tokens: int,
    cpu_threads: int,
) -> list[dict[str, Any]]:
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

    import torch
    from texteller import img2latex, load_model, load_tokenizer

    torch.set_num_threads(cpu_threads)
    model = load_model(use_onnx=False)
    tokenizer = load_tokenizer()
    model.eval()
    device = torch.device("cpu")

    outputs: list[str] = []
    with torch.inference_mode():
        for start in range(0, len(items), batch_size):
            batch = [str(path) for _, path in items[start : start + batch_size]]
            outputs.extend(
                img2latex(
                    model,
                    tokenizer,
                    batch,
                    device=device,
                    out_format="latex",
                    keep_style=False,
                    max_tokens=max_tokens,
                    num_beams=1,
                )
            )
    if len(outputs) != len(items):
        raise RuntimeError("output_count_mismatch")
    return [
        {"question_no": question_no, "raw_latex": _single_line(output)}
        for (question_no, _), output in zip(items, outputs, strict=True)
    ]


def _emit(payload: dict[str, Any]) -> None:
    print(f"{RESULT_PREFIX}{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}")


def main() -> int:
    try:
        items, hf_home, batch_size, max_tokens, cpu_threads = _read_request()
        recognized = _recognize(
            items,
            hf_home,
            batch_size,
            max_tokens,
            cpu_threads,
        )
    except WorkerInputError as exc:
        _emit({"ok": False, "schema_version": SCHEMA_VERSION, "error_code": str(exc)})
        return 2
    except (ImportError, ModuleNotFoundError):
        _emit({"ok": False, "schema_version": SCHEMA_VERSION, "error_code": "runtime_unavailable"})
        return 3
    except (OSError, RuntimeError, ValueError):
        _emit({"ok": False, "schema_version": SCHEMA_VERSION, "error_code": "inference_failed"})
        return 4

    _emit(
        {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "model": MODEL_NAME,
            "provider_call_count": 0,
            "items": recognized,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
