import { $ } from '../core/utils.js';
import { initAttendanceLedgerLink } from './attendanceLedgerLink.js';

function clickById(id) {
  const el = $(id);
  if (!el) return false;
  el.click();
  return true;
}

function scrollToSection(id) {
  const el = document.getElementById(id);
  if (!el) return false;
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return true;
}

const OPS_SLOT_BOUNDARY_MINUTES = 18 * 60;
const OPS_SLOT_START_MINUTES = { 1: 13 * 60, 2: 18 * 60 };
// KPI target ends ten minutes before the nominal slot close.
const OPS_SLOT_END_MINUTES = { 1: (16 * 60) + 50, 2: (21 * 60) + 50 };
const OPS_BREAKS = {
  1: [{ start: (14 * 60) + 55, end: (15 * 60) + 10 }],
  2: [{ start: (19 * 60) + 55, end: (20 * 60) + 10 }],
};

function minutesOfDay(d) {
  return (d.getHours() * 60) + d.getMinutes() + (d.getSeconds() / 60);
}

function currentOpsSlot(now = new Date()) {
  return minutesOfDay(now) < OPS_SLOT_BOUNDARY_MINUTES ? 1 : 2;
}

function parseHHMM(value) {
  const match = /^(\d{1,2}):(\d{2})$/.exec(String(value || '').trim());
  if (!match) return null;
  const hh = Number(match[1]);
  const mm = Number(match[2]);
  if (!Number.isInteger(hh) || !Number.isInteger(mm)) return null;
  if (hh < 0 || hh > 23 || mm < 0 || mm > 59) return null;
  return (hh * 60) + mm;
}

function slotGroupsFromRow(row) {
  const fromData = String(row?.dataset?.slotGroup || '')
    .split(',')
    .map(n => Number(n))
    .filter(n => n === 1 || n === 2);
  if (fromData.length) return new Set(fromData);

  const label = String(row?.querySelector?.('.slotLabel')?.textContent || row?.cells?.[1]?.textContent || '');
  const compact = label.replace(/\s+/g, '');
  const groups = new Set();
  if (/(?:^|[^0-9])1(?:타임|교시)?(?:[^0-9]|$)/.test(compact) || /[월화수목금토일]1/.test(compact)) groups.add(1);
  if (/(?:^|[^0-9])2(?:타임|교시)?(?:[^0-9]|$)/.test(compact) || /[월화수목금토일]2/.test(compact)) groups.add(2);
  if (groups.size) return groups;

  const arriveMinutes = parseHHMM(row?.querySelector?.('.arriveLabel')?.textContent);
  if (arriveMinutes == null) return groups;
  groups.add(arriveMinutes >= OPS_SLOT_BOUNDARY_MINUTES ? 2 : 1);
  return groups;
}

function workMinutesBetween(start, end, breaks = []) {
  const from = Math.max(0, start);
  const to = Math.max(from, end);
  let total = Math.max(0, to - from);

  breaks.forEach((breakTime) => {
    const overlap = Math.max(0, Math.min(to, breakTime.end) - Math.max(from, breakTime.start));
    total -= overlap;
  });

  return Math.max(0, total);
}

function remainingWorkMinutes(slot, now = new Date()) {
  const nowMinutes = minutesOfDay(now);
  const slotStart = OPS_SLOT_START_MINUTES[slot] ?? nowMinutes;
  const slotEnd = OPS_SLOT_END_MINUTES[slot] ?? nowMinutes;
  if (nowMinutes >= slotEnd) return 0;
  return workMinutesBetween(Math.max(nowMinutes, slotStart), slotEnd, OPS_BREAKS[slot] || []);
}

function currentSlotRows(slot) {
  return Array.from(document.querySelectorAll('#todayWrap tr[data-sid], #doneWrap tr[data-sid]'))
    .filter(row => row?.dataset?.selfStudy !== '1')
    .filter(row => slotGroupsFromRow(row).has(slot));
}

function renderClock() {
  const el = $('opsNow');
  if (!el) return;
  const d = new Date();
  const yoil = '일월화수목금토'[d.getDay()];
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  el.textContent = `${yyyy}.${mm}.${dd} (${yoil}) ${hh}:${mi}`;
}

function renderMetrics() {
  const slot = currentOpsSlot();
  const rows = currentSlotRows(slot);
  const total = rows.length;
  const completed = rows.filter(row => {
    const left = !!row.closest('#doneWrap');
    const homeworkChecked = row.dataset.hw === '1' || row.querySelector('.hwCheckChk')?.checked;
    return left || homeworkChecked;
  }).length;
  const pending = Math.max(0, total - completed);
  const progress = total ? Math.round((completed / total) * 100) : 0;
  const minutesEach = pending ? (remainingWorkMinutes(slot) / pending) : 0;

  const pendingEl = $('kpiHomeworkPending') || $('kpiDone');
  const minutesEl = $('kpiMinutesPerStudent') || $('kpiAttendance');
  const progEl = $('kpiProgress');
  const progBar = $('kpiProgressBar');
  const focusEl = $('opsFocusValue');
  const focusRing = $('opsFocusRing');
  const title = `${slot}타임 기준`;

  if (pendingEl) pendingEl.textContent = `${pending}명`;
  if (minutesEl) minutesEl.textContent = `${minutesEach.toFixed(1)}분`;
  if (progEl) progEl.textContent = `${progress}%`;
  if (progBar) progBar.style.width = `${progress}%`;
  if (focusEl) focusEl.textContent = `${progress}%`;
  if (focusRing) focusRing.style.setProperty('--p', String(progress));

  [pendingEl, minutesEl, progEl].forEach((el) => {
    const card = el?.closest?.('.kpi-card');
    if (card) card.title = title;
  });
}

function initRailActions() {
  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-ui-action]');
    if (!btn) return;
    const action = btn.getAttribute('data-ui-action');
    if (!action) return;

    switch (action) {
      case 'scroll-today':
        scrollToSection('todaySection');
        break;
      case 'scroll-done':
        scrollToSection('doneSection');
        break;
      case 'scroll-calendar':
        scrollToSection('calendarSection');
        break;
      case 'open-extra':
        clickById('extraBtn');
        break;
      case 'open-absent':
        clickById('absentRegisterBtn');
        break;
      default:
        break;
    }
  });
}

function initMetricWatchers() {
  let raf = 0;
  const schedule = () => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      renderMetrics();
    });
  };

  ['todayWrap', 'doneWrap'].forEach((id) => {
    const target = $(id);
    if (!target) return;
    const obs = new MutationObserver(schedule);
    obs.observe(target, { childList: true, subtree: true, attributes: true });
  });

  document.addEventListener('admin:refresh', schedule);
  document.addEventListener('attendance:updated', schedule);
  document.addEventListener('change', (ev) => {
    if (ev.target?.closest?.('#todayWrap, #doneWrap')) schedule();
  });
  setInterval(schedule, 30 * 1000);

  schedule();
}

export function initAdminUiEnhance() {
  renderClock();
  setInterval(renderClock, 30 * 1000);

  initRailActions();
  initAttendanceLedgerLink();
  initMetricWatchers();
}
