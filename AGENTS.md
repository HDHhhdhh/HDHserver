# AGENTS.md

## Project Overview
- This is a local Flask-based academy operations app.
- Admin UI: `/admin`, implemented mainly in `static/admin.html` and `static/js/admin/`.
- Student UI: `/students`, `/student/<sid>`, and related static JS.
- Backend API routes live in `routes/`; shared helpers live in `core/`.
- Runtime data is stored locally in JSON files and SQLite. Treat it as real user data, not fixtures.

## Key Paths
- `app.py`: Flask app factory, middleware, blueprint registration.
- `routes/api_basic.py`: students, videos, logs, progress, assignments, and core JSON APIs.
- `routes/api_attend.py`: today list, attendance, contact, absence APIs.
- `routes/api_watch.py`: video watch/progress callbacks.
- `core/log_repository.py`: class log repository for SQLite + `logs.json` dual-read/dual-write behavior.
- `core/log_rules.py`: pure class-log merge/conflict rules with no file, SQLite, Flask, or runtime-data access.
- `static/js/shared/api.js`: shared frontend fetch/API helper for JSON requests and standardized API errors.
- `static/js/admin/main.js`: admin frontend entrypoint.
- `static/js/admin/features/logModal.js`: class log, homework, and video progress modal.
- `static/js/admin/features/today*.js`: today list state and rendering.
- `scripts/backup_runtime_data.py`: zip backup for runtime data.

## Runtime Data Safety
- Do not overwrite or reset runtime data files unless the user explicitly asks.
- Important data files include `students.json`, `videos.json`, `updates.json`, `progress.json`, `logs.json`, `app.sqlite`, `watch.json`, `attendance.json`, `contact.json`, `arrive_time.json`, `extra_attend.json`, `absent.json`, `weekend_slots.json`, `today_order.json`, `school_calendar.json`, and `tests.json`.
- Treat SQLite sidecars such as `app.sqlite-wal`, `app.sqlite-shm`, `*.db-wal`, `*.db-shm`, root `*.tmp` files, `data/*.json`, `files/`, `instance/`, and generated/downloaded operational outputs as runtime/local data when present.
- Before data migrations or bulk repair, create a backup:
  `python scripts/backup_runtime_data.py`
- Prefer PATCH-style updates over full-file rewrites.
- Preserve existing keys and unknown fields when merging log/progress records.
- Keep JSON as UTF-8. Do not introduce mojibake or replacement text such as `????`.
- Be careful with "read-only" checks: `GET /api/logs` and `GET /api/logs/entry` may touch SQLite schema/WAL state, `GET /api/updates` may auto-write `updates.json`, and today's `GET /api/student/bootstrap` may auto-write `updates.json`.

## Agent Workflow
- Read this `AGENTS.md` first, then run `git status --short` before edits. Record pre-existing dirty, staged, and untracked files separately from files changed by the current task.
- Use subagents actively for broad or risky work when they can inspect independent areas in parallel. Keep subagents read-only unless a task explicitly gives them an edit scope.
- The main agent owns final synthesis, file edits, verification, and user-facing conclusions.
- Before the final response, clean up any open subagents by waiting for useful results or closing them, then report how subagents were used.
- After completing work, run the relevant verification commands, check `git status --short`, and separate code changes from runtime-data changes.
- When the user asks for git registration/staging after completion, stage only the verified files in scope. Do not stage, unstage, revert, or normalize unrelated existing changes.

## Reusable Skills and Subagents
- Use `academy-runtime-safety` for any change that can touch runtime data, backups, migrations, smoke checks, Git versioning, or code/data separation.
- Use `academy-log-progress-guardian` for class logs, homework tables, video progress, watch callbacks, assigned tests, student bootstrap, SQLite/JSON fallback behavior, and mojibake-sensitive note fields.
- Use `admin-ui-date-verifier` for `/admin` UI work, selected-date behavior, row actions with `data-date`, today list/calendar/attendance/absence/contact/homework flows, Browser checks, and Korean rendering regressions.
- No persistent custom subagent registry is configured in this environment. When subagents are available, implement the custom-subagent behavior by spawning a read-only explorer with the prompt pattern from the relevant skill before editing broad or risky surfaces.
- The repeated user priorities from prior sessions are: protect real local data, preserve merge-safe log/progress contracts, verify admin selected-date behavior, keep Korean text readable, use Browser/UI checks after frontend changes, and keep GitHub versioning code-only unless data backup is explicitly requested.

## Current Refactor Boundaries
- Frontend API calls should use the shared helper in `static/js/shared/api.js` when adding or touching admin/all JSON fetch wrappers. Preserve endpoint URLs, payload keys, cache behavior, and existing response shapes.
- When changing app features, routes, data contracts, admin/student workflows, or safety rules, update the administrator chatbot knowledge in `core/admin_chat.py` and any related chatbot UI copy so `/admin` chatbot answers stay current. Include this in verification notes for feature changes.
- Class log reads/writes should go through `get_log_repository()` / `LogRepository` instead of open-coding SQLite + `logs.json` merge behavior in route handlers. Keep SQLite and JSON fallback compatibility when changing log flows.
- Pure class-log rules belong in `core/log_rules.py`. Keep `merge_log_entry_safe`, `log_entry_conflicts_with_base`, homework-row comparison normalization, and `truthy` semantics centralized there.
- Keep runtime-data repair and hydration separate from pure rules. For example, `_repair_log_entry_placeholders()` currently stays in `routes/api_basic.py` because homework placeholder repair can read `students.json` through student book lookup.
- Do not merge watch/progress auto-status rules into log rules. `routes/api_basic.py` and `routes/api_watch.py` still contain duplicated watch/progress transition logic; extract it only with focused tests for manual white/skip preservation and automatic watch-progress behavior.

## Development Commands
- Start the local server:
  `python app.py`
- Compile Python after backend edits:
  `python -m compileall -q app.py routes core scripts`
- Run the lightweight safety suite:
  `python scripts/verify_refactor_safety.py`
- Run safe smoke checks:
  `python scripts/verify_refactor_safety.py --smoke`
- Check edited JavaScript files:
  `node --check static/js/admin/features/logModal.js`
- Check edited shared API helper/wrappers when touched:
  `node --check static/js/shared/api.js`
- Use targeted API smoke checks with Flask `app.test_client()` or `Invoke-RestMethod` before browser testing.

## Verification Checklist
- For admin UI changes, verify `/admin` loads and the target modal/table renders.
- For log/homework/progress changes, verify both:
  `/api/logs/entry?date=YYYY-MM-DD&sid=<sid>`
  and `/api/logs?date=YYYY-MM-DD&sid=<sid>`.
- After any patch that can affect class logs, always run a regression check for the admin log modal:
  1. Open a known student/date with existing `notes`, video progress, and `homeworkTable`.
  2. Confirm special notes load as readable Korean or are blank when the source is unrecoverable mojibake; never show `???`/`????`.
  3. Confirm homework book/current/next fields load without `???`/`????`.
  4. Toggle one green progress cell to white, save, reload `/admin`, reopen the same modal, and confirm it stays white.
  5. Confirm automatic watch progress does not override a manual white/skip setting.
- For video assignment changes, verify `/api/updates`, `/api/progress`, and the student bootstrap flow.
- For date-sensitive features, use the admin selected date, not the machine's real today, unless the feature explicitly needs real today.
- For admin row actions such as supplement/absence/contact/homework, use the row's own `data-date` when available. Use live `getAdminDate()` only as a fallback.
- For assigned tests in student bootstrap, preserve `progress[date][sid].tests` statuses as authoritative. Use log `assignedTests` as metadata/fallback without resurrecting stale cleared assignments.

## Coding Rules
- Follow the existing small-module structure rather than adding new frameworks.
- Keep frontend changes scoped to the relevant `static/js/admin/features/` module.
- Use `getAdminDate()` for admin operating-date behavior.
- Use `todayLocalKey()` only when the real local date is intended.
- Keep save logic merge-safe. Empty values must not erase existing meaningful data unless an explicit clear/delete field is used.
- Keep student bootstrap response shapes stable. In particular, `assignedTests` is a top-level array; do not change endpoint URLs or payload keys without a dedicated migration plan.
- In logs/progress code, SQLite and JSON fallbacks may both matter. Fill missing fields narrowly rather than replacing a whole entry from another store.
- Avoid large rewrites of existing modules unless the user asks for a refactor.
- Add comments only for non-obvious data-safety or merge behavior.

## Browser/UI Notes
- After frontend changes, reload the admin page before verifying.
- Prefer the Browser/in-app browser plugin for local UI verification. If it is unavailable, use the Chrome extension browser or Playwright fallback and report which path was used.
- Prefer DOM/API checks for exact data, then screenshot checks for visual regressions.
- Text must remain readable in Korean; verify UTF-8 rendering when touching static HTML/JS.
- Stop any dev server started only for verification unless the user asks to keep it running.

## Git Workflow
- Do not revert user changes.
- Keep commits focused by feature or fix.
- Before pushing, check `git status --short` and summarize runtime-data changes separately from code changes.
- Before committing, separate staged changes, unstaged changes, untracked files, and runtime/local data. Do not mix unrelated dirty work into the same commit.
- After verified work is complete and the user wants git registration, add only the intended files with explicit paths.

## GitHub Version Management
- Use GitHub as the patch-version ledger when the user asks to preserve, publish, or roll back code versions.
- Before code patches, check `git status --short` and note existing dirty files so unrelated user work is not mixed in or reverted.
- Runtime data is local operational data. Do not commit or push runtime data files unless the user explicitly asks for a data backup commit.
- Prefer code-only commits for app patches. Keep local student/video/homework/progress data separate from patch versioning.
- When the user asks to save a version, commit after verification, push to the configured GitHub remote, and report the branch/commit.
- When a rollback is needed, roll back code through Git/GitHub while preserving local runtime data unless the user explicitly asks to restore data too.
- Use branch names with the `codex/` prefix by default for new patch work.

## Known Risk Areas
- `logs.json` and `app.sqlite` are dual-write/dual-read stores. Keep their merge behavior compatible.
- `progress.json` is large and date/sid keyed. Avoid full replacement writes from the frontend.
- Older logs may contain legacy or corrupted text. Repair display and future saves without deleting unrelated fields.
- The admin page uses both cached frontend state and server refreshes; hydrate date/sid-scoped data before assuming `state` is complete.
