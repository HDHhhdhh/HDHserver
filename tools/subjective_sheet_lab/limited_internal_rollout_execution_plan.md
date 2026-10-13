# Limited Internal Rollout Execution Plan

Generated: 2026-07-10 03:02:00 +09:00
Classification: PLANNING_ONLY_LIMITED_INTERNAL_ROLLOUT_EXECUTION_PLAN

## 1. Rollout Purpose

This plan defines how to move from hidden/internal alpha evidence toward a one-student limited rollout decision for OCR answer capture. It is planning-only documentation. It does not execute rollout, does not run browser/app or route calls, does not call Gemini/API/provider, does not call `/api/submit-test`, does not click or instruct `#tsSubmit` or final submit, does not modify runtime data, and does not enable production default.

Current evidence supports a narrow internal-alpha planning path only: the mock-only stage is past, the hidden `?ocr=1` student page connection is confirmed, `/api/ocr-test-sheet-review` HTTP 200 and a 20-item review payload have been observed, the review UI has opened, answer-key/grading/path leak evidence is 0, safe-block behavior is confirmed when review/retake state remains unresolved, and the 20-line fill bridge is confirmed in local-only fixture paths. Separately performed final-submit certification is submission-pipeline evidence only, not OCR answer-correctness evidence.

## 2. Current GO Scope

- Hidden internal alpha is GO for narrow planning and controlled internal operation only.
- Current allowed test scope is `t_unit_daesu_01_lv3_r1` / round `1` only.
- Entry is through the hidden `?ocr=1` path only.
- Provider-disabled and no-submit review/fill planning may proceed when all safety counts remain 0.

## 3. Current NO-GO Scope

- Production default remains NO-GO.
- Arbitrary test, round, or allowlist expansion is NO-GO.
- Multi-student rollout is NO-GO.
- Live Gemini/provider OCR accuracy work is NO-GO without explicit process-local approval and a declared positive call budget.
- Final submit is NO-GO without separate certification scope and explicit approval.
- Answer-key, expected, canonical answer, accepted answers, solution metadata, or grading exposure is NO-GO.
- Runtime JSON, DB, or student-record mutation outside an approved certification task is NO-GO.

## 4. Candidate Student Selection Rule

Start with exactly one explicitly named internal alpha student in the approval/run packet. Do not run several students at once. Do not broaden the test, round, or allowlist. If the selected student needs a different test, round, live provider call, submit, runtime write, or production-default behavior, stop and record `NEEDS_USER_APPROVAL` instead of adapting the plan.

## 5. Entry Path

- Open only the hidden `?ocr=1` path.
- Select only `t_unit_daesu_01_lv3_r1`.
- Use only round `1`.
- Confirm the selected assigned card/test context before any upload or review step in a separately approved run.

## 6. Execution Roles

| Role | Responsibility | Boundary |
| --- | --- | --- |
| Operator | Runs the approved one-student hidden alpha session and records observed counts. | No provider, submit, final-submit, production-default change, or runtime mutation unless separately approved. |
| Observer / audit room | Checks route/status evidence, leak guards, stop conditions, and claim boundaries. | Read-only unless its task explicitly allows a report/status write. |
| Docs room | Records planning, status, and narrow evidence summaries. | Documents/status only; no runtime, code, benchmark truth, recognized/cache, or answer-key edits. |
| Coordinator room | Routes the next safe task or asks one approval question when gates are hit. | Does not invent approval or provider budget. |

## 7. Pre-Run Checklist

- Confirm the run packet names exactly one internal alpha student.
- Confirm target `t_unit_daesu_01_lv3_r1` / round `1`.
- Confirm hidden `?ocr=1` path only.
- Confirm provider disabled unless explicit current approval grants a positive call budget.
- Confirm production default remains NO-GO.
- Confirm route eligibility check is part of the approved run, not this docs task.
- Confirm no answer-key, expected, canonical, accepted-answer, grading, solution, or local-path leak is allowed.
- Confirm runtime snapshot/hash policy before any run that may touch copied or original runtime state.
- Confirm stop conditions are acknowledged by operator, observer, docs room, and coordinator room.
- Confirm manual fallback is available before upload/review starts.

## 8. Student Answer-Sheet Handling

The student should provide one clear answer per problem in the intended answer area. The operator may upload the answer-sheet image only inside a separately approved internal alpha run. Answer keys must not be used to infer final answers. Erased, crossed-out, overwritten, multiple, ambiguous, or unclear answers must become `review_required`, `retake_required`, or manual fallback cases, never `safe_auto_grade` guesses. If review/retake state remains unresolved, fill must stay blocked.

## 9. OCR Review Procedure

1. Confirm the one student, selected test, and round.
2. Upload the answer-sheet image only through the approved hidden flow.
3. Use the review route only under the approved no-provider/no-submit or separately approved live-provider scope.
4. Confirm the review UI opens and exposes the expected 20 review items.
5. Manually confirm only answers that are visible and reasonable from the student work.
6. Do not resolve uncertain items from answer keys, expected/canonical/accepted answers, grading fields, or solution metadata.
7. Fill only when there are 20 safe, non-empty answers and no unresolved review/retake state.
8. If any blocker remains, leave fill blocked and use manual fallback or retake handling.

## 10. Submit Rule

`/api/submit-test` remains forbidden unless separately approved. `#tsSubmit` and final submit remain forbidden unless separately approved. Final-submit certification is a different task from this OCR review/rollout planning task.

## 11. Stop Conditions

Stop and record `NEEDS_USER_APPROVAL` if any step requires:

- Gemini/API/provider call or provider budget setup.
- `/api/submit-test`.
- `#tsSubmit` or final submit.
- Production default enablement.
- Runtime JSON, DB, or student-record write outside explicit approval.
- Answer-key, path, solution metadata, or grading exposure.
- Allowlist expansion.
- Test or round mismatch.
- Unresolved `review_required` or `retake_required` state.
- Tests-config, answer-key, benchmark truth, recognized output, or provider-cache modification.
- Operating-code edit.
- Multiple-student rollout execution.
- Live OCR accuracy QA without explicit approval and budget.

## 12. Rollback And Cleanup Procedure

This plan does not authorize automatic restore. If an approved run stops, keep production default NO-GO, keep submit/final-submit counts at 0, preserve evidence needed for audit, discard untrusted OCR-filled text, and use manual fallback. Cleanup route artifacts only when the approved task explicitly defines the cleanup policy; otherwise report exact artifact labels/counts without exposing local filesystem paths in student payloads. Request explicit approval before restore, repair, privileged diagnostics, runtime mutation, benchmark truth edits, recognized/cache overwrite, or artifact deletion.

## 13. Logs And Network Evidence Checklist

| Evidence item | Required recording |
| --- | --- |
| `/api/ocr-test-sheet-review` | Count and status, including HTTP status when a route call is authorized. |
| Legacy `/api/ocr-test-sheet` | Count must be recorded; expected 0 unless explicitly approved. |
| Gemini/API/provider | Count must be recorded; expected 0 unless explicitly approved with budget. |
| `/api/submit-test` | Count must be recorded; expected 0. |
| `#tsSubmit` / final submit | Click/activation count must be recorded; expected 0. |
| Review payload | Item count and status buckets. |
| Leak scan | Answer-key/grading/path leak result. |
| Runtime hash/snapshot | Original-runtime unchanged result, or approved mutation evidence. |
| Production default | Must remain NO-GO. |

## 14. Fallback

Manual text entry remains available and preferred whenever OCR output is incomplete, ambiguous, blocked, unauthorized, or inconsistent with visible student work. A safe block is acceptable when uncertainty remains; do not lower review/retake gates to force fill.

## 15. GO/NO-GO Table

| Decision area | Status | Notes |
| --- | --- | --- |
| Hidden internal alpha narrow scope | GO | `?ocr=1`, `t_unit_daesu_01_lv3_r1`, round `1` only. |
| Limited rollout planning | GO | Planning-only documentation and coordination. |
| Actual limited rollout | NEEDS_USER_APPROVAL | Requires exactly one named student and approved run scope. |
| Multi-student rollout | NO-GO | Do not batch students. |
| Arbitrary test/round expansion | NO-GO | Requires separate allowlist/test approval. |
| Live Gemini/provider OCR accuracy | NO-GO | Requires explicit process-local approval and positive budget. |
| `/api/submit-test` | NO-GO | Different approval/certification task. |
| `#tsSubmit` / final submit | NO-GO | Different approval/certification task. |
| Production default | NO-GO | Do not enable production default. |
| Runtime/DB/student-record mutation | NO-GO | Unless separately approved for a certification task. |

## 16. Additional Approval Gates

Additional explicit approval is required before any Gemini/API live call, provider call budget creation or increase, `/api/submit-test`, `#tsSubmit` or final submit, production default enablement, other-test allowlist expansion, tests-config modification, answer-key modification, DB/runtime/student-record modification, benchmark truth modification, recognized/cache overwrite, provider-cache overwrite, privileged writer-attribution diagnostics, restore, rollback, or operating-code edit.

## Final Boundary

This plan preserves answer-key, grading, and local-path leak guards. It records a controlled path toward a one-student internal alpha decision only. It is not live OCR accuracy certification, final-submit certification, limited rollout PASS, production readiness, or production default GO.

## 17. Latest One-Student Pilot Completion Addendum

Classification reflected: `PASS_ISOLATED_LOCAL_ONLY_ONE_STUDENT_PILOT_AUDITED`.

The one-student local-only teacher-supervised no-submit pilot is now DONE / PASS for its narrow scope. The audited evidence covers one OCR review route call with HTTP 200, a 20-item review payload, 15 teacher-confirmed items, and `#tsAnswersText` exactly 20 lines with 15 filled and 5 blank. Gemini/API/provider, external OCR, `/api/submit-test`, `#tsSubmit`/final submit, answer-key/grading/path leak, original runtime/shared OCR drift, and operating-code change counts were all 0. Production default remains NO-GO.

This addendum does not broaden the plan. UI and isolated QA runner are PASS only for the one-student route/review/teacher-confirm/partial-fill/no-submit path. Local-only OCR candidate coverage and accuracy remain separate from this pilot and the P0 `NO_GO_LOCAL_OCR` result is unchanged. Fresh external provider OCR, final-submit certification, multi-student rollout, another-test allowlist work, production readiness, and production default enablement each require separate approval.

Next safe choices are candidates only, not automatic actions: student 2-3 local-only teacher-supervised no-submit pilot, one test-account final-submit certification, re-deciding whether to improve local OCR coverage, preparing another-test allowlist plan, or keeping production default as a separate NO-GO decision.

Audit caveat: the automatic audit worker did not complete normally because of a Windows sandbox-helper issue. A direct read-only audit confirmed the same evidence and closed this step as PASS. The automation issue should be treated as audit infrastructure debt, not pilot feature failure, and the same audit loop should not be rerun automatically.
