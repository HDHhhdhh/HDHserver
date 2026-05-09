import { $ } from '../core/utils.js';

const DENSITY_KEY = 'adminDensityMode';

function countRows(wrapId) {
  const host = $(wrapId);
  if (!host) return 0;
  return host.querySelectorAll('tr[data-sid]').length;
}

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
  const today = countRows('todayWrap');
  const done = countRows('doneWrap');
  const total = today + done;
  const checked = document.querySelectorAll('#todayWrap .attendChk:checked').length;
  const attended = Math.min(total, checked + done);
  const progress = total ? Math.round((done / total) * 100) : 0;

  const doneEl = $('kpiDone');
  const attEl = $('kpiAttendance');
  const progEl = $('kpiProgress');
  const progBar = $('kpiProgressBar');
  const focusEl = $('opsFocusValue');
  const focusRing = $('opsFocusRing');

  if (doneEl) doneEl.textContent = `${done}명`;
  if (attEl) attEl.textContent = `${attended}명`;
  if (progEl) progEl.textContent = `${progress}%`;
  if (progBar) progBar.style.width = `${progress}%`;
  if (focusEl) focusEl.textContent = `${progress}%`;
  if (focusRing) focusRing.style.setProperty('--p', String(progress));
}

function initDensityToggle() {
  const btn = $('densityToggle');
  if (!btn) return;

  function apply(mode) {
    const m = mode === 'compact' ? 'compact' : 'cozy';
    document.body.dataset.density = m;
    btn.textContent = m === 'compact' ? '여백 보기' : '컴팩트 보기';
    try {
      localStorage.setItem(DENSITY_KEY, m);
    } catch { /* ignore */ }
  }

  let initial = 'cozy';
  try {
    initial = localStorage.getItem(DENSITY_KEY) || 'cozy';
  } catch { /* ignore */ }
  apply(initial);

  btn.addEventListener('click', () => {
    const next = document.body.dataset.density === 'compact' ? 'cozy' : 'compact';
    apply(next);
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

  schedule();
}

export function initAdminUiEnhance() {
  renderClock();
  setInterval(renderClock, 30 * 1000);

  initDensityToggle();
  initRailActions();
  initMetricWatchers();
}
