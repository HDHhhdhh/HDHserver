# OCR 실험실 소스와 로컬 산출물

이 폴더는 독립 실행 스크립트로 구성된 OCR 실험실이다. Python 패키지나
운영 서버의 자동 실행 디렉터리가 아니다.

## 등록 범위

Git에는 재사용 가능한 최상위 소스, 구조·계약·운영 지침, 합성 fixture만
등록한다. `.gitignore`의 명시적 허용 목록이 등록 범위를 정한다.

실제 학생별 일회성 실행 스크립트, 원본 이미지, 전사, 인식 결과, provider
응답, 평가 보고서, 승인 기록, 모델 가중치, 캐시, 백업과 하위 산출물 폴더는
로컬에 보존한다. Git 상태 정리는 이 데이터를 삭제하거나 이동하지 않는다.

## 현재 규칙과 역사 코드

실험실 작업의 안전 지침은 [AGENTS.md](AGENTS.md)를 따른다. 운영 학생 시험
OCR 기능은 [규칙 색인](../../docs/SERVER_RULES_INDEX.md#rule-student-ocr-001)이
가리키는 정본 §21과 D-09를 따른다. 두 경계를 혼합하지 않는다.

`phase1_*`, `phase2*`, 과거 student OCR·submit·browser runner와 당시 통합
계획은 역사적 연구 소스다. 파일을 등록한 사실은 해당 경로의 복구, 실행,
운영 통합 또는 provider 호출을 승인하지 않는다. 기존 학생 제출 경로를
새 OCR 기능의 구현으로 재사용하지 않는다.

현재 오프라인 검토 payload 계약은
[ocr_review_payload_contract.md](ocr_review_payload_contract.md)에서 시작한다.
과거 fixture는 합성 검증 자료이며 실제 학생 기록이나 모델 정확도의
증거가 아니다.

## 검증 경계

프로젝트 기본 안전 검증은 `scripts/verify_refactor_safety.py`가 담당한다.
실험실 전체 runner는 기본 검증에 자동으로 포함되지 않는다. 일부 runner는
보고서 생성, 외부 OCR 실행 또는 provider 호출을 수행한다. 등록만을 위해
실행하지 않으며, 실행 시에는 AGENTS의 별도 권한과 출력 범위를 확인한다.
