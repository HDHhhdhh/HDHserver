# Limited Rollout Operator Checklist

Status: docs-only planning artifact
Updated: 2026-07-05 16:49:08 +09:00
Production default: NO-GO

This checklist is for hidden/internal alpha and limited internal rollout planning only. It is not production approval, not approval to run browser/app QA, not approval to call routes, not approval to call Gemini/API/providers, not approval to submit final answers, and not approval to change runtime data, benchmark truth, recognized outputs, provider cache, operating code, or production defaults.

## Source Evidence Boundary

Use this checklist only with the evidence already recorded in codex_status/docs.md and tools/subjective_sheet_lab/post_qa_production_readiness_gap_matrix.md.

Current supporting evidence is narrow:

- PASS_HIDDEN_INTERNAL_ALPHA: one hidden internal alpha route/UI flow reached review UI confirmation and filled 20 editable answer lines without submit, provider, or final-submit claims.
- PASS_UPLOAD_REVIEW_FILL_ONLY_VERIFIED: one provider-disabled/local-only assigned-card upload/review/fill-only bridge succeeded for a cached fillable payload.
- Batch 1-4 no-provider evidence: selected feature-off, fill-only, fail-closed, and review UI interaction edge evidence.
- PASS_CONTROLLED_RUNTIME_LOCK_UPLOAD_REVIEW_FILL_ONLY_NO_PROVIDER_AUDITED: one controlled-runtime no-provider bridge rerun completed with protected runtime hash drift 0.
- PASS_CACHE_HIT_NO_PROVIDER_CALL_AUDITED: one cache-hit/no-provider replay completed with provider calls 0 and documented OCR-vs-human metrics; it is not fresh provider success.
- PASS_STATIC_NEGATIVE_STATE_VERIFIER_NO_RUNTIME_WRITE_AUDITED: static/file inventory evidence for route, payload, UI, provider-gate, no-submit, leak, review-required, choice, and stale contracts.
- PASS_WITH_CAVEATS_BATCH_6_COPIED_SANDBOX_NEGATIVE_STATE_QA_AUDITED: selected copied-sandbox negative-state evidence remains useful but caveated, not clean PASS.

Do not treat any item above as production readiness, broad live OCR accuracy, clean shared-runtime isolation, exact writer attribution, unrestricted final-submit correctness, or production default approval.

## Hidden/Internal Alpha Scope

- OCR remains hidden/internal and available only through the hidden internal alpha path.
- The flow stays review-gated. Every OCR result must be reviewed by an operator before any answer text is applied.
- Provider calls stay disabled by default. Existing cache/local evidence may be discussed only as no-provider evidence.
- No automatic submit is allowed. This checklist does not permit calling /api/submit-test or activating final submit controls.
- Operators must keep answer-key, grading, and local-path data out of prompts, reports intended for students, student-facing JSON, screenshots intended for students, and recognized outputs.
- The evidence supports continued internal planning and checklist preparation only.

## Limited Internal Rollout Scope

Limited rollout planning may discuss a small internal group only if all of these remain true:

- The rollout is internal or instructor/operator controlled, not default student-facing production.
- Scope stays constrained to the currently evidenced test/round and known internal QA scenario unless a later task explicitly expands coverage.
- Provider remains disabled unless a future user message grants process-local provider authorization with a declared positive call budget.
- Every result is operator-reviewed, and uncertain, missing, erased, overwritten, multiple, ambiguous, or low-confidence answers remain review-gated or retake-gated.
- No final submit is performed as part of OCR review unless a future user message explicitly authorizes final submit and states the runtime-write and rollback policy.
- Production default remains NO-GO.

## Operator Pre-Checks

Before any future authorized internal run, the operator or coordinator must confirm:

- Current task authorization names the exact room, target scope, write scope, and stop conditions.
- Provider budget is 0, unless the current user message explicitly provides process-local provider authorization and a positive declared budget.
- /api/submit-test calls are not authorized for OCR review work.
- #tsSubmit or any final submit control is not authorized for OCR review work.
- Production default remains disabled.
- Runtime JSON, DB, student records, test config, answer keys, benchmark truth, recognized outputs, and provider cache are not writable unless the task explicitly grants that exact write.
- Browser/app or route QA is not started unless the task explicitly authorizes no-provider/no-submit execution and states runtime isolation expectations.
- Any rollback or restore action has separate explicit authorization and a named scope.
- New reports use repo-relative references only and do not add local absolute filesystem paths.

## No-Submit/No-Provider Default Rules

- Default provider/Gemini/API call count is 0.
- Default /api/submit-test call count is 0.
- Default final submit click count is 0.
- Default browser/app and route execution count is 0 for docs_room work.
- Default production status is NO-GO.
- If a task requires provider calls, submit/final submit, runtime restore, operating-code edits, benchmark edits, recognized/cache overwrite, or production default enablement, stop and record NEEDS_USER_APPROVAL in the room status.

## Approval Gates

| Gate | Required approval before work continues |
| --- | --- |
| Provider/Gemini/API calls | Explicit process-local provider authorization, declared positive call budget, target scope, overwrite/cache policy, and leak guards. |
| Submit or final submit | Explicit final-submit authorization plus runtime-write and rollback policy. |
| Browser/app or route QA | Explicit no-provider/no-submit execution authorization plus stable isolated runtime or controlled runtime lock when runtime hashes matter. |
| Runtime restore or rollback | Explicit restore authorization and named snapshot or rollback scope. |
| Operating-code edits | Explicit protected-file edit authorization and a separate verification plan. |
| Benchmark truth or answer-key edits | Explicit benchmark-edit authorization; never infer OCR results from grading data. |
| Recognized output or provider cache overwrite | Explicit overwrite policy naming the exact artifact scope. |
| Writer attribution tooling | Explicit approval for process/file monitoring, filesystem watcher, handle watcher, ETW/Procmon capture, or equivalent writer-identity diagnostics. |
| Production default | Separate production-readiness approval after blockers close; current status remains NO-GO. |

## Rollback And Stop Conditions

Stop the rollout or planned run immediately if any of these occur:

- Any OCR review path calls /api/submit-test without explicit approval.
- Any OCR review path activates final submit controls without explicit approval.
- Any provider call is needed when provider budget is 0.
- Any provider path would exceed the declared call budget.
- Any answer-key, grading, or local-path data would reach student-facing output, provider prompts, recognized outputs, or status reports intended for students.
- Any recognized-only, erased, overwritten, multiple, missing, ambiguous, or answer-mode-mismatch item would become unsafe auto-grade.
- Any runtime JSON, DB, student record, test config, benchmark truth, recognized output, provider cache, or operating-code write is needed outside the allowed task scope.
- Runtime hash drift appears in a run that requires clean runtime isolation.
- The operator cannot confirm review-required, data-check, retake, warning, or unresolved-case handling.
- Production default enablement becomes necessary.

Rollback posture for future authorized runs:

- Freeze the OCR rollout path and return to lab-only planning.
- Preserve the evidence packet and status notes without adding answer-key, grading, or path leaks.
- Do not restore snapshots or rewrite runtime data until a separate user approval names the restore scope.
- Route the next decision back to coordinator/audit before execute-room work resumes.

## Remaining Blockers Before Production Default

Production default remains NO-GO until all of these are closed with separate evidence:

- Fresh live provider success remains unproven and unauthorized.
- Broad independent OCR-vs-human handwriting accuracy remains insufficient.
- Exact writer/process/PID/HTTP route attribution remains unproven.
- Clean shared-runtime isolation remains unproven.
- Batch 6 remains PASS_WITH_CAVEATS, not clean PASS.
- Broader student, device, and browser coverage remains incomplete.
- Actual assigned multi-round selector coverage remains caveated.
- Stale, no-fill, and broader hidden-combination negative states remain incomplete.
- Operator/admin review UX for review-required, data-check, retake, warning, and unresolved cases remains incomplete.
- Live provider timeout, quota, malformed, partial, cache-miss, and fallback behavior remains unproven.
- Monitoring ownership, rollback ownership, stop thresholds, incident handling, and artifact retention remain incomplete.

## Operator Decision Table

| Decision | Current status | Operator action |
| --- | --- | --- |
| Hidden/internal alpha planning | GO as planning only | Maintain hidden scope, no provider, no submit, review-gated operation. |
| Limited internal rollout planning | GO as checklist/gate design only | Use this checklist to define gates and stop conditions; do not execute without a future authorized task. |
| No-provider local QA execution | Not authorized by this docs task | Require a future task that explicitly permits browser/app or route execution and runtime isolation policy. |
| Provider-live OCR QA | NO-GO until authorized | Require process-local provider authorization and declared budget. |
| Final submit path | NO-GO for this checklist | Require explicit final-submit authorization and rollback policy. |
| Production default | NO-GO | Require separate production-readiness approval after blockers close. |

## Safety Counts For This Checklist Run

- Gemini/API/provider calls: 0
- Browser/app execution: 0
- Route calls: 0
- /api/submit-test calls: 0
- #tsSubmit or final submit clicks: 0
- Runtime JSON/DB/student-record writes: 0
- Test config, answer-key, benchmark truth, recognized output, or provider cache writes: 0
- Operating-code edits: 0
- Production default changes: 0
