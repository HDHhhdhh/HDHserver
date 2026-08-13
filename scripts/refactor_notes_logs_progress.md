# Logs and Progress Refactor Notes

This note records the current backend contract before risky logs/progress
refactors. It is documentation only; do not treat it as a migration plan.

## Runtime Data Boundaries

- `logs.json` and `app.sqlite` are operational data stores.
- `progress.json` is operational data and is date/sid keyed.
- `watch.json` can indirectly affect `progress.json` through automatic watch
  progress writes.
- Do not rewrite, reformat, migrate, or repair these files without an explicit
  user request and a runtime backup.

## Logs Storage Contract

- Logs use dual storage:
  - SQLite table `logs(date, sid, entry_json, updated_at)` in `app.sqlite`.
  - JSON fallback/backup map in `logs.json`, shaped as
    `{ "YYYY-MM-DD": { "sid": entry } }`.
- SQLite is the primary source for normal log reads.
- `logs.json` fills missing SQLite date/sid records. It does not merge fields
  into an existing SQLite entry returned for the same date/sid.
- `core/logs_sqlite.py` is not the main app contract. It is a small direct
  SQLite helper with no schema setup, no JSON fallback, and no placeholder
  repair.

## Logs Endpoint Contract

- `GET /api/logs/entry?date=YYYY-MM-DD&sid=<sid>`
  - Validates `date` and `sid`.
  - Tries SQLite first.
  - Returns `{ ok: true, source: "sqlite", entry }` when SQLite has an entry.
  - Falls back to `logs.json` and returns `source: "json"`.
- `GET /api/logs`
  - Accepts optional `date` and `sid`.
  - Returns the nested `{ date: { sid: entry } }` map.
  - Uses SQLite first and JSON only for missing date/sid records.
- `POST /api/logs`
  - Legacy full-map merge endpoint.
  - Merges valid date/sid entries into SQLite.
  - Merges incoming entries into `logs.json`.
  - Avoid broad refactors here; prefer `/api/logs/patch`.
- `POST /api/logs/patch`
  - Preferred log write endpoint.
  - Body shape is:
    `{ date, sid, entry, __clear?, base? }`.
  - `__clear` is the explicit field-delete mechanism.
  - Empty incoming values must not erase existing meaningful values unless the
    field is explicitly listed in `__clear`.
  - `base` is used for optimistic conflict checks on `notes` and
    `homeworkTable`.
  - Unknown fields in existing entries must be preserved by safe merge.

## Logs Risk Notes

- Log GET endpoints are not purely read-only at the filesystem level:
  `_db_connect()` can create the DB directory, enable WAL mode, and create
  SQLite `-wal` / `-shm` files.
- Runtime backups should include existing root SQLite sidecar files such as
  `app.sqlite-wal` and `app.sqlite-shm`; backup collection must not create or
  open SQLite files just to discover sidecars.
- Log GET endpoints call schema setup, so they may create the `logs` table or
  index if absent.
- `POST /api/logs/patch` can partially diverge the two stores if one side
  succeeds and the other side fails. Do not change this behavior without a
  dedicated migration/reconciliation phase.
- SQLite conflict handling and JSON conflict handling are not identical enough
  to casually reorder.
- Older log text can contain placeholder/mojibake-like values. The current
  repair path must continue to avoid displaying or saving `???`/`????` in
  notes/homework fields.

## Progress Storage Contract

- `progress.json` is the progress store.
- The top-level shape is `{ "YYYY-MM-DD": { "sid": progressEntry } }`.
- `/api/progress` loading is strict for malformed data: missing files become
  `{}`, but non-object data and read failures are errors.
- Writes use the progress lock and atomic JSON save.

## Progress Endpoint Contract

- `GET /api/progress`
  - No query returns the whole map.
  - `?date=YYYY-MM-DD` returns `{ date: dayMap }`.
  - `?date=YYYY-MM-DD&sid=<sid>` returns `{ date: { sid: entry } }`.
  - `?sid=<sid>` scans all dates and returns only non-empty entries.
  - `?sids=<sid1>,<sid2>` and repeated `?sid=<sid1>&sid=<sid2>`
    return the same date-keyed shape filtered to the requested students.
  - `?date=YYYY-MM-DD&sids=<sid1>,<sid2>` returns `{ date: filteredDayMap }`.
  - GET sid lookup accepts exact and integer-normalized sid aliases.
- `POST /api/progress/patch`
  - Body shape is `{ date, sid, progress, source? }`.
  - Patch is scoped to one date/sid entry.
  - The write path stores under the exact submitted `sid`.
  - It prunes empty sid/date buckets after merge.

## Progress Merge Contract

- Server-owned metadata keys:
  - `__allStudentsProgressMids`
  - `__autoWatchProgressMids`
  - `__manualProgressMids`
- Incoming keys that start with `__` are ignored.
- `tests` is a special nested progress area. Test keys can be removed with
  empty, `none`, `False`, or `{ remove: true }`.
- Manual/default progress semantics:
  - `none` is a persisted explicit manual white/clear marker.
  - `""` deletes the mid.
  - Any other non-empty status string is stored.
- Non-auto non-empty patches mark `__manualProgressMids[mid] = true`.
- `source: "allStudents"` marks `__allStudentsProgressMids`.
- `source: "auto"` is reserved for automatic watch progress and must not
  override manual states.

## Watch/Progress Contract

- Watch writes bypass `/api/progress/patch` and write through the same progress
  lock from `routes/api_watch.py`.
- Automatic watch progress may advance only blank or auto-owned states.
- Manual `none`, `skip`, `done`, and `interrupted` must not be overwritten by
  automatic watch progress.
- Legacy non-manual `interrupted` can still upgrade to `done`.
- Kollus callbacks use the same watch/progress writer path.

## Frontend Contract

- `logModal.js` calls `/api/logs/patch` with `{ date, sid, entry, __clear?, base? }`.
- `logModal.js` calls `/api/progress/patch` with `{ date, sid, progress }`.
- The admin log modal sends only changed progress mids.
- Manual white is sent as `none`, not as an empty string.
- Notes and homework compare against modal snapshots before patching.
- `today.js` expects `GET /api/logs?date=YYYY-MM-DD` to return
  `{ date: dayLogs }`.
- `today.js` expects `GET /api/progress?date=YYYY-MM-DD` to return
  `{ date: dayProgress }`.
- `today.js` and roster export may request progress history with
  `GET /api/progress?sids=<sid1>,<sid2>` so refresh/export paths do not
  download the full progress history map when only visible students are needed.

## Assigned Test and Answer-Link Contract

- Student bootstrap keeps `assignedTests` as a top-level array.
- For current-day test assignments, `progress[date][sid].tests` is the
  authority for active, done, skipped, and cleared statuses.
- Log `assignedTests` and `testAssignmentDailyTests` are metadata/fallbacks;
  they must not resurrect stale cleared assignments.
- `assignedTests[].answerUrl` can come from, in order: an assignment item,
  `tests-config.json` solution metadata such as `sourceFiles.solutionFileId`,
  or the generated `static/js/test_answer_link_map.json`.
- When academy network access is restricted, student bootstrap keeps the
  assigned test visible but strips direct solution file ids and answer URLs.

## Test Catalog Writer Contract

- Catalog writer scripts must be exercised with temp paths during verification:
  `--config`, `--csv`, `--output`, and `--issues`.
- Live writes to `tests-config.json` or `static/js/test_answer_link_map.json`
  require a runtime backup and an explicit `--backup-confirmed` flag.
- REVIEW and SCHOOL_PAST imports preserve solution metadata such as
  `sourceFiles.solutionFileId`; UNIT answer links are regenerated into the
  link map from Drive explanation files.

## Admin Selected-Date Session Contract (Phase 7 Complete)

- `static/js/admin/core/adminDate.js` remains the single source of truth for
  the admin operating date and keeps the `adminSelectedDate` sessionStorage
  key plus the `admin:date-change` event detail `{ dateStr }`.
- Stored values, setter inputs, and external date-change events all use the
  same semantic `YYYY-MM-DD` calendar validation. Shape-correct but impossible
  values such as `2026-02-31`, non-leap `2026-02-29`, and invalid months are
  rejected.
- Missing, malformed, impossible, or unreadable sessionStorage values fall
  back to the real local date. Valid setter calls still broadcast in-page when
  sessionStorage rejects a write and remain authoritative through a page-local
  memory fallback, while `{ silent: true }` persists without broadcasting and
  invalid setters are no-ops.
- Previous/next navigation shifts calendar days in UTC calendar fields so its
  result does not depend on parsing a bare date string in the host timezone;
  navigation clamps at the supported `0001-01-01` and `9999-12-31` bounds.
- The no-app/no-runtime regression is
  `node scripts/verify_admin_date_session_storage.mjs`; it is part of the
  default safety suite and can be selected with
  `python scripts/verify_refactor_safety.py --only-admin-date-session-storage`.

## Legacy Test Statistics Cache (Phase 8 Complete)

- `routes/api_tests.py::_iter_test_records()` still reads `tests.json` first on
  every request; that durable store remains authoritative for same-day
  duplicates.
- Only normalized legacy test candidates projected from `logs.json` are cached.
  The cache is keyed by absolute path plus filesystem identity/time/size fields,
  is populated only after a stable non-empty read, and returns deep copies.
- Repeated `/api/tests-stats` and `/api/tests-records` calls therefore avoid
  reparsing and walking unrelated class-log entries while the legacy file is
  unchanged. Missing, failed, empty, or concurrently replaced reads are not
  made sticky.
- The dedupe identity includes the top-level date. Identical same-day durable
  and legacy copies still collapse, while the same student/test with a blank
  `createdAt` on different dates remains two real attempts.
- Date range semantics, malformed-record filtering, metadata normalization,
  response fields, sort order, and cache headers remain unchanged.
- The temp-only focused regression is
  `python scripts/verify_refactor_safety.py --only-legacy-test-record-cache`;
  it is also registered in the default safety suite.

## Test Catalog Search and Ordering (Phase 9 Complete)

- `static/js/tests.js` keeps catalog search separate from the statistics
  search. The catalog query matches the displayed/name/ID, subject,
  difficulty, term, round, and problem-count text through the shared Korean
  search contract.
- Ordering is limited to one rendered category/subject/difficulty group. UNIT
  and TRAINING_PACK rows stay inside their round, and past-test rows stay
  inside their exam term. Cross-group drops are ignored.
- Search, round-filter, and term-filter views are intentionally read-only for
  ordering so a partial list cannot silently redefine hidden rows. Desktop
  drag and keyboard up/down controls share the same guarded save path.
- A reorder changes only `sortOrder` and raw array placement for the affected
  rows. It preserves `sourceOrder`, `sourceFiles`, source IDs, every answer
  round, and unknown fields; a failed save restores the exact prior array and
  `sortOrder` property state.
- Catalog GETs return an `X-Tests-Config-Revision`; every whole-config POST
  must send that revision. Missing or stale revisions fail before merge so a
  concurrent edit or deletion cannot be overwritten or resurrected.
- Statistics refreshes do not reload `TEST_CFG`. The New button keeps its
  unsaved draft in editor controls until Save, so neither a reorder nor rule
  autosave can persist an unconfirmed test definition.
- The no-app/no-runtime UI regression is
  `node scripts/verify_test_catalog_search_and_sort.mjs`. The focused selector
  `python scripts/verify_refactor_safety.py --only-test-catalog-search-sort`
  also runs the temp-file Flask write/revision contract in
  `scripts/verify_tests_config_write_safety.py`; both are registered in the
  default safety suite.

## Admin Hover Tooltip Performance (Phase 10 Complete)

- `static/js/admin/features/hoverTooltip.js` keeps the existing delegated
  `todayWrap` / `doneWrap` / `allWrap` listener topology and makes repeated
  initialization idempotent; student rows never receive per-row listeners.
- SID/name lookup uses a roster-identity/length keyed `Map` index instead of
  scanning every student on each hover. Same-anchor pointer events reuse the
  current HTML. Re-entry rebuilds the compact today tooltip so in-place roster
  edits cannot leave stale or unbounded cached markup behind.
- Pointer movement records only the latest coordinates and performs at most
  one placement per animation frame. Tooltip dimensions are measured once per
  visible hover, so repeated pointer events neither force synchronous layout
  nor rebuild the same DOM.
- Fixed log/student-work tooltips return before progress/video enumeration when
  video content is disabled. Delayed fixed placement is generation-guarded so
  hide/layout changes cannot restore a stale popup, and drag reuses the
  pointer-down dimensions instead of measuring on every move. Assistant-note
  mount, storage, and global launcher contracts remain unchanged.
- The no-app/no-runtime stress regression is
  `node scripts/verify_hover_tooltip_performance.mjs`; it exercises a 10,000
  student roster and more than 1,000 pointer events. It is also wired through
  `python scripts/verify_refactor_safety.py --only-hover-tooltip-performance`
  and the default suite.

## Admin Hover Tooltip Responsive Accessibility (Phase 11 Complete)

- The compact student-name tooltip now bounds its inner content to the outer
  `92vw` viewport allowance and permits narrow Korean labels/values to wrap;
  fixed log/student-work panel sizing remains owned by its existing popup CSS.
- Delegated `focusin`, `focusout`, and `keydown` handlers mirror pointer hover
  without adding per-row listeners. Keyboard focus owns the tooltip while
  active, link `Enter` remains untouched, and `Escape` dismisses only the
  tooltip while keeping focus on the student link.
- Hover mode uses `role="tooltip"`, `aria-hidden`, and a token-preserving
  `aria-describedby="adminSchoolTip"` link. The interactive fixed student panel
  switches to a labelled `role="region"` so its assistant-note controls are not
  exposed as a non-interactive tooltip.
- Focus transitions are microtask/generation guarded. `today:rendered` and the
  new `all:rendered` boundary remove stale ARIA/pointer state without closing a
  fixed student-work panel.
- `static/js/all/main.js` initializes only the shared admin tooltip and mirrors
  the already-loaded all-page roster state. The larger admin modal graph remains
  lazy behind the first counseling button interaction.
- `node scripts/verify_hover_tooltip_performance.mjs` now covers large-roster
  performance plus focus transitions, mixed pointer/focus ownership, Escape,
  ARIA role separation, fixed-panel refresh behavior, responsive width source,
  and the all-page lightweight bridge. Run the focused alias with
  `python scripts/verify_refactor_safety.py --only-hover-tooltip-accessibility`.

## Class Log Export Format Options (Phase 12 Complete)

- The existing `#exportLogs` action now opens an accessible, keyboard-trapped
  dialog. Opening or cancelling the dialog performs no API request; data is
  loaded only after a valid submit.
- TXT and CSV remain enabled by default, preserving the legacy two-download
  behavior. TXT can include any combination of notes, tests, progress, and
  homework, while records with no selected content are omitted.
- CSV intentionally keeps its canonical 14-column schema and homework row
  expansion so downstream consumers do not receive a shape that changes with
  UI options. Spreadsheet-formula prefixes are neutralized before CSV quoting.
- Options live only in the current page instance. They are not written to
  browser storage or the server, and assistant-student notes remain outside
  every class-log export.
- `static/js/admin/features/exportLogFormat.js` owns pure normalization,
  validation, TXT rendering, and CSV serialization. Run the focused contract
  with `python scripts/verify_refactor_safety.py --only-export-log-format`.

## Student App Install Guide Entry (Phase 13 Complete)

- `/app` now leaves the signed-out or current app state visible when the shell
  initializes. The installation guide opens only from the explicit
  `data-install-guide-open` button; it is not a first-load gate.
- Explicit opening still makes the page background inert and focuses the
  labelled dialog. Escape, the backdrop, and both dismiss controls close it
  and restore focus to the opener. Standalone installations and successful
  native install events hide the opener and overlay, clear any captured stale
  prompt, release inertness, and move focus back into the app.
- `scripts/student_mobile_app_checks/pwa-flow.mjs` executes this lifecycle with
  an isolated DOM fixture, including the actual boot seam, the real shell's
  hidden/dismiss markup, click-to-open, Escape/dismiss, prompt focus handling,
  install completion, stale-prompt cleanup, inert cleanup, and focus
  restoration. The default refactor verifier runs this flow with its receipt
  redirected to a temporary directory; use `--only-student-install-guide` for
  the focused contract.

## Student App Deployment Contract (Phase 14 Complete)

- The default refactor safety suite now executes the existing deployment
  contract checker. Windows covers production/dev Preflight fixtures, Canary
  and approved Expanded gates, rollback back to public-off, PowerShell syntax,
  worker overlap through a unique dry-run-only fixture mutex,
  Tunnel/task/listener failures, and secret backup exclusions.
  Non-Windows CI runs the portable source and secret-backup subset instead of
  attempting an unavailable `powershell.exe` binary; a dedicated Windows 3.12
  CI job runs the full contract.
- `-FixtureMode` requires `-DryRun` plus all seven snapshot paths before any
  check can fall back to process, Task Scheduler, listener, or HTTP state.
- The wrapper restores and rejects changes to the process environment, working
  directory, and backup runtime root even when the checker raises or returns a
  malformed receipt. It also observes live runtime content/size/mtime before
  and after solely to reject mutation. Deployment fixtures remain in OS
  temporary directories and do not import the Flask app, call a live host or
  Push provider, or mutate Task Scheduler, Tunnel, keys, or runtime stores.
- Run only this contract with
  `python scripts/verify_refactor_safety.py --only-student-mobile-deployment`.
  Fixture PASS is not physical-device, live-host, subscription, or delivery
  evidence; those remain blocked until approved devices and infrastructure are
  available.

## Today Absence Recovery And Unarchived Students (Phase 16 Complete)

- Absence recovery is a narrow, idempotent server operation that holds the
  canonical absence-file lock while removing the selected SID/date from
  `by_date`, `by_student`, and `by_slot` together. Client state changes only
  after an accepted normalized response; if the response is lost after commit,
  a no-store read reconciles the final state before reporting failure. Legacy
  whole-map writers require the revision returned by `GET /api/absent`, and the
  sheet sync rebases only its additive cells under the same lock.
- After a successful recovery, the selected date's manual `today_order` is
  cleared through the locked date-scoped `DELETE /api/today_order` operation so
  unrelated dates are preserved and the returning student is placed by the
  canonical Today sorting rules. If only that secondary reset fails, the
  completed absence save is reported as partial success and the forced server
  refresh still runs. Drag saves likewise use a single date-scoped `PATCH`.
- `/api/logs/unarchived-summary` keeps its historical cleanup counts and now
  also returns the latest `done=true`, `archived!=true` log per SID across all
  real canonical dates. Each row contains only the render booleans (`done`,
  `archived`, optional `hwChecked`/`selfStudy`), never log notes, homework, or
  test metadata. A `rowsAvailable` marker distinguishes an authoritative empty
  result from storage degradation; the latter falls back to the selected
  date's existing local records. Historical rows display their date and keep
  slot/arrival controls read-only until that date is selected.
- Demo primary/fallback fetch interceptors implement the same response shape.
  Run the focused, runtime-free contract with
  `python scripts/verify_refactor_safety.py --only-today-completion`.

## Verification Contract

Safe default checks:

- `python scripts\verify_refactor_safety.py`
  - The default verifier parses every Python file covered by the CI compile
    command with the Python 3.11 grammar, even when the local venv is newer.
- `python scripts\verify_refactor_safety.py --smoke`
  - Smoke mode fingerprints runtime files before and after safe GET checks,
    including existing root SQLite sidecars (`*.sqlite-wal`, `*.sqlite-shm`,
    `*.db-wal`, `*.db-shm`).
  - Default smoke continues to skip both log GET endpoints.
- `GET /api/progress?date=YYYY-MM-DD&sid=<sid>`
- `GET /api/attendance?date=YYYY-MM-DD`
- `GET /api/contact?date=YYYY-MM-DD`
- `GET /arrive-time?date=YYYY-MM-DD`
- `GET /api/watch/latest?date=YYYY-MM-DD&sid=<sid>`

Checks to treat as risky:

- `GET /api/logs` and `GET /api/logs/entry` can touch SQLite WAL/schema state.
- The log GET smoke is therefore opt-in and requires both flags:
  `python scripts\verify_refactor_safety.py --smoke --smoke-log-gets`.
  Before running it against local operational data, create a backup with
  `python scripts\backup_runtime_data.py` and retain the printed backup path.
- The opt-in check sends the selected date/SID to
  `/api/logs/entry?date=<candidate>&sid=<candidate>` and
  `/api/logs?date=<candidate>&sid=<candidate>`. It does not print the candidate
  values or response bodies. If either candidate is invalid or the SID is
  empty, it calls neither endpoint and fails the opt-in smoke instead of
  widening `/api/logs` to a date-wide read.
- Smoke captures `mtime_ns`, size, and SHA-256 for SQLite main files plus their
  WAL/SHM sidecars before and after requests. WAL/SHM creation, deletion, or
  modification is reported as an allowed structured observation. Any change to
  a main `*.sqlite` or `*.db` file, including an mtime-only change, fails.
- `--smoke-log-gets` without `--smoke` is rejected; do not treat this mode as a
  substitute for a backup or run it casually against live operational data.
- `GET /api/updates` can auto-write `updates.json`.
- Today's `GET /api/student/bootstrap` can auto-write `updates.json`.
- Any `POST`, `PATCH`, or `DELETE` check can mutate runtime data and requires a
  backup plus an explicit report of what will change.

## Phase 6 Follow-Up Candidates

- The opt-in log GET observability mode is implemented as `--smoke-log-gets`;
  keep its backup guidance, main-database failure rule, and default skip intact.
- Phase 7 note: `scripts/backup_runtime_data.py` includes existing root
  SQLite sidecars (`*.sqlite-wal`, `*.sqlite-shm`, `*.db-wal`, `*.db-shm`)
  by filename suffix, without opening SQLite to discover them.
- Phase 8 note: `scripts/verify_refactor_safety.py` fingerprints existing
  root SQLite sidecars with the same suffixes during smoke checks, and backup
  coverage also includes root `.tmp` files to match verification.
- Keep runtime backup coverage aligned with SQLite sidecar files when new DB
  paths are introduced.
- Phase 7 admin selected-date sessionStorage behavior is verified by the
  default and focused safety checks; preserve this contract before further
  date-sensitive frontend changes.
- Keep backend logs/progress refactors split into one endpoint or one helper at
  a time.
