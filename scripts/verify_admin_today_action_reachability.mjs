import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
  renderTodayActionButtons,
  renderTodayDocumentButton,
} from '../static/js/admin/features/todayActionMarkup.js';

const today = renderTodayActionButtons({ sid: 'sid-1', name: '홍길동' });
assert.equal((today.match(/<button /g) || []).length, 4, 'today rows expose four primary actions');
assert.equal((today.match(/type="button"/g) || []).length, 4, 'every today action is a non-submit button');
for (const contract of [
  ['openStudentPopups', '홍길동 학생 운영 팝업', '>운영</button>'],
  ['studentTestRecordBtn', '홍길동 테스트 기록 보기', '>기록</button>'],
  ['markAbsent', '홍길동 결석 처리', '>결석</button>'],
  ['markLeave', '홍길동 하원 처리', '>하원</button>'],
]) {
  assert.ok(contract.every(token => today.includes(token)), `today action contract missing: ${contract[0]}`);
}
assert.match(today, /role="group" aria-label="홍길동 작업"/, 'row actions expose one named group');
assert.doesNotMatch(today, /[🧾🚫🏠↩🧹]/u, 'primary row actions use readable text instead of emoji-only labels');

const done = renderTodayActionButtons({ sid: 'sid-2', name: '완료 학생', date: '2026-08-14', includeDoneActions: true });
assert.equal((done.match(/<button /g) || []).length, 6, 'done rows retain all six existing actions');
assert.equal((done.match(/type="button"/g) || []).length, 6, 'every done action is a non-submit button');
assert.match(done, /class="undoDone"[^>]+aria-label="완료 학생 하원 취소">취소<\/button>/);
assert.match(done, /class="clearDone"[^>]+aria-label="완료 학생 기록 정리">정리<\/button>/);
assert.match(done, /role="group" aria-label="완료 학생 2026-08-14 작업"/, 'done actions include their target date');

const hostile = renderTodayActionButtons({ sid: 'sid"<1', name: '이름"<script>' });
assert.ok(!hostile.includes('<script>'), 'student-controlled action labels are escaped');
assert.match(hostile, /data-test-result-sid="sid&quot;&lt;1"/);
assert.match(hostile, /aria-label="이름&quot;&lt;script&gt; 작업"/);

const doc = renderTodayDocumentButton({ docUrl: 'https://example.test/?x="<', name: '문서 학생' });
assert.match(doc, /^<button type="button" class="btn-doc"/);
assert.match(doc, /data-doc-url="https:\/\/example\.test\/\?x=&quot;&lt;"/);
assert.match(doc, /aria-label="문서 학생 문서 열기"/);

const renderSource = fs.readFileSync('static/js/admin/features/today.render.js', 'utf8');
const cssSource = fs.readFileSync('static/css/admin.css', 'utf8');

assert.match(renderSource, /import \{ renderTodayActionButtons, renderTodayDocumentButton \} from '\.\/todayActionMarkup\.js';/);
assert.equal((renderSource.match(/renderTodayActionButtons\(\{/g) || []).length, 2, 'both current row render paths share the action contract');
assert.equal((renderSource.match(/renderTodayDocumentButton\(\{/g) || []).length, 2, 'both current row render paths share the document contract');
assert.match(
  renderSource,
  /renderWhiteReviewPendingCell\(s\.id, s\.name, whiteReviewPending\)[\s\S]*?<td class="today-action-cell">/,
  'today actions retain the approved white-review column immediately before them',
);
assert.ok(
  /renderWhiteReviewPendingCell\(sidKey, name\)\}[\s\S]*?<td class="done-action-cell">/.test(renderSource),
  'done actions retain the approved white-review column immediately before them',
);
assert.equal((renderSource.match(/class="done-action-date"/g) || []).length, 1, 'the actual done-row renderer exposes a mobile date badge');
assert.equal((renderSource.match(/date: dateKey, includeDoneActions: true/g) || []).length, 1, 'the done action group names its frozen target date');
assert.match(renderSource, /done-white-review-head/);
assert.match(renderSource, /width:36px.*width:232px/, 'white-review and action column widths remain approved');
assert.match(cssSource, /#todayWrap \.today-table \.today-actions button[^}]*min-height:\s*40px/);
assert.match(cssSource, /#doneWrap \.done-table \.today-actions button[^}]*min-height:\s*40px/);
assert.match(cssSource, /@media \(max-width: 640px\)[\s\S]*grid-template-columns:\s*repeat\(3, 44px\)/);
assert.match(cssSource, /@media \(max-width: 640px\)[\s\S]*#doneWrap \.done-action-date\s*\{[^}]*display:\s*block/);
assert.match(cssSource, /#doneWrap \.done-action-date\s*\{[^}]*background:[^;]*var\(--brand\)[^}]*color:\s*var\(--ink\)/);

console.log('admin today action reachability checks passed');
