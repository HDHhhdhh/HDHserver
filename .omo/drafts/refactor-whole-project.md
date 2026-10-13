# Draft: Whole Project Refactor

## Requirements (confirmed)
- User invoked `omo:init-deep`.
- User invoked `omo:ulw-plan` for `omo:refactor this whole project`.

## Skill Survey
- `omo:init-deep`: use to update the hierarchical `AGENTS.md` knowledge base.
- `omo:ulw-plan`: use because the request is architecture-scale, ambiguous, and explicitly asks for planning.
- `omo:refactor`: use for intent validation and refactor safety protocol; production refactor execution is deferred until a concrete target/wave is approved.
- `academy-runtime-safety`: keep in mind because this repo contains live JSON/SQLite runtime data; no runtime data changes are in scope for planning.
- `academy-log-progress-guardian`: relevant to any future refactor touching logs, homework, video progress, watch callbacks, or student bootstrap.
- `admin-ui-date-verifier`: relevant to any future refactor touching `/admin`, selected-date behavior, row actions, or Korean-rendered admin UI.
- `omo:programming`: relevant for future `.py`/`.js` production changes, but not for this planning-only artifact unless code changes begin.

## Technical Decisions
- Treat `refactor this whole project` as a planning request, not immediate production mutation, because whole-project refactor is open-ended and the refactor skill requires concrete target, outcome, scope, and success criteria before edits.
- Keep current deliverables to AGENTS hierarchy refresh plus a decision-complete refactor work plan.
- Do not change runtime JSON, SQLite, frontend behavior, backend routes, or source code in this pass.

## Research Findings
- Pre-edit `git status --short`: clean.
- Current commit: `05e5310`.
- Current branch: `codex/apple-clean-redesign`.
- Existing AGENTS hierarchy: root, `core`, `routes`, `scripts`, `static`, `static/js`, `static/js/admin`, `static/js/admin/features`, `static/js/all`.
- `bash` resolves to unavailable WSL in this session; PowerShell is used for local inspection.
- Source-root scan (`app.py`, `core`, `routes`, `static`, `scripts`): 126 files, about 69,260 code/doc lines, 29 code files over 500 lines.
- Largest hotspots: `static/css/admin.css` (6,015 lines), `static/js/student.js` (2,964), `static/js/admin/features/announcements.js` (2,750), `scripts/verify_refactor_safety.py` (2,175), `routes/api_basic.py` (1,829), `static/js/admin/features/logModal.js` (1,618), `static/js/admin/features/today.render.js` (1,549).
- AGENTS scoring kept the existing hierarchy and added `static/css/AGENTS.md` because `static/css` is a distinct high-line-count cascade boundary.

## Open Questions
- Which first refactor wave should be executed after the plan: backend log/progress contracts, frontend admin API wrapper consolidation, test/bootstrap cleanup, or verification tooling?

## Scope Boundaries
- INCLUDE: AGENTS.md hierarchy analysis/update; `.omo/plans/` whole-project refactor plan; no production behavior changes.
- EXCLUDE: direct source-code refactors, runtime data migration, commits/staging, browser QA for app behavior.

## Evidence Ledger
- Captured: init-deep discovery metrics from source-root scan.
- Captured: read-only subagent findings for structure, entrypoints, conventions, anti-patterns, build/CI, tests, architecture, hotspots, and runtime contracts.
- Captured: AGENTS update added `static/css/AGENTS.md` and refreshed root metadata.
- Captured: plan artifact path `.omo/plans/whole-project-refactor.md`.
- Captured: first plan agent was inconclusive and closed; second plan agent initially reported a write issue, then completed and expanded `.omo/plans/whole-project-refactor.md`. Root tightened reviewer-flagged QA placeholders and evidence sections.
- Captured: Metis gap analysis found ambiguity in "whole project", missing wave boundaries, runtime QA mutation risk, need for distinct backend/admin/student/CSS/verification acceptance checks, `static/js/student copy.js` scope ambiguity, and CSS cascade risk. The final plan records these under `Metis review findings incorporated`.
- Captured: scoped status shows intended tracked docs plus untracked `.omo/` and `static/css/AGENTS.md`.
- Captured: recursive `.omo` listing shows this pass added `.omo/drafts/refactor-whole-project.md` and `.omo/plans/whole-project-refactor.md`; pre-existing `.omo/ulw-loop/**` files are unrelated prior artifacts.
- Captured: docs verification found plan sections, AGENTS references, and artifact line counts.
- Captured: `python scripts/verify_refactor_safety.py` exited 0.
- Captured: `git diff --check` exited 0 with only existing CRLF normalization warnings for tracked markdown.

## Test/QA Exemption
- No production code or runtime data changes are in scope for this pass, so RED-GREEN TDD is not applicable. Verification will be documentation/data-shaped: file existence, hierarchy references, and git status separation.
