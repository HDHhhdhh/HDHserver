# OCR Lab Artifact Retention And Cleanup Policy

## Purpose

This policy defines how OCR lab artifacts should be kept, archived, or deleted after Phase 2E work. It is a document-only policy. It does not authorize deletion, movement, code changes, provider calls, submission calls, or production default changes. Production default remains NO-GO.

## Artifact Categories

- `incoming_cases`: source full-sheet images captured for benchmark or lab intake.
- `crop_benchmark_inputs`: benchmark crop inputs and generated crop sets used for repeatable evaluation.
- `gemini_contact_review_assets`: contact sheets, enhanced crops, and review assets prepared for provider review.
- `gemini_outputs`: recognized outputs, human transcription outputs, evaluation outputs, benchmark reports, and phase reports.
- `phase2c_route_uploads`: route-generated crop/contact runtime folders from internal OCR review route testing.
- `phase2e_live_qa_cache`: Phase 2E live QA recognized cache files and route-specific live test artifacts.
- `backups`: explicit backup snapshots, copied reports, source artifacts, or rollback material.
- `reports`: markdown, JSON, CSV, and text reports created by OCR lab checks, phase QA, or benchmark evaluation.

## Keep Permanently

- Benchmark source images.
- `expected.json`.
- `human_transcription.json`.
- `recognized.json` used in benchmark reports.
- Evaluation reports.
- Canonical phase reports.

## Keep Temporarily

- Route-upload temp folders.
- Debug sheets.
- Synthetic test images.
- Failed-run scratch folders.

Temporary artifacts may be cleanup candidates only after they are confirmed not to be referenced by a current benchmark report, phase report, validator output, or QA record.

## Never Delete Without Explicit Approval

- `expected.json`.
- `human_transcription.json`.
- `recognized.json` used by a report.
- `backups`.
- Current canonical reports.

Explicit approval must identify the exact path or inventory row to delete. Broad approval such as "clean old OCR files" is not enough for protected artifacts.

## Safe Cleanup Candidates

- Duplicate temp upload folders.
- Synthetic test images.
- Obsolete debug artifacts.
- Cache files not referenced by any report.

Safe cleanup candidates still require explicit approval before deletion.

## Naming And Folder Rules

- Use `case_id` in generated folder names and reports.
- Separate benchmark folders from route runtime folders.
- Do not overwrite person_03/person_04 benchmark folders.
- Do not expose local filesystem paths to student JSON.
- Keep route runtime artifacts under clearly scoped route/runtime folders, not benchmark truth folders.
- Keep benchmark truth artifacts under the corresponding independent case folder.

## Cleanup Procedure

1. Inventory first.
2. Produce a dry-run list of cleanup candidates.
3. Check whether each candidate is referenced by reports, benchmark summaries, verifier outputs, or phase QA reports.
4. Create a backup if needed.
5. Delete only after explicit approval for the exact files or folders.
6. Write a cleanup report listing what was reviewed, what was deleted, what was kept, and why.

## Confirmation For This Policy Document

- no files deleted
- no files moved
- no code changes
- no Gemini/API call
- no /api/submit-test call
- no production default changes
- production default remains NO-GO
