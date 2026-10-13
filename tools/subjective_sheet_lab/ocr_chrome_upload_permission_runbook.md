# Chrome Upload Permission Runbook

Purpose: fix the Chrome extension file-upload blocker for hidden OCR manual QA.

## Symptom

The student OCR modal is visible, but Codex/Chrome automation cannot attach a local answer-sheet image. The browser reports that file upload is blocked.

## Required Chrome Setting

1. Open Chrome.
2. Go to `chrome://extensions`.
3. Find the `Codex` extension.
4. Click `Details`.
5. Enable `Allow access to file URLs`.
6. Return to the student page and reload.

Chrome internal extension pages cannot be opened or toggled by this agent because browser automation policy blocks `chrome://extensions`.

## Verification After Enabling

1. Open `/student/<sid>?ocr=1`.
2. Open the test submit modal.
3. Select the intended test and round.
4. Click the answer-sheet file chooser.
5. Select a local `jpg`, `jpeg`, `png`, or `webp` file.
6. Confirm the selected filename appears in the input.
7. Do not click `/api/submit-test`.
8. Do not click `#tsSubmit`.

## Fallback If Still Blocked

Use provider-free verifier coverage until Chrome permission is fixed:

```powershell
node tools\subjective_sheet_lab\verify_student_ocr_answers_text_ui_bridge.js
node tools\subjective_sheet_lab\verify_student_ocr_cached_fixture_qa.js
node tools\subjective_sheet_lab\verify_student_ocr_route_progress_states.js
node tools\subjective_sheet_lab\verify_student_ocr_submit_guard.js
```

If a visual artifact is needed, use the existing isolated-browser screenshots:

- `tools/subjective_sheet_lab/qa_screenshot_20260705_playwright_file_selected.png`
- `tools/subjective_sheet_lab/qa_screenshot_20260705_file_selected_retry_blocked.png`
- `tools/subjective_sheet_lab/qa_screenshot_20260705_upload_blocked_modal.png`

## Safety

- Gemini/API calls: 0 unless separately approved.
- `/api/submit-test` calls: 0 unless separately approved.
- `#tsSubmit` clicks: 0 unless separately approved.
- Production default remains `NO-GO`.
- Do not expose API key or `.env` values.
