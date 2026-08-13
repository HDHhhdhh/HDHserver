"""Network-free checks for VAPID key generation and rollback safety."""

from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
import types
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

from scripts import generate_student_vapid_key as generator


ROOT: Path = Path(__file__).resolve().parents[2]
_SCRIPT: Path = ROOT / "scripts" / "generate_student_vapid_key.py"

AssertionRecorder: TypeAlias = Callable[[bool, str], None]


def run_generator_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Bound generator subprocesses so a hung child cannot hang verification."""

    try:
        return subprocess.run(command, capture_output=True, text=True, check=False, timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError("generator command exceeded the 15-second safety bound") from exc


def run_generator_check(record: AssertionRecorder) -> str:
    """Exercise generation, non-overwrite, provider, and key-derivation cases."""

    with tempfile.TemporaryDirectory(prefix="student-vapid-check-") as temporary:
        folder = Path(temporary)
        private = folder / "nested" / "instance" / "vapid-private.pem"
        public = folder / "nested-out" / "vapid-public.txt"
        command = [sys.executable, str(_SCRIPT), "--private-path", str(private), "--public-output", str(public)]
        first = run_generator_command(command)
        occupied = folder / "occupied-public.txt"
        occupied.write_text("keep", encoding="ascii")
        occupied_command = [sys.executable, str(_SCRIPT), "--private-path", str(folder / "occupied-private.pem"), "--public-output", str(occupied)]
        occupied_result = run_generator_command(occupied_command)
        record(occupied_result.returncode == 2 and "overwrite" in occupied_result.stderr.lower(), "existing generator destination was not refused")
        record(occupied.read_text(encoding="ascii") == "keep", "existing generator destination was altered")
        provider_available = first.returncode == 0
        if not provider_available:
            record(first.returncode == 2, "missing crypto provider must fail with exit 2")
            record("cryptography" in first.stderr.lower(), "provider failure must be explicit")
            record(not private.exists() and not public.exists(), "provider failure must not create files")
            record(not private.parent.exists() and not public.parent.exists(), "provider failure must not create output directories")
            return "provider-unavailable"
        record(private.is_file() and public.is_file(), "generator did not create both files")
        public_text = public.read_text(encoding="ascii").strip()
        record(len(public_text) == 87 and "=" not in public_text, "public VAPID key encoding mismatch")
        from cryptography.hazmat.primitives import serialization
        parsed_key = serialization.load_pem_private_key(private.read_bytes(), password=None)
        derived = base64.urlsafe_b64encode(parsed_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).rstrip(b"=").decode("ascii")
        record(derived == public_text, "public VAPID key does not match private key")
        private_before = private.read_bytes()
        public_before = public.read_bytes()
        second = run_generator_command(command)
        record(second.returncode == 2, "second generator run must refuse overwrite")
        record(private.read_bytes() == private_before and public.read_bytes() == public_before, "refusal altered key files")
        return "provider-available"


def run_generator_rollback_check(record: AssertionRecorder) -> None:
    """Exercise second-destination rollback with a deterministic fake provider."""

    serialization = types.ModuleType("cryptography.hazmat.primitives.serialization")
    serialization.Encoding = types.SimpleNamespace(PEM="PEM", X962="X962")
    serialization.PrivateFormat = types.SimpleNamespace(TraditionalOpenSSL="traditional")
    serialization.PublicFormat = types.SimpleNamespace(UncompressedPoint="uncompressed")
    serialization.NoEncryption = lambda: "no-encryption"
    ec = types.ModuleType("cryptography.hazmat.primitives.asymmetric.ec")
    curve = object()

    class FakePublicKey:
        def public_bytes(self, *_args: str) -> bytes:
            return b"\x04" + b"\x01" * 64

    class FakePrivateKey:
        def private_bytes(self, *_args: str) -> bytes:
            return b"fixture-private-pem"

        def public_key(self) -> FakePublicKey:
            return FakePublicKey()

    ec.SECP256R1 = lambda: curve
    ec.generate_private_key = lambda _curve: FakePrivateKey()
    primitives = types.ModuleType("cryptography.hazmat.primitives")
    primitives.serialization = serialization
    asymmetric = types.ModuleType("cryptography.hazmat.primitives.asymmetric")
    asymmetric.ec = ec
    cryptography = types.ModuleType("cryptography")
    hazmat = types.ModuleType("cryptography.hazmat")
    hazmat.primitives = primitives
    module_map = {
        "cryptography": cryptography,
        "cryptography.hazmat": hazmat,
        "cryptography.hazmat.primitives": primitives,
        "cryptography.hazmat.primitives.serialization": serialization,
        "cryptography.hazmat.primitives.asymmetric": asymmetric,
        "cryptography.hazmat.primitives.asymmetric.ec": ec,
    }
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in module_map}
    sys.modules.update(module_map)
    original_write = generator._write_exclusive
    calls = [0]

    def fail_second(path: Path, data: bytes, mode: int) -> None:
        calls[0] += 1
        if calls[0] == 2:
            raise OSError("simulated second destination failure")
        original_write(path, data, mode)

    generator._write_exclusive = fail_second
    try:
        with tempfile.TemporaryDirectory(prefix="student-vapid-rollback-") as temporary:
            folder = Path(temporary)
            private = folder / "instance" / "private.pem"
            public = folder / "instance" / "public.txt"
            try:
                generator.generate_key_pair(private, public)
            except OSError as exc:
                if str(exc) != "simulated second destination failure":
                    raise AssertionError("generator surfaced an unexpected rollback failure") from exc
            else:
                raise AssertionError("generator did not surface the simulated second-destination failure")
            record(not private.exists() and not public.exists(), "generator rollback left a partial key file")
    finally:
        generator._write_exclusive = original_write
        for name, previous_module in previous.items():
            if previous_module is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous_module
