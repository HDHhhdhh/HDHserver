#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

"""Generate VAPID P-256 files through the installed cryptography provider."""

from __future__ import annotations

import argparse
import base64
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_push_sender import (
    StudentPushConfigurationError,
    StudentPushDependencyError,
    validate_private_key_path,
    validate_public_output_path,
)


@dataclass(frozen=True, slots=True)
class VapidGenerationResult:
    private_path: Path
    public_output: Path
    public_key: str


class VapidGeneratorError(Exception):
    """Expected, user-actionable generator failure."""


class VapidProviderUnavailable(VapidGeneratorError):
    """The vetted provider needed for P-256 generation is not installed."""


class VapidDestinationExists(VapidGeneratorError):
    """One of the requested output paths already exists."""


def _write_exclusive(path: Path, data: bytes, mode: int) -> None:
    """Create one destination without ever replacing an existing file."""

    descriptor: int | None = None
    created = False
    completed = False
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        created = True
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, mode)
        completed = True
    except FileExistsError as exc:
        raise VapidDestinationExists("refusing to overwrite an existing VAPID destination") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created and not completed:
            path.unlink(missing_ok=True)


def _refuse_existing(path: Path) -> None:
    if os.path.lexists(path):
        raise VapidDestinationExists("refusing to overwrite an existing VAPID destination")


def generate_key_pair(private_path: Path | str, public_output: Path | str) -> VapidGenerationResult:
    """Create a private PEM and public key text file exactly once."""

    private = validate_private_key_path(private_path)
    public = validate_public_output_path(public_output)
    if private == public:
        raise VapidGeneratorError("private and public destinations must differ")
    _refuse_existing(private)
    _refuse_existing(public)
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ModuleNotFoundError as exc:
        raise VapidProviderUnavailable("cryptography is required; install the student-app dependency set first") from exc
    try:
        key = ec.generate_private_key(ec.SECP256R1())
        private_bytes = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
        public_bytes = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    except (TypeError, ValueError) as exc:
        raise VapidGeneratorError("cryptography provider rejected P-256 generation") from exc
    public_key = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("ascii")
    private.parent.mkdir(parents=True, exist_ok=True)
    public.parent.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        _write_exclusive(private, private_bytes, 0o600)
        created.append(private)
        _write_exclusive(public, (public_key + "\n").encode("ascii"), 0o644)
        created.append(public)
    except (OSError, VapidGeneratorError):
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return VapidGenerationResult(private_path=private, public_output=public, public_key=public_key)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create non-overwriting VAPID key files")
    parser.add_argument("--private-path", required=True, type=Path)
    parser.add_argument("--public-output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the generator CLI; stdout contains only the public key on success."""

    args = _parser().parse_args(argv)
    try:
        result = generate_key_pair(args.private_path, args.public_output)
    except (VapidGeneratorError, StudentPushConfigurationError, StudentPushDependencyError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(result.public_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
