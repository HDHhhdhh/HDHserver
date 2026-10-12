# OCR Preflight Env Split Operator Runbook

Status: `environment_split_verified`

This runbook is lab-only. It does not modify `run_phase1_preflight_checks.py`,
operating routes, static UI, runtime JSON, DB files, tests-config, answer keys,
or student records.

## Current Evidence

Source reports:

- `tools/subjective_sheet_lab/ocr_preflight_environment_matrix.json`
- `tools/subjective_sheet_lab/ocr_preflight_failure_classifier.json`
- `tools/subjective_sheet_lab/ocr_preflight_report_freshness.json`
- `tools/subjective_sheet_lab/ocr_next_action_queue_state_verification.json`
- `tools/subjective_sheet_lab/ocr_next_action_queue_state_guard.json`
- `tools/subjective_sheet_lab/ocr_extended_gate_count_consistency.json`
- `tools/subjective_sheet_lab/ocr_training_pack_intake_only_command_checklist.json`
- `tools/subjective_sheet_lab/ocr_training_pack_intake_only_command_checklist_guard.json`
- `tools/subjective_sheet_lab/ocr_training_pack_standard_field_coverage.json`
- `tools/subjective_sheet_lab/ocr_training_pack_evidence_missing_blocker_snapshot.json`
- `tools/subjective_sheet_lab/ocr_training_pack_evidence_missing_blocker_snapshot_guard.json`
- `tools/subjective_sheet_lab/ocr_training_pack_evidence_prearrival_contract_gate.json`
- `tools/subjective_sheet_lab/ocr_training_pack_recognized_evidence_filename_diagnostics.json`
- `tools/subjective_sheet_lab/ocr_training_pack_partial_evidence_arrival_guard.json`
- `tools/subjective_sheet_lab/ocr_user_action_required_inventory.json`
- `tools/subjective_sheet_lab/ocr_user_action_required_inventory_guard.json`
- `tools/subjective_sheet_lab/ocr_provider_free_chain_manifest_consistency.json`
- `tools/subjective_sheet_lab/ocr_provider_free_chain_manifest_consistency_guard.json`
- `tools/subjective_sheet_lab/ocr_qa_start_here_freshness_guard.json`
- `tools/subjective_sheet_lab/ocr_qa_start_here_verification.json`
- `tools/subjective_sheet_lab/ocr_qa_start_here_rendered_summary.json`
- `tools/subjective_sheet_lab/ocr_qa_start_here_rendered_summary_guard.json`
- `tools/subjective_sheet_lab/ocr_provider_free_gate_chain_rendered_steps.json`
- `tools/subjective_sheet_lab/ocr_provider_free_gate_chain_rendered_steps_guard.json`
- `tools/subjective_sheet_lab/ocr_extended_gate_count_consistency_guard.json`
- `tools/subjective_sheet_lab/ocr_count_consistency_path_rendered_guard.json`
- `tools/subjective_sheet_lab/ocr_post_chain_guard_manifest.json`
- `tools/subjective_sheet_lab/ocr_post_chain_guard_manifest_guard.json`
- `tools/subjective_sheet_lab/ocr_post_chain_operator_summary.json`
- `tools/subjective_sheet_lab/ocr_post_chain_operator_summary_guard.json`
- `tools/subjective_sheet_lab/ocr_post_chain_operator_refresh.json`
- `tools/subjective_sheet_lab/ocr_post_chain_operator_refresh_guard.json`
- `tools/subjective_sheet_lab/ocr_post_chain_evidence_index.json`
- `tools/subjective_sheet_lab/ocr_post_chain_evidence_index_guard.json`
- `tools/subjective_sheet_lab/ocr_post_chain_evidence_handoff_runner.json`
- `tools/subjective_sheet_lab/ocr_post_chain_evidence_handoff_runner_guard.json`
- `tools/subjective_sheet_lab/ocr_post_chain_handoff_retention_manifest.json`
- `tools/subjective_sheet_lab/ocr_post_chain_handoff_retention_manifest_guard.json`
- `tools/subjective_sheet_lab/ocr_post_chain_cleanup_candidate_manifest.json`
- `tools/subjective_sheet_lab/ocr_post_chain_cleanup_candidate_manifest_guard.json`
- `tools/subjective_sheet_lab/ocr_preflight_operator_runbook_rendered_summary.json`
- `tools/subjective_sheet_lab/ocr_preflight_operator_runbook_rendered_summary_guard.json`
- `tools/subjective_sheet_lab/ocr_preflight_operator_runbook_consistency.json`
- `tools/subjective_sheet_lab/ocr_preflight_operator_runbook_consistency_guard.json`
- `tools/subjective_sheet_lab/ocr_provider_free_gate_chain.json`
- `tools/subjective_sheet_lab/ocr_provider_free_final_handoff_chain.json`
- `tools/subjective_sheet_lab/ocr_provider_free_final_handoff_chain_guard.json`
- `tools/subjective_sheet_lab/ocr_provider_free_handoff_status_card.json`
- `tools/subjective_sheet_lab/ocr_provider_free_handoff_status_card_guard.json`
- `tools/subjective_sheet_lab/ocr_provider_free_handoff_guard_common_self_check.json`
- `tools/subjective_sheet_lab/ocr_provider_free_manual_qa_handoff_refresh.json`
- `tools/subjective_sheet_lab/ocr_provider_free_manual_qa_handoff_refresh_guard.json`

Latest verified summary:

- `ok`: `true`
- `production_default`: `NO_GO`
- `extended_gate_count`: `85`
- `chain_step_count`: `29`
- `failed_step_count`: `0`
- `command_probe_count`: `4`
- `failing_command_count`: `0`
- `provider_call_count`: `0`
- `external_ocr_api_call_count`: `0`
- `submit_test_call_count`: `0`
- `ts_submit_click_count`: `0`
- `answer_key_or_grading_field_leak_count`: `0`
- `filesystem_path_leak_count`: `0`
- `preflight_script_modified`: `false`

## Why This Exists

Some OCR image checks require `C:\server-ocr\.venv` because that environment has
image-processing packages such as `numpy` and `cv2`.

Some app/route checks require `C:\server\venv` because that environment has
application dependencies such as `flask`.

Running all preflight checks under only one environment can create a false
failure. The matrix verifier proves the same checks pass when each check uses
the correct environment.

## Required Environment Split

Run image/OCR checks with:

```text
C:\server-ocr\.venv\Scripts\python.exe
```

Run app/route/import checks with:

```text
C:\server\venv\Scripts\python.exe
```

Do not edit `tools/subjective_sheet_lab/run_phase1_preflight_checks.py` unless
the user explicitly approves changing the preflight list.

## Operator Commands

From `C:\server`, refresh the complete provider-free manual-QA handoff:

```powershell
C:\server-ocr\.venv\Scripts\python.exe tools\subjective_sheet_lab\verify_ocr_provider_free_manual_qa_handoff_refresh.py
```

Expected full handoff refresh result:

```text
status = OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_READY
step_count = 9
failed_step_count = 0
common_self_check_status = OCR_PROVIDER_FREE_HANDOFF_GUARD_COMMON_SELF_CHECK_VERIFIED
status_card_manual_qa_handoff_status = READY
provider_call_count = 0
submit_test_call_count = 0
production_default = NO_GO
```

Expected full handoff refresh guard result:

```text
status = OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_GUARD_VERIFIED
probe_count = 12
failed_probe_count = 0
copied_common_self_check_step_blocked = true
copied_final_chain_step_blocked = true
copied_final_guard_step_blocked = true
copied_status_card_step_blocked = true
copied_status_card_guard_step_blocked = true
copied_missing_step_blocked = true
```

To refresh only the base provider-free evidence and compact handoff:

```powershell
C:\server-ocr\.venv\Scripts\python.exe tools\subjective_sheet_lab\verify_ocr_provider_free_final_handoff_chain.py
```

Expected chain result:

```text
ok = true
chain_step_count = 29
failed_step_count = 0
count_consistency_ok = true
```

Expected final handoff result:

```text
status = OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_VERIFIED
step_count = 3
failed_step_count = 0
handoff_guard_failed_probe_count = 0
```

Expected handoff status card result:

```text
status = OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_READY
manual_qa_handoff_status = READY
source_report_count = 2
stale_source_count = 0
failed_source_count = 0
```

Expected handoff status card guard result:

```text
status = OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_GUARD_VERIFIED
probe_count = 7
failed_probe_count = 0
copied_stale_guard_report_blocked = true
copied_nonzero_source_count_blocked = true
```

Expected classifier result:

```text
status = environment_split_verified
failing_command_count = 0
provider_call_count = 0
submit_test_call_count = 0
production_default = NO_GO
```

Expected freshness result:

```text
status = fresh_and_consistent
issue_count = 0
classifier_newer_than_matrix = true
counts_agree = true
zero_call_counts = true
zero_leak_counts = true
```

## Decision Rules

If the classifier status is `environment_split_verified`:

- Treat one-environment preflight failures as environment split issues until a
  specific probe contradicts that conclusion.
- Continue using the matrix gate for OCR lab readiness.
- Keep production default `NO_GO`.
- Do not call Gemini/API.
- Do not call `/api/submit-test`.
- Do not click or script `#tsSubmit`.

If the classifier status is `action_required`:

- Inspect the failed command probe in
  `tools/subjective_sheet_lab/ocr_preflight_environment_matrix.json`.
- Do not escalate to live OCR.
- Do not submit test answers.
- Record the blocker as `USER_APPROVAL_REQUIRED` only if fixing it needs a
  forbidden file, provider call, submit call, runtime data change, or production
  default change.

## Safety Invariants

- Gemini/API provider calls remain `0` unless a future prompt includes explicit
  process-local authorization and declared positive call budget.
- `/api/submit-test` calls remain `0`.
- `#tsSubmit` clicks remain `0`.
- Student-facing JSON must not contain answer-key, canonical-answer, grading, or
  local filesystem path fields.
- Existing benchmark recognized/cache files must not be overwritten without
  explicit benchmark-specific authorization.

## Next Safe Work

Provider-free next step:

- Run `verify_ocr_post_chain_operator_refresh.py` after future provider-free
  chain refreshes. It executes the eight standalone post-chain verifiers in order
  and writes one operator-facing summary so the rendered chain markdown stays
  locked to all 29 current steps, zero call/leak counts, production default
  `NO_GO`, the standalone post-chain guard commands/report paths remain visible,
  post-chain reports are fresh relative to the chain JSON, and copied stale
  metadata is blocked without touching live report files.
- Run `verify_ocr_post_chain_operator_refresh_guard.py` after the refresh
  wrapper when changing post-chain guard plumbing. It proves copied refresh rows
  with an exit failure or stale report state are blocked without running live
  provider calls or modifying live post-chain report files.
- Run `verify_ocr_post_chain_evidence_index.py` after the refresh wrapper and
  guard to emit the compact operator-facing post-chain status card for manual
  QA handoff.
- Run `verify_ocr_post_chain_evidence_index_guard.py` after the evidence index
  when changing compact handoff plumbing. It proves copied source reports with a
  bad status or non-zero failed count are blocked without modifying live
  post-chain reports.
- Run `verify_ocr_post_chain_evidence_handoff_runner.py` after the compact
  evidence index guard to regenerate the dependency-ordered compact handoff:
  common self-check -> freshness guard -> evidence index -> evidence index
  guard.
- Run `verify_ocr_post_chain_evidence_handoff_runner_guard.py` after the
  handoff runner when changing compact handoff plumbing. It proves copied bad
  step status, stale freshness status, and missing step scenarios are blocked
  without mutating live handoff artifacts.
- Prefer `verify_ocr_provider_free_final_handoff_chain.py` as the one-command
  operator refresh. It runs the provider-free gate chain first, then refreshes
  the compact handoff runner guard.
- Run `verify_ocr_provider_free_final_handoff_chain_guard.py` after final
  wrapper changes. It proves copied provider-free chain failure, copied handoff
  guard failure, and missing step scenarios are blocked without mutating live
  chain artifacts.
- Run `verify_ocr_provider_free_handoff_status_card.py` after the final wrapper
  and guard. It gives manual-QA operators a compact all-green handoff block and
  blocks stale final-wrapper evidence before live OCR approval.
- Run `verify_ocr_provider_free_handoff_status_card_guard.py` after the status
  card when changing compact handoff plumbing. It proves copied stale guard
  evidence, copied non-zero source counts, and copied non-zero source metrics
  block manual-QA handoff without mutating live status artifacts.
- Run `verify_ocr_post_chain_handoff_retention_manifest.py` after the evidence
  index and guard to separate canonical manual-QA handoff files from
  regenerated helper artifacts before cleanup or operator handoff.
- Run `verify_ocr_post_chain_handoff_retention_manifest_guard.py` after the
  retention manifest when changing cleanup or handoff plumbing. It proves copied
  artifact rows with a missing canonical handoff file or unsafe helper JSON are
  blocked without modifying live post-chain reports.
- Run `verify_ocr_post_chain_cleanup_candidate_manifest.py` after the retention
  manifest guard to list canonical handoff files to keep and regenerated helper
  artifacts that can be recreated. This is a read-only guide; it must not delete,
  move, or rewrite any listed artifact.
- Run `verify_ocr_post_chain_cleanup_candidate_manifest_guard.py` after the
  cleanup candidate manifest when changing cleanup guidance. It proves copied
  cleanup rows with `delete_allowed=true` or `move_allowed=true` are blocked
  without deleting, moving, or rewriting live artifacts.

Approval-required next step:

- Add this env split gate to `run_phase1_preflight_checks.py`. This is blocked
  until the user explicitly authorizes modifying that forbidden preflight file.
