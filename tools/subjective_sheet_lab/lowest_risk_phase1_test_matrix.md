# Lowest-Risk Phase 1 OCR/Vision Test Matrix

This matrix is for future validation. It must not call Gemini/API or `/api/submit-test` unless a row explicitly says a fake-account manual submit is being tested.

## Legend

- Flag off: `/student/<sid>`
- Flag on: `/student/<sid>?ocr=1`
- Manual submit: existing `#tsSubmit`
- OCR code: any new OCR/Vision button, mock flow, or internal route

## Stage 0: Read-Only Audit Matrix

| ID | Surface | Setup | Action | Expected | Must Not Happen |
|---|---|---|---|---|---|
| S0-01 | Source | `static/student.html` | Inspect only | Student shell and `#openTestSubmit` identified | File edit |
| S0-02 | Source | `static/js/student.js` | Inspect only | `ensureModal()` and `#tsAnswersText` insertion point identified | File edit |
| S0-03 | Source | `static/js/student.js` | Inspect submit handler | `POST /api/submit-test` payload shape documented | Endpoint call |
| S0-04 | Source | `static/js/student.js` | Inspect feature flag | Existing `?ocr=1` behavior documented if present | Behavior change |

## Stage 1: No-Op Feature Flag Probe Matrix

| ID | Surface | Setup | Action | Expected | Must Not Happen |
|---|---|---|---|---|---|
| S1-01 | Browser DOM | Flag off | Load student page | No OCR/Vision button | OCR DOM appears |
| S1-02 | Browser DOM | Flag off | Open submit modal | Modal contains `#tsType`, `#tsTestId`, `#tsRound`, `#tsAnswersText`, `#tsSubmit` | New OCR panel appears |
| S1-03 | Browser network | Flag off | Open submit modal | No OCR/Vision request | `/api/ocr-test-sheet` or internal route call |
| S1-04 | JS behavior | Flag off | Type in `#tsAnswersText` | Textarea behavior unchanged | Value overwritten |
| S1-05 | Console | Flag off | Load and open modal | No new console error | OCR initialization error |

## Stage 2: Hidden OCR Button With Mock Only Matrix

| ID | Surface | Setup | Action | Expected | Must Not Happen |
|---|---|---|---|---|---|
| S2-01 | Browser DOM | Flag off | Open modal | OCR button absent | OCR button visible |
| S2-02 | Browser DOM | Flag on | Open modal | `[답안지 사진으로 입력]` visible after answer textarea | Direct textarea hidden |
| S2-03 | Mock flow | Flag on | Click OCR button | Mock review opens | Gemini/API call |
| S2-04 | Mock flow | Flag on with safe-only payload | Apply mock final payload | Ordered answers fill `#tsAnswersText` | `/api/submit-test` call |
| S2-05 | Mock flow | Flag on with `review_required` | Try final conversion | Conversion blocked | Partial answers filled as final |
| S2-06 | Mock flow | Flag on with `retake_required` | Try final conversion | Conversion blocked | Retake item accepted as final |
| S2-07 | Mock flow | Flag on with `retake_uploaded` | Try final conversion | Conversion blocked | Uploaded retake accepted as final |
| S2-08 | Mock flow | Flag on with `data_check_required` | Try final conversion | Conversion blocked | Student edits data-check into final |
| S2-09 | Leak check | Flag on | Inspect DOM/network/console | No answer-key-only fields | `expected`, `canonical_answer`, or `accepted_answers` appears |
| S2-10 | Fallback | Flag on | Close mock flow | Manual `#tsAnswersText` remains usable | Manual submit path disabled |

## Stage 3: Internal Route Only Matrix

| ID | Surface | Setup | Action | Expected | Must Not Happen |
|---|---|---|---|---|---|
| S3-01 | API | Feature disabled | POST upload route | JSON `feature_disabled` | Record save |
| S3-02 | API | Feature enabled, no image | POST upload route | JSON invalid request | Server crash |
| S3-03 | API | Feature enabled, mock/local image | POST upload route | Review payload only | `/api/submit-test` call |
| S3-04 | API | Feature enabled, retake image | POST retake route | One updated item only | DB write |
| S3-05 | API | Final payload unresolved | POST finalize route | Blocking JSON error | `answersText` returned |
| S3-06 | API | Final payload resolved | POST finalize route | `answersText` returned | Student record saved |
| S3-07 | Leak check | Any API response | Scan response | No answer-key-only fields | Secret or answer-key leak |

## Stage 4: Limited Internal Account Test Matrix

| ID | Surface | Setup | Action | Expected | Must Not Happen |
|---|---|---|---|---|---|
| S4-01 | Access | Non-allowlisted account, flag on | Open modal | OCR unavailable or hidden | OCR flow available |
| S4-02 | Access | Allowlisted test account, flag off | Open modal | OCR hidden | OCR visible |
| S4-03 | Access | Allowlisted test account, flag on | Open modal | OCR visible | Manual input hidden |
| S4-04 | End-to-end without save | Allowlisted test account | Complete OCR review | `#tsAnswersText` filled | Auto-submit |
| S4-05 | Manual fake submit only | Fake account, explicit submit test | Press existing `#tsSubmit` | Existing submit payload shape used | OCR code calls submit |
| S4-06 | Reporting | Allowlisted test account | Complete OCR review | Sanitized report only | API key, `.env`, answer key in report |
| S4-07 | Rollback | Disable flag | Reload page | OCR hidden, manual flow works | Data migration required |

## Failure Handling Matrix

| ID | Failure | Expected Message | Expected State |
|---|---|---|---|
| F-01 | Gemini 429 | `사진 인식 요청이 많습니다. 직접 입력으로 제출해 주세요.` | Manual input usable, no retry loop |
| F-02 | Gemini 503 | `사진 인식 서버가 일시적으로 불안정합니다. 직접 입력으로 제출해 주세요.` | Manual input usable, no retry loop |
| F-03 | Marker failure | `답안지 전체와 네 모서리 마커가 보이게 다시 촬영해 주세요.` | Whole-sheet retake, no review payload |
| F-04 | Crop failure | `일부 답안칸을 읽지 못했습니다. 직접 입력으로 제출해 주세요.` | No save, fallback available |
| F-05 | Invalid payload | `인식 결과를 확인할 수 없습니다. 직접 입력으로 제출해 주세요.` | No render, no save |
| F-06 | Contract failure | `인식 결과 검증에 실패했습니다. 직접 입력으로 제출해 주세요.` | No `answersText` fill |

## Mobile Smoke Matrix

| ID | Device | URL | Action | Expected |
|---|---|---|---|---|
| M-01 | Android Chrome | Flag off | Open submit modal | No OCR UI |
| M-02 | Android Chrome | Flag on | Tap OCR button | Mock/photo input opens |
| M-03 | Android Chrome | Flag on | Return from OCR flow | `#tsAnswersText` usable |
| M-04 | iOS Safari if supported | Flag off | Open submit modal | No OCR UI |
| M-05 | iOS Safari if supported | Flag on | Tap OCR button | Mock/photo input opens |
| M-06 | Narrow viewport | Flag on | Review mock payload | Cards fit and actions remain visible |

## Submit Compatibility Matrix

| ID | Setup | Action | Expected |
|---|---|---|---|
| C-01 | Manual input only | Type answers | `#tsAnswersText` retains user text |
| C-02 | Mock OCR final payload | Apply to modal | `#tsAnswersText` gets ordered newline-separated answers |
| C-03 | Mock OCR after apply | Edit textarea manually | Existing textarea accepts edits |
| C-04 | Existing submit handler inspected | Build payload | `{ sid, testId, round, answersText, memo }` shape preserved |
| C-05 | OCR code path inspected | Search calls | OCR code does not call `/api/submit-test` |

## Required Evidence Per Test Run

- Screenshot or DOM snapshot for feature-off and feature-on modal.
- Network log proving no OCR route on feature-off.
- Console log screenshot or exported console check.
- Sanitized response samples for internal route tests.
- `answersText` sample after final conversion.
- `git status --short` showing only intended files changed.
