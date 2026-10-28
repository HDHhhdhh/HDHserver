# Native student API configuration and recovery

Register through the existing public surface with
`STUDENT_APP_PUBLIC_ENABLED=1`. The public development Host is
`dev-app.5a-math.com`, and the exact mutation Origin is
`https://dev-app.5a-math.com`. Listener ports 8004/8003 are tunnel origins,
not public URL ports. Existing cookie, CSRF, SID and proxy checks apply.

## Configuration

- `STUDENT_APP_V2_DB_PATH`: submission journal, solution ticket receipts and
  homework request bodies. Defaults to `student-app-v2.sqlite` beside the
  legacy runtime files. Its `.gate` sibling is a SQLite cross-process mutex.
  Preserve the journal together with the compatibility stores in backups.
- `STUDENT_APP_DEBUG_ACADEMY_SECRET`: enables `X-Debug-Academy: 0|1` only
  on the configured exact dev host with matching `X-Debug-Secret`.
  Production ignores both headers.
- `STUDENT_APP_CONTENT_ROOT`: optional server-owned directory containing
  PDF/PNG files named by their source file IDs. No client filesystem path
  is accepted.
- `STUDENT_APP_DRIVE_ACCESS_TOKEN`: optional configured Drive reader.
  Without a reader, problem documents may be fetched from public Drive;
  unavailable/private files return 503 rather than a fabricated document.
  PDF rendering requires the existing PyMuPDF runtime.
- `STUDENT_APP_SOLUTION_SIGNING_SECRET`: required for the approved fallback
  when no server content reader is configured. The authenticated solution
  endpoint issues a signed 60-second server ticket, consumes it once
  transactionally, and redirects to Drive. Network access is rechecked at
  consumption too. The upstream URL cannot be revoked after redirect.
- `STUDENT_APP_RELEASE_METADATA`: path to release JSON with exactly
  `versionCode`, `versionName`, `minSupportedVersionCode`, `apkUrl`,
  `sha256`, `notes`, `publishedAt`. No release is invented when absent;
  the endpoint returns 503. This API does not publish an APK.

Homework uses the existing feature flag, migrated canonical homework tables,
revision checks and administrator commit/reconciliation service.

Problem and solution byte responses include `X-Document-Page-Count`: `1` for
a PNG source, or the total PDF page count for a rendered page. The response
body remains PNG bytes. The solution fallback still returns the same-origin
302 ticket redirect followed by a second checked 302 to the upstream document.

## Submission authority

An assignment-date/student/test/round has one durable UUID reservation.
The result is committed before SQLite logs, JSON logs, tests JSON and
assignment progress are reconciled. Every compatibility append deduplicates
inside its own lock/transaction. Only a completed reconciliation returns
`ok: true, status: graded`. Repeating its UUID returns the saved result;
another UUID returns 409. The legacy catalog-test submission route shares
this authority regardless of the public feature flag, including
`name + score + wrong` without `answersText`. Score-only legacy reports retain
their existing response shape and are marked `gradingSource: legacy_reported`
in stored records; they are not represented as server grading invocations.
The public student route rejects non-catalog entries. Genuinely ad-hoc
administrative entries remain behind the existing administrator boundary.

`submission_pending` (503) means a result exists and the same UUID or result
GET can finish reconciliation without regrading. `submission_indeterminate`
(503) means the process died after its reservation but before the result
commit. Literal at-most-once invocation cannot be made atomic with Python
execution, so this state deliberately does not regrade automatically. Its
response includes `operatorActionRequired: true`. Use the supported authorized
reset below; changing progress or deleting a row by hand is not that protocol.

Existing pre-journal results remain visible, and their presence prevents
new grading. Results outside the academy contain scores and wrong question
numbers, not answer keys or question content.

## Authorized submission reset

These routes are never registered on the student public allowlist:

- `GET /api/admin/student-test-submissions?assignmentId=...` inspects the
  current client submission ID/state and prior reset audit summaries.
- `POST /api/admin/student-test-submissions/reset` accepts exactly
  `operationId` (UUIDv4), `assignmentId`, `expectedClientSubmissionId` and
  `reason` (nonempty, at most 500 characters).

Use the existing configured administrator HTTP Basic credentials from an
academy/local administrative connection, with the exact same Origin on
mutations. The public student host returns 404 even with administrator Basic
credentials. A student cookie cannot authorize either action. The verified
administrator username, not a body-supplied actor, is recorded in the audit.
The operator route remains usable during a public-app rollback/flag-off
period; that flag cannot turn local catalog writes into unjournaled records.

The administrator first inspects the assignment, reviews the uncertain or
completed outcome, then explicitly submits reset with that expected current
ID. Success returns `ok: true`, `status: reset`, `operationId`, `assignmentId`,
`previousClientSubmissionId`, `previousStatus`, `resetAt` and
`newClientSubmissionIdRequired: true`. Reuse the exact operation/body after a
lost response or interrupted cleanup. Changing its body returns 409
`idempotency_conflict`; a different action targeting a stale expected
submission returns 409 `submission_changed`.

Under the shared process gate, reset archives the original journal/result and
matching records from all compatibility stores, increments the assignment
generation and enters `resetting`. It removes only matching SQLite-log,
JSON-log and tests-JSON outcomes, reopens unchanged completed progress, and
revokes issued solution tickets. Intervening cancellation or metadata edits
are preserved. Only then does one transaction retire the current submission
and complete the operation. A crash or unavailable sink returns 503
`submission_reset_pending`; the same operator request resumes the stored
operation. No new student submission is admitted while cleanup is pending.

Already-running writers must leave the gate before reset can start.
Pre-reset requests queued outside it are generation-fenced, and late
grade/completion callbacks use client-ID/generation compare-and-set.
Retired UUIDs remain tombstoned by the audit; they cannot overwrite a newer
submission or be reused for another assignment.

After reset, the old UUID receives 409 `submission_reset` with
`newClientSubmissionIdRequired: true`. Result GET is 404 `not_submitted`
until a fresh UUID is explicitly submitted. The client must preserve answers,
replace only the expected draft UUID, and return to review; it must not
automatically resubmit or rotate UUIDs for arbitrary failures. The new UUID
may be graded once; subsequent different IDs conflict again. Replaying an
old completed reset operation returns its saved response without touching
the new generation.

## Isolated verification

`python scripts/student_app_v2_checks.py` runs real-store, concurrent and
process-interruption tests in a disposable source/data copy.
`--existing` runs the full existing student mobile suite there.
`--baseline` runs unchanged HEAD instead of the working tree.
`--refactor` runs the broader repository safety suite there.
`--reset` runs the reset/legacy identity, real-store, interruption and
forced-overlap HTTP checks. `--reset --baseline --revision <commit>` runs the
reproducer against that immutable product commit, copying only the reproducer.
`--manual` starts an owned localhost server on an OS-assigned port, executes
literal `curl.exe -i` requests and closes the listener in a finally block.
`--evidence <directory>` retains redacted logs outside temporary state.
