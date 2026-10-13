# 학생 앱 개발 PC ↔ 운영 서버컴 인수인계

아래 고정된 `20260809` release·hash·영수증과 진행 상태는 당시 인수인계 예시로 보존한다. 현재 적용 승인이나 새 배포 지시가 아니며, 실제 실행 전에는 대상 노드의 현행 release·영수증·사용자 승인 범위를 다시 확인한다. 이 저장소의 현행 8004는 [관리형 격리 서버](isolated-design-server.md)를 따른다.

## 원칙

- 개발 PC는 `dev-app.5a-math.com`, 운영 서버컴은 `app.5a-math.com`만 담당한다.
- 코드 이동은 개발 → 운영 단방향이다. 운영 runtime은 운영 서버컴이 유일한 원본이다.
- `students.json`, `auth_accounts.json`, `app.sqlite`, 진도·로그·공지 JSON, `files/`, `instance/`, VAPID key, Tunnel credential은 코드 번들 또는 Drive에 넣지 않는다.
- 운영 → 개발 방향으로는 개인정보가 없는 상태 영수증만 전달한다.
- 같은 Cloudflare named Tunnel credential을 두 PC에서 실행하지 않는다.

## Google Drive 폴더 계약

두 PC가 공통으로 접근하는 `5A Student App - Dev Prod Handoff` 폴더를 사용한다.

```text
releases/        # runtime 없는 ZIP과 .sha256.txt
receipts-dev/    # 개발 PC 상태 영수증
receipts-prod/   # 운영 서버컴 배포 전후 상태 영수증
instructions/    # 이 문서와 운영 실행 명령
```

Drive는 배포 큐이지 실시간 파일 동기화 저장소가 아니다. 운영 root를 Drive Desktop 동기화 폴더로 지정하지 않는다.

## 개발 PC가 보내는 항목

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
python scripts\build_student_app_code_release.py `
  --output "generated\student-app-code-$stamp.zip"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\collect_student_app_node_status.ps1 `
  -Role Development `
  -PublicHost dev-app.5a-math.com `
  -OriginPort 8004 `
  -OutFile "generated\dev-node-$stamp.json"
```

업로드 전 ZIP verifier가 성공해야 한다.

```powershell
python scripts\build_student_app_code_release.py `
  --verify-only "generated\student-app-code-$stamp.zip"
```

manifest의 `source.dirty=true`이면 이것은 현재 검증 workspace snapshot이라는 뜻이다. Git remote가 복구된 뒤에는 검증된 commit/tag 기반 release로 전환한다.

## 운영 서버컴이 처음 돌려줄 항목

기존 코드를 변경하기 전에 상태 스크립트 하나만 운영 서버컴에 내려받아 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File C:\server\scripts\collect_student_app_node_status.ps1 `
  -Role Production `
  -PublicHost app.5a-math.com `
  -OriginPort 8003 `
  -ServerRoot C:\server `
  -OutFile C:\server\generated\prod-node-before.json
```

`prod-node-before.json`만 `receipts-prod/`에 업로드한다. runtime 파일 자체는 업로드하지 않는다.

## 운영 배포 순서

1. 운영 Waitress와 Push worker 상태를 기록한다.
2. 운영 runtime을 `scripts/backup_runtime_data.py`로 백업하고 archive SHA-256을 기록한다.
3. ZIP과 `.sha256.txt`를 운영 PC의 별도 staging 폴더에 내려받는다.
4. `prepare_student_app_production_stage.ps1`을 실행해 운영 root 밖에서 ZIP hash, release manifest, runtime 제외, compileall, backend/frontend focused all을 검증한다. `stage-path-declarations`는 `import core.paths`로 경로 선언만 확인하며 runtime을 생성하지 않는다(`stageRuntimeSeeded=false`). 검증은 staging 내부에서 수행하며 운영 process/runtime을 읽거나 변경하지 않는다.
5. `prod-stage-preflight.json`의 `readyForApply=true`를 확인하고 `receipts-prod/`에 업로드한다.
6. 별도 승인 후 `apply_student_app_production.ps1`로 코드만 배포한다. 이 스크립트는 Waitress를 멈춘 상태에서 runtime ZIP과 기존 코드 rollback 사본을 만들고, manifest의 코드만 적용한 뒤 Waitress를 재시작한다. `removedPaths`는 rollback 폴더로 이동하며 즉시 삭제하지 않는다.
7. 필요한 SQLite migration은 코드 복사와 별도 단계에서 하나씩 적용한다.
8. exact-host local probe와 운영 canary 로그인을 확인한다.
9. 새 `prod-node-after.json`을 생성해 Drive에 올린다.
10. 개발·운영 영수증을 비교한 뒤에만 `app.5a-math.com` DNS를 운영 Tunnel로 cutover한다.

```powershell
python scripts\compare_student_app_nodes.py `
  generated\dev-node.json `
  generated\prod-node-after.json
```

### staging preflight 실행 예시

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File "$env:USERPROFILE\Downloads\prepare_student_app_production_stage.ps1" `
  -BundlePath "$env:USERPROFILE\Downloads\student-app-code-20260809-180647.zip" `
  -ChecksumPath "$env:USERPROFILE\Downloads\student-app-code-20260809-180647.zip.sha256.txt" `
  -ServerRoot C:\server
```

### 승인된 코드 적용 실행 예시

아래 예시는 현재 승인된 release에만 유효하다. `ExpectedBundleSha256`은 `prod-stage-preflight.json`, checksum 파일, ZIP bytes 세 곳 모두와 일치해야 한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File "$env:USERPROFILE\Downloads\apply_student_app_production.ps1" `
  -StageReceiptPath "$env:USERPROFILE\Downloads\prod-stage-preflight.json" `
  -BundlePath "$env:USERPROFILE\Downloads\student-app-code-20260809-180647.zip" `
  -ChecksumPath "$env:USERPROFILE\Downloads\student-app-code-20260809-180647.zip.sha256.txt" `
  -ExpectedBundleSha256 D99A6B2FC69D17AB3719438704B888E8F76545D8739DC1A3DA6C7D07EFE1EA7D `
  -ExpectedStageReceiptSha256 E9CF7417AC994DD929485B189163839C3D44EF8258A678058D8D83968CCECB7B `
  -ServerRoot C:\server `
  -ConfirmApply
```

성공 시 콘솔에 표시되는 `prod-code-apply.json`을 `receipts-prod/`에 올린다. 실행 전 `Academy Server Waitress` Task가 `C:\server\scripts\run_waitress_server.ps1`과 `C:\server`를 정확히 가리키고, Push Task가 없거나 Disabled여야 한다. 이 단계는 Cloudflare, DNS, VAPID, Task 정의, migration을 변경하지 않으며 `app.5a-math.com/app`을 계속 404로 유지한다. 실패 시 영수증의 `rollback.succeeded=true`와 rollback probe `200/404/404`가 모두 기록된 경우에만 코드 자동 rollback 완료로 판단한다. runtime ZIP은 자동 복원하지 않는다.

## 금지 사항

- 개발 PC의 root JSON/SQLite를 운영 서버에 whole-file overwrite
- 운영 root를 공유 폴더, SMB 쓰기 공유 또는 Drive 동기화 대상으로 설정
- 운영 DB를 개발 PC가 네트워크 드라이브로 직접 열기
- 운영과 개발이 같은 VAPID private key 사용
- 두 장비가 같은 `app.5a-math.com` Tunnel을 동시에 광고
- 배포 실패 시 runtime archive를 통째로 worktree에 덮어쓰기

## 현재 진행 상태

운영 서버컴의 상태 영수증과 staging preflight 영수증은 수신·검증을 마쳤다. 개발 PC에서 운영 서버컴으로 직접 접속할 수 없으므로, 현재 단계는 운영 서버컴에서 승인된 코드 적용 스크립트를 1회 실행하고 `prod-code-apply.json`을 `receipts-prod/`에 올리는 것이다. Cloudflare 설치·DNS cutover·VAPID·migration은 이 영수증 검수 뒤의 별도 승인 단계다.
