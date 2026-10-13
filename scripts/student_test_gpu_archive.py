"""Additive GPU artifact transport: verified ZIP, 80 MiB parts and safe extraction."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
import zipfile

CHUNK = 1024 * 1024
PART_BYTES = 80 * CHUNK


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def safe_name(name):
    parts = name.rstrip("/").split("/")
    if (not name or "\\" in name or PurePosixPath(name).is_absolute() or PureWindowsPath(name).drive
            or any(part in {"", ".", ".."} or part.endswith((".", " ")) or any(c in part for c in ':<>"|?*')
                   or any(ord(c) < 32 for c in part)
                   or part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)]}
                   for part in parts)):
        raise ValueError(f"unsafe archive path: {name!r}")
    return "/".join(parts)


def inventory(zipper):
    seen, regular = set(), set()
    total = 0
    for info in zipper.infolist():
        name = safe_name(info.filename).casefold()
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if name in seen or kind not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1:
            raise ValueError("duplicate, link, special or encrypted ZIP entry")
        seen.add(name)
        if not info.is_dir():
            regular.add(name)
        total += info.file_size
    for name in seen:
        if any("/".join(name.split("/")[:n]) in regular for n in range(1, len(name.split("/")))):
            raise ValueError("file/directory destination collision")
    if len(seen) > 100000 or total > 30 * 1024**3:
        raise ValueError("archive extraction limit exceeded")
    return total


def pack(source, archive):
    source, archive = Path(source).resolve(), Path(archive).resolve()
    if not source.is_dir() or archive.exists() or archive.is_relative_to(source):
        raise ValueError("new archive outside source required")
    paths = sorted(source.rglob("*"))
    for path in paths:
        metadata = path.lstat()
        if path.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400 or not path.resolve().is_relative_to(source):
            raise ValueError("linked source is not allowed")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipper:
        for path in paths:
            if path.is_file():
                zipper.write(path, safe_name(path.relative_to(source).as_posix()))
    with zipfile.ZipFile(archive) as zipper:
        inventory(zipper)
        if zipper.testzip() is not None:
            raise ValueError("ZIP CRC failed")
        for info in zipper.infolist():
            digest = hashlib.sha256()
            with zipper.open(info) as stream:
                for chunk in iter(lambda: stream.read(CHUNK), b""):
                    digest.update(chunk)
            if digest.hexdigest() != sha256(source / info.filename):
                raise ValueError("archive/source byte mismatch")
    receipt = {"name": archive.name, "bytes": archive.stat().st_size, "sha256": sha256(archive),
               "files": sum(p.is_file() for p in paths), "archiveVerified": True}
    json_new(archive.with_suffix(archive.suffix + ".receipt.json"), receipt)
    return receipt


def split(archive, output, part_bytes=PART_BYTES):
    archive, output = Path(archive).resolve(), Path(output).resolve()
    if not archive.is_file() or output.exists() or part_bytes < 1 or part_bytes > PART_BYTES:
        raise ValueError("new parts directory and <=80 MiB parts required")
    before = sha256(archive)
    output.mkdir(parents=True, exist_ok=False)
    parts = []
    with archive.open("rb") as stream:
        index = 1
        while True:
            chunk = stream.read(min(CHUNK, part_bytes))
            if not chunk:
                break
            path = output / f"{archive.name}.part{index:03d}"
            with path.open("xb") as part:
                part.write(chunk)
                left = part_bytes - len(chunk)
                while left:
                    chunk = stream.read(min(CHUNK, left))
                    if not chunk:
                        break
                    part.write(chunk)
                    left -= len(chunk)
            parts.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
            index += 1
    if sha256(archive) != before:
        raise ValueError("archive changed during split")
    manifest = {"schema": "student_test_gpu_archive_parts_v1", "archiveName": archive.name,
                "bytes": archive.stat().st_size, "sha256": before, "partBytesLimit": part_bytes, "parts": parts}
    json_new(output / "ARCHIVE_PARTS.json", manifest)
    return manifest


def join(manifest_path, output):
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if output.exists() or manifest.get("schema") != "student_test_gpu_archive_parts_v1" or not manifest.get("parts"):
        raise ValueError("valid parts manifest and new output required")
    seen = set()
    for row in manifest["parts"]:
        name = safe_name(row["name"])
        path = manifest_path.parent / name
        if "/" in name or name.casefold() in seen or path.is_symlink() or not path.resolve().is_relative_to(manifest_path.parent):
            raise ValueError("unsafe or duplicate part")
        seen.add(name.casefold())
        if path.stat().st_size != row["bytes"] or sha256(path) != row["sha256"]:
            raise ValueError("part verification failed")
    if sum(row["bytes"] for row in manifest["parts"]) != manifest["bytes"]:
        raise ValueError("part size sum mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        for row in manifest["parts"]:
            with (manifest_path.parent / row["name"]).open("rb") as source:
                shutil.copyfileobj(source, destination, CHUNK)
    if output.stat().st_size != manifest["bytes"] or sha256(output) != manifest["sha256"]:
        raise ValueError("reassembled archive verification failed; do not use")
    return {"archive": str(output), "sha256": manifest["sha256"], "verified": True}


def extract(archive, output, expected_bytes, expected_sha256):
    archive, output = Path(archive).resolve(), Path(output).resolve()
    if output.exists() or archive.stat().st_size != expected_bytes or sha256(archive) != expected_sha256:
        raise ValueError("ZIP verification failed or output already exists")
    with zipfile.ZipFile(archive) as zipper:
        total = inventory(zipper)
        parent = output.parent
        while not parent.exists():
            parent = parent.parent
        if shutil.disk_usage(parent).free < total + CHUNK:
            raise ValueError("insufficient extraction space")
        output.mkdir(parents=True, exist_ok=False)
        for info in zipper.infolist():
            target = output / safe_name(info.filename)
            if not target.resolve().is_relative_to(output):
                raise ValueError("destination escaped output")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipper.open(info) as source, target.open("xb") as destination:
                    shutil.copyfileobj(source, destination, CHUNK)
    return {"output": str(output), "uncompressedBytes": total, "verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("pack"); p.add_argument("--source", required=True); p.add_argument("--archive", required=True)
    p = commands.add_parser("split"); p.add_argument("--archive", required=True); p.add_argument("--output", required=True)
    p = commands.add_parser("join"); p.add_argument("--manifest", required=True); p.add_argument("--output", required=True)
    p = commands.add_parser("extract"); p.add_argument("--archive", required=True); p.add_argument("--output", required=True)
    p.add_argument("--bytes", type=int, required=True); p.add_argument("--sha256", required=True)
    args = parser.parse_args()
    if args.command == "pack": result = pack(args.source, args.archive)
    elif args.command == "split": result = split(args.archive, args.output)
    elif args.command == "join": result = join(args.manifest, args.output)
    else: result = extract(args.archive, args.output, args.bytes, args.sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2))
