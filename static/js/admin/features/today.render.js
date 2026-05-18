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

import {
  yoilOf,
  labelFor,
  plannedTimeFor,
  plannedTimeBase,
  getArriveOverride,
  setArriveOverride,
  isAttended, setAttended,
  isContacted, setContacted,
  isHwChecked, setHomeworkCheckedRemote,
  getLeaveTime, setLeaveTimeRemote,
  saveWeekendSlotsFromLabel,
  saveOrder,
  nowHHMM,
  nowISO,
  patchLog,
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

function setAbsenceMapsSafely({ byDate, byStudent } = {}) {
  state.absentByDate = looksLikeAbsentByDateMap(byDate) ? normalizeAbsentByDateMap(byDate) : (state.absentByDate || {});
  state.absences = (byStudent && typeof byStudent === 'object') ? normalizeAbsencesByStudent(byStudent) : (state.absences || {});
  ensureWindowStateAlias();
}

// Normalize absence maps once at module boot.
(function bootAbsenceMaps() {
  state.absentByDate = looksLikeAbsentByDateMap(state.absentByDate) ? normalizeAbsentByDateMap(state.absentByDate) : (state.absentByDate || {});
  state.absences = (state.absences && typeof state.absences === 'object') ? normalizeAbsencesByStudent(state.absences) : (state.absences || {});
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
      width:30px;height:30px;margin:0;border-radius:10px;
      border:1px solid rgba(148,163,184,.55);
      background:rgba(248,250,252,.95);
      transition:transform .08s ease, filter .12s ease, background .12s ease, border-color .12s ease;
      user-select:none;
    }
    body.dark .chk4 .c{border-color:#334155;background:rgba(2,6,23,.55)}
    .chk4 .c:hover{filter:brightness(1.03)}
    .chk4 input{width:18px;height:18px;accent-color:#10b981;margin:0}
    .chk4 .c + .c{margin-left:6px}
    .chk4 .c[data-kind="contact"] input{accent-color:#3b82f6}
    .chk4 .c[data-kind="check"] input{accent-color:#f59e0b}
    .chk4 .c[data-on="1"]{background:rgba(16,185,129,.10);border-color:rgba(16,185,129,.45)}
    .chk4 .c[data-kind="contact"][data-on="1"]{background:rgba(59,130,246,.10);border-color:rgba(59,130,246,.45)}
    .chk4 .c[data-kind="check"][data-on="1"]{background:rgba(245,158,11,.12);border-color:rgba(245,158,11,.55)}
    .chk4 .c:active{transform:scale(.98)}
    .chk4 .c input:disabled{cursor:not-allowed;opacity:.95}
    #todayWrap table.today-table{min-width:1140px;table-layout:fixed}
    #doneWrap table.done-table{min-width:1060px;table-layout:fixed}
    .today-table th,.today-table td,.done-table th,.done-table td{overflow:hidden;text-overflow:ellipsis}
    .today-check-cell,.today-doc-cell,.today-action-cell,.makeup-count-cell{text-align:center}
    .today-action-cell,.done-action-cell{white-space:nowrap;overflow:visible!important;text-overflow:clip!important}
    .today-actions{display:inline-flex;align-items:center;justify-content:center;gap:6px;white-space:nowrap}
    .today-actions button{flex:0 0 auto}
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
  `;
  document.head.appendChild(s);
})();

// Slot labels force a fixed arrive time.
// - slot 1 => 13:00
// - slot 2 => 18:00
// - mixed slots use the earliest slot
function _parseSlotNumsFromLabel(txt) {
  const s = String(txt || '').trim();

  // 요일+교시: 월1, 토2, 토1/토2 같은 문자열에서 교시 번호 추출
  const hits = s.match(/[일월화수목금토]\s*[-]?\s*[12]/g);
  if (hits && hits.length) {
    const nums = hits
      .map(x => x.match(/[12]/)?.[0])
      .filter(Boolean)
      .map(n => parseInt(n, 10));
    return Array.from(new Set(nums)).sort((a, b) => a - b);
  }

  // "1교시", "2교시" 형태도 허용
  const hits2 = s.match(/[12]\s*교시/g);
  if (hits2 && hits2.length) {
    const nums = hits2
      .map(x => x.match(/[12]/)?.[0])
      .filter(Boolean)
      .map(n => parseInt(n, 10));
    return Array.from(new Set(nums)).sort((a, b) => a - b);
  }

  return [];
}

function _forcedArriveTimeBySlotLabel(dateKey, labelText) {
  const nums = _parseSlotNumsFromLabel(labelText);
  if (!nums.length) return '';
  const minSlot = Math.min(...nums);
  if (minSlot === 1) return '13:00';
  if (minSlot === 2) return '18:00';
  return '';
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
        <col style="width:32px"><col style="width:72px"><col style="width:84px"><col style="width:84px">
        <col style="width:120px"><col style="width:104px"><col style="width:120px"><col style="width:160px">
        <col style="width:56px"><col style="width:228px">
      </colgroup>
      <thead>
        <tr>
          <th style="width:24px"></th>
          <th>구분</th>
          <th style="width:84px">도착</th>
          <th style="width:84px">하원</th>
          <th>이름</th>
          <th style="width:98px">날짜</th>
          <th>학교</th>
          <th>커리큘럼</th>
          <th>문서</th>
          <th>작업</th>
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

  wrap.addEventListener('keydown', (ev) => {
    const el = ev.target.closest?.('.arriveLabel,.leaveLabel');
    if (!el) return;
    if (ev.key === 'Enter') { ev.preventDefault(); el.blur(); }
    if (ev.key === 'Escape') { el.textContent = el.dataset.orig || ''; el.blur(); }
  });

  wrap.addEventListener('focusin', (ev) => {
    const el = ev.target.closest?.('.arriveLabel,.leaveLabel');
    if (!el) return;
    el.style.borderColor = '#cbd5e1';
    el.style.background = 'rgba(148,163,184,.12)';
  });

  // doneWrap edits only update the local override value.
  wrap.addEventListener('focusout', async (ev) => {
    const el = ev.target.closest?.('.arriveLabel');
    if (!el) return;

    el.style.borderColor = 'transparent';
    el.style.background = 'transparent';

    const tr = el.closest('tr[data-sid][data-date]'); if (!tr) return;
    const sid = tr.dataset.sid;
    const date = tr.dataset.date;

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

    const tr = el.closest('tr[data-sid][data-date]'); if (!tr) return;
    const sid = tr.dataset.sid;
    const date = tr.dataset.date;

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
  const leave = (tr.querySelector('.leaveLabel')?.textContent || '').trim();

  const nameLink = tr.querySelector('a.stuName');
  const nameCellHtml = nameLink
    ? nameLink.outerHTML
    : `<span class="stuName">${(tr.querySelector('.stuName')?.textContent || '').trim()}</span>`;

  const tds = tr.querySelectorAll('td');
  const school = (tds[6]?.textContent || '').trim();
  const curLabel = (tds[7]?.textContent || '').trim();
  const docBtn = tr.querySelector('.btn-doc');
  const docUrl = docBtn?.dataset?.docUrl || '';

  const sid = String(tr.dataset.sid || '');

  const newRow = document.createElement('tr');
  newRow.dataset.sid = sid;
  newRow.dataset.date = dateKey;
  newRow.innerHTML = `
    <td class="drag-handle" style="cursor:grab;width:24px;text-align:center">::</td>
    <td>${label}</td>

    <td style="text-align:center;width:84px;">
      <span class="arriveLabel" contenteditable="true" spellcheck="false"
            data-orig="${arrive || ''}"
            style="display:inline-block;min-width:56px;padding:2px 6px;border-radius:6px;border:1px solid transparent">
        ${arrive || ''}
      </span>
    </td>

    <td style="text-align:center;width:84px;">
      <span class="leaveLabel" contenteditable="true" spellcheck="false"
            data-orig="${leave || ''}"
            style="display:inline-block;min-width:56px;padding:2px 6px;border-radius:6px;border:1px solid transparent">
        ${leave || ''}
      </span>
    </td>

    <td>${nameCellHtml}</td>
    <td>${dateKey}</td>
    <td>${school || ''}</td>
    <td>${curLabel || ''}</td>
    <td><button class="btn-doc" data-doc-url="${docUrl}" title="문서 열기">📄</button></td>

    <td>
      <button class="openStudentPopups" title="영상 배정 + 수업 기록">🧾</button>
      <button class="markAbsent" title="결석">🚫</button>
      <button class="markLeave" title="하원">🏠</button>
      <button class="undoDone" title="완료 되돌리기" style="margin-left:6px">↩️</button>
      <button class="clearDone" title="기록 정리" style="margin-left:6px">🧹</button>
    </td>
  `;

  tbDone.prepend(newRow);

  tr.remove();

  const cnt = $('todayCount');
  if (cnt) {
    const cur = parseInt(cnt.textContent || '0', 10);
    cnt.textContent = String(Math.max(0, (Number.isFinite(cur) ? cur : 0) - 1));
  }

  const wrapToday = $('todayWrap');
  if (wrapToday) {
    const remain = wrapToday.querySelectorAll('tr[data-sid]').length;
    if (!remain) wrapToday.innerHTML = '오늘 학생 없음';
  }
}

// --- render ---
export function renderToday(list, dateKey, alphaSortOnly, makeupCounts = {}) {
  const host = $('todayWrap');
  const cnt = $('todayCount');
  if (!host) return;

  const rows = list.map(s => {
    const curLabel = s.curriculum + (s.subCurriculum ? ' ' + s.subCurriculum : '');
    const label = labelFor(dateKey, s.id);

    const attended = isAttended(dateKey, s.id);
    const contacted = isContacted(dateKey, s.id);
    const hwChecked = isHwChecked(dateKey, s.id);

    const arriveTime = plannedTimeFor(dateKey, s.id);
    const leaveTime = getLeaveTime(dateKey, s.id);

    const school =
      s.school ?? s.schoolName ?? s.highSchool ?? s.middleSchool ??
      s.high ?? s.middle ?? s.schoolHigh ?? s.schoolMiddle ?? '';

    const labelText = (label || yoilOf(dateKey) || '').trim();
    const makeupCount = Number(makeupCounts?.[String(s.id)] || 0);

    return `
      <tr data-sid="${s.id}" data-date="${dateKey}"
          ${attended ? 'data-att="1"' : ''} ${contacted ? 'data-contact="1"' : ''}
          ${hwChecked ? 'data-hw="1"' : ''}>
        <td class="drag-handle today-drag-cell" style="cursor:${alphaSortOnly ? 'default' : 'grab'};text-align:center">::</td>

        <td class="today-slot-cell">
          <span class="slotLabel" contenteditable="true" spellcheck="false"
                data-orig="${labelText}"
                style="display:inline-block;min-width:48px;padding:2px 6px;border-radius:6px;border:1px solid transparent">
            ${labelText}
          </span>
        </td>

        <td class="att-time" style="text-align:center;width:84px;">
          <span class="arriveLabel" contenteditable="true" spellcheck="false"
                data-orig="${arriveTime || ''}"
                style="display:inline-block;min-width:56px;padding:2px 6px;border-radius:6px;border:1px solid transparent">
            ${arriveTime || ''}
          </span>
        </td>

        <td class="leave-time" style="text-align:center;width:84px;">
          <span class="leaveLabel" contenteditable="true" spellcheck="false"
                data-orig="${leaveTime || ''}"
                style="display:inline-block;min-width:56px;padding:2px 6px;border-radius:6px;border:1px solid transparent">
            ${leaveTime || ''}
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

        <td>
          <a href="/student/${s.id}" target="_blank" class="stuName" data-sid="${s.id}">
            ${s.name}
          </a>
        </td>

        <td>${school || ''}</td>
        <td>${curLabel}</td>
        <td class="today-doc-cell"><button class="btn-doc" data-doc-url="${s.docUrl || ''}" title="문서 열기">📄</button></td>

        <td>
          <button class="openStudentPopups" title="영상 배정 + 수업 기록">🧾</button>
          <button class="openTestProgress" title="테스트 진도">🧪</button>
          <button class="markAbsent" title="결석">🚫</button>
          <button class="markLeave" title="하원">🏠</button>
        </td>
        <td class="makeup-count-cell">
          <span class="makeup-count-badge ${makeupCount > 0 ? 'needs' : ''}">${makeupCount}</span>
        </td>
      </tr>
    `;
  }).join('');

  host.innerHTML = list.length ? `
    <table class="today-table">
      <colgroup>
        <col style="width:32px"><col style="width:72px"><col style="width:84px"><col style="width:84px">
        <col style="width:168px"><col style="width:120px"><col style="width:120px"><col style="width:160px">
        <col style="width:56px"><col style="width:168px"><col style="width:64px">
      </colgroup>
      <thead>
        <tr>
          <th></th>
          <th>구분</th>
          <th>도착</th>
          <th>하원</th>
          <th>출석/연락/숙제</th>
          <th>이름</th>
          <th>학교</th>
          <th>커리큘럼</th>
          <th>문서</th>
          <th>작업</th>
          <th>보강</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  ` : '오늘 학생 없음';

  Array.from(host.querySelectorAll('tr[data-sid]')).forEach(tr => {
    if (tr.dataset.att === '1') tr.style.background = 'rgba(16,185,129,0.09)';
    else tr.style.background = '';
  });

  Array.from(host.querySelectorAll('.chk4 .c')).forEach(pill => {
    const input = pill.querySelector('input');
    if (!input) return;
    pill.dataset.on = input.checked ? '1' : '0';
  });

  if (cnt) cnt.textContent = String(list.length);

  requestAnimationFrame(() => attachSortable(dateKey, alphaSortOnly));
}

export function renderDone(doneEntries) {
  const wrap = $('doneWrap');
  if (!wrap) return;

  if (!doneEntries.length) {
    wrap.innerHTML = '완료 기록 없음';
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
    const leaveTime = getLeaveTime(date, sid);
    const label = labelFor(date, sid);

    return `
      <tr data-sid="${sid}" data-date="${date}">
        <td class="drag-handle" style="cursor:grab;width:24px;text-align:center">::</td>
        <td>${label}</td>

        <td style="text-align:center;width:84px;">
          <span class="arriveLabel" contenteditable="true" spellcheck="false"
                data-orig="${arriveTime || ''}"
                style="display:inline-block;min-width:56px;padding:2px 6px;border-radius:6px;border:1px solid transparent">
            ${arriveTime || ''}
          </span>
        </td>

        <td style="text-align:center;width:84px;">
          <span class="leaveLabel" contenteditable="true" spellcheck="false"
                data-orig="${leaveTime || ''}"
                style="display:inline-block;min-width:56px;padding:2px 6px;border-radius:6px;border:1px solid transparent">
            ${leaveTime || ''}
          </span>
        </td>

        <td>
          ${s ? `<a href="/student/${s.id}" target="_blank" class="stuName">${name}</a>`
              : `<span class="stuName">${name}</span>`
          }
        </td>

        <td>${date}</td>
        <td>${school || ''}</td>
        <td>${curLabel}</td>
        <td><button class="btn-doc" data-doc-url="${docUrl}" title="문서 열기">📄</button></td>
        <td>
          <button class="openStudentPopups" title="영상 배정 + 수업 기록">🧾</button>
          <button class="markAbsent" title="결석">🚫</button>
          <button class="markLeave" title="하원">🏠</button>
          <button class="undoDone" title="완료 되돌리기" style="margin-left:6px">↩️</button>
          <button class="clearDone" title="기록 정리" style="margin-left:6px">🧹</button>
        </td>
      </tr>
    `;
  }).join('');

  wrap.innerHTML = `
    <table class="done-table">
      <colgroup>
        <col style="width:32px"><col style="width:72px"><col style="width:84px"><col style="width:84px">
        <col style="width:120px"><col style="width:104px"><col style="width:120px"><col style="width:160px">
        <col style="width:56px"><col style="width:228px">
      </colgroup>
      <thead>
        <tr>
          <th style="width:24px"></th>
          <th>구분</th>
          <th style="width:84px">도착</th>
          <th style="width:84px">하원</th>
          <th>이름</th>
          <th style="width:98px">날짜</th>
          <th>학교</th>
          <th>커리큘럼</th>
          <th>문서</th>
          <th>작업</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;

  _bindDoneWrapInlineEditOnce();
}

// --- todayWrap event delegation ---
export function bindTodayTableEvents(loadTodayAndRender) {
  const host = $('todayWrap');
  if (!host) return;

  if (host._todayDelegated) return;
  host._todayDelegated = true;

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

    const tr = el.closest('tr[data-sid][data-date]');
    if (!tr) return;

    const sid = tr.dataset.sid;
    const dateKey = tr.dataset.date;

    const prevLabel = (el.dataset.orig || '').trim();
    const oldForcedBase = _forcedArriveTimeBySlotLabel(dateKey, prevLabel) || '';

    const txt = (el.textContent || '').trim();
    const cleaned = txt.replace(/\(보강\)/g, '').trim();
    el.textContent = cleaned;

    const oldBase = plannedTimeBase(dateKey, sid) || '';
    const oldOv = (getArriveOverride(dateKey, sid) || '').trim();

    el.dataset.orig = cleaned;
    await saveWeekendSlotsFromLabel(sid, cleaned, dateKey);
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

    const tr = el.closest('tr[data-sid][data-date]');
    if (!tr) return;

    const sid = tr.dataset.sid;
    const dateKey = tr.dataset.date;
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

    const tr = el.closest('tr[data-sid][data-date]');
    if (!tr) return;

    const sid = tr.dataset.sid;
    const dateKey = tr.dataset.date;
    const txt = (el.textContent || '').trim();

    el.dataset.orig = txt;
    try { await setLeaveTimeRemote(dateKey, sid, txt); }
    catch (e) { console.error(e); alert('하원시간 저장 실패'); }

    await loadTodayAndRender();
  });

  host.addEventListener('change', async (ev) => {
    const dateKey = getAdminDate();

    // Attendance
    const att = ev.target.closest?.('.attendChk');
    if (att) {
      const tr = att.closest('tr[data-sid]'); if (!tr) return;
      const sid = tr.dataset.sid;
      const prevChecked = isAttended(dateKey, sid);
      const checked = att.checked;

      tr.dataset.att = checked ? '1' : '';
      tr.style.background = checked ? 'rgba(16,185,129,0.09)' : '';
      const pill = att.closest('.c'); if (pill) pill.dataset.on = checked ? '1' : '0';

      setAttended(dateKey, sid, checked);
      document.dispatchEvent(new CustomEvent('attendance:updated'));

      try {
        await patchFlagRemote('att', dateKey, sid, checked);
      } catch (e) {
        console.error(e);
        att.checked = prevChecked;
        tr.dataset.att = prevChecked ? '1' : '';
        tr.style.background = prevChecked ? 'rgba(16,185,129,0.09)' : '';
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
      const tr = ct.closest('tr[data-sid]'); if (!tr) return;
      const sid = tr.dataset.sid;
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

      await loadTodayAndRender();
      return;
    }

    // Homework completion is the single visible homework flag.
    const hc = ev.target.closest?.('.hwCheckChk');
    if (hc) {
      const tr = hc.closest('tr[data-sid]'); if (!tr) return;
      const sid = tr.dataset.sid;
      const checked = hc.checked;

      try { await setHomeworkCheckedRemote(dateKey, sid, checked); }
      catch (e) { console.error(e); alert('숙제 체크 저장 실패'); }

      const pill = hc.closest('.c'); if (pill) pill.dataset.on = checked ? '1' : '0';
      await loadTodayAndRender();
      return;
    }
  });

  if (!document._todayDocClickBound) {
    document._todayDocClickBound = true;

    document.addEventListener('click', async (e) => {
      const docBtn = e.target.closest('.btn-doc');
      if (docBtn) {
        const url = docBtn.dataset.docUrl;
        if (url) window.open(url, '_blank');
        return;
      }

      const absentBtn = e.target.closest('.markAbsent');
      if (absentBtn) {
        const tr = absentBtn.closest('tr[data-sid]'); if (!tr) return;
        const sid = String(tr.dataset.sid);
        const dateKey = getAdminDate();

        const prevAttended = isAttended(dateKey, sid);
        const prevContacted = isContacted(dateKey, sid);
        const prevByStudent = state.absences?.[sid];
        const prevDateList = Array.isArray(state.absentByDate?.[dateKey])
          ? state.absentByDate[dateKey].map(String)
          : [];

        // Clear attendance/contact before marking the row absent.
        setAttended(dateKey, sid, false);
        setContacted(dateKey, sid, false);
        document.dispatchEvent(new CustomEvent('attendance:updated'));

        try {
          await patchFlagRemote('att', dateKey, sid, false);
          await patchFlagRemote('contact', dateKey, sid, false);
        } catch (syncErr) {
          console.error(syncErr);
          setAttended(dateKey, sid, prevAttended);
          setContacted(dateKey, sid, prevContacted);
          document.dispatchEvent(new CustomEvent('attendance:updated'));
          alert('결석 전에 출석/연락 정리 실패');
          await loadTodayAndRender();
          return;
        }

        // Update local absence maps first so the UI stays consistent.
        state.absences = state.absences && typeof state.absences === 'object' ? state.absences : {};
        state.absentByDate = looksLikeAbsentByDateMap(state.absentByDate) ? state.absentByDate : {};

        state.absences[sid] = dateKey;
        const cur = Array.isArray(state.absentByDate[dateKey]) ? state.absentByDate[dateKey].map(String) : [];
        state.absentByDate[dateKey] = Array.from(new Set([...cur, sid]));

        ensureWindowStateAlias();

        try {
          const res = await fetch('/api/absent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              by_date: state.absentByDate,
              by_student: state.absences,
            }),
          });

          let data = null;
          try { data = await res.json(); } catch { }

          if (!res.ok) throw new Error(`/api/absent ${res.status}`);

          // Prefer the server copy if it returns fresher absence maps.
          const byDate = data?.by_date || data?.absentByDate || (data?.ok ? data?.by_date : null);
          const byStu = data?.by_student || data?.absences || (data?.ok ? data?.by_student : null);

          setAbsenceMapsSafely({ byDate, byStudent: byStu });

          toast('결석 처리됨');
          await loadTodayAndRender();

          if (typeof window.recalcCalendarCounts === 'function') window.recalcCalendarCounts();
        } catch (e2) {
          console.error(e2);
          // rollback local absence map
          state.absences = state.absences && typeof state.absences === 'object' ? state.absences : {};
          state.absentByDate = looksLikeAbsentByDateMap(state.absentByDate) ? state.absentByDate : {};
          if (prevByStudent) state.absences[sid] = prevByStudent;
          else delete state.absences[sid];
          state.absentByDate[dateKey] = prevDateList;
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
        const tr = leaveBtn.closest('tr[data-sid]'); if (!tr) return;
        const sid = String(tr.dataset.sid);

        const dateKey = tr.dataset.date || getAdminDate();
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
          await loadTodayAndRender();
        } catch (err) {
          console.error(err);
          alert('하원 저장 실패');
        }
        return;
      }

      const undoBtn = e.target.closest('.undoDone');
      const clearBtn = e.target.closest('.clearDone');
      if (undoBtn || clearBtn) {
        const tr = e.target.closest('tr[data-sid][data-date]');
        if (!tr) return;
        const sid = String(tr.dataset.sid);
        const date = tr.dataset.date;

        try {
          if (undoBtn) {
            await patchLog(date, sid, { done: false }, ['archived']);
            toast('완료 취소됨');
          } else {
            await patchLog(date, sid, { archived: true });
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

