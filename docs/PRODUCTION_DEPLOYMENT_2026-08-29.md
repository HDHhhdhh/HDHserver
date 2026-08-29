# Production deployment — 2026-08-29

Status: deployed to production 8003; server and data-contract smoke passed.
The Chrome-only production-admin policy and the native Kollus evidence
exception are closed by [decision D-10](LOGIC_DECISION_LEDGER.md#d-10-운영-관리자-브라우저와-kollus-실기동-증거).

Understood as: activate the verified non-OCR server-rule changes made after the
currently running 8003 process started, keep OCR and optional student-App
features disabled, and leave unrelated dirty-tree work unstaged and untouched.

## Release boundary

The running 8003 process started at 2026-08-29 14:20:03 KST. The following
runtime sources changed after that boundary and are included in this release.
The SHA-256 values lock the exact pre-restart source set.

| Path | SHA-256 |
|---|---|
| `core/absence_transaction.py` | `0E70389D578ED27760A8CEBC9FE459005C9259283881F23758AA4B1FC97D9179` |
| `core/date_rules.py` | `13E435150A07C3A3970E4554CFD242709D1E148B41DED0A40F18E8937BD73081` |
| `core/log_repository.py` | `8DA0D1076BBAE0795D7D2BC6416871B86517944E76DCB8BF2218A5C2D695B9DF` |
| `core/update_assignment_store.py` | `57983F4E0412A24AB9C396323E5E416FF5DC28713D6B76F1E0C0FE2A4BF5A38A` |
| `routes/api_basic.py` | `52ADFAD71B8EB7F8A1ED20E35B2873732B9182C77D7588921E63685EA23F2A60` |
| `routes/api_logs.py` | `2A00EC6EE12CD4DC25F820AC67DAED390922E9251BD1AB68CDDCDBBD1B50C59B` |
| `routes/api_progress.py` | `4474F2E1F8F82A1441F7F80CA7B8EE3C7E7ABDD3D1BF8327277B5494368FD542` |
| `routes/api_schedule_overrides.py` | `D957FDA3733659EA63C3A54F4E5FC7981A32E94082485DE5E8F72DD4EB80446A` |
| `routes/api_updates.py` | `AFDF9CCD03799C3214D9469C49A9DDA39A0AF2EE203ACC4E698141EC75AF079C` |
| `routes/api_watch.py` | `A3D658926603F90904FF5583B1F08B725AE5E2A07A7D4F31A9C54ED49062D8CD` |
| `routes/student_auto_assignment_service.py` | `D2A723B9DD3215F618949F7E75DE61498D5FCB4FADDD9F79BEEB4A2A17455DDD` |
| `static/js/student.js` | `9D654EE0D26DAB9FEBF68FF28A11ED6C6E1DCA622CF7BD15ADC247B54FDEA0EA` |

`static/js/student.js` is served directly and was already live before the
restart; it remains in the boundary because browser QA covers the combined
server/student-page contract.

## Explicit exclusions

- `core/student_test_ocr_config.py` and every OCR capture, review, worker,
  training, model, and OCR-document artifact are outside this release.
- `STUDENT_TEST_OCR_ENABLED` remains unset, which is the disabled state.
- The production task continues to use `-DevelopmentIsolation`; optional
  student-App dashboard, homework, reminder, and focus features remain disabled.
- No unrelated working-tree file is staged, reverted, normalized, or committed.

## Gates

- [x] Runtime backup completed before restart:
  `_runtime_backups/runtime-data-20260829_075111.zip`.
- [x] Compile and full safety suite passed against the locked source set.
- [x] Locked source hashes still matched immediately before restart.
- [x] 8003 restarted through the managed scheduled task and returned HTTP 200
  from both `192.168.0.5` and loopback.
- [x] In-app Browser and Chrome loaded the real student page, authoritative
  review list, local review registration, Kollus URL, and Kollus iframe with no
  browser console warnings or errors.
- [x] Chrome loaded the production admin board with the online indicator, real
  rows, no fatal text, no replacement characters, and no console warnings or
  errors.
- [x] A real academy-network `/api/watch` POST returned 200 and preserved the
  selected completed watch/progress/assignment tuple byte-for-byte.
- [x] Runtime-data fingerprints, pending-journal state, managed task, listener,
  OCR-disabled capability, and the QA student's state passed the post-deploy
  check.
- [x] D-10 records native Kollus frame start as an accepted evidence exclusion,
  not a pass: both browsers remained in `vjs-agent-checking` with
  `readyState = 0` and showed player-initialization failure.
- [x] D-10 fixes production administrator support to Chrome. The in-app
  Browser's `ERR_BLOCKED_BY_CLIENT` response to the Basic-auth challenge is not
  an open server defect, and Basic auth remains unchanged.

## Deployment result

- The managed task replaced PID 10932 with PID 10584. The new process started
  at 2026-08-29 16:56:14 KST and remained the port-8003 listener during the
  post-deploy check.
- `/api/ping` returned 200 over the academy LAN and loopback. The OCR capability
  endpoint returned `enabled: false`; the task still runs with
  `-DevelopmentIsolation`.
- The QA tuple was `이민용626` / `2026-08-29` / `3FWqGfJP`. Assignment source
  remained `manual`, watch remained completed at `2143 / 2143`, and progress
  plus automatic ownership remained `done`.
- The idempotent watch request left the complete `watch.json` and
  `progress.json` hashes unchanged in its immediate before/after comparison.
  Later whole-file changes occurred while production traffic continued, but
  the QA tuple stayed unchanged. Other expected operational files also changed
  during the live window; no pre-existing fingerprinted file disappeared and
  no pending journal remained.
- The scheduled-task launcher does not configure a dedicated Waitress file-log
  sink. Post-deploy health therefore used the managed-task state, listener
  identity, HTTP probes, browser consoles, data fingerprints, and target-state
  invariants.
- No unrelated dirty-tree file was staged, reverted, normalized, or committed.
