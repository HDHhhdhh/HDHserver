# PROJECT KNOWLEDGE BASE

This file owns repository-wide scope, runtime-data, verification, and Git safety.
Keep essential safety and work-completion rules first and this entrypoint below 32 KiB; put scoped detail in its existing owner.
Business-rule ownership starts at [docs/SERVER_RULES_INDEX.md](docs/SERVER_RULES_INDEX.md).

## Scope, Approval, and Completion
- A request to review or diagnose is read-only unless it also authorizes a change. A request to implement authorizes ordinary in-scope source edits and isolated verification, not unrelated external actions.
- Reuse explicit approval for the same target, action, scope, and limits. Do not ask again merely because a skill repeats an approval step. A new semantic conflict, scope expansion, runtime mutation outside existing approval, or exhausted approval limit needs a new decision.
- Preserve explicit counts and boundaries (for example, one production restart means one, not unlimited retries). Tool denials and sandbox limits remain binding; never use a different path to bypass them.
- Ask only material questions unresolved by available evidence. Batch independent questions; sequence dependent ones. Continue authorized work that does not depend on the answer.
- If one action needs new authority, pause that action only. Finish safe independent preparation and present a concrete result for review; do not infer authority to complete a blocked branch.
- Define completion against the requested outcome and required checks. Report implementation, verification, production rollout, and approval-dependent work separately. No findings/no further edits is a valid verification result; never invent changes to satisfy a workflow.
- Skills support the task; they do not grant authority, override repository/runtime safeguards, or require unrelated publication or a rewrite. Advisory substeps return to the caller. Optional unavailable reviews are disclosed, not fabricated as passes; user-mandated gates remain required.
- Maintain required regression gates. Size reruns to affected behavior without treating an optional follow-up as a new completion condition. Do not restart the server solely to apply these instruction files.

## Runtime Data Safety
- Do not overwrite or reset runtime data files unless the user explicitly asks.
- The canonical inventory and ownership are [`RULE-DATA-001`](docs/SERVER_RULES_INDEX.md#rule-data-001) and [the data-source table](docs/PROJECT_FUNCTIONS_AND_LOGIC.md). Do not maintain a second supposedly complete filename list here.
- `persons.json`, `students.json`, and the person-identity journal are runtime data. Once person identity is configured, a missing or partial identity store is a fault to diagnose, not permission to create an empty replacement.
- `app.sqlite` is the sole supported root SQLite database. The empty, unreferenced legacy `vacation.db` was retired on 2026-08-24; do not recreate or ignore it.
- Treat SQLite sidecars such as `app.sqlite-wal`, `app.sqlite-shm`, `*.db-wal`, `*.db-shm`, root `*.tmp` files, `data/*.json`, `files/`, `instance/`, `_data_mirror/`, `_runtime_backups/`, `.codex_drive_download/`, `generated/`, and generated/downloaded operational outputs as runtime/local data when present.
- `core.paths` declares paths without creating runtime files. `app.create_app()` explicitly initializes legacy defaults after the server guard and runs recovery; importing `app` still has runtime side effects.
- Before data migrations or bulk repair, create a backup:
  `python scripts/backup_runtime_data.py`
- The backup now requires an approved quiescent maintenance window; it refuses an active production listener and never stops it itself. See `RULE-DATA-001` for the native SQLite snapshot/restore contract.
- Prefer PATCH-style updates over full-file rewrites.
- Preserve existing keys and unknown fields when merging log/progress records.
- Keep JSON as UTF-8. Do not introduce mojibake or replacement text such as `????`.
- Be careful with "read-only" checks: log and assistant-note GETs can ensure/migrate SQLite schema or WAL state; `GET /api/updates` defaults to storage-only; compatibility `?ensure=1` or `UPDATES_GET_ENSURE=1` can still write `updates.json`; today's student bootstrap can do both.
- Log-GET smoke is opt-in only: run `python scripts/verify_refactor_safety.py --smoke --smoke-log-gets` after `python scripts/backup_runtime_data.py`. The verifier compares `mtime_ns`, size, and SHA-256 for main databases and sidecars; any main-database change, including an mtime-only change, fails. `--smoke-log-gets` without `--smoke` is invalid.

## 테스트 서버 활용 규칙
- Port 8003 is the canonical production server. Keep it available during test work and never stop, restart, or replace it merely to run a test server; production maintenance requires explicit user direction.
- The only supported concurrent test server is the loopback-only server on `127.0.0.1:8004` managed by `scripts/manage_isolated_design_server.ps1`. Never run another `app:app`, `app.run(...)`, Flask, or Waitress process directly from the live repository.
- The test server must run from `instance/isolated-design-server/app`. Its JSON, SQLite, `data/`, `files/`, `instance/`, mirror, backup, and generated runtime state must remain separate from production. Never copy, read as seed data, write, or automatically merge production runtime into the test runtime.
- Data entered through the test server belongs only to the test runtime and must never be merged into production automatically. Importing a production snapshot or promoting test data requires explicit user approval, a fresh runtime backup, a reviewed one-way migration plan, and separate verification.
- Use the manager lifecycle only: run `Status` before acting, `Start` for initial launch, `Refresh` for frontend/source snapshot refresh, `Start -Restart` after Python or route changes, and `Stop` only after confirming no user or other active task still needs the test server. A plain `Refresh` does not reload already-imported backend code.
- Keep port 8004 private to loopback. Public/LAN exposure, real push delivery, public student-app behavior, or Kollus callbacks require a separately approved QA deployment and must not be enabled by weakening the local isolation guard.
- D-18 permits only the default-OFF managed `-KollusVideoQa` window for its exact synthetic SID/MID. Keep the receipt/process/root/loopback checks and video-only permission separate from academy access, answers, public/push/callback gates; turn it off after verification. See canonical §18.
- After every start or restart, require all of these checks: manager status reports `managed: true` and HTTP 200; exactly one loopback listener owns port 8004; production `/api/ping` on port 8003 still succeeds; and the public production `/app` remains reachable. After `Refresh`, verify both servers plus the changed test page.
- If start or status validation fails, do not bypass the runtime guard, kill an unknown port owner, or fall back to the live repository. Inspect manager status, receipt, and stderr. `Stop` may terminate only the receipt-matched isolated test process and must never target production.

## Git Workflow
- Do not revert user changes.
- Keep commits focused by feature or fix.
- Before pushing, check `git status --short` and summarize runtime-data changes separately from code changes.
- Before committing, separate staged changes, unstaged changes, untracked files, and runtime/local data. Do not mix unrelated dirty work into the same commit.
- After verified work is complete and the user wants git registration, add only the intended files with explicit paths.
- Runtime data is local operational data. Do not commit or push runtime data files unless the user explicitly asks for a data backup commit.
- Prefer code-only commits for app patches. Keep local student/video/homework/progress data separate from patch versioning.
- Use branch names with the `codex/` prefix by default for new patch work.

## Agent Workflow
- Read this `AGENTS.md` first, then run `git status --short` before edits. Record pre-existing dirty, staged, and untracked files separately from files changed by the current task.
- Use subagents for broad or risky work only when the current tool policy and user request allow delegated agents. Keep subagents read-only unless a task explicitly gives them an edit scope.
- The main agent owns final synthesis, file edits, verification, and user-facing conclusions.
- Before the final response, clean up any open subagents by waiting for useful results or closing them, then report how subagents were used.
- When investigating Codex/OMO runtime issues, do not recursively search all of `%USERPROFILE%\.codex` or plugin cache folders. Inspect targeted config files, latest hook outputs, and recent sandbox log lines with tight output limits so command-runner pipes are not flooded.
- Before reporting completion, run the relevant verification commands, check `git status --short`, and separate code changes from runtime-data changes.
- When the user asks for git registration/staging after completion, stage only the verified files in scope. Do not stage, unstage, revert, or normalize unrelated existing changes.

## Commands
```powershell
python -m compileall -q app.py routes core scripts
python scripts/verify_refactor_safety.py
node --check <edited-file.js>
```
`--smoke` imports the live app and permits WAL/SHM churn; it is not equivalent to a pure unit suite.
Live `--smoke` is opt-in under Runtime Data Safety, not a routine documentation check. For a browser server use only the managed 8004 lifecycle in 테스트 서버 활용 규칙; there is no frontend package runner.

## Verification Notes
- For admin UI changes, reload `/admin`, verify exact target data/state with API or documented browser evidence, then run screenshot QA when layout changed.
- Log/homework/progress work requires both log endpoints plus the browser regression in `static/js/admin/features/AGENTS.md`; a green-to-white manual state must survive reload and automatic watch updates.
- Video assignment work spans `videos.json`, `updates.json`, `progress.json`, `watch.json`, `/api/get-url`, student bootstrap, the admin modal, and the student playlist. Run `scripts/verify_updates_routes.py` plus the focused auto-assignment/watch/review checks before the full suite.
- Student review UI changes require `node scripts/verify_student_previous_video_review.js` plus `node scripts/verify_student_material_access_scope.js`; keep both fixtures aligned with the done-only chooser and title-only outside-academy response.
- Student-test work must preserve progress-authoritative assignments, top-level `assignedTests`, answer-link precedence, academy-network stripping, and historical record reads. `static/js/student/testPresentation.js` owns only read-only presentation semantics; `student.js` owns the card DOM and click feedback. Keep `verify_student_test_presentation.mjs`, the pre-existing material-access VM, and answer-mobile/retired-submission checks green. Legacy submission/OCR routes and `/student-test/<sid>` are retired; never revive them. The separate default-OFF capture/OCR feature follows canonical §21 and D-09, with its own quality and rollout gates.
- Test answer-link precedence lives in `core/test_answer_links.py`. `api_tests` must use the public resolver and `core.storage.file_lock`, not private helpers from `api_basic`; preserve direct assignment → config metadata → generated map order and academy-network stripping.
- Public announcement files require all three gates: a safe one-segment `/files/announcements/<name>` request, an active public SID, and current SID-visible membership in `announcements.json`. Keep membership in `core/announcement_image_access.py`; `api_fs` must not import private announcement-route helpers.
- The default suite is bespoke and incomplete; targeted `--only-*` modes do not replace the full run, and CI does not run live smoke or browser QA.

## Browser/UI Notes
- After frontend changes, reload the admin page before verifying.
- Prefer current callable browser control for local UI verification, following its documented entrypoint (including CUA). Skill names or legacy bootstrap recipes do not determine availability. Correct API misuse/stale tabs in that runtime; inspect the prescribed server manager for connection refusals. Use an available Chrome/Playwright fallback only for an actual capability gap or connection failure, within the same authorized QA scope, and report why. Never reroute permission denials. Preserve explicit browser restrictions; do not install dependencies, change authentication, or expose a server without required authorization.
- Production administrator browser support and the scoped native-player evidence exception are owned by [`RULE-OPS-001`](docs/SERVER_RULES_INDEX.md#rule-ops-001) and decision D-10. Use Chrome for production administrator pages; never weaken Basic auth to make the in-app Browser load them, and do not remove existing isolated two-browser regression gates.
- Follow 테스트 서버 활용 규칙 whenever browser or design verification needs a running server.
- Use API/DOM evidence for exact data where available; documented accessibility/visible-state checks also prove UI state. Use screenshots for visual regressions. Missing DOM helpers alone do not justify abandoning working browser control.
- Text must remain readable in Korean; verify UTF-8 rendering when touching static HTML/JS.
- Clean up a verification-only server through its manager after the ownership/use checks in 테스트 서버 활용 규칙; keep a shared or uncertain-use server running and report it rather than stopping an unknown owner's process.

## Coding Rules

- Provider and 기출엄선 overlay exceptions to the existing video/watch/current-course rules are owned by [canonical §9](docs/PROJECT_FUNCTIONS_AND_LOGIC.md#youtube-gichul-overlay). Keep new automatic scope, existing-snapshot preservation, and review eligibility distinct; preserve Kollus-only watch semantics.
- Follow the existing small-module structure rather than adding new frameworks.
- Keep frontend changes scoped to the relevant `static/js/admin/features/` module.
- Use `todayLocalKey()` only when the real local date is intended.
- Keep save logic merge-safe. Empty values must not erase existing meaningful data unless an explicit clear/delete field is used.
- Keep student bootstrap response shapes stable. In particular, `assignedTests` is a top-level array; do not change endpoint URLs or payload keys without a dedicated migration plan.
- In logs/progress code, SQLite and JSON fallbacks may both matter. Fill missing fields narrowly rather than replacing a whole entry from another store.
- Avoid large rewrites of existing modules unless the user asks for a refactor.
- Add comments only for non-obvious data-safety or merge behavior.

## Known Risk Areas
- `logs.json` and `app.sqlite` are dual-write/dual-read stores. Keep their merge behavior compatible.
- `progress.json` is large and date/sid keyed. Avoid full replacement writes from the frontend.
- Normal `POST /api/videos` rejects removal of an existing video ID or a URL-derived MID change with 409 before writing. Same-MID signed URL/metadata edits and new rows remain allowed. Do not add a request bypass. The supported correction path is the browser-only draft in `video-manage.js`, dry-run/apply through `scripts/apply_video_catalog_correction.ps1`, a stopped Waitress listener, a fresh verified runtime backup, and the pure four-store transform in `core/video_catalog_correction.py`. Referenced deletion fails closed; correction drafts contain full URLs and must not be committed.
- Watch `updatedAt` is epoch milliseconds. `static/js/student/watchState.js` must normalize it without bitwise coercion, and the server must preserve valid millisecond values while repairing legacy 32-bit values; keep both wire regression checks when changing serialization or merge logic.
- `/api/kollus/lms-callback` fails closed when `KOLLUS_CALLBACK_SECRET` is unset and validates the configured secret or signed token. Keep callback verification separate from the academy-only browser playback gate.
- Whole-map `/api/absent` writes with a shape-valid but impossible calendar date currently return 500 before creating a journal. User choice B keeps this as a known limitation; preserve the verified no-write/no-notification outcome, but do not describe 500 as a desirable API contract.
- Older logs may contain legacy or corrupted text. Repair display and future saves without deleting unrelated fields.
- The admin page uses both cached frontend state and server refreshes; hydrate date/sid-scoped data before assuming `state` is complete.
- `data/today_order.json` is the sole today-order store. The retired root `today_order.json` was migrated and removed; do not recreate it or add a second path.
- Unreferenced static assets may still be directly servable by filename; confirm external/manual use before deleting them. Do not restore the retired `static/main.html`, `static/student copy.html`, or `static/js/student copy.js` files as alternate student surfaces.
- Install core/default-verification dependencies from `requirements.txt`; optional student-app dependencies remain in `requirements-student-app.txt`. There is no frontend package runner. CI installs the manifest before invoking the custom safety harness; browser QA stays separate.

## Navigation and Scoped Guidance
- Read the applicable child `AGENTS.md` before editing: [core](core/AGENTS.md), [routes](routes/AGENTS.md), [scripts](scripts/AGENTS.md), [static](static/AGENTS.md), [CSS](static/css/AGENTS.md), [JavaScript](static/js/AGENTS.md), and deeper guides named there.
- Admin guidance: [entry](static/js/admin/AGENTS.md), [core](static/js/admin/core/AGENTS.md), [features](static/js/admin/features/AGENTS.md), [demo sandbox](static/js/admin/demo/AGENTS.md).
- Other JS guidance: [shared](static/js/shared/AGENTS.md), [all-students entry](static/js/all/AGENTS.md), [all-students features](static/js/all/features/AGENTS.md).
- Business meaning and decisions: [Server Rules Index](docs/SERVER_RULES_INDEX.md). Implementation locations and symbols: [Code Flow Map](docs/CODE_FLOW_MAP.md); use `rg` for current definitions rather than maintaining a second symbol inventory here.
- The ignored OCR lab has a separate [guide](tools/subjective_sheet_lab/AGENTS.md); read it before scanning, calling providers, or generating lab artifacts.

## Overview
- Local Flask academy-operations app with static HTML shells, native ES modules, and large standalone student/test scripts; no Jinja template tree or frontend build system.
- `app.py:create_app()` installs write/network guards and registers the flat blueprints. Runtime state lives beside the code in JSON and SQLite.
- For semantic conflicts, use the actual-versus-intended model in the Rules Index: verified code/runtime describes actual behavior; the latest approved decision and canonical logic document describe intent; any mismatch is implementation drift.

## Current Refactor Boundaries
- Preserve endpoint URLs, payload keys, response shapes, revision/clear-field contracts, unknown fields, and shared JSON-helper behavior. Read the owner below before changing a boundary; this entrypoint does not duplicate its full contract.
- Person/SID identity, immutable IDs, shared profile fan-out, strict partial-store failure, and journaled student writes: [routes guidance](routes/AGENTS.md) and [RULE-IDENTITY-001](docs/SERVER_RULES_INDEX.md#rule-identity-001).
- Automatic/manual/self-study video meanings, real-today initialization, protected dated snapshots, count/course changes, authoritative review membership, and provider exceptions: [core guidance](core/AGENTS.md), [routes guidance](routes/AGENTS.md), and [RULE-VIDEO-001](docs/SERVER_RULES_INDEX.md#rule-video-001).
- Log dual-store merge/repair, watch/progress ownership, absence barriers and recovery, date validation, and the explicit D-04 exception: [core guidance](core/AGENTS.md), [routes guidance](routes/AGENTS.md), and [rule index](docs/SERVER_RULES_INDEX.md). Class-log repositories and watch writers stay separate from pure rules and notification hooks.
- File/material three-store locking, segment-aware transforms, revision checks, journal recovery and degraded read/write behavior: [core guidance](core/AGENTS.md), [routes guidance](routes/AGENTS.md), and [canonical material rules](docs/PROJECT_FUNCTIONS_AND_LOGIC.md#13-공지설문캘린더자료).
- School-calendar revisions, conflict reload and the single save queue: [RULE-CALENDAR-001](docs/SERVER_RULES_INDEX.md#rule-calendar-001) and [JavaScript guidance](static/js/AGENTS.md).
- Student bootstrap authority, public SID/academy sanitization, top-level `assignedTests`, nine-slot state and student browser-controller ownership: [routes guidance](routes/AGENTS.md) and [JavaScript guidance](static/js/AGENTS.md). Failed bootstrap must not reconstruct partial state through retired requests.
- Administrator public/legacy exceptions and schedule-override validation/hook behavior: [routes guidance](routes/AGENTS.md) and [rule index](docs/SERVER_RULES_INDEX.md).
- SID-level white-review pending, fixed column widths, modal date/SID sessions, merge-safe saves and cache/edit locks: [admin feature guidance](static/js/admin/features/AGENTS.md) and [RULE-WHITE-REVIEW-001](docs/SERVER_RULES_INDEX.md#rule-white-review-001).
- Test catalog revisioned single/bulk writes, source/solution metadata, answer precedence, pure browser projection and stylesheet gates: [RULE-TEST-001](docs/SERVER_RULES_INDEX.md#rule-test-001), [routes guidance](routes/AGENTS.md), [JavaScript guidance](static/js/AGENTS.md), and [CSS guidance](static/css/AGENTS.md).
- Test additions and CSV/catalog changes must keep the quick-printer registration/material mapping and student explanation links in sync; the paired-registration decision and retired/default-OFF capture boundary remain in [canonical §11](docs/PROJECT_FUNCTIONS_AND_LOGIC.md#11-시험-배정답지과거-기록) and [scripts guidance](scripts/AGENTS.md).
