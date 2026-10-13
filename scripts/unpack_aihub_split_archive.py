from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tarfile
import zipfile
from pathlib import Path


PART_PATTERN = re.compile(r"^(?P<base>.+\.zip)\.part(?P<offset>\d+)$", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely extract a direct AI Hub zip, or reassemble .zip.part<offset> members from a tar."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path)
    source.add_argument("--direct-zip", dest="direct_zip", type=Path)
    parser.add_argument("--zip", dest="zip_path", type=Path)
    parser.add_argument("--extract", dest="extract_root", type=Path, required=True)
    args = parser.parse_args()
    if args.archive is not None and args.zip_path is None:
        parser.error("--zip is required with --archive")
    if args.direct_zip is not None and args.zip_path is not None:
        parser.error("--zip cannot be used with --direct-zip")
    return args


def _validated_parts(archive: tarfile.TarFile) -> tuple[str, list[tuple[int, tarfile.TarInfo]]]:
    parsed: list[tuple[str, int, tarfile.TarInfo]] = []
    for member in archive.getmembers():
        if not member.isfile():
            continue
        match = PART_PATTERN.match(member.name.replace("\\", "/"))
        if match is None:
            raise ValueError("AI Hub tar contains an unexpected file member")
        parsed.append((Path(match.group("base")).name, int(match.group("offset")), member))
    if not parsed:
        raise ValueError("AI Hub tar contains no zip parts")
    base_names = {base.casefold() for base, _offset, _member in parsed}
    if len(base_names) != 1:
        raise ValueError("AI Hub tar mixes multiple zip archives")
    parts = sorted((offset, member) for _base, offset, member in parsed)
    expected_offset = 0
    for offset, member in parts:
        if offset != expected_offset or member.size <= 0:
            raise ValueError("AI Hub zip parts are missing, overlapping, or empty")
        expected_offset += member.size
    return parsed[0][0], parts


def _safe_zip_target(root: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("//"):
        raise ValueError("AI Hub zip member escapes the extraction root")
    normalized = normalized.lstrip("/")
    relative = Path(normalized)
    if not normalized or relative.is_absolute() or ".." in relative.parts or (relative.parts and ":" in relative.parts[0]):
        raise ValueError("AI Hub zip member escapes the extraction root")
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("AI Hub zip member escapes the extraction root")
    return target


def _extract_zip(*, zip_path: Path, extract_root: Path) -> dict:
    extracted_files = 0
    extracted_bytes = 0
    reused_extracted_files = 0
    written_files = 0
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = _safe_zip_target(extract_root, member.filename)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            partial_target = target.with_name(target.name + ".partial")
            if target.is_file():
                if target.stat().st_size != member.file_size:
                    raise ValueError("existing AI Hub extraction target size is invalid")
                reused_extracted_files += 1
                extracted_files += 1
                extracted_bytes += member.file_size
                continue
            if target.exists():
                raise ValueError("existing AI Hub extraction target has an invalid type")
            partial_target.unlink(missing_ok=True)
            with archive.open(member) as source, partial_target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
            if partial_target.stat().st_size != member.file_size:
                raise ValueError("AI Hub extracted member size is invalid")
            os.replace(partial_target, target)
            extracted_files += 1
            extracted_bytes += member.file_size
            written_files += 1
    return {
        "extractedFiles": extracted_files,
        "extractedBytes": extracted_bytes,
        "reusedExtractedFiles": reused_extracted_files,
        "writtenFiles": written_files,
    }


def extract_direct_zip(*, zip_path: Path, extract_root: Path) -> dict:
    zip_path = zip_path.resolve()
    extract_root = extract_root.resolve()
    if not zip_path.is_file():
        raise ValueError("AI Hub direct zip does not exist")
    extract_root.mkdir(parents=True, exist_ok=True)
    extracted = _extract_zip(zip_path=zip_path, extract_root=extract_root)
    return {
        "schema": "aihub_direct_zip_unpack_v1",
        "archive": str(zip_path),
        "embeddedZip": zip_path.name,
        "partCount": 1,
        "zipBytes": zip_path.stat().st_size,
        "reusedZip": True,
        **extracted,
        "extractRoot": str(extract_root),
    }


def reassemble_and_extract(*, archive_path: Path, zip_path: Path, extract_root: Path) -> dict:
    archive_path = archive_path.resolve()
    zip_path = zip_path.resolve()
    extract_root = extract_root.resolve()
    if not archive_path.is_file():
        raise ValueError("AI Hub tar archive does not exist")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    extract_root.mkdir(parents=True, exist_ok=True)
    partial_zip = zip_path.with_name(zip_path.name + ".partial")
    if partial_zip.exists():
        raise ValueError("AI Hub reconstructed zip partial already exists")
    reused_zip = zip_path.is_file()
    with tarfile.open(archive_path, mode="r:*") as archive:
        embedded_name, parts = _validated_parts(archive)
        expected_size = sum(member.size for _offset, member in parts)
        if reused_zip:
            if zip_path.stat().st_size != expected_size:
                raise ValueError("existing AI Hub reconstructed zip size is invalid")
        else:
            with partial_zip.open("xb") as output:
                for _offset, member in parts:
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError("AI Hub zip part could not be read")
                    with source:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
    if not reused_zip:
        if partial_zip.stat().st_size != expected_size:
            raise ValueError("AI Hub reconstructed zip size is invalid")
        os.replace(partial_zip, zip_path)

    extracted = _extract_zip(zip_path=zip_path, extract_root=extract_root)
    return {
        "schema": "aihub_split_archive_unpack_v1",
        "archive": str(archive_path),
        "embeddedZip": embedded_name,
        "partCount": len(parts),
        "zipBytes": expected_size,
        "reusedZip": reused_zip,
        **extracted,
        "extractRoot": str(extract_root),
    }


def main() -> int:
    args = parse_args()
    if args.direct_zip is not None:
        summary = extract_direct_zip(
            zip_path=args.direct_zip,
            extract_root=args.extract_root,
        )
    else:
        summary = reassemble_and_extract(
            archive_path=args.archive,
            zip_path=args.zip_path,
            extract_root=args.extract_root,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
