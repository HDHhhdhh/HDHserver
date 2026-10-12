'use strict';

const fs = require('fs');
const path = require('path');

const studentJs = path.resolve(__dirname, '..', '..', 'static', 'js', 'student.js');
const source = fs.readFileSync(studentJs, 'utf8');

function requireMatch(pattern, label) {
  if (!pattern.test(source)) {
    throw new Error(`Missing ${label}`);
  }
}

const routeBuilderStart = source.indexOf('async function ocrReviewFetchRoutePayload(test, round, imageFile) {');
const routeBuilderEnd = source.indexOf('async function ocrReviewOpenRouteFlow()', routeBuilderStart);

if (routeBuilderStart < 0 || routeBuilderEnd < 0) {
  throw new Error('Unable to locate OCR review request builder');
}

requireMatch(
  /const OCR_PHASE2E_FRESH_REVIEW_REQUESTED = OCR_TEST_SHEET_ENABLED && \/\(\?:\^\|\[\?&\]\)freshPhase2E=1\(\?:&\|\$\)\/\.test\(location\.search \|\| ''\);/,
  'explicit fresh-review opt-in gate',
);

const builderSource = source.slice(routeBuilderStart, routeBuilderEnd);
const freshFieldAppends = builderSource.match(/form\.append\('freshPhase2E', '1'\);/g) || [];
if (freshFieldAppends.length !== 1) {
  throw new Error('freshPhase2E must be appended exactly once');
}

if (!/if \(OCR_PHASE2E_FRESH_REVIEW_REQUESTED\) \{\s*form\.append\('freshPhase2E', '1'\);\s*\}/.test(builderSource)) {
  throw new Error('freshPhase2E must remain available only through the explicit opt-in gate');
}

console.log('PASS verify_student_ocr_cache_first_request');
