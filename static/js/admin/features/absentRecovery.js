// /js/admin/features/absentRecovery.js
// 결석 복구(해제) 모달 — 안전 가드(엘리먼트 없으면 패스)
import { $, toast } from '../core/utils.js';
import { getAdminDate } from '../core/adminDate.js';
import { state } from '../core/state.js';

const CT = { 'Content-Type': 'application/json' };
let recoverTriggerDelegated = false;

function ensureModal() {
  if (document.getElementById('absentRecoverModal')) return;

  document.body.insertAdjacentHTML('beforeend', `
    <div id="absentRecoverModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9999;align-items:center;justify-content:center">
      <div style="background:#fff;border-radius:12px;padding:14px;width:360px;max-height:80vh;overflow:auto">
        <h3 style="margin:0 0 10px 0">결석 복구</h3>
        <div id="arDateWrap" style="margin-bottom:8px">
          <label style="font-size:12px;opacity:.7">날짜</label>
          <input type="date" id="arDate" style="height:34px;border:1px solid #e5e7eb;border-radius:8px;padding:0 8px;width:100%">
        </div>
        <div id="arList" style="border:1px solid #e5e7eb;border-radius:10px;padding:8px;min-height:80px;max-height:300px;overflow:auto"></div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button id="arRestore" style="height:34px;padding:0 12px;border:none;border-radius:8px;background:#10b981;color:#fff;font-weight:800">복구</button>
          <button id="arClose" style="height:34px;padding:0 12px;border:1px solid #e5e7eb;border-radius:8px;background:#fff">닫기</button>
        </div>
      </div>
    </div>
  `);
}

function openModal(dateStr) {
  const modal = document.getElementById('absentRecoverModal');
  const dateInput = document.getElementById('arDate');
  const list = document.getElementById('arList');
  if (!modal || !dateInput || !list) return; // 안전 가드

  dateInput.value = dateStr;
  // 현재 날짜의 결석 명단 불러와 렌더
  renderFor(dateStr);
  modal.style.display = 'flex';
}

function closeModal() {
  const modal = document.getElementById('absentRecoverModal');
  if (modal) modal.style.display = 'none';
}

function renderFor(dateStr) {
  const list = document.getElementById('arList');
  if (!list) return;

  const ids = (state.absentByDate?.[dateStr] || []).map(String);
  const studs = (state.students || [])
    .filter(s => ids.includes(String(s.id)))
    .sort((a, b) => String(a.name).localeCompare(String(b.name), 'ko'));

  if (!studs.length) {
    list.innerHTML = `<div style="opacity:.6">결석한 학생이 없습니다.</div>`;
    list.dataset.sids = '[]';
    return;
  }

  list.innerHTML = studs.map(s => `
    <label style="display:flex;align-items:center;gap:8px;padding:6px 4px;border-bottom:1px dashed #e5e7eb">
      <input type="checkbox" class="ar-chk" value="${s.id}">
      <div style="flex:1">
        <div style="font-weight:700">${s.name}</div>
        <div style="font-size:12px;opacity:.65">${s.curriculum || ''}${s.subCurriculum ? ' · '+s.subCurriculum : ''}</div>
      </div>
    </label>
  `).join('');

  list.dataset.sids = JSON.stringify(studs.map(s => String(s.id)));
}

async function restoreSelected() {
  const modal = document.getElementById('absentRecoverModal');
  const dateInput = document.getElementById('arDate');
  const list = document.getElementById('arList');
  if (!modal || !dateInput || !list) return;

  const dateStr = dateInput.value;
  const checks = Array.from(list.querySelectorAll('.ar-chk:checked'));
  if (!checks.length) { alert('복구할 학생을 선택하세요.'); return; }

  // 상태 반영: by_date / by_student 모두에서 제거
  const byDate = { ...(state.absentByDate || {}) };
  const byStu = { ...(state.absences || {}) };

  const set = new Set((byDate[dateStr] || []).map(String));
  const removed = [];
  for (const chk of checks) {
    const sid = String(chk.value);
    if (set.has(sid)) { set.delete(sid); removed.push(sid); }
    if (byStu[sid] === dateStr) delete byStu[sid];
  }
  byDate[dateStr] = Array.from(set);
  state.absentByDate = byDate;
  state.absences = byStu;

  try {
    await fetch('/api/absent', {
      method: 'POST', headers: CT,
      body: JSON.stringify({ by_date: byDate, by_student: byStu })
    });
    toast('결석 복구됨');
    // 리스트 갱신
    renderFor(dateStr);
    // 오늘표/달력 갱신
    document.dispatchEvent(new CustomEvent('admin:refresh'));
    if (typeof window.recalcCalendarCounts === 'function') window.recalcCalendarCounts();
  } catch (e) {
    console.error(e);
    alert('복구 저장 실패');
  }
}

// ─────────────────────────────────────
// Public API
// ─────────────────────────────────────
export function initAbsentRecovery() {
  // 🔒 페이지에 트리거 버튼이 없으면 조용히 패스
  const trigger = document.getElementById('absentRecoverBtn');
  if (!trigger) return;

  ensureModal();

  // 안전한 1회 바인딩
  const wire = (el, fn) => {
    if (!el || el._wired) return;
    el._wired = true;
    fn();
  };

  if (!recoverTriggerDelegated) {
    recoverTriggerDelegated = true;
    document.addEventListener('click', (e) => {
      if (!e.target.closest?.('#absentRecoverBtn')) return;
      e.preventDefault();
      openModal(getAdminDate());
    });
  }

  const modal = document.getElementById('absentRecoverModal');
  const closeBtn = document.getElementById('arClose');
  const restoreBtn = document.getElementById('arRestore');
  const dateInput = document.getElementById('arDate');

  wire(closeBtn, () => closeBtn.addEventListener('click', closeModal));
  wire(restoreBtn, () => restoreBtn.addEventListener('click', restoreSelected));
  wire(dateInput, () => dateInput.addEventListener('change', (e) => renderFor(e.target.value)));

  // 배경 클릭 닫기
  if (modal && !modal._bgWired) {
    modal._bgWired = true;
    modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
  }
}
