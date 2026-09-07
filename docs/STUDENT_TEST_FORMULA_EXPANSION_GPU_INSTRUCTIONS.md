# 무료 OCR 데이터 확대 GPU 실행 지시문 · 2026-09-07

## 목표와 권한

기존 NVIDIA GPU 컴퓨터의 UniMERNet 환경에서, 패키지에 실제 포함된 공개 AI Hub 파생 crop/전사를 사용하여 두 curriculum profile의 데이터 확대 비교 실험을 완료한다. 준비만 하고 멈추지 말고, 아래 사전 검사가 통과하면 승인된 학습·평가·반환 자료 제작·원래 비공개 Drive 폴더 업로드까지 진행한다. 문제가 생긴 항목만 차단으로 기록하고 독립 작업을 계속한다.

유료 API/외부 OCR 예산 0. providerCallCount:0, deploymentReady:false를 유지한다. 이 패키지는 운영 서버 백업, 원천 AI Hub 전체 데이터, 가상환경, 모델 weight 묶음이 아니다. 실제 이미지·전사·provenance·고정 validation·코드·architecture/tokenizer 네 파일은 포함한다. 기존 CUDA 환경과 아래 SHA로 고정한 원래 pretrained weight는 GPU 컴퓨터에 있어야 한다. 없으면 해당 학습만 차단하고 임의 다른 weight나 유료 서비스로 대체하지 않는다. 새 환경 설치도 승인 범위에 없다.

기존 코드·데이터·checkpoint·이전 GPU 실험·운영 DB를 삭제/덮어쓰기하지 않는다. 운영 모델 복사, 기능 활성화, 서버 중지/재시작은 금지한다. 객관식 1~5 모델은 변경하지 않는다. 이번 범위는 주관식 수식 OCR 실험이다.

## 1. 수신과 폴더

이 지시문 앞의 전달 표에 있는 실제 Drive 링크에서 원본 ZIP과 독립 transport helper를 다운로드한다. Drive metadata에서 이름/타입/크기/부모를 확인한다. 저장형 ZIP은 원본 다운로드만 사용하고 문서 export/텍스트 추출로 대체하지 않는다. 인증 실패 시 공유 설정을 변경하지 않는다.

`C:/server-ocr`가 없으면 생성한다. 그 안의 **존재하지 않는 새** `formula_expansion_20260907_01` 작업 폴더를 선택한다. 이미 있으면 숫자 suffix를 올린다. 이하 `WORK`는 이 폴더, `PACKET`은 `WORK/packet`, `CODE`는 `PACKET/code`다. 시스템 HOME/CODEX_HOME 변수는 재정의하지 않는다. 외부 receipt에 있는 다른 컴퓨터 원본 경로는 이 컴퓨터 경로로 해석하지 않는다.

입력 보관/추출/8회 학습 checkpoint와 반환 사본을 위해 **최소 60 GiB 빈 공간**을 확인한다. 기존 동일 architecture의 실제 학습 checkpoint가 약 1.29 GB보다 크면 `checkpoint 크기 × 40 + 8 GiB`와 60 GiB 중 큰 값으로 상향한다. 이 계산은 stage별 best/latest/milestone 파일, B 후보 네 개의 반환 사본, ZIP·parts·재조립 검증 사본을 모두 보존하는 조건이다. 부족하면 기존 파일을 지우지 말고 차단한다. 학습 시작 전과 반환 묶음 제작 전에도 남은 공간을 확인한다.

ZIP과 helper의 바이트 수 및 SHA-256을 전달 표의 값과 대조한다. 하나라도 다르면 사용하지 말고 실제/기대값을 기록한다. 이번 입력은 업로드 도구의 파일당 100 MiB 제한 때문에 **80 MiB 이하 part 3개**로 제공한다. parts manifest와 각 part를 원본 그대로 같은 새 downloads 폴더에 받은 뒤, 먼저 독립 helper 내용을 읽고 `join --manifest <ARCHIVE_PARTS.json> --output <새 ZIP>`으로 재조립한다. 전체 크기/해시 일치 후 다음 명령으로 안전 추출한다. Python은 이미 설치된 `C:/server-ocr/.venv-unimernet/Scripts/python.exe`를 우선 사용한다.

```powershell
& $ocrPython $transportHelper extract --archive $verifiedZip --output $packetPath --bytes $expectedBytes --sha256 $expectedSha256
```

변수는 전달 표의 검증된 실제 파일/값으로 설정한다. helper는 절대경로, `..`, Windows drive/ADS, 링크, 대소문자 중복 목적경로, 파일/폴더 충돌을 거부하고 새 폴더 안으로만 추출한다. 검사 실패 시 보안 제한을 우회하지 않는다.

`PACKET_MANIFEST.json`의 **모든 files 항목**을 path/bytes/SHA로 확인한다. 실제 일반 파일 수는 `fileCountExcludingManifest + 1`이어야 한다. manifest 밖 파일/중복/외부 링크도 거부한다. 입력 전체를 불변 snapshot으로 취급하고 학습 산출물을 PACKET 안에 쓰지 않는다. 검증 도중 생성되는 Python 캐시는 패키지 밖 `WORK/pycache`로 PYTHONPYCACHEPREFIX를 설정한다.

## 2. 데이터와 기준선

실제 개수·학년·해시·stage 예산의 권위 있는 입력은 `data/EXPANSION_INPUTS.json`이다. 제외 근거는 `data/SELECTION_AUDIT.json`이다.

- 공통수학 `m3_h1`: 중3+고1. expanded **1,922**개 = focused **967**개 + auxiliary **955**개.
- 상위 `m3_h1_h2_h3`: 중3+고1+고2+고3. expanded **3,245**개 = focused **1,757**개 + auxiliary **1,488**개.
- focused는 기존 숫자식 문법에 곱셈/나눗셈/명시적 제곱근 표기의 선택용 alias를 추가한 것이다. 라벨은 원래 전사를 그대로 보존했다.
- auxiliary는 숫자가 포함된 완전한 짧은 수식/등식이다. 변수 포함 보조 수식은 OCR 구조 학습용이지 운영에서 변수 답안을 지원한다는 뜻이 아니다. 단독 `=`, 잘린 지수, 알 수 없는 명령 등은 제외했다.
- 전체 converted Training 29,247개 중 26,001개는 이 문법 범위 밖이다. 학습 이미지 육안 대조 중 지수/등호 전사 불일치가 발견된 1개도 라벨 수정 없이 제외했다. 전체 라벨을 사람이 검증한 것은 아니다.
- converted pool에는 기존 작성자당 cap 200 등이 적용돼 있다. 이 패키지를 원천 Training 전체라고 부르지 않는다. 이미지 복제로 새로운 고유 표본 수를 부풀리지 않았다.
- validation은 기존 파일 바이트 그대로: 공통 1,459 crop/3 writer hash, 상위 1,473 crop/6 writer hash. 중3 1,332 + 고1 127 + 상위에만 고2 14. 고3 0.
- 새 Training 전체와 validation 사이의 grade-scoped writer hash/source hash/정확한 이미지 SHA 교집합을 다시 검사했다. 신원과 near-duplicate 독립성이 완전히 입증된 것은 아니다. 동일인의 학년 간 관계도 알 수 없다.

원래 pretrained base는 `PREREQUISITES.json`의 크기와 다음 SHA가 모두 맞아야 한다.

`6f7608624e2d7549c7f0f05fcfbe073ae521328cf70f1d46374d96f9881d7371`

권장 위치: `C:/server-ocr/models/unimernet_tiny/unimernet_tiny.pth`. 이름이나 latest/best 문자열만으로 대체하지 않는다. 두 profile의 두 전략 모두 이 **동일 원본 base**에서 시작한다. architecture/tokenizer는 PACKET/model의 네 파일을 사용한다. 그 파일들을 운영 모델 디렉터리에 덮어쓰지 않는다.

2026-09-06 focused1000 결과는 별도 역사적 비교 후보다. 이 서버에서는 3.9 GB 반환 ZIP을 끝까지 받지 못했으므로 그 checkpoint 바이너리는 미검증 상태다. 이번 ZIP에도 없다. GPU 컴퓨터에 해당 후보가 남아 있을 때만 아래 정확한 SHA를 확인하여 별도 비교 평가한다. 없으면 선택 비교 2건을 미실행으로 기록하고 핵심 실험은 계속한다.

- 공통 focused1000: `f4e64c53b1a32ae77ceec32053660430ae5cd27f764850256eb271fcdfda9bf0`
- 상위 focused1000: `233c0f0917fecedc2bd4a9d943318a4b20f8f143053f84508b2e0c5f11aed855`

이전 full/focused 숫자 동치 결과(문서/receipt상)는 공통 1205→1354/1459, 상위 1232→1355/1473이었다. 새 focused pool은 약간 넓어졌고 예산/seed도 다르므로, 이전 점수와의 차이를 데이터 확대의 단독 인과 효과라고 주장하지 않는다. 인과 비교는 이번 같은 예산의 두 전략 사이에서만 한다.

## 3. 환경·학습 전 검사

이미 설치된 PyTorch의 CUDA available, GPU 이름/VRAM, Python/PyTorch/UniMERNet 버전, 실행 코드 SHA를 기록한다. CUDA 불가 시 CPU 학습으로 우회하지 않는다. HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, NO_ALBUMENTATIONS_UPDATE=1로 네트워크 다운로드를 차단한다. 외부 OCR/API 호출 금지.

CODE를 작업 디렉터리로 사용하고 다음 순수 검사부터 수행한다.

```powershell
& $ocrPython -m scripts.verify_student_test_formula_expansion
& $ocrPython -m scripts.verify_student_test_gpu_archive
& $ocrPython -m scripts.verify_student_test_formula_training_config
& $ocrPython -m scripts.verify_student_test_formula_profile_training
```

각 dataset의 실제 이미지 수/순차 index/전사 줄 수/provenance와 manifest 해시를 대조한다. validation을 재필터하거나 전사를 고치지 않는다. 기존 grader/evaluator 코드도 바꾸지 않는다. 라벨 tokenizer 길이 분포와 train processor 적용 후 전사가 달라지는 표본 수를 보고한다. 자동으로 전사를 고치거나 삭제하지 않는다. 데이터 로더가 파일 오류를 다른 표본으로 대체한 경우 횟수를 기록하며, 고유 소비 표본 수를 관찰하지 않았으면 추정값으로만 표시한다.

## 4. 사전에 고정한 2단계 비교

seed **20260907**, batch **4**, accum **2**, num_workers **0**, 동일 모델/해상도/augmentation/optimizer/LR 설정을 유지한다. `generate_student_test_formula_training_config.py`의 기존 설정을 사용한다. OOM이면 한쪽만 batch를 줄이거나 짧게 돌리지 말고 해당 paired comparison을 차단한다. 하이퍼파라미터 탐색/추가 반복은 이번 범위 밖이다.

| profile | 전략 | A 데이터 | A microbatch | B 데이터 | B microbatch |
|---|---|---|---:|---|---:|
| m3_h1 | focused_control | focused | 2,000 | focused | 1,000 |
| m3_h1 | expanded_curriculum | expanded | 2,000 | focused | 1,000 |
| m3_h1_h2_h3 | focused_control | focused | 3,000 | focused | 1,000 |
| m3_h1_h2_h3 | expanded_curriculum | expanded | 3,000 | focused | 1,000 |

총 **4개 전략/profile 조합, 8회 stage 학습**. 공통은 조합당 3,000 microbatch/약 12,000 image exposure, 상위는 4,000/약 16,000이다. accum2를 exposure에 다시 곱하지 않는다. 같은 microbatch는 같은 GPU 시간/토큰 계산량을 뜻하지 않으므로 stage별 실제 시간도 기록한다.

A는 각 전략 모두 동일 pretrained에서 시작한다. B는 해당 A의 **고정된 마지막 iteration checkpoint_latest.pth**에서 model weight를 가져온다. A의 validation-best를 B 초기값으로 쓰지 않는다. 양쪽 B 모두 optimizer/LR/scaler를 새로 시작하는 fine-tuning이며 `resume_ckpt_path:null`이다. A 최신 파일을 best로 이름만 바꾸지 않는다. B의 최종 반환 후보는 로그로 실제 iteration이 입증된 B checkpoint_best.pth다.

각 조합을 순차 실행한다. 새 경로 `WORK/configs/<profile>/<strategy>/<stage>.yaml`, `WORK/runs/<profile>/<strategy>/<stage>`만 사용한다. 모든 출력 경로가 없음을 먼저 검사한다. 기존 config generator는 파일을 덮어쓸 수 있으므로 이 사전 조건을 생략하지 않는다.

단계별 명령 형식:

```powershell
& $ocrPython -m scripts.generate_student_test_formula_training_config --profile $profile --train-dataset $trainPath --validation-dataset $validationPath --base-model-dir $packetModel --base-weight $stageInputWeight --output-config $newConfig --output-dir $newRunRoot --max-iters $stageBudget --batch-size 4 --accum-grad-iters 2 --num-workers 0 --seed 20260907
& $ocrPython -m scripts.train_student_test_formula_profiles --config $newConfig --preflight-only
& $ocrPython -m scripts.train_student_test_formula_profiles --config $newConfig
```

각 명령의 exit code를 확인하고 stdout/stderr를 새 로그에 저장한다. preflight가 실패하면 그 config로 학습하지 않는다. 동일 profile의 여러 config를 한 invocation에 넣지 않는다. subprocess 완료 출력의 실제 run path를 사용하며 폴더명으로 iteration을 추정하지 않는다.

A 종료 후 학습 로그/receipt와 checkpoint SHA를 대조한다. 이미 설치된 PyTorch로 CPU `weights_only=True`를 사용해 `iters` metadata를 확인할 수 있다. A의 actual iters가 위 고정 budget과 다르면 B를 시작하지 않는다. 안전 metadata 로드가 호환되지 않을 때 `weights_only=False`로 임의 우회하지 말고, 명시적인 final-iteration 저장 로그와 저장 직후 해시를 별도 근거로 기록하거나 모호하면 차단한다. B도 actual best iteration을 로그와 metadata로 기록한다. B의 1,000은 B-local iteration이며 A+B 누적 수와 구분한다.

## 5. 고정 validation 평가와 후보 선택

필수 평가 **6개**: 원래 base × 두 profile, 새 B focused_control best × 두 profile, 새 B expanded_curriculum best × 두 profile. 선택 평가 최대 **2개**: SHA가 맞는 이전 focused1000 × 두 profile. 존재하지 않는 이전 report/JSONL을 새로 검증했다고 쓰지 않는다. 같은 model SHA/dataset/evaluator 조건이 완전히 같을 때만 실제 prediction hash 증거와 함께 중복 평가를 생략한다.

기존 evaluator를 변경 없이 사용한다. 모델 구조는 PACKET/model, weight는 검증한 절대경로로 전달한다. `--weight` 절대경로는 Path 결합에서 model directory 밖의 해당 파일을 가리킨다. 출력은 각각 새 `WORK/evaluations/<profile>/<candidate>`다.

```powershell
& $ocrPython -m scripts.evaluate_student_test_formula_dataset --dataset $validationPath --model-dir $packetModel --weight $verifiedWeight --output $newEvaluation --device cuda
```

생성 상한 **64 token**, deterministic generation, EOS 존재 AND tokenCount<64를 유지한다. EOS가 있어도 cap 도달이면 생성 실패다. 분모는 항상 1459/1473이다. 오류/빈 출력/미종료를 제거하지 않는다. numericCorrect와 textExact를 분리하고 전체 숫자 실패는 전체 분모−numericCorrect로 산출한다. 숫자 실패와 생성 실패는 겹칠 수 있어 단순 합산 금지.

report.json과 predictions.jsonl을 모두 보존하고 행 수, index 0..N−1 완전성/중복, 각 grade/writer, generation failure 합계를 다시 대조한다. source/eval 코드·dataset·prediction·모델 SHA를 기록한다. writer hash는 grade-scoped라는 제한을 유지한다.

각 profile에서 expanded를 추천하려면 이번 focused_control 대비 numericCorrect가 **엄격히 증가**, 전체 textExact/각 grade·writer numericCorrect·textExact가 감소하지 않음, generation failure 증가 없음이 모두 필요하다. 통과하지 않으면 확대 효과 미입증으로 기록하고 자동 선택하지 않는다. 최종 B 후보 네 개는 결과와 무관하게 모두 보존한다. 이전 focused1000이 새 후보보다 좋으면 그 사실도 따로 보고한다. 위 규칙은 development 후보 추천일 뿐 운영 GO가 아니다.

이 validation은 이전에도 모델 선택에 사용한 공개 개발 세트다. 독립 미사용 holdout/실카메라/학생 calibration이라고 부르지 않는다. 고2 14개, 고3 0개라는 제한 때문에 고2 일반화나 고3 정확도를 주장할 수 없다. 실제 촬영/미사용 작성자 검증 없이는 최종 학습 완료·자동 채점 출시·운영 GO를 주장하지 않는다.

## 6. 결과 증거와 분할 반환

새 `WORK/return_evidence/RETURN`에 README, COMPARISON.md/json, evaluation_index.json, 전체 report/predictions JSONL, 실제 configs+manifest, logs, audit, PREREQUISITES, 입력 PACKET_MANIFEST 사본, architecture/tokenizer 네 파일, RETURN_RECEIPT.json을 모은다. 원본 파일을 이동하지 말고 새 사본을 만든다. 큰 model weight는 이 evidence 폴더에 넣지 않는다.

receipt에는 다음을 기록한다: 입력 Drive ID/링크/수신시각·ZIP크기/SHA·inventory 검사, dataset와 prediction hashes, 학습 8건의 성공/실패/미실행, 필수 평가 6건과 선택 평가 2건을 분리한 상태, stage base/최종 checkpoint 원본 경로/반환 경로/strategy/profile/actual iteration/size/SHA, architecture 네 파일 연결, 선택 근거와 한계, paid/provider 0, deploymentReady:false. copiedFiles는 receipt를 제외한 실제 반환 파일만 열거하고 receipt 자신의 size/SHA는 외부 archive receipt에 기록한다. 입력 PACKET_MANIFEST는 반환 inventory가 아니다.

새 `WORK/return_checkpoints/RETURN`에는 최종 B **네 후보**를 profile/strategy별 경로로 복사한다. checkpoint_best.pth, 공통 model 네 파일, CHECKPOINT_RECEIPT.json을 포함한다. A best/latest 및 이전 후보는 GPU 원래 위치에 보존하되 자동으로 모두 반환하지 않는다. optimizer를 제거한 변환 weight나 latest를 best로 이름만 바꾼 파일로 대체하지 않는다.

evidence와 checkpoints는 **별도 ZIP**으로 만든다. helper `pack`으로 원본 대조/CRC/SHA를 검증하고, **80 MiB보다 큰 모든 ZIP을 helper `split`으로 분할**한다. 새 파트 폴더의 ARCHIVE_PARTS.json과 모든 part를 업로드한다. 거대 ZIP 하나만 업로드하지 않는다. 작은 evidence ZIP도 80 MiB 초과 시 분할한다. 확인된 연결 도구 업로드 제한은 100 MiB이므로 200 MiB 조각으로 되돌리지 않는다.

```powershell
& $ocrPython -m scripts.student_test_gpu_archive pack --source $returnEvidence --archive $newEvidenceZip
& $ocrPython -m scripts.student_test_gpu_archive pack --source $returnCheckpoints --archive $newCheckpointZip
& $ocrPython -m scripts.student_test_gpu_archive split --archive $newCheckpointZip --output $newPartsDirectory
```

분할 후 별도 새 로컬 경로로 한 번 재조립하여 전체 SHA 일치를 확인한다. 이 검증용 사본도 임의 삭제하지 않는다. 공간 부족이면 검증 미실행을 기록하고 승인 없이 원본 정리하지 않는다.

원샷 프롬프트 전달 표의 **동일 비공개 Drive 폴더**에 결과 evidence ZIP/receipt, checkpoint parts/parts manifest, transport helper, 한국어 요약, 수신 컴퓨터용 원샷 프롬프트를 새 파일로 업로드한다. 공개 공유를 만들거나 기존 파일을 대체하지 않는다. 업로드된 파일 ID/부모/이름/크기를 metadata로 재확인하고 실제 링크를 최종 프롬프트에 넣는다. 업로드 전 생성한 receipt 문구를 과거 사실과 다르게 덮어쓰지 말고 UPLOAD_RECEIPT를 별도 추가한다.

수신용 프롬프트에는 실제 링크·각 ZIP/part/receipt의 크기/SHA, 재조립/추출 명령, 네 후보의 실제 iteration·architecture 연결, 보고서/JSONL 고정 분모 검토 지시, 미실행/실패 구분, 운영 변경·새 학습 금지를 명확히 적는다. 가능하면 evidence를 먼저 받아 문서 검토부터 할 수 있게 만든다.

## 완료 보고

실제로 수행한 학습/평가 건수, 두 profile의 fixed-denominator 결과, 후보 채택/미채택 이유, 실패·미실행·제약, 모든 반환 링크를 한국어로 한 번에 요약한다. 작업은 새 실험 산출물과 전달 자료까지만 완료하며 운영 모델·서비스는 그대로 둔다.
