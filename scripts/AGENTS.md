# SCRIPTS KNOWLEDGE BASE

## Overview
Scripts cover verification, runtime backups, generated test catalog files, answer-link maps, and import utilities.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Runtime backup | `backup_runtime_data.py` | Run before migrations, repair jobs, or bulk runtime-data changes. |
| Safety suite | `verify_refactor_safety.py` | Compile, JS checks, unit checks, optional safe smoke checks. |
| Unit-test link map | `build_unit_test_answer_link_map_from_gdown.py` | Regenerates `static/js/test_answer_link_map.json`. |
| Unit catalog imports | `import_unit_test_catalog*.py`, `seed_tests_config.js` | Modify `tests-config.json`. |
| Review/school-past imports | `import_review_test_catalog_append_csv.py`, `import_school_past_test_catalog_append_csv.py` | Preserve solution metadata. |
| CSV generators | `build_*_csv_from_*` | Produce ignored `generated/*.csv` outputs. |
| Refactor notes | `refactor_notes_logs_progress.md` | Historical log/progress safety contract. |

## Conventions
- Treat scripts that write root JSON, SQLite, `tests-config.json`, or generated maps as operational changes.
- Before bulk repair or migration, create a backup with `python scripts/backup_runtime_data.py`.
- Verification commands:
  ```bash
  python -m compileall -q app.py routes core scripts
  python scripts/verify_refactor_safety.py
  python scripts/verify_refactor_safety.py --smoke
  ```
- Keep generated CSV/debug/image outputs under `generated/`.
- For test catalog updates, keep student answer links in sync:
  - `REVIEW` and `SCHOOL_PAST`: preserve/update `sourceFiles.solutionFileId` or equivalent metadata.
  - `UNIT`: regenerate/update `static/js/test_answer_link_map.json` from Drive explanation files.
- Exercise catalog writer scripts with temp `--config`, `--csv`, `--output`, and `--issues` paths during verification.
- Before running catalog writer scripts against live `tests-config.json` or `static/js/test_answer_link_map.json`, run `python scripts/backup_runtime_data.py` and pass `--backup-confirmed`.

## Anti-Patterns
- Do not commit runtime backup archives, generated CSVs, debug screenshots, or local Drive downloads unless explicitly requested.
- Do not run import/seed scripts casually; they can change `tests-config.json` and visible student behavior.
- Do not make smoke checks that mutate runtime data without fingerprinting and reporting it.
