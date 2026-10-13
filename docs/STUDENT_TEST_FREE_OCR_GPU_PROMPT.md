# 무료 OCR GPU 비교 실험: 다른 컴퓨터용 실행 지시

아래 One-shot prompt 전체를 GPU 컴퓨터의 Codex에 전달한다. 전달 대상인 `student_test_free_ocr_gpu_20260906_verified.zip`은 공개 AI Hub 파생 crop과 코드만 포함하며 실제 학생 촬영이나 서버 운영 DB는 포함하지 않는다. ZIP 내부 `GPU_PROMPT.md`는 링크 추가 전 오프라인 지시본이다. Drive 다운로드부터 시작할 때는 링크와 ZIP 검증값이 포함된 아래 본문을 사용한다.

## One-shot prompt

무료 OCR 개선 실험을 진행해 주세요. 유료 API/외부 OCR 호출 예산은 0입니다. 이 컴퓨터의 NVIDIA GPU와 이미 설치된 `C:/server-ocr/.venv-unimernet`을 사용합니다. 기존 데이터, 체크포인트, `C:/server` 프로젝트는 삭제·덮어쓰기하지 마세요. 운영 서버가 있다면 중지/재시작하지 마세요.

먼저 연결된 Google Drive에서 다음 검증된 학습 패키지를 다운로드하세요. 링크는 비공개이며 이 Drive에 접근 가능한 계정으로 연결되어 있어야 합니다. 접근이 안 되면 공개 공유로 바꾸거나 다른 파일로 대체하지 말고 해당 항목만 보고하세요.

- 학습 패키지: https://drive.google.com/file/d/1M9jHJWFwRsTpH554s4xlqN4NO122s5nu/view?usp=drivesdk
- 원본 Drive 폴더: https://drive.google.com/drive/folders/10DOGMapLqOtogOSaf3OnZvl3QaRzvS10
- 파일명: `student_test_free_ocr_gpu_20260906_verified.zip`
- 정확한 크기: `55898650` bytes
- SHA-256: `3ae04d5bedd36bf380699005a9970f1f581a59ab67013e18bfad4e68c0fd8402`

저장형 ZIP이므로 Drive metadata를 확인한 뒤 원본 파일 다운로드를 사용하고 Google 문서 export나 텍스트 추출을 사용하지 마세요. 크기와 SHA-256이 위 값과 일치하는지 확인한 뒤에만 압축을 해제하고 코드를 실행하세요. 다운로드 파일과 기존 파일의 경로가 겹치면 기존 파일을 덮지 말고 새 경로를 사용하세요. 이 패키지는 추가 실험용 데이터·코드 묶음이며 아래 2번의 기존 전체 Training/모델/가상환경까지 포함한 전체 환경 백업은 아닙니다.

1. 전달받은 ZIP을 새로운 빈 `C:/server-ocr/free_ocr_20260906`에 풉니다. 이미 폴더가 있으면 덮지 말고 새 suffix를 붙이세요. ZIP SHA-256과 `PACKET_MANIFEST.json`의 모든 파일 크기·SHA-256을 확인하세요. 새 코드 실행 위치는 `<packet>/code`입니다. 기존 `C:/server` 코드를 교체하지 않습니다.
2. 아래 기존 자산이 있는지 확인하세요. 없으면 임의의 비슷한 모델/라벨로 대체하지 말고 그 단계만 차단 상태로 보고하세요. Python/패키지 버전, CUDA 장치와 VRAM을 기록하고 `torch.cuda.is_available()`이 false면 학습을 시작하지 마세요. 유료 GPU를 새로 빌리지 않습니다.
   - `C:/server-ocr/models/unimernet_tiny/`의 weight/config/tokenizer
   - `C:/server-ocr/datasets/aihub_education/formula_profiles/training/m3_h1`
   - `C:/server-ocr/datasets/aihub_education/formula_profiles/training/m3_h1_h2_h3`
3. 기존 상위 과목 학습의 `C:/server-ocr/training_runs/unimernet_m3_h1_h2_h3/20260831000/checkpoint_best.pth`를 확인하세요. 이 checkpoint는 기록상 4,000 iteration이고, 현재 서버가 받은 것은 latest 5,000입니다. best가 실제로 있으면 별도 RETURN 폴더에 복사하고 SHA-256 및 해당 로그를 기록하세요. 없으면 `unavailable`로 남기고 최신 파일을 best라고 이름만 바꾸지 마세요. 이 항목이 없어도 새 데이터 비교 실험은 계속할 수 있습니다.
4. `<packet>/code`를 cwd로 아래 두 계약 검사를 실행하세요. 실제 서버 DB는 import하거나 열지 않습니다.

```powershell
& 'C:/server-ocr/.venv-unimernet/Scripts/python.exe' -B -m scripts.verify_student_test_formula_training_config
& 'C:/server-ocr/.venv-unimernet/Scripts/python.exe' -B -m scripts.verify_student_test_formula_profile_training
```

5. 실험은 **동일 base checkpoint, 동일 seed, 동일 1,000 microbatch iteration**으로 full/focused × 두 프로필 총 4회만 수행하세요. 이미 완료된 실행을 덮어쓰지 않습니다. 새로운 work 경로를 사용하세요. 아래 명령의 `<packet>`과 `<new-work>`를 실제 절대경로로 바꿉니다.

```powershell
& 'C:/server-ocr/.venv-unimernet/Scripts/python.exe' -B -m scripts.run_student_test_formula_experiments --packet-root '<packet>' --runtime-root 'C:/server-ocr' --work-root '<new-work>' --max-iters 1000 --train
```

명령은 이미지·annotation·base weight 해시를 고정한 config를 최종 경로에서 새로 생성하고, full 두 프로필 다음 focused 두 프로필을 순차 실행합니다. 네 config를 한 번의 `train_student_test_formula_profiles` 호출에 몰아 넣으면 profile 중복으로 거부됩니다. batch4/accum2 기준 명목 4,000 sample exposures/약 500 optimizer updates가 각 run의 예산입니다. 추가 iteration/새 데이터/모델 교체를 임의로 늘리지 마세요. 이 작은 실험은 방향 비교이지 최종 학습 완료가 아닙니다.

6. 기존 base 및 가능한 기존 반환/best 모델, 새 full/focused best checkpoint를 각 프로필의 **동일 packet validation**에서 평가하세요. 점수는 숫자값 동치, 정규화 문자열 일치, 생성 상한 실패, 학년별/작성자별 결과를 구분합니다. 평가 디렉터리는 모델마다 새로 만듭니다.

```powershell
& 'C:/server-ocr/.venv-unimernet/Scripts/python.exe' -B -m scripts.evaluate_student_test_formula_dataset --dataset '<packet>/data/validation/<profile>' --model-dir 'C:/server-ocr/models/unimernet_tiny' --weight '<absolute-checkpoint-path>' --output '<new-eval-output>' --device cuda
```

`--model-dir`는 공통 architecture/tokenizer 디렉터리이고 `--weight`는 해당 checkpoint의 절대경로를 받을 수 있습니다. 새 학습은 항상 `checkpoint_best.pth`를 선택합니다. generated EOS라도 64-token cap에 도달한 출력은 실패로 계산합니다. 오류 표본을 분모에서 빼거나 전사를 OCR 출력에 맞춰 수정하지 마세요. `data/EXPERIMENT_INPUTS.json`의 내용을 보존하세요.

7. 공통수학용 validation은 1,459 crop/3 writer hash, 상위는 1,473/6입니다. 상위의 고3 검증 표본은 0개입니다. writer hash는 grade-scoped이며 동일인 신원을 완전히 검증한 것이 아닙니다. 고3 정확도·실카메라 정확도·운영 GO를 주장하지 마세요. calibration/출시용 학생 데이터로 재명명하지 마세요.
8. 각 프로필에서 full/focused의 결과를 비교해 반환 후보 1개를 선택하되 두 실험의 checkpoint는 이 컴퓨터에 모두 보존하세요. 동치율, 전체 실패수, 학년/작성자별 악화를 함께 보고 선택 이유를 남기세요. 기존 best4000이 있으면 별도 후보로 반환하세요. 현재 서버의 모델 교체나 기능 활성화는 하지 않습니다.
9. RETURN에는 선택 checkpoint, model config/tokenizer 4종, 실행 config와 manifest, 학습 로그, 모든 비교 evaluation report/예측 JSONL, `EXPERIMENT_PLAN.json`, `EXPERIMENT_INPUTS.json`, `RETURN_RECEIPT.json`을 넣으세요. receipt는 checkpoint별 profile/strategy/원본 경로/실제 best iteration/크기/SHA-256, 학습 성공·실패·미실행 구분, 예측/데이터 해시, `deploymentReady:false`, `providerCallCount:0`을 포함해야 합니다. 최종 weight를 이미 운영 승인된 것으로 표시하지 마세요.
10. RETURN ZIP과 SHA-256을 제공하세요. 파일 공유는 사용자가 승인한 Drive 폴더가 있을 때만 그곳에 올리고, 없으면 로컬 archive 경로를 보고하세요. 원천 데이터/기존 archive/기존 모델을 정리한다며 삭제하지 마세요.

중간에 막힌 항목이 있으면 그 항목만 중단하고 안전하게 가능한 비교·검증은 완료한 뒤, 실제 수행 결과와 남은 항목을 한 번에 요약해 주세요.
