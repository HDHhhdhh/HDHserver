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

## Verification Contract

Safe default checks:

- `python scripts\verify_refactor_safety.py`
- `python scripts\verify_refactor_safety.py --smoke`
  - Smoke mode fingerprints runtime files before and after safe GET checks,
    including existing root SQLite sidecars (`*.sqlite-wal`, `*.sqlite-shm`,
    `*.db-wal`, `*.db-shm`).
- `GET /api/progress?date=YYYY-MM-DD&sid=<sid>`
- `GET /api/attendance?date=YYYY-MM-DD`
- `GET /api/contact?date=YYYY-MM-DD`
- `GET /arrive-time?date=YYYY-MM-DD`
- `GET /api/watch/latest?date=YYYY-MM-DD&sid=<sid>`

Checks to treat as risky:

- `GET /api/logs` and `GET /api/logs/entry` can touch SQLite WAL/schema state.
- `GET /api/updates` can auto-write `updates.json`.
- Today's `GET /api/student/bootstrap` can auto-write `updates.json`.
- Any `POST`, `PATCH`, or `DELETE` check can mutate runtime data and requires a
  backup plus an explicit report of what will change.

## Phase 6 Follow-Up Candidates

- Add a verification mode that records SQLite WAL/schema mtimes before and
  after optional log GET checks, but keep it opt-in.
- Phase 7 note: `scripts/backup_runtime_data.py` includes existing root
  SQLite sidecars (`*.sqlite-wal`, `*.sqlite-shm`, `*.db-wal`, `*.db-shm`)
  by filename suffix, without opening SQLite to discover them.
- Phase 8 note: `scripts/verify_refactor_safety.py` fingerprints existing
  root SQLite sidecars with the same suffixes during smoke checks, and backup
  coverage also includes root `.tmp` files to match verification.
- Keep runtime backup coverage aligned with SQLite sidecar files when new DB
  paths are introduced.
- Separately verify the dirty `adminDate.js` sessionStorage behavior before
  more date-sensitive frontend changes.
- Keep backend logs/progress refactors split into one endpoint or one helper at
  a time.
