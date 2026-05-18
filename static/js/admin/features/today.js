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
  normalizeSearch as normalizeSharedSearch,
  searchKeyForText as sharedSearchKeyForText,
} from '../../shared/search.js';
import { countPendingMakeupsBySid, makeupPendingActivationDate } from './makeupPending.js';

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
  isHwChecked,
  truthy,
  labelFor,
} from './today.state.js';

import {
  renderToday,
  renderDone,
  bindTodayTableEvents,
} from './today.render.js';

async function ensureLogsForDate(dateKey, options = {}) {
  const key = String(dateKey || '').trim();
  if (!key || (state.logs?.[key] && !options.force)) return;
  try {
    const res = await fetch(`/api/logs?date=${encodeURIComponent(key)}`, { cache: 'no-store' });
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
    const res = await fetch(`/api/progress?date=${encodeURIComponent(key)}`, { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    if (data && typeof data === 'object') {
      state.progress = state.progress || {};
      state.progress[key] = (data[key] && typeof data[key] === 'object') ? data[key] : {};
      window.progressData = state.progress;
    }
  } catch {}
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
      window.absentByDate = state.absentByDate;
      if (window.state) {
        window.state.absentByDate = state.absentByDate;
        window.state.absences = state.absences;
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
  el.textContent = `정리 필요: 어제까지 완료/자유석 ${total}건${studentText} (${preview}${more}). 내보내기 전 확인`;
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
    if (String(getAdminDate() || '') !== String(dateKey || '')) return;
    renderStaleDoneWarning(data);
  } catch (err) {
    console.warn('[today] stale done summary failed:', err);
  }
}

// ─────────────────────────────────────────────
// 가나다 정렬 토글 (localStorage 유지)
// ─────────────────────────────────────────────
const LS_ALPHA_SORT = 'todayAlphaSortOnly';
const LS_SEARCH_FIELD = 'todaySearchField';
const TODAY_SEARCH_FIELDS = new Set(['all', 'name', 'school', 'curriculum']);
let _alphaSortOnly = (localStorage.getItem(LS_ALPHA_SORT) === '1');
let _todaySearchField = TODAY_SEARCH_FIELDS.has(localStorage.getItem(LS_SEARCH_FIELD))
  ? localStorage.getItem(LS_SEARCH_FIELD)
  : 'all';

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
  return searchKeyForText(studentFieldValues(stu, field).filter(Boolean).join(' '));
}

function alphaBtnText() { return _alphaSortOnly ? '원래정렬' : '가나다정렬'; }
function updateAlphaSortBtn() {
  const btn = document.getElementById('todayAlphaSortBtn');
  if (!btn) return;
  btn.textContent = alphaBtnText();
  btn.setAttribute('aria-pressed', _alphaSortOnly ? 'true' : 'false');
  btn.dataset.on = _alphaSortOnly ? '1' : '0';
}

function ensureTodaySearchControls(tools) {
  if (!tools || document.getElementById('todaySearchInput')) return;

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

  const field = search.querySelector('#todaySearchField');
  const input = search.querySelector('#todaySearchInput');
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
  if (document.getElementById('todayAlphaSortBtn') && document.getElementById('todaySearchInput')) return;

  if (!document.getElementById('todayAlphaSortBtnStyle')) {
    const s = document.createElement('style');
    s.id = 'todayAlphaSortBtnStyle';
    s.textContent = `
      .today-tools{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0}
      .today-tools .btn-sort{
        display:inline-flex;align-items:center;justify-content:center;
        height:48px;padding:0 18px;border-radius:15px;
        border:1px solid rgba(148,163,184,.55);
        background:rgba(248,250,252,.95);
        cursor:pointer;user-select:none;font-size:19.5px;line-height:1;
        font-weight:800;
        transition:transform .08s ease, filter .12s ease, background .12s ease, border-color .12s ease;
      }
      body.dark .today-tools .btn-sort{border-color:#334155;background:rgba(2,6,23,.55);color:#e2e8f0}
      .today-tools .btn-sort:hover{filter:brightness(1.03)}
      .today-tools .btn-sort:active{transform:scale(.98)}
      .today-tools .btn-sort[data-on="1"]{background:rgba(99,102,241,.12);border-color:rgba(99,102,241,.55)}
      .today-search{
        display:flex;align-items:center;gap:8px;flex:1 1 420px;min-width:min(100%, 320px);
        margin-left:auto;
      }
      .today-search select,
      .today-search input{
        height:42px;border-radius:12px;border:1px solid rgba(148,163,184,.55);
        background:rgba(248,250,252,.96);color:#0f172a;box-sizing:border-box;
        font-size:15px;font-weight:700;outline:none;
      }
      .today-search select{flex:0 0 116px;padding:0 10px}
      .today-search input{min-width:0;flex:1 1 auto;padding:0 13px}
      .today-search input:focus,
      .today-search select:focus{border-color:rgba(37,99,235,.72);box-shadow:0 0 0 3px rgba(37,99,235,.12)}
      .today-search .today-search-hint{
        flex:0 0 auto;min-width:72px;font-size:13px;font-weight:800;color:#64748b;text-align:right;
      }
      body.dark .today-search select,
      body.dark .today-search input{border-color:#334155;background:rgba(2,6,23,.55);color:#e2e8f0}
      body.dark .today-search .today-search-hint{color:#94a3b8}
      #todayWrap tr.is-search-hidden{display:none !important}
      #todayWrap[data-alpha="1"] .drag-handle{opacity:.35;cursor:default !important}
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

  if (document.getElementById('todayAlphaSortBtn')) {
    ensureTodaySearchControls(tools);
    updateAlphaSortBtn();
    wrap.dataset.alpha = _alphaSortOnly ? '1' : '0';
    return;
  }

  const btn = document.createElement('button');
  btn.id = 'todayAlphaSortBtn';
  btn.type = 'button';
  btn.className = 'btn-sort';
  btn.textContent = alphaBtnText();
  btn.dataset.on = _alphaSortOnly ? '1' : '0';
  btn.setAttribute('aria-pressed', _alphaSortOnly ? 'true' : 'false');
  btn.title = '한 번 누르면 기존 정렬/드래그순서 무시하고 가나다, 다시 누르면 원래 정렬';

  btn.addEventListener('click', () => {
    _alphaSortOnly = !_alphaSortOnly;
    try { localStorage.setItem(LS_ALPHA_SORT, _alphaSortOnly ? '1' : '0'); } catch {}
    updateAlphaSortBtn();
    loadTodayAndRender();
  });

  tools.appendChild(btn);
  ensureTodaySearchControls(tools);
  updateAlphaSortBtn();
  wrap.dataset.alpha = _alphaSortOnly ? '1' : '0';
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ensureAlphaSortBtn, { once: true });
} else {
  ensureAlphaSortBtn();
}

function applyTodaySearchFilter() {
  const host = document.getElementById('todayWrap');
  const input = document.getElementById('todaySearchInput');
  const field = document.getElementById('todaySearchField');
  const hint = document.getElementById('todaySearchHint');
  if (!host || !input) return;

  const query = normalizeSearch(input.value);
  const mode = TODAY_SEARCH_FIELDS.has(field?.value) ? field.value : _todaySearchField;
  const rows = Array.from(host.querySelectorAll('tr[data-sid]'));
  let visible = 0;

  for (const row of rows) {
    const sid = String(row.dataset.sid || '');
    const stu = (state.students || []).find(s => String(s.id) === sid);
    const key = stu ? studentSearchKey(stu, mode) : searchKeyForText(row.textContent || '');
    const matches = !query || key.includes(query);
    row.hidden = !matches;
    row.classList.toggle('is-search-hidden', !matches);
    row.setAttribute('aria-hidden', matches ? 'false' : 'true');
    if (matches) visible += 1;
  }

  if (hint) {
    hint.textContent = query ? `${visible}/${rows.length}명` : '';
  }
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
  // 그룹 > 출석 확인 > 숙제 검사 완료 > 등원시간 > 가나다
  list.sort((a, b) => {
    const ga = timeGroupRank(dateStr, a.id);
    const gb = timeGroupRank(dateStr, b.id);
    if (ga !== gb) return ga - gb;

    const attA = isAttended(dateStr, a.id) ? 1 : 0;
    const attB = isAttended(dateStr, b.id) ? 1 : 0;
    const hwcA = isHwChecked(dateStr, a.id) ? 1 : 0;
    const hwcB = isHwChecked(dateStr, b.id) ? 1 : 0;
    const ta = plannedMinutesFor(dateStr, a.id);
    const tb = plannedMinutesFor(dateStr, b.id);

    if (attA !== attB) return attA - attB;
    if (hwcA !== hwcB) return hwcA - hwcB;
    if (ta !== tb) return ta - tb;

    const nameCmp = String(a.name || '').localeCompare(String(b.name || ''), 'ko');
    if (nameCmp !== 0) return nameCmp;
    return String(a.id).localeCompare(String(b.id));
  });

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

  await Promise.all([
    refreshStudentsIfNeeded({ force }),
    refreshAbsencesIfNeeded({ force }),
    ensureLogsForDate(dateKey, { force }),
    ensureProgressForDate(dateKey, { force }),
    loadWeekendSlots(),
    ensureAttendLoaded(dateKey, { force }),
    ensureContactLoaded(dateKey, { force }),
    ensureArriveLoaded(dateKey, { force }),
  ]);

  if (seq !== todayRenderSeq || String(getAdminDate() || '') !== String(dateKey || '')) return;

  const doneEntries = sortDoneEntries(
    collectUnarchivedLogsByDate(dateKey),
  );

  const [{ list: raw }] = await Promise.all([
    computeTodayList(dateKey),
    loadOrderMap({ force }),
  ]);
  if (seq !== todayRenderSeq || String(getAdminDate() || '') !== String(dateKey || '')) return;
  const list = _alphaSortOnly ? raw : applySavedOrder(raw, dateKey);
  const makeupCounts = countPendingMakeupsBySid({
    students: state.students || [],
    absentByDate: state.absentByDate || {},
    extra: state.extra || {},
    minAbsenceDate: makeupPendingActivationDate(),
  });

  const wrap = document.getElementById('todayWrap');
  if (wrap) wrap.dataset.alpha = _alphaSortOnly ? '1' : '0';

  renderToday(list, dateKey, _alphaSortOnly, makeupCounts);
  applyTodaySearchFilter();
  renderDone(doneEntries);
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
  loadTodayAndRender({ force, reason: 'event' });
});
document.addEventListener('admin:date-change', () => loadTodayAndRender({ force: true, reason: 'date' }));
initAdminAutoRefresh();
