# 영상 카탈로그 수정 모드

기존 영상의 MID를 바꾸거나 영상을 삭제할 때만 쓰는 유지보수 절차다. 평소 영상 관리 화면의 저장은 계속 안전하게 차단된다.

## 아주 간단히 말하면

- **일반 모드:** 제목·챕터·같은 MID의 새 서명 URL·새 영상만 바로 저장된다.
- **수정 모드:** 화면에서 고쳐도 서버에는 저장되지 않는다. 대신 `video-correction-....json` 수정안 파일만 내려받는다.
- **실제 적용:** 서버를 잠깐 멈추고 백업한 뒤, 수정안에 맞춰 `videos.json`, `updates.json`, `progress.json`, `watch.json`을 함께 바꾼다.

즉, 수정 모드는 “바로 수술”이 아니라 “수술 계획서 작성” 단계다.

## 수정안 만들기

1. `/video-manage`를 연다.
2. **수정 모드 켜기**를 누르고 경고를 확인한다.
3. 필요한 MID 변경·삭제·추가·내용 수정을 한다.
4. 화면의 변경 건수를 확인한다.
5. **수정안 다운로드**를 누른다.
6. 작업을 버리려면 **수정 취소**를 누른다. 이때 운영 데이터는 바뀌지 않는다.

수정안에는 전체 영상 URL이 들어 있으므로 외부에 공유하거나 Git에 올리지 않는다.

## 먼저 검사만 하기

다음 명령은 운영 데이터를 쓰지 않는다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/apply_video_catalog_correction.ps1 -Draft "C:\다운로드\video-correction-파일.json"
```

검사가 거부되는 대표 이유는 다음과 같다.

- 수정안을 만든 뒤 운영 `videos.json`이 달라짐
- 중복 ID 또는 중복 MID
- URL에서 읽은 MID와 행의 MID가 다름
- 삭제할 영상을 배정·진도·시청 데이터가 아직 참조함

## 실제 적용하기

검사 결과를 확인한 뒤 다음처럼 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/apply_video_catalog_correction.ps1 -Draft "C:\다운로드\video-correction-파일.json" -Apply -ConfirmApply
```

스크립트가 자동으로 다음 순서를 지킨다.

1. 쓰기 없는 dry-run 재검사
2. Waitress 예약 작업 정지 및 8003 포트 종료 확인
3. 네 운영 파일이 포함된 전체 런타임 백업 생성
4. 백업의 경로와 네 파일 SHA-256이 현재 파일과 같은지 확인
5. 배정·진도·시청 MID를 함께 변환하고 카탈로그는 마지막에 저장
6. 저장 결과 재검사; 실패하면 이미 쓴 파일을 원래 내용으로 롤백
7. Waitress 재시작 및 8003 포트 확인

`-Apply`와 `-ConfirmApply`가 둘 다 없으면 실제 적용은 시작되지 않는다. 8003 포트를 예상하지 못한 프로그램이 잡고 있거나, 백업 뒤 파일이 달라져도 적용은 거부된다.

## 삭제 규칙

기존 MID를 참조하는 배정·진도·시청 기록이 하나라도 있으면 삭제를 자동 거부한다. 기록을 어떻게 처리할지 별도 결정 없이 자동으로 지우지 않는다.