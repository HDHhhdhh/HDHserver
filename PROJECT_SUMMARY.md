# PROJECT SUMMARY

**기준일:** 2026-08-24
**기준 브랜치/커밋:** `codex/apple-clean-redesign` / `91b7bb1` 이후 현재 작업 트리

이 파일은 한 장짜리 안내다. 기능과 로직의 정본은 [docs/PROJECT_FUNCTIONS_AND_LOGIC.md](docs/PROJECT_FUNCTIONS_AND_LOGIC.md), 코드 연결은 [docs/CODE_FLOW_MAP.md](docs/CODE_FLOW_MAP.md), 과거 주문 충돌 판정은 [docs/LOGIC_DECISION_LEDGER.md](docs/LOGIC_DECISION_LEDGER.md)를 따른다.

## 시스템

`C:/server`는 학생 명단, 출결, 오늘 순서, 수업·숙제 로그, 영상 배정/시청, 시험 배정·답지·과거 기록, 보강, 공지, 캘린더, 자료 파일을 운영하는 Flask + 정적 JavaScript 학원 운영 허브다. JSON과 `app.sqlite`는 실제 운영 데이터이므로 코드와 별도로 보호한다.

## 주요 화면

- `/`: 학생 로그인
- `/admin`, `/dh1130`: 날짜별 관리자 운영판
- `/students`: 전체 학생
- `/student/<sid>`: 학생 영상·시험 배정·답지(제출 기능 없음)
- `/video-manage`, `/tests`, `/school-cal`, `/file-manage`: 카탈로그·일정·자료 관리
- `/demo/rh3123/*`: live write를 막는 데모

## 핵심 불변식

- 관리자 변경은 실제 오늘이 아니라 선택 날짜와 행의 `data-date`를 우선한다.
- 오늘 순서는 `data/today_order.json` 하나만 사용하며 구형 루트 동명 파일은 제거됐다.
- 로그는 SQLite 우선 + `logs.json` 결손 보충이며 빈 값이 의미 있는 값을 지우지 않는다.
- 학생 bootstrap의 `assignedTests`는 최상위 배열이며 시험 카드는 답지 열람 전용이다. 학생 제출/OCR 제출 경로와 `/student-test/<sid>`는 없다.
- progress 수동 상태가 watch 자동 상태보다 우선한다.
- watch `updatedAt`은 epoch milliseconds이며 비트 연산으로 줄이지 않는다.
- 영상 자동 배정은 real-today의 허용된 멱등 진입점에서만 최초 생성한다. 관리자 모달과 과거·미래 조회는 생성하지 않으며 수동 흰색·skip·완료·자습·복습을 보존한다.
- tests-config의 기존 시험은 명시적 delete ID 없이 삭제하지 않는다.
- 영상 관리 일반 모드는 새 행과 같은-MID 수정을 허용하지만 기존 영상의 MID 변경·삭제는 409로 차단한다.
- 기존 MID 교정은 브라우저에서 서버 미반영 수정안만 만든 뒤, dry-run·Waitress 정지·백업 hash 검증·4-store 변환·롤백·재시작 절차로만 적용한다.
- 관리자 페이지군과 활성 학생 계정 관리 API는 네트워크 위치와 무관하게 fail-closed Basic 인증을 요구한다. 학생 앱 공개 host의 관리자 API는 404이며 학생 영상·답지는 계속 학원 네트워크로 제한한다.
- `app.5a-math.com` HTTP는 404다. `5a-math.com`은 독립 전환 승인 전 기존 root를 유지하며 두 호스트는 별도 origin이다.
- 데모는 실서버 write를 만들지 않는다.

## 운영 상태

- Waitress: Windows 예약 작업, localhost/LAN 8003
- 공개: Cloudflare Tunnel을 통해 `5a-math.com`, `app.5a-math.com`
- 학생 JWT: 영구 `AUTH_SECRET`으로 30일 자동 로그인
- 학생 앱 PWA: 현재 저장소에 통합됐고 public만 활성화되어 있다. dashboard/homework/reminders/focus는 비활성이다.
- 외부 호환: 별도 학생 앱이 현재 사용 중이므로 `/api/watch-status`를 유지한다.
- 열린 외부 항목: 모든 백업에 없는 과거 시험 점수 원본, Waitress/cloudflared의 사용자 로그온 종속

## 검증

```powershell
python -m compileall -q app.py routes core scripts
python scripts/verify_refactor_safety.py
python scripts/verify_academy_proxy_network_access.py
node --check static/js/student.js
```

배포·대량 복구 전에는 `python scripts/backup_runtime_data.py`를 먼저 실행하고, Git에는 runtime JSON/SQLite/업로드를 넣지 않는다.
