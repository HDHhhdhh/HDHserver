# PROJECT KNOWLEDGE BASE

**Maintained guidance:** business-rule ownership starts at
[`docs/SERVER_RULES_INDEX.md`](docs/SERVER_RULES_INDEX.md). This file owns
repository-wide edit, runtime-data, verification, and Git safety.

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
- `docs/SERVER_RULES_INDEX.md`: canonical rule ownership and links to meaning, implementation, decisions, and verification.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| App bootstrap | `app.py` | Flask app factory, guards, blueprint registration. |
| Person identity/student roster | `core/person_identity.py`, `core/person_identity_store.py`, `routes/api_students.py` | `persons.json` owns stable people; `students.json` owns subject/SID rows. |
| Canonical date-key validation | `core/date_rules.py` | Exact real-calendar `YYYY-MM-DD` parsing shared by date-indexed route/store boundaries. |
| Core log/progress/student-video rules | `core/` | Keep pure schedule, projection, and assignment transforms separate from watch/progress writers, persistence/cache, and runtime notification bridges. |
| Backend APIs | `routes/` | `api_basic.py` is broadest; announcements, auth, tests, files, attendance, watch, and today metadata each have own blueprints. |
| Video catalog API | `routes/api_videos.py` | Dedicated locked `/api/videos` GET/POST boundary and normal-mode identity-change guard. |
| Progress API | `routes/api_progress.py` | Dedicated `/api/progress` GET filtering and locked `/api/progress/patch` merge/notification boundary. |
| Video assignment API | `routes/api_updates.py` | Dedicated `/api/updates*` HTTP boundary with app-injected automatic/self-study assignment services. |
| Student bootstrap API | `routes/api_student_bootstrap.py`, `routes/student_bootstrap_projection.py` | Dedicated HTTP/public-session boundary plus Flask-free aggregate projection with app-injected dependencies. |
| Class log API | `routes/api_logs.py`, `routes/log_repository_provider.py` | Dedicated log/homework-book HTTP boundary plus route-side placeholder repair and shared repository factory. |
| Material API | `routes/api_materials.py`, `routes/material_state_provider.py` | Dedicated `/api/materials` and revisioned `/api/mat-assign` HTTP boundary plus coherent degraded-read projection. |
| Schedule override API | `routes/api_schedule_overrides.py` | Dedicated `/api/extra-attend` and `/api/weekend-slots` boundary with app-injected automatic-assignment hooks. |
| Admin UI | `static/admin.html`, `static/js/admin/` | Use selected admin date and row `data-date` contracts. |
| Demo UI | `static/js/admin/demo/` | Loaded before five page entrypoints; must never leak API writes to the live server. |
| Styling/cascade | `static/css/` | `admin.css`, `student.css`, and `style.css` are broad shared surfaces; `tests.css` owns only the test-management page overrides. |
| Student video flow | `core/student_schedule_rules.py`, `core/student_video_projection.py`, `core/student_video_assignment_rules.py`, `routes/student_auto_assignment_service.py`, `routes/api_videos.py`, `routes/api_progress.py`, `routes/api_updates.py`, `routes/api_student_bootstrap.py`, `routes/student_bootstrap_projection.py`, `routes/api_basic.py`, `routes/api_watch.py`, `routes/api_kollus.py`, `static/js/student/bootstrapState.js`, `static/js/student/watchState.js`, `static/js/student/playback.js`, `static/js/student/reviewPlaylist.js`, `static/js/student.js` | Pure schedule/projection/assignment rules, path-injected runtime orchestration, catalog and update HTTP, browser bootstrap state, local watch storage/sync, active-MID playback, and authorized local review registration form one contract. |
| Student UI/tests | `static/student.html`, `static/js/student/bootstrapState.js`, `static/js/student/watchState.js`, `static/js/student/playback.js`, `static/js/student/reviewPlaylist.js`, `static/js/student/announcementState.js`, `static/js/student/testPresentation.js`, `static/js/student.js`, `static/js/tests.js` | Preserve bootstrap `assignedTests`/`reviewVideos` shapes, watch/playback payloads, local review scope, announcement transitions, test-card projection, and academy-network gates. |
| Runtime checks | `scripts/verify_refactor_safety.py` | Main safety suite and smoke checks. |
| OCR lab | `tools/subjective_sheet_lab/` | Large ignored local corpus; read its child guide before any scan, provider call, or artifact generation. |

## Overview
- Local Flask academy-operations app with static HTML shells, native ES modules, and large standalone student/test scripts; no Jinja template tree or frontend build system.
- `app.py:create_app()` installs write/network guards and registers the flat blueprints. Runtime state lives beside the code in JSON and SQLite.
- For semantic conflicts, use the actual-versus-intended model in the Rules Index: verified code/runtime describes actual behavior; the latest approved decision and canonical logic document describe intent; any mismatch is implementation drift.

## Structure
```text
core/                    # rules, storage, repositories, network gates
routes/                  # static-page and API blueprints
static/                  # directly served HTML/CSS/JS shells
scripts/                 # safety harness plus operational writers/generators
tools/subjective_sheet_lab/  # ignored OCR lab; separate safety policy
```

## Code Map
Use `rg` or symbol search for current locations; line numbers and reach counts are
deliberately not duplicated here because they drift.

| Symbol | Location | Role |
|---|---|---|
| `create_app` | `app.py` | Server composition, cross-origin write guard, academy answer-map gate. |
| `save_atomic` | `core/storage.py` | Atomic JSON replace plus best-effort mirror/snapshot; caller owns locking. |
| `load_identity_state_strict` / person mutations | `core/person_identity_store.py` | Strict journaled `persons.json` + `students.json` identity boundary. |
| `configure_student_identity_assignment_hooks` | `routes/api_students.py`, `app.py` | Composes roster writes with public automatic-assignment callbacks without importing `api_basic` private helpers. |
| `get_log_repository` | `routes/log_repository_provider.py` | Shared factory for log/bootstrap/attendance/test flows; `api_basic.py` re-exports it for compatibility. |
| `load_material_state_for_read` | `routes/material_state_provider.py` | Path-injected coherent materials/assignments/page-folders read with last-good degradation. |
| `LogRepository` | `core/log_repository.py` | SQLite-primary plus `logs.json` missing-field compatibility merge and dual writes. |
| `load_progress_strict` | `core/progress_store.py` | Shared signature cache and strict progress JSON read boundary. |
| `parse_iso_date_key` | `core/date_rules.py` | Pure exact `YYYY-MM-DD` parser that rejects impossible, compact, and timestamp-shaped keys. |
| `save_watch_entry` | `core/watch_progress_writer.py` | Shared monotonic watch persistence and automatic progress bridge. |
| `clear_assignments_for_new_absences` | `core/absence_assignment_cleanup.py` | Date/SID-scoped absence assignment transformations. |
| `apply_absence_transaction_locked` | `core/absence_transaction.py` | Journaled all-store commit, rollback, and restart recovery for new absences. |
| `resolve_video_review_states_before_date` | `core/video_review_rules.py` | Pure pre-date progress/watch projection for review eligibility. |
| `effective_auto_video_assign_count` | `core/student_schedule_rules.py` | Pure date/slot/self-study/absence schedule interpretation. |
| `student_review_video_projection` | `core/student_video_projection.py` | Pure current-course completion, blocking, filtering, and sanitized review projection. |
| `advance_existing_auto_assignment` | `core/student_video_assignment_rules.py` | Pure metadata-preserving auto-assignment rebase/append transforms. |
| `load_updates_with_auto_assign` / `reconcile_self_study_assignment` | `routes/student_auto_assignment_service.py` | Path/dependency-injected absence barrier, real-today loads, locks, persistence, automatic initialization, and self-study reconciliation. |
| `_ensure_today_auto_assign` | `routes/api_basic.py` | Compatibility wrapper over the injected assignment service. |
| `configure_updates_assignment_hooks` | `routes/api_updates.py`, `app.py` | Composes the update HTTP boundary with public automatic/self-study services without importing `api_basic` private helpers. |
| `configure_student_bootstrap_projection` | `routes/api_student_bootstrap.py`, `app.py` | Composes the bootstrap HTTP/public-session boundary with an explicit projection dependency bundle. |
| `build_student_bootstrap_payload` | `routes/student_bootstrap_projection.py` | Flask-free aggregate payload, course-block, review, material, and test projection. |
| `configure_schedule_override_assignment_hooks` | `routes/api_schedule_overrides.py`, `app.py` | Composes schedule-store HTTP writes with public auto-assignment callbacks without private cross-blueprint imports. |
| `getAdminDate` | `static/js/admin/core/adminDate.js` | Selected admin operating date and change broadcast. |
| `bootstrap` | `static/js/admin/core/state.js` | Initial real-today snapshot and compatibility globals. |
| `loadTodayAndRender` | `static/js/admin/features/today.js` | Date-scoped admin hydration/render/event orchestrator. |
| `installDemoBootstrap` | `static/js/admin/demo/bootstrap.js` | Pre-entrypoint fetch/navigation sandbox for demo routes. |
| `loadInitialData` | `static/js/student/bootstrapState.js` | Injected public/non-public bootstrap plus concurrent latest-watch load and fixed initial-state projection. |
| `createController` | `static/js/student/watchState.js` | Injected local watch merge/storage, millisecond serialization, debounce, retry, and `/api/watch` flush boundary. |
| `StudentPlayback.createController` | `static/js/student/playback.js` | Injected active MID, resume URL, `/api/get-url`, iframe bridge, and Kollus progress event boundary. |
| `StudentReviewPlaylist.createController` | `static/js/student/reviewPlaylist.js` | Injected SID/date storage key, fresh-authority prune, ordered selection, registration, and cancellation boundary. |
| `StudentAnnouncementState.createController` | `static/js/student/announcementState.js` | DOM/transport-free announcement pending, acknowledgement, survey/reply, strict board projection, filter, and pagination state boundary. |
| `StudentTestPresentation.viewModel` | `static/js/student/testPresentation.js` | DOM/transport-free assigned-test normalization, labels, answer access, card metadata, pending count, and mobile navigation rule. |
| `init` | `static/js/student.js` | Session redirect, cache hydration, DOM rendering, and explicit load-error stop. |
| `visibleCatalogTests` / write request projections | `static/js/tests/catalogState.js` | DOM/transport-free test-catalog normalization, search/sort/grouping, order gates, revision headers, and rollback snapshots. |
| `projectAnswerRound` / CSV projections | `static/js/tests/catalogEditorState.js` | DOM/transport-free answer parsing/modes, round merge projection, CSV template/parser/header aliases, and row answer projection. |
| `projectStatsRows` / `projectStatsDetail` | `static/js/tests/catalogStatisticsState.js` | DOM/transport-free statistics lookup, summary, search/sort, record-detail, and wrong-answer presentation projection. |
| Test-management cascade | `static/css/tests.css` | Page-scoped catalog/editor/statistics/modal styles loaded after shared `main.css` and `admin.css`. |
| `main` | `scripts/verify_refactor_safety.py` | Bespoke compile/source/temp-fixture/Node verification hub. |

## Runtime Data Safety
- Do not overwrite or reset runtime data files unless the user explicitly asks.
- The canonical inventory and ownership are [`RULE-DATA-001`](docs/SERVER_RULES_INDEX.md#rule-data-001) and [the data-source table](docs/PROJECT_FUNCTIONS_AND_LOGIC.md). Do not maintain a second supposedly complete filename list here.
- `persons.json`, `students.json`, and the person-identity journal are runtime data. Once person identity is configured, a missing or partial identity store is a fault to diagnose, not permission to create an empty replacement.
- `app.sqlite` is the sole supported root SQLite database. The empty, unreferenced legacy `vacation.db` was retired on 2026-08-24; do not recreate or ignore it.
- Treat SQLite sidecars such as `app.sqlite-wal`, `app.sqlite-shm`, `*.db-wal`, `*.db-shm`, root `*.tmp` files, `data/*.json`, `files/`, `instance/`, `_data_mirror/`, `_runtime_backups/`, `.codex_drive_download/`, `generated/`, and generated/downloaded operational outputs as runtime/local data when present.
- Importing `core.paths` (and therefore importing `app`) can create `files/` plus missing root JSON stores; do not treat import probes as filesystem-pure.
- Before data migrations or bulk repair, create a backup:
  `python scripts/backup_runtime_data.py`
- Prefer PATCH-style updates over full-file rewrites.
- Preserve existing keys and unknown fields when merging log/progress records.
- Keep JSON as UTF-8. Do not introduce mojibake or replacement text such as `????`.
- Be careful with "read-only" checks: log and assistant-note GETs can ensure/migrate SQLite schema or WAL state; `GET /api/updates` may auto-write `updates.json`; today's student bootstrap can do both.
- Log-GET smoke is opt-in only: run `python scripts/verify_refactor_safety.py --smoke --smoke-log-gets` after `python scripts/backup_runtime_data.py`. The verifier compares `mtime_ns`, size, and SHA-256 for main databases and sidecars; any main-database change, including an mtime-only change, fails. `--smoke-log-gets` without `--smoke` is invalid.

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
- Collection endpoints /api/students, /api/materials, and /api/logs are GET-only. `routes/api_students.py` owns `/api/students`, `/api/add-student`, `/api/update`, and `DELETE /api/students/<sid>`; logs use patch/batch routes. /api/fs/page-folders is retired as an HTTP surface, while PAGE_FOLDERS_PATH and existing runtime data remain compatibility state.
- Person identity follows [`RULE-IDENTITY-001`](docs/SERVER_RULES_INDEX.md#rule-identity-001): `persons.json` is the production person contract and `students.json` keeps subject/SID rows. Add, clone, update, and delete must use `core/person_identity_store.py` so the two stores commit through one journaled boundary. Shared profile fields and SID-specific fields stay distinct; `id` and `personId` are immutable. A configured partial/unreadable state fails closed with 503 rather than falling back to or recreating an empty store. Keep those HTTP routes out of `api_basic.py`; `app.py` injects only its public automatic-assignment callbacks into the student blueprint.
- White-review inspection pending follows [`RULE-WHITE-REVIEW-001`](docs/SERVER_RULES_INDEX.md#rule-white-review-001): `students.json.whiteReviewPending` is an exact-boolean SID field edited only through the locked/journaled student update boundary. Today-table date changes, leave/homework-leave, record cleanup, logs, attendance, and progress must not clear or rewrite it. Preserve the fixed `진도 → 백지 → 작업 → 보강 → 문서` column contract without changing the today-table total width or other admin spacing.
- `routes/api_updates.py` owns `GET /api/updates`, `POST /api/updates/patch`, and `POST /api/updates/self-study`; keep these HTTP routes out of `api_basic.py`. `app.py` injects public initializer/reconciliation services. SID/merge/source rules live in `core/update_assignment_rules.py`; strict object persistence and the canonical updates lock live in `core/update_assignment_store.py`. Follow [`RULE-VIDEO-001`](docs/SERVER_RULES_INDEX.md#rule-video-001): only a missing `updates.json` is empty, while unreadable/non-object state fails closed without rewriting the source bytes. PATCH accepts only an object body and an exact JSON boolean `remove`; it validates the final locked merge so omitting `source` cannot retain or modify a future `source:auto` assignment.
- `routes/api_student_bootstrap.py` owns `GET /api/student/bootstrap`, public-session SID binding, academy-network response sanitization, latest-watch projection, and no-cache response composition. `routes/student_bootstrap_projection.py` owns the Flask-free aggregate payload. `app.py` injects the explicit dependency bundle built by `api_basic.py`; keep the endpoint and duplicate payload assembly out of `api_basic.py`. Preserve ghost, course-blocked, `assignedTests`, `reviewVideos`, and public/mobile response shapes.
- `static/js/student/bootstrapState.js` owns browser-side bootstrap/watch load and fixed nine-slot compatibility projection. `static/js/student/watchState.js` owns SID-scoped watch localStorage, monotonic merge, millisecond-safe snapshots, debounce/retry, and `/api/watch` transport. `static/js/student/playback.js` owns active MID, resume URL, `/api/get-url`, iframe controller attachment, same-window/MID message filtering, and Kollus progress projection. `static/js/student/reviewPlaylist.js` owns the injected SID/date local key, fresh-bootstrap prune, ordered pending selection, registration, and cancellation. `static/js/student/announcementState.js` owns strict announcement/board normalization, pending and completion semantics, ack/survey/reply transitions, reply limits, board filtering, and pagination merge. `static/js/student/testPresentation.js` owns assigned-test normalization, status/difficulty labels, answer access projection, card metadata, pending count, and mobile same-tab rules. Both modules remain free of DOM, fetch, and ambient storage. `student.html` must load all six in that order before `student.js`; keep authoritative `reviewVideos` access/blocking, assignment interpretation, playlist/DOM badges, page lifecycle wiring, test-card element creation/click behavior, announcement transport/modal/accessibility/user feedback, board scroll events, redirect mutation, and error text composition in `student.js`, and never add legacy partial-data fallback requests.
- File rename/move/delete/upload must acquire the file-tree lock before the deterministic material-state locks, recover any pending three-store journal, and use core/material_reference_rules.py for segment-aware descendant transforms. Preserve unknown fields and never update 교재실 when the target prefix is 교재.
- Material/bootstrap reads must load materials, assignments, and pageFolders as one `core.material_state` snapshot. `routes/api_materials.py` owns `/api/materials` and `/api/mat-assign`; keep those HTTP routes out of `api_basic.py`, while bootstrap may use the path-injected provider. `GET /api/mat-assign` returns `X-Material-State-Revision`; whole-map assignment POSTs require matching `If-Match` and return 409 when stale. A valid pending journal rolls forward at startup/read boundaries. An unreadable journal or store must not stop the server: material reads use the last-good snapshot (or empty read-only fallback), while material/file mutations return 503.
- School-calendar HTTP ownership is `routes/api_school_calendar.py`; strict reads and compare-and-replace use `core.school_calendar_store`. GET returns `X-School-Calendar-Revision` plus ETag, while whole-document POST requires the preceding revision in `If-Match`; missing/invalid returns 428 and stale returns 409 without writing. Pure document/edit-row projection belongs in `static/js/school-calendar/state.js`; browser DOM/event orchestration stays in `static/js/school-cal.js`; GET/revision/save composition belongs in `static/js/school-calendar/persistence.js`, backed by the one shared save queue. After 409/428 require a fresh GET instead of merging stale input automatically.
- Off-academy non-public administrator APIs require the same HTTP Basic credentials as protected admin pages. Do not apply that guard ahead of public/mobile sessions or the legacy student routes that own academy, SID, callback-secret, or credential checks (`get-url`, bootstrap, watch, auth, student announcement actions, feedback, Kollus callback, ping).
- `routes/api_schedule_overrides.py` owns `/api/extra-attend` GET/PATCH and `/api/weekend-slots` GET/POST. Preserve date-scoped extra merges, student-scoped weekend merges, file-lock coverage, real-today-only initialization, schedule notifications, and successful response shapes. An explicit real-today extra PATCH must replay the idempotent initializer even when the store is already equal and `changedDates` is empty, so an identical retry repairs a prior post-commit hook failure. Weekend POST validation completes before the lock or any hook: malformed/non-object/empty bodies and invalid dates return 400, the read-only ghost returns 403, and unknown roster SIDs return 404 with no write, assignment reconciliation, or notification. `app.py` injects the public `api_basic` assignment callbacks; do not import private automatic-assignment helpers into the schedule blueprint.
- Date-indexed progress, logs, updates/self-study, watch/watch-status, and schedule-override boundaries use `core.date_rules` and reject an impossible or noncanonical date with 400 before any lock, repository, assignment hook, notification, or JSON/SQLite write. Keep successful payload and response shapes unchanged. Whole-map `/api/absent` remains the explicit D-04 exception below.
- Absence consistency barriers must cover every related progress and automatic-assignment writer, including `/api/watch`, `/api/watch-status`, `/api/kollus/lms-callback`, real-today initialization, and self-study reconcile, so playback or stale absence reads cannot recreate state during/after an absence commit.
- Class log reads/writes should go through `routes.log_repository_provider.get_log_repository()` / `LogRepository` instead of open-coding SQLite + `logs.json` merge behavior in route handlers. Keep SQLite and JSON fallback compatibility when changing log flows; the `routes.api_basic` import path remains a compatibility alias.
- Pure class-log rules belong in `core/log_rules.py`. Keep `merge_log_entry_safe`, `log_entry_conflicts_with_base`, homework-row comparison normalization, and `truthy` semantics centralized there.
- Keep runtime-data repair and hydration separate from pure rules. `repair_log_entry_placeholders()` stays in `routes/log_repository_provider.py` because homework placeholder repair can read `students.json` through student book lookup.
- Do not merge watch/progress auto-status rules into log rules. Pure transitions live in `core/progress_rules.py`, shared watch/automatic-progress writes in `core/watch_progress_writer.py`, strict progress persistence in `core/progress_store.py`, and milestone hooks in `core/progress_notifications.py`. `api_watch` and `api_kollus` must use the shared writer and must not import each other or private helpers from `api_basic`; preserve focused manual white/skip/interrupted, timestamp, callback-auth, and automatic watch-progress tests.
- Newly registered absence pairs use the journaled coordinator in `core/absence_transaction.py` through `routes/absence_assignment_cleanup.py`; attendance, makeup sheet sync, and the offline sync script must not import each other. Preserve carryover-before-clear semantics and the logical order updates → progress → logs → absent → carryover. Success commits every store, synchronous failure restores every narrow before-image, unfinished non-committed journals roll back before startup/new writes, and related API reads/writes wait on the coordinator barrier. Automatic assignment must acquire coordinator → authoritative absence read → updates lock; same-context nesting of the identical coordinator is reentrant, while other threads/processes remain excluded. Notifications remain post-commit and outside this transaction.
- The server owns automatic video snapshots and may create one only for the real current KST date. Bare `GET /api/updates`, the admin date-boundary refresh, a non-public real-today student bootstrap, and real-today schedule events may initialize a missing snapshot; historical/future reads and future schedule events are storage-only. Never persist a future `source: "auto"` snapshot; PATCH checks the final assignment after merging under the updates lock, so an omitted incoming `source` cannot bypass the rule. Explicit removal or reclassification away from `auto` is allowed, and a real-today initialization removes any named future-auto residue while preserving future `manual`, `selfStudy`, and unknown legacy entries. Candidate history is bounded through the target date, so future progress/watch cannot block today's videos. The configured count is clamped to 1-6 (default 3, A:Ble default 1) and doubles when today has adjacent active class slots after weekend overrides and slot absences. The cap applies when a new date-bound snapshot is created and when a later count setting is saved; do not bulk-rewrite roster data or resize an existing dated snapshot. An existing today snapshot is date-bound: progress, watch, ordinary schedule/consecutive-slot, and count-setting changes must never resize, remove, or refill it, and an all-done/all-skip log save must not clear it. The explicit exception is a newly registered absence transaction, which removes that date/SID assignment; absence cancellation does not restore it. Count-setting writes update only the student setting for the next date-boundary creation. Explicit future `manual` and `selfStudy` entries remain protected. Admin modal hydration must use `GET /api/updates?readOnly=1`. The retired student-side “copy the last assignment” writer must not be restored; automatic assignment authority stays on the server.
- Keep assignment meanings distinct: `source: "auto"` is a server-created date snapshot (only an explicit curriculum change may rebase stale course MIDs), `source: "manual"` and `source: "selfStudy"` are protected explicit assignments, and student “영상 등록” is only a SID/date-scoped local playlist preference. It must not write `updates.json`, class logs, counseling history, progress, or watch state until playback actually occurs.
- Student `reviewVideos` is an authoritative sanitized bootstrap projection. The chooser accepts only current-curriculum `done` items through the requested date; it must not infer membership from the catalog, progress/watch maps, or localStorage. Server-side self-study selection is narrower and accepts only completed items strictly before the assignment date.
- Keep watch thresholds shared at 5% `interrupted` and 90%/completed `done`. Automatic watch writes must preserve manual white/`none`, `skip`, and manual `interrupted` ownership metadata, and must never advance, remove, or refill an existing auto snapshot.
- Keep assistant-student notes isolated from class-log notes, counseling records, CSV/print exports, and browser storage even though both repositories share `app.sqlite`.
- Test catalog writes follow [`RULE-TEST-001`](docs/SERVER_RULES_INDEX.md#rule-test-001): a single test definition uses revisioned `PATCH /api/tests-config/test`; global rules, bulk operations, and deletion use revisioned `POST /api/tests-config`. Preserve source/solution metadata and unknown fields; clearing requires the explicit clear-field contract.
- `static/js/tests/catalogState.js` owns test-catalog config/test normalization, search/sort/grouping, reorder blocking, revision/write-request projection, and deep rollback snapshots without DOM, fetch, or ambient browser state. `static/js/tests.js` owns fetch timing, mutation locks, DOM, CSV/editor orchestration, reload/rollback rendering, and user feedback. Keep the literal state oracle, the pre-existing entrypoint reorder/409/rollback scenario, and the temp Flask write-safety verifier complementary.
- `static/js/tests/catalogEditorState.js` owns answer parsing and mode validation, answer-round merge projection, CSV template/cell/parser/header aliases, and CSV answer/mode row projection without DOM, fetch, file access, or ambient browser state. `static/js/tests.js` retains input/file DOM, downloads, config mutation, save timing, reload, and feedback. By the approved 1A contract, undelimited `1342` remains one answer plus padding; the UI must describe only delimiter-separated multi-answer forms such as `1 3 4 2` and `1,3,4,2`.
- `static/js/tests/catalogStatisticsState.js` owns statistics type labels, signature/name/id lookup precedence, summary and table projection, search/sort, record metrics, API-detail-only answer links, and wrong-answer detail normalization without DOM, fetch, storage, or endpoint strings. `static/js/tests.js` retains statistics endpoint timing, modal/table DOM, escaping, events, and feedback. Keep the literal statistics oracle, pre-existing real-entrypoint VM, admin record-detail UI VMs, backend detail contract, and two-browser QA complementary.
- `static/css/tests.css` owns the extracted `body.admin.tests-page` cascade, responsive breakpoints, touch targets, and statistics modal/table layout. `static/tests.html` loads it after `main.css` and `admin.css` and must not regain a large inline style block. Preserve the pre-extraction normalized CSS hash, shell-body hash, existing CSS-aware UI verifiers, and two-browser computed-style evidence as complementary checks.
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
- Video assignment work spans `videos.json`, `updates.json`, `progress.json`, `watch.json`, `/api/get-url`, student bootstrap, the admin modal, and the student playlist. Run `scripts/verify_updates_routes.py` plus the focused auto-assignment/watch/review checks before the full suite.
- Student review UI changes require `node scripts/verify_student_previous_video_review.js` plus `node scripts/verify_student_material_access_scope.js`; keep both fixtures aligned with the done-only chooser and title-only outside-academy response.
- Student-test work must preserve progress-authoritative assignments, top-level `assignedTests`, answer-link precedence, academy-network stripping, and historical record reads. `static/js/student/testPresentation.js` owns only read-only presentation semantics; `student.js` owns the card DOM and click feedback. Keep `verify_student_test_presentation.mjs`, the pre-existing material-access VM, and answer-mobile/retired-submission checks green. Student submission, grading, OCR capture/review routes, and `/student-test/<sid>` are retired; rebuild them as a new feature instead of reviving legacy code.
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
- Production administrator browser support and the scoped native-player evidence exception are owned by [`RULE-OPS-001`](docs/SERVER_RULES_INDEX.md#rule-ops-001) and decision D-10. Use Chrome for production administrator pages; never weaken Basic auth to make the in-app Browser load them, and do not remove existing isolated two-browser regression gates.
- Follow the dedicated test-server rules below whenever browser or design verification needs a running server.
- Prefer DOM/API checks for exact data, then screenshot checks for visual regressions.
- Text must remain readable in Korean; verify UTF-8 rendering when touching static HTML/JS.
- Stop any dev server started only for verification unless the user asks to keep it running.

## 테스트 서버 활용 규칙
- Port 8003 is the canonical production server. Keep it available during test work and never stop, restart, or replace it merely to run a test server; production maintenance requires explicit user direction.
- The only supported concurrent test server is the loopback-only server on `127.0.0.1:8004` managed by `scripts/manage_isolated_design_server.ps1`. Never run another `app:app`, `app.run(...)`, Flask, or Waitress process directly from the live repository.
- The test server must run from `instance/isolated-design-server/app`. Its JSON, SQLite, `data/`, `files/`, `instance/`, mirror, backup, and generated runtime state must remain separate from production. Never copy, read as seed data, write, or automatically merge production runtime into the test runtime.
- Data entered through the test server belongs only to the test runtime and must never be merged into production automatically. Importing a production snapshot or promoting test data requires explicit user approval, a fresh runtime backup, a reviewed one-way migration plan, and separate verification.
- Use the manager lifecycle only: run `Status` before acting, `Start` for initial launch, `Refresh` for frontend/source snapshot refresh, `Start -Restart` after Python or route changes, and `Stop` only after confirming no user or other active task still needs the test server. A plain `Refresh` does not reload already-imported backend code.
- Keep port 8004 private to loopback. Public/LAN exposure, real push delivery, public student-app behavior, or Kollus callbacks require a separately approved QA deployment and must not be enabled by weakening the local isolation guard.
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
- There is no dependency manifest or frontend package runner. CI pins Python 3.11 and Node 20 but only compiles and invokes the custom safety harness.
