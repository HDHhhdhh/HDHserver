"""Read-only integrity contract shared by formula config generation and preflight."""
from __future__ import annotations

import hashlib
from pathlib import Path


def dataset_signature(root: Path) -> dict:
    root = root.resolve()
    annotation = root / "equations.txt"
    equations = annotation.read_text(encoding="utf-8").splitlines()
    if not equations or any(not line.strip() for line in equations):
        raise ValueError("formula equations must be nonempty, one per image")
    files = sorted((root / "images").glob("*.png"))
    expected = [f"{index:07d}.png" for index in range(len(equations))]
    if [path.name for path in files] != expected or any(not path.is_file() or path.stat().st_size == 0 for path in files):
        raise ValueError("formula image coverage does not match equations")
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("ascii") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {"count": len(equations), "annotationSha256": hashlib.sha256(annotation.read_bytes()).hexdigest(),
            "imagesSha256": digest.hexdigest()}
