// /js/admin/features/today.js
// today.js 엔트리(조립본)
// - loadTodayAndRender 공개
// - alpha sort 토글 포함
// - computeTodayList + render 호출
//
// ✅ CHANGE
// - ✅ 정렬 그룹 고정: 1타임(위) > 연강(중간) > 2타임(아래)
//   - 기준: labelFor(dateStr, sid) 텍스트에서 슬롯 숫자 추출
//   - 평일: [1,2], 주말: [1,2,3]
//   - alphaSortOnly(가나다 모드)에서는 예외 없이 이름만 정렬

import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import {
  applySearchPlaceholder,
  matchesSearchKey,
  normalizeSearch as normalizeSharedSearch,
  searchKeyForText as sharedSearchKeyForText,
  studentSearchKey as sharedStudentSearchKey,
} from '../../shared/search.js';
import { countPendingMakeupsBySid } from './makeupPending.js';

import {
  loadWeekendSlots,
  ensureAttendLoaded,
  ensureContactLoaded,
  ensureArriveLoaded,
  collectUnarchivedLogsByDate,
  loadOrderMap,
  applySavedOrder,
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
} from './today.state.js';

import {
  renderToday,
  renderDone,
  bindTodayTableEvents,
} from './today.render.js';

function dateQuery(dateKey) {
  return new URLSearchParams({ date: String(dateKey || '') }).toString();
}

function isCurrentAdminDate(dateKey) {
  return String(getAdminDate() || '') === String(dateKey || '');
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

const logHistoryLoadedSids = new Set();

async function ensureLogHistoryForSids(sids, options = {}) {
  const keys = Array.from(new Set((sids || []).map(sid => String(sid || '').trim()).filter(Boolean)));
  if (!keys.length) return;

  const pending = keys.filter(sid => options.forceHistory || !logHistoryLoadedSids.has(sid));
  if (!pending.length) return;

  for (const sid of pending) {
    try {
      const q = new URLSearchParams({ sid }).toString();
      const res = await fetch(`/api/logs?${q}`, { cache: 'no-store' });
      if (!res.ok) continue;
      const data = await res.json();
      if (data && typeof data === 'object') {
        state.logs = state.logs || {};
        mergeDateSidMap(state.logs, data);
        window.logs = state.logs;
        logHistoryLoadedSids.add(sid);
      }
    } catch {}
  }
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

function ensureStaleDoneWarningStyle() {
  if (document.getElementById('staleDoneWarningStyle')) return;
  const s = document.createElement('style');
  s.id = 'staleDoneWarningStyle';
  s.textContent = `
    #staleDoneWarning{
      display:block;margin:8px 0 0;padding:7px 9px;border-radius:8px;
      border:1px solid rgba(245,158,11,.45);
      background:rgba(245,158,11,.12);
      color:#92400e;font-weight:700;line-height:1.35;
    }
    body.dark #staleDoneWarning{
      border-color:rgba(251,191,36,.5);
      background:rgba(251,191,36,.13);
      color:#fde68a;
    }
    #staleDoneWarning[hidden]{display:none}
  `;
  document.head.appendChild(s);
}

function renderStaleDoneWarning(summary) {
  const anchor = document.getElementById('todaySlotCounts');
  if (!anchor) return;

  ensureStaleDoneWarningStyle();

  let el = document.getElementById('staleDoneWarning');
  if (!el) {
    el = document.createElement('p');
    el.id = 'staleDoneWarning';
    el.className = 'hero-sub';
    el.setAttribute('aria-live', 'polite');
    anchor.insertAdjacentElement('afterend', el);
  }

  const byDateRows = Array.isArray(summary?.byDate) ? summary.byDate : [];
  const total = Number(summary?.total || 0);
  if (!total || !byDateRows.length) {
    el.hidden = true;
    el.textContent = '';
    return;
  }

  const preview = byDateRows
    .slice(0, 3)
    .map((row) => `${row.date} ${row.count}건`)
    .join(', ');
  const more = byDateRows.length > 3 ? ` 외 ${byDateRows.length - 3}일` : '';
  const students = Number(summary?.students || 0);
  const studentText = students && students !== total ? `/${students}명` : '';

  el.hidden = false;
  el.textContent = `정리 필요: 어제까지 하원 ${total}건${studentText} (${preview}${more}). 내보내기 전 확인`;
}

let staleSummaryRequestSeq = 0;
async function refreshStaleDoneWarning(dateKey) {
  const seq = ++staleSummaryRequestSeq;
  try {
    const qs = new URLSearchParams({ exclude_date: String(dateKey || '') });
    const res = await fetch(`/api/logs/unarchived-summary?${qs.toString()}`, { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    if (seq !== staleSummaryRequestSeq) return;
    if (!isCurrentAdminDate(dateKey)) return;
    renderStaleDoneWarning(data);
  } catch (err) {
    console.warn('[today] stale done summary failed:', err);
  }
}

// ─────────────────────────────────────────────
// 오늘 학생 도구/검색
// ─────────────────────────────────────────────
const LS_SEARCH_FIELD = 'todaySearchField';
const TODAY_SEARCH_FIELDS = new Set(['all', 'name', 'school', 'curriculum']);
let _alphaSortOnly = false;
let _todaySearchField = TODAY_SEARCH_FIELDS.has(localStorage.getItem(LS_SEARCH_FIELD))
  ? localStorage.getItem(LS_SEARCH_FIELD)
  : 'all';
let _makeupCarryover = null;

function normalizeSearch(value) {
  return normalizeSharedSearch(value);
}

const HANGUL_BASE = 0xac00;
const HANGUL_END = 0xd7a3;
const HANGUL_INITIALS_COMPAT = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ'];
const HANGUL_INITIALS_LEAD = [
  0x1100, 0x1101, 0x1102, 0x1103, 0x1104, 0x1105, 0x1106, 0x1107, 0x1108,
  0x1109, 0x110a, 0x110b, 0x110c, 0x110d, 0x110e, 0x110f, 0x1110, 0x1111, 0x1112,
].map(code => String.fromCharCode(code));

function hangulInitials(value, initials = HANGUL_INITIALS_COMPAT) {
  return Array.from(String(value || '')).map(ch => {
    const code = ch.charCodeAt(0);
    if (code < HANGUL_BASE || code > HANGUL_END) return ch;
    return initials[Math.floor((code - HANGUL_BASE) / 588)] || ch;
  }).join('');
}

function searchKeyForText(value) {
  return sharedSearchKeyForText(value);
}

function studentFieldValues(stu, field) {
  const school = [
    stu?.school,
    stu?.schoolName,
    stu?.highSchool,
    stu?.middleSchool,
    stu?.high,
    stu?.middle,
    stu?.schoolHigh,
    stu?.schoolMiddle,
  ];
  const curriculum = [
    stu?.curriculum,
    stu?.subCurriculum,
    stu?.subject,
    stu?.course,
  ];

  if (field === 'name') return [stu?.name, stu?.id];
  if (field === 'school') return school;
  if (field === 'curriculum') return curriculum;
  return [stu?.name, stu?.id, ...school, ...curriculum];
}

function studentSearchKey(stu, field) {
  if (field === 'all') return sharedStudentSearchKey(stu);
  if (field === 'name') return sharedStudentSearchKey({ name: stu?.name, id: stu?.id });
  return searchKeyForText(studentFieldValues(stu, field).filter(Boolean).join(' '));
}

function updateAlphaSortBtn() {
  _alphaSortOnly = false;
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
      if (!row.hidden && !row.classList.contains('is-search-hidden')) continue;
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
    const key = stu ? studentSearchKey(stu, mode) : searchKeyForText(row.textContent || '');
    const matches = matchesSearchKey(key, queryText);
    row.hidden = !matches;
    row.classList.toggle('is-search-hidden', !matches);
    row.setAttribute('aria-hidden', matches ? 'false' : 'true');
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

function compareTodayStudents(dateStr, baseOrder) {
  return (a, b) => {
    const ga = timeGroupRank(dateStr, a.id);
    const gb = timeGroupRank(dateStr, b.id);
    if (ga !== gb) return ga - gb;

    const attA = isAttended(dateStr, a.id) ? 1 : 0;
    const attB = isAttended(dateStr, b.id) ? 1 : 0;
    const hwcA = isHwChecked(dateStr, a.id) ? 1 : 0;
    const hwcB = isHwChecked(dateStr, b.id) ? 1 : 0;
    const selfA = isSelfStudy(dateStr, a.id) ? 1 : 0;
    const selfB = isSelfStudy(dateStr, b.id) ? 1 : 0;
    const statusA = selfA ? 2 : hwcA ? 1 : 0;
    const statusB = selfB ? 2 : hwcB ? 1 : 0;
    const reqA = homeworkRequestRank(dateStr, a);
    const reqB = homeworkRequestRank(dateStr, b);
    const ta = plannedMinutesFor(dateStr, a.id);
    const tb = plannedMinutesFor(dateStr, b.id);

    if (selfA !== selfB) return selfA - selfB;
    if (attA !== attB) return attA - attB;
    if (reqA !== reqB) return reqA - reqB;
    if (reqA === 0 && reqB === 0) {
      const atA = hwCheckRequestedAt(dateStr, a.id) || '9999-99-99T99:99:99.999Z';
      const atB = hwCheckRequestedAt(dateStr, b.id) || '9999-99-99T99:99:99.999Z';
      const atCmp = atA.localeCompare(atB);
      if (atCmp !== 0) return atCmp;
    }
    if (statusA !== statusB) return statusA - statusB;
    if (ta !== tb) return ta - tb;

    const nameCmp = String(a.name || '').localeCompare(String(b.name || ''), 'ko-KR', {
      sensitivity: 'base',
      numeric: true,
    });
    if (nameCmp !== 0) return nameCmp;

    if (baseOrder) {
      const ai = baseOrder.get(String(a.id)) ?? Number.MAX_SAFE_INTEGER;
      const bi = baseOrder.get(String(b.id)) ?? Number.MAX_SAFE_INTEGER;
      if (ai !== bi) return ai - bi;
    }

    return String(a.id).localeCompare(String(b.id), 'ko-KR', {
      sensitivity: 'base',
      numeric: true,
    });
  };
}

function sortTodayStudents(list, dateStr, { preserveCurrentOrder = false } = {}) {
  const out = Array.isArray(list) ? list : [];
  const baseOrder = preserveCurrentOrder
    ? new Map(out.map((stu, idx) => [String(stu?.id), idx]))
    : null;
  out.sort(compareTodayStudents(dateStr, baseOrder));
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

async function computeTodayList(dateKey) {
  const dateStr = dateKey || getAdminDate();
  const wchr = yoilOf(dateStr);
  const studs = state.students || [];
  const absentByDate = state.absentByDate || {};

  const extraMap = await loadExtraAttendMap();

  const regular = studs.filter(s => hasWeekday(s, wchr));
  const extraIds = (extraMap[dateStr] || []).map(x => String(x).trim());
  const extraStudents = extraIds
    .map(id => studs.find(s => String(s.id) === id))
    .filter(Boolean);

  const seen = new Set();
  let list = [...regular, ...extraStudents].filter(s => {
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

  // 가나다 모드면 이름만 (그룹 정렬 적용 X)
  if (_alphaSortOnly) {
    list.sort((a, b) => {
      const an = String(a.name || '');
      const bn = String(b.name || '');
      const c = an.localeCompare(bn, 'ko');
      if (c !== 0) return c;
      return String(a.id).localeCompare(String(b.id));
    });
    return { dateStr, list };
  }

  // 정렬 우선순위:
  // 그룹 > 출석 확인 > 숙검요청(요청 빠른 순) > 숙제 검사 완료 > 등원시간 > 가나다
  return { dateStr, list };
}

// ─────────────────────────────────────────────
// 공개: 로드 + 렌더
// ─────────────────────────────────────────────
let todayRenderSeq = 0;

export async function loadTodayAndRender(options = {}) {
  ensureAlphaSortBtn();
  updateAlphaSortBtn();

  const force = !!options.force;
  const seq = ++todayRenderSeq;
  const dateKey = getAdminDate();
  const forceDatePayloads = !!(force && (options.reason === 'date' || options.forceDatePayloads));

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
  ]);

  if (seq !== todayRenderSeq || !isCurrentAdminDate(dateKey)) return;

  const doneEntries = sortDoneEntries(
    collectUnarchivedLogsByDate(dateKey),
  );

  const [{ list: raw }] = await Promise.all([
    computeTodayList(dateKey),
    loadOrderMap({ force }),
  ]);
  if (seq !== todayRenderSeq || !isCurrentAdminDate(dateKey)) return;
  const list = sortTodayStudents(applySavedOrder(raw, dateKey), dateKey, { preserveCurrentOrder: true });

  await ensureProgressHistoryForSids(list.map(s => s.id), { forceHistory: forceDatePayloads });
  if (seq !== todayRenderSeq || !isCurrentAdminDate(dateKey)) return;

  const makeupCounts = countPendingMakeupsBySid({
    students: state.students || [],
    absentByDate: state.absentByDate || {},
    absentSlotsByDate: state.absentSlotsByDate || {},
    extra: state.extra || {},
    weekendSlots: state.weekendSlots || window.weekendSlots || {},
    carryover: _makeupCarryover || {},
    manualMakeups: _makeupCarryover?.manual || {},
  });

  const wrap = document.getElementById('todayWrap');
  if (wrap) wrap.dataset.alpha = '0';

  renderDone(doneEntries);
  renderToday(list, dateKey, false, makeupCounts);
  applyTodaySearchFilter();
  renderStaleDoneWarning({ total: 0, byDate: [] });
  void refreshStaleDoneWarning(dateKey);
  document.dispatchEvent(new CustomEvent('today:rendered', {
    detail: { dateKey, students: list },
  }));
}

// 이벤트 바인딩(1회)
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    bindTodayTableEvents(loadTodayAndRender);
  }, { once: true });
} else {
  bindTodayTableEvents(loadTodayAndRender);
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

  const refresh = () => {
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
