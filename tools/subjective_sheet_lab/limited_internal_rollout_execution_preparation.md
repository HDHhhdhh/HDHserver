# Limited Internal Rollout Execution Preparation

Status: EXECUTION_PREPARATION_RECORDED
Updated: 2026-07-05 18:52:00 +09:00
Production default: NO-GO
Provider/Gemini/API budget: 0 by default

## Purpose

This runbook prepares a narrow limited internal rollout. It does not execute the rollout.

The current approved posture is:

- Hidden/internal alpha planning: GO for narrow scope.
- Limited internal rollout preparation: GO as a planning artifact.
- Production default: NO-GO.

This runbook does not authorize browser/app execution, route QA, Gemini/API/provider calls, `/api/submit-test`, `#tsSubmit`, final submit, runtime writes, operating-code edits, recognized/cache overwrite, benchmark truth edits, runtime restore, privileged writer monitoring, or production default enablement.

## Rollout Scope

Allowed planning scope:

- Hidden OCR path only.
- Allowlisted test only: `t_unit_daesu_01_lv3_r1`.
- Round only: `1`.
- Provider disabled by default.
- Review-gated flow only.
- Manual fallback must remain available.
- Production default remains disabled.

Not allowed by this runbook:

- Broad/default student exposure.
- Expanding allowlist.
- Running live provider calls.
- Auto-submitting OCR answers.
- Treating cached/local evidence as fresh live OCR success.
- Treating final-submit pipeline certification as OCR answer correctness.

## Target Roster Policy

No target student roster is approved by this document.

Before a real limited rollout execution, the user must approve:

- Exact student ids or group.
- Exact test id and round.
- Whether browser/app execution is allowed.
- Whether `/api/ocr-test-sheet-review` calls are allowed.
- Whether `/api/submit-test` or final submit is forbidden or explicitly allowed.
- Runtime write policy.
- Rollback or restore policy.

Default recommendation:

- Start with one internal/instructor-controlled target.
- Use provider-disabled/local-only mode first.
- Keep `/api/submit-test` and final submit forbidden for OCR review.
- Stop after upload -> review -> fill-only unless the user separately authorizes final submit.

## Required Operator Preflight

Before any execution room is allowed to run a real limited rollout task, confirm:

- Production default is still NO-GO.
- OCR remains hidden behind the internal alpha path.
- Test id is `t_unit_daesu_01_lv3_r1`.
- Round is `1`.
- Provider/Gemini/API budget is `0`, unless a new user message grants a positive call budget.
- `/api/submit-test` is forbidden unless explicitly authorized in the current task.
- `#tsSubmit` and final submit are forbidden unless explicitly authorized in the current task.
- Runtime JSON, DB, student records, test config, answer keys, benchmark truth, recognized outputs, and provider cache are not writable unless the task explicitly grants that exact write.
- Any browser/app or route execution task names runtime isolation expectations.
- Answer-key, grading, expected, canonical, accepted-answer, and local filesystem path leaks remain forbidden.
- Manual `#tsAnswersText` fallback remains available.

## Execution Approval Template

Use this template if the user wants to execute a limited rollout QA run:

```text
승인: limited internal rollout QA를 실행해라.
대상:
- student(s): <exact ids or group>
- testId: t_unit_daesu_01_lv3_r1
- round: 1

허용:
- browser/app execution: <yes/no>
- /api/ocr-test-sheet-review: <max count or no>
- Gemini/API/provider calls: 0
- /api/submit-test: no
- #tsSubmit/final submit: no
- runtime JSON/DB/student records writes: no
- operating-code edits: no
- production default enable: no

조건:
- provider-disabled/local-only
- hidden ?ocr=1 path only
- upload -> review -> fill-only only
- answer-key/grading/path leak 0
- manual fallback available
- stop on runtime drift, leak, submit call, provider call, route count over budget, or production-default change

결과 기록:
- codex_status/runner_person_04_browser_qa.md
- codex_status/rooms/execute_status.md
```

## Expected Execution Room Boundaries

Execution room must write `RUNNING` at task start and `DONE`, `BLOCKED`, or `FAILED` at exit.

Required status fields:

- Target student id(s).
- URL label, without local filesystem paths.
- Test id and round.
- Server mode.
- Provider/Gemini/API call count.
- `/api/ocr-test-sheet-review` call count.
- legacy `/api/ocr-test-sheet` call count.
- `/api/submit-test` call count.
- `#tsSubmit` or final submit clicked yes/no.
- `#tsAnswersText` line count, if fill-only occurs.
- Review UI opened yes/no.
- Leak scan result.
- Runtime write/hash result, if in scope.
- Cleanup result.
- PASS/BLOCKED/FAIL classification.

## PASS Criteria For A No-Submit Limited Rollout QA

Use this PASS only for no-provider, no-submit QA:

- Hidden path is used.
- Test id and round are allowlisted.
- Image upload is accepted.
- `/api/ocr-test-sheet-review` stays within the approved call count.
- Review UI opens.
- Required review confirmations are completed by the operator, if present.
- `#tsAnswersText` is filled with exactly 20 non-empty editable lines, or the task explicitly expects a safe block.
- `/api/submit-test` count is 0.
- `#tsSubmit` and final submit count is 0.
- Gemini/API/provider count is 0.
- legacy OCR route count is 0.
- Answer-key/grading/path leak count is 0.
- Production default remains NO-GO.

## Safe Block Criteria

Classify as `PASS_SAFE_BLOCK` rather than failure when:

- Review UI opens but policy correctly withholds fill because all items require review, retake, or data check.
- Missing/invalid image, unsupported test, wrong round, ghost sid, oversized image, network failure, or crop failure fails closed.
- Manual `#tsAnswersText` remains editable and no OCR answer is filled.
- Submit, final submit, provider, and leak counts remain 0.

## Failure Criteria

Classify as `FAIL` and stop if any of these occur:

- Gemini/API/provider is called without explicit positive budget.
- `/api/submit-test` is called without explicit authorization.
- `#tsSubmit` or final submit is clicked without explicit authorization.
- Production default changes.
- Answer-key, grading, expected, canonical, accepted-answer, or local path data appears in student-facing output.
- Runtime, DB, student record, test config, answer key, benchmark truth, recognized output, or provider cache is written outside the approved scope.
- OCR output bypasses review-required, retake-required, erased/overwritten, ambiguous, missing, or answer-mode safeguards.

## Rollback Posture

This runbook does not authorize rollback or restore.

If a future authorized run needs rollback:

- Stop OCR-related execution first.
- Preserve evidence and logs without adding leaks.
- Ask for a separate restore approval naming exact files or snapshot.
- Do not rewrite runtime data or DB without explicit restore scope.
- Route back through audit before any further execution.

## Current Production NO-GO Reasons

Production default remains NO-GO because these remain incomplete:

- Fresh live provider success under a newly approved call budget.
- Broad OCR-vs-human handwriting accuracy.
- Exact runtime writer PID/process attribution.
- Clean shared-runtime isolation.
- Broader student, device, and browser coverage.
- Assigned multi-round selector coverage.
- Stale/no-fill and hidden-combination negative states.
- Operator/admin review UX.
- Provider timeout, quota, malformed, partial, cache-miss, and fallback behavior.
- Monitoring owner, rollback owner, stop thresholds, incident handling, and artifact retention operations.

## Safety Counts For This Preparation

- Gemini/API/provider calls: 0
- Browser/app execution: 0
- Route calls: 0
- `/api/submit-test` calls: 0
- `#tsSubmit` or final submit clicks: 0
- Runtime JSON/DB/student-record writes: 0
- Test config, answer-key, benchmark truth, recognized output, or provider cache writes: 0
- Operating-code edits: 0
- Production default changes: 0
