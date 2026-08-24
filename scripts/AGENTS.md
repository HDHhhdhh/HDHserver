# SCRIPTS KNOWLEDGE BASE

## Overview
Scripts cover verification, runtime backups, generated test catalog files, answer-link maps, and import utilities.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Runtime backup | `backup_runtime_data.py` | Run before migrations, repair jobs, or bulk runtime-data changes. |
| Future auto cleanup | `remove_future_auto_assignments.py` | Dry-run by default; live apply requires a confirmed runtime backup and removes only future `source:auto`. |
| Today-order consolidation | `migrate_today_order_store.py`, `verify_today_order_store_migration.py` | Dry-run/temporary contracts; live apply requires backup confirmation, archives the root legacy file, and leaves only `data/today_order.json`. |
| Makeup sheet sync | `sync_makeup_sheet_additive.py`, `verify_makeup_sheet_additive_sync.py`, `verify_makeup_sheet_route_safety.py`, `verify_absence_transaction.py`, `verify_absence_makeup_matrix.py` | Additive-only sync; live writes use the shared journal transaction, and failure/crash/HTTP/offline verification stays temp-only. A12 records the approved impossible-date 500 as a known limitation while requiring no writes or notifications. |
| Video progress matrix | `verify_video_progress_matrix.py`, `verify_student_watch_autosave.mjs` | Temp-route watch/Kollus persistence plus browser debounce, retry, pagehide/visibility flush, and active-MID bridge behavior. |
| Legacy consumer cleanup | `verify_legacy_consumer_cleanup.mjs` | Keeps retired full-map POST routes, page-folder HTTP routes, static files, and fake endpoints absent; executes canonical student-delete success/failure with exactly one DELETE request. |
| File/material reference integrity | `verify_file_reference_routes.py` | Temp-only pure/route checks for Korean names, descendant boundaries, root move, unknown-field preservation, staging rollback, malformed-state fail-closed behavior, upload DIR assignment, and three-store journal recovery. |
- File/material verification also covers assignment revision 428/409 behavior, last-good degraded reads, 503 write blocking, strict malformed-store handling, the revision-aware browser client, and current-old-backend compatibility; keep every fixture temp-only.
| Test shared services | `verify_test_shared_services.py` | Temp-only resolver precedence, tests-config lock exclusion, real test-record route gating, and private-import boundary checks. |
| Announcement image access | `verify_announcement_image_access.py` plus student-mobile `student-data`/`academy-gates` | Pure/store matrix and 94 actual-route assertions for SID visibility, hidden states, traversal, local compatibility, and runtime isolation. |
| Safety suite | `verify_refactor_safety.py` | Compile, JS checks, unit checks, optional safe smoke checks. |
| Student mobile verification | `verify_student_mobile_app.py`, `verify_student_mobile_app.mjs`, `student_mobile_app_checks/` | Temp/pure contracts; the default refactor suite runs the PWA install-guide boot/interaction flow with a temp receipt. |
| Student deployment verification | `student_mobile_app_checks/deployment.py`, `verify_student_app_deployment.ps1` | Windows CI runs the full isolated-mutex temp fixture; non-Windows CI runs portable source/backup contracts. Neither is rollout evidence. |
| Class-log export verifier | `verify_export_log_format.mjs` | Pure options/TXT/CSV/privacy/source contract, including green-only line-separated tests, school/Ilsan source+difficulty labels, and TXT/CSV blue-video exclusion; no app import or runtime reads. |
| Assistant-note verifier | `verify_assistant_student_notes.py` | Temp SQLite/API/source checks; standalone behavior check, not part of the default suite. |
| Student video-review verifier | `verify_student_previous_video_review.js` | HTML/CSS/DOM contract for done-only bootstrap choices, local registration, academy restriction, and reopened assignments. |
| Student access verifier | `verify_student_material_access_scope.js` | Cross-checks restricted video/test/material behavior; its review fixture must use the same done-only contract. |
| Video catalog guards | `verify_video_manage_ids.mjs`, `verify_video_mid_change_guard.py` | Numeric row-ID/UI warning source contract plus temp-file API proof that normal mode blocks existing MID changes and removals. |
| Video catalog correction | `verify_video_catalog_correction.py`, `apply_video_catalog_correction.py`, `apply_video_catalog_correction.ps1` | Temp/pure migration and rollback proof; live apply wrapper stops Waitress, backs up, verifies hashes, applies, and restarts. |
| Unit-test link map | `build_unit_test_answer_link_map_from_gdown.py` | Regenerates `static/js/test_answer_link_map.json`. |
| Unit catalog imports | `import_unit_test_catalog*.py`, `seed_tests_config.js` | Modify `tests-config.json`. |
| Review/school-past imports | `import_review_test_catalog_append_csv.py`, `import_school_past_test_catalog_append_csv.py` | Preserve solution metadata. |
| CSV generators | `build_*_csv_from_*` | Produce ignored `generated/*.csv` outputs. |
| Manual SQL | `migrations/*.sql` | No runner or ordering contract; inspect idempotency and current schema before use. |
| Visual verifier | `verify_admin_makeup_calendar_discoverability.mjs` | Windows/Chrome-specific; may start the app and write `.omo/evidence`. |
| Refactor notes | `refactor_notes_logs_progress.md` | Historical log/progress safety contract. |

## Conventions
- Treat scripts that write root JSON, SQLite, `tests-config.json`, or generated maps as operational changes.
- Before bulk repair or migration, create a backup with `python scripts/backup_runtime_data.py`.
- The root `today_order.json` is retired. Do not add it back to fingerprints or deployment lists; canonical today order is `data/today_order.json`.
- Main verification commands:
  ```bash
  python -m compileall -q app.py routes core scripts
  python scripts/verify_refactor_safety.py
  python scripts/verify_refactor_safety.py --smoke
  ```
- Keep generated CSV/debug/image outputs under `generated/`.
- Compile/default verification can create `__pycache__` and root `tmp/` artifacts. `--smoke` imports the live app, performs selected GETs, and permits WAL/SHM changes.
- Full-app standalone verifiers are runtime-sensitive even when their assertions are read-only; fingerprint all relevant stores before using them.
- For test catalog updates, keep student answer links in sync:
  - `REVIEW` and `SCHOOL_PAST`: preserve/update `sourceFiles.solutionFileId` or equivalent metadata.
  - `UNIT`: regenerate/update `static/js/test_answer_link_map.json` from Drive explanation files.
- REVIEW/SCHOOL_PAST imports and the answer-map builder support temp paths and enforce `--backup-confirmed` for live outputs.
- UNIT replacement import and `seed_tests_config.js` now require explicit backup confirmation and reject implicit ID removals; `--allow-unit-removal` is required for an intentional shrink. Append/sort remain live mutators, so back up first and do not assume every script accepts temp-path or confirmation flags.
- The tracked canonical answer map is `static/js/test_answer_link_map.json` with `sourceId -> round -> entry`. The retired `static/js/test_answer_link_map.js` wrapper and `/js/test_answer_link_map.js` URL must stay absent and must not be ignored or regenerated.
- SQL files in `migrations/` are manual artifacts, not an executable chain. The current assistant-note create/add-column files conflict if applied sequentially; reconcile them before any live migration.
- Browser evidence under `.omo/evidence/` is ignored local QA output and is validated only through the explicit `--only-frontend-evidence-inventory` selector; the default safety suite must remain reproducible without it.
- `tests-config.json` is ignored runtime data. The default safety suite uses a synthetic UNIT answer-material contract; validate the current local catalog separately with `--only-unit-test-answer-material-readiness`. Retired student submission checks must assert route/UI absence while preserving admin assignment coverage.
- Video verification layers are complementary: the default Python suite covers pure/server assignment, bootstrap, self-study, and watch rules; `verify_student_previous_video_review.js` covers the student DOM; `verify_student_material_access_scope.js` covers academy restriction; `verify_video_manage_ids.mjs` covers catalog row IDs plus the normal/correction-mode browser source contract. Do not treat one as a substitute for the others.
- Automatic video verification must prove non-today loads and future schedule events are storage-only, count setting changes do not touch assignments, and only the real current KST date can receive a new `source:auto` snapshot.
- Makeup sheet sync must use `routes.absence_assignment_cleanup.absence_write_scope` plus `commit_new_absences_locked` with canonical paths. Keep network reads before live locks and dry-run mutation-free. Live writes must preserve updates → progress → logs → absence → carryover semantics while every synchronous failure rolls all stores back and an unfinished crash journal is recoverable.
- Keep every review fixture `done`-only. An `interrupted` fixture is intentionally excluded by `student.js` and cannot be used to assert that a restricted review row renders.
- Normal-mode video catalog tests must not exercise live files. Keep `verify_video_mid_change_guard.py` temp-only and reject any reintroduction of `_migrate_video_mid_references()` or a normal `/api/videos` guard bypass.
- Correction drafts and runtime backup archives are sensitive local artifacts and must not be committed. Live MID correction is permitted only through the PowerShell wrapper with both `-Apply` and `-ConfirmApply`; do not invoke the Python `--apply` path against the live root by hand.
- Keep `verify_student_watch_timestamp.mjs` and `verify_watch_timestamp_guard.py` green; they reject 32-bit/10-digit `updatedAt` values and prove browser-to-server millisecond preservation/repair.

## Anti-Patterns
- Do not commit runtime backup archives, generated CSVs, debug screenshots, or local Drive downloads unless explicitly requested.
- Do not run import/seed scripts casually; they can change `tests-config.json` and visible student behavior.
- Do not make smoke checks that mutate runtime data without fingerprinting and reporting it.
- Do not treat generator exit code `0` uniformly as issue-free; some builders still emit warning/issue artifacts.
- Do not treat a byte-copied SQLite/WAL backup from a busy app as transactionally consistent.
