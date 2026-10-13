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

// Restore only the five superseded TH prefixes for the independent extraction baseline.
const desktopCellWidths = ['18%', '9%', '12%', '45%', '16%'];
const desktopHeaderWidths = ['22%', '15%', '16%', '31%', '16%'];
let extractionCSS = css;
for (let column = 1; column <= 5; column += 1) {
  const prefix = `body.admin.tests-page .detail-student-table`;
  const cell = `${prefix} td:nth-child(${column})`;
  const header = `${prefix} th:nth-child(${column})`;
  const anchor = `\n${cell} {`;
  assert.equal(css.split(anchor).length - 1, 1, 'each allowed inverse has one unindented TD anchor');
  assert.ok(css.includes(`${cell} {\n  width: ${desktopCellWidths[column - 1]};`));
  assert.ok(css.includes(`${header} {\n  width: ${desktopHeaderWidths[column - 1]};`));
  extractionCSS = extractionCSS.replace(anchor, `\n${header},${anchor}`);
}
assert.equal(css.split('\n').length - 1, 1724, 'actual CSS permits exactly five selector-line removals');
assert.equal((css.match(/body\.admin\.tests-page/g) || []).length, 279, 'actual CSS scope delta is exactly five');
assert.match(css, /@media \(max-width: 640px\)[\s\S]*?th:nth-child\(5\)[\s\S]*?td:nth-child\(5\)\s*\{\s*width: 100%;/);

assert.equal(
  sha256(extractionCSS),
  '9438d2eb2dbc5a7b925becdbbaed2135acb654a1620c6f4db0380dd3b98f39f8',
  'tests.css differs from the normalized pre-extraction inline stylesheet',
);
assert.equal(extractionCSS.split('\n').length - 1, 1729, 'tests.css line count drifted');
assert.equal((extractionCSS.match(/body\.admin\.tests-page/g) || []).length, 284, 'page scope count drifted');
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

assert.ok(html.includes('일산 기출은 중상·상·그래프 포함'));
// Approved level text and cache busting must not weaken the remaining layout oracle.
const bodySource = html.slice(html.indexOf('<body'))
  .replace('일산 기출은 중상·상·그래프 포함', '일산 기출은 중·중상·그래프 포함')
  .replace('/js/tests.js?v=20260907-ilsan-level-r1&hub=20261001-detail1', '/js/tests.js?v=20260829-catalog-statistics-state-r1');
assert.equal(
  sha256(bodySource),
  '5b9d215033a321c2bd319f54c33520744b405bded334318c473e02e1a7842600',
  'tests.html body or script contract changed after the approved answer-help decision',
);

console.log('tests stylesheet extraction checks passed: pre-extraction CSS hash, cascade order, approved body hash, scopes, responsive order, and modal/table selectors');
