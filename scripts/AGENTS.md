# SCRIPTS KNOWLEDGE BASE

## Overview
Scripts cover verification, runtime backups, generated test catalog files, answer-link maps, and import utilities.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Runtime backup | `backup_runtime_data.py` | Run before migrations, repair jobs, or bulk runtime-data changes. |
| Safety suite | `verify_refactor_safety.py` | Compile, JS checks, unit checks, optional safe smoke checks. |
| Student mobile verification | `verify_student_mobile_app.py`, `verify_student_mobile_app.mjs`, `student_mobile_app_checks/` | Temp/pure contracts; the default refactor suite runs the PWA install-guide boot/interaction flow with a temp receipt. |
| Student deployment verification | `student_mobile_app_checks/deployment.py`, `verify_student_app_deployment.ps1` | Windows CI runs the full isolated-mutex temp fixture; non-Windows CI runs portable source/backup contracts. Neither is rollout evidence. |
| Class-log export verifier | `verify_export_log_format.mjs` | Pure options/TXT/CSV/privacy/source contract; no app import or runtime reads. |
| Assistant-note verifier | `verify_assistant_student_notes.py` | Temp SQLite/API/source checks; standalone behavior check, not part of the default suite. |
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
- The tracked canonical answer map is `static/js/test_answer_link_map.json` with `sourceId -> round -> entry`; the ignored `.js` sibling is a stale legacy artifact.
- SQL files in `migrations/` are manual artifacts, not an executable chain. The current assistant-note create/add-column files conflict if applied sequentially; reconcile them before any live migration.
- Browser evidence under `.omo/evidence/` is ignored local QA output and is validated only through the explicit `--only-frontend-evidence-inventory` selector; the default safety suite must remain reproducible without it.

## Anti-Patterns
- Do not commit runtime backup archives, generated CSVs, debug screenshots, or local Drive downloads unless explicitly requested.
- Do not run import/seed scripts casually; they can change `tests-config.json` and visible student behavior.
- Do not make smoke checks that mutate runtime data without fingerprinting and reporting it.
- Do not treat generator exit code `0` uniformly as issue-free; some builders still emit warning/issue artifacts.
- Do not treat a byte-copied SQLite/WAL backup from a busy app as transactionally consistent.
