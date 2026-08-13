// /js/admin/features/absentRecovery.js
// 결석 복구(해제) 모달 — 안전 가드(엘리먼트 없으면 패스)
import { $, toast } from '../core/utils.js';
import { getAdminDate } from '../core/adminDate.js';
import { state } from '../core/state.js';
import { ensureOk, fetchJsonChecked, sendJson } from '../../shared/api.js';
import { clearTodayOrder } from './today.state.js';

let recoverTriggerDelegated = false;

function objectMap(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function normalizeAbsentByDateMap(value) {
  const out = {};
  for (const [date, ids] of Object.entries(objectMap(value))) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(date))) continue;
    const unique = new Set((Array.isArray(ids) ? ids : []).map(id => String(id).trim()).filter(Boolean));
    out[date] = Array.from(unique);
  }
  return out;
}

function normalizeAbsencesByStudent(value) {
  const out = {};
  for (const [sid, date] of Object.entries(objectMap(value))) {
    const sidKey = String(sid).trim();
    const dateKey = String(date || '').trim();
    if (sidKey && /^\d{4}-\d{2}-\d{2}$/.test(dateKey)) out[sidKey] = dateKey;
  }
  return out;
}

function normalizeAbsentSlotMap(value) {
  const out = {};
  for (const [date, sidMap] of Object.entries(objectMap(value))) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(date))) continue;
    const rows = {};
    for (const [sid, rawSlots] of Object.entries(objectMap(sidMap))) {
      const sidKey = String(sid).trim();
      const values = Array.isArray(rawSlots) ? rawSlots : [rawSlots];
      const slots = Array.from(new Set(values
        .map(value => parseInt(value, 10))
        .filter(slot => slot === 1 || slot === 2)))
        .sort((a, b) => a - b);
      if (sidKey && slots.length) rows[sidKey] = slots;
    }
    if (Object.keys(rows).length) out[date] = rows;
  }
  return out;
}

function applyAbsentPayload(payload) {
  if (!payload || typeof payload !== 'object'
    || !payload.by_date || typeof payload.by_date !== 'object'
    || !payload.by_student || typeof payload.by_student !== 'object'
    || !payload.by_slot || typeof payload.by_slot !== 'object') {
    throw new Error('결석 복구 응답 형식이 올바르지 않습니다.');
  }

  state.absentByDate = normalizeAbsentByDateMap(payload.by_date);
  state.absences = normalizeAbsencesByStudent(payload.by_student);
  state.absentSlotsByDate = normalizeAbsentSlotMap(payload.by_slot);

  window.state = window.state || state;
  window.state.absentByDate = state.absentByDate;
  window.state.absences = state.absences;
  window.state.absentSlotsByDate = state.absentSlotsByDate;
  window.absentByDate = state.absentByDate;
  window.absences = state.absences;
  window.absentSlotsByDate = state.absentSlotsByDate;
}

export function buildRecoveredAbsencePayload(source, dateRaw, recoveredIds) {
  const dateKey = String(dateRaw || '').trim();
  const recovered = new Set((Array.isArray(recoveredIds) ? recoveredIds : [])
    .map(sid => String(sid).trim())
    .filter(Boolean));

  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateKey)) {
    throw new Error('결석 복구 날짜가 올바르지 않습니다.');
  }
  if (!recovered.size) {
    throw new Error('복구할 학생이 없습니다.');
  }

  const byDate = {};
  for (const [date, ids] of Object.entries(objectMap(source?.by_date))) {
    byDate[date] = Array.isArray(ids) ? [...ids] : [];
  }
  byDate[dateKey] = (byDate[dateKey] || []).filter(sid => !recovered.has(String(sid).trim()));

  const byStudent = { ...objectMap(source?.by_student) };
  for (const sid of recovered) {
    if (String(byStudent[sid] || '') === dateKey) delete byStudent[sid];
  }

  const bySlot = {};
  for (const [date, sidMap] of Object.entries(objectMap(source?.by_slot))) {
    const rows = {};
    for (const [sid, slots] of Object.entries(objectMap(sidMap))) {
      rows[sid] = Array.isArray(slots) ? [...slots] : slots;
    }
    bySlot[date] = rows;
  }
  if (bySlot[dateKey]) {
    for (const sid of recovered) delete bySlot[dateKey][sid];
    if (!Object.keys(bySlot[dateKey]).length) delete bySlot[dateKey];
  }

  return { by_date: byDate, by_student: byStudent, by_slot: bySlot };
}

async function recoverAbsentRemote(dateKey, recoveredIds) {
  try {
    const response = await sendJson('/api/absent/recover', {
      date: dateKey,
      sids: recoveredIds,
    }, {
      credentials: 'same-origin',
    });
    await ensureOk(response, 'absence recovery save');
    return await response.json();
  } catch (saveError) {
    // A lost response can happen after the atomic server mutation committed.
    // Re-read the canonical maps before reporting failure; the operation is
    // idempotent, so the user may also retry safely if reconciliation fails.
    try {
      const latest = await fetchJsonChecked('/api/absent', 'absence recovery reconciliation', {
        cache: 'no-store',
        credentials: 'same-origin',
      });
      const byDate = objectMap(latest?.by_date);
      const byStudent = objectMap(latest?.by_student);
      const bySlot = objectMap(latest?.by_slot);
      if (latest?.by_date && latest?.by_student && latest?.by_slot) {
        const selected = new Set(recoveredIds.map(String));
        const dateIds = Array.isArray(byDate[dateKey]) ? byDate[dateKey].map(String) : [];
        const recovered = [...selected].every(sid => (
          !dateIds.includes(sid)
          && String(byStudent[sid] || '') !== dateKey
          && !Object.prototype.hasOwnProperty.call(objectMap(bySlot[dateKey]), sid)
        ));
        if (recovered) return latest;
      }
    } catch { /* keep the original save error */ }
    throw saveError;
  }
}

export async function recoverAbsencesForDate(dateRaw, recoveredIds, dependencies = {}) {
  const dateKey = String(dateRaw || '').trim();
  const recovered = Array.from(new Set((Array.isArray(recoveredIds) ? recoveredIds : [])
    .map(sid => String(sid).trim())
    .filter(Boolean)));
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateKey)) {
    throw new Error('결석 복구 날짜가 올바르지 않습니다.');
  }
  if (!recovered.length) {
    throw new Error('복구할 학생이 없습니다.');
  }

  const recoverRemote = dependencies.recoverRemote || recoverAbsentRemote;
  const clearOrder = dependencies.clearOrder || clearTodayOrder;

  const saved = await recoverRemote(dateKey, recovered);

  let orderReset = true;
  try {
    await clearOrder(dateKey);
  } catch (orderError) {
    orderReset = false;
    // 결석 저장은 이미 완료됐다. 수동 순서 초기화 실패를 저장 실패로
    // 오인하지 않고, 강제 새로고침으로 서버의 결석 상태부터 수렴시킨다.
    console.warn('[absence recovery] today order reset failed:', orderError);
  }
  return { saved, orderReset };
}

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
  const restoreBtn = document.getElementById('arRestore');
  if (!modal || !dateInput || !list) return;

  const dateStr = dateInput.value;
  const checks = Array.from(list.querySelectorAll('.ar-chk:checked'));
  if (!checks.length) { alert('복구할 학생을 선택하세요.'); return; }
  const recoveredIds = checks.map(chk => String(chk.value)).filter(Boolean);
  if (restoreBtn) restoreBtn.disabled = true;

  try {
    const { saved, orderReset } = await recoverAbsencesForDate(dateStr, recoveredIds);
    applyAbsentPayload(saved);
    toast(orderReset ? '결석 복구됨' : '결석은 복구됐지만 오늘표 순서 초기화 실패');
    if (dateInput.value === dateStr) renderFor(dateStr);
    document.dispatchEvent(new CustomEvent('attendance:updated'));
    document.dispatchEvent(new CustomEvent('admin:refresh', {
      detail: { force: true, forceDatePayloads: true },
    }));
    if (typeof window.recalcCalendarCounts === 'function') window.recalcCalendarCounts();
  } catch (e) {
    console.error(e);
    alert('복구 저장 실패');
  } finally {
    if (restoreBtn) restoreBtn.disabled = false;
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
