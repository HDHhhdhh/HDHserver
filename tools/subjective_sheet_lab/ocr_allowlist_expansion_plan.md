# OCR Allowlist Expansion Plan

Generated: 2026-07-10 03:30:00 +09:00
Classification: ALLOWLIST_SURFACE_PRESENT_QA_PENDING_PLAN

## Purpose

This plan defines how to move from one hidden internal alpha test toward September allowlist production without enabling OCR globally.

## Current Baseline

- Current QA-certified allowlist baseline: `t_unit_daesu_01_lv3_r1` / round `1`.
- Current route/client OCR allowlist surface also includes `t_unit_daesu_02_lv3_r1` / round `1`, but that pair is not QA-certified.
- Current entry path: hidden `?ocr=1`.
- Current production default: NO-GO.
- Current role of OCR: review-gated answer-entry assistant.
- Current submit policy: OCR review must not auto-call `/api/submit-test` or click `#tsSubmit`.

## Candidate Test Intake Fields

Each candidate test/round needs a row with:

- test id.
- round.
- subject/unit label.
- expected student volume.
- answer mode per question.
- required answer-sheet layout.
- available sample images.
- crop/contact readiness.
- cached review payload availability.
- known handwriting risks.
- review/retake policy notes.
- teacher owner.
- rollout month target.
- GO/NO-GO status.

## Candidate Readiness Gates

A candidate test/round can be proposed for allowlist only when all are true:

- Answer-mode table exists for all questions.
- OCR review payload schema is known to produce 20 student-safe items.
- No answer-key, expected, canonical, accepted-answer, grading, or local path fields are exposed.
- Manual fallback is documented.
- Review/retake behavior is documented.
- At least one no-provider or cached route/review/fill dry run is available, or a live provider run is separately approved.
- Feature-off behavior for non-allowlisted tests remains safe.
- Teacher-supervised checklist is available.

## July Expansion Rule

Do not expand the allowlist beyond the current one test/round during the first teacher-supervised run. July expansion is operational learning, not test-scope expansion.

Allowed July decisions:

- Keep one test and one round.
- Run one named student at a time after approval.
- Collect teacher-supervised evidence.
- Record friction, review/retake cases, image quality issues, and manual fallback rate.

## August Candidate Review

In August, choose five to ten candidate test/rounds for internal exam use. A candidate may move to "ready for QA" only after answer-mode and review rules are complete.

Suggested priority:

1. Tests with stable answer formats.
2. Tests with low erased/overwritten ambiguity.
3. Tests with already prepared image/crop/contact assets.
4. Tests where manual fallback cost is acceptable.
5. Tests with teacher owner available for supervision.

## September Allowlist Production Rule

Allowlist production means:

- OCR can be visible to students only for approved test/round pairs.
- Non-allowlisted tests hide/disable OCR.
- OCR review remains mandatory.
- Manual input remains available.
- Provider/API policy is explicit.
- Off switch is tested.
- Monitoring owner is assigned.

It does not mean global production default or all-test OCR support.

## Approval Gates

Explicit approval is required for:

- Adding a new live allowlist test/round.
- Running live Gemini/API/provider OCR.
- Increasing provider call budget.
- Allowing `/api/submit-test` or `#tsSubmit` in a certification run.
- Enabling production default.
- Editing tests-config, answer keys, DB/runtime/student records, operating code, benchmark truth, or recognized/cache artifacts.

## Allowlist Candidate Status Template

| Test ID | Round | Month Target | Answer Modes Ready | Review Policy Ready | QA Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `t_unit_daesu_01_lv3_r1` | 1 | July baseline | partial/current | current | hidden alpha/no-provider evidence | teacher/operator | current baseline |
| `t_unit_daesu_02_lv3_r1` | 1 | next surface-present target | answer-mode table drafted | no | none | TBD | ALLOWLIST_SURFACE_PRESENT_BUT_NOT_QA_CERTIFIED |
| TBD | TBD | August candidate | no | no | none | TBD | not ready |

## Current Recommendation

Keep `t_unit_daesu_01_lv3_r1` / round `1` as the only QA-certified OCR test while the teacher-supervised checklist is validated. Treat `t_unit_daesu_02_lv3_r1` / round `1` as surface-present but QA-pending; do not claim it is certified, production-ready, or ready for rollout until the required no-provider/no-submit QA evidence is recorded.

## Surface-Present QA-Pending Target: t_unit_daesu_02_lv3_r1

Status: `ALLOWLIST_SURFACE_PRESENT_BUT_NOT_QA_CERTIFIED`.

Meaning:

- The route/client OCR allowlist surface already contains this test/round.
- It is not QA-certified.
- Hidden OCR QA, partial fill QA, and no-submit QA are not yet certified for this target.
- This is not production default GO.
- This is not actual rollout approval.
- Do not describe it as a certified allowlist target until QA passes.

Target:

- Test ID: `t_unit_daesu_02_lv3_r1`
- Round: `1`
- Label: `지수2 Lv.3`
- Production default: NO-GO
- Live OCR: not run
- Submit/final submit: not run
- Current decision: correct status/docs to surface-present, QA-pending; do not modify operating code

Draft answer-mode table:

| Mode | Questions |
| --- | --- |
| `choice_number` | q003, q006, q007, q009, q010, q011, q015, q020 |
| `answer_value` | q001, q002, q004, q005, q008, q012, q013, q014, q016, q017, q018, q019 |

Required evidence before QA certification or rollout use:

- testId and round confirmation
- 20-question count confirmation
- answer-mode verification
- answer-sheet sample
- crop/contact sheet
- human transcription
- recognized/review_payload evidence
- partial fill QA
- safe-block or blank fallback confirmation
- no-submit confirmation
- explicit provider budget decision if live OCR accuracy QA is requested

Planned no-provider/no-submit QA:

- Use hidden `?ocr=1`.
- Keep Gemini/API/provider at 0.
- Keep `/api/submit-test` at 0.
- Do not click `#tsSubmit` or final submit.
- Call `/api/ocr-test-sheet-review` at most once.
- Confirm review payload has 20 items.
- Confirm review UI opens.
- Confirm partial fill plus blank fallback behavior.
- Confirm `#tsAnswersText` has 20 lines.
- Keep production default NO-GO.

Approval gates remain:

- Any allowlist surface cleanup, removal, or operating-code change requires user approval.
- Artifact-based OCR QA for this candidate requires user approval.
- Live Gemini/API/provider OCR accuracy QA requires explicit provider authorization and declared budget.
- Final submit certification requires separate approval.
