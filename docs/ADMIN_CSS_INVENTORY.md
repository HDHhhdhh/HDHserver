# 관리자 CSS 소유권 인벤토리

이 문서는 `static/css/admin.css`의 **의도된 도메인 소유권, 소비 표면, 분리 순서, 결정 대기 항목**의 정본이다. 실제 선택자와 현재 로드 상태는 CSS·HTML·JavaScript가 말하며, `scripts/verify_admin_css_inventory.mjs --json`이 이를 다시 산출한다. 다른 문서는 이 내용을 복사하지 않고 이 문서를 참조한다.

현재 상태는 **인벤토리 완료, 첫 분리 적용·검증 완료**다. OCR과 학생 App 관련 CSS는 범위 밖이다.

## 실제 소비 표면

`admin.css` 문자열 검색과 HTML/JavaScript 로드 구조 파싱을 서로 독립적으로 수행한 결과다.

| 표면 | 로드 방식 | 현재 cascade 순서 | 의미 |
|---|---|---|---|
| `/admin` | `static/admin.html` 직접 로드 | `main.css` → `admin.css` → `admin-export-logs.css` → `student-work-light.css` → `student-test-ocr-admin.css` | 전체 관리자 운영판. 내보내기 CSS만 여기서 추가 로드하며 마지막 OCR 파일은 이번 범위 밖이다. |
| `/tests` | `static/tests.html` 직접 로드 | `main.css` → `admin.css` → `tests.css` | `tests.css`가 시험 화면 전용 override를 소유한다. |
| `/all` 학생기록 팝업 | `static/js/all/features/studentRecordPopup.js` 동적 로드 | `main.css` → `admin.css` → `student-work-light.css` | 팝업이 열린 동안 `body.admin`을 임시 적용한다. |

따라서 `body.admin`이라는 scope만으로는 `/admin` 전용이라고 판정할 수 없다. `/tests`와 `/all` 팝업의 실제 DOM·동적 class 소비까지 확인해야 한다.

## 2026-08-29 분리 전 기준선

| 항목 | 값 |
|---|---:|
| 파일 | 243,632 bytes / 10,138 content lines |
| 원본 SHA-256 | `c47cf89cfa6b174a33f67ad88696b7c673c76b70193fb23db1e2cf2965c0c701` |
| qualified rule / selector occurrence / distinct selector | 1,388 / 1,814 / 1,234 |
| 두 번 이상 선언된 selector 이름 | 322 |
| media block / `!important` | 34 / 220 |
| `body.admin.tests-page` selector occurrence | 35 |
| `tests.css`와 동일한 distinct selector | 13 |
| `body.admin` 밖 selector | 0 |

이 표는 현재 파일을 영구 동결하는 규칙이 아니라 첫 분리의 출발점을 식별하는 역사적 기준선이다. 이후 현재 수치는 verifier의 `--json` 출력이 소유한다.

## 도메인 판정(분리 전 inventory)

| 도메인 | occurrence / distinct | 분리 전 범위 | 소비·결합 | 판정 |
|---|---:|---|---|---|
| 시험 화면 잔여 | 35 / 20 | 5,665–7,688 | `/tests`, `tests.css`와 13개 selector 중복 | 의미 충돌 가능. 자동 이동·병합 금지. |
| simple mode | 111 / 63 | 5,454–9,953 | shell·hero·table·action을 함께 변경 | 독립 책임이 아니므로 보류. |
| 공지·답장 | 606 / 447 | 2,196–9,101 | hero, modal, desktop/mobile override가 반복 | 대형 결합 도메인. 먼저 내부 소유권을 더 나눠야 한다. |
| 보강 planner | 68 / 53 | 1,013–9,101 | calendar와 late mobile override에 분산 | 단일 연속 블록이 아니므로 보류. |
| 조교 메모 | 166 / 107 | 8,119–10,138 | `/admin`과 `/all` 팝업이 함께 소비 | 관리자 전용 파일로 이동하면 안 된다. |
| 관리자 메모 | 29 / 25 | 7,324–9,968 | 학생 로그 rail의 최종 layout과 결합 | rail 경계 결정 전 보류. |
| 학생 로그 rail | 39 / 35 | 9,682–9,968 | 관리자 메모와 같은 `hero-note-rail` 사용 | 두 패널 layout 계약을 함께 다뤄야 한다. |
| 수업 기록 내보내기 modal | 37 / 31 | 7,122–7,321 | `/admin` DOM과 `exportLogs.js`만 소비 | **`admin-export-logs.css`로 분리 완료.** |
| 학생 계정·집중 기록 | 76 / 68 | 8,288–8,630 | 학생 App 운영 기능 | 사용자 지정 범위 밖. |

## 첫 분리 적용 상태

수업 기록 내보내기 modal CSS만 `static/css/admin-export-logs.css`로 이동했다. `admin.css`는 9,936 content lines가 됐고, 새 파일은 분리 전 201줄과 byte-normalized SHA-256이 같다.

- 경계: `body.admin.export-logs-open`부터 `body.admin .admin-operation-notes` 직전까지의 연속 201줄
- selector: 37 occurrence, 31 distinct, 모두 `body.admin.export-logs-open` 또는 `body.admin #exportLogsModal …`
- responsive: `@media (max-width: 640px)` 한 블록
- specificity 예외: `!important` 0개, `@import` 금지
- 분리 전 정규화 CSS SHA-256: `fe4830147c7a4ee1d25b107a698aeceb7f42a059158e5511278b63f1a6d343ef`
- 독립 DOM 기준선: `#exportLogsModal` 블록 72줄, SHA-256 `cb46713d6f4c68c6c9d6fd7a783e1c327085144a641dbacdee21c8d1c675aa8f`
- 적용 load 위치: `/admin`에서 `admin.css` 뒤, `student-work-light.css` 앞
- 금지된 소비자: `/tests`와 `/all` 학생기록 팝업은 새 파일을 로드하지 않는다.

기능 의미와 focus/Escape/중복 제출/내보내기 결과는 기존 `scripts/verify_export_log_format.mjs`가 새 파일을 직접 읽어 별도로 검증한다. 인앱 Browser와 Chrome에서 light/dark, desktop/mobile modal의 계산 스타일은 각 브라우저의 분리 전 기준선과 일치했고, 초점 이동과 Escape 종료·opener 복귀도 같았다. 두 브라우저 모두 새 stylesheet 29개 rule을 로드했고 console warning/error와 framework overlay는 없었다. 관리형 격리 runtime 30개 파일의 길이·SHA-256도 전후 동일했다.

## 결정 대기 항목

이번 단계에서 해결하지 않는다.

- `admin.css`에 남은 35개 시험 화면 selector와 `tests.css`의 13개 동일 selector 중 어느 쪽이 공통 기본값인지
- 공용 token, table, `.modal-*`, `.btn`의 의미를 관리자와 시험 화면에서 통합할지 분리할지
- `hero-note-rail`을 layout 파일로 볼지 관리자 메모·학생 로그 기능 파일 중 하나가 소유할지
- `/all` 팝업까지 소비하는 조교 메모·학생 작업 modal CSS를 별도 공유 파일로 만들지

이 항목은 코드 이동 중 자동으로 해석하지 않고, 사용자 결정이 필요한 모순으로 올린다.

## 검증 독립성

`$mandela` 감사에서 다음 누수 위험이 발생했다.

- **Shared hallucination / Tautology:** 새 문서와 새 parser만 서로 확인할 수 있다. 수정 전 CSS SHA-256과 modal DOM SHA-256을 외부 기준선으로 고정하고, 소비자는 별도의 literal 검색과 HTML/JavaScript 구조 파싱으로 두 번 열거한다.
- **Verifier = designer:** 같은 구현자가 만든 새 verifier만으로 분리를 승인할 수 있다. 기존 `verify_export_log_format.mjs`, 실제 entrypoint/DOM, 인앱 Browser·Chrome의 분리 전후 computed-style 비교를 독립 표면으로 유지한다.

브라우저 비교는 새 파일의 존재가 아니라 계산된 layout·색·반응형·초점·Escape 결과를 각 브라우저 자체의 분리 전 값과 비교한다.

## 명령

```powershell
node scripts/verify_admin_css_inventory.mjs --json
node scripts/verify_admin_css_inventory.mjs
node scripts/verify_export_log_format.mjs
python scripts/verify_refactor_safety.py
```
