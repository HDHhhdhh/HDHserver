# Teacher-Supervised Local-Only Pilot Operations Plan

Updated: 2026-07-18 KST
Classification: PLANNING_ONLY_TEACHER_SUPERVISED_LOCAL_ONLY_PILOT
Decision: NO_GO until the roster and each real rollout session receive separate explicit user approval.

## Purpose and boundaries

This document defines a possible teacher-supervised, local-only OCR-assisted answer-entry pilot. It is an operations plan only. It does not select students, start a pilot, authorize browser/app or route execution, certify live OCR accuracy, establish production readiness, change the production default, or authorize student rollout.

The only supported functional scope is:

- test t_unit_daesu_01_lv3_r1;
- round 1;
- the hidden student-page entry path exposed only with ?ocr=1;
- teacher-reviewed answer-entry assistance followed by editable manual correction;
- local-only OCR candidates or manual entry fallback.

Actual-student images and handwriting must remain on the local machine. Transfer to Gemini, an external OCR API, or any other provider is prohibited under this plan. Provider authorization for another purpose does not authorize actual-student transfer under this plan.

OCR output is never an answer key, grading result, or submit instruction. Answer keys, expected or canonical answers, accepted-answer lists, grading fields, solution metadata, and local filesystem paths must not be used to infer OCR output or appear in student-facing payloads, screenshots, reports, or evidence.

## Non-authorizations and NO-GO defaults

| Control | Required state for this plan |
| --- | --- |
| Gemini/API/provider calls | 0 |
| External actual-student image transfer | prohibited |
| /api/submit-test calls | 0 |
| #tsSubmit or final-submit clicks | 0 |
| Production default | NO-GO |
| Non-target test or round | prohibited |
| Answer-key/grading/path leak hits | 0 |
| Automatic grading claim | prohibited |

No step in this plan grants permission to enable the production default, expand the allowlist, modify operating code, write runtime JSON/DB/student records, edit test configuration or answer keys, overwrite benchmark truth or recognized/provider-cache artifacts, restore snapshots, or begin an actual rollout.

## Candidate pool standard: 10 active slots and up to 2 reserves

The proposed pool is 10 active candidate slots plus up to 2 reserve slots. This document deliberately uses only abstract slots P01 through P12; it contains no actual student names, IDs, or identity mapping.

A candidate is eligible only when all of the following are true:

1. The candidate is scheduled for the exact supported test and round.
2. A teacher can supervise the entire session in person and stop the flow immediately.
3. The candidate can provide one clearly framed, legible answer-sheet image without unrelated personal information in frame.
4. The device can keep image handling local and can use manual answer entry if OCR is unavailable or unsafe.
5. The teacher understands that OCR assists transcription only and is not grading or answer validation.
6. The candidate can rewrite, retake, or manually enter erased, crossed-out, overwritten, multiple, ambiguous, missing, or unclear answers.
7. The candidate is not needed to test a new test type, round, browser feature, provider path, or production-default behavior.
8. A non-public identity-to-slot mapping, if needed operationally, is maintained outside this document under the applicable privacy policy.

Selection should provide ordinary device/browser variety without turning this narrow pilot into broad compatibility certification. A reserve may replace an active slot only after the same eligibility check and a new approval covering that substitution.

## Two mandatory user approval gates

### Gate A: roster approval

Before any identity is assigned to P01 through P12, the user must explicitly approve the proposed 10 active candidates and any reserves. Approval must confirm the target test/round, teacher ownership, local-only handling, provider count 0, submit/final-submit counts 0, and the off-switch owner. A previously prepared or assigned candidate list is not approval to start this pilot.

### Gate B: per-session real rollout approval

Before each real candidate session starts, the user must explicitly approve that single session. Approval must identify the candidate slot, date/window, teacher/operator, device/browser, target test/round, local-only input mode, evidence owner, and rollback/off-switch owner. Approval for one slot or date does not carry over to another slot, a retry, a reserve substitution, or a later session.

If either approval is absent, unclear, stale, or broader than this scope, record NEEDS_USER_APPROVAL and do not open the OCR flow.

## Roles

| Role | Responsibility |
| --- | --- |
| User/approver | Approves the roster and every real session separately; does not grant blanket rollout approval. |
| Teacher/operator | Maintains supervision, compares only with visible student work, controls the stop/off switch, preserves editability, and records evidence. |
| Student | Supplies the work and may rewrite, retake, or manually enter unclear answers; is never asked to trust OCR as grading. |
| Evidence reviewer | Confirms counts, leak guards, device/browser record, and stop-condition handling without using answer keys. |

One teacher/operator should handle one candidate session at a time. Unattended, parallel, take-home, or self-service OCR use is outside this plan.

## Preflight checklist

Every item must be checked immediately before a future, separately authorized session.

- [ ] Gate A roster approval covers this candidate slot.
- [ ] Gate B approval covers this exact session, operator, device/browser, test, and round.
- [ ] The selected scope is exactly t_unit_daesu_01_lv3_r1, round 1.
- [ ] The entry path is hidden ?ocr=1; OCR remains unavailable through the normal default path.
- [ ] Production default is still NO-GO; no allowlist or feature-default change is planned.
- [ ] Gemini/API/provider budget and observed call count are both 0.
- [ ] Actual-student image egress is disabled; no external OCR or provider endpoint is available to this session.
- [ ] /api/submit-test monitoring starts at 0 and the flow will stop if it changes.
- [ ] #tsSubmit/final submit will not be clicked or instructed, and the observed click count starts at 0.
- [ ] The answer textarea is visible or reachable, editable, and usable without OCR.
- [ ] The teacher has a manual-input fallback and knows how to preserve 20 answer positions.
- [ ] The image shows only the intended answer sheet, is readable, and contains no unrelated personal material.
- [ ] No answer key, expected/canonical/accepted answer, grading field, or solution metadata is open or used for review.
- [ ] The evidence record uses only the candidate slot and artifact labels, not an actual name or local filesystem path.
- [ ] The device/browser record and stop/off-switch owner are ready.

Any unchecked item means NO_GO for that session.

## Teacher-supervised procedure

### 1. Confirm the student work

The teacher checks that the sheet belongs to the approved slot and exact target session without putting identifying information into the shared evidence record. One final answer should be visible per question. If an answer is erased, crossed out, overwritten, multiple, ambiguous, or unclear, ask for a clean rewrite or plan manual entry; do not let OCR decide which mark is final.

### 2. Enter the hidden flow

Use only the approved student page with ?ocr=1, select t_unit_daesu_01_lv3_r1 and round 1, and confirm the manual textarea remains editable. Stop if OCR appears without the hidden query, if another test/round is selected, or if the page requires a production-default change.

### 3. Use local-only processing

Choose the locally held sheet image only in the approved local-only flow. Do not invoke Gemini, an external OCR API, or any provider fallback. If local processing is unavailable, slow, incomplete, or uncertain, skip OCR and use manual entry.

### 4. Review every item

The teacher reviews against the visible student work only:

- safe_auto_grade: treat the label as a transcription candidate, not a grading decision; verify the visible mark before keeping it.
- review_required: confirm only when the final answer is visibly unambiguous; otherwise leave the answer position blank.
- retake_required: do not fill from OCR; retake the image, ask for a clean rewrite, or enter manually.
- data_check_required, missing, malformed, warning, or unresolved: leave blank and use manual fallback.

Never consult an answer key to resolve uncertainty. A plausible mathematical answer is not evidence that OCR read the student's work correctly.

### 5. Apply partial fill safely

The partial-fill result must preserve exactly 20 ordered answer positions. Verified transcription candidates may populate their positions; all unresolved positions remain blank. Partial fill is acceptable only as an intermediate editable state. It must not fabricate placeholder answers, collapse line positions, or force unresolved items into a non-empty value.

### 6. Complete blanks manually

For every blank, the teacher uses the visible sheet, a clean rewrite, or a retake to enter the student's intended final answer manually. If the intended answer is still unclear, stop the session rather than guessing. Keep the textarea editable throughout.

### 7. Verify without submitting

Confirm that the final textarea still has exactly 20 ordered editable positions and, if the session is recorded as transcription-complete, 20 non-empty student-confirmed entries. Record the evidence counts. Do not call /api/submit-test, do not click or instruct #tsSubmit, and do not perform final submit. Submission requires separate explicit authorization outside this plan.

## Manual-input fallback

Manual input is the normal safe fallback, not a failure workaround.

- If local OCR cannot start, enter all 20 positions manually.
- If partial fill succeeds, preserve verified positions and manually complete only the blanks.
- If a photo is unclear, obtain a clean rewrite or retake before manual transcription.
- If line ordering or textarea editability is uncertain, discard the OCR-assisted draft from the UI and re-enter manually; do not rewrite runtime data or restore a snapshot.
- If the teacher cannot determine the student's final mark from visible work, leave the session incomplete and escalate rather than infer an answer.

## Session stop conditions

Stop immediately and classify the session as STOPPED_SAFE or FAIL as appropriate if any of the following occurs:

- either approval gate is missing or no longer matches the session;
- the test, round, candidate slot, teacher, or device/browser differs from the approval;
- an actual-student image or derived crop is about to leave the local machine;
- any Gemini/API/provider call occurs or is required;
- /api/submit-test is called or a submit side effect is observed;
- #tsSubmit or final submit is clicked, instructed, or automatically activated;
- OCR is visible without ?ocr=1, production default changes, or scope expands beyond the target;
- answer-key, grading, expected/canonical/accepted-answer, solution, or local-path data appears in a payload, UI, report, screenshot, or log;
- any uncertain item is filled without teacher confirmation from visible student work;
- wrong_safe_auto_grade is greater than 0 in later key-free human-transcription review;
- the partial-fill result does not preserve 20 ordered positions or the textarea becomes non-editable;
- runtime/data/config, operating code, benchmark truth, recognized output, or provider cache changes outside a separately approved scope;
- evidence cannot prove provider 0, submit 0, final-submit 0, and leak hits 0.

After a stop, use manual input only if the current approval still permits it and the leak/runtime boundary is intact. Otherwise end the session and route the evidence to audit/coordinator review.

## Off switch and rollback

The immediate off switch is operational and does not require data restoration:

1. Close the OCR review UI and remove ?ocr=1 from the page path.
2. Keep the OCR review route and all provider/live flags disabled outside the specifically authorized local session.
3. Continue with the ordinary editable manual textarea only, or end the session.
4. Preserve the minimal evidence record under a non-identifying session label.
5. Do not delete artifacts, restore snapshots, rewrite runtime data, or modify code as an improvised rollback.

Roster suspension is the broader off switch: pause all remaining slots and reserves until the incident is audited and the user gives a new per-session approval. One stopped session never triggers an automatic retry or candidate substitution.

## Device and browser record

Complete one row per approved session. Do not record an actual student name or a local file path.

| Session label | Candidate slot | Device class / OS | Browser / version | Viewport or screen class | Image source | Network mode | Teacher present | Textarea editable | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| session-label | P__ | desktop/mobile, OS | browser/version | class | camera/file, local | local-only | yes/no | yes/no | not-run/complete/stopped |

Device variety is evidence about this narrow pilot only. It must not be reported as broad browser/mobile certification.

## Logs and network evidence

Use artifact labels and repository-relative report references only. Do not include raw student identities, image contents, answer-key material, or local absolute paths.

| Evidence item | Required result | Recorded value |
| --- | --- | --- |
| Candidate/session label | Approved abstract identifiers only | P__ / session-label |
| Target | t_unit_daesu_01_lv3_r1, round 1 | value |
| Hidden entry | ?ocr=1; default path remains feature-off | pass/fail |
| Local OCR/review action | Count and local result; no provider fallback | count/status |
| Gemini/API/provider requests | 0 | count |
| External image/crop transfer | 0 | count |
| Legacy OCR route calls | 0 unless a future task explicitly scopes a local check | count |
| /api/submit-test calls | 0 | count |
| #tsSubmit/final-submit clicks | 0 | count |
| Review item count | 20 or documented safe block | count/status |
| Item statuses | Counts for safe/review/retake/data-check/unresolved | counts |
| Partial-fill shape | 20 ordered positions; unresolved positions blank | pass/fail |
| Final editable textarea | editable; 20 positions; completion state recorded | pass/fail |
| Manual fallback | available and use recorded | yes/no, reason |
| Leak scan | answer-key/grading/path hits 0 | count |
| Production default | NO-GO | state |
| Runtime/config/code drift | 0 outside separately approved scope | count/result |
| Network evidence label | local-only behavior and zero provider/submit traffic | artifact-label |

Network evidence should be minimized to counts, endpoint categories, statuses, and timestamps needed to prove the safety invariants. Do not retain request bodies containing student work in shared status documents.

## Session outcome labels

| Outcome | Meaning |
| --- | --- |
| COMPLETE_MANUAL_ONLY | All positions were transcribed manually; OCR/provider/submit/final-submit counts remained 0. |
| COMPLETE_LOCAL_PARTIAL_FILL | Local-only OCR assisted, all retained values were teacher-verified, blanks were completed manually, and no submit occurred. |
| PASS_SAFE_BLOCK | OCR safely declined or left unresolved positions blank and manual fallback remained available. |
| STOPPED_SAFE | A preflight or runtime stop condition ended the flow before a prohibited action. |
| FAIL | Provider/submit/final-submit activity, leak, unsafe fill, scope escape, or unauthorized mutation occurred. |

None of these labels means live OCR accuracy certification, automatic-grading certification, production readiness, production-default approval, or authorization for additional students.

## Completion and review

After each future approved session, the teacher and evidence reviewer must reconcile the device/browser row, logs/network table, item counts, manual fallback use, and all zero-count invariants. Any anomaly routes to audit/coordinator review before another slot runs.

This planning artifact itself starts no sessions. Current state remains:

- candidate roster approval: not granted by this document;
- real rollout approval: not granted by this document;
- Gemini/API/provider calls: 0;
- /api/submit-test calls: 0;
- #tsSubmit/final-submit clicks: 0;
- actual-student provider transfer: prohibited;
- production default: NO-GO.
