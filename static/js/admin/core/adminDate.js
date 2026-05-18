// /js/admin/core/adminDate.js
// ✅ admin에서 "가상 오늘" 날짜를 선택/저장/방송하는 전역 날짜 컨텍스트
// - localStorage 저장: adminSelectedDate
// - 이벤트: admin:date-change (detail: { dateStr })

const LS_KEY = 'adminSelectedDate';

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

export function getAdminDate() {
  try {
    const v = localStorage.getItem(LS_KEY);
    if (v && /^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
  } catch {}
  return todayISO();
}

export function setAdminDate(dateStr, { silent = false } = {}) {
  const v = String(dateStr || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return;

  try { localStorage.setItem(LS_KEY, v); } catch {}

  if (!silent) {
    document.dispatchEvent(new CustomEvent('admin:date-change', { detail: { dateStr: v } }));
  }
}

function shiftDays(dateStr, deltaDays) {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return todayISO();
  d.setDate(d.getDate() + deltaDays);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function ensureStyles() {
  if (document.getElementById('adminDateBarStyles')) return;
  const s = document.createElement('style');
  s.id = 'adminDateBarStyles';
  s.textContent = `
  .adb-wrap{
    display:flex; align-items:center; gap:8px;
    padding:8px 10px; border-radius:10px;
    border:1px solid rgba(148,163,184,.35);
    background:rgba(15,23,42,.04);
    font-size:12px;
    flex-wrap:wrap;
  }
  body.dark .adb-wrap{
    background:rgba(15,23,42,.75);
    border-color:rgba(148,163,184,.5);
  }
  .adb-title{ font-weight:600; opacity:.9; margin-right:2px; }
  .adb-date{ padding:6px 8px; border-radius:8px; border:1px solid rgba(148,163,184,.45); background:#fff; font-size:12px; }
  body.dark .adb-date{ background:rgba(2,6,23,.6); color:#e2e8f0; }
  .adb-btn{
    padding:6px 8px; border-radius:8px;
    border:1px solid rgba(148,163,184,.45);
    background:transparent; cursor:pointer;
    font-size:12px;
  }
  .adb-btn:hover{ filter:brightness(.97); }
  #adb_today{
    height:48px;
    padding:0 12px;
    border-radius:12px;
    font-size:18px;
    font-weight:800;
  }
  body.dark .adb-btn{ color:#e2e8f0; }
  .adb-hint{ opacity:.75; }
  `;
  document.head.appendChild(s);
}

/**
 * ✅ 날짜 바 마운트
 * - 기본 마운트 위치: #adminDateMount 있으면 거기
 * - 없으면 header.topbar 아래(없으면 body 맨 위)
 */
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
    <div class="adb-wrap">
      <span class="adb-title">기준 날짜</span>
      <button class="adb-btn" id="adb_prev" title="하루 전">◀</button>
      <input class="adb-date" id="adb_date" type="date" />
      <button class="adb-btn" id="adb_next" title="하루 후">▶</button>
      <button class="adb-btn" id="adb_today">오늘</button>
      <span class="adb-hint">이 날짜로 오늘표/그래프가 바뀜</span>
    </div>
  `;

  const $ = (id) => document.getElementById(id);
  const input = $('adb_date');
  const prev = $('adb_prev');
  const next = $('adb_next');
  const btnToday = $('adb_today');

  input.value = getAdminDate();

  input.addEventListener('change', () => {
    setAdminDate(input.value);
  });

  prev.addEventListener('click', () => {
    const d = shiftDays(getAdminDate(), -1);
    input.value = d;
    setAdminDate(d);
  });

  next.addEventListener('click', () => {
    const d = shiftDays(getAdminDate(), +1);
    input.value = d;
    setAdminDate(d);
  });

  btnToday.addEventListener('click', () => {
    const d = todayISO();
    input.value = d;
    setAdminDate(d);
  });

  // 다른 곳에서 날짜 바뀌면 input도 동기화
  document.addEventListener('admin:date-change', (e) => {
    const d = e?.detail?.dateStr;
    if (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) input.value = d;
  });
}
