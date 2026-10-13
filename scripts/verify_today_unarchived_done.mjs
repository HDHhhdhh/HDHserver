import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

import {
  doneEntriesFromUnarchivedSummary,
  missingLeaveWarningText,
  missingLeaveWarningRows,
  recordCleanupWarningText,
} from '../static/js/admin/features/todayDoneSummary.js';

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

assert.equal(
  missingLeaveWarningText({
    rowsAvailable: true,
    total: 4,
    students: 3,
    rows: [
      { date: '2026-08-26', sid: 'sid-a', arriveTime: '18:00' },
      { date: '2026-08-29', sid: 'sid-a', arriveTime: '17:45' },
      { date: '2026-08-28', sid: 'sid-b', arriveTime: '18:05' },
      { date: '2026-08-27', sid: 'sid-c', arriveTime: '13:00' },
    ],
  }),
  '2026-08-29 · 하원',
  'missing-leave warning must expose only in-baseline dates and its action type',
);
assert.equal(
  missingLeaveWarningText({
    rowsAvailable: true,
    total: 2,
    byDate: [{ date: '2026-08-28', count: 2 }],
    rows: [
      { date: '2026-08-28', sid: 'legacy-a', arriveTime: '17:47' },
      { date: '2026-08-28', sid: 'legacy-b', arriveTime: '17:20' },
    ],
  }),
  '',
  'the known incomplete 2026-08-28 traces must not render a warning before a server restart',
);
assert.equal(
  recordCleanupWarningText({
    rowsAvailable: true,
    total: 5,
    byDate: [
      { date: '2026-08-29', count: 2 },
      { date: '2026-08-28', count: 3 },
    ],
  }),
  '2026-08-29, 2026-08-28 · 기록 정리',
  'record-cleanup warning must expose only dates and its action type',
);
assert.equal(missingLeaveWarningText({ rowsAvailable: false, total: 1, rows: [] }), '');
assert.equal(missingLeaveWarningText({ rowsAvailable: true, total: 0, rows: [] }), '');
assert.equal(recordCleanupWarningText({ rowsAvailable: false, total: 1, byDate: [{ date: '2026-08-29', count: 1 }] }), '');

const renderSource = fs.readFileSync('static/js/admin/features/today.render.js', 'utf8');
const todaySource = fs.readFileSync('static/js/admin/features/today.js', 'utf8');
const apiSource = fs.readFileSync('routes/api_logs.py', 'utf8');
const arriveApiSource = fs.readFileSync('routes/api_arrive_time.py', 'utf8');
const mainSource = fs.readFileSync('static/js/admin/main.js', 'utf8');
const adminHtml = fs.readFileSync('static/admin.html', 'utf8');
const adminCss = fs.readFileSync('static/css/admin.css', 'utf8');
assert.match(renderSource, /dateKey === String\(getAdminDate\(\) \|\| ''\)/, 'historical rows need a selected-date edit gate');
assert.match(renderSource, /renderReadonlySlotLabel\('—'\)/, 'historical slot labels must not show an unhydrated value');
assert.match(renderSource, /class="arriveLabelReadonly"/, 'historical arrive values must render read-only');
assert.match(renderSource, /arriveTime = isSelectedDate \? plannedTimeFor/, 'historical arrive values must not read an unhydrated cache');
assert.match(renderSource, /data-sid="\$\{escapeAttr\(sidKey\)\}"/, 'summary-controlled SIDs must be escaped');
assert.match(renderSource, /<span class="stuName">\$\{escapeAttr\(name\)\}<\/span>/, 'unknown roster names must be escaped');
assert.match(todaySource, /function renderDoneSummaryWhenIdle\(/, 'async done summaries need an edit-safe renderer');
assert.match(todaySource, /wrap\.contains\(active\)/, 'async done summary replacement must defer while editing');
assert.match(todaySource, /withStudentLookup\(\(\) => renderDone\(sortDoneEntries\(entries\)\)\);\s*applyTodaySearchFilter\(\);/, 'async done summaries must preserve the active search filter');
assert.match(apiSource, /return nocache_resp\(get_log_repository\(\)\.summarize_unarchived_done\(exclude_date\)\)/, 'all-date per-student summaries must be no-store');
assert.match(arriveApiSource, /MISSING_LEAVE_WARNING_START_DATE = "2026-08-29"/, 'known pre-baseline arrival noise must stay outside the warning');
assert.match(arriveApiSource, /@bp_api_arrive_time\.get\("\/api\/arrive-time\/missing-leave-summary"\)/, 'arrival owner must expose the missing-leave summary');
assert.match(todaySource, /fetchMissingLeaveSummary\(dateKey\)/, 'today view must request the missing-leave summary');
assert.match(todaySource, /if \(missingLeaveWarningDateKey !== dateKey\) \{\s*renderMissingLeaveWarning\(\{ total: 0, rowsAvailable: true, rows: \[\] \}\);\s*missingLeaveWarningDateKey = dateKey;/, 'same-date refresh must preserve the last authoritative missing-leave warning until the new response arrives');
assert.match(mainSource, /missingLeaveRefresh=20260927/, 'today module cache key must expose the refresh fix');
assert.match(adminHtml, /missingLeaveRefresh=20260927/, 'admin shell cache key must expose the refresh fix');
assert.match(todaySource, /const \[unarchivedSummary, missingLeaveSummary\] = await Promise\.all\(/, 'independent warnings must load in parallel');
assert.match(todaySource, /el\.setAttribute\('role', 'alert'\)/, 'missing-leave warning must be announced assertively');
assert.match(todaySource, /function createOperationWarningIcon\(\)/, 'warning rows need a shared vector icon factory');
assert.match(todaySource, /icon\.setAttribute\('aria-hidden', 'true'\)/, 'the visible label must own warning semantics while the SVG stays decorative');
assert.match(todaySource, /className = 'hero-warning-icon'/, 'warning icon wrapper must remain explicit');
assert.match(todaySource, /className = 'hero-warning-label'/, 'warning text must remain separately styleable');
assert.match(todaySource, /과거 하원 기록 확인/, 'warning must identify historical records instead of implying current students');
assert.match(todaySource, /setAdminDate\(row\.date\)/, 'warning action must use the existing selected-date transition');
assert.match(mainSource, /leaveDetails=20261011/, 'today module must invalidate the warning details cache');
assert.match(adminHtml, /leaveDetails=20261011/, 'shell and stylesheet must invalidate the warning details cache');
assert.match(adminCss, /\.hero-panel:has\(#missingLeaveWarning:not\(\[hidden\]\)\)\s*\{\s*height:\s*auto;/, 'desktop warning details must expand the command board');
assert.match(adminCss, /\.hero-panel:has\(#missingLeaveWarning:not\(\[hidden\]\)\) > \.hero-actions\s*\{\s*grid-row:\s*2;\s*margin-top:\s*0;/, 'desktop actions must flow below warning details');
assert.match(mainSource, /today\.js\?v=20260830-warning-visual1/, 'today entrypoint cache key must expose the warning visual change');
assert.match(adminHtml, /id="todayOperationWarnings" class="hero-warning-stack"/, 'admin hero needs a dedicated warning boundary');
assert.match(adminHtml, /missingLeave=2/, 'admin shell cache key must expose the warning change');
assert.match(adminHtml, /warningVisual=1/, 'admin shell cache key must expose the warning visual change');
assert.match(adminHtml, /admin\.css\?v=20260831-quick-print-filter2-warning-visual2/, 'admin shell cache key must expose the full-width warning change');
assert.match(adminCss, /body\.admin \.hero-warning-stack\s*\{[\s\S]*?max-height:\s*none;[\s\S]*?grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);[\s\S]*?overflow:\s*visible;/, 'warning stack must not create an internal scrollbar');
assert.match(adminCss, /body\.admin \.hero-warning-stack:not\(:has\(> \.hero-operation-warning:not\(\[hidden\]\) ~ \.hero-operation-warning:not\(\[hidden\]\)\)\)[\s\S]*?> \.hero-operation-warning:not\(\[hidden\]\)\s*\{[\s\S]*?grid-column:\s*1 \/ -1;/, 'a single visible warning must span both quick-action columns');
assert.match(adminCss, /body\.admin \.hero-warning-stack > \.hero-operation-warning\s*\{[\s\S]*?font-size:\s*14px;[\s\S]*?font-weight:\s*900;/, 'warning typography must be visibly larger and stronger');
assert.match(adminCss, /body\.admin #staleDoneWarning\s*\{[\s\S]*?border-color:\s*var\(--hero-warning-amber\);/, 'record-cleanup warning needs the amber warning treatment');
assert.match(adminCss, /body\.admin #missingLeaveWarning\s*\{[\s\S]*?var\(--hero-warning-red\)/, 'missing-leave warning needs the danger treatment');
assert.match(adminCss, /body\.admin\.dark #missingLeaveWarning\s*\{[\s\S]*?color:\s*#fecaca;/, 'danger warning needs an explicit dark-mode contrast pair');

const detailSummary = {
  rowsAvailable: true, total: 9,
  rows: [
    {date:'2026-09-07', sid:'sid-a', arriveTime:'18:08'},
    {date:'2026-09-07', sid:'sid-a', arriveTime:'18:08'},
    {date:'2026-09-08', sid:'sid-b', arriveTime:'13:00'},
    {date:'2026-08-28', sid:'old', arriveTime:'13:00'},
    {date:'2026-02-31', sid:'invalid', arriveTime:'13:00'},
    {date:'2026-10-11', sid:'today', arriveTime:'13:00'},
    {date:'2026-10-12', sid:'future', arriveTime:'13:00'},
    {date:'2026-09-09', sid:'blank', arriveTime:''},
    {date:'2026-09-10', sid:'object', arriveTime:{time:'13:00'}},
  ],
};
const detailRows = [
  {date:'2026-09-08', sid:'sid-b', arriveTime:'13:00'},
  {date:'2026-09-07', sid:'sid-a', arriveTime:'18:08'},
];
assert.deepEqual(missingLeaveWarningRows(detailSummary, {today:'2026-10-11'}), detailRows);
assert.deepEqual(missingLeaveWarningRows(detailSummary, {today:'2026-10-11',excludeDate:'2026-09-08'}), [detailRows[1]]);
assert.deepEqual(missingLeaveWarningRows({...detailSummary,rowsAvailable:false}), []);
assert.deepEqual(missingLeaveWarningRows({...detailSummary,total:0}), []);
assert.deepEqual(missingLeaveWarningRows({...detailSummary,rows:[]}), []);

class WarningElement {
  constructor(tag) { this.tagName=tag.toUpperCase();this.children=[];this.attributes={};this.events={};this.hidden=false;this.textContent=''; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.append(child); }
  replaceChildren(...children) { this.children=children; }
  setAttribute(key,value) { this.attributes[key]=value; }
  addEventListener(event,handler) { this.events[event]=handler; }
}
const warningStack=new WarningElement('div');
const warningElements=[warningStack];
warningStack.id='todayOperationWarnings';
const openedDates=[];
const warningDocument={
  getElementById(id) { return warningElements.find(element=>element.id===id) || null; },
  createElement(tag) { const element=new WarningElement(tag);warningElements.push(element);return element; },
};
const warningContext=vm.createContext({
  document:warningDocument,
  todayOperationWarningStack:()=>warningStack,
  state:{students:[{id:'sid-a',name:'안호율'},{id:'sid-b',name:'<img src=x onerror=alert(1)>'}]},
  missingLeaveWarningRows,
  todayLocalKey:()=> '2026-10-11', getAdminDate:()=> '2026-10-11',
  setAdminDate:date=>openedDates.push(date),
  syncTodayOperationWarningStack:()=>{warningStack.hidden=!warningStack.children.some(child=>!child.hidden);},
});
const renderer=todaySource.slice(todaySource.indexOf('function renderMissingLeaveWarning('),todaySource.indexOf('async function fetchUnarchivedDoneSummary('));
vm.runInContext(`${renderer}\nthis.renderWarning=renderMissingLeaveWarning;`,warningContext);
warningContext.renderWarning(detailSummary);
const warning=warningDocument.getElementById('missingLeaveWarning');
assert.equal(warning.tagName,'SECTION');
assert.equal(warning.hidden,false);
assert.equal(warning.attributes.role,'alert');
assert.equal(warning.children[0].children[1].textContent,'과거 하원 기록 확인 · 2건');
const items=warning.children[1].children;
assert.equal(items.length,2);
assert.equal(items[0].children[0].children[0].textContent,'2026-09-08 · <img src=x onerror=alert(1)> · 등원 13:00');
assert.equal(items[1].children[0].children[0].textContent,'2026-09-07 · 안호율 · 등원 18:08');
assert.equal(items[1].children[0].children[1].textContent,'하원 완료로 저장되지 않음');
assert.equal(items[1].children[1].type,'button');
items[1].children[1].events.click();
assert.deepEqual(openedDates,['2026-09-07']);
warningContext.renderWarning({rowsAvailable:false,total:1,rows:detailRows});
assert.equal(warning.hidden,true);
assert.equal(warning.children.length,0);
assert.equal(warningStack.hidden,true);
warningContext.renderWarning({rowsAvailable:true,total:0,rows:[]});
assert.equal(warning.hidden,true);

console.log('today unarchived done projection and historical missing-leave detail checks passed');
