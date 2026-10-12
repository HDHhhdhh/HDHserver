import { state } from '../core/state.js';
import { api } from '../core/api.js';
import { getAdminDate, setAdminDate } from '../core/adminDate.js';
import { todayLocalKey } from '../core/utils.js';
import {
  applySearchPlaceholder,
  matchesSearchKey,
  normalizeSearch,
  searchKeyForText,
} from '../../shared/search.js';
import { todayStudentSearchKey } from './todaySearch.js?v=20260929-school-initials1';
import {
  countPendingMakeupsBySid,
  scheduledMakeupStudentIdsForDate,
} from './makeupPending.js';
import {
  doneEntriesFromUnarchivedSummary,
  missingLeaveWarningText,
  missingLeaveWarningRows,
  recordCleanupWarningText,
} from './todayDoneSummary.js?v=20260830-warning-boundary1&leaveDetails=20261011';

export {
  doneEntriesFromUnarchivedSummary,
  missingLeaveWarningText,
  recordCleanupWarningText,
} from './todayDoneSummary.js?v=20260830-warning-boundary1&leaveDetails=20261011';

import {
  loadWeekendSlots,
  ensureAttendLoaded,
  ensureContactLoaded,
  ensureArriveLoaded,
  collectUnarchivedLogsByDate,
  loadOrderMap,
  applySavedOrder,
  getSavedOrder,
  hasWeekday,
  yoilOf,
  plannedMinutesFor,
  isAttended,
  isSelfStudy,
  isHwChecked,
  isHwCheckRequested,
  hwCheckRequestedAt,
  truthy,
  labelFor,
  withStudentLookup,
} from './today.state.js';

import {
  renderToday,
  renderDone,
  bindTodayTableEvents,
} from './today.render.js?v=20260912-done-white-review1&youtube=20260913&adminSpeed=20261003';

function dateQuery(dateKey) {
  return new URLSearchParams({ date: String(dateKey || '') }).toString();
}

function isCurrentAdminDate(dateKey) {
  return String(getAdminDate() || '') === String(dateKey || '');
}

function makeupCountGroupKey(student) {
  const name = String(student?.name || '').trim();
  if (!name) return String(student?.id || '').trim();
  const school = String(student?.school || '').trim();
  const grade = String(student?.grade || '').trim();
  return [name, school, grade].filter(Boolean).join('|');
}

function aggregateMakeupCountsByStudent(students, countsBySid) {
  const rows = Array.isArray(students) ? students : [];
  const studentsBySid = new Map(rows.map(student => [String(student?.id || ''), student]));
  const groupTotals = new Map();
  const groupBySid = new Map();

  Object.entries(countsBySid || {}).forEach(([sid, rawCount]) => {
    const count = Number(rawCount || 0) || 0;
    if (count <= 0) return;
    const student = studentsBySid.get(String(sid)) || { id: sid };
    const groupKey = makeupCountGroupKey(student);
    groupBySid.set(String(sid), groupKey);
    groupTotals.set(groupKey, (groupTotals.get(groupKey) || 0) + count);
  });

  rows.forEach(student => {
    const sid = String(student?.id || '');
    if (!sid) return;
    const groupKey = makeupCountGroupKey(student);
    if (groupTotals.has(groupKey)) groupBySid.set(sid, groupKey);
  });

  const out = { ...(countsBySid || {}) };
  groupBySid.forEach((groupKey, sid) => {
    out[sid] = groupTotals.get(groupKey) || 0;
  });
  return out;
}

function mergeDateSidMap(target, incoming) {
  if (!incoming || typeof incoming !== 'object') return;
  Object.entries(incoming).forEach(([date, day]) => {
    if (!day || typeof day !== 'object') return;
    target[date] = target[date] || {};
    Object.entries(day).forEach(([sid, entry]) => {
      if (entry && typeof entry === 'object') target[date][String(sid)] = entry;
    });
  });
}

async function ensureLogsForDate(dateKey, options = {}) {
  const key = String(dateKey || '').trim();
  if (!key || (state.logs?.[key] && !options.force)) return;
  try {
    const res = await fetch(`/api/logs?${dateQuery(key)}`, { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    if (data && typeof data === 'object') {
      state.logs = state.logs || {};
      state.logs[key] = (data[key] && typeof data[key] === 'object') ? data[key] : {};
      window.logs = state.logs;
    }
  } catch {}
}

async function ensureProgressForDate(dateKey, options = {}) {
  const key = String(dateKey || '').trim();
  if (!key || (state.progress?.[key] && !options.force)) return;
  try {
    const res = await fetch(`/api/progress?${dateQuery(key)}`, { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    if (data && typeof data === 'object') {
      state.progress = state.progress || {};
      state.progress[key] = (data[key] && typeof data[key] === 'object') ? data[key] : {};
      window.progressData = state.progress;
    }
  } catch {}
}

const progressHistoryLoadedSids = new Set();
let progressHistoryLoadedAll = false;
let progressHistoryAllPromise = null;

async function loadAllProgressHistoryOnce(force = false) {
  if (progressHistoryLoadedAll && !force) return true;
  if (progressHistoryAllPromise && !force) return progressHistoryAllPromise;

  progressHistoryAllPromise = (async () => {
    try {
      const res = await fetch('/api/progress', { cache: 'no-store' });
      if (!res.ok) return false;
      const data = await res.json();
      if (data && typeof data === 'object') {
        state.progress = state.progress || {};
        mergeDateSidMap(state.progress, data);
        window.progressData = state.progress;
        progressHistoryLoadedAll = true;
        return true;
      }
    } catch {}
    return false;
  })();

  try {
    return await progressHistoryAllPromise;
  } finally {
    progressHistoryAllPromise = null;
  }
}

async function loadProgressHistoryForSidBatch(sids) {
  const keys = Array.from(new Set((sids || []).map(sid => String(sid || '').trim()).filter(Boolean)));
  if (!keys.length) return true;

  const batchSize = 60;
  for (let i = 0; i < keys.length; i += batchSize) {
    const chunk = keys.slice(i, i + batchSize);
    const q = new URLSearchParams({ sids: chunk.join(',') }).toString();
    const res = await fetch(`/api/progress?${q}`, { cache: 'no-store' });
    if (!res.ok) return false;
    const data = await res.json();
    if (!data || typeof data !== 'object') return false;
    state.progress = state.progress || {};
    mergeDateSidMap(state.progress, data);
    window.progressData = state.progress;
    chunk.forEach(sid => progressHistoryLoadedSids.add(sid));
  }
  return true;
}

async function ensureProgressHistoryForSids(sids, options = {}) {
  const keys = Array.from(new Set((sids || []).map(sid => String(sid || '').trim()).filter(Boolean)));
  if (!keys.length) return;
  if (progressHistoryLoadedAll && !options.forceHistory) {
    keys.forEach(sid => progressHistoryLoadedSids.add(sid));
    return;
  }

  const pending = keys.filter(sid => options.forceHistory || !progressHistoryLoadedSids.has(sid));
  if (!pending.length) return;

  if (pending.length >= 4) {
    const loadedBatch = await loadProgressHistoryForSidBatch(pending);
    if (loadedBatch) return;

    const loaded = await loadAllProgressHistoryOnce(!!options.forceHistory);
    if (loaded) {
      pending.forEach(sid => progressHistoryLoadedSids.add(sid));
      return;
    }
  }

  await Promise.all(pending.map(async (sid) => {
    try {
      const q = new URLSearchParams({ sid }).toString();
      const res = await fetch(`/api/progress?${q}`, { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      if (data && typeof data === 'object') {
        state.progress = state.progress || {};
        mergeDateSidMap(state.progress, data);
        window.progressData = state.progress;
        progressHistoryLoadedSids.add(sid);
      }
    } catch {}
  }));
}

async function refreshStudentsIfNeeded(options = {}) {
  if (!options.force && Array.isArray(state.students) && state.students.length) return;
  try {
    const res = await fetch('/api/students', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    if (Array.isArray(data)) {
      state.students = data;
      window.students = state.students;
    }
  } catch {}
}

async function refreshAbsencesIfNeeded(options = {}) {
  if (!options.force && state.absentByDate && Object.keys(state.absentByDate).length) return;
  try {
    const res = await fetch('/api/absent', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    if (data && typeof data === 'object') {
      state.absentByDate = data.by_date || data.absentByDate || state.absentByDate || {};
      state.absences = data.by_student || data.absences || state.absences || {};
      state.absentSlotsByDate = data.by_slot || data.absentSlotsByDate || state.absentSlotsByDate || {};
      window.absentByDate = state.absentByDate;
      window.absentSlotsByDate = state.absentSlotsByDate;
      if (window.state) {
        window.state.absentByDate = state.absentByDate;
        window.state.absences = state.absences;
        window.state.absentSlotsByDate = state.absentSlotsByDate;
      }
    }
  } catch {}
}

function todayOperationWarningStack() {
  return document.getElementById('todayOperationWarnings');
}

function syncTodayOperationWarningStack() {
  const stack = todayOperationWarningStack();
  if (!stack) return;
  stack.hidden = !Array.from(stack.children).some(child => !child.hidden);
}

function createOperationWarningIcon() {
  const svgNs = 'http://www.w3.org/2000/svg';
  const icon = document.createElementNS(svgNs, 'svg');
  icon.setAttribute('viewBox', '0 0 24 24');
  icon.setAttribute('fill', 'none');
  icon.setAttribute('stroke', 'currentColor');
  icon.setAttribute('stroke-width', '2');
  icon.setAttribute('stroke-linecap', 'round');
  icon.setAttribute('stroke-linejoin', 'round');
  icon.setAttribute('aria-hidden', 'true');
  icon.setAttribute('focusable', 'false');

  const triangle = document.createElementNS(svgNs, 'path');
  triangle.setAttribute('d', 'M10.3 3.2 2.4 17a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.2a2 2 0 0 0-3.4 0Z');
  const stem = document.createElementNS(svgNs, 'path');
  stem.setAttribute('d', 'M12 9v4');
  const dot = document.createElementNS(svgNs, 'path');
  dot.setAttribute('d', 'M12 17h.01');
  icon.append(triangle, stem, dot);
  return icon;
}

function setOperationWarningMessage(el, message) {
  const text = String(message || '').trim();
  el.hidden = !text;
  let label = el.querySelector('.hero-warning-label');
  if (!text) {
    if (label) label.textContent = '';
    return;
  }
  if (!label) {
    const icon = document.createElement('span');
    icon.className = 'hero-warning-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.appendChild(createOperationWarningIcon());
    label = document.createElement('span');
    label.className = 'hero-warning-label';
    el.replaceChildren(icon, label);
  }
  label.textContent = text;
}

function renderStaleDoneWarning(summary) {
  const stack = todayOperationWarningStack();
  if (!stack) return;

  let el = document.getElementById('staleDoneWarning');
  if (!el) {
    el = document.createElement('p');
    el.id = 'staleDoneWarning';
    el.className = 'hero-sub hero-operation-warning hero-operation-warning--cleanup';
    el.setAttribute('aria-live', 'polite');
    stack.appendChild(el);
  }

  const message = recordCleanupWarningText(summary);
  setOperationWarningMessage(el, message);
  syncTodayOperationWarningStack();
}

function renderMissingLeaveWarning(summary) {
  const stack = todayOperationWarningStack();
  if (!stack) return;
  let el = document.getElementById('missingLeaveWarning');
  if (!el) {
    el = document.createElement('section');
    el.id = 'missingLeaveWarning';
    el.className = 'hero-sub hero-operation-warning hero-operation-warning--leave';
    el.setAttribute('role', 'alert');
    el.setAttribute('aria-live', 'assertive');
    stack.appendChild(el);
  }

  const rows = missingLeaveWarningRows(summary, { today: todayLocalKey(), excludeDate: getAdminDate() });
  el.hidden = rows.length === 0;
  if (!rows.length) {
    el.replaceChildren();
    syncTodayOperationWarningStack();
    return;
  }
  const heading = document.createElement('div');
  heading.className = 'missing-leave-heading';
  const icon = document.createElement('span');
  icon.className = 'hero-warning-icon';
  icon.setAttribute('aria-hidden', 'true');
  const label = document.createElement('span');
  label.className = 'hero-warning-label';
  label.textContent = `과거 하원 기록 확인 · ${rows.length}건`;
  heading.append(icon, label);
  const list = document.createElement('ul');
  list.className = 'missing-leave-list';
  const students = new Map((state.students || []).map(student => [String(student.id), student]));
  for (const row of rows) {
    const name = String(students.get(row.sid)?.name || row.sid);
    const item = document.createElement('li');
    const info = document.createElement('div');
    const title = document.createElement('span');
    title.className = 'missing-leave-student';
    title.textContent = `${row.date} · ${name} · 등원 ${row.arriveTime}`;
    const reason = document.createElement('span');
    reason.className = 'missing-leave-reason';
    reason.textContent = '하원 완료로 저장되지 않음';
    info.append(title, reason);
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'missing-leave-open';
    open.textContent = '날짜 확인';
    open.setAttribute('aria-label', `${row.date} ${name} 하원 기록 확인`);
    open.addEventListener('click', () => setAdminDate(row.date));
    item.append(info, open);
    list.appendChild(item);
  }
  el.replaceChildren(heading, list);
  syncTodayOperationWarningStack();
}

async function fetchUnarchivedDoneSummary(dateKey) {
  try {
    const qs = new URLSearchParams({ exclude_date: String(dateKey || '') });
    const res = await fetch(`/api/logs/unarchived-summary?${qs.toString()}`, { cache: 'no-store' });
    if (!res.ok) return null;
    const data = await res.json();
    return data && typeof data === 'object' ? data : null;
  } catch (err) {
    console.warn('[today] stale done summary failed:', err);
    return null;
  }
}

async function fetchMissingLeaveSummary(dateKey) {
  try {
    const qs = new URLSearchParams({ exclude_date: String(dateKey || '') });
    const res = await fetch(`/api/arrive-time/missing-leave-summary?${qs.toString()}`, { cache: 'no-store' });
    if (!res.ok) return null;
    const data = await res.json();
    return data && typeof data === 'object' ? data : null;
  } catch (err) {
    console.warn('[today] missing leave summary failed:', err);
    return null;
  }
}

// ─────────────────────────────────────────────
// 오늘 학생 도구/검색
// ─────────────────────────────────────────────
const LS_SEARCH_FIELD = 'todaySearchField';
const TODAY_SEARCH_FIELDS = new Set(['all', 'name', 'school', 'curriculum']);
let _todaySearchField = TODAY_SEARCH_FIELDS.has(localStorage.getItem(LS_SEARCH_FIELD))
  ? localStorage.getItem(LS_SEARCH_FIELD)
  : 'all';
let _makeupCarryover = null;

function updateAlphaSortBtn() {
  document.getElementById('todayAlphaSortBtn')?.remove();
}

function ensureHomeworkLeaveButton() {
  let button = document.getElementById('homeworkLeaveBtn');
  if (!button) {
    button = document.createElement('button');
    button.id = 'homeworkLeaveBtn';
    button.className = 'btn secondary';
    button.type = 'button';
    button.textContent = '숙검하원';
    button.title = '숙제 검사 완료 학생 일괄 하원';
  }
  return button;
}

function placeTodaySearchActions(search) {
  const absentButton = document.getElementById('absentRecoverBtn');
  const homeworkLeaveButton = ensureHomeworkLeaveButton();
  const input = search?.querySelector?.('#todaySearchInput');
  if (!input) return;
  input.insertAdjacentElement('afterend', homeworkLeaveButton);
  if (absentButton) homeworkLeaveButton.insertAdjacentElement('afterend', absentButton);
}

function ensureTodaySearchControls(tools) {
  if (!tools) return;
  const existingSearch = document.getElementById('todaySearchInput')?.closest?.('.today-search');
  if (existingSearch) {
    placeTodaySearchActions(existingSearch);
    return;
  }

  const search = document.createElement('div');
  search.className = 'today-search';
  search.innerHTML = `
    <select id="todaySearchField" aria-label="오늘 학생 검색 대상">
      <option value="all">전체</option>
      <option value="name">이름</option>
      <option value="school">학교</option>
      <option value="curriculum">과목</option>
    </select>
    <input id="todaySearchInput" type="search" autocomplete="off"
           placeholder="오늘 학생 검색" aria-label="오늘 학생 검색">
    <span id="todaySearchHint" class="today-search-hint" aria-live="polite"></span>
  `;
  tools.appendChild(search);
  placeTodaySearchActions(search);

  const field = search.querySelector('#todaySearchField');
  const input = search.querySelector('#todaySearchInput');
  applySearchPlaceholder(input, '오늘 학생 검색');
  field.value = _todaySearchField;
  field.addEventListener('change', () => {
    _todaySearchField = TODAY_SEARCH_FIELDS.has(field.value) ? field.value : 'all';
    try { localStorage.setItem(LS_SEARCH_FIELD, _todaySearchField); } catch {}
    applyTodaySearchFilter();
  });
  input.addEventListener('input', applyTodaySearchFilter);
  input.addEventListener('search', applyTodaySearchFilter);
  input.addEventListener('compositionend', applyTodaySearchFilter);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') {
      input.value = '';
      applyTodaySearchFilter();
    }
  });
}
function ensureAlphaSortBtn() {
  if (document.getElementById('todaySearchInput')) {
    document.getElementById('todayAlphaSortBtn')?.remove();
    const wrap = document.getElementById('todayWrap');
    if (wrap) wrap.dataset.alpha = '0';
    return;
  }

  if (!document.getElementById('todayAlphaSortBtnStyle')) {
    const s = document.createElement('style');
    s.id = 'todayAlphaSortBtnStyle';
    s.textContent = `
      .today-tools{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0}
      .today-search{
        --today-search-max:max(320px, min(calc(100% - 180px), calc(56.25vw - 58px)));
        display:flex;align-items:center;gap:8px;flex:0 1 var(--today-search-max);
        min-width:min(100%, 320px);max-width:var(--today-search-max);
      }
      .today-search select,
      .today-search input{
        height:42px;border-radius:12px;border:1px solid rgba(148,163,184,.55);
        background:rgba(248,250,252,.96);color:#0f172a;box-sizing:border-box;
        font-size:15px;font-weight:700;outline:none;
      }
      .today-search select{flex:0 0 116px;padding:0 10px}
      .today-search input{min-width:0;flex:1 1 auto;padding:0 13px}
      body.admin .today-search #absentRecoverBtn{
        flex:0 0 auto;height:42px !important;padding:0 16px !important;border-radius:12px !important;
        font-size:15px !important;line-height:1 !important;white-space:nowrap;
      }
      body.admin .today-search #homeworkLeaveBtn{
        flex:0 0 auto;height:42px !important;padding:0 16px !important;border-radius:12px !important;
        font-size:15px !important;line-height:1 !important;white-space:nowrap;
      }
      .today-search input:focus,
      .today-search select:focus{border-color:rgba(37,99,235,.72);box-shadow:0 0 0 3px rgba(37,99,235,.12)}
      .today-search .today-search-hint{
        flex:0 0 auto;min-width:72px;font-size:13px;font-weight:800;color:#64748b;text-align:right;
      }
      body.dark .today-search select,
      body.dark .today-search input{border-color:#334155;background:rgba(2,6,23,.55);color:#e2e8f0}
      body.dark .today-search .today-search-hint{color:#94a3b8}
      #todayWrap tr.is-search-hidden,
      #doneWrap tr.is-search-hidden{display:none !important}
      #todayWrap[data-alpha="1"] .drag-handle{opacity:.35;cursor:default !important}
      @media (max-width:1180px){
        .today-search{flex-basis:100%;max-width:100%}
      }
      @media (max-width:720px){
        .today-search{flex-basis:100%;margin-left:0}
        .today-search .today-search-hint{display:none}
      }
    `;
    document.head.appendChild(s);
  }

  const wrap = document.getElementById('todayWrap');
  if (!wrap) return;

  let tools = document.getElementById('todayTools');
  if (!tools) {
    tools = document.createElement('div');
    tools.id = 'todayTools';
    tools.className = 'today-tools';
    wrap.insertAdjacentElement('beforebegin', tools);
  }

  updateAlphaSortBtn();
  ensureTodaySearchControls(tools);
  wrap.dataset.alpha = '0';
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ensureAlphaSortBtn, { once: true });
} else {
  ensureAlphaSortBtn();
}

const todaySearchKeyMemo = new WeakMap();

function todayRowSearchKey(row, stu, mode) {
  const texts = !stu && mode === 'all'
    ? Array.from(row.cells || [], cell => cell.textContent || '')
    : [];
  const buildKey = () => stu
    ? todayStudentSearchKey(stu, mode)
    : texts.map(searchKeyForText).join('|');
  let signature;
  try { signature = JSON.stringify([mode, !!stu, stu || texts]); }
  catch { return buildKey(); }
  const cached = todaySearchKeyMemo.get(row);
  if (cached?.signature === signature) return cached.key;
  const key = buildKey();
  todaySearchKeyMemo.set(row, { signature, key });
  return key;
}

function applyTodaySearchFilter() {
  const host = document.getElementById('todayWrap');
  const doneHost = document.getElementById('doneWrap');
  const input = document.getElementById('todaySearchInput');
  const field = document.getElementById('todaySearchField');
  const hint = document.getElementById('todaySearchHint');
  if (!host || !input) return;

  const queryText = input.value || '';
  const mode = TODAY_SEARCH_FIELDS.has(field?.value) ? field.value : _todaySearchField;
  const todayRows = Array.from(host.querySelectorAll('tr[data-sid]'));
  const doneRows = Array.from(doneHost?.querySelectorAll('tr[data-sid]') || []);
  const rows = [...todayRows, ...doneRows];
  let todayVisible = 0;
  let doneVisible = 0;

  if (!normalizeSearch(queryText)) {
    for (const row of rows) {
      if (!row.hidden && !row.classList.contains('is-search-hidden') && row.getAttribute('aria-hidden') !== 'true') continue;
      row.hidden = false;
      row.classList.remove('is-search-hidden');
      row.setAttribute('aria-hidden', 'false');
    }
    if (hint) hint.textContent = '';
    return;
  }

  const studentsById = new Map(
    (state.students || []).map(stu => [String(stu?.id || ''), stu]),
  );

  for (const row of rows) {
    const sid = String(row.dataset.sid || '');
    const stu = studentsById.get(sid);
    const key = todayRowSearchKey(row, stu, mode);
    const matches = matchesSearchKey(key, queryText);
    const hidden = !matches;
    if (row.hidden !== hidden) row.hidden = hidden;
    if (row.classList.contains('is-search-hidden') !== hidden) {
      row.classList.toggle('is-search-hidden', hidden);
    }
    const ariaHidden = matches ? 'false' : 'true';
    if (row.getAttribute('aria-hidden') !== ariaHidden) {
      row.setAttribute('aria-hidden', ariaHidden);
    }
    if (matches && row.closest('#doneWrap')) doneVisible += 1;
    else if (matches) todayVisible += 1;
  }

  if (hint) {
    hint.textContent = queryText.trim()
      ? `${todayVisible}/${todayRows.length}명 · 하원 ${doneVisible}/${doneRows.length}`
      : '';
  }
}

async function loadMakeupCarryoverMap(options = {}) {
  if (_makeupCarryover && !options.force) return _makeupCarryover;
  try {
    const res = await fetch('/api/makeup-carryover', { cache: 'no-store' });
    if (!res.ok) throw new Error(`/api/makeup-carryover ${res.status}`);
    const data = await res.json();
    _makeupCarryover = data && typeof data === 'object' ? data : {};
  } catch (err) {
    console.warn('[today] makeup carryover load failed:', err);
    _makeupCarryover = _makeupCarryover || {};
  }
  return _makeupCarryover;
}

// ─────────────────────────────────────────────
// ✅ 라벨 기반 슬롯 숫자 추출 + 그룹 랭크
// - 그룹: 1타임(0) > 연강(1) > 2타임(2)
// - 주말: [1,2,3] (연강 판별은 2개 이상)
// - 평일: [1,2]
// ─────────────────────────────────────────────
function _uniqNumsFromLabel(labelText, allowed) {
  const s = String(labelText || '');
  const nums = (s.match(/[0-9]/g) || [])
    .map(x => parseInt(x, 10))
    .filter(n => allowed.includes(n));
  return Array.from(new Set(nums)).sort((a, b) => a - b);
}
function timeGroupRank(dateStr, sid) {
  const w = yoilOf(dateStr);
  const label = String(labelFor(dateStr, sid) || '').trim();

  const allowed = (w === '토' || w === '일') ? [1, 2, 3] : [1, 2];
  const nums = _uniqNumsFromLabel(label, allowed);

  const has1 = nums.includes(1);
  const has2 = nums.includes(2);
  const isMulti = nums.length >= 2; // 연강

  // Slot-first grouping: 1st slot, multi-slot, then 2nd slot.
  if (has1 && !has2 && !isMulti) return 0;
  if (isMulti) return 1;                   // 연강(1+2 등)
  if (has2 && !has1 && !isMulti) return 2;

  // 나머지(예: 주말 3타임, 라벨 이상치 등)는 기존 정렬 흐름에 섞이게 중간값
  return 1;
}

function sortDoneEntries(entries) {
  const out = Array.isArray(entries) ? [...entries] : [];

  const nameBySid = new Map(
    (state.students || []).map((s) => [String(s.id), String(s.name || '').trim()]),
  );

  out.sort((a, b) => {
    const aSid = String(a?.[0] || '');
    const bSid = String(b?.[0] || '');
    const aName = nameBySid.get(aSid) || aSid;
    const bName = nameBySid.get(bSid) || bSid;

    const nameCmp = aName.localeCompare(bName, 'ko-KR', { sensitivity: 'base', numeric: true });
    if (nameCmp !== 0) return nameCmp;
    return aSid.localeCompare(bSid, 'ko-KR', { sensitivity: 'base', numeric: true });
  });

  return out;
}

function homeworkRequestRank(dateStr, stu) {
  const sid = stu?.id;
  if (isSelfStudy(dateStr, sid)) return 1;
  const attended = isAttended(dateStr, sid);
  const checked = isHwChecked(dateStr, sid);
  const requested = attended && !checked && isHwCheckRequested(dateStr, sid);
  return requested ? 0 : 1;
}

function compareTodayStudents(dateStr, baseOrder, manualOrder) {
  const collator = new Intl.Collator('ko-KR', { sensitivity: 'base', numeric: true });
  const keys = new WeakMap();
  const keyFor = student => {
    let key = keys.get(student);
    if (!key) {
      const sid = student.id;
      const self = isSelfStudy(dateStr, sid) ? 1 : 0;
      const checked = isHwChecked(dateStr, sid) ? 1 : 0;
      key = {
        group: timeGroupRank(dateStr, sid),
        attended: isAttended(dateStr, sid) ? 1 : 0,
        self,
        status: self ? 2 : checked ? 1 : 0,
        request: homeworkRequestRank(dateStr, student),
        requestedAt: hwCheckRequestedAt(dateStr, sid) || '9999-99-99T99:99:99.999Z',
        minutes: plannedMinutesFor(dateStr, sid),
        name: String(student.name || ''),
        sid: String(sid),
      };
      keys.set(student, key);
    }
    return key;
  };
  return (a, b) => {
    const ka = keyFor(a);
    const kb = keyFor(b);
    const ga = ka.group;
    const gb = kb.group;
    if (ga !== gb) return ga - gb;

    const attA = ka.attended;
    const attB = kb.attended;
    const selfA = ka.self;
    const selfB = kb.self;
    const statusA = ka.status;
    const statusB = kb.status;
    const reqA = ka.request;
    const reqB = kb.request;
    const ta = ka.minutes;
    const tb = kb.minutes;

    if (selfA !== selfB) return selfA - selfB;
    if (attA !== attB) return attA - attB;
    if (reqA !== reqB) return reqA - reqB;
    if (reqA === 0 && reqB === 0) {
      const atA = ka.requestedAt;
      const atB = kb.requestedAt;
      const atCmp = atA.localeCompare(atB);
      if (atCmp !== 0) return atCmp;
    }
    if (statusA !== statusB) return statusA - statusB;
    if (ta !== tb) return ta - tb;

    if (manualOrder) {
      const ai = manualOrder.get(String(a.id)) ?? Number.MAX_SAFE_INTEGER;
      const bi = manualOrder.get(String(b.id)) ?? Number.MAX_SAFE_INTEGER;
      if (ai !== bi) return ai - bi;
    }

    const nameCmp = collator.compare(ka.name, kb.name);
    if (nameCmp !== 0) return nameCmp;

    if (baseOrder) {
      const ai = baseOrder.get(String(a.id)) ?? Number.MAX_SAFE_INTEGER;
      const bi = baseOrder.get(String(b.id)) ?? Number.MAX_SAFE_INTEGER;
      if (ai !== bi) return ai - bi;
    }

    return collator.compare(ka.sid, kb.sid);
  };
}

function sortTodayStudents(list, dateStr, { preserveCurrentOrder = false, savedOrder = [] } = {}) {
  const out = Array.isArray(list) ? list : [];
  const baseOrder = preserveCurrentOrder
    ? new Map(out.map((stu, idx) => [String(stu?.id), idx]))
    : null;
  const manualOrder = new Map();
  for (const id of savedOrder) {
    const sid = String(id);
    if (!manualOrder.has(sid)) manualOrder.set(sid, manualOrder.size);
  }
  out.sort(compareTodayStudents(dateStr, baseOrder, manualOrder));
  return out;
}

// ─────────────────────────────────────────────
// 선택 날짜 명단 계산
// ─────────────────────────────────────────────
async function loadExtraAttendMap() {
  try {
    const m = await fetch('/api/extra-attend', { cache: 'no-store' }).then(r => r.json());
    if (m && typeof m === 'object') {
      state.extra = m;
      window.extra = state.extra;
      return m;
    }
    return {};
  } catch {
    return {};
  }
}

function computeTodayList(dateKey, extraMap = state.extra || {}) {
  const dateStr = dateKey || getAdminDate();
  const wchr = yoilOf(dateStr);
  const studs = state.students || [];
  const absentByDate = state.absentByDate || {};

  const regular = studs.filter(s => hasWeekday(s, wchr));
  const extraIds = (extraMap[dateStr] || []).map(x => String(x).trim());
  const scheduledMakeupIds = scheduledMakeupStudentIdsForDate({
    students: studs,
    carryover: _makeupCarryover || {},
    date: dateStr,
  });
  const supplementalIds = Array.from(new Set([...extraIds, ...scheduledMakeupIds]));
  const supplementalStudents = supplementalIds
    .map(id => studs.find(s => String(s.id) === id))
    .filter(Boolean);

  const seen = new Set();
  let list = [...regular, ...supplementalStudents].filter(s => {
    const id = String(s.id);
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });

  const absentSet = new Set((absentByDate[dateStr] || []).map(String));
  list = list.filter(s => !absentSet.has(String(s.id)));

  const logsDay = state.logs?.[dateStr] || {};
  list = list.filter(s => {
    const e = logsDay[String(s.id)] || {};
    return !(truthy(e.done));
  });

  // 정렬 우선순위:
  // 그룹 > 출석 확인 > 숙검요청(요청 빠른 순) > 숙제 검사 완료 > 등원시간 > 가나다
  return { dateStr, list };
}

// ─────────────────────────────────────────────
// 공개: 로드 + 렌더
// ─────────────────────────────────────────────
let todayRefreshFlight = null;
let todayRefreshTail = Promise.resolve();
let assignmentBoundaryFlight = null;
let todayRenderSeq = 0;
let missingLeaveWarningDateKey = '';
let lastAutoAssignmentBoundaryDate = todayLocalKey();

function renderDoneSummaryWhenIdle(entries, seq, dateKey) {
  const apply = () => {
    if (seq !== todayRenderSeq || !isCurrentAdminDate(dateKey)) return;
    const wrap = document.getElementById('doneWrap');
    const active = document.activeElement;
    if (wrap && active && wrap.contains(active)) {
      wrap.addEventListener('focusout', () => queueMicrotask(apply), { once: true });
      return;
    }
    withStudentLookup(() => renderDone(sortDoneEntries(entries)));
    applyTodaySearchFilter();
  };
  apply();
}

async function refreshUpdatesAtAssignmentBoundary(reason = '') {
  const realDate = todayLocalKey();
  const boundary = reason === 'date' || realDate !== lastAutoAssignmentBoundaryDate;
  if (!boundary) return;
  if (assignmentBoundaryFlight?.realDate === realDate) return assignmentBoundaryFlight.promise;
  const flight = { realDate, promise: null };
  flight.promise = (async () => {
    try {
      const updates = await api.get('/api/updates', { cache: 'no-store' });
      if (assignmentBoundaryFlight !== flight || todayLocalKey() !== realDate) return;
      if (updates && typeof updates === 'object') state.updates = updates;
      lastAutoAssignmentBoundaryDate = realDate;
    } catch {}
  })();
  assignmentBoundaryFlight = flight;
  try { return await flight.promise; }
  finally { if (assignmentBoundaryFlight === flight) assignmentBoundaryFlight = null; }
}

export async function loadTodayAndRender(options = {}) {
  const force = !!options.force;
  const dateKey = getAdminDate();
  const forceDatePayloads = !!(force && (options.reason === 'date' || options.forceDatePayloads));
  const key = JSON.stringify([dateKey, force, forceDatePayloads, options.reason === 'date', todayLocalKey()]);
  const share = options.reason !== 'event' && options.reason !== 'mutation';
  if (share && todayRefreshFlight?.key === key) return todayRefreshFlight.promise;
  const seq = ++todayRenderSeq;
  const pendingBoundary = assignmentBoundaryFlight?.promise;
  if (!share) assignmentBoundaryFlight = null;
  const previous = Promise.all([todayRefreshTail, pendingBoundary]);
  const flight = { key, promise: null };
  flight.promise = (async () => {
    await previous;
    if (seq !== todayRenderSeq || !isCurrentAdminDate(dateKey)) return;

  ensureAlphaSortBtn();
  updateAlphaSortBtn();

  await refreshUpdatesAtAssignmentBoundary(options.reason || '');
  if (seq !== todayRenderSeq || !isCurrentAdminDate(dateKey)) return;


  const extraAttendPromise = loadExtraAttendMap();
  await Promise.all([
    refreshStudentsIfNeeded({ force }),
    refreshAbsencesIfNeeded({ force }),
    ensureLogsForDate(dateKey, { force: forceDatePayloads }),
    ensureProgressForDate(dateKey, { force: forceDatePayloads }),
    loadWeekendSlots(),
    ensureAttendLoaded(dateKey, { force }),
    ensureContactLoaded(dateKey, { force }),
    ensureArriveLoaded(dateKey, { force }),
    loadMakeupCarryoverMap({ force }),
    extraAttendPromise,
    loadOrderMap({ force }),
  ]);

  if (seq !== todayRenderSeq || !isCurrentAdminDate(dateKey)) return;

  const localDoneEntries = sortDoneEntries(collectUnarchivedLogsByDate(dateKey));
  const extraMap = await extraAttendPromise;

  const { list: raw } = await computeTodayList(dateKey, extraMap);
  if (seq !== todayRenderSeq || !isCurrentAdminDate(dateKey)) return;
  const list = withStudentLookup(() => sortTodayStudents(applySavedOrder(raw, dateKey), dateKey, {
    preserveCurrentOrder: true,
    savedOrder: getSavedOrder(dateKey),
  }));

  await ensureProgressHistoryForSids(list.map(s => s.id), { forceHistory: forceDatePayloads });
  if (seq !== todayRenderSeq || !isCurrentAdminDate(dateKey)) return;

  const makeupCounts = aggregateMakeupCountsByStudent(state.students || [], countPendingMakeupsBySid({
    students: state.students || [],
    absentByDate: state.absentByDate || {},
    absentSlotsByDate: state.absentSlotsByDate || {},
    extra: state.extra || {},
    weekendSlots: state.weekendSlots || window.weekendSlots || {},
    carryover: _makeupCarryover || {},
    manualMakeups: _makeupCarryover?.manual || {},
  }));

  const wrap = document.getElementById('todayWrap');
  if (wrap) wrap.dataset.alpha = '0';

  withStudentLookup(() => {
    renderDone(localDoneEntries);
    renderToday(list, dateKey, false, makeupCounts);
  });
  applyTodaySearchFilter();
  renderStaleDoneWarning({ total: 0, byDate: [] });
  // Keep the last authoritative warning through same-date auto refreshes.
  // Clear it only when switching dates so an old date never leaks into the new view.
  if (missingLeaveWarningDateKey !== dateKey) {
    renderMissingLeaveWarning({ total: 0, rowsAvailable: true, rows: [] });
    missingLeaveWarningDateKey = dateKey;
  }
  document.dispatchEvent(new CustomEvent('today:rendered', {
    detail: { dateKey, students: list },
  }));

  void (async () => {
    const [unarchivedSummary, missingLeaveSummary] = await Promise.all([
      fetchUnarchivedDoneSummary(dateKey),
      fetchMissingLeaveSummary(dateKey),
    ]);
    if (seq !== todayRenderSeq || !isCurrentAdminDate(dateKey)) return;
    const summaryDoneEntries = doneEntriesFromUnarchivedSummary(unarchivedSummary);
    if (summaryDoneEntries !== null) renderDoneSummaryWhenIdle(summaryDoneEntries, seq, dateKey);
    renderStaleDoneWarning(unarchivedSummary || { total: 0, byDate: [] });
    renderMissingLeaveWarning(missingLeaveSummary || { total: 0, rowsAvailable: false, rows: [] });
  })();

  })();
  todayRefreshFlight = flight;
  todayRefreshTail = flight.promise.catch(() => {});
  try { return await flight.promise; }
  finally { if (todayRefreshFlight === flight) todayRefreshFlight = null; }
}

function refreshAfterTodayMutation(options = {}) {
  return loadTodayAndRender({ ...options, reason: 'mutation' });
}

// 이벤트 바인딩(1회)
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    bindTodayTableEvents(refreshAfterTodayMutation);
  }, { once: true });
} else {
  bindTodayTableEvents(refreshAfterTodayMutation);
}

function isElementEditing(el) {
  if (!el || el === document.body) return false;
  if (el.id === 'todaySearchInput' || el.id === 'todaySearchField') return false;
  return !!el.closest?.('input, textarea, select, [contenteditable="true"]');
}

function isModalOpen(el) {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
}

function shouldSkipAutoRefresh() {
  if (document.hidden) return true;
  if (isElementEditing(document.activeElement)) return true;
  return [
    '#logModal',
    '#vidModal',
    '#testModal',
    '#extraModal',
    '#absentRegisterModal',
    '#attendModal',
    '#selectionModal',
    '#yoilModal',
  ].some(selector => isModalOpen(document.querySelector(selector)));
}

function initAdminAutoRefresh() {
  if (window.__adminTodayAutoRefreshStarted) return;
  window.__adminTodayAutoRefreshStarted = true;

  const refresh = async () => {
    await refreshUpdatesAtAssignmentBoundary('auto');
    if (shouldSkipAutoRefresh()) return;
    loadTodayAndRender({ force: true, reason: 'auto' });
  };

  window.setInterval(refresh, 30 * 1000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
  });
}

document.addEventListener('admin:refresh', (ev) => {
  const force = !!ev?.detail?.force;
  const forceDatePayloads = !!ev?.detail?.forceDatePayloads;
  loadTodayAndRender({ force, forceDatePayloads, reason: 'event' });
});
document.addEventListener('admin:date-change', () => loadTodayAndRender({ force: true, reason: 'date' }));
initAdminAutoRefresh();
