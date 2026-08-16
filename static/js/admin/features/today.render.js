// /js/admin/features/today.render.js
// today.js rendering and events
//
// Notes:
// - Keep imported `state` and `window.state` aligned.
// - Use patch endpoints for attendance, contact, and arrive-time writes.
// - Move rows into `doneWrap` immediately, then sync remote state.
// - Avoid custom setters for absence maps; update plain objects directly.

import { $, toast } from '../core/utils.js';
import { getAdminDate, getRealToday } from '../core/adminDate.js';
import { state } from '../core/state.js';
import { decorateStudentTestRecordButtons } from '../../shared/testRecordDetails.js';
import { ensureOk, sendJson } from '../../shared/api.js';

import {
  yoilOf,
  labelFor,
  parseSlotsFromText,
  plannedTimeFor,
  plannedTimeBase,
  getArriveOverride,
  setArriveOverride,
  isAttended, setAttended,
  isContacted, setContacted,
  isSelfStudy, setSelfStudyRemote,
  isHwChecked, setHomeworkCheckedRemote,
  isHwCheckRequested, setHomeworkCheckRequestedRemote,
  hwCheckRequestedAt,
  getLeaveTime, setLeaveTimeRemote,
  saveWeekendSlotsFromLabel,
  saveOrder,
  nowHHMM,
  nowISO,
  patchLog,
  truthy,
} from './today.state.js';

// --- state alias helpers ---
function ensureWindowStateAlias() {
  // Some older code paths still read `window.state` directly.
  // Point both references at the same live containers.
  try {
    if (!window.state) window.state = state;
    // If `window.state` is a different object, sync the shared fields only.
    window.state.absences = state.absences;
    window.state.absentByDate = state.absentByDate;
    window.state.absentSlotsByDate = state.absentSlotsByDate;
    window.state.students = state.students;
    window.state.logs = state.logs;
    window.state.progress = state.progress;
  } catch { /* noop */ }
}

// Validate maps shaped like { 'YYYY-MM-DD': ['sid', ...], ... }.
function looksLikeAbsentByDateMap(x) {
  if (!x || typeof x !== 'object') return false;
  const keys = Object.keys(x);
  // Sampling the first few keys is enough here.
  for (let i = 0; i < Math.min(keys.length, 25); i++) {
    const k = keys[i];
    if (/^\d{4}-\d{2}-\d{2}$/.test(k)) return true;
  }
  return false;
}

function normalizeAbsentByDateMap(x) {
  if (!x || typeof x !== 'object') return {};
  const out = {};
  for (const [k, v] of Object.entries(x)) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(k)) continue;
    const arr = Array.isArray(v) ? v.map(String) : [];
    out[k] = Array.from(new Set(arr));
  }
  return out;
}

function normalizeAbsencesByStudent(x) {
  if (!x || typeof x !== 'object') return {};
  const out = {};
  for (const [sid, date] of Object.entries(x)) {
    if (!sid) continue;
    if (typeof date !== 'string') continue;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) continue;
    out[String(sid)] = date;
  }
  return out;
}

function normalizeAbsentSlotMap(x) {
  if (!x || typeof x !== 'object') return {};
  const out = {};
  for (const [date, sidMap] of Object.entries(x)) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(date)) || !sidMap || typeof sidMap !== 'object') continue;
    const rows = {};
    for (const [sid, raw] of Object.entries(sidMap)) {
      const vals = Array.isArray(raw) ? raw : [raw];
      const slots = Array.from(new Set(vals.map(v => parseInt(v, 10)).filter(n => n === 1 || n === 2))).sort((a, b) => a - b);
      if (String(sid).trim() && slots.length) rows[String(sid)] = slots;
    }
    if (Object.keys(rows).length) out[date] = rows;
  }
  return out;
}

function setAbsenceMapsSafely({ byDate, byStudent, bySlot } = {}) {
  state.absentByDate = looksLikeAbsentByDateMap(byDate) ? normalizeAbsentByDateMap(byDate) : (state.absentByDate || {});
  state.absences = (byStudent && typeof byStudent === 'object') ? normalizeAbsencesByStudent(byStudent) : (state.absences || {});
  state.absentSlotsByDate = bySlot && typeof bySlot === 'object' ? normalizeAbsentSlotMap(bySlot) : (state.absentSlotsByDate || {});
  ensureWindowStateAlias();
}

function parseSlotNumbers(raw) {
  const values = Array.isArray(raw) ? raw : [raw];
  const slots = values.flatMap(value => parseSlotsFromText(value));
  return Array.from(new Set(slots)).sort((a, b) => a - b);
}

function rowSlotsForAbsence(dateKey, sid, tr) {
  const weekendSlots =
    parseSlotNumbers(state.weekendSlots?.[dateKey]?.[String(sid)])
      .concat(parseSlotNumbers(window.weekendSlots?.[dateKey]?.[String(sid)]));
  const labelText = tr?.querySelector?.('.slotLabel')?.textContent || labelFor(dateKey, sid);
  const labelSlots = parseSlotNumbers(labelText);
  return Array.from(new Set([...weekendSlots, ...labelSlots])).sort((a, b) => a - b);
}

function closestTodayRow(el) {
  return el?.closest?.('tr[data-sid]') || null;
}

function rowSid(tr) {
  return String(tr?.dataset?.sid || '').trim();
}

function rowDateKey(tr) {
  return String(tr?.dataset?.date || getAdminDate() || '').trim();
}

async function markMakeupDemandOpen(dateKey, sid, slots) {
  const date = String(dateKey || '').trim();
  const studentId = String(sid || '').trim();
  const slotList = parseSlotNumbers(slots);
  if (!date || !studentId) return;

  const latestRes = await fetch('/api/makeup-carryover', { cache: 'no-store' });
  await ensureOk(latestRes, '보강 이월 불러오기');
  const revision = String(latestRes.headers.get('X-Makeup-Carryover-Revision') || '').trim();
  const latest = await latestRes.json();
  const next = latest && typeof latest === 'object' ? latest : {};
  const byAbsence = next.by_absence && typeof next.by_absence === 'object' ? next.by_absence : {};
  const dateRows = { ...(byAbsence[date] || {}) };
  const updatedAt = new Date().toISOString();

  (slotList.length ? slotList : ['']).forEach(slot => {
    const key = slot ? `${studentId}|${slot}` : studentId;
    const prev = dateRows[key] || {};
    dateRows[key] = {
      ...prev,
      state: 'open',
      updatedAt,
      note: prev.note || '',
    };
  });

  byAbsence[date] = dateRows;
  next.by_absence = byAbsence;

  const res = await sendJson('/api/makeup-carryover', next, {
    headers: revision ? { 'If-Match': revision } : {},
  });
  if (res.status === 409 || res.status === 428) {
    throw new Error('다른 관리자 화면에서 보강 정보가 변경됐습니다. 새로고침 후 다시 시도해 주세요.');
  }
  await ensureOk(res, '보강 이월 저장');
}

// Normalize absence maps once at module boot.
(function bootAbsenceMaps() {
  state.absentByDate = looksLikeAbsentByDateMap(state.absentByDate) ? normalizeAbsentByDateMap(state.absentByDate) : (state.absentByDate || {});
  state.absences = (state.absences && typeof state.absences === 'object') ? normalizeAbsencesByStudent(state.absences) : (state.absences || {});
  state.absentSlotsByDate = normalizeAbsentSlotMap(state.absentSlotsByDate || {});
  ensureWindowStateAlias();
})();

// --- remote patch helpers ---
// Use per-field patch endpoints to avoid full-map overwrites.
//   - /api/attendance/patch  {date,sid,value:true/false}
//   - /api/contact/patch     {date,sid,value:true/false}
//   - /api/arrive-time/patch {date,sid,value:"HH:MM"}
async function _postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${url} ${res.status}`);
}

async function patchFlagRemote(kind, date, sid, checked) {
  const url =
    kind === 'att' ? '/api/attendance/patch'
      : kind === 'contact' ? '/api/contact/patch'
        : null;
  if (!url) return;
  await _postJSON(url, { date, sid: String(sid), value: !!checked });
}

async function patchArriveTimeRemote(date, sid, hhmm) {
  await _postJSON('/arrive-time/patch', { date, sid: String(sid), value: String(hhmm || '') });
}

function syncTodayRowVisual(tr) {
  if (!tr) return;
  const selfStudy = tr.dataset.selfStudy === '1';
  const homeworkDone = tr.dataset.hw === '1';
  const homeworkRequested = tr.dataset.hwRequest === '1';
  const attended = tr.dataset.att === '1';
  tr.classList.toggle('is-self-study-row', selfStudy);
  tr.classList.toggle('is-homework-row', homeworkDone);
  tr.classList.toggle('is-homework-request-row', !selfStudy && !homeworkDone && homeworkRequested);
  tr.classList.toggle('is-attended-row', !selfStudy && !homeworkDone && !homeworkRequested && attended);
}

const ARRIVE_WHEEL_STEP_MINUTES = 15;
const ARRIVE_WHEEL_HINT = '클릭 후 스크롤로 15분 조정';
const ARRIVE_WHEEL_ATTENDED_HINT = '출석 체크 완료: 스크롤 조정 불가';

function parseHHMM(value) {
  const match = /^(\d{1,2}):(\d{2})$/.exec(String(value || '').trim());
  if (!match) return null;
  const hh = Number(match[1]);
  const mm = Number(match[2]);
  if (!Number.isInteger(hh) || !Number.isInteger(mm)) return null;
  if (hh < 0 || hh > 23 || mm < 0 || mm > 59) return null;
  return hh * 60 + mm;
}

function formatHHMM(totalMinutes) {
  const clamped = Math.max(0, Math.min((23 * 60) + 45, totalMinutes));
  const hh = Math.floor(clamped / 60);
  const mm = clamped % 60;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
}

function shiftHHMM(value, deltaMinutes) {
  const minutes = parseHHMM(value);
  if (minutes == null) return '';
  return formatHHMM(minutes + deltaMinutes);
}

function handleArriveWheel(ev) {
  const el = ev.target.closest?.('.arriveLabel');
  if (!el) return;
  if (document.activeElement !== el) return;

  const tr = closestTodayRow(el);
  if (!tr) return;
  const sid = rowSid(tr);
  const dateKey = rowDateKey(tr);
  if (!sid || !dateKey) return;
  if (tr.dataset.att === '1' || isAttended(dateKey, sid)) return;

  const next = shiftHHMM(el.textContent, ev.deltaY < 0 ? ARRIVE_WHEEL_STEP_MINUTES : -ARRIVE_WHEEL_STEP_MINUTES);
  if (!next) return;

  ev.preventDefault();
  el.textContent = next;

  setArriveOverride(dateKey, sid, next);
  document.dispatchEvent(new CustomEvent('attendance:updated'));
}

// --- Sortable ---
function tbodyEl() { return document.querySelector('#todayWrap table tbody'); }
function detachSortableIfAny() {
  const tb = tbodyEl();
  if (!tb) return;
  if (tb._sortable) {
    try { tb._sortable.destroy(); } catch { }
    tb._sortable = null;
  }
}
function attachSortable(dateKey, alphaSortOnly) {
  if (alphaSortOnly) { detachSortableIfAny(); return; }
  const tb = tbodyEl();
  if (!tb) return;

  if (tb._sortable) {
    try { tb._sortable.destroy(); } catch { }
    tb._sortable = null;
  }

  if (!window.Sortable) {
    console.warn('[today] SortableJS not loaded');
    return;
  }

  tb._sortable = window.Sortable.create(tb, {
    animation: 150,
    handle: '.drag-handle',
    ghostClass: 'sortable-ghost',
    onEnd: async () => {
      if (alphaSortOnly) return;
      const newOrder = Array.from(tb.querySelectorAll('tr[data-sid]')).map(tr => String(tr.dataset.sid));
      try { await saveOrder(dateKey, newOrder); toast('순서 저장됨'); }
      catch (e) { console.error(e); alert('순서 저장 실패'); }
    },
  });
}

// Inject drag-handle touch style once.
(function () {
  if (document.getElementById('drag-handle-style')) return;
  const s = document.createElement('style');
  s.id = 'drag-handle-style';
  s.textContent = '.drag-handle{touch-action:none;}';
  document.head.appendChild(s);
})();
(function () {
  if (document.getElementById('today-check-style')) return;
  const s = document.createElement('style');
  s.id = 'today-check-style';
  s.textContent = `
    .chk4{display:inline-flex;align-items:center;gap:0}
    .chk4 .c{
      display:inline-flex;align-items:center;justify-content:center;
      width:34px;height:34px;margin:0;border-radius:11px;
      border:1px solid rgba(148,163,184,.55);
      background:rgba(248,250,252,.95);
      transition:transform .08s ease, filter .12s ease, background .12s ease, border-color .12s ease;
      user-select:none;
    }
    body.dark .chk4 .c{border-color:#334155;background:rgba(2,6,23,.55)}
    .chk4 .c:hover{filter:brightness(1.03)}
    .chk4 input{width:20px;height:20px;accent-color:#10b981;margin:0}
    .chk4 .c + .c{margin-left:6px}
    .chk4 .c[data-kind="contact"] input{accent-color:#3b82f6}
    .chk4 .c[data-kind="check"] input{accent-color:#f59e0b}
    .chk4 .c[data-on="1"]{background:rgba(16,185,129,.10);border-color:rgba(16,185,129,.45)}
    .chk4 .c[data-kind="contact"][data-on="1"]{background:rgba(59,130,246,.10);border-color:rgba(59,130,246,.45)}
    .chk4 .c[data-kind="check"][data-on="1"]{background:rgba(245,158,11,.12);border-color:rgba(245,158,11,.55)}
    .chk4 .c:active{transform:scale(.98)}
    .chk4 .c input:disabled{cursor:not-allowed;opacity:.95}
    .self-study-toggle{
      display:inline-flex;align-items:center;justify-content:center;
      width:34px;height:34px;margin:0;border-radius:11px;
      border:1px solid rgba(148,163,184,.55);
      background:rgba(248,250,252,.95);
      user-select:none;
      transition:transform .08s ease, filter .12s ease, background .12s ease, border-color .12s ease;
    }
    .self-study-toggle:hover{filter:brightness(1.02)}
    .self-study-toggle:active{transform:scale(.98)}
    .self-study-toggle input{width:20px;height:20px;margin:0;accent-color:#64748b}
    .self-study-toggle[data-on="1"]{background:rgba(100,116,139,.13);border-color:rgba(100,116,139,.55)}
    body.dark .self-study-toggle{background:rgba(2,6,23,.55);border-color:#334155}
    #todayWrap table.today-table{min-width:1228px;table-layout:fixed;font-size:15px}
    #doneWrap table.done-table{min-width:776px;table-layout:fixed;font-size:15px}
    .today-table th,.today-table td,.done-table th,.done-table td{overflow:hidden;text-overflow:ellipsis}
    .done-table th,.done-table td{text-align:center;vertical-align:middle}
    .today-table th{font-size:14px}
    .today-table td{font-size:15px}
    .today-table .stuName,.done-table .stuName{font-size:15.5px}
    .today-check-cell,.today-self-study-cell,.today-homework-request-cell,.today-doc-cell,.today-action-cell,.makeup-count-cell,.today-progress-cell{text-align:center}
    .today-action-cell,.done-action-cell{white-space:nowrap;overflow:visible!important;text-overflow:clip!important}
    .today-actions{display:inline-flex;align-items:center;justify-content:center;gap:8px;white-space:nowrap}
    .today-actions button{flex:0 0 auto}
    .homework-request-toggle{
      display:inline-flex;align-items:center;justify-content:center;
      width:34px;height:34px;margin:0;border-radius:11px;
      border:1px solid rgba(148,163,184,.55);
      background:rgba(248,250,252,.95);
      user-select:none;
      transition:transform .08s ease, filter .12s ease, background .12s ease, border-color .12s ease;
    }
    .homework-request-toggle:hover{filter:brightness(1.02)}
    .homework-request-toggle:active{transform:scale(.98)}
    .homework-request-toggle input{width:20px;height:20px;margin:0;accent-color:#10b981}
    .homework-request-toggle[data-on="1"]{background:rgba(16,185,129,.10);border-color:rgba(16,185,129,.45)}
    .homework-request-toggle input:disabled{cursor:not-allowed;opacity:.55}
    #todayWrap tr.is-attended-row{background:rgba(16,185,129,.055)!important}
    #todayWrap tr.is-homework-request-row{background:rgba(248,113,113,.11)!important}
    #todayWrap tr.is-homework-row{background:rgba(59,130,246,.085)!important}
    #todayWrap tr.is-self-study-row{background:rgba(100,116,139,.14)!important;color:#64748b}
    body.dark #todayWrap tr.is-attended-row{background:rgba(16,185,129,.14)!important}
    body.dark #todayWrap tr.is-homework-request-row{background:rgba(248,113,113,.16)!important}
    body.dark #todayWrap tr.is-homework-row{background:rgba(59,130,246,.18)!important}
    body.dark #todayWrap tr.is-self-study-row{background:rgba(100,116,139,.22)!important;color:#cbd5e1}
    body.dark .homework-request-toggle{background:rgba(2,6,23,.55);border-color:#334155}
    .makeup-count-cell{
      width:64px;min-width:64px;
      padding-left:4px!important;padding-right:4px!important;
      font-weight:800
    }
    .makeup-count-badge{
      display:inline-flex;align-items:center;justify-content:center;
      min-width:24px;height:24px;padding:0 7px;border-radius:999px;
      border:1px solid rgba(148,163,184,.55);
      background:rgba(248,250,252,.95);color:#64748b;font-size:12px;
      box-sizing:border-box;
    }
    .makeup-count-badge.needs{
      background:rgba(239,68,68,.12);border-color:rgba(239,68,68,.45);color:#b91c1c;
    }
    body.dark .makeup-count-badge{background:rgba(2,6,23,.55);border-color:#334155;color:#94a3b8}
    body.dark .makeup-count-badge.needs{background:rgba(239,68,68,.18);border-color:rgba(248,113,113,.5);color:#fecaca}
    .today-progress-marker{
      display:inline-flex;align-items:center;justify-content:center;
      min-width:24px;height:24px;border-radius:8px;
      border:1px solid rgba(59,130,246,.35);
      background:rgba(59,130,246,.10);color:#1d4ed8;
      font-size:12px;font-weight:900;
    }
    body.dark .today-progress-marker{border-color:rgba(96,165,250,.45);background:rgba(59,130,246,.18);color:#bfdbfe}
    .today-progress-marker.is-test-carryover{
      border-color:rgba(239,68,68,.55);background:rgba(239,68,68,.14);color:#b91c1c;
    }
    body.dark .today-progress-marker.is-test-carryover{
      border-color:rgba(248,113,113,.6);background:rgba(239,68,68,.2);color:#fecaca;
    }
  `;
  document.head.appendChild(s);
})();

// Slot labels force a fixed arrive time.
// - slot 1 => 13:00
// - slot 2 => 18:00
// - mixed slots use the earliest slot
function _parseSlotNumsFromLabel(txt, dateKey = '') {
  return parseSlotsFromText(txt, dateKey);
}

function _forcedArriveTimeBySlotLabel(dateKey, labelText) {
  const nums = _parseSlotNumsFromLabel(labelText, dateKey);
  if (!nums.length) return '';
  const minSlot = Math.min(...nums);
  if (minSlot === 1) return '13:00';
  if (minSlot === 2 || minSlot === 3) return '18:00';
  return '';
}

function _slotGroupsFromLabelAndArrive(labelText, arriveTime, dateKey = '') {
  let nums = _parseSlotNumsFromLabel(labelText, dateKey)
    .map(Number)
    .filter(n => n === 1 || n === 2 || n === 3);

  if (!nums.length) {
    const t = String(arriveTime || '').trim();
    const minutes = parseHHMM(t);
    if (minutes != null) nums = [minutes >= 18 * 60 ? 2 : 1];
  }

  return Array.from(new Set(nums)).sort((a, b) => a - b).join(',');
}

const HOMEWORK_LEAVE_SLOT_BOUNDARY_MINUTES = 18 * 60;

function currentOpsSlot(now = new Date()) {
  const minutes = (now.getHours() * 60) + now.getMinutes();
  return minutes < HOMEWORK_LEAVE_SLOT_BOUNDARY_MINUTES ? 1 : 2;
}

function homeworkLeaveSlotNumbers(row) {
  return Array.from(new Set(
    String(row?.dataset?.slotGroup || '')
      .split(',')
      .map(value => Number(value.trim()))
      .filter(value => value === 1 || value === 2 || value === 3),
  )).sort((a, b) => a - b);
}

function shouldIncludeHomeworkLeaveRow(row, currentSlot = currentOpsSlot()) {
  const homeworkChecked = row?.dataset?.hw === '1';
  const selfStudy = row?.dataset?.selfStudy === '1';
  if (!homeworkChecked && !selfStudy) return false;

  const slots = homeworkLeaveSlotNumbers(row);
  const isConsecutive = slots.length >= 2 && slots.includes(1);
  return !(currentSlot === 1 && isConsecutive);
}

const PROGRESS_MANUAL_META_KEY = '__manualProgressMids';
const TEST_ASSIGN_DAILY_ITEMS_KEY = 'testAssignmentDailyTests';
const TEST_ASSIGN_ABSENCE_CARRYOVER_KEY = 'testAssignmentAbsenceCarryover';
const TEST_ASSIGN_ABSENCE_SOURCE_KEY = 'testAssignmentAbsenceSourceDate';

function escapeAttr(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}

function renderEditableSlotLabel(labelText) {
  const label = String(labelText || '').trim();
  return `<span class="slotLabel" contenteditable="true" spellcheck="false"
          data-orig="${escapeAttr(label)}"
          style="display:inline-block;min-width:48px;padding:2px 6px;border-radius:6px;border:1px solid transparent">
    ${escapeAttr(label)}
  </span>`;
}

function progressEntryForSid(day, sid) {
  if (!day || typeof day !== 'object') return {};
  const sidKey = String(sid || '');
  const direct = day[sidKey];
  if (direct && typeof direct === 'object') return direct;
  const matchedSid = Object.keys(day).find(key => String(key) === sidKey);
  const entry = matchedSid ? day[matchedSid] : null;
  return (entry && typeof entry === 'object') ? entry : {};
}

function normalizeTestAssignmentStatus(status) {
  const raw = status && typeof status === 'object' ? status.status : status;
  const s = String(raw || '').trim();
  if (!s || s === 'none') return '';
  if (s === 'assigned' || s === 'done' || s === 'interrupted' || s === 'skip') return s;
  return 'assigned';
}

function assignedTestItemLabel(item) {
  const label = String(item?.label || '').trim();
  if (label) return label;
  const round = String(item?.round || '').trim();
  const pieces = [
    item?.categoryLabel,
    item?.curriculum,
    item?.difficulty,
    round && /회/.test(round) ? round : (round ? `${round}회차` : ''),
    item?.name,
  ].map(value => String(value || '').trim()).filter(Boolean);
  return pieces.join(' / ');
}

const TEST_ASSIGN_ILSAN_GRAPH_DIFFICULTY = '그래프 포함';
const TEST_ASSIGN_LEGACY_ILSAN_GRAPH_DIFFICULTY = '삼각함수 그래프 포함';
const TEST_ASSIGN_CATEGORY_LABELS = {
  REVIEW: '복습 테스트',
  UNIT: '단원평가',
  SCHOOL_PAST: '학군지 기출',
  ILSAN_PAST: '일산 기출',
};

function testAssignmentCategoryLabel(key) {
  return TEST_ASSIGN_CATEGORY_LABELS[String(key || '').trim()] || String(key || '').trim();
}

function testAssignmentRoundLabel(value) {
  const r = String(value || '').trim();
  if (!r) return '';
  return /회/.test(r) ? r : `${r}회차`;
}

function testAssignmentLabel(item) {
  return String(item?.label || '').trim();
}

function escapeRegExp(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function isIlsanGraphAssignmentItem(item) {
  const categoryKey = String(item?.categoryKey || item?.category || '').trim();
  const source = `${item?.difficulty || ''} ${item?.name || ''} ${item?.label || ''}`;
  return categoryKey === 'ILSAN_PAST' && (
    source.includes(TEST_ASSIGN_ILSAN_GRAPH_DIFFICULTY) ||
    source.includes(TEST_ASSIGN_LEGACY_ILSAN_GRAPH_DIFFICULTY) ||
    source.includes('그래프')
  );
}

function testAssignmentRecordPrefix(item) {
  if (isIlsanGraphAssignmentItem(item)) return '일산기출(그래프부터)';
  const categoryKey = String(item?.categoryKey || item?.category || '').trim();
  const prefix = String(item?.categoryLabel || testAssignmentCategoryLabel(categoryKey) || '')
    .replace(/\s+/g, '') || categoryKey;
  const difficulty = String(item?.difficulty || '').trim();
  return prefix && difficulty ? `${prefix}(${difficulty})` : prefix;
}

function testAssignmentRecordName(item) {
  const label = testAssignmentLabel(item);
  let name = String(item?.name || '').trim();
  if (!name && label) {
    name = label.split('/').map(part => part.trim()).filter(Boolean).pop() || label;
  }
  if (isIlsanGraphAssignmentItem(item)) {
    name = name.replace(/^삼각함수\s*그래프\s*포함\s*/u, '').trim();
  }

  const round = testAssignmentRoundLabel(item?.round);
  if (round) {
    name = name.replace(new RegExp(`^${escapeRegExp(round)}\\s*`, 'u'), '').trim();
  }
  const rawRound = String(item?.round || '').trim();
  if (rawRound && rawRound !== round) {
    name = name.replace(new RegExp(`^${escapeRegExp(rawRound)}\\s*회차\\s*`, 'u'), '').trim();
  }
  return name;
}

function testAssignmentRecordStatusLabel(status) {
  const normalized = normalizeTestAssignmentStatus(status) || 'assigned';
  if (normalized === 'done') return '완료';
  if (normalized === 'assigned' || normalized === 'interrupted') return '배부';
  return '';
}

function buildAssignmentNote(items) {
  const lines = (items || []).map(item => {
    const status = testAssignmentRecordStatusLabel(item?.status);
    if (!status) return '';
    const parts = [
      testAssignmentRecordPrefix(item),
      testAssignmentRoundLabel(item?.round),
      testAssignmentRecordName(item),
    ].filter(Boolean);
    const body = parts.length ? parts.join(' ') : testAssignmentLabel(item);
    return body ? `${body} (${status})` : '';
  }).filter(Boolean);
  return lines.join('\n');
}

function stripAssignmentNoteBlocks(notes) {
  return String(notes || '')
    .replace(/(?:^|\n+)\[테스트 배정\]\n(?:- [^\n]*(?:\n|$))+/g, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function replaceAssignmentNoteBlock(notes, previousBlock, nextBlock) {
  const current = String(notes || '').trimEnd();
  const previous = String(previousBlock || '').trim();
  const replacement = String(nextBlock || '').trim();
  if (!current) return replacement;

  let base = current;
  if (previous) {
    base = base.split(previous).join('');
  }
  base = stripAssignmentNoteBlocks(base);
  if (!replacement) return base;
  return `${base ? `${base}\n\n` : ''}${replacement}`.trim();
}

function completeAssignedTestItems(items) {
  if (!Array.isArray(items)) return { changed: false, items: null };
  let changed = false;
  const nextItems = items.map(item => {
    if (!item || typeof item !== 'object') return item;
    const status = normalizeTestAssignmentStatus(item.status || 'assigned');
    if (status !== 'assigned') return item;
    changed = true;
    return { ...item, status: 'done', statusLabel: '완료' };
  });
  return { changed, items: changed ? nextItems : null };
}

function assignedTestCompletionPatch(progressEntry) {
  const tests = progressEntry?.tests;
  if (!tests || typeof tests !== 'object') return {};

  const patch = {};
  Object.entries(tests).forEach(([label, status]) => {
    const labelKey = String(label || '').trim();
    if (!labelKey || normalizeTestAssignmentStatus(status) !== 'assigned') return;
    patch[labelKey] = status && typeof status === 'object'
      ? { ...status, status: 'done' }
      : 'done';
  });
  return patch;
}

function hasCleanupAssignmentItems(entry) {
  return Array.isArray(entry?.[TEST_ASSIGN_DAILY_ITEMS_KEY]) || Array.isArray(entry?.assignedTests);
}

async function fetchLogEntryForCleanup(dateKey, sid) {
  const current = logEntryForSid(dateKey, sid);
  if (hasCleanupAssignmentItems(current)) return current;

  const res = await fetch(`/api/logs/entry?date=${encodeURIComponent(dateKey)}&sid=${encodeURIComponent(sid)}`, {
    cache: 'no-store',
  });
  if (!res.ok) return current;
  const data = await res.json().catch(() => ({}));
  const entry = data?.entry && typeof data.entry === 'object' ? data.entry : {};
  if (Object.keys(entry).length) {
    state.logs = state.logs || {};
    state.logs[dateKey] = state.logs[dateKey] || {};
    state.logs[dateKey][String(sid)] = entry;
    window.logs = state.logs;
    ensureWindowStateAlias();
    return entry;
  }
  return current;
}

function recordCleanupLogTestPatch(entry) {
  const patch = {};

  [TEST_ASSIGN_DAILY_ITEMS_KEY, 'assignedTests'].forEach(key => {
    const result = completeAssignedTestItems(entry?.[key]);
    if (result.changed) patch[key] = result.items;
  });

  const dailyItems = Array.isArray(patch[TEST_ASSIGN_DAILY_ITEMS_KEY])
    ? patch[TEST_ASSIGN_DAILY_ITEMS_KEY]
    : (Array.isArray(entry?.[TEST_ASSIGN_DAILY_ITEMS_KEY]) ? entry[TEST_ASSIGN_DAILY_ITEMS_KEY] : []);
  const noteBlock = buildAssignmentNote(dailyItems);
  if (noteBlock) {
    patch.testAssignmentNote = noteBlock;
    const prevNotes = String(entry?.notes || '').trimEnd();
    const prevBlock = String(entry?.testAssignmentNote || '').trim();
    const nextNotes = replaceAssignmentNoteBlock(prevNotes, prevBlock, noteBlock);
    if (nextNotes.trim() !== prevNotes.trim()) patch.notes = nextNotes.trim();
  }

  return patch;
}

function completedTestLabelsFromLogPatch(logPatch) {
  const labels = new Set();
  [TEST_ASSIGN_DAILY_ITEMS_KEY, 'assignedTests'].forEach(key => {
    const items = logPatch?.[key];
    if (!Array.isArray(items)) return;
    items.forEach(item => {
      if (normalizeTestAssignmentStatus(item?.status) !== 'done') return;
      const label = assignedTestItemLabel(item);
      if (label) labels.add(label);
    });
  });
  return labels;
}

function hasProgressTestStatuses(entry) {
  const tests = entry?.tests;
  return !!(tests && typeof tests === 'object' && Object.keys(tests).some(label => String(label || '').trim()));
}

async function fetchProgressEntryForCleanup(dateKey, sid) {
  const current = progressEntryForSid(state.progress?.[dateKey], sid);
  if (hasProgressTestStatuses(current)) return current;

  const res = await fetch(`/api/progress?date=${encodeURIComponent(dateKey)}&sid=${encodeURIComponent(sid)}`, {
    cache: 'no-store',
  });
  if (!res.ok) return {};
  const data = await res.json().catch(() => ({}));
  const day = data?.[dateKey] && typeof data[dateKey] === 'object' ? data[dateKey] : {};
  const entry = progressEntryForSid(day, sid);
  if (Object.keys(entry).length) {
    state.progress = state.progress || {};
    state.progress[dateKey] = state.progress[dateKey] || {};
    state.progress[dateKey][String(sid)] = entry;
    window.progressData = state.progress;
    ensureWindowStateAlias();
  }
  return entry;
}

export async function completeAssignedTestsForRecordCleanup(dateKey, sid) {
  if (isSidAbsentOn(dateKey, sid)) return {};

  const logEntry = await fetchLogEntryForCleanup(dateKey, sid);
  const logPatch = recordCleanupLogTestPatch(logEntry);
  const progressEntry = await fetchProgressEntryForCleanup(dateKey, sid);
  const progressTests = assignedTestCompletionPatch(progressEntry);
  const currentProgressTests = progressEntry?.tests && typeof progressEntry.tests === 'object'
    ? progressEntry.tests
    : {};
  completedTestLabelsFromLogPatch(logPatch).forEach(label => {
    if (!normalizeTestAssignmentStatus(currentProgressTests[label])) {
      progressTests[label] = 'done';
    }
  });

  if (Object.keys(progressTests).length) {
    const res = await fetch('/api/progress/patch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        date: dateKey,
        sid,
        progress: { tests: progressTests },
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.error || `/api/progress/patch ${res.status}`);
    if (data?.progress && typeof data.progress === 'object') {
      state.progress = state.progress || {};
      state.progress[dateKey] = state.progress[dateKey] || {};
      state.progress[dateKey][String(sid)] = data.progress;
      window.progressData = state.progress;
      ensureWindowStateAlias();
    }
  }

  return logPatch;
}

function shouldSkipForLow(student, video) {
  if (!student || student.level !== '하') return false;
  const ex = video?.exNum;
  if (!ex || typeof ex !== 'object') return false;
  return Number(ex['하']) === 0;
}

function progressVideoGroupKey(item) {
  return `${String(item?.curriculum || '')}\n${String(item?.subCurriculum || '')}`;
}

function logEntryForSid(dateKey, sid) {
  return progressEntryForSid(state.logs?.[dateKey], sid);
}

function carryoverTestItems(entry) {
  const carryover = entry?.[TEST_ASSIGN_ABSENCE_CARRYOVER_KEY];
  const items = carryover?.assignedTests;
  return Array.isArray(items)
    ? items.filter(item => item && typeof item === 'object' && String(item.label || item.name || '').trim())
    : [];
}

function isSidAbsentOn(dateKey, sid) {
  return new Set((state.absentByDate?.[dateKey] || []).map(String)).has(String(sid));
}

function carryoverConsumedBefore({ sourceDate, targetDate, sid }) {
  return Object.keys(state.logs || {})
    .filter(date => /^\d{4}-\d{2}-\d{2}$/.test(date) && date > sourceDate && date < targetDate)
    .some(date => String(logEntryForSid(date, sid)?.[TEST_ASSIGN_ABSENCE_SOURCE_KEY] || '') === sourceDate);
}

function findAbsentTestCarryover(dateKey, sid) {
  const targetDate = String(dateKey || '');
  const sidKey = String(sid || '');
  if (!targetDate || !sidKey) return null;

  const dates = Object.keys(state.logs || {})
    .filter(date =>
      /^\d{4}-\d{2}-\d{2}$/.test(date) &&
      date < targetDate &&
      isSidAbsentOn(date, sidKey)
    )
    .sort()
    .reverse();

  for (const sourceDate of dates) {
    const entry = logEntryForSid(sourceDate, sidKey);
    const items = carryoverTestItems(entry);
    if (!items.length) continue;
    if (carryoverConsumedBefore({ sourceDate, targetDate, sid: sidKey })) continue;
    return { sourceDate, items };
  }
  return null;
}

function buildAbsentTestCarryoverMap(dateKey, students) {
  const out = new Map();
  (students || []).forEach(student => {
    const sid = String(student?.id || '');
    const carryover = findAbsentTestCarryover(dateKey, sid);
    if (carryover) out.set(sid, carryover);
  });
  return out;
}

function buildProgressTestMarkerSet(dateKey, students) {
  const targetDate = String(dateKey || '');
  const videosByGroup = new Map();
  for (const video of state.videos || []) {
    const mid = String(video?.mid || '').trim();
    if (!mid) continue;
    const key = progressVideoGroupKey(video);
    const group = videosByGroup.get(key) || [];
    group.push({ ...video, mid });
    videosByGroup.set(key, group);
  }

  const progressDates = Object.keys(state.progress || {})
    .filter(date => /^\d{4}-\d{2}-\d{2}$/.test(date) && (!targetDate || date <= targetDate))
    .sort();

  const ready = new Set();
  if (!videosByGroup.size) return ready;

  for (const student of students || []) {
    const sid = String(student?.id || '');
    if (!sid) continue;

    const videos = videosByGroup.get(progressVideoGroupKey(student)) || [];
    if (!videos.length) continue;

    const mids = new Set(videos.map(video => video.mid));
    const progressByMid = {};
    const explicitNoneMids = new Set();

    for (const date of progressDates) {
      const entry = progressEntryForSid(state.progress?.[date], sid);
      const manualMeta = (entry[PROGRESS_MANUAL_META_KEY] && typeof entry[PROGRESS_MANUAL_META_KEY] === 'object')
        ? entry[PROGRESS_MANUAL_META_KEY]
        : {};

      Object.entries(entry).forEach(([mid, status]) => {
        const key = String(mid);
        if (key.startsWith('__') || key === 'tests' || !mids.has(key)) return;

        const value = String(status || 'none');
        if (value === 'none') {
          if (manualMeta[key]) {
            progressByMid[key] = 'none';
            explicitNoneMids.add(key);
          }
          return;
        }

        progressByMid[key] = value;
        explicitNoneMids.delete(key);
      });
    }

    const complete = videos.every(video => {
      const mid = video.mid;
      const status = explicitNoneMids.has(mid)
        ? 'none'
        : (progressByMid[mid] || (shouldSkipForLow(student, video) ? 'skip' : ''));
      return status === 'done' || status === 'skip';
    });
    if (complete) ready.add(sid);
  }

  return ready;
}

// Move completed rows into doneWrap immediately.
function _ensureDoneTableIfMissing() {
  const wrap = $('doneWrap');
  if (!wrap) return null;

  const tb = wrap.querySelector('tbody');
  if (tb) return tb;

  wrap.innerHTML = `
    <table class="done-table">
      <colgroup>
        <col style="width:72px"><col style="width:64px"><col style="width:120px"><col style="width:84px">
        <col style="width:112px"><col style="width:268px"><col style="width:56px">
      </colgroup>
      <thead>
        <tr>
          <th>구분</th>
          <th title="등원시간">등원</th>
          <th>이름</th>
          <th>학교</th>
          <th>커리큘럼</th>
          <th>작업</th>
          <th>문서</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  `;
  return wrap.querySelector('tbody');
}

function _bindDoneWrapInlineEditOnce() {
  const wrap = $('doneWrap');
  if (!wrap) return;

  if (wrap._doneDelegated) return;
  wrap._doneDelegated = true;

  wrap.addEventListener('wheel', handleArriveWheel, { passive: false });

  wrap.addEventListener('keydown', (ev) => {
    const el = ev.target.closest?.('.slotLabel,.arriveLabel,.leaveLabel');
    if (!el) return;
    if (ev.key === 'Enter') { ev.preventDefault(); el.blur(); }
    if (ev.key === 'Escape') { el.textContent = el.dataset.orig || ''; el.blur(); }
  });

  wrap.addEventListener('focusin', (ev) => {
    const el = ev.target.closest?.('.slotLabel,.arriveLabel,.leaveLabel');
    if (!el) return;
    el.style.borderColor = '#cbd5e1';
    el.style.background = 'rgba(148,163,184,.12)';
  });

  wrap.addEventListener('focusout', async (ev) => {
    const el = ev.target.closest?.('.slotLabel');
    if (!el) return;

    el.style.borderColor = 'transparent';
    el.style.background = 'transparent';

    const tr = closestTodayRow(el); if (!tr) return;
    const sid = rowSid(tr);
    const date = rowDateKey(tr);
    if (!sid || !date) return;

    const prevOrig = el.dataset.orig || '';
    const prevLabel = prevOrig.trim();
    const oldForcedBase = _forcedArriveTimeBySlotLabel(date, prevLabel) || '';
    const txt = (el.textContent || '').trim();
    const cleaned = txt.replace(/\(보강\)/g, '').trim();
    el.textContent = cleaned;

    const oldBase = plannedTimeBase(date, sid) || '';
    const oldOv = (getArriveOverride(date, sid) || '').trim();

    try {
      await saveWeekendSlotsFromLabel(sid, cleaned, date);
    } catch (e) {
      el.textContent = prevOrig;
      el.dataset.orig = prevOrig;
      try { toast('주말 슬롯 저장 실패'); } catch {}
      alert('주말 슬롯 저장 실패');
      return;
    }

    el.dataset.orig = cleaned;

    const arriveEl = tr.querySelector('.arriveLabel');
    const slotGroup = _slotGroupsFromLabelAndArrive(cleaned, arriveEl?.textContent || '', date);
    if (slotGroup) tr.dataset.slotGroup = slotGroup;
    else delete tr.dataset.slotGroup;

    document.dispatchEvent(new CustomEvent('attendance:updated'));

    const forcedNewBase = _forcedArriveTimeBySlotLabel(date, cleaned) || '';
    const shouldAuto =
      (!oldOv) ||
      (oldForcedBase && oldOv === oldForcedBase) ||
      (oldOv === oldBase);

    if (shouldAuto && forcedNewBase) {
      setArriveOverride(date, sid, forcedNewBase);
      if (arriveEl) {
        arriveEl.textContent = forcedNewBase;
        arriveEl.dataset.orig = forcedNewBase;
      }

      try {
        await patchArriveTimeRemote(date, sid, forcedNewBase);
      } catch (e) {
        console.error(e);
        setArriveOverride(date, sid, oldOv);
        if (arriveEl) {
          arriveEl.textContent = oldOv;
          arriveEl.dataset.orig = oldOv;
        }
        alert('도착시간 저장 실패');
      }
    }
  });

  // doneWrap edits only update the local override value.
  wrap.addEventListener('focusout', async (ev) => {
    const el = ev.target.closest?.('.arriveLabel');
    if (!el) return;

    el.style.borderColor = 'transparent';
    el.style.background = 'transparent';

    const tr = closestTodayRow(el); if (!tr) return;
    const sid = rowSid(tr);
    const date = rowDateKey(tr);
    if (!sid || !date) return;

    const prev = (el.dataset.orig || '').trim();
    const txt = (el.textContent || '').trim();
    setArriveOverride(date, sid, txt);

    try {
      await patchArriveTimeRemote(date, sid, txt);
      el.dataset.orig = txt;
    } catch (e) {
      console.error(e);
      setArriveOverride(date, sid, prev);
      el.textContent = prev;
      el.dataset.orig = prev;
      alert('도착시간 저장 실패');
    }
  });

  wrap.addEventListener('focusout', async (ev) => {
    const el = ev.target.closest?.('.leaveLabel');
    if (!el) return;

    el.style.borderColor = 'transparent';
    el.style.background = 'transparent';

    const tr = closestTodayRow(el); if (!tr) return;
    const sid = rowSid(tr);
    const date = rowDateKey(tr);
    if (!sid || !date) return;

    const txt = (el.textContent || '').trim();
    el.dataset.orig = txt;

    try { await setLeaveTimeRemote(date, sid, txt); }
    catch (e) { console.error(e); alert('하원시간 저장 실패'); }
  });
}

function _isInTodayWrap(tr) { return !!tr?.closest?.('#todayWrap'); }
function _isInDoneWrap(tr) { return !!tr?.closest?.('#doneWrap'); }

function _moveTodayRowToDoneWrap(tr, dateKey) {
  // Only move rows that still belong to the today list.
  if (!_isInTodayWrap(tr)) return;

  const tbDone = _ensureDoneTableIfMissing();
  if (!tbDone) return;

  _bindDoneWrapInlineEditOnce();

  const label = (tr.querySelector('.slotLabel')?.textContent || '').trim();
  const arrive = (tr.querySelector('.arriveLabel')?.textContent || '').trim();

  const nameLink = tr.querySelector('a.stuName');
  const nameCellHtml = nameLink
    ? nameLink.outerHTML
    : `<span class="stuName">${(tr.querySelector('.stuName')?.textContent || '').trim()}</span>`;

  const school = (tr.querySelector('.today-school-cell')?.textContent || '').trim();
  const curLabel = (tr.querySelector('.today-curriculum-cell')?.textContent || '').trim();
  const docBtn = tr.querySelector('.btn-doc');
  const docUrl = docBtn?.dataset?.docUrl || '';

  const sid = String(tr.dataset.sid || '');
  const slotGroup = tr.dataset.slotGroup || _slotGroupsFromLabelAndArrive(label, arrive, dateKey);
  const arriveTitle = (tr.dataset.att === '1' || isAttended(dateKey, sid)) ? ARRIVE_WHEEL_ATTENDED_HINT : ARRIVE_WHEEL_HINT;

  const newRow = document.createElement('tr');
  newRow.dataset.sid = sid;
  newRow.dataset.date = dateKey;
  if (slotGroup) newRow.dataset.slotGroup = slotGroup;
  if (tr.dataset.hw === '1') newRow.dataset.hw = '1';
  if (tr.dataset.selfStudy === '1') newRow.dataset.selfStudy = '1';
  newRow.innerHTML = `
    <td class="today-slot-cell">${renderEditableSlotLabel(label)}</td>
    <td class="att-time done-arrive-cell">
      <span class="arriveLabel" contenteditable="true" spellcheck="false"
            data-orig="${escapeAttr(arrive)}"
            title="${arriveTitle}"
            style="display:inline-block;min-width:44px;padding:2px 4px;border-radius:6px;border:1px solid transparent">
        ${escapeAttr(arrive)}
      </span>
    </td>
    <td class="today-name-cell">${nameCellHtml}</td>
    <td class="today-school-cell">${school || ''}</td>
    <td class="today-curriculum-cell">${curLabel || ''}</td>
    <td class="done-action-cell">
      <div class="today-actions">
      <button class="openStudentPopups" title="상담 기록">🧾</button>
      <button class="studentTestRecordBtn" data-test-result-sid="${escapeAttr(sid)}" title="테스트 기록 보기">기록</button>
      <button class="markAbsent" title="결석">🚫</button>
      <button class="markLeave" title="하원">🏠</button>
      <button class="undoDone" title="하원 되돌리기" style="margin-left:6px">↩️</button>
      <button class="clearDone" title="기록 정리" style="margin-left:6px">🧹</button>
      </div>
    </td>
    <td class="today-doc-cell"><button class="btn-doc" data-doc-url="${docUrl}" title="문서 열기">📄</button></td>
  `;

  tbDone.prepend(newRow);

  tr.remove();

  const cnt = $('todayCount');
  if (cnt && tr.dataset.selfStudy !== '1') {
    const cur = parseInt(cnt.textContent || '0', 10);
    cnt.textContent = String(Math.max(0, (Number.isFinite(cur) ? cur : 0) - 1));
  }

  const wrapToday = $('todayWrap');
  if (wrapToday) {
    const remain = wrapToday.querySelectorAll('tr[data-sid]').length;
    if (!remain) wrapToday.innerHTML = '오늘 학생 없음';
  }
}

function ensureSelfStudyHeader(host) {
  const headRow = host?.querySelector?.('thead tr');
  if (!headRow || headRow.querySelector('.today-self-study-head')) return;
  const th = document.createElement('th');
  th.className = 'today-self-study-head';
  th.textContent = '자습';
  headRow.insertBefore(th, headRow.children[5] || null);
}

// --- render ---
export function renderToday(list, dateKey, alphaSortOnly, makeupCounts = {}) {
  const host = $('todayWrap');
  const cnt = $('todayCount');
  if (!host) return;

  const progressReadySids = buildProgressTestMarkerSet(dateKey, list);
  const absentTestCarryoverBySid = buildAbsentTestCarryoverMap(dateKey, list);
  const rows = list.map(s => {
    const curLabel = s.curriculum + (s.subCurriculum ? ' ' + s.subCurriculum : '');
    const label = labelFor(dateKey, s.id);

    const attended = isAttended(dateKey, s.id);
    const contacted = isContacted(dateKey, s.id);
    const selfStudy = isSelfStudy(dateKey, s.id);
    const hwChecked = isHwChecked(dateKey, s.id);
    const hwRequested = isHwCheckRequested(dateKey, s.id);
    const hwRequestAt = hwCheckRequestedAt(dateKey, s.id);

    const arriveTime = plannedTimeFor(dateKey, s.id);
    const school =
      s.school ?? s.schoolName ?? s.highSchool ?? s.middleSchool ??
      s.high ?? s.middle ?? s.schoolHigh ?? s.schoolMiddle ?? '';

    const labelText = (label || yoilOf(dateKey) || '').trim();
    const makeupCount = Number(makeupCounts?.[String(s.id)] || 0);
    const progressReady = progressReadySids.has(String(s.id));
    const absentTestCarryover = absentTestCarryoverBySid.get(String(s.id));
    const progressMarker = absentTestCarryover
      ? `<span class="today-progress-marker is-test-carryover" title="${escapeAttr(`${absentTestCarryover.sourceDate} 결석일 테스트 배부됨`)}">T</span>`
      : (progressReady ? '<span class="today-progress-marker">T</span>' : '');
    const arriveTitle = attended ? ARRIVE_WHEEL_ATTENDED_HINT : ARRIVE_WHEEL_HINT;
    const slotGroup = _slotGroupsFromLabelAndArrive(labelText, arriveTime, dateKey);
    const rowClass = selfStudy
      ? 'is-self-study-row'
      : hwChecked
      ? 'is-homework-row'
      : hwRequested
        ? 'is-homework-request-row'
        : attended
          ? 'is-attended-row'
          : '';

    return `
      <tr class="${rowClass}" data-sid="${s.id}" data-date="${dateKey}"
          ${attended ? 'data-att="1"' : ''} ${contacted ? 'data-contact="1"' : ''}
          ${selfStudy ? 'data-self-study="1"' : ''}
          ${hwChecked ? 'data-hw="1"' : ''} ${hwRequested ? 'data-hw-request="1"' : ''}
          ${slotGroup ? `data-slot-group="${slotGroup}"` : ''}
          ${hwRequestAt ? `data-hw-request-at="${hwRequestAt}"` : ''}>
        <td class="drag-handle today-drag-cell" style="cursor:${alphaSortOnly ? 'default' : 'grab'};text-align:center">::</td>

        <td class="today-slot-cell">${renderEditableSlotLabel(labelText)}</td>

        <td class="today-name-cell">
          <a href="/student/${s.id}" target="_blank" class="stuName" data-sid="${s.id}">
            ${s.name}
          </a>
        </td>

        <td class="att-time" style="text-align:center;width:84px;">
          <span class="arriveLabel" contenteditable="true" spellcheck="false"
                data-orig="${arriveTime || ''}"
                title="${arriveTitle}"
                style="display:inline-block;min-width:56px;padding:2px 6px;border-radius:6px;border:1px solid transparent">
            ${arriveTime || ''}
          </span>
        </td>

        <td class="today-check-cell">
          <div class="chk4" aria-label="체크 3종">
            <label class="c" data-kind="att" data-on="${attended ? '1' : '0'}" title="출석">
              <input type="checkbox" class="attendChk" data-id="${s.id}" ${attended ? 'checked' : ''}>
            </label>
            <label class="c" data-kind="contact" data-on="${contacted ? '1' : '0'}" title="연락">
              <input type="checkbox" class="contactChk" data-id="${s.id}" ${contacted ? 'checked' : ''}>
            </label>
            <label class="c" data-kind="check" data-on="${hwChecked ? '1' : '0'}" title="숙제 체크 완료">
              <input type="checkbox" class="hwCheckChk" data-id="${s.id}" ${hwChecked ? 'checked' : ''}>
            </label>
          </div>
        </td>

        <td class="today-self-study-cell">
          <label class="self-study-toggle" data-on="${selfStudy ? '1' : '0'}" title="자습">
            <input type="checkbox" class="selfStudyChk" data-id="${s.id}" ${selfStudy ? 'checked' : ''}>
          </label>
        </td>

        <td class="today-homework-request-cell">
          <label class="homework-request-toggle" data-on="${hwRequested ? '1' : '0'}" title="숙검요청">
            <input type="checkbox" class="hwRequestChk" data-id="${s.id}" ${hwRequested ? 'checked' : ''} ${hwChecked || selfStudy ? 'disabled' : ''}>
          </label>
        </td>

        <td class="today-school-cell">${school || ''}</td>
        <td class="today-curriculum-cell">${curLabel}</td>
        <td class="today-progress-cell">${progressMarker}</td>

        <td class="today-action-cell">
          <div class="today-actions">
          <button class="openStudentPopups" title="상담 기록">🧾</button>
          <button class="studentTestRecordBtn" data-test-result-sid="${escapeAttr(s.id)}" data-test-result-name="${escapeAttr(s.name || s.id)}" title="테스트 기록 보기">기록</button>
          <button class="markAbsent" title="결석">🚫</button>
          <button class="markLeave" title="하원">🏠</button>
          </div>
        </td>
        <td class="makeup-count-cell">
          <span class="makeup-count-badge ${makeupCount > 0 ? 'needs' : ''}">${makeupCount}</span>
        </td>
        <td class="today-doc-cell"><button class="btn-doc" data-doc-url="${s.docUrl || ''}" title="문서 열기">📄</button></td>
      </tr>
    `;
  }).join('');

  detachSortableIfAny();
  host.innerHTML = list.length ? `
      <table class="today-table">
      <colgroup>
        <col style="width:32px"><col style="width:72px"><col style="width:120px"><col style="width:84px">
        <col style="width:168px"><col style="width:44px"><col style="width:84px"><col style="width:84px"><col style="width:112px">
        <col style="width:36px"><col style="width:268px"><col style="width:64px"><col style="width:56px">
      </colgroup>
      <thead>
        <tr>
          <th></th>
          <th>구분</th>
          <th>이름</th>
          <th>도착</th>
          <th>출석/연락/숙제</th>
          <th>숙검요청</th>
          <th>학교</th>
          <th>커리큘럼</th>
          <th>진도</th>
          <th>작업</th>
          <th>보강</th>
          <th>문서</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  ` : '오늘 학생 없음';

  ensureSelfStudyHeader(host);

  if (cnt) cnt.textContent = String(list.filter(s => !isSelfStudy(dateKey, s.id)).length);

  decorateStudentTestRecordButtons(host).catch(console.warn);
  requestAnimationFrame(() => attachSortable(dateKey, alphaSortOnly));
}

export function renderDone(doneEntries) {
  const wrap = $('doneWrap');
  if (!wrap) return;

  if (!doneEntries.length) {
    wrap.innerHTML = '하원 기록 없음';
    return;
  }

  const rows = doneEntries.map(([sid, entry, date]) => {
    const s =
      (window?.state?.students || []).find?.(x => String(x.id) === String(sid))
      || (document?.defaultView?.state?.students || []).find?.(x => String(x.id) === String(sid))
      || null;

    const name = s?.name || String(sid);
    const curLabel = s ? (s.curriculum + (s.subCurriculum ? ' ' + s.subCurriculum : '')) : '';
    const school = s ? (s.school ?? s.schoolName ?? s.highSchool ?? s.middleSchool ?? s.high ?? s.middle ?? '') : '';
    const docUrl = s?.docUrl || '';

    const arriveTime = plannedTimeFor(date, sid);
    const label = labelFor(date, sid);
    const slotGroup = _slotGroupsFromLabelAndArrive(label, arriveTime, date);
    const hwChecked = truthy(entry?.hwChecked);
    const selfStudy = truthy(entry?.selfStudy) || isSelfStudy(date, sid);
    const arriveTitle = isAttended(date, sid) ? ARRIVE_WHEEL_ATTENDED_HINT : ARRIVE_WHEEL_HINT;

    return `
      <tr data-sid="${sid}" data-date="${date}" ${slotGroup ? `data-slot-group="${slotGroup}"` : ''} ${hwChecked ? 'data-hw="1"' : ''} ${selfStudy ? 'data-self-study="1"' : ''}>
        <td class="today-slot-cell">${renderEditableSlotLabel(label)}</td>
        <td class="att-time done-arrive-cell">
          <span class="arriveLabel" contenteditable="true" spellcheck="false"
                data-orig="${escapeAttr(arriveTime || '')}"
                title="${arriveTitle}"
                style="display:inline-block;min-width:44px;padding:2px 4px;border-radius:6px;border:1px solid transparent">
            ${escapeAttr(arriveTime || '')}
          </span>
        </td>
        <td class="today-name-cell">
          ${s ? `<a href="/student/${s.id}" target="_blank" class="stuName" data-sid="${escapeAttr(s.id)}">${name}</a>`
              : `<span class="stuName">${name}</span>`
          }
        </td>
        <td class="today-school-cell">${school || ''}</td>
        <td class="today-curriculum-cell">${curLabel}</td>
        <td class="done-action-cell">
          <div class="today-actions">
          <button class="openStudentPopups" title="상담 기록">🧾</button>
          <button class="studentTestRecordBtn" data-test-result-sid="${escapeAttr(sid)}" data-test-result-name="${escapeAttr(name || sid)}" title="테스트 기록 보기">기록</button>
          <button class="markAbsent" title="결석">🚫</button>
          <button class="markLeave" title="하원">🏠</button>
          <button class="undoDone" title="하원 되돌리기" style="margin-left:6px">↩️</button>
          <button class="clearDone" title="기록 정리" style="margin-left:6px">🧹</button>
          </div>
        </td>
        <td class="today-doc-cell"><button class="btn-doc" data-doc-url="${docUrl}" title="문서 열기">📄</button></td>
      </tr>
    `;
  }).join('');

  wrap.innerHTML = `
    <table class="done-table">
      <colgroup>
        <col style="width:72px"><col style="width:64px"><col style="width:120px"><col style="width:84px">
        <col style="width:112px"><col style="width:268px"><col style="width:56px">
      </colgroup>
      <thead>
        <tr>
          <th>구분</th>
          <th title="등원시간">등원</th>
          <th>이름</th>
          <th>학교</th>
          <th>커리큘럼</th>
          <th>작업</th>
          <th>문서</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;

  _bindDoneWrapInlineEditOnce();
  decorateStudentTestRecordButtons(wrap).catch(console.warn);
}

// --- todayWrap event delegation ---
export function bindTodayTableEvents(loadTodayAndRender) {
  const host = $('todayWrap');
  if (!host) return;

  if (host._todayDelegated) return;
  host._todayDelegated = true;

  host.addEventListener('wheel', handleArriveWheel, { passive: false });

  host.addEventListener('keydown', (ev) => {
    const slot = ev.target.closest?.('.slotLabel');
    const arrive = ev.target.closest?.('.arriveLabel');
    const leave = ev.target.closest?.('.leaveLabel');
    const el = slot || arrive || leave;
    if (!el) return;

    if (ev.key === 'Enter') { ev.preventDefault(); el.blur(); }
    if (ev.key === 'Escape') { el.textContent = el.dataset.orig || ''; el.blur(); }
  });

  host.addEventListener('focusin', (ev) => {
    const el = ev.target.closest?.('.slotLabel,.arriveLabel,.leaveLabel');
    if (!el) return;
    el.style.borderColor = '#cbd5e1';
    el.style.background = 'rgba(148,163,184,.12)';
  });

  // Recompute planned arrive time from the slot label only.
  host.addEventListener('focusout', async (ev) => {
    const el = ev.target.closest?.('.slotLabel');
    if (!el) return;

    el.style.borderColor = 'transparent';
    el.style.background = 'transparent';

    const tr = closestTodayRow(el);
    if (!tr) return;

    const sid = rowSid(tr);
    const dateKey = rowDateKey(tr);
    if (!sid || !dateKey) return;

    const prevOrig = el.dataset.orig || '';
    const prevLabel = prevOrig.trim();
    const oldForcedBase = _forcedArriveTimeBySlotLabel(dateKey, prevLabel) || '';

    const txt = (el.textContent || '').trim();
    const cleaned = txt.replace(/\(보강\)/g, '').trim();
    el.textContent = cleaned;

    const oldBase = plannedTimeBase(dateKey, sid) || '';
    const oldOv = (getArriveOverride(dateKey, sid) || '').trim();

    try {
      await saveWeekendSlotsFromLabel(sid, cleaned, dateKey);
    } catch (e) {
      el.textContent = prevOrig;
      el.dataset.orig = prevOrig;
      try { toast('주말 슬롯 저장 실패'); } catch {}
      alert('주말 슬롯 저장 실패');
      return;
    }

    el.dataset.orig = cleaned;
    document.dispatchEvent(new CustomEvent('attendance:updated'));

    const forcedNewBase = _forcedArriveTimeBySlotLabel(dateKey, cleaned) || '';

    const shouldAuto =
      (!oldOv) ||
      (oldForcedBase && oldOv === oldForcedBase) ||
      (oldOv === oldBase);

    if (shouldAuto && forcedNewBase) {
      setArriveOverride(dateKey, sid, forcedNewBase);

      const arriveEl = tr.querySelector('.arriveLabel');
      if (arriveEl) {
        arriveEl.textContent = forcedNewBase;
        arriveEl.dataset.orig = forcedNewBase;
      }

      try {
        await patchArriveTimeRemote(dateKey, sid, forcedNewBase);
      } catch (e) {
        console.error(e);
        setArriveOverride(dateKey, sid, oldOv);
        if (arriveEl) {
          arriveEl.textContent = oldOv;
          arriveEl.dataset.orig = oldOv;
        }
        alert('도착시간 저장 실패');
      }
    }

    await loadTodayAndRender();
  });

  // Direct arrive-time edits update local state first, then patch remotely.
  host.addEventListener('focusout', async (ev) => {
    const el = ev.target.closest?.('.arriveLabel');
    if (!el) return;

    el.style.borderColor = 'transparent';
    el.style.background = 'transparent';

    const tr = closestTodayRow(el);
    if (!tr) return;

    const sid = rowSid(tr);
    const dateKey = rowDateKey(tr);
    if (!sid || !dateKey) return;
    const prev = (el.dataset.orig || '').trim();
    const txt = (el.textContent || '').trim();

    setArriveOverride(dateKey, sid, txt);

    try {
      await patchArriveTimeRemote(dateKey, sid, txt);
      el.dataset.orig = txt;
    } catch (e) {
      console.error(e);
      setArriveOverride(dateKey, sid, prev);
      el.textContent = prev;
      el.dataset.orig = prev;
      alert('도착시간 저장 실패');
    }

    await loadTodayAndRender();
  });

  host.addEventListener('focusout', async (ev) => {
    const el = ev.target.closest?.('.leaveLabel');
    if (!el) return;

    el.style.borderColor = 'transparent';
    el.style.background = 'transparent';

    const tr = closestTodayRow(el);
    if (!tr) return;

    const sid = rowSid(tr);
    const dateKey = rowDateKey(tr);
    if (!sid || !dateKey) return;
    const txt = (el.textContent || '').trim();

    el.dataset.orig = txt;
    try { await setLeaveTimeRemote(dateKey, sid, txt); }
    catch (e) { console.error(e); alert('하원시간 저장 실패'); }

    await loadTodayAndRender();
  });

  host.addEventListener('change', async (ev) => {
    // Attendance
    const att = ev.target.closest?.('.attendChk');
    if (att) {
      const tr = closestTodayRow(att); if (!tr) return;
      const sid = rowSid(tr);
      const dateKey = rowDateKey(tr);
      if (!sid || !dateKey) return;
      const prevChecked = isAttended(dateKey, sid);
      const checked = att.checked;

      tr.dataset.att = checked ? '1' : '';
      const rowArriveEl = tr.querySelector('.arriveLabel');
      if (rowArriveEl) rowArriveEl.title = checked ? ARRIVE_WHEEL_ATTENDED_HINT : ARRIVE_WHEEL_HINT;
      syncTodayRowVisual(tr);
      const pill = att.closest('.c'); if (pill) pill.dataset.on = checked ? '1' : '0';

      setAttended(dateKey, sid, checked);
      document.dispatchEvent(new CustomEvent('attendance:updated'));

      try {
        await patchFlagRemote('att', dateKey, sid, checked);
      } catch (e) {
        console.error(e);
        att.checked = prevChecked;
        tr.dataset.att = prevChecked ? '1' : '';
        if (rowArriveEl) rowArriveEl.title = prevChecked ? ARRIVE_WHEEL_ATTENDED_HINT : ARRIVE_WHEEL_HINT;
        syncTodayRowVisual(tr);
        if (pill) pill.dataset.on = prevChecked ? '1' : '0';
        setAttended(dateKey, sid, prevChecked);
        document.dispatchEvent(new CustomEvent('attendance:updated'));
        alert('출석 저장 실패');
        await loadTodayAndRender();
        return;
      }

      if (checked && dateKey === getRealToday()) {
        const prevArrive = (getArriveOverride(dateKey, sid) || '').trim();
        const t = nowHHMM();
        setArriveOverride(dateKey, sid, t);
        const arriveEl = tr.querySelector('.arriveLabel');
        if (arriveEl) { arriveEl.textContent = t; arriveEl.dataset.orig = t; }

        try {
          await patchArriveTimeRemote(dateKey, sid, t);
        } catch (e2) {
          console.error(e2);
          setArriveOverride(dateKey, sid, prevArrive);
          if (arriveEl) {
            arriveEl.textContent = prevArrive;
            arriveEl.dataset.orig = prevArrive;
          }
        }
      }

      await loadTodayAndRender();
      return;
    }

    // Contact
    const ct = ev.target.closest?.('.contactChk');
    if (ct) {
      const tr = closestTodayRow(ct); if (!tr) return;
      const sid = rowSid(tr);
      const dateKey = rowDateKey(tr);
      if (!sid || !dateKey) return;
      const prevChecked = isContacted(dateKey, sid);
      const checked = ct.checked;

      tr.dataset.contact = checked ? '1' : '';
      const pill = ct.closest('.c'); if (pill) pill.dataset.on = checked ? '1' : '0';

      setContacted(dateKey, sid, checked);

      try {
        await patchFlagRemote('contact', dateKey, sid, checked);
      } catch (e) {
        console.error(e);
        ct.checked = prevChecked;
        tr.dataset.contact = prevChecked ? '1' : '';
        if (pill) pill.dataset.on = prevChecked ? '1' : '0';
        setContacted(dateKey, sid, prevChecked);
        alert('연락 저장 실패');
        await loadTodayAndRender();
        return;
      }

      return;
    }

    // Self-study excludes the row from homework-check operation metrics.
    const ss = ev.target.closest?.('.selfStudyChk');
    if (ss) {
      const tr = closestTodayRow(ss); if (!tr) return;
      const sid = rowSid(tr);
      const dateKey = rowDateKey(tr);
      if (!sid || !dateKey) return;
      const prevChecked = isSelfStudy(dateKey, sid);
      const checked = ss.checked;
      const pill = ss.closest('.self-study-toggle');
      const requestInput = tr.querySelector('.hwRequestChk');
      const requestPill = tr.querySelector('.homework-request-toggle');

      tr.dataset.selfStudy = checked ? '1' : '';
      if (pill) pill.dataset.on = checked ? '1' : '0';
      if (checked) {
        tr.dataset.hwRequest = '';
        delete tr.dataset.hwRequestAt;
        if (requestInput) {
          requestInput.checked = false;
          requestInput.disabled = true;
        }
        if (requestPill) requestPill.dataset.on = '0';
      } else if (requestInput && tr.dataset.hw !== '1') {
        requestInput.disabled = false;
      }
      syncTodayRowVisual(tr);
      document.dispatchEvent(new CustomEvent('attendance:updated'));

      try {
        await setSelfStudyRemote(dateKey, sid, checked);
      } catch (e) {
        console.error(e);
        ss.checked = prevChecked;
        tr.dataset.selfStudy = prevChecked ? '1' : '';
        if (pill) pill.dataset.on = prevChecked ? '1' : '0';
        if (requestInput) requestInput.disabled = prevChecked || tr.dataset.hw === '1';
        syncTodayRowVisual(tr);
        document.dispatchEvent(new CustomEvent('attendance:updated'));
        alert('자습 저장 실패');
        await loadTodayAndRender();
        return;
      }

      await loadTodayAndRender();
      return;
    }

    // Homework check request.
    const hr = ev.target.closest?.('.hwRequestChk');
    if (hr) {
      const tr = closestTodayRow(hr); if (!tr) return;
      const sid = rowSid(tr);
      const dateKey = rowDateKey(tr);
      if (!sid || !dateKey) return;
      if (isSelfStudy(dateKey, sid)) {
        hr.checked = false;
        return;
      }
      const prevChecked = isHwCheckRequested(dateKey, sid);
      const checked = hr.checked;
      const pill = hr.closest('.homework-request-toggle');

      tr.dataset.hwRequest = checked ? '1' : '';
      if (checked) tr.dataset.hwRequestAt = nowISO();
      else delete tr.dataset.hwRequestAt;
      if (pill) pill.dataset.on = checked ? '1' : '0';
      syncTodayRowVisual(tr);

      try {
        await setHomeworkCheckRequestedRemote(dateKey, sid, checked);
      } catch (e) {
        console.error(e);
        hr.checked = prevChecked;
        tr.dataset.hwRequest = prevChecked ? '1' : '';
        if (!prevChecked) delete tr.dataset.hwRequestAt;
        if (pill) pill.dataset.on = prevChecked ? '1' : '0';
        syncTodayRowVisual(tr);
        alert('숙검요청 저장 실패');
        await loadTodayAndRender();
        return;
      }

      await loadTodayAndRender();
      return;
    }

    // Homework completion is the single visible homework flag.
    const hc = ev.target.closest?.('.hwCheckChk');
    if (hc) {
      const tr = closestTodayRow(hc); if (!tr) return;
      const sid = rowSid(tr);
      const dateKey = rowDateKey(tr);
      if (!sid || !dateKey) return;
      const checked = hc.checked;
      const prevChecked = isHwChecked(dateKey, sid);
      const prevHw = tr.dataset.hw;
      const prevHwRequest = tr.dataset.hwRequest;
      const prevHwRequestAt = tr.dataset.hwRequestAt;
      const requestInput = tr.querySelector('.hwRequestChk');
      const requestPill = tr.querySelector('.homework-request-toggle');
      const requestChecked = requestInput?.checked;
      const requestDisabled = requestInput?.disabled;
      const requestPillOn = requestPill?.dataset?.on;
      const pill = hc.closest('.c');
      const prevPillOn = pill?.dataset?.on;
      const restoreDatasetValue = (key, value) => {
        if (value === undefined) delete tr.dataset[key];
        else tr.dataset[key] = value;
      };

      try { await setHomeworkCheckedRemote(dateKey, sid, checked); }
      catch (e) {
        console.error(e);
        hc.checked = prevChecked;
        restoreDatasetValue('hw', prevHw);
        restoreDatasetValue('hwRequest', prevHwRequest);
        restoreDatasetValue('hwRequestAt', prevHwRequestAt);
        if (requestInput) {
          requestInput.checked = requestChecked;
          requestInput.disabled = requestDisabled;
        }
        if (requestPill) {
          if (requestPillOn === undefined) delete requestPill.dataset.on;
          else requestPill.dataset.on = requestPillOn;
        }
        if (pill) {
          if (prevPillOn === undefined) delete pill.dataset.on;
          else pill.dataset.on = prevPillOn;
        }
        syncTodayRowVisual(tr);
        alert('숙제 체크 저장 실패');
        await loadTodayAndRender();
        return;
      }

      tr.dataset.hw = checked ? '1' : '';
      if (checked) {
        tr.dataset.hwRequest = '';
        delete tr.dataset.hwRequestAt;
        if (requestInput) {
          requestInput.checked = false;
          requestInput.disabled = true;
        }
        if (requestPill) requestPill.dataset.on = '0';
      }
      syncTodayRowVisual(tr);
      if (pill) pill.dataset.on = checked ? '1' : '0';
      await loadTodayAndRender();
      return;
    }
  });

  if (!document._todayDocClickBound) {
    document._todayDocClickBound = true;

    document.addEventListener('click', async (e) => {
      const homeworkLeaveBtn = e.target.closest('#homeworkLeaveBtn');
      if (homeworkLeaveBtn) {
        const currentSlot = currentOpsSlot();
        const rows = Array.from(document.querySelectorAll('#todayWrap tr[data-sid]'));
        const seen = new Set();
        const targets = [];

        for (const tr of rows) {
          if (!shouldIncludeHomeworkLeaveRow(tr, currentSlot)) continue;
          const sid = rowSid(tr);
          const dateKey = rowDateKey(tr);
          if (!sid || !dateKey) continue;
          const key = `${dateKey}\u0000${sid}`;
          if (seen.has(key)) continue;
          seen.add(key);
          targets.push({ dateKey, sid });
        }

        if (!targets.length) {
          toast('숙제 검사 완료 학생이 없습니다.');
          return;
        }

        const prevText = homeworkLeaveBtn.textContent;
        const t = nowHHMM();
        const leaveAt = nowISO();
        let ok = 0;
        let failed = 0;

        homeworkLeaveBtn.disabled = true;
        homeworkLeaveBtn.textContent = '처리중';

        try {
          for (const target of targets) {
            try {
              await patchLog(target.dateKey, target.sid, {
                done: true,
                leaveTime: t,
                leaveAt,
              }, ['archived']);
              ok += 1;
            } catch (err) {
              failed += 1;
              console.error('[today] homework leave failed:', target, err);
            }
          }

          if (ok) document.dispatchEvent(new CustomEvent('attendance:updated'));
          await loadTodayAndRender({ force: true });

          if (failed) {
            toast(`숙검하원 ${ok}/${targets.length}명 처리됨`);
            if (!ok) alert('숙검하원 저장 실패');
          } else {
            toast(`숙검하원 ${ok}명 하원 처리됨 (${t})`);
          }
        } finally {
          homeworkLeaveBtn.disabled = false;
          homeworkLeaveBtn.textContent = prevText || '숙검하원';
        }
        return;
      }

      const docBtn = e.target.closest('.btn-doc');
      if (docBtn) {
        const url = docBtn.dataset.docUrl;
        if (url) window.open(url, '_blank');
        return;
      }

      const absentBtn = e.target.closest('.markAbsent');
      if (absentBtn) {
        const tr = closestTodayRow(absentBtn); if (!tr) return;
        const sid = rowSid(tr);
        const dateKey = rowDateKey(tr);
        if (!sid || !dateKey) return;
        const absenceSlots = rowSlotsForAbsence(dateKey, sid, tr);

        const prevAttended = isAttended(dateKey, sid);
        const prevContacted = isContacted(dateKey, sid);
        const prevByStudent = state.absences?.[sid];
        const prevDateList = Array.isArray(state.absentByDate?.[dateKey])
          ? state.absentByDate[dateKey].map(String)
          : [];
        const prevSlotMap = normalizeAbsentSlotMap(state.absentSlotsByDate || {});

        // Clear attendance/contact before marking the row absent.
        setAttended(dateKey, sid, false);
        setContacted(dateKey, sid, false);
        document.dispatchEvent(new CustomEvent('attendance:updated'));

        try {
          await Promise.all([
            patchFlagRemote('att', dateKey, sid, false),
            patchFlagRemote('contact', dateKey, sid, false),
          ]);
        } catch (syncErr) {
          console.error(syncErr);
          setAttended(dateKey, sid, prevAttended);
          setContacted(dateKey, sid, prevContacted);
          document.dispatchEvent(new CustomEvent('attendance:updated'));
          alert('결석 전에 출석/연락 정리 실패');
          await loadTodayAndRender({ force: true });
          return;
        }

        // Update local absence maps first so the UI stays consistent.
        state.absences = state.absences && typeof state.absences === 'object' ? state.absences : {};
        state.absentByDate = looksLikeAbsentByDateMap(state.absentByDate) ? state.absentByDate : {};
        state.absentSlotsByDate = normalizeAbsentSlotMap(state.absentSlotsByDate || {});

        state.absences[sid] = dateKey;
        const cur = Array.isArray(state.absentByDate[dateKey]) ? state.absentByDate[dateKey].map(String) : [];
        state.absentByDate[dateKey] = Array.from(new Set([...cur, sid]));
        if (absenceSlots.length) {
          state.absentSlotsByDate[dateKey] = {
            ...(state.absentSlotsByDate[dateKey] || {}),
            [sid]: absenceSlots,
          };
        } else if (state.absentSlotsByDate[dateKey]) {
          delete state.absentSlotsByDate[dateKey][sid];
          if (!Object.keys(state.absentSlotsByDate[dateKey]).length) delete state.absentSlotsByDate[dateKey];
        }

        ensureWindowStateAlias();
        void loadTodayAndRender().catch(err => {
          console.error('[today] optimistic absence render failed:', err);
        });

        try {
          const res = await fetch('/api/absent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              by_date: state.absentByDate,
              by_student: state.absences,
              by_slot: state.absentSlotsByDate,
            }),
          });

          let data = null;
          try { data = await res.json(); } catch { }

          if (!res.ok) throw new Error(`/api/absent ${res.status}`);

          // Prefer the server copy if it returns fresher absence maps.
          const byDate = data?.by_date || data?.absentByDate || (data?.ok ? data?.by_date : null);
          const byStu = data?.by_student || data?.absences || (data?.ok ? data?.by_student : null);
          const bySlot = data?.by_slot || data?.absentSlotsByDate || (data?.ok ? data?.by_slot : null);

          setAbsenceMapsSafely({ byDate, byStudent: byStu, bySlot });
          try {
            await markMakeupDemandOpen(dateKey, sid, absenceSlots);
          } catch (openErr) {
            console.error(openErr);
            alert('결석은 저장됐지만 보강 잡기 명단 갱신에 실패했습니다.');
          }

          toast('결석 처리됨');
          await loadTodayAndRender({ force: true });

          if (typeof window.recalcCalendarCounts === 'function') window.recalcCalendarCounts();
        } catch (e2) {
          console.error(e2);
          // rollback local absence map
          state.absences = state.absences && typeof state.absences === 'object' ? state.absences : {};
          state.absentByDate = looksLikeAbsentByDateMap(state.absentByDate) ? state.absentByDate : {};
          if (prevByStudent) state.absences[sid] = prevByStudent;
          else delete state.absences[sid];
          state.absentByDate[dateKey] = prevDateList;
          state.absentSlotsByDate = prevSlotMap;
          ensureWindowStateAlias();

          // rollback attend/contact local + server(best effort)
          setAttended(dateKey, sid, prevAttended);
          setContacted(dateKey, sid, prevContacted);
          document.dispatchEvent(new CustomEvent('attendance:updated'));
          try {
            await patchFlagRemote('att', dateKey, sid, prevAttended);
            await patchFlagRemote('contact', dateKey, sid, prevContacted);
          } catch (rbErr) {
            console.error(rbErr);
          }

          alert('결석 처리 실패');
          await loadTodayAndRender();
        }
        return;
      }

      const leaveBtn = e.target.closest('.markLeave');
      if (leaveBtn) {
        const tr = closestTodayRow(leaveBtn); if (!tr) return;
        const sid = rowSid(tr);
        const dateKey = rowDateKey(tr);
        if (!sid || !dateKey) return;
        const t = nowHHMM();

        try {
          await patchLog(dateKey, sid, {
            done: true,
            leaveTime: t,
            leaveAt: nowISO(),
          }, ['archived']);

          document.dispatchEvent(new CustomEvent('attendance:updated'));

          const leaveEl = tr.querySelector('.leaveLabel');
          if (leaveEl) { leaveEl.textContent = t; leaveEl.dataset.orig = t; }

          toast(`하원 처리됨 (${getLeaveTime(dateKey, sid) || t})`);
          // doneWrap이 "archived != true" 전체를 렌더하므로,
          // 수동으로 행을 옮기면 중복이 생길 수 있다.
          // 저장 후 전체 재렌더로 단일 소스를 유지한다.
          await loadTodayAndRender({ force: true });
        } catch (err) {
          console.error(err);
          alert('하원 저장 실패');
        }
        return;
      }

      const undoBtn = e.target.closest('.undoDone');
      const clearBtn = e.target.closest('.clearDone');
      if (undoBtn || clearBtn) {
        const tr = closestTodayRow(e.target);
        if (!tr) return;
        const sid = rowSid(tr);
        const date = rowDateKey(tr);
        if (!sid || !date) return;

        try {
          if (undoBtn) {
            await patchLog(date, sid, { done: false }, ['archived']);
            toast('하원 취소됨');
          } else {
            const testPatch = await completeAssignedTestsForRecordCleanup(date, sid);
            await patchLog(date, sid, { ...testPatch, archived: true });
            toast('기록 정리됨');
          }
          await loadTodayAndRender();
        } catch (err) {
          console.error(err);
          alert('로그 저장 실패');
        }
      }
    });
  }
}

