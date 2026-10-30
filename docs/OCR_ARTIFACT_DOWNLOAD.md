# OCR 자료 다운로드

[Google Drive 업로드 폴더](https://drive.google.com/drive/folders/1mmm-sUIfrbRPfGMOO4xo_fclVBOqhLcc)

폴더: `OCR_handoff_20261030_7deeb42`

상태: **2026-10-30 업로드 완료**. 138개 archive 조각, 3개 PARTS manifest, 재조립 도구·안내문, 최종 전달 manifest를 등록했다.
Google Drive는 소유자 전용 비공개 권한이다. 이 GitHub 저장소가 공개여도 Drive 접근 권한은 생기지 않는다.

## 받은 자료

| 묶음 | 내부 파일 수 | 조각 수 | 재조립 archive 크기 |
|---|---:|---:|---:|
| `datasets` | 379,742 | 113 | 9,477,560,320 bytes |
| `checkpoints` | 12 | 24 | 1,996,738,560 bytes |
| `comparison_original` | 137 | 1 | 460,800 bytes |

합계 archive 크기: 11,474,759,680 bytes. 형식은 tar+gzip이며 각 조각은 최대 80 MiB다.
`datasets`의 파일 수는 내부 hardlink 72,480개를 포함한다.

- 데이터셋: 이 컴퓨터에 남아 있는 AI Hub 교육 OCR 디렉터리. 원천 파일·변환 crop·라벨·profile 자료를 포함한다.
- 모델: 숫자 CNN v3, UniMERNet 공통·상위 체크포인트와 설정. 기존 GPU 후보 전체 백업은 아니다.
- 비교 결과: `comparison_20261030_01`의 원본·예측·호출 원장·회전 진단 근거. 회전 오류가 포함된 최초 40 crop 비교의 역사 자료다. 진행 중인 회전 보정 재비교 결과가 아니다.

## 수신과 검증

[수신 안내문](https://drive.google.com/file/d/1Ipf2uH14GWjmzDr_X8hcJQA9AGFBzrrZ/view)과 [DELIVERY_MANIFEST.json](https://drive.google.com/file/d/1syc5wYUo53vd5P1y5ab-s6b00T1JsvR6/view)을 먼저 읽는다.

1. 새 로컬 폴더와 충분한 공간을 준비한다. 조각·재조립본·추출본을 보존하려면 40 GiB 이상을 권장한다.
2. 필요한 묶음의 `*.PARTS.json`, 모든 part, `verify_and_join.py`를 같은 폴더에 받는다.
3. helper 전체를 읽고 SHA-256을 대조한 뒤 재조립한다.

```powershell
python verify_and_join.py --manifest checkpoints.PARTS.json --output checkpoints_verified.tar.gz
```

4. `verified:true`를 확인한 뒤 새 빈 폴더에만 안전하게 압축 해제한다. 기존 환경에 자동 복사하지 않는다.

helper SHA-256: `2b692a8dada371f337a8fa52ef6e4d64776266914eeb35cbf3f644ab57e41a32`.

재조립 archive SHA-256:

| 묶음 | SHA-256 |
|---|---|
| `datasets` | `1a5c0b7199633f419a2438826a66315bfed6e072ce00f917a39c77526d854c4a` |
| `checkpoints` | `8255f8cca433c5654bef92d041a8941ebf10969e3b05d58eb4cc7e280fa40e87` |
| `comparison_original` | `31f58f0917ba12de7be1a8d2c382858cef8aac768679a9bfae445a7e6d4116c9` |

전송 전 전체 archive를 끝까지 읽어 경로 안전성을 검사했고 138개 로컬 조각의 SHA-256을 다시 계산했다.
업로드 후 143개 고정 payload 파일의 이름·정확한 크기·폴더 소속·소유자 전용 권한과 Chrome 업로드 완료를 확인했다.
Drive 원본 전체를 다시 내려받아 해시를 계산한 것은 아니다. 수신 컴퓨터는 manifest의 조각 및 archive SHA-256을 반드시 확인해야 한다.

API 키, 인증 설정, 운영 DB, 실제 학생 촬영 자료, 가상환경은 포함하지 않는다.
삭제된 원천 학습 이미지는 복구하지 않았다. 기존 crop 방향·라벨 오류가 해결된 학습 세트라고 주장하지 않는다.
새 학습·추론 평가·운영 모델 교체·서버 재시작은 수행하지 않았다. `providerCallCount:0`, `deploymentReady:false`다.

코드 기준: `codex/admin-operations-toolkit` 브랜치의 `7deeb421be02590925016647ad4090739267bd6a`.
현재 서버에서 진행 중인 미커밋 수정과 새 비교 결과는 이 snapshot에 포함하지 않았다.
진행 기록은 `docs/STUDENT_TEST_OCR_CHECKPOINT_2026-10-30.md`를 참고한다.
