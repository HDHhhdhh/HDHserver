# 무료 OCR 데이터 확대 GPU 패키지 · 2026-09-07

준비·검증·비공개 Drive 업로드 완료. 이 컴퓨터에서 새 학습·추론은 하지 않았고 운영 코드·모델·서비스·DB는 변경하지 않았다. `trainingExecuted:false`, `providerCallCount:0`, `deploymentReady:false`.

GPU 컴퓨터 Codex에 [원샷 프롬프트](https://drive.google.com/file/d/1Ls48QocBFldSq3KX6dMNoPVQVv4mVl3-/view?usp=drivesdk)의 전체 내용을 붙여 넣으면 된다. 실제 다운로드 링크, 크기/SHA, 재조립, 환경 검사, 8회 stage 학습, 평가, 분할 반환 지시가 모두 포함돼 있다.

- [전체 파일 폴더](https://drive.google.com/drive/folders/1OgIMX4r6t4IwshIbBhuGRBhQ-Wk0If51)
- [수신/전달 추적 manifest](STUDENT_TEST_FORMULA_EXPANSION_2026-09-07.manifest.json)
- [GPU 실행 본문 원본](STUDENT_TEST_FORMULA_EXPANSION_GPU_INSTRUCTIONS.md)
- [실제 데이터·학년·학습 예산 정본](../generated/free_ocr_expansion_20260907_02/data/EXPANSION_INPUTS.json)
- [선정·제외 감사 기록](../generated/free_ocr_expansion_20260907_02/data/SELECTION_AUDIT.json)

## 데이터 선정

| 시험 과목군 | 이전 focused | 이번 expanded | 마지막 focused |
|---|---:|---:|---:|
| 공통수학1·2: 중3+고1 | 919 | 1,922 | 967 |
| 대수·미적분1·확통·기하·미적분2: 중3+고1+고2+고3 | 1,647 | 3,245 | 1,757 |

상위 풀은 공통수학 풀을 포함하므로 두 행을 더해 고유 이미지 수로 세면 안 된다. 새로운 촬영이나 이미지 복제로 수를 늘린 것이 아니라, 기존 AI Hub converted Training 29,247개에서 실제 crop을 선별했다. 해당 converted pool은 원천 전체가 아니며 이미 작성자당 cap 200 등의 전처리를 거쳤다.

focused는 숫자·분수·루트 등 짧은 숫자식과 선택 판정용 구문 alias를 허용한다. 원래 전사는 계산하거나 바꾸지 않았다. auxiliary는 숫자가 있는 완전한 짧은 수식/등식이다. 변수 포함 식도 구조 학습의 보조 자료로만 쓰며, 운영 답안 문법을 확대하지 않는다. 단독 기호·잘린 지수 등 26,001개는 문법 선별 밖이다. 추가 육안 점검에서 지수/등호 전사 불일치가 보인 1개는 고치지 않고 제외했다. 전체 전사 정확성을 사람이 검수한 데이터라는 주장은 하지 않는다.

## 실험 범위

두 profile에서 각각 `focused→focused` 대 `expanded→focused`를 비교한다. 공통 A2,000+B1,000, 상위 A3,000+B1,000 microbatch. 같은 pretrained SHA, seed20260907, batch4/accum2, 동일 stage boundary와 B optimizer/LR reset을 사용한다. A는 고정 마지막 iteration/latest에서 B로 연결하고 best로 이름을 바꾸지 않는다. 총 8회 학습, 필수 평가 6개와 이전 focused checkpoint가 실제 검증 가능할 때 선택 평가 2개다.

모델 weight와 가상환경은 패키지에 없다. 기존 GPU 컴퓨터의 CUDA 환경 및 SHA가 고정된 원래 UniMERNet pretrained weight를 재사용한다. 최소 60 GiB 여유 공간을 확인하며, 기존 checkpoint 크기가 더 크면 지시문 계산식으로 상향한다. 데이터 확대 효과는 아직 미검증이다.

## 검증과 전달

- 최종 ZIP: `student_test_formula_expansion_GPU_20260907_r3.zip`, 182,062,136 bytes.
- SHA-256: `0fc19a0a72ad6949e0cb3a63fc90c635ff41f79eb64941a1e84a11d2661f9142`.
- manifest 10,867개 항목의 크기/SHA 일치, manifest 포함 실제 일반 파일 10,868개. 누락·추가·중복 0.
- 최종 패키지 snapshot에서 전용 9개 테스트 통과. 기존 config/profile runner 계약 20 assertions 통과. 서버 기본 회귀 검사는 두 차례 통과했다. 전체 구문 검사는 기존 캐시 ACL 오류 후 새 승인된 캐시 경로로 재실행해 통과했다. live smoke/운영 재시작은 하지 않았다.
- 학습용 7,891개 materialized 이미지/전사 쌍을 원본과 대조했다. 이는 profile과 focused/expanded 간 중복을 포함한 검사 건수이며 고유 새 표본 수가 아니다.
- validation의 이전 승인 annotation/image/provenance/manifest 해시를 고정해 대조했다. Training과 validation의 grade-scoped writer/source/exact-image SHA 교집합 0. 실제 동일인 신원·near duplicate 독립성까지 검증한 것은 아니다.
- 업로드 도구에서 실제 100 MiB 제한을 확인하여 입력과 향후 반환을 80 MiB 이하로 분할했다. 입력 3조각을 로컬에서 재조립해 전체 SHA를 확인했다. Drive에서는 이름/타입/크기/부모/비공개 상태를 재조회했다. 업로드 후 모든 binary를 다시 다운로드한 검증은 아니며 GPU 수신 시 SHA 검사를 필수로 지정했다.
- 원샷 프롬프트는 Drive에서 다시 읽어 로컬 원문과 일치함을 확인했다(줄바꿈/끝 공백 정규화).

## 남는 한계와 보존

validation은 이전에 후보 선택에 사용한 공개 개발 세트다. 공통 1,459 crop/3 writer hash, 상위 1,473 crop/6 writer hash. 고2 14개, 고3 0개이며 실카메라/calibration/출시 holdout이 아니다. `mandela` 검토의 재사용 개발 세트 및 shared-pool 한계는 남는다. 독립 촬영 검증 전 운영 GO를 주장하지 않는다.

[9월6일 반환 기록](STUDENT_TEST_FREE_OCR_RETURN_2026-09-06.md)의 3.9 GB ZIP/checkpoint 미수신 상태는 그대로다. 이번 입력은 그 미검증 checkpoint에 의존하지 않는다. 과거 문서의 준비/실행/업로드 시점도 수정하지 않았다.

`re0-loop`로 제작·검증 범위를 묶고, `mandela`로 검증 재사용/누수를 구분했다. `sip` 및 별도 읽기 전용 에이전트 검토로 고정 validation 해시, 공백 숫자 거부, 60 GiB 저장공간 조건을 보강했다. SSOT 점검에서는 이번 데이터 정본과 과거 시점 기록을 분리했으며 기존 문서를 통합/삭제하지 않았다.

초안 `free_ocr_expansion_20260907_01`, `_02/packet`, `_02/packet_release`, r1/r2 ZIP은 보존했다. Drive의 초기 `student_test_gpu_archive.py`는 200 MiB 초안이므로 실행에 사용하지 않는다. **원샷 프롬프트에 연결된 `student_test_gpu_archive_80MiB.py`와 r3 입력 조각만 사용한다.** 최종 자료 외 초안을 전달 후보로 해석하지 않는다. 대형 파일을 Git에 추가하거나 staging하지 않았다.
