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

async function ensureLogsForDate(dateKey) {
  const key = String(dateKey || '').trim();
  if (!key || state.logs?.[key]) return;
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

// ─────────────────────────────────────────────
// 가나다 정렬 토글 (localStorage 유지)
// ─────────────────────────────────────────────
const LS_ALPHA_SORT = 'todayAlphaSortOnly';
let _alphaSortOnly = (localStorage.getItem(LS_ALPHA_SORT) === '1');

function alphaBtnText() { return _alphaSortOnly ? '원래정렬' : '가나다정렬'; }
function updateAlphaSortBtn() {
  const btn = document.getElementById('todayAlphaSortBtn');
  if (!btn) return;
  btn.textContent = alphaBtnText();
  btn.setAttribute('aria-pressed', _alphaSortOnly ? 'true' : 'false');
  btn.dataset.on = _alphaSortOnly ? '1' : '0';
}
function ensureAlphaSortBtn() {
  if (document.getElementById('todayAlphaSortBtn')) return;

  if (!document.getElementById('todayAlphaSortBtnStyle')) {
    const s = document.createElement('style');
    s.id = 'todayAlphaSortBtnStyle';
    s.textContent = `
      .today-tools{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0}
      .today-tools .btn-sort{
        display:inline-flex;align-items:center;justify-content:center;
        height:32px;padding:0 12px;border-radius:10px;
        border:1px solid rgba(148,163,184,.55);
        background:rgba(248,250,252,.95);
        cursor:pointer;user-select:none;font-size:13px;line-height:1;
        transition:transform .08s ease, filter .12s ease, background .12s ease, border-color .12s ease;
      }
      body.dark .today-tools .btn-sort{border-color:#334155;background:rgba(2,6,23,.55);color:#e2e8f0}
      .today-tools .btn-sort:hover{filter:brightness(1.03)}
      .today-tools .btn-sort:active{transform:scale(.98)}
      .today-tools .btn-sort[data-on="1"]{background:rgba(99,102,241,.12);border-color:rgba(99,102,241,.55)}
      #todayWrap[data-alpha="1"] .drag-handle{opacity:.35;cursor:default !important}
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
  updateAlphaSortBtn();
  wrap.dataset.alpha = _alphaSortOnly ? '1' : '0';
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ensureAlphaSortBtn, { once: true });
} else {
  ensureAlphaSortBtn();
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
    return (m && typeof m === 'object') ? m : {};
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
export async function loadTodayAndRender() {
  ensureAlphaSortBtn();
  updateAlphaSortBtn();

  const dateKey = getAdminDate();

  await ensureLogsForDate(dateKey);
  await loadWeekendSlots();
  await ensureAttendLoaded(dateKey);
  await ensureContactLoaded(dateKey);
  await ensureArriveLoaded(dateKey);

  const doneEntries = sortDoneEntries(
    collectUnarchivedLogsByDate(dateKey),
  );

  const { list: raw } = await computeTodayList(dateKey);

  await loadOrderMap();
  const list = _alphaSortOnly ? raw : applySavedOrder(raw, dateKey);

  const wrap = document.getElementById('todayWrap');
  if (wrap) wrap.dataset.alpha = _alphaSortOnly ? '1' : '0';

  renderToday(list, dateKey, _alphaSortOnly);
  renderDone(doneEntries);
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

document.addEventListener('admin:refresh', loadTodayAndRender);
document.addEventListener('admin:date-change', loadTodayAndRender);
