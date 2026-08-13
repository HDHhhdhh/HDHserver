import assert from 'node:assert/strict';
import fs from 'node:fs';

import { doneEntriesFromUnarchivedSummary } from '../static/js/admin/features/todayDoneSummary.js';

const older = { done: true, leaveTime: '17:00' };
const latest = { done: 'true', archived: false, hwChecked: true };
const other = { done: 1, archived: false };

const entries = doneEntriesFromUnarchivedSummary({
  rowsAvailable: true,
  rows: [
    { sid: 'sid-a', date: '2026-08-12', entry: older },
    { sid: 'sid-a', date: '2026-08-14', entry: latest },
    { sid: 'sid-b', date: '2026-08-13', entry: other },
    { sid: 'sid-c', date: '2026-08-11', entry: { done: true, archived: true } },
    { sid: 'sid-d', date: '2026-08-10', entry: { done: false } },
    { sid: '', date: '2026-08-14', entry: { done: true } },
    { sid: 'sid-e', date: 'not-a-date', entry: { done: true } },
    { sid: 'sid-g', date: '2026-02-31', entry: { done: true } },
    { sid: 'sid-f', date: '2026-08-09', entry: null },
  ],
});

assert.ok(Array.isArray(entries));
assert.equal(entries.length, 2, 'only latest, unarchived, completed students should remain');
const bySid = new Map(entries.map(row => [row[0], row]));
assert.deepEqual(bySid.get('sid-a'), ['sid-a', latest, '2026-08-14']);
assert.deepEqual(bySid.get('sid-b'), ['sid-b', other, '2026-08-13']);
assert.equal(doneEntriesFromUnarchivedSummary({ total: 0 }), null, 'legacy summary without rows must use local fallback');
assert.equal(
  doneEntriesFromUnarchivedSummary({ rowsAvailable: false, rows: [] }),
  null,
  'a degraded empty summary must use local fallback',
);
assert.deepEqual(
  doneEntriesFromUnarchivedSummary({ rowsAvailable: true, rows: [] }),
  [],
  'an authoritative empty summary must stay empty',
);

const renderSource = fs.readFileSync('static/js/admin/features/today.render.js', 'utf8');
const todaySource = fs.readFileSync('static/js/admin/features/today.js', 'utf8');
const apiSource = fs.readFileSync('routes/api_basic.py', 'utf8');
assert.match(renderSource, /dateKey === String\(getAdminDate\(\) \|\| ''\)/, 'historical rows need a selected-date edit gate');
assert.match(renderSource, /renderReadonlySlotLabel\('—'\)/, 'historical slot labels must not show an unhydrated value');
assert.match(renderSource, /class="arriveLabelReadonly"/, 'historical arrive values must render read-only');
assert.match(renderSource, /arriveTime = isSelectedDate \? plannedTimeFor/, 'historical arrive values must not read an unhydrated cache');
assert.match(renderSource, /data-sid="\$\{escapeAttr\(sidKey\)\}"/, 'summary-controlled SIDs must be escaped');
assert.match(renderSource, /<span class="stuName">\$\{escapeAttr\(name\)\}<\/span>/, 'unknown roster names must be escaped');
assert.match(todaySource, /function renderDoneSummaryWhenIdle\(/, 'async done summaries need an edit-safe renderer');
assert.match(todaySource, /wrap\.contains\(active\)/, 'async done summary replacement must defer while editing');
assert.match(todaySource, /renderDone\(sortDoneEntries\(entries\)\);\s*applyTodaySearchFilter\(\);/, 'async done summaries must preserve the active search filter');
assert.match(apiSource, /return nocache_resp\(_summarize_unarchived_done_logs\(exclude_date\)\)/, 'all-date per-student summaries must be no-store');

console.log('today unarchived done projection checks passed');
