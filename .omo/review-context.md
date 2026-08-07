# Review Context

## Goal
Whole-project refactor of the local Flask academy operations app according to .omo/plans/whole-project-refactor.md, preserving runtime data, behavior contracts, Korean rendering, admin selected-date behavior, log/progress/watch contracts, answer-link handling, and safety-suite evidence.

## Constraints
- Follow C:/server/AGENTS.md and scoped AGENTS.md files.
- Runtime JSON/SQLite/catalog data must not have lasting modifications; Task2 historical probe cleanup is explicitly accepted by owner only as a no-lasting-modification exception.
- Preserve endpoint URLs, payload keys, response shapes, admin selected date, row data-date behavior, Korean text readability, and student assignedTests top-level contract.
- Class log reads/writes should go through LogRepository; pure log rules stay in core/log_rules.py; watch/progress auto-status rules stay separate.
- Tests and browser/QA evidence must support changed behavior; F1-F4 final verification passed.
- Do not stage/commit in review.

## Run Command
python app.py

## Verification Already Run
- python -m compileall -q app.py routes core scripts
- node --check .omo/evidence/f3-live-routes-qa.cjs
- python scripts/verify_refactor_safety.py
- python scripts/verify_refactor_safety.py --smoke
- git diff --check
- runtime data git status checks; clean

## Changed Files
AGENTS.md
core/admin_chat.py
core/log_repository.py
core/progress_rules.py
routes/api_basic.py
routes/api_kollus.py
routes/api_watch.py
scripts/AGENTS.md
scripts/build_unit_test_answer_link_map_from_gdown.py
scripts/import_review_test_catalog_append_csv.py
scripts/import_school_past_test_catalog_append_csv.py
scripts/refactor_notes_logs_progress.md
scripts/verify_refactor_safety.py
static/AGENTS.md
static/css/admin.css
static/css/student.css
static/css/style.css
static/js/admin/core/api.js
static/js/admin/core/state.js
static/js/admin/features/logModal.js
static/js/admin/features/testModal.js
static/js/admin/features/today.render.js
static/js/admin/features/videoModal.js
static/js/shared/api.js
static/js/student.js

## Diff Stat
 AGENTS.md                                          |    4 +-
 core/admin_chat.py                                 |    2 +-
 core/log_repository.py                             |   41 +-
 core/progress_rules.py                             |   51 +-
 routes/api_basic.py                                |  347 ++--
 routes/api_kollus.py                               |    3 +-
 routes/api_watch.py                                |   29 +-
 scripts/AGENTS.md                                  |    2 +
 .../build_unit_test_answer_link_map_from_gdown.py  |   23 +-
 scripts/import_review_test_catalog_append_csv.py   |   37 +-
 .../import_school_past_test_catalog_append_csv.py  |   37 +-
 scripts/refactor_notes_logs_progress.md            |   23 +
 scripts/verify_refactor_safety.py                  | 1981 +++++++++++++++++++-
 static/AGENTS.md                                   |    1 +
 static/css/admin.css                               |  678 +++----
 static/css/student.css                             |    5 +
 static/css/style.css                               |   13 +-
 static/js/admin/core/api.js                        |    3 +-
 static/js/admin/core/state.js                      |    5 +-
 static/js/admin/features/logModal.js               |  234 ++-
 static/js/admin/features/testModal.js              |  180 +-
 static/js/admin/features/today.render.js           |  155 +-
 static/js/admin/features/videoModal.js             |  136 +-
 static/js/shared/api.js                            |    6 +
 static/js/student.js                               |   39 +-
 25 files changed, 3119 insertions(+), 916 deletions(-)

## Key Evidence
- .omo/plans/whole-project-refactor.md: all top-level checkboxes complete
- .omo/start-work/ledger.jsonl: JSONL valid, 50 events
- .omo/boulder.json: status completed
- .omo/evidence/f4-runtime-exception-acceptance.json
- .omo/evidence/final-safety-suite-after-f4-acceptance.txt
- .omo/evidence/final-smoke-after-f4-acceptance.txt
- .omo/evidence/final-runtime-status-after-f4-acceptance.txt
- .omo/evidence/f3-live-routes-status.json and screenshots for live /admin and /student QA
