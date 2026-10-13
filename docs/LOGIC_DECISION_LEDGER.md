# 로직 결정 원장

**규칙 소유권·감사 기준:** [SERVER_RULES_INDEX.md](SERVER_RULES_INDEX.md)

**목적:** 과거 주문, 현재 구현, 현재 운영 설정이 다를 때 어떤 계약을 따를지 기록한다.

이 문서는 구현 흐름을 설명하는 문서가 아니다. 상세 현재 동작은 [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md), 코드 연결은 [코드 흐름 지도](CODE_FLOW_MAP.md)를 따른다. 여기서는 서로 다른 설명이 발견됐을 때의 판정과 아직 필요한 사용자 결정을 관리한다.

## 판정 기준

1. 실제 동작은 현재 코드와 런타임을 읽기 전용으로 검증해 판정한다.
2. 의도된 규칙은 최신의 명시적 사용자 결정, 이 결정 원장, 기능·로직 기준서 순으로 판정한다.
3. 실제 동작과 의도된 규칙이 다르면 한쪽을 조용히 정본으로 만들지 않고 구현 드리프트로 기록한다.
4. 현재 코드만으로 주문의 의도를 단정하지 않는다. 후속 커밋이 앞선 주문을 되돌렸다면 사용자 확인 대상으로 남긴다.
5. 날짜, 호스트, 네트워크, 배정 출처가 다른 계약은 모순으로 합치지 않는다.
6. 외부 소비자를 확인할 수 없는 endpoint와 직접 정적 경로는 호환 대상으로 보존한다.
7. `결정 필요` 항목이 해결되기 전에는 해당 동작을 삭제하거나 넓히지 않는다.

## 확정된 판정

### 2026-09-13 시험 전 출석의 연강 집계

사용자 결정: 시험 전 출석은 등원한 날짜 수가 아니라 수업 타임 수다. 정규 등원을 날짜당 1회로 세던 규칙을 대체한다. 집계 기간·보강 중복 제거·결석 및 자습 제외·미예약 보강 안내는 [기능·로직 기준서 §7](PROJECT_FUNCTIONS_AND_LOGIC.md#7-출결오늘-순서보강)을 따른다. 화면 조회 계산만 변경하고 학생 일정·출결 등 운영 데이터는 수정하지 않는다.

### 2026-09-13 자습 결석의 보강 제외

사용자 결정: 자습으로 설정된 학생의 관리자 결석 처리는 보강 명단에 자동 등록하지 않는다. 일반 수업 결석과 기존 배정 정리는 유지한다. 날짜별 판정·영구 제외 근거·복구 후 재등록·기존 기록 보존 계약은 [기능·로직 기준서 §7](PROJECT_FUNCTIONS_AND_LOGIC.md#7-출결오늘-순서보강)을 따른다. 과거 운영 데이터 일괄 보정과 추가 운영 재시작은 이 요청에 포함하지 않는다.

### 2026-09-12 영상 초록 재배정

사용자 승인: 수동 미완료에서 명시적으로 초록으로 되돌리면 자동 진도를 재개한다. 이미 완료한 영상도 **새 재배정 이후의 시청**으로 재판정하며 과거 시청 기록은 보존한다. 배정 출처의 수동 보호와 흰색·주황·제외의 수동 진도 보호는 별개다. 상세 계약과 검증은 [기능·로직 기준서 §10](PROJECT_FUNCTIONS_AND_LOGIC.md#10-시청-기록과-진도-상태)을 따른다. 기존 runtime 기록 일괄 보정과 운영 재시작은 이 의미 결정에 포함하지 않는다.

| ID | 충돌한 설명 | 현행 판정 | 근거·조치 |
|---|---|---|---|
| L-01 | PWA를 제거한다 / 학생 앱 PWA를 제공한다 | 후속 주문이 제거 방침을 대체했다. PWA는 현재 기능이다. | `20cfa6e`에서 학생 앱이 통합됐고 현재 예약 작업은 public만 켠다. 2026-08-13 문서는 역사 기록으로만 본다. |
| L-02 | `5a-math.com`과 `app.5a-math.com`은 같은 별칭이다 / 서로 다른 공개면이다 | 서로 다른 origin과 역할을 가진다. | legacy host는 기존 로그인·학생 화면을 유지하고 앱 전용 경로를 막는다. app host는 HTTPS와 명시 allowlist만 허용한다. |
| L-03 | 공개 HTTP는 모두 HTTPS 308이다 / app HTTP는 404이고 legacy root는 유지된다 | 현재의 단계별 도메인 전환 계약을 따른다. | app host HTTP는 404다. legacy root는 독립 redirect 승인이 꺼진 동안 200이며, 승인 뒤에도 쿼리 없는 루트 GET/HEAD만 app URL로 302한다. |
| L-04 | 학생 시험 제출·채점·OCR이 폐기됐다 / 새 OCR 제출을 도입한다 | 과거 표면은 계속 폐기하고 새 기능으로 분리한다. | `/student-test/<sid>`, `/api/submit-test`, `/api/ocr-test-sheet*`는 복원하지 않는다. 신규 `/student-test-capture`와 `/api/student-test-ocr/*`는 D-09 계약으로 구현하며 품질 gate 전까지 기본 OFF다. |
| L-05 | bootstrap 실패 시 여러 API로 복원한다 / 오류를 표시하고 중단한다 | 단일 bootstrap이 권위이며 실패 시 중단한다. | 구형 7개 요청 fallback은 제거됐고 부분 데이터 조립을 되살리지 않는다. |
| L-06 | 복습 후보는 `done` 또는 `interrupted`다 / `done`만 허용한다 | 현재 과정의 `done`만 허용한다. | `reviewVideos`는 서버가 정제한 유일한 권위다. `interrupted`, `skip`, `none`은 후보가 아니다. |
| L-07 | 영상 `training-pack` 배정 API가 있다 / 트레이닝팩은 시험 분류다 | 시험 카테고리 의미만 유지한다. | `/api/updates/training-pack`과 `/api/updates/review`는 존재하지 않는다. |
| L-08 | 영상 자동 배정은 조회로 실행하지 않는다 / 일부 조회가 오늘 snapshot을 만들 수 있다 | 문맥이 다른 계약이다. | 관리자 모달은 `readOnly=1`로 순수 조회한다. real-today의 bare updates GET, 날짜 경계, 허용된 bootstrap·일정 이벤트만 멱등 생성할 수 있다. 과거·미래 조회는 생성하지 않는다. |
| L-09 | legacy 학생 사본도 현재 화면이다 / 단일 학생 화면만 쓴다 | 사본은 제거됐다. | `static/student copy.html`, `static/js/student copy.js`를 복원하지 않는다. |
| L-10 | dashboard·homework·reminders·focus 코드가 있으므로 운영 중이다 / 현재 꺼져 있다 | 구현 존재와 운영 활성은 별도다. | 현재 예약 작업은 public만 ON이고 네 기능은 OFF다. 마이그레이션과 rollout 승인 없이 활성화하지 않는다. |
| L-11 | 결석 저장 실패 시 호출부의 부분 롤백을 유지한다 / 관련 저장소 전체를 원상복구한다 | 사용자 선택 A에 따라 롤백 우선 원자성 계약으로 변경한다. | updates, progress, SQLite/JSON class logs, absent, optional makeup carryover의 좁은 before-image를 저널링한다. 성공 전 오류는 전부 복구하고, 미완료 저널은 시작/다음 쓰기 전에 복구하며, 복구 실패는 503·시작 실패로 닫는다. |
| L-12 | 서버는 항상 시작 가능해야 한다 / 손상된 파일·교재 트랜잭션 때문에 전체 시작을 막는다 | 전체 서버는 시작하고 파일·교재 쓰기만 읽기 전용 저하 모드로 닫는다. | 유효 저널은 자동 roll-forward한다. 앞 문장의 roll-forward는 version 1 경계이며, v2의 prepared rollback·committing roll-forward 구분은 D-07과 [정본 §13](PROJECT_FUNCTIONS_AND_LOGIC.md#13-공지설문캘린더자료)을 따른다. 읽을 수 없는 저널·저장소는 마지막 정상 snapshot(없으면 빈 읽기 전용 projection)으로 조회를 유지하고, `/api/mat-assign`과 파일 mutation은 503을 반환한다. whole-map 배정 저장은 revision/`If-Match`로 stale overwrite를 409 차단한다. |
| L-13 | 영상 완료·skip 뒤 오늘 배정을 지우고 다음 영상을 보충한다 / 날짜 최초 배정을 고정한다 | 사용자 선택 1A에 따라 날짜별 자동 배정은 고정 snapshot이다. | 모든 배정 영상이 완료·skip이어도 로그 저장과 watch/progress 쓰기는 배정을 삭제·전진·보충하지 않는다. 과정 변경 때만 현재 과정 밖 MID를 교체하며 유효한 기존 MID와 가능한 원래 슬롯 수를 보존한다. |
| L-14 | 자동 snapshot은 결석 변화에도 불변이다 / 새 결석 저장은 해당 날짜 배정을 제거한다 | 사용자 선택 2A에 따라 새 결석 원자 트랜잭션을 명시적 삭제 예외로 둔다. | 새 `(date, sid)` 결석 커밋만 updates 배정을 제거한다. 자동 초기화/self-study writer는 coordinator → 권위 결석 read → updates lock 순서를 사용해 삭제 후 stale 재생성을 막는다. 결석 취소는 자동 복원하지 않으며, 일반 일정·연강·진도·watch 변경은 L-13 snapshot을 유지한다. |
| L-15 | 복습 등록 뒤 현재 DOM만 갱신한다 / 플레이어 재구성을 위해 사용자가 직접 새로고침한다 | 2026-08-29 사용자 결정에 따라 새 복습 등록 성공 직후 페이지를 한 번 강제 새로고침한다. | 등록은 계속 SID/date localStorage 전용이고 서버 배정·로그·진도 쓰기를 하지 않는다. 새로고침 bootstrap이 목록·플레이어 표면을 다시 구성하며 `/api/get-url`과 watch는 등록 행을 실제 재생할 때만 사용한다. |

## 모순이 아닌 병존 계약

| 구분 | 함께 유지할 계약 |
|---|---|
| 날짜 | 관리자 선택일·행 `data-date`와 서버의 real-today는 목적이 다르다. |
| 영상 상태 | 수동 `none`·`skip`·`interrupted`와 watch 자동 `interrupted`·`done`은 소유권이 다르다. |
| 영상 배정 | `auto`, `manual`, `selfStudy`, 학생 local review playlist는 서로 대체하지 않는다. |
| 저장소 | 수업 로그는 SQLite 우선이지만 `logs.json` 결손 보충·호환을 유지한다. |
| 공개면 | legacy 학생 JWT 흐름과 public app cookie session은 서로 다른 인증 표면이다. |
| 기능 플래그 | 비활성 Blueprint 코드가 존재해도 등록되지 않은 endpoint는 현재 기능이 아니다. |

## 사용자 결정 상태

### D-01 관리자 원격 접속

- 2026-08-13 `fbb3a2e`는 올바른 Basic 인증이면 학원 밖 관리자 접속을 허용했다.
- 2026-08-16 `c234f0c`는 당시 학원망·loopback 제한을 다시 추가했다. 현행 정책은 아래 2026-08-24 사용자 결정을 따른다.
- **사용자 결정(2026-08-24): 학원 밖에서도 올바른 Basic 인증이면 관리자 페이지를 허용한다.**
- 적용 상태: 관리자 페이지와 학원 밖 non-public 관리자 API는 동일한 fail-closed Basic을 요구한다. 학생 앱 공개 host의 관리자 API 404와 학생·Kollus 경로가 이미 가진 session/CSRF, 학원망, SID/MID, callback-secret 계약은 Basic보다 먼저 유지한다. D-03으로 제외한 비활성 homework/focus 기능은 활성화하지 않았다.

### D-02 별도 개발 학생 앱 호환

- `/api/watch-status`는 현재 웹 학생이 사용하지 않는다.
- 코드와 지침은 다른 컴퓨터에서 개발 중인 학생 앱이 `/api/watch`로 이관될 때까지 유지하라고 명시한다.
- **사용자 결정(2026-08-24): 별도 학생 앱을 현재 사용 중이므로 endpoint와 응답 형태를 유지한다.**
- 적용 상태: 현재 동작과 일치한다. 별도 앱이 `/api/watch`로 이관됐다는 후속 결정 전에는 제거하지 않는다.

### D-03 비활성 학생 앱 기능의 리팩터링 범위

- dashboard: 학생의 과정 진도, 다음 수업, 숙제 수, 읽지 않은 게시판 수를 한 화면에 요약한다.
- homework: 기존 수업 로그와 별도로 SQLite에 숙제 배정·마감·완료 상태를 관리하고 관리자 저장과 맞춘다.
- reminders: 수업·숙제 마감·진도·공지 알림을 큐에 넣어 앱 push로 보낸다.
- focus: 수업 시간에 집중 세션을 시작·종료하고 화면 숨김 시간을 "앱 이탈 추정"으로 기록해 관리자 요약에 보여 준다.
- **사용자 결정(2026-08-24): 네 기능은 계속 OFF로 보존하고 첫 구조 리팩터링의 동작 변경 범위에서 제외한다. 삭제·활성화·운영 DB migration을 수행하지 않는다.**

### D-04 결석 전체 저장의 실재하지 않는 달력 날짜

- `/api/absent`의 전체 저장은 `YYYY-MM-DD` 모양이지만 실제 달력에 없는 날짜(예: `2026-99-99`)를 신규 결석으로 받으면 트랜잭션 진입 전 검증 예외를 500으로 반환한다.
- 이 경우 updates, progress, SQLite/JSON class logs, absent, makeup carryover는 전부 무변경이고 일정 알림도 발생하지 않는다.
- **사용자 결정(2026-08-24, 선택 B): 400 선행 검증으로 바꾸지 않고 현재 500을 알려진 제한으로 유지한다.**
- 적용 상태: `verify_absence_makeup_matrix.py`의 A12가 `500 + 무쓰기 + 무알림`을 `[KNOWN]`으로 계속 확인한다. 향후 400으로 개선되면 같은 검증은 정상 PASS로 전환될 수 있으며, 현재 500을 바람직한 API 계약으로 해석하지 않는다.

### D-05 legacy·미사용 소비자 정리

- 동작 무변경 정리: 호출 0회였던 학생측 과거 배정 복사 writer를 제거하고, 학생 소스에 `/api/updates/patch`가 다시 생기지 않도록 검사한다.
- 유지 확정: `/api/watch-status`는 D-02에 따라 외부 학생 앱 이관 전까지 유지한다. homework/focus/reminders/dashboard는 D-03에 따라 OFF 상태로 보존한다.
- **사용자 결정(2026-08-24, 모두 A): 삭제된 `main.html` 전용 `static/js/main.js`, 전부 주석 처리된 `materials.js`와 demo upload shim, `/api/delete-student` fallback을 모두 제거한다.**
- 적용 상태: 두 정적 파일과 주석 import/init, 두 demo shim을 제거했다. 학생 삭제는 성공·실패 모두 canonical DELETE 한 번만 보내며 전용 실행 검사가 이를 고정한다.
- full-map legacy API의 별도 데이터 계약 결정과 적용 상태는 D-06에서 이어서 관리한다.

### D-06 전체맵 저장 계약 정리

- 사용자 결정(2026-08-24, 모두 A): 소비자 없는 전체 컬렉션 POST는 제거하고, 활성 자료 배정은 서버 잠금 명령형 API로, 학교 일정은 저장 큐와 revision 충돌 방지로 전환한다.
- 적용 상태(5-2A-1): /api/students, /api/materials, 기본 /api/logs는 GET 전용이다. 학생 쓰기는 잠금된 add/update/delete 경로만 사용하고, 로그 쓰기는 patch/patch-batch만 사용한다.
- 적용 상태(5-2A-1): assign-panel.js, file-assign.js, 관리자 assignModal 연결·파일, demo materials POST를 제거했다. /api/fs/page-folders HTTP GET/POST도 제거했지만 PAGE_FOLDERS_PATH와 기존 런타임 데이터는 보존했다.

#### D-06A 자료 배정

- **사용자 결정:** 활성 자료 배정은 동시 수정 충돌을 막는 서버 잠금·revision 계약으로 전환한다.
- **적용 완료:** `GET /api/mat-assign`은 whole material-state revision을 반환한다. POST는 `If-Match`가 없으면 428, stale이면 무쓰기 409이며 material state 저널·last-good·503 저하 모드를 공유한다.

#### D-06B 학교 일정

- **사용자 결정:** 학교 일정은 client save queue와 revision 충돌 방지로 전환한다.
- **작업 트리 적용(2026-08-28):** `GET /api/school-calendar`은 문서와 `X-School-Calendar-Revision`/ETag를 함께 반환한다. POST는 같은 revision의 `If-Match`가 없으면 428, stale이면 무쓰기 409이며, strict store read와 원자 저장을 같은 파일 잠금 안에서 수행한다. `school-calendar/persistence.js`가 화면의 GET·revision 초기화와 auto/switch/flush/metadata 저장을 하나의 queue로 조합하고 성공 revision을 다음 요청에 인계한다.
- **검증 상태:** 독립 표준 라이브러리 hash oracle, 실제 Flask 임시 route의 두 client 경합과 파일 byte 판정, 외부 관찰형 브라우저 queue, literal state oracle, demo parity 검증이 적용돼 있다. 격리 8004의 인앱 브라우저와 Chrome에서 변경 전후 DOM 일치, 실제 저장, stale 409, 콘솔 오류 0을 확인했다.
- **남은 배포 gate:** 운영 8003은 재시작하지 않았으므로 현재 실행 중인 서버에는 아직 반영되지 않았다. 명시적 운영 재시작과 운영 표면 검증 전에는 “운영 반영 완료”로 표시하지 않는다.

### D-07 파일관리 한글 경로·참조 무결성

- 발견: UI의 루트 이동은 빈 dst를 보내지만 서버는 거부했고, 한글 rename은 ASCII 전용 secure_filename 결과가 비어 400이었다. 폴더 rename/move/delete도 하위 materials·assignments·pageFolders 참조를 완전히 변환하지 않았다.
- 사용자 결정(2026-08-24, 선택 A): 자료 배정 API 전환보다 이 실제 파일관리 결함을 먼저 수정한다.
- 적용 상태: 한글 안전 이름, 빈 dst 루트 이동, segment-aware 하위 경로 변환, unknown 필드 보존, 파일-tree → material-state 순서 잠금, 삭제 staging, pre-journal 동기 실패 rollback, upload DIR 자동배정을 구현했다.
- 복구 경계: 각 파일 mutation뿐 아니라 서버 시작과 통합 material-state GET도 pending journal을 먼저 복구한다. 손상된 journal/store는 서버 전체를 막지 않고 last-good 또는 빈 읽기 전용 projection으로 조회를 유지하며 관련 쓰기만 503으로 닫는다.
- 후속 구현(2026-10-01): 파일 변경과 기존 metadata journal 생성 사이의 프로세스 crash gap을 확인했다. Version 2 prepared intent를 파일 변경 전에 기록해 커밋 시작 전 undo를 보장하고, durable committing marker 이후에는 기존 forward 완료 의미를 유지한다. 기존 version 1 journal도 계속 지원한다. Temp 강제 종료·재복구 50개와 실제 route 41개 검사를 통과했으며 전체 suite·실제 UI·운영 적용은 [Hub 후속 기록](SERVER_PROJECT_FOLLOWUP_2026-10-01.txt)에서 구분한다.

### D-08 검증체계와 대형 파일 분할 순서

- **사용자 결정(2026-08-28):** 다음 단계는 `$mandela`의 독립 근거 원칙을 검증체계에 적용한 뒤 대형 파일을 책임 단위로 분할한다. 화면 사용자에게 보이는 기능·응답 차이가 없는 선택은 권장안으로 진행하되, 의미·규칙의 모순은 사용자가 직접 결정한다.
- **검증 gate:** 구현 helper로 기대값을 다시 계산하지 않는 독립 oracle, 실제 임시 route/store 또는 rendered DOM 같은 실표면, 실패 시 무쓰기·runtime hash 불변을 함께 확인한다. source 문자열 검사 하나만으로 동작 완료를 선언하지 않는다.
- **분할 순서:** 먼저 D-06B처럼 계약이 고정된 작은 seam에서 추출 방식을 검증한다. 이후 `routes/api_basic.py`, `static/js/student.js`, `static/js/tests.js`, 광범위 CSS를 서로 다른 단계로 나누며 한 번에 한 책임만 이동한다.
- **적용 상태(열 HTTP seam + 순수 core 세 경계 + runtime service):** `/api/school-calendar` HTTP 계약은 `routes/api_school_calendar.py`, 화면의 GET·revision 초기화·저장 queue 조합은 `static/js/school-calendar/persistence.js`, 순수 문서↔편집 행 projection은 `static/js/school-calendar/state.js`로 이동했다. page entry에는 DOM·이벤트·저장 시점·사용자 피드백이 남는다. 영상 카탈로그 `/api/videos` GET/POST와 정상 저장 identity guard는 `routes/api_videos.py`, 진도 `/api/progress` GET·PATCH는 `routes/api_progress.py`로 이동했다. 수업 로그 `/api/logs*`·`/api/homework-books`는 `routes/api_logs.py`, route-side placeholder repair와 공용 factory는 `routes/log_repository_provider.py`로 이동했으며 `routes.api_basic.get_log_repository`는 기존 소비자를 위한 호환 재노출로 남겼다. 자료 `/api/materials`와 배정 `/api/mat-assign`은 `routes/api_materials.py`, bootstrap과 공유하는 coherent·degraded read는 path-injected `routes/material_state_provider.py`로 이동했다. 보강출석 `/api/extra-attend`와 주말 slot `/api/weekend-slots`은 `routes/api_schedule_overrides.py`, 학생 `/api/students`·add/clone·단일 필드 update·delete는 `routes/api_students.py`, updates GET/PATCH/self-study는 `routes/api_updates.py`로 이동했고 `app.py`가 public assignment hook을 주입한다. 학생 bootstrap GET/public-session/network sanitize는 `routes/api_student_bootstrap.py`, Flask-free 집계 payload는 `routes/student_bootstrap_projection.py`로 이동했고 `app.py`가 `api_basic.py`의 명시적 dependency bundle을 주입한다. SID/merge/source 규칙은 `core/update_assignment_rules.py`, updates strict object persistence와 lock은 `core/update_assignment_store.py`가 공유하고 A:Ble 기본 배정 수는 `core/student_auto_assignment_rules.py`에서 roster와 자동 배정이 공유한다. 자동배정의 일정 해석, 영상/복습 projection, 자습 선택·append/rebase 변환은 각각 `core/student_schedule_rules.py`, `core/student_video_projection.py`, `core/student_video_assignment_rules.py`로 이동했다. 주입형 runtime 파일·repository·lock·clock 조합과 real-today 초기화·자습 reconcile은 `routes/student_auto_assignment_service.py`로 이동했고, `api_basic.py`에는 dependency factory·호환 hook과 bootstrap 조립만 남았다.
- **검증 상태:** school-calendar는 literal state oracle, 독립 hash, 실제 임시 Flask 경합, 외부 transport 순서·동시성, 변경 전후 인앱/Chrome DOM으로 고정한다. 영상 카탈로그는 실제 전용 Blueprint+임시 store에서 GET/POST, 204/400/409, 실패 byte/hash 불변을 검증하고, 격리 8004의 인앱 Browser와 Chrome에서 동일한 영상관리 데모 UI·콘솔 오류 0 및 실제 `/api/videos` 200 JSON 응답을 확인했다. 진도 경계는 실제 전용 Blueprint+임시 store에서 GET 필터, PATCH source merge, post-save 알림, 400/403/409 byte/hash 불변을 검증하며, 격리 8004의 두 브라우저에서 동일한 관리자 데모 렌더·콘솔 오류 0 및 실제 `/api/progress` 200 JSON 응답을 확인했다. 수업 로그 경계는 실제 전용 Blueprint와 임시 JSON·SQLite에서 scoped GET, dual write, placeholder repair, export/summary, 검증 실패 hash 불변을 독립 literal oracle로 확인한다. 자료 경계는 실제 전용 Blueprint와 임시 3-store에서 stdlib 독립 revision oracle, 두 GET의 coherent revision, weak ETag 저장, 400/405/428/409/503 실패의 원본 hash 불변, 손상 journal의 last-good degraded read를 확인한다. 격리 8004의 인앱 Browser와 Chrome에서도 같은 관리자 운영판, 콘솔 오류 0, 실제 `/api/materials`·`/api/mat-assign` 200 object 응답과 동일한 64자리 revision을 확인했다. 관리자 인증 경계는 우회하거나 약화하지 않는다.
- **검증 추가:** schedule override 경계는 실제 전용 Blueprint와 임시 extra/weekend store에서 literal 기대 상태, 400/403/405/500 실패 hash 불변, 실제 두 writer의 lock 배제, 오늘 initializer·학생별 reconcile·알림 인자를 외부 관찰한다. Post-commit fault injection은 extra/weekend 원본 저장 뒤 첫 initializer만 실패시켜 500과 저장 완료를 확인하고, 동일 payload 재시도가 extra의 `changedDates: []` 및 weekend의 204 성공을 유지하면서 initializer(weekend는 reconcile까지)를 다시 실행함을 확인한다. 학생 identity route도 같은 필드 재시도로 저장된 roster 기반 initializer가 복구됨을 별도 fixture에서 고정한다. 관리자 화면의 유효 payload 계약은 기존 weekend/extra 브라우저 회귀와 함께 고정하며, 격리 8004의 인앱 Browser와 Chrome에서 같은 관리자 운영판·보강 action, 콘솔 오류 0, 실제 `/api/extra-attend`·`/api/weekend-slots` 200 object 응답과 body 일치를 확인했다.
- **검증 추가:** 학생 identity 경계는 production helper로 만들지 않은 literal person/SID 디렉터리를 실제 전용 Blueprint와 임시 두 store에 주입한다. GET·new person·same-person clone·공유 profile fanout·SID field·A:Ble 기본값·일정 배정 hook·retire를 외부 관찰하고, conflicting/missing clone과 immutable ID 실패는 두 store의 byte 길이와 독립 SHA-256 불변을 확인한다. core 저널 rollback/restart recovery 검증은 별도로 계속 실행한다. 격리 8004의 인앱 Browser와 Chrome에서 같은 전체 학생 demo DOM(한글 replacement 문자·visible alert·console error 없음)을 확인했고, page-main-world XHR로 실제 `/api/students` 200 JSON array의 동일한 61개 body를 양쪽에서 확인했다.
- **검증 추가:** updates 경계는 production helper로 기대값을 만들지 않은 literal fixture를 실제 전용 Blueprint와 임시 store에 주입한다. read-only/일반 GET의 hook 분리, numeric SID merge와 unknown/source 보존, 제거, self-study 정규화·callback 인자, base POST 405를 외부 관찰한다. PATCH body object·`remove` JSON boolean 계약을 실제 route에서 확인하고 문자열 `"false"`/`"true"`, 숫자, null, 배열, object 삭제 표시는 400과 원본 byte/hash 불변이어야 한다. 미래 자동 배정은 incoming 조각이 아니라 잠금 안의 최종 병합 결과로 판정하여 `source` 생략 우회를 409로 막고, 명시적 삭제와 `manual` 재분류는 허용하면서 unknown 필드를 보존한다. 잘못된 UTF-8·최상위 배열은 GET/PATCH 503과 원본 byte·독립 SHA-256 불변, 파일 부재는 read-only `{}` 무생성과 첫 유효 PATCH 생성을 확인한다. 400/403/404/409 실패도 원본 불변을 유지한다. 격리 8004의 인앱 Browser와 Chrome에서 동일한 데모 관리자 DOM(오늘 5행, replacement 문자·visible load error·console warning/error 없음)을 확인했고, 실제 `/api/updates?readOnly=1`은 200 object/no-store이며 호출 전후 격리 `updates.json` 길이와 SHA-256이 동일했다. 보호된 실제 `/admin`의 Basic 인증은 우회하지 않았다.
- **검증 추가:** 공용 `core/date_rules.py`는 실제 정규 `YYYY-MM-DD`만 허용한다. 변경 전 negative control에서 `2026-02-30`이 진도 GET/PATCH, 로그 GET/entry/summary/단건·혼합 batch, 자습 reconcile hook, watch/watch-status/latest에 진입함을 네 실제 임시 route 검증으로 재현했다. 적용 뒤 같은 literal은 모두 400이고 progress/watch/updates 및 JSON·SQLite 로그 fingerprint가 불변이며 notification·self-study hook도 호출되지 않는다. 유효 leap day와 non-leap/compact/timestamp 반례를 별도 literal로 확인한다. 사용자 결정 D-04의 whole-map `/api/absent` 500·무쓰기·무알림 예외는 변경하지 않는다.
- **검증 추가:** 학생 bootstrap 경계는 production expectation helper를 쓰지 않는 literal fixture와 실제 전용 Blueprint·임시 9-store를 사용한다. endpoint 단독 소유, 401/400/404/405, ghost/regular/course-blocked/public payload, public active-SID 우선, link/watch 제한, real-today non-public에서만 주입 auto initializer가 호출되는 경계를 외부 관찰하고 모든 실패·과거·public 조회의 원본 byte와 독립 SHA-256 불변을 확인한다. 격리 8004의 인앱 Browser와 Chrome에서는 실제 `/student/ghost-outside-test`가 동일한 학생명·영상 1개·시험 1개·숨겨진 review surface로 렌더됐고 한글 replacement·가시 load failure·console warning/error가 없었다. 두 브라우저 reload 전후 격리 `updates/progress/watch/students/videos`의 길이와 SHA-256도 모두 동일했다. raw JSON URL의 직접 탭 탐색은 브라우저 client가 차단했으므로 우회하지 않았고, 실제 endpoint 계약은 전용 Flask route oracle과 학생 화면 통합으로 확인했다.
- **검증 추가:** 자동배정 순수 core 경계는 production helper로 기대값을 다시 계산하지 않는 literal 일정·연강 수·복습 payload·차단·append/rebase oracle을 사용한다. 네 순수 모듈의 Flask/runtime path·저장/lock import 부재와 입력 불변을 확인하고, 기존 snapshot·route hook·self-study·bootstrap 검증으로 실제 조합 표면의 동등성을 교차 확인한다. 사용자 승인 2A 뒤에는 입력 10이 설정 6, 연강 유효 12가 되는 literal과 신규 snapshot 6개·기존 8개 snapshot byte/hash 무변경을 별도 oracle에 기록한다. 배포 가드의 adversarial unit은 고정 runtime observer를 주입해 운영 8003의 동시 진도/watch 쓰기를 자기 변경으로 오인하지 않으며, 실제 배포 contract만 명시적 격리 receipt와 함께 동시 쓰기를 관찰한다.
- **검증 추가:** 자동배정 runtime service는 production storage/helper로 기대값을 만들지 않은 실제 임시 JSON과 stdlib SHA-256, 실제 thread/OS file lock을 사용한다. 과거 조회의 lock·save 부재, 오늘 최초 literal snapshot, lock 안 read/save 순서, 반복 멱등성, save 실패 byte/hash 불변, 손상 store strict-load 실패와 원본 hash 불변, 동시 두 호출의 단일 commit, self-study invalid-video 무쓰기를 외부 관찰한다. 결석 경쟁은 같은 literal fixture에서 barrier 제거 대조군이 stale `absent`를 읽고 삭제된 배정을 재생성하는 것을 먼저 확인한 뒤, 실제 coordinator barrier 적용군이 결석 커밋 종료 후 권위 상태를 다시 읽어 최종 SID 배정을 비워 두는 것을 검증한다. 별도 transaction 검증은 동일 컨텍스트 중첩 barrier가 timeout 없이 재진입하고 다른 thread의 OS lock 배제는 유지함을 확인한다. AST gate는 `api_basic.py`의 세 호환 함수가 storage/lock을 직접 소유하지 않는 것도 고정한다.
- **적용 상태(student.js 1차):** `static/js/student/bootstrapState.js`가 public-session loader 또는 비공개 bootstrap·latest-watch 병렬 요청을 주입받아 기존 9칸 초기 상태를 만든다. `student.js`에는 public active SID 반영, cache hydrate, DOM·재생·오류 표시가 남으며 bootstrap 실패의 부분 fallback은 계속 금지한다.
- **검증 추가:** `verify_student_bootstrap_state.mjs`는 production projection으로 기대값을 만들지 않은 literal payload, 독립 입력 SHA-256, 외부 fetch 순서와 pending watch를 사용해 투영·병렬 시작·watch 실패 허용·bootstrap 실패 중단·public loader 주입·shell script 선행 순서를 고정한다. 기존 student DOM/access/watch와 두 브라우저 화면 회귀를 별도로 유지한다.
- **적용 상태(student.js 2차):** `static/js/student/watchState.js`가 local watch/resume key, monotonic local/server merge, epoch-millisecond snapshot, duplicate-send 억제, 1500 ms debounce, 실패 재시도와 keepalive `/api/watch` transport를 주입형 controller로 소유한다. `student.js`에는 서버 배정 판정, DOM badge, page lifecycle listener와 active-MID Kollus playback orchestration이 남는다. bootstrap → watch → entrypoint의 classic-script 순서는 shell 계약으로 고정했다.
- **검증 추가:** watch controller는 production helper로 기대값을 만들지 않은 literal server map과 payload로 입력 hash 불변, 병합 결과, 재시도, access gate, target-only clear를 실행한다. 별도 실제 `student.js` 조각에서 pagehide/visibility keepalive와 Kollus active-MID·5%/90% event를 관찰하고, 기존 학생 bootstrap/review/access DOM 회귀 및 server temp-route matrix와 교차 확인한다. 격리 8004의 인앱 Browser와 Chrome에서도 bootstrap → watch → entrypoint 순서, main-world `StudentWatchState`, 학생·영상·시험 DOM, 학원망 제한 상태와 콘솔 0건이 일치했고, reload 전후 격리 updates/progress/watch/students/videos 길이·SHA-256이 동일했다. 당시 배정 수 6/10과 weekend loose-input 모순은 변경하지 않았고, 이후 아래 1A·2A·3A 결정으로 해소했다.
- **적용 상태(student.js 3차):** `static/js/student/playback.js`가 active MID, 5초 이상 resume query, `/api/get-url`, HTTPS upgrade, iframe Kollus attach/poll, same-window/MID message gate와 90%/ended 완료 event를 주입형 controller로 소유한다. `student.js`에는 playlist 선택·active row, player ready/empty, 게시판 영상 scroll/focus와 오류 문구 주입이 남는다. bootstrap → watch → playback → entrypoint의 classic-script 순서를 shell 계약으로 고정했다.
- **검증 추가:** `verify_student_playback.mjs`는 production helper로 기대값을 만들지 않은 literal URL·응답·progress snapshot과 독립 SHA-256을 사용한다. resume/기존 query, 학원망 차단, 정확한 get-url, HTTP→HTTPS, controller attach·seek·3초 poll·200회 timeout, same-window active-MID 5%/90%, MID switch flush, 403/500/network 오류와 입력 불변을 외부 관찰하고 기존 watch/bootstrap/review/access/academy-gate 회귀와 교차 확인한다. 격리 8004의 인앱 Browser와 Chrome에서도 main-world `StudentPlayback`, bootstrap → watch → playback → entrypoint 순서, 동일 resume URL, 학생·영상·시험·학원망 제한 DOM과 콘솔 0건을 확인했고 reload 전후 격리 updates/progress/watch/students/videos 길이·SHA-256이 동일했다.
- **적용 상태(student.js 4차):** `static/js/student/reviewPlaylist.js`가 주입형 storage/SID/date 경계에서 `student:review-playlist:<sid>:<date>` key, 저장 MID 정규화, fresh bootstrap 자격 기준 prune, chooser 선택 순서, 등록·취소를 소유한다. `student.js`에는 서버 권위 `reviewVideos` done-only 정규화, access/blocking, DOM 렌더링과 playback 조합이 남는다. bootstrap → watch → playback → reviewPlaylist → entrypoint의 classic-script 순서를 shell 계약으로 고정했다.
- **검증 추가:** `$mandela` 점검에서 새 모듈과 새 단위 검증만으로 닫으면 verifier=designer/shared-confirmation 위험이 있다고 판정했다. `verify_student_review_playlist.mjs`는 production helper로 기대값을 만들지 않은 literal key·목록과 독립 입력 SHA-256으로 stale prune, 선택 순서, 멱등 등록, 취소·재등록, SID/날짜 격리, storage 실패 fallback, DOM/fetch/ambient-storage 부재를 실행하고, 분리 전에 이미 존재하던 `verify_student_previous_video_review.js` DOM 계약과 접근·재생 회귀를 독립 실표면으로 유지한다. 격리 8004의 인앱 Browser와 Chrome에서도 main-world `StudentReviewPlaylist`, bootstrap → watch → playback → reviewPlaylist → entrypoint 순서, literal key/정규화 probe, 동일 학생·영상·시험·제한 복습 DOM과 콘솔 0건을 확인했고, reload 전후 격리 updates/progress/watch/students/videos 길이·SHA-256이 동일했다. QA 후 8004는 관리 절차로 종료했고 운영 8003 `/api/ping`과 `/app`은 계속 200이었다.
- **적용 상태(student.js 5차):** `static/js/student/announcementState.js`가 strict announcement/board projection, 미확인·완료 계산, 확인·필수 설문·답장 전이, 답장 3회 제한, 게시판 filter/reset, deduplicated pagination을 DOM·fetch·ambient storage 없이 소유한다. `student.js`에는 endpoint 요청, modal/carousel/form DOM, 접근성, board scroll/focus와 사용자 피드백이 남는다. bootstrap → watch → playback → reviewPlaylist → announcementState → entrypoint의 classic-script 순서를 shell 계약으로 고정했고 `student.js`는 4,027줄에서 3,862줄로 줄었다.
- **검증 추가:** `$mandela` 점검에 따라 새 모듈·새 단위 검사만으로 완료하지 않는다. `verify_student_announcement_state.mjs`는 production helper로 기대값을 만들지 않은 literal 공지/status/board와 독립 입력 SHA-256으로 필수 설문, legacy reply mirror dedupe, 3회 제한, strict payload, 페이지 중복 제거, filter/reset, DOM/fetch/storage 부재를 실행한다. 분리 전에 존재한 student-mobile `board`·`notifications` 회귀를 실제 entrypoint/deep-link/shell의 독립 표면으로 유지하고, 서버 이미지 권한 검증은 별도 `verify_announcement_image_access.py`가 소유한다. 격리 8004의 인앱 Browser와 Chrome에서도 main-world `StudentAnnouncementState`, 여섯 script 순서, 필수 설문 pending 1→0 probe, 동일 학생명·영상 1개·시험 1개·제한 복습·공지 modal 3필터/1행, 한글 replacement 부재와 콘솔 0건을 확인했다. 재로드 전후 격리 `updates/progress/watch/students/videos`의 길이·SHA-256은 모두 동일했고, QA 후 8004를 관리 절차로 종료한 뒤 운영 8003 `/api/ping`과 `/app`은 계속 200이었다.
- **적용 상태(student.js 6차):** `static/js/student/testPresentation.js`가 assignedTests unknown-field 보존 정규화·dedupe, assigned/interrupted/done/skip 상태와 일산 난이도 라벨, answerUrl alias·학원망 접근 projection, 카드 metadata·미완료 수·mobile/tablet same-tab 규칙을 DOM·fetch·ambient storage 없이 소유한다. `student.js`에는 실제 `<a>`/`<button>` 생성, target/rel, dataset, disabled/aria, 학원망 제한 안내와 DOM append가 남는다. bootstrap → watch → playback → reviewPlaylist → announcementState → testPresentation → entrypoint의 classic-script 순서를 shell 계약으로 고정했고 `student.js`는 3,862줄에서 3,802줄로 줄었다.
- **검증 추가:** `$mandela` 점검에서 새 모듈과 새 oracle만으로는 verifier=designer 위험이 남는다. `verify_student_test_presentation.mjs`는 production helper로 기대값을 만들지 않은 literal assignedTests와 독립 입력 SHA-256으로 dedupe·unknown-field 보존·상태/난이도 라벨·답지 alias·학원망 접근·명시적 restriction 호환·metadata·pending·same-tab·DOM/fetch/storage 부재를 실행한다. 분리 전에 존재한 `verify_student_material_access_scope.js`의 제한 시험 카드·클릭 VM, `verify_student_answer_mobile.js`의 탐색 seam, retired-submission 검증을 별도 실표면으로 유지한다. 격리 8004의 인앱 Browser와 Chrome에서도 main-world `StudentTestPresentation`, 일곱 script 순서, literal 일산 상→중상·interrupted→배부·학원 안/밖 answer projection, 동일 학생명·제한 `BUTTON` 카드 1개·assigned/배정·metadata/dataset, 한글 replacement 부재와 콘솔 0건을 확인했다. 재로드 전후 격리 `updates/progress/watch/students/videos` 길이·SHA-256은 모두 동일했고, QA 후 8004를 관리 절차로 종료한 뒤 운영 8003 `/api/ping`과 `/app`은 계속 200이었다.
- **적용 상태(tests.js 1차):** `static/js/tests/catalogState.js`가 config/category/test 정규화, 검색·정렬·그룹, 현재 filter 밖 reorder 차단, revisioned 전체 POST·단일 PATCH request projection과 deep rollback snapshot을 DOM·fetch·ambient browser state 없이 소유한다. `tests.js`에는 실제 endpoint 호출, save/mutation lock, 편집기·CSV·목록 DOM, 409/428 reload와 실패 rollback 렌더·사용자 피드백이 남았고 2,468줄에서 2,189줄로 줄었다.
- **검증 추가:** `$mandela` 점검에서 새 상태 모듈과 새 oracle의 작성자가 같아 `Verifier = Designer` 누수가 남는다고 판정했다. `verify_test_catalog_state.mjs`는 production helper로 기대값을 만들지 않은 literal config/test/revision과 독립 입력 SHA-256으로 정규화·검색/정렬/그룹·순서 gate·request body/header·snapshot·DOM/fetch 부재를 실행한다. 분리 전부터 존재한 `verify_test_catalog_search_and_sort.mjs`는 실제 entrypoint의 drag/keyboard reorder, search/source-ID, term/round scope, 409 reload, 실패 rollback과 metadata 보존을 계속 실행하고, `verify_tests_config_write_safety.py`는 temp Flask route의 revision/삭제 무쓰기를 별도로 고정한다.
- **브라우저 증거(tests.js 1차):** 관리형 격리 8004의 인앱 Browser와 Chrome에서 `/demo/rh3123/tests`가 동일한 16개 카탈로그·현재 범위 1개를 렌더했고, 일치 검색 1개 → 불일치 검색 0개/빈 결과 문구 → 원복 1개의 상태 전이가 같았다. 두 화면 모두 module entry cache key, 한글 replacement 부재, 가시 alert·console warning/error 0건을 확인했다. reload 뒤에도 동일했고 격리 `updates/progress/watch/students/videos`의 길이·SHA-256은 전후 동일했다. QA 후 8004 listener를 관리 절차로 종료했으며 운영 8003 `/api/ping`과 `/app`은 계속 200이었다.
- **적용 상태(tests.js 2차):** `static/js/tests/catalogEditorState.js`가 답안 문자열·문항 유형 정규화/검증/요약, 회차별 answerKeys/answerModes 보존 merge, CSV template/cell/parser/header alias와 행별 정답·유형 projection을 DOM·fetch·file/blob 없이 소유한다. `tests.js`에는 input/file/download/editor DOM, config mutation, save/reload와 alert/toast가 남았고 2,189줄에서 1,895줄로 줄었다.
- **검증 추가:** `$mandela` 점검에서 새 editor 모듈과 새 oracle만으로 닫으면 다시 `Verifier = Designer` 누수가 생긴다고 판정했다. `verify_test_catalog_editor_state.mjs`는 production helper로 기대값을 만들지 않은 literal answer/mode/CSV와 독립 입력 SHA-256으로 parser·validation·round merge·template/header aliases·warning fallback·ambient dependency 부재를 실행한다. 분리 전 실제 `tests.js`를 실행하던 catalog reorder/409/rollback 및 관리자 record VM을 새 module loader에 연결했고, 독립 core/network/migration answer-mode 검사와 temp Flask revision/delete 검증을 계속 유지한다.
- **브라우저 증거(tests.js 2차):** 관리형 격리 8004의 인앱 Browser와 Chrome에서 같은 16개 카탈로그·현재 범위 1개를 열고 같은 20문항 editor를 선택했다. 문항 mode 전이는 `미확인 20 → 객관식 1·미확인 19 → 미확인 20`으로 같았고 CSV 양식·가져오기 제어, 새 module cache key, compact `1342` 안내 노출, 한글 replacement 부재, 가시 alert·console warning/error 0건을 확인했다. reload 뒤에도 동일했고 저장 버튼은 누르지 않았다. 격리 `updates/progress/watch/students/videos` 길이·SHA-256은 전후 동일했으며 QA 후 8004를 종료하고 운영 8003 `/api/ping`·`/app` 200을 재확인했다.
- **적용 상태(tests.js 3차):** `static/js/tests/catalogStatisticsState.js`가 통계 라벨, ID→signature→이름 조회, category summary, 검색·정렬, 응시 메트릭·기록 행·오답 상세 presentation을 DOM·fetch·storage 없이 소유한다. 답지는 상세 API의 `answerUrl`만 사용하며 static map fallback을 두지 않는다. `tests.js`에는 통계 endpoint·loading, escape된 table/modal DOM, event·feedback이 남았고 1,895줄에서 1,806줄로 줄었다.
- **검증 추가:** `$mandela` 기준에서 새 statistics 모듈과 새 oracle만으로는 `Verifier = Designer`를 해소하지 못한다. `verify_test_catalog_statistics_state.mjs`는 production helper로 기대값을 재계산하지 않는 literal lookup/summary/sort/detail과 입력 SHA-256을 쓰고, 분리 전부터 있던 실제 entrypoint reorder/409/rollback VM, 두 admin record-detail UI VM, Python backend 상세 계약, 두 브라우저 표면을 독립 증거로 유지한다.
- **브라우저 증거(tests.js 3차):** 관리형 격리 8004의 인앱 Browser와 Chrome에서 동일한 5개 summary·7개 UNIT 통계 행, 평균 내림차순 `88.0% → 72.0%`, `미분` 검색 1건, 6개 상세 metric·6개 응시 기록, SCHOOL_PAST 분류 전환 3행을 확인했다. 재로드 후 새 module cache key, 16개 카탈로그, 한글 replacement·가시 alert·console warning/error 0건이 같았다. 저장 제어는 누르지 않았고 격리 `updates/progress/watch/students/videos` 길이·SHA-256은 전후 동일했다. QA 후 8004를 관리 절차로 종료했고 운영 8003 `/api/ping`·`/app`은 계속 200이었다.
- **적용 상태(CSS 1차):** `static/tests.html`에 있던 1,729줄의 `body.admin.tests-page` catalog/editor/statistics/modal cascade를 `static/css/tests.css`로 이동하고 `main.css` → `admin.css` → versioned `tests.css` 순서로 로드한다. 선택자·선언·breakpoint 순서는 바꾸지 않았고 HTML은 2,052줄에서 322줄로 줄었다.
- **검증 추가:** `$mandela` 기준에서 새 external CSS와 새 source oracle만 서로 확인하면 `Verifier = Designer` 누수가 남는다. `verify_tests_stylesheet_extraction.mjs`는 분리 전에 캡처한 정규화 CSS SHA-256, shell body SHA-256, cascade·breakpoint 순서를 고정한다. 분리 전 두 브라우저의 실제 계산 스타일·레이아웃·모달 수치와 screenshot을 외부 기준선으로 두고, 기존 mobile-touch·answer-mode·answer-link·record-detail 검증이 새 CSS를 직접 읽도록 연결해 독립 실표면을 유지한다.
- **브라우저 증거(CSS 1차):** 관리형 격리 8004의 인앱 Browser 1280×720과 Chrome 2560×1225에서 분리 전후 body/topbar/page/hero/two-column shell/summary/table의 크기·grid·padding·gap·색·border·shadow 계산값이 같았다. 새 versioned CSS는 HTTP 200과 분리 전 SHA-256으로 확인했고, 평균 내림차순 → `미분` 검색 1행 → 6 metric·6 record 상세 모달의 크기·z-index·overflow가 양쪽에서 동일했다. 다크모드 색도 일치했고 blank/overlay·한글 replacement·가시 alert·console warning/error는 0건이었다. 모바일 실 viewport 대신 byte-identical 1024/760/640px rule order와 기존 44px mobile-touch/record-detail 회귀를 유지했다. 격리 runtime 5종의 길이·SHA-256은 전후 같았고, QA 후 8004를 종료한 뒤 운영 8003 `/api/ping`·`/app` 200을 재확인했다.
- **사용자 결정(2026-08-29, 1A):** compact `1342` parser는 한 답안 + padding 호환으로 유지한다. 테스트 관리 도움말에서는 네 답안으로 오해시키는 compact 예시를 제거하고 공백형·쉼표형만 안내한다.
- **사용자 결정(2026-08-29, 2A):** 기본 자동 영상 배정 상한은 UI·SSOT·backend 모두 6으로 통합한다. 기존 roster 값을 bulk rewrite하지 않고 새 날짜 snapshot 계산과 이후 설정 저장에만 cap을 적용하며, 이미 존재하는 날짜 snapshot은 축소·보충하지 않는다.
- **사용자 결정(2026-08-29, 3A):** `/api/weekend-slots` POST는 malformed/non-object/empty body와 invalid date를 400, ghost를 403, unknown roster SID를 404로 거부한다. 검증은 쓰기 전에 끝내며 실패 요청은 파일·자동배정 hook·알림을 건드리지 않는다. 성공 204와 학생별 merge는 유지한다.
- **검증 상태(1A·2A·3A):** compact parser literal과 실제 도움말 부재/노출을 함께 고정했다. 자동배정은 입력 10 → 신규 6개 snapshot, 기존 8개 snapshot byte/SHA-256 무변경, roster 원본 무재작성으로 검증했다. Weekend 전용 Blueprint의 malformed/list/empty/impossible-date/non-object/empty-map/ghost/unknown 혼합 요청은 400/403/404와 파일·hook·알림 0회를 확인했다. 전체 `verify_refactor_safety.py`는 통과했다. 관리형 격리 8004의 인앱 Browser와 Chrome에서 같은 시험 선택 → 20문항 editor → 공백·쉼표 예시 2개/compact 예시 0개, blank/overlay·한글 replacement·console warning/error 0건을 확인했고 인앱 390×844 DOM도 같았다. 격리 runtime 6종의 길이·SHA-256은 전후 동일했으며 QA 후 8004를 종료하고 운영 8003 `/api/ping`·`/app` 200을 확인했다.
- **CSS 2차 inventory 완료:** 소비 표면·도메인 reach·결정 queue의 정본은 [`ADMIN_CSS_INVENTORY.md`](ADMIN_CSS_INVENTORY.md)다. 직접 `/admin`·`/tests`와 동적 `/all` 학생기록 팝업을 확인했으며, OCR/App 범위를 제외한 첫 독립 후보로 `/admin` 전용 수업 기록 내보내기 modal을 선정했다. 공용 token/table/modal과 시험 잔여 selector는 자동 해석하지 않는다.
- **CSS 2차 검증 기준선:** `verify_admin_css_inventory.mjs`가 두 방식의 소비자 열거, 분리 전 201줄 CSS SHA-256, 72줄 modal DOM SHA-256, scope·breakpoint·namespace 격리를 고정한다. `$mandela`의 Shared hallucination/Tautology/Verifier=Designer 누수는 기존 `verify_export_log_format.mjs`와 인앱 Browser·Chrome computed-style 비교로 독립시킨다.
- **적용 상태(CSS 2차):** 수업 기록 내보내기 modal CSS만 `static/css/admin-export-logs.css`로 이동하고 `/admin`의 `admin.css` 뒤·`student-work-light.css` 앞에 로드한다. 새 파일은 분리 전 201줄 SHA-256과 같고, `/tests`와 `/all` 팝업은 로드하지 않는다. 기존 export 기능 verifier도 새 파일을 직접 읽는다.
- **브라우저 증거(CSS 2차):** 관리형 격리 8004에서 인앱 Browser와 Chrome 각각의 분리 전후 desktop/mobile·light/dark 계산 스타일이 같았다. 새 stylesheet 29개 rule 로드, modal 초점 이동, Escape 종료와 opener 초점 복귀, 의미 있는 DOM, framework overlay 부재, console warning/error 0건을 양쪽에서 확인했다. 격리 runtime 30개 파일의 길이·SHA-256은 전후 동일했다.
- **후속 결정:** 승인된 CSS 2차 계획은 완료했다. 공용 token/table/modal, 시험 잔여 selector, `hero-note-rail`, `/all` 공유 조교 메모 CSS는 [`ADMIN_CSS_INVENTORY.md`](ADMIN_CSS_INVENTORY.md)의 사용자 결정 queue에 남긴다.

### D-09 학생 시험 OCR 제출

- **사용자 결정(2026-08-28):** PaddleOCR/UniMERNet 2경로를 사용한다. 한 장의 정형 20문항 답안지를 시험 카탈로그의 명시적 `answerModes`에 따라 문항별로 라우팅하며 정답값에서 유형을 추론하지 않는다.
- **사용자 결정(2026-08-29, 학년 경계):** 객관식 `1`~`5`는 고등 전 학년 공용 모델 하나로 학습한다. 학년별 1:1:1 병합이나 학생 현재 학년 기반 라우팅은 하지 않고, 작성자별 상한과 전체 pool의 숫자 클래스 균형만 적용한다. 성능은 고1·고2·고3별로 따로 보고 실제 격차가 확인될 때만 학년 전용 모델을 추가한다. 주관식은 시험 과목을 기준으로 두 모델을 사용한다. `공통수학1·2`는 `M_G3+H_G1`, `대수·미적분1·확통·기하·미적분2`는 `M_G3+H_G1+H_G2+H_G3` 데이터로 학습하며, 학생 현재 학년은 라우팅에 쓰지 않는다.
- **카탈로그 계약:** 새 시험 추가 시 회차별 모든 문항의 `choice_number`/`answer_value`/`manual_review` 유형을 정답과 함께 받아야 한다. 첫 rollout은 `UNIT`, 20문항, 앞의 두 자동 유형만 허용하고 `manual_review` 및 잘못된 객관식 키는 제외한다.
- **학생 흐름:** 학원망의 실시간 카메라만 사용한다. 0개 불확실은 자동 채점, 1~3개는 객관식 1~5 선택 또는 주관식 문항 재촬영, 4개 이상은 전체 재촬영이다. 주관식은 최대 2회 후 보류하고 “정답 여부는 선생님이 판별”로 표시한다.
- **관리자 흐름:** 보류는 당일 확정 대상이다. 학생 crop과 실제 답지 crop을 나란히 제공한다. 공식 UNIT PDF cache가 있으면 공통 1쪽 정답표의 해당 셀을 저장 없이 동적으로 자르고, 없거나 읽지 못하면 기대값과 답지 원본으로 폴백한다. 보류 정답/오답 확정과 오답→정답 수정만 허용하며 수정 이력은 문항·이전·이후 상태만 남긴다.
- **보관·공개:** 촬영/crop은 7일 뒤 삭제 대상이다. 보류가 있어도 기존 Drive 답지는 공개하고 최종 점수만 숨긴다. 학생 응답에는 정답키를 넣지 않는다.
- **성능 gate:** 속도 p90 30초, 파일럿 상한 60초, 한 번 촬영 성공 90%, 전체 재촬영 5% 이하, 보류 2% 이하, 정답을 오답으로 확정하는 오류 0건을 목표로 한다. 실패 시 정확도를 낮추지 않고 기능을 OFF/파일럿에 둔다.
- **적용 상태 정본:** 구현 계약은 [`PROJECT_FUNCTIONS_AND_LOGIC.md` §21](PROJECT_FUNCTIONS_AND_LOGIC.md#21-학생-시험-ocr-제출과-카탈로그-유형-계약), 데이터·반환 GPU 모델·평가 수치·출시 준비는 [`STUDENT_TEST_OCR_PUBLIC_DATA.md`](STUDENT_TEST_OCR_PUBLIC_DATA.md)가 소유한다. 이 원장에 실험 점수를 중복하지 않는다. 별도 개발 앱은 추후 같은 API로 연결한다.
- **사용자 요청 및 반영(2026-09-06):** 새 실제 손글씨 촬영 데이터가 없는 상태에서 세션 전면 검토·구조 조정을 요청했다. 입력 결합 오류를 정정하고 평가 manifest, 학습 이미지/weight 해시, best checkpoint 선택, installed/deploymentReady 분리, commit 후 자동 채점과 실패 상태 처리를 보강했다. [검토 기록](STUDENT_TEST_OCR_REVIEW_2026-09-06.md)에 근거·회귀·미완료 운영 항목을 남긴다. 기존 학년/문항 라우팅 결정을 바꾸거나 운영 schema/기능을 활성화한 결정은 아니다.
- **개선 구현 착수(2026-10-03, 기록 10-04):** 사용자는 구조·모델·학습·수집 검토 뒤 계획 수립과 작업 시작을 요청했다. [5단계 계획과 단계별 검증 기록](STUDENT_TEST_OCR_IMPROVEMENT_PLAN_2026-10-03.txt)에 구현·검증·남은 항목을 구분한다. 운영 모델 교체·기능 활성화·추가 학습을 수행한 기록이 아니다.
- **2단계 구현(2026-10-04):** 사용자 요청으로 시험/회차 계약과 비동기 문항 촬영, 상주 worker, lease·채점 복구를 구현했다. 순수 실패 주입·전체 회귀와 숫자 부분 지연 진단을 기록했다. 수식·혼합 실촬영의 실제 지연 검증은 남아 있다. [현재 처리 계약](PROJECT_FUNCTIONS_AND_LOGIC.md#21-학생-시험-ocr-제출과-카탈로그-유형-계약)을 따르며 운영 rollout을 수행한 결정은 아니다.
- **3단계 구현(2026-10-04):** 사용자 요청으로 모델 준비와 분리된 기본-OFF 보관 점검과 지난 날짜 보류 요약을 구현·격리 검증했다. 운영 삭제·기능 활성화는 하지 않았다. checkpoint 추가 수신은 [새 수신 기록](STUDENT_TEST_FORMULA_CHECKPOINT_RECEIVE_2026-10-04.md)의 휴지통 원본 파일 때문에 차단되어 네 후보 바이너리 검증은 남았다. 당일 교사 판정·7일 보관이라는 원래 결정을 바꾸지 않았다.

### D-10 운영 관리자 브라우저와 Kollus 실기동 증거

- **사용자 결정(2026-08-29):** 운영 관리자 페이지 `/admin`, `/dh1130`과 보호된 관리자 별칭은 Chrome을 지원 브라우저로 고정한다. 인앱 Browser의 `ERR_BLOCKED_BY_CLIENT`는 HTTP Basic 인증 도전을 처리하지 못한 클라이언트 제약으로 분류하며, 이를 피하려고 Basic 인증을 약화하거나 우회 경로를 추가하지 않는다.
- **인앱 Browser 범위:** 학생·공개 화면과 관리형 격리 8004의 비운영 UI 회귀 비교에 사용한다. 이미 정해진 시험·CSS 등의 두 브라우저 격리 검증은 계속 유지하며, Chrome 전용 결정은 운영 관리자 접속 표면에만 적용한다.
- **Kollus 결정(2026-08-29):** 2026-08-29 운영 배포에서는 네이티브 Kollus 프레임 시작을 승인 gate에서 제외한다. 인앱 Browser와 Chrome 모두 iframe까지 도달했지만 로컬 플레이어가 `vjs-agent-checking`, `readyState = 0`에서 초기화 실패했으며 이 결과를 통과로 기록하지 않는다.
- **계속 필수인 증거:** 학원망 `/api/get-url`, SID/MID·네트워크 gate, Kollus iframe 전달, `/api/watch`·progress의 monotonic/멱등 계약, 배정 snapshot 불변, 브라우저 console·DOM 검증은 제외하지 않는다. 이번 예외는 `static/js/student/playback.js`의 이벤트·진도 계약이나 향후 playback 변경 회귀 검증을 완화하지 않는다.
- **적용 상태:** 코드 변경 없이 운영 지원·검증 범위만 확정했다. Chrome 운영판, 양쪽 학생 화면, Kollus URL·iframe, 실제 학원망 watch 무변경 저장, 운영 8003·저널 상태는 통과했고 네이티브 프레임 시작만 승인된 미검증 범위로 닫았다.

### D-11 백지리뷰 검사 대기

- **사용자 결정(2026-08-29):** 오늘 학생 표의 `진도`와 `작업` 사이에 `백지` 열을 두고, 학생이 백지리뷰 검사를 받지 못한 채 귀가하면 체크한다. 다음 등원 때 우선 검사하고 완료 후 관리자가 직접 해제한다.
- **상태 범위:** `students.json`의 SID 전용 exact boolean `whiteReviewPending`이 원본이다. 선택 날짜·하원·숙검하원·기록 정리·로그·진도와 독립이며 이 흐름에서 자동 초기화하거나 지우지 않는다.
- **레이아웃 결정:** `진도`와 `백지`는 각각 36px, `작업`은 232px, `보강`은 64px, `문서`는 56px다. 새 열만큼 작업 열을 줄여 오늘 학생 표 전체 폭과 보강·문서 위치를 유지하며 다른 관리자 디자인은 바꾸지 않는다.
- **검증 결정:** 실제 identity/legacy 임시 명단, 불리언 실패 byte/hash 불변, 실제 today renderer의 저장·rollback·다른 날짜 재렌더, Chrome 8004의 계산 폭·reload 영속·해제·screenshot을 함께 사용한다.
- **적용·검증 상태:** `api_students` exact-boolean gate와 today renderer를 적용했다. 임시 identity/legacy route, renderer interaction/rollback, 기존 기록정리 회귀, 전체 safety suite가 통과했다. Chrome 8004에서 체크→reload 유지→해제→reload 해제, 4행 접근성 label, console 0건을 확인했고, table/wrapper/진도 폭은 변경 전과 같으며 보강·문서 좌표 오차는 최대 0.021px 반올림이었다. 모바일 표는 wrapper 내부 가로스크롤에 머물렀다. QA 뒤 8004를 종료했고 운영 8003은 재시작하지 않은 채 `/api/ping`과 `/app` 200을 유지한다.

### D-12 빠른 인쇄기 결석 이월 재출력

- **사용자 결정(2026-08-30):** 실제 종이 인쇄 여부 대신 빠른 인쇄기 CSV에 포함되어 성공 생성된 사실을 출력 이력으로 사용한다. 이력은 학생 전체가 아니라 `SID + 안정 시험 ID + 자료 ID + 최초 배정일`의 정확한 배정 건으로 남긴다.
- **제외 결정(2026-08-30):** 현재 과목의 초록 배정이라는 기존 조건은 유지한다. 대상 로그의 결석 이월 출처와 출처 로그의 carryover 시험이 정확히 일치하고 그 최초 배정 키가 과거 출력 이력에 있을 때만 기본 CSV에서 제외한다.
- **운영 보정(2026-08-31, 위 제외 게이트 대체):** 이력 기능 도입 전 성공 CSV는 새 테이블에 없어서 김태준033의 2026-08-30 출력분이 2026-08-31 첫 재배정 CSV에 다시 포함됐다. 정확한 결석 이월 출처와 출처 당시 `assigned` 상태가 확인되면 과거 이력 유무와 관계없이 기본 제외한다. 결석과 무관한 수동 전환, 출처 당시 완료·배부였던 시험, 같은 학생의 다른 시험은 계속 포함하며 명시적 재인쇄 옵션이 기본 제외를 해제한다. 성공 CSV 이력은 감사·중복 관찰 기록으로 계속 유지한다.
- **사용자 제어(2026-09-20 변경):** 팝업에 자동 제외 `명 · 건`을 표시하고 `이미 출력한 결석 이월 항목도 포함(재인쇄)`은 매번 기본 켜짐으로 연다. 사용자가 체크를 해제하면 기존 자동 제외가 적용되며, 자동 제외 후 0건이면 빈 CSV를 만들지 않는다. 이 기본값 결정이 2026-08-30의 기본 꺼짐 결정을 대체한다.
- **저장·실패 경계:** `app.sqlite`의 별도 `quick_printer_export_history` repository가 복합 기본키와 `BEGIN IMMEDIATE`로 성공 CSV 행을 기록한다. preview, 미매칭 전체 실패, 0행, history transaction 실패는 출력 이력을 남기거나 CSV를 반환하지 않는다.
- **적용·검증 상태:** core projection/repository, 관리자 preview/export route, 팝업 집계·재인쇄 옵션, demo sandbox와 temp-only restart/concurrency/rollback 부정 코퍼스를 적용했다. 전체 safety suite가 통과했고, 관리형 8004에서 기본 제외 `2명·3건`/12행, 재인쇄 15행, 2타임 필터 3행, 390×844 배치와 console 0건을 확인했다. 런타임 백업 후 운영 8003을 예약 작업으로 재기동했고 `/api/ping`·`/app`·정적 자산 200, 실제 8/28 배정 preview 2행, 미매칭 원자 실패, 출력 이력 0행을 확인했다.

### D-13 전체 검토 후 저장·백업·검증 보강

- **사용자 승인(2026-09-05):** 전체 검토에서 확인한 저장 대상 경합, 저장/재조회 불일치, 백업 일관성, 조회 잠금·커버리지, 자산 캐시·검증 환경 문제를 패치한다. 의미 정본은 기능·로직 기준서 §6·§8·§14이며 별도 규칙 정본을 만들지 않는다.
- **인증 결정(2026-09-05):** 사용자가 `현재 내부망 예외 유지`를 선택했다. 학원 내부 관리자 API의 기존 네트워크 신뢰 정책을 유지한다. 학생망과 관리자 API가 연결될 때의 조건부 위험을 제거했다고 보고하지 않는다.
- **후속 승인(2026-09-05):** 사용자가 남은 보호 페이지 QA, 대형 파일 추가 분할, 운영 재시작·반영을 승인했다. QA 인증은 8004 프로세스의 일회성 환경값으로만 설정하며 운영 인증은 바꾸지 않는다. 테스트 배정 규칙을 DOM/저장 orchestration에서 분리하되 기능·화면을 유지한다.
- **우선순위 확인(2026-09-05):** 사용자가 `최근 배정 우선이 맞아`로 확정했다. 기능·로직 기준서 §11의 최근 보기 우선 문구만 현행 코드·회귀검사의 최근 배정 우선 계약에 맞춘다. 저장·화면 동작은 바꾸지 않는다.
- **백업 재시도 승인(2026-09-05):** 첫 운영 반영의 백업은 읽기 전용 SQLite 연결의 WAL/SHM 생성으로 원본 변화 검사에 걸려 확정되지 않았다. 임시 복사본에만 SQLite를 여는 방식과 closed-WAL 무변경 회귀를 검증한 뒤, 사용자가 백업 확정을 위한 추가 정지·재시작 1회를 명시 승인했다.
- **백업 재시도 결과(2026-09-05):** 승인된 1회를 사용해 PID 1472에서 26500으로 정상 재시작했다. 백업은 감시 프로세스의 늦은 `guard-stopped` 기록으로 `instance/waitress-shadow-guard.log` 변화가 감지되어 확정하지 않았다. SQLite 부수 파일 재발은 없었다. 기능·로직 기준서 §14에 리스너와 감시 프로세스가 모두 종료된 뒤 백업하는 절차를 고정했다. 추가 정지는 실행하지 않았으며 검증된 운영 백업은 아직 미완료다.
- **백업 확정(2026-09-06):** 위 미완료 상태는 해소했다. 이후 사용자가 별도로 승인했으나 미사용 상태였던 재시작 1회와 최근 미완료 작업 마무리 요청에 따라, 동일 예약 작업의 runner·리스너·감시 프로세스가 모두 종료된 것을 확인한 뒤 `runtime-data-20260905_165241-a1613cf7.zip`을 확정했다. 137개 파일의 archive membership/크기/SHA-256과 임시 복원 SQLite 13개 테이블의 `integrity_check=ok`를 확인했다. archive SHA-256은 `2acf353f9606208d1d2a1b90009acc235ab15fc53f75cf6349cf4cff9e634b5f`다. 기존 작업 설정을 변경하지 않고 PID 26500 → 22372로 1회 재기동했으며 운영 ping·로컬/공개 app 200, 정상 감시 재개와 기존 격리 8004 유지가 확인됐다. 운영 복원이나 데이터 일괄 변환은 하지 않았다.
- **운영 경계:** 완전 로그 snapshot은 이후 정상 저장부터 적용하며 운영 데이터 일괄 변환은 하지 않는다. 확정 백업은 모든 작성자가 멈춘 승인된 유지보수 상태에서만 만들며 백업 스크립트가 서버를 멈추지 않는다.
- **검증 경계:** 실제 임시 SQLite/JSON과 HTTP 실패 주입, 저장 중 팝업 전환·중복·후속 실패, 독립 복원/해시, read cohort와 exclusive writer, 기본 안전검사·깨끗한 의존성 환경·관리형 8004 화면을 사용한다. 데모 UI와 실제 HTTP 검사를 서로 대체하지 않는다. 격리 보호 페이지의 새 QA 인증값 생성은 처음에는 보안 승인에서 차단됐으며 위 후속 명시 승인 후에만 적용했다.

### D-14 YouTube 영상과 기출엄선 병행

- **사용자 승인(2026-09-13):** grilling 1~28 답변 및 `구현 시작`에 따라 YouTube 단일 영상·재생목록 한 건 등록, 기존 과정 위에 SID별 기출엄선 병행, 새 자동배정 후보 전환, 기존 완료 영상 복습, 학원망 단일 플레이어, 기록정리 완료를 구현한다. 의미 정본은 [기능·로직 기준서 §9](PROJECT_FUNCTIONS_AND_LOGIC.md#youtube-gichul-overlay)이며 별도 RULE 정본을 만들지 않는다.
- **보존:** 기존 Kollus 시청/재배정 세대, A:Ble/APEX 과정과 이력, 오늘 snapshot, 배정 수·연강 배수, 명시적 수동 배정과 해제, 하원/기록정리 구분을 보존한다. YouTube watch/시청률/이어보기는 만들지 않으며 별도 학생 앱 연동·외부 목록 자동 확장·실시간 방송은 범위 밖이다.
- **운영 반영(2026-09-13):** 후속 `1. 2. 둘 다 진행` 승인과 권한 설정 후 재개 요청으로 격리 QA 및 운영 재시작 1회를 수행했다. 기존 예약 작업 설정을 그대로 유지해 운영 PID 14396 → 22564로 재기동했으며 8003 ping·로컬/공개 `/app` 200과 YouTube/기출엄선/기록정리 capability를 확인했다. 운영 카탈로그나 학생별 병행 설정을 미리 등록하지 않았으며 테스트 데이터는 운영에 복사·병합하지 않았다. QA 종료 뒤 다른 사용 중인 작업·탭이 없음을 확인하고 manager로 8004를 종료했으며 격리 테스트 표본은 해당 runtime에만 보관했다.
- **자동 검증:** 전용 Python 9개 테스트군과 Node URL/재생/상태 전이, 실제 cleanup helper의 개별·bulk capability/구서버 차단, 전체 `verify_refactor_safety.py`, compileall과 diff 검사를 통과했다. 독립 cold-read 1회에서 발견한 기본값·초록/흰색·실패 보관 범위의 모호함은 §9에 보강했다.
- **관리형 8004 실제 QA:** 운영 데이터를 seed로 쓰지 않은 합성 학생/카탈로그로 검증했다. 인앱 Browser에서 영상·재생목록 등록/중복 거부/재조회, 학생별 병행 저장, 자동·수동 배정, 하원 시 초록 유지 → 개별 기록정리 후 파랑 및 재조회 유지, 학원 밖 학생 화면의 제목만 공개를 확인했다. Chrome 152에서는 재생목록의 실제 재생 시간 증가(0 → 2.016초), 단일 영상의 30초 시작(31.013초까지 재생), 기존 APEX 완료 영상 복습, 단일 iframe과 외부 열기 링크, 390×844 학생 화면, 일괄 기록정리와 병행 OFF/ON 후 오늘 snapshot 불변을 확인했다. 재생 중 서버 watch POST는 0건이며 격리 watch 저장소 SHA-256은 전후 동일했다.
- **검증 범위·오류 분류:** 검증 시작 시 브라우저 연결에 Chrome이 없어 설치된 Chrome/Playwright를 허용된 대체 경로로 사용했다. 학원망 플레이어 검증은 8004 API 요청에만 합성 학원 IP를 주입했으며 서버 인증·격리 설정을 약화하지 않았다. 인앱의 학원망 실제 YouTube 재생은 미검증이고 Chrome 실제 재생으로 구분한다. 학생 페이지 콘솔 오류는 0건이다. 관리자 팝업의 별도 숙제 API 404는 격리 서버의 해당 기능 OFF 및 기존 legacy fallback 계약으로 확인했다. 초기 QA 스크립트의 구형 YouTube 버튼 selector/팝업 hydrate 대기 오류는 실제 DOM·완료 상태 기준으로 고쳐 재검증했으며 앱 기능 패치는 추가하지 않았다.

### D-15 보강 연결 교정 시 출석 이력 보존

- **사용자 결정(2026-10-01):** 앞으로 결석과 보강의 연결을 교정할 때 대상 날짜에 출석 기록 또는 수업 로그가 있으면 그 날짜의 출석 기록을 바꾸지 않는다. 의미 정본과 보존 대상은 [기능·로직 기준서 §7](PROJECT_FUNCTIONS_AND_LOGIC.md#7-출결오늘-순서보강)을 따른다.
- **교정 방식:** 잘못 연결된 결석의 `scheduledMakeup` 상태·note·ownership만 수정한다. `attendance.json`, `extra_attend.json`, `weekend_slots.json`, `arrive_time.json`, `logs.json`, SQLite 수업 로그는 삭제·이동하지 않는다.
- **2026-10-01 적용:** 박선유230은 `10/11 → 10/4` 연결을 유지하고 `10/13` 직보를 독립 예약으로 분리했다. 유현진012은 `9/26 → 10/3` 연결을 유지하고 오래된 `9/26 → 9/19` 연결만 취소 상태로 바꿨다. 9/19 완료 수업 로그와 모든 출석 관련 저장소는 그대로 보존했다.

### D-16 레거시 계정 ID 변경과 마스터 비밀번호 범위

- **사용자 결정(2026-10-01):** 로그인 ID를 변경하면 이전 JWT를 종료하고 다시 로그인하게 한다. `MASTER_PW`는 학생 이름 로그인, 변경된 계정 ID 로그인, 계정 ID·비밀번호 변경 모두에서 허용한다.
- **계약:** 의미 정본은 [기능·로직 기준서 §3](PROJECT_FUNCTIONS_AND_LOGIC.md#3-사용자-인증-네트워크-경계)이다. 새 ID로 연결하는 방식으로 이전 토큰을 살려 두지 않는다. 관리자 Basic·공개 학생 앱 인증·학원망 판정의 범위는 확대하지 않는다.
- **반영 상태:** 기존 토큰·공유 계정 재활성화·동시 변경·로그인 경합·실패 무쓰기 회귀, 최신 전체105개 unit 그룹, 관리형8004 실제HTTP33 assertions를 통과했고 사용자 순서1 → 3 → 2 → 4에 따라2026-10-01 21:20 운영 반영을 완료했다. 관리자 Basic·공개 앱 인증 범위와 운영 업무 데이터는 유지했다.

### D-17 보강 예약 삭제 표식 왕복 보존

- **사용자 결정(2026-10-01):** 보강 정규화 분기의 `scheduledMakeup:null` 삭제 표식을 보존한다.
- **계약:** 의미 정본은 [기능·로직 기준서 §7](PROJECT_FUNCTIONS_AND_LOGIC.md#7-출결오늘-순서보강)이다. 결석·수동 보강의 명시적 null을 저장·GET·POST·revision에서 유지하여 승인 메모의 예약이 재생성되지 않게 한다. 키가 없는 legacy 메모, 다른 coercion·unknown 필드 투영, 출석 이력 보존 규칙은 유지한다.
- **반영 범위:** 순수 정규화 helper와 임시 HTTP→실제 브라우저 계산 회귀를 보강한다. 기존 운영 데이터를 일괄 다시 쓰거나 출석·진도 기록을 교정하는 결정은 아니다. 전체105개 unit 그룹·관리형8004 실제HTTP 및Chrome/IAB 재조회·독립검토를 통과했고2026-10-01 22:36 새백업/재기동1회로 운영 반영했다. 운영 업무 데이터는 유지했으며 상세 증거는 Hub 실행 기록에 남긴다.

### D-18 관리형 8004 영상 전용 QA 예외

- **사용자 승인(2026-10-02):** “8004 영상 전용 QA 예외 승인”에 따라 지정 합성 학생·영상의 실제 재생 및 자동 watch를 현재 관리형 loopback 서버에서 검증한다.
- **계약:** 정본의 [관리형 8004 영상 전용 QA 예외](PROJECT_FUNCTIONS_AND_LOGIC.md#관리형-8004-영상-전용-qa-예외-d-18)를 따른다. 기본 OFF, marker/receipt/PID/시각/loopback/non-public/지정 SID·MID를 함께 검증하며 영상 권한만 분리한다.
- **보존:** 운영 학원망·시험·자료·Basic·public·push·callback과 운영 데이터는 유지한다. provider URL에는 QA 학생 식별자를 발행하지 않는다. 테스트 창 종료 뒤 예외를 끄며 운영으로 QA 기록을 병합하지 않는다.
- **상태(2026-10-02):** 구현·전용/전체 회귀·실제 Chrome native 자동 watch200·90%done·수동none/reload·OFF403 검증 완료. 현재 예외 OFF이며 합성 QA 데이터는 보존한다. 실제 학원망 QA와 genuine provider callback은 별도 미검증이다. 상세 증거는 [D-18 실행 기록](SERVER_KOLLUS_LOOPBACK_QA_DECISION_2026-10-02.txt)에 둔다.

### D-19 오늘 학생 자동 분류 안의 드래그 순서 우선

- **사용자 선택(2026-10-02):** “같은 자동 분류 안에서 드래그 우선 (권장)”을 승인했다.
- **계약:** 타임·자습·출석·숙검 요청/요청 시각·숙검 상태·등원시간의 기존 자동 우선순위가 모두 같을 때만 해당 날짜의 저장된 SID 순서를 이름보다 우선한다. 저장된 순서가 없으면 기존 가나다 정렬을 유지하고, 저장 순서에 없는 학생끼리는 가나다순을 유지한다.
- **경계:** `data/today_order.json`과 기존 날짜 PATCH 계약을 유지한다. 운영 데이터 마이그레이션·기존 날짜 삭제·자동 분류 해제는 포함하지 않는다. 실제 reload/drag 검증은 관리형 8004의 기존 합성 학생으로 진행한다.
- **상태:** 승인된 비교 순서와 날짜별 읽기 경계를 구현했다. 전용34case/수정 전 negative control/Chrome native drag·reload·API64명 비교/독립 검토finding0/전체 non-smoke105그룹을 통과했다. 세부 근거는 Hub 실행 기록에 남긴다.

### D-20 과거 하원 경고의 확인 정보 표시

- **사용자 요청(2026-10-11):** “하원 미완료 왜 뜨는거냐 지금. 이거 처리할 정보도 페이지에 같이 디스플레이하게 패치해.”
- **계약:** [기능·로직 기준서 §7](PROJECT_FUNCTIONS_AND_LOGIC.md#7-출결오늘-순서보강)의 과거 날짜 집계 경계는 유지한다. 기존 B의 문구만 표시하던 디자인을 대체하여 날짜·학생·등원시각·완료 기록 부재와 날짜 확인 버튼을 표시한다.
- **보존:** 일반 로그 조회의 legacy 보충/완전 snapshot 권위 및 D-17 예약 삭제 표식을 경고에도 적용한다. 과거 하원 여부를 추정해 운영 로그를 자동으로 완료하거나 삭제하는 결정은 아니다.

## 리팩터링에 바로 적용할 경계

- 확정된 L 항목은 현재 계약으로 테스트와 문서를 맞춘다.
- D 항목은 사용자 결정 전 endpoint 제거, 접근 범위 확대, feature flag 기본값 변경을 금지한다.
- D-05/D-06으로 승인·제거된 정적 파일, fake endpoint, 전체 컬렉션 POST를 복원하지 않는다. 자료 배정은 D-06A의 revision 계약을, 학교 일정은 D-06B의 queue/revision 계약을 유지한다.
- 구조 중복은 동작 보존 테스트를 먼저 만들고 작은 단위로 분리한다. 4-2에서 `api_watch`의 `api_basic` private helper 의존을 core progress store/notification 경계로 분리했고, 4-3에서 watch/Kollus writer를 통합했으며, 4-4에서 attendance/makeup/offline sync의 결석 배정 정리를 공용 core 서비스와 adapter로 분리했다. 4-4A에서는 사용자 선택 A에 따라 그 다중 저장을 저널 기반 전체 롤백·시작 복구·요청 장벽으로 승격했다. 4-5A에서는 `api_tests`의 private lock/answer-link 의존을 공용 core 경계로 분리했고, 4-5B에서는 `api_fs`의 announcement-image private guard 의존을 `core.announcement_image_access`로 분리했다. 알려진 private cross-blueprint seam은 모두 해소됐으며, 후속 구조 작업은 legacy·미사용 후보의 실제 소비자를 확인한 뒤 정한다.
