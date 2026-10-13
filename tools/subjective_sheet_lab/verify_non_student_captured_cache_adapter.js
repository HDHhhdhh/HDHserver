const assert = require('assert/strict');
const fs = require('fs');
const http = require('http');
const path = require('path');
const {
  buildTrustedAdultCase,
} = require('./non_student_captured_cache_adapter');
const {
  createPrototypeServer,
} = require('./non_student_gemini_server_prototype');

const CAPTURE_DIR = path.join(
  'C:/server-ocr/gemini_gateway_smoke_outputs',
  'adult_non_student_20260727_01',
  'teacher_01_gateway_smoke',
  'C',
);

function readJson(name) {
  return JSON.parse(fs.readFileSync(path.join(CAPTURE_DIR, name), 'utf8'));
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function requestJson(port, body) {
  const payload = JSON.stringify(body);
  return new Promise((resolve, reject) => {
    const request = http.request({
      hostname: '127.0.0.1',
      port,
      path: '/lab/non-student/gemini-review',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
      },
    }, response => {
      let text = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { text += chunk; });
      response.on('end', () => resolve({
        statusCode: response.statusCode,
        body: JSON.parse(text),
      }));
    });
    request.on('error', reject);
    request.end(payload);
  });
}

function assertThrowsCode(action, code) {
  assert.throws(action, error => error?.code === code);
}

async function main() {
  const manifest = readJson('provider_input_manifest.json');
  const recognized = readJson('recognized.json');
  const trustedCase = buildTrustedAdultCase({
    caseId: 'adult_teacher_01_capture_001',
    testId: 'adult_non_student_benchmark_20',
    round: '1',
    manifest,
    recognized,
  });

  assert.equal(trustedCase.provenance, 'adult_non_student');
  assert.equal(trustedCase.cache_status, 'hit');
  assert.equal(trustedCase.items.length, 20);
  assert.equal(trustedCase.items.every(item => item.review_state === 'review_recommended'), true);
  assert.equal(trustedCase.items.every(item => item.candidate), true);
  assert.equal(trustedCase.items.some(item => 'final_answer' in item), false);
  assert.equal(JSON.stringify(trustedCase).includes('C:\\'), false);

  const tamperedManifest = clone(manifest);
  tamperedManifest.contact_sha256[0] = '0'.repeat(64);
  assertThrowsCode(() => buildTrustedAdultCase({
    caseId: 'adult_tampered',
    testId: 'adult_non_student_benchmark_20',
    round: '1',
    manifest: tamperedManifest,
    recognized,
  }), 'CACHE_IDENTITY_MISMATCH');

  const leakedRecognized = clone(recognized);
  leakedRecognized.items[0].recognized = 'C:\\private\\answer.png';
  assertThrowsCode(() => buildTrustedAdultCase({
    caseId: 'adult_path_leak',
    testId: 'adult_non_student_benchmark_20',
    round: '1',
    manifest,
    recognized: leakedRecognized,
  }), 'LOCAL_PATH_DETECTED');

  const server = createPrototypeServer({
    evidence: { providerCalls: 0 },
    cases: new Map([[trustedCase.case_id, trustedCase]]),
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  assert.equal(typeof address, 'object');

  try {
    const response = await requestJson(address.port, { case_id: trustedCase.case_id });
    assert.equal(response.statusCode, 200);
    assert.equal(response.body.provider_calls, 0);
    assert.equal(response.body.payload.items.length, 20);
    assert.deepEqual(response.body.classification_counts, {
      AUTO_CONFIRM: 0,
      REVIEW_RECOMMENDED: 20,
      DIRECT_INPUT: 0,
      RETAKE_REQUIRED: 0,
    });
    assert.equal(response.body.payload.items.every(item => item.final_answer === null), true);
    assert.equal(response.body.payload.items.every(item => item.requires_confirmation), true);
    assert.equal(response.body.payload.items.every(item => item.allow_edit), true);
    assert.equal(
      response.body.payload.items.every(item => item.candidate_source === 'gemini_captured_cache'),
      true,
    );
  } finally {
    await new Promise((resolve, reject) => {
      server.close(error => {
        if (error) reject(error);
        else resolve();
      });
    });
  }

  console.log(JSON.stringify({
    ok: true,
    capturedCacheIdentityVerified: true,
    payloadItems: 20,
    reviewRecommended: 20,
    autoConfirm: 0,
    finalAnswers: 0,
    providerCalls: 0,
    submitCalls: 0,
    productionDefault: 'NO-GO',
  }, null, 2));
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
