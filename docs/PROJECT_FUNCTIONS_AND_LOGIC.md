# 학원 운영 허브 — 전체 기능 및 주요 로직 기준서

**기준일:** 2026-08-24
**기준 브랜치:** `codex/apple-clean-redesign`
**기준 커밋:** `91b7bb1`
**목적:** 기능 패치·장애 점검·코드 리뷰 때 세션을 다시 읽거나 로직을 매번 역추적하지 않도록 현재 계약을 한곳에 고정한다.

이 문서는 동작 설명서다. 작업 방법과 데이터 안전 규칙은 루트 및 하위 `AGENTS.md`가 우선한다.

## 1. 시스템 한 문장 정의

이 저장소는 학생 명단, 출결, 오늘 순서, 수업·숙제 기록, 영상 배정과 시청 진도, 시험 배정·채점·성적, 보강, 공지, 학사 일정, 자료 파일을 함께 운영하는 Flask 기반 학원 운영 허브다. 홍보 사이트나 범용 SaaS가 아니며 저장소 옆의 JSON·SQLite가 실제 운영 데이터다.

## 2. 현재 구조와 요청 경로

```text
학생/관리자 브라우저
  ├─ 기존 공개면: 5a-math.com → 로그인·기존 학생 페이지
  ├─ 학생 앱 공개면: app.5a-math.com → /app·PWA·세션 제한 API
  │    └─ Cloudflare Tunnel → localhost:8003
  └─ 학원 LAN: 서버 IP:8003
       └─ Waitress → Flask app.py → feature flag별 18~24개 Blueprint → 정적 HTML/JS 또는 JSON API
```

현재 예약 작업 인자에서는 public 학생 앱만 켜고 dashboard/homework/reminders/focus는 꺼서 21개 Blueprint와 134개 URL rule을 조립한다. 플래그별 상세 구성과 실제 요청·저장 흐름은 [CODE_FLOW_MAP.md](CODE_FLOW_MAP.md)를 따른다.

- 프런트 빌드 시스템과 Jinja 템플릿 트리는 없다. `static/`의 HTML과 네이티브 JavaScript를 Flask가 직접 제공한다.
- `5a-math.com`은 기존 로그인·`/student/<sid>`·공유 학생 자산을 유지한다. 학생 앱 전환 승인이 꺼진 동안 HTTP 루트도 200으로 유지하고 `/app`, manifest, service worker, 모바일 인증 API 같은 학생 앱 전용 경로는 404로 닫는다.
- `app.5a-math.com`은 HTTPS 전용 학생 앱 공개면이다. HTTP 요청은 404이고, HTTPS `/`는 cache 금지 302로 `/app`에 이동한다. `/app`, manifest, service worker와 명시 등록한 API만 허용하며 미등록 경로·메서드는 404다.
- 두 호스트는 별칭이 아니며 브라우저 저장소도 origin별로 분리된다. 학생 앱의 보호 페이지·파일·API는 유효한 앱 세션을 요구하고, 요청 SID는 세션의 `active_sid`와 같아야 한다.
- Cloudflare의 `CF-Visitor.scheme`, 일반 프록시의 `X-Forwarded-Proto`, 클라이언트 IP 헤더는 loopback, Cloudflare 대역 또는 명시한 `TRUSTED_PROXY_CIDRS`에서 온 요청에만 신뢰한다.
- 기존 학생 페이지와 별도로 학생 앱 PWA가 다시 제공되고 있다. manifest와 shell 자산은 재검증 캐시 정책을 사용하며, 인증 없는 session 조회·student bootstrap은 401로 닫힌다.

## 3. 사용자, 인증, 네트워크 경계

| 표면 | 인증·접근 | 핵심 계약 |
|---|---|---|
| 학생 로그인 `/` | 이름/계정 로그인 후 30일 JWT | `AUTH_SECRET`이 재시작 후에도 같아야 자동 로그인이 유지된다. |
| 학생 앱 `https://app.5a-math.com/app` | 학생 앱 세션 + HTTPS | 루트는 `/app`으로 302 이동한다. 허용 목록 밖 경로·메서드는 404, 세션 없는 보호 API는 401, 다른 SID는 403이다. |
| 학생 `/student/<sid>` | 학생 JWT 흐름과 sid | bootstrap의 `assignedTests`는 항상 최상위 배열이다. |
| 관리자 페이지군·활성 학생 계정 관리 API | HTTP Basic | 네트워크 위치와 무관하게 올바른 `ACADEMY_ADMIN_USERNAME`, `ACADEMY_ADMIN_PASSWORD_HASH`가 있어야 한다. 누락·오인증은 401이며 학생 앱 공개 host에서는 관리자 API를 404로 숨긴다. |
| 영상 재생 URL | 학원 네트워크 | `/api/get-url`에서 실제 클라이언트 IP·공개 세션 SID·카탈로그 MID를 검증한다. Kollus LMS callback은 외부 사업자가 호출하므로 별도 `KOLLUS_CALLBACK_SECRET`으로 보호한다. |
| 답지 맵 | 학원 네트워크 | `/js/test_answer_link_map.json` 직접 접근도 차단한다. |
| 쓰기 API | 동일 origin | POST/PUT/PATCH/DELETE의 Origin·Referer가 현재 Host와 다르면 403이다. |
| 데모 | `/demo/rh3123/*` | 데모 bootstrap이 fetch와 저장을 가로채며 실서버 쓰기를 만들면 안 된다. |

학생 계정은 `auth_accounts.json`의 호환 데이터를 사용한다. 학생 이름과 서버 환경변수 `MASTER_PW` 조합은 학생이 실제 로그인 ID나 비밀번호를 바꾼 뒤에도 해당 이름의 현재 계정으로 로그인할 수 있다. 마스터 비밀번호 값은 코드·문서·로그에 기록하지 않고 Machine 우선, 예약 작업 사용자 범위 fallback으로만 읽는다. 이 경로는 계정 ID와 비밀번호 해시를 바꾸지 않으며, 이름이 아닌 변경된 계정 ID에는 적용되지 않는다. 런처는 `AUTH_SECRET`도 같은 우선순위로 읽으며 값이 없거나 기본 placeholder면 운영 Waitress가 기동하지 않는 것이 정상이다.

## 4. 화면 지도

| 경로 | 역할 | 주요 코드 |
|---|---|---|
| `/` | 학생 로그인 | `static/index.html`, `static/js/auth.js` |
| `/admin`, `/dh1130` | 날짜별 관리자 운영판 | `static/admin.html`, `static/js/admin/` |
| 관리자 학생 툴팁 | 학생 이름·출석·학교 정보 표시; 이름 옆 난이도 배지(상·중상·중·하)는 표시하지 않음 | `static/js/admin/features/hoverTooltip.js` |
| `/students` | 전체 학생 명단·미니 진도·내보내기 | `static/all.html`, `static/js/all/` |
| `/student/<sid>` | 학생 영상·시험·숙제/수업 정보 | `static/student.html`, `static/js/student.js` |
| `/app`, `/app/*` | 학생 앱 설치·세션 shell | `static/student-app.html`, `static/js/student-app.js` |
| `/video-manage` | 영상 카탈로그 관리 | 영상 관리 HTML/JS |
| `/tests` | 시험 카탈로그·기록·통계 | `static/tests.html`, `static/js/tests.js` |
| `/school-cal` | 학교 일정 | 학교 캘린더 HTML/JS |
| `/file-manage` | 자료 폴더·파일 관리 | 파일 관리 HTML/JS |
| `/demo/rh3123/*` | 관리자 기능 데모 | `static/js/admin/demo/` |

로그인 화면은 `static/index.html`, 학생 페이지는 `static/student.html`과 `static/js/student.js`만 사용한다. 구형 `main.html`과 잘못된 자동배정·watch 이중 쓰기를 포함하던 `student copy.html` / `js/student copy.js` 사본은 2026-08-23 제거했으며 다시 별도 로그인·학생 페이지로 복구하지 않는다.

## 5. 날짜와 식별자 계약

- 관리자 기능의 기본 기준일은 화면에서 선택한 날짜다. `getAdminDate()`를 사용한다.
- 실제 로컬 오늘이 의도된 경우에만 `todayLocalKey()`를 사용한다.
- 행 단위 작업은 해당 행의 `data-date`를 우선한다. 화면 전역 상태만 보고 다른 날짜를 덮어쓰면 안 된다.
- 학생 sid는 문자열이 기준이다. `"007"`과 `"7"` 같은 legacy alias를 읽을 때 호환하되 새 쓰기에서 임의 숫자 변환을 하지 않는다.
- 날짜 키는 `YYYY-MM-DD`다.

## 6. 하루 운영 흐름

1. 관리자 bootstrap은 실제 오늘의 초기 스냅샷과 공통 상태를 읽는다.
2. 선택 날짜가 바뀌면 그 날짜의 출결, 순서, 로그, 영상/시험 상태를 다시 hydrate한 뒤 렌더링한다.
3. 출석·결석·보강·도착·연락·오늘 순서는 각 전용 PATCH/POST 흐름으로 부분 갱신한다.
4. 학생별 로그와 숙제는 의미 있는 기존 값을 빈 문자열로 지우지 않는 merge-safe 규칙으로 저장한다.
5. 영상 자동 배정은 실제 KST 오늘 날짜가 시작된 뒤 bare `GET /api/updates`, 관리자 날짜 경계 감지, 비공개 오늘 bootstrap, 오늘 일정 사건이 누락된 오늘 snapshot을 최초 생성할 때만 일어난다. 미래 날짜는 자동 snapshot을 미리 저장하지 않으며, 관리자 모달은 read-only updates 조회를 사용한다.
6. 학생 시청은 `watch.json`에 위치·길이·완료·시각을 저장하고 자동 상태를 `progress.json`에 투영한다.
7. 시험 배정·답지 링크·과거 기록 조회는 유지하지만 학생 시험 제출은 제공하지 않는다.
8. 완료·하원·숙검하원은 서로 다른 정책이다. 상태 변경이 없는 버튼을 상태 완료와 혼동하지 않는다.

## 7. 출결·오늘 순서·보강

- 출석, 결석, 도착 시각, 연락 상태는 각각 `attendance.json`, `absent.json`, `arrive_time.json`, `contact.json` 계열 API가 담당한다.
- 보강은 `extra_attend.json`, 주말 시간은 `weekend_slots.json`, 보강 이월은 전용 carryover API가 담당한다.
- 오늘 순서의 유일한 원본은 `data/today_order.json`이다. 루트 `today_order.json`은 2026-08-24 백업·통합 후 제거됐으며 다시 만들지 않는다.
- 오늘표의 완료는 수업 로그의 `done`과 연결되지만 결석·출석·하원 버튼의 의미와 동일하지 않다.
- “숙검하원”은 오후 6시 전 연강 학생을 제외하고, 오후 6시 이후에는 포함한다. 자습 학생은 포함한다.
- 연강/보강/주말 slot 배열은 기존 문자열 sid와 다중 slot 호환을 유지한다.
- 결석 전체 저장에 실제 달력에 없는 `YYYY-MM-DD`가 신규로 들어오면 현재 500을 반환하는 알려진 제한이 있다. 사용자 선택 B에 따라 선행 400 검증은 추가하지 않았으며, 이 실패는 모든 관련 저장소 무변경·무알림이어야 한다.

## 8. 수업 로그와 숙제

### 저장 원칙

- 논리 원본은 `LogRepository`다. SQLite가 우선이며 `logs.json`은 호환 fallback·mirror 역할을 한다.
- 같은 날짜/sid가 두 저장소에 있으면 SQLite의 의미 있는 필드를 보존하고 JSON은 빠진 필드만 좁게 채운다.
- 저장은 `get_log_repository()`를 통하고, 순수 병합·충돌 규칙은 `core/log_rules.py`에 둔다.
- 빈 값은 명시적 clear/delete 계약이 없으면 기존 교재, 숙제표, 메모를 지우지 않는다.
- 알 수 없는 필드와 legacy 숙제 행 메타데이터도 보존한다.
- 일부 GET은 SQLite 스키마/WAL을 보장할 수 있으므로 운영 데이터 관점에서 완전한 무변경 읽기로 간주하지 않는다.

### 화면 의미

- 학생 페이지의 수업·숙제 미완료 패널은 로그의 완료/보관 상태를 읽는다.
- 전체 학생/관리자 팝업은 같은 로그 계약을 공유하되 선택 날짜를 유지한다.
- 숙제 검사 팝업은 입력칸 자체가 위치를 설명하므로 교재·이번 숙제/진행률·코멘트·다음 숙제 헤더 문구를 표시하지 않는다.
- 단순 `하원`과 `숙검하원`은 하원 완료만 기록하며 시험 상태를 바꾸지 않는다.
- `기록 정리`는 하원 완료 행을 최종 보관하는 별도 명령이며, 이때만 시험 완료 전이를 수행한다.

### 내보내기 계약

- `명단 내보내기`의 영상 텍스트는 선택일 배정 snapshot에서 선택일 전에 이미 `done`이었고 선택일에 명시적으로 재개되지 않은 차시는 제외한다. 선택일 당일 처음 완료됐거나 비완료 상태로 다시 연 차시는 유지하며, 같은 날 배정된 테스트와 함께 출력한다.
- `로그 내보내기` TXT와 CSV `progress` 열은 같은 비완료 변화 목록을 사용한다. 둘 다 `done`(파란색)을 제외하고 `interrupted` 같은 비완료 변화만 표시하되, CSV의 고정 14열 구조는 유지한다.
- 두 내보내기의 테스트 텍스트는 현재 커리큘럼에서 상태가 `assigned`(초록색)인 배정 이름만 사용한다. `SCHOOL_PAST`는 `학군지(난이도) 회차 이름`, `ILSAN_PAST`는 `일산(난이도) 회차 이름`으로 표기하며, 채점 정보는 제외하고 테스트 이름마다 실제 줄바꿈을 넣는다.
- 내보내기 전 로그·진도 전체 이력을 `no-store`로 다시 읽고, 조교 학생 메모는 TXT·CSV 어디에도 포함하지 않는다.

### 기록 정리 상태 전환 계약

| 최신 권위 상태 | 시험 처리 | 로그 처리 |
|---|---|---|
| 진도 `assigned` | `done`으로 전환 | 같은 시험의 배정 메타데이터를 완료로 정리 |
| 진도 `done` | 유지 | 로그의 남은 `assigned` 메타데이터가 있으면 완료로 동기화 |
| 진도 `interrupted` | 유지 | 완료로 올리지 않음 |
| 진도 `skip` | 유지 | 완료로 올리지 않음 |
| 진도에 명시적 흰색(`none`/explicit blank) 키가 있음 | 유지 | 완료로 올리지 않음 |
| 진도에 해당 시험 키가 없고 최신 로그에는 배정이 있음 | 로그를 보조 근거로 `done` 생성 | 완료로 정리 |
| 해당 날짜 결석 학생 | 시험 전이 생략 | 최신 로그 검증 후 행만 보관 가능 |

권위와 실행 순서는 다음과 같이 고정한다.

1. 개별 정리는 클릭한 행의 `data-date`와 sid, 일괄 정리는 선택 날짜에서 수집한 각 sid를 대상으로 한다.
2. 브라우저의 `state.logs`, `state.progress`는 렌더링 캐시일 뿐 정리 시점의 권위가 아니다. 값이 비어 있지 않아도 최신이라는 뜻으로 사용하지 않는다.
3. 먼저 `/api/logs/entry?date=...&sid=...`를 `no-store`로 다시 읽는다. 응답이 실패·비JSON·빈 entry이거나 최신 entry가 `done != true` 또는 `archived == true`면 즉시 중단한다.
4. 결석이 아니면 `/api/progress?date=...&sid=...`도 `no-store`로 다시 읽고, 정확한 날짜/sid entry가 없거나 응답 형식이 잘못되면 중단한다.
5. 상태 판정은 최신 진도를 우선한다. 최신 진도에 시험 키 자체가 없을 때만 최신 로그 배정 메타데이터를 누락 보정용 근거로 사용한다.
6. 쓰기는 `progress tests patch`를 먼저 성공시킨 뒤, 시험 메타데이터 patch와 `archived: true`를 한 로그 patch로 저장한다. 개별·일괄 정리 모두 `completeAssignedTestsForRecordCleanup()`을 거쳐야 한다.
7. 최신 조회 또는 progress patch가 실패하면 로그 보관을 호출하지 않는다. 화면에는 실패를 알리고 행은 미보관 상태로 남겨 재시도할 수 있게 한다.
8. progress patch 성공 뒤 로그 patch만 실패하면 시험은 완료이고 행은 미보관인 복구 가능한 중간 상태다. 재시도는 같은 결과를 만드는 멱등 동작이어야 한다.
9. 단순 `하원`, `숙검하원`, 하원 취소에서 이 helper를 호출하거나 시험 상태를 암묵적으로 변경하지 않는다.

현재 최신 조회와 두 저장은 서로 다른 API 호출이므로 완전한 원자 트랜잭션은 아니다. 정리 도중 다른 화면에서 새 시험을 배정하는 경쟁이 실제로 반복되면 프런트 재조회 횟수를 늘리는 방식으로 덮지 말고, 서버의 날짜/sid 단위 전용 정리 endpoint와 잠금·버전 검증으로 승격한다.

필수 회귀 검증은 `node scripts/verify_record_cleanup_test_status.mjs`다. 최소한 개별/일괄 정리, 비어 있는 캐시, 값이 있는 stale cache, `assigned → done`, `interrupted/skip/명시적 흰색` 보존, 최신 조회·progress patch 실패 시 무쓰기·무보관, 원격 하원 취소 시 무보관을 포함한다. 이 검증은 `python scripts/verify_refactor_safety.py` 기본 suite에서도 실행되어야 한다.

## 9. 영상 카탈로그와 배정

### 카탈로그 식별자와 저장

- `videos.json`의 `id`는 영상 관리 행의 안정적인 숫자 ID이고, `mid`는 실제 Kollus media content key다. 새 행 ID는 현재 유효한 숫자 ID의 최댓값 다음 값으로 만든다.
- 영상 관리 화면은 Kollus URL에서 `mid`를 추출하며 `/api/videos` POST는 잠금 안에서 카탈로그 전체를 저장한다. 일반 모드에서는 새 행 추가와 제목·챕터·과정·같은 MID의 서명 URL 보정만 허용한다.
- 기존 안정 ID가 사라지거나 같은 ID의 URL-derived MID가 달라지면 서버는 쓰기 전에 409를 반환하고 화면은 마지막 저장 상태로 복구한다. 일반 POST에 우회 flag는 없다. 수정 모드는 마지막 저장본을 기준으로 브라우저에서 별도 JSON 초안만 만들며 서버 POST를 하지 않는다. 실제 적용은 `apply_video_catalog_correction.ps1`의 dry-run → Waitress 정지 → 런타임 백업/hash 확인 → 4개 store 일관 변환 → 재시작 절차로만 수행한다.
- 실제 사용 순서는 [VIDEO_CATALOG_CORRECTION_MODE.md](VIDEO_CATALOG_CORRECTION_MODE.md)를 따른다.

### 배정 유형

| 유형 | 의미 | 주의 |
|---|---|---|
| 자동 `source: "auto"` | 서버가 실제 오늘의 수업·과정·과거 진도를 기준으로 오늘 최초 생성한 snapshot | 미래 날짜에는 저장하지 않는다. 생성 뒤 고정되며, 오늘의 명시적 과정 변경으로 저장 MID가 현재 과정 밖이 된 경우만 재배치한다. |
| 수동 `source: "manual"` | 관리자가 학생·날짜에 명시적으로 저장 | 교차 과정 추가 영상과 명시적 빈 배정을 포함하며 자동 로직이 덮지 않는다. |
| 자습 `source: "selfStudy"` | 서버가 자습일의 과거 완료 영상을 지정 | `/api/updates/self-study`가 자습·결석·보관·완료 이력을 다시 검증한다. |
| 학생 “영상 등록” | bootstrap이 허용한 완료 영상을 당일 개인 재생목록에 추가 | `updates.json` 배정 유형이 아니다. `student:review-playlist:<sid>:<date>` localStorage에만 저장한다. |

### 자동 배정 불변식

- 서버 자동 배정의 최초 생성 진입점은 실제 오늘을 대상으로 한 bare `GET /api/updates`, 관리자 30초 날짜 경계 감지, 비공개 real-today 학생 bootstrap, 오늘 보강/일정 변경이다. 서버가 자정에 실행 중인 관리자 화면을 만나면 30초 이내 생성하고, 화면이 닫혀 있으면 첫 오늘 관리자/학생 접근이 같은 멱등 함수를 실행한다. 미래 보강·일정 변경과 미래 날짜 조회는 storage-only이며 `source: "auto"`를 만들지 않는다. 관리자 영상 모달은 반드시 `/api/updates?readOnly=1`로 연다.
- 대상은 정규 수업 또는 보강 등록 학생이며 결석과 `done` 로그는 제외한다. 자습은 일반 대상 판정과 분리된 명시적 일일 모드다.
- 학생별 설정은 기본 개수 1~6개, 기본값 3개, A:Ble 기본값 1개다. 오늘의 weekend override와 slot 결석을 반영한 실제 슬롯이 인접하면 유효 개수는 2배가 된다.
- 자동 후보는 학생의 정확한 현재 curriculum/subCurriculum 안에서 chapter 순으로 고른다. nonblank subCurriculum이 맞지 않을 때 과목 전체 fallback을 쓰지 않으며 다른 과정은 관리자 수동 추가만 허용한다.
- 과거 `done`과 `skip`은 자동 후보에서 제외한다. 자동 `interrupted`는 이어볼 수 있고, 나중의 수동 `none`/`interrupted`는 완료 이력을 명시적으로 다시 열 수 있다.
- 미래 `source: "auto"` snapshot은 만들거나 유지하지 않는다. 미래 수동·자습과 출처를 확정할 수 없는 legacy 항목은 별도 명시 배정으로 보존한다. 오늘 자동 snapshot은 progress/watch 완료, 일정, 결석, 연강, 학생별 개수 변경으로 전진·축소·삭제·보충하지 않는다. 개수 변경은 다음 날짜 경계에서 사용할 학생 설정만 저장한다.
- 완료·skip 때문에 자동 snapshot이 비었다고 판단해 제거하지 않는다. 자동 snapshot 제거는 명시적 과정 재지정처럼 현재 과정 MID가 사라진 경우에만 허용하고, 수동 빈 저장은 명시적 clear로 남긴다.

### 학생 복습 등록과 자습 배정

- `/api/student/bootstrap.reviewVideos`가 학생 복습 후보의 유일한 권위다. 요청 날짜까지의 현재 curriculum/subCurriculum `done` 영상만 포함하므로 같은 날 방금 완료한 영상도 후보가 될 수 있다. `interrupted`, `skip`, `none`, 미시청, 다른 과정은 제외한다.
- 학생 웹은 `/api/student/bootstrap` 실패 시 오류를 표시하고 초기화를 중단한다. 학생·영상·배정·자료·결석·로그 API를 따로 호출해 일부 데이터만 조립하던 구형 7개 요청 fallback은 제거되었으며 다시 사용하지 않는다.
- bootstrap은 후보를 chapter/MID 순으로 정렬하고 raw progress/watch와 event date를 제거한다. 학원 외 응답에서는 URL·재생 권한도 제거하고 `playbackRestricted`만 남긴다. 현재 미완료 재생목록에 남아 있는 MID는 중복 후보에서 제외하지만, 오늘 완료되어 재생목록에서 빠진 MID는 복습 후보로 다시 보일 수 있다.
- 학생의 체크와 “영상 등록”은 서버 요청 없이 localStorage에 선택 순서대로 저장하고 현재 재생목록 뒤에 붙인다. 새 bootstrap 후보에 없는 저장 MID와 중복은 매 로드 때 제거한다. 등록 행을 실제 재생할 때만 기존 `/api/get-url`·Kollus bridge·`/api/watch` 흐름을 사용한다.
- 일반일과 자습일의 chooser UI는 같다. 결석, 보관, ghost, course-blocked, malformed bootstrap에서는 숨기고, 학원 외 네트워크에서는 제목만 보여 주며 등록·재생·watch 쓰기를 금지한다.
- 서버 자습 배정은 별도다. `/api/updates/self-study`는 target date보다 엄격히 이전에 완료한 현재 과정 MID만 받고, 기존 비-selfStudy 수동 배정을 보호한다. 학생의 로컬 “영상 등록” 버튼은 이 endpoint를 호출하지 않는다.

## 10. 시청 기록과 진도 상태

### 원본과 필드

`watch.json`의 날짜/sid/mid 레코드는 다음 필드를 가진다.

| 필드 | 의미 | 병합 |
|---|---|---|
| `last` | 가장 멀리 본 초 위치 | 큰 값 유지 |
| `dur` | 영상 길이(초) | 큰 값 유지 |
| `completed` | 완료 여부 | 한 번 true면 자동 replay가 false로 내리지 않음 |
| `updatedAt` | JavaScript epoch milliseconds wire 값 | 정수화 후 큰 값 유지 |

- 브라우저와 Kollus callback은 `updatedAt`을 epoch milliseconds로 보낸다. 브라우저는 bitwise 절단 없이 정규화하고, 서버는 유효한 밀리초 값은 보존하며 과거 32비트 절단값은 수신 시 현재 밀리초로 교정한다.
- `verify_student_watch_timestamp.mjs`와 `verify_watch_timestamp_guard.py`가 브라우저 직렬화와 서버 수신 교정을 검사한다.
- 5% 이상 시청은 자동 `interrupted`, 90% 이상 또는 완료 이벤트는 자동 `done`이다.
- 길이를 모르는 상태에서 위치가 0보다 크면 시작으로 본다.
- `progress.json`은 화면 상태의 권위 원본이며, 같은 날짜/mid의 watch보다 우선한다.
- 과거 `done` 후 나중에 재생한 `interrupted`는 완료 이력을 자동 취소하지 않는다.
- 브라우저는 Kollus controller의 ready/progress/play/pause/done 이벤트와 3초 polling을 localStorage에 병합하고 1.5초 debounce, 영상 전환, pagehide, 숨김 때 `/api/watch`로 flush한다. watch 저장은 실패해도 로컬 재생 위치를 유지하며 다음 동기화에서 다시 시도한다.
- `/api/watch`와 Kollus callback은 같은 monotonic watch 병합 및 자동 progress writer를 사용한다. 완료가 유효하게 저장되어도 자동 배정 reconcile을 호출하지 않으며 날짜별 snapshot은 그대로 유지한다.

### 수동/자동 우선순위

1. 명시적 수동 상태와 `__manualProgressMids`
2. 기존 자동 상태와 `__autoWatchProgressMids`
3. 새 watch 자동 투영
4. 비어 있는 기본값

자동 업데이트는 수동 흰색(`none`), 수동 `skip`, 수동 `interrupted`를 덮지 않는다. 자동 `interrupted`는 자동 `done`으로 올라갈 수 있다. 자동 빈 값은 자동 미완료를 지울 수 있지만 완료를 내리지 않는다.

## 11. 시험 배정·답지·과거 기록

- 카탈로그 원본은 `tests-config.json`이다. `tests.json`과 legacy 로그의 기존 성적은 읽기 전용 과거 기록이며 학생 화면에서 새 기록을 만들지 않는다.
- `/api/tests-config`의 전체 저장은 기존 시험의 암묵적 삭제를 409로 거부한다. 삭제는 명시적 ID 목록으로 요청한다.
- 기존 키, `sourceFiles`, 답지 메타데이터를 보존한다.
- `REVIEW`, `SCHOOL_PAST`는 `sourceFiles.solutionFileId` 또는 동등 메타데이터를 유지한다.
- `UNIT` 답지는 Drive 설명 파일에서 생성한 `static/js/test_answer_link_map.json`과 동기화한다. 구형 `test_answer_link_map.js`와 `/js/test_answer_link_map.js` 주소는 2026-08-24 제거됐으며 다시 만들지 않는다.
- UNIT 해설 링크 생성은 과목·난이도·단원명 후보가 여러 개면 Drive PDF 파일명의 선행 순번과 카탈로그 `sourceOrder`가 정확히 일치하는 한 시험에만 연결한다. 순번이 없거나 여전히 여러 후보이면 링크를 만들지 않고 `ambiguous_answer_file`로 실패한다.
- 하나의 Drive `fileId`는 카탈로그 전체에서 한 sourceId/회차만 소유할 수 있다. 해설이 확인되지 않은 시험은 잘못된 PDF를 재사용하지 않고 링크를 비워 두며 `answerLinkStatus: "missing"`을 명시한다. 생성기는 이를 비치명적 `expected_missing_round`로 보고하고, 테스트 관리 목록은 `해설 미연결`로 표시하며, 검증 전까지 해당 회차의 `answerModes`를 전 문항 `manual_review`로 둔다.
- 학생 bootstrap은 `assignedTests`를 최상위 배열로 반환하고 각 카드의 `answerUrl` 우선순위를 유지한다.
- 시험 배정 상태는 기본 `assigned`, 완료/정리 후 `done`이다. 화면 편의 상태가 기록 원본을 임의로 대체하면 안 된다.
- 학생별 단원평가 기본 레벨은 학생 레코드의 `testLevelDefaults.UNIT[정규화 과목]`이 원본이다. 테스트 배정 팝업의 `레벨 설정`은 Lv.3~Lv.6 GUI에서 이 필드만 `/api/update`로 저장하며, 현재 배정 상태나 관리 페이지의 공통 규칙을 함께 바꾸지 않는다.
- 학생별 기본 레벨이 있어도 일반 `난이도` 선택에는 해당 분류의 전체 난이도(UNIT은 Lv.3~Lv.6)를 계속 노출한다.
- 테스트 배정 팝업의 최초 과목은 현재 학생 레코드의 `curriculum` 정규화값이 절대 우선이다. 학생별 브라우저 최근 보기나 배정 이력이 다른 과목이어도 최초 과목을 덮어쓰지 않는다.
- 현재 커리큘럼 과목 안에서만 첫 보기 우선순위를 학생별 브라우저 최근 보기(`admin.testAssignment.recentView.v1:<sid>`) → 현재/직전 배정 이력의 마지막 유효 항목 → 학생별 기본값과 테스트 관리 공통 규칙 순으로 적용한다.
- 최근 보기는 현재 커리큘럼과 같은 과목의 분류·난이도·고사·회차만 복원한다. 카탈로그에서 삭제되었거나 조합이 맞지 않거나 다른 과목인 저장값·이력은 무시하며, 팝업 안에서 수동으로 본 다른 과목은 다음 오픈의 시작값으로 저장하지 않는다.
- Ctrl/Cmd+클릭의 다중 선택은 배정 상태와 별개인 `선택` 표시다. 방향키 상태 순환은 왼쪽/오른쪽 모두 `흰(없음) ↔ 주(배부) ↔ 초(배정) ↔ 파(완료) ↔ 빨(제외)`의 역/정방향을 유지한다.
- 학생 시험 카드는 배정 상태와 서버가 투영한 답지 링크만 표시한다. 답지가 없으면 비활성이고, 학원 밖에서는 제한 안내만 표시한다.
- `/api/submit-test`, `/api/ocr-test-sheet`, `/api/ocr-test-sheet-review`, `/student-test/<sid>`는 제거되었다. `/api/tests`는 GET 전용이며 과거 기록을 쓰거나 삭제하지 않는다.
- 외부 네트워크 응답에서는 답지 URL, solution/answer 필드와 정답 키를 제거한다.

## 12. 메모·운영 이력의 분리

| 기능 | 저장/의미 | 섞으면 안 되는 것 |
|---|---|---|
| 조교 학생 메모 | SQLite 기반 thread, 작성일·작성자·색상, 편집/삭제/핀/리마인더/완료 | 수업 로그 메모, 상담 CSV |
| 관리자 운영 노트 | 관리자 화면 운영 메모 | 학생별 조교 메모 |
| 학생 운영 로그 | 학생 관련 사건 이력, 개별/전체 삭제 | 수업 로그, 브라우저 localStorage |
| 학생 복습 재생목록 | SID/date 범위 localStorage UI 선호 | 서버 배정, 수업 로그, 상담/운영 이력 |

확인일 메모 카드는 `[상태] 작성일 → 확인일`을 단독 행으로 유지하고, 다음 행의 왼쪽에는 작성자·핀, 오른쪽 끝에는 `수정 · 삭제`를 배치하며 메모 내용은 그 아래 행에서 시작한다. 날짜와 작업 버튼은 같은 가로 영역에서 겹치면 안 된다.

조교 메모는 고정·확인일 우선순위를 유지하되 같은 우선순위 안에서는 `created_at DESC, id DESC`로 최신 작성 메모를 위에 표시하고, 목록을 열거나 새 메모를 등록한 뒤에도 맨 위를 보여준다.

삭제·완료·핀·리마인더는 각각 다른 상태 변화다. UI에서 한 동작을 다른 저장소의 삭제로 확대하지 않는다.

## 13. 공지·설문·캘린더·자료

- 공지는 목록/작성/수정/삭제, 이미지 업로드/다운로드 소스, 확인, 답글·설문 제출을 지원한다.
- 학교 일정은 `school_calendar.json`과 캘린더 API가 담당하며 sheet/import 작업은 기존 학교·학기 키를 merge한다.
- 자료는 `materials`, `mat-assign`, `files/`와 파일 API가 담당한다.
- 파일 API는 tree, folder, rename, move, delete, upload를 제공한다. 한글 이름을 보존하고 폴더 하위 materials URL, assignment ID·URL·relative·DIR token, page-folder 값을 segment 단위로 함께 갱신한다. 루트 이동은 빈 dst를 사용한다. 삭제는 staging 뒤 세 JSON을 저널 커밋하며 pre-journal 실패는 파일을 복구한다. /api/fs/page-folders HTTP 표면은 폐기됐지만 내부 저장소는 참조 무결성 대상으로 유지한다.
- `materials.json`, `mat_assign.json`, `page_folders.json`은 결정적 잠금 순서와 하나의 복구 저널로 읽고 저장한다. `/api/mat-assign` GET의 revision을 POST `If-Match`로 돌려주지 않으면 428, 낡았으면 무쓰기 409다. 유효한 미완료 저널은 roll-forward하고, 손상된 저널·저장소에서는 마지막 정상 snapshot으로 조회만 유지하며 파일·교재 mutation은 503이다. 이 장애는 서버의 다른 기능과 시작을 막지 않는다.
- 보강 이월과 시트 동기화는 전용 API다. 대량 적용 전 런타임 백업이 필요하다.
- 비학생 OCR review cache는 내부 API이며 실제 시험 제출과 분리한다.

## 14. 주요 데이터 원본

| 데이터 | 주 원본 | 비고 |
|---|---|---|
| 학생 | `students.json` | 알 수 없는 학생 필드 보존 |
| 영상 카탈로그 | `videos.json` | 숫자 row `id`, Kollus `mid`, URL·과정·chapter·서술형 번호 |
| 날짜별 배정 | `updates.json` | legacy/`auto`, `manual`, `selfStudy`; 학생 로컬 복습 등록은 포함하지 않음 |
| 화면 진도 상태 | `progress.json` | 수동/자동 메타키 포함 |
| 시청 위치 | `watch.json` | `last`, `dur`, monotonic `completed`, 의도된 밀리초 `updatedAt` |
| 학생 복습 재생목록 | 브라우저 localStorage `student:review-playlist:<sid>:<date>` | fresh bootstrap `reviewVideos`로 매번 교집합 정리; 서버 이력 아님 |
| 수업·숙제 로그 | SQLite `app.sqlite` + `logs.json` | SQLite 우선, JSON 결손 보충 |
| 시험 카탈로그 | `tests-config.json` | 암묵 삭제 금지 |
| 과거 시험 결과 | `tests.json` + legacy 로그 | 기존 점수·오답 조회 전용; 학생 제출 쓰기 없음 |
| 출결 계열 | `attendance.json`, `absent.json`, `arrive_time.json`, `contact.json` | 날짜/sid 부분 갱신 |
| 미완료 결석 트랜잭션 | `instance/absence_transactions/pending.json` | 진행 중에만 존재; 민감 before-image는 미러하지 않고 commit/rollback 뒤 제거 |
| 보강 | `extra_attend.json`, `weekend_slots.json` | carryover 별도 |
| 오늘 순서 | `data/today_order.json` | 단일 canonical store; 루트 동명 파일은 제거됨 |
| 학사 일정 | `school_calendar.json` | import merge |
| 학생 계정 | `auth_accounts.json` | JWT 비밀키와 별개 |
| 메모·운영 로그 | `app.sqlite` 내 분리 테이블 | 서로 다른 repository/route |
| 학생 앱 세션·계정 감사 | `app.sqlite` | session, audit, activation, throttle 테이블 |
| 학생 앱 푸시 | `app.sqlite` | subscription, outbox, bypass 테이블; VAPID/flag와 별도 |
| 학생 앱 숙제·focus·reminder | `app.sqlite` 명시적 migration | 현재 운영 DB에는 미적용이며 해당 feature flag도 OFF |
| 업로드 | `files/` | Git 코드와 분리한 운영 자료 |

`app.sqlite-wal`, `app.sqlite-shm`, `data/`, `files/`, `_data_mirror/`, `_runtime_backups/`, root `*.tmp`도 런타임 데이터다.

루트 SQLite 정본은 `app.sqlite` 하나다. 데이터가 없고 코드 참조도 없던 구형 `vacation.db`는 2026-08-24 백업 후 제거했으며 다시 만들지 않는다.

## 15. API 그룹

- 기본 데이터: `/api/students`, `/api/videos`, `/api/updates`, `/api/progress`, `/api/materials`, `/api/school-calendar`
- /api/students와 /api/materials는 GET 전용이다. 학생 쓰기는 add/update/delete 경로가 students 파일 잠금 안에서 수행하며 전체 배열 POST는 허용하지 않는다.
- 부분 갱신: `/api/update`, `/api/updates/patch`, `/api/progress/patch`
- 자습 영상 배정: `/api/updates/self-study`
- 학생 통합 읽기: `/api/student/bootstrap`
- 시청: `/api/watch`, `/api/watch/latest`, `/api/watch-status`, `/api/get-url`, `/api/kollus/lms-callback`

`/api/watch-status`는 다른 개발컴퓨터에서 작업 중인 학생 앱을 위한 임시 호환 API다. 현재 웹 학생 화면은 `/api/watch`만 사용하며, 학생 앱을 같은 방식으로 전환해 병합하기 전에는 제거하지 않는다. 새 웹 코드에서는 `/api/watch-status`를 사용하지 않는다.

`/api/updates/review`와 `/api/updates/training-pack` 영상 배정 endpoint는 존재하지 않는다. 학생 복습 등록은 localStorage이고, 시험 카테고리 `트레이닝팩`과 영상 배정 API를 혼동하지 않는다.

`/api/updates` 기본 주소는 GET 전용이다. 영상 배정 저장은 학생·날짜 단위의 `/api/updates/patch` 또는 검증된 `/api/updates/self-study`만 사용하며, 여러 날짜·학생을 한꺼번에 합치던 기본 주소 POST는 제거되었다.
- 로그: /api/logs(GET 전용), /api/logs/patch, /api/logs/patch-batch, /api/logs/entry, 미보관 요약, 숙제 교재
- 시험: `/api/tests`(GET 전용), `/api/tests-config`, `/api/tests-records`, `/api/tests-stats`; 학생 제출/OCR 제출 API 없음
- 출결: attendance, attend, today, absent, arrive-time, contact

등원시간의 표준 주소는 `/api/arrive-time`과 `/api/arrive-time/patch`다. 접두어가 없던 옛 `/arrive-time*` 주소는 제거되었으며 다시 사용하지 않는다.

출석·연락의 기본 주소(`/api/attendance`, `/api/contact`)는 조회 전용이다. 저장은 학생 한 명씩 처리하는 각 `/patch` 주소만 사용하며, 여러 학생을 한꺼번에 저장하던 기본 주소 POST는 제거되었다.

보강출석은 `/api/extra-attend` 하나만 사용한다. `/api/extra`, `/api/extra_attend`, `/api/extra-attend/all`은 실서버에 없는 옛 이름이며 사용하거나 복원하지 않는다.

새 결석 `(date, sid)`은 공용 계획 규칙으로 시험 carryover를 먼저 수집한 뒤 `updates` 배정 제거, progress 시험 `assigned → interrupted(배부)`, dual class-log 정리, `absent`, 선택적 makeup carryover 순으로 반영한다. 이 묶음은 `core/absence_transaction.py`가 날짜 단위 JSON before-image와 SQLite 대상 행을 transient no-mirror 저널에 기록해 관리한다. 성공 전 어느 단계에서 실패해도 전부 복구하고 알림을 보내지 않으며, 프로세스 종료로 남은 non-committed 저널은 서버 시작 또는 다음 결석 쓰기 전에 이전 상태로 복구한다. 복구 자체가 실패하면 503/시작 실패로 닫는다. 정상 응답·revision·시험 상태 의미와 결석 취소 시 배정을 자동 복원하지 않는 규칙은 그대로다.
영상 시청 저장(`/api/watch`, `/api/watch-status`, Kollus LMS callback)도 같은 결석 consistency barrier를 통과하므로, 결석 정리가 progress를 비운 직후 동시 재생 요청이 상태를 되살릴 수 없다.
- 오늘 순서·보강: today_order patch, extra-attend, weekend-slots, makeup-carryover, sheet-sync
- 인증: `/api/auth/login`, `me`, `switch`, `change`
- 메모·이력: assistant-student-notes, admin-operation-notes, student-logs
- 학생 앱: `/api/mobile/auth/*`, `/api/mobile/push/*`, `/api/mobile/student/board`; homework/focus는 feature flag 조건부
- 학생 계정 관리: `/api/student-accounts`, `/api/admin/student-focus/summary`; 관리자 homework도 feature flag 조건부
- 공지: announcements, image, ack, submit
- 파일: `/api/fs/*`, `/files/<path>`
- 내부: non-student OCR review cache

엔드포인트 URL, payload 키, 응답 shape는 전용 마이그레이션 없이 바꾸지 않는다.

## 16. 코드의 기준 위치

| 로직 | 기준 위치 |
|---|---|
| 앱 조립·HTTPS·CSRF·답지 gate | `app.py` |
| 네트워크/답지 strip | `core/network_access.py` |
| 시험 답지 링크 우선순위 | `core/test_answer_links.py` |
| 공지 이미지 학생 공개 멤버십 | `core/announcement_image_access.py` |
| 로그 병합 규칙 | `core/log_rules.py` |
| 로그 저장소 | `core/log_repository.py` |
| 시청/진도 상태 전이 | `core/progress_rules.py` |
| 공용 watch·자동 진도 writer | `core/watch_progress_writer.py` |
| 결석 배정 projection | `core/absence_assignment_cleanup.py` |
| 결석 다중 저장 원자성 | `core/absence_transaction.py`, `routes/absence_assignment_cleanup.py`, `app.py` |
| 진도 JSON cache·잠금·저장 | `core/progress_store.py` |
| 진도 milestone 알림 bridge | `core/progress_notifications.py` |
| 학생 복습 후보 | `core/video_review_rules.py` |
| 원자 JSON 저장 | `core/storage.py` |
| 광범위 API/자동 배정 | `routes/api_basic.py` |
| 시청 API | `routes/api_watch.py` |
| 시험 | `routes/api_tests.py` |
| 관리자 날짜 | `static/js/admin/core/adminDate.js` |
| 관리자 하루 hydrate/render | `static/js/admin/features/today.js` |
| 학생 bootstrap/시청 | `static/js/student.js` |
| 학생 앱 host/session 정책 | `core/student_public_surface.py`, `core/student_app_config.py` |
| 학생 앱 인증·계정 | `core/student_app_auth_*`, `routes/api_student_app_auth.py`, `routes/api_student_accounts.py` |
| 학생 앱 push/notification | `core/student_push_*`, `core/student_notification_*`, `routes/api_student_push.py` |
| 학생 앱 숙제·focus | `core/student_homework_*`, `core/student_focus_*`, 해당 route 모듈 |
| 공통 API | `static/js/shared/api.js` |
| 회귀 허브 | `scripts/verify_refactor_safety.py` |

## 17. 영역별 패치 점검표

| 변경 영역 | 반드시 확인할 것 | 최소 검증 |
|---|---|---|
| 관리자 UI | 선택 날짜, 행 `data-date`, Korean UTF-8, modal scroll | `node --check` + DOM/API + screenshot |
| 로그/숙제 | SQLite/JSON 양쪽, 빈 값 보존, manual white reload | 관련 unit + 양쪽 endpoint + 브라우저 |
| 영상 카탈로그/MID | 숫자 ID, 일반 모드 409, 수정 모드 초안, 참조 삭제 거부, 정지·백업·롤백 적용 | `verify_video_manage_ids.mjs` + `verify_video_mid_change_guard.py` + `verify_video_catalog_correction.py` |
| 영상 자동 배정 | real-today 최초 생성, 미래 auto 금지, read-only modal, 정확한 과정, 연강 2배, 완료 후 당일 불변 snapshot | assignment boundary/immutability unit + video modal policy |
| 학생 시청 | 5%/90%, replay done, academy gate, SID bind, millisecond wire value, flush | progress/watch unit + `verify_student_watch_timestamp.mjs` + `verify_watch_timestamp_guard.py` |
| 학생 복습 등록 | bootstrap done-only, current course, local-only registration, stale storage prune, restricted title-only | previous-video DOM + material access + 브라우저 |
| 공지 이미지 공개 | raw URI 단일 파일, active SID, 현재 가시 공지 멤버십, 숨김 상태, 로컬 호환 | `verify_announcement_image_access.py` + student-data/academy-gates |
| 시험 공용 경계 | direct/config/map 우선순위, tests-config 잠금 경쟁, 관리자 기록 학원 내·외 gate, private import 부재 | `verify_test_shared_services.py` |
| 시험 | top-level `assignedTests`, status, 답지 우선순위, config 삭제 안전, 과거 기록 보존, 제출 경로 부재 | assignment/bootstrap/config/history + retired-surface 검증 |
| 출결/오늘 순서 | 문자열 sid, 선택 날짜, `data/today_order.json` | route unit + 해당 화면 |
| 인증/프록시 | Basic fail-closed, AUTH_SECRET 지속, 신뢰 프록시, HTTPS loop 없음 | admin/auth/proxy 검증 + 실제 HTTP/HTTPS |
| 파일 | 경로 탈출 방지, 업로드/이동 참조 | file route 검증 |
| 데모 | 모든 write가 sandbox에 머무는지 | demo behavior 검증 |

공통 명령:

```powershell
python -m compileall -q app.py routes core scripts
node --check static/js/student.js
node --check static/js/admin/features/videoModal.js
node scripts/verify_video_manage_ids.mjs
node scripts/verify_student_previous_video_review.js
node scripts/verify_student_material_access_scope.js
python scripts/verify_refactor_safety.py --only-video-modal-assignment-policy
python scripts/verify_refactor_safety.py
python scripts/verify_academy_proxy_network_access.py
python scripts/verify_refactor_safety.py --smoke
```

`--smoke`는 live app import와 WAL/SHM 변화를 허용하므로 순수 단위 검증과 다르다. UI 변경은 reload 후 DOM/API를 먼저 확인하고 레이아웃 변경이면 screenshot까지 확인한다.

## 18. 운영·배포 계약

- Waitress는 Windows 예약 작업 `Academy Server Waitress`로 8003 포트를 연다.
- 공개 도메인은 Cloudflare Tunnel이 localhost:8003으로 전달한다.
- 기존 호스트 `5a-math.com`의 HTTP 루트는 전환 승인 전까지 200으로 유지한다. 학생 앱 호스트 `app.5a-math.com`은 HTTP를 404로 닫고 HTTPS 루트만 `/app`으로 302 이동한다.
- Waitress와 tunnel의 로그온 종속 여부를 별도 확인한다. 사용자 로그아웃 후에도 운영해야 하면 둘 다 관리자 권한의 Windows service 또는 비대화형 작업으로 옮겨야 한다.
- Cloudflare tunnel 서비스화는 자격 증명/config를 LocalSystem이 읽을 수 있는 위치로 옮기고 관리자 권한으로 설치·검증해야 한다. 코드 패치만으로 끝나는 작업이 아니다.
- 코드 배포 전 `python scripts/backup_runtime_data.py`로 운영 데이터를 백업한다.
- 재시작 후 listener, task result, HTTP→HTTPS, HTTPS login, 학생 bootstrap, 학원/외부 gate를 확인한다.
- 검증을 위해 띄운 임시 서버는 종료한다.

## 19. 알려진 호환성과 위험

- 로그는 SQLite와 JSON 이중 경로다. 한쪽만 고치면 누락 또는 회귀가 생긴다.
- `progress.json`은 크고 날짜/sid keyed다. 프런트 전체 파일 교체를 하지 않는다.
- 학생 bootstrap GET과 일부 GET은 보장/마이그레이션 쓰기를 할 수 있다.
- bare `GET /api/updates`는 이름과 달리 자동 배정 쓰기를 할 수 있다. 검사·모달 hydrate에는 반드시 `?readOnly=1`을 사용한다.
- 기존 영상 MID 변경·삭제는 일반 `/api/videos`에서 계속 409로 차단한다. 구현된 수정 모드는 운영 POST 없이 버전된 초안을 다운로드하고, 실제 적용은 이중 확인·서버 정지·확정 백업 hash·4-store readback·실패 롤백을 강제한다. 참조가 남은 삭제는 자동 거부한다.
- watch `updatedAt`의 32비트 절단은 제거됐고 서버 수신 교정도 추가됐다. 관련 정규화나 병합을 바꿀 때 millisecond wire 회귀 검사를 함께 갱신한다.
- `/api/kollus/lms-callback`은 `KOLLUS_CALLBACK_SECRET`이 비어 있으면 403으로 fail-closed하며, 설정된 secret 또는 서명 토큰을 검증한다. 운영에서는 secret 설정과 `verify_kollus_callback_auth.py` 검사를 유지한다.
- 학생 review fixture는 현행 done-only chooser와 맞춰져 있다. 전체 green 보고 전에는 기본 safety suite를 현재 작업 트리에서 다시 실행한다.
- 오래된 손상 문자열은 표시·미래 저장만 좁게 수리하고 다른 필드를 지우지 않는다.
- 직접 제공되는 legacy static 파일은 참조가 없다는 이유만으로 삭제하지 않는다.
- 테스트 카탈로그와 답지 맵은 함께 움직인다.
- 공개 두 도메인은 같은 앱이지만 localStorage가 공유되지 않는다.
- 과거 백업 어디에도 없는 시험 성적은 코드로 복구할 수 없다. 외부 원본이 필요하다.

## 20. 변경 절차

1. `git status --short`로 기존 변경을 분리한다.
2. 이 문서에서 해당 기능의 원본·우선순위·검증 표를 읽는다.
3. 대상 폴더의 `AGENTS.md`를 읽는다.
4. 데이터 migration/bulk repair면 먼저 runtime backup을 만든다.
5. 최소 범위로 수정하고 상태 전이·응답 shape를 보존한다.
6. 좁은 unit/source test → 전체 safety suite → 필요한 live/browser 순으로 검증한다.
7. 주요 runtime 파일의 전후 해시 또는 명시적 변경 내역을 확인한다.
8. 같은 패치에서 이 기준서와 인수인계를 갱신한다.
9. Git에는 검증된 코드·문서만 명시적 경로로 올리고 운영 데이터는 제외한다.

## 21. 향후 OCR용 카탈로그 메타데이터와 비학생 연구 경계

- 시험 정의는 회차 키를 가진 `answerModes` 객체를 소유한다. 각 배열 길이는 `problems`와 같아야 하며 값은 `choice_number`, `answer_value`, `manual_review` 중 하나다.
- 문항 유형은 정답값에서 추론하지 않는다. 관리 화면의 명시적 선택 또는 Drive 원본 해설지의 객관식 원문 표기처럼 검증 가능한 근거만 사용한다.
- `answerModes`와 `answerLinkStatus`는 학생에게 공개 가능한 형식/연결상태 메타데이터다. 외부 네트워크의 `/api/tests-config`에도 남기되 `answerKey`, `answerKeys`, 답지 URL과 solution 메타데이터는 계속 제거한다.
- 테스트 관리 저장은 현재 회차의 `answerModes[round]`와 `answerKeys[round]`만 갱신하고 다른 회차 및 알 수 없는 필드를 보존한다.
- `answerModes`와 단답 정규화 코드는 카탈로그 관리·오프라인 연구용 메타데이터다. 현재 학생 UI나 학생 API는 이를 OCR 검수·제출에 사용하지 않는다.
- 비학생 OCR은 `/api/internal/non-student-ocr/review-cache`의 비활성 기본·내부 토큰 경계만 사용하며 `tests.json`, 로그, 진도, 학생 화면에 쓰지 않는다.
- `choice_number`와 `answer_value` 정규화는 오프라인 검증 자료로만 유지한다. 학생 제출 채점 권한이나 자동 기록 생성을 의미하지 않는다.
- 향후 학생 OCR/제출을 도입할 때는 기존 코드를 되살리지 말고 UI·인증·채점·저장 트랜잭션·데이터 이관·회귀 검증을 새 기능으로 설계한다.
- UNIT 전체 유형 마이그레이션은 Drive 해설 PDF별 근거 JSON이 카탈로그 전체를 덮을 때만 허용한다. live `tests-config.json` 쓰기 전 `scripts/backup_runtime_data.py` 백업과 `--backup-confirmed`가 필요하다.

최소 검증:

```powershell
python scripts/verify_test_answer_modes.py
python scripts/verify_unit_answer_link_map_safety.py
node --check static/js/tests.js
node --check static/js/student.js
```
