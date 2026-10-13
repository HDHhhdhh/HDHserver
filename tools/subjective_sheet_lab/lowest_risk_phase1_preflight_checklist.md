# Lowest-Risk Phase 1 OCR/Vision Preflight Checklist

Use this before any future code change. This checklist is intentionally stricter than the current lab gate.

## A. Scope Lock

- [ ] This is hidden/internal only.
- [ ] Production default remains no-go.
- [ ] Feature flag integration remains go-with-conditions only.
- [ ] No operating app files are modified during preflight.
- [ ] No Gemini/API call is made.
- [ ] No `/api/submit-test` call is made.
- [ ] No runtime data or DB files are modified.

## B. Stage 0 Read-Only Audit

- [ ] Inspect `static/student.html`.
- [ ] Inspect `static/js/student.js`.
- [ ] Record current `#openTestSubmit` behavior.
- [ ] Record dynamic modal creation path.
- [ ] Record exact `#tsAnswersText` location.
- [ ] Record exact `#tsSubmit` handler path.
- [ ] Record current `/api/submit-test` payload shape from code.
- [ ] Record current `?ocr=1` experimental behavior if present.
- [ ] Do not edit files.

## C. Stage 1 No-Op Flag Probe

- [ ] Feature detection is `?ocr=1` only.
- [ ] Feature off creates no OCR/Vision UI.
- [ ] Feature off creates no OCR/Vision network calls.
- [ ] Feature off changes no submit behavior.
- [ ] Feature off does not alter `#tsAnswersText`.
- [ ] No OCR button is added in Stage 1.
- [ ] No backend route is added in Stage 1.

## D. Stage 2 Mock-Only Button

- [ ] OCR button appears only with `?ocr=1`.
- [ ] Button text is `[답안지 사진으로 입력]`.
- [ ] Button is placed after `#tsAnswersText` area and before memo.
- [ ] Button opens mock review flow only.
- [ ] Mock flow uses local fixture only.
- [ ] No Gemini/API call.
- [ ] No backend OCR call.
- [ ] No `/api/submit-test` call from OCR code.
- [ ] Final mock payload only fills `#tsAnswersText`.
- [ ] Existing submit button is still manually pressed by user.

## E. Stage 3 Internal Route Only

- [ ] Route is hidden/internal.
- [ ] Route is disabled unless feature flag is on.
- [ ] Upload route returns review payload only.
- [ ] Retake route returns one updated item only.
- [ ] Finalize route returns `answersText` only.
- [ ] Route never calls `/api/submit-test`.
- [ ] Route never writes DB/runtime/student records.
- [ ] Route response excludes answer-key-only fields.

## F. Stage 4 Limited Internal Account Test

- [ ] Test account allowlist exists.
- [ ] `?ocr=1` is still required.
- [ ] Default students cannot access the flow.
- [ ] Logging/reporting excludes secrets and answer keys.
- [ ] Rollback by disabling feature flag is tested.

## G. Files Allowed Later

- [ ] `static/js/student.js`
- [ ] `static/css/student.css` only if needed
- [ ] New `routes/api_subjective_vision.py`
- [ ] New `core/subjective_sheet_pipeline.py`
- [ ] New `core/subjective_review_contract.py`
- [ ] New or adapted `core/subjective_review_policy.py`
- [ ] `app.py` only for blueprint registration if unavoidable

## H. Files Not Allowed

- [ ] Do not modify `routes/api_tests.py`.
- [ ] Do not modify `/api/submit-test`.
- [ ] Do not modify `tests.json`.
- [ ] Do not modify `tests-config.json`.
- [ ] Do not modify `students.json`.
- [ ] Do not modify `logs.json`.
- [ ] Do not modify `app.sqlite`.
- [ ] Do not modify `data/**`.
- [ ] Do not modify `/tests` management UI.
- [ ] Do not modify admin test management flow.

## I. Blocking Status Rules

- [ ] `review_required` blocks conversion until resolved.
- [ ] `retake_required` blocks conversion.
- [ ] `retake_uploaded` blocks conversion.
- [ ] `data_check_required` blocks conversion.
- [ ] Missing question blocks conversion.
- [ ] Duplicate question blocks conversion.
- [ ] Empty final answer blocks conversion.
- [ ] Answer with newline blocks conversion.

## J. No-Answer-Key-Leak Checks

Reject any student-facing output containing:

- [ ] `expected`
- [ ] `canonical_answer`
- [ ] `accepted_answers`
- [ ] raw answer key row
- [ ] raw provider payload
- [ ] `GEMINI_API_KEY`
- [ ] `AIza`
- [ ] `x-goog-api-key`
- [ ] `.env` value

## K. Feature-Off Regression Checks

- [ ] Default URL has no OCR/Vision button.
- [ ] Default URL has no OCR/Vision panel.
- [ ] Default modal still has `#tsType`.
- [ ] Default modal still has `#tsTestId`.
- [ ] Default modal still has `#tsRound`.
- [ ] Default modal still has `#tsAnswersText`.
- [ ] Default modal still has `#tsSubmit`.
- [ ] Existing submit payload shape is unchanged.
- [ ] No OCR/Vision fetch occurs.
- [ ] No new console error occurs.

## L. Failure Fallback Messages

- [ ] 429: `사진 인식 요청이 많습니다. 직접 입력으로 제출해 주세요.`
- [ ] 503: `사진 인식 서버가 일시적으로 불안정합니다. 직접 입력으로 제출해 주세요.`
- [ ] Marker failure: `답안지 전체와 네 모서리 마커가 보이게 다시 촬영해 주세요.`
- [ ] Crop failure: `일부 답안칸을 읽지 못했습니다. 직접 입력으로 제출해 주세요.`
- [ ] Invalid payload: `인식 결과를 확인할 수 없습니다. 직접 입력으로 제출해 주세요.`
- [ ] Contract failure: `인식 결과 검증에 실패했습니다. 직접 입력으로 제출해 주세요.`
- [ ] All failures keep manual input usable.
- [ ] All failures avoid automatic submit.

## M. Validation Commands

Run before future code change:

```powershell
python tools\subjective_sheet_lab\verify_ocr_benchmark_gate.py
python tools\subjective_sheet_lab\validate_ocr_review_contract.py
python tools\subjective_sheet_lab\verify_ocr_review_contract_negative.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
node --check static\js\student.js
git status --short
```

Run after future frontend-only change:

```powershell
node --check static\js\student.js
python tools\subjective_sheet_lab\validate_ocr_review_contract.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
```

Run after future backend route change:

```powershell
python -m py_compile app.py routes\api_subjective_vision.py core\subjective_sheet_pipeline.py core\subjective_review_contract.py core\subjective_review_policy.py
python tools\subjective_sheet_lab\validate_ocr_review_contract.py
python tools\subjective_sheet_lab\verify_ocr_review_contract_negative.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
node --check static\js\student.js
```

## N. Mobile Smoke

- [ ] Android Chrome default URL has no OCR UI.
- [ ] Android Chrome flagged URL can open mock/photo input.
- [ ] iOS Safari default URL has no OCR UI if supported.
- [ ] iOS Safari flagged URL can open mock/photo input if supported.
- [ ] Narrow viewport modal is usable.
- [ ] Student can abandon OCR and type manually.

## O. Submit Payload Compatibility

- [ ] OCR result fills `#tsAnswersText` only.
- [ ] OCR-filled `answersText` is one answer per line.
- [ ] A 20-question OCR result produces exactly 20 non-empty lines.
- [ ] Line 1 maps to q001 through line 20 maps to q020.
- [ ] OCR output does not use concatenated digit format.
- [ ] Multi-character answers such as `12`, `64`, and `42` remain intact as single lines.
- [ ] Existing handler reads `answersText` from `#tsAnswersText`.
- [ ] Existing handler sends `sid`.
- [ ] Existing handler sends `testId`.
- [ ] Existing handler sends `round`.
- [ ] Existing handler sends `memo`.
- [ ] OCR code does not call `/api/submit-test`.
- [ ] Existing `#tsSubmit` remains the only final save action.

## P. Rollback

- [ ] Disable `?ocr=1` usage or feature flag.
- [ ] Reload default student page.
- [ ] OCR/Vision button is gone.
- [ ] Existing submit modal still works.
- [ ] No DB migration needed.
- [ ] No runtime data repair needed.

## Q. Go/No-Go

- [ ] Go for Stage 0 read-only audit.
- [ ] Go for Stage 1 only if feature-off baseline is captured.
- [ ] No-go for Stage 2 until Stage 1 proves identical feature-off behavior.
- [ ] No-go for Stage 3 until mock-only Stage 2 passes.
- [ ] No-go for Stage 4 until internal route proves no-save/no-leak behavior.
