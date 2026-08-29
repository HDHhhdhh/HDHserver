# 학원 운영 허브 — 코드·데이터 흐름 지도

**규칙 소유권·감사 기준:** [SERVER_RULES_INDEX.md](SERVER_RULES_INDEX.md)
**범위:** `app.py`, `core/`, `routes/`, `static/`, 기본 검증 스크립트

이 문서는 “어떤 화면 요청이 어떤 규칙과 저장소를 거쳐 결과를 만드는가”를 정리한 구현 지도다. 사용자에게 보이는 의미와 상태 계약은 [PROJECT_FUNCTIONS_AND_LOGIC.md](PROJECT_FUNCTIONS_AND_LOGIC.md), 작업 안전 규칙은 루트 및 하위 `AGENTS.md`가 우선한다.

## 1. 점검 기준선

- 이 지도는 현재 소스의 책임과 연결을 설명한다. 특정 감사 실행, 백업 파일,
  서버 상태, 검사 통과 결과는 여기의 영구 규칙이 아니며 각 작업 결과에 기록한다.
- 파일 수, 줄 수, Blueprint 수, URL rule 수는 변경 때마다 움직이는
  파생값이므로 고정하지 않는다. 구조 판단은 아래 책임 표와 현재 심볼
  검색을 사용한다.

## 2. 앱 조립 모드

`create_app()`은 학생 앱 기능 플래그에 따라 Blueprint와 URL 표면을 조건부
등록한다. 따라서 문서나 테스트에서 Blueprint·URL 수를 상수로 가정하면
안 된다.

| 조립 모드 | 주요 플래그 | 학생 앱 추가 표면 |
|---|---|---|
| 기본 셸/플래그 OFF | `PUBLIC_ENABLED=0` | 모바일 인증·푸시·게시판 미등록 |
| 현재 예약 작업 인자 | public ON, dashboard/homework/reminders/focus OFF | 모바일 인증, 푸시 기반, 게시판 |
| 모든 학생 앱 기능 ON | public/dashboard/homework/reminders/focus ON | 위 기능 + 공개/관리자 숙제, 공개 focus |

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
| 사람·학생 명단 | `api_students`, `api_auth`, `api_student_accounts` | `person_identity`, `person_identity_store`, `student_auto_assignment_rules`, app-injected 배정 hook, 계정 규칙 | `persons.json`, `students.json`, identity journal, `auth_accounts.json` | 로그인, 관리자, 전체 학생 |
| 백지리뷰 검사 대기 | `api_students`의 `/api/update` | identity journal 또는 legacy roster lock의 SID 단일 필드 갱신 | `students.json.whiteReviewPending` | 관리자 오늘 학생 표 |
| 날짜·출결 | `api_attend`, `api_arrive_time`, `api_todaymeta`, `api_schedule_overrides`, `api_makeup_carryover` | `date_rules`, `absent`, `absence_assignment_cleanup`, `absence_transaction`, schedule projection, app-injected auto-assignment hooks, makeup sync | 출결 JSON군, `updates.json`, `progress.json`, class logs, `data/today_order.json`, `makeup_carryover.json`, transient journal | 관리자 오늘표·캘린더 |
| 수업 로그 | `api_logs`의 `/api/logs*`·`/api/homework-books` | `log_repository_provider`, `log_rules`, `LogRepository` | `app.sqlite.logs` 우선 + `logs.json` 호환 | 관리자 로그, 학생 숙제, 내보내기 |
| 학생 숙제 v2 | 조건부 `api_student_homework` | homework service/repository | 명시적 migration의 SQLite 숙제 테이블 | 관리자 로그 팝업, 학생 앱 |
| 영상 카탈로그 | `api_videos`의 `/api/videos` | route-local normal-save identity guard + offline correction rules | `videos.json` | 영상 관리, 관리자 배정, 학생 |
| 영상 배정 | `api_updates`의 `/api/updates*`, `api_student_bootstrap`의 `/api/student/bootstrap` | `update_assignment_store`, `student_auto_assignment_service`, `student_schedule_rules`, `student_video_projection`, `student_video_assignment_rules`, `student_bootstrap_projection`, update assignment 규칙 | `updates.json`, `progress.json`, `watch.json` | 관리자 영상 팝업, 학생 재생목록 |
| 시청·진도 | `api_progress`, `api_watch`, `api_kollus` | `watch_progress_writer`, `progress_rules`, `progress_store`, `progress_notifications` | `watch.json`, `progress.json` | 학생 재생, 관리자 상태색 |
| 시험 | `api_tests`, bootstrap | test config safety, answer-link projection | `tests-config.json`, `tests.json`, progress/log metadata | 시험 관리, 관리자 배정, 학생 카드 |
| 공지·게시판 | `api_announcements`, 조건부 `api_student_board` | board projection, notification event ID | `announcements.json`, `announce_status.json`, 첨부 파일 | 관리자 공지, 학생/학생 앱 |
| 학교 일정 | `api_school_calendar` | `school_calendar_store` | `school_calendar.json` | 학교 일정 편집, 관리자·전체 학생 일정 조회 |
| 자료·파일 | `api_materials`, `api_fs` | `material_state_provider` + material_reference_rules + material_state journal + 경로/파일-tree 잠금 | materials.json, mat_assign.json, page_folders.json, files/ | 관리자·학생 자료 |
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

서버의 일반 날짜 키는 `core/date_rules.py`가 실제 정규 `YYYY-MM-DD`인지 판정한다. 진도·로그·updates/self-study·watch/watch-status·schedule override는 불가능 날짜를 repository·lock·hook·알림·저장 전에 400으로 닫는다. 결석 전체-map은 사용자 결정 D-04의 500·무쓰기 알려진 제한을 그대로 유지한다.

`백지`는 선택 날짜에 속한 행에서 편집하지만 날짜별 상태가 아니다. `today.render.js`가 현재 SID의 `whiteReviewPending`을 렌더하고 exact boolean을 `/api/update`로 보내며, `api_students`가 identity journal 또는 legacy 명단 잠금 안에서 `students.json`의 그 SID만 갱신한다. 하원·기록 정리는 로그만 변경하므로 이 필드에 닿지 않는다.

### 5.2 학생 bootstrap

```text
legacy JWT 또는 public app cookie session
  → api_student_bootstrap가 요청 SID/active SID·날짜·학원망 검증
  → student_bootstrap_projection이 학생·결석·로그·배정·영상·진도·시청·시험·자료 집계
  → 현재 재생목록, reviewVideos, assignedTests projection
  → api_student_bootstrap가 public link/watch 제한과 no-cache 응답 조합
  → 단일 bootstrap 응답
  → student/bootstrapState.js가 bootstrap·latest-watch를 기존 초기 상태로 투영
  → student.js가 서버 membership만 정규화·렌더링
```

비공개 real-today bootstrap은 누락된 자동 배정을 만들 수 있다. public 요청, 다른 날짜, 읽기 전용 관리자 조회는 storage-only다. bootstrap 실패 시 학생 화면은 과거 다중 GET fallback을 사용하지 않는다.

### 5.3 영상 재생과 진도

```text
student.js playlist/board action → student/playback.js play(mid)
  → /api/get-url: 네트워크 + session SID + known SID/MID 검증
  → playback.js가 resume URL·iframe Kollus attach/poll·same-window active-MID progress 판정
  → student/watchState.js가 local monotonic merge·debounce·keepalive /api/watch 저장
  → 또는 Kollus LMS callback
  → core/watch_progress_writer의 monotonic watch merge·자동 progress write
  → progress_rules의 auto 상태 투영
  → 조건부 notification milestone hook
```

5%는 자동 `interrupted`, 90% 또는 완료 이벤트는 자동 `done`이다. 수동 흰색·skip·interrupted가 자동 상태보다 우선하며, watch 저장과 관리자 로그 저장은 모든 배정 영상이 완료돼도 기존 자동 배정 snapshot을 삭제·재선정·보충하지 않는다. 새 결석 원자 트랜잭션만 해당 날짜/SID 배정을 제거하며, 결석 취소는 이를 자동 복원하지 않는다.

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
  → 개별 시험 추가·수정·분류 이동은 revision 포함 PATCH
  → 전체 규칙·bulk import·명시적 삭제는 revision 포함 POST
  → 암묵 ID 삭제·stale revision 거부, unknown/source metadata 보존
  → progress의 날짜/SID test 상태가 학생 배정 권위
  → bootstrap이 답지 우선순위와 네트워크 제한을 투영
```

`tests.json`과 legacy 로그는 과거 기록 읽기용이다. 과거 학생 제출·OCR 표면은 등록하지 않으며 새 흐름은 아래 전용 경계로 분리한다.

### 5.5A 학생 시험 OCR

```text
학생 페이지 assignedTests
  → 기능·학원망·오늘 배정·UNIT 20문항 eligibility
  → SID/testId/round/date 일회용 capture token
  → 실시간 카메라 안정 프레임 5회 확인 + 3장 중 최적 full-sheet 저장
  → ArUco 4점 원근 보정 + 답안칸 검출 + blank-template 제거
  → answerModes별 1~5 숫자 분류/PaddleOCR 또는 UniMERNet/PP-FormulaNet-S
     · 1~3개 수식 불확실에만 적응형 2차 전처리
  → 0개 불확실: 서버 채점
     1~3개: 객관식 선택 또는 주관식 문항 재촬영
     4개 이상: 전체 재촬영
     주관식 2회 실패: pending_teacher
  → 학생 결과에는 오답 번호·보류 수·Drive 답지만 투영
  → 관리자 Basic-auth review에서 보류 확정/오답→정답 수정
     · 로컬 공식 PDF cache가 있으면 1쪽 정답표의 해당 셀을 동적 crop
     · 없거나 손상되면 기대값 + Drive 원문 링크로 fallback
```

`student_test_ocr_repository`가 submission/question/job/asset/history를 revision으로 묶는다. 서버 router만 `answerModes`로 crop을 분기하며 OCR worker payload에는 `questionNo`와 `imagePath`만 들어간다. 정답키는 채점 서비스가 카탈로그 revision을 다시 확인한 뒤 사용한다. 학생 파일은 생성 후 7일 보관한다. 공식 PDF crop은 `STUDENT_TEST_OCR_SOLUTION_PDF_ROOT` 아래 UNIT PDF를 읽기만 하고 no-store로 응답한다. 운영 schema migration과 feature flag 활성화는 품질 gate와 별도이며, 숫자 모델의 key-free `metrics.json`이 `GO`가 아니면 일반 runtime availability도 닫힌다.

### 5.6 학생 앱 알림

```text
공지/일정/숙제/진도 canonical mutation
  → feature flag 확인
  → idempotent notification event/outbox
  → push subscription 대상 lease/send/retry
```

reminders가 꺼져 있으면 일정·진도 hook은 repository를 열지 않고 0건으로 종료한다. 공지 push 기반은 별도이며 VAPID·스키마가 준비되지 않으면 fail-closed 응답을 사용한다.

### 5.7 사람 identity와 학생 쓰기

`persons.json`, `students.json`, pending journal 상태로 identity 활성 여부 판정
  → add/clone/update/delete 전에 두 저장소 strict load·검증
  → person 공유 필드와 SID 전용 필드를 분리해 projection
  → deterministic lock + before-image journal로 두 저장소 커밋
  → 동기 실패 rollback, crash journal은 시작/다음 쓰기 전에 복구

일반 add는 새 person을 만들고 `cloneFromSid`는 같은 person에 새 SID를
연결한다. identity 일부가 손실되면 legacy로 조용히 후퇴하지 않고 관련
학생 쓰기를 503으로 닫는다.

## 6. 저장소 지도

### 6.1 JSON·파일

| 묶음 | 파일 | 쓰기 특성 |
|---|---|---|
| 사람/학생/계정 | persons.json, students.json, identity pending journal, auth_accounts.json | identity 활성 시 person+student 저널 쓰기; legacy 설치는 기존 students 잠금 |
| 수업 | `logs.json`, `progress.json`, `updates.json`, `watch.json` | 날짜/SID/MID merge와 잠금 필요 |
| 출결 | `attendance.json`, `contact.json`, `arrive_time.json`, `absent.json`, `extra_attend.json`, `weekend_slots.json`, `makeup_carryover.json` | 학생·날짜 부분 갱신 |
| 카탈로그 | `videos.json`, `tests-config.json`, `tests.json` | 영상은 보호된 전체 저장; 시험은 개별 PATCH 또는 revision 전체 저장; 기록은 읽기 전용 |
| 자료/일정 | materials.json, mat_assign.json, page_folders.json, school_calendar.json, files/ | material state와 school calendar 모두 revision으로 stale whole-map write를 차단; calendar client는 단일 save queue 사용 |
| 공지 | `announcements.json`, `announce_status.json`, 첨부 파일 | 공지와 학생별 상태 분리 |
| 오늘 순서 | `data/today_order.json` | GET/PATCH/DELETE, 단일 canonical 경로 |

`core.paths`를 가져오면 누락된 canonical JSON과 `files/`를 생성한다. `AUTH_PATH`(`auth.json`)와 `CLINIC_PATH`(`clinic.json`)는 현재 생산 코드 소비자가 확인되지 않았지만 import 시 생성 대상이므로, 외부 사용 확인 없이 바로 제거하지 않는다.

### 6.2 `app.sqlite` 테이블

SQLite schema는 적용된 migration과 기능 플래그에 따라 달라지는 런타임
상태다. 고정 개수를 계약으로 삼지 말고, 확인이 필요하면 side effect
가능성을 고려해 현재 `sqlite_schema`를 점검한다. 현재 코드가 소유하는
주요 테이블군은 다음과 같다.

- `logs`
- `assistant_student_notes`, `admin_operation_notes`, `student_operation_logs`
- `student_app_sessions`, `student_account_audit`, `student_activation_codes`, `student_login_throttle`
- `student_push_subscriptions`, `student_push_outbox`, `student_push_bypasses`

다음 기능은 SQL 파일과 repository가 있어도 migration 적용 여부에 따라
관련 테이블이 없을 수 있다.

- focus: `student_focus_sessions`, `student_focus_events`
- homework: `student_homework_assignments`, `student_homework_reconciliations`
- reminders: preferences/events/schedule-state/milestones/deliveries 5개 테이블
- student test OCR: submissions, capture tokens, questions, assets, jobs, grade history 6개 테이블

마이그레이션은 수동 artifact이므로 기능을 켜는 결정과 분리해 임의
적용하지 않는다.

### 6.3 브라우저 저장소

- 학생 복습 목록: `student:review-playlist:<sid>:<date>`
- 관리자 선택일·최근 보기: 기능별 session/localStorage 키
- 데모: `academy.adminDemo.v1` 및 tutorial 전용 session key
- 학생 OCR 촬영 화면: `student-test-ocr-launch:<launchId>` sessionStorage(일회용 token·진행 중 submission 복구)

브라우저 저장소는 UI 편의 상태다. 서버 배정·진도·시험·로그 권위를 대체하지 않는다.

## 7. 구조적 hotspot

| 파일 | 집중된 책임 |
|---|---|
| `static/css/admin.css` | 여러 관리자/시험/동적 팝업의 broad cascade. 소비자·도메인 소유권은 [관리자 CSS 소유권 인벤토리](ADMIN_CSS_INVENTORY.md) 참조 |
| `static/css/admin-export-logs.css` | `/admin` 전용 수업 기록 내보내기 modal과 640px responsive override |
| `static/css/tests.css` | `/tests` 전용 catalog/editor/statistics/modal cascade와 반응형 override |
| `static/js/student/bootstrapState.js` | public/non-public bootstrap·latest-watch load와 기존 9칸 초기 상태 projection |
| `static/js/student/watchState.js` | SID별 local watch/resume 상태, 병합, epoch-millisecond snapshot, debounce/retry, `/api/watch` transport |
| `static/js/student/playback.js` | active MID, resume URL, `/api/get-url`, iframe Kollus attach/poll와 진도 message gate |
| `static/js/student/reviewPlaylist.js` | SID/날짜별 local key, fresh-authority prune, 선택 순서, 등록·취소 상태 |
| `static/js/student/announcementState.js` | strict 공지/게시판 정규화, 미확인·완료, ack/survey/reply 전이, 필터·페이지 병합 |
| `static/js/student/testPresentation.js` | assignedTests 정규화·status/난이도 라벨·답지 접근·카드 metadata·pending/mobile-nav projection |
| `static/js/student.js` | cache hydrate, 서버 복습 권위, 배정·DOM, playlist/player, 공지 transport/modal, 시험 카드 element와 학생 화면 orchestration |
| `routes/api_updates.py` | updates GET/PATCH/self-study HTTP 검증·503 응답·strict boolean 삭제·잠금 merge 뒤 future-auto gate와 app-injected service 호출 |
| `routes/api_student_bootstrap.py` | bootstrap GET, public active-SID·학원망·link/watch/no-cache HTTP 경계 |
| `routes/student_bootstrap_projection.py` | Flask-free bootstrap aggregate payload와 course/review/material/test 조합 |
| `routes/student_auto_assignment_service.py` | 주입된 결석 coordinator barrier·strict updates 저장·repository·lock·clock을 사용한 자동 초기화·자습 reconcile |
| `core/update_assignment_store.py` | `updates.json` strict object 읽기·원자 저장·공용 잠금과 typed store failure |
| `routes/api_basic.py` | 자동배정 dependency factory·호환 hook과 bootstrap dependency 조립 |
| `routes/api_students.py` | 학생 명단 GET, add/clone, 단일 필드 update, `whiteReviewPending` exact-boolean gate, retire와 app-injected 배정 후처리 |
| `routes/api_logs.py` / `routes/log_repository_provider.py` | 수업 로그 HTTP·숙제 교재 조회 / placeholder repair·공용 repository wiring |
| `routes/api_materials.py` / `routes/material_state_provider.py` | 자료·배정 HTTP / bootstrap과 공유하는 coherent·degraded material-state 읽기 |
| `routes/api_schedule_overrides.py` | 보강출석·주말 slot HTTP, 잠금 merge, 알림, app-injected 배정 후처리와 오늘 extra no-op 재시도 |
| `routes/api_videos.py` | 영상 카탈로그 GET/POST, Kollus MID 정규화, 정상 저장 identity guard |
| `routes/api_progress.py` | 진도 GET 필터와 잠금 PATCH merge·milestone 알림 경계 |
| `static/js/admin/features/calendar.js` | 캘린더·결석·보강·시트 동기화 |
| `static/js/admin/features/announcements.js` | 공지 편집·설문·대상·이미지 |
| `static/js/admin/features/logModal.js` | 로그·숙제·진도·통합 팝업 |
| `static/js/admin/features/videoModal.js` | 배정·진도·watch·로그 연계 |
| `static/js/admin/features/testModal.js` | 카탈로그 선택·최근 보기·상태 저장 |
| `static/js/tests.js` | 개별 시험 PATCH, 전체 규칙·삭제 저장, 기록·통계 |
| `static/js/admin/features/today.render.js` | 오늘/완료 행, 백지리뷰 검사 대기 표시·저장, 대부분의 row action |
| `static/js/school-cal.js` | 학기/시험 DOM 상태, 표 렌더링, 이벤트, 저장 시점·사용자 피드백 |
| `static/js/school-calendar/state.js` | 순수 문서↔편집 행 projection, 정규화, active-page metadata |
| `static/js/school-calendar/persistence.js` | no-store GET, revision 초기화, auto/switch/flush/metadata 저장 queue 조합 |

큰 파일 자체를 결함으로 보지 않는다. 먼저 데이터 권위와 상태 전이를 테스트로 고정한 뒤 책임 단위로 분리한다.
D-08의 school-calendar 두 seam과 `api_basic.py`의 영상 카탈로그·진도·수업 로그·자료 배정·schedule override·학생 identity·updates·학생 bootstrap HTTP seam은 완료됐다. 일정 HTTP 경계는 `routes/api_school_calendar.py`, client transport는 `static/js/school-calendar/persistence.js`, 순수 문서 state는 `static/js/school-calendar/state.js`가 소유하며 `school-cal.js`에는 DOM·이벤트 orchestration이 남는다. 영상 카탈로그는 `routes/api_videos.py`, 진도 GET·PATCH는 `routes/api_progress.py`, 수업 로그와 숙제 교재 조회는 `routes/api_logs.py`, route-side placeholder repair와 공용 factory는 `routes/log_repository_provider.py`가 소유한다. 자료 GET과 revisioned 배정 저장은 `routes/api_materials.py`, bootstrap과 공유하는 coherent·degraded 읽기는 `routes/material_state_provider.py`가 소유한다. 보강출석과 주말 slot HTTP는 `routes/api_schedule_overrides.py`, 학생 roster/identity HTTP는 `routes/api_students.py`, updates GET/PATCH/self-study HTTP는 `routes/api_updates.py`가 소유하고 `app.py`가 public assignment hook을 주입한다. 학생 bootstrap/watch/playback/review-local/announcement/test-presentation은 각각 `static/js/student/bootstrapState.js`, `static/js/student/watchState.js`, `static/js/student/playback.js`, `static/js/student/reviewPlaylist.js`, `static/js/student/announcementState.js`, `static/js/student/testPresentation.js`로 분리되어 이 순서로 `student.js`보다 먼저 로드된다. playback 모듈은 active MID, resume URL, `/api/get-url`, iframe Kollus bridge와 progress message를, review 모듈은 fresh-authority 안의 SID/날짜별 선택·등록·취소를, announcement 모듈은 strict 정규화·미확인/완료·ack/survey/reply 전이·필터·페이지 병합을, test-presentation 모듈은 assignedTests 정규화·라벨·답지 접근·card metadata·pending/mobile-nav를 소유한다. 관리자 시험 카탈로그의 정규화·검색/정렬·그룹·순서 gate·revision request projection은 `static/js/tests/catalogState.js`, 답안 parser·mode·회차 merge·CSV projection은 `static/js/tests/catalogEditorState.js`, 통계 lookup·summary·검색/정렬·상세 presentation은 `static/js/tests/catalogStatisticsState.js`로 분리됐고 `tests.js`에는 fetch/file/table/modal DOM/mutation orchestration이 남는다. SID/merge/source 규칙과 updates 잠금은 core 모듈로 공유하고, A:Ble 기본 배정 수 규칙은 `core/student_auto_assignment_rules.py`가 자동 배정과 roster update에 함께 제공한다. 자동배정의 일정 해석·영상 projection·배정 변환은 각각 `core/student_schedule_rules.py`, `core/student_video_projection.py`, `core/student_video_assignment_rules.py`가 소유하고, 주입형 runtime read·lock·save·자습 reconcile은 `routes/student_auto_assignment_service.py`가 소유한다. `api_basic.py`에는 dependency factory·호환 hook과 bootstrap 조립만 남는다. 후속 분할도 독립 oracle·실제 임시 route/store gate 아래 한 도메인씩 이동한다. `/tests`의 page-only cascade는 `static/css/tests.css`로 분리됐다. `admin.css`의 소비자·도메인 소유권·결정 queue는 [관리자 CSS 소유권 인벤토리](ADMIN_CSS_INVENTORY.md)가 정본이다. 첫 후보인 `/admin` 수업 기록 내보내기 modal은 `static/css/admin-export-logs.css`로 분리됐다.

## 8. 현재 cross-module seam과 호환 표면

아래 해결된 seam들은 동작 보존 검증과 함께 해소했고, 나머지 항목은 외부 소비자·호환 범위를 확인하며 순차 처리한다.

- 해결됨(4-2): `api_watch`는 `api_basic`을 import하지 않고 core progress 저장·알림 경계를 사용한다.
- 해결됨(4-3): `api_watch`와 `api_kollus`는 경로 주입형 `core/watch_progress_writer.py`를 함께 사용하며 서로의 private writer를 import하지 않는다.
- 해결됨(4-4): attendance, makeup route, offline sheet sync는 `routes/absence_assignment_cleanup.py` adapter를 공유하고 실제 날짜/SID projection은 `core/absence_assignment_cleanup.py`가 담당한다.
- 해결됨(4-4A): 새 결석의 updates → progress → dual logs → absent → optional carryover 쓰기는 `core/absence_transaction.py`의 no-mirror 저널과 좁은 before-image로 전부 커밋/롤백한다. 시작 시 미완료 저널을 복구하고 관련 HTTP 경로와 `student_auto_assignment_service`의 실제 writer는 같은 coordinator barrier를 통과한다. 자동배정은 coordinator → authoritative absence read → updates lock 순서이며 동일 요청의 중첩 barrier만 재진입한다.
- 해결됨(4-5A): `api_tests`의 tests-config 잠금은 `core.storage.file_lock`, 답지 우선순위는 순수 `core/test_answer_links.py`를 사용한다. 관리자 시험 기록과 학생 bootstrap이 같은 해석 규칙을 쓰며, private `api_basic` lock/answer-link import는 제거됐다.
- 해결됨: 시험 정의 추가·수정·분류 이동은 `PATCH /api/tests-config/test`로 한 레코드만 병합하고, 전체 POST는 규칙·bulk import·명시적 삭제에 한정한다.
- 해결됨(4-5B): `api_fs`는 `api_announcements` private guard 대신 `core/announcement_image_access.py`의 잠금 store 판정을 사용한다. raw URI 단일 파일 검사·public SID gate·현재 SID-visible 공지 멤버십이 모두 통과해야 이미지를 전송한다.
- 해결됨(D-08): `api_students.py`가 학생 GET/add/clone/update/delete를 소유한다. identity 활성화 시 `person_identity_store`로 두 파일을 journal commit하고 legacy mode와 부분 손실 fail-closed를 구분한다. `app.py`가 `api_basic`의 public 배정 hook을 주입하며 private helper import는 없다.
- 해결됨(D-08): `api_updates.py`가 updates GET/PATCH/self-study HTTP를 단독 소유한다. `app.py`가 `api_basic`의 public 초기화·자습 reconcile 서비스를 주입하고, 전용 blueprint는 private helper를 import하지 않는다. `core/update_assignment_store.py`는 파일 부재와 손상·비-object를 구분하는 strict persistence와 공용 잠금을 소유한다. PATCH 삭제는 JSON boolean만 받고 미래 자동 배정 gate는 잠금 안의 최종 병합 결과에 적용하므로 `source` 생략으로 우회할 수 없다. `verify_updates_routes.py`가 실제 임시 store의 literal 응답·merge, strict 삭제 타입, 미래-auto 제거·재분류와 우회 거부, 손상 503, 파일 부재 초기화 및 실패 byte/SHA-256 불변을 고정한다.
- 해결됨(D-08): `api_student_bootstrap.py`가 bootstrap GET, public active-SID, 학원망 판정, 공개 link/watch sanitize와 no-cache 응답을 소유하고, `student_bootstrap_projection.py`가 Flask-free 집계 payload를 소유한다. `app.py`는 `api_basic`이 만든 명시적 dependency bundle을 주입한다. `verify_student_bootstrap_routes.py`는 실제 전용 blueprint와 임시 store에서 literal ghost/regular/public payload, today auto-init 호출 경계, 실패·과거·public 조회의 byte/SHA-256 불변을 고정한다.
- 해결됨(D-08): 자동배정의 날짜·slot·자습·결석 해석, 현재 과정·완료·차단·복습 응답 projection, 자습 과거 영상 선택·자동 append/rebase를 세 순수 core 모듈로 분리했다. `verify_student_video_assignment_rules.py`는 production helper로 기대값을 재계산하지 않는 literal oracle, runtime import 부재, 입력 불변을 확인하고 기존 snapshot·route·bootstrap 회귀가 실제 조합 경계를 고정한다. 사용자 승인 2A로 backend 설정 상한도 UI와 같은 6으로 맞췄으며 새 snapshot만 이 cap을 사용하고 기존 날짜 snapshot은 그대로 둔다.
- 해결됨(D-08 student.js 1차): `static/js/student/bootstrapState.js`가 public-session 또는 비공개 bootstrap·latest-watch load와 9칸 호환 projection을 소유한다. `student.js`에는 active SID 반영과 cache/DOM hydrate가 남고, 독립 Node oracle이 literal projection·병렬 시작·실패 중단·script 순서를 고정한다.
- 해결됨(D-08 student.js 2차): `static/js/student/watchState.js`가 주입형 SID/date/access/request/clock 경계에서 local watch/resume 저장, monotonic 병합, millisecond snapshot, debounce·재시도·keepalive `/api/watch` 저장을 소유한다. `student.js`에는 배정 판정, DOM badge와 lifecycle listener, active-MID Kollus event/play orchestration이 남으며 독립 Node oracle이 literal merge/payload, 입력 불변, 중복 억제, 실패 재시도, access gate, lifecycle flush와 script 순서를 실행한다.
- 해결됨(D-08 student.js 3차): `static/js/student/playback.js`가 주입형 window/location/frame/SID/access/watch/request/timer 경계에서 active MID, resume URL, `/api/get-url`, HTTPS upgrade, iframe Kollus attach/poll, same-window/MID 진도 event와 90% 완료 판정을 소유한다. `student.js`에는 playlist 선택, player ready/empty, board-scroll DOM orchestration이 남으며 독립 Node oracle이 literal URL/payload, progress input hash 불변, switch flush, controller retry/timeout과 403/500/network 실패를 실행한다.
- 해결됨(D-08 student.js 4차): `static/js/student/reviewPlaylist.js`가 주입형 storage/SID/date 경계에서 local key, 저장 MID 정규화, fresh bootstrap prune, chooser 삽입 순서, 등록·취소를 소유한다. `student.js`에는 서버 권위 `reviewVideos` 정규화, access/blocking, DOM·재생 조합이 남으며 독립 Node oracle과 기존 DOM 회귀가 key scope, prune, 순서, 멱등성, 취소·재등록, SID/날짜 격리와 무서버 쓰기를 교차 확인한다.
- 해결됨(D-08 student.js 5차): `static/js/student/announcementState.js`가 strict 공지/게시판 projection, 미확인·완료, 확인·설문·답장 전이, 답장 3회 제한, 필터와 deduplicated pagination을 소유한다. `student.js`에는 endpoint transport, modal/carousel/form DOM, 접근성, board scroll/focus와 사용자 피드백이 남으며 literal 독립 oracle과 기존 student-mobile board/notifications 회귀가 의미·실표면을 교차 확인한다.
- 해결됨(D-08 student.js 6차): `static/js/student/testPresentation.js`가 assignedTests unknown-field 보존 정규화·dedupe, status/일산 난이도 라벨, 답지 alias·학원망 접근, card metadata·pending count·mobile same-tab 규칙을 소유한다. `student.js`에는 `<a>`/`<button>` 생성, target/rel, disabled, 제한 안내와 DOM append가 남으며 literal 독립 oracle과 기존 answer-mobile·material-access VM·retired-submission 회귀가 의미·실표면을 교차 확인한다.
- 해결됨(D-08 tests.js 1차): `static/js/tests/catalogState.js`가 config/test 정규화, 검색·정렬·그룹, reorder scope gate, revisioned POST/PATCH request projection과 deep rollback snapshot을 DOM·fetch 없이 소유한다. `tests.js`에는 실제 endpoint·mutation lock·편집/CSV/목록 DOM·rollback 렌더가 남으며 literal/hash oracle, 분리 전 entrypoint reorder/409/rollback 회귀, temp Flask write-safety가 서로 독립된 증거를 제공한다.
- 해결됨(D-08 tests.js 2차 + 1A): `static/js/tests/catalogEditorState.js`가 답안 문자열·문항 mode 정규화/검증/요약, 기존 회차를 보존하는 answer map projection, CSV template/cell/parser/header alias와 행별 답안 projection을 DOM·fetch·file 없이 소유한다. `tests.js`에는 file/blob/download·editor DOM, config mutation/save와 feedback이 남으며 literal/hash oracle, 기존 entrypoint VM, core/migration answer-mode 검증과 temp Flask write-safety가 교차 확인한다. Compact `1342`는 한 답안으로 유지하고 UI는 공백·쉼표 구분 다문항 형식만 안내한다.
- 해결됨(D-08 tests.js 3차): `static/js/tests/catalogStatisticsState.js`가 통계 라벨·lookup 우선순위·summary·검색/정렬·응시/오답 상세 presentation을 DOM·fetch·storage 없이 소유한다. `tests.js`에는 통계 endpoint/loading, escape된 table/modal DOM과 event가 남으며 literal/hash oracle, 분리 전 entrypoint VM, 관리자 record-detail UI/backend 계약과 두 브라우저 QA가 교차 확인한다. 상세 답지 URL은 API 응답에서만 오며 static map으로 fallback하지 않는다.
- 해결됨(D-08 CSS 1차): `static/tests.html`의 1,729줄 page-only cascade를 `static/css/tests.css`로 이동하고 `main.css` → `admin.css` 뒤에 로드한다. 선택자·선언·breakpoint 순서는 분리 전 정규화 SHA-256으로, HTML body·script 계약은 별도 SHA-256으로 고정한다. 기존 mobile-touch, answer-mode, answer-link, record-detail 검증은 실제 외부 CSS를 읽으며 두 브라우저의 계산 스타일·레이아웃·통계 모달을 분리 전 기준선과 비교한다.
- 해결됨(D-08 CSS 2차): `/admin`만 소비하는 수업 기록 내보내기 modal 201줄을 `static/css/admin-export-logs.css`로 이동해 `admin.css` 뒤에 로드한다. `/tests`와 `/all` 팝업은 새 파일을 로드하지 않으며, pre-split CSS/DOM hash·기존 export 기능 verifier·두 브라우저의 desktop/mobile·light/dark 계산 스타일과 Escape 초점 복귀가 경계를 고정한다.
- `student.js`는 classic script 제약 때문에 `shared/search.js`와 유사한 한글 검색 정규화를 자체 보유한다.
- 해결됨(5-1A): 호출되지 않던 `ensureTodayAssignmentIfMissing()`과 과거 배정 복사 writer를 `student.js`에서 제거했다. 학생 화면 소스에는 `/api/updates/patch` 쓰기가 없어야 하며 회귀 검사가 이를 고정한다.
- 해결됨(5-1B): 사용자 선택 A에 따라 삭제된 `main.html` 전용 `static/js/main.js`를 제거했다. 현재 로그인 shell은 `index.html` → `auth.js` → `/api/auth/change` 하나만 사용한다.
- 해결됨(5-1B/5-2A-1 및 후속): 주석뿐이던 materials 모듈과 demo upload shim, materials 전체 POST, 고아 자료 모듈, 관리자 assignModal을 제거했다. 활성 mat-assign은 material-state revision·저널 경계로 전환됐다.
- 해결됨(5-1B): 사용자 선택 A에 따라 실서버에 존재한 적 없는 `/api/delete-student` fallback과 demo shim을 제거했다. live/demo 모두 canonical `DELETE /api/students/:sid` 한 번만 호출하며, 실패 상태는 두 번째 요청 없이 그대로 표시한다.
- 해결됨(5-2A-1): 학생·materials·기본 logs 컬렉션은 GET-only로 고정했고 page-folders HTTP 표면을 제거했다. 학생 add/update/delete는 동일 students 파일 잠금 안에서 read-modify-write한다.
- 해결됨(D-06B/D-08 두 seam, 작업 트리): school-calendar GET revision과 POST `If-Match` 428/409를 strict core store에 두고 HTTP route를 `api_school_calendar.py`로 분리했다. 화면의 no-store GET과 auto/switch/flush/metadata 저장은 `school-calendar/persistence.js`, 순수 문서↔편집 행 projection은 `school-calendar/state.js`가 소유한다. literal oracle·실제 임시 route 경합·두 브라우저 DOM/저장/stale 409 gate가 이 경계를 고정하며 운영 8003 rollout은 별도 배포 단계다.
- 해결됨(D-08 + 3A): 보강출석 GET/PATCH와 주말 slot GET/POST는 `api_schedule_overrides.py`로 이동했다. `app.py`가 `api_basic`의 public assignment hook을 주입하므로 전용 blueprint는 private helper를 import하지 않는다. Weekend POST는 전체 body·실제 ISO 날짜·ghost·roster SID를 쓰기 전에 검증하고 400/403/404 실패에서는 저장·reconcile·알림을 모두 생략한다.
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

## 10. 감사와 변경의 입력

규칙의 의미·결정·검증 소유권은 `SERVER_RULES_INDEX.md`에서 시작한다.
이 지도는 현재 코드 연결을 확인하는 데만 사용한다. 문서와 코드가 다르면
실제 동작과 의도된 규칙을 따로 판정하고 구현 드리프트로 기록한 뒤,
사용자 결정 없이 endpoint·runtime data·응답 shape를 바꾸지 않는다.
