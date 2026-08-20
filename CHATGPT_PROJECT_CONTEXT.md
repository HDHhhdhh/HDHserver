# 학원 운영 허브 — ChatGPT 프로젝트 컨텍스트

> 대상: ChatGPT 5.6 Pro의 `학원 운영 허브` 세션
> 기준일: 2026-08-13
> 저장소: `C:\server`
> 기준 브랜치/커밋: `codex/apple-clean-redesign` / `d7cb5d4` 이후 현재 작업 트리
> 현재 기능·상태 전이 정본: `docs/PROJECT_FUNCTIONS_AND_LOGIC.md`
> 최근 이슈·변화 감사: `docs/SESSION_AUDIT_2026-07-30_2026-08-13.md`
> 주의: 실제 파일, `AGENTS.md`, 위 정본 문서가 이 확장 컨텍스트보다 우선한다.

## 0. ChatGPT에 이 문서를 주는 방법

ChatGPT 웹 세션은 이 PC의 `C:\server`를 자동으로 읽을 수 없다. 새 세션에는 이 문서를 파일로 첨부하고, 아래의 **세션 시작 메시지**를 함께 보낸다.

실제 코드 수정이나 정밀 진단을 요청할 때는 관련 파일과 해당 폴더의 `AGENTS.md`도 추가로 첨부한다. 학생 이름, 연락처, 성적, 상담 내용 등 실제 운영 데이터는 꼭 필요한 범위만 공유하고 가능하면 비식별화한다.

### 세션 시작 메시지

```text
첨부한 문서는 현재 C:\server에서 운영하는 “학원 운영 허브” 프로젝트의 기준 컨텍스트다.

이 프로젝트를 단순 웹사이트가 아니라 실제 학원 운영 데이터를 다루는 로컬 운영 시스템으로 이해해줘. 앞으로 답변할 때 다음 원칙을 지켜줘.

1. 코드와 운영 데이터를 명확히 구분한다.
2. students.json, progress.json, logs.json, app.sqlite 등 운영 데이터는 내가 명시적으로 요청하지 않는 한 초기화·전체 덮어쓰기·삭제 대상으로 제안하지 않는다.
3. 변경안은 기존 Flask + 정적 HTML/CSS/네이티브 ES 모듈 구조를 유지하는 작은 수정으로 제안한다.
4. 관리자 화면의 선택 날짜와 실제 오늘 날짜를 혼동하지 않는다.
5. 로그는 SQLite와 logs.json 호환성이 모두 중요하고, 학생 bootstrap 응답의 assignedTests는 최상위 배열이어야 한다.
6. 영상/답지의 학원 네트워크 제한과 데모 화면의 실서버 쓰기 차단을 유지한다.
7. 확실하지 않은 현재 상태, 데이터 구조, 배포 환경은 추측하지 말고 필요한 파일이나 확인 명령을 요청한다.
8. 답변은 한국어로 하고, 수정 제안에는 영향 파일·데이터 위험·검증 방법을 함께 적는다.

먼저 이 시스템의 역할과 주요 운영 흐름을 10줄 이내로 요약해서 이해한 내용을 확인해줘.
```

---

## 1. 한 문장 정의

`server`는 학생 명단, 출결, 수업 기록, 숙제, 영상 배정과 시청 진도, 시험 배정·채점·성적, 보강, 공지, 학사 일정, 자료 파일을 한곳에서 관리하는 **학원용 로컬 운영 허브**다.

홍보 사이트나 범용 SaaS가 아니다. 원장·강사·학생이 실제 수업일에 사용하는 운영 시스템이며, 코드 저장소 안에 현재 운영 데이터도 함께 존재한다.

## 2. 시스템의 사용자와 역할

### 관리자·강사

- 학생 명단과 반/과정 정보를 관리한다.
- 날짜별 출석, 결석, 보강, 도착 시간, 연락 상태를 확인하고 수정한다.
- 학생별 수업 기록, 숙제 범위, 메모, 완료 상태를 기록한다.
- 강의 영상을 배정하고 학생별 진도를 확인·보정한다.
- 시험을 배정하고 제출 결과, 오답, 점수와 통계를 확인한다.
- 학교 일정, 공지, 자료 파일과 오늘의 학생 순서를 관리한다.
- 학생별 보조 메모를 별도 저장소에 기록한다.

### 학생

- 개인 주소 `/student/<sid>` 또는 `/student-test/<sid>`로 자신의 페이지를 연다.
- 오늘 배정된 영상, 숙제, 시험과 공지를 확인한다.
- 허용된 네트워크에서 영상을 재생하고 답지 링크를 연다.
- 시험 답안을 입력하거나 지원되는 흐름에서 답안지 사진 OCR을 사용한 뒤 결과를 확인·제출한다.

### 데모 사용자

- `/demo/rh3123` 계열 화면에서 관리자 기능을 체험한다.
- 데모용 fetch/store/navigation 계층이 실서버 API 쓰기를 막아야 한다.
- 데모 데이터와 실제 학생 데이터가 섞이면 안 된다.

## 3. 기술 구조

### 백엔드

- Python과 Flask 기반이다.
- `app.py:create_app()`이 앱을 만들고 페이지 및 API Blueprint를 등록한다.
- 운영 서버는 Waitress가 `app:app`을 로드하는 구조다.
- API는 `routes/` 아래 기능별 Blueprint로 나뉜다.
- 핵심 규칙, 저장, 저장소, 네트워크 판정은 `core/`에 있다.

### 프런트엔드

- 별도 React/Vue 빌드 시스템이 없다.
- `static/`의 HTML, CSS, JavaScript가 Flask에서 직접 제공된다.
- 관리자 기능은 `static/js/admin/`의 네이티브 ES 모듈로 구성된다.
- 전체 학생 화면은 `static/js/all/`, 공통 API·검색·달력·자습 도우미는 `static/js/shared/`에 있다.
- 학생 페이지는 큰 단일 진입점인 `static/js/student.js`와 시험 관련 스크립트를 함께 사용한다.

### 저장 계층

- 다수의 JSON 파일이 `C:\server` 루트에 존재한다.
- `app.sqlite`는 수업 로그의 주 저장소와 보조 학생 메모 등에 사용된다.
- 수업 로그는 SQLite 우선이지만 `logs.json` 호환 읽기·쓰기도 중요하다.
- JSON 저장은 가능한 한 잠금과 `save_atomic()`을 거쳐 원자적으로 수행한다.
- `_data_mirror/`, `_runtime_backups/` 등에는 복구용 미러나 백업이 생길 수 있다.

### 전체 흐름

```text
관리자/학생 브라우저
        ↓
static HTML·CSS·JavaScript
        ↓ JSON API
Flask app.py + routes/*
        ↓
core 규칙·저장소·네트워크 판정
        ↓
루트 JSON 파일 + app.sqlite + files/
        ↓
미러·스냅샷·운영 백업
```

## 4. 주요 화면

| 주소 | 역할 | 주요 파일 |
|---|---|---|
| `/` | 기본 진입 화면 | `static/index.html` |
| `/admin` | 관리자 운영 보드 | `static/admin.html`, `static/js/admin/` |
| `/students` | 전체 학생 명단·조회 | `static/all.html`, `static/js/all/` |
| `/student/<sid>` | 학생 개인 페이지 | `static/student.html`, `static/js/student.js` |
| `/student-test/<sid>` | 학생 시험 진입 | 학생 페이지 셸 재사용 |
| `/video-manage` | 영상 자료·배정 관리 | `static/video-manage.html` |
| `/school-cal` | 학교·학사 일정 관리 | `static/school-cal.html` |
| `/tests` | 시험 카탈로그·기록 관리 | `static/tests.html`, `static/js/tests.js` |
| `/file-manage` | 자료 폴더·파일 관리 | `static/file-manage.html` |

일부 관리자 및 데모 별칭 주소도 있다. 주소 자체를 인증 수단으로 간주하면 안 되며, 인증·네트워크 제한은 별도 계층에서 판단해야 한다.

## 5. 하루 운영 흐름

### 5.1 서버 시작

1. Windows에서 `실행.bat`를 실행한다.
2. `venv\Scripts\waitress-serve.exe` 존재 여부를 확인한다.
3. `Academy Server Waitress` 예약 작업이 있으면 실행을 요청한다.
4. 예약 작업이 없으면 `scripts/run_waitress_server.ps1`을 숨김 PowerShell 프로세스로 시작한다.
5. 기본 접속 주소 `http://192.168.0.5:8003/`을 연다.

### 5.2 관리자 초기 로드

관리자 앱의 `bootstrap()`은 학생, 영상, 자료, 배정, 출결, 로그, 진도, 학교 일정, 시험 설정 등을 여러 API에서 병렬로 읽어 공용 상태에 넣는다.

중요한 구분:

- 초기 bootstrap의 기준일은 실제 로컬 오늘이다.
- 이후 관리자 업무는 화면에서 선택한 날짜를 기준으로 동작할 수 있다.
- 기능 수정 시 `todayLocalKey()`와 `getAdminDate()`의 의미를 혼동하면 과거 날짜를 수정하거나 오늘 데이터에 잘못 기록할 수 있다.

### 5.3 수업 전

- 오늘 출석 대상과 순서를 확인한다.
- 결석, 보강, 추가 등원, 주말 슬롯을 반영한다.
- 학생별 영상과 시험을 배정한다.
- 학교 일정과 공지를 확인한다.

### 5.4 수업 중

- 도착 시간과 출석 상태를 기록한다.
- 학생별 수업 기록과 숙제 범위를 수정한다.
- 영상 시청 상태가 watch/progress 데이터에 반영된다.
- 필요하면 진도 상태를 수동으로 완료, 중단, 건너뜀 또는 명시적 해제로 보정한다.

### 5.5 학생 사용

학생 페이지는 가능하면 `/api/student/bootstrap` 한 번으로 학생 정보, 영상, 배정, 결석, 로그, 시험 등을 모아 받는다. 이전 호환을 위한 여러 개별 API fallback도 남아 있다.

학생이 시험을 제출하면 채점 결과가 수업 로그와 `tests.json`에 기록될 수 있고, 해당 시험 배정의 완료 상태도 갱신된다.

### 5.6 수업 후

- 수업 완료, 숙제, 메모, 시험 결과가 보존되었는지 확인한다.
- 내보내기나 통계 화면으로 필요한 기록을 확인한다.
- 대량 수정이나 데이터 마이그레이션 전에는 런타임 데이터 백업을 만든다.

## 6. 핵심 데이터 지도

아래 파일은 코드 자산이 아니라 **실제 운영 상태**다. 이름이 비슷한 파일을 새 기본값으로 덮어쓰면 학생 기록이 손실될 수 있다.

| 영역 | 대표 저장소 | 개념적 구조·주의점 |
|---|---|---|
| 학생 명단 | `students.json` | 학생 ID(`sid`)가 다른 데이터의 연결 키다. 삭제는 연쇄 영향을 검토한다. |
| 영상 카탈로그 | `videos.json` | 영상 ID와 과정 정보. 배정·진도와 연결된다. |
| 날짜별 영상 배정 | `updates.json` | 대체로 날짜 → 학생 → 영상 목록. GET 과정에서 오늘 자동 배정이 보정될 수 있다. |
| 영상 진도 | `progress.json` | 대체로 날짜 → 학생 → 영상별 상태. 크기가 매우 크므로 전체 교체를 피한다. |
| 시청 원시 상태 | `watch.json` | 재생·시청 상태와 자동 진도 판정에 사용된다. |
| 수업 로그 | `app.sqlite`, `logs.json` | SQLite 우선 + JSON 호환 구조. 한쪽만 고치면 불일치가 생길 수 있다. |
| 출석·결석 | `attendance.json`, `absent.json` | 날짜·학생·슬롯 정보가 함께 쓰인다. |
| 도착·연락 | `arrive_time.json`, `contact.json` | 출석 화면의 부가 상태다. |
| 보강·추가 등원 | `extra_attend.json`, `weekend_slots.json` | 날짜/학생/슬롯 연결을 보존한다. |
| 학교 일정 | `school_calendar.json` | 관리자 달력과 학생 일정 판정에 사용된다. |
| 오늘 순서 | `data/today_order.json` 중심 | 루트 `today_order.json`과 경로가 통일되지 않은 부분이 있어 확인이 필요하다. |
| 시험 카탈로그 | `tests-config.json` | 시험 정의, 문항 수, 정답, 풀이 파일 메타데이터를 포함할 수 있다. |
| 시험 결과 | `tests.json` 및 수업 로그 | 제출 시 양쪽 기록 경로가 모두 중요하다. |
| 공지 | `announcements.json`, `announce_status.json` | 공지 본문과 학생별 확인 상태다. |
| 학생 보조 메모 | `app.sqlite` | 수업 메모·상담 기록·내보내기와 의도적으로 분리된 저장소다. |
| 자료 파일 | `files/`, `page_folders.json` | 파일 API를 통해 폴더·업로드·이동·삭제를 수행한다. |

실제 구조는 레거시 데이터와 호환 필드 때문에 더 복잡할 수 있다. 변경 전 현재 레코드의 알려지지 않은 필드를 확인하고 그대로 보존한다.

## 7. 반드시 보존할 데이터 규칙

### 7.1 전체 덮어쓰기보다 좁은 병합

- 한 학생·한 날짜·한 항목만 바꿀 때는 PATCH 형태를 우선한다.
- 빈 문자열이나 빈 배열이 기존의 의미 있는 값을 지우지 않도록 한다.
- 명시적 삭제/초기화 필드가 있는 경우에만 값을 지운다.
- 기존 레코드의 알 수 없는 키도 보존한다.

### 7.2 수업 로그의 이중 저장 호환성

- 로그 접근은 `get_log_repository()`와 `LogRepository`를 사용한다.
- SQLite만 또는 `logs.json`만 직접 고치는 방식을 새로 추가하지 않는다.
- 순수 병합·충돌 규칙은 `core/log_rules.py`에 둔다.
- 데이터 복구·학생 교재 조회처럼 파일을 읽는 보정 로직은 route 계층과 분리 여부를 신중히 판단한다.

### 7.3 영상 진도의 수동 상태 우선

- 영상 상태에는 완료, 중단, 건너뜀, 명시적 해제 등의 의미가 있다.
- 수동 `skip`이나 흰색/해제 상태가 자동 watch 업데이트 때문에 되살아나거나 덮이면 안 된다.
- watch와 progress 규칙은 로그 규칙과 별개다.

### 7.4 학생 bootstrap 응답 계약

- `/api/student/bootstrap`의 `assignedTests`는 **최상위 배열**이다.
- 기존 endpoint URL, payload key, 응답 shape를 임의로 바꾸지 않는다.
- 개별 API fallback을 제거하려면 별도의 호환성 계획이 필요하다.

### 7.5 시험 답지와 네트워크 제한

- 영상 재생과 시험 답지는 학원 네트워크 전용이다.
- 외부 접속 시 시험 설정과 학생 bootstrap에서 답지 링크·정답 관련 필드를 제거한다.
- `UNIT` 시험의 답지 링크 맵과 `REVIEW`/`SCHOOL_PAST`의 solution 메타데이터를 시험 카탈로그 변경과 함께 맞춘다.
- 프록시 헤더는 신뢰된 프록시에서 온 경우에만 클라이언트 IP 판정에 사용해야 한다.

### 7.6 GET도 항상 순수 읽기는 아니다

- 로그·보조 메모 GET이 SQLite 스키마 또는 WAL 상태를 만들 수 있다.
- `/api/updates` GET이 오늘 자동 배정을 계산해 `updates.json`을 저장할 수 있다.
- 오늘 학생 bootstrap은 위 두 종류의 변경을 함께 일으킬 수 있다.
- 따라서 라이브 앱 import나 smoke test를 “파일을 전혀 건드리지 않는 조회”로 보면 안 된다.

### 7.7 인코딩

- JSON과 정적 파일은 UTF-8을 유지한다.
- 기존 일부 주석·레거시 텍스트에는 깨진 한글이 남아 있을 수 있다.
- 깨진 텍스트를 `????` 같은 대체 문자열로 저장하거나 정상 한글까지 일괄 변환하지 않는다.

## 8. 서버 실행 방식

### 운영 실행

`scripts/run_waitress_server.ps1`의 기본값:

- listen: `0.0.0.0:8003`
- threads: `16`
- connection limit: `400`
- channel timeout: `60초`
- WSGI target: `app:app`
- 시작 전 8003 포트의 기존 listener 확인
- 데이터 미러 파일별 최대 스냅샷 수: `24`
- 스냅샷 최소 간격: `3600초`

2026-08-13 감사 시점에는 `Academy Server Waitress` 예약 작업과 8003 listener가 실행 중이다. 다만 작업의 로그온 유형이 Interactive이고 cloudflared도 사용자 AppData/HKCU Run에 의존해 사용자가 로그아웃하면 공개 서비스가 멈출 위험이 있다. 무인 운영이 필요하면 관리자 권한으로 둘 다 Windows service 또는 비대화형 service-account 작업으로 전환하고 logout/reboot 생존을 검증한다.

- 관리자 페이지군은 학원망 내부에서만 `ACADEMY_ADMIN_USERNAME`, `ACADEMY_ADMIN_PASSWORD_HASH` 기반 fail-closed Basic 인증을 허용하며, 외부망은 403으로 차단한다.
- 운영 런처는 영구 `AUTH_SECRET`을 Machine 우선, 예약 작업 사용자 범위 fallback으로 읽는다.
- `5a-math.com`과 `app.5a-math.com`은 같은 앱의 별칭이며 cross-domain redirect는 하지 않는다.
- 공개 두 host의 HTTP는 같은 URL의 HTTPS로 308 전환하고 학원 LAN HTTP는 유지한다.
- PWA/별도 학생 앱은 현재 운영 범위에서 제거됐다.

### 개발 실행

```powershell
python app.py
```

이 경로는 Flask 개발 서버를 `0.0.0.0:8003`, debug 모드로 실행한다. 일상 운영에는 Waitress 경로를 우선한다.

### 네트워크·프록시

- 앱은 로컬 사설망과 등록된 학원 공인 주소를 학원 네트워크로 판정한다.
- Cloudflare 프록시 주소와 관련 헤더를 안전하게 해석하는 코드가 있다.
- `TRUST_PROXY_HEADERS`, `TRUSTED_PROXY_CIDRS`, `DB_PATH` 같은 환경 변수가 동작을 바꿀 수 있다.
- forwarded HTTPS와 클라이언트 IP는 신뢰 프록시 peer에서 온 경우에만 인정한다.
- 그러나 터널 프로세스, 도메인, 방화벽, 공유기 포트포워딩 구성은 이 저장소만으로 확정할 수 없다.

## 9. 주요 코드 지도

| 위치 | 책임 |
|---|---|
| `app.py` | Flask 앱 생성, 공개 HTTPS, 쓰기 요청 출처 검사, 학원 전용 답지 파일 차단, Blueprint 등록 |
| `routes/pages.py` | 정적 HTML 화면 주소 |
| `routes/api_basic.py` | 학생·영상·배정·진도·로그·학교 일정·학생 bootstrap 등 넓은 핵심 API |
| `routes/api_attend.py` | 오늘 대상, 출석, 결석, 연락 상태 |
| `routes/api_arrive_time.py` | 도착 시간 |
| `routes/api_watch.py` | 영상 시청과 진도 상태 |
| `routes/api_tests.py` | 시험 설정, OCR, 제출, 기록, 통계 |
| `routes/api_announcements.py` | 공지와 확인/제출 상태 |
| `routes/api_fs.py` | 파일 트리, 업로드, 이동, 이름 변경, 삭제 |
| `routes/api_auth.py` | 로그인과 사용자 전환·변경 |
| `routes/api_makeup_carryover.py` | 보강 이월과 시트 동기화 |
| `routes/api_assistant_notes.py` | 학생별 보조 메모 CRUD |
| `core/paths.py` | 런타임 데이터 경로와 누락 JSON 기본 생성 |
| `core/storage.py` | JSON 로드·원자 저장·미러·스냅샷 |
| `core/log_repository.py` | 수업 로그의 SQLite/JSON 호환 저장소 |
| `core/log_rules.py` | 수업 로그의 순수 병합·충돌 규칙 |
| `core/network_access.py` | 실제 클라이언트 IP, 프록시 신뢰, 학원 네트워크, 답지 필드 제거 |
| `static/js/admin/core/adminDate.js` | 관리자 선택 날짜의 기준 |
| `static/js/admin/core/state.js` | 관리자 초기 상태 bootstrap |
| `static/js/admin/features/today.js` | 날짜별 관리자 화면 로드·렌더·이벤트 조정 |
| `static/js/student.js` | 학생 페이지 초기화와 통합 bootstrap/fallback |
| `scripts/verify_refactor_safety.py` | 프로젝트의 중심 회귀 검증 스크립트 |

각 폴더를 수정하기 전에 그 폴더의 `AGENTS.md`를 읽는다. 하위 `AGENTS.md`의 규칙이 더 구체적이면 그것을 우선한다.

## 10. 변경 작업의 기본 절차

1. 루트 `AGENTS.md`와 대상 폴더의 `AGENTS.md`를 읽는다.
2. `git status --short`로 기존 변경을 기록한다.
3. 코드 변경과 운영 데이터 변경을 분리한다.
4. 변경할 기능의 현재 API shape와 날짜·학생 키를 확인한다.
5. 전체 파일 재작성보다 가장 작은 안전한 수정을 한다.
6. 위험에 맞는 검증을 수행한다.
7. 다시 `git status --short`를 확인하고 코드, 런타임 데이터, 기존 변경을 구분한다.
8. 사용자가 요청한 경우에만 검증된 대상 파일을 명시적 경로로 stage/commit한다.

대량 데이터 수정이나 마이그레이션 전:

```powershell
python scripts/backup_runtime_data.py
```

백업 생성 자체도 파일 쓰기이므로 사용자의 데이터 변경 요청 범위 안에서 실행한다.

## 11. 검증 기준

### 기본 정적·회귀 검사

```powershell
python -m compileall -q app.py routes core scripts
python scripts/verify_refactor_safety.py
node --check <수정한-JavaScript-파일>
```

### 라이브 smoke

```powershell
python scripts/verify_refactor_safety.py --smoke
```

smoke는 앱을 import하고 라이브 저장소의 SQLite WAL/SHM 등에 변화를 만들 수 있다. 순수 단위 테스트와 같지 않다.

### UI 변경

- 관리자 변경 후 `/admin`을 새로고침한다.
- API/DOM으로 정확한 날짜, 학생, 상태를 먼저 확인한다.
- 레이아웃이 바뀌면 실제 브라우저 스크린샷 QA를 추가한다.
- 한국어가 깨지지 않는지 확인한다.
- 검증만 위해 시작한 서버는 작업 후 종료한다.

### 특히 필요한 회귀

- 로그/숙제/진도: 로그 endpoint와 브라우저 회귀를 함께 확인한다.
- 수동 진도 해제 또는 `skip`: 새로고침과 자동 watch 갱신 뒤에도 유지되어야 한다.
- 영상 배정: updates, progress, watch, student bootstrap을 함께 확인한다.
- 학생 시험: progress 기반 상태, 최상위 `assignedTests`, 답지 링크 우선순위, 학원 밖 링크 제거를 확인한다.

## 12. Git과 운영 데이터

- 현재 저장소가 dirty하더라도 기존 변경을 되돌리거나 정리하지 않는다.
- 기능별로 작은 코드 commit을 만든다.
- `students.json`, `progress.json`, `logs.json`, `app.sqlite` 같은 운영 데이터는 사용자가 데이터 백업 commit을 명시적으로 요청하지 않는 한 commit/push하지 않는다.
- stage할 때는 검증한 코드 파일을 명시적 경로로만 추가한다.
- 새 작업 브랜치는 기본적으로 `codex/` 접두사를 사용한다.
- `git reset --hard`, 광범위한 checkout, 무차별 삭제는 사용하지 않는다.

## 13. 알려진 위험과 기술 부채

1. `logs.json`과 `app.sqlite`가 이중 읽기·쓰기 호환 관계다.
2. `progress.json`은 매우 커서 전체 파싱·전송·재저장이 비용과 손상 위험을 키운다.
3. 관리자 화면은 서버 최신값과 프런트 캐시를 함께 사용한다.
4. 실제 오늘과 관리자 선택 날짜를 혼동하기 쉽다.
5. watch와 progress의 자동 상태 전이가 수동 상태를 침범할 수 있다.
6. 루트와 `data/`에 이름이 같은 운영 파일이 존재하는 경우가 있다.
7. 일부 오래된 레코드와 소스 텍스트에 레거시 필드 또는 깨진 한글이 남아 있다.
8. 직접 제공되는 미참조 정적 HTML/JS도 외부에서 수동 사용 중일 수 있어 단순 삭제하면 안 된다.
9. 기본 검증 스크립트는 중요하지만 모든 라이브·브라우저 시나리오를 포함하지 않는다.
10. 외부 OCR 공급자 호출과 실제 학생 답안 제출은 별도 안전 범위다. `tools/subjective_sheet_lab/AGENTS.md` 없이 OCR 실험을 진행하지 않는다.

## 14. ChatGPT가 답변할 때 사용할 판단 기준

### 단순 설명 요청

- 프로젝트 전체 구조보다 사용자가 묻는 운영 흐름을 먼저 설명한다.
- “코드 기준 사실”, “현재 데이터로 확인한 사실”, “추정”을 구분한다.

### 버그 진단 요청

- 재현 날짜, 학생 ID의 비식별 값, 화면, API, 기대 상태와 실제 상태를 확인한다.
- 관리자 캐시, 선택 날짜, JSON, SQLite, 자동 보정 중 어느 계층의 문제인지 나눈다.
- 진단 요청만 받았다면 임의로 운영 데이터를 수정하지 않는다.

### 코드 변경 요청

- 영향 파일과 데이터 위험을 먼저 밝힌다.
- 기존 구조를 유지하는 최소 변경을 제안한다.
- API 호환성, 병합 안정성, 네트워크 제한, 데모 격리를 점검한다.
- 검증 명령과 실제 UI 확인 시나리오를 함께 준다.

### 데이터 복구 요청

- 먼저 백업과 현재 파일 상태를 확인한다.
- 삭제·초기화보다 미러, 스냅샷, SQLite/JSON의 좁은 병합 복구를 우선 검토한다.
- 복구 대상 날짜·학생·필드를 정확히 한정한다.
- 실제 쓰기 전에 복구 계획과 되돌릴 방법을 사용자에게 확인받는다.

## 15. ChatGPT에 추가로 제공하면 좋은 자료

요청 종류에 따라 아래 파일을 함께 첨부하면 정확도가 높아진다.

| 요청 | 추가 자료 |
|---|---|
| 전체 구조·운영 정책 | 루트 `AGENTS.md` |
| 관리자 화면 | `static/AGENTS.md`, `static/js/admin/AGENTS.md`, 해당 feature 파일 |
| 출결·로그·API | `routes/AGENTS.md`, 관련 route, `core/AGENTS.md` |
| 학생 화면·시험 | `static/js/AGENTS.md`, `static/js/student.js`, `routes/api_tests.py`의 관련 부분 |
| 저장·데이터 복구 | `core/storage.py`, `core/log_repository.py`, 비식별화한 대상 레코드 |
| 서버 기동 장애 | `실행.bat`, `scripts/run_waitress_server.ps1`, 예약 작업 상태, 8003 listener와 프로세스 정보 |
| UI 시각 문제 | 실제 화면 캡처, 브라우저 크기, 재현 순서 |

전체 런타임 JSON이나 SQLite를 그대로 올리는 것은 피한다. 필요한 날짜·학생의 최소 샘플만 비식별화해 제공한다.

---

## 부록 A. ChatGPT용 짧은 프로젝트 소개

```text
“학원 운영 허브”는 Windows PC의 C:\server에서 운영하는 Flask 기반 학원 관리 시스템이다. Waitress가 기본 8003 포트에서 app:app을 서비스하고, 프런트엔드는 빌드 없는 정적 HTML/CSS/네이티브 JavaScript다. 관리자·강사는 학생 명단, 출결, 보강, 수업 로그, 숙제, 영상 배정·시청 진도, 시험·OCR·채점, 공지, 학교 일정과 파일을 관리한다. 학생은 개인 URL에서 오늘의 영상·숙제·시험을 확인하고 제출한다.

중요한 점은 코드 저장소 안에 실제 운영 JSON과 app.sqlite가 함께 있다는 것이다. 로그는 SQLite와 logs.json 호환성이 모두 필요하고, progress.json은 매우 크며, 관리자 선택 날짜와 실제 오늘 날짜가 다를 수 있다. GET 요청도 자동 배정이나 DB 스키마/WAL을 갱신할 수 있다. 따라서 데이터는 전체 덮어쓰기보다 날짜·학생 단위 PATCH/병합으로 수정하고, 기존 필드와 수동 진도 상태를 보존해야 한다. 학생 bootstrap의 assignedTests 최상위 배열, 학원 네트워크 밖의 영상·답지 제한, 데모의 실서버 쓰기 차단도 핵심 계약이다.
```

## 부록 B. 아직 저장소 밖에서 확인해야 하는 운영 정보

다음은 PC 운영자만 확정할 수 있으므로 ChatGPT가 추측하면 안 된다.

- 실제 서비스 도메인과 외부 접속 경로
- Cloudflare Tunnel 또는 다른 프록시 프로세스의 설치·실행 방식
- Windows 예약 작업의 실제 실행 계정, 트리거, 재시작 정책
- 공유기 포트포워딩과 Windows 방화벽 규칙
- 운영 백업의 외부 보관 위치와 복구 책임자
- `TRUST_PROXY_HEADERS`, `TRUSTED_PROXY_CIDRS`, `DB_PATH`의 실제 운영값
- 장애 알림·모니터링·로그 보관 정책
- 학생 및 강사 개인정보의 보존 기간과 접근 권한 정책
