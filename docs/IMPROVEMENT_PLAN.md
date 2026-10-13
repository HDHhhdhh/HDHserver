# HDHserver 안정성·속도 개선 실행 계획 (IMPROVEMENT_PLAN)

- 작성일: 2026-10-13 / 기준 커밋: `main` `4fe2ea4`
- 근거: 외부 아키텍처 리뷰(`reviews/HDHserver_리뷰.md`, 2026-10-13) + 본 문서 작성 시 코드 재확인(아래 줄번호는 재확인 시점 기준)
- 실행자: Codex (서버 PC에서 실행). **이 문서는 계획이며 구현을 포함하지 않는다.**
- 목표 우선순위: **(1) 안정성** — 오류 없는 완결된 로직, 데이터 유실/손상 없음, 인증 정확성 → **(2) 속도** — 체감 UI 반응성 + 실제 데이터 처리 속도

---

## 0. 도구/패턴 메모 (사전 탐색 결과)

- `filelock`(PyPI)·`pydantic`/`msgspec`는 **도입하지 않는다**: CI(`.github/workflows/refactor-safety.yml:28`)는 Flask/gdown/PyJWT만 설치하고 서버 venv도 수동 관리라 새 의존성이 곧 장애 원인이 된다. 레포 자체 락(`core/storage.py:189 InterProcessFileLock`, `:354 file_lock`)과 작은 손수 검증 함수로 충분하다.
- SQLite WAL은 이미 켜져 있고(`core/log_repository.py:109`), 일관된 백업은 stdlib `sqlite3.Connection.backup()`으로 가능하다. ETag/If-None-Match는 `cache:'no-store'` fetch와 궁합이 나빠 **리비전 비교 엔드포인트**(소형 JSON)로 대체한다. esbuild는 빌드 시스템이 없는 레포(`AGENTS.md` L36, CI에 npm 없음)에 맞지 않아 보류하고 네이티브 동적 `import()`만 쓴다.

---

## 1. 코드 재확인 결과 (리뷰 대비 정정·보강)

| 항목 | 재확인 결과 |
|---|---|
| 관리자 API 무인증 | 사실. `app.py:143-158`에 등록되는 `bp_api_basic / bp_api_attend / bp_api_arrive_time / bp_api_announcements / bp_api_tests / bp_api_watch / bp_api_fs / bp_api_kollus / bp_api_todaymeta / bp_api_makeup_carryover` 모두 `before_request` 없음. 페이지만 `routes/pages.py:82-93`에서 보호. 반면 `routes/api_student_accounts.py:126-140`, `api_student_focus.py:217`, `api_student_homework.py:272`, `api_assistant_notes.py:42`, `api_admin_operation_notes.py:34`에는 **이미 쓸 수 있는 가드 패턴**이 있다. |
| 락 없는 통째 교체 | 사실. `routes/api_basic.py` `crud` L74-79, `api_students` L2437-2446, `api_videos` L2449-2458, `api_materials` L2938-2943, `api_add_student` L2956-2967, `api_extra_attend` L2981-3012, `api_delete_student` L3205-3213, `api_update_student_field` L3216-3255. 락 패턴은 `routes/api_attend.py:87-100`(`file_lock`), `api_basic.py:395-402`(`_progress_lock`/`_updates_lock`), `api_tests.py:154-165`. |
| AUTH_SECRET | `routes/api_auth.py:24-26` 임의 시크릿 폴백 사실. **영향 범위는 레거시 `/student/<sid>` 페이지 JWT뿐**(`static/js/auth.js`). PWA `/app`은 `core/student_sessions.py`를 쓰므로 무관. `_save_json_atomic` L41-44는 고정 `.tmp` 이름·락 없음·미러 없음. |
| `GET /api/updates` 부작용 | 쓰기는 `_updates_lock` 안에서 일어난다(`api_basic.py:2255-2271`). 문제는 "락 없음"이 아니라 **GET이 데이터를 바꾸고 폴링 탭마다 락을 다투는 것**. |
| 로그 이중기록 | 사실. `api_basic.py:3181-3187`(SQLite 충돌+JSON 성공)과 `:3190-3197`(SQLite 성공+JSON 실패)이 `ok:true`를 돌려준다. `read_logs`(`core/log_repository.py:340-372`)는 `?date=`가 있어도 `logs.json` 전체를 파싱해 병합한다. |
| `(date,sid)` 인덱스 | **이미 PRIMARY KEY다**(`log_repository.py:115-121`). sid 단독 인덱스도 있음(L123). 새 인덱스는 필요 없고 JSON 병합 제거가 진짜 속도 요인. |
| 통째 POST 호출처 | `/api/materials`: `static/js/assign-panel.js:79`, `static/js/admin/features/materials.js:64`. `/api/mat-assign`: `assign-panel.js:202`, `file-assign.js:252`, `file-manage.js:713,756`, `admin/features/assignModal.js:304`. `/api/extra-attend`: `admin/features/calendar.js:2036,2327,3138`, `admin/features/extraModal.js:408`. `/api/videos`: `video-manage.js:444`. **`POST /api/students` 통째 호출은 프론트에서 발견되지 않음**(GET만). |
| 로드실패→`{}` | `static/js/admin/core/state.js:22-30` `api.getOr(..., {})`, `file-assign.js:135-137`, `file-manage.js:686,741`. 추가 발견: `core/storage.py:35-37` `load()`가 **JSONDecodeError 외의 모든 예외(PermissionError 등)에 `{}`를 반환** → 일시적 읽기 오류 + 통째 저장 = 파일 비움. |
| 죽은 코드 | `models.py`(34줄), `core/logs_sqlite.py`(기본 경로 `C:\server\app.sqlite`, L4), `core/paths.py:45 AUTH_PATH` 모두 import하는 곳 없음. `static/js/student copy.js`(1694줄)·`static/student copy.html`은 `AGENTS.md` L144대로 외부 사용 확인 후 삭제. |
| 프론트 부팅/폴링 | `admin/core/state.js:15-31` 11개 GET 병렬. `admin/features/today.js:971` 30초마다 `loadTodayAndRender({force:true})` → L869-879에서 9종 재조회. |
| 리비전 충돌 패턴 | 2종 존재: `api_tests.py:1500-1520`(`X-Tests-Config-Revision`, 없으면 428/다르면 409), `api_attend.py:569-583`(`If-Match`, 428/409). 리비전 계산은 `core/test_config_safety.py:49-58`(`sha256(json.dumps(sort_keys=True))`). |

---

## 2. 설계 선택

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A. JSON 유지 + JsonStore 강화** | 22개 루트 JSON(`core/paths.py`)을 그대로 두고 `core/json_store.py`(락+검증+리비전+캐시+비동기 미러)로 접근을 일원화 | 마이그레이션 0, 백업/미러/검증 하네스(`scripts/verify_refactor_safety.py` 8717줄) 그대로, 100명 규모에서 전체 재작성 비용 무시 가능(수십~수백 KB) | 파일 단위 락이라 동시 쓰기는 직렬화됨(현 규모에선 무해), 부분 조회는 서버 메모리 캐시로 해결 |
| B. 전면 SQLite | 모든 저장소를 `app.sqlite`로 | 진짜 트랜잭션, 부분 읽기 | 22개 저장소·52개 `save_atomic` 호출처·프론트 "통째 GET/POST" 계약·미러/스냅샷/백업 도구·검증 하네스 전부 수정. 비용 대비 이득 작음 |
| **C. A + 로그만 SQLite 단일 진실** | A를 기본으로 하고, 이미 절반 옮겨진 로그만 SQLite 단일화(`logs.json`은 export 전용) | A의 장점 + 이중기록 불일치 종결 + 로그 읽기 속도 | 로그 정합 작업(P5-1) 1회 필요 |

**권장: C.** 전면 SQLite(B)는 학생 수가 수백 명으로 늘거나 `progress.json`이 수십 MB가 되어 저장 지연이 체감될 때 재검토한다.

---

## 3. 실행 규약 (모든 단계 공통)

1. **브랜치**: 단계별 `codex/p<N>-<topic>` (AGENTS.md 규칙). 한 커밋 = 한 작업(아래 ID 사용, 예: `P2-1`).
2. **필수 명령** (작업마다):
   ```powershell
   python -m compileall -q app.py routes core scripts
   python scripts/verify_refactor_safety.py          # 전체. --only-* 는 보조
   node --check <수정한 js>
   git status --short                                 # 코드 변경과 런타임 데이터 변경 분리 확인
   ```
3. **복사본에서 먼저** (실서버 데이터 절대 직접 사용 금지):
   ```powershell
   python scripts/backup_runtime_data.py             # zip → _runtime_backups/
   robocopy <서버루트> <서버루트>_stage /E /XD venv .git _data_mirror _runtime_backups
   # 스테이지에서 실행 (스크립트는 $PSScriptRoot 상위를 루트로 잡으므로 스테이지 복사본의 스크립트를 실행)
   $env:DATA_MIRROR_DIR = "<서버루트>_stage\_data_mirror"
   .\scripts\run_waitress_server.ps1 -Listen 127.0.0.1:8013 -RuntimeRootOverride <서버루트>_stage -PublicEnabledOverride 0
   ```
   `-RuntimeRootOverride` 없이 실행하면 머신 환경변수의 학생앱 경로(실서버)를 쓴다(`scripts/run_waitress_server.ps1:129-148`).
4. **검증 스크립트 규약**: 새 검증은 `scripts/verify_<topic>.py` (`scripts/verify_tests_config_write_safety.py`, `scripts/verify_auth_secret_safety.py` 스타일: Flask test client + 임시 디렉터리, 실데이터 금지)로 만들고 `scripts/verify_refactor_safety.py`의 `checks` 리스트(L8159)에 등록해 CI가 돌게 한다. **기존 체크 삭제 금지**, 계약이 바뀌면 체크를 새 계약으로 갱신하고 커밋 메시지에 사유 기록.
5. **런타임 데이터 커밋 금지** (`students.json`, `app.sqlite*`, `_data_mirror/` 등). 새 동작은 **환경변수 스위치**로 도입해 배포 당일 되돌릴 수 있게 한다(부록 C).
6. 단계 적용 순서: P0 → P1 → (운영 2~3일 관찰) → P2 → P3 → P4 → P5 → P6 → P7. 각 단계 사이에 실서버 waitress 로그에서 500/409/`[ADMIN-API-GUARD]` 라인을 확인한다.

---

## 4. 단계별 작업

### Phase 0 — 준비 (약 1시간)

**P0-1 백업·스테이징·기준선** [P0]
- 변경: 위 규약 3 실행. SQLite는 WAL 중 zip이 일관되지 않으므로 추가로 `python -c "import sqlite3;s=sqlite3.connect('app.sqlite');d=sqlite3.connect('_runtime_backups/app.sqlite.bak');s.backup(d)"`.
- 기준선 기록: `verify_refactor_safety.py` 결과(통과/실패 목록), `git status --short`의 untracked 런타임 파일 목록, `GET /api/logs?date=오늘`·`/admin` 첫 로드 시간(브라우저 DevTools) 3회 평균 → `docs/baseline-2026-10.md`(선택).
- 검증: 스테이지 서버 `http://127.0.0.1:8013/admin` 로그인·오늘표 표시.

---

### Phase 1 — 인증·시크릿·오류 포맷 (반나절)

**P1-1 관리자 API 인증 가드** [P0]
- 문제: 위 표 1행. 학원 Wi-Fi의 아무 기기에서 `POST /api/students` body `[]`(`api_basic.py:2441-2443`은 받은 JSON을 그대로 저장) 또는 `DELETE /api/students/<sid>`(L3205)로 명단을 지울 수 있다.
- 변경:
  1. `core/admin_api_guard.py` 신설: `install_admin_api_guard(bp, *, student_endpoints: frozenset[str])`. `@bp.before_request`에서 (a) `request.endpoint`(예: `api_basic.api_student_bootstrap`)가 `student_endpoints`면 통과(해당 엔드포인트 자체의 세션/JWT/학원망 검사가 그대로 적용), (b) 아니면 `admin_network_allowed(request)` 실패 → 403 JSON, `verify_admin_authorization(request.headers.get("Authorization"))` 실패 → 401 JSON + `WWW-Authenticate: ADMIN_AUTH_CHALLENGE`. `current_app.config["ACADEMY_ADMIN_AUTHORIZER"]` 오버라이드는 `pages.py:88-90`과 동일하게 존중. 형태는 `routes/api_student_accounts.py:126-140`을 그대로 복제.
  2. 모드 `ADMIN_API_GUARD=off|log|enforce`(코드 기본 `enforce`, **실서버 첫 배포는 `log`로 2~3 운영일**). `log`는 거부 대상 요청을 `current_app.logger.warning("[ADMIN-API-GUARD] would-deny %s %s ip=%s endpoint=%s")`로 남기고 통과.
  3. 허용목록(부록 A 초안)을 Codex가 확정: `static/js/student.js`, `student-app*.js`, `student-focus.js`, `tests.js`, `auth.js`, `main.js`, `school-cal.js`, `static/sw.js`, `sw.js`에서 `/api/`·`/files/` 문자열 grep + `core/student_public_surface*.py`(공개 도메인이 이미 열거한 학생 표면)를 진실 원천으로 사용. **`/api/kollus/lms-callback`(`api_kollus.py:231`)은 외부 Kollus 서버가 호출하므로 절대 Basic 인증 뒤에 두지 않는다.**
  4. 레거시 폴백 `static/js/student.js:1491-1500`은 bootstrap 실패 시 `/api/students`·`/api/videos`(전체 명단)를 읽는다. 1차: 명단 수준 GET(`/api/students`, `/api/videos`, sid 없는 `/api/logs`·`/api/progress`, `/api/updates`, `/api/materials`, `/api/mat-assign`, `/api/absent`, `/api/extra-attend`)은 `log` 모드로 1주 관찰 → 학생 히트가 없으면 폴백 블록을 "서버 연결 실패" 안내로 교체하고 `enforce`. **쓰기(POST/PUT/PATCH/DELETE)는 허용목록 외 첫날부터 `enforce`.**
  5. 관리자 JS 수정 불필요: 같은 출처 fetch는 Basic 자격증명을 자동 재사용하고 `credentials:'omit'`은 레포에 없다(grep 확인). 데모 라우트(`static/js/admin/demo/fetch.js`)는 실API를 부르지 않아 무관.
- 검증: `scripts/verify_admin_api_guard.py` — test client + `ACADEMY_ADMIN_AUTHORIZER` 오버라이드 + 임시 런타임 디렉터리. 단언: 무인증 `POST /api/students []` → 401 JSON **및 `students.json` sha256 불변**; 인증 시 성공; `GET /api/student/bootstrap?sid=` 영향 없음; 무인증 `DELETE /api/students/x` → 401; 비LAN IP → 403 JSON; `ADMIN_API_GUARD=log` → 통과 + warning 로그. 스테이지 수동: Basic 로그인 후 60초 대기 → 폴링(`today.js:971`)이 계속 200; `python scripts/verify_refactor_safety.py --only-student-mobile-deployment` 통과.
- 위험/롤백: 허용목록 누락 → 학생 화면 오류. 완화 = `log` 소크, 부록 A, 즉시 롤백 `ADMIN_API_GUARD=off`(환경변수+재시작). 데이터 마이그레이션 없음.
- 선행: P1-3을 같은 PR에 (401/403이 JSON이어야 함).

**P1-2 AUTH_SECRET 필수화** [P0]
- 문제: `routes/api_auth.py:24-26` 시크릿 없으면 프로세스마다 `secrets.token_urlsafe(32)` → 재시작마다 30일 토큰(L27, 발급 L221/검증 L226) 전부 무효. `scripts/run_waitress_server.ps1:22-40`의 머신 환경변수 목록에 `AUTH_SECRET`/`MASTER_PW`가 없다(프로세스에 이미 있을 때만 상속).
- 변경:
  1. `api_auth.py`: 폴백은 유지하되(`scripts/verify_auth_secret_safety.py:19`가 env를 지우고 모듈을 import함) `AUTH_SECRET_IS_EPHEMERAL: bool` 플래그를 노출.
  2. `app.py create_app()`: `if api_auth.AUTH_SECRET_IS_EPHEMERAL and os.environ.get("ALLOW_EPHEMERAL_AUTH_SECRET") != "1": raise RuntimeError("AUTH_SECRET is not set; refusing to start")`.
  3. `run_waitress_server.ps1`: `$studentAppMachineEnv`에 `"AUTH_SECRET","MASTER_PW"` 추가, 비격리 모드에서 `$env:AUTH_SECRET`이 비면 `throw`. `-DevelopmentIsolation`에서는 `$env:ALLOW_EPHEMERAL_AUTH_SECRET="1"`.
  4. `verify_refactor_safety.py --smoke`는 실앱을 import하므로 스모크 러너가 import 전에 `ALLOW_EPHEMERAL_AUTH_SECRET=1`을 설정.
  5. `MASTER_PW`(L31, `_master_pw_ok` L315) 우회는 소유자 기능이므로 유지하되 12자 미만이면 기동 거부, 마스터 로그인마다 `logger.warning(aid)`.
- 검증: `verify_auth_secret_safety.py` 그대로 통과(자체 Flask 앱 사용, L30-33). 새 체크 `scripts/verify_app_startup_guards.py`: 시크릿·허용플래그 없이 `create_app()` → RuntimeError; 플래그 있으면 정상. 스테이지: 시크릿 설정 → 레거시 학생 페이지 로그인 → waitress 재시작 → 새로고침 후 로그인 유지.
- 위험/롤백: 머신 환경변수 미설정 시 배포 후 기동 실패 → **배포 전** `[Environment]::SetEnvironmentVariable("AUTH_SECRET","<64자 난수>","Machine")`. 1회성: 기존 임의 시크릿 토큰은 무효 → 레거시 페이지 학생 1회 재로그인. 롤백 `ALLOW_EPHEMERAL_AUTH_SECRET=1`.

**P1-3 API 오류 JSON 통일 + `fetchJson` ok 검사** [P1]
- 문제: `app.py:139-141` 403 핸들러가 모든 경로에 `BLOCK_HTML`; `pages.py:74-79` 401은 text/plain; Flask 기본 400/404/405/500은 HTML. `static/js/shared/api.js:40-43 fetchJson`은 `ok` 검사 없이 `.json()` → HTML 본문이 `SyntaxError`가 되고 `fetchJsonOr`(L51-57)가 그것을 조용히 폴백값으로 바꾼다.
- 변경:
  1. `app.py`: 400/401/403/404/405/409/413/428/500 + `HTTPException` 공통 핸들러. `request.path.startswith(("/api/","/files/"))` 또는 Accept가 JSON이면 `{"ok":false,"error":"<code>","message":...}`(401엔 `WWW-Authenticate` 유지), 아니면 기존 HTML/텍스트(`BLOCK_HTML` 유지).
  2. `shared/api.js`: `fetchJson`이 `.json()` 전에 `ensureOk(response, url)`(L30-38 존재) 호출. 4xx 본문을 일부러 읽는 호출(`/api/logs/patch` 409, `/api/absent` 428/409, `/api/tests-config` 409)은 raw `fetch`+`res.json()`을 쓰므로(`today.render.js:695/758/797`, `logModal.js:355`, `tests.js:1179`) 영향 없음 — `fetchJson(`/`api.get(` 호출처를 grep해 4xx 성공 의존이 없음을 확인.
  3. `fetchJsonOr`: `console.warn('[api] fallback', url, err)` 추가(의미는 유지, 중요 경로 제거는 P3-2).
- 검증: `scripts/verify_api_error_format.py`: `GET /api/없는경로` → 404 JSON; remote_addr 8.8.8.8로 `/api/students` → 403 JSON; `/admin` → 403 HTML. `node --check static/js/shared/api.js`; `--only-admin-api-wrapper-usage-source` 통과.
- 위험/롤백: HTML 오류를 텍스트로 파싱하던 경로가 `ApiError`를 던짐 → 토스트로 노출(의도). 되돌리기 = revert.

---

### Phase 2 — 락·중복검사·경계 검증 (반나절)

**P2-0 `core.storage.load` 예외 삼킴 제거** [P0]
- 문제: `core/storage.py:35-37` — 디코드 외 모든 예외(Windows에서 미러/백업/백신이 파일을 잡았을 때의 `PermissionError`, `OSError`)에 `{}`를 반환. 통째 저장(`api_students` L2441-2443, `api_extra_attend` L2989-2992, `crud` L74-79)과 결합하면 **일시적 읽기 오류가 파일 비움으로 변한다.**
- 변경: `FileNotFoundError`만 기본값(`.json`→`{}`), 나머지는 `raise`(`log.exception` 유지). `load(x) or {}` 호출자는 그대로 동작; 오류는 500 JSON(P1-3)으로 드러난다.
- 검증: `scripts/verify_json_store_safety.py`(P2~P4에 걸쳐 확장): `read_text`가 `PermissionError`를 내도록 monkeypatch → `load` raise; 없는 파일 → 기존 기본값. 전체 하네스 실행 — `{}`에 의존하는 픽스처가 있으면 **픽스처를 고친다**(동작 아님).
- 위험: 숨어 있던 읽기 오류가 500으로 보임(의도). 스테이지 1일 waitress 로그 확인.

**P2-1 read-modify-write 전부 `file_lock`** [P0]
- 문제: 표 1행의 핸들러들 + `api_videos`가 호출하는 `_migrate_video_mid_references`(L326-370, UPD/WATCH를 락 없이 재작성) + `api_weekend_slots`(L3015-3043, 확인) + `routes/api_auth.py` `_save_json_atomic`(L41-44: 고정 `.tmp` 이름이라 동시 쓰기 둘이 서로의 tmp를 덮음)을 쓰는 `_refresh_and_persist_account_sids`(L320-347, 로그인/me/switch마다 호출: L427, 472, 498, 535, 572)와 `change`(L585-636). Waitress 16스레드(`run_waitress_server.ps1:3`) + 탭 2개면 마지막 쓰기가 다른 변경을 조용히 지운다.
- 변경:
  - 각 핸들러의 load→수정→save_atomic을 `with file_lock(PATH):`로 감싼다(`routes/api_attend.py:87-100`과 동일). `TimeoutError` → `jsonify({"ok":False,"error":"store_busy"}), 409`(`api_basic.py:2616-2617` 패턴). `_InterProcessFileLock` 별칭(L375) 대신 `core.storage.file_lock` 사용. 락 파일 이름은 반드시 `<파일>.lock` 유지(외부 스크립트 호환).
  - **락 순서**(부록 B)를 `core/storage.py` docstring에 명문화. 여러 저장소를 만지는 핸들러(`api_videos`→VID 후 `_updates_lock`/`_progress_lock`/WATCH)는 그 순서만 따른다. `_load_updates_with_auto_assign`(L2236-2272)은 다른 저장소를 읽은 뒤 `_updates_lock`만 잡으므로 현 상태 유지.
  - `api_auth.py`: `_load_json/_save_json_atomic` → `core.storage.load/save_atomic` + `file_lock(ACCT_PATH)`, `_refresh_and_persist_account_sids`·`change`의 읽기-수정-쓰기 전체를 락 안으로. 중복 정의 `STU_PATH`(L19) → `core.paths.STU_PATH`. 부수효과: `auth_accounts.json`도 미러/스냅샷을 받게 됨.
- 검증: `scripts/verify_json_store_concurrency.py`: 임시 `students.json`(100명) + test client, `threading.Barrier`로 16스레드 동시 출발, 각자 다른 sid에 `POST /api/update` → 100건 모두 반영·파일 파싱 가능. 20회 반복 20/20(수정 전엔 비결정적으로 실패하는 것이 정상이며 그것이 이 하네스의 목적). `auth_accounts.json`에 대해 `/api/auth/login` 16동시도 동일.
- 위험/롤백: 과부하 시 409(조용한 유실 대신, 의도). revert로 복귀. 포맷 변경 없음. 오래된 락 자동 해제는 `storage.py:278-307`에 이미 있음.

**P2-2 add-student ID 중복 방지** [P1]
- 문제: `api_basic.py:2960-2962` id = 이름슬러그+3자리 난수, 중복 검사 없음. 중복되면 두 학생이 로그/진도 키를 공유하고 `DELETE /api/students/<sid>`(L3205)는 첫 번째만 지운다.
- 변경: STU 락 안에서 `existing = {str(s.get("id")) ...}`; 최대 1000회 시도로 빈 id 선택, 없으면 409 `id_space_exhausted`; 빈 슬러그 400; `data`가 dict·`name` 비어있지 않음 검사.
- 검증: `verify_json_store_safety.py`: 같은 이름 id 999개 선점 → 남은 1개 배정; 1000개 선점 → 409; 200회 추가 → 전부 유일. 읽기전용 보고 `scripts/report_duplicate_student_ids.py`로 기존 중복 유무를 소유자에게 보고.
- 위험: 기존 데이터 영향 없음.

**P2-3 경계 본문 타입 검증** [P1]
- 문제: `request.get_json(force=True)`를 그대로 저장: `/api/students`(L2442), `/api/materials`(L2942), `/api/mat-assign`(`crud` L77), `/api/extra-attend`(L2986-2992: dict가 아니면 `{}`로 저장 = 잘못된 본문이 파일을 비움), `/api/update`(L3216-3255: `field` 무제한, `id`도 덮어쓸 수 있음), `/api/videos`(L2455).
- 변경: `core/payload.py`에 작은 검증기 `expect_dict`, `expect_list_of_dicts(require_keys=("id",))`, `expect_date_keyed_dict`(키 `DATE_RE`, 값 dict) → 400 `{"ok":false,"error":"invalid_payload","detail":...}`. `/api/update`: `field` ∈ `^[A-Za-z][A-Za-z0-9_]{0,39}$` 이고 `id` 금지, `value`는 스칼라/스칼라 리스트(객체 허용 필드는 `static/js/all/features/table.js`의 `patchField` 호출과 `_coerce_auto_video_assign_count`에서 도출한 집합만). `/api/students` POST: 명단이 5명 넘게 줄면 `X-Confirm-Roster-Shrink: 1` 없이는 409 `roster_shrink_guard`(P3-1 리비전 전 임시 퓨즈).
- 검증: `scripts/verify_admin_api_body_validation.py`: 잘못된 타입 → 400 + 파일 sha256 불변; 올바른 타입 → 성공; `field=id` → 400; 100→0명 헤더 없이 → 409.
- 위험/롤백: 예상 밖 형태를 보내던 정상 호출 → 400 detail로 스테이지에서 발견. revert.

---

### Phase 3 — 통째 POST 제거·리비전·로드실패 차단·GET 부작용 (1일)

**P3-1 통째 교체 POST에 리비전(`If-Match`) 강제** [P0]
- 문제: 표 "통째 POST 호출처" 행. 두 탭이면 마지막 저장이 다른 탭의 편집을 조용히 삭제. 레포에 이미 두 패턴(`api_tests.py:1500-1520`, `api_attend.py:569-583`)과 리비전 함수(`core/test_config_safety.py:49-58`)가 있다.
- 변경:
  1. `tests_config_revision`을 `core/storage.py:json_revision(obj)`로 일반화(기존 이름은 별칭 유지).
  2. 서버: 통째 GET에 `X-Store-Revision` 헤더, 통째 POST는 `If-Match`(또는 `X-Store-Revision`) 읽기. `JSON_STORE_REVISION_MODE=soft|strict`(첫 배포 `soft`: 헤더 없음→warning+허용, 불일치→항상 409; 호출처 전부 전환 후 `strict`: 없음→428 `revision_required`). 비교는 P2-1 락 안에서. 응답은 `return "", 204` 대신 `200 {"ok":true,"revision":...}` + 헤더(호출처는 `res.ok`만 보므로 무해 — grep으로 확인).
  3. 단건 편집용 PATCH 추가로 충돌 자체를 드물게: `POST /api/extra-attend/patch {date, sid, value|remove}`(`/api/updates/patch` L2575-2617 모델), `POST /api/mat-assign/patch {sid, materials:[...]|remove}`. `extraModal.js:408`, `calendar.js:2036/2327/3138`은 patch로 전환; 일괄 화면(`assign-panel.js`, `file-manage.js`)은 통째 POST + `If-Match` 유지.
  4. 프론트: `shared/api.js`에 `fetchJsonWithRevision(url) → {data, revision}`, `sendJsonIfMatch(url, data, revision)`. 409/428이면 해당 저장소를 다시 읽고 "다른 화면에서 먼저 변경되었습니다. 새로고침 후 다시 저장해 주세요."(`api_basic.py:3167` 문구) 표시, **오래된 사본으로 자동 재시도 금지**. 리비전은 `state.revisions[store]`(`admin/core/state.js`)에 보관.
- 검증: `scripts/verify_store_revision_guard.py`: GET→rev A; `If-Match: A` POST→200 rev B; 다시 A로 POST→409; strict에서 헤더 없음→428; soft→200+warning. 스테이지 브라우저: 두 탭에서 서로 다른 학생의 보강을 저장 → (patch) 둘 다 성공 / (통째) 두 번째가 충돌 메시지 — 이전처럼 첫 탭 변경이 사라지지 않음.
- 위험/롤백: 동시 편집 시 충돌 메시지가 새로 보임(의도). `JSON_STORE_REVISION_MODE=soft` 또는 revert. 마이그레이션 없음.
- 선행: P2-1, P1-3.

**P3-2 로드 실패 → 저장 차단** [P0]
- 문제: `admin/core/state.js:22-30`의 `getOr(..., {})`가 실패(500/401/HTML 오류/네트워크)를 `{}`로 바꾸고, 이후 `extraModal.js:408`·`materials.js:64`·`assignModal.js:304` 등이 그 빈 맵을 통째 POST → 파일 비움. 레거시도 동일(`file-assign.js:135-137`→`:252`, `file-manage.js:686/741`→`:713/756`).
- 변경: 서버 측 진짜 퓨즈는 P3-1 strict(리비전이 없다는 것은 로드하지 않았다는 뜻 → 428). 클라이언트: `state.js`의 해당 저장소를 `api.getStrict`로 바꾸고 성공 시에만 `state.loaded[store]=true`; 부팅 실패는 `main.js:35-37`의 `console.error` 대신 화면 배너 "데이터 로드 실패 — 새로고침 전까지 저장이 비활성화됩니다" + 미로드 저장소의 저장 버튼 `disabled`. 각 통째 저장 지점에 `if (!state.loaded.extra) return;` 가드 + `If-Match`. `file-assign.js`/`file-manage.js`의 `.catch(()=>({}))`를 strict 로드로 교체하고 실패 시 저장 경로 비활성.
- 검증: 스테이지에서 `/api/extra-attend`를 실패시키고(`ADMIN_API_GUARD=enforce` 상태에서 무인증 접근 → 401) 배너·저장 비활성·POST 미발생 확인; 서버: strict에서 `If-Match` 없는 POST → 428 + 파일 불변.
- 위험/롤백: 서버가 불안정할 때 오류가 더 자주 보임(정상). revert JS.

**P3-3 `GET /api/updates` 부작용 제거** [P1]
- 문제: `api_basic.py:2558-2563` GET(readOnly 아님)이 `_load_updates_with_auto_assign`(L2236-2272)을 호출해 `save_atomic(UPD_PATH, fixed)`(L2271)할 수 있음. 관리자 탭마다 30초 폴링(`today.js:862/966 refreshUpdatesAtAssignmentBoundary`)이 이것을 부르고 `/api/student/bootstrap`(L2725)도 유발(`AGENTS.md` L74) → 읽기가 데이터를 바꾸고, 락 경합, 미러/스냅샷(`storage.py:86-148`) 반복.
- 변경: `POST /api/updates/ensure-today`(관리자) = 현재의 쓰기 경로. `GET /api/updates`는 기본 읽기 전용(`?ensure=1`이면 한 릴리스 동안 구동작 유지, 사용 로그). 클라이언트 `refreshUpdatesAtAssignmentBoundary`는 (날짜 경계, 탭)당 1회와 명단/시간표 편집 후에만 `ensure-today` 호출(`/api/update`의 `day*`/`selfStudyDays`는 서버가 L3241/3251에서 이미 ensure → 유지), 폴링은 GET만. 학생 bootstrap은 **오늘만** create-only ensure 유지하되 `updates[today]`에 sid가 이미 있으면 락 없이 건너뜀.
- 검증: 스테이지에서 `GET /api/updates` 20병렬 → `updates.json` mtime 불변; `ensure-today` 2회 → 두 번째는 쓰기 없음(`_json_stable` 동일); `--only-video-modal-assignment-policy`, today 계열 체크 통과.
- 위험/롤백: 관리자 탭 없이 날짜가 바뀌면 첫 학생 bootstrap/첫 ensure가 생성(지금도 지연 생성이므로 동일). 롤백 `UPDATES_GET_ENSURE=1`.

**P3-4 로그 PATCH 응답 정직화 (P5 전 과도기)** [P1]
- 문제: `api_basic.py:3181-3187`, `:3190-3197`이 한쪽만 성공해도 `ok:true`; `read_logs` 병합이 분기를 가린다.
- 변경: SQLite 커밋 시에만 `ok:true`(3190-3197은 유지하되 `logger.error(date, sid)`로 분기를 가시화); 3181-3187(SQLite 충돌 + JSON 성공)은 409 `sqlite_base_conflict` + `entry`로 바꿔 UI가 다시 읽게 함. JSON만 성공한 것을 성공으로 보고하지 않는다.
- 검증: `scripts/verify_log_patch_contract.py`: 임시 경로 `LogRepository`로 SQLite 충돌 → 409; JSON 실패 → 200 + warning + error 로그.
- 위험/롤백: 오래된 모달에서 409가 더 자주 보임 — 모달은 이미 409를 처리(3163-3169). revert.

---

### Phase 4 — `core/json_store.py` 일원화 + 미러 비동기 (1~2일)

**P4-1 JsonStore** [P1]
- 문제: `save_atomic` 호출처 52곳(AGENTS.md 코드맵)이 각자 load/락/검증/save를 구현; 캐시는 progress만(`api_basic.py:82-110`, `(mtime_ns,size)` 키); P2-3 검증기와 P3-1 리비전이 흩어진다.
- 변경: `class JsonStore(path, default_factory, validate=None, compact=False)` — `read() -> (data, revision)`(82-110과 같은 stat 키 캐시, 스레드 안전), `revision()`(stat 변경 시에만 바이트 sha256), `update(mutator, *, expected_revision=None, timeout_sec=15)`(file_lock→load→mutator→validate→save_atomic→캐시 갱신→새 리비전), `replace(data, expected_revision)`; 예외 `StoreBusy`/`RevisionConflict`/`StoreCorrupt` → P1-3 핸들러에서 409/409/500. `core/stores.py`에 `core/paths.py`의 경로마다 하나씩 등록(students·videos는 list, 나머지 dict). 전환 순서: P2/P3 엔드포인트(students, videos, materials, mat-assign, extra-attend, school-calendar, weekend-slots) → updates/progress/watch(`_updates_lock`/`_progress_lock`과 **같은 락 파일 이름** 유지).
- 검증: `verify_json_store_safety.py` 확장: 외부 바이트 쓰기 후 다음 read가 새 값; 리비전 안정성; 충돌 예외; 손상 JSON → `StoreCorrupt`(절대 `{}` 아님). 전체 하네스; 스테이지 1일 소크.
- 위험/롤백: 손대는 핸들러가 많음 → 엔드포인트 단위 작은 커밋, 커밋마다 하네스. 포맷·락파일 이름 불변.
- 선행: P2-0, P2-1, P3-1.

**P4-2 미러/스냅샷 백그라운드 큐** [P2, 속도]
- 문제: `save_atomic`(`storage.py:151-186`)이 요청 스레드에서 `_mirror_copy`(86-148: `copy2`, 스냅샷 디렉터리 `glob`, `stat`, `filecmp.cmp` 전체 읽기, `_prune_snapshots`)를 동기 실행 — 모든 저장마다, **파일 락을 잡은 채로** → 다른 스레드의 락 대기도 늘어난다.
- 변경: `save_atomic(..., mirror="async")` 기본: 경로를 `queue.Queue`에 넣고 데몬 스레드 1개(`core/storage.py` 지연 싱글턴, 경로 중복 합치기, `atexit`에서 최대 5초 드레인)가 처리. `DATA_MIRROR_SYNC=1`이면 기존 동기(저장 후 바로 종료하는 `scripts/*` 용). 스냅샷 규칙(간격/중복 제거) 불변.
- 검증: 스테이지에서 `POST /api/updates/patch` 200회 순차 시간 전/후 수치 보고; 미러 파일·스냅샷이 2초 내 생성; 하네스가 미러를 동기로 단언하면 스모크 러너에 `DATA_MIRROR_SYNC=1`.
- 위험/롤백: 저장과 미러 사이 크래시 시 그 1회 미러만 누락(원본은 안전). `DATA_MIRROR_SYNC=1`.

**P4-3 api_auth 저장소 통일** [P1] — P2-1에서 못 끝낸 부분: `ACCT_PATH`를 JsonStore로. `core/paths.py:45 AUTH_PATH(auth.json)`는 미사용 → 파일은 두고 상수는 P7에서 제거.

---

### Phase 5 — 로그 SQLite 단일 진실 (2~3일)

**P5-1 사전 정합: `logs.json` → SQLite 보충** [P0]
- 문제: SQLite가 1차지만 `logs.json`에만 있는 항목/필드가 있을 수 있다(그래서 `read_logs` 365-372, `read_entry` 320-338이 병합). 정합 없이 읽기를 SQLite로 바꾸면 그 행들이 UI에서 사라진다.
- 변경: `scripts/reconcile_logs_json_into_sqlite.py`(기본 `--dry-run`): `logs.json`의 모든 (date,sid)에 대해 SQLite에 없으면 insert, 있으면 **빈 필드만 채움**(`LogRepository._merge_json_fallback_fields` L285-295 의미 재사용); 둘 다 비어있지 않고 다른 값은 **덮어쓰지 않고 목록으로 출력**. 카운트(inserted/filled/unchanged/conflicts) 출력. `migrate_logs_json_to_sqlite_cutoff.py`는 기본 경로가 `C:\server\...`(L4-5)이고 병합 규칙 확인(L40+) 전엔 그대로 쓰지 않는다. 실행 전 P0-1 백업 + `sqlite3 .backup()` 사본.
- 검증: dry-run 카운트 보고 → 적용 → `scripts/verify_log_store_parity.py`: 무작위 날짜 30 + sid 30에 대해 `dual` 모드 `read_logs()`와 SQLite 단독 결과가 키 정렬 후 동일.
- 위험/롤백: conflicts는 소유자 결정 필요(스크립트는 절대 덮어쓰지 않음). SQLite 백업 복원.

**P5-2 읽기 경로 SQLite 단독** [P1]
- 문제: `read_logs`(340-372)는 `?date=`가 있어도 `logs.json` 전체 파싱(`read_json_map` 197-202) — 관리자 부팅 `/api/logs?date=`와 30초 폴링마다; `read_entry`(320-338), `summarize_unarchived_done`(648-807)도 동일. 인덱스는 이미 충분(PK(date,sid) L115-121, `idx_logs_sid` L123).
- 변경: `LOG_STORE_MODE=dual|sqlite`(P5-1 후 기본 `sqlite`; `dual`=현 동작, 롤백용). `sqlite` 모드에서는 JSON을 읽지 않음; SQLite 실패 → 500 JSON(**조용한 JSON 폴백 금지** — 그 폴백이 분기를 숨긴 원인).
- 검증: 두 모드 parity; 스테이지 `GET /api/logs?date=` p50 전/후(logs.json 크기에 비례해 감소 기대); 하네스에서 JSON 폴백 읽기를 단언하는 체크는 새 계약으로 **갱신**(삭제 금지).
- 위험/롤백: P5-1 후 JSON에만 남은 항목 → 안 보임; parity 스크립트가 게이트. `LOG_STORE_MODE=dual`.

**P5-3 쓰기 경로: SQLite 트랜잭션만 성공 기준, `logs.json`은 export** [P1]
- 문제: `patch_entry` 438-544, `legacy_post` 374-413, `append_record` 546-592, `transform_entries` 594-646이 두 저장소에 쓰며 부분 성공 상태(P3-4)와 저장마다 이중 락/IO.
- 변경: `sqlite` 모드에서 JSON 쓰기는 선택(`LOG_JSON_EXPORT=1|0`, 한 릴리스 동안 1, 이후 0): 응답 경로 밖(P4-2 큐 스레드)에서 해당 (date,sid)만 best-effort 기록; 상태는 SQLite 트랜잭션만으로 결정; `api_logs_patch`는 `{"ok":true,"entry":merged}`(프론트가 `sqlite`/`json` 플래그·`warning`을 읽는지 `logModal.js`/`today.render.js` grep 후 제거). 백업/사람용 `scripts/export_logs_sqlite_to_json.py`.
- 검증: `verify_log_patch_contract.py` 갱신; 동시성: 같은 (date,sid)의 다른 필드를 16스레드가 patch → 모두 보존(`BEGIN IMMEDIATE` L454 직렬화).
- 위험/롤백: `logs.json`을 직접 읽는 스크립트(`scripts/`에서 `LOGS_PATH`/`logs.json` grep) → export 또는 repository로 전환. `LOG_STORE_MODE=dual`.
- 선행: P5-1, P5-2, P4-2.

**P5-4 정리**: `core/logs_sqlite.py`(미사용, 기본 경로가 `log_repository.py:87-95`와 다름) → P7 삭제. 백업 스크립트(`backup_runtime_data.py:14-24`)는 `*.sqlite(-wal/-shm)`를 이미 포함하나 `.backup()` 일관 사본 옵션 추가.

---

### Phase 6 — 속도 (1~2일)

**P6-1 `/api/admin/bootstrap` 통합** [P1]
- 문제: `admin/core/state.js:17-31` GET 11개; 각각 서버에서 JSON 파싱; `/api/updates`가 크리티컬(`getCriticalJson`)이며 쓸 수도 있음(P3-3); 16스레드 중 11개를 한 페이지가 점유.
- 변경: `GET /api/admin/bootstrap?date=YYYY-MM-DD`(관리자 가드) → `{students, videos, materials, updates(readOnly), assigns, extra, logs(date), absent, progress(date), schoolCal, testsConfig, revisions:{store:rev}}`, **키별 shape는 개별 엔드포인트와 완전히 동일**(같은 함수 재사용; `absent`는 `load_absent()` 통합 shape; `testsConfig`는 `get_tests_config` 1487-1498과 같은 답지 링크 제거 적용). 프론트 `bootstrap()`은 통합 엔드포인트 시도 → 404면 기존 11개 GET 폴백(백/프론트 독립 배포). `state.revisions` 저장.
- 검증: `scripts/verify_admin_bootstrap_contract.py`: 임시 픽스처에서 통합 응답의 각 키 == 개별 엔드포인트 응답(deep-equal). 스테이지 DevTools: 요청 11→1, 첫 렌더 시간 전/후.
- 위험/롤백: 통합/개별 shape 어긋남 → 계약 체크가 방지. 엔드포인트 삭제 시 프론트 자동 폴백.

**P6-2 폴링을 리비전 비교로** [P1]
- 문제: `today.js:961-975` 30초마다 `loadTodayAndRender({force:true})` → L869-879에서 students/absent/logs(date)/progress(date)/weekend/attend/contact/arrive/makeup 전체 재조회(변경 여부 무관); 탭 2~3개면 서버 부하의 대부분. `nocache_resp`(`storage.py:370-375`)가 `no-store`라 브라우저 조건부 요청 불가.
- 변경: `GET /api/admin/revisions?date=` → `{students:rev, absent:rev, logs:{date:rev}, progress:{date:rev}, ...}`(JsonStore `revision()` stat 기반; SQLite 로그는 해당 날짜 `MAX(updated_at)` — 느리면 그때 `(date, updated_at)` 인덱스). 폴링은 이것(≈300B)만 받고 바뀐 저장소만 재조회; `visibilitychange`(972-974)도 동일. 명시적 사용자 동작(`admin:refresh`, 날짜 변경 977-982)은 `force:true` 유지. 안전망으로 10분마다 전체 새로고침 1회.
- 검증: 스테이지 유휴 탭: waitress 로그에 30초당 `/api/admin/revisions` 1건만; 다른 탭에서 로그 저장 → 다음 폴링이 `/api/logs?date=`만 재조회. `--only-today-completion`, `--only-admin-today-actions` 통과.
- 위험/롤백: 리비전에 없는 저장소는 갱신 안 됨 → L869-879가 읽는 저장소 전부를 응답에 포함. revert JS(서버 엔드포인트는 추가형).

**P6-3 응답 기반(낙관적) 행 갱신** [P2]
- 문제: 저장 후 `admin:refresh`로 전체 재조회. 이미 `/api/updates/patch`는 `assignment`(2615), `/api/logs/patch`는 `entry`(3199), `/api/progress/patch`는 병합 결과를 돌려준다. `aria-busy`/disabled는 있음(좋음).
- 변경: 저장 경로(`today.render.js:695/758/797`, `logModal.js:355`, `videoModal.js:1013`, `absentRegister.js`)에서 응답 entry를 `state`에 반영하고 그 행만 재렌더; 오류/409면 해당 저장소 재조회 + 메시지. P6-2 폴링이 최종 일관성 안전망.
- 검증: 스테이지에서 로그 저장 → 네트워크 탭에 PATCH만(`/api/logs?date=`·`/api/students` 재조회 없음); `--only-log-modal-*` 통과.
- 위험/롤백: 서버 부수효과가 다른 행에 미치는 엔드포인트(결석 등록이 배정을 비움, `api_attend.py:587-591`)는 영향 저장소(updates/progress/logs 해당 날짜)만 범위 재조회. revert JS.

**P6-4 `/api/progress` 무필터 금지** [P2]
- 문제: `api_basic.py:2461-2492` 필터 없으면 `progress.json` 전체 반환(`AGENTS.md` L140 "large", 무한 성장).
- 변경: `date|sid|sids` 중 하나 필수(400 `filter_required`) — 호출처 grep 선행(`all/core/state.js:56`, `student.js` `?sid=`, `today.js:892 ensureProgressHistoryForSids`); 이력 창용 `since=YYYY-MM-DD` 추가. 캐시(82-110) 유지.
- 검증: 무필터 호출처 없음(grep); `GET /api/progress` → 400; progress 관련 `--only-*` 통과.

**P6-5 정적 자산** [P3] — 번들러 도입 금지. `static/js/student.js`(8759줄)는 휴대폰 첫 렌더가 실제로 느리다고 **측정된 경우에만** 드물게 쓰는 구간을 동적 `import()`(`all/features/table.js:1125` 패턴)로 지연; Flask 정적 응답의 `ETag`/`Last-Modified`(기본 제공) 확인 + `SEND_FILE_MAX_AGE_DEFAULT` 설정으로 재방문 304.

---

### Phase 7 — 정리 (반나절)

- 죽은 코드 삭제(오늘 grep으로 importer 없음 확인): `models.py`, `core/logs_sqlite.py`, `core/paths.py:45 AUTH_PATH`; `_InterProcessFileLock` 별칭(`api_basic.py:375`)은 호출처가 `file_lock`으로 옮겨진 뒤.
- `static/js/student copy.js` + `static/student copy.html`: `AGENTS.md` L144대로 waitress/Cloudflare 접근 로그 2주에 `student copy` 히트 없음 확인 후 삭제.
- 과도기 스위치 제거(새 동작이 기본이 된 다음 릴리스): `JSON_STORE_REVISION_MODE=soft`, `UPDATES_GET_ENSURE`, `LOG_STORE_MODE=dual`, `LOG_JSON_EXPORT`.
- `AGENTS.md` 갱신: L74("GET /api/updates may auto-write")는 P3-3 후 거짓, L139(이중기록)는 P5 후 거짓, 새 환경변수·락 순서·JsonStore 사용 규칙 추가.

---

## 5. 사용자 입장에서 변화하는 것

**학생**
- 레거시 학생 페이지(`/student/<sid>`) 사용자: 서버 재시작 후 로그아웃되지 않는다(P1-2). 단 **배포 직후 1회 재로그인**(기존 임의 시크릿으로 서명된 토큰 무효).
- PWA(`/app`) 사용자: 세션 방식이 달라 **변화 없음**.
- 보이지 않지만 안전: 학원 Wi-Fi의 다른 기기가 명단·배정을 지우거나 통째로 내려받을 수 없다(P1-1). 학생 화면이 쓰는 API는 허용목록으로 유지되므로 정상 사용엔 차이 없음(허용목록 누락 시엔 오류가 보일 수 있어 `log` 모드로 먼저 관찰).
- 오늘 영상/과제 로딩이 약간 빨라진다(P3-3 GET 부작용·락 경합 제거, P5 로그 읽기 단축).

**관리자**
- 눈에 보이는 변화: (1) 두 탭/두 사람이 같은 화면을 저장하면 "다른 화면에서 먼저 변경되었습니다" 메시지가 뜰 수 있다 — 이전엔 한쪽 변경이 **조용히 사라졌다**(P3-1). (2) 데이터 로드 실패 시 배너가 뜨고 저장 버튼이 비활성화된다(P3-2). (3) 오류가 HTML 대신 메시지로 보인다(P1-3). (4) 관리자 페이지 첫 로드가 빨라진다(요청 11→1, P6-1), 30초 폴링이 거의 트래픽을 만들지 않는다(P6-2), 저장 후 해당 행만 즉시 갱신된다(P6-3).
- 보이지 않지만 안전: 동시 저장 유실 없음(P2-1), 새 학생 ID 중복 없음(P2-2), 잘못된 형식의 저장 거부(P2-3), 일시적 읽기 오류로 파일이 비워지는 경로 차단(P2-0), 로그 이중기록 불일치 종료(P5).
- 운영: `AUTH_SECRET` 머신 환경변수 없이는 서버가 기동을 거부한다(P1-2) — **배포 전 설정 필수**. 새 환경변수는 부록 C.

---

## 6. 구현 시 주의

- **기존 JSON 데이터 포맷·키·엔드포인트 URL 변경 금지**(`AGENTS.md`). 응답 shape 유지. `204 → 200 JSON` 전환은 호출처가 `res.ok`만 보는지 grep으로 확인한 뒤에만.
- **하위 호환**: 모든 새 동작은 환경변수 스위치(`log→enforce`, `soft→strict`, `dual→sqlite`)로 들어오고, 백엔드/프론트가 **독립 배포** 가능해야 한다(통합 bootstrap 404 폴백, `If-Match` soft 모드 등).
- **복사본에서 먼저**(규약 3). 실서버 적용은 단계별로, 사이에 운영 로그 관찰.
- **새 의존성 금지**(CI는 Flask/gdown/PyJWT만). filelock/pydantic 불필요.
- **런타임 데이터 커밋 금지**, 코드 변경과 데이터 변경을 항상 분리 보고.
- **검증 하네스**: 체크 삭제 금지, 계약 변경 시 갱신 + 사유.
- **설계 선택**: 섹션 2의 C(JSON+JsonStore 우선, 로그만 SQLite). 100명 단일 학원에서 전면 SQLite는 비용 대비 이득이 작다. 재검토 조건: 학생 수백 명 또는 `progress.json` 수십 MB로 저장 지연 체감.
- **롤백**: 모든 단계는 코드 revert + 환경변수로 되돌릴 수 있다. 유일한 데이터 변경은 P5-1(SQLite 보충)이며 사전 백업·dry-run·parity 체크가 게이트.
- **AUTH_SECRET**: 배포 전 머신 환경변수 설정, 설정 전엔 서버가 뜨지 않는다는 점을 소유자에게 미리 알린다.

---

## 부록 A. 학생 접근 허용 엔드포인트 초안 (Codex가 grep으로 확정·보완)

| 엔드포인트(엔드포인트 이름) | 메서드 | 호출처 | 비고 |
|---|---|---|---|
| `/api/student/bootstrap` (`api_basic.api_student_bootstrap`) | GET | `student.js:1481` | sid 범위 검사는 핸들러 내부 |
| `/api/progress?sid=` (`api_basic.api_progress`) | GET | `student.js` | P6-4 후 필터 필수 |
| `/api/feedback` | POST | 확인 필요 | |
| `/api/tests-config` (`api_tests.get_tests_config`) | GET | `tests.js:332` | 공개 세션 검사 내장 |
| `/api/submit-test`, `/api/ocr-test-sheet*`, `/api/tests-records`(학생 범위) | POST/GET | `tests.js`, `student.js` | |
| `/api/watch/latest`, `/api/watch`, `/api/watch-status` (`api_watch.*`) | GET/POST | `student.js:1476` 등 | 학생 시청 진행 |
| `/api/announcements` GET, `/api/announce-status`, `/api/announce-ack`, `/api/announce-submit` | GET/POST | 학생 페이지 | 이미지 업로드류는 관리자 |
| `/files/<path>` (`api_fs`) | GET | 자료 열람 | `verify_student_material_access_scope.js` 범위 검사 유지; `/api/fs/*`는 관리자 |
| `/api/get-url` (`api_kollus`) | GET | 영상 재생 | 학원망 게이트 유지 |
| `/api/kollus/lms-callback` | GET/POST | **외부 Kollus 서버** | 절대 Basic 인증 금지 |
| `/api/auth/*` (`api_auth`) | POST/GET | `auth.js` | 자체 JWT |
| `/api/mobile/*` (학생앱) | — | 별도 블루프린트 | 가드 대상 아님(공개 표면이 이미 관리) |
| 레거시 폴백 GET(`/api/students`, `/api/videos`, `/api/updates`, `/api/materials`, `/api/mat-assign`, `/api/absent`, `/api/logs?date=`) | GET | `student.js:1491-1500` | 1주 `log` 관찰 후 폴백 제거 → enforce |

## 부록 B. 락 순서 (여러 저장소를 만질 때 반드시 이 순서로 획득)

`STU → VID → MAT → ASN → EXTRA → UPD → PRG → WATCH → TESTS → TESTS_CFG → LOGS → ABS → 나머지 알파벳순`. 락 파일 이름은 항상 `<파일>.lock`(외부 스크립트·기존 `_updates_lock` 등과 호환).

## 부록 C. 새 환경변수

| 이름 | 값 | 기본(코드) | 첫 배포 권장 | 단계 |
|---|---|---|---|---|
| `ADMIN_API_GUARD` | `off/log/enforce` | `enforce` | `log` 2~3일 → `enforce` | P1-1 |
| `AUTH_SECRET` | 64자 난수(Machine) | 없음→기동 거부 | 배포 전 설정 | P1-2 |
| `ALLOW_EPHEMERAL_AUTH_SECRET` | `1` | 미설정 | 개발/CI만 | P1-2 |
| `JSON_STORE_REVISION_MODE` | `soft/strict` | `soft` | 호출처 전환 후 `strict` | P3-1 |
| `UPDATES_GET_ENSURE` | `1` | 미설정 | 문제 시 롤백용 | P3-3 |
| `DATA_MIRROR_SYNC` | `1` | 미설정(비동기) | 스크립트/롤백 | P4-2 |
| `LOG_STORE_MODE` | `dual/sqlite` | `sqlite` | P5-1 후 `sqlite` | P5-2 |
| `LOG_JSON_EXPORT` | `0/1` | `1` → 다음 릴리스 `0` | `1` | P5-3 |
