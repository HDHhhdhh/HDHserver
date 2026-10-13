# 격리 디자인 테스트 서버

운영 Waitress `0.0.0.0:8003`을 켠 채 디자인·브라우저 검증용 서버를 `127.0.0.1:8004`에서 실행하는 절차다. 테스트 서버는 `instance/isolated-design-server/app`에 현재 코드의 스냅샷을 만들고, JSON·SQLite·files·data를 그 디렉터리 안에서 새로 생성한다. 운영 runtime은 복사하지 않는다.

## 명령

```powershell
# 시작: 코드 스냅샷 갱신 후 8004 실행
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_isolated_design_server.ps1 Start

# 상태
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_isolated_design_server.ps1 Status

# 프런트엔드 파일 스냅샷 갱신
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_isolated_design_server.ps1 Refresh

# Python/route 변경까지 다시 읽도록 재시작
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_isolated_design_server.ps1 Start -Restart

# 격리 runtime에 OCR migration을 별도로 적용한 뒤 기능 ON 검증
$env:STUDENT_TEST_OCR_ENABLED = "1"
$env:STUDENT_TEST_OCR_RUNTIME_ROOT = "C:\server-ocr"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_isolated_design_server.ps1 Start -Restart

# 종료
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_isolated_design_server.ps1 Stop
```

기본 주소는 `http://127.0.0.1:8004`다. 데모 화면은 기존 `/demo/...` 경로를 사용한다.

## 격리 계약

- 복사 대상은 `app.py`, `core/`, `routes/`, `static/`와 학생 시험 OCR 실행에 필요한 worker다. worker 목록은 관리 스크립트의 `Sync-CodeSnapshot`이 소유한다. migration·운영 데이터·Drive cache는 복사하지 않는다.
- 루트 JSON, SQLite, `data/`, `files/`, `instance/`, 백업과 미러는 운영에서 복사하지 않는다.
- 테스트 runtime은 테스트 서버를 재시작해도 유지된다.
- OCR flag·runtime 경로는 시작 명령의 환경에서만 전달하며 asset·답지 cache 경로는 격리 app 아래로 강제한다. 운영 migration이나 Drive cache를 자동 복사하지 않는다.
- marker와 코드 루트가 일치하는 관리 서버는 loopback 전용이므로 학생 OCR UI QA에 한해 학원망 gate를 통과한다. 운영 코드 루트와 일반 개발 서버에는 이 예외가 적용되지 않는다.
- 포트 8004가 다른 프로세스에 점유돼 있으면 자동 종료하지 않고 실패한다.
- Start·Stop·Status·Refresh는 포트별 OS mutex로 직렬화한다. 시작 시 해당 invocation이 실행한 프로세스의 ancestry·시작 시각과 정확히 하나의 loopback listener를 확인하며 HTTP 검사·receipt 기록 후에도 소유권을 재확인한다. 시작 실패 정리는 그 invocation의 확인된 프로세스에만 한정한다.
- 중지 시 기록된 PID와 시작 시각, 명령행이 모두 맞는 테스트 서버만 종료한다.
- 기존 version 1 receipt의 필드는 계속 지원한다. 새 lineage 필드가 없다는 이유로 정상 관리 서버를 unknown owner로 바꾸지 않는다. 소유권 조회 실패는 빈 포트로 취급하지 않는다.
- 테스트 서버는 loopback 전용이고 public student app·push·Kollus callback을 비활성화한다.
- 운영 코드 폴더에서 직접 `waitress-serve ... app:app` 또는 `app.run(...)`을 실행하는 방식은 계속 차단한다.


## 격리 QA 인증

관리자 페이지의 HTTP Basic 인증은 격리 서버에서도 유지한다. QA 전용 `ACADEMY_ADMIN_USERNAME`과 `ACADEMY_ADMIN_PASSWORD_HASH`를 manager 실행 프로세스에만 주입하고 생산 인증 파일이나 운영 데이터를 읽어 복사하지 않는다. 시작 뒤 호출자의 환경값은 복원한다. QA 인증은 시작한 격리 프로세스가 살아 있는 동안 유지되며, 다음 재시작에는 다시 주입해야 한다. 브라우저는 이 계정으로 127.0.0.1:8004에 정상 로그인한다. 인증 때문에 Basic 보호를 제거하거나 서버를 외부에 노출하지 않는다.

## 승인된 Kollus 영상 QA

D-18은 지정한 합성 학생·영상만 로컬 재생과 browser watch 저장을 허용한다. 범위와 검증 조건의 소유자는 [canonical §18](PROJECT_FUNCTIONS_AND_LOGIC.md#관리형-8004-영상-전용-qa-예외-d-18)이다. 일반 Start는 이 예외를 끈다. 승인한 검증에만 아래 명령을 사용하며, 기존 QA 인증값을 같은 방식으로 주입한다.

```powershell
./scripts/manage_isolated_design_server.ps1 -Action Status
./scripts/manage_isolated_design_server.ps1 -Action Start -Restart -KollusVideoQa
```

Status의 `kollusVideoQaEnabled: true`와 기본 서버 상태 검사를 확인한다. Chrome에서 `http://127.0.0.1:8004`의 기기 앱 권한도 필요하다. 검증을 마치면 Status 후 `-Action Start -Restart`로 예외를 끄고 `kollusVideoQaEnabled: false`와 두 서버의 가용성을 확인한다. 테스트 기록은 격리 runtime에 보존하며 운영으로 병합하지 않는다.
