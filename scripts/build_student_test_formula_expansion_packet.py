"""Snapshot verified public data/code into a new GPU packet, without model weights."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from scripts.build_student_test_free_gpu_packet import SOURCES
from scripts.student_test_gpu_archive import json_new, pack, sha256, split, PART_BYTES
from scripts.prepare_student_test_formula_expansion import verify_frozen

ROOT = Path(__file__).resolve().parents[1]
EXTRA_SOURCES = (
    "scripts/student_test_formula_expansion_selection.py", "scripts/prepare_student_test_formula_expansion.py",
    "scripts/verify_student_test_formula_expansion.py", "scripts/student_test_gpu_archive.py",
    "scripts/verify_student_test_gpu_archive.py",
)
MODEL_FILES = ("config.json", "preprocessor_config.json", "tokenizer_config.json", "tokenizer.json")
BASE_SHA256 = "6f7608624e2d7549c7f0f05fcfbe073ae521328cf70f1d46374d96f9881d7371"


def write_delivery(receipt_path, package_url, folder_url, helper_url, output, part_urls=None):
    """Render the complete prompt only after Drive returns real upload links."""
    import re
    receipt_path, output = Path(receipt_path), Path(output)
    if output.exists() or output.with_suffix(".manifest.json").exists():
        raise ValueError("new delivery destinations required")
    if not all(re.fullmatch(r"https://drive\.google\.com/(?:file/d|drive/folders)/[A-Za-z0-9_-]+(?:/view\?usp=drivesdk)?", value)
               for value in (package_url, folder_url, helper_url)):
        raise ValueError("actual canonical Drive links required")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    archive = receipt_path.parent / receipt["name"]
    helper = ROOT / "scripts" / "student_test_gpu_archive.py"
    instructions = ROOT / "docs" / "STUDENT_TEST_FORMULA_EXPANSION_GPU_INSTRUCTIONS.md"
    if archive.stat().st_size != receipt["bytes"] or sha256(archive) != receipt["sha256"]:
        raise ValueError("delivery archive changed")
    parts_header = ""
    parts_manifest = None
    if part_urls:
        parts_path = receipt_path.parent / "input_parts" / "ARCHIVE_PARTS.json"
        parts_manifest = json.loads(parts_path.read_text(encoding="utf-8"))
        if len(part_urls) != len(parts_manifest["parts"]) or parts_manifest["sha256"] != receipt["sha256"]:
            raise ValueError("parts/link coverage mismatch")
        parts_header = f"- ARCHIVE_PARTS.json 크기: {parts_path.stat().st_size} bytes\n- ARCHIVE_PARTS.json SHA-256: {sha256(parts_path)}\n"
        for row, url in zip(parts_manifest["parts"], part_urls):
            if not re.fullmatch(r"https://drive\.google\.com/file/d/[A-Za-z0-9_-]+/view\?usp=drivesdk", url):
                raise ValueError("actual part Drive link required")
            parts_header += f"- {row['name']}: {url}\n  크기 {row['bytes']} bytes / SHA-256 {row['sha256']}\n"
    header = f"""아래 작업을 이 NVIDIA GPU 컴퓨터에서 수행해 주세요. 파일 검증 후 학습·평가·결과 업로드까지 승인된 범위대로 진행하세요.

전달 표 (실제 업로드 링크):
- 작업 및 결과 반환 Drive 폴더: {folder_url}
- {'입력 parts manifest (ARCHIVE_PARTS.json)' if part_urls else '입력 원본 ZIP'}: {package_url}
- 입력 파일명: {receipt['name']}
- 입력 크기: {receipt['bytes']} bytes
- 입력 SHA-256: {receipt['sha256']}
- ZIP 실제 일반 파일 수: {receipt['files']} (PACKET_MANIFEST.json 자신 포함)
- 독립 안전 추출/분할/재조립 helper: {helper_url}
- helper 파일명: student_test_gpu_archive_80MiB.py (패키지 안의 scripts/student_test_gpu_archive.py와 같은 코드)
- helper 크기: {helper.stat().st_size} bytes
- helper SHA-256: {sha256(helper)}
{parts_header}

ZIP에는 실제 학습/검증 이미지·전사·provenance·코드·모델 설정이 있습니다. 모델 weight와 가상환경은 미포함이며, 기존 GPU 컴퓨터의 동일 pretrained weight와 CUDA 환경을 검증해 재사용합니다. GPU 여유 공간은 최소 60 GiB입니다. 유료 API/외부 OCR 예산은 0이고 운영 모델·서비스는 변경하지 않습니다.

"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(header + instructions.read_text(encoding="utf-8"))
    manifest = {"schema": "student_test_formula_expansion_delivery_v1", "createdAt": datetime.now(timezone.utc).isoformat(),
        "folderUrl": folder_url, "packageUrl": package_url, "helperUrl": helper_url, "partUrls": part_urls,
        "partsManifest": parts_manifest,
        "archive": {**receipt, "localPath": str(archive)},
        "helper": {"bytes": helper.stat().st_size, "sha256": sha256(helper)},
        "prompt": {"localPath": str(output), "bytes": output.stat().st_size, "sha256": sha256(output)},
        "instructionsSha256": sha256(instructions), "trainingExecuted": False, "providerCallCount": 0, "deploymentReady": False}
    json_new(output.with_suffix(".manifest.json"), manifest)
    return manifest


def build(data, packet, archive, model_dir):
    data, packet, archive, model_dir = (Path(p).resolve() for p in (data, packet, archive, model_dir))
    if packet.exists() or archive.exists() or packet.is_relative_to(data) or archive.is_relative_to(packet):
        raise ValueError("packet and archive must be new, independent destinations")
    inputs = json.loads((data / "EXPANSION_INPUTS.json").read_text(encoding="utf-8"))
    if inputs.get("trainingExecuted") is not False or inputs.get("providerCallCount") != 0:
        raise ValueError("preparation-only input contract failed")
    verify_frozen(data / "validation")
    base = model_dir / "unimernet_tiny.pth"
    if sha256(base) != BASE_SHA256:
        raise ValueError("local original base differs from fixed experiment prerequisite")
    shutil.copytree(data, packet / "data")
    for source in sorted(data.rglob("*")):
        if source.is_file() and sha256(source) != sha256(packet / "data" / source.relative_to(data)):
            raise ValueError("data snapshot mismatch")
    for name in (*SOURCES, *EXTRA_SOURCES):
        destination = packet / "code" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    model = {}
    (packet / "model").mkdir()
    for name in MODEL_FILES:
        shutil.copyfile(model_dir / name, packet / "model" / name)
        model[name] = {"bytes": (packet / "model" / name).stat().st_size, "sha256": sha256(packet / "model" / name)}
    shutil.copyfile(ROOT / "docs" / "STUDENT_TEST_FORMULA_EXPANSION_GPU_INSTRUCTIONS.md", packet / "GPU_INSTRUCTIONS.md")
    prerequisite = {"schema": "student_test_formula_expansion_prerequisites_v1", "baseWeightIncluded": False,
        "baseWeight": {"suggestedGpuPath": "C:/server-ocr/models/unimernet_tiny/unimernet_tiny.pth",
                       "bytes": base.stat().st_size, "sha256": BASE_SHA256}, "model": model,
        "environment": "existing NVIDIA CUDA UniMERNet environment; no installation or paid API authorized",
        "trainingExecuted": False, "deploymentReady": False, "providerCallCount": 0}
    json_new(packet / "PREREQUISITES.json", prerequisite)
    files = [{"path": p.relative_to(packet).as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p)}
             for p in sorted(packet.rglob("*")) if p.is_file()]
    json_new(packet / "PACKET_MANIFEST.json", {"schema": "student_test_formula_expansion_packet_v1",
        "createdAt": datetime.now(timezone.utc).isoformat(), "files": files, "fileCountExcludingManifest": len(files),
        "includesActualImagesAndTranscriptions": True, "includesStudentPhotos": False, "includesRuntimeDatabase": False,
        "includesModelWeights": False, "trainingExecuted": False, "providerCallCount": 0, "deploymentReady": False})
    receipt = pack(packet, archive)
    if receipt["bytes"] > PART_BYTES:
        receipt["partsManifest"] = str(archive.parent / "input_parts" / "ARCHIVE_PARTS.json")
        split(archive, archive.parent / "input_parts")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("data", "packet", "archive", "model-dir"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.data, args.packet, args.archive, args.model_dir), ensure_ascii=False, indent=2))
