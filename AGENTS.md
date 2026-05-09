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
- `static/js/admin/main.js`: admin frontend entrypoint.
- `static/js/admin/features/logModal.js`: class log, homework, and video progress modal.
- `static/js/admin/features/today*.js`: today list state and rendering.
- `scripts/backup_runtime_data.py`: zip backup for runtime data.

## Runtime Data Safety
- Do not overwrite or reset runtime data files unless the user explicitly asks.
- Important data files include `students.json`, `videos.json`, `updates.json`, `progress.json`, `logs.json`, `app.sqlite`, `watch.json`, `attendance.json`, `contact.json`, `arrive_time.json`, `extra_attend.json`, `absent.json`, `weekend_slots.json`, `today_order.json`, `school_calendar.json`, and `tests.json`.
- Before data migrations or bulk repair, create a backup:
  `python scripts/backup_runtime_data.py`
- Prefer PATCH-style updates over full-file rewrites.
- Preserve existing keys and unknown fields when merging log/progress records.
- Keep JSON as UTF-8. Do not introduce mojibake or replacement text such as `????`.

## Development Commands
- Start the local server:
  `python app.py`
- Compile Python after backend edits:
  `python -m py_compile app.py routes/*.py core/*.py`
- Check edited JavaScript files:
  `node --check static/js/admin/features/logModal.js`
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

## Coding Rules
- Follow the existing small-module structure rather than adding new frameworks.
- Keep frontend changes scoped to the relevant `static/js/admin/features/` module.
- Use `getAdminDate()` for admin operating-date behavior.
- Use `todayLocalKey()` only when the real local date is intended.
- Keep save logic merge-safe. Empty values must not erase existing meaningful data unless an explicit clear/delete field is used.
- Avoid large rewrites of existing modules unless the user asks for a refactor.
- Add comments only for non-obvious data-safety or merge behavior.

## Browser/UI Notes
- After frontend changes, reload the admin page before verifying.
- Prefer DOM/API checks for exact data, then screenshot checks for visual regressions.
- Text must remain readable in Korean; verify UTF-8 rendering when touching static HTML/JS.

## Git Workflow
- Do not revert user changes.
- Keep commits focused by feature or fix.
- Before pushing, check `git status --short` and summarize runtime-data changes separately from code changes.

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
