# OCR Provider-Free Preflight Inclusion Plan

Date: 2026-07-06 KST

## Current Status

- Existing preflight file touched by this task: no
- Protected file requiring separate approval: `tools/subjective_sheet_lab/run_phase1_preflight_checks.py`
- Existing readiness artifact: `ocr_provider_free_accuracy_gate_preflight_readiness.json`
- Existing sandbox artifact: `ocr_provider_free_accuracy_gate_preflight_sandbox.json`
- Ready to add when separately approved: yes
- Gemini/API calls: 0
- `/api/submit-test` calls: 0
- `#tsSubmit` clicks: 0
- Production default: `NO-GO`

## Intended Addition After Approval

Add one provider-free check to the preflight list:

```text
ocr_provider_free_accuracy_gate_extended
python tools/subjective_sheet_lab/verify_ocr_provider_free_accuracy_gate_extended.py
```

## Why The Extended Gate Is The Better Preflight Target

- It includes the base provider-free gate.
- It includes q003/q018 ambiguity routing.
- It includes q015/q016 relation/operator ambiguity routing.
- It includes high-priority mismatch crop-quality analysis.
- It includes visible-digit second-pass request safety.
- It includes person_03 live-call handoff safety.
- It includes Training Pack crop fixture readiness.
- It includes Training Pack route-upload source inventory.
- It includes Training Pack provider-free replay skeleton validation.
- It includes Training Pack UI replay bridge blocking for skeleton payloads.
- It includes Training Pack accuracy-claim guard blocking skeletons from OCR accuracy metrics.
- It includes Training Pack recognized evidence intake for future nonzero recognized cache payloads.
- It includes Training Pack recognized-cache replacement readiness blocking skeleton replacement without OCR evidence.
- It includes Training Pack replacement sandbox blocking replacement and accuracy recompute without recognized evidence.
- It includes Training Pack crop fixture spec verification.
- It keeps provider/API, submit-test, and path/sensitive-field leak counts at 0.

## Stop Conditions

- Do not edit the preflight file without a separate explicit approval.
- Do not include any check that can call Gemini/API.
- Do not include any check that can call `/api/submit-test`.
- Do not include any check that needs runtime data mutation.
- Do not include any check that depends on answer keys or grading fields.

## Current Evidence

- Extended provider-free gate count: 37
- q015/q016 relation review-required count: 2
- q015/q016 auto-confirm count: 0
- Training Pack crop fixture targets: 4
- Training Pack complete crop fixtures: 0
- Training Pack route-upload source candidates: 4
- Training Pack source assets ready: 4
- Training Pack cache replay payloads: 0
- Training Pack replay skeleton payloads: 4
- Training Pack replay skeleton review-required items: 80
- Training Pack replay skeleton recognized values: 0
- Training Pack UI replay bridge payloads: 4
- Training Pack UI replay bridge blocked final payloads: 4
- Training Pack UI replay bridge fill allowed: 0
- Training Pack UI replay bridge review cards: 80
- Training Pack accuracy-claim guard payloads: 4
- Training Pack accuracy-claim allowed: false
- Training Pack accuracy-claim recognized values: 0
- Training Pack recognized evidence intake targets: 4
- Training Pack recognized evidence intake files: 0
- Training Pack recognized evidence intake recognized values: 0
- Training Pack recognized evidence contract probes: 5
- Training Pack recognized evidence contract rejected probes: 4
- Training Pack recognized evidence contract ready: true
- Training Pack replacement-readiness source assets ready: 4
- Training Pack replacement-readiness evidence source: recognized evidence intake report
- Training Pack replacement-readiness evidence files: 0
- Training Pack replacement-readiness recognized values: 0
- Training Pack replacement-readiness OCR evidence count: 0
- Training Pack replacement allowed: false
- Training Pack replacement next status: `USER_APPROVAL_REQUIRED`
- Training Pack replacement sandbox contract ready: true
- Training Pack replacement sandbox contract files: 0
- Training Pack replacement sandbox contract rejected probes: 4
- Training Pack replacement sandbox attempted: false
- Training Pack replacement sandbox payloads created: 0
- Training Pack replacement sandbox accuracy attempted: false
- Training Pack replacement sandbox accuracy reports: 0
- Training Pack fixture-spec capture-required targets: 4
- Provider call count: 0
- External OCR API call count: 0
- Submit-test call count: 0
- `#tsSubmit` click count: 0
- Sensitive-field leak count: 0
- Filesystem path leak count: 0
