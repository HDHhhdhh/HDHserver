const crypto = require('crypto');
const {
  AUTO_CONFIRM_POLICY_VERSION,
} = require('./auto_confirm_review_payload_adapter');

const CASE_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const MANIFEST_KEYS = new Set([
  'schema',
  'model',
  'variant',
  'prompt_sha256',
  'input_package',
  'question_count',
  'contact_sha256',
  'external_scope',
  'request_sha256',
]);
const RECOGNIZED_KEYS = new Set(['question', 'recognized']);
const LOCAL_PATH_PATTERN = /(?:[A-Za-z]:\\|file:\/\/|\/(?:home|Users|server|tmp)\/)/i;

class CapturedCacheError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'CapturedCacheError';
    this.code = code;
  }
}

function fail(code, message) {
  throw new CapturedCacheError(code, message);
}

function requireObject(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    fail('INVALID_CAPTURE_CONTRACT', `${label} must be an object`);
  }
  return value;
}

function rejectUnexpectedKeys(value, allowed, label) {
  const unexpected = Object.keys(value).find(key => !allowed.has(key));
  if (unexpected) {
    fail('INVALID_CAPTURE_CONTRACT', `${label} field is not accepted: ${unexpected}`);
  }
}

function stableStringify(value) {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(',')}]`;
  }
  if (value && typeof value === 'object') {
    const fields = Object.keys(value)
      .sort()
      .map(key => `${JSON.stringify(key)}:${stableStringify(value[key])}`);
    return `{${fields.join(',')}}`;
  }
  return JSON.stringify(value);
}

function sha256(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

function parseManifest(rawManifest) {
  const manifest = requireObject(rawManifest, 'manifest');
  rejectUnexpectedKeys(manifest, MANIFEST_KEYS, 'manifest');
  if (manifest.schema !== 'gemini_accuracy_sprint_provider_input_v1') {
    fail('INVALID_CAPTURE_CONTRACT', 'manifest schema is unsupported');
  }
  if (manifest.external_scope !== 'deidentified_contact_sheets_only') {
    fail('DEIDENTIFICATION_SCOPE_REQUIRED', 'deidentified contact-only scope is required');
  }
  if (manifest.question_count !== 20) {
    fail('INVALID_CAPTURE_CONTRACT', 'manifest must cover 20 questions');
  }
  if (!Array.isArray(manifest.contact_sha256) || manifest.contact_sha256.length !== 4) {
    fail('INVALID_CAPTURE_CONTRACT', 'manifest must contain four contact hashes');
  }
  const hashes = [manifest.prompt_sha256, ...manifest.contact_sha256, manifest.request_sha256];
  if (!hashes.every(value => SHA256_PATTERN.test(String(value)))) {
    fail('INVALID_CAPTURE_CONTRACT', 'manifest hashes must be SHA-256 values');
  }
  const identity = { ...manifest };
  delete identity.request_sha256;
  if (sha256(stableStringify(identity)) !== manifest.request_sha256) {
    fail('CACHE_IDENTITY_MISMATCH', 'captured cache request identity does not match');
  }
  return manifest;
}

function parseRecognized(rawRecognized) {
  const recognized = requireObject(rawRecognized, 'recognized cache');
  rejectUnexpectedKeys(recognized, new Set(['items']), 'recognized cache');
  if (!Array.isArray(recognized.items) || recognized.items.length !== 20) {
    fail('INVALID_CAPTURE_CONTRACT', 'recognized cache must contain 20 items');
  }
  const questions = new Set();
  return recognized.items.map(rawItem => {
    const item = requireObject(rawItem, 'recognized item');
    rejectUnexpectedKeys(item, RECOGNIZED_KEYS, 'recognized item');
    const question = Number(item.question);
    if (!Number.isInteger(question) || question < 1 || question > 20 || questions.has(question)) {
      fail('INVALID_CAPTURE_CONTRACT', 'recognized questions must uniquely cover 1 through 20');
    }
    questions.add(question);
    const candidate = String(item.recognized || '').trim();
    if (candidate.length > 80) {
      fail('INVALID_CAPTURE_CONTRACT', `recognized candidate is too long for q${question}`);
    }
    if (LOCAL_PATH_PATTERN.test(candidate)) {
      fail('LOCAL_PATH_DETECTED', `local path detected in q${question}`);
    }
    return { question, candidate };
  }).sort((left, right) => left.question - right.question);
}

function buildTrustedAdultCase({ caseId, testId, round, manifest, recognized }) {
  if (!CASE_ID_PATTERN.test(String(caseId || ''))) {
    fail('INVALID_CASE_ID', 'caseId is invalid');
  }
  if (!String(testId || '').trim()) {
    fail('INVALID_CAPTURE_CONTRACT', 'testId is required');
  }
  const parsedManifest = parseManifest(manifest);
  const parsedItems = parseRecognized(recognized);
  return {
    case_id: caseId,
    provenance: 'adult_non_student',
    cache_status: 'hit',
    cache_identity: parsedManifest.request_sha256,
    model: parsedManifest.model,
    test_id: String(testId).trim(),
    round: String(round || '1'),
    auto_confirm_policy_version: AUTO_CONFIRM_POLICY_VERSION,
    items: parsedItems.map(({ question, candidate }) => ({
      question_no: question,
      review_state: candidate && candidate !== '?' ? 'review_recommended' : 'direct_input',
      candidate: candidate === '?' ? '' : candidate,
      candidate_source: 'gemini_captured_cache',
      warning: candidate && candidate !== '?'
        ? ['teacher_confirmation_required']
        : ['provider_unresolved'],
      crop_preview: '',
    })),
  };
}

module.exports = {
  CapturedCacheError,
  buildTrustedAdultCase,
};
