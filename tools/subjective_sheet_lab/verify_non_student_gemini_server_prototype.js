const assert = require('assert/strict');
const http = require('http');
const {
  createPrototypeServer,
} = require('C:/server/tools/subjective_sheet_lab/non_student_gemini_server_prototype');

const fixture = require(
  'C:/server/tools/subjective_sheet_lab/non_student_gemini_server_contract_fixture.json',
);

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

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function buildCases() {
  const invalidEvidence = clone(fixture);
  delete invalidEvidence.items[0].auto_confirm_evidence.boundary_gate_pass;

  const restricted = clone(fixture);
  restricted.items[0].expected = 'forbidden';

  return new Map([
    [fixture.case_id, fixture],
    ['adult_unverified_auto', invalidEvidence],
    ['adult_malformed', { ...clone(fixture), items: fixture.items.slice(0, 19) }],
    ['adult_restricted', restricted],
    ['student_case', { ...clone(fixture), provenance: 'student' }],
  ]);
}

async function main() {
  const evidence = { providerCalls: 0 };
  const server = createPrototypeServer({
    evidence,
    cases: buildCases(),
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  assert.equal(typeof address, 'object');
  const port = address.port;

  try {
    const hit = await requestJson(port, { case_id: fixture.case_id });
    assert.equal(hit.statusCode, 200);
    assert.equal(hit.body.provenance, 'adult_non_student');
    assert.equal(hit.body.payload.items.length, 20);
    assert.deepEqual(hit.body.classification_counts, {
      AUTO_CONFIRM: 7,
      REVIEW_RECOMMENDED: 8,
      DIRECT_INPUT: 3,
      RETAKE_REQUIRED: 2,
    });
    assert.equal(hit.body.provider_calls, 0);
    assert.equal(hit.body.auto_confirm_downgraded_count, 0);
    assert.equal('wrong_auto_confirm' in hit.body, false);
    assert.equal(hit.body.payload.items.some(item => 'expected' in item), false);
    assert.equal(hit.body.payload.items.some(item => 'filesystem_path' in item), false);

    const unknown = await requestJson(port, { case_id: 'unknown_case' });
    assert.equal(unknown.statusCode, 503);
    assert.equal(unknown.body.code, 'CACHE_NOT_FOUND_PROVIDER_DISABLED');
    assert.equal(unknown.body.fallback, 'manual_review');

    const injected = await requestJson(port, {
      case_id: fixture.case_id,
      provenance: 'adult_non_student',
    });
    assert.equal(injected.statusCode, 400);
    assert.equal(injected.body.code, 'UNEXPECTED_REQUEST_FIELD');

    const student = await requestJson(port, { case_id: 'student_case' });
    assert.equal(student.statusCode, 403);
    assert.equal(student.body.code, 'NON_STUDENT_ONLY');

    const malformed = await requestJson(port, { case_id: 'adult_malformed' });
    assert.equal(malformed.statusCode, 400);
    assert.equal(malformed.body.code, 'INVALID_REVIEW_CONTRACT');

    const leaked = await requestJson(port, { case_id: 'adult_restricted' });
    assert.equal(leaked.statusCode, 400);
    assert.equal(leaked.body.code, 'RESTRICTED_FIELD_DETECTED');

    const downgraded = await requestJson(port, { case_id: 'adult_unverified_auto' });
    assert.equal(downgraded.statusCode, 200);
    assert.equal(downgraded.body.auto_confirm_downgraded_count, 1);
    assert.equal(downgraded.body.classification_counts.AUTO_CONFIRM, 6);
    assert.equal(downgraded.body.classification_counts.REVIEW_RECOMMENDED, 9);
    assert.equal(downgraded.body.payload.items[0].final_answer, null);
    assert.equal(evidence.providerCalls, 0);
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
    endpoint: '/lab/non-student/gemini-review',
    trustedCaseLookup: true,
    payloadItems: 20,
    classificationCounts: {
      AUTO_CONFIRM: 7,
      REVIEW_RECOMMENDED: 8,
      DIRECT_INPUT: 3,
      RETAKE_REQUIRED: 2,
    },
    unverifiedAutoConfirmDowngraded: true,
    providerCalls: 0,
    submitCalls: 0,
    productionDefault: 'NO-GO',
  }, null, 2));
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
