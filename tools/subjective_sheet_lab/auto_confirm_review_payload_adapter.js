const AUTO_CONFIRM_POLICY_VERSION = 'gemini_flash_lite_policy_d_boundary_v1';
const REVIEW_STATES = new Set([
  'auto_confirm',
  'review_recommended',
  'direct_input',
  'retake_required',
]);

function assertCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function buildAutoConfirmEvidence(candidate, overrides = {}) {
  const value = String(candidate || '').trim();
  return {
    policy_version: AUTO_CONFIRM_POLICY_VERSION,
    truth_used_by_gate: false,
    model_confidence: 'high',
    parser_pass: true,
    historical_agreement: true,
    original_confidence: 'high',
    enhanced_confidence: 'high',
    original_candidate: value,
    enhanced_candidate: value,
    ...overrides,
  };
}

function normalizeItem(item) {
  const questionNo = Number(item?.question_no);
  const reviewState = String(item?.review_state || '');
  const candidate = String(item?.candidate || '').trim();
  assertCondition(Number.isInteger(questionNo), 'question_no must be an integer');
  assertCondition(REVIEW_STATES.has(reviewState), `unsupported review_state for q${questionNo}`);

  const normalized = {
    question_no: questionNo,
    review_state: reviewState,
    candidate: candidate ? { value: candidate } : null,
    warning: Array.isArray(item?.warning) ? [...item.warning] : [],
    crop_preview: String(item?.crop_preview || ''),
    candidate_source: String(item?.candidate_source || ''),
    allow_edit: true,
    requires_confirmation: reviewState !== 'auto_confirm',
    retake_reason: String(item?.retake_reason || ''),
    resolution: reviewState === 'auto_confirm' ? 'auto_confirm' : 'unresolved',
    final_answer: reviewState === 'auto_confirm' ? candidate : null,
  };

  if (reviewState === 'auto_confirm') {
    assertCondition(candidate, `auto_confirm candidate missing for q${questionNo}`);
    normalized.auto_confirm_evidence = item.auto_confirm_evidence || buildAutoConfirmEvidence(candidate);
  }
  return normalized;
}

function buildAutoConfirmReviewPayload({ testId, round = '1', items }) {
  assertCondition(String(testId || '').trim(), 'testId is required');
  assertCondition(Array.isArray(items) && items.length === 20, 'exactly 20 items are required');
  const normalizedItems = items.map(normalizeItem).sort((left, right) => left.question_no - right.question_no);
  const questionNumbers = normalizedItems.map(item => item.question_no);
  assertCondition(new Set(questionNumbers).size === 20, 'question_no values must be unique');
  assertCondition(questionNumbers.every((value, index) => value === index + 1), 'question_no values must cover 1 through 20');
  return {
    source: 'lab_auto_confirm_review_payload_v1',
    auto_confirm_policy_version: AUTO_CONFIRM_POLICY_VERSION,
    test_id: String(testId).trim(),
    round: String(round),
    problem_count: 20,
    items: normalizedItems,
  };
}

module.exports = {
  AUTO_CONFIRM_POLICY_VERSION,
  buildAutoConfirmEvidence,
  buildAutoConfirmReviewPayload,
};
