# 학생 시험 OCR 공개 데이터·학습 운영 메모

**현재 상태(2026-09-06):** AI Hub 이미지 변환과 외부 NVIDIA 수식 학습은 완료했고 두 반환 체크포인트가 설치되어 있다. 그러나 새 v4 답안지의 실제 학생 촬영 holdout은 없고 운영은 **OFF / NO_GO**다. 기본 객관식은 v3를 유지한다. 이 문서가 OCR 학습·평가·출시 준비 상태의 정본이며, [전면 검토 기록](STUDENT_TEST_OCR_REVIEW_2026-09-06.md)은 이번 판단의 근거와 수정 범위를 보존한다.

**후속 증거 안내(2026-09-07):** 무료 확대 실험의 원격 학습·평가 기록 및 반환 evidence 검증은 [수신 검토](STUDENT_TEST_FORMULA_EXPANSION_RETURN_2026-09-07.md)와 [추적 manifest](STUDENT_TEST_FORMULA_EXPANSION_RETURN_2026-09-07.manifest.json)를 따른다. checkpoint 바이너리 재조립·검증과 운영 채택은 미완료이며 OFF / NO_GO를 유지한다. 아래 2026-09-06 결과는 당시 기록으로 보존한다.

**처리 구조 개선(2026-10-04):** 1단계의 생성·문항 crop·인식값 문법·오류 종료와 2단계의 시험/회차 계약·비동기 재촬영·상주 worker·lease/채점 복구를 구현하고 순수 회귀를 통과했다. 구현·회귀 및 숫자 부분 지연 진단은 [개선 계획](STUDENT_TEST_OCR_IMPROVEMENT_PLAN_2026-10-03.txt), 처리 계약은 [기준서 §21](PROJECT_FUNCTIONS_AND_LOGIC.md#21-학생-시험-ocr-제출과-카탈로그-유형-계약)이 소유한다. 수식·혼합 실촬영 지연은 미검증이다. 학습이나 정확도 재평가는 수행하지 않았고 기존 모델·반환 산출물과 OFF / NO_GO를 유지한다.

**3단계 후속(2026-10-04):** 별도 기본-OFF의 7일 보관 scheduler와 지난 날짜 보류 점검을 구현·격리 검증했다. 운영 삭제는 실행하지 않았다. checkpoint 추가 수신은 원본 part001의 휴지통 상태로 차단됐다. [이번 수신 점검](STUDENT_TEST_FORMULA_CHECKPOINT_RECEIVE_2026-10-04.md)과 [추적 manifest](STUDENT_TEST_FORMULA_CHECKPOINT_RECEIVE_2026-10-04.manifest.json)를 따른다. 새 학습·추론 평가·운영 모델 채택은 없으며 OFF / NO_GO를 유지한다.

**4단계 준비(2026-10-04):** v4 수집 키트·혼합 20문항 snapshot/저장 예측 검토 도구와 공개 focused Training의 대조군/촬영 증강본을 준비했다. 실제 촬영·독립 전사·증강 가독성 감사·새 GPU 비교는 남아 있다. [진행 기록](STUDENT_TEST_OCR_IMPROVEMENT_PLAN_2026-10-03.txt)과 [수집·검토 사용법](STUDENT_TEST_OCR_CAMERA_DATA_2026-10-04.txt)을 따른다. 준비물을 실제 촬영 정확도나 운영 GO의 근거로 사용하지 않으며 OFF / NO_GO를 유지한다.

**5단계 준비(2026-10-04):** 현재 촬영 frontend·영역변환·스타일·서버 경계를 출시 artifact 범위에 포함하고 NO_GO 전용 사전심사 도구를 구현·격리 검증했다. 실제 독립 촬영·보완/채점 trace·전체 지연·운영 적용은 미완료다. [진행 기록](STUDENT_TEST_OCR_IMPROVEMENT_PLAN_2026-10-03.txt)과 [사전심사·승인 후 적용 순서](STUDENT_TEST_OCR_RELEASE_PREP_2026-10-04.txt)를 따른다. 운영 활성화·모델 교체·서버 재시작은 수행하지 않았다.

**무료 개선 후속:** 사용자는 유료 전환 대신 무료 개선 전체 진행을 승인했다. 원본/기존/테두리 제거 후보를 동일 입력으로 비교했고, 수식은 원본 crop이 유리하여 유형별 입력 경로를 분리했다. 실제 비교 수치·공개 파생 데이터·검증한 GPU 전달 패키지는 [무료 OCR 실행 결과](STUDENT_TEST_FREE_OCR_RESULTS_2026-09-06.md)에 기록했다. 추가 GPU 학습 자체는 미실행이며, 현재 컴퓨터에서 할 수 있는 데이터 준비·실행 코드·패키지 검증을 완료했다. 운영 OFF는 유지한다.

## 이번 검토의 정정

- 2026-08-31 반환 모델 재검증에는 `formula_daesu` 전사와 다른 사진 crop을 연결한 오류가 있었다. 당시 35.7%·32.1% 및 이를 이용한 학습 전후 개선 결론은 철회한다. 과거 `generated/gpu_formula_return_integration_20260831.md`와 그 실행 JSON은 감사용으로 보존하되 현재 품질 근거로 쓰지 않는다.
- 2026-09-06 재검증은 8/29 원래 crop·전사·template 해시에 맞춰 입력을 고정했다. 주관식 `1~5`를 제외하던 평가 필터도 제거했으므로 수식 경로 진단 분모는 28개에서 60개가 됐다. 새 결과를 옛 28개 점수와 직접 비교하지 않는다.
- 수식 보고서의 `rawAccuracy`는 **숫자값 동치율**이며 문자 전사 완전 일치율이나 20문항 전체 촬영 성공률이 아니다. 결과 상세는 [검토 기록의 진단 결과](STUDENT_TEST_OCR_REVIEW_2026-09-06.md#동일-입력-재진단)에 둔다.
- 파일 설치, 학습 로그 지표, 과거 crop 진단, 실제 카메라 출시 검증을 서로 다른 증거로 취급한다. 과거 crop 전처리에서 테두리·점선 잔존을 직접 확인했다. 낮은 점수를 모델 학습량 또는 촬영 도메인 차이 하나로 단정하지 않는다.
- 현재 환경에서 `readiness_report()`는 `installed:true`, `deploymentReady:false`다. 숫자 학습 gate와 독립 카메라 증거가 모두 부족하다. 플래그만으로 활성화할 수 없고 미준비 모델 우회는 marker-verified 격리 서버에 한정한다.

## 결론

- 객관식 숫자 1~5는 공개 숫자 데이터로 기본 필체 범위를 넓히고, 실제 답안지와 다른 문자·다중 숫자는 `__reject__`로 학습한다.
- 한국 학생의 답안지 필체에 가장 가까운 공개 후보는 AI Hub 교육 자료 OCR 데이터다. 계정 가입, 데이터 이용 신청, API key 발급은 한 번 필요하지만 승인 뒤 다운로드·변환·재학습은 자동화할 수 있다.
- 고1·고2·고3 객관식은 공용 모델 하나로 합친다. 학년별 양을 억지로 같게 만들지 않고 작성자와 숫자 클래스 쏠림만 제어하며, 평가는 학년별로 분리한다.
- 수식은 UniMERNet 사전학습 가중치에서 시작하되 AI Hub 교육 OCR의 `Bbox.type == 2` 수식 crop으로 두 개의 과목 프로필을 미세조정한다. `공통수학1·2`용은 `M_G3+H_G1`, 상위 과목용은 `M_G3+H_G1+H_G2+H_G3`를 사용한다.
- 인터넷 데이터만으로 운영 정확도를 선언하지 않는다. 정답키가 아닌 독립 사람 전사 holdout에서 오수락 0건과 통계 gate를 함께 통과해야 한다.

## 데이터 구성과 2026-08-29까지의 진단 기록

이 절의 날짜별 모델 점수는 당시 실험 기록이다. 이후 반환 모델·입력 오류 정정은 위 현재 상태와 검토 기록을 우선한다.

`scripts/train_student_test_choice_classifier.py`는 다음 데이터를 한 번에 섞는다.

| 역할 | 데이터 | 현재 사용량 | 라벨 |
|---|---|---:|---|
| 숫자 1~5 기본 분포 | MNIST | 30,000 | `1`~`5` |
| 다른 필체의 숫자 1~5 | EMNIST Digits | 30,000 | `1`~`5` |
| 범위 밖 숫자 | EMNIST Digits의 0·6·7·8·9 | 10,000 | `__reject__` |
| 문자 오인식 방지 | EMNIST Letters | 10,000 | `__reject__` |
| 두 자리 이상 오인식 방지 | MNIST 두 숫자 합성 | 10,000 | `__reject__` |
| 답안지 도메인 적응 | 기존 독립 사람 전사 crop | 가용분 반복 증강 | 전사값 또는 `__reject__` |

공개 데이터 출처와 개수, 실제 case의 crop 파일명 hash와 전사 파일 hash는 checkpoint와 `metrics.json`에 남긴다. 정답키는 학습 입력과 worker 입력에 전달하지 않는다.

AI Hub 교육 OCR 변환기는 작성자·라벨별 crop 상한을 먼저 적용한다. 여러 학년의 변환 결과를 학습기에 반복해서 `--aihub-root`로 주면, 학습기는 모든 root를 하나의 pool로 합친 뒤 `1`~`5`만 전역 균형화한다. 학년별로 각각 oversampling하지 않으므로 원자료의 자연스러운 학년 비중은 유지된다. 고2 Training을 먼저 적용하되, 다음 판정은 공식 Validation의 고1·고2·고3 지표를 각각 기록한다. 고1·고3 Training 추가는 분리 평가에서 성능 격차나 표본 부족이 확인될 때 우선한다.

주관식은 다음 두 학습 산출물을 분리한다.

| 모델 프로필 | 시험 과목 | AI Hub Training grade root |
|---|---|---|
| `m3_h1` | 공통수학1, 공통수학2 | `M_G3`, `H_G1` |
| `m3_h1_h2_h3` | 대수, 미적분1, 확통, 기하, 미적분2 | `M_G3`, `H_G1`, `H_G2`, `H_G3` |

프로필은 학생 학년이 아니라 시험 카탈로그 `curriculum`으로 선택한다. 공식 Validation 지표도 grade root별로 따로 기록한다. 주관식 수식이 있는 미등록 과목은 가까운 프로필을 추정하지 않는다.

2026-08-29 공식 원천 ZIP을 모두 받은 뒤 실제 이미지 crop 변환을 완료했다. Training 수식에는 작성자당 200개 상한을 적용했고 Validation은 원분포를 유지했다. 객관식 Training은 고1·고2·고3만 공용 pool에 사용하며 중3 객관식은 보조 Validation 진단만 남긴다.

| grade root | Training 수식 crop | 작성자 | Validation 수식 crop | Training 객관식 `1~5` / reject | Validation 객관식 `1~5` / reject |
|---|---:|---:|---:|---:|---:|
| `M_G3` | 9,499 | 207 | 9,187 | 미사용 | 510 / 42,832 |
| `H_G1` | 8,478 | 228 | 2,408 | 1,479 / 20,422 | 154 / 37,540 |
| `H_G2` | 5,213 | 184 | 1,223 | 697 / 19,416 | 133 / 36,716 |
| `H_G3` | 6,057 | 163 | 843 | 900 / 21,973 | 102 / 35,490 |

수식 프로필 입력은 `m3_h1` Training 17,977·Validation 11,595개, `m3_h1_h2_h3` Training 29,247·Validation 13,661개다. 프로필 이미지는 원 grade crop을 hardlink해 중복 저장하지 않았고 manifest·annotation·실제 PNG 수를 모두 대조했다. 공식 Validation의 작은 box 제외 때문에 라벨 감사의 box 수와 실제 crop 수가 고2 57개, 고3 23개만큼 다르다.

2026-08-29 라벨 split 감사에서 Training과 Validation의 `Images.identifier` 중복은 네 학년 모두 0건이었지만 작성자 ID는 일부 겹쳤다. 따라서 공식 Validation 전체 점수와 별도로, 객관식은 네 학년 Training 전체에 한 번도 등장하지 않은 작성자만, 수식은 해당 프로필의 Training 전체에 한 번도 등장하지 않은 작성자만 추린 `strict` 지표를 함께 기록한다. `scripts.audit_student_test_aihub_validation`이 이 경계를 검사한다. 이 검사는 라벨·split 무결성 증거이며 모델 정확도 증거가 아니다.

현재 라벨만으로 계산한 객관식 strict 표본의 가장 작은 숫자 클래스는 `M_G3/H_G1/H_G2/H_G3 = 59/10/2/4`개다. 특히 고1·고2·고3은 학년별 클래스당 20개 gate를 만족하지 못하므로, 공식 AI Hub 학년별 수치는 보조 진단으로만 사용하고 운영 GO는 별도 실제 답안지 필체 holdout으로 판정한다.

첫 공개 데이터 파일럿 `choice_digit_v4`는 분리 holdout 20문항에서 raw 75%, 객관식 자동 수락 12/18, reject 2/2였으나 고신뢰 `3 → 2` 오수락 1건이 발생했다. 따라서 `NO_GO`이며 운영 기본값은 안전했던 v3에서 바꾸지 않았다. PaddleOCR 교차합의도 같은 crop에서 신뢰 판정 0건이라 운영하면 자동 수락을 전부 없애므로 사용하지 않는다.

기존 실제 필체 한 장을 추가 적응한 보수판은 raw 80%, 자동 수락 10/18, 오수락 0건, reject 1/2였다. 기존 사람 전사 3장을 섞은 판은 12/18 수락으로 회복했지만 같은 고신뢰 오수락 1건이 다시 나타났다. 공개 범용 숫자 데이터만 늘리는 방식으로는 운영 개선이 확인되지 않았다.

고1·고2·고3 AI Hub Training crop을 전체 pool에서 클래스당 885개와 reject 4,425개로 균형화한 새 공용 모델은 독립 `teacher_02`에서 raw 17/20, 객관식 자동 수락 14/18, 고신뢰 오답 0건이었지만 reject recall이 1/2라 `NO_GO`다. 공식 AI Hub Validation 단일-crop 진단에서도 고1·고2·고3의 `1~5 raw / reject recall / coverage / 고신뢰 오답`은 각각 `85.71% / 88.84% / 29.87% / 288`, `69.92% / 87.77% / 20.30% / 252`, `62.75% / 86.37% / 31.37% / 380`이었다. 중3 보조 진단도 `86.47% / 79.08% / 23.53% / 409`로 안전하지 않았다. 이 평가는 실제 runtime의 두 variant 합의가 빠진 단일 변환 crop 진단이므로 GO 근거가 될 수 없지만, 높은 임계값에서도 오수락이 많다는 NO-GO 반증으로는 충분하다. 결과는 ignored `generated/ocr_aihub_choice_validation_20260829.json`에 있으며 SHA-256은 `EBABB4DDE9C98664BD3EFC5AAE296767A9B2C55795CFB0C23F143134CD7B31F1`이다.

같은 새 checkpoint를 실제 runtime 전처리와 두 variant 합의로 `teacher_01+teacher_02` 사람 전사 40문항에 다시 적용하면 객관식 raw 27/38(71.05%), 자동 수락 18/38(47.37%), 고신뢰 오답 0, reject 1/2다. v3의 22/38(57.89%), 14/38(36.84%), 0, reject 0/2보다는 나아졌지만 표본·coverage·reject gate를 통과하지 못한다. 같은 실행의 미세조정 전 수식은 다시 2/28, 자동 수락 2/28, 고신뢰 오답 1건이었다. 보고서는 ignored `generated/ocr_accuracy_after_aihub_20260829.{json,md}`이며 SHA-256은 각각 `F9D37B0E7D81684CC0699D69E6F67308279DB1B5ABE06150D50CEEC51B009ECF`, `48C982C5BA1CA8A7218DB32A9D59235351D2AC97E369A5ADD841DFC82E6FE790`이다.

2026-08-29 사람 전사만 사용한 전체 로컬 재추론에서도 독립 `teacher_02` 결과가 그대로 재현됐다. v3는 11/18 자동 수락·오수락 0, v4 pilot은 12/18·오수락 1, teacher_01 적응판은 10/18·오수락 0, 다중 적응판은 12/18·오수락 1이다. 따라서 v3 유지·전 후보 `NO_GO` 판정은 변하지 않는다. 같은 실행에서 미세조정 전 UniMERNet tiny + Paddle + PP-FormulaNet-S를 실제 숫자·분수·루트 범위의 사람 전사 28문항에 적용한 결과 raw 2/28, 자동 수락 2/28, 오수락 1건이었다. 분수는 0/1, 루트는 0/3이었다. 이는 과목 프로필 체크포인트가 없는 기본 모델 진단이며, 앞서 성공한 단일 `1/2` crop은 전체 품질 증거로 사용할 수 없다. 재현 보고서는 ignored `generated/ocr_accuracy_rerun_20260829.{json,md}`에 둔다.

## 공개 데이터 선택표

| 우선순위 | 데이터 | 적합한 용도 | 조건·주의 | 결정 |
|---:|---|---|---|---|
| 1 | [AI Hub 교육 자료 OCR](https://www.aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&currMenu=115&dataSetSn=71300&topMenu=100) | 한국 초·중·고 손글씨, 답안지 도메인 적응 | 승인 데이터의 이용조건·출처 표시 의무 준수 | 이용 승인 완료, 고2 우선 적용 |
| 2 | [AI Hub 수학 풀이과정 손글씨](https://www.aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&currMenu=&dataSetSn=71716&topMenu=) | 분수·루트·수식 crop 보강 | 가입·승인 및 스키마 변환 필요 | 수식 holdout과 함께 도입 |
| 3 | [NIST EMNIST](https://www.nist.gov/itl/products-and-services/emnist-dataset) | 숫자 필체 다양화, 범위 밖 문자 reject | 한국 학생 필체·답안지 촬영 도메인과 차이가 큼 | 적용 완료 |
| 4 | [UniMER-1M](https://huggingface.co/datasets/wanderkid/UniMER_Dataset/blob/main/README.md) | 인쇄·손글씨 수식 사전학습 | 현재 UniMERNet 가중치가 이미 이 계열 데이터로 학습됨. HME100K 일부는 별도 저작권 절차 필요 | 가중치 재사용, 전체 재학습 보류 |
| 5 | [HASYv2](https://zenodo.org/records/259444) | 단일 수학기호 reject/보조 분류 | ODbL 의무, 완성 수식 인식 데이터가 아님 | 선택적 보조 후보 |
| 제외 | [MathWriting](https://github.com/google-research/google-research/blob/master/mathwriting/archive_readme.md) | 온라인 손글씨 수식 | CC BY-NC-SA라 학원 상용 운영에 자동 반입하지 않음 | 기본 제외 |
| 보류 | [DiffMath](https://github.com/awei669/DiffMath) | 합성 손글씨 수식 생성 | 논문은 유망하지만 현재 저장소가 code/data 공개 전 상태 | 공개 후 재검토 |

AI Hub는 [공식 AIHub Shell 안내](https://www.aihub.or.kr/devsport/apishell/list.do)에 따라 계정·승인·API key가 준비된 뒤 dataset/file key 단위 다운로드를 자동화할 수 있다. 로그인 정보나 key를 저장소에 넣지 않는다.

승인된 파일을 내려받은 뒤에는 공식 Training split만 다음 변환기에 넣는다. 공개 Test split을 학습에 섞지 않는다.

```powershell
python -B -m scripts.import_aihub_education_choice_dataset `
  --labels <AIHUB_TRAIN_LABEL_ROOT> `
  --images <AIHUB_TRAIN_IMAGE_ROOT> `
  --output C:\server-ocr\datasets\aihub_education_choice_train `
  --max-choice-per-writer 8 `
  --max-reject-per-writer 16
```

생성된 학년별 폴더를 `scripts.train_student_test_choice_classifier --aihub-root <H_G1_OUTPUT> --aihub-root <H_G2_OUTPUT> ...`처럼 추가하면 전체 pool의 클래스 균형·증강·학년별 provenance 기록까지 기존 학습 흐름에서 처리한다. 변환기는 공식 `Images.identifier`, `Images.type`, `Bbox[].data`, `Bbox[].x/y`만 읽고 정답키 필드는 사용하지 않는다.

주관식 변환·프로필 생성은 다음 순서다.

```powershell
python -B -m scripts.import_aihub_education_formula_dataset `
  --grade H_G2 `
  --labels <H_G2_TRAIN_LABEL_ROOT> `
  --images <H_G2_TRAIN_IMAGE_ROOT> `
  --output <FORMULA_CONVERTED_H_G2> `
  --max-per-writer 200

python -B -m scripts.build_student_test_formula_profile_dataset `
  --profile m3_h1 `
  --grade-root M_G3 <FORMULA_CONVERTED_M_G3> `
  --grade-root H_G1 <FORMULA_CONVERTED_H_G1> `
  --output <FORMULA_PROFILE_M3_H1>
```

공식 UniMERNet의 `images/0000000.png + equations.txt` 형식으로 생성하며 학년별 수를 같게 만들지 않는다. 설정 생성기와 학습 실행기는 annotation·연속 이미지 파일의 실제 개수/내용 SHA-256·base weight SHA-256·CUDA를 검증한다. 이미지가 없거나 입력이 바뀌면 학습을 거부한다. 이 검사는 이미지 decode 품질이나 라벨 정답성까지 보증하지 않는다. 과거 count-only manifest는 새 설정 생성기로 다시 생성해야 한다.

Windows는 single-config subprocess, 그 외는 단일 GPU `torchrun`을 사용한다. 기본 DataLoader worker는 0이며 upstream optimizer registry와 비분산 barrier 호환을 실행기에 보존했다. 이번 로컬 검증은 계약/회귀 테스트이며 새 CUDA 경로의 실제 학습 검증은 다음 GPU 호스트에서 수행한다. 반환 산출물은 `checkpoint_best.pth`를 필수로 선택하고 latest로 몰래 대체하지 않는다. 현재 CPU 호스트에서는 weight update를 하지 않는다. 새 manifest를 생성한 NVIDIA 호스트에서 다음처럼 두 프로필을 순차 실행한다.

```powershell
C:\server-ocr\.venv-unimernet\Scripts\python.exe -B -m scripts.train_student_test_formula_profiles `
  --config C:\server-ocr\training_configs\unimernet_m3_h1.yaml `
  --config C:\server-ocr\training_configs\unimernet_m3_h1_h2_h3.yaml
```

## 사용자 라벨 작업을 최소화하는 순서

1. MNIST·EMNIST처럼 라벨이 이미 있는 데이터는 공식 loader로 내려받아 바로 학습한다.
2. AI Hub 승인 후 원본과 annotation을 그대로 내려받고, annotation이 한 글자 `1`~`5`인 crop만 positive로 추출한다.
3. 한 작성자가 학습을 독점하지 않도록 작성자·라벨별 상한을 적용한다. 학년별 표본 수는 강제로 같게 만들지 않는다.
4. `0·6·7·8·9`, 문자, 두 글자 이상, 지워 쓴 답, 수식은 `__reject__`로 자동 변환한다.
5. 배경색·선 굵기·흐림·원근·밝기 변형을 답안지 전처리 뒤의 48×48 분포에 맞춰 합성한다.
6. 운영 중 학생이 직접 수정한 1~3개 불확실 문항은 바로 재학습하지 않는다. 7일 삭제 규칙과 개인정보·분리 holdout 정책을 만족하는 별도 승인 corpus만 사용한다.
7. 사람 작업은 새 라벨 대량 생성이 아니라, 서로 다른 필체로 구성된 최종 holdout의 표본 감사에만 집중한다.

## 품질 gate

- 필체 단위로 train/validation/holdout을 분리한다. 같은 답안지의 회전·밝기 변형을 다른 split에 넣지 않는다.
- 각 `1`~`5`마다 holdout 20개 이상, reject 20개 이상을 확보한다.
- 신뢰도 0.995, margin 0.90, 두 전처리 variant 합의 기준을 낮추지 않는다.
- 자동 수락 오인식 0건, 객관식 coverage 98% 이상, reject recall 98% 이상을 요구한다.
- 독립·동일분포 이항 시행 가정에서 무오류 `n`건의 단측 95% 오류율 상한은 `1 - 0.05^(1/n)`이며 1% 이하의 산술 최소값은 299다. 같은 작성자의 여러 문항/사진은 독립 시행으로 간주할 수 없으므로 **299 crop 또는 26명만으로 충분하다는 뜻이 아니다**. 작성자 군집 검토와 실제 운영 분포 검토를 별도로 통과해야 한다.
- 숫자 `metrics.json:GO`는 필요조건일 뿐 충분조건이 아니다. `core/student_test_ocr_readiness.py`가 소유하는 `student_test_ocr_deployment_evidence_v1` 계약으로 choice/두 수식 경로의 검토 증거, 표본별 전사 확인·분리, sheet 속도/재촬영/보류 지표, 현재 모델·tokenizer·전처리 파일·정책 해시까지 함께 확인한다. 경로당 299건 무오류는 보수적 사전 심사선이며 통계적 안전 보증이 아니다. 수식 경로의 coverage는 보고하고, 98% 고정 gate는 객관식에만 적용한다.
- `STUDENT_TEST_OCR_DEPLOYMENT_EVIDENCE`의 기본 경로는 `C:\server-ocr\deployment_evidence.json`이다. 사람이 검토한 증거 계약이며 JSON의 자기선언 자체를 독립 검증으로 보지 않는다. 현재 GO 파일은 생성하지 않았다.

## 현재 평가의 신뢰도 한계

과거 사람 전사 crop의 라벨 작성·설계·검토는 같은 Codex 시각 검토 흐름이다. 실험별 필체 분리 여부와 별개로 동일 labeler pool 편향이 남고 여러 번 모델 선택에 사용한 사진은 untouched holdout이 아니다. 현재 수치는 회귀 진단에만 쓰며 운영 `GO`의 독립 ground truth로 쓰지 않는다. 새 v4 답안지 실제 필체 데이터는 아직 없다.

최종 gate에서는 답안 작성자 또는 실험 설계와 무관한 판독자가 OCR 출력과 정답키를 보지 않은 채 실제로 적힌 값을 먼저 확정하고, 전사 파일 hash를 고정한 뒤 모델을 실행한다. 이 작업은 매 제출마다 하는 교사 확인이 아니라 rollout 전 한 번의 표본 감사다.

지정값을 베껴 쓰게 하더라도 지시값과 실제 필기는 다를 수 있다. 지정 답안표를 사진 확인 없이 정답 라벨로 사용하지 않는다. 같은 종이를 두 번 찍은 사진은 반드시 같은 split에 두며, calibration용 작성자와 최종 평가용 작성자를 분리한다. 수집 인원은 예비 결과와 군집 단위 불확실성을 보고 정한다.

## 다음 GPU 실험과 출시 순서

1. 상위 과목의 기존 best(4,000 iteration) 체크포인트를 회수해 현재 반환 latest(5,000)와 같은 고정 진단 입력으로 비교한다. 하위는 반환 로그상 best가 5,000이다. 기존 가중치와 변환 이미지/provenance는 삭제하지 않는다.
2. 새 이미지 제작 없이 공식 Training에서 짧은 수치 답안 후보를 만든다. 프로필 생성기의 `--numeric-answers-only`는 기존 숫자값 문법으로 라벨을 선별하며 `1~5`도 포함한다. 기존 전체 수식 학습과 숫자·분수·루트 중심 학습을 비교하고, 한쪽을 사전 승자로 선언하지 않는다.
3. 공식 Validation에서 `--exclude-writers-from <TRAIN_PROFILE>`로 Training 작성자를 뺀 평가 프로필을 만든다. 이 배제는 기존 `grade:writer` 기반 `writerHash` 범위이며 학년 간 동일 인물까지 증명하지 않는다. 두 프로필의 학년 구성은 사용자 결정대로 고정한다. 학년·표현 종류별 숫자값 동치율/전사 일치율/실패율을 별도로 기록한다.
4. 전처리 3종 비교는 후속 실험에서 완료했다. 수식은 원본, 객관식은 기존 보정 경로를 채택하고 테두리 제거 후보는 기각했다. 근거와 제한은 [무료 OCR 실행 결과](STUDENT_TEST_FREE_OCR_RESULTS_2026-09-06.md)에 둔다. 학습량·전처리·confidence를 동시에 바꾸지 않으며 실제 20문항 지연시간은 별도로 확인한다.
5. 공공 데이터에서 후보가 개선된 뒤 v4 실카메라 calibration과 별도 최종 holdout을 수집한다. threshold를 그 holdout으로 고르지 않는다. 토큰 score 0.995를 99.5% 정답 확률로 해석하지 않는다.
6. 출시 전 20문항 end-to-end/대기열/재시작 복구와 실제 당일 보류 처리 절차를 확인한다. 7일 보관·지난 보류의 정기 호출 소스와 격리 실패 검증은 3단계에서 구현했지만 **7일 자동 삭제 운영은 미적용**이다. 모델 수신·전체 촬영 지연·독립 품질 gate와 운영 migration·유지보수·기능 활성화는 별도로 완료해야 한다.

## 재현 경계

- 학습기: `scripts/train_student_test_choice_classifier.py`
- worker: `scripts/student_test_choice_worker.py`
- 학습 계약 검증: `python -B -m scripts.verify_student_test_choice_training`
- AI Hub 변환 검증: `C:\server-ocr\.venv-unimernet\Scripts\python.exe -B -m scripts.verify_student_test_aihub_import`
- AI Hub 수식 변환·프로필 검증: `C:\server-ocr\.venv-unimernet\Scripts\python.exe -B -m scripts.verify_student_test_aihub_formula_import`
- AI Hub 학년별 split 검증: `python -B -m scripts.verify_student_test_aihub_validation`
- AI Hub 객관식 학년별 모델 검증: `python -B -m scripts.verify_student_test_aihub_choice_validation`
- AI Hub 분할 archive 검증: `python -B -m scripts.verify_aihub_split_archive_unpack`
- UniMERNet 학습 설정 검증: `python -B -m scripts.verify_student_test_formula_training_config`
- UniMERNet 순차 학습 실행기 검증: `python -B -m scripts.verify_student_test_formula_profile_training`
- worker 계약 검증: `python -B -m scripts.verify_student_test_ocr_worker_contracts`
- Paddle 보조 신호 비교: `scripts/benchmark_student_test_choice_supporters.py`
- 전체 로컬 정확도 재추론: `scripts/benchmark_student_test_local_ocr_accuracy.py`

학습기는 `answers[]` 전사 문서와 과거 품질 실험의 `items[].human_answer` 전사 문서를 모두 읽는다. 후자에 `expected` 정답키가 함께 있어도 `human_answer`, `human_confidence`, `question_no`, `notes`만 정규화해 사용한다.
