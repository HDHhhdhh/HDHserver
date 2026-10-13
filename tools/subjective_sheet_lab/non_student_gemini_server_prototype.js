const http = require('http');
const {
  AUTO_CONFIRM_POLICY_VERSION,
  buildAutoConfirmReviewPayload,
} = require('./auto_confirm_review_payload_adapter');

const ENDPOINT = '/lab/non-student/gemini-review';
const MAX_BODY_BYTES = 1024 * 1024;
const CASE_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const REQUEST_KEYS = new Set(['case_id']);
const RESTRICTED_KEYS = new Set([
  'answerkey',
  'expected',
  'canonicalanswer',
  'acceptedanswers',
  'grading',
  'gradingfields',
  'iscorrect',
  'score',
  'filesystempath',
  'studentid',
  'studentname',
  'sid',
]);

class ContractError extends Error {
  constructor(code, message, statusCode) {
    super(message);
    this.name = 'ContractError';
    this.code = code;
    this.statusCode = statusCode;
  }
}

function sendJson(response, statusCode, body) {
  const payload = JSON.stringify(body);
  response.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(payload),
  });
  response.end(payload);
}

function normalizedKey(key) {
  return String(key).replace(/[^a-z0-9]/gi, '').toLowerCase();
}

function restrictedKey(value) {
  if (!value || typeof value !== 'object') return null;
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = restrictedKey(item);
      if (found) return found;
    }
    return null;
  }
  for (const [key, nested] of Object.entries(value)) {
    if (RESTRICTED_KEYS.has(normalizedKey(key))) return key;
    const found = restrictedKey(nested);
    if (found) return found;
  }
  return null;
}

function containsLocalPath(value) {
  if (typeof value === 'string') {
    return /(?:[A-Za-z]:\\|file:\/\/|\/(?:home|Users|server|tmp)\/)/i.test(value);
  }
  if (!value || typeof value !== 'object') return false;
  const values = Array.isArray(value) ? value : Object.values(value);
  return values.some(containsLocalPath);
}

function parseCaseId(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw new ContractError('INVALID_REQUEST', 'request body must be an object', 400);
  }
  const unexpected = Object.keys(body).find(key => !REQUEST_KEYS.has(key));
  if (unexpected) {
    throw new ContractError(
      'UNEXPECTED_REQUEST_FIELD',
      `request field is not accepted: ${unexpected}`,
      400,
    );
  }
  const caseId = String(body.case_id || '');
  if (!CASE_ID_PATTERN.test(caseId)) {
    throw new ContractError('INVALID_CASE_ID', 'case_id is invalid', 400);
  }
  return caseId;
}

function hasVerifiedAutoConfirmEvidence(item) {
  if (item.review_state !== 'auto_confirm') return false;
  if (!item.candidate || item.warning?.length) return false;
  const evidence = item.auto_confirm_evidence;
  return Boolean(
    evidence &&
    evidence.policy_version === AUTO_CONFIRM_POLICY_VERSION &&
    evidence.boundary_gate_pass === true &&
    evidence.truth_used_by_gate === false &&
    evidence.parser_pass === true &&
    evidence.historical_agreement === true &&
    evidence.original_confidence === 'high' &&
    evidence.enhanced_confidence === 'high' &&
    String(evidence.original_candidate) === String(item.candidate) &&
    String(evidence.enhanced_candidate) === String(item.candidate)
  );
}

function sanitizeItems(items) {
  let downgradedCount = 0;
  const sanitized = items.map(item => {
    if (item?.review_state !== 'auto_confirm' || hasVerifiedAutoConfirmEvidence(item)) {
      return item;
    }
    downgradedCount += 1;
    return {
      ...item,
      review_state: 'review_recommended',
      warning: [...new Set([...(item.warning || []), 'auto_confirm_evidence_unverified'])],
    };
  });
  return { sanitized, downgradedCount };
}

function parseTrustedCase(entry) {
  const restricted = restrictedKey(entry);
  if (restricted) {
    throw new ContractError(
      'RESTRICTED_FIELD_DETECTED',
      `restricted field is not accepted: ${restricted}`,
      400,
    );
  }
  if (containsLocalPath(entry)) {
    throw new ContractError('LOCAL_PATH_DETECTED', 'local paths are not accepted', 400);
  }
  if (entry?.provenance !== 'adult_non_student') {
    throw new ContractError('NON_STUDENT_ONLY', 'adult non-student cache required', 403);
  }
  if (entry?.cache_status !== 'hit') {
    throw new ContractError(
      'CACHE_NOT_FOUND_PROVIDER_DISABLED',
      'matching cache is unavailable and provider is disabled',
      503,
    );
  }
  if (entry?.auto_confirm_policy_version !== AUTO_CONFIRM_POLICY_VERSION) {
    throw new ContractError(
      'CALIBRATION_POLICY_MISMATCH',
      'cache does not match the frozen calibration policy',
      400,
    );
  }
  const { sanitized, downgradedCount } = sanitizeItems(entry.items || []);
  try {
    return {
      payload: buildAutoConfirmReviewPayload({
        testId: entry.test_id,
        round: entry.round,
        items: sanitized,
      }),
      downgradedCount,
    };
  } catch (error) {
    throw new ContractError(
      'INVALID_REVIEW_CONTRACT',
      error instanceof Error ? error.message : 'invalid review contract',
      400,
    );
  }
}

function classificationCounts(items) {
  const counts = {
    AUTO_CONFIRM: 0,
    REVIEW_RECOMMENDED: 0,
    DIRECT_INPUT: 0,
    RETAKE_REQUIRED: 0,
  };
  for (const item of items) counts[item.review_state.toUpperCase()] += 1;
  return counts;
}

function readJsonBody(request) {
  return new Promise((resolve, reject) => {
    let size = 0;
    let text = '';
    let tooLarge = false;
    request.setEncoding('utf8');
    request.on('data', chunk => {
      size += Buffer.byteLength(chunk);
      tooLarge = tooLarge || size > MAX_BODY_BYTES;
      if (!tooLarge) text += chunk;
    });
    request.on('end', () => {
      if (tooLarge) {
        reject(new ContractError('BODY_TOO_LARGE', 'request body exceeds 1 MiB', 413));
        return;
      }
      try {
        resolve(JSON.parse(text));
      } catch {
        reject(new ContractError('INVALID_JSON', 'request body must be valid JSON', 400));
      }
    });
    request.on('error', reject);
  });
}

function createPrototypeServer({ evidence, cases }) {
  if (Number(evidence?.providerCalls) !== 0) {
    throw new ContractError('PROVIDER_MUST_BE_DISABLED', 'provider call count must be zero', 500);
  }
  const trustedCases = new Map(cases);
  return http.createServer(async (request, response) => {
    if (request.method !== 'POST' || request.url !== ENDPOINT) {
      sendJson(response, 404, { code: 'NOT_FOUND' });
      return;
    }
    try {
      const caseId = parseCaseId(await readJsonBody(request));
      const entry = trustedCases.get(caseId);
      if (!entry) {
        throw new ContractError(
          'CACHE_NOT_FOUND_PROVIDER_DISABLED',
          'trusted cache entry was not found',
          503,
        );
      }
      const { payload, downgradedCount } = parseTrustedCase(entry);
      sendJson(response, 200, {
        provenance: 'adult_non_student',
        source: 'trusted_server_cache',
        cache_status: 'hit',
        provider_calls: 0,
        calibration_policy_version: AUTO_CONFIRM_POLICY_VERSION,
        auto_confirm_downgraded_count: downgradedCount,
        classification_counts: classificationCounts(payload.items),
        payload,
      });
    } catch (error) {
      if (error instanceof ContractError) {
        sendJson(response, error.statusCode, {
          code: error.code,
          message: error.message,
          fallback: error.statusCode === 503 ? 'manual_review' : 'stop',
          provider_calls: 0,
        });
        return;
      }
      sendJson(response, 500, {
        code: 'PROTOTYPE_INTERNAL_ERROR',
        fallback: 'stop',
        provider_calls: 0,
      });
    }
  });
}

module.exports = {
  createPrototypeServer,
};
