# Hidden OCR Pre-integration GO/NO-GO Checklist

Date: 2026-07-02 KST

Status: generated/confirmed from the current direct user instruction. This checklist supersedes any queued `docs_next.md` task for this scope.

## Current Decision

| Decision point | Status | Reason |
| --- | --- | --- |
| Checklist/documentation readiness | GO | Current Phase 2D/2E and Batch 1-4 evidence is consolidated enough to define pre-integration gates. |
| No-provider hidden `?ocr=1` route/UI minimal candidate | PASS for candidate validation only | Latest reviewed evidence supports a narrow no-provider hidden-route/UI candidate claim with provider, submit, final submit, and production-default counts at 0. |
| Provider-disabled/local-only lab QA evidence | GO for narrow lab scope | Batch 1-4 evidence verifies selected browser/route/review UI paths with provider, submit, final submit, leak, and runtime-write counts at 0. |
| Phase 2D cached/review-payload baseline | GO as internal lab baseline | Existing docs treat Phase 2D cached recognized/review-payload behavior as the authoritative internal/lab baseline. |
| Phase 2E live provider integration | NO-GO until explicit provider authorization | Live Gemini/API/provider calls require process-local authorization, declared call budget, local/lab confirmation, and cache/fail-closed gates. |
| Hidden OCR operating-code integration | NO-GO until blockers below are closed | Current evidence is not enough to treat hidden integration as clean or production-ready. |
| Production default | NO-GO | Production default must remain disabled until a separate production-readiness decision closes all remaining blockers. |

## Latest Minimal Candidate Verification

Classification: `PASS_NO_PROVIDER_HIDDEN_OCR_ROUTE_UI_CANDIDATE_ONLY`.

The latest reviewed Phase 2D/2E evidence supports only this narrow claim: the no-provider hidden `?ocr=1` route/UI minimal candidate is a PASS for candidate validation and documentation planning.

This does not approve operating-code integration. It does not prove live OCR accuracy, final submit success, production readiness, or production default GO.

Verified boundary for this candidate:

- Hidden OCR remains behind explicit `?ocr=1` / internal flag assumptions.
- Phase 2D cached/review-payload behavior remains the internal/lab baseline.
- Phase 2E live provider behavior remains disabled/default-closed unless separately authorized.
- OCR review is review/fill-only and must not grade or submit.
- Gemini/API/provider calls: 0.
- `/api/submit-test` calls: 0.
- `#tsSubmit` clicks and final submit: 0.
- Production default enablement: 0.
- Production default remains `NO-GO`.

Candidate limit:

- PASS is limited to no-provider hidden route/UI candidate verification.
- Protected-file edit authorization is still required before any actual operating-code integration.
- Remaining blockers below still apply.

## Evidence Sources Read

- `codex_status/docs.md`
- `codex_status/audit_person_04.md`
- `codex_status/runner_person_04_browser_qa.md`
- `codex_status/rooms/*.md`
- `tools/subjective_sheet_lab/non_provider_hidden_ocr_browser_qa_summary.md`
- `tools/subjective_sheet_lab/post_qa_production_readiness_gap_matrix.md`

## Closed Evidence

- [x] Batch 1 `BROADER_NON_PROVIDER_BROWSER_QA_BATCH_1_PASS`: provider-disabled/local-only browser QA passed desktop repeatability, mobile viewport fillable run, feature-off default page, and warning/review_required block path for one controlled target.
- [x] Batch 2 `PASS_FAIL_CLOSED_BATCH2`: missing image, invalid image type, and route/network failure failed closed with `#tsAnswersText` empty/editable and no submit/provider/final-submit activity.
- [x] Batch 3 `PASS_FAIL_CLOSED_BATCH3`: feature-disabled/default route, blocked testId, wrong round, ghost sid, and oversized image failed closed in provider-disabled/local-only route/browser QA.
- [x] Batch 4 `PASS_REVIEW_UI_EDGE_BATCH4_WITH_ROUND_SELECT_CAVEAT`: review UI edge behavior passed for manual review_required confirmation, choice-number validation, valid fill, stale OCR-filled clearing, test-change clearing, and synthetic round mismatch clearing.
- [x] No-submit evidence is preserved across recorded QA: `/api/submit-test` 0, `#tsSubmit` 0, final submit 0.
- [x] Provider budget stayed 0 in the recorded non-provider QA: Gemini/API/provider calls 0.
- [x] Production default stayed disabled: production default enablement 0 and status `NO-GO`.
- [x] Recorded selected-path leak scans are clean: forbidden answer-key/grading/path hits 0 in the PASS evidence.
- [x] Runtime JSON/DB/student-record writes observed in the PASS evidence stayed 0.
- [x] Phase 2E provider posture is documented as default-closed/local-only unless explicitly authorized.
- [x] Phase 2D cached/review-payload path remains the current internal/lab baseline, not a production default.

## Remaining Blockers

- [ ] Live OCR handwriting accuracy is not proven against independent human transcription.
- [ ] Final submit and grading integration are not proven.
- [ ] Production readiness is not proven.
- [ ] Actual assigned multi-round selector coverage remains open; Batch 4 only verified synthetic round mismatch clearing.
- [ ] Hidden negative-state combinations remain incomplete: provider-disabled cache miss, malformed payload, crop failure, stale payload, no-fill states, and broader combinations still need executable evidence after final protected diff settles.
- [ ] Live provider timeout, quota, malformed response, cache miss, fallback, and fail-closed behavior remain untested without explicit provider authorization.
- [ ] Broader browser/device/student coverage remains narrow because the current PASS evidence centers on one controlled target.
- [ ] Repeatable leak coverage is still needed across payload, DOM, network, metadata, failure, report, and log surfaces.
- [ ] Current protected-file integration remains too broad unless `/api/submit-test` / progress-status behavior is explicitly separated, approved, and regression-tested.
- [ ] Runtime write safety still needs broader bootstrap, failure, retry, stale, and multi-user evidence.
- [ ] Operator/admin review workflow, monitoring, stop conditions, artifact retention, rollback, and ownership remain incomplete for production.

## Authorization Needed

Before hidden OCR operating-code integration:

- [ ] Explicit protected-file edit authorization for the exact files to be changed.
- [ ] Explicit target state: Phase 2D cached/local route integration, Phase 2E live provider integration, or a staged combination.
- [ ] Explicit no-submit constraint unless final-submit testing is separately authorized.
- [ ] Explicit no-runtime-write constraint unless runtime writes are separately scoped and approved.
- [ ] Required validator/verifier list approved before code changes.
- [ ] Rollback target and file ownership confirmed.

Before any Gemini/API/provider call:

- [ ] Explicit user authorization for provider calls.
- [ ] Declared process-local provider call budget.
- [ ] Local/lab-only environment confirmation.
- [ ] API key availability confirmed without printing or exposing it.
- [ ] Cache-first behavior confirmed.
- [ ] Provider prompt/input confirmed to exclude answer keys, canonical/accepted answers, grading fields, and student-facing filesystem paths.
- [ ] Provider output schema validator ready.
- [ ] Fail-closed fallback for timeout, quota, malformed JSON, empty output, forbidden fields, and path leaks ready.

Before browser/app QA:

- [ ] Browser/app execution explicitly authorized for the target run.
- [ ] `/api/submit-test`, `#tsSubmit`, and final submit remain blocked unless separately authorized.
- [ ] Route/provider/submit/runtime counters are instrumented.
- [ ] Local-only target/student/test/round is declared.
- [ ] Runtime JSON/DB/student-record hash checks are planned before and after.

## Next Approved Integration Candidate

Recommended next candidate is not production integration. It is a narrow protected-file code-room candidate only after explicit edit authorization:

1. Keep Phase 2D cached/review-payload behavior as the default internal/lab baseline.
2. Keep Phase 2E live provider disabled by default and fail-closed without explicit provider authorization.
3. Split or harden hidden OCR review-route work so it does not depend on `/api/submit-test` or progress-status changes.
4. Preserve review-only behavior: OCR route creates a review payload only, never final-submits and never grades.
5. On cache miss, malformed payload, provider disabled, provider error, or forbidden-field/path leak, fail closed to review_required/no-fill or safe error rather than returning fillable mock answers.
6. Re-run the hidden negative-state matrix and Batch 1-4 relevant no-submit browser/route checks after any protected-file change.

Candidate status: conditional GO for planning only; NO-GO for actual integration until edit authorization and blocker-specific verification are in place.

## Required Pre-integration Checklist

- [ ] Production default is still `NO-GO`.
- [ ] No Gemini/API/provider call is planned unless separately authorized with a declared budget.
- [ ] `/api/submit-test`, `#tsSubmit`, and final submit are blocked for OCR review flow.
- [ ] Phase 2D cached/review-payload path is verified.
- [ ] Phase 2E disabled/default-closed path is verified.
- [ ] Feature-off/default page path is verified.
- [ ] Warning/review_required path blocks unsafe fill.
- [ ] Fillable cached payload path fills exactly 20 editable non-empty lines in local-only QA.
- [ ] Missing image fails closed.
- [ ] Invalid image type fails closed.
- [ ] Route/network failure fails closed.
- [ ] Feature-disabled/default route fails closed.
- [ ] Blocked testId fails closed.
- [ ] Wrong round fails closed.
- [ ] Ghost sid fails closed.
- [ ] Oversized image fails closed.
- [ ] Review UI manual confirmation works without submit/provider calls.
- [ ] Choice-number invalid values block fill.
- [ ] Choice-number valid values fill only after validation.
- [ ] Stale OCR-filled text clears on context mismatch.
- [ ] Test-change clearing works.
- [ ] Real assigned multi-round selector coverage is either verified or explicitly left as a blocking caveat.
- [ ] Cache miss fallback is executable-verified.
- [ ] Malformed payload fallback is executable-verified.
- [ ] Crop failure fallback is executable-verified.
- [ ] No-fill state is executable-verified.
- [ ] Forbidden answer-key/grading/path leak scan is clean across response, DOM, network, metadata, failure, report, and log surfaces.
- [ ] Runtime JSON/DB/student-record writes remain 0 for review-only OCR QA.
- [ ] Verifier outputs are documented in lab reports.
- [ ] Rollback plan is documented.

## Stop Conditions

Stop the integration or QA run immediately if any condition occurs:

- Gemini/API/provider call occurs without explicit provider authorization and declared call budget.
- `/api/submit-test` is called from OCR review flow without explicit final-submit authorization.
- `#tsSubmit` is clicked or final submit occurs in a no-submit QA run.
- Production default is enabled.
- OCR route exposes answer keys, accepted/canonical answers, grading fields, or local filesystem paths.
- Cache miss or provider-disabled path returns fillable mock answers instead of safe fail-closed/review_required behavior.
- Any uncertain, warning, missing, erased, overwritten, ambiguous, or malformed output becomes safe_auto_grade without review.
- Runtime JSON/DB/student-record writes occur in a review-only/no-write QA run.
- Response/DOM/network/log leak scan finds forbidden answer-key/grading/path tokens.
- Actual assigned test/round context is mismatched and answers remain filled instead of clearing.
- Protected-file diff includes unapproved `/api/submit-test`, progress-status, production-default, runtime-write, or provider-call changes.
- Required counters are missing, making provider/submit/final-submit/runtime counts unverifiable.

## Final GO/NO-GO Template

| Gate | Current status |
| --- | --- |
| Closed local evidence documented | GO |
| Batch 1-4 provider-disabled/local-only QA evidence | GO for narrow lab scope |
| Checklist ready | GO |
| Next integration planning | Conditional GO with explicit edit authorization |
| Hidden OCR operating-code integration | NO-GO until blockers and authorizations are closed |
| Live provider calls | NO-GO until explicit provider-call authorization and budget |
| Final submit/grading certification | NO-GO until separately authorized and tested |
| Production readiness | NO-GO |
| Production default | NO-GO |

## Docs-Room Safety Statement

- Gemini/API/provider calls by docs room: 0.
- Browser/app execution by docs room: 0.
- Route calls by docs room: 0.
- `/api/submit-test` calls by docs room: 0.
- `#tsSubmit` clicks by docs room: 0.
- Final submit by docs room: 0.
- Operating-code edits by docs room: 0.
- Runtime JSON/DB/student-record writes by docs room: 0.
- Production default remains `NO-GO`.
