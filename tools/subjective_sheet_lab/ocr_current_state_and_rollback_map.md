# OCR Current State And Rollback Map

Date: 2026-06-30 KST

Scope: report-only snapshot for coordinating parallel OCR work. This file records the current evidence-based OCR state and rollback references. It does not implement Phase 2E, does not call Gemini/API, does not call `/api/submit-test`, does not click `#tsSubmit`, does not change environment variables, and does not modify operating app data/config.

## 1. Current Canonical Baseline

Current canonical OCR baseline: **Phase 2D cached recognized/review-payload route-backed baseline**.

Observed current route/client flow from the working tree and phase reports:

```text
?ocr=1 + allowlisted test/round
-> student.js sends multipart FormData to /api/ocr-test-sheet-review
-> route checks disabled default, sid, ghost sid, test id, round, image type, image size
-> Phase 2C crop/contact pipeline runs
-> Phase 2D cache lookup runs
-> cache hit returns a student-safe review_payload
-> cache miss/disabled/malformed/forbidden falls back safely
-> Phase 2E skeleton may be consulted after Phase 2D cache miss
-> review UI fills #tsAnswersText only after review/fill
-> final submit remains the existing #tsSubmit -> /api/submit-test path
```

Important baseline properties:

- Production default remains **NO-GO**.
- `/api/ocr-test-sheet-review` remains gated by `OCR_PHASE2_REVIEW_ROUTE_ENABLED`.
- OCR remains behind `?ocr=1` and the allowlisted test/round guard.
- Current allowlist target is `t_unit_daesu_01_lv3_r1` / round `1`.
- Phase 2D is separately gated by `OCR_PHASE2D_CACHED_REVIEW_ENABLED`.
- Recognized-only cache is converted to `review_required`; it is not treated as safe auto-grade.
- The OCR review route must not call `/api/submit-test`.
- The OCR/provider path must not read or expose answer keys.

## 2. Current Live-Call Status

Current live-call status: **Phase 2E limited live Gemini QA may be pending/running in another session, but the production default remains NO-GO**.

Evidence from current files:

- `tools/subjective_sheet_lab/phase2e_gemini_live_ocr_call_plan.md` is complete as the design-only plan.
- `tools/subjective_sheet_lab/phase2e_implementation_readiness_checklist.md` is complete as the readiness checklist.
- `tools/subjective_sheet_lab/phase2e_gemini_live_ocr_adapter.py` exists as a skeleton.
- `tools/subjective_sheet_lab/phase2e_live_ocr_manual_qa_runbook.md` exists as the future live-QA runbook.
- Current Phase 2E adapter markers show disabled-by-default flags and a skeleton result path:
  - `OCR_PHASE2E_GEMINI_LIVE_ENABLED`
  - `OCR_PHASE2E_CACHE_WRITE_ENABLED`
  - `OCR_PHASE2E_LOCAL_ONLY`
  - `OCR_PHASE2E_PROVIDER_CALLS_REQUIRE_CACHE_MISS`
  - `OCR_PHASE2E_MAX_PROVIDER_CALLS_PER_REQUEST`
  - `OCR_PHASE2E_FAIL_CLOSED_ON_PROVIDER_ERROR`
  - `OCR_PHASE2E_PROVIDER_CALLS_ALLOWED`
  - provider call attempted: `False`
  - provider call count: `0`
  - current implemented live path result: `skeleton_no_provider_call`

Coordination note: if another session is performing limited live Gemini QA, treat its runtime artifacts and logs as external current-state evidence. Do not assume those artifacts are disposable.

## 3. Key Dirty Files Currently Expected

Current scoped status observed on 2026-06-30:

```text
 M routes/api_tests.py
 M static/js/student.js
?? tools/subjective_sheet_lab/run_phase1_preflight_checks.py
?? tools/subjective_sheet_lab/phase2c_crop_pipeline_adapter.py
?? tools/subjective_sheet_lab/phase2d_cached_review_payload_adapter.py
?? tools/subjective_sheet_lab/phase2e_gemini_live_ocr_adapter.py
```

Other dirty/untracked files also exist in the worktree, including non-OCR-looking files such as `core/admin_chat.py`, `scripts/verify_refactor_safety.py`, `.omo/teams/`, and several lab reports. Those should be treated as concurrent work unless a session explicitly owns them.

Expected OCR-related dirty files:

- `routes/api_tests.py`
  - Contains the internal `/api/ocr-test-sheet-review` route stack.
  - Includes Phase 2A route gate and allowlist, Phase 2B image validation, Phase 2C crop/contact pipeline call, Phase 2D cache hook, and Phase 2E skeleton hook after Phase 2D cache miss.
- `static/js/student.js`
  - Contains the `?ocr=1` hidden UI, allowlisted OCR controls, image upload/FormData route call, review UI, answer-mode validation, and `#tsAnswersText` fill behavior.
  - Must not be casually reverted because it carries Phase 2B route-backed UI plus later review/fill safety behavior.
- `tools/subjective_sheet_lab/run_phase1_preflight_checks.py`
  - Present as an untracked lab verifier/preflight harness.
  - Phase reports indicate it was updated across Phase 2A/2B/2C to count `/api/ocr-test-sheet-review`, image-bearing calls, and route-backed behavior.

## 4. Major Report Files By Phase

Cross-cutting and baseline/audit reports:

- `tools/subjective_sheet_lab/ocr_phase_state_reconciliation_audit.md`
- `tools/subjective_sheet_lab/ocr_production_readiness_evidence_summary.md`
- `tools/subjective_sheet_lab/ocr_next_action_queue.md`
- `tools/subjective_sheet_lab/ocr_review_payload_contract.md`
- `tools/subjective_sheet_lab/answersText_parser_rule_audit.md`
- `tools/subjective_sheet_lab/answersText_newline_output_policy_report.md`
- `tools/subjective_sheet_lab/final_review_payload_bridge_report.md`

Phase 1 / Phase 1.5:

- `tools/subjective_sheet_lab/phase1_manual_qa_runbook.md`
- `tools/subjective_sheet_lab/phase1_manual_qa_result_report.md`
- `tools/subjective_sheet_lab/phase1_hidden_integration_verification.md`
- `tools/subjective_sheet_lab/phase1_ocr_eligibility_guard_report.md`
- `tools/subjective_sheet_lab/phase1_5_ui_safety_patch_report.md`

Phase 2A:

- `tools/subjective_sheet_lab/phase2_internal_ocr_route_stub_plan.md`
- `tools/subjective_sheet_lab/phase2a_internal_ocr_route_stub_report.md`
- `tools/subjective_sheet_lab/phase2a_client_route_wiring_fix_report.md`
- `tools/subjective_sheet_lab/phase2a_route_stub_manual_qa_report.md`

Phase 2B:

- `tools/subjective_sheet_lab/phase2b_image_upload_stub_report.md`

Phase 2C:

- `tools/subjective_sheet_lab/phase2c_crop_pipeline_integration_plan.md`
- `tools/subjective_sheet_lab/phase2c_crop_pipeline_connection_report.md`

Phase 2D:

- `tools/subjective_sheet_lab/phase2d_cached_review_payload_connection_report.md`
- `tools/subjective_sheet_lab/phase2d_canonicalization_report.md`

Phase 2E:

- `tools/subjective_sheet_lab/phase2e_gemini_live_ocr_call_plan.md`
- `tools/subjective_sheet_lab/phase2e_implementation_readiness_checklist.md`
- `tools/subjective_sheet_lab/phase2e_gemini_live_ocr_adapter_skeleton_report.md`
- `tools/subjective_sheet_lab/phase2e_live_ocr_manual_qa_runbook.md`

Benchmark and handwriting evidence:

- `tools/subjective_sheet_lab/person_03_recognized_eval_report.md`
- `tools/subjective_sheet_lab/person_03_q016_q017_miss_analysis.md`
- `tools/subjective_sheet_lab/person_04_benchmark_intake_plan.md`
- `tools/subjective_sheet_lab/additional_human_transcription_benchmark_report.md`

## 5. Runtime Artifact Locations

Do not edit or delete these from unrelated sessions.

| Location | Current observed state | Purpose |
| --- | ---: | --- |
| `C:\server-ocr\phase2c_route_uploads\` | exists; observed 521 directories / 4316 files | Phase 2C route upload runtime cases, crop outputs, review contact assets, manifests. |
| `C:\server-ocr\gemini_outputs\` | exists; observed 21 directories / 176 files | Gemini/cached OCR outputs, recognized JSON, evaluation outputs, Phase 1 preflight reports, benchmark reports. |
| `C:\server-ocr\crop_benchmark_inputs\` | exists; observed 21 directories / 242 files | Benchmark crop cases, expected files, warped sheets, overlays, q001-q020 crops. |

Additional OCR runtime/verifier locations observed:

- `C:\server-ocr\phase2d_cache_verifier\`
- `C:\server-ocr\phase2e_adapter_verifier\`
- `C:\server-ocr\gemini_contact_review_assets\`
- `C:\server-ocr\incoming_cases\`
- `C:\server-ocr\test_assets\`

Runtime cleanup rule: remove generated runtime artifacts only with explicit ownership and approval. Benchmark inputs, human transcriptions, recognized outputs, and live-QA evidence may be needed for audit.

## 6. Known Backups, If Discoverable

Discovered backup directory:

- `tools/subjective_sheet_lab/backups\`

Discovered backup files/directories:

- `tools/subjective_sheet_lab/backups/logs.20260629T032137Z.before_phase1_accidental_submit_cleanup.json`
- `tools/subjective_sheet_lab/backups/tests.20260629T032137Z.before_phase1_accidental_submit_cleanup.json`
- `tools/subjective_sheet_lab/backups/progress.2026-06-29.before_phase1_temp_qa_assignment.json`
- `tools/subjective_sheet_lab/backups/progress.2026-06-29.current_before_phase1_temp_qa_assignment.json`
- `tools/subjective_sheet_lab/backups/phase1_accidental_submit_cleanup-20260629-122220/`
- `tools/subjective_sheet_lab/backups/phase1_accidental_submit_cleanup-20260629-122220/app.sqlite`
- `tools/subjective_sheet_lab/backups/phase1_accidental_submit_cleanup-20260629-122220/logs.json`
- `tools/subjective_sheet_lab/backups/phase1_accidental_submit_cleanup-20260629-122220/tests.json`
- `tools/subjective_sheet_lab/backups/phase1_accidental_submit_cleanup-20260629-122220/manifest.json`

Patch/snapshot references:

- `tools/subjective_sheet_lab/phase1_hidden_integration_patch.patch`
- `tools/subjective_sheet_lab/phase1_worktree_status_snapshot.txt`
- `tools/subjective_sheet_lab/student_js_dirty_diff_snapshot.patch`
- `tools/subjective_sheet_lab/student_js_phase1_current_dirty_snapshot.patch`

No `backup`-named paths were observed under `C:\server-ocr` at max depth 3 during this snapshot.

## 7. Rollback Strategy By Phase

Rollback here means restoring a previous phase behavior intentionally. It does not mean deleting concurrent work or runtime evidence casually.

### Phase 2E Skeleton

Current ownership:

- `routes/api_tests.py`
  - Phase 2E skeleton is consulted after Phase 2D cache miss.
- `tools/subjective_sheet_lab/phase2e_gemini_live_ocr_adapter.py`
- `tools/subjective_sheet_lab/verify_phase2e_gemini_live_ocr_adapter.py`
- `tools/subjective_sheet_lab/phase2e_gemini_live_ocr_adapter_skeleton_report.md`
- `tools/subjective_sheet_lab/phase2e_gemini_live_ocr_call_plan.md`
- `tools/subjective_sheet_lab/phase2e_implementation_readiness_checklist.md`
- `tools/subjective_sheet_lab/phase2e_live_ocr_manual_qa_runbook.md`

Minimal rollback target:

- Disable all Phase 2E flags:
  - `OCR_PHASE2E_GEMINI_LIVE_ENABLED=false`
  - `OCR_PHASE2E_PROVIDER_CALLS_ALLOWED=false`
  - `OCR_PHASE2E_LOCAL_ONLY=true`
  - `OCR_PHASE2E_CACHE_WRITE_ENABLED=false`
- Keep Phase 2D as canonical baseline.
- If code rollback is explicitly requested, remove only the Phase 2E route hook and the Phase 2E adapter/verifier files.
- Do not touch `/api/submit-test`.
- Do not delete live-QA artifacts unless the live-QA owner approves cleanup.

Risk if reverted blindly:

- May erase the documented safety gates and call-count/fail-closed skeleton needed before live Gemini work.
- May conflict with another session running limited Phase 2E QA.

### Phase 2D Cache Hook

Current ownership:

- `routes/api_tests.py`
  - Phase 2D cache lookup after Phase 2C success, before Phase 2E skeleton.
- `tools/subjective_sheet_lab/phase2d_cached_review_payload_adapter.py`
- `tools/subjective_sheet_lab/verify_phase2d_cached_review_payload_route.py`
- `tools/subjective_sheet_lab/phase2d_cached_review_payload_connection_report.md`
- `tools/subjective_sheet_lab/phase2d_canonicalization_report.md`

Minimal rollback target:

- Disable `OCR_PHASE2D_CACHED_REVIEW_ENABLED`.
- Route should fall back to the Phase 2A mock review payload after Phase 2C success.
- If code rollback is explicitly requested, remove only the Phase 2D import/call/replacement branch and adapter/verifier files.
- Preserve Phase 2C crop/contact route behavior unless the rollback target is earlier than Phase 2C.

Risk if reverted blindly:

- Removes the current canonical baseline.
- Breaks cache-first behavior required before Phase 2E live-provider calls.
- Can make later live QA less safe because cache hit paths would no longer prevent provider calls.

### Phase 2C Crop Route

Current ownership:

- `routes/api_tests.py`
  - Phase 2C crop/contact call after image validation.
- `tools/subjective_sheet_lab/phase2c_crop_pipeline_adapter.py`
- `tools/subjective_sheet_lab/verify_phase2c_crop_pipeline_route.py`
- `tools/subjective_sheet_lab/phase2c_crop_pipeline_connection_report.md`
- Runtime artifacts under `C:\server-ocr\phase2c_route_uploads\`.

Minimal rollback target:

- Disable `OCR_PHASE2_REVIEW_ROUTE_ENABLED` to prevent new route calls.
- If code rollback is explicitly requested, remove the Phase 2C adapter import/call and return to Phase 2B image-validation-only mock payload behavior.
- Do not delete `C:\server-ocr\phase2c_route_uploads\` without approval; it contains route QA evidence and possible parallel-session artifacts.

Risk if reverted blindly:

- Phase 2D and Phase 2E lose their required crop/contact input source.
- Verifiers depending on real crop/contact artifacts will fail.
- Concurrent live-QA sessions may lose evidence or expected runtime folders.

### Phase 2B Upload UI

Current ownership:

- `static/js/student.js`
  - Image upload control, FormData route call, review panel, answer-mode validation, and `#tsAnswersText` fill behavior.
- `routes/api_tests.py`
  - Image file validation: `image`, jpg/jpeg/png/webp, MIME type, 8 MiB cap.
- `tools/subjective_sheet_lab/run_phase1_preflight_checks.py`
- `tools/subjective_sheet_lab/verify_phase2a_internal_ocr_route_stub.py`
- `tools/subjective_sheet_lab/phase2b_image_upload_stub_report.md`

Minimal rollback target:

- Hide OCR by removing `?ocr=1` from manual QA URLs or disabling route flags.
- If code rollback is explicitly requested, revert image upload/FormData UI and route image-validation additions together.
- Preserve manual `#tsAnswersText` and existing submit behavior.

Risk if reverted blindly:

- Can break current route-first OCR review UI and preflight expectations.
- Can accidentally return to mock-only assumptions that conflict with Phase 2D.
- Can remove answer-mode validation and 20-line fill safety in `student.js`.

## 8. What Must Not Be Reverted Casually

- `routes/api_tests.py` OCR route stack, because it now carries Phase 2A through Phase 2E coordination points.
- `static/js/student.js` OCR review/fill code, because it includes route-first behavior, image upload, answer-mode validation, leak checks, and `#tsAnswersText` safety.
- `tools/subjective_sheet_lab/run_phase1_preflight_checks.py`, because reports indicate it tracks route-backed preflight behavior.
- Phase 2C/2D/2E adapter and verifier files, because they define current lab contracts.
- `C:\server-ocr\phase2c_route_uploads\`, because it contains generated route case evidence.
- `C:\server-ocr\gemini_outputs\`, because it contains recognized caches, evaluations, preflight reports, and possible live-QA evidence.
- `C:\server-ocr\crop_benchmark_inputs\`, because it contains benchmark source crops and expected files.
- Any files in `tools/subjective_sheet_lab/backups\`, because they are the discovered rollback/audit backup references.
- Any unrelated dirty files from other sessions, including non-OCR app files, unless explicitly owned.

## 9. What Must Not Be Touched By Unrelated Sessions

Unrelated sessions must not modify:

- `app.py`
- `routes/`, especially `routes/api_tests.py`
- `static/`, especially `static/js/student.js`
- `data/`
- DB files
- `tests-config.json`
- answer keys
- student records
- progress/logs/tests runtime data
- `C:\server-ocr\phase2c_route_uploads\`
- `C:\server-ocr\gemini_outputs\`
- `C:\server-ocr\crop_benchmark_inputs\`
- `C:\server-ocr\gemini_contact_review_assets\`
- Phase 2E live-QA artifacts or logs if another session is running provider QA

Coordination rule: a session that only needs a report should add a new report under `tools/subjective_sheet_lab/` and should not run verifiers that regenerate runtime artifacts unless explicitly requested.

## 10. Confirmation For This Snapshot Task

This snapshot task made:

- no operating app code changes
- no `app.py` changes
- no `routes/` changes
- no `static/` changes
- no `static/js/student.js` changes
- no `data/` changes
- no DB changes
- no `tests-config.json` changes
- no answer-key changes
- no student-record changes
- no progress/logs/tests runtime data changes
- no Gemini/API calls
- no `/api/submit-test` calls
- no /api/submit-test calls
- no `#tsSubmit` click
- no environment variable changes
- no Phase 2E implementation

Only this report file was added:

- `tools/subjective_sheet_lab/ocr_current_state_and_rollback_map.md`
