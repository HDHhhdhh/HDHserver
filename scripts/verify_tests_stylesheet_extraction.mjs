import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';

const html = fs.readFileSync('static/tests.html', 'utf8').replace(/\r\n/g, '\n');
const css = fs.readFileSync('static/css/tests.css', 'utf8').replace(/\r\n/g, '\n');
const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');

const stylesheetHrefs = [...html.matchAll(/<link\s+rel="stylesheet"\s+href="([^"]+)"\s*>/g)]
  .map(match => match[1]);

assert.deepEqual(stylesheetHrefs, [
  '/css/main.css',
  '/css/admin.css',
  '/css/tests.css?v=20260829-tests-css-r1',
], 'test-page stylesheet order changed');
assert.doesNotMatch(html, /<style(?:\s|>)/i, 'tests.html must not retain an inline style block');
assert.match(html, /<body class="admin tests-page">/, 'test-page cascade scope changed');
assert.ok(
  html.indexOf('/css/tests.css?v=20260829-tests-css-r1') < html.indexOf('</head>'),
  'test-page stylesheet must load before the document body',
);

assert.equal(
  sha256(css),
  '9438d2eb2dbc5a7b925becdbbaed2135acb654a1620c6f4db0380dd3b98f39f8',
  'tests.css differs from the normalized pre-extraction inline stylesheet',
);
assert.equal(css.split('\n').length - 1, 1729, 'tests.css line count drifted');
assert.equal((css.match(/body\.admin\.tests-page/g) || []).length, 284, 'page scope count drifted');
assert.deepEqual(
  [...css.matchAll(/@media\s*\(max-width:\s*(\d+)px\)/g)].map(match => Number(match[1])),
  [1024, 640, 640, 1080, 900, 760],
  'responsive breakpoint order changed',
);
assert.equal((css.match(/!important/g) || []).length, 6, 'specificity compatibility count drifted');
assert.doesNotMatch(css, /@import\b/i, 'tests.css must not introduce another cascade layer');

for (const requiredSelector of [
  'body.admin.tests-page .hero-card {',
  'body.admin.tests-page .tests-shell {',
  'body.admin.tests-page .answer-mode-grid {',
  'body.admin.tests-page .stats-summary {',
  'body.admin.tests-page .stats-detail-modal {',
  'body.admin.tests-page .detail-student-table {',
]) {
  assert.ok(css.includes(requiredSelector), `tests.css lost selector: ${requiredSelector}`);
}

const bodySource = html.slice(html.indexOf('<body'));
assert.equal(
  sha256(bodySource),
  '5b9d215033a321c2bd319f54c33520744b405bded334318c473e02e1a7842600',
  'tests.html body or script contract changed after the approved answer-help decision',
);

console.log('tests stylesheet extraction checks passed: pre-extraction CSS hash, cascade order, approved body hash, scopes, responsive order, and modal/table selectors');
