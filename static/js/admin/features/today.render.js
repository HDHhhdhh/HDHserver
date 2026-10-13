// /js/admin/features/today.render.js
// today.js rendering and events
//
// Notes:
// - Keep imported `state` and `window.state` aligned.
// - Use patch endpoints for attendance, contact, and arrive-time writes.
// - Avoid custom setters for absence maps; update plain objects directly.

import { $, toast } from '../core/utils.js';
import { getAdminDate, getRealToday } from '../core/adminDate.js';
import { state } from '../core/state.js';
import { decorateStudentTestRecordButtons } from '../../shared/testRecordDetails.js';
import { ensureOk, sendJson } from '../../shared/api.js';
import { renderTodayActionButtons, renderTodayDocumentButton } from './todayActionMarkup.js';

const WHITE_REVIEW_PENDING_FIELD = 'whiteReviewPending';
const whiteReviewSaves = new Set();

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
  patchLogsBatch,
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

function whiteReviewPendingForSid(sid) {
  const student = (state.students || []).find(item => String(item?.id || '') === String(sid || ''));
  return student?.[WHITE_REVIEW_PENDING_FIELD] === true;
}

function setWhiteReviewPendingLocal(sid, pending) {
  const student = (state.students || []).find(item => String(item?.id || '') === String(sid || ''));
  if (!student) return false;
  student[WHITE_REVIEW_PENDING_FIELD] = pending === true;
  window.students = state.students;
  return true;
}

function renderWhiteReviewPendingCell(sid, name, pending = whiteReviewPendingForSid(sid)) {
  const knownStudent = (state.students || []).some(student => String(student?.id) === String(sid));
  return `<td class="today-white-review-cell">
    <div class="chk4" aria-label="백지리뷰 검사 대기">
      <label class="c" data-kind="check" data-on="${pending ? '1' : '0'}" title="백지리뷰 검사 대기">
        <input type="checkbox" class="whiteReviewPendingChk" data-id="${escapeAttr(sid)}"
               aria-label="${escapeAttr(`${name || sid} 백지리뷰 검사 대기`)}" ${pending ? 'checked' : ''}
               ${!knownStudent || whiteReviewSaves.has(String(sid)) ? 'disabled' : ''}>
      </label>
    </div>
  </td>`;
}

function syncWhiteReviewCheckboxes(sid, pending, trigger) {
  const controls = new Set([trigger, ...document.querySelectorAll('.whiteReviewPendingChk')]);
  for (const input of controls) {
    const tr = closestTodayRow(input);
    if (rowSid(tr) !== sid) continue;
    input.checked = pending;
    input.disabled = whiteReviewSaves.has(sid);
    tr.dataset.whiteReviewPending = pending ? '1' : '';
    const pill = input.closest('.c');
    if (pill) pill.dataset.on = pending ? '1' : '0';
  }
}

async function saveWhiteReviewCheckbox(input, refresh) {
  const sid = rowSid(closestTodayRow(input));
  if (!sid) return;
  const previous = whiteReviewPendingForSid(sid);
  if (whiteReviewSaves.has(sid)) {
    syncWhiteReviewCheckboxes(sid, previous, input);
    return;
  }
  const checked = input.checked === true;
  whiteReviewSaves.add(sid);
  setWhiteReviewPendingLocal(sid, checked);
  syncWhiteReviewCheckboxes(sid, checked, input);
  try {
    await patchWhiteReviewPendingRemote(sid, checked);
    setWhiteReviewPendingLocal(sid, checked);
  } catch (error) {
    console.error(error);
    setWhiteReviewPendingLocal(sid, previous);
    syncWhiteReviewCheckboxes(sid, previous, input);
    alert('백지리뷰 검사 대기 저장 실패');
    if (refresh) await refresh({ force: true });
    else document.dispatchEvent(new CustomEvent('admin:refresh'));
  } finally {
    whiteReviewSaves.delete(sid);
    syncWhiteReviewCheckboxes(sid, whiteReviewPendingForSid(sid), input);
  }
}

function normalizeLeaveIdentityPart(value) {
  const text = String(value ?? '');
  try { return text.normalize('NFKC').trim(); }
  catch { return text.trim(); }
}

function studentSchoolForLeaveIdentity(student) {
  return normalizeLeaveIdentityPart(
    student?.school ?? student?.schoolName ?? student?.highSchool ?? student?.middleSchool ??
    student?.high ?? student?.middle ?? student?.schoolHigh ?? student?.schoolMiddle ?? '',
  );
}

function studentLeaveIdentityKey(student) {
  const sid = normalizeLeaveIdentityPart(student?.id);
  const name = normalizeLeaveIdentityPart(student?.name);
  const school = studentSchoolForLeaveIdentity(student);
  const grade = normalizeLeaveIdentityPart(student?.grade);
  if (!name || !school) return `sid:${encodeURIComponent(sid)}`;
  return `person:${[name, school, grade].map(encodeURIComponent).join('|')}`;
}

function leaveIdentityForRow(row) {
  const stored = String(row?.dataset?.studentIdentity || '').trim();
  if (stored) return stored;

  const sid = rowSid(row);
  const student = (state.students || []).find(item => String(item?.id || '') === sid);
  return studentLeaveIdentityKey(student || { id: sid });
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
  if (dateRows[studentId]?.state === 'self-study') return;
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
  await _postJSON('/api/arrive-time/patch', { date, sid: String(sid), value: String(hhmm || '') });
}

async function patchWhiteReviewPendingRemote(sid, pending) {
  const res = await sendJson('/api/update', {
    id: String(sid),
    field: WHITE_REVIEW_PENDING_FIELD,
    value: pending === true,
  });
  await ensureOk(res, '백지리뷰 검사 대기 저장');
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
    .chk4 .c[data-kind="att"] input{accent-color:#10b981}
    .chk4 .c[data-kind="contact"] input{accent-color:#3b82f6}
    .chk4 .c[data-kind="check"] input{accent-color:#f59e0b}
    .chk4 .c[data-on="1"]{background:rgba(16,185,129,.10);border-color:rgba(16,185,129,.45)}
    .chk4 .c[data-kind="att"][data-on="1"]{background:rgba(16,185,129,.10);border-color:rgba(16,185,129,.45)}
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
    #doneWrap table.done-table{min-width:880px;table-layout:fixed;font-size:15px}
    .today-table th,.today-table td,.done-table th,.done-table td{overflow:hidden;text-overflow:ellipsis}
    .done-table th,.done-table td{text-align:center;vertical-align:middle}
    body.admin #doneWrap .done-table .today-white-review-cell,
    body.admin #doneWrap .done-table .done-white-review-head{padding-left:1px;padding-right:1px;white-space:nowrap}
    .today-table th{font-size:14px}
    .today-table td{font-size:15px}
    .today-table .stuName,.done-table .stuName{font-size:15.5px}
    .today-check-cell,.today-self-study-cell,.today-homework-request-cell,.today-doc-cell,.today-action-cell,.makeup-count-cell,.today-progress-cell,.today-white-review-cell{text-align:center}
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

function _forcedArriveTimeBySlotLabel(dateKey, labelText) {
  const nums = parseSlotsFromText(labelText, dateKey);
  if (!nums.length) return '';
  const minSlot = Math.min(...nums);
  if (minSlot === 1) return '13:00';
  if (minSlot === 2 || minSlot === 3) return '18:00';
  return '';
}

function _slotGroupsFromLabelAndArrive(labelText, arriveTime, dateKey = '') {
  let nums = parseSlotsFromText(labelText, dateKey)
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

function homeworkLeaveRowsByStudent(rows) {
  const grouped = new Map();
  for (const row of Array.from(rows || [])) {
    const sid = rowSid(row);
    const dateKey = String(row?.dataset?.date || '').trim();
    if (!sid || !dateKey) continue;
    const key = `${dateKey}\u0000${leaveIdentityForRow(row)}`;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(row);
  }
  return Array.from(grouped.values());
}

function homeworkLeaveSlotNumbersForRows(rows) {
  return Array.from(new Set(
    Array.from(rows || []).flatMap(row => homeworkLeaveSlotNumbers(row)),
  )).sort((a, b) => a - b);
}

function shouldIncludeHomeworkLeaveRows(rows, currentSlot = currentOpsSlot()) {
  const group = Array.from(rows || []);
  const canLeave = group.some(row => row?.dataset?.hw === '1' || row?.dataset?.selfStudy === '1');
  if (!canLeave) return false;

  const slots = homeworkLeaveSlotNumbersForRows(group);
  const isConsecutive = slots.length >= 2;
  return !(currentSlot === 1 && isConsecutive);
}

function shouldIncludeHomeworkLeaveRow(row, currentSlot = currentOpsSlot()) {
  return shouldIncludeHomeworkLeaveRows([row], currentSlot);
}

function homeworkLeaveTargetRows(rows, currentSlot = currentOpsSlot()) {
  return homeworkLeaveRowsByStudent(rows)
    .filter(group => shouldIncludeHomeworkLeaveRows(group, currentSlot))
    .flat();
}

function linkedLeaveRows(sourceRow, rows, currentSlot = currentOpsSlot()) {
  const sourceKey = `${String(sourceRow?.dataset?.date || '').trim()}\u0000${leaveIdentityForRow(sourceRow)}`;
  const linked = Array.from(rows || []).filter(row => (
    `${String(row?.dataset?.date || '').trim()}\u0000${leaveIdentityForRow(row)}` === sourceKey
  ));
  if (!linked.includes(sourceRow)) linked.unshift(sourceRow);

  const isConsecutive = homeworkLeaveSlotNumbersForRows(linked).length >= 2;
  return isConsecutive && currentSlot !== 1 ? linked : [sourceRow];
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

function renderReadonlySlotLabel(labelText) {
  const label = String(labelText || '').trim();
  return `<span class="slotLabelReadonly" title="과거 날짜 기록은 해당 날짜를 선택한 뒤 편집할 수 있습니다.">
    ${escapeAttr(label)}
  </span>`;
}

function progressEntryForSid(day, sid) {
  if (!day || typeof day !== 'object') return {};
  const sidKey = String(sid || '');
  const direct = day[sidKey];
  if (direct && typeof direct === 'object') return direct;
  return {};
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
  const difficulty = String(item?.difficulty || '').trim();
  if (categoryKey === 'ILSAN_PAST' && (difficulty === '중상' || difficulty === '상')) return false;
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
  const rawDifficulty = String(item?.difficulty || '').trim();
  const difficulty = item?.categoryKey === 'ILSAN_PAST' && rawDifficulty === '중'
    ? '중상'
    : rawDifficulty;
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

function useLatestLogEntryForCleanup(dateKey, sid, entry) {
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
    throw new Error('최신 하원 기록을 확인할 수 없습니다.');
  }
  if (!truthy(entry.done)) throw new Error('이미 하원이 취소된 기록입니다.');
  if (truthy(entry.archived)) throw new Error('이미 정리된 기록입니다.');

  state.logs = state.logs || {};
  state.logs[dateKey] = state.logs[dateKey] || {};
  state.logs[dateKey][String(sid)] = entry;
  window.logs = state.logs;
  ensureWindowStateAlias();
  return entry;
}

async function fetchLogEntryForCleanup(dateKey, sid) {
  const res = await fetch(`/api/logs/entry?date=${encodeURIComponent(dateKey)}&sid=${encodeURIComponent(sid)}`, {
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(`/api/logs/entry ${res.status}`);

  const data = await res.json().catch(() => null);
  return useLatestLogEntryForCleanup(dateKey, sid, data?.entry);
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

function useLatestProgressEntryForCleanup(dateKey, sid, entry) {
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
    throw new Error('최신 진행 기록을 확인할 수 없습니다.');
  }

  const sidKey = String(sid);
  state.progress = state.progress || {};
  state.progress[dateKey] = state.progress[dateKey] || {};
  state.progress[dateKey][sidKey] = entry;
  window.progressData = state.progress;
  ensureWindowStateAlias();
  return entry;
}

async function fetchProgressEntryForCleanup(dateKey, sid) {
  const res = await fetch(`/api/progress?date=${encodeURIComponent(dateKey)}&sid=${encodeURIComponent(sid)}`, {
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(`/api/progress ${res.status}`);
  state.youtubeRecordCleanupSupported = res.headers?.get?.('X-YouTube-Record-Cleanup') === '1';

  const data = await res.json().catch(() => null);
  const day = data?.[dateKey];
  const sidKey = String(sid);
  if (!day || typeof day !== 'object' || Array.isArray(day)
      || !Object.prototype.hasOwnProperty.call(day, sidKey)
      || !day[sidKey] || typeof day[sidKey] !== 'object' || Array.isArray(day[sidKey])) {
    throw new Error('최신 진행 기록을 확인할 수 없습니다.');
  }
  return useLatestProgressEntryForCleanup(dateKey, sid, progressEntryForSid(day, sid));
}

export async function preloadRecordCleanupEntries(targets) {
  const groups = new Map();
  (Array.isArray(targets) ? targets : []).forEach(([date, sid]) => {
    const dateKey = String(date || '').trim();
    const sidKey = String(sid || '').trim();
    if (!dateKey || !sidKey) return;
    if (!groups.has(dateKey)) groups.set(dateKey, []);
    if (!groups.get(dateKey).includes(sidKey)) groups.get(dateKey).push(sidKey);
  });

  const latest = new Map();
  await Promise.all(Array.from(groups.entries()).map(async ([dateKey, sids]) => {
    const progressQuery = new URLSearchParams({ date: dateKey, sids: sids.join(',') });
    const [logsRes, progressRes] = await Promise.all([
      fetch(`/api/logs?date=${encodeURIComponent(dateKey)}`, { cache: 'no-store' }),
      fetch(`/api/progress?${progressQuery.toString()}`, { cache: 'no-store' }),
    ]);
    if (!logsRes.ok) throw new Error(`/api/logs ${logsRes.status}`);
    if (!progressRes.ok) throw new Error(`/api/progress ${progressRes.status}`);
    state.youtubeRecordCleanupSupported = progressRes.headers?.get?.('X-YouTube-Record-Cleanup') === '1';

    const [logsData, progressData] = await Promise.all([
      logsRes.json().catch(() => null),
      progressRes.json().catch(() => null),
    ]);
    if (!logsData || typeof logsData !== 'object' || Array.isArray(logsData)) {
      throw new Error('최신 하원 기록 묶음을 확인할 수 없습니다.');
    }
    if (!progressData || typeof progressData !== 'object' || Array.isArray(progressData)) {
      throw new Error('최신 진행 기록 묶음을 확인할 수 없습니다.');
    }

    const logDay = logsData[dateKey] && typeof logsData[dateKey] === 'object' ? logsData[dateKey] : {};
    const progressDay = progressData[dateKey] && typeof progressData[dateKey] === 'object'
      ? progressData[dateKey]
      : {};
    sids.forEach(sid => {
      const key = `${dateKey}\u0000${sid}`;
      latest.set(key, {
        authoritative: true,
        logEntry: Object.prototype.hasOwnProperty.call(logDay, sid) ? logDay[sid] : null,
        progressEntry: Object.prototype.hasOwnProperty.call(progressDay, sid) ? progressDay[sid] : {},
      });
    });
  }));
  return latest;
}

export async function completeAssignedTestsForRecordCleanup(dateKey, sid, preloaded = null) {
  const logEntry = preloaded?.authoritative
    ? useLatestLogEntryForCleanup(dateKey, sid, preloaded.logEntry)
    : await fetchLogEntryForCleanup(dateKey, sid);
  const logPatch = recordCleanupLogTestPatch(logEntry);
  if (isSidAbsentOn(dateKey, sid)) return logPatch;

  const progressEntry = preloaded?.authoritative
    ? useLatestProgressEntryForCleanup(dateKey, sid, preloaded.progressEntry)
    : await fetchProgressEntryForCleanup(dateKey, sid);
  const progressTests = assignedTestCompletionPatch(progressEntry);
  const currentProgressTests = progressEntry?.tests && typeof progressEntry.tests === 'object'
    ? progressEntry.tests
    : {};
  completedTestLabelsFromLogPatch(logPatch).forEach(label => {
    if (!Object.prototype.hasOwnProperty.call(currentProgressTests, label)) {
      progressTests[label] = 'done';
    }
  });

  const completeYouTube = state.youtubeRecordCleanupSupported === true;
  if (!completeYouTube && (state.videos || []).some(video => video?.provider === 'youtube')) {
    throw new Error('YouTube 기록정리 기능의 서버 반영 후 다시 시도하세요.');
  }
  if (Object.keys(progressTests).length || completeYouTube) {
    const res = await fetch('/api/progress/patch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        date: dateKey,
        sid,
        progress: { tests: progressTests },
        ...(completeYouTube ? { completeAssignedYouTube: true } : {}),
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


function _bindDoneWrapInlineEditOnce() {
  const wrap = $('doneWrap');
  if (!wrap) return;

  if (wrap._doneDelegated) return;
  wrap._doneDelegated = true;

  wrap.addEventListener('change', async (ev) => {
    const input = ev.target.closest?.('.whiteReviewPendingChk');
    if (input) await saveWhiteReviewCheckbox(input);
  });

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

    let slotSaveResult;
    try {
      slotSaveResult = await saveWeekendSlotsFromLabel(sid, cleaned, date);
    } catch (e) {
      el.textContent = prevOrig;
      el.dataset.orig = prevOrig;
      try { toast('주말 슬롯 저장 실패'); } catch {}
      alert('주말 슬롯 저장 실패');
      return;
    }
    if (slotSaveResult?.orderReset === false) {
      toast('슬롯은 저장됐지만 오늘표 순서 초기화에 실패했습니다.');
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
    if (txt === prev) return;
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


function ensureSelfStudyHeader(host) {
  const headRow = host?.querySelector?.('thead tr');
  if (!headRow || headRow.querySelector('.today-self-study-head')) return;
  const th = document.createElement('th');
  th.className = 'today-self-study-head';
  th.textContent = '자습';
  headRow.insertBefore(th, headRow.children[5] || null);
}

// --- render ---
function replaceStudentTable(host, markup, tableClass) {
  const table = host.querySelector(`table.${tableClass}`);
  const template = document.createElement('template');
  if (!table || !template.content) { host.innerHTML = markup; return; }
  template.innerHTML = markup;
  const nextTable = template.content.querySelector(`table.${tableClass}`);
  const body = table.tBodies?.[0];
  const nextBody = nextTable?.tBodies?.[0];
  if (!body || !nextBody) { host.innerHTML = markup; return; }

  const syncAttributes = (current, next) => {
    for (const attribute of Array.from(current.attributes)) {
      if (!next.hasAttribute(attribute.name)) current.removeAttribute(attribute.name);
    }
    for (const attribute of Array.from(next.attributes)) {
      if (current.getAttribute(attribute.name) !== attribute.value) {
        current.setAttribute(attribute.name, attribute.value);
      }
    }
  };
  syncAttributes(table, nextTable);
  for (const selector of ['colgroup', 'thead']) {
    const current = table.querySelector(selector);
    const next = nextTable.querySelector(selector);
    if (current && next && !current.isEqualNode(next)) current.replaceWith(next);
  }
  const rowsByKey = new Map();
  const rowKey = row => JSON.stringify([row.dataset.date, row.dataset.sid]);
  for (const row of Array.from(body.rows)) {
    const key = rowKey(row);
    if (!rowsByKey.has(key)) rowsByKey.set(key, []);
    rowsByKey.get(key).push(row);
  }
  const retained = new Set();
  let cursor = body.firstElementChild;
  for (const nextRow of Array.from(nextBody.rows)) {
    const current = rowsByKey.get(rowKey(nextRow))?.shift();
    let row = nextRow;
    if (current && current.cells.length === nextRow.cells.length) {
      row = current;
      syncAttributes(row, nextRow);
      const nextCells = Array.from(nextRow.cells);
      for (let index = 0; index < row.cells.length; index += 1) {
        const cell = row.cells[index], nextCell = nextCells[index];
        if (!cell.isEqualNode(nextCell)) {
          cell.replaceWith(nextCell);
        } else {
          // Checkbox properties can differ without changing their checked HTML attribute.
          const inputs = cell.querySelectorAll('input');
          const nextInputs = nextCell.querySelectorAll('input');
          inputs.forEach((input, inputIndex) => {
            if (input.checked !== nextInputs[inputIndex].checked) input.checked = nextInputs[inputIndex].checked;
          });
        }
      }
    }
    retained.add(row);
    if (row !== cursor) body.insertBefore(row, cursor);
    cursor = row.nextElementSibling;
  }
  for (const row of Array.from(body.rows)) {
    if (!retained.has(row)) row.remove();
  }
}

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
    const whiteReviewPending = s?.[WHITE_REVIEW_PENDING_FIELD] === true;

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
      <tr class="${rowClass}" data-sid="${s.id}" data-date="${dateKey}" data-student-identity="${escapeAttr(studentLeaveIdentityKey(s))}"
          ${s.curriculum ? `data-curriculum="${escapeAttr(s.curriculum)}"` : ''} ${s.subCurriculum ? `data-subcurriculum="${escapeAttr(s.subCurriculum)}"` : ''}
          ${attended ? 'data-att="1"' : ''} ${contacted ? 'data-contact="1"' : ''}
          ${selfStudy ? 'data-self-study="1"' : ''}
          ${hwChecked ? 'data-hw="1"' : ''} ${hwRequested ? 'data-hw-request="1"' : ''}
          ${whiteReviewPending ? 'data-white-review-pending="1"' : ''}
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

        ${renderWhiteReviewPendingCell(s.id, s.name, whiteReviewPending)}

        <td class="today-action-cell">
          ${renderTodayActionButtons({ sid: s.id, name: s.name })}
        </td>
        <td class="makeup-count-cell">
          <span class="makeup-count-badge ${makeupCount > 0 ? 'needs' : ''}">${makeupCount}</span>
        </td>
        <td class="today-doc-cell">${renderTodayDocumentButton({ docUrl: s.docUrl, name: s.name, sid: s.id })}</td>
      </tr>
    `;
  }).join('');

  detachSortableIfAny();
  replaceStudentTable(host, list.length ? `
      <table class="today-table">
      <colgroup>
        <col style="width:32px"><col style="width:72px"><col style="width:120px"><col style="width:84px">
        <col style="width:168px"><col style="width:44px"><col style="width:84px"><col style="width:84px"><col style="width:112px">
        <col style="width:36px"><col style="width:36px"><col style="width:232px"><col style="width:64px"><col style="width:56px">
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
          <th>백지</th>
          <th>작업</th>
          <th>보강</th>
          <th>문서</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  ` : '오늘 학생 없음', 'today-table');

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
    const sidKey = String(sid || '').trim();
    const dateKey = String(date || '').trim();
    const s =
      (window?.state?.students || []).find?.(x => String(x.id) === sidKey)
      || (document?.defaultView?.state?.students || []).find?.(x => String(x.id) === sidKey)
      || null;

    const name = s?.name || sidKey;
    const curLabel = s ? (s.curriculum + (s.subCurriculum ? ' ' + s.subCurriculum : '')) : '';
    const school = s ? (s.school ?? s.schoolName ?? s.highSchool ?? s.middleSchool ?? s.high ?? s.middle ?? '') : '';
    const docUrl = s?.docUrl || '';

    const isSelectedDate = dateKey === String(getAdminDate() || '');
    const arriveTime = isSelectedDate ? plannedTimeFor(dateKey, sidKey) : '';
    const label = isSelectedDate ? labelFor(dateKey, sidKey) : '';
    const slotGroup = isSelectedDate ? _slotGroupsFromLabelAndArrive(label, arriveTime, dateKey) : '';
    const hwChecked = truthy(entry?.hwChecked);
    const selfStudy = truthy(entry?.selfStudy) || isSelfStudy(dateKey, sidKey);
    const arriveTitle = isSelectedDate
      ? (isAttended(dateKey, sidKey) ? ARRIVE_WHEEL_ATTENDED_HINT : ARRIVE_WHEEL_HINT)
      : '과거 날짜 기록은 해당 날짜를 선택한 뒤 편집할 수 있습니다.';
    const slotMarkup = isSelectedDate ? renderEditableSlotLabel(label) : renderReadonlySlotLabel('—');
    const arriveMarkup = isSelectedDate
      ? `<span class="arriveLabel" contenteditable="true" spellcheck="false"
                data-orig="${escapeAttr(arriveTime || '')}"
                title="${escapeAttr(arriveTitle)}"
                style="display:inline-block;min-width:44px;padding:2px 4px;border-radius:6px;border:1px solid transparent">
            ${escapeAttr(arriveTime || '')}
          </span>`
      : `<span class="arriveLabelReadonly" title="${escapeAttr(arriveTitle)}">—</span>`;

    return `
      <tr data-sid="${escapeAttr(sidKey)}" data-date="${escapeAttr(dateKey)}" data-student-identity="${escapeAttr(studentLeaveIdentityKey(s || { id: sidKey }))}" ${s?.curriculum ? `data-curriculum="${escapeAttr(s.curriculum)}"` : ''} ${s?.subCurriculum ? `data-subcurriculum="${escapeAttr(s.subCurriculum)}"` : ''} ${slotGroup ? `data-slot-group="${escapeAttr(slotGroup)}"` : ''} ${hwChecked ? 'data-hw="1"' : ''} ${selfStudy ? 'data-self-study="1"' : ''}>
        <td class="done-date-cell">${escapeAttr(dateKey)}</td>
        <td class="today-slot-cell">${slotMarkup}</td>
        <td class="att-time done-arrive-cell">
          ${arriveMarkup}
        </td>
        <td class="today-name-cell">
          ${s ? `<a href="/student/${encodeURIComponent(String(s.id))}" target="_blank" class="stuName" data-sid="${escapeAttr(s.id)}">${escapeAttr(name)}</a>`
              : `<span class="stuName">${escapeAttr(name)}</span>`
          }
        </td>
        <td class="today-school-cell">${escapeAttr(school || '')}</td>
        <td class="today-curriculum-cell">${escapeAttr(curLabel)}</td>
        ${renderWhiteReviewPendingCell(sidKey, name)}
        <td class="done-action-cell">
          <span class="done-action-date">${escapeAttr(dateKey)}</span>
          ${renderTodayActionButtons({ sid: sidKey, name, date: dateKey, includeDoneActions: true })}
        </td>
        <td class="today-doc-cell">${renderTodayDocumentButton({ docUrl, name, sid: sidKey })}</td>
      </tr>
    `;
  }).join('');

  replaceStudentTable(wrap, `
    <table class="done-table">
      <colgroup>
        <col style="width:104px"><col style="width:72px"><col style="width:64px"><col style="width:120px"><col style="width:84px">
        <col style="width:112px"><col style="width:36px"><col style="width:232px"><col style="width:56px">
      </colgroup>
      <thead>
        <tr>
          <th>날짜</th>
          <th>구분</th>
          <th title="등원시간">등원</th>
          <th>이름</th>
          <th>학교</th>
          <th>커리큘럼</th>
          <th class="done-white-review-head">백지</th>
          <th>작업</th>
          <th>문서</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `, 'done-table');

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

    let slotSaveResult;
    try {
      slotSaveResult = await saveWeekendSlotsFromLabel(sid, cleaned, dateKey);
    } catch (e) {
      el.textContent = prevOrig;
      el.dataset.orig = prevOrig;
      try { toast('주말 슬롯 저장 실패'); } catch {}
      alert('주말 슬롯 저장 실패');
      return;
    }
    if (slotSaveResult?.orderReset === false) {
      toast('슬롯은 저장됐지만 오늘표 순서 초기화에 실패했습니다.');
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
    // This SID-scoped flag intentionally survives date changes, leave, and record cleanup.
    const whiteReview = ev.target.closest?.('.whiteReviewPendingChk');
    if (whiteReview) {
      await saveWhiteReviewCheckbox(whiteReview, loadTodayAndRender);
      return;
    }

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

        for (const tr of homeworkLeaveTargetRows(rows, currentSlot)) {
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

        homeworkLeaveBtn.disabled = true;
        homeworkLeaveBtn.textContent = '처리중';
        homeworkLeaveBtn.setAttribute('aria-busy', 'true');

        try {
          await patchLogsBatch(targets.map(target => ({
            date: target.dateKey,
            sid: target.sid,
            entry: {
              done: true,
              leaveTime: t,
              leaveAt,
            },
            clearKeys: ['archived'],
          })));

          document.dispatchEvent(new CustomEvent('attendance:updated'));
          await loadTodayAndRender();
          toast(`숙검하원 ${targets.length}명 하원 처리됨 (${t})`);
        } catch (err) {
          console.error('[today] homework leave batch failed:', err);
          alert('숙검하원 저장 실패');
          await loadTodayAndRender({ force: true, forceDatePayloads: true });
        } finally {
          homeworkLeaveBtn.disabled = false;
          homeworkLeaveBtn.textContent = prevText || '숙검하원';
          homeworkLeaveBtn.removeAttribute('aria-busy');
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

        let absenceRevision = '';
        try {
          const latestRes = await fetch('/api/absent', { cache: 'no-store' });
          if (!latestRes.ok) throw new Error(`/api/absent ${latestRes.status}`);
          const latest = await latestRes.json();
          absenceRevision = String(latestRes.headers.get('X-Absence-Revision') || '').trim();
          state.absences = normalizeAbsencesByStudent(latest?.by_student || {});
          state.absentByDate = normalizeAbsentByDateMap(latest?.by_date || {});
          state.absentSlotsByDate = normalizeAbsentSlotMap(latest?.by_slot || {});
        } catch (latestError) {
          console.error(latestError);
          setAttended(dateKey, sid, prevAttended);
          setContacted(dateKey, sid, prevContacted);
          document.dispatchEvent(new CustomEvent('attendance:updated'));
          try {
            await patchFlagRemote('att', dateKey, sid, prevAttended);
            await patchFlagRemote('contact', dateKey, sid, prevContacted);
          } catch (rollbackError) {
            console.error(rollbackError);
          }
          alert('최신 결석 정보를 불러오지 못했습니다.');
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
            headers: {
              'Content-Type': 'application/json',
              ...(absenceRevision ? { 'If-Match': absenceRevision } : {}),
            },
            body: JSON.stringify({
              by_date: state.absentByDate,
              by_student: state.absences,
              by_slot: state.absentSlotsByDate,
            }),
          });

          let data = null;
          try { data = await res.json(); } catch { }

          if (!res.ok) throw new Error(`/api/absent ${res.status}`);

          document.dispatchEvent(new CustomEvent('attendance:updated'));
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

          document.dispatchEvent(new CustomEvent('attendance:updated'));
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
        const activeRows = Array.from(document.querySelectorAll('#todayWrap tr[data-sid]'));
        const targetRows = linkedLeaveRows(tr, activeRows, currentOpsSlot());
        const seen = new Set();
        const targets = [];
        for (const row of targetRows) {
          const targetSid = rowSid(row);
          const targetDate = rowDateKey(row);
          const key = `${targetDate}\u0000${targetSid}`;
          if (!targetSid || !targetDate || seen.has(key)) continue;
          seen.add(key);
          targets.push({ sid: targetSid, dateKey: targetDate });
        }
        const t = nowHHMM();

        try {
          const leavePatch = {
            done: true,
            leaveTime: t,
            leaveAt: nowISO(),
          };
          await patchLogsBatch(targets.map(target => ({
            date: target.dateKey,
            sid: target.sid,
            entry: leavePatch,
            clearKeys: ['archived'],
          })));

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

