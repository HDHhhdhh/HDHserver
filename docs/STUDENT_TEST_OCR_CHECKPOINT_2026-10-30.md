# OCR 코드·세션 체크포인트 · 2026-10-30

이 문서는 사용자가 요청한 Git 보존 시점의 기록이다. 운영 배포 완료를 뜻하지 않는다.
현재 업무 규칙은 [Server Rules Index](SERVER_RULES_INDEX.md)를 따른다.

## 대화 기록

- 세션: `019ffb79-5698-7560-ae91-6b6915e74019` · OCR 기능 관련 (동훈).
- [대화 원문 JSONL](ocr_sessions/2026-10-30/dialogue.jsonl): 로컬 세션에 남아 있는 사용자 메시지와 공개 답변·진행 안내 937개. 사용자 112개, assistant 825개.
- [내보내기 manifest](ocr_sessions/2026-10-30/manifest.json): 원본 스냅샷 경계·SHA-256, 대화 파일 크기·SHA-256, 제외 항목 수를 기록한다.
- 범위: 2026-08-13부터 2026-10-30 Git 보존 작업 중 스냅샷까지. 메시지별 시각은 UTC다.
- 내부 추론, 시스템·개발자 지침, 환경 주입문, 도구 호출·결과 원문, 첨부 이미지·파일은 포함하지 않았다. 비밀키 패턴을 검사했으며 치환 대상은 0개였다.
- 과거 메시지의 완료·정확도 주장은 당시 기록이다. 이번에 전체를 재검증한 것은 아니다. 이 문서나 대화 기록으로 최신 규칙을 덮어쓰지 않는다.

## 이번에 보존한 코드

| 파일 | 역할 |
|---|---|
| `scripts/import_aihub_education_choice_dataset.py` | annotation 좌표계와 EXIF 회전을 맞춘 뒤 숫자 crop 생성. 기존 출력 폴더 재사용 거부. |
| `scripts/import_aihub_education_formula_dataset.py` | 같은 좌표계 함수를 사용한 수식 crop 생성. 불일치 이미지를 건너뛰고 집계. |
| `scripts/verify_aihub_crop_orientation.py` | EXIF 1~8, raw 좌표계, 차원 불일치, 두 변환기의 실제 임시 crop·원본 보존 회귀 검사. |
| `tools/subjective_sheet_lab/compare_openai_ocr_20261030.py` | 기존 40 crop의 로컬/Luna/Terra 제한 비교, 호출 원장, 고정 분모 평가. |
| `tools/subjective_sheet_lab/retry_local_formula_comparison_20261030.py` | Windows 캐시·사용자 환경을 보존한 로컬 수식 모델 시작 재시도. |
| `tools/subjective_sheet_lab/audit_ocr_comparison_20261030.py` | 원본 연결·요청 누출·응답·비용·모델 해시 검토. |
| `tools/subjective_sheet_lab/confirm_ocr_crop_orientation_20261030.py` | 기존 표본 11개의 회전 원인 확인용 새 진단 사본 생성. OCR 재실행 아님. |
| `tools/subjective_sheet_lab/verify_openai_ocr_comparison_20261030.py` | 호출 상한·실패 분모·변조 방지 등 오프라인 계약 검사. |
| `scripts/export_codex_session_dialogue.py` | 한 개의 명시적 세션에서 공개 대화만 새 폴더로 내보내기. |
| `scripts/verify_codex_session_dialogue_export.py` | 합성 대화로 내부 정보 제외·비밀 패턴 치환·원본 보존 검사. |

lab 스크립트에는 이 컴퓨터의 경로와 날짜별 출력 폴더가 있다. 다른 환경에서 즉시 실행 가능한 패키지라고 주장하지 않는다.
API 실행은 별도의 현재 승인과 호출 상한이 필요하다. 과거 원장 폴더에서 재호출하면 안 된다.

## 완료된 비교와 한계

기존 40개 crop에 대해 Luna 40회, Terra 40회를 실제 호출했다. 로컬은 CNN + UniMERNet을 사용했다.
숫자값 기준 기존 라벨 일치는 로컬 26/40, Luna 20/40, Terra 21/40이었다.
평균 crop 처리 시간은 각각 약 0.454초, 2.682초, 2.597초였다. 로컬 모델 로딩 시간은 별도다.
API 사용 토큰 기준 표준 단가 추정 합계는 약 $0.0135861이며 청구서·크레딧 적용은 확인하지 않았다.

그러나 고2 분수·루트 11개에서 원본 EXIF Orientation 6과 annotation 좌표계가 달랐다.
기존 변환기가 회전 전 픽셀을 잘라 다른 영역을 전달했다. 따라서 위 수치는 신뢰 가능한 OCR 정확도 순위가 아니다.
표본을 분모에서 빼거나 원래 전사를 모델 출력에 맞게 고치지 않았다.
공개 개발 validation, 학습 작성자와의 일부 중복, 고3 지원 숫자 표본 0개라는 한계도 남아 있다.

로컬 결과 원본은 Git 제외 경로 `tools/subjective_sheet_lab/comparison_20261030_01/`에 보존돼 있다.
`RESULTS_KO.txt`가 최종 사람용 요약이고, `ORIENTATION_FINDING.json`이 나중에 확정한 회전 원인 근거다.
`REPORT.json`은 당시 고정 라벨 대비 원시 지표다. 이전 `FINAL_REVIEW.*`는 원인 확정 전의 기록이다.

## 중단 시점의 미완료 작업

사용자는 회전 보정 후 crop 재생성·검증·재비교와 기존 학습 데이터의 같은 오류 점검을 승인했다.
Luna·Terra 각각 **추가 40회**도 승인했지만, 이번 Git 보존 요청으로 그 작업을 중단했다.

1. 공용 EXIF/좌표계 처리와 두 importer 연결은 구현했다. 합성 회귀 검사로 코드 동작을 확인한다.
2. 실제 40개 crop의 새 버전 생성·동일 표본 연결 검증은 아직 하지 않았다.
3. 추가 API 호출은 **Luna 0/40, Terra 0/40**이다. 기존 실행의 40회씩과 구분한다.
4. 기존 학습 데이터 영향은 아직 확정하지 않았다. 같은 변환기 사용만으로 실제 오류 수를 단정하지 않는다. 원천 이미지 일부가 정리된 상태이므로 재현 가능 범위를 먼저 확인해야 한다.
5. API 튜닝은 조사 중이다. 프롬프트·예시 제공과 모델 가중치 학습은 구분하며, 개선 효과를 아직 측정하지 않았다.

`deploymentReady:false`를 유지한다. 운영 모델·설정·DB·학생 UI·서버는 변경하거나 재시작하지 않았다.
API 키 입력 파일, 데이터셋, 진단 이미지, 원시 응답, 체크포인트, 운영 데이터는 이 Git 보존에 포함하지 않는다.

## 검증 범위

- 관련 검사 5종 통과: 기존 importer 2종(10·20 assertions), 비교 실행기 계약 7 tests, 회전 4 tests, 대화 내보내기 2 tests.
- 새 Python 코드 구문, Git 공백 검사, 대화 메시지 수·SHA-256, staged 파일의 실제 API 키 미포함 검사를 통과했다.
- `python -B scripts/verify_refactor_safety.py`도 실행했다. OCR 계약 검사까지 통과했지만, 결석·보강 통합 검사 구간에서 더 진행된 출력을 확인하지 못했다. 약 620초 후 이 작업이 시작한 검사 프로세스만 종료했다. **전체 기본 검사는 미완료이며 통과로 기록하지 않는다.** 원인은 이번에 확정하거나 수정하지 않았다.
- 전체 검사는 다른 작업의 기존 수정본이 있는 작업공간에서 실행했다. 그 수정본은 이 OCR 커밋에 포함하지 않는다.
- 운영 live smoke·브라우저 QA·독립 하위 에이전트 검토는 수행하지 않았다. 운영 서버는 종료 대상이 아니었다.

이 검증을 실데이터 재생성·재비교 완료로 읽으면 안 된다. 이번 Git 보존은 진행 중 작업의 체크포인트다.
