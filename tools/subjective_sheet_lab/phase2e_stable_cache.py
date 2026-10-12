from __future__ import annotations

import hashlib
import os
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_PHASE2E_CACHE_ROOT: Final[Path] = Path(r"C:\server-ocr\phase2e_live_qa_cache")
PHASE2E_CACHE_ROOT_ENV: Final[str] = "OCR_PHASE2E_CACHE_ROOT"
PHASE2E_PROVIDER_MODEL_ENV: Final[str] = "OCR_PHASE2E_PROVIDER_MODEL"
PHASE2E_PROVIDER_PROMPT_VERSION_ENV: Final[str] = "OCR_PHASE2E_PROVIDER_PROMPT_VERSION"
DEFAULT_PHASE2E_PROVIDER_MODEL: Final[str] = "gemini-2.5-flash-lite"
DEFAULT_PHASE2E_PROVIDER_PROMPT_VERSION: Final[str] = "image_candidates_v2"
PNG_SIGNATURE: Final[bytes] = b"\x89PNG\r\n\x1a\n"
PNG_PROVIDER_CHUNKS: Final[frozenset[bytes]] = frozenset((b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"))
CONTACT_GROUPS: Final[tuple[tuple[int, int], ...]] = ((1, 5), (6, 10), (11, 15), (16, 20))


@dataclass(frozen=True, slots=True)
class StableOcrCacheRequest:
    sid: str
    test_id: str
    round_no: int
    source_image: Path
    cache_root: Path
    provider_model: str | None = None
    prompt_version: str | None = None
    deidentified_input_fingerprint: str | None = None
    form_id: str = "answer_sheet_20_v1"
    preprocessing_version: str = "crop_contact_v1"


def phase2e_cache_root(environ: Mapping[str, str] | None = None) -> Path:
    source = os.environ if environ is None else environ
    raw = source.get(PHASE2E_CACHE_ROOT_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_PHASE2E_CACHE_ROOT


def phase2e_provider_model(environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    return safe_provider_segment(source.get(PHASE2E_PROVIDER_MODEL_ENV, ""), DEFAULT_PHASE2E_PROVIDER_MODEL)


def phase2e_provider_prompt_version(environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    return safe_provider_segment(source.get(PHASE2E_PROVIDER_PROMPT_VERSION_ENV, ""), DEFAULT_PHASE2E_PROVIDER_PROMPT_VERSION)


def stable_recognized_path_or_none(request: StableOcrCacheRequest) -> Path | None:
    from tools.subjective_sheet_lab.ocr_run_identity import build_run_identity
    try:
        identity = build_run_identity(
            request.source_image.read_bytes(), test_id=request.test_id, round_no=request.round_no,
            form_id=request.form_id, model=request.provider_model or phase2e_provider_model(),
            prompt_version=request.prompt_version or phase2e_provider_prompt_version(),
            preprocessing_version=request.preprocessing_version)
    except (OSError, ValueError):
        return None
    sid_hash = hashlib.sha256(request.sid.encode("utf-8")).hexdigest()[:12]
    return request.cache_root / ("ocr_v1_"+sid_hash+"_"+identity["identity_sha256"]) / "recognized.json"


def deidentified_input_fingerprint_for_source(source_image: Path) -> str | None:
    contact_dir = source_image.parent.parent / "review_assets" / "contact_sheets"
    paths = tuple(sorted(contact_dir.glob("*.png"))) if contact_dir.is_dir() else ()
    return deidentified_contact_fingerprint(paths)


def deidentified_contact_fingerprint(paths: tuple[Path, ...]) -> str | None:
    if len(paths) != len(CONTACT_GROUPS):
        return None
    digest = hashlib.sha256()
    for (start, end), path in zip(CONTACT_GROUPS, paths, strict=True):
        try:
            normalized = deidentified_png_bytes(path)
        except OSError:
            return None
        digest.update(f"answer_sheet_q{start:03d}_q{end:03d}\n".encode("ascii"))
        digest.update(hashlib.sha256(normalized).digest())
    return digest.hexdigest()


def deidentified_png_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if not raw.startswith(PNG_SIGNATURE):
        raise OSError(f"provider contact sheet is not PNG: {path.name}")
    chunks: list[bytes] = []
    offset = len(PNG_SIGNATURE)
    saw_ihdr = False
    saw_idat = False
    saw_iend = False
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise OSError(f"provider contact sheet is truncated: {path.name}")
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(raw):
            raise OSError(f"provider contact sheet has an invalid chunk: {path.name}")
        kind = raw[offset + 4:offset + 8]
        chunk = raw[offset:end]
        offset = end
        if kind not in PNG_PROVIDER_CHUNKS:
            continue
        if kind == b"IHDR":
            saw_ihdr = True
        elif kind == b"IDAT":
            saw_idat = True
        elif kind == b"IEND":
            saw_iend = True
        chunks.append(chunk)
        if kind == b"IEND":
            break
    if not saw_ihdr or not saw_idat or not saw_iend:
        raise OSError(f"provider contact sheet is incomplete: {path.name}")
    return PNG_SIGNATURE + b"".join(chunks)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_cache_segment(value: str) -> str:
    chars = [char.lower() if char.isascii() and (char.isalnum() or char in {"-", "_"}) else "_" for char in value.strip()]
    slug = "_".join(part for part in "".join(chars).split("_") if part).strip("-_") or "case"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:40].strip('-_') or 'case'}_{digest}"


def safe_provider_segment(value: str, default: str) -> str:
    candidate = value.strip()
    if not candidate:
        return default
    if not all(char.isascii() and (char.isalnum() or char in {"-", "_", "."}) for char in candidate):
        return default
    return candidate[:80]
