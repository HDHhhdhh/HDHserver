# Copied Sandbox Assignment Preflight Checklist

## Purpose

Prevent a copied-runtime final-submit certification from producing an avoidable `assignmentProgress.status=not_matched` result because its copied progress fixture lacks a current-date active assignment.

## Before Any Submit-Capable Certification

- [ ] Use a fresh copied app/runtime, copied SQLite database, and copied JSON runtime files.
- [ ] Keep original runtime and shared OCR roots read-only.
- [ ] Record original protected-file hashes before and after the run.
- [ ] Set the copied runtime date context deliberately; do not assume a copied historical date is current.
- [ ] Identify the anonymous selected SID in memory only. Do not publish the raw SID.
- [ ] Confirm the copied `progress.json` contains the submission-date day object.
- [ ] Confirm that day object contains the exact selected SID key after the same trim/normalization used by the route.
- [ ] Confirm the SID entry has a non-empty `tests` object.
- [ ] Confirm one active assignment is `assigned` or `interrupted`.
- [ ] Prefer an assignment object with exact `testId` equal to the selected test ID.
- [ ] If matching falls back to labels, confirm the label match is unique and uses the intended round.
- [ ] Confirm test ID, source ID, and round are consistent between the selected UI test and copied assignment record.

## Fail-Closed Rules

- Missing submission-date day: do not claim assignment progress completion.
- Missing SID entry: do not claim assignment progress completion.
- No active matching assignment: do not claim assignment progress completion.
- Ambiguous label match: stop and classify `BLOCKED_ASSIGNMENT_MATCH_AMBIGUOUS`.
- Do not alter the original runtime, create real assignments, or submit again to repair a fixture.

## Boundary

This is a copied-sandbox preflight only. It does not authorize a new submit, answer-key exposure, provider call, production-default change, or real-student runtime write.
