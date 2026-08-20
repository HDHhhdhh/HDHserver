# 학원 운영 허브 — 전체 기능 및 주요 로직 기준서

**기준일:** 2026-08-14
**기준 브랜치:** `codex/apple-clean-redesign`
**기준 커밋:** `d7cb5d4` 이후 현재 작업 트리
**목적:** 기능 패치·장애 점검·코드 리뷰 때 세션을 다시 읽거나 로직을 매번 역추적하지 않도록 현재 계약을 한곳에 고정한다.

이 문서는 동작 설명서다. 작업 방법과 데이터 안전 규칙은 루트 및 하위 `AGENTS.md`가 우선한다.

## 1. 시스템 한 문장 정의

이 저장소는 학생 명단, 출결, 오늘 순서, 수업·숙제 기록, 영상 배정과 시청 진도, 시험 배정·채점·성적, 보강, 공지, 학사 일정, 자료 파일을 함께 운영하는 Flask 기반 학원 운영 허브다. 홍보 사이트나 범용 SaaS가 아니며 저장소 옆의 JSON·SQLite가 실제 운영 데이터다.

## 2. 현재 구조와 요청 경로

```text
학생/관리자 브라우저
  ├─ 공개: 5a-math.com, app.5a-math.com
  │    └─ Cloudflare Tunnel → localhost:8003
  └─ 학원 LAN: 서버 IP:8003
       └─ Waitress → Flask app.py → 16개 Blueprint → 정적 HTML/JS 또는 JSON API
```

- 프런트 빌드 시스템과 Jinja 템플릿 트리는 없다. `static/`의 HTML과 네이티브 JavaScript를 Flask가 직접 제공한다.
- 두 공개 도메인은 같은 로그인 앱을 가리키는 별칭이다. 서로 리디렉션하지 않으며 브라우저 저장소는 origin별로 분리된다.
- 공개 두 호스트의 HTTP는 308로 같은 경로·쿼리의 HTTPS로 이동한다. 학원 LAN의 HTTP는 유지한다.
- Cloudflare의 `CF-Visitor.scheme`, 일반 프록시의 `X-Forwarded-Proto`, 클라이언트 IP 헤더는 loopback, Cloudflare 대역 또는 명시한 `TRUSTED_PROXY_CIDRS`에서 온 요청에만 신뢰한다.
- PWA·서비스워커·별도 학생 앱 배포물은 2026-08-13에 의도적으로 제거됐다. 현재 학생 화면은 기존 정적 학생 페이지다.
- 과거 브라우저에 `5a-math.com → app.5a-math.com/app` 영구 전환이나 학생 PWA가 남아 있으면 `/app` 정리 화면이 해당 origin의 서비스워커·Cache Storage를 제거하고 캐시 우회 쿼리로 `5a-math.com`에 복귀시킨다. 복귀 응답은 네트워크 캐시만 지우며 로그인용 `localStorage`는 보존한다.

## 3. 사용자, 인증, 네트워크 경계

| 표면 | 인증·접근 | 핵심 계약 |
|---|---|---|
| 학생 로그인 `/` | 이름/계정 로그인 후 30일 JWT | `AUTH_SECRET`이 재시작 후에도 같아야 자동 로그인이 유지된다. |
| 학생 `/student/<sid>` | 학생 JWT 흐름과 sid | bootstrap의 `assignedTests`는 항상 최상위 배열이다. |
| 학생 시험 `/student-test/<sid>` | 학생 흐름 | 답지·정답 데이터는 학원 네트워크에서만 노출한다. |
| 관리자 페이지군 | 학원망 + HTTP Basic | 학원망 밖에서는 403으로 닫히며, 내부에서도 `ACADEMY_ADMIN_USERNAME`, `ACADEMY_ADMIN_PASSWORD_HASH`가 없거나 인증이 틀리면 401로 닫힌다. |
| 영상 재생 URL | 학원 네트워크 | `/api/get-url`에서 실제 클라이언트 IP를 검증한다. |
| 답지 맵 | 학원 네트워크 | `/js/test_answer_link_map.json` 직접 접근도 차단한다. |
| 쓰기 API | 동일 origin | POST/PUT/PATCH/DELETE의 Origin·Referer가 현재 Host와 다르면 403이다. |
| 데모 | `/demo/rh3123/*` | 데모 bootstrap이 fetch와 저장을 가로채며 실서버 쓰기를 만들면 안 된다. |

학생 계정은 `auth_accounts.json`의 호환 데이터를 사용한다. 학생 이름과 운영 마스터 비밀번호 `159846` 조합은 학생이 실제 로그인 ID나 비밀번호를 바꾼 뒤에도 해당 이름의 현재 계정으로 로그인할 수 있다. 이 경로는 계정 ID와 비밀번호 해시를 바꾸지 않으며, 이름이 아닌 변경된 계정 ID에는 적용되지 않는다. 런처는 Machine 범위의 `AUTH_SECRET`을 우선하고 예약 작업 사용자 범위를 fallback으로 사용한다. 값이 없거나 기본 placeholder면 운영 Waitress가 기동하지 않는 것이 정상이다.

## 4. 화면 지도

| 경로 | 역할 | 주요 코드 |
|---|---|---|
| `/` | 학생 로그인 | `static/main.html`, 인증 JS |
| `/admin`, `/dh1130` | 날짜별 관리자 운영판 | `static/admin.html`, `static/js/admin/` |
| 관리자 학생 툴팁 | 학생 이름·출석·학교 정보 표시; 이름 옆 난이도 배지(상·중상·중·하)는 표시하지 않음 | `static/js/admin/features/hoverTooltip.js` |
| `/students` | 전체 학생 명단·미니 진도·내보내기 | `static/all.html`, `static/js/all/` |
| `/student/<sid>` | 학생 영상·시험·숙제/수업 정보 | `static/student.html`, `static/js/student.js` |
| `/student-test/<sid>` | 시험 응시·제출 | `static/student-test.html`, `static/js/student-test.js` |
| `/video-manage` | 영상 카탈로그 관리 | 영상 관리 HTML/JS |
| `/tests` | 시험 카탈로그·기록·통계 | `static/tests.html`, `static/js/tests.js` |
| `/school-cal` | 학교 일정 | 학교 캘린더 HTML/JS |
| `/file-manage` | 자료 폴더·파일 관리 | 파일 관리 HTML/JS |
| `/demo/rh3123/*` | 관리자 기능 데모 | `static/js/admin/demo/` |

`static/student copy.html`, `static/js/student copy.js` 같은 legacy 직접 제공 파일도 외부 수동 사용 여부가 확인되기 전에는 삭제하지 않는다. 학생 시청 동기화 패치는 현재 학생 파일과 이 legacy 사본을 함께 유지한다.

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
5. 영상 자동 배정은 허용된 운영 사건에서만 일어나며 조회·모달 열기만으로 배정하지 않는다.
6. 학생 시청은 `watch.json`에 위치·길이·완료·시각을 저장하고 자동 상태를 `progress.json`에 투영한다.
7. 시험 제출은 시험 기록과 학생 로그/진도에 함께 반영한다.
8. 완료·하원·숙검하원은 서로 다른 정책이다. 상태 변경이 없는 버튼을 상태 완료와 혼동하지 않는다.

## 7. 출결·오늘 순서·보강

- 출석, 결석, 도착 시각, 연락 상태는 각각 `attendance.json`, `absent.json`, `arrive_time.json`, `contact.json` 계열 API가 담당한다.
- 보강은 `extra_attend.json`, 주말 시간은 `weekend_slots.json`, 보강 이월은 전용 carryover API가 담당한다.
- 오늘 순서의 실제 live API는 `data/today_order.json`을 사용한다. 루트 `today_order.json`과 자동으로 동일하다고 가정하지 않는다.
- 오늘표의 완료는 수업 로그의 `done`과 연결되지만 결석·출석·하원 버튼의 의미와 동일하지 않다.
- “숙검하원”은 오후 6시 전 연강 학생을 제외하고, 오후 6시 이후에는 포함한다. 자습 학생은 포함한다.
- 연강/보강/주말 slot 배열은 기존 문자열 sid와 다중 slot 호환을 유지한다.

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

### 배정 유형

| 유형 | 의미 | 주의 |
|---|---|---|
| 일반/수동 | 관리자가 학생·날짜에 지정 | 기존 수동 선택을 자동 로직이 덮어쓰지 않는다. |
| 자동 | 정상 수업 흐름에서 과정에 맞춰 지정 | 날짜 전환, 보강 추가, 허용된 연강/등원 사건에서만 실행한다. |
| 자습 `selfStudy` | 자습용 지정 | 일반 자동 배정과 분리한다. |
| 이전 영상 복습 `review` | 과거 시청 영상을 학생이 다시 등록 | 기록은 상담/운영 로그에 남고 등록 취소와 이력 삭제는 다르다. |
| 트레이닝팩 | 본 과정 외 보조 영상 | 본 과정 자동 배정으로 취급하지 않는다. |
| 추가 영상 | 관리자가 별도 지정 | 일반 자동 선택 스냅샷을 침범하지 않는다. |

### 자동 배정 불변식

- 영상 모달 열기, 조회, 복습 완료 확인만으로 자동 재선택하지 않는다.
- 선택 날짜가 실제 오늘이 아닐 때 오늘용 자동 쓰기를 만들지 않는다.
- 수동 흰색(`none`), `skip`, 완료, 자습, 복습 및 기존 수동 선택을 보존한다.
- 빨강/skip으로 제외한 영상은 연강 2회 배정에서도 다시 선택하지 않는다.
- 연강 ×2는 같은 제외 집합과 과정 조건을 두 슬롯 모두에 적용한다.
- 배정 스냅샷을 보존해 단순 새로고침이 다른 영상으로 바뀌지 않게 한다.

### 복습과 트레이닝팩

- 학생 복습 후보는 이전에 실제로 본 완료/중단 영상 중 현재 과정·허용 범위만 포함한다.
- 미시청, 다른 과정, skip 영상은 복습 후보가 아니다.
- 자습 학생은 복습을 쓸 수 있지만 결석 또는 학원 외 네트워크에서는 등록/재생이 제한된다.
- 트레이닝팩은 학생의 본 과정으로 자동 편입하지 않는다. 과정이 맞고 난이도가 중/하인 보조 영상을 선택하는 별도 흐름이다.

## 10. 시청 기록과 진도 상태

### 원본과 필드

`watch.json`의 날짜/sid/mid 레코드는 다음 필드를 가진다.

| 필드 | 의미 | 병합 |
|---|---|---|
| `last` | 가장 멀리 본 초 위치 | 큰 값 유지 |
| `dur` | 영상 길이(초) | 큰 값 유지 |
| `completed` | 완료 여부 | 한 번 true면 자동 replay가 false로 내리지 않음 |
| `updatedAt` | JavaScript epoch milliseconds | 최신 유효 밀리초 유지 |

- `updatedAt`은 13자리 밀리초가 계약이다. 2000-01-01 이전으로 해석되는 10자리 초/32비트 절단 값은 누락으로 정규화하고 다음 저장에서 서버 밀리초로 다시 찍는다.
- 프런트에서는 시각에 비트 연산자 `| 0`을 절대 사용하지 않는다.
- 5% 이상 시청은 자동 `interrupted`, 90% 이상 또는 완료 이벤트는 자동 `done`이다.
- 길이를 모르는 상태에서 위치가 0보다 크면 시작으로 본다.
- `progress.json`은 화면 상태의 권위 원본이며, 같은 날짜/mid의 watch보다 우선한다.
- 과거 `done` 후 나중에 재생한 `interrupted`는 완료 이력을 자동 취소하지 않는다.

### 수동/자동 우선순위

1. 명시적 수동 상태와 `__manualProgressMids`
2. 기존 자동 상태와 `__autoWatchProgressMids`
3. 새 watch 자동 투영
4. 비어 있는 기본값

자동 업데이트는 수동 흰색(`none`), 수동 `skip`, 수동 `interrupted`를 덮지 않는다. 자동 `interrupted`는 자동 `done`으로 올라갈 수 있다. 자동 빈 값은 자동 미완료를 지울 수 있지만 완료를 내리지 않는다.

## 11. 시험·채점·답지

- 카탈로그 원본은 `tests-config.json`, 제출/성적 기록은 `tests.json`과 로그/진도 연계 데이터다.
- `/api/tests-config`의 전체 저장은 기존 시험의 암묵적 삭제를 409로 거부한다. 삭제는 명시적 ID 목록으로 요청한다.
- 기존 키, `sourceFiles`, 답지 메타데이터를 보존한다.
- `REVIEW`, `SCHOOL_PAST`는 `sourceFiles.solutionFileId` 또는 동등 메타데이터를 유지한다.
- `UNIT` 답지는 Drive 설명 파일에서 생성한 `static/js/test_answer_link_map.json`과 동기화한다.
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
- OCR review는 인식·검토 단계이고 `submit-test`는 실제 제출 단계다. 검토만으로 성적을 만들지 않는다.
- 제출은 시험 기록, 학생 로그, 진도의 round/assignment 일치를 함께 검증한다.
- 외부 네트워크 응답에서는 답지 URL, solution/answer 필드와 정답 키를 제거한다.

## 12. 메모·운영 이력의 분리

| 기능 | 저장/의미 | 섞으면 안 되는 것 |
|---|---|---|
| 조교 학생 메모 | SQLite 기반 thread, 작성일·작성자·색상, 편집/삭제/핀/리마인더/완료 | 수업 로그 메모, 상담 CSV |
| 관리자 운영 노트 | 관리자 화면 운영 메모 | 학생별 조교 메모 |
| 학생 운영 로그 | 학생 관련 사건 이력, 개별/전체 삭제 | 수업 로그, 브라우저 localStorage |
| 복습 영상 이력 | 등록/취소 사건을 남김 | 현재 배정 존재 여부 |

확인일 메모 카드는 `[상태] 작성일 → 확인일`을 단독 행으로 유지하고, 다음 행의 왼쪽에는 작성자·핀, 오른쪽 끝에는 `수정 · 삭제`를 배치하며 메모 내용은 그 아래 행에서 시작한다. 날짜와 작업 버튼은 같은 가로 영역에서 겹치면 안 된다.

조교 메모는 고정·확인일 우선순위를 유지하되 같은 우선순위 안에서는 `created_at DESC, id DESC`로 최신 작성 메모를 위에 표시하고, 목록을 열거나 새 메모를 등록한 뒤에도 맨 위를 보여준다.

삭제·완료·핀·리마인더는 각각 다른 상태 변화다. UI에서 한 동작을 다른 저장소의 삭제로 확대하지 않는다.

## 13. 공지·설문·캘린더·자료

- 공지는 목록/작성/수정/삭제, 이미지 업로드/다운로드 소스, 확인, 답글·설문 제출을 지원한다.
- 학교 일정은 `school_calendar.json`과 캘린더 API가 담당하며 sheet/import 작업은 기존 학교·학기 키를 merge한다.
- 자료는 `materials`, `mat-assign`, `files/`와 파일 API가 담당한다.
- 파일 API는 tree, folder, rename, move, delete, upload, page-folders를 제공한다. 경로는 항상 `FILES_ROOT` 아래로 검증한다.
- 보강 이월과 시트 동기화는 전용 API다. 대량 적용 전 런타임 백업이 필요하다.
- 비학생 OCR review cache는 내부 API이며 실제 시험 제출과 분리한다.

## 14. 주요 데이터 원본

| 데이터 | 주 원본 | 비고 |
|---|---|---|
| 학생 | `students.json` | 알 수 없는 학생 필드 보존 |
| 영상 카탈로그 | `videos.json` | mid 안정성, 색/skip 제외 |
| 날짜별 배정 | `updates.json` | 일반·자습·복습·트레이닝팩 구분 |
| 화면 진도 상태 | `progress.json` | 수동/자동 메타키 포함 |
| 시청 위치 | `watch.json` | 밀리초 `updatedAt` |
| 수업·숙제 로그 | SQLite `app.sqlite` + `logs.json` | SQLite 우선, JSON 결손 보충 |
| 시험 카탈로그 | `tests-config.json` | 암묵 삭제 금지 |
| 시험 결과 | `tests.json` | 제출·점수·오답 |
| 출결 계열 | `attendance.json`, `absent.json`, `arrive_time.json`, `contact.json` | 날짜/sid 부분 갱신 |
| 보강 | `extra_attend.json`, `weekend_slots.json` | carryover 별도 |
| 오늘 순서 | `data/today_order.json` | 루트 동명 파일과 혼동 금지 |
| 학사 일정 | `school_calendar.json` | import merge |
| 학생 계정 | `auth_accounts.json` | JWT 비밀키와 별개 |
| 메모·운영 로그 | `app.sqlite` 내 분리 테이블 | 서로 다른 repository/route |
| 업로드 | `files/` | Git 코드와 분리한 운영 자료 |

`app.sqlite-wal`, `app.sqlite-shm`, `data/`, `files/`, `_data_mirror/`, `_runtime_backups/`, root `*.tmp`도 런타임 데이터다.

## 15. API 그룹

- 기본 데이터: `/api/students`, `/api/videos`, `/api/updates`, `/api/progress`, `/api/materials`, `/api/school-calendar`
- 부분 갱신: `/api/update`, `/api/updates/patch`, `/api/progress/patch`
- 영상 유형: `/api/updates/self-study`, `/api/updates/review`, `/api/updates/training-pack`
- 학생 통합 읽기: `/api/student/bootstrap`
- 시청: `/api/watch`, `/api/watch/latest`, `/api/watch-status`, `/api/get-url`, Kollus callback
- 로그: `/api/logs`, `/api/logs/patch`, `/api/logs/entry`, 미보관 요약, 숙제 교재
- 시험: `/api/tests-config`, `/api/tests-records`, `/api/tests-stats`, OCR review, `/api/submit-test`
- 출결: attendance, attend, today, absent, arrive-time, contact
- 오늘 순서·보강: today_order patch, extra-attend, weekend-slots, makeup-carryover, sheet-sync
- 인증: `/api/auth/login`, `me`, `switch`, `change`
- 메모·이력: assistant-student-notes, admin-operation-notes, student-logs
- 공지: announcements, image, ack, submit
- 파일: `/api/fs/*`, `/files/<path>`
- 내부: non-student OCR review cache

엔드포인트 URL, payload 키, 응답 shape는 전용 마이그레이션 없이 바꾸지 않는다.

## 16. 코드의 기준 위치

| 로직 | 기준 위치 |
|---|---|
| 앱 조립·HTTPS·CSRF·답지 gate | `app.py` |
| 네트워크/답지 strip | `core/network_access.py` |
| 로그 병합 규칙 | `core/log_rules.py` |
| 로그 저장소 | `core/log_repository.py` |
| 시청/진도 상태 전이 | `core/progress_rules.py` |
| 학생 복습 후보 | `core/video_review_rules.py` |
| 원자 JSON 저장 | `core/storage.py` |
| 광범위 API/자동 배정 | `routes/api_basic.py` |
| 시청 API | `routes/api_watch.py` |
| 시험 | `routes/api_tests.py` |
| 관리자 날짜 | `static/js/admin/core/adminDate.js` |
| 관리자 하루 hydrate/render | `static/js/admin/features/today.js` |
| 학생 bootstrap/시청 | `static/js/student.js` |
| 공통 API | `static/js/shared/api.js` |
| 회귀 허브 | `scripts/verify_refactor_safety.py` |

## 17. 영역별 패치 점검표

| 변경 영역 | 반드시 확인할 것 | 최소 검증 |
|---|---|---|
| 관리자 UI | 선택 날짜, 행 `data-date`, Korean UTF-8, modal scroll | `node --check` + DOM/API + screenshot |
| 로그/숙제 | SQLite/JSON 양쪽, 빈 값 보존, manual white reload | 관련 unit + 양쪽 endpoint + 브라우저 |
| 영상 자동 배정 | 오늘 제한, 수동/skip 보존, 연강 ×2, snapshot | assignment/reconcile unit |
| 학생 시청 | 5%/90%, replay done, 밀리초 시각, 외부 gate | progress/watch unit + 학생 JS syntax |
| 시험 | top-level `assignedTests`, status, 답지 우선순위, config 삭제 안전 | submit/bootstrap/config 검증 |
| 출결/오늘 순서 | 문자열 sid, 선택 날짜, `data/today_order.json` | route unit + 해당 화면 |
| 인증/프록시 | Basic fail-closed, AUTH_SECRET 지속, 신뢰 프록시, HTTPS loop 없음 | admin/auth/proxy 검증 + 실제 HTTP/HTTPS |
| 파일 | 경로 탈출 방지, 업로드/이동 참조 | file route 검증 |
| 데모 | 모든 write가 sandbox에 머무는지 | demo behavior 검증 |

공통 명령:

```powershell
python -m compileall -q app.py routes core scripts
node --check static/js/student.js
python scripts/verify_refactor_safety.py
python scripts/verify_academy_proxy_network_access.py
python scripts/verify_refactor_safety.py --smoke
```

`--smoke`는 live app import와 WAL/SHM 변화를 허용하므로 순수 단위 검증과 다르다. UI 변경은 reload 후 DOM/API를 먼저 확인하고 레이아웃 변경이면 screenshot까지 확인한다.

## 18. 운영·배포 계약

- Waitress는 Windows 예약 작업 `Academy Server Waitress`로 8003 포트를 연다.
- 공개 도메인은 Cloudflare Tunnel이 localhost:8003으로 전달한다.
- 현재 공개 HTTP는 앱에서 HTTPS로 308 전환한다.
- Waitress와 tunnel의 로그온 종속 여부를 별도 확인한다. 사용자 로그아웃 후에도 운영해야 하면 둘 다 관리자 권한의 Windows service 또는 비대화형 작업으로 옮겨야 한다.
- Cloudflare tunnel 서비스화는 자격 증명/config를 LocalSystem이 읽을 수 있는 위치로 옮기고 관리자 권한으로 설치·검증해야 한다. 코드 패치만으로 끝나는 작업이 아니다.
- 코드 배포 전 `python scripts/backup_runtime_data.py`로 운영 데이터를 백업한다.
- 재시작 후 listener, task result, HTTP→HTTPS, HTTPS login, 학생 bootstrap, 학원/외부 gate를 확인한다.
- 검증을 위해 띄운 임시 서버는 종료한다.

## 19. 알려진 호환성과 위험

- 로그는 SQLite와 JSON 이중 경로다. 한쪽만 고치면 누락 또는 회귀가 생긴다.
- `progress.json`은 크고 날짜/sid keyed다. 프런트 전체 파일 교체를 하지 않는다.
- 학생 bootstrap GET과 일부 GET은 보장/마이그레이션 쓰기를 할 수 있다.
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

## 21. OCR 문항 유형 및 단답 검수 계약

- 시험 정의는 회차 키를 가진 `answerModes` 객체를 소유한다. 각 배열 길이는 `problems`와 같아야 하며 값은 `choice_number`, `answer_value`, `manual_review` 중 하나다.
- 문항 유형은 정답값에서 추론하지 않는다. 관리 화면의 명시적 선택 또는 Drive 원본 해설지의 객관식 원문 표기처럼 검증 가능한 근거만 사용한다.
- `answerModes`와 `answerLinkStatus`는 학생에게 공개 가능한 형식/연결상태 메타데이터다. 외부 네트워크의 `/api/tests-config`에도 남기되 `answerKey`, `answerKeys`, 답지 URL과 solution 메타데이터는 계속 제거한다.
- 테스트 관리 저장은 현재 회차의 `answerModes[round]`와 `answerKeys[round]`만 갱신하고 다른 회차 및 알 수 없는 필드를 보존한다.
- OCR 검수는 20문항 전체 유형표가 있는 UNIT/트레이닝팩 시험에서만 활성화한다. 서버는 카탈로그 유형을 OCR 정책에 주입하고 응답의 각 항목에 `answer_mode`를 붙인다.
- 클라이언트는 카탈로그 유형과 서버 제공 유형이 모두 있으면 일치 여부를 검사한다. `manual_review`는 자동 채움하지 않고 학생 직접 확인 단계로 보낸다.
- `choice_number`는 1~5만 허용한다. 학생 OCR 검수의 `answer_value` 형식 확인 범위는 짧은 정수·소수·분수, 최대 두 개의 제곱근 항과 한 개의 덧셈/뺄셈 연산이다. 문자식이나 범위를 벗어난 식은 자동 채움하지 않는다.
- OCR lab 안전 경계상 이 작업은 `/api/submit-test`를 수정하거나 호출하지 않는다. 실제 제출 채점은 기존의 정확한 문자열 비교를 유지하며, 단답식 정규화 연결은 별도 승인·검증 작업으로 남긴다.
- UNIT 전체 유형 마이그레이션은 Drive 해설 PDF별 근거 JSON이 카탈로그 전체를 덮을 때만 허용한다. live `tests-config.json` 쓰기 전 `scripts/backup_runtime_data.py` 백업과 `--backup-confirmed`가 필요하다.

최소 검증:

```powershell
python scripts/verify_test_answer_modes.py
python scripts/verify_unit_answer_link_map_safety.py
node --check static/js/tests.js
node --check static/js/student.js
```
