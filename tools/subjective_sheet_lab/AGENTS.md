# OCR LAB KNOWLEDGE BASE

## Overview
Safety-critical, mostly ignored local workspace for subjective-answer OCR review. It is a flat script lab, not a package: Phase 2C crops, Phase 2D cache, gated Phase 2E Gemini, then Phase 2F local Paddle fallback.

## Scope And Search
- Normal Git status does not reveal most new or changed lab files because `tools/subjective_sheet_lab/` is ignored; report tracked versus ignored/local changes explicitly.
- Exclude `_qa_tmp/`, `backups/`, `ui_smoke_artifacts/`, `visual_evidence/`, caches, and `__pycache__/` from broad searches. `_qa_tmp/` contains copied apps/environments and tens of thousands of files.
- No nested AGENTS scope is warranted; subdirectories are artifacts, caches, backups, or evidence rather than source domains.

## Runtime Map
| Stage | Location | Contract |
|---|---|---|
| Production boundary | `routes/api_non_student_ocr.py` only | Internal captured-cache route is separate; student submit/OCR routes and UI are retired. |
| Phase 2C | `phase2c_crop_pipeline_*.py` | Calls hard-coded `C:/server-ocr` tools and writes route/crop artifacts. |
| Phase 2D | `phase2d_cached_review_payload_adapter.py` | Cache-first payload reconstruction and leak checks. |
| Phase 2E | `phase2e_gemini_live_ocr_adapter.py`, `phase2e_live_provider_runner.py`, `gemini_provider.py` | Fail-closed authorization/cache gates and live HTTP boundary. |
| Phase 2F | `phase2f_local_paddle_review_adapter.py` | Local OCR fallback; outputs remain `review_required`. |
| Policy/schema | `ocr_review_schema.py`, `ocr_review_payload_validator.py` | Status, source, unresolved, and answer-key/path-leak contracts. |
| Evaluation | `human_transcription_eval.py`, `ocr_benchmark_gate.py` | Key-free human-transcription comparison and readiness gate. |

## Default Posture
- Explicitly requested code maintenance inside the lab is allowed. It does not authorize provider calls, benchmark writes, route/UI changes, or runtime-data access.
- Gemini/API/provider calls are forbidden by default; call budget is `0`.
- A live call requires the current user message to contain process-local authorization and a positive maximum call budget. Never exceed it; report actual calls.
- Production integration default is `NO-GO`. Benchmark/provider work must not change production routes, student UI, grading, submit behavior, DB, or runtime JSON.

## Absolute No-Go
- Do not add, restore, call, or smoke-test student submission/OCR routes or UI. They are retired; the lab may use only its separately authorized non-student cache boundary.
- Do not use answer keys, expected/canonical answers, or grading fields to infer OCR output.
- Do not put answer-key data or local filesystem paths into provider prompts, recognized output, student-facing JSON, or student reports.
- Do not run browser automation capable of submitting tests.
- For benchmark/eval work, do not edit `app.py`, `routes/api_tests.py`, `static/js/student.js`, `run_phase1_preflight_checks.py`, root runtime JSON/SQLite/sidecars, `_data_mirror/`, `data/`, `instance/`, `files/`, benchmark inputs, or `C:/server-ocr/**/{expected,canonical*,grading*}.json`.

## Artifact And Provider Rules
- Benchmark inputs are read-only. Write `recognized.json` only for an explicitly authorized person/output and never inside an input folder.
- Leak-audit provider inputs before any call. Gemini diagnostics/caches are internal because they may retain full local paths.
- Use `human_transcription.json` for key-free evaluation. Answer-key grading requires separate explicit authorization.
- Erased, crossed-out, overwritten, multiple, ambiguous, or unclear answers are `review_required` or `retake_required`, never `safe_auto_grade`.
- The environment gate can be opened by process configuration; do not assume the adapter itself proves user authorization. Configured call limits are not a substitute for counting actual requests.

## Verification And Commands
- Standalone `verify_*.py` / `verify_*.js` files are the test model; there is no pytest/Jest discovery or dependency manifest.
- `run_ocr_regression_suite.py --quick|--full` writes JSON/Markdown reports. `run_phase1_preflight_checks.py` launches subprocess/Chrome checks and writes under `C:/server-ocr`; neither is read-only.
- Main runners cover only a subset of verifiers. Skipped/missing checks and `verify_cached_ocr_regression_suite.py` can still yield success; inspect produced case counts and failure records.
- Do not invoke external OCR/provider/browser/report-producing commands unless the user authorized that exact action and output scope.

## Benchmark Report
- Report `현재 준비됨`, `막힘`, and `Gemini 호출 전에 필요한 것` when applicable.
- Include declared and actual provider-call counts, artifact paths, answer-key/path leak results, unsafe `safe_auto_grade` counts, and confirmation that submit/UI/runtime data were untouched.
