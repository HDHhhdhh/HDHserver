// /js/admin/features/extraModal.js
// 오늘 보강 학생 모달 (요일 슬롯: 월1/월2 ... 토1/토2, 일1/일2) — 라이트/다크 테마 대응
import { $, CT, toast } from '../core/utils.js';
import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import { clearTodayOrder, saveWeekendSlotsPatch, setArriveOverrides } from './today.state.js';
import { applySearchPlaceholder, matchesSearchKey, normalizeSearch, studentSearchKey } from '../../shared/search.js';
import { ensureOk, sendJson } from '../../shared/api.js';
import {
  legacyExtraAttendanceIds,
  legacyStudentName,
  mergeExtraAttendanceSelection,
} from './extraAttendanceMerge.js?v=20260821-safe-merge1';
import { saveScheduleOverridesFailClosed } from './scheduleOverrideSave.js?v=20260927-orphan-extra1';

function ensure() {
  if ($('#extraModal')) return;

  document.body.insertAdjacentHTML('beforeend', `
    <div id="extraModal" class="extra-backdrop" style="display:none" aria-modal="true" role="dialog">
      <div class="extra-panel">
        <div class="extra-topbar">
          <div class="extra-head">
            <h3 class="extra-title">오늘 보강 학생</h3>
            <div class="extra-actions extra-actions-top">
              <button type="button" class="ex-btn primary ex-save">저장</button>
              <button type="button" class="ex-btn ex-close">닫기</button>
            </div>
          </div>
          <div class="extra-search-row">
            <input type="search" id="exSearch" class="extra-search" placeholder="학생 이름 검색" autocomplete="off">
            <button type="button" id="exSearchPick" class="ex-btn">선택</button>
          </div>
          <div id="exSearchHint" class="extra-search-hint" aria-live="polite"></div>
        </div>
        <div id="exZone"></div>
        <div class="extra-actions extra-actions-bottom">
          <button type="button" class="ex-btn primary ex-save">저장</button>
          <button type="button" class="ex-btn ex-close">닫기</button>
        </div>
      </div>
    </div>
  `);

  const s = document.createElement('style');
  s.id = 'extraModalTheme';
  s.textContent = `
  /* ── Backdrop / Panel ───────────────────────────────── */
  #extraModal.extra-backdrop{
    position:fixed; inset:0; display:flex; align-items:center; justify-content:center;
    background:rgba(0,0,0,.45); z-index:9999;
  }
  #extraModal .extra-panel{
    width:546px; max-width:96vw; height:min(936px, 92vh); max-height:92vh;
    display:flex; flex-direction:column; overflow:hidden;
    border-radius:16px; padding:18px; box-sizing:border-box;
    border:1px solid var(--line, #334155);
    background:var(--card-dark, #0f172a);
    color:var(--text-dark, #e5e7eb);
    box-shadow:0 12px 34px rgba(0,0,0,.34);
  }
  body:not(.dark) #extraModal .extra-panel{
    background:var(--card-light, #ffffff);
    color:var(--text, #0f172a);
    border-color:var(--line, #e5e7eb);
  }
  #extraModal .extra-topbar{
    flex:0 0 auto;
    position:sticky; top:-18px; z-index:2;
    margin:-18px -18px 13px; padding:18px 18px 13px;
    background:var(--card-dark, #0f172a);
    border-bottom:1px solid color-mix(in oklab, var(--line, #334155) 80%, transparent);
  }
  body:not(.dark) #extraModal .extra-topbar{
    background:var(--card-light, #ffffff);
    border-bottom-color:color-mix(in oklab, var(--line, #e5e7eb) 80%, transparent);
  }
  #extraModal .extra-head{ display:flex; align-items:center; justify-content:space-between; gap:13px }
  #extraModal .extra-title{ margin:0; font-size:21px; font-weight:800 }
  #extraModal .extra-actions{ display:flex; gap:10px; justify-content:flex-end; margin-top:13px }
  #extraModal .extra-actions-top{ margin-top:0; flex-shrink:0 }
  #extraModal .extra-search-row{ display:flex; gap:10px; margin-top:13px }
  #extraModal .extra-search{
    min-width:0; flex:1; height:47px; box-sizing:border-box;
    border:1px solid var(--line, #334155);
    border-radius:13px; padding:0 13px;
    font-size:17px;
    background:color-mix(in oklab, var(--card-dark, #0f172a) 90%, var(--accent,#60a5fa));
    color:var(--text-dark, #e5e7eb);
    outline:none;
  }
  body:not(.dark) #extraModal .extra-search{
    background:color-mix(in oklab, #ffffff 92%, var(--accent,#2563eb));
    color:var(--text, #0f172a);
    border-color:var(--line, #e5e7eb);
  }
  #extraModal .extra-search:focus{
    border-color:var(--accent,#2563eb);
    box-shadow:0 0 0 2px color-mix(in oklab, var(--accent,#2563eb) 22%, transparent);
  }
  #extraModal .extra-search::placeholder{ color:currentColor; opacity:.55 }
  #extraModal .extra-search-row .ex-btn{ height:47px; white-space:nowrap }
  #extraModal .extra-search-hint{
    min-height:21px; margin-top:7px; font-size:16px; line-height:21px; opacity:.7;
  }

  /* ── 공통 버튼 ──────────────────────────────────────── */
  #extraModal .ex-btn{
    border:1px solid var(--line, #334155);
    background:color-mix(in oklab, var(--card-dark, #0f172a) 85%, var(--accent,#60a5fa));
    color:var(--text-dark, #e5e7eb);
    border-radius:13px; padding:9px 16px; cursor:pointer; font-weight:600;
    font-size:17px;
  }
  body:not(.dark) #extraModal .ex-btn{
    background:color-mix(in oklab, #ffffff 85%, var(--accent,#2563eb));
    color:var(--text, #0f172a); border-color:var(--line, #e5e7eb);
  }
  #extraModal .ex-btn.primary{
    background:var(--accent,#2563eb); color:#fff; border-color:transparent;
  }
  #extraModal .ex-btn:disabled{
    opacity:.45; cursor:not-allowed;
  }

  /* ── 리스트 ────────────────────────────────────────── */
  #exZone{ flex:1 1 auto; min-height:0; overflow:auto; display:flex; flex-direction:column; gap:8px; }
  #exZone .row{
    display:flex; align-items:center; justify-content:space-between; gap:13px;
    padding:10px 13px; border-radius:16px; border:1px solid var(--line,#334155);
    background:color-mix(in oklab, var(--card-dark,#0f172a) 92%, #0000);
    transition:background .15s ease, border-color .15s ease;
  }
  #exZone .row.is-filtered-out{ display:none !important; }
  body:not(.dark) #exZone .row{
    background:color-mix(in oklab, var(--card-light,#fff) 96%, #0000);
    border-color:var(--line,#e5e7eb);
  }
  #exZone .row.on{
    background:color-mix(in oklab, var(--accent,#2563eb) 18%, var(--card-dark,#0f172a));
    border-color:color-mix(in oklab, var(--accent,#2563eb) 40%, var(--line,#334155));
  }
  body:not(.dark) #exZone .row.on{
    background:color-mix(in oklab, var(--accent,#2563eb) 14%, var(--card-light,#fff));
    border-color:color-mix(in oklab, var(--accent,#2563eb) 45%, var(--line,#e5e7eb));
  }
  #exZone .row.legacy{ border-style:dashed; }
  #exZone .row.legacy small{
    color:color-mix(in oklab, currentColor 62%, #f59e0b);
    font-weight:700;
  }

  #exZone .row label{ display:flex; align-items:center; gap:10px; cursor:pointer; flex:1; color:inherit; font-size:17px }
  #exZone .row small{ opacity:.75; color:inherit }

  #exZone input[type="checkbox"]{
    width:21px; height:21px; accent-color:var(--accent,#2563eb); margin:0;
  }

  /* ── 슬롯 버튼(요일1·요일2) ─────────────────────────── */
  #exZone .slot-box{ display:flex; gap:10px; flex-wrap:wrap; justify-content:flex-end }
  #exZone .slot-btn{
    min-width:55px; height:44px; padding:0 13px; border-radius:13px; cursor:pointer; font-weight:900;
    font-size:17px;
    border:1px solid var(--line,#334155);
    background:color-mix(in oklab, var(--chip, rgba(96,165,250,.12)) 70%, transparent);
    color:inherit;
    white-space:nowrap;
  }
  body:not(.dark) #exZone .slot-btn{
    border-color:var(--line,#e5e7eb);
    background:color-mix(in oklab, var(--chip, #eef2ff) 70%, transparent);
  }
  #exZone .slot-btn.on{
    background:var(--accent,#2563eb); color:#fff; border-color:transparent;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.15);
  }
  #exZone .slot-btn:focus-visible{ outline:2px solid var(--accent,#2563eb); outline-offset:2px; }
  #extraModal .extra-actions-bottom{ flex:0 0 auto; }
  `;
  document.head.appendChild(s);
}

export function initExtraModal() {
  ensure();

  const exModal = $('extraModal');
  const exZone = $('exZone');
  const exSearch = $('exSearch');
  const exSearchPick = $('exSearchPick');
  const exSearchHint = $('exSearchHint');
  const btn = $('extraBtn');
  if (!btn) return;
  let baselineSelectedIds = [];
  let openSequence = 0;
  let ready = false;
  let saving = false;

  // 유틸
  const WCHR = '일월화수목금토';
  const yoilChar = (dateStr) => WCHR[new Date(dateStr).getDay()];
  const slotLabel = (dateStr, n) => `${yoilChar(dateStr)}${n}`;

  // ✅ 이제 슬롯은 전 요일 공통 1,2
  const SLOT_NUMS = [1, 2];
  const ARRIVE_BY_SLOT = { 1: '13:00', 2: '18:00' };

  function parseSlotList(raw) {
    const values = Array.isArray(raw) ? raw : [raw];
    const slots = values.flatMap(value => {
      const matches = String(value ?? '').match(/\d+/g) || [];
      return matches.map(n => parseInt(n, 10));
    }).filter(n => SLOT_NUMS.includes(n));
    return Array.from(new Set(slots)).sort((a, b) => a - b);
  }

  function dayValues(stu) {
    return Object.keys(stu || {})
      .filter(k => /^day\d+$/.test(k) && stu[k])
      .sort((a, b) => parseInt(a.slice(3), 10) - parseInt(b.slice(3), 10))
      .map(k => String(stu[k]));
  }

  function regularSlotsForStudent(stu, dateStr) {
    const wchr = yoilChar(dateStr);
    return parseSlotList(dayValues(stu).filter(v => String(v).startsWith(wchr)));
  }

  function mergedSlotsForStudent(sid, dateStr, slots, studentsById = null) {
    const stu = (studentsById
      ? studentsById.get(String(sid))
      : (state.students || []).find(s => String(s?.id || '') === String(sid))) || {};
    const merged = Array.from(new Set([
      ...regularSlotsForStudent(stu, dateStr),
      ...parseSlotList(slots),
    ])).sort((a, b) => a - b);
    return merged.length ? merged : [1];
  }

  function serializeSlots(slots) {
    const nums = parseSlotList(slots);
    if (nums.length <= 1) return nums[0] || 1;
    return nums;
  }

  // 최신 slots 로드(엔드포인트명은 유지)
  async function loadExtraAttend() {
    const response = await fetch('/api/extra-attend', { cache: 'no-store' });
    await ensureOk(response, '\uBCF4\uAC15 \uBA85\uB2E8 \uBD88\uB7EC\uC624\uAE30');
    const payload = await response.json();
    return payload && typeof payload === 'object' ? payload : {};
  }

  async function loadDaySlots() {
    const response = await fetch('/api/weekend-slots', { cache: 'no-store' });
    await ensureOk(response, '\uBCF4\uAC15 \uC2AC\uB86F \uBD88\uB7EC\uC624\uAE30');
    const payload = await response.json();
    return payload && typeof payload === 'object' ? payload : {};
  }

  const getRows = () => Array.from(document.querySelectorAll('#exZone .row'));
  applySearchPlaceholder(exSearch, '학생 이름 검색');

  function escapeAttr(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function setStudentSelected(row, selected, ensureDefaultSlot = false) {
    const chk = row?.querySelector('.chk-sid');
    if (!chk) return;
    chk.checked = selected;
    row.classList.toggle('on', selected);

    if (selected && ensureDefaultSlot && !row.querySelector('.slot-btn.on')) {
      const firstSlot = row.querySelector('.slot-btn[data-n="1"]') || row.querySelector('.slot-btn');
      if (firstSlot) firstSlot.classList.add('on');
    }
  }

  function applySearchFilter() {
    const queryText = exSearch?.value || '';
    const needle = normalizeSearch(queryText);
    let visible = 0;

    for (const row of getRows()) {
      const key = row.dataset.searchKey || normalizeSearch(row.textContent || '');
      const matches = matchesSearchKey(key, queryText);
      row.hidden = !matches;
      row.classList.toggle('is-filtered-out', !matches);
      row.setAttribute('aria-hidden', matches ? 'false' : 'true');
      if (matches) visible += 1;
    }

    if (exSearchPick) exSearchPick.disabled = !needle || visible === 0;
    if (exSearchHint) {
      exSearchHint.textContent = needle ? (visible ? `${visible}명` : '검색 결과 없음') : '';
    }
  }

  function pickSearchStudent() {
    const needle = normalizeSearch(exSearch?.value);
    if (!needle) return;

    const matches = getRows().filter(row => !row.hidden);
    const exact = matches.find(row => normalizeSearch(row.querySelector('.student-name')?.textContent) === needle);
    const row = exact || matches[0];
    if (!row) return;
    if (row.classList.contains('legacy')) {
      if (exSearchHint) exSearchHint.textContent = '퇴원 학생의 이전 보강 기록은 이 화면에서 수정할 수 없습니다.';
      return;
    }

    setStudentSelected(row, true, true);
    row.scrollIntoView({ block: 'nearest' });

    const name = row.querySelector('.student-name')?.textContent || '';
    if (exSearchHint) exSearchHint.textContent = name ? `${name} 선택됨` : '선택됨';
  }

  exSearch?.addEventListener('input', applySearchFilter);
  exSearch?.addEventListener('search', applySearchFilter);
  exSearch?.addEventListener('compositionend', applySearchFilter);
  exSearch?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      pickSearchStudent();
    } else if (e.key === 'Escape') {
      exSearch.value = '';
      applySearchFilter();
    }
  });
  exSearchPick?.addEventListener('click', pickSearchStudent);

  // 열기
  btn.addEventListener('click', async () => {
    if (saving) return;
    const sequence = ++openSequence;
    const today = getAdminDate();
    ready = false;
    exModal.querySelectorAll('.ex-save').forEach(button => { button.disabled = true; });
    exZone.innerHTML = '<p role="status">보강 명단을 불러오는 중입니다.</p>';
    exModal.style.display = 'flex';

    let extraMap;
    let slotMap;
    try {
      [extraMap, slotMap] = await Promise.all([loadExtraAttend(), loadDaySlots()]);
    } catch (error) {
      if (sequence !== openSequence) return;
      exZone.innerHTML = '<p role="alert">보강 명단을 불러오지 못했습니다. 닫은 뒤 다시 열어 주세요.</p>';
      console.error('[extra attendance] open failed:', error);
      toast('\uCD5C\uC2E0 \uBCF4\uAC15 \uBA85\uB2E8\uC744 \uBD88\uB7EC\uC624\uC9C0 \uBABB\uD588\uC2B5\uB2C8\uB2E4.');
      return;
    }

    if (sequence !== openSequence) return;
    exModal.dataset.date = today;
    state.extra = extraMap;
    window.extra = state.extra;
    const perDay = slotMap[today] || {};
    const checked = (state.extra[today] || []).map(String);
    const checkedSet = new Set(checked);
    baselineSelectedIds = checked.slice();
    const studentsById = new Map();
    for (const student of state.students || []) {
      const sid = String(student?.id || '');
      if (!studentsById.has(sid)) studentsById.set(sid, student);
    }
    const slotLabels = new Map(SLOT_NUMS.map(n => [n, slotLabel(today, n)]));

    const sorted = (state.students || []).slice()
      .sort((a, b) => String(a.name).localeCompare(String(b.name), 'ko'));
    const displayRows = [
      ...sorted.map(student => ({ student, isLegacy: false })),
      ...legacyExtraAttendanceIds(sorted, checked).map(sid => ({
        student: { id: sid, name: legacyStudentName(sid), curriculum: '\uC774\uC804 \uD559\uC0DD \uAE30\uB85D' },
        isLegacy: true,
      })),
    ];

    exZone.innerHTML = displayRows.map(({ student: s, isLegacy }) => {
      const sid = String(s.id);
      const isOn = checkedSet.has(sid);

      const raw = perDay[sid];
      const rawSlots = parseSlotList(raw);
      const slots = isOn ? mergedSlotsForStudent(sid, today, rawSlots.length ? rawSlots : [1], studentsById) : rawSlots;

      const slotBox = `
        <div class="slot-box" aria-label="슬롯 선택">
          ${SLOT_NUMS.map(n => `
            <button type="button"
                    class="slot-btn ${slots.includes(n) ? 'on' : ''}"
                    data-n="${n}"
                    title="${slotLabels.get(n)}" ${isLegacy ? 'disabled' : ''}>
              ${slotLabels.get(n)}
            </button>
          `).join('')}
        </div>`;

      return `
        <div class="row ${isOn ? 'on' : ''} ${isLegacy ? 'legacy' : ''}" data-sid="${escapeAttr(sid)}" data-search-key="${escapeAttr(studentSearchKey(s))}">
          <label>
            <input type="checkbox" class="chk-sid" ${isOn ? 'checked' : ''} ${isLegacy ? 'disabled title="퇴원 학생의 이전 보강 기록은 유지됩니다"' : ''}>
            <span class="student-name">${escapeAttr(s.name)}</span>
            <small>${s.curriculum || ''}${s.subCurriculum ? ' · ' + s.subCurriculum : ''}</small>
          </label>
          ${slotBox}
        </div>`;
    }).join('');

    if (exSearch) exSearch.value = '';
    if (exSearchPick) exSearchPick.disabled = true;
    if (exSearchHint) exSearchHint.textContent = '';
    ready = true;
    exModal.querySelectorAll('.ex-save').forEach(button => { button.disabled = false; });
    requestAnimationFrame(() => {
      if (sequence === openSequence && exModal.style.display !== 'none') exSearch?.focus();
    });
  });

  const closeExtraModal = () => {
    if (saving) return;
    openSequence += 1;
    ready = false;
    exModal.style.display = 'none';
  };
  window.closeExtraAttendancePopup = closeExtraModal;
  document.body.addEventListener('click', (e) => {
    const closeBtn = e.target.closest?.('#extraModal .ex-close');
    if (closeBtn) closeExtraModal();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || saving) return;
    if (exModal.style.display === 'none') return;
    closeExtraModal();
  });

  // 체크박스 변화 → 행 하이라이트 토글
  document.body.addEventListener('change', (e) => {
    const chk = e.target.closest('#exZone .chk-sid'); if (!chk) return;
    const row = chk.closest('.row'); if (!row) return;
    if (row.classList.contains('legacy')) return;
    setStudentSelected(row, chk.checked);
  });

  // 슬롯 버튼 토글(이벤트 위임) — 누르면 체크/행 활성화 자동 ON
  document.body.addEventListener('click', (e) => {
    const b = e.target.closest('#exZone .slot-btn'); if (!b) return;
    const row = b.closest('.row'); if (!row) return;
    if (row.classList.contains('legacy')) return;

    b.classList.toggle('on');

    const chk = row.querySelector('.chk-sid');
    if (chk && !chk.checked) {
      chk.checked = true;
      row.classList.add('on');
    }
  });

  // 저장
  document.body.addEventListener('click', async (e) => {
    const saveBtn = e.target.closest?.('#extraModal .ex-save');
    if (!saveBtn || saveBtn.disabled || saving || !ready) return;

    const today = String(exModal.dataset.date || '').trim();
    if (!today) {
      toast('보강 날짜를 다시 선택해 주세요.');
      return;
    }

    saving = true;
    const saveButtons = Array.from(exModal.querySelectorAll('.ex-save'));
    const saveLabels = saveButtons.map(button => button.textContent);
    const controlStates = Array.from(exModal.querySelectorAll('button, input')).map(control => [control, control.disabled]);
    controlStates.forEach(([control]) => { control.disabled = true; });
    saveButtons.forEach(button => {
      button.textContent = '저장 중…';
      button.setAttribute('aria-busy', 'true');
    });

    let extraSaved = false;
    try {
      // 선택 학생
      const rows = Array.from(document.querySelectorAll('#exZone .row'));
      const selectedRows = rows.filter(r => r.querySelector('.chk-sid')?.checked);
      const activeSelectedRows = selectedRows.filter(r => !r.classList.contains('legacy'));
      const uiSelectedIds = selectedRows.map(r => String(r.dataset.sid));
      const currentStudentIds = new Set((state.students || []).map(student => String(student?.id || '')));
      const [latestExtraResponse, slotResponse] = await Promise.all([
        fetch('/api/extra-attend', { cache: 'no-store' }),
        fetch('/api/weekend-slots', { cache: 'no-store' }),
      ]);
      await Promise.all([
        ensureOk(latestExtraResponse, '\uCD5C\uC2E0 \uBCF4\uAC15 \uBA85\uB2E8 \uBD88\uB7EC\uC624\uAE30'),
        ensureOk(slotResponse, '보강 슬롯 불러오기'),
      ]);
      const [latestExtra, slotMap] = await Promise.all([
        latestExtraResponse.json(), slotResponse.json(),
      ]);
      if (!latestExtra || typeof latestExtra !== 'object' || Array.isArray(latestExtra)
        || !slotMap || typeof slotMap !== 'object' || Array.isArray(slotMap)) {
        throw new Error('보강 명단과 슬롯을 다시 불러온 뒤 저장해 주세요.');
      }
      const selection = mergeExtraAttendanceSelection(
        latestExtra?.[today] || [],
        baselineSelectedIds,
        uiSelectedIds,
      );
      const selectedIds = selection.selectedIds;
      const removedIds = new Set(selection.removedIds);

      // 보강 명단보다 슬롯을 먼저 확정한다. 슬롯 저장이 실패하면 명단에
      // 요일만 남는 고아 행을 만들지 않는다.
      const perDay = { ...(slotMap[today] || {}) };
      const weekendPatch = {};

      for (const sid of removedIds) {
        // 퇴원 SID의 과거 슬롯은 보존하고, 현재 명단 SID만 갱신한다.
        if (!currentStudentIds.has(sid)) continue;
        delete perDay[sid];
        weekendPatch[sid] = [];
      }

      // 선택된 학생: on 버튼 수집(없으면 [1])
      for (const row of activeSelectedRows) {
        const sid = String(row.dataset.sid);
        const nums = Array.from(row.querySelectorAll('.slot-btn.on'))
          .map(b => parseInt(b.dataset.n, 10))
          .filter(n => SLOT_NUMS.includes(n))
          .sort((a, b) => a - b);
        const value = serializeSlots(mergedSlotsForStudent(sid, today, nums.length ? nums : [1]));
        perDay[sid] = value;
        weekendPatch[sid] = value;
      }

      let extraResult = {};
      const nextExtra = latestExtra && typeof latestExtra === 'object' ? { ...latestExtra } : {};
      if (selectedIds.length) nextExtra[today] = selectedIds;
      else delete nextExtra[today];
      await saveScheduleOverridesFailClosed({
        extraMap: nextExtra,
        weekendPatch: { [today]: weekendPatch },
        saveWeekend: async patch => {
          const mapping = patch?.[today];
          if (mapping && Object.keys(mapping).length) await saveWeekendSlotsPatch(today, mapping);
        },
        saveExtra: async () => {
          const extraResponse = await sendJson(
            '/api/extra-attend',
            { deltas: { [today]: Object.fromEntries([
              ...selection.addedIds.map(sid => [sid, true]),
              ...selection.removedIds.map(sid => [sid, false]),
            ]) } },
            { method: 'PATCH' },
          );
          await ensureOk(extraResponse, '보강 명단 저장');
          extraSaved = true;
          extraResult = await extraResponse.json();
          if (!Array.isArray(extraResult?.dates?.[today])) {
            throw new Error('보강 명단의 저장 결과를 확인하지 못했습니다. 새로고침해 주세요.');
          }
        },
      });
      state.extra = nextExtra;
      state.extra[today] = extraResult.dates[today].map(String);
      if (!state.extra[today].length) delete state.extra[today];
      window.extra = state.extra;

      // 보강 슬롯에 맞춰 등원시간도 함께 갱신 (1교시=13:00, 2교시=18:00)
      const arrivePatch = {};
      for (const row of activeSelectedRows) {
        const sid = String(row.dataset.sid);
        const raw = perDay[sid];
        const slots = Array.isArray(raw)
          ? raw.map(Number).filter(n => SLOT_NUMS.includes(n))
          : (Number.isInteger(raw) && SLOT_NUMS.includes(raw) ? [raw] : []);
        const first = slots.length ? Math.min(...slots) : 1;
        arrivePatch[sid] = ARRIVE_BY_SLOT[first] || '13:00';
      }
      if (Object.keys(arrivePatch).length) {
        const arriveResponse = await sendJson('/api/arrive-time', { [today]: arrivePatch });
        await ensureOk(arriveResponse, '등원시간 저장');
        setArriveOverrides(today, arrivePatch);
      }

      // 3) 오늘 사용자 정렬 캐시 초기화 → 자동 정렬 반영
      let orderReset = true;
      try { await clearTodayOrder(today); }
      catch (orderError) {
        orderReset = false;
        console.warn('[extra attendance] today order reset failed:', orderError);
      }

      toast(orderReset ? '보강 저장' : '보강은 저장됐지만 오늘표 순서 초기화 실패');
      exModal.style.display = 'none';
      document.dispatchEvent(new CustomEvent('admin:refresh', { detail: { force: true } }));
      if (typeof window.recalcCalendarCounts === 'function') await window.recalcCalendarCounts();
    } catch (error) {
      console.error('[extra attendance] save failed:', error);
      alert(extraSaved
        ? '보강 명단은 저장됐지만 후속 정보 저장에 실패했습니다. 새로고침 후 다시 확인해 주세요.'
        : '보강 저장에 실패했습니다. 새로고침 후 다시 시도해 주세요.');
      document.dispatchEvent(new CustomEvent('admin:refresh', { detail: { force: true } }));
    } finally {
      saving = false;
      controlStates.forEach(([control, disabled]) => { control.disabled = disabled; });
      saveButtons.forEach((button, index) => {
        button.disabled = false;
        button.textContent = saveLabels[index];
        button.removeAttribute('aria-busy');
      });
    }
  });
}
