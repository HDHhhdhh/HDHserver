# 학생 시험 OCR 공개 데이터·학습 운영 메모

**상태:** 연구·파일럿 전용. 운영 모델 교체나 기능 플래그 활성화를 승인하지 않는다.

## 결론

- 객관식 숫자 1~5는 공개 숫자 데이터로 기본 필체 범위를 넓히고, 실제 답안지와 다른 문자·다중 숫자는 `__reject__`로 학습한다.
- 한국 학생의 답안지 필체에 가장 가까운 공개 후보는 AI Hub 교육 자료 OCR 데이터다. 계정 가입, 데이터 이용 신청, API key 발급은 한 번 필요하지만 승인 뒤 다운로드·변환·재학습은 자동화할 수 있다.
- 고1·고2·고3 객관식은 공용 모델 하나로 합친다. 학년별 양을 억지로 같게 만들지 않고 작성자와 숫자 클래스 쏠림만 제어하며, 평가는 학년별로 분리한다.
- 수식은 UniMERNet 사전학습 가중치에서 시작하되 AI Hub 교육 OCR의 `Bbox.type == 2` 수식 crop으로 두 개의 과목 프로필을 미세조정한다. `공통수학1·2`용은 `M_G3+H_G1`, 상위 과목용은 `M_G3+H_G1+H_G2+H_G3`를 사용한다.
- 인터넷 데이터만으로 운영 정확도를 선언하지 않는다. 정답키가 아닌 독립 사람 전사 holdout에서 오수락 0건과 통계 gate를 함께 통과해야 한다.

## 적용 완료

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

2026-08-29 고2 Training 적용 결과는 작성자 184명, 수식 crop 5,213개다. 이 중 분수 214개, 루트 23개, 단순 수 187개이며 작성자당 200개 상한으로 13,220개 쏠림 후보를 제외했다. 같은 원천에서 객관식은 `1/2/3/4/5 = 186/175/139/114/83`, reject 19,416개를 만들었다. 이는 학습 입력 확보 상태일 뿐 운영 성능 판정이 아니다.

원천 이미지를 받기 전 공식 라벨만 검사한 수식 분포는 다음과 같다. `상한 후 후보`는 작성자당 200개를 적용한 값이며 실제 crop 수는 작은/잘못된 box 제외로 조금 줄 수 있다.

| grade root | Training 수식 box | 작성자 | 상한 후 후보 | 공식 Validation 수식 box |
|---|---:|---:|---:|---:|
| `M_G3` | 17,804 | 207 | 9,810 | 9,187 |
| `H_G1` | 22,453 | 228 | 8,629 | 2,408 |
| `H_G2` | 18,448 | 184 | 5,228 | 1,280 |
| `H_G3` | 12,009 | 163 | 6,078 | 866 |

2026-08-29 라벨 split 감사에서 Training과 Validation의 `Images.identifier` 중복은 네 학년 모두 0건이었지만 작성자 ID는 일부 겹쳤다. 따라서 공식 Validation 전체 점수와 별도로, 객관식은 네 학년 Training 전체에 한 번도 등장하지 않은 작성자만, 수식은 해당 프로필의 Training 전체에 한 번도 등장하지 않은 작성자만 추린 `strict` 지표를 함께 기록한다. `scripts.audit_student_test_aihub_validation`이 이 경계를 검사한다. 이 검사는 라벨·split 무결성 증거이며 모델 정확도 증거가 아니다.

현재 라벨만으로 계산한 객관식 strict 표본의 가장 작은 숫자 클래스는 `M_G3/H_G1/H_G2/H_G3 = 59/10/2/4`개다. 특히 고1·고2·고3은 학년별 클래스당 20개 gate를 만족하지 못하므로, 공식 AI Hub 학년별 수치는 보조 진단으로만 사용하고 운영 GO는 별도 실제 답안지 필체 holdout으로 판정한다.

첫 공개 데이터 파일럿 `choice_digit_v4`는 분리 holdout 20문항에서 raw 75%, 객관식 자동 수락 12/18, reject 2/2였으나 고신뢰 `3 → 2` 오수락 1건이 발생했다. 따라서 `NO_GO`이며 운영 기본값은 안전했던 v3에서 바꾸지 않았다. PaddleOCR 교차합의도 같은 crop에서 신뢰 판정 0건이라 운영하면 자동 수락을 전부 없애므로 사용하지 않는다.

기존 실제 필체 한 장을 추가 적응한 보수판은 raw 80%, 자동 수락 10/18, 오수락 0건, reject 1/2였다. 기존 사람 전사 3장을 섞은 판은 12/18 수락으로 회복했지만 같은 고신뢰 오수락 1건이 다시 나타났다. 공개 범용 숫자 데이터만 늘리는 방식으로는 운영 개선이 확인되지 않았다.

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

공식 UniMERNet의 `images/0000000.png + equations.txt` 학습 형식으로 생성하며, 프로필 병합은 grade별 수를 같게 만들지 않는다. `scripts.generate_student_test_formula_training_config`가 기존 `unimernet_tiny.pth`에서 시작하는 CUDA 미세조정 설정을 만든다. 현재 내장 GPU 호스트에서는 데이터만 준비하고 학습을 실행하지 않는다. NVIDIA CUDA 호스트로 이동한 뒤 공식 `train.py --cfg-path <CONFIG>` 경로를 사용한다.

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
- 오수락 0건이어도 자동 수락 표본에서 오류율의 단측 95% 상한이 1% 이하여야 한다. 이 조건만으로도 최소 299건의 무오류 자동 수락이 필요하다.
- 모델의 `metrics.json`이 `GO`가 아니면 일반 runtime에서 로드하지 않는다.

## 현재 평가의 신뢰도 한계

현재 holdout 답안지는 학습 필체와 분리되어 있고 정답키 대신 보이는 글자를 전사했지만, 그 전사를 만든 주체와 실험을 설계·검토한 주체가 같은 Codex 시각 검토 흐름이다. 따라서 `verifier = designer`와 동일 labeler pool 편향이 남는다. 현재 수치는 모델 비교용 진단으로는 쓰되 운영 `GO`의 독립 ground truth로 쓰지 않는다.

최종 gate에서는 답안 작성자 또는 실험 설계와 무관한 판독자가 OCR 출력과 정답키를 보지 않은 채 실제로 적힌 값을 먼저 확정하고, 전사 파일 hash를 고정한 뒤 모델을 실행한다. 이 작업은 매 제출마다 하는 교사 확인이 아니라 rollout 전 한 번의 표본 감사다.

## 재현 경계

- 학습기: `scripts/train_student_test_choice_classifier.py`
- worker: `scripts/student_test_choice_worker.py`
- 학습 계약 검증: `python -B -m scripts.verify_student_test_choice_training`
- AI Hub 변환 검증: `C:\server-ocr\.venv-unimernet\Scripts\python.exe -B -m scripts.verify_student_test_aihub_import`
- AI Hub 수식 변환·프로필 검증: `C:\server-ocr\.venv-unimernet\Scripts\python.exe -B -m scripts.verify_student_test_aihub_formula_import`
- AI Hub 학년별 split 검증: `python -B -m scripts.verify_student_test_aihub_validation`
- AI Hub 분할 archive 검증: `python -B -m scripts.verify_aihub_split_archive_unpack`
- UniMERNet 학습 설정 검증: `python -B -m scripts.verify_student_test_formula_training_config`
- worker 계약 검증: `python -B -m scripts.verify_student_test_ocr_worker_contracts`
- Paddle 보조 신호 비교: `scripts/benchmark_student_test_choice_supporters.py`
- 전체 로컬 정확도 재추론: `scripts/benchmark_student_test_local_ocr_accuracy.py`

학습기는 `answers[]` 전사 문서와 과거 품질 실험의 `items[].human_answer` 전사 문서를 모두 읽는다. 후자에 `expected` 정답키가 함께 있어도 `human_answer`, `human_confidence`, `question_no`, `notes`만 정규화해 사용한다.
