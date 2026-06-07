# Whole Project Refactor Plan

## TL;DR
> Summary:      Behavior-preserving refactor roadmap for the `C:\server` academy operations app, with Wave 1 as the only recommended first production wave after explicit user approval.
> Deliverables:
> - Backend log/progress contract refactor tasks
> - Admin module refactor tasks for log, video, test, and today-row flows
> - Student/test bootstrap and answer-link contract tasks
> - CSS cascade containment tasks
> - Verification tooling and evidence requirements
> Effort:       XL
> Risk:         High - live JSON/SQLite runtime data, dual log stores, and date-sensitive admin/student workflows

## Scope
### Must have
- Preserve runtime data: root JSON, SQLite files, sidecars, `data/*.json`, `files/`, and `instance/` remain untouched unless a task explicitly creates a backup and fingerprints state first, following `AGENTS.md:48`, `AGENTS.md:53`, and `routes/AGENTS.md:22`.
- Keep `LogRepository` as the class-log persistence boundary for SQLite plus `logs.json`, based on `core/log_repository.py:61`, `core/log_repository.py:279`, `core/log_repository.py:299`, `core/log_repository.py:413`, and `routes/api_basic.py:1202`.
- Keep pure log merge/conflict semantics in `core/log_rules.py:18`, `core/log_rules.py:22`, and `core/log_rules.py:128`.
- Keep automatic watch/progress transition rules in `core/progress_rules.py`, especially metadata/status ownership at `core/progress_rules.py:8`, `core/progress_rules.py:14`, `core/progress_rules.py:105`, and `core/progress_rules.py:256`.
- Preserve `/api/student/bootstrap` response shape: `assignedTests` stays top-level, and `progress[date][sid].tests` remains authoritative over log metadata, per `routes/api_basic.py:1839`, `routes/api_basic.py:1947`, and `routes/AGENTS.md:23`.
- Preserve academy-network access gating for videos, test answer links, `/api/tests-config`, and `/js/test_answer_link_map.*`, based on `core/network_access.py:66`, `core/network_access.py:70`, `routes/api_basic.py:1080`, `routes/api_basic.py:1855`, `routes/api_basic.py:1933`, `routes/api_tests.py:529`, and `app.py:52`.
- Preserve app-level write protections and auth route registration: cross-origin write blocking stays intact at `app.py:33`, and auth routes remain registered through `app.py:22`, `app.py:107`, and `routes/api_auth.py:386`.
- Preserve admin selected-date and row-date contracts: use row `data-date` first and `getAdminDate()` only as fallback, following `static/js/admin/core/adminDate.js:20`, `static/js/admin/features/today.render.js:951`, and `static/js/admin/features/today.render.js:1360`.
- Keep Korean text as UTF-8 and preserve Korean-capable font stacks, per `AGENTS.md:56`, `static/css/AGENTS.md:16`, and `static/css/AGENTS.md:26`.
- Update `core/admin_chat.py` whenever a user-facing contract changes, especially text around progress/watch and tests at `core/admin_chat.py:117`, `core/admin_chat.py:128`, `core/admin_chat.py:137`, and `core/admin_chat.py:141`.

### Must NOT have (guardrails, anti-slop, scope boundaries)
- No production refactor starts until the user explicitly approves Wave 1.
- No runtime data migrations, full JSON rewrites, SQLite resets, generated answer-link-map hand edits, or broad cleanup unrelated to the active task.
- No endpoint URL, payload key, bootstrap shape, or frontend global-window contract changes without a dedicated migration plan.
- No weakening, skipping, or deleting existing checks in `scripts/verify_refactor_safety.py`.
- No retirement of `static/js/student copy.js` or other apparently unused files without a separate unused-file proof.

### Assumptions and defaults
- This is a whole-project roadmap plus executable task plan; Wave 1 is the recommended first implementation wave.
- Default test decision is TDD for behavioral contracts and tests-after for mechanical CSS containment where static tests cannot prove layout.
- Browser QA uses the Browser/in-app browser first; if unavailable, use Playwright with Chromium and record that fallback in evidence.
- Backend API QA uses Flask `test_client()` with isolated fixtures or non-today dates because `GET /api/logs`, `GET /api/logs/entry`, `GET /api/updates`, and today's student bootstrap can touch runtime state.
- Isolation policy: prefer pure helpers or temp-path `LogRepository`/temp-file drivers. If a route smoke must import `app.create_app()`, wrap it with `scripts.verify_refactor_safety.runtime_fingerprints()` before/after and fail/report any drift except the SQLite sidecars already allowed by `scripts/verify_refactor_safety.py:2305`.

### Metis review findings incorporated
- Metis identified that "whole project" was ambiguous; this plan resolves it as a roadmap plus an explicitly recommended first executable wave.
- Metis required wave boundaries, file ownership, rollback, runtime mutation policy, and stop conditions; these are encoded in the task cards, dependency matrix, and final scope-fidelity checks.
- Metis flagged separate acceptance needs for backend, admin UI, student/bootstrap/tests, CSS, and verification tooling; each wave has distinct references, acceptance criteria, and QA scenarios.
- Metis flagged `static/js/student copy.js` as ambiguous; it remains out of scope until a dedicated unused-file proof.
- Metis flagged CSS cascade risk; Wave 4 uses the concrete URL and viewport matrix below.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: TDD for backend/API/JS contracts, tests-after for CSS containment + existing `scripts/verify_refactor_safety.py`
- QA policy: every task has agent-executed scenarios
- Evidence naming examples: `.omo/evidence/task-1-whole-project-refactor.txt`, `.omo/evidence/task-7-whole-project-refactor.png`, `.omo/evidence/task-18-server-stop.txt`.
- Baseline commands after relevant edits:
  - `python -m compileall -q app.py routes core scripts`
  - `python scripts/verify_refactor_safety.py`
  - `python scripts/verify_refactor_safety.py --smoke`
  - Use the per-wave Node command expansion in the final verification section.
- External references:
  - Flask testing: `https://flask.palletsprojects.com/en/stable/testing/`
  - Flask request context: `https://flask.palletsprojects.com/en/stable/reqcontext/`
  - Python compileall: `https://docs.python.org/3/library/compileall.html`
  - Node `--check`: `https://nodejs.org/api/cli.html`
  - Playwright screenshots: `https://playwright.dev/docs/screenshots`

## Execution strategy
### Parallel execution waves
> Target 5-8 tasks per wave. <3 per wave (except final) = under-splitting.
> Extract shared dependencies as Wave-1 tasks to maximize parallelism.

Wave 1 (backend log/progress contracts, no production refactor before user approval):
- Task 1: Characterize and refactor log repository fallback assembly
- Task 2: Simplify log route orchestration through `LogRepository`
- Task 3: Characterize and refactor progress auto/manual merge predicates
- Task 4: Align watch route writes with progress rules
- Task 5: Narrow bootstrap assigned-test helpers and chatbot contract text

Wave 2 (admin modules, after Wave 1):
- Task 6: Contain today row `data-date` action helpers
- Task 7: Split log modal hydrate/save policy
- Task 8: Split video modal assignment/watch/log policy
- Task 9: Split test modal catalog UI from persistence bridge
- Task 10: Normalize simple admin JSON API wrapper usage

Wave 3 (student/test bootstrap, after Waves 1-2):
- Task 11: Lock backend answer-link precedence
- Task 12: Lock student answer-link rendering and access gating
- Task 13: Protect test catalog import/link-map scripts

Wave 4 (CSS cascade containment, after relevant frontend tasks):
- Task 14: Contain admin stylesheet scope
- Task 15: Contain student stylesheet scope
- Task 16: Contain legacy/shared stylesheet and token overlap

Wave 5 (verification and evidence, runs throughout, final after Waves 1-4):
- Task 17: Expand safety-suite evidence without weakening checks
- Task 18: Add browser QA evidence scripts/specs
- Task 19: Final docs/chatbot drift audit

Critical path: Task 1 -> Task 2 -> Task 5 -> Task 11 -> Task 12 -> Task 17 -> F1-F4

### Dependency matrix
| Task | Depends on | Blocks | Can parallelize with |
|------|------------|--------|----------------------|
| 1 | none | 2, 5, 17 | 3, 6, 14 |
| 2 | 1 | 5, 17 | 4 |
| 3 | none | 4, 7, 8, 17 | 1, 6, 14 |
| 4 | 3 | 8, 17 | 2 |
| 5 | 1, 2, 3 | 11, 19 | none |
| 6 | none | 7, 8, 9, 10, 18 | 1, 3, 14 |
| 7 | 3, 6 | 18 | 8, 9 |
| 8 | 3, 4, 6 | 18 | 7, 9 |
| 9 | 5, 6 | 11, 12, 18 | 7, 8 |
| 10 | 6 | 7, 8, 9 | 14, 15 |
| 11 | 5, 9 | 12, 13, 17 | 14 |
| 12 | 11 | 18 | 13, 15 |
| 13 | 11 | 17, 19 | 12 |
| 14 | none | 18 | 1, 3, 6 |
| 15 | 12 | 18 | 13 |
| 16 | 14, 15 | 18 | 17 |
| 17 | 1, 2, 3, 4, 5, 11, 13 | F1 | 18, 19 |
| 18 | 6, 7, 8, 9, 12, 14, 15, 16 | F3 | 17, 19 |
| 19 | 5, 13, 17 | F4 | 18 |

## Todos
> Implementation + Test = ONE task. Never separate.
> Every task MUST have: References + Acceptance Criteria + QA Scenarios + Commit.

- [x] 1. Characterize and refactor log repository fallback assembly

  What to do: Add tests first in `scripts/verify_refactor_safety.py` for SQLite/JSON fallback merge behavior, then extract only small private helpers inside `core/log_repository.py` to make fallback assembly clearer. Use temp-path `LogRepository` instances for direct QA. Stop if any root runtime JSON/SQLite file changes; rollback by reverting only `core/log_repository.py` and the safety-suite edits.
  Must NOT do: Do not move runtime repair into `core/log_rules.py`; do not bypass `LogRepository`; do not change `/api/logs*` response shapes.

  Parallelization: Can parallel: YES | Wave 1 | Blocks: [2, 5, 17] | Blocked by: []

  References (executor has NO interview context - be exhaustive):
  - Pattern:  `core/log_repository.py:61` - dual-store repository class boundary.
  - Pattern:  `core/log_repository.py:279` - `read_entry()` SQLite-first, JSON fallback behavior.
  - Pattern:  `core/log_repository.py:299` - `read_logs()` map merge behavior.
  - Pattern:  `core/log_repository.py:413` - `patch_entry()` conflict/dual-write path.
  - Pattern:  `core/log_rules.py:22` - pure merge rule to call, not duplicate.
  - Test:     `scripts/verify_refactor_safety.py:188` - existing log-rule checks.
  - External: `https://flask.palletsprojects.com/en/stable/testing/` - use Flask test client for route-level checks.

  Acceptance criteria (agent-executable only):
  - [ ] `python scripts/verify_refactor_safety.py` passes and includes a named assertion proving JSON fills only missing date/sid entries and does not overwrite SQLite fields.
  - [ ] `python -m compileall -q app.py routes core scripts` exits 0.
  - [ ] `git status --short` shows no runtime data files changed by this task.

  QA scenarios (MANDATORY - task incomplete without these):
  ```
  Scenario: fallback merge preserves SQLite entry fields
    Tool:     PowerShell
    Steps:    python -c "import json,pathlib,tempfile; from core.log_repository import LogRepository; from core.log_rules import merge_log_entry_safe,log_entry_conflicts_with_base; td=tempfile.TemporaryDirectory(); p=pathlib.Path(td.name); repo=LogRepository(logs_path=p/'logs.json', db_path=str(p/'app.sqlite'), merge_entry=merge_log_entry_safe, entry_conflicts=log_entry_conflicts_with_base); repo.legacy_post({'2026-06-06':{'s1':{'notes':'sqlite','extra':'keep'}}}); (p/'logs.json').write_text(json.dumps({'2026-06-06':{'s2':{'notes':'json'}}}, ensure_ascii=False), encoding='utf-8'); out=repo.read_logs('2026-06-06',''); print(out['2026-06-06']['s1']['extra'], out['2026-06-06']['s2']['notes'])"
    Expected: stdout is keep json and process exits 0
    Evidence: .omo/evidence/task-1-whole-project-refactor.txt

  Scenario: invalid log patch still returns controlled error
    Tool:     PowerShell
    Steps:    python -c "from app import create_app; c=create_app().test_client(); r=c.post('/api/logs/patch', json={'date':'bad','sid':'s1','entry':{}}); print(r.status_code); print(r.get_json())"
    Expected: status is 400 and JSON error is bad date
    Evidence: .omo/evidence/task-1-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `refactor(logs): isolate repository fallback assembly` | Files: [`core/log_repository.py`, `scripts/verify_refactor_safety.py`]

- [x] 2. Simplify log route orchestration through `LogRepository`

  What to do: After Task 1, remove any duplicated route-level log persistence orchestration that can safely delegate to `get_log_repository()`. Keep routes in `routes/api_basic.py` as validators/response shapers only. Stop if endpoint payloads or status codes drift.
  Must NOT do: Do not remove legacy `/api/logs` POST compatibility; do not route normal writes through `core/logs_sqlite.py`; do not alter `__clear` semantics.

  Parallelization: Can parallel: YES | Wave 1 | Blocks: [5, 17] | Blocked by: [1]

  References:
  - Pattern:  `routes/api_basic.py:1202` - repository factory injects repair/merge/conflict rules.
  - Pattern:  `routes/api_basic.py:2030` - `/api/logs/entry` route.
  - Pattern:  `routes/api_basic.py:2069` - `/api/logs` GET/POST route.
  - Pattern:  `routes/api_basic.py:2090` - `/api/logs/patch` route.
  - Pattern:  `core/log_repository.py:349` - legacy POST behavior.
  - Pattern:  `core/log_repository.py:413` - patch behavior.
  - Test:     `scripts/verify_refactor_safety.py:426` - repository sync/conflict test area.

  Acceptance criteria:
  - [ ] `python scripts/verify_refactor_safety.py` passes with route-level log checks still green.
  - [ ] `python -m compileall -q app.py routes core scripts` exits 0.
  - [ ] Flask test client returns HTTP 200 JSON for `/api/logs/entry?date=2026-06-06&sid=__missing__` with `ok: true`, an object `entry`, and no raw local paths.

  QA scenarios:
  ```
  Scenario: log entry route delegates safely
    Tool:     PowerShell
    Steps:    python -c "from app import create_app; from scripts.verify_refactor_safety import runtime_fingerprints,runtime_diff_keys; b=runtime_fingerprints(); c=create_app().test_client(); r=c.get('/api/logs/entry?date=2026-06-06&sid=__missing__'); a=runtime_fingerprints(); data=r.get_json(); assert r.status_code==200, r.status_code; assert data.get('ok') is True, data; assert isinstance(data.get('entry'), dict), data; assert 'C:\\server' not in r.get_data(as_text=True); print(runtime_diff_keys(b,a)); print('PASS log entry route delegates safely')"
    Expected: stdout contains PASS log entry route delegates safely; runtime diff is empty or only allowed SQLite sidecars
    Evidence: .omo/evidence/task-2-whole-project-refactor.txt

  Scenario: bad log patch date rejected
    Tool:     PowerShell
    Steps:    python -c "from app import create_app; c=create_app().test_client(); r=c.post('/api/logs/patch', json={'date':'bad-date','sid':'s1','entry':{}}); print(r.status_code); print(r.get_json())"
    Expected: status is 400 and error is bad date
    Evidence: .omo/evidence/task-2-whole-project-refactor-error.txt

    Note: current route date validation is intentionally format-only (`YYYY-MM-DD` via `DATE_RE`), not semantic calendar validation. Values such as `2026-99-99` are format-valid under the preserved behavior and must not be used as rejection probes unless a future task intentionally changes the API contract.
  ```

  Commit: YES | Message: `refactor(routes): delegate log endpoints to repository` | Files: [`routes/api_basic.py`, `scripts/verify_refactor_safety.py`]

- [x] 3. Characterize and refactor progress auto/manual merge predicates

  What to do: Add tests first for manual `none`, `skip`, `interrupted`, and auto `done`/`interrupted` interactions, then extract named pure predicates in `core/progress_rules.py` only. Keep metadata keys intact.
  Must NOT do: Do not move progress rules into `core/log_rules.py`; do not rename `__manualProgressMids`, `__autoWatchProgressMids`, or `__allStudentsProgressMids`.

  Parallelization: Can parallel: YES | Wave 1 | Blocks: [4, 7, 8, 17] | Blocked by: []

  References:
  - Pattern:  `core/progress_rules.py:8` - manual metadata key.
  - Pattern:  `core/progress_rules.py:14` - valid video progress statuses.
  - Pattern:  `core/progress_rules.py:62` - watch auto status.
  - Pattern:  `core/progress_rules.py:105` - main progress merge function.
  - Pattern:  `core/progress_rules.py:256` - auto watch progress merge.
  - Test:     `scripts/verify_refactor_safety.py:209` - existing progress rule checks.
  - Test:     `scripts/verify_refactor_safety.py:225` - manual overwrite assertions.

  Acceptance criteria:
  - [ ] `python scripts/verify_refactor_safety.py` passes and includes named assertions for manual white, manual skip, manual interrupted, auto interrupted, and auto done.
  - [ ] `python -m compileall -q app.py routes core scripts` exits 0.
  - [ ] A direct Python call to `merge_progress_day_sid()` shows auto `done` does not overwrite manual `none`.

  QA scenarios:
  ```
  Scenario: auto watch cannot overwrite manual white
    Tool:     PowerShell
    Steps:    python -c "from core.progress_rules import merge_progress_day_sid, PROGRESS_MANUAL_META_KEY; cur={'m1':'none',PROGRESS_MANUAL_META_KEY:{'m1':True}}; print(merge_progress_day_sid(cur, {'m1':'done'}, source='auto')['m1'])"
    Expected: stdout is none
    Evidence: .omo/evidence/task-3-whole-project-refactor.txt

  Scenario: bad incoming status is ignored gracefully
    Tool:     PowerShell
    Steps:    python -c "from core.progress_rules import merge_progress_day_sid, WATCH_AUTO_PROGRESS_META_KEY; cur={'m1':'done',WATCH_AUTO_PROGRESS_META_KEY:{'m1':'done'}}; out=merge_progress_day_sid(cur, {'m1':''}, source='auto'); assert out.get('m1')=='done', out; print('PASS auto empty does not downgrade done')"
    Expected: stdout contains PASS auto empty does not downgrade done
    Evidence: .omo/evidence/task-3-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `refactor(progress): name auto manual merge predicates` | Files: [`core/progress_rules.py`, `scripts/verify_refactor_safety.py`]

- [x] 4. Align watch route writes with progress rules

  What to do: Refactor `routes/api_watch.py` so route helpers call the pure progress/watch functions directly and contain only request validation, storage locking, and response shaping. Add tests before edits for `_save_progress_status()` and `/api/watch-status`.
  Must NOT do: Do not change watch JSON shape; do not allow watch auto status to override manual white/skip.

  Parallelization: Can parallel: YES | Wave 1 | Blocks: [8, 17] | Blocked by: [3]

  References:
  - Pattern:  `routes/api_watch.py:103` - `_save_progress_status()` route-storage helper.
  - Pattern:  `routes/api_watch.py:135` - calls `merge_auto_watch_progress_status()`.
  - Pattern:  `routes/api_watch.py:189` - `/api/watch` route.
  - Pattern:  `routes/api_watch.py:231` - `/api/watch-status` route.
  - Pattern:  `core/progress_rules.py:22` - normalize watch entry.
  - Test:     `scripts/verify_refactor_safety.py:384` - watch route progress checks.

  Acceptance criteria:
  - [ ] `python scripts/verify_refactor_safety.py` passes with watch-route checks.
  - [ ] `python -m compileall -q app.py routes core scripts` exits 0.
  - [ ] `git status --short` shows no `watch.json`, `progress.json`, or SQLite sidecar changes from QA.

  QA scenarios:
  ```
  Scenario: watch route helper preserves manual white
    Tool:     PowerShell
    Steps:    python -c "from scripts import verify_refactor_safety as v; v.run_watch_route_progress_unit_checks(); print('watch-route-ok')"
    Expected: stdout contains watch-route-ok and process exits 0
    Evidence: .omo/evidence/task-4-whole-project-refactor.txt

  Scenario: watch status without network permission fails cleanly or validates input
    Tool:     PowerShell
    Steps:    python -c "from core.progress_rules import watch_auto_status; assert watch_auto_status({'last':4,'dur':100})==''; assert watch_auto_status({'last':95,'dur':100})=='done'; print('PASS watch auto status thresholds')"
    Expected: stdout contains PASS watch auto status thresholds
    Evidence: .omo/evidence/task-4-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `refactor(watch): align route writes with progress rules` | Files: [`routes/api_watch.py`, `scripts/verify_refactor_safety.py`]

- [x] 5. Narrow bootstrap assigned-test helpers and chatbot contract text

  What to do: Add characterization tests for `/api/student/bootstrap` assigned-test authority, then extract private helpers in `routes/api_basic.py`; move a helper to `core/` only if pure and runtime-data-free. Update `core/admin_chat.py` only if behavior/copy changes.
  Must NOT do: Do not change top-level `assignedTests`; do not resurrect stale cleared tests from log metadata; do not call today's bootstrap in QA without smoke fingerprinting.

  Parallelization: Can parallel: NO | Wave 1 | Blocks: [11, 19] | Blocked by: [1, 2, 3]

  References:
  - Pattern:  `routes/api_basic.py:419` - previous test status authority helper.
  - Pattern:  `routes/api_basic.py:668` - assigned-test builder.
  - Pattern:  `routes/api_basic.py:720` - log `assignedTests` metadata read.
  - Pattern:  `routes/api_basic.py:800` - writes `answerUrl` into bootstrap items.
  - Pattern:  `routes/api_basic.py:1839` - student bootstrap route.
  - Pattern:  `routes/api_basic.py:1947` - response includes top-level `assignedTests`.
  - Pattern:  `core/admin_chat.py:137` - chatbot states progress tests are authoritative.
  - Test:     `scripts/verify_refactor_safety.py:793` - assignedTests bootstrap contract.

  Acceptance criteria:
  - [ ] `python scripts/verify_refactor_safety.py` passes and the `assignedTests bootstrap authority contract` still checks top-level array, progress authority, and stale assignment suppression.
  - [ ] `python -m compileall -q app.py routes core scripts` exits 0.
  - [ ] If chatbot text changes, safety suite asserts the new contract text.

  QA scenarios:
  ```
  Scenario: bootstrap keeps assignedTests top-level
    Tool:     PowerShell
    Steps:    python -c "from scripts import verify_refactor_safety as v; v.run_student_bootstrap_unit_checks(); print('bootstrap-contract-ok')"
    Expected: stdout contains bootstrap-contract-ok and process exits 0
    Evidence: .omo/evidence/task-5-whole-project-refactor.txt

  Scenario: missing sid rejected
    Tool:     PowerShell
    Steps:    python -c "from app import create_app; c=create_app().test_client(); r=c.get('/api/student/bootstrap?date=2026-06-06'); print(r.status_code); print(r.get_json())"
    Expected: status is 400 and error is missing sid
    Evidence: .omo/evidence/task-5-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `refactor(bootstrap): isolate assigned test authority helpers` | Files: [`routes/api_basic.py`, `core/admin_chat.py`, `scripts/verify_refactor_safety.py`]

- [x] 6. Contain today row `data-date` action helpers

  What to do: Refactor row action helper boundaries in `today.render.js` and `today.state.js` without changing behavior. Add Node behavior checks for row `data-date` precedence before touching production code.
  Must NOT do: Do not replace whole attendance/contact/absence maps for a row action; do not use real local today where a row has `data-date`.

  Parallelization: Can parallel: YES | Wave 2 | Blocks: [7, 8, 9, 10, 18] | Blocked by: []

  References:
  - Pattern:  `static/js/admin/features/today.render.js:6` - patch endpoint guidance.
  - Pattern:  `static/js/admin/features/today.render.js:242` - arrival row lookup uses `tr[data-sid][data-date]`.
  - Pattern:  `static/js/admin/features/today.render.js:951` - rendered today rows carry `data-date`.
  - Pattern:  `static/js/admin/features/today.render.js:1360` - contact action date fallback.
  - Pattern:  `static/js/admin/features/today.render.js:1547` - homework-leave action date.
  - Pattern:  `static/js/admin/features/today.state.js:80` - `patchLog()`.
  - Pattern:  `static/js/admin/features/today.state.js:547` - attendance cache setter.
  - Pattern:  `static/js/admin/features/today.state.js:591` - contact cache setter.

  Acceptance criteria:
  - [ ] `node --check static/js/admin/features/today.render.js` exits 0.
  - [ ] `node --check static/js/admin/features/today.state.js` exits 0.
  - [ ] `python scripts/verify_refactor_safety.py` passes any added row-date behavior driver.

  QA scenarios:
  ```
  Scenario: row action uses row data-date
    Tool:     playwright(real Chrome)
    Steps:    Start `python app.py`; run `npx --yes --package @playwright/test playwright test .omo/evidence/task-6-row-date.spec.mjs --project=chromium`, where the spec opens `http://127.0.0.1:5000/admin`, sets selected date to 2026-06-07, injects or locates a row with `data-date="2026-06-06"`, clicks a contact/homework action, and records intercepted request JSON.
    Expected: intercepted request body date is 2026-06-06
    Evidence: .omo/evidence/task-6-whole-project-refactor.png

  Scenario: missing row date falls back to selected admin date
    Tool:     playwright(real Chrome)
    Steps:    Same spec removes the row `data-date`, sets selected date to 2026-06-07, triggers the same action, and records intercepted request JSON.
    Expected: intercepted request body date is 2026-06-07
    Evidence: .omo/evidence/task-6-whole-project-refactor-error.png
  ```

  Commit: YES | Message: `refactor(admin): isolate today row date actions` | Files: [`static/js/admin/features/today.render.js`, `static/js/admin/features/today.state.js`, `scripts/verify_refactor_safety.py`]

- [x] 7. Split log modal hydrate/save policy

  What to do: Split `logModal.js` into clearer internal sections or small local helpers for hydrate, snapshots, progress patch collection, and merge-safe save. Add behavior checks first for manual white persistence and empty-field clear semantics.
  Must NOT do: Do not change modal IDs; do not erase unknown log fields; do not let auto watch fill overwrite explicit `none`.

  Parallelization: Can parallel: YES | Wave 2 | Blocks: [18] | Blocked by: [3, 6]

  References:
  - Pattern:  `static/js/admin/features/logModal.js:13` - log snapshot state.
  - Pattern:  `static/js/admin/features/logModal.js:19` - done/skip finished statuses.
  - Pattern:  `static/js/admin/features/logModal.js:112` - progress patch endpoint.
  - Pattern:  `static/js/admin/features/logModal.js:175` - `/api/logs/entry` hydrate.
  - Pattern:  `static/js/admin/features/logModal.js:1138` - changed progress patch collection.
  - Pattern:  `static/js/admin/features/logModal.js:1310` - open modal for row.
  - Pattern:  `static/js/admin/features/logModal.js:1587` - save base.
  - Pattern:  `static/js/admin/features/logModal.js:1851` - auto watch must not overwrite manual state.

  Acceptance criteria:
  - [ ] `node --check static/js/admin/features/logModal.js` exits 0.
  - [ ] `python scripts/verify_refactor_safety.py` passes log modal behavior drivers.
  - [ ] Browser QA proves manual white remains white after save, reload, and reopen.

  QA scenarios:
  ```
  Scenario: manual white persists after save
    Tool:     playwright(real Chrome)
    Steps:    Start `python app.py`; run `npx --yes --package @playwright/test playwright test .omo/evidence/task-7-log-modal.spec.mjs --project=chromium`, where the spec opens `http://127.0.0.1:5000/admin`, sets admin date `2026-06-06`, targets `tr[data-sid="007"][data-date="2026-06-06"]`, opens the log modal, toggles progress cell `td.progress-cell[data-mid="m1"]` to white, saves, reloads, reopens, and reads the same cell state.
    Expected: same cell has data-state="none"; no `???` or `????` appears in notes/homework fields; screenshot path is `.omo/evidence/task-7-whole-project-refactor.png`
    Evidence: .omo/evidence/task-7-whole-project-refactor.png

  Scenario: blank notes do not erase meaningful existing notes without explicit clear
    Tool:     PowerShell
    Steps:    python -c "from core.log_rules import merge_log_entry_safe; print(merge_log_entry_safe({'notes':'keep'}, {'notes':''}).get('notes'))"
    Expected: stdout is keep
    Evidence: .omo/evidence/task-7-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `refactor(admin): split log modal persistence policy` | Files: [`static/js/admin/features/logModal.js`, `scripts/verify_refactor_safety.py`]

- [x] 8. Split video modal assignment/watch/log policy

  What to do: Separate assignment selection, auto/manual source decisions, watch-progress blocking, and extra-video log side effects inside `videoModal.js`. Add behavior checks first for row date and manual assignment preservation.
  Must NOT do: Do not overwrite manual video assignments; do not drop extra-video log note updates; do not use real today when `editingVideoDate` exists.

  Parallelization: Can parallel: YES | Wave 2 | Blocks: [18] | Blocked by: [3, 4, 6]

  References:
  - Pattern:  `static/js/admin/features/videoModal.js:36` - manual progress metadata key.
  - Pattern:  `static/js/admin/features/videoModal.js:39` - course complete statuses.
  - Pattern:  `static/js/admin/features/videoModal.js:572` - hydrate for video modal.
  - Pattern:  `static/js/admin/features/videoModal.js:771` - log assignment patch helper.
  - Pattern:  `static/js/admin/features/videoModal.js:907` - assignment writer preserves source.
  - Pattern:  `static/js/admin/features/videoModal.js:1002` - course progress completion.
  - Pattern:  `static/js/admin/features/videoModal.js:1132` - open modal.
  - Pattern:  `static/js/admin/features/videoModal.js:1137` - row `data-date` source.
  - Pattern:  `static/js/admin/features/videoModal.js:1449` - save uses editing date.

  Acceptance criteria:
  - [ ] `node --check static/js/admin/features/videoModal.js` exits 0.
  - [ ] `python scripts/verify_refactor_safety.py` passes video assignment behavior checks.
  - [ ] Browser QA proves a manual video assignment remains `source:"manual"` after save/reopen.

  QA scenarios:
  ```
  Scenario: manual assignment survives auto course completion
    Tool:     playwright(real Chrome)
    Steps:    Start `python app.py`; run `npx --yes --package @playwright/test playwright test .omo/evidence/task-8-video-modal.spec.mjs --project=chromium`, where the spec opens `/admin`, opens a row video modal, selects an assignment manually, saves, reopens, and captures `/api/updates/patch` request body.
    Expected: request body entry.source is manual and date equals the row `data-date`
    Evidence: .omo/evidence/task-8-whole-project-refactor.png

  Scenario: empty forced assignment clears updates without log crash
    Tool:     playwright(real Chrome)
    Steps:    Same spec calls `window.saveVideoAssignmentPopup({showPopup:false, refresh:false, forceEmpty:true})` in page context for an open modal and captures console/errors.
    Expected: no uncaught error; intercepted `/api/updates/patch` body has `videos: []` and `source: "manual"` for date `2026-06-06`, sid `007`
    Evidence: .omo/evidence/task-8-whole-project-refactor-error.png
  ```

  Commit: YES | Message: `refactor(admin): split video assignment policy` | Files: [`static/js/admin/features/videoModal.js`, `scripts/verify_refactor_safety.py`]

- [x] 9. Split test modal catalog UI from persistence bridge

  What to do: Keep catalog/filter rendering separate from save behavior in `testModal.js`; add tests before edits for `progress[date][sid].tests` authority and log `assignedTests` metadata behavior.
  Must NOT do: Do not resurrect cleared assignments; do not make log `assignedTests` authoritative over progress; do not change category keys.

  Parallelization: Can parallel: YES | Wave 2 | Blocks: [11, 12, 18] | Blocked by: [5, 6]

  References:
  - Pattern:  `static/js/admin/features/testModal.js:2` - progress tests are the assignment store.
  - Pattern:  `static/js/admin/features/testModal.js:542` - current progress tests.
  - Pattern:  `static/js/admin/features/testModal.js:974` - open modal for row.
  - Pattern:  `static/js/admin/features/testModal.js:980` - row `data-date` source.
  - Pattern:  `static/js/admin/features/testModal.js:1108` - log assignment patch.
  - Pattern:  `static/js/admin/features/testModal.js:1124` - log `assignedTests` metadata.
  - Pattern:  `static/js/admin/features/testModal.js:1171` - save modal.
  - Pattern:  `static/js/admin/features/testModal.js:1199` - progress patch.

  Acceptance criteria:
  - [ ] `node --check static/js/admin/features/testModal.js` exits 0.
  - [ ] `python scripts/verify_refactor_safety.py` passes assigned-test authority checks.
  - [ ] Browser QA proves saving a test writes `/api/progress/patch` with `tests` and `/api/logs/patch` only as metadata/notes.

  QA scenarios:
  ```
  Scenario: test save writes progress authority and log metadata
    Tool:     playwright(real Chrome)
    Steps:    Start `python app.py`; run `npx --yes --package @playwright/test playwright test .omo/evidence/task-9-test-modal.spec.mjs --project=chromium`, where the spec opens `/admin`, opens a row test modal, selects one visible test, saves, and records intercepted `/api/progress/patch` and `/api/logs/patch`.
    Expected: progress request contains `progress.tests`; log request contains `assignedTests` metadata when non-skip items exist
    Evidence: .omo/evidence/task-9-whole-project-refactor.png

  Scenario: skipped/cleared test is not resurrected from log metadata
    Tool:     PowerShell
    Steps:    python -c "from scripts import verify_refactor_safety as v; v.run_student_bootstrap_unit_checks(); print('no-resurrection-ok')"
    Expected: stdout contains no-resurrection-ok and process exits 0
    Evidence: .omo/evidence/task-9-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `refactor(admin): split test assignment persistence` | Files: [`static/js/admin/features/testModal.js`, `scripts/verify_refactor_safety.py`]

- [x] 10. Normalize simple admin JSON API wrapper usage

  What to do: Convert only simple JSON GET/POST calls to `static/js/admin/core/api.js` or `static/js/shared/api.js` where behavior is identical. Leave conflict-aware, retry, and merge-base flows local unless the wrapper can preserve all semantics.
  Must NOT do: Do not genericize `/api/logs/patch`, `/api/progress/patch`, or lock-retry flows if it hides error labels or retry behavior.

  Parallelization: Can parallel: YES | Wave 2 | Blocks: [7, 8, 9] | Blocked by: [6]

  References:
  - Pattern:  `static/js/shared/api.js:40` - `fetchJson`.
  - Pattern:  `static/js/shared/api.js:45` - `fetchJsonOr`.
  - Pattern:  `static/js/admin/core/api.js:1` - admin wrapper imports shared helpers.
  - Pattern:  `static/js/admin/core/state.js:18` - bootstrap entry.
  - Pattern:  `static/js/admin/core/state.js:26` - critical `/api/updates` get.
  - Pattern:  `static/js/admin/core/state.js:29` - critical `/api/logs` get.
  - Pattern:  `static/js/admin/core/state.js:31` - critical `/api/progress` get.
  - Test:     `scripts/verify_refactor_safety.py:823` - shared helper/bootstrap assertions.

  Acceptance criteria:
  - [ ] `node --check static/js/shared/api.js` exits 0 if touched.
  - [ ] Run these exact syntax checks for edited admin files: `node --check static/js/admin/core/state.js`; `node --check static/js/admin/core/api.js`; `node --check static/js/admin/features/today.render.js`; `node --check static/js/admin/features/logModal.js`; `node --check static/js/admin/features/testModal.js`; `node --check static/js/admin/features/videoModal.js`.
  - [ ] `python scripts/verify_refactor_safety.py` preserves strict bootstrap error-label assertions.

  QA scenarios:
  ```
  Scenario: critical bootstrap failure still rejects visibly
    Tool:     PowerShell
    Steps:    python scripts/verify_refactor_safety.py
    Expected: suite exits 0 and strict bootstrap helper assertions pass
    Evidence: .omo/evidence/task-10-whole-project-refactor.txt

  Scenario: optional tests-config fallback remains optional
    Tool:     PowerShell
    Steps:    node --check static/js/admin/core/state.js
    Expected: process exits 0; source still contains `api.getOr('/api/tests-config', { categories: {} })`
    Evidence: .omo/evidence/task-10-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `refactor(admin-api): normalize simple json calls` | Files: [`static/js/shared/api.js`, `static/js/admin/core/api.js`, `static/js/admin/core/state.js`, `static/js/admin/features/today.render.js`, `static/js/admin/features/logModal.js`, `static/js/admin/features/testModal.js`, `static/js/admin/features/videoModal.js`, `scripts/verify_refactor_safety.py`]

- [x] 11. Lock backend answer-link precedence

  What to do: Add tests for answer URL precedence in bootstrap: assignment direct URL, test config URL/file id, generated link map. Refactor backend helper names/shape only after tests.
  Must NOT do: Do not hand-edit `static/js/test_answer_link_map.json`; do not change `TEST_ANSWER_LINK_MAP_PATH`; do not require network access for Drive URL validation.

  Parallelization: Can parallel: YES | Wave 3 | Blocks: [12, 13, 17] | Blocked by: [5, 9]

  References:
  - Pattern:  `routes/api_basic.py:518` - loads answer-link map.
  - Pattern:  `routes/api_basic.py:544` - reads URL aliases from map entry.
  - Pattern:  `routes/api_basic.py:576` - builds Drive URL from config file id.
  - Pattern:  `routes/api_basic.py:668` - assigned-test builder.
  - Pattern:  `routes/api_basic.py:800` - assigns `answerUrl`.
  - Pattern:  `routes/api_basic.py:1080` - strips answer links when academy network is not allowed.
  - Pattern:  `routes/api_basic.py:1215` - answer-link map path.
  - Pattern:  `routes/api_basic.py:1933` - applies academy restriction to assigned tests.
  - Pattern:  `core/network_access.py:70` - strips answer-link fields from nested test data.
  - Pattern:  `routes/api_tests.py:529` - `/api/tests-config` applies answer-link restriction.
  - Pattern:  `app.py:52` - blocks generated answer-link map outside academy network.
  - Test:     `scripts/verify_refactor_safety.py:799` - chatbot answer-link knowledge strings.

  Acceptance criteria:
  - [ ] `python scripts/verify_refactor_safety.py` passes with answer-link precedence cases.
  - [ ] `python -m compileall -q app.py routes core scripts` exits 0.
  - [ ] Bootstrap test fixture returns Drive-style `answerUrl` when only `sourceFiles.solutionFileId` is present.
  - [ ] Outside-academy fixture strips `answerUrl`/file IDs from assigned tests while keeping the assigned-test item visible.

  QA scenarios:
  ```
  Scenario: backend resolves answerUrl from config metadata
    Tool:     PowerShell
    Steps:    python -c "from scripts import verify_refactor_safety as v; v.run_student_bootstrap_unit_checks(); print('answer-link-backend-ok')"
    Expected: stdout contains answer-link-backend-ok and process exits 0
    Evidence: .omo/evidence/task-11-whole-project-refactor.txt

  Scenario: missing answer metadata leaves answerUrl absent, not broken
    Tool:     PowerShell
    Steps:    python -c "from core.network_access import strip_answer_link_fields; item={'label':'T','answerUrl':'https://drive.google.com/file/d/x/view','sourceFiles':{'solutionFileId':'x'}}; stripped,changed=strip_answer_link_fields(item); print(changed, 'answerUrl' in stripped, stripped.get('sourceFiles'))"
    Expected: stdout shows True False and sourceFiles without solutionFileId
    Evidence: .omo/evidence/task-11-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `refactor(tests): lock bootstrap answer link precedence` | Files: [`routes/api_basic.py`, `scripts/verify_refactor_safety.py`]

- [x] 12. Lock student answer-link rendering and access gating

  What to do: Refactor `static/js/student.js` only after Task 11; keep bootstrap consumption, `window.__ASSIGNED_TESTS__`, answer button rendering, and academy-network gating stable.
  Must NOT do: Do not remove legacy fallback to `/api/tests-config` or generated map unless a test proves it is unused; do not expose Drive links when access is restricted.

  Parallelization: Can parallel: YES | Wave 3 | Blocks: [15, 18] | Blocked by: [11]

  References:
  - Pattern:  `static/js/student.js:491` - bootstrap fetch.
  - Pattern:  `static/js/student.js:509` - normalizes bootstrap `assignedTests`.
  - Pattern:  `static/js/student.js:780` - assigned tests panel rendering.
  - Pattern:  `static/js/student.js:793` - answer URL extraction for button.
  - Pattern:  `static/js/student.js:918` - assigned test normalization.
  - Pattern:  `static/js/student.js:920` - `window.__ASSIGNED_TESTS__`.
  - Pattern:  `static/js/student.js:2779` - link-map entry URL resolution.
  - Pattern:  `static/js/student.js:2788` - configured test answer URL.

  Acceptance criteria:
  - [ ] `node --check static/js/student.js` exits 0.
  - [ ] Browser QA proves `#assignedTestsPanel` renders a link when allowed and disables/restricts the link when academy access is false.
  - [ ] `python scripts/verify_refactor_safety.py` passes student/bootstrap checks.

  QA scenarios:
  ```
  Scenario: student card renders allowed answer link
    Tool:     playwright(real Chrome)
    Steps:    Start `python app.py`; run `npx --yes --package @playwright/test playwright test .omo/evidence/task-12-student-links.spec.mjs --project=chromium`, where the spec opens `http://127.0.0.1:5000/student/007?date=2026-06-06`, injects or intercepts bootstrap fixture label `UNIT-LINK-QA-2026-06-06`, and inspects `#assignedTestsPanel [data-answer-url]`.
    Expected: panel is visible and data-answer-url equals `https://drive.google.com/file/d/TEST_SOLUTION_FILE_ID_20260606/view`
    Evidence: .omo/evidence/task-12-whole-project-refactor.png

  Scenario: restricted access does not open answer link
    Tool:     playwright(real Chrome)
    Steps:    Same spec stubs bootstrap with `academyAccessAllowed:false` and an assigned test answerUrl, then clicks the answer control.
    Expected: page URL remains `http://127.0.0.1:5000/student/007?date=2026-06-06`; no `page` event opens a Drive URL; `#assignedTestList .assigned-test-btn[data-answer-restricted="1"][data-answer-url="https://drive.google.com/file/d/TEST_SOLUTION_FILE_ID_20260606/view"]` has tagName `BUTTON` and no `href` attribute
    Evidence: .omo/evidence/task-12-whole-project-refactor-error.png
  ```

  Commit: YES | Message: `refactor(student): preserve assigned test answer links` | Files: [`static/js/student.js`, `scripts/verify_refactor_safety.py`]

- [x] 13. Protect test catalog import/link-map scripts

  What to do: Add or preserve tests around scripts that mutate `tests-config.json` or generate `static/js/test_answer_link_map.json`. Document command safety and require backups before real runs.
  Must NOT do: Do not run Drive/gdown import scripts against live files casually; do not mutate `tests-config.json` without explicit backup and user approval.

  Parallelization: Can parallel: YES | Wave 3 | Blocks: [17, 19] | Blocked by: [11]

  References:
  - Pattern:  `scripts/AGENTS.md:18` - scripts can mutate operational data.
  - Pattern:  `scripts/AGENTS.md:28` - REVIEW/SCHOOL_PAST solution metadata requirement.
  - Pattern:  `scripts/AGENTS.md:29` - UNIT link-map regeneration requirement.
  - Pattern:  `scripts/AGENTS.md:33` - do not run import/seed casually.
  - Pattern:  `scripts/build_unit_test_answer_link_map_from_gdown.py:172` - writes `answerUrl`.
  - Pattern:  `scripts/build_unit_test_answer_link_map_from_gdown.py:191` - config argument.
  - Pattern:  `scripts/build_unit_test_answer_link_map_from_gdown.py:192` - output map argument.
  - Pattern:  `scripts/import_review_test_catalog_append_csv.py:122` - sourceFiles metadata.
  - Pattern:  `scripts/import_school_past_test_catalog_append_csv.py:149` - sourceFiles metadata.

  Acceptance criteria:
  - [ ] `python -m compileall -q scripts` exits 0.
  - [ ] Any new script tests use temp files only and leave root `tests-config.json` and `static/js/test_answer_link_map.json` unchanged.
  - [ ] `git status --short` shows no runtime/generated catalog files changed unless explicitly in scope.

  QA scenarios:
  ```
  Scenario: script safety uses temp output
    Tool:     PowerShell
    Steps:    python -m compileall -q scripts
    Expected: process exits 0
    Evidence: .omo/evidence/task-13-whole-project-refactor.txt

  Scenario: generated map is not hand-edited
    Tool:     PowerShell
    Steps:    git status --short -- tests-config.json static/js/test_answer_link_map.json
    Expected: no output unless the task explicitly generated these files with backup evidence
    Evidence: .omo/evidence/task-13-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `test(catalog): guard answer link script contracts` | Files: [`scripts/build_unit_test_answer_link_map_from_gdown.py`, `scripts/import_unit_test_catalog_csv.py`, `scripts/import_review_test_catalog_append_csv.py`, `scripts/import_school_past_test_catalog_append_csv.py`, `scripts/verify_refactor_safety.py`, `scripts/refactor_notes_logs_progress.md`]

- [x] 14. Contain admin stylesheet scope

  What to do: Refactor `static/css/admin.css` by page/body scope and modal block, preserving Korean font stacks, dark mode, and responsive table/modal layout. Add static selector/font checks if behavior changes.
  Must NOT do: Do not introduce unscoped global selectors; do not move admin modal styles into shared CSS without proving all pages are intended.

  Parallelization: Can parallel: YES | Wave 4 | Blocks: [16, 18] | Blocked by: []

  References:
  - Pattern:  `static/css/admin.css:5` - admin body scope starts early.
  - Pattern:  `static/css/admin.css:52` - dark theme/reset area.
  - Pattern:  `static/css/admin.css:1917` - modal infrastructure area.
  - Pattern:  `static/css/admin.css:6485` - late service-wide admin normalization.
  - Pattern:  `static/css/admin.css:6487` - scoped font normalization.
  - Pattern:  `static/css/AGENTS.md:23` - no unscoped globals.
  - Pattern:  `static/css/AGENTS.md:26` - Korean-capable fonts.

  Acceptance criteria:
  - [ ] Static check confirms any changed selector in `admin.css` is scoped to `body.admin`, a modal ID, or another existing stable admin wrapper.
  - [ ] Browser screenshots cover `/admin` desktop and mobile, light/dark if available.
  - [ ] Korean text in admin modals/tables remains readable and does not overlap.

  QA scenarios:
  ```
  Scenario: admin layout still renders after CSS containment
    Tool:     playwright(real Chrome)
    Steps:    Start `python app.py`; run `npx --yes --package @playwright/test playwright test .omo/evidence/task-14-admin-css.spec.mjs --project=chromium`, where the spec screenshots `/admin` at 1440x900 and 390x844.
    Expected: screenshots are nonblank; today table and modal controls are visible without overlap
    Evidence: .omo/evidence/task-14-whole-project-refactor.png

  Scenario: admin CSS keeps Korean font stack
    Tool:     PowerShell
    Steps:    python -c "from pathlib import Path; s=Path('static/css/admin.css').read_text(encoding='utf-8'); assert 'Noto Sans KR' in s or 'Apple SD Gothic Neo' in s or 'Malgun Gothic' in s; print('font-ok')"
    Expected: stdout contains font-ok
    Evidence: .omo/evidence/task-14-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `refactor(css): contain admin stylesheet scope` | Files: [`static/css/admin.css`, `scripts/verify_refactor_safety.py`]

- [x] 15. Contain student stylesheet scope

  What to do: Refactor `static/css/student.css` by `body.student-page`, assigned-test panel, announcement modal, and responsive layout blocks. Coordinate with Task 12 for assigned-test card behavior.
  Must NOT do: Do not break `#assignedTestsPanel`, announcement modals, academy-access UI, or mobile layout; do not use Latin-only font stacks.

  Parallelization: Can parallel: YES | Wave 4 | Blocks: [16, 18] | Blocked by: [12]

  References:
  - Pattern:  `static/css/student.css:5` - student page body scope.
  - Pattern:  `static/css/student.css:573` - announcement modal block.
  - Pattern:  `static/css/student.css:1110` - later modal rewrite block.
  - Pattern:  `static/css/student.css:2368` - announcement history modal block.
  - Pattern:  `static/css/student.css:2663` - late normalization block.
  - Pattern:  `static/student.html:83` - `#assignedTestsPanel` shell.
  - Pattern:  `static/css/AGENTS.md:16` - Korean font stack requirement.

  Acceptance criteria:
  - [ ] Browser screenshots cover `http://127.0.0.1:5000/student/007?date=2026-06-06` at desktop `1440x900` and mobile `390x844`.
  - [ ] `#assignedTestsPanel` remains hidden with no assigned tests and visible with assigned tests.
  - [ ] Korean text and test card buttons fit without overlap.

  QA scenarios:
  ```
  Scenario: student assigned tests panel fits
    Tool:     playwright(real Chrome)
    Steps:    Start `python app.py`; run `npx --yes --package @playwright/test playwright test .omo/evidence/task-15-student-css.spec.mjs --project=chromium`, where the spec loads `http://127.0.0.1:5000/student/007?date=2026-06-06` with assigned-test fixture label `UNIT-LINK-QA-2026-06-06` at viewports `1440x900` and `390x844`.
    Expected: panel text/buttons do not overlap; screenshots `.omo/evidence/task-15-student-css-1440.png` and `.omo/evidence/task-15-student-css-390.png` are nonblank
    Evidence: .omo/evidence/task-15-whole-project-refactor.png

  Scenario: no assigned tests hides panel cleanly
    Tool:     playwright(real Chrome)
    Steps:    Same spec stubs bootstrap with `assignedTests:[]` and inspects `#assignedTestsPanel`.
    Expected: panel has `hidden` or is not displayed
    Evidence: .omo/evidence/task-15-whole-project-refactor-error.png
  ```

  Commit: YES | Message: `refactor(css): contain student stylesheet scope` | Files: [`static/css/student.css`, `scripts/verify_refactor_safety.py`]

- [x] 16. Contain legacy/shared stylesheet and token overlap

  What to do: Reduce duplicate token/global overlap between `static/css/style.css` and `static/css/main.css` only where behavior is proven stable. Keep all-students/tests utility pages visually stable.
  Must NOT do: Do not move shared selectors into `admin.css`; do not break `/students`, `/tests`, all-students, or utility pages.

  Parallelization: Can parallel: YES | Wave 4 | Blocks: [18] | Blocked by: [14, 15]

  References:
  - Pattern:  `static/css/main.css:6` - shared token block.
  - Pattern:  `static/css/main.css:35` - base font-family uses Korean-capable variables.
  - Pattern:  `static/css/style.css:1` - legacy token block.
  - Pattern:  `static/css/style.css:41` - legacy body font-family.
  - Pattern:  `static/css/style.css:1744` - all-page containment area.
  - Pattern:  `static/css/style.css:1818` - shared modal wrappers.
  - Pattern:  `static/css/style.css:1923` - responsive all-page overrides.

  Acceptance criteria:
  - [ ] Browser screenshots cover `http://127.0.0.1:5000/students`, `http://127.0.0.1:5000/tests`, and `http://127.0.0.1:5000/student/007?date=2026-06-06` at desktop `1440x900` and mobile `390x844`.
  - [ ] Static check confirms Korean-capable fonts remain in `main.css` and `style.css`.
  - [ ] No changed selector broadens from page-scoped to global without explicit comment and QA evidence.

  QA scenarios:
  ```
  Scenario: shared pages remain visually stable
    Tool:     playwright(real Chrome)
    Steps:    Start `python app.py`; run `npx --yes --package @playwright/test playwright test .omo/evidence/task-16-shared-css.spec.mjs --project=chromium`, where the spec screenshots `http://127.0.0.1:5000/students`, `http://127.0.0.1:5000/tests`, and `http://127.0.0.1:5000/student/007?date=2026-06-06` at `1440x900` and `390x844`.
    Expected: screenshots `.omo/evidence/task-16-students-1440.png`, `.omo/evidence/task-16-students-390.png`, `.omo/evidence/task-16-tests-1440.png`, `.omo/evidence/task-16-tests-390.png`, `.omo/evidence/task-16-student-1440.png`, and `.omo/evidence/task-16-student-390.png` are nonblank and no overlapping table/modal text is detected by DOM bounding boxes
    Evidence: .omo/evidence/task-16-whole-project-refactor.png

  Scenario: shared CSS keeps Korean font stack
    Tool:     PowerShell
    Steps:    python -c "from pathlib import Path; s=(Path('static/css/style.css').read_text(encoding='utf-8')+Path('static/css/main.css').read_text(encoding='utf-8')); assert 'Noto Sans KR' in s or 'Apple SD Gothic Neo' in s or 'Malgun Gothic' in s; print('shared-font-ok')"
    Expected: stdout contains shared-font-ok
    Evidence: .omo/evidence/task-16-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `refactor(css): contain shared stylesheet scope` | Files: [`static/css/style.css`, `static/css/main.css`, `scripts/verify_refactor_safety.py`]

- [x] 17. Expand safety-suite evidence without weakening checks

  What to do: Add focused helpers and named assertions to `scripts/verify_refactor_safety.py` for any contract changed by Tasks 1-13. Keep smoke fingerprinting and skip rules intact.
  Must NOT do: Do not delete, skip, loosen, or rename existing checks to hide failures.

  Parallelization: Can parallel: YES | Wave 5 | Blocks: [F1] | Blocked by: [1, 2, 3, 4, 5, 11, 13]

  References:
  - Pattern:  `scripts/verify_refactor_safety.py:29` - JS check file list.
  - Pattern:  `scripts/verify_refactor_safety.py:178` - `run_js_checks()`.
  - Pattern:  `scripts/verify_refactor_safety.py:209` - progress unit checks.
  - Pattern:  `scripts/verify_refactor_safety.py:384` - watch route progress checks.
  - Pattern:  `scripts/verify_refactor_safety.py:793` - assignedTests bootstrap contract.
  - Pattern:  `scripts/verify_refactor_safety.py:2261` - smoke paths.
  - Pattern:  `scripts/verify_refactor_safety.py:2299` - skips today's bootstrap due to auto-write risk.
  - Pattern:  `scripts/verify_refactor_safety.py:2317` - `--smoke`.

  Acceptance criteria:
  - [ ] `python scripts/verify_refactor_safety.py` exits 0.
  - [ ] `python scripts/verify_refactor_safety.py --smoke` exits 0 or reports a documented safe skip without runtime fingerprint drift.
  - [ ] `python -m compileall -q app.py routes core scripts` exits 0.

  QA scenarios:
  ```
  Scenario: full safety suite passes
    Tool:     PowerShell
    Steps:    python scripts/verify_refactor_safety.py
    Expected: process exits 0
    Evidence: .omo/evidence/task-17-whole-project-refactor.txt

  Scenario: smoke fingerprints runtime state
    Tool:     PowerShell
    Steps:    python scripts/verify_refactor_safety.py --smoke
    Expected: process exits 0 or safe-skip message is printed; no unexpected runtime mutation is reported
    Evidence: .omo/evidence/task-17-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `test(safety): expand refactor contract coverage` | Files: [`scripts/verify_refactor_safety.py`]

- [x] 18. Add browser QA evidence scripts/specs

  What to do: Add task-scoped Playwright specs or Browser transcripts under `.omo/evidence/` for frontend tasks. Specs may be temporary evidence artifacts unless the user wants them productized.
  Must NOT do: Do not require real Drive access; do not leave dev server sessions running unless user asks.

  Parallelization: Can parallel: YES | Wave 5 | Blocks: [F3] | Blocked by: [6, 7, 8, 9, 12, 14, 15, 16]

  References:
  - Pattern:  `AGENTS.md:125` - Browser/UI verification notes.
  - Pattern:  `AGENTS.md:127` - prefer Browser/in-app browser, fallback to Chrome/Playwright.
  - Pattern:  `AGENTS.md:129` - verify Korean rendering when touching static HTML/JS.
  - External: `https://playwright.dev/docs/screenshots` - screenshot evidence.
  - External: `https://playwright.dev/docs/browsers` - browser setup.

  Acceptance criteria:
  - [ ] Every frontend task has its named screenshot or transcript: task 6, 7, 8, 9, 12, 14, 15, and 16 evidence paths listed in their task cards.
  - [ ] Server process started for QA is stopped after evidence capture.
  - [ ] Evidence records target URL, viewport, selected date when relevant, and pass/fail observation.

  QA scenarios:
  ```
  Scenario: frontend evidence exists
    Tool:     PowerShell
    Steps:    python -c "from pathlib import Path; required=[6,7,8,9,12,14,15,16]; missing=[n for n in required if not list(Path('.omo/evidence').glob(f'task-{n}-*'))]; print(missing); assert not missing"
    Expected: stdout is []
    Evidence: .omo/evidence/task-18-whole-project-refactor.txt

  Scenario: no verification server left running by task scripts
    Tool:     PowerShell
    Steps:    python -c "print('executor must record server pid stop evidence in .omo/evidence/task-18-server-stop.txt')"
    Expected: executor-created server-stop evidence file exists and names stopped pid/port
    Evidence: .omo/evidence/task-18-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `test(ui): add browser refactor evidence` | Files: [`.omo/evidence/task-*.spec.mjs`, `.omo/evidence/*.txt`, `scripts/verify_refactor_safety.py`]

- [x] 19. Final docs/chatbot drift audit

  What to do: Audit `core/admin_chat.py`, `scripts/refactor_notes_logs_progress.md`, and scoped `AGENTS.md` files only for changed user-facing contracts. Update narrowly and verify text coverage.
  Must NOT do: Do not churn AGENTS files for implementation details; do not rewrite generated docs or unrelated guidance.

  Parallelization: Can parallel: YES | Wave 5 | Blocks: [F4] | Blocked by: [5, 13, 17]

  References:
  - Pattern:  `core/admin_chat.py:117` - manual white/skip watch-progress warning.
  - Pattern:  `core/admin_chat.py:128` - progress rules centralization text.
  - Pattern:  `core/admin_chat.py:137` - progress tests are authoritative.
  - Pattern:  `core/admin_chat.py:141` - answer-link sync requirement.
  - Pattern:  `core/admin_chat.py:177` - bootstrap shape text.
  - Pattern:  `scripts/refactor_notes_logs_progress.md:101` - manual progress metadata notes.
  - Pattern:  `AGENTS.md:78` - admin chatbot sync rule.

  Acceptance criteria:
  - [ ] `python scripts/verify_refactor_safety.py` passes chatbot knowledge assertions.
  - [ ] `git diff -- core/admin_chat.py scripts/refactor_notes_logs_progress.md AGENTS.md static/AGENTS.md static/css/AGENTS.md` contains only changed-contract text.
  - [ ] No runtime data appears in the diff.

  QA scenarios:
  ```
  Scenario: chatbot contract text is covered
    Tool:     PowerShell
    Steps:    python scripts/verify_refactor_safety.py
    Expected: suite exits 0 and chatbot contract assertions pass
    Evidence: .omo/evidence/task-19-whole-project-refactor.txt

  Scenario: docs audit excludes runtime data
    Tool:     PowerShell
    Steps:    git status --short
    Expected: output separates code/docs/evidence from runtime data; no root runtime JSON/SQLite file is staged or committed
    Evidence: .omo/evidence/task-19-whole-project-refactor-error.txt
  ```

  Commit: YES | Message: `docs(refactor): sync academy contract knowledge` | Files: [`core/admin_chat.py`, `scripts/refactor_notes_logs_progress.md`, `AGENTS.md`, `static/AGENTS.md`, `static/css/AGENTS.md`]

## Final verification wave (MANDATORY - after all implementation tasks)
> Runs in PARALLEL. ALL must APPROVE. Surface results to the caller and wait for an explicit "okay" before declaring complete.
- [x] F1. Plan compliance audit - every task done, every acceptance criterion met
- [x] F2. Code quality review - diagnostics clean, idioms match, no dead code
- [x] F3. Real manual QA - every QA scenario executed with evidence captured
- [x] F4. Scope fidelity - nothing extra shipped beyond Must-Have, nothing Must-NOT-Have introduced

## Commit strategy
- One logical change per commit. Conventional Commits use the literal shape `type(scope): imperative subject`, for example `refactor(logs): isolate repository fallback assembly`.
- Atomic: every commit builds and passes tests on its own.
- No "WIP" / "fix typo squash later" commits on the final branch - clean up before merge.
- Reference the plan file path in the final commit footer: `Plan: .omo/plans/whole-project-refactor.md`.
- Runtime data stays uncommitted unless the user explicitly asks for a data backup commit.
- Before every commit, run `git status --short` and record staged, unstaged, untracked, and runtime/local files separately.

## Success criteria
- All Must-Have shipped; all QA scenarios pass with captured evidence; F1-F4 approved; commit history clean.
- Wave 1 is completed first and approved before Waves 2-4 begin.
- No runtime data changes occur without explicit backup/fingerprint evidence.
- `core/admin_chat.py` and safety-suite assertions remain current for changed user-facing contracts.
