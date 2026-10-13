# OCR Internal QA Operator Checklist Draft

Date: 2026-06-30 KST

Scope: internal/lab operator checklist for OCR QA coordination. This is a markdown-only draft. It does not change routes, frontend code, validators, adapters, preflight scripts, data files, runtime artifacts, provider settings, or production default.

## Current State Summary

- Current canonical baseline: Phase 2D cached recognized/review-payload flow.
- Phase 2E limited live QA has passed.
- Broader Phase 2E internal QA is allowed only with explicit process-local provider-call authorization and a declared call budget.
- Production default remains `NO-GO`.
- OCR must remain opt-in and allowlist-gated.
- OCR review must not trigger final submission.
- Recognized-only OCR output remains review-gated; it is not treated as automatically final.

## Before QA

- [ ] Confirm this session owns only documentation or the explicitly approved QA task.
- [ ] Confirm no operating code files will be edited.
- [ ] Confirm no runtime student/progress/log/test data will be edited.
- [ ] Confirm production/default behavior remains disabled.
- [ ] Confirm OCR is being tested only in the internal/lab flow.
- [ ] Confirm the provider-call budget is declared before any live-provider run.
- [ ] Confirm provider-call authorization is process-local, not global.
- [ ] Confirm provider calls are `0` for cache-hit, provider-disabled, fallback, and fixture-only cases.
- [ ] Confirm cache-first behavior is tested before any live-provider case.
- [ ] Confirm no secret values are printed, copied, logged, or screenshot.
- [ ] Confirm student-facing evidence will not contain local filesystem paths.
- [ ] Confirm student-facing evidence will not contain internal answer values or scoring metadata.

## During QA

- [ ] Use only the allowlisted internal OCR review flow.
- [ ] Upload the approved lab image only when QA requires an image.
- [ ] Verify cache hit or cache miss before interpreting provider behavior.
- [ ] Count provider calls per case and total provider calls for the run.
- [ ] Stop if provider calls exceed the declared budget.
- [ ] Stop if final submission is triggered.
- [ ] Do not click the final submit button.
- [ ] Do not edit answer configuration, student records, database files, or runtime logs.
- [ ] Do not create recognized cache artifacts unless the specific QA task authorizes cache writes.
- [ ] Keep all recognized-only results in review-required mode unless a separate approved policy says otherwise.
- [ ] Confirm ambiguous, erased, overwritten, missing, or malformed answers stay review-gated.
- [ ] Confirm choice-number answers accept only simple option numbers.
- [ ] Confirm answer-value items contain only final answers.
- [ ] Confirm the final filled answer text has exactly 20 non-empty lines for the current 20-question flow.

## Network And UI Safety Checks

- [ ] OCR review route calls occur only in the OCR review flow.
- [ ] Final submit route call count remains `0`.
- [ ] Legacy OCR endpoint call count remains `0`.
- [ ] Final submit button click count remains `0`.
- [ ] No automatic submit occurs after OCR review, fallback, or fill.
- [ ] The review UI remains editable before final submission.
- [ ] The student-facing payload contains no local filesystem path text.
- [ ] The student-facing payload contains no internal scoring or answer data.
- [ ] Provider errors fail closed to review/manual handling.
- [ ] Quota or rate-limit failures do not retry beyond the declared budget.

## Evidence To Save

- [ ] QA case id or short run label.
- [ ] Date/time and operator.
- [ ] Phase under test.
- [ ] Provider-call budget.
- [ ] Actual provider-call count.
- [ ] Cache hit/miss outcome.
- [ ] Route result summary.
- [ ] Review status counts.
- [ ] Final answer text line count.
- [ ] Confirmation that final submit route call count was `0`.
- [ ] Confirmation that final submit button click count was `0`.
- [ ] Confirmation that production/default behavior stayed disabled.

Evidence notes should use short labels and summaries. Do not paste secrets, local filesystem paths, raw provider credentials, internal answer values, or scoring metadata into student-facing notes.

## Stop Conditions

Stop QA immediately if any of these occur:

- A live provider call occurs without explicit process-local authorization.
- Provider-call count exceeds the declared budget.
- Final submission is triggered.
- The final submit button is clicked.
- A student-facing response exposes a local filesystem path.
- A student-facing response exposes internal answer or scoring data.
- Production/default behavior becomes enabled.
- A runtime artifact is created outside the approved QA scope.

## After QA

- [ ] Leave global/default provider flags disabled or unset.
- [ ] Do not clean runtime artifacts unless cleanup is explicitly assigned.
- [ ] Record whether cache writes occurred.
- [ ] Record whether provider calls occurred.
- [ ] Record any missing, ambiguous, erased, overwritten, malformed, or path-leak cases.
- [ ] Record final GO/NO-GO outcome for the QA scope only.
- [ ] Keep production default as `NO-GO`.

## Decision Template

| Decision item | Status | Notes |
| --- | --- | --- |
| Phase 2D baseline intact | GO/NO-GO |  |
| Phase 2E internal QA scope approved | GO/NO-GO |  |
| Live provider calls authorized for this process | GO/NO-GO |  |
| Provider-call budget respected | GO/NO-GO |  |
| Final submit route call count stayed 0 | GO/NO-GO |  |
| Final submit button click count stayed 0 | GO/NO-GO |  |
| Student-facing path/internal-data leak absent | GO/NO-GO |  |
| Production default remains NO-GO | GO/NO-GO |  |

## Confirmation For This Checklist

- no code changes
- no validator changes
- no adapter changes
- no preflight script changes
- no Gemini/API call
- no final submit call
- no submit button click
- no environment changes
- no production default changes
- no operating data/config changes
- no internal answer-value disclosure
- no filesystem path disclosure
