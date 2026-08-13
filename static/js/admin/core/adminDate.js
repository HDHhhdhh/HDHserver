// /js/admin/core/adminDate.js
// ✅ admin에서 "가상 오늘" 날짜를 선택/저장/방송하는 전역 날짜 컨텍스트
// - sessionStorage 저장: adminSelectedDate
// - 이벤트: admin:date-change (detail: { dateStr })

const LS_KEY = 'adminSelectedDate';
let inMemorySelectedDate = null;

function isValidAdminDate(value) {
  if (typeof value !== 'string') return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < 1000 || year > 9998 || month < 1 || month > 12 || day < 1) return false;

  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= daysInMonth[month - 1];
}

function todayISO() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

export function getRealToday() {
  return todayISO();
}

export function parseAdminDateLocal(dateStr) {
  const value = String(dateStr || '').trim();
  if (!isValidAdminDate(value)) return null;
  const [year, month, day] = value.split('-').map(Number);
  const parsed = new Date(0);
  parsed.setHours(12, 0, 0, 0);
  parsed.setFullYear(year, month - 1, day);
  return parsed;
}

export function getAdminDate() {
  if (isValidAdminDate(inMemorySelectedDate)) return inMemorySelectedDate;
  try {
    const v = sessionStorage.getItem(LS_KEY);
    if (isValidAdminDate(v)) return v;
  } catch {}
  return todayISO();
}

export function setAdminDate(dateStr, { silent = false } = {}) {
  const v = String(dateStr || '').trim();
  if (!isValidAdminDate(v)) return;

  let stored = false;
  try {
    sessionStorage.setItem(LS_KEY, v);
    stored = true;
  } catch {}
  inMemorySelectedDate = stored ? null : v;

  if (!silent) {
    document.dispatchEvent(new CustomEvent('admin:date-change', { detail: { dateStr: v } }));
  }
}

function shiftDays(dateStr, deltaDays) {
  if (!isValidAdminDate(dateStr)) return todayISO();
  const [year, month, day] = dateStr.split('-').map(Number);
  const d = new Date(0);
  d.setUTCHours(12, 0, 0, 0);
  d.setUTCFullYear(year, month - 1, day + deltaDays);
  const yyyy = String(d.getUTCFullYear()).padStart(4, '0');
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(d.getUTCDate()).padStart(2, '0');
  const shifted = `${yyyy}-${mm}-${dd}`;
  return isValidAdminDate(shifted) ? shifted : dateStr;
}

function ensureStyles() {
  if (document.getElementById('adminDateBarStyles')) return;
  const s = document.createElement('style');
  s.id = 'adminDateBarStyles';
  s.textContent = `
  #adminDateMount .adb-wrap{
    width:100%;
    height:100%;
    min-height:0;
    box-sizing:border-box;
    display:flex;
    flex-direction:column;
    justify-content:center;
    align-items:center;
    gap:9px;
    padding:12px 14px;
    border-radius:18px;
    border:1px solid var(--line-strong, rgba(148,163,184,.45));
    background:transparent;
    box-shadow:none;
  }
  body.dark #adminDateMount .adb-wrap{
    background:transparent;
    border-color:rgba(148,163,184,.5);
    box-shadow:none;
  }
  #adminDateMount .adb-nav-row{
    width:100%;
    display:grid;
    grid-template-columns:54px minmax(84px,1fr) 54px;
    align-items:center;
    gap:8px;
  }
  #adminDateMount .adb-btn{
    height:54px;
    border-radius:15px;
    border:1px solid var(--line-strong, rgba(148,163,184,.45));
    background:var(--card, #ffffff);
    color:var(--ink, #0f172a);
    cursor:pointer;
    display:inline-flex;
    align-items:center;
    justify-content:center;
    box-sizing:border-box;
    font-weight:900;
    letter-spacing:0;
    box-shadow:none;
  }
  #adminDateMount .adb-btn:hover{ filter:brightness(.98); transform:translateY(-1px); }
  #adminDateMount .adb-icon-btn{
    padding:0;
    font-size:30px;
    line-height:1;
  }
  #adminDateMount .adb-today-btn{
    min-width:0;
    padding:0 16px;
    font-size:21px;
    line-height:1;
  }
  #adminDateMount .adb-date-display{
    width:min(100%, 220px);
    height:46px;
    min-width:0;
    box-sizing:border-box;
    padding:0 10px;
    border:1px solid var(--line-strong, rgba(148,163,184,.45));
    border-radius:12px;
    background:var(--card, #ffffff);
    color:var(--ink, #0f172a);
    font-family:inherit;
    font-size:18px;
    line-height:1;
    font-weight:800;
    letter-spacing:0;
    font-variant-numeric:tabular-nums;
    text-align:center;
    color-scheme:light;
    cursor:pointer;
  }
  #adminDateMount .adb-date-display::-webkit-calendar-picker-indicator{
    cursor:pointer;
    opacity:.78;
  }
  #adminDateMount .adb-date-display:focus-visible{
    outline:3px solid color-mix(in srgb, var(--brand, #2563eb) 34%, transparent);
    outline-offset:2px;
  }
  body.dark #adminDateMount .adb-btn,
  body.dark #adminDateMount .adb-date-display{ color:#e2e8f0; }
  body.dark #adminDateMount .adb-btn{ background:rgba(2,6,23,.64); }
  body.dark #adminDateMount .adb-date-display{
    background:rgba(2,6,23,.64);
    color-scheme:dark;
  }
  @media (max-width:760px){
    #adminDateMount .adb-wrap{ min-height:104px; padding:12px; border-radius:16px; }
    #adminDateMount .adb-nav-row{ grid-template-columns:44px minmax(72px,1fr) 44px; gap:8px; }
    #adminDateMount .adb-btn{ height:44px; border-radius:13px; }
    #adminDateMount .adb-icon-btn{ font-size:25px; }
    #adminDateMount .adb-today-btn{ font-size:18px; }
    #adminDateMount .adb-date-display{ width:100%; height:44px; font-size:16px; }
  }
  @media (max-width:480px){
    body.admin #adminDateMount .adb-date-display{
      padding:0 4px;
      font-size:14px;
      letter-spacing:-.02em;
    }
    body.admin #adminDateMount .adb-date-display::-webkit-calendar-picker-indicator{
      width:18px;
      height:18px;
      margin:0;
      padding:0;
    }
  }
  `;
  document.head.appendChild(s);
}

/**
 * ✅ 날짜 바 마운트
 * - 기본 마운트 위치: #adminDateMount 있으면 거기
 * - 없으면 header.topbar 아래(없으면 body 맨 위)
 */
function syncHeroDatePosition(host) {
  const panel = host?.closest?.('.hero-panel');
  const roster = document.getElementById('exportRoster');
  const kpis = panel?.querySelector?.('.hero-kpis');
  if (!panel || !host || !roster || !kpis) return;

  if (host.__heroDatePositionCleanup) {
    host.__heroDatePositionCleanup();
  }

  let rafId = 0;
  let observer = null;

  const update = () => {
    rafId = 0;
    if (window.matchMedia?.('(max-width: 1320px)')?.matches) {
      panel.classList.remove('is-date-centered');
      panel.style.removeProperty('--hero-date-left');
      panel.style.removeProperty('--hero-date-top');
      return;
    }

    const panelRect = panel.getBoundingClientRect();
    const rosterRect = roster.getBoundingClientRect();
    const kpisRect = kpis.getBoundingClientRect();
    const hostRect = host.getBoundingClientRect();
    if (!panelRect.width || !panelRect.height) return;

    const gap = kpisRect.left - rosterRect.right;
    if (gap < hostRect.width + 16) {
      panel.classList.remove('is-date-centered');
      panel.style.removeProperty('--hero-date-left');
      panel.style.removeProperty('--hero-date-top');
      return;
    }

    const panelStyle = getComputedStyle(panel);
    const originLeft =
      panelRect.left +
      (parseFloat(panelStyle.borderLeftWidth) || 0) +
      (parseFloat(panelStyle.paddingLeft) || 0);
    const originTop =
      panelRect.top +
      (parseFloat(panelStyle.borderTopWidth) || 0) +
      (parseFloat(panelStyle.paddingTop) || 0);
    const centerX = ((rosterRect.right + kpisRect.left) / 2) - originLeft;
    const centerY = (panelRect.top + (panelRect.height / 2)) - originTop;
    panel.classList.add('is-date-centered');
    panel.style.setProperty('--hero-date-left', `${Math.round(centerX)}px`);
    panel.style.setProperty('--hero-date-top', `${Math.round(centerY)}px`);
  };

  const schedule = () => {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(update);
  };

  schedule();
  window.addEventListener('resize', schedule, { passive: true });
  if (window.ResizeObserver) {
    observer = new ResizeObserver(schedule);
    [panel, roster, kpis, host].forEach((el) => observer.observe(el));
  }

  host.__heroDatePositionCleanup = () => {
    if (rafId) cancelAnimationFrame(rafId);
    window.removeEventListener('resize', schedule);
    observer?.disconnect?.();
  };
}

export function initAdminDateBar({ mountId = 'adminDateMount' } = {}) {
  ensureStyles();

  let host = document.getElementById(mountId);
  if (!host) {
    host = document.createElement('div');
    host.id = mountId;
    const hdr = document.querySelector('header.topbar') || document.body;
    hdr.insertAdjacentElement('afterend', host);
  }

  host.innerHTML = `
    <div class="adb-wrap" aria-label="기준 날짜">
      <div class="adb-nav-row">
        <button class="adb-btn adb-icon-btn" id="adb_prev" type="button" title="하루 전" aria-label="하루 전">‹</button>
        <button class="adb-btn adb-today-btn" id="adb_today" type="button">오늘</button>
        <button class="adb-btn adb-icon-btn" id="adb_next" type="button" title="하루 후" aria-label="하루 후">›</button>
      </div>
      <input class="adb-date-display" id="adb_date_display" type="date"
             min="1000-01-01" max="9998-12-31" aria-label="기준 날짜 직접 선택">
    </div>
  `;
  syncHeroDatePosition(host);

  const $ = (id) => document.getElementById(id);
  const dateDisplay = $('adb_date_display');
  const prev = $('adb_prev');
  const next = $('adb_next');
  const btnToday = $('adb_today');

  const syncDisplay = (dateStr = getAdminDate()) => {
    if (!dateDisplay || !isValidAdminDate(dateStr)) return;
    dateDisplay.value = dateStr;
    dateDisplay.title = dateStr;
  };

  syncDisplay();

  prev.addEventListener('click', () => {
    const d = shiftDays(getAdminDate(), -1);
    syncDisplay(d);
    setAdminDate(d);
  });

  next.addEventListener('click', () => {
    const d = shiftDays(getAdminDate(), +1);
    syncDisplay(d);
    setAdminDate(d);
  });

  btnToday.addEventListener('click', () => {
    const d = todayISO();
    syncDisplay(d);
    setAdminDate(d);
  });

  dateDisplay.addEventListener('change', () => {
    const current = getAdminDate();
    const selected = String(dateDisplay.value || '').trim();
    if (!isValidAdminDate(selected) || selected === current) {
      syncDisplay(current);
      return;
    }
    setAdminDate(selected);
  });

  // 다른 곳에서 날짜 바뀌면 표시도 동기화
  document.addEventListener('admin:date-change', (e) => {
    const d = e?.detail?.dateStr;
    if (isValidAdminDate(d)) syncDisplay(d);
  });
}
