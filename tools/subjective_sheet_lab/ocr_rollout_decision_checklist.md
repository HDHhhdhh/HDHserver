# OCR Rollout Decision Checklist

Date: 2026-06-30 KST

Scope: decision checklist for moving OCR answer-sheet review from internal/lab QA toward limited student-facing rollout. This is a report-only artifact and does not authorize production default enablement.

## 1. Current Status

- Current authoritative baseline: Phase 2D cached recognized/review-payload route-backed baseline.
- Phase 2E live QA status: limited/internal route-level live QA passed.
- Phase 2E broader internal lab QA: still running / not yet complete in this checklist.
- Production default: NO-GO.
- OCR visibility remains hidden behind `?ocr=1`.
- OCR eligibility remains limited to `t_unit_daesu_01_lv3_r1` / round `1`.
- Final submission remains the existing `/api/submit-test` path after student confirmation.

## 2. Required Technical Conditions

All items below must be proven before moving beyond internal/lab QA.

- [ ] OCR review flow makes no automatic `/api/submit-test` call.
- [ ] OCR review flow does not click `#tsSubmit`.
- [ ] Student-facing route response contains no answer-key fields, including `expected`, `canonical_answer`, or `accepted_answers`.
- [ ] Student-facing route response contains no grading fields or labels, including `correct`, `incorrect`, `score`, `wrong`, or `pct`.
- [ ] Student-facing route response contains no filesystem paths, including `C:\`, `C:/`, `server-ocr`, crop folders, contact-sheet folders, or cache folders.
- [ ] Successful review/fill produces exactly 20 non-empty newline-separated lines in `#tsAnswersText`.
- [ ] `choice_number` validation blocks non-option values such as `x=2`, `3sqrt(2)`, `1,3`, and option expressions.
- [ ] Erased, crossed-out, overwritten, multiple-answer, or unclear-final-answer warnings block `safe_auto_grade`.
- [ ] Recognized-only OCR/cache/provider output remains `review_required`; it is not inferred into `safe_auto_grade`.
- [ ] Production/default environment remains disabled unless a later explicit production rollout decision changes it.

## 3. Required Benchmark Conditions

These benchmark conditions must be met before limited student-facing rollout.

- [ ] Multiple independent normal-handwriting cases have been evaluated, not only stress/low-legibility cases.
- [ ] OCR-vs-human accuracy target is met on high-confidence human transcription rows.
  - Suggested limited-rollout gate: at least `90%` OCR-vs-human accuracy across at least `3` independent normal-handwriting cases.
  - Suggested production-default gate: a separately approved larger benchmark target, with production still NO-GO until that evidence exists.
- [ ] `wrong_safe_auto_grade = 0` across all included benchmark cases.
- [ ] Missing counts are documented per case.
- [ ] Ambiguous / low-confidence human labels are documented per case and excluded from strict high-confidence accuracy denominators when appropriate.
- [ ] person_03 q016/q017 lesson is reflected: erased/overwritten/crossed-out handwriting must remain review-gated or retake-gated, not auto-accepted.
- [ ] person_04 or later independent cases are added before treating current evidence as rollout-ready.
- [ ] Normal-handwriting and stress-handwriting results are reported separately.

## 4. Required QA Conditions

Each case below needs explicit evidence before limited student-facing rollout.

- [ ] Cache hit returns a student-safe 20-item review payload with zero Gemini/API calls.
- [ ] Cache miss falls back safely when provider calls are disabled.
- [ ] Provider disabled path makes zero Gemini/API calls and returns a review/manual fallback.
- [ ] Provider enabled path uses explicit process-local authorization and a declared call budget.
- [ ] Quota / `429` provider failure falls back safely without retry loops beyond the call budget.
- [ ] Invalid provider JSON is rejected or fails closed without exposing raw provider output to the student.
- [ ] Missing question output does not shift answer lines; it either falls back safely or returns a 20-item payload with the missing item review-required.
- [ ] Erased/overwritten answer case routes to `review_required` or `retake_required`.
- [ ] Answer-mode mismatch case, such as a formula in a `choice_number` row, is blocked before filling `#tsAnswersText`.
- [ ] Browser/manual QA confirms the OCR review path still does not submit final answers.

## 5. Rollout Stages

1. Lab only
   - Route/client/verifier work stays internal.
   - Provider calls are disabled unless explicitly authorized for a bounded lab run.
   - Production default remains NO-GO.

2. Instructor-only hidden flag
   - OCR remains behind `?ocr=1`.
   - Only trained instructor/operator accounts use the flow.
   - The operator reviews every OCR result before fill.

3. One test / one student
   - Scope remains `t_unit_daesu_01_lv3_r1` / round `1`.
   - One known QA student or one approved real student is used.
   - No automatic final submit is allowed.

4. Small controlled student group
   - Limited to the allowlisted test/round.
   - Review/retake metrics, missing counts, and user correction counts are collected.
   - Any wrong safe auto-grade or path/key leak stops rollout.

5. Production default
   - Current status: NO-GO.
   - Requires a separate explicit decision, larger benchmark evidence, completed broader QA, and rollback/monitoring ownership.

## 6. GO/NO-GO Table

| Stage | Current decision | Required evidence before GO |
| --- | --- | --- |
| Internal lab QA | GO | Phase 2D verifiers pass; Phase 2E limited route-level evidence remains bounded; no submit/key/path leaks. |
| Instructor hidden QA | CONDITIONAL GO | Broader internal lab QA completes; hidden `?ocr=1` flow is verified in browser; all results remain review-gated. |
| Limited student QA | NO-GO today | Multiple normal-handwriting benchmarks meet the OCR-vs-human target; `wrong_safe_auto_grade = 0`; person_04 or later case added; failure cases pass. |
| Production default | NO-GO | Separate production-readiness decision, larger benchmark set, monitoring/rollback plan, and explicit approval to change default behavior. |

## 7. Stop Conditions

Stop rollout and return to lab-only if any of the following occurs:

- Any OCR review path calls `/api/submit-test`.
- Any OCR review path clicks `#tsSubmit`.
- Any answer-key, grading, or filesystem path field reaches student-facing JSON or UI.
- Any recognized-only, erased/overwritten, missing, ambiguous, or answer-mode-mismatch item becomes `safe_auto_grade`.
- Any provider path exceeds its declared call budget.
- Any production/default flag is enabled without explicit rollout approval.

## 8. Confirmation For This Checklist Task

- No code changes were made.
- No `app.py`, route, static, `static/js/student.js`, validator, adapter, or preflight script was modified.
- No data, DB, `tests-config.json`, answer key, student record, progress/logs/tests runtime data, or production default was modified.
- No environment variables were changed.
- No Gemini/API call was made.
- No `/api/submit-test` call was made.
- `#tsSubmit` was not clicked.
