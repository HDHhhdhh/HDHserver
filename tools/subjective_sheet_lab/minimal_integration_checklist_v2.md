# Minimal Subjective OCR/Vision Integration Checklist v2

This checklist is for future integration work. It is not an implementation log.

## A. Pre-integration Guardrails

- [ ] Confirm the work is behind a disabled-by-default feature flag.
- [ ] Confirm default student page behavior is unchanged.
- [ ] Confirm manual/direct answer submission remains available.
- [ ] Confirm `/api/submit-test` will not be changed in early phases.
- [ ] Confirm OCR/Vision processing endpoints will not call `/api/submit-test`.
- [ ] Confirm no runtime data files are modified by OCR/Vision processing.
- [ ] Confirm API keys are read server-side only and never sent to the browser.

## B. Files That Must Stay Unchanged Until Explicit Integration Work

- [ ] `app.py`
- [ ] `routes/api_tests.py` `/api/submit-test`
- [ ] `static/student.html` default behavior
- [ ] `static/js/student.js` default student flow
- [ ] `static/css/student.css` default styling
- [ ] runtime data files such as `tests.json`, `tests-config.json`, `students.json`, `logs.json`, `app.sqlite`

## C. Future Backend Gate

- [ ] Full-sheet upload endpoint returns review payload only.
- [ ] Full-sheet upload endpoint does not save a student test record.
- [ ] Full-sheet upload endpoint distinguishes whole-sheet failure from per-question failure.
- [ ] Per-question retake endpoint returns one updated item only.
- [ ] Retake endpoint does not save a student test record.
- [ ] Optional validation endpoint can convert reviewed items to ordered `answersText`.
- [ ] Student-safe responses exclude `expected`, `canonical_answer`, and `accepted_answers`.
- [ ] Admin/debug reports may include answer-key details only outside student-facing UI.

## D. Future Frontend Gate

- [ ] Photo entry point is hidden unless the feature flag is enabled.
- [ ] Existing submit modal can still be opened manually.
- [ ] Existing `#tsAnswersText` path still works.
- [ ] Review UI shows only actionable items by default.
- [ ] `safe_auto_grade` items are collapsed.
- [ ] `review_required` items allow candidate selection or direct/keypad correction.
- [ ] `retake_required` items focus on per-question retake.
- [ ] `retake_uploaded` items require re-recognition.
- [ ] `data_check_required` is not student-editable.
- [ ] Developer/debug details are absent from student UI.

## E. Final Payload Gate

- [ ] Final payload has exactly one answer per configured question.
- [ ] Question numbers are continuous and unique.
- [ ] `review_required` items are confirmed before submit.
- [ ] `retake_required` items are resolved before submit.
- [ ] `retake_uploaded` items are re-recognized before submit.
- [ ] `data_check_required` blocks photo-flow final submit.
- [ ] Final reviewed item payload maps deterministically to `answersText`.
- [ ] Final save uses existing `/api/submit-test` only after student confirmation.

## F. Safety Tests Before Any Rollout

- [ ] Default student URL has no OCR/Vision UI.
- [ ] Feature-flag URL has OCR/Vision UI.
- [ ] Network responses contain no expected/canonical/accepted answers.
- [ ] Browser DOM contains no expected/canonical/accepted answers.
- [ ] Browser console contains no API key, `.env`, raw provider payload, or answer key.
- [ ] OCR/Vision failure leaves manual submission usable.
- [ ] Mobile capture works on Android Chrome.
- [ ] Mobile capture works on iOS Safari if iOS devices are supported.
- [ ] Retake flow works for a single question.
- [ ] Whole-sheet failure asks for whole-sheet recapture.
- [ ] Feature flag rollback restores the old flow.

## G. Phase Gates

### Phase 0: Lab-only

- [ ] Review mock is stable.
- [ ] Warning policy is documented.
- [ ] Payload mapping is documented.
- [ ] No operating app changes.

### Phase 1: Internal route only

- [ ] Internal endpoint exists behind no student link.
- [ ] Synthetic/local test images work.
- [ ] No save path is reachable.
- [ ] Review payload is student-safe.

### Phase 2: Hidden student flag

- [ ] Default URL unchanged.
- [ ] Hidden flag opens photo flow.
- [ ] Manual fallback remains visible.
- [ ] Final submit requires student confirmation.

### Phase 3: Limited test accounts

- [ ] Allowlist or fake/test student IDs only.
- [ ] Monitoring/reporting enabled.
- [ ] Admin/developer handling exists for `data_check_required`.

### Phase 4: Real rollout

- [ ] Rollout is gradual.
- [ ] Manual fallback remains available.
- [ ] Retake and review rates are acceptable.

### Phase 5: Monitoring and rollback

- [ ] One-switch disable is tested.
- [ ] Existing `/api/submit-test` path still works.
- [ ] Runtime records are not corrupted by OCR/Vision failures.

## H. Stop Conditions

Stop and do not roll out if any of these occur:

- Expected/canonical/accepted answer leak.
- OCR/Vision endpoint saves student records.
- OCR/Vision endpoint calls `/api/submit-test`.
- Feature flag exposes the flow to all students by accident.
- `retake_uploaded` can be submitted.
- `data_check_required` can be student-edited into a final answer.
- Manual submission path breaks.
