"""Create a fresh collection kit using the unchanged v4 sheet; no images/model execution."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil

from scripts.student_test_camera_dataset import _ancestors, digest, encoded, fresh_directory

V4 = {
    "answer_sheet_v4.pdf": "d7dd5adc8440ede0de8a34c7ffaef1b3eeec4ddf9679b04fd7e93ef48f684fd3",
    "answer_sheet_v4_coordinates.json": "57fcb45eb4863080e09c19e2f2b932a3c4e5375b119e0d364a5137e05c7899a8",
    "answer_sheet_v4_warped_reference.png": "f86a0eabbbb398b8ff6c41a55d1d1a91e7938f910823fa8db25836b101abed0e",
}
# Writing instructions only. These values must never be copied into human transcription.
PROMPTS = [("choice_number", "integer", str(n)) for n in range(1, 6)] + [
    ("answer_value", "integer", "1"), ("answer_value", "integer", "3"),
    ("answer_value", "integer", "5"), ("answer_value", "integer", "0"),
    ("answer_value", "integer", "-7"), ("answer_value", "integer", "12"),
    ("answer_value", "fraction", "1/2"), ("answer_value", "fraction", "-3/4"),
    ("answer_value", "fraction", "7/3"), ("answer_value", "radical", "√2"),
    ("answer_value", "radical", "3√5"), ("answer_value", "radical", "-√7"),
    ("answer_value", "two_term", "1+√3"), ("answer_value", "two_term", "2-√5"),
    ("answer_value", "two_term", "(1+√2)/3"),
]

GUIDE = """실촬영 초기 진단 수집 · 24명 · 동일 종이 2회 촬영

1. 이용 동의·용도·보관 기간을 먼저 확인한다. 미성년자 자료의 승인 여부는 담당자가 확인한다.
   권한/보관 reference는 별도 기록의 식별자다. 이름·전화·SID를 이 키트에 적지 않는다.
2. 기존 v4 답안지를 사용한다. Name/Student ID는 비워 두고 W001 같은 가명만 별도 매핑한다.
   원본이 식별정보를 포함하면 공유하기 전에 비식별화한다. 얼굴·위치정보/EXIF도 확인한다.
3. writer_guides의 해당 작성 안내를 학생에게만 보여 준다. 20칸 모두 본인 필체로 쓴다.
   choice_number도 버블이 아니라 숫자를 적는다. answer_value의 1·3·5는 주관식 경로다.
   분수는 가로 분수선, 루트는 실제 루트 기호로 쓴다. OCR용으로 특별히 정서하도록 요구하지 않는다.
4. 같은 종이를 실시간 카메라로 두 번 촬영한다. 한 사진을 복사하거나 필터로 변형하지 않는다.
   '흔들림 없이 촬영해 주세요. 종이 네 모서리가 모두 보이게 해 주세요.'
   두 사진 사이에 종이의 답을 고치지 않는다. 오류·빈칸도 유지한다.
5. 승인된 담당자가 원본/20개 crop/변환 receipt를 정리한다. crop receipt에는 원본/템플릿/코드 SHA,
   문항별 crop SHA와 실제 좌표·변환을 기록한다. 해시만으로 기하학적 crop 정확성을 증명하지 않는다.
6. 독립 전사자는 crop만 보고 실제 보이는 필기를 읽는다. writer_guides·문제 정답키·모델 출력을
   보여 주지 않는다. intake 템플릿의 전사는 모두 빈칸이다. 안내 값에서 복사하지 않는다.
   readable/blank/ambiguous/unsupported를 기록한다. 알아볼 수 없는 답은 임의로 채우지 않는다.
   readable 전사가 두 촬영에서 다르면 사람이 원본을 재확인한다. 모델 출력에 맞춰 수정하지 않는다.
7. 같은 작성자는 학년/과목이 달라도 동일 global writerId를 쓴다. 종이·두 사진·crop·증강은 같은 split.
   기본 16명 development / 8명 calibration은 초기 진단용이다. 최종 release holdout은 새 작성자로
   나중에 별도 수집한다. 초기 진단을 독립 미사용 출시 검증이라고 부르지 않는다.
8. 승인·전사 완료 후 실제 파일 경로/SHA/사진 metadata로 INTAKE_TEMPLATE.json을 완성하고 freeze한다.
   FROZEN_LABELS는 평가자에게만, MODEL_INPUTS는 추론자에게만 준다. 정답 전사·안내 값은 OCR 입력에 없다.
   freeze 이후 모델 실행/임계값 보정을 시작한다. calibration 라벨로 학습하지 않는다.

이 키트에는 학생 사진/전사/새 checkpoint가 없다. 24명×20칸×2촬영=960 photo-slot이지만
독립 작성자는 24명이고 같은 종이의 실제 필기는 480칸이다. 사진 두 장을 독립 표본으로 세지 않는다.
따라 쓰는 초기 진단은 자연스러운 실제 시험 촬영과 다르다. 출시 검증은 새 작성자의 자연 필체로 한다.
운영 촬영 7일 삭제와 학습자료 유지 허가는 별개다. 수집용 자료의 보관 기간/재사용 권한을 확인하기 전
운영 crop을 학습에 복사하지 않는다. 이 도구는 운영 파일 삭제나 보관 변경을 수행하지 않는다.
"""


def prepare(template_dir: Path, output: Path, seed: int = 20261004) -> dict:
    _ancestors(template_dir)
    for name, sha in V4.items():
        path = template_dir / name
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400 or digest(path) != sha:
            raise ValueError("existing v4 template differs; do not substitute/regenerate it")
    fresh_directory(output)
    (output / "template").mkdir()
    for name in V4:
        shutil.copyfile(template_dir / name, output / "template" / name)
        if digest(output / "template" / name) != V4[name] or digest(template_dir / name) != V4[name]:
            raise ValueError("template changed during copy; no success manifest emitted")
    (output / "writer_guides").mkdir()
    roster, photos = [], []
    for number in range(1, 25):
        writer = f"W{number:03d}"
        if number <= 12:
            grade, course, split = "H_G1", "공통수학1", "development" if number <= 8 else "calibration"
        elif number <= 18:
            grade, course, split = "H_G2", "대수", "development" if number <= 16 else "calibration"
        else:
            grade, course, split = "H_G3", "미적분2", "development" if number <= 22 else "calibration"
        prompts = list(PROMPTS)
        random.Random(f"{seed}:{writer}").shuffle(prompts)
        guide = [f"{writer} 작성 안내 · 사진 두 장 모두 같은 종이 · 실제 grade/course는 담당자가 확인", "번호\t유형\t쓸 값"]
        for no, (mode, kind, value) in enumerate(prompts, 1):
            guide.append(f"{no:02d}\t{'객관식 숫자' if mode == 'choice_number' else '주관식 값'}\t{value}")
        (output / "writer_guides" / (writer + ".txt")).write_text("\n".join(guide) + "\n", encoding="utf-8")
        roster.append({"writerId": writer, "plannedGrade": grade, "plannedTestCourse": course, "split": split})
        for ordinal in (1, 2):
            photo = f"{writer}_A_P{ordinal}"
            photos.append({"writerId": writer, "sheetId": f"{writer}_A", "photoId": photo,
                "captureOrdinal": ordinal, "studentGrade": grade, "testCourse": course, "split": split,
                "original": {"path": f"photos/{photo}.jpg", "sha256": "FILL_ACTUAL_SHA256"},
                "cropReceipt": {"path": f"receipts/{photo}.json", "sha256": "FILL_ACTUAL_SHA256"},
                "questions": [{"questionNo": no, "answerMode": mode, "expressionKind": kind,
                    "legibility": "UNREVIEWED", "transcription": "",
                    "crop": {"path": f"crops/{photo}/{no:02d}.png", "sha256": "FILL_ACTUAL_SHA256"}}
                    for no, (mode, kind, _) in enumerate(prompts, 1)]})
    intake = {"schema": "student_test_camera_intake_v1", "permissions": {"confirmed": False,
        "deidentified": False, "reference": "", "retentionReference": ""},
        "review": {"reviewerId": "REVIEWER", "actualHandwriting": False, "blindTo": [], "completedAt": ""},
        "template": {key: {"path": "template/" + name, "sha256": V4[name]} for key, name in (
            ("pdf", "answer_sheet_v4.pdf"), ("coordinates", "answer_sheet_v4_coordinates.json"),
            ("warpedReference", "answer_sheet_v4_warped_reference.png"))}, "photos": photos}
    (output / "INTAKE_TEMPLATE.json").write_bytes(encoded(intake))
    (output / "ROSTER.json").write_bytes(encoded(roster))
    (output / "COLLECTION_GUIDE_KO.txt").write_text(GUIDE, encoding="utf-8")
    (output / "CROP_RECEIPT_TEMPLATE.json").write_bytes(encoded({"schema": "student_test_camera_crop_receipt_v1",
        "parentPhotoSha256": "FILL_ACTUAL_SHA256", "templateCoordinatesSha256": V4["answer_sheet_v4_coordinates.json"],
        "cropperCodeSha256": "FILL_ACTUAL_SHA256", "questions": [{"questionNo": n,
            "cropSha256": "FILL_ACTUAL_SHA256", "transform": {"FILL_ACTUAL_COORDINATES_AND_HOMOGRAPHY": None}} for n in range(1, 21)]}))
    plan = {"schema": "student_test_camera_experiment_plan_v1", "seed": seed,
        "firstContrast": "same_public_focused_pool: camera_augmentation_off_vs_on",
        "fixedFactors": ["initial checkpoint SHA", "architecture/tokenizer SHA", "source labels/count/writers",
            "seed", "batch4/accum2", "microbatch budget", "optimizer/LR", "checkpoint selection", "64-token decoder", "acceptance policy"],
        "publicSource": "generated/free_ocr_expansion_20260907_02/data/training/focused",
        "publicSourceCounts": {"m3_h1": 967, "m3_h1_h2_h3": 1757},
        "publicDevelopmentValidation": {"m3_h1": {"crops": 1459, "gradeScopedWriterHashes": 3},
            "m3_h1_h2_h3": {"crops": 1473, "gradeScopedWriterHashes": 6, "H_G2_crops": 14, "H_G3_crops": 0}},
        "selectionRule": "numeric strict increase; text and every grade/writer numeric+text nondecrease; generation failures nonincrease",
        "cameraCollection": {"plannedWriters": 24, "plannedSheets": 24, "plannedPhotos": 48, "plannedPhotoSlots": 960,
            "developmentWriters": 16, "calibrationWriters": 8, "releaseHoldoutIncluded": False},
        "remainingBeforeGpuRun": ["verified initial checkpoint/model assets and fixed training budget",
            "augmentation visual readability audit", "permission/provenance references", "separate authorized NVIDIA execution"],
        "trainingExecuted": False, "evaluationExecuted": False, "sourcePhotosPresent": False,
        "providerCallCount": 0, "deploymentReady": False}
    (output / "EXPERIMENT_PLAN.json").write_bytes(encoded(plan))
    for name in V4:
        if digest(output / "template" / name) != V4[name] or digest(template_dir / name) != V4[name]:
            raise ValueError("template changed before final receipt")
    manifest = {"schema": "student_test_camera_collection_kit_v1", "copiedTemplateIsUnchanged": True,
        "generatorCodeSha256": digest(Path(__file__)),
        "templateSource": str(template_dir.absolute()), "templateSha256": V4,
        "files": [{"path": str(p.relative_to(output)).replace("\\", "/"), "bytes": p.stat().st_size, "sha256": digest(p)}
            for p in sorted(output.rglob("*")) if p.is_file()], "providerCallCount": 0, "deploymentReady": False,
        "trainingExecuted": False, "evaluationExecuted": False, "includesStudentPhotos": False}
    (output / "KIT_MANIFEST.json").write_bytes(encoded(manifest))
    return {"output": str(output.absolute()), "filesIncludingManifest": len(manifest["files"]) + 1,
        "templateSha256": V4, "plannedSlots": 960, "providerCallCount": 0, "deploymentReady": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.template_dir, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
