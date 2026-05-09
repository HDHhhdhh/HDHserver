// /js/admin/features/extraModal.js
// 오늘 보강 학생 모달 (요일 슬롯: 월1/월2 ... 토1/토2, 일1/일2) — 라이트/다크 테마 대응
import { $, CT, toast, todayLocalKey } from '../core/utils.js';
import { state } from '../core/state.js';
import { setArriveOverride } from './today.state.js';

// ────────────────────────────────────────────
// (선택) 오늘 순서 캐시 삭제 → 새 보강 추가 시 하단 고정 현상 방지
async function clearTodayOrder(dateStr) {
  try {
    const map = await fetch('/api/today_order', { cache: 'no-store' }).then(r => r.json()).catch(() => ({}));
    if (map && map[dateStr]) {
      delete map[dateStr];
      await fetch('/api/today_order', { method: 'POST', headers: CT, body: JSON.stringify(map) });
    }
  } catch { /* ignore */ }
}

function ensure() {
  if ($('#extraModal')) return;

  document.body.insertAdjacentHTML('beforeend', `
    <div id="extraModal" class="extra-backdrop" style="display:none" aria-modal="true" role="dialog">
      <div class="extra-panel">
        <h3 class="extra-title">오늘 보강 학생</h3>
        <div id="exZone"></div>
        <div class="extra-actions">
          <button type="button" id="exSave"  class="ex-btn primary">저장</button>
          <button type="button" id="exClose" class="ex-btn">닫기</button>
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
    width:360px; max-width:92vw; max-height:80vh; overflow:auto;
    border-radius:12px; padding:14px; box-sizing:border-box;
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
  #extraModal .extra-title{ margin:0 0 8px 0; font-size:16px; font-weight:800 }
  #extraModal .extra-actions{ display:flex; gap:8px; justify-content:flex-end; margin-top:10px }

  /* ── 공통 버튼 ──────────────────────────────────────── */
  #extraModal .ex-btn{
    border:1px solid var(--line, #334155);
    background:color-mix(in oklab, var(--card-dark, #0f172a) 85%, var(--accent,#60a5fa));
    color:var(--text-dark, #e5e7eb);
    border-radius:10px; padding:7px 12px; cursor:pointer; font-weight:600;
  }
  body:not(.dark) #extraModal .ex-btn{
    background:color-mix(in oklab, #ffffff 85%, var(--accent,#2563eb));
    color:var(--text, #0f172a); border-color:var(--line, #e5e7eb);
  }
  #extraModal .ex-btn.primary{
    background:var(--accent,#2563eb); color:#fff; border-color:transparent;
  }

  /* ── 리스트 ────────────────────────────────────────── */
  #exZone{ display:flex; flex-direction:column; gap:6px; }
  #exZone .row{
    display:flex; align-items:center; justify-content:space-between; gap:10px;
    padding:8px 10px; border-radius:12px; border:1px solid var(--line,#334155);
    background:color-mix(in oklab, var(--card-dark,#0f172a) 92%, #0000);
    transition:background .15s ease, border-color .15s ease;
  }
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

  #exZone .row label{ display:flex; align-items:center; gap:8px; cursor:pointer; flex:1; color:inherit }
  #exZone .row small{ opacity:.75; color:inherit }

  #exZone input[type="checkbox"]{
    width:16px; height:16px; accent-color:var(--accent,#2563eb); margin:0;
  }

  /* ── 슬롯 버튼(요일1·요일2) ─────────────────────────── */
  #exZone .slot-box{ display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end }
  #exZone .slot-btn{
    min-width:42px; height:34px; padding:0 10px; border-radius:10px; cursor:pointer; font-weight:900;
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
  `;
  document.head.appendChild(s);
}

export function initExtraModal() {
  ensure();

  const exModal = $('extraModal');
  const exZone = $('exZone');
  const btn = $('extraBtn');
  if (!btn) return;

  // 유틸
  const WCHR = '일월화수목금토';
  const yoilChar = (dateStr) => WCHR[new Date(dateStr).getDay()];
  const slotLabel = (dateStr, n) => `${yoilChar(dateStr)}${n}`;

  // ✅ 이제 슬롯은 전 요일 공통 1,2
  const SLOT_NUMS = [1, 2];
  const ARRIVE_BY_SLOT = { 1: '13:00', 2: '18:00' };

  // 최신 slots 로드(엔드포인트명은 유지)
  async function loadDaySlots() {
    try { return await fetch('/api/weekend-slots', { cache: 'no-store' }).then(r => r.json()); }
    catch { return {}; }
  }

  // 열기
  btn.addEventListener('click', async () => {
    const today = todayLocalKey();

    const slotMap = await loadDaySlots();
    const perDay = slotMap[today] || {};

    const checked = (state.extra[today] || []).map(String);

    const sorted = (state.students || []).slice()
      .sort((a, b) => String(a.name).localeCompare(String(b.name), 'ko'));

    exZone.innerHTML = sorted.map(s => {
      const sid = String(s.id);
      const isOn = checked.includes(sid);

      const raw = perDay[sid];
      const slots = Array.isArray(raw) ? raw.map(Number) : Number.isInteger(raw) ? [raw] : [];

      const slotBox = `
        <div class="slot-box" aria-label="슬롯 선택">
          ${SLOT_NUMS.map(n => `
            <button type="button"
                    class="slot-btn ${slots.includes(n) ? 'on' : ''}"
                    data-n="${n}"
                    title="${slotLabel(today, n)}">
              ${slotLabel(today, n)}
            </button>
          `).join('')}
        </div>`;

      return `
        <div class="row ${isOn ? 'on' : ''}" data-sid="${sid}">
          <label>
            <input type="checkbox" class="chk-sid" ${isOn ? 'checked' : ''}>
            <span>${s.name}</span>
            <small>${s.curriculum || ''}${s.subCurriculum ? ' · ' + s.subCurriculum : ''}</small>
          </label>
          ${slotBox}
        </div>`;
    }).join('');

    exModal.style.display = 'flex';
  });

  // 닫기
  document.body.addEventListener('click', (e) => {
    if (e.target.id === 'exClose' || e.target.id === 'extraModal') exModal.style.display = 'none';
  });

  // 체크박스 변화 → 행 하이라이트 토글
  document.body.addEventListener('change', (e) => {
    const chk = e.target.closest('#exZone .chk-sid'); if (!chk) return;
    const row = chk.closest('.row'); if (!row) return;
    row.classList.toggle('on', chk.checked);
  });

  // 슬롯 버튼 토글(이벤트 위임) — 누르면 체크/행 활성화 자동 ON
  document.body.addEventListener('click', (e) => {
    const b = e.target.closest('#exZone .slot-btn'); if (!b) return;
    const row = b.closest('.row'); if (!row) return;

    b.classList.toggle('on');

    const chk = row.querySelector('.chk-sid');
    if (chk && !chk.checked) {
      chk.checked = true;
      row.classList.add('on');
    }
  });

  // 저장
  $('exSave').addEventListener('click', async () => {
    const today = todayLocalKey();

    // 선택 학생
    const rows = Array.from(document.querySelectorAll('#exZone .row'));
    const selectedRows = rows.filter(r => r.querySelector('.chk-sid')?.checked);
    const selectedIds = selectedRows.map(r => String(r.dataset.sid));

    // 1) 보강 명단 저장
    state.extra[today] = selectedIds;
    await fetch('/api/extra-attend', { method: 'POST', headers: CT, body: JSON.stringify(state.extra) });

    // 2) ✅ 요일 슬롯 저장(1,2)
    let slotMap = {};
    try { slotMap = await fetch('/api/weekend-slots', { cache: 'no-store' }).then(r => r.json()); } catch { }
    const perDay = slotMap[today] || {};

    // 해제된 학생 삭제
    Object.keys(perDay).forEach(sid => { if (!selectedIds.includes(String(sid))) delete perDay[sid]; });

    // 선택된 학생: on 버튼 수집(없으면 [1])
    for (const row of selectedRows) {
      const sid = String(row.dataset.sid);
      const nums = Array.from(row.querySelectorAll('.slot-btn.on'))
        .map(b => parseInt(b.dataset.n, 10))
        .filter(n => SLOT_NUMS.includes(n))
        .sort((a, b) => a - b);
      perDay[sid] = nums.length ? nums : [1];
    }

    slotMap[today] = perDay;
    await fetch('/api/weekend-slots', {
      method: 'POST', headers: CT, body: JSON.stringify({ [today]: perDay })
    });

    // 보강 슬롯에 맞춰 등원시간도 함께 갱신 (1교시=13:00, 2교시=18:00)
    const arrivePatch = {};
    for (const sid of selectedIds) {
      const raw = perDay[sid];
      const slots = Array.isArray(raw)
        ? raw.map(Number).filter(n => SLOT_NUMS.includes(n))
        : (Number.isInteger(raw) && SLOT_NUMS.includes(raw) ? [raw] : []);
      const first = slots.length ? Math.min(...slots) : 1;
      const t = ARRIVE_BY_SLOT[first] || '13:00';
      arrivePatch[sid] = t;
      // today.state 캐시도 같이 갱신해서 즉시 화면 반영
      setArriveOverride(today, sid, t);
    }
    if (Object.keys(arrivePatch).length) {
      await fetch('/arrive-time', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify({ [today]: arrivePatch }),
      });
    }

    // 3) 오늘 사용자 정렬 캐시 초기화 → 자동 정렬 반영
    await clearTodayOrder(today);

    toast('보강 저장');
    exModal.style.display = 'none';
    document.dispatchEvent(new CustomEvent('admin:refresh'));
    if (typeof window.recalcCalendarCounts === 'function') window.recalcCalendarCounts();
  });
}
