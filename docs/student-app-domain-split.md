# 학생 앱 개발/운영 도메인 분리

코드 번들 및 양쪽 장비 상태 영수증 교환 절차는 [student-app-node-handoff.md](student-app-node-handoff.md)를 따른다. runtime은 동기화하지 않는다.

## 고정 역할

| 환경 | 공개 hostname | 장비 | origin | 공개 범위 |
|---|---|---|---|---|
| 개발/QA | `dev-app.5a-math.com` | 현재 개발 PC | `127.0.0.1:8004` | 비어 있지 않은 QA canary SID만 |
| 운영 | `app.5a-math.com` | 기존 운영 서버컴 | `127.0.0.1:8003` | 운영 승인 범위 |

두 환경은 서로 다른 Waitress 프로세스, Tunnel credential, runtime, VAPID key를 사용한다. 같은 named Tunnel credential을 두 장비에서 동시에 실행하거나 두 프로세스가 하나의 runtime을 장기간 공유하지 않는다.

## 현재 전환 상태

- 개발 PC의 `Academy Dev Server Waitress`는 loopback `127.0.0.1:8004`에서 실행한다.
- 개발 프로세스는 `run_waitress_server.ps1`의 process override로 `dev-app.5a-math.com`과 QA canary를 사용한다. machine-level 운영 설정은 변경하지 않는다.
- 개발 PC Tunnel에는 전환 기간 동안 다음 두 ingress가 존재한다.

```yaml
ingress:
  - hostname: app.5a-math.com
    service: http://127.0.0.1:8003
  - hostname: dev-app.5a-math.com
    service: http://127.0.0.1:8004
  - service: http_status:404
```

- Cloudflare Cache Rule은 두 hostname 모두 origin cache header를 존중하고 edge cache를 bypass한다.
- 운영 서버컴이 준비되기 전에는 `app.5a-math.com` DNS와 개발 PC의 8003 rollback origin을 제거하지 않는다.
- 현재 8003과 8004는 같은 workspace/runtime을 읽는 임시 전환 상태다. 운영 서버 cutover가 끝날 때까지 개발 기능 flag와 QA 쓰기를 제한하고, 이후 8003 Task를 중지해야 완전 분리가 된다.

## 운영 서버컴 준비

1. 운영 runtime을 정지 상태로 백업한다. 학생/로그/진도 JSON 및 `app.sqlite`를 개발 PC 파일로 덮어쓰지 않는다.
2. 검증된 code-only artifact를 운영 root에 배포한다. 복사된 venv는 사용하지 않고 운영 PC에서 dependency를 설치한다.
3. machine environment를 `STUDENT_APP_PUBLIC_HOST=app.5a-math.com`, `STUDENT_APP_LEGACY_HOST=5a-math.com`으로 설정한다.
4. `STUDENT_APP_PUBLIC_ENABLED=0`, `STUDENT_APP_LEGACY_REDIRECT_ENABLED=0`과 비어 있지 않은 운영 canary로 시작한다.
5. 운영 전용 named Tunnel과 credential을 운영 PC에만 설치한다. 개발 Tunnel credential을 재사용하지 않는다.
6. local exact-host `/app` 404(preflight), flag-on canary `/app` 200/no-store, 무세션 API 401, legacy root 200, legacy-origin 앱 경로 404, `/admin` 및 교차 hostname 404를 확인한다.
7. 운영 VAPID key와 기존 subscription 유지 여부를 별도로 결정한다. 기존 Push를 유지하려면 운영 key를 보안 채널로 이관해야 한다.

## DNS cutover

운영 origin과 Tunnel의 canary 검증이 끝난 뒤에만 다음 순서로 전환한다.

1. `app.5a-math.com` DNS를 운영 전용 Tunnel로 overwrite한다.
2. 외부 `/`, `/app`, session 401, cache header, static alias 404, double-slash 404를 확인한다.
3. 로그인·curriculum switch·logout/revoke를 운영 canary로 확인한다.
4. 실패하면 즉시 DNS를 기존 개발 PC Tunnel로 되돌린다.
5. 사용자 production 승인 전에는 legacy redirect를 `0`으로 유지한다. 승인 뒤에만 `STUDENT_APP_LEGACY_REDIRECT_ENABLED=1`로 바꾸고 exact `5a-math.com/`의 302 목적지가 `https://app.5a-math.com/app`인지 확인한다.
6. 안정 확인 후 개발 PC Tunnel에서 `app` ingress를 제거하고 `dev-app`만 남긴다.
7. 개발 PC의 기존 `Academy Server Waitress` 8003 Task는 마지막 rollback 창이 끝난 후에만 중지한다.

## rollback

- 운영 cutover 실패: legacy redirect를 먼저 끄고 `app` DNS를 이전 Tunnel로 복구한 다음 운영 public flag를 끈다.
- 개발 장애: `dev-app` DNS/ingress만 제거하고 `Academy Dev Server Waitress`를 중지한다. `app` ingress와 Task는 건드리지 않는다.
- 어떤 rollback도 계정, session, subscription, outbox, SQLite table 또는 runtime JSON을 삭제하지 않는다.

## 안전 검증

읽기 전용 probe에는 `/`, `/app`, `/api/mobile/auth/session`, `/manifest.webmanifest`, `/sw.js`, `/student-app.html`, `//student-app.html`, `/admin`만 사용한다. `/api/updates`와 오늘자 bootstrap은 GET에서도 runtime을 쓸 수 있으므로 배포 probe에서 사용하지 않는다.
