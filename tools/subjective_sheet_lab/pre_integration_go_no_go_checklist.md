# Subjective OCR/Vision Pre-Integration Go/No-Go Checklist

Status: lab-only dry run complete, real student integration not started.

This checklist is the final gate before any future feature-flag integration into the real student page. It is based on the current lab artifacts and local validation reports. It does not authorize production rollout by itself.

## 1. Current Go/No-Go Summary

Decision: **NO-GO for real student page integration today**.

Reason:

- The local review pipeline and final `answersText` bridge are ready as lab components.
- The student-safe payload policy is verified locally.
- The Gemini same-contact final evaluation is still incomplete because of quota exhaustion.
- No feature-flagged internal endpoint has been implemented yet.
- No browser/mobile integration QA has been run against the real student page.

Allowed next phase: **Phase 1 internal-only integration**, not student-facing rollout.

## 2. Lab Pipeline Components Completed

- [x] OCR/Vision policy evaluator: `evaluate_ocr_result.py`
- [x] Review UI mock: `review_ui_mock.html`
- [x] Review UI samples:
  - `review_ui_mock_sample.json`
  - `review_ui_mock_sample_person02.json`
  - `review_ui_mock_sample_jamo.json`
- [x] Review policy regression script: `verify_evaluate_ocr_policy.py`
- [x] Review UI policy verification: `verify_review_ui_mock_policy.py`
- [x] Final review payload to `answersText` bridge:
  - `final_review_payload_bridge.py`
  - `verify_final_review_payload_bridge.py`
  - `final_review_payload_bridge_fixture.json`
  - `final_review_payload_bridge_report.md`
- [x] End-to-end lab dry run:
  - `subjective_review_dry_run_core.py`
  - `subjective_review_pipeline_dry_run.py`
  - `subjective_review_dry_run_fixture.json`
  - `subjective_review_dry_run_report.md`
- [x] Integration planning docs:
  - `server_integration_plan_v2.md`
  - `minimal_integration_checklist_v2.md`

## 3. Required Files and Scripts Before Integration

Keep these files available and passing before starting integration:

```text
tools/subjective_sheet_lab/evaluate_ocr_result.py
tools/subjective_sheet_lab/review_ui_mock.html
tools/subjective_sheet_lab/review_ui_mock_sample.json
tools/subjective_sheet_lab/review_ui_mock_sample_person02.json
tools/subjective_sheet_lab/review_ui_mock_sample_jamo.json
tools/subjective_sheet_lab/final_review_payload_bridge.py
tools/subjective_sheet_lab/verify_final_review_payload_bridge.py
tools/subjective_sheet_lab/final_review_payload_bridge_fixture.json
tools/subjective_sheet_lab/subjective_review_dry_run_core.py
tools/subjective_sheet_lab/subjective_review_pipeline_dry_run.py
tools/subjective_sheet_lab/subjective_review_dry_run_fixture.json
tools/subjective_sheet_lab/server_integration_plan_v2.md
tools/subjective_sheet_lab/minimal_integration_checklist_v2.md
```

Generated local evidence files:

```text
tools/subjective_sheet_lab/final_review_payload_answersText.txt
tools/subjective_sheet_lab/final_review_payload_bridge_report.md
tools/subjective_sheet_lab/subjective_review_dry_run_review_payload.json
tools/subjective_sheet_lab/subjective_review_dry_run_final_payload.json
tools/subjective_sheet_lab/subjective_review_dry_run_answersText.txt
tools/subjective_sheet_lab/subjective_review_dry_run_report.md
```

## 4. Validation Commands

Run these local commands before starting any integration branch:

```powershell
python -m py_compile `
  tools\subjective_sheet_lab\evaluate_ocr_result.py `
  tools\subjective_sheet_lab\final_review_payload_bridge.py `
  tools\subjective_sheet_lab\verify_final_review_payload_bridge.py `
  tools\subjective_sheet_lab\subjective_review_dry_run_core.py `
  tools\subjective_sheet_lab\subjective_review_pipeline_dry_run.py

python tools\subjective_sheet_lab\verify_evaluate_ocr_policy.py
python tools\subjective_sheet_lab\verify_review_ui_mock_policy.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
python tools\subjective_sheet_lab\subjective_review_pipeline_dry_run.py
```

Expected result:

- All commands exit `0`.
- Dry run prints `{"ok": true, "answers": 20, ...}`.
- `subjective_review_dry_run_report.md` says leak scan is `none`.
- No command calls Gemini/API.
- No command calls `/api/submit-test`.

## 5. Lab Dry Run Status

Completed local flow:

```text
recognized/evaluated OCR result
-> review payload
-> simulated student review decisions
-> final review payload
-> answersText conversion
```

Verified:

- [x] `safe_auto_grade` items pass through.
- [x] `review_required` blocks conversion until simulated confirmation.
- [x] Candidate-selected answers convert correctly.
- [x] Keypad/direct-input answers convert correctly.
- [x] `retake_required` blocks until resolved.
- [x] `retake_uploaded` blocks until re-recognized.
- [x] `data_check_required` blocks conversion.
- [x] Final `answersText` has stable 20-question order.
- [x] Student-facing outputs do not leak `expected`, `canonical_answer`, or `accepted_answers`.

## 6. Gemini Same-Contact Final Eval Status

Current status: **INCOMPLETE / quota-dependent**.

Evidence path:

```text
C:\server-ocr\gemini_outputs\person_02_same_contact\quota_checkpoint.md
C:\server-ocr\gemini_outputs\person_02_same_contact\error_report.json
C:\server-ocr\gemini_outputs\person_02_same_contact\same_contact_comparison_summary.md
```

Known state:

- Model: `gemini-2.5-flash-lite`
- Last blocker: HTTP 429 `RESOURCE_EXHAUSTED`
- Completed: q001-q010
- Pending: q011-q020
- Completed-only result: 8/10 correct, 80.0%
- Do not treat pending questions as final missing items.
- Do not treat completed-only 80% as full 20-question same-contact accuracy.

Go condition for this item:

- [ ] Quota has recovered or a permitted billing/key plan is available.
- [ ] Resume same-contact evaluation without repeating completed cached calls.
- [ ] Complete q011-q020.
- [ ] Produce a full 20-question `same_contact` evaluation summary.
- [ ] Reconfirm no key, prompt payload, or expected-answer leak in student-facing artifacts.

## 7. Security Rules

Hard requirements:

- Student-facing review payload must never include:
  - `expected`
  - `canonical_answer`
  - `accepted_answers`
  - raw answer key rows
  - raw provider payload
  - API key or `.env` value
- OCR/Vision endpoints must never call `/api/submit-test`.
- OCR/Vision endpoints must never save final student test records.
- The final save path must remain student-confirmed.
- Accepted match with warnings must not become `safe_auto_grade`.
- `data_check_required` must be admin/developer handled, not student-editable.

Local evidence:

- `final_review_payload_bridge_report.md`: answer-key leak scan `none`.
- `subjective_review_dry_run_report.md`: student-facing output leak scan `none`.

## 8. Final Payload to answersText Bridge Status

Status: **READY for Phase 1 internal integration contract testing**.

Verified by:

```text
tools/subjective_sheet_lab/final_review_payload_bridge.py
tools/subjective_sheet_lab/verify_final_review_payload_bridge.py
tools/subjective_sheet_lab/final_review_payload_bridge_report.md
tools/subjective_sheet_lab/subjective_review_pipeline_dry_run.py
tools/subjective_sheet_lab/subjective_review_dry_run_report.md
```

Bridge behavior:

- Sorts final answers by `question_no`.
- Requires exactly 20 resolved questions for the current lab fixture.
- Emits the plain newline-separated `answersText` format used by the real student submit modal.
- Rejects unresolved or unsafe states before conversion.
- Rejects student-forbidden answer-key fields.

## 9. Statuses That Must Block Final Submit

These statuses must block final photo-flow submit:

- `review_required`
- `retake_required`
- `retake_uploaded`
- `data_check_required`

Additional blocking cases:

- Missing question number.
- Duplicate question number.
- Item count not equal to configured problem count.
- Empty final answer.
- Newline inside a per-question final answer.
- Any student-facing payload containing `expected`, `canonical_answer`, or `accepted_answers`.

Allowed final sources after resolution:

- `safe_auto_grade`
- `student_selected_candidate`
- `student_direct_input`
- `safe_auto_grade_after_retake`
- `student_selected_candidate_after_retake`
- `student_direct_input_after_retake`

## 10. Blockers Before Real Integration

Do not start real student page integration until these are resolved:

- [ ] Gemini same-contact evaluation is completed for all 20 person_02 crops.
- [ ] Full-sheet image processing contract is defined for marker/crop/enhance failure modes.
- [ ] Internal-only backend contract test exists and proves no save path is reachable.
- [ ] Student-safe review payload contract is finalized.
- [ ] Admin/developer handling path for `data_check_required` is defined.
- [ ] Mobile capture and per-question retake UI QA plan is ready.
- [ ] Rollback flag and default-off behavior are specified.

## 11. Feature Flag Rollout Conditions

Phase 1: internal only

- No student page link.
- No real student records.
- No `/api/submit-test` call.
- Local/test images only.

Phase 2: hidden student flag

- Default student URL unchanged.
- Hidden flag only, for example `?visionReview=1`.
- Manual submit remains visible and functional.
- Final save still requires student confirmation.

Phase 3: limited test accounts

- Allowlist fake/test students only.
- Monitoring captures review, retake, data-check, and fallback rates.
- Expected-answer leak checks are run against network responses and DOM.

Phase 4: broader rollout

- Only after same-contact final eval, mobile QA, and rollback drill pass.

## 12. Rollback Plan

Rollback must be a feature-flag disable, not a data migration.

Rollback requirements:

- Disable photo-recognition entry point.
- Keep existing manual submit modal untouched.
- Keep `/api/submit-test` unchanged.
- Leave existing student records untouched.
- Preserve local OCR/Vision session artifacts only for debug if they do not contain secrets.
- Confirm default student URL returns to current behavior.

## 13. What Must NOT Be Touched Until Integration Phase

Do not modify these before an explicit integration task starts:

- `app.py`
- `routes/**`
- `static/student.html`
- `static/js/student.js`
- `static/css/student.css`
- DB files, including `app.sqlite` and sidecars
- Runtime data files under root or `data/**`
- `tests.json`
- `tests-config.json`
- `/api/submit-test` implementation or behavior

Do not call:

- Gemini/API
- `/api/submit-test`
- Any endpoint that writes student records

## 14. Exact Next Implementation Step

When integration starts, the next implementation step should be:

Create a **Phase 1 internal-only backend contract harness** that accepts a local full-sheet test image or prepared local crops, returns the same student-safe review payload shape verified by `subjective_review_pipeline_dry_run.py`, and proves that no student record save path is reachable.

Minimum acceptance for that first integration step:

- New flow is default-off and not linked from the real student page.
- It does not call `/api/submit-test`.
- It does not write `tests.json`, logs, DB, or student data.
- It returns no `expected`, `canonical_answer`, or `accepted_answers` in student-facing JSON.
- It reuses the lab status policy and final `answersText` bridge.
- It has a local verification command that exits `0`.

Only after that passes should hidden student-page feature-flag work begin.
