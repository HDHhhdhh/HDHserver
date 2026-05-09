// static/js/all/features/CloneStudentModal.js
import { loadAll, state } from '../core/state.js';

const CT = { 'Content-Type': 'application/json' };

function el(tag, attrs = {}, html = '') {
  const x = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') x.className = v;
    else if (k === 'style') x.style.cssText = v;
    else if (k.startsWith('data-')) x.setAttribute(k, v);
    else x[k] = v;
  }
  if (html) x.innerHTML = html;
  return x;
}

function getStudents() {
  return (state?.students && state.students.length ? state.students : window.students) || [];
}

function prettySchool(stu) {
  return (stu.school || stu.highSchool || stu.middleSchool || '').trim();
}

function studentLabel(stu) {
  const name = (stu.name || '').trim();
  const school = prettySchool(stu);
  const cur = (stu.curriculum || '').trim();
  return `${name}${school ? ` / ${school}` : ''}${cur ? ` (${cur})` : ''}`;
}

function ensureTopButton(openFn) {
  if (document.getElementById('openCloneStudent')) return;

  // 우선 topbar 안의 nav 옆에 붙이고,
  // 못 찾으면 body 최상단에 떠 있게라도 붙임.
  const topbar = document.querySelector('header.topbar') || document.querySelector('.topbar');
  const nav = topbar?.querySelector('nav') || null;

  const btn = el('button', {
    id: 'openCloneStudent',
    type: 'button',
    class: 'btn',
    style: `
      height:34px;
      padding:0 10px;
      border-radius:10px;
      border:1px solid var(--btn-border,#e5e7eb);
      background:var(--btn-bg,#f8fafc);
      color:var(--btn-fg,#0f172a);
      cursor:pointer;
      font-weight:800;
      font-size:13px;
      white-space:nowrap;
    `
  }, '커리 복제');

  btn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    openFn();
  });

  if (nav) {
    nav.insertAdjacentElement('beforeend', btn);
  } else if (topbar) {
    topbar.insertAdjacentElement('beforeend', btn);
  } else {
    btn.style.position = 'fixed';
    btn.style.right = '16px';
    btn.style.top = '16px';
    btn.style.zIndex = '99999';
    document.body.appendChild(btn);
  }
}

function ensureModal() {
  if (document.getElementById('CloneStudentModal')) return;

  const modal = el('div', {
    id: 'CloneStudentModal',
    style: `
      display:none; position:fixed; inset:0; background:rgba(0,0,0,.45);
      justify-content:center; align-items:center; z-index:99999;
    `,
    'aria-hidden': 'true'
  });

  modal.innerHTML = `
    <div style="
      background:var(--topbar-bg, #fff);
      color:var(--topbar-fg, #0f172a);
      border:1px solid var(--topbar-border, #e5e7eb);
      width:560px; max-width:92vw; border-radius:14px;
      padding:14px; box-shadow:0 12px 32px rgba(0,0,0,.35)
    ">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px">
        <div style="font-weight:900;font-size:16px">커리 복제(학생 선택 → 커리만 변경)</div>
        <button id="csmClose" style="border:none;background:transparent;font-size:20px;cursor:pointer;color:inherit">✕</button>
      </div>

      <div style="margin-top:12px;display:grid;gap:10px">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div>
            <div style="font-size:12px;opacity:.75;margin-bottom:6px">학생 선택</div>
            <select id="csmStu" style="width:100%;height:36px;border-radius:10px;border:1px solid var(--topbar-border,#e5e7eb);background:transparent;color:inherit;padding:0 10px"></select>
          </div>

          <div>
            <div style="font-size:12px;opacity:.75;margin-bottom:6px">새 커리큘럼</div>
            <select id="csmCurr" style="width:100%;height:36px;border-radius:10px;border:1px solid var(--topbar-border,#e5e7eb);background:transparent;color:inherit;padding:0 10px">
              <option value="공수1">공수1</option>
              <option value="공수2">공수2</option>
              <option value="대수">대수</option>
              <option value="미적분1">미적분1</option>
              <option value="미적분2">미적분2</option>
              <option value="기하">기하</option>
              <option value="확통">확통</option>
              <option value="A:Ble">A:Ble</option>
              <option value="APEX">APEX</option>
            </select>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div>
            <div style="font-size:12px;opacity:.75;margin-bottom:6px">요일/시간</div>
            <select id="csmMode" style="width:100%;height:36px;border-radius:10px;border:1px solid var(--topbar-border,#e5e7eb);background:transparent;color:inherit;padding:0 10px">
              <option value="copyDays" selected>그대로 복사</option>
              <option value="emptyDays">비우고 추가</option>
            </select>
          </div>

          <div>
            <div style="font-size:12px;opacity:.75;margin-bottom:6px">복제 안내</div>
            <div id="csmHint" style="height:36px;display:flex;align-items:center;padding:0 10px;border-radius:10px;border:1px dashed var(--topbar-border,#e5e7eb);opacity:.85">
              학생을 고르고 커리를 바꾸면 새 학생 1명이 추가됩니다
            </div>
          </div>
        </div>

        <div>
          <div style="font-size:12px;opacity:.75;margin-bottom:6px">메모(선택)</div>
          <textarea id="csmMemo" rows="3"
            style="width:100%;border-radius:10px;border:1px solid var(--topbar-border,#e5e7eb);
                   background:transparent;color:inherit;padding:10px;resize:vertical"></textarea>
        </div>
      </div>

      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
        <button id="csmCancel" style="height:36px;padding:0 12px;border-radius:10px;border:1px solid var(--topbar-border,#e5e7eb);background:transparent;color:inherit;cursor:pointer">취소</button>
        <button id="csmSubmit" style="height:36px;padding:0 12px;border-radius:10px;border:1px solid var(--btn-border,#e5e7eb);background:var(--btn-bg,#f8fafc);color:var(--btn-fg,#0f172a);cursor:pointer;font-weight:900">추가</button>
      </div>
    </div>
  `;

  document.body.appendChild(modal);
}

function buildCloneBody(stu, nextCurr, mode, memo) {
  const copyDays = mode === 'copyDays';

  const body = {
    name: (stu.name || '').trim(),
    curriculum: nextCurr,
    subCurriculum: (stu.subCurriculum || '').trim(),
    grade: (stu.grade || '').trim(),
    level: (stu.level || '').trim(),

    school: (stu.school || stu.highSchool || stu.middleSchool || '').trim(),
    docUrl: (stu.docUrl || '').trim(),
    subBook1: (stu.subBook1 || '').trim(),
    subBook2: (stu.subBook2 || '').trim(),

    day1: copyDays ? (stu.day1 || '').trim() : '',
    day2: copyDays ? (stu.day2 || '').trim() : '',
    day3: copyDays ? (stu.day3 || '').trim() : '',
    day4: copyDays ? (stu.day4 || '').trim() : '',
    day5: copyDays ? (stu.day5 || '').trim() : '',
  };

  // 서버에 memo 필드 없을 가능성 높아서, 안전하게 docUrl 뒤에만 붙임
  const m = String(memo || '').trim();
  if (m) {
    const base = body.docUrl || '';
    body.docUrl = base ? `${base}  #${m}` : `#${m}`;
  }

  return body;
}

export function initCloneStudentModal({ onCloned } = {}) {
  ensureModal();

  const modal = document.getElementById('CloneStudentModal');
  const selStu = document.getElementById('csmStu');
  const selCurr = document.getElementById('csmCurr');
  const selMode = document.getElementById('csmMode');
  const memo = document.getElementById('csmMemo');
  const btnClose = document.getElementById('csmClose');
  const btnCancel = document.getElementById('csmCancel');
  const btnSubmit = document.getElementById('csmSubmit');

  function close() {
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
  }

  function refillStudents() {
    const studs = getStudents().slice();
    studs.sort((a, b) => studentLabel(a).localeCompare(studentLabel(b), 'ko'));

    selStu.innerHTML = studs.map(s => {
      const id = String(s.id);
      const label = studentLabel(s).replace(/</g, '&lt;').replace(/>/g, '&gt;');
      return `<option value="${id}">${label}</option>`;
    }).join('');

    // 첫 값 기준으로 새 커리 기본값을 맞춰주긴 하는데,
    // 동일 커리 선택하면 submit에서 막음.
    const first = studs[0];
    if (first && selCurr) selCurr.value = String(first.curriculum || '공수1');
  }

  function open() {
    refillStudents();
    if (selMode) selMode.value = 'copyDays';
    if (memo) memo.value = '';
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
  }

  ensureTopButton(open);

  btnClose?.addEventListener('click', close);
  btnCancel?.addEventListener('click', close);
  modal?.addEventListener('click', (e) => { if (e.target === modal) close(); });

  // 학생 선택 바뀌면, 기본 새 커리를 현재 커리로 맞춰놓기(실수 방지)
  selStu?.addEventListener('change', () => {
    const sid = String(selStu.value || '');
    const stu = getStudents().find(s => String(s.id) === sid);
    if (stu && selCurr) selCurr.value = String(stu.curriculum || '공수1');
  });

  btnSubmit?.addEventListener('click', async () => {
    const sid = String(selStu?.value || '').trim();
    if (!sid) return alert('학생을 선택하세요.');

    const stu = getStudents().find(s => String(s.id) === sid);
    if (!stu) return alert('학생 정보를 찾지 못했습니다. 새로고침 후 다시 시도해 주세요.');

    const nextCurr = String(selCurr?.value || '').trim();
    if (!nextCurr) return alert('새 커리큘럼을 선택하세요.');

    const curCurr = String(stu.curriculum || '').trim();
    if (curCurr === nextCurr) return alert('같은 커리큘럼으로는 복제할 필요가 없습니다.');

    const mode = String(selMode?.value || 'copyDays');
    const body = buildCloneBody(stu, nextCurr, mode, memo?.value);

    try {
      btnSubmit.disabled = true;
      btnSubmit.textContent = '추가중...';

      const r = await fetch('/api/add-student', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify(body)
      });
      if (!r.ok) throw new Error(String(r.status));

      close();

      if (typeof onCloned === 'function') {
        await onCloned();
      } else {
        await loadAll();
      }

      alert('추가 완료');
    } catch (e) {
      alert('추가 실패: ' + (e?.message || e));
    } finally {
      btnSubmit.disabled = false;
      btnSubmit.textContent = '추가';
    }
  });

  // 테이블 리렌더/새로 로드돼도 학생 목록 최신 상태 유지
  document.addEventListener('admin:refresh', () => {
    try { refillStudents(); } catch {}
  });
}
