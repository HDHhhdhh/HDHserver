# Codex 인수인계 — 2026-08-13

> 역사 스냅샷: 이 문서는 2026-08-13 당시 상태를 보존한다. 이후 PWA 재통합, 공개 도메인 분리, 시험 제출/OCR 폐기 등 계약이 바뀌었으므로 현재 작업에는 `docs/PROJECT_FUNCTIONS_AND_LOGIC.md`, `docs/CODE_FLOW_MAP.md`, `docs/LOGIC_DECISION_LEDGER.md`를 사용한다.

현재 `d7cb5d4` 이후 작업 트리에는 코드 패치와 기준 문서가 있으며 runtime JSON/SQLite/업로드는 변경하지 않았다.

## 이번 변경

- 학생 시청 `updatedAt`의 signed 32-bit 절단 제거
- backend에서 seconds/32-bit 시각을 누락으로 정규화해 다음 저장에서 서버 밀리초로 자연 교정
- 공개 `5a-math.com`, `app.5a-math.com` HTTP를 같은 URL의 HTTPS로 308
- Cloudflare `CF-Visitor.scheme` 우선, `X-Forwarded-Proto` fallback; 신뢰 proxy peer에서만 인정
- proxy/HTTPS/timestamp 회귀 검사 추가
- 전체 기능·로직 정본과 최근 2주 세션 감사 추가
- 루트 `AGENTS.md`, `PROJECT_SUMMARY.md`, `CHATGPT_PROJECT_CONTEXT.md`를 정본에 연결
- 관리자 운영판 학생 이름 툴팁에서 이름 옆 학생 난이도 배지 제거

문서 진입점:

- `docs/README.md`
- `docs/PROJECT_FUNCTIONS_AND_LOGIC.md`
- `docs/SESSION_AUDIT_2026-07-30_2026-08-13.md`

## 검증 결과

- Python compileall: 통과
- 현재/legacy 학생 JS `node --check`: 통과
- timestamp unit/source: 통과
- `scripts/verify_academy_proxy_network_access.py`: 통과
- 전체 `scripts/verify_refactor_safety.py`: 통과
- Waitress 재시작 후 새 PID/listener 정상
- 실제 공개 HTTP: 두 도메인 모두 308
- 실제 공개 HTTPS login: 두 도메인 모두 200
- 로컬 HTTP: 200 유지
- 관리자 인증: 공개 `/admin` 무인증 401
- 답지 gate: 신뢰 proxy의 외부 IP 403, 학원 IP 200
- `watch.json`, `progress.json`, `updates.json`, `app.sqlite` 해시: 전후 동일

in-app Browser는 Node browser runtime이 Windows sandbox `helper_unknown_error`로 두 번 종료돼 DOM/console/screenshot/interaction을 실행하지 못했다. 앱 HTTP 계약과 회귀 검사는 통과했지만 렌더링 QA는 남아 있다.

## 열린 항목

1. 모든 확인된 backup과 SQLite에 없는 과거 시험 점수는 외부 원본이 있어야 복구할 수 있다.
2. Waitress 예약 작업은 Interactive, cloudflared는 사용자 AppData/HKCU Run 기반이다. 로그아웃 후 공개 서비스 중단 위험을 없애려면 관리자 권한으로 둘 다 Windows service 또는 비대화형 service account로 옮기고 logout/reboot 생존을 검증해야 한다.
3. 현재 scheduled-task action에는 과거 `PublicHostOverride` 등 더 이상 쓰지 않는 인자가 남지만 PowerShell의 `$args`로 무시되고 있다. 서비스 전환 때 action도 함께 정리한다.

## 배포 주의

- 운영 Waitress는 현재 작업 트리의 패치로 재시작된 상태다.
- Git 등록은 아직 하지 않았다. 사용자 요청 전에는 stage/commit/push하지 않는다.
- 대량 데이터 복구·migration 전에는 `python scripts/backup_runtime_data.py`를 먼저 실행한다.
- PWA/별도 학생 앱은 의도적으로 제외된 현재 정책이다.
- 관리자 페이지군의 학원망 경계 + Basic 인증과 학생 영상·답지 학원 네트워크 제한을 유지한다.
