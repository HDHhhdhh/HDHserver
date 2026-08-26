# PROJECT KNOWLEDGE BASE

**Generated:** 2026-08-22 | **Commit:** 20cfa6e | **Branch:** codex/apple-clean-redesign

## Hierarchy
- `AGENTS.md`: repo-wide runtime-data, workflow, verification, and Git rules.
- `core/AGENTS.md`: pure rules, storage, repository, and network helpers.
- `routes/AGENTS.md`: Flask API/page blueprint contracts and route-level merge safety.
- `static/AGENTS.md`: static HTML/CSS shells and frontend asset boundaries.
- `static/css/AGENTS.md`: broad stylesheet cascade, responsive, modal, and Korean font rules.
- `static/js/AGENTS.md`: shared JavaScript contracts, student/test pages, and canonical answer-link map.
- `static/js/shared/AGENTS.md`: shared fetch, search, calendar, and self-study helpers.
- `static/js/admin/AGENTS.md`: admin module bootstrap, selected-date behavior, shared API wrapper usage.
- `static/js/admin/core/AGENTS.md`: admin date, API, state, theme, and view-mode helpers.
- `static/js/admin/demo/AGENTS.md`: demo-only fetch/store/navigation sandbox and tutorial system.
- `static/js/admin/features/AGENTS.md`: high-risk admin feature modules and row `data-date` actions.
- `static/js/all/AGENTS.md`: all-students page modules and API wrapper.
- `static/js/all/features/AGENTS.md`: all-students table, mutation buttons, roster export, and mini progress editor.
- `scripts/AGENTS.md`: verification, backup, import, and generated-output scripts.
- `tools/subjective_sheet_lab/AGENTS.md`: local ignored OCR-lab safety scope; provider calls, benchmark artifacts, and submit-flow prohibitions.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| App bootstrap | `app.py` | Flask app factory, guards, blueprint registration. |
| Core log/progress/video-review rules | `core/` | Keep pure rules separate from watch/progress writers, persistence/cache, and runtime notification bridges. |
| Backend APIs | `routes/` | `api_basic.py` is broadest; announcements, auth, tests, files, attendance, watch, and today metadata each have own blueprints. |
| Admin UI | `static/admin.html`, `static/js/admin/` | Use selected admin date and row `data-date` contracts. |
| Demo UI | `static/js/admin/demo/` | Loaded before five page entrypoints; must never leak API writes to the live server. |
| Styling/cascade | `static/css/` | `admin.css`, `student.css`, and `style.css` are broad shared surfaces. |
| Student video flow | `routes/api_basic.py`, `routes/api_watch.py`, `routes/api_kollus.py`, `static/js/student.js` | Auto assignment, bootstrap projection, Kollus playback, watch/progress sync, and local review registration form one contract. |
| Student UI/tests | `static/student.html`, `static/js/student.js`, `static/js/tests.js` | Preserve bootstrap `assignedTests`/`reviewVideos` shapes and academy-network gates. |
| Runtime checks | `scripts/verify_refactor_safety.py` | Main safety suite and smoke checks. |
| OCR lab | `tools/subjective_sheet_lab/` | Large ignored local corpus; read its child guide before any scan, provider call, or artifact generation. |

## Overview
- Local Flask academy-operations app with static HTML shells, native ES modules, and large standalone student/test scripts; no Jinja template tree or frontend build system.
- `app.py:create_app()` installs write/network guards and registers the flat blueprints. Runtime state lives beside the code in JSON and SQLite.

## Structure
```text
core/                    # rules, storage, repositories, network gates
routes/                  # static-page and API blueprints
static/                  # directly served HTML/CSS/JS shells
scripts/                 # safety harness plus operational writers/generators
tools/subjective_sheet_lab/  # ignored OCR lab; separate safety policy
```

## Code Map
Codegraph indexed 258 files; Python/JavaScript LSP servers are configured but not installed.

| Symbol | Location | Reach | Role |
|---|---|---:|---|
| `create_app` | `app.py:48` | registered blueprints | Server composition, cross-origin write guard, academy answer-map gate. |
| `save_atomic` | `core/storage.py:151` | 52 caller symbols | Atomic JSON replace plus best-effort mirror/snapshot; caller owns locking. |
| `get_log_repository` | `routes/api_basic.py:1283` | 7+ direct sites | Shared factory for log/bootstrap/attendance/test flows. |
| `LogRepository` | `core/log_repository.py:63` | 4 dependent files | SQLite-primary plus `logs.json` compatibility reads/writes. |
| `load_progress_strict` | `core/progress_store.py:31` | basic/watch plus compatibility consumers | Shared signature cache and strict progress JSON read boundary. |
| `save_watch_entry` | `core/watch_progress_writer.py:35` | watch/Kollus routes | Shared monotonic watch persistence and automatic progress bridge. |
| `clear_assignments_for_new_absences` | `core/absence_assignment_cleanup.py` | compatibility/tests | Date/SID-scoped absence assignment transformation rules across updates, progress tests, and class logs. |
| `apply_absence_transaction_locked` | `core/absence_transaction.py:233` | attendance/makeup/offline sync | Journaled all-store commit, rollback, and restart recovery for newly registered absences. |
| `resolve_video_review_states_before_date` | `core/video_review_rules.py:101` | bootstrap/self-study | Pure pre-date progress/watch projection for review eligibility. |
| `_ensure_today_auto_assign` | `routes/api_basic.py` | updates/bootstrap/event hooks | Server-owned real-today automatic assignment creation. |
| `getAdminDate` | `static/js/admin/core/adminDate.js:36` | admin modules | Selected admin operating date and change broadcast. |
| `bootstrap` | `static/js/admin/core/state.js:15` | admin entry | Initial real-today snapshot and compatibility globals. |
| `loadTodayAndRender` | `static/js/admin/features/today.js:858` | 3+ paths | Date-scoped admin hydration/render/event orchestrator. |
| `installDemoBootstrap` | `static/js/admin/demo/bootstrap.js:53` | 5 shells | Pre-entrypoint fetch/navigation sandbox for demo routes. |
| `loadInitialData` / `init` | `static/js/student.js:1483,2498` | student shell | Authoritative bootstrap aggregation; failures stop with an explicit load error. |
| `main` | `scripts/verify_refactor_safety.py:10147` | safety checks | Bespoke compile/source/temp-fixture/Node verification hub. |

## Runtime Data Safety
- Do not overwrite or reset runtime data files unless the user explicitly asks.
- Important data files include `students.json`, `videos.json`, `updates.json`, `progress.json`, `logs.json`, `app.sqlite`, `watch.json`, `attendance.json`, `contact.json`, `arrive_time.json`, `extra_attend.json`, `absent.json`, `weekend_slots.json`, `data/today_order.json`, `school_calendar.json`, and `tests.json`.
- `app.sqlite` is the sole supported root SQLite database. The empty, unreferenced legacy `vacation.db` was retired on 2026-08-24; do not recreate or ignore it.
- Treat SQLite sidecars such as `app.sqlite-wal`, `app.sqlite-shm`, `*.db-wal`, `*.db-shm`, root `*.tmp` files, `data/*.json`, `files/`, `instance/`, `_data_mirror/`, `_runtime_backups/`, `.codex_drive_download/`, `generated/`, and generated/downloaded operational outputs as runtime/local data when present.
- Importing `core.paths` (and therefore importing `app`) can create `files/` plus missing root JSON stores; do not treat import probes as filesystem-pure.
- Before data migrations or bulk repair, create a backup:
  `python scripts/backup_runtime_data.py`
- Prefer PATCH-style updates over full-file rewrites.
- Preserve existing keys and unknown fields when merging log/progress records.
- Keep JSON as UTF-8. Do not introduce mojibake or replacement text such as `????`.
- Be careful with "read-only" checks: log and assistant-note GETs can ensure/migrate SQLite schema or WAL state; `GET /api/updates` may auto-write `updates.json`; today's student bootstrap can do both.

## Agent Workflow
- Read this `AGENTS.md` first, then run `git status --short` before edits. Record pre-existing dirty, staged, and untracked files separately from files changed by the current task.
- Use subagents for broad or risky work only when the current tool policy and user request allow delegated agents. Keep subagents read-only unless a task explicitly gives them an edit scope.
- The main agent owns final synthesis, file edits, verification, and user-facing conclusions.
- Before the final response, clean up any open subagents by waiting for useful results or closing them, then report how subagents were used.
- When investigating Codex/OMO runtime issues, do not recursively search all of `%USERPROFILE%\.codex` or plugin cache folders. Inspect targeted config files, latest hook outputs, and recent sandbox log lines with tight output limits so command-runner pipes are not flooded.
- After completing work, run the relevant verification commands, check `git status --short`, and separate code changes from runtime-data changes.
- When the user asks for git registration/staging after completion, stage only the verified files in scope. Do not stage, unstage, revert, or normalize unrelated existing changes.

## Current Refactor Boundaries
- Frontend API calls should use the shared helper in `static/js/shared/api.js` when adding or touching admin/all JSON fetch wrappers. Preserve endpoint URLs, payload keys, cache behavior, and existing response shapes.
- Collection endpoints /api/students, /api/materials, and /api/logs are GET-only. Student writes use locked /api/add-student, /api/update, and DELETE /api/students/<sid>; logs use patch/batch routes. /api/fs/page-folders is retired as an HTTP surface, while PAGE_FOLDERS_PATH and existing runtime data remain compatibility state.
- File rename/move/delete/upload must acquire the file-tree lock before the deterministic material-state locks, recover any pending three-store journal, and use core/material_reference_rules.py for segment-aware descendant transforms. Preserve unknown fields and never update 교재실 when the target prefix is 교재.
- Material/bootstrap reads must load materials, assignments, and pageFolders as one `core.material_state` snapshot. `GET /api/mat-assign` returns `X-Material-State-Revision`; whole-map assignment POSTs require matching `If-Match` and return 409 when stale. A valid pending journal rolls forward at startup/read boundaries. An unreadable journal or store must not stop the server: material reads use the last-good snapshot (or empty read-only fallback), while material/file mutations return 503.
- Off-academy non-public administrator APIs require the same HTTP Basic credentials as protected admin pages. Do not apply that guard ahead of public/mobile sessions or the legacy student routes that own academy, SID, callback-secret, or credential checks (`get-url`, bootstrap, watch, auth, student announcement actions, feedback, Kollus callback, ping).
- Absence consistency barriers must cover every related progress writer, including `/api/watch`, `/api/watch-status`, and `/api/kollus/lms-callback`, so playback cannot recreate progress during an absence commit.
- Class log reads/writes should go through `get_log_repository()` / `LogRepository` instead of open-coding SQLite + `logs.json` merge behavior in route handlers. Keep SQLite and JSON fallback compatibility when changing log flows.
- Pure class-log rules belong in `core/log_rules.py`. Keep `merge_log_entry_safe`, `log_entry_conflicts_with_base`, homework-row comparison normalization, and `truthy` semantics centralized there.
- Keep runtime-data repair and hydration separate from pure rules. For example, `_repair_log_entry_placeholders()` currently stays in `routes/api_basic.py` because homework placeholder repair can read `students.json` through student book lookup.
- Do not merge watch/progress auto-status rules into log rules. Pure transitions live in `core/progress_rules.py`, shared watch/automatic-progress writes in `core/watch_progress_writer.py`, strict progress persistence in `core/progress_store.py`, and milestone hooks in `core/progress_notifications.py`. `api_watch` and `api_kollus` must use the shared writer and must not import each other or private helpers from `api_basic`; preserve focused manual white/skip/interrupted, timestamp, callback-auth, and automatic watch-progress tests.
- Newly registered absence pairs use the journaled coordinator in `core/absence_transaction.py` through `routes/absence_assignment_cleanup.py`; attendance, makeup sheet sync, and the offline sync script must not import each other. Preserve carryover-before-clear semantics and the logical order updates → progress → logs → absent → carryover. Success commits every store, synchronous failure restores every narrow before-image, unfinished non-committed journals roll back before startup/new writes, and related API reads/writes wait on the coordinator barrier. Notifications remain post-commit and outside this transaction.
- The server owns automatic video snapshots and may create one only for the real current KST date. Bare `GET /api/updates`, the admin date-boundary refresh, a non-public real-today student bootstrap, and real-today schedule events may initialize a missing snapshot; historical/future reads and future schedule events are storage-only. Never persist a future `source: "auto"` snapshot. An existing today snapshot is date-bound: progress, watch, schedule, absence, consecutive-slot, and count-setting changes must never resize or refill it. The configured count doubles when today has adjacent active class slots after weekend overrides and slot absences. Count-setting writes update only the student setting for the next date-boundary creation. Explicit future `manual` and `selfStudy` entries remain protected. Admin modal hydration must use `GET /api/updates?readOnly=1`. The retired student-side “copy the last assignment” writer must not be restored; automatic assignment authority stays on the server.
- Keep assignment meanings distinct: `source: "auto"` is a server-created date snapshot (only an explicit curriculum change may rebase stale course MIDs), `source: "manual"` and `source: "selfStudy"` are protected explicit assignments, and student “영상 등록” is only a SID/date-scoped local playlist preference. It must not write `updates.json`, class logs, counseling history, progress, or watch state until playback actually occurs.
- Student `reviewVideos` is an authoritative sanitized bootstrap projection. The chooser accepts only current-curriculum `done` items through the requested date; it must not infer membership from the catalog, progress/watch maps, or localStorage. Server-side self-study selection is narrower and accepts only completed items strictly before the assignment date.
- Keep watch thresholds shared at 5% `interrupted` and 90%/completed `done`. Automatic watch writes must preserve manual white/`none`, `skip`, and manual `interrupted` ownership metadata, and must never advance, remove, or refill an existing auto snapshot.
- Keep assistant-student notes isolated from class-log notes, counseling records, CSV/print exports, and browser storage even though both repositories share `app.sqlite`.
- When updating test catalog CSV data from the test management page or related import scripts, keep the student personal-page explanation links in sync. For `REVIEW` and `SCHOOL_PAST`, preserve/update `sourceFiles.solutionFileId` or equivalent solution metadata in `tests-config.json`; for `UNIT`, regenerate/update `static/js/test_answer_link_map.json` from the Drive explanation files and never recreate the retired `.js` wrapper. Verify `/api/student/bootstrap` returns `assignedTests[].answerUrl` and the student page renders today-test cards as Drive explanation links.

## Commands
```powershell
python app.py
python -m compileall -q app.py routes core scripts
python scripts/verify_refactor_safety.py
python scripts/verify_refactor_safety.py --smoke
node --check <edited-file.js>
```
`--smoke` imports the live app and permits WAL/SHM churn; it is not equivalent to a pure unit suite.

## Verification Notes
- For admin UI changes, reload `/admin`, verify the target modal/table with DOM/API evidence, then run screenshot QA when layout changed.
- Log/homework/progress work requires both log endpoints plus the browser regression in `static/js/admin/features/AGENTS.md`; a green-to-white manual state must survive reload and automatic watch updates.
- Video assignment work spans `videos.json`, `updates.json`, `progress.json`, `watch.json`, `/api/get-url`, student bootstrap, the admin modal, and the student playlist. Run the focused auto-assignment/watch/review checks before the full suite.
- Student review UI changes require `node scripts/verify_student_previous_video_review.js` plus `node scripts/verify_student_material_access_scope.js`; keep both fixtures aligned with the done-only chooser and title-only outside-academy response.
- Student-test work must preserve progress-authoritative assignments, top-level `assignedTests`, answer-link precedence, academy-network stripping, and historical record reads. Student submission, grading, OCR capture/review routes, and `/student-test/<sid>` are retired; rebuild them as a new feature instead of reviving legacy code.
- Test answer-link precedence lives in `core/test_answer_links.py`. `api_tests` must use the public resolver and `core.storage.file_lock`, not private helpers from `api_basic`; preserve direct assignment → config metadata → generated map order and academy-network stripping.
- Public announcement files require all three gates: a safe one-segment `/files/announcements/<name>` request, an active public SID, and current SID-visible membership in `announcements.json`. Keep membership in `core/announcement_image_access.py`; `api_fs` must not import private announcement-route helpers.
- The default suite is bespoke and incomplete; targeted `--only-*` modes do not replace the full run, and CI does not run live smoke or browser QA.

## Coding Rules
- Follow the existing small-module structure rather than adding new frameworks.
- Keep frontend changes scoped to the relevant `static/js/admin/features/` module.
- Use `todayLocalKey()` only when the real local date is intended.
- Keep save logic merge-safe. Empty values must not erase existing meaningful data unless an explicit clear/delete field is used.
- Keep student bootstrap response shapes stable. In particular, `assignedTests` is a top-level array; do not change endpoint URLs or payload keys without a dedicated migration plan.
- In logs/progress code, SQLite and JSON fallbacks may both matter. Fill missing fields narrowly rather than replacing a whole entry from another store.
- Avoid large rewrites of existing modules unless the user asks for a refactor.
- Add comments only for non-obvious data-safety or merge behavior.

## Browser/UI Notes
- After frontend changes, reload the admin page before verifying.
- Prefer the Browser/in-app browser plugin for local UI verification. If it is unavailable, use the Chrome extension browser or Playwright fallback and report which path was used.
- Never start any additional `app:app` or Flask development server while production port 8003 is running. A loopback 8003 listener can steal Cloudflare traffic, while an 8004 listener still shares the repository JSON/SQLite runtime and can block production locks. Reuse the live server for read-only checks, use demo/test-client fixtures, or stop production before isolated server work; always stop verification listeners after testing.
- Prefer DOM/API checks for exact data, then screenshot checks for visual regressions.
- Text must remain readable in Korean; verify UTF-8 rendering when touching static HTML/JS.
- Stop any dev server started only for verification unless the user asks to keep it running.

## Git Workflow
- Do not revert user changes.
- Keep commits focused by feature or fix.
- Before pushing, check `git status --short` and summarize runtime-data changes separately from code changes.
- Before committing, separate staged changes, unstaged changes, untracked files, and runtime/local data. Do not mix unrelated dirty work into the same commit.
- After verified work is complete and the user wants git registration, add only the intended files with explicit paths.
- Runtime data is local operational data. Do not commit or push runtime data files unless the user explicitly asks for a data backup commit.
- Prefer code-only commits for app patches. Keep local student/video/homework/progress data separate from patch versioning.
- Use branch names with the `codex/` prefix by default for new patch work.

## Known Risk Areas
- `logs.json` and `app.sqlite` are dual-write/dual-read stores. Keep their merge behavior compatible.
- `progress.json` is large and date/sid keyed. Avoid full replacement writes from the frontend.
- Normal `POST /api/videos` rejects removal of an existing video ID or a URL-derived MID change with 409 before writing. Same-MID signed URL/metadata edits and new rows remain allowed. Do not add a request bypass. The supported correction path is the browser-only draft in `video-manage.js`, dry-run/apply through `scripts/apply_video_catalog_correction.ps1`, a stopped Waitress listener, a fresh verified runtime backup, and the pure four-store transform in `core/video_catalog_correction.py`. Referenced deletion fails closed; correction drafts contain full URLs and must not be committed.
- Watch `updatedAt` is epoch milliseconds. `student.js` must normalize without bitwise coercion, and the server must preserve valid millisecond values while repairing legacy 32-bit values; keep both wire regression checks when changing serialization or merge logic.
- `/api/kollus/lms-callback` fails closed when `KOLLUS_CALLBACK_SECRET` is unset and validates the configured secret or signed token. Keep callback verification separate from the academy-only browser playback gate.
- Whole-map `/api/absent` writes with a shape-valid but impossible calendar date currently return 500 before creating a journal. User choice B keeps this as a known limitation; preserve the verified no-write/no-notification outcome, but do not describe 500 as a desirable API contract.
- Older logs may contain legacy or corrupted text. Repair display and future saves without deleting unrelated fields.
- The admin page uses both cached frontend state and server refreshes; hydrate date/sid-scoped data before assuming `state` is complete.
- `data/today_order.json` is the sole today-order store. The retired root `today_order.json` was migrated and removed; do not recreate it or add a second path.
- Unreferenced static assets may still be directly servable by filename; confirm external/manual use before deleting them. Do not restore the retired `static/main.html`, `static/student copy.html`, or `static/js/student copy.js` files as alternate student surfaces.
- There is no dependency manifest or frontend package runner. CI pins Python 3.11 and Node 20 but only compiles and invokes the custom safety harness.
