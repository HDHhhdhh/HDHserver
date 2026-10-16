# 학생 모바일 앱 최소 운영 runbook

이 문서는 운영 장비에서 `app.5a-math.com`을 Flask/Waitress 프로세스 하나에 연결하는 배포 절차다. 개발 장비의 `dev-app.5a-math.com` 분리와 cutover/rollback은 [student-app-domain-split.md](student-app-domain-split.md)를 함께 따른다. 문서 작성과 `verify_student_app_deployment.ps1 -DryRun`은 DNS, Tunnel, Task Scheduler, key, backup 또는 runtime data를 변경하지 않는다. Phase 14에서 temp-only Todo 14 배포 계약을 기본 안전검증에 편입했지만, fixture PASS는 실기기·실제 host·Push 공급자 증거가 아니다. 실제 변경은 실기기 검증과 사용자 production 승인 후에만 수행한다.

## 고정 계약

| 항목 | 값 |
|---|---|
| 서버 root | 이 저장소의 절대 경로 |
| Python | `venv\Scripts\python.exe` (Python 3.12) |
| Waitress | `scripts\run_waitress_server.ps1`, `0.0.0.0:8003` |
| 공개 hostname | `app.5a-math.com` |
| Tunnel origin | `http://127.0.0.1:8003` |
| Push worker | `scripts\run_student_push_worker.ps1` (기존 공지 → 수업/숙제 스캔 → 일반 알림 전달) |
| Push task | `Academy Student Push Delivery`, 1분 주기(Task XML `PT1M`), `IgnoreNew` |
| private key | `instance\student-app-vapid-private.pem` |
| public key 사본 | `instance\student-app-vapid-public.txt` |

운영 장비에는 새 admin hostname, Caddy, hosts 파일, 두 번째 Flask 앱 또는 두 번째 listener를 만들지 않는다. 개발 listener는 별도 개발 장비와 `dev-app` exact host에서만 운영한다. private key, Tunnel credential, cookie, CSRF, subscription endpoint, 공지 본문과 학생 식별자는 Git·공유 evidence·로그에 남기지 않는다. 승인된 runtime backup은 접근 제한된 별도 저장소에서 [RULE-DATA-001](SERVER_RULES_INDEX.md#rule-data-001)과 [정본 §14](PROJECT_FUNCTIONS_AND_LOGIC.md#백업-확정-경계)를 따른다. private key와 credential은 그 backup에서도 제외한다.

## 1. 운영 데이터 backup

먼저 Push task를 disable하고 실행 중인 worker가 없음을 확인한다. 일관된 SQLite 복사본을 위해 짧은 점검 창에 `Academy Server Waitress`를 중지하고 8003 listener와 해당 runner의 shadow guard가 모두 종료된 뒤 backup한다. 아래 `$backupRoot`는 저장소 밖의 접근 제한된 위치여야 한다.

```powershell
$serverRoot = (Resolve-Path .).Path
$backupRoot = 'D:\academy-runtime-backups'
Stop-ScheduledTask -TaskName 'Academy Student Push Delivery' -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName 'Academy Server Waitress' -ErrorAction Stop
if (Get-NetTCPConnection -LocalPort 8003 -State Listen -ErrorAction SilentlyContinue) { throw '8003 is still listening' }
# 정본 §14에 따라 이 runner에 연결된 shadow guard의 종료도 확인한 뒤 진행한다.
$archive = & "$serverRoot\venv\Scripts\python.exe" "$serverRoot\scripts\backup_runtime_data.py" --out $backupRoot
if ($LASTEXITCODE -ne 0) { throw 'backup failed' }
```

archive의 `MANIFEST.json`에서 현재 존재하는 `auth_accounts.json`과 독립 `app.sqlite` snapshot의 membership·크기·SHA-256을 확인하고, 임시 복원의 `integrity_check`가 `ok`인지 확인한다. 커밋된 WAL 내용은 native SQLite snapshot에 포함되며 WAL/SHM sidecar는 별도 복구 파일로 넣지 않는다. `instance/student-app-vapid-private.pem`과 `instance/student-app-vapid-private.pem.*`는 archive와 manifest에 없어야 한다. `scripts/backup_runtime_data.py`가 이 exact exclusion을 적용하므로 key 생성 뒤에도 같은 backup 절차를 계속 사용할 수 있다. archive 이름과 SHA-256만 Todo 14 기록에 남기고 내용은 evidence로 복사하지 않는다.

## 2. dependency 설치와 version 확인

현재 venv에만 설치한다. system Python이나 이전 PC에서 복사한 venv를 사용하지 않는다.

```powershell
& .\venv\Scripts\python.exe -m pip install -r .\requirements-student-app.txt
& .\venv\Scripts\python.exe -c "import importlib.metadata as m,sys; assert sys.version_info[:2] == (3,12); assert m.version('pywebpush') == '2.3.0'; print('dependency-ok')"
```

## 3. VAPID key 최초 1회 생성

private/public 목적지 중 하나라도 이미 있으면 generator는 overwrite를 거부한다. 재실행으로 key를 회전하지 않는다. `mailto:`에는 운영 연락 주소를 넣되 아래 placeholder를 그대로 쓰지 않는다.

```powershell
$serverRoot = (Resolve-Path .).Path
$privateKey = "$serverRoot\instance\student-app-vapid-private.pem"
$publicKey = "$serverRoot\instance\student-app-vapid-public.txt"
& "$serverRoot\venv\Scripts\python.exe" "$serverRoot\scripts\generate_student_vapid_key.py" --private-path $privateKey --public-output $publicKey
if ($LASTEXITCODE -ne 0) { throw 'VAPID generation failed or destination already exists' }
$userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $privateKey /inheritance:r /grant:r "*$($userSid):(F)" '*S-1-5-18:(F)' '*S-1-5-32-544:(F)'
if ($LASTEXITCODE -ne 0) { throw 'VAPID ACL hardening failed' }
```

private key는 읽거나 출력하지 않는다. public key 파일만 브라우저 공개 키 대조에 사용할 수 있다. key 회전은 별도 incident/change 절차이며 기존 key를 덮어쓰지 않는다.

## 4. Waitress 작업 환경

`Academy Server Waitress`가 실행되는 동일 machine scope에 다음 이름을 설정한다. 값은 로그에 출력하지 않는다. 첫 시작은 반드시 flag off와 비어 있지 않은 test SID allowlist다.

```text
STUDENT_APP_PUBLIC_ENABLED=0
STUDENT_APP_PUBLIC_HOST=app.5a-math.com
STUDENT_APP_LEGACY_HOST=5a-math.com
STUDENT_APP_LEGACY_REDIRECT_ENABLED=0
STUDENT_APP_TRUSTED_PROXIES=127.0.0.1/32,::1/128
STUDENT_APP_CANARY_SIDS=<comma-separated-test-sids>
STUDENT_APP_SESSION_COOKIE_SECURE=1
STUDENT_APP_SESSION_SAMESITE=Lax
STUDENT_APP_DASHBOARD_ENABLED=0
STUDENT_APP_HOMEWORK_ENABLED=0
STUDENT_APP_REMINDERS_ENABLED=0
STUDENT_APP_FOCUS_ENABLED=0
STUDENT_APP_VAPID_SUBJECT=mailto:<operations-address>
STUDENT_APP_VAPID_PRIVATE_KEY_PATH=<server-root>\instance\student-app-vapid-private.pem
ACADEMY_ADMIN_USERNAME=<academy-admin-id>
ACADEMY_ADMIN_PASSWORD_HASH=<werkzeug-scrypt-or-pbkdf2-hash>
TRUST_PROXY_HEADERS=1
```

PowerShell의 `[Environment]::SetEnvironmentVariable(name, value, 'Machine')`을 관리자 세션에서 사용하거나 기존 작업 등록 시스템에 같은 이름을 넣는다. 관리자 비밀번호는 평문 환경변수로 저장하지 않고 `werkzeug.security.generate_password_hash()` 결과만 `ACADEMY_ADMIN_PASSWORD_HASH`에 넣는다. private key의 **내용**은 environment에 넣지 않는다. 값 변경 후 `Academy Server Waitress`를 재시작해야 새 프로세스가 읽는다. runner는 Task Scheduler의 오래된 환경 block을 피하려고 위 machine 값만 명시적으로 다시 읽는다. `run_waitress_server.ps1`가 exact venv Waitress와 port 8003을 사용하며 다른 listener를 추가하지 않는다. Waitress는 loopback proxy의 `X-Forwarded-Proto`만 신뢰하고 다른 forwarded client/host header는 지운다. 실제 client authority는 app의 단일 `CF-Connecting-IP` 검증에 남겨 둔다. `STUDENT_APP_PUBLIC_ENABLED`는 앱 호스트 공개를, `STUDENT_APP_LEGACY_REDIRECT_ENABLED`는 기존 사이트 루트의 앱 전환을 각각 제어한다. 두 번째 값은 사용자 최종 승인 전까지 반드시 `0`으로 유지한다.

### 서버 내부 운영 모드 재조회

학생앱 설정과 별도로 [set_server_mode_environment.ps1](../scripts/set_server_mode_environment.ps1)이 관리자 가드·로그 저장·revision·mirror 관련 모드를 재조회한다. 정확한 허용 목록은 helper에 둔다. 각 값은 Machine 우선, 비어 있으면 User를 사용한다. 양쪽이 모두 비면 상속된 Process 값을 지워 코드 기본값을 사용한다. 모든 읽기가 성공한 뒤 Process에 반영하며, 읽기 오류가 나면 Waitress 실행 전에 중단한다. 이 helper는 영구 환경변수를 쓰거나 값을 출력하지 않는다.

일반 runner 실행은 자동으로 재조회한다. 기존 `-DevelopmentIsolation` 실행은 Process 설정을 유지한다. 현재 운영 작업도 이 옵션을 사용하므로, 새 운영 모드 적용 시 검토한 예약 작업 인자에 **`-ReloadServerModes`를 추가해야 한다**. helper 코드 배포만으로 현재 운영 모드가 변경됐다고 판단하지 않는다. 기존 학생앱·인증·시크릿의 설정 우선순위는 유지한다. 예약 작업 인자 변경과 재시작은 승인된 운영 반영 때 수행한다.

## 5. Push delivery task 등록

다음은 production 승인 뒤 관리자 PowerShell에서 한 번 실행하는 등록 템플릿이다. runner 자체의 named mutex와 Task Scheduler의 `IgnoreNew`가 중첩 실행을 함께 막는다.

```powershell
$serverRoot = (Resolve-Path .).Path
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$serverRoot\scripts\run_student_push_worker.ps1`""
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $serverRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'Academy Student Push Delivery' -Action $action -Trigger $trigger -Settings $settings -Principal $principal
Disable-ScheduledTask -TaskName 'Academy Student Push Delivery'
```

등록 직후에는 disabled 상태를 유지한다. runner의 dry-run만 먼저 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_student_push_worker.ps1 -DryRun
```

실제 task command에는 `-DryRun`을 넣지 않는다. runner는 exact venv Python으로
`deliver_student_push_outbox.py --once`, `enqueue_student_reminders.py --once`,
`deliver_student_notification_outbox.py --once`를 차례로 한 번씩 실행한다. 새 알림용
SQLite migration과 focused 검증이 끝나기 전에는 `STUDENT_APP_REMINDERS_ENABLED=0`을 유지한다.

### 개발 격리 Push 작업

`dev-app.5a-math.com` 검증은 production task와 키를 재사용하지 않는다. 개발 키는 개발
작업트리의 ignored `instance\student-app-vapid-private.pem`에 두고, Waitress와 worker에
`-VapidSubjectOverride`와 `-VapidPrivateKeyPathOverride`를 항상 한 쌍으로 전달한다.
worker에는 `-PublicHostOverride dev-app.5a-math.com`, 비어 있지 않은 개발 canary SID,
`-PublicEnabledOverride 1`, 개발 작업트리 `-RuntimeRootOverride`,
`-DevelopmentIsolation`도 함께 전달한다. 이 조합은 다른 host/runtime/key 경로를
fail-closed로 거부한다.

개발용 예약 작업은 production과 다른 이름으로 등록하고 실기기 구독이 확인될 때까지
disabled 상태를 유지한다. 준비 확인은 동일 인자를 사용한
`run_student_push_worker.ps1 -DryRun`으로만 수행한다. `STUDENT_APP_REMINDERS_ENABLED=0`이어도 legacy 공지 worker는
실제 outbox를 전송할 수 있으므로, 구독 대상과 outbox를 확인하지 않은 non-dry 실행은 금지한다.

공지나 기존 outbox를 만들지 않는 개발 실기기 1회 검증은 전용 도구만 사용한다. 이 도구는
`dev-student-001` 합성 학생, 현재 계정/세션 바인딩, 전체 활성 구독 정확히 1개, legacy/generic
대기 큐와 schedule pending 0개, 개발 작업트리의 VAPID key를 모두 다시 확인한다. 구독 ID,
endpoint, 구독 key, 계정 ID, SID는 명령 인자·출력·증거에 기록하지 않는다.

```powershell
.\venv\Scripts\python.exe -X utf8 .\scripts\send_student_test_push.py `
  --dry-run
```

dry-run이 `ready:true`일 때만 출력된 불투명 `targetCommitment`와 `approvalId`를 별도 사용자
승인과 함께 정확히 한 번 전송한다. 이 값들은 endpoint나 식별자를 복원하지 않으며,
`approvalId`는 ignored `instance`의 최소 승인 레코드와 함께 5분 내 한 번만 소비된다. dry-run
뒤 권한·세션·구독·대기 큐가 바뀌거나 같은 승인을 재사용하면 전송을 거부한다. 이 경로는 예약
작업을 켜거나 공지/알림 outbox를 lease하지 않는다. 성공은 불투명한 receipt ID만 출력한다.
provider 404/410은 전송 대상 한 행만 binding 전체 일치 조건으로 revoke하고, 429/5xx/timeout은
DB를 변경하지 않은 채 `retryable:true`로 끝난다. 테스트 payload의 provider TTL은 60초이며,
서비스워커도 `dev-app.5a-math.com`에서만 `push_test`를 표시한다.

```powershell
.\venv\Scripts\python.exe -X utf8 .\scripts\send_student_test_push.py `
  --send --confirm SEND_DEV_TEST_PUSH_ONCE `
  --target-commitment <dry-run-targetCommitment> `
  --approval-id <dry-run-approvalId>
```

timeout/429/5xx의 `retryable:true`는 자동 재시도 지시가 아니다. provider 수락 여부가 불명확할
수 있으므로 기기 수신을 먼저 확인하고, 다시 보낼 때에는 새 dry-run과 별도 승인을 받는다.
승인 레코드와 그 임시/소비 파일은 runtime backup에서 제외하며 `approvalId`는 장기 증거에
남기지 않는다.

## 6. named Cloudflare Tunnel

Cloudflare credential이 없으면 여기서 `BLOCKED_NO_CLOUDFLARE_AUTH`로 중단한다. 문서 또는 verifier가 DNS/Tunnel을 생성하지 않는다. 기존 또는 신규 named tunnel의 locally-managed config 예시는 다음과 같다. credential 파일과 config는 저장소 밖의 ACL 제한 위치에 둔다.

```yaml
tunnel: <tunnel-uuid>
credentials-file: C:\ProgramData\cloudflared\<tunnel-uuid>.json
ingress:
  - hostname: app.5a-math.com
    service: http://127.0.0.1:8003
  - service: http_status:404
```

승인된 운영 단계에서만 다음을 실행한다.

```powershell
cloudflared tunnel ingress validate
cloudflared tunnel ingress rule https://app.5a-math.com
cloudflared tunnel route dns <tunnel-name-or-uuid> app.5a-math.com
cloudflared tunnel --config C:\ProgramData\cloudflared\config.yml run <tunnel-name-or-uuid>
```

Cloudflare 공식 모델은 public hostname 하나를 local service 하나에 매핑하며, locally-managed ingress의 마지막 규칙은 catch-all이어야 한다. 참고: [Routing](https://developers.cloudflare.com/tunnel/routing/), [configuration file](https://developers.cloudflare.com/tunnel/advanced/local-management/configuration-file/), [run parameters](https://developers.cloudflare.com/tunnel/advanced/run-parameters/).

## 7. read-only preflight와 canary

flag off 상태에서 server/task/key/tunnel config가 준비된 뒤 실행한다. `Preflight`는 exact Host+HTTPS proxy request의 `/app`이 404인지 확인한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_student_app_deployment.ps1 -DryRun -Phase Preflight -TunnelConfigPath C:\ProgramData\cloudflared\config.yml
```

exit `0`은 PASS, exit `3`과 `BLOCKED_*`는 외부 상태 미준비, exit `2`와 `FAIL_*`는 잘못된 구성이다. 어느 것도 secret 값을 출력하지 않는다. fixture mode PASS는 verifier 계약만 증명하며 rollout 증거가 아니다.

코드·runbook 계약만 집중 검증하려면 아래 명령을 사용한다. Windows에서는 PowerShell syntax와 production/dev/rollout 실패 주입까지 포함한 전체 temp fixture를 실행한다. `-FixtureMode`는 `-DryRun`과 environment/Python/key-policy/task/Tunnel/listener/health snapshot 경로가 모두 없으면 live fallback 전에 즉시 실패한다. worker 검사는 `-DryRun`에서만 허용되는 고유 `Local\...ContractFixture...` mutex와 정리된 fixture 환경을 사용하므로 실제 예약 worker의 production mutex와 경합하지 않는다. Ubuntu CI 같은 비Windows 환경에서는 PowerShell을 실행하지 않고 동일 소스 계약과 backup 비밀 제외를 검사하며, 별도 `windows-latest` CI job이 전체 Windows 계약을 실행한다. 어느 모드도 live host, Task Scheduler, Tunnel, provider를 조회하거나 상태를 변경하지 않는다. runtime store는 mutation 감지를 위한 content/size/mtime fingerprint로만 읽고 쓰지 않는다. checker가 실패하거나 잘못된 receipt를 반환해도 process environment, working directory, backup root는 항상 복원되며 live runtime 변화도 검증 실패로 처리한다. 기본 `verify_refactor_safety.py` 실행에도 해당 플랫폼 모드의 계약 검사가 포함된다.

```powershell
.\venv\Scripts\python.exe -X utf8 .\scripts\verify_refactor_safety.py --only-student-mobile-deployment
```

Todo 14 자동검증과 네 실기기 준비 후에만 `STUDENT_APP_PUBLIC_ENABLED=1`로 바꾸고 Waitress를 재시작한다. 이 단계에서도 `STUDENT_APP_LEGACY_REDIRECT_ENABLED=0`과 test/staff SID allowlist를 유지한다. 따라서 `5a-math.com`은 기존 로그인과 `/student/<sid>` 흐름을 계속 사용하고, 앱 canary는 `app.5a-math.com/app`을 직접 연다. hostname을 연결한 다음 아래 검증이 PASS해야 한다. HTTPS `/app` 200, `Cache-Control: no-store`, secure host-only session cookie와 `SameSite=Lax`는 Browser Network/Application evidence로 별도 확인한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_student_app_deployment.ps1 -DryRun -Phase Canary -TunnelConfigPath C:\ProgramData\cloudflared\config.yml
Enable-ScheduledTask -TaskName 'Academy Student Push Delivery'
```

실제 test 공지 1건의 delivery, 404/410 subscription 정리와 transient retry를 전용 test account로 확인한다. 승인 전에는 allowlist를 비우거나 `STUDENT_APP_LEGACY_REDIRECT_ENABLED`를 켜지 않는다. Todo 14, F1–F4와 사용자 production 승인을 모두 받은 뒤에만 allowlist를 비우고 `STUDENT_APP_LEGACY_REDIRECT_ENABLED=1`로 바꾼 다음 `-Phase Expanded -RolloutApproved`로 재검증한다. 승인된 redirect는 쿼리 없는 exact `/`의 GET/HEAD만 `https://app.5a-math.com/app`으로 302 전환하며 기존 deep link와 쿼리 요청은 그대로 둔다.

## 8. rollback

cross-SID, public admin/API 노출, academy gate 우회 또는 credential-change 우회가 하나라도 나오면 다음 순서를 지킨다.

1. 먼저 `STUDENT_APP_LEGACY_REDIRECT_ENABLED=0`, 이어서 `STUDENT_APP_PUBLIC_ENABLED=0`으로 바꾸고 `Academy Server Waitress`를 재시작한다. `5a-math.com` 기존 루트 200과 exact public Host `/app` 404를 확인한다.
2. Cloudflare dashboard/API에서 `app.5a-math.com` published application을 disable/remove한다. local ingress에서는 해당 hostname 규칙을 제거하고 catch-all 404를 유지한 뒤 tunnel을 재시작한다. tunnel 자체나 다른 hostname은 삭제하지 않는다.
3. `Disable-ScheduledTask -TaskName 'Academy Student Push Delivery'`로 delivery를 중지한다.

rollback은 코드/flag/Tunnel hostname/task 상태만 되돌린다. `app.sqlite`, `auth_accounts.json`, 계정, session, subscription, outbox 또는 additive table을 삭제하거나 초기화하지 않는다. 일반 rollback에서 backup archive를 worktree에 bulk extract하지 않는다. runtime 손상이 별도로 확인된 경우 현재 runtime을 먼저 새 archive로 보존하고, 이전 archive를 임시 격리 디렉터리에만 풀어 manifest/hash를 검증한 다음 승인된 targeted merge로 기존 additive table을 보존한다.

## 로그와 증거

허용되는 기록은 명령 exit code, `PASS`/`FAIL_*`/`BLOCKED_*`, package version, task 이름, port, hostname, backup archive ID/hash뿐이다. private/public key 원문, credential/token, environment 값, cookie/CSRF, subscription endpoint/key, 공지 본문과 SID는 기록하지 않는다. verifier transcript는 redacted 상태 그대로 Todo 13 evidence에 저장하고 fixture와 실제 host 결과를 구분한다.
