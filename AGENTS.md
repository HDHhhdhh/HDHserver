# PROJECT KNOWLEDGE BASE

**Generated:** 2026-07-16 | **Commit:** 58648c8 | **Branch:** codex/apple-clean-redesign

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
| Core log/progress rules | `core/` | Keep pure rules separate from storage/runtime repair. |
| Backend APIs | `routes/` | `api_basic.py` is broadest; announcements, auth, tests, files, attendance, watch, and today metadata each have own blueprints. |
| Admin UI | `static/admin.html`, `static/js/admin/` | Use selected admin date and row `data-date` contracts. |
| Demo UI | `static/js/admin/demo/` | Loaded before five page entrypoints; must never leak API writes to the live server. |
| Styling/cascade | `static/css/` | `admin.css`, `student.css`, and `style.css` are broad shared surfaces. |
| Student UI/tests | `static/student.html`, `static/js/student.js`, `static/js/tests.js` | Preserve bootstrap `assignedTests` shape and answer links. |
| Runtime checks | `scripts/verify_refactor_safety.py` | Main safety suite and smoke checks. |
| OCR lab | `tools/subjective_sheet_lab/` | Large ignored local corpus; read its child guide before any scan, provider call, or artifact generation. |

## Overview
- Local Flask academy-operations app with static HTML shells, native ES modules, and large standalone student/test scripts; no Jinja template tree or frontend build system.
- `app.py:create_app()` installs write/network guards and registers 13 flat blueprints. Runtime state lives beside the code in JSON and SQLite.

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
| `create_app` | `app.py:29` | 13 blueprints | Server composition, cross-origin write guard, academy answer-map gate. |
| `save_atomic` | `core/storage.py:151` | 52 caller symbols | Atomic JSON replace plus best-effort mirror/snapshot; caller owns locking. |
| `get_log_repository` | `routes/api_basic.py:1315` | 7+ direct sites | Shared factory for log/bootstrap/attendance/test flows. |
| `LogRepository` | `core/log_repository.py:61` | 4 dependent files | SQLite-primary plus `logs.json` compatibility reads/writes. |
| `getAdminDate` | `static/js/admin/core/adminDate.js:20` | 44 call sites | Selected admin operating date and change broadcast. |
| `bootstrap` | `static/js/admin/core/state.js:15` | admin entry | Initial real-today snapshot and compatibility globals. |
| `loadTodayAndRender` | `static/js/admin/features/today.js:788` | 3+ paths | Date-scoped admin hydration/render/event orchestrator. |
| `installDemoBootstrap` | `static/js/admin/demo/bootstrap.js:47` | 5 shells | Pre-entrypoint fetch/navigation sandbox for demo routes. |
| `loadInitialData` / `init` | `static/js/student.js:543,1022` | student shell | Bootstrap aggregation with seven-endpoint legacy fallback. |
| `main` | `scripts/verify_refactor_safety.py:5072` | 49 checks | Bespoke compile/source/temp-fixture/Node verification hub. |

## Runtime Data Safety
- Do not overwrite or reset runtime data files unless the user explicitly asks.
- Important data files include `students.json`, `videos.json`, `updates.json`, `progress.json`, `logs.json`, `app.sqlite`, `watch.json`, `attendance.json`, `contact.json`, `arrive_time.json`, `extra_attend.json`, `absent.json`, `weekend_slots.json`, `today_order.json`, `school_calendar.json`, and `tests.json`.
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
- Class log reads/writes should go through `get_log_repository()` / `LogRepository` instead of open-coding SQLite + `logs.json` merge behavior in route handlers. Keep SQLite and JSON fallback compatibility when changing log flows.
- Pure class-log rules belong in `core/log_rules.py`. Keep `merge_log_entry_safe`, `log_entry_conflicts_with_base`, homework-row comparison normalization, and `truthy` semantics centralized there.
- Keep runtime-data repair and hydration separate from pure rules. For example, `_repair_log_entry_placeholders()` currently stays in `routes/api_basic.py` because homework placeholder repair can read `students.json` through student book lookup.
- Do not merge watch/progress auto-status rules into log rules. `routes/api_basic.py` and `routes/api_watch.py` still contain duplicated watch/progress transition logic; extract it only with focused tests for manual white/skip preservation and automatic watch-progress behavior.
- Keep assistant-student notes isolated from class-log notes, counseling records, CSV/print exports, and browser storage even though both repositories share `app.sqlite`.
- When updating test catalog CSV data from the test management page or related import scripts, keep the student personal-page explanation links in sync. For `REVIEW` and `SCHOOL_PAST`, preserve/update `sourceFiles.solutionFileId` or equivalent solution metadata in `tests-config.json`; for `UNIT`, regenerate/update `static/js/test_answer_link_map.json` from the Drive explanation files. Verify `/api/student/bootstrap` returns `assignedTests[].answerUrl` and the student page renders today-test cards as Drive explanation links.

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
- Video assignment work spans `/api/updates`, `/api/progress`, watch state, and student bootstrap.
- Student-test work must preserve progress-authoritative statuses, top-level `assignedTests`, answer-link precedence, and academy-network stripping.
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
- Older logs may contain legacy or corrupted text. Repair display and future saves without deleting unrelated fields.
- The admin page uses both cached frontend state and server refreshes; hydrate date/sid-scoped data before assuming `state` is complete.
- Live admin today-order routes use `data/today_order.json`, while `core.paths.TODAY_ORDER_PATH` points at the root file; do not assume those stores are unified.
- `static/main.html`, `static/student copy.html`, and similarly unreferenced assets remain directly servable; confirm external/manual use before deletion.
- There is no dependency manifest or frontend package runner. CI pins Python 3.11 and Node 20 but only compiles and invokes the custom safety harness.
