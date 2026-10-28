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

## Submission authority

An assignment-date/student/test/round has one durable UUID reservation.
The result is committed before SQLite logs, JSON logs, tests JSON and
assignment progress are reconciled. Every compatibility append deduplicates
inside its own lock/transaction. Only a completed reconciliation returns
`ok: true, status: graded`. Repeating its UUID returns the saved result;
another UUID returns 409. The legacy catalog-test submission route shares
this authority when the public application is enabled, preserving its
successful response fields. Legacy ad-hoc administrative score entries
without a catalog identity are not native assignments.

`submission_pending` (503) means a result exists and the same UUID or result
GET can finish reconciliation without regrading. `submission_indeterminate`
(503) means the process died after its reservation but before the result
commit. Literal at-most-once invocation cannot be made atomic with Python
execution, so this state deliberately does not regrade automatically.
Resolve it through authorized operator maintenance; do not delete a journal
row merely because a compatibility sink is missing. Any administrator reset
must explicitly include the journal identity and matching compatibility
records. Changing progress alone is not a reset and cannot bypass the ledger.

Existing pre-journal results remain visible, and their presence prevents
new grading. Results outside the academy contain scores and wrong question
numbers, not answer keys or question content.

## Isolated verification

`python scripts/student_app_v2_checks.py` runs real-store, concurrent and
process-interruption tests in a disposable source/data copy.
`--existing` runs the full existing student mobile suite there.
`--baseline` runs unchanged HEAD instead of the working tree.
`--refactor` runs the broader repository safety suite there.
`--manual` starts an owned localhost server on an OS-assigned port, executes
literal `curl.exe -i` requests and closes the listener in a finally block.
`--evidence <directory>` retains redacted logs outside temporary state.
