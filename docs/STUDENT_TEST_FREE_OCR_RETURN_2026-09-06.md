# 무료 OCR GPU 반환 수신 기록 — 2026-09-06

## 결론과 검증 상태

**문서상 결과 확인·신규 등록 완료, ZIP/checkpoint 바이너리 수신 검증은 차단 상태다.** 두 focused best1000은 반환 후보로만 등록했다. 운영 모델 교체·기능 활성화·서비스 중지/재시작·새 학습·새 추론은 하지 않았다. `deploymentReady:false`, `providerCallCount:0`이다.

이 문서는 [기존 OCR 상태 정본](STUDENT_TEST_OCR_PUBLIC_DATA.md), [무료 개선·GPU 패키지 준비 기록](STUDENT_TEST_FREE_OCR_RESULTS_2026-09-06.md), [실행 프롬프트](STUDENT_TEST_FREE_OCR_GPU_PROMPT.md)의 후속 **수신 기록**이다. 과거 문서·receipt·계획서의 시점별 사실을 고쳐 쓰지 않았다. 모델 설치나 출시 승인 문서가 아니다.

- [수신 추적 manifest](STUDENT_TEST_FREE_OCR_RETURN_2026-09-06.manifest.json): Drive 수신 metadata, 기대값/실제값, 후보·공통 모델 파일 연결, 데이터·예측 해시, 검증/미검증 상태.
- [받은 receipt 원본](../generated/free_ocr_return_intake_20260906_01/DRIVE_RETURN_RECEIPT.json)
- [받은 요약 원본](../generated/free_ocr_return_intake_20260906_01/DRIVE_SUMMARY_KO.md)
- 새 결과 폴더: `C:/server/generated/free_ocr_return_intake_20260906_01/`. **RETURN/ 추출 폴더는 생성하지 않았다.**

## 무엇을 실제로 확인했는가

| 항목 | 이번 수신 측 확인 |
|---|---|
| Drive metadata | 지정 ZIP·receipt·요약의 파일명, MIME, 크기, 부모 폴더 일치 |
| ZIP 다운로드 | HTTP 413. 3,901,195,892 bytes가 커넥터 268,435,456-byte 제한 초과 |
| 저장 공간 | 시작 시 C: 약 55.9 GB 여유. ZIP과 receipt에 기재된 추출 파일의 합계 약 7.80 GB보다 충분. ZIP 중앙 목록의 실제 압축 해제 크기는 미확인 |
| 별도 receipt 원본 | 브라우저 일반 다운로드. **110,362 bytes 및 지정 SHA-256 일치**. 새 결과 폴더 복사본도 일치 |
| 별도 요약 원본 | 브라우저 일반 다운로드. **3,043 bytes 및 receipt의 요약 SHA-256 일치** |
| receipt 내부 정합성 | 111개 파일 목록의 경로 문자열·중복·메타데이터, 9평가의 산술/그룹 합계, 4학습과 파일 참조 등 390개 문서 정합성 조건 일치 |
| 실제 ZIP 112개 파일 | **미확인**. receipt 목록을 실제 ZIP inventory로 검증한 것이 아님 |
| checkpoint 3개·model 4개 | receipt의 경로·크기·해시·후보 연결만 확인. **바이너리와 PyTorch metadata 미확인** |
| report·JSONL·config·log·audit 원본 | ZIP 미수신으로 **미열람**. JSONL 재집계·표본 index/중복·라벨 대조도 미수행 |

다운로드 도구가 반환한 파일 참조를 로컬로 저장할 기능이 없어, 작은 receipt와 요약은 인증된 브라우저의 원본 다운로드 버튼을 사용했다. receipt의 브라우저 이벤트 대기는 timeout이었지만 실제 로컬 파일을 찾아 크기·해시로 완료를 확인했다. 공유 설정·로그인 계정·외부 파일은 변경하지 않았다.

원본 receipt SHA-256은 `a6ea1aad8f3f28b6d3463b148a758a01ff40bff49dba13794569457ab35ef95c`다. 이 일치는 **별도 Drive receipt**에 한정된다. ZIP 내부 receipt와 같은 바이트인지는 ZIP 수신 뒤 확인해야 한다.

`PACKET_MANIFEST.json`은 원래 입력 패키지의 목록이다. 사용자가 명시한 5,525개 입력 파일이 RETURN에 모두 있어야 한다고 요구하지 않았다. 기대 RETURN inventory는 receipt의 copiedFiles 111개와 receipt 자체 1개다.

## 4회 학습·9개 평가의 문서상 수신 결과

receipt의 `training`과 `executionSummary`에 **학습 성공 4 / 실패 0 / 미실행 0**, 평가 성공 **9 / 실패 0 / 미실행 0**이 기재돼 있고 레코드 수·상태가 서로 맞는다. 같은 base SHA-256, batch4/accum2, 각 1,000 microbatch 기록도 일치한다.

**seed 20260906은 요약에만 기재되어 있다. receipt에는 seed 필드가 없어 원격 YAML 원본에 대한 검증은 미수행이다.** 학습 로그의 완료 marker와 best iteration은 receipt 선언을 읽었을 뿐 실제 로그·checkpoint로 다시 증명하지 않았다.

다음은 **해시 검증한 receipt의 집계값**이다. 숫자값 동치와 정규화 문자열 일치를 구분하며, 이 표를 독립적인 예측 JSONL 재검증 결과로 해석하면 안 된다.

| 프로필 | 평가 모델 | 숫자값 동치 | 정규화 문자열 일치 | 전체 숫자 실패 | 생성 상한/미종료 실패 |
|---|---|---:|---:|---:|---:|
| 공통수학 | 사전학습 base | 1166/1459 (79.92%) | 1130/1459 (77.45%) | 293 | 0 |
| 상위 | 사전학습 base | 1166/1473 (79.16%) | 1130/1473 (76.71%) | 307 | 0 |
| 공통수학 | 기존 best | 1271/1459 (87.11%) | 1255/1459 (86.02%) | 188 | 0 |
| 상위 | 기존 best | 1284/1473 (87.17%) | 1265/1473 (85.88%) | 189 | 0 |
| 상위 | 기존 latest5000 | 1284/1473 (87.17%) | 1264/1473 (85.81%) | 189 | 0 |
| 공통수학 | 새 full1000 | 1205/1459 (82.59%) | 1187/1459 (81.36%) | 254 | 0 |
| 상위 | 새 full1000 | 1232/1473 (83.64%) | 1211/1473 (82.21%) | 241 | 0 |
| 공통수학 | 새 focused1000 | 1354/1459 (92.80%) | 1331/1459 (91.23%) | 105 | 0 |
| 상위 | 새 focused1000 | 1355/1473 (91.99%) | 1327/1473 (90.09%) | 118 | 0 |

- 공통수학: full → focused에서 숫자 일치 **+149**, 실패 **254 → 105**.
- 상위: 숫자 일치 **+123**, 실패 **241 → 118**.
- receipt에 기재된 모든 학년·writer 그룹의 숫자 및 문자열 일치는 full 대비 개선 또는 동일이고 생성 실패 증가는 없다. 그룹 합계가 전체와 일치한다.
- 반대로 새 full1000은 기존 best보다 낮다. “추가 학습이면 모두 개선”된 결과가 아니라, 이 개발용 비교에서 focused 전략이 유리했던 결과다.
- 생성 실패 0은 9개 **기재 집계**에서 확인했다. 실제 `tokenCount >= 64` 행 존재 여부는 JSONL을 받아 확인해야 한다. 숫자 실패와 생성 실패는 겹칠 수 있어 합산하지 않는다.
- 기존 JSONL 계약에는 token IDs가 없으므로, 수신 후에도 `terminated:true`의 EOS 관측 사실을 그 파일만으로 독립 복원할 수는 없다. cap 도달을 실패로 세는 일관성 검사는 가능하다.

## 후보와 공통 모델 파일의 연결

모든 아래 경로는 **미수신 RETURN 내부 상대경로**다. GPU 원본 경로와 향후 이 컴퓨터의 경로를 섞지 않도록 manifest의 `originalGpuPath`와 `currentLocalPath:null`로 구분했다.

| 후보 | profile / strategy | receipt의 실제 best iteration | 기대 bytes | RETURN 상대경로 |
|---|---|---:|---:|---|
| 공통수학 선택 | m3_h1 / focused | 1000 | 1,289,942,276 | checkpoints/m3_h1/focused/checkpoint_best.pth |
| 상위 선택 | m3_h1_h2_h3 / focused | 1000 | 1,289,942,340 | checkpoints/m3_h1_h2_h3/focused/checkpoint_best.pth |
| 기존 상위 별도 후보 | m3_h1_h2_h3 / legacy_best4000 | 4000 | 1,289,942,404 | checkpoints/legacy_m3_h1_h2_h3_best/checkpoint_best.pth |

각 후보의 전체 기대 SHA-256은 manifest에 기록했고 사용자 제공값과 receipt 기재값의 일치를 확인했다. 세 후보는 공통 `model/config.json`, `model/preprocessor_config.json`, `model/tokenizer_config.json`, `model/tokenizer.json`에 연결했다. 네 파일의 receipt 해시는 저장했지만 반환 바이너리 해시 대조는 아직 하지 못했다.

기존 상위 best4000과 latest5000은 숫자 일치가 1,284로 같지만 문자열 일치는 1,265 / 1,264다. **같은 checkpoint로 취급하지 않는다.** 출력 22개 차이·4개 개선/4개 악화와 기존 반환본 중복 제외 사유는 요약에 기재되어 있으며, `audit/EXISTING_MODEL_COMPARISON.json`, `COMMON_BEST_LATEST_EQUIVALENCE.json`, `RETURNED_MODELS_EQUIVALENCE.json` 원본으로는 아직 확인하지 못했다.

새 full/focused best 네 개가 GPU 컴퓨터에 보존되고 RETURN에 focused 두 개와 legacy best4000만 포함된다는 것은 receipt의 보존/구성 선언이다. 실제 원격 파일 보존 상태를 이 컴퓨터에서 확인한 것은 아니다.

## 성능 근거의 한계

- 공통수학 **1,459 crop / 3 writer hash**, 상위 **1,473 / 6**. 학년 구성은 중3 1,332, 고1 127, 상위 고2 14, 고3 0이다.
- 상위 고2는 full/focused 모두 **3/14**다. 전체 91.99%를 고2·고3 과목 정확도로 일반화하지 않는다.
- writer hash는 grade-scoped 식별자이며 동일인 신원이 완전히 검증되지 않았다. 한 writer hash에 1,269 crop이 몰려 있어 crop 개수를 필체 다양성으로 보지 않는다.
- 공개 AI Hub 파생 **개발용 validation**, 1,000 microbatch 방향 비교다. 실제 학생 촬영·새 답안지 calibration·독립 출시 holdout이 아니다.
- `mandela` 점검: 공유 데이터/라벨 계열과 후보 선택에 사용한 개발 세트는 새 필체·카메라 일반화의 독립 근거가 아니다. 해결 근거는 나중에 별도 작성자·촬영 조건의 손대지 않은 holdout이다. 이번에는 수집·추론하지 않았다.
- 요약과 receipt는 같은 생산자의 기록이다. 서로 일치한다는 이유만으로 독립 검증을 두 번 한 것처럼 세지 않는다. 재현 코드를 설계했던 에이전트와 별도 읽기 전용 에이전트의 산술 점검도 원본 JSONL 검증을 대체하지 않는다.

## 원본의 시점 차이 보존

`EXPERIMENT_PLAN.json`/`EXPERIMENT_INPUTS.json`의 `trainingExecuted:false`는 준비 시점 기록이며, 실제 수행 상태는 receipt의 training/executionSummary와 구분한다. 두 계획서 원본은 아직 열지 않았고 이 의미는 receipt의 preparationRecordNote에서 확인했다.

receipt의 `uploadPerformed:false`와 요약의 로컬 제공 문구는 승인 업로드 전 기록이다. 이후 Drive metadata에는 업로드된 세 파일이 존재한다. 현재 전달 링크·생성/수정 시각을 신규 manifest에 별도로 남겼고 원본을 수정하지 않았다.

## 남은 수신 검증

1. [결과 ZIP](https://drive.google.com/file/d/1-2vNfkzHkPHtPlTNRmz5jmjs0_88qcr0/view?usp=drivesdk)을 이 컴퓨터에 직접 다운로드한 뒤 **로컬 경로를 제공**하면 이어갈 수 있다. 새 학습이나 결과 재생성은 필요 없다.
2. 정확한 3,901,195,892 bytes 및 SHA-256 `974b29c2542151e7520a574ff53e72681f8c81ed0f80dd2061ec08df9c2fcb30`를 먼저 확인한다.
3. 새로운 빈 추출 폴더에서 절대/상위 탈출 경로, 링크, Windows 중복 목적경로를 거부하고 112개 실제 파일과 111개 copiedFiles의 크기·해시, 두 receipt의 바이트 동일성을 확인한다.
4. 세 checkpoint·공통 모델 4파일·로그 기반 best iteration, 기존 모델 동치성 audit을 확인한다. 필요하면 설치된 PyTorch의 CPU/`weights_only=True` metadata만 검사하고 불가하면 미수행으로 남긴다.
5. 9개 report/JSONL 원본을 고정 분모·index 완전성·중복·cap·학년/writer별로 재집계하고, 해시가 일치하는 기존 validation 라벨과 대조한다. **추론을 새로 실행하지 않는다.**

평가: **문서상 결과는 한계를 붙여 공유 가능. 바이너리 수신 완료·운영 승인으로는 사용 불가.** 새 파일은 이 결과 문서와 manifest, ignored 결과 폴더의 원본 두 개뿐이다. 기존 코드·데이터·checkpoint·운영 DB는 손대지 않았으며 staging/commit도 하지 않았다. 애플리케이션 변경이 없어 전체 앱 회귀나 서버 검사를 추가 실행하지 않았다.
