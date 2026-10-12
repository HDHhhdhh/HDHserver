# OCR September Allowlist Production Roadmap

Generated: 2026-07-10 03:30:00 +09:00
Classification: PLANNING_ONLY_ALLOWLIST_PRODUCTION_ROADMAP

## A. Goal Definition

The September target is not unrestricted OCR production. The target is allowlist-based OCR production for internal academy use:

- OCR can be available from the normal student page by September.
- Only allowlisted tests and rounds are supported.
- OCR is an answer-entry assistant, not an autonomous grader.
- The student or teacher must review OCR output before answers are filled.
- Risky answers must not be automatically finalized.
- `review_required`, `retake_required`, and manual input fallback remain normal operating paths.
- A feature flag, allowlist, and off switch are required.
- All tests, all handwriting, unattended automatic grading, and global production default enablement are outside the September goal.

Current narrow baseline:

- Hidden internal alpha is GO for narrow scope.
- Current allowed test is `t_unit_daesu_01_lv3_r1` / round `1`.
- Current hidden entry path is `?ocr=1`.
- Upload -> `/api/ocr-test-sheet-review` -> review UI -> 20 items -> `#tsAnswersText` fill/block has been observed.
- No-provider/no-submit QA evidence exists.
- `/api/submit-test` automatic call count remains 0.
- `#tsSubmit` / final submit automatic click count remains 0.
- Production default remains NO-GO.
- Live OCR accuracy still requires separate approval and a declared provider budget.

## B. July Milestone: Teacher-Supervised Limited Use

Goal: prove that a teacher can supervise a very small number of student OCR uses without relying on production default.

Scope:

- Start with one named student, then expand to four or five students only after the first run is reviewed.
- Keep the test scope at one stabilized test/round first: `t_unit_daesu_01_lv3_r1` / round `1`.
- Use the student page hidden OCR path.
- Keep provider budget at 0 unless a separate live OCR accuracy run is explicitly approved.
- Keep `/api/submit-test` and `#tsSubmit` forbidden unless a separate final-submit certification task is approved.

Required July evidence:

- Teacher opens the student page and confirms the intended test/round.
- Teacher uploads the answer sheet.
- OCR review route returns a student-safe review payload.
- Review UI shows 20 items or safely blocks with clear review/retake state.
- If fill is allowed, `#tsAnswersText` has exactly 20 non-empty editable lines.
- If fill is blocked, manual input fallback remains available.
- Answer-key, grading, and local filesystem path leaks remain 0.
- Any runtime/data/config write outside explicit approval stops the run.

July stop condition:

- Any provider call, submit call, final-submit click, production default change, answer-key/path leak, wrong test/round, or unexpected runtime write stops the run and keeps OCR as hidden/internal only.

## C. August Milestone: Internal Exam-Use Expansion

Goal: prepare OCR for actual internal exam season by broadening only the allowlist planning and supervised QA surface.

Scope:

- Expand from four or five students toward 10-30 supervised students only after July evidence is stable.
- Identify five to ten major test/round candidates for allowlist consideration.
- Do not add tests to the live allowlist until their answer-mode table, review policy, and QA evidence are ready.

August deliverables:

- Candidate allowlist table with test id, round, answer modes, image/crop readiness, review risk, and owner.
- Fixed answer-sheet writing rules:
  - choice answers use choice number only.
  - answer-value questions use final answer only.
  - erased, crossed-out, overwritten, multiple, or unclear answers are rewritten or handled as review/retake.
- Fixed answer-mode table creation procedure for each candidate test.
- `review_required` and `retake_required` handling guide for teacher-supervised use.
- Minimum mobile/browser QA matrix:
  - one desktop browser path.
  - one mobile or tablet viewport path.
  - feature-off/default-page regression.
  - no-submit hidden OCR path.
- Monitoring and rollback owner for each supervised run.

August NO-GO:

- Global production default.
- Automatic grading claims.
- Any unreviewed OCR answer submission.
- Allowlist expansion without candidate readiness evidence.
- Provider calls without explicit budget.

## D. September Milestone: Allowlist Production Limited Open

Goal: allow OCR to be visible from the regular student page for allowlisted tests/rounds only, while keeping off switch and manual fallback.

September production shape:

- OCR controls may be available without the hidden query only if the feature flag, allowlist, and off switch are explicitly approved.
- Non-allowlisted tests must hide or disable OCR with a safe message.
- Allowlisted tests must still require review before fill.
- Risky or unresolved items must block fill or require manual confirmation.
- Final submit remains the existing submit path and must not be called by OCR review automatically.
- Teachers must be able to turn OCR off or instruct students to use manual input.

Minimum September gates:

- Feature flag/off switch verified.
- Allowlist test/round mapping verified.
- Student-facing payload leak scan clean.
- Answer-mode mapping verified for each allowlisted test.
- No automatic `/api/submit-test` from OCR review.
- No automatic `#tsSubmit` / final submit click.
- Manual input fallback verified.
- Provider/API policy documented and enforced.
- Monitoring checklist and stop thresholds documented.

Production default status:

- Production default remains NO-GO until the above September gates are explicitly approved.
- The September target is conditional allowlist production, not global OCR enablement.

## E. Completion Criteria

Allowlist production readiness can be considered only when all are true:

- Student page real-use flow is stable for the selected allowlist tests.
- Test allowlist addition procedure is stable and repeatable.
- Answer-mode table creation is documented and checked for each candidate test.
- Submit/final-submit safety criteria are explicit.
- Answer-key, grading, and local-path leak checks are clean.
- Provider/API call policy is explicit.
- OCR can be turned off quickly.
- Manual input fallback is available.
- `review_required` and `retake_required` handling is understood by teachers.
- Monitoring and rollback ownership are assigned.

## F. Excluded Scope

These are not part of the September target:

- All tests and all rounds.
- Multi-student unrestricted rollout.
- Unattended automatic grading.
- Inferring final answers from answer keys.
- Treating live OCR cache accuracy as broad production accuracy.
- Changing answer keys or `tests-config.json`.
- Modifying production default without a separate approval.
- Replacing manual review or manual input fallback.

## G. Next Orchestration

Immediate next safe work:

1. Audit this roadmap read-only.
2. Prepare teacher-supervised checklist and allowlist expansion plan as documents.
3. Keep execute room stopped unless a one-student supervised run is explicitly approved.

Approval required before execution:

- actual student rollout start.
- live Gemini/API/provider OCR accuracy QA.
- `/api/submit-test`.
- `#tsSubmit` / final submit.
- production default enablement.
- other-test allowlist changes.
- runtime/DB/student-record writes.
- operating-code edits.
- benchmark truth or recognized/cache overwrite.
