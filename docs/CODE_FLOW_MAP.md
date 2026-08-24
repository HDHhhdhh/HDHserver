# 학원 운영 허브 — 코드·데이터 흐름 지도

**기준일:** 2026-08-24
**기준 브랜치:** `codex/apple-clean-redesign`
**기준 커밋:** `91b7bb1`
**범위:** `app.py`, `core/`, `routes/`, `static/`, 기본 검증 스크립트

이 문서는 “어떤 화면 요청이 어떤 규칙과 저장소를 거쳐 결과를 만드는가”를 정리한 구현 지도다. 사용자에게 보이는 의미와 상태 계약은 [PROJECT_FUNCTIONS_AND_LOGIC.md](PROJECT_FUNCTIONS_AND_LOGIC.md), 작업 안전 규칙은 루트 및 하위 `AGENTS.md`가 우선한다.

## 1. 점검 기준선

- 운영 서버와 `Academy Server Waitress` 예약 작업을 중지한 상태에서 조사했다.
- 기본 안전성 검사와 `--smoke`가 모두 종료 코드 0으로 통과했다.
- 검사 전후 주요 JSON·SQLite 지문은 같았고 `app.sqlite-wal`, `app.sqlite-shm`도 남지 않았다.
- 운영 데이터 백업은 `_runtime_backups/runtime-data-20260823_171741.zip`에 만들었으며 Git 대상이 아니다.
- 운영 코드 규모는 Python 98개/25,230줄, JavaScript 92개/47,603줄, HTML 10개/4,119줄, CSS 6개/19,817줄이다.

## 2. 앱 조립 모드

`create_app()`은 학생 앱 기능 플래그에 따라 Blueprint와 URL 표면을 조건부 등록한다. 따라서 문서나 테스트에서 Blueprint 수를 하나의 상수로 가정하면 안 된다.

| 조립 모드 | 주요 플래그 | Blueprint | URL rule | 학생 앱 추가 표면 |
|---|---|---:|---:|---|
| 기본 셸/플래그 OFF | `PUBLIC_ENABLED=0` | 18 | 121 | 모바일 인증·푸시·게시판 미등록 |
| 현재 예약 작업 인자 | public ON, dashboard/homework/reminders/focus OFF | 21 | 134 | 모바일 인증, 푸시 기반, 게시판 |
| 모든 학생 앱 기능 ON | public/dashboard/homework/reminders/focus ON | 24 | 141 | 위 기능 + 공개/관리자 숙제, 공개 focus |

현재 예약 작업은 `-DevelopmentIsolation -PublicEnabledOverride 1`을 사용한다. DevelopmentIsolation의 기본 OFF 값 뒤에 public만 다시 켜므로 dashboard, homework, reminders, focus는 비활성이다. 관리자 focus 요약 Blueprint는 public focus 플래그와 무관하게 항상 등록되지만, 스키마가 없으면 fail-closed 응답을 내는 구조다.

## 3. 화면과 진입점

| 경로 | HTML/진입 스크립트 | 서버/API 흐름 | 날짜 기준 |
|---|---|---|---|
| `/` | `index.html` → `auth.js` | `/api/auth/*` | 해당 없음 |
| `/admin`, `/dh1130` | `admin.html` → demo bootstrap → `admin/main.js` | 공통 bootstrap 후 기능별 API hydrate | 실제 오늘로 시작, 이후 선택일/행 `data-date` |
| `/students` | `all.html` → demo bootstrap → `all/main.js` | 학생·영상·캘린더 로드, SID별 진도 lazy load | 실제 로컬 오늘 |
| `/student/<sid>` | `student.html` → `student-focus.js`, `student.js` | 권위 있는 `/api/student/bootstrap` 단일 초기화 | 요청 날짜, 기본 실제 오늘 |
| `/app`, `/app/*` | `student-app.html` → `student-app.js` | 모바일 세션 확인 후 허용된 학생 화면으로 연결 | 세션의 active SID |
| `/tests` | `tests.html` → demo bootstrap → `tests.js` | 카탈로그·기록·통계 | 카탈로그/기록별 |
| `/video-manage` | `video-manage.html` → demo bootstrap → `video-manage.js` | 영상 카탈로그 전체 저장 또는 오프라인 수정 초안 | 해당 없음 |
| `/school-cal` | `school-cal.html` → demo bootstrap → `school-cal.js` | 학교 일정 전체 편집 | 일정 날짜 |
| `/file-manage` | `file-manage.html` → `file-manage.js` | 파일 트리·이동·업로드 | 해당 없음 |
| `/demo/rh3123*` | 실제 shell + `admin/demo/bootstrap.js` 선행 | `sessionStorage` 합성 API | 고정 합성 시각 |

## 4. 영역별 권위와 흐름

| 영역 | 요청 경계 | 순수 규칙/서비스 | 저장 원본 | 주요 소비 화면 |
|---|---|---|---|---|
| 학생 명단 | `api_basic`, `api_auth`, `api_student_accounts` | 계정 규칙·감사·활성화 서비스 | `students.json`, `auth_accounts.json`, 계정 관련 SQLite 테이블 | 로그인, 관리자, 전체 학생, 학생 앱 |
| 날짜·출결 | `api_attend`, `api_arrive_time`, `api_todaymeta`, `api_makeup_carryover` | `absent`, `absence_assignment_cleanup`, `absence_transaction`, schedule projection, makeup sync | 출결 JSON군, `updates.json`, `progress.json`, class logs, `data/today_order.json`, `makeup_carryover.json`, transient journal | 관리자 오늘표·캘린더 |
| 수업 로그 | `api_basic`의 `/api/logs*` | `log_rules`, `LogRepository` | `app.sqlite.logs` 우선 + `logs.json` 호환 | 관리자 로그, 학생 숙제, 내보내기 |
| 학생 숙제 v2 | 조건부 `api_student_homework` | homework service/repository | 명시적 migration의 SQLite 숙제 테이블 | 관리자 로그 팝업, 학생 앱 |
| 영상 카탈로그 | `/api/videos` | video identity/correction rules | `videos.json` | 영상 관리, 관리자 배정, 학생 |
| 영상 배정 | `/api/updates*`, bootstrap | 자동 배정·복습 projection | `updates.json`, `progress.json`, `watch.json` | 관리자 영상 팝업, 학생 재생목록 |
| 시청·진도 | `api_watch`, `api_kollus` | `watch_progress_writer`, `progress_rules`, `progress_store`, `progress_notifications` | `watch.json`, `progress.json` | 학생 재생, 관리자 상태색 |
| 시험 | `api_tests`, bootstrap | test config safety, answer-link projection | `tests-config.json`, `tests.json`, progress/log metadata | 시험 관리, 관리자 배정, 학생 카드 |
| 공지·게시판 | `api_announcements`, 조건부 `api_student_board` | board projection, notification event ID | `announcements.json`, `announce_status.json`, 첨부 파일 | 관리자 공지, 학생/학생 앱 |
| 자료·파일 | api_basic, api_fs | material_reference_rules + material_state journal + 경로/파일-tree 잠금 | materials.json, mat_assign.json, page_folders.json, files/ | 관리자·학생 자료 |
| 조교/운영 메모 | 전용 notes/logs API | 서로 다른 repository | `app.sqlite`의 분리 테이블 | 관리자만 |
| 학생 앱 인증 | 조건부 `api_student_app_auth`, 관리자 계정 API | account/session/activation/throttle 서비스 | `auth_accounts.json`, SQLite 세션·감사·활성화·throttle | `/app`, 관리자 계정 |
| 학생 앱 푸시 | 조건부 `api_student_push` | push/notification repository와 sender | SQLite push/outbox/notification 테이블 | 학생 앱 설정, 백그라운드 발송 |
| 집중 모드 | 조건부 공개 API + 상시 관리자 요약 | focus rules/repository, schedule projection | 명시적 migration의 focus 테이블 | 학생 focus UI, 관리자 요약 |
| 데모 | 브라우저 fetch/navigation guard | demo contract modules | 지정된 `sessionStorage` 키만 | 관리자 계열 데모 |

## 5. 핵심 상태 전이

### 5.1 관리자 선택 날짜

```text
admin shell
  → core/state.js가 실제 오늘 호환 상태 로드
  → adminDate.js가 선택 날짜 결정
  → today.js와 각 modal이 선택 날짜/행 data-date로 재조회
  → row patch 또는 merge-safe 저장
  → 날짜·SID 범위 캐시만 병합
```

모달은 열린 순간의 날짜와 SID를 고정한다. 저장 시점의 전역 선택일로 다시 계산하지 않는다.

### 5.2 학생 bootstrap

```text
legacy JWT 또는 public app cookie session
  → 요청 SID/active SID 검증
  → 학생·결석·로그·배정·영상·진도·시청·시험·자료 읽기
  → 현재 재생목록, reviewVideos, assignedTests, 접근 제한 projection
  → 단일 bootstrap 응답
  → student.js가 서버 membership만 정규화·렌더링
```

비공개 real-today bootstrap은 누락된 자동 배정을 만들 수 있다. public 요청, 다른 날짜, 읽기 전용 관리자 조회는 storage-only다. bootstrap 실패 시 학생 화면은 과거 다중 GET fallback을 사용하지 않는다.

### 5.3 영상 재생과 진도

```text
student.js play(mid)
  → /api/get-url: 네트워크 + session SID + known SID/MID 검증
  → Kollus player 또는 LMS callback
  → core/watch_progress_writer의 monotonic watch merge·자동 progress write
  → progress_rules의 auto 상태 투영
  → 조건부 notification milestone hook
```

5%는 자동 `interrupted`, 90% 또는 완료 이벤트는 자동 `done`이다. 수동 흰색·skip·interrupted가 자동 상태보다 우선하며, watch 저장은 기존 자동 배정 snapshot을 재선정하거나 채우지 않는다.

### 5.4 로그와 숙제

```text
관리자 log modal
  → 최신 /api/logs/entry 재조회
  → placeholder repair는 route 경계에서 수행
  → log_rules로 병합/충돌 판정
  → LogRepository가 SQLite 우선 + logs.json 호환 저장
```

homework 기능이 켜진 경우 로그 저장과 SQLite 숙제 batch는 reconciliation 상태로 연결된다. 현재 예약 작업에서는 homework가 꺼져 있어 관리자 팝업의 404 fallback이 legacy 로그 흐름을 선택한다.

### 5.5 시험

```text
tests-config revision GET
  → 관리자 전체 config 편집
  → revision 포함 POST
  → 암묵 ID 삭제·stale revision 거부
  → progress의 날짜/SID test 상태가 학생 배정 권위
  → bootstrap이 답지 우선순위와 네트워크 제한을 투영
```

`tests.json`과 legacy 로그는 과거 기록 읽기용이다. 학생 제출·OCR 제출 표면은 등록하지 않는다.

### 5.6 학생 앱 알림

```text
공지/일정/숙제/진도 canonical mutation
  → feature flag 확인
  → idempotent notification event/outbox
  → push subscription 대상 lease/send/retry
```

reminders가 꺼져 있으면 일정·진도 hook은 repository를 열지 않고 0건으로 종료한다. 공지 push 기반은 별도이며 VAPID·스키마가 준비되지 않으면 fail-closed 응답을 사용한다.

## 6. 저장소 지도

### 6.1 JSON·파일

| 묶음 | 파일 | 쓰기 특성 |
|---|---|---|
| 학생/계정 | students.json, auth_accounts.json | 학생 컬렉션은 GET-only; add/field update/delete RMW는 students 잠금 사용 |
| 수업 | `logs.json`, `progress.json`, `updates.json`, `watch.json` | 날짜/SID/MID merge와 잠금 필요 |
| 출결 | `attendance.json`, `contact.json`, `arrive_time.json`, `absent.json`, `extra_attend.json`, `weekend_slots.json`, `makeup_carryover.json` | 학생·날짜 부분 갱신 |
| 카탈로그 | `videos.json`, `tests-config.json`, `tests.json` | 보호된 전체 저장 또는 읽기 전용 기록 |
| 자료/일정 | materials.json, mat_assign.json, page_folders.json, school_calendar.json, files/ | materials는 GET-only, page-folders HTTP는 폐기; 활성 mat-assign·calendar 전체 저장은 후속 전환 대상 |
| 공지 | `announcements.json`, `announce_status.json`, 첨부 파일 | 공지와 학생별 상태 분리 |
| 오늘 순서 | `data/today_order.json` | GET/PATCH/DELETE, 단일 canonical 경로 |

`core.paths`를 가져오면 누락된 canonical JSON과 `files/`를 생성한다. `AUTH_PATH`(`auth.json`)와 `CLINIC_PATH`(`clinic.json`)는 현재 생산 코드 소비자가 확인되지 않았지만 import 시 생성 대상이므로, 외부 사용 확인 없이 바로 제거하지 않는다.

### 6.2 현재 `app.sqlite` 테이블

현재 읽기 전용 schema 조회에서 다음 11개 테이블이 확인됐다.

- `logs`
- `assistant_student_notes`, `admin_operation_notes`, `student_operation_logs`
- `student_app_sessions`, `student_account_audit`, `student_activation_codes`, `student_login_throttle`
- `student_push_subscriptions`, `student_push_outbox`, `student_push_bypasses`

다음 기능은 SQL 파일과 repository가 있지만 현재 DB에는 관련 테이블이 없다.

- focus: `student_focus_sessions`, `student_focus_events`
- homework: `student_homework_assignments`, `student_homework_reconciliations`
- reminders: preferences/events/schedule-state/milestones/deliveries 5개 테이블

이는 현재 예약 작업의 해당 feature flag OFF 상태와 일치한다. 마이그레이션은 수동 artifact이므로 기능을 켜는 결정과 분리해 임의 적용하지 않는다.

### 6.3 브라우저 저장소

- 학생 복습 목록: `student:review-playlist:<sid>:<date>`
- 관리자 선택일·최근 보기: 기능별 session/localStorage 키
- 데모: `academy.adminDemo.v1` 및 tutorial 전용 session key

브라우저 저장소는 UI 편의 상태다. 서버 배정·진도·시험·로그 권위를 대체하지 않는다.

## 7. 구조적 hotspot

| 파일 | 현재 줄 수 | 집중된 책임 |
|---|---:|---|
| `static/css/admin.css` | 10,081 | 여러 관리자/시험 화면의 테마·표·모달·반응형 |
| `static/js/student.js` | 4,472 | public session, dashboard, 숙제, 검색, bootstrap, 재생, 공지, 시험 |
| `routes/api_basic.py` | 3,460 | 학생/자료/진도/배정/bootstrap/logs 및 여러 projection |
| `static/js/admin/features/calendar.js` | 3,094 | 캘린더·결석·보강·시트 동기화 |
| `static/js/admin/features/announcements.js` | 3,072 | 공지 편집·설문·대상·이미지 |
| `static/js/admin/features/logModal.js` | 2,981 | 로그·숙제·진도·통합 팝업 |
| `static/js/admin/features/videoModal.js` | 2,291 | 배정·진도·watch·로그 연계 |
| `static/js/admin/features/testModal.js` | 2,273 | 카탈로그 선택·최근 보기·상태 저장 |
| `static/js/tests.js` | 2,247 | 시험 카탈로그 전체 편집·기록·통계 |
| `static/js/admin/features/today.render.js` | 2,196 | 오늘/완료 행과 대부분의 row action |

큰 파일 자체를 결함으로 보지 않는다. 먼저 데이터 권위와 상태 전이를 테스트로 고정한 뒤 책임 단위로 분리한다.

## 8. 현재 cross-module seam과 호환 표면

아래 해결된 seam들은 동작 보존 검증과 함께 해소했고, 나머지 항목은 외부 소비자·호환 범위를 확인하며 순차 처리한다.

- 해결됨(4-2): `api_watch`는 `api_basic`을 import하지 않고 core progress 저장·알림 경계를 사용한다.
- 해결됨(4-3): `api_watch`와 `api_kollus`는 경로 주입형 `core/watch_progress_writer.py`를 함께 사용하며 서로의 private writer를 import하지 않는다.
- 해결됨(4-4): attendance, makeup route, offline sheet sync는 `routes/absence_assignment_cleanup.py` adapter를 공유하고 실제 날짜/SID projection은 `core/absence_assignment_cleanup.py`가 담당한다.
- 해결됨(4-4A): 새 결석의 updates → progress → dual logs → absent → optional carryover 쓰기는 `core/absence_transaction.py`의 no-mirror 저널과 좁은 before-image로 전부 커밋/롤백한다. 시작 시 미완료 저널을 복구하고 관련 HTTP 경로는 같은 coordinator barrier를 통과한다.
- 해결됨(4-5A): `api_tests`의 tests-config 잠금은 `core.storage.file_lock`, 답지 우선순위는 순수 `core/test_answer_links.py`를 사용한다. 관리자 시험 기록과 학생 bootstrap이 같은 해석 규칙을 쓰며, private `api_basic` lock/answer-link import는 제거됐다.
- 해결됨(4-5B): `api_fs`는 `api_announcements` private guard 대신 `core/announcement_image_access.py`의 잠금 store 판정을 사용한다. raw URI 단일 파일 검사·public SID gate·현재 SID-visible 공지 멤버십이 모두 통과해야 이미지를 전송한다.
- `student.js`는 classic script 제약 때문에 `shared/search.js`와 유사한 한글 검색 정규화를 자체 보유한다.
- 해결됨(5-1A): 호출되지 않던 `ensureTodayAssignmentIfMissing()`과 과거 배정 복사 writer를 `student.js`에서 제거했다. 학생 화면 소스에는 `/api/updates/patch` 쓰기가 없어야 하며 회귀 검사가 이를 고정한다.
- 해결됨(5-1B): 사용자 선택 A에 따라 삭제된 `main.html` 전용 `static/js/main.js`를 제거했다. 현재 로그인 shell은 `index.html` → `auth.js` → `/api/auth/change` 하나만 사용한다.
- 해결됨(5-1B/5-2A-1): 주석뿐이던 materials 모듈과 demo upload shim에 이어 materials 전체 POST, 고아 자료 모듈, 관리자 assignModal을 제거했다. materials 조회는 유지하며 활성 mat-assign 전환은 다음 소단계다.
- 해결됨(5-1B): 사용자 선택 A에 따라 실서버에 존재한 적 없는 `/api/delete-student` fallback과 demo shim을 제거했다. live/demo 모두 canonical `DELETE /api/students/:sid` 한 번만 호출하며, 실패 상태는 두 번째 요청 없이 그대로 표시한다.
- 해결됨(5-2A-1): 학생·materials·기본 logs 컬렉션은 GET-only로 고정했고 page-folders HTTP 표면을 제거했다. 학생 add/update/delete는 동일 students 파일 잠금 안에서 read-modify-write한다.
- 학생 숙제 관리자 API는 기능 플래그 ON에서만 등록되고 `logModal.js`는 404를 legacy 모드 신호로 사용한다.
- `/api/watch-status`는 현재 웹 학생이 쓰지 않으며 외부 개발 앱 병합 전까지 임시 유지한다.

## 9. 읽기의 부작용 등급

| 동작 | 등급 | 이유 |
|---|---|---|
| 순수 `core` rule 호출 | 무변경 | 파일·Flask 의존 없음 |
| 정적 소스/JSON 직접 읽기 | 원칙상 무변경 | 앱 import를 피할 때 |
| `core.paths`/`app` import | 생성 가능 | 누락 JSON·`files/` 생성 |
| 로그/조교 메모 repository 읽기 | SQLite 변경 가능 | schema 보장, WAL, backfill |
| bare `GET /api/updates` | 운영 쓰기 가능 | 실제 오늘 자동 snapshot 생성/rebase |
| 비공개 real-today bootstrap | 운영 쓰기 가능 | 누락 자동 배정 생성 가능 |
| `GET /api/updates?readOnly=1`, 비오늘/public bootstrap | storage-only 계약 | 자동 배정 생성 금지 |

## 10. 다음 감사 단계의 입력

Phase 3에서는 이 지도를 기준으로 각 후보를 다음 네 종류로 나눈다.

1. 실제 요구사항 모순
2. 상황별로 둘 다 필요한 별도 계약
3. 이미 비활성인 legacy/호환 코드
4. 동작은 맞지만 구조만 중복된 리팩터링 대상

판정 전에는 endpoint, runtime JSON/SQLite, 공개 학생 앱 flag, 학생 bootstrap shape를 변경하지 않는다.
