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

# 종료
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_isolated_design_server.ps1 Stop
```

기본 주소는 `http://127.0.0.1:8004`다. 데모 화면은 기존 `/demo/...` 경로를 사용한다.

## 격리 계약

- 복사 대상은 `app.py`, `models.py`, `core/`, `routes/`, `static/`뿐이다.
- 루트 JSON, SQLite, `data/`, `files/`, `instance/`, 백업과 미러는 운영에서 복사하지 않는다.
- 테스트 runtime은 테스트 서버를 재시작해도 유지된다.
- 포트 8004가 다른 프로세스에 점유돼 있으면 자동 종료하지 않고 실패한다.
- 중지 시 기록된 PID와 시작 시각, 명령행이 모두 맞는 테스트 서버만 종료한다.
- 테스트 서버는 loopback 전용이고 public student app·push·Kollus callback을 비활성화한다.
- 운영 코드 폴더에서 직접 `waitress-serve ... app:app` 또는 `app.run(...)`을 실행하는 방식은 계속 차단한다.
