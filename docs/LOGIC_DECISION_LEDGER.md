# 로직 결정 원장

**기준일:** 2026-08-24

**목적:** 과거 주문, 현재 구현, 현재 운영 설정이 다를 때 어떤 계약을 따를지 기록한다.

이 문서는 구현 흐름을 설명하는 문서가 아니다. 상세 현재 동작은
`PROJECT_FUNCTIONS_AND_LOGIC.md`, 코드 연결은 `CODE_FLOW_MAP.md`를 따른다.
여기서는 서로 다른 설명이 발견됐을 때의 판정과 아직 필요한 사용자 결정을 관리한다.

## 판정 기준

1. 최신의 명시적 사용자 결정과 현재 운영 설정을 우선한다.
2. 현재 코드만으로 주문의 의도를 단정하지 않는다. 후속 커밋이 앞선 주문을 되돌렸다면 사용자 확인 대상으로 남긴다.
3. 날짜, 호스트, 네트워크, 배정 출처가 다른 계약은 모순으로 합치지 않는다.
4. 외부 소비자를 확인할 수 없는 endpoint와 직접 정적 경로는 호환 대상으로 보존한다.
5. `결정 필요` 항목이 해결되기 전에는 해당 동작을 삭제하거나 넓히지 않는다.

## 확정된 판정

| ID | 충돌한 설명 | 현행 판정 | 근거·조치 |
|---|---|---|---|
| L-01 | PWA를 제거한다 / 학생 앱 PWA를 제공한다 | 후속 주문이 제거 방침을 대체했다. PWA는 현재 기능이다. | `20cfa6e`에서 학생 앱이 통합됐고 현재 예약 작업은 public만 켠다. 2026-08-13 문서는 역사 기록으로만 본다. |
| L-02 | `5a-math.com`과 `app.5a-math.com`은 같은 별칭이다 / 서로 다른 공개면이다 | 서로 다른 origin과 역할을 가진다. | legacy host는 기존 로그인·학생 화면을 유지하고 앱 전용 경로를 막는다. app host는 HTTPS와 명시 allowlist만 허용한다. |
| L-03 | 공개 HTTP는 모두 HTTPS 308이다 / app HTTP는 404이고 legacy root는 유지된다 | 현재의 단계별 도메인 전환 계약을 따른다. | app host HTTP는 404다. legacy root는 독립 redirect 승인이 꺼진 동안 200이며, 승인 뒤에도 쿼리 없는 루트 GET/HEAD만 app URL로 302한다. |
| L-04 | 학생 시험 제출·채점·OCR이 현재 기능이다 / 답지 열람만 제공한다 | 제출·OCR 표면은 폐기됐다. | `/student-test/<sid>`, `/api/submit-test`, `/api/ocr-test-sheet*`는 등록하지 않고 `/api/tests`는 GET 전용이다. 재도입은 새 기능으로 설계한다. |
| L-05 | bootstrap 실패 시 여러 API로 복원한다 / 오류를 표시하고 중단한다 | 단일 bootstrap이 권위이며 실패 시 중단한다. | 구형 7개 요청 fallback은 제거됐고 부분 데이터 조립을 되살리지 않는다. |
| L-06 | 복습 후보는 `done` 또는 `interrupted`다 / `done`만 허용한다 | 현재 과정의 `done`만 허용한다. | `reviewVideos`는 서버가 정제한 유일한 권위다. `interrupted`, `skip`, `none`은 후보가 아니다. |
| L-07 | 영상 `training-pack` 배정 API가 있다 / 트레이닝팩은 시험 분류다 | 시험 카테고리 의미만 유지한다. | `/api/updates/training-pack`과 `/api/updates/review`는 존재하지 않는다. |
| L-08 | 영상 자동 배정은 조회로 실행하지 않는다 / 일부 조회가 오늘 snapshot을 만들 수 있다 | 문맥이 다른 계약이다. | 관리자 모달은 `readOnly=1`로 순수 조회한다. real-today의 bare updates GET, 날짜 경계, 허용된 bootstrap·일정 이벤트만 멱등 생성할 수 있다. 과거·미래 조회는 생성하지 않는다. |
| L-09 | legacy 학생 사본도 현재 화면이다 / 단일 학생 화면만 쓴다 | 사본은 제거됐다. | `static/student copy.html`, `static/js/student copy.js`를 복원하지 않는다. |
| L-10 | dashboard·homework·reminders·focus 코드가 있으므로 운영 중이다 / 현재 꺼져 있다 | 구현 존재와 운영 활성은 별도다. | 현재 예약 작업은 public만 ON이고 네 기능은 OFF다. 마이그레이션과 rollout 승인 없이 활성화하지 않는다. |
| L-11 | 결석 저장 실패 시 호출부의 부분 롤백을 유지한다 / 관련 저장소 전체를 원상복구한다 | 사용자 선택 A에 따라 롤백 우선 원자성 계약으로 변경한다. | updates, progress, SQLite/JSON class logs, absent, optional makeup carryover의 좁은 before-image를 저널링한다. 성공 전 오류는 전부 복구하고, 미완료 저널은 시작/다음 쓰기 전에 복구하며, 복구 실패는 503·시작 실패로 닫는다. |

| L-12 | 서버는 항상 시작 가능해야 한다 / 손상된 파일·교재 트랜잭션 때문에 전체 시작을 막는다 | 전체 서버는 시작하고 파일·교재 쓰기만 읽기 전용 저하 모드로 닫는다. | 유효 저널은 자동 roll-forward한다. 읽을 수 없는 저널·저장소는 마지막 정상 snapshot(없으면 빈 읽기 전용 projection)으로 조회를 유지하고, `/api/mat-assign`과 파일 mutation은 503을 반환한다. whole-map 배정 저장은 revision/`If-Match`로 stale overwrite를 409 차단한다. |
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
- 2026-08-16 `c234f0c`는 학원망·loopback 제한을 다시 추가했고 현재 코드와 회귀 검사는 이를 고정한다.
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
- 후속 확정: /api/mat-assign 명령형 전환과 school-calendar 저장 큐/revision은 사용자가 A로 확정했으며 다음 소단계에서 구현·검증한다. 아직 적용된 것으로 해석하지 않는다.

### D-07 파일관리 한글 경로·참조 무결성

- 발견: UI의 루트 이동은 빈 dst를 보내지만 서버는 거부했고, 한글 rename은 ASCII 전용 secure_filename 결과가 비어 400이었다. 폴더 rename/move/delete도 하위 materials·assignments·pageFolders 참조를 완전히 변환하지 않았다.
- 사용자 결정(2026-08-24, 선택 A): 자료 배정 API 전환보다 이 실제 파일관리 결함을 먼저 수정한다.
- 적용 상태: 한글 안전 이름, 빈 dst 루트 이동, segment-aware 하위 경로 변환, unknown 필드 보존, 파일-tree → material-state 순서 잠금, 삭제 staging, pre-journal 동기 실패 rollback, upload DIR 자동배정을 구현했다.
- 복구 경계: 각 파일 mutation은 pending material-state journal을 먼저 복구한다. 서버 시작 자동복구와 관련 GET read barrier는 운영 데이터에 영향을 주는 별도 선택으로 아직 적용하지 않았다.
## 리팩터링에 바로 적용할 경계

- 확정된 L 항목은 현재 계약으로 테스트와 문서를 맞춘다.
- D 항목은 사용자 결정 전 endpoint 제거, 접근 범위 확대, feature flag 기본값 변경을 금지한다.
- D-05/D-06으로 승인·제거된 정적 파일, fake endpoint, 전체 컬렉션 POST를 복원하지 않는다. 활성 자료 배정과 학교 일정 저장은 D-06의 후속 소단계에서 전환한다.
- 구조 중복은 동작 보존 테스트를 먼저 만들고 작은 단위로 분리한다. 4-2에서 `api_watch`의 `api_basic` private helper 의존을 core progress store/notification 경계로 분리했고, 4-3에서 watch/Kollus writer를 통합했으며, 4-4에서 attendance/makeup/offline sync의 결석 배정 정리를 공용 core 서비스와 adapter로 분리했다. 4-4A에서는 사용자 선택 A에 따라 그 다중 저장을 저널 기반 전체 롤백·시작 복구·요청 장벽으로 승격했다. 4-5A에서는 `api_tests`의 private lock/answer-link 의존을 공용 core 경계로 분리했고, 4-5B에서는 `api_fs`의 announcement-image private guard 의존을 `core.announcement_image_access`로 분리했다. 알려진 private cross-blueprint seam은 모두 해소됐으며, 후속 구조 작업은 legacy·미사용 후보의 실제 소비자를 확인한 뒤 정한다.
