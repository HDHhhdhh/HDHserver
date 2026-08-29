import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = relative => fs.readFileSync(path.join(root, relative), 'utf8');
const html = read('static/admin.html');
const main = read('static/js/admin/main.js');
const feature = read('static/js/admin/features/studentTestOcrReview.js');
const css = read('static/css/student-test-ocr-admin.css');

let assertions = 0;

for (const id of [
  'studentTestOcrReviewOpen',
  'studentTestOcrReviewModal',
  'studentTestOcrReviewClose',
  'studentTestOcrReviewDate',
  'studentTestOcrReviewRefresh',
  'studentTestOcrReviewStatus',
  'studentTestOcrReviewList',
  'studentTestOcrReviewDetail',
]) {
  assert.equal((html.match(new RegExp(`id=["']${id}["']`, 'g')) || []).length, 1, id);
  assertions += 1;
}
assert.match(html, /id="studentTestOcrReviewOpen"[^>]*hidden/);
assertions += 1;

assert.ok(main.includes("import { initStudentTestOcrReview }"));
assert.ok(main.includes('initStudentTestOcrReview();'));
assertions += 2;

assert.ok(feature.includes("import { getAdminDate }"));
assert.ok(feature.includes('frozenDate = getAdminDate()'));
assert.ok(feature.includes('/pending?date='));
assert.ok(feature.includes("endpoint: 'resolve'"));
assert.ok(feature.includes("endpoint: 'correct'"));
assert.ok(feature.includes('오답 → 정답 수정'));
assert.ok(!feature.includes('정답 → 오답'));
assert.ok(feature.includes('studentCropUrl'));
assert.ok(feature.includes('solutionCropUrl'));
assert.ok(feature.includes('답지 원본에서 확인'));
assertions += 10;

assert.ok(css.includes('body.admin .student-test-ocr-admin-panel'));
assert.ok(css.includes('body.admin.dark .student-test-ocr-admin-grade'));
assert.ok(css.includes('.student-test-ocr-review-open[hidden]'));
assert.ok(css.includes('.student-test-ocr-admin-modal[hidden]'));
assert.ok(css.includes('display: none !important'));
assert.ok(!/^\s*\.student-test-ocr-admin-panel\s*\{/m.test(css));
assertions += 6;

console.log(`student-test-ocr-admin passed: ${assertions} assertions`);
