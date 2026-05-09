// /js/admin/features/assignModal.js
// 자료 → 학생 지정(그룹 배정) 모달
// - 커리큘럼/세부커리/레벨(상·중상·중·하)로 대상 학생 필터
// - 자료 다중 선택 → 대상 학생 모두에게 일괄 배정
// - 기존 per-student 배열(state.assigns[sid])을 유지하면서 중복 없이 merge
// - 안전 가드: 페이지에 #matTable 없으면 조용히 패스

import { toast } from '../core/utils.js';
import { state } from '../core/state.js';

let openingMid = null;
const $$ = (id) => document.getElementById(id);

function uniq(arr) { return Array.from(new Set(arr)); }
function byNameKo(a, b) { return String(a.name).localeCompare(String(b.name), 'ko'); }

function ensure() {
  if ($$('stuModal')) return;

  document.body.insertAdjacentHTML('beforeend', `
    <div id="stuModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
         justify-content:center;align-items:center;z-index:9999">
      <div class="am-card">
        <h3 style="margin:0 0 10px 0;font-size:18px">자료 배정</h3>

        <!-- 대상 학생 필터 -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
          <div>
            <label class="am-label">커리큘럼</label>
            <select id="amCur" class="am-input"></select>
          </div>
          <div>
            <label class="am-label">세부 커리큘럼</label>
            <select id="amSub" class="am-input">
              <option value="">(전체)</option>
            </select>
          </div>
        </div>

        <div style="margin-bottom:10px">
          <div class="am-label" style="margin-bottom:6px">레벨(복수 선택)</div>
          <div id="amLvWrap" style="display:flex;gap:8px;flex-wrap:wrap">
            ${['상','중상','중','하'].map(lv => `
              <label class="am-chip">
                <input type="checkbox" class="amLv" value="${lv}"> ${lv}
              </label>`).join('')}
            <label class="am-chip dashed">
              <input type="checkbox" class="amLv" value="(빈값)"> (레벨 미기입)
            </label>
          </div>
        </div>

        <!-- 대상 미리보기 -->
        <div class="am-box" style="margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <div style="font-weight:700">대상 학생 <span id="amStuCount" style="opacity:.7;font-weight:600">(0명)</span></div>
            <button type="button" id="amSelAllLv" class="am-btn">레벨 전체</button>
          </div>
          <div id="amStuList" class="am-list"></div>
        </div>

        <!-- 자료 선택 -->
        <div class="am-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <div style="font-weight:700">배정할 자료</div>
            <div style="display:flex;gap:6px">
              <button type="button" id="amMatAll"  class="am-btn">전체선택</button>
              <button type="button" id="amMatNone" class="am-btn">해제</button>
            </div>
          </div>
          <div id="amMatList" class="am-list"></div>
        </div>

        <div style="text-align:right;margin-top:12px;display:flex;gap:8px;justify-content:flex-end">
          <button id="sSave"  class="am-btn primary">배정</button>
          <button id="sClose" class="am-btn">닫기</button>
        </div>
      </div>
    </div>
  `);

  // ───── 스타일 (라이트 + 다크 모드) ─────
  const s = document.createElement('style');
  s.textContent = `
    .am-card {
      background:#fff; color:#111;
      padding:14px; border-radius:12px;
      max-height:84%; overflow:auto; width:520px;
      box-shadow:0 12px 32px rgba(0,0,0,.28);
    }
    body.dark .am-card {
      background:#1e293b; color:#e5e7eb;
    }

    .am-label { font-size:12px; opacity:.8; display:block; margin-bottom:2px; }
    body.dark .am-label { opacity:.9; }

    .am-input {
      width:100%; height:34px; border:1px solid #e5e7eb; border-radius:8px; padding:0 8px;
      background:#fff; color:#111;
    }
    body.dark .am-input {
      background:#0f172a; border-color:#475569; color:#e5e7eb;
    }

    .am-chip {
      display:inline-flex; align-items:center; gap:6px;
      border:1px solid #e5e7eb; border-radius:999px; padding:4px 10px; cursor:pointer;
      font-size:13px;
    }
    .am-chip.dashed { border-style:dashed; }
    body.dark .am-chip { border-color:#475569; }

    .am-box {
      border:1px solid #e5e7eb; border-radius:10px; padding:8px;
    }
    body.dark .am-box { border-color:#475569; }

    .am-btn {
      border:none; background:#f3f4f6; border-radius:8px; padding:4px 8px; cursor:pointer;
    }
    body.dark .am-btn { background:#334155; color:#e5e7eb; }
    .am-btn.primary { background:#10b981; color:#fff; font-weight:800; }

    .am-list {
      display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
      gap:6px; max-height:220px; overflow:auto;
    }
    .am-list > div {
      border:1px solid #e5e7eb; border-radius:8px; padding:6px;
    }
    body.dark .am-list > div { border-color:#475569; }
  `;
  document.head.appendChild(s);
}

function uniqueVals(arr) {
  return Array.from(new Set(arr.filter(Boolean)));
}

// ⬇⬇⬇ 핵심: 현재 필터 기준의 대상 SID 재계산 함수
function getFilteredSids() {
  const cur = $$('amCur')?.value ?? '';
  const sub = $$('amSub')?.value ?? '';
  const chosenLv = Array.from(document.querySelectorAll('.amLv:checked')).map(i => i.value);

  const studs = (state.students || []).slice().sort(byNameKo).filter(s => {
    if (cur && (String(s.curriculum || '').trim() !== cur)) return false;
    if (sub && (String(s.subCurriculum || '').trim() !== sub)) return false;

    const lv = String(s.level || '').trim();
    if (!chosenLv.length) return true;            // 레벨 미선택 → 커리/세부커리만 필터
    if (lv && chosenLv.includes(lv)) return true; // 지정 레벨 매칭
    if (!lv && chosenLv.includes('(빈값)')) return true; // 레벨 미기입 포함
    return false;
  });

  return studs.map(s => String(s.id));
}

function buildFilters() {
  const students = (state.students || []).slice().sort(byNameKo);

  // 커리/세부커리 옵션
  const curSel = $$('amCur');
  const subSel = $$('amSub');

  const curList = uniqueVals(students.map(s => (s.curriculum || '').trim()));
  curSel.innerHTML = [
    `<option value="">(전체)</option>`,
    ...curList.map(c => `<option value="${c}">${c || '(미기입)'}</option>`)
  ].join('');

  // 세부커리는 커리 선택에 따라 동적 구성
  function refreshSub() {
    const cur = curSel.value;
    const pool = students.filter(s => !cur || (s.curriculum || '').trim() === cur);
    const subList = uniqueVals(pool.map(s => (s.subCurriculum || '').trim()));
    subSel.innerHTML = [`<option value="">(전체)</option>`, ...subList.map(v => `<option value="${v}">${v || '(미기입)'}</option>`)].join('');
  }
  refreshSub();

  curSel.onchange = () => { refreshSub(); renderTargets(); };
  subSel.onchange = renderTargets;

  // 레벨 전체 버튼
  $$('amSelAllLv').onclick = () => {
    document.querySelectorAll('.amLv').forEach(chk => (chk.checked = true));
    renderTargets();
  };

  // 레벨 체크 변화
  document.querySelectorAll('.amLv').forEach(chk => chk.addEventListener('change', renderTargets));

  // 자료 목록
  renderMaterialList();

  // 대상 학생 첫 렌더
  renderTargets();
}

// 자료 목록 표시(체크박스). state.materials는 {id:{title,url,curriculum}} 형식
function renderMaterialList() {
  const box = $$('amMatList');
  const mats = state.materials || {};
  const entries = Object.entries(mats)
    .map(([id, m]) => ({ id, ...(m || {}) }))
    .sort((a, b) => Number(a.id) - Number(b.id));

  box.innerHTML = entries.map(m => `
    <label style="display:flex;align-items:center;gap:8px;border:1px solid #e5e7eb;border-radius:8px;padding:6px">
      <input type="checkbox" class="amMat" value="${m.id}">
      <div style="font-size:13px;line-height:1.3">
        <div style="font-weight:700">${m.title || '(제목없음)'}</div>
        <div style="opacity:.65">${m.curriculum || ''}</div>
      </div>
    </label>
  `).join('');

  // 전체/해제 버튼
  $$('amMatAll').onclick = () => {
    box.querySelectorAll('.amMat').forEach(ch => (ch.checked = true));
  };
  $$('amMatNone').onclick = () => {
    box.querySelectorAll('.amMat').forEach(ch => (ch.checked = false));
  };

  // 특정 자료행에서 열렸다면 해당 자료 미리 체크
  if (openingMid) {
    const el = box.querySelector(`.amMat[value="${openingMid}"]`);
    if (el) el.checked = true;
  }
}

// 필터에 따라 대상 학생 미리보기
function renderTargets() {
  const sids = getFilteredSids();
  const studs = (state.students || []).slice().sort(byNameKo)
    .filter(s => sids.includes(String(s.id)));

  const list = $$('amStuList');
  list.innerHTML = studs.map(s => `
    <div style="border:1px solid #e5e7eb;border-radius:8px;padding:6px">
      <div style="font-weight:700">${s.name}</div>
      <div style="opacity:.65;font-size:12px">${s.curriculum || ''} ${s.subCurriculum || ''} · ${s.level || '-'}</div>
    </div>
  `).join('');

  $$('amStuCount').textContent = `(${studs.length}명)`;
}

// 모달 열기
function openModal(mid /* string|number|null */) {
  openingMid = mid ? String(mid) : null;
  const m = $$('stuModal');
  if (!m) return;

  // 초기화 + 데이터로 채우기
  buildFilters();

  // 특정 자료 체크 반영
  if (openingMid) {
    const t = setTimeout(() => {
      const el = document.querySelector(`.amMat[value="${openingMid}"]`);
      if (el) el.checked = true;
      clearTimeout(t);
    }, 0);
  }

  m.style.display = 'flex';
}

// 모달 닫기
function closeModal() {
  const m = $$('stuModal');
  if (m) m.style.display = 'none';
  openingMid = null;
}

// 실제 저장 로직: 선택 자료들을 "현재 필터 결과" 학생에게만 merge
async function saveAssign() {
  const sids = getFilteredSids(); // ✅ 저장 시 항상 재계산
  const matIds = Array.from(document.querySelectorAll('.amMat:checked')).map(i => String(i.value));

  if (!sids.length) { alert('대상 학생이 없습니다.'); return; }
  if (!matIds.length) { alert('배정할 자료를 선택하세요.'); return; }

  // 필터가 전혀 없으면 전체 배정 경고
  const cur = $$('amCur')?.value ?? '';
  const sub = $$('amSub')?.value ?? '';
  const lvlCnt = document.querySelectorAll('.amLv:checked').length;
  if (!cur && !sub && lvlCnt === 0) {
    const ok = confirm(`필터가 비어있어 전체 학생 ${sids.length}명에게 배정됩니다. 진행할까요?`);
    if (!ok) return;
  }

  // state.assigns: { sid: [mat_id,...] }
  const assigns = state.assigns || {};
  for (const sid of sids) {
    assigns[sid] = uniq([...(assigns[sid] || []).map(String), ...matIds]);
  }
  state.assigns = assigns;

  await fetch('/api/mat-assign', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(assigns)
  });

  toast('배정 완료');
  closeModal();
}

// ──────────────────────────────────────────────
// public API
// ──────────────────────────────────────────────
export function initAssignModal() {
  ensure();

  // 자료 테이블에서 버튼으로 열기 (없으면 패스)
  const table = document.getElementById('matTable');
  if (table) {
    table.addEventListener('click', (e) => {
      const btn = e.target.closest('.asBtn');
      if (!btn) return;
      const tr = btn.closest('tr[data-mid]');
      const mid = tr?.dataset?.mid || null;
      openModal(mid);
    });
  }

  // 닫기
  document.body.addEventListener('click', (e) => {
    if (e.target.id === 'sClose' || e.target.id === 'stuModal') closeModal();
  });

  // 저장
  document.body.addEventListener('click', (e) => {
    if (e.target.id === 'sSave') saveAssign();
  });
}
