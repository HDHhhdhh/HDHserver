# 안정성·속도 개선 실행 기록

기준 지시: Drive `Codex지시문_HDHserver.md`와 [원본 계획](IMPROVEMENT_PLAN.md). 작업 브랜치는 `codex/stability-speed-impl`이다. 원본 계획은 보존하고, 최신 운영 코드와 다른 전제는 아래에 기록한다.

## 승인된 실행 방식

- 2026-10-13 사용자 선택: 원격 main에서 시작한 브랜치에 최신 운영 브랜치도 병합해 보존한다.
- 운영 백업은 오프라인 검증에만 사용한다. 관리형 127.0.0.1:8004는 합성 데이터로 검증한다. 8013 복사본 서버와 운영 데이터의 QA 초기값 사용은 승인되지 않았다.
- 기존 영구 AUTH_SECRET을 재사용한다. Machine과 User 중 영구 설정을 읽는 현행 runner 계약을 보존한다. 시크릿 값과 런타임 자료는 Git에 넣지 않는다.
- 2026-10-13 사용자 선택: MASTER_PW의 12자 최소 길이 요구는 적용하지 않는다. 기존 비밀번호를 유지하며 사용 기록만 보강한다.
- OCR은 별도 전담 범위다. 기존 커밋을 보존하며 이 작업에서 OCR 기능·데이터를 수정하지 않는다.
- 코드 구현, 합성 검증, 운영 반영, 운영일 관찰을 구분한다. 실제 관찰 기간을 테스트 실행으로 대체하지 않는다.

## 최신 코드에 맞춘 계획 해석

- 외부 관리자 Basic 인증은 이미 구현돼 있다. 새 log/off 모드가 이 보호를 풀지 않게 한다. 올바른 Basic을 가진 원격 관리자 접근도 보존한다.
- 로그인 저장소의 strict read와 잠금, 로그의 SQLite 충돌 시 두 저장소 무쓰기, complete-snapshot 표식, person identity/material/absence journal 경계는 기존 구현을 재사용한다.
- JSON 저장소 일원화가 journal coordinator를 대체하지 않는다. 각 소유자의 기존 잠금 순서와 unknown field·명시적 삭제 계약을 유지한다.
- 오늘 SID 존재만으로 자동 배정의 rebase·결석 barrier를 건너뛰지 않는다.
- 로그 revision에는 같은 초 수정과 삭제도 반영한다. MAX(updated_at)만으로 변경 유무를 판정하지 않는다.
- SQLite 단독 전환은 전체 유효 map 정합·parity·백업·복원 검증 후에 적용한다. 충돌을 임의로 덮어쓰지 않는다.
- 이미 제거된 레거시 파일은 다시 만들지 않는다. 다음 릴리스용 호환 스위치 제거는 운영 관찰 뒤에 판단한다.

## P0 준비

운영 소스 기준선 `ffbff9a`의 전체 기본 하네스는 exit 0, 105개 그룹 통과, 실패 0이다. 운영 checkout은 처음에 clean이었고 운영 브랜치를 바꾸지 않았다. 원격 main `4fe2ea4`와 운영 소스는 4/111개 커밋으로 갈라져 있었다.

운영 감시 프로세스의 마지막 로그 쓰기가 첫 백업의 검증을 실패시켰다. 그 파일은 확정되지 않았고 서비스를 즉시 복구했다. 두 번째 정지에서는 정확한 runner와 guard의 종료까지 기다린 뒤 native SQLite snapshot·manifest/checksum 검증을 통과한 백업을 만들었다. 운영 ping과 공개 학생 app은 복구 후 HTTP 200이었다. 백업 및 오프라인 자료는 로컬에서만 보존한다.

Chrome 운영 화면의 일반 탐색/새로고침 3회 기준선은 문서 load 평균 856.3ms, 날짜별 logs 요청 평균 263.2ms, logs 응답 30,306bytes다. 이는 브라우저 네트워크 기록이며 표가 사용 가능해지는 시간이나 모든 저장 동작의 체감 지연을 뜻하지 않는다. 임시 측정 탭을 닫았고 기존 사용자 탭은 유지했다.

통합은 운영의 백지 체크·고정 열 너비·학생 운영 팝업·revisioned 저장·loader/epoch 보호를 보존한다. main의 날짜 parser/선택 날짜 추적·화면 탐색·접근 가능한 작업 버튼을 최신 구조에 맞춘다. 제거된 낙관적 행 이동 경로는 복원하지 않는다.

통합 후 전체 기본 하네스는 exit 0, 107개 그룹 통과, 실패 0이다. 최신 날짜 parser와 calendar generation을 추출 VM에도 연결했다. 기존 단언을 유지하고 잘못된 날짜 회귀를 추가했다. 테스트 인쇄기의 catalog byte hash는 Windows의 줄바꿈 자동 변환으로 달라질 수 있어 `.gitattributes`에서 해당 추적 CSV의 바이트를 보존한다. catalog 내용과 기존 매핑을 바꾸지 않았다. 인쇄기 검증은 승인된 오프라인 백업의 tests-config를 기존 read-only 입력 옵션으로 읽었으며 QA 서버에 넣지 않았다.

합성 관리자 인증 주입과 8004 시작 명령은 자동 승인 검토에서 정책상 차단됐다. 사용자가 문서의 process-only 절차로 직접 실행했다. manager managed/HTTP 200, 단일 127.0.0.1 listener, 운영 ping/공개 app 200을 확인했다. 합성 학생만 QA API로 등록했다. Chrome에서 체크 저장·새로고침 유지, 날짜 전환, 운영 팝업의 숙제 통합 저장·서버 조회, 하원 처리·done 작업 버튼을 확인했다. 390px viewport의 실제 너비와 44px 작업 버튼도 확인하고 viewport를 복원했다. IAB 데모에서는 날짜·세 섹션 탐색·오늘/하원 백지 열·작업 버튼 DOM과 스크린샷을 확인했다. IAB 입력 조작은 도구 timeout으로 완주하지 못했으며 Chrome의 실제 저장 증거와 구분한다.

Chrome의 기존 127.0.0.1:8004 서비스 워커가 인증 탐색을 오프라인 화면으로 처리했다. 동일한 loopback listener의 localhost에서 정상 Basic 로그인 후 주소의 인증값을 제거해 검증했다. 서버 인증과 격리 설정은 유지했다. 스크린샷과 실행 로그, 합성 QA 자료는 로컬 audit/runtime에만 남긴다.

P0 준비·통합의 기본 및 Chrome 합성 저장 게이트가 통과했다. P1부터 코드 구현을 진행하며 운영일 관찰과 배포는 별도로 기록한다.

## P1 인증·시크릿·오류 처리

새 관리자 API 가드는 실제로 등록된 관리자 API에 적용한다. 기존 공개 학생 adapter와 외부 Basic 가드를 먼저 실행한다. 공개 adapter가 검증한 요청, 정확한 native 학생 경로·method, adapter가 등록한 mobile 경로만 학생 예외로 인정한다. 기존 원격 Basic 관리자 접근과 Kollus callback의 자체 인증을 유지한다. `off`는 신규 가드만 해제하고, `log`는 인증 없는 GET을 기록하되 관리자 쓰기는 차단한다. HEAD는 native handler의 쓰기 분기 위험 때문에 관찰 통과 대상에 넣지 않았다.

OCR의 두 기존 blueprint는 사용자 지시에 따라 이번 신규 가드의 대상에서 제외한다. 이름을 설치 시 고정하며 기존 외부 가드와 각 handler의 인증은 유지한다. OCR 소스·자료는 조사하거나 수정하지 않았다. 합성 fixture에서 제외 범위가 뒤늦게 늘어나지 않음과 기존 원격 인증 유지도 확인했다.

기존 영구 AUTH_SECRET을 유지하고 임의 secret 상태에서는 runtime 초기화 전에 시작을 거부한다. OS 임시 디렉터리의 실제 app import에서 거부와 무쓰기, 명시적인 임시 허용 후 시작을 확인했다. MASTER_PW 길이 제한은 승인된 예외에 따라 추가하지 않았다. 사용 기록에는 endpoint와 계정만 남기고 비밀번호·token은 남기지 않는다.

기본 HTTP 오류는 API/files/JSON Accept 요청에서 JSON으로 응답한다. 401 challenge와 405 Allow를 보존하고 일반 페이지 HTML도 유지한다. 각 endpoint의 기존 JSON 오류 계약은 바꾸지 않는다. shared `fetchJson`은 HTTP 실패를 먼저 검사하고 `fetchJsonOr`는 fallback 사용을 기록한다. 레거시 로그인 추천은 JWT와 현재 계정의 SID 연결을 검증하는 `/api/auth/schedules`에서 시간표만 읽는다. 전체 명단 및 연락처·메모는 반환하지 않는다.

개별 fixture에서 새 가드 19개 테스트, 오류 포맷, 시작 전 무쓰기, 계정별 시간표 범위, shared helper 및 기존 인증·추천·공개 surface 검사를 통과했다. 전체 기본 하네스는 exit 0, 108개 그룹 통과, 실패 0이다. 시작 거부의 실제 app-import fixture를 보강한 뒤 해당 개별 게이트와 compileall도 다시 통과했다.

사용자가 process-only QA 인증 절차로 backend를 재시작했다. Windows PowerShell 5.1이 BOM 없는 UTF-8의 한글 경로를 잘못 읽던 handoff 스크립트는 USERPROFILE 기반 ASCII 경로 조합으로 고쳤고 실제 5.1 파서에서 검증했다. 새 PID 33148의 manager managed/HTTP 200, 단일 loopback listener, 운영 ping/공개 app 200과 P1 파일의 snapshot hash 일치를 확인했다. 실제 미인증 관리자 GET은 JSON 401과 Basic challenge로 거부됐고 계정별 schedules는 token 누락 401을 반환했다. Chrome의 합성 학생 운영 팝업에서 숙제 통합 저장·저장 완료·닫힘·새로고침 후 동일 값 유지와 활성 저장 버튼을 확인했다. IAB 데모에서는 하원 탐색과 학생 팝업 열기를 확인했다. 스크린샷은 로컬 audit에만 보존한다. 기존 정책 차단을 우회하지 않았다. 운영 반영과 2~3 운영일 관찰은 아직 시작하지 않았다.

## P2 잠금·식별자·입력 경계

공통 load는 파일 부재의 기존 기본값만 유지하고 읽기·디코드 오류는 기록 후 전파한다. 학생 추가·필드 변경의 본문 형태와 이름을 검증하며, 기존 selfStudyDays와 testLevelDefaults 객체 편집은 허용한다. 알 수 없는 필드와 명시적 비움, identity journal, 응답 형태는 유지한다. 기존 SID 중복 방지의 무작위 시도 뒤 결정적인 빈 번호 탐색을 추가했다. 퇴원·영상 MID 수정·통째 명단 POST 등 이미 보호되거나 폐기된 경로는 다시 만들지 않았다.

레거시 인증은 canonical STU_PATH를 사용하며 누락·손상 명단을 빈 배열로 해석하지 않는다. 한 요청 안에서는 처음 검증한 명단 snapshot으로 계정 변경과 응답을 끝내고, 다음 요청과 요청 밖 helper는 다시 읽는다. 저장 뒤 재읽기 실패로 503을 반환하던 경로를 차단한다. 주말 시간표의 명단 읽기 오류는 ghost 권한 오류와 분리한다. 잘못된 일정 저장소는 원본 bytes와 mtime을 유지하며 쓰기·알림을 거부한다. auth_accounts의 기존 account lease와 mirror=False는 유지한다.

실제 소스의 JSON 오류·무쓰기 3개 테스트, 학생 본문·객체·식별자·16동시 작업자 100명 20회 저장·동일 이름 200명 추가 5개 테스트, 일정 오류 3개 테스트가 통과했다. 기존 계정 race와 16개 동시 로그인, 명단 오류 시 계정/session/password 불변, 요청별 1회 읽기와 다음 요청 최신성도 통과했다. 모든 fixture의 데이터 경로는 OS-temp다. 전체 기본 하네스는 exit 0, 109개 그룹 통과, 실패 0이다. 운영 백업의 오프라인 학생 103명은 중복·빈 SID 0건이었다.

사용자의 직접 실행 지시에 따라 기존과 같은 process-only QA 인증·manager 재시작 명령을 다시 제출했고 이번에는 성공했다. 이전 거부를 다른 실행 경로로 우회하지 않았다. PID 18884의 managed/HTTP 200·단일 loopback listener와 P2 파일의 snapshot hash 일치, 운영 ping/공개 app 200을 확인했다. Chrome에서 백지 체크 저장·새로고침 유지와 학생 UNIT 기본 레벨 객체 저장·새로고침 후 Lv.4 유지, API의 동일 값을 확인했다. 잘못된 객체 필드 저장은 400이고 학생 응답은 동일했다. 정상 extra/weekend GET은 200이다. IAB 데모 팝업 열기·닫기도 통과했다. 운영 반영은 하지 않았다.

## P3 충돌·로드 실패·조회 부작용

기본 updates GET을 저장소 조회로 분리하고 관리자 ensure-today POST를 추가했다. 기존 초기화·rebase·학생 bootstrap·결석 barrier를 유지한다. 20개 병렬 조회에서 모든 fixture store의 bytes·mtime·hash가 같았고, 인증 없는 초기화는 거부됐으며 두 번째 초기화는 다시 쓰지 않았다. 선택 날짜는 GET, 실제 오늘 경계는 POST이며 기존 오늘 화면의 역순 응답·저장 invalidation·자정 single-flight를 유지한다.

영상 목록은 VID 잠금 안에서 revision을 비교한다. 기존 MID/삭제 409가 먼저이며 성공은 빈 204를 유지한다. 초기 로드 실패와 잘못된 저장소는 저장을 차단한다. 영상 full-entrypoint VM은 새 버전 연쇄·409/428 후 대기 차단·초기 실패·다음 버전 없는 성공을 확인하고 기존 retry/수정 모드 no-POST 등 9개 그룹도 유지했다.

보강은 기존 PATCH에 SID delta를 추가한다. 네 캘린더 writer는 네 입력을 모두 검증한 뒤 첫 쓰기를 시작한다. 캘린더와 보강 팝업은 opening baseline으로 편집 의도를 고정하고 마지막 읽기 이후 원격 추가도 서버에서 보존한다. 퇴원 SID와 손대지 않은 슬롯은 유지하고 실제 응답 dates를 사용한다. Calendar listener 9개 그룹과 보강 full-entrypoint 10개 그룹에서 실패 무쓰기·session/date·slot 순서·delta fallback 금지를 확인했다. Calendar 전체 렌더는 별도 브라우저 게이트다.

실제 모듈 route 9개 테스트는 버전 충돌·실제 VID 잠금 대기·보강 동시 SID·기존 payload·손상 저장소·today no-op 후처리를 검증했다. 두 demo router에 동일 delta/revision/초기화 계약을 적용하고 session-only·오류 무쓰기·live forward 0을 확인했다. 기존 material/test/calendar revision과 class-log 충돌 계약은 재사용한다. 전체 기본 하네스는 exit 0, 109개 그룹 통과, 실패 0이다. 첫 실행의 GET/POST·delta·preload·cache-key 구형 단언은 기존 부정 사례와 CSS baseline hash를 유지한 채 실제 계약에 맞췄다. 독립 검토에서 찾은 캘린더 저장 owner 부재와 재시도 시 다음 결석분 중복 소비를 재현하고 수정했다. 슬롯은 잠그기 전 고정해 부분 결석을 보존하며 ESC도 같은 owner를 따른다. 보강 200 응답의 dates 누락·형식 오류·JSON 읽기 실패에서는 저장된 명단을 인정하고 후속 arrival/order를 중단한다.

관리형 PID 34880의 loopback/HTTP 200, 운영 ping·공개 app 200과 실제 backend snapshot hash를 확인했다. 20개 병렬 updates GET에서 8개 primary JSON의 bytes·mtime·hash가 같았다. Chrome 두 관리자 화면이 다른 학생을 저장한 뒤 양쪽 SID와 각각 [1,2]/[2] 타임이 서버와 새로고침 화면에 유지됐다. 실제 FullCalendar의 토요일 보강은 [2]로 저장돼 날짜 팝업의 2타임 학생과 예상 1명에 반영됐다. 영상의 첫 화면 제목 저장 후 오래된 두 번째 화면은 충돌 안내·저장 차단을 보여 줬고, 새로고침하면 첫 저장 제목과 저장 버튼이 복구됐다. IAB 데모 보강 저장·닫힘을 확인했고 실제 forwardedApiCalls 0, API resource 0이었다. duplicate 검증 탭은 닫았다. 스크린샷과 합성 자료는 로컬에만 보존한다. 운영 소스에는 아직 반영하지 않았다.

subagent는 P1/P2 경계 검토와 P3 route·실제 video/extra entrypoint·calendar listener fixture 및 독립 diff 검토에 사용했다. 실제 소스 적용·검증·결론은 hub가 맡는다. P4 JsonStore 초안은 local audit의 OS-temp 24개 테스트·111건 쓰기까지이며 실제 통합과 async mirror는 다음 작업이다.

## P4 JSON transport·미러

JsonStore와 lazy bounded registry를 실제 owner에 연결했다. 학생/영상/보강/weekend/학교캘린더/자료/updates/progress/watch와 계정 writer가 기존 lease·typed error·포맷·unknown field·journal 경계를 유지한다. 신원·자료·계정과 mutation precondition은 fresh read이며 일반 projection/progress cache는 방어 복사본이다. strict owner의 warm-cache 읽기 실패가 journal/쓰기를 시작하지 않는 실제 모듈 fixture를 추가했다. 레거시와 학생 앱 account writers 모두 미러 제외를 유지한다. 실제 credential·운영 데이터는 Git에 넣지 않는다.

미러는 허용된 tmp bytes만 queue에 넣고 새 excluded primary를 다시 읽지 않는다. 실제 Windows CRLF/compact byte parity·coalescing/dirty replay·동기 추월·별도 PID destination lease·alias 보호·snapshot 정책·5초 종료를 14개 fixture에서 확인했다. transport는 28개 테스트, owner는 whole auth blueprint·신원/자료 rollback/recovery 등을 포함한 12개 테스트를 통과했다. independent review에서 발견한 상대경로 변경과 warm-cache read-failure 회귀를 수정했다. Windows concurrent lock delete-pending은 원래 권한 오류를 보존하는 세 번 재시도로 보강하고 실제 16writer×20round 학생 저장 검사를 통과했다.

처음 전체 실행의 old read_text fault hook과 pure object path fixture를 실제 byte-read/새 transport seam에 맞췄다. 기존 실패 무쓰기·hook·literal·concurrency 단언은 유지했다. unused revision 직렬화와 fresh JSON의 중복 copy도 줄였다. 전체 기본 하네스의 최종 실행은 exit 0, 109개 그룹 통과, 실패 0이다.

관리형 8004를 hub가 직접 재시작했다. 합성 관리자 설정만 process scope에서 주입하고 부모 환경을 복원했다. PID 40092의 managed/단일 loopback/HTTP200, 운영 ping·공개 app200과 13개 backend snapshot hash를 확인했다. Chrome에서 합성 영상의 초록 배정을 흰색으로 저장해 none/manual watch hold/배정 제거를 API로 확인했고 reload 후에도 none/unchecked가 유지됐다. 두 log GET은 합성 runtime에서 200이었다. 실제 native Kollus 재생/학원망 검증과 이 단계의 synthetic fixture는 구분한다.

200회 순차 HTTP의 첫 before/after는 동시 full-suite 부하 속에서 mean 21.677→27.676ms, p95 26.541→33.859ms로 개선되지 않았다. 이 결과를 개선 수치로 사용하지 않는다. 최종 코드의 같은 synthetic dated assignment에서 각 200회 순차 HTTP를 비교했다. sync/async mean은 37.851→23.945ms(36.7% 감소), p50은 35.893→22.368ms, p95는 40.624→28.886ms(28.9% 감소)였다. 이는 loopback의 해당 저장 응답 측정이며 전체 팝업·운영망 속도를 보장하는 수치는 아니다. 최종 PID 11548에서 19개 backend source hash 일치와 동일 흰색 저장 상태를 다시 확인했다. IAB 데모에서도 보강 저장·닫힘·학생 추가와 forwardedApiCalls/API resource 0을 확인했다. manager의 snapshots=0 설정은 유지했고 최신 primary/mirror byte 일치는 2초 안에 확인했다. snapshot 정책 자체는 OS-temp fixture로 검증했다. 운영 배포와 실제 운영일 soak는 별도이며 아직 수행하지 않았다.

## 단계 상태

| 단계 | 구현 | 합성 검증 | 운영 적용·관찰 |
|---|---|---|---|
| P0 | 준비·통합 완료 | 전체 107그룹·Chrome 합성 저장 통과, IAB 렌더 확인 | 백업·서비스 복구 완료, 운영 소스 배포는 대기 |
| P1 | 인증·오류·계정 범위 구현 | 전체 108그룹·8004 실제 인증/Chrome 저장·IAB 탐색/팝업 통과 | log 첫 배포·2~3 운영일 관찰 대기 |
| P2 | 잠금·입력·SID·strict read 구현 | 전체 109그룹·8004 상태/객체 저장·400 무변경·두 브라우저 팝업 통과 | P1 관찰 뒤 반영 대기 |
| P3 | 충돌·delta·strict preload·GET 분리·저장 owner 구현 | 전체 109그룹·실제 2화면 보강/영상 충돌·FullCalendar·IAB 저장 통과 | P1 관찰 뒤 반영 대기 |
| P4 | 공통 transport·async mirror 실제 통합 | 전체109그룹·transport28·owner12·mirror14·실제 흰색 저장/reload·IAB 보강 저장 통과 | 배포·운영일 soak 대기 |
| P5 | 대기 | 대기 | 정합 충돌·parity 게이트 필요 |
| P6 | 대기 | 대기 | 전후 측정 필요 |
| P7 | 대기 | 대기 | 관찰 뒤 호환 스위치 정리 |
