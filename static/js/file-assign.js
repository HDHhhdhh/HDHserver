// /js/file-assign.js  (통합판)
// 기능: 오른쪽 배정 패널 하나로 통합. 예전 파일은 제거해도 됨.
//
// - 커리큘럼/세부 커리/레벨(복수)로 학생 필터
// - 자료 다중 선택 후 일괄 배정 (중복 머지)
// - 검색, 전체선택/해제
// - 기존 여러 id/data-속성 셀렉터를 모두 지원(마크업이 달라도 작동)
// - 패널에 요소가 없으면 최소 UI를 자동 생성

// ------------------------------ 공통 헬퍼 ------------------------------
const $  = (s, p=document) => p.querySelector(s);
const $$ = (s, p=document) => Array.from(p.querySelectorAll(s));

async function jget(url) {
  const r = await fetch(url, { cache:'no-store' });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function jpost(url, body) {
  const r = await fetch(url, {
    method:'POST',
    headers:{ 'Content-Type':'application/json' },
    body: JSON.stringify(body||{})
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json().catch(()=> ({}));
}
const byNameKo = (a,b)=> String(a.name||'').localeCompare(String(b.name||''),'ko');
const uniq = arr => Array.from(new Set(arr));

// 여러 마크업을 호환하기 위해 가능한 셀렉터 후보를 순차 시도
function pick(...sels) {
  for (const s of sels) {
    const el = typeof s==='string' ? $(s) : s;
    if (el) return el;
  }
  return null;
}

// ------------------------------ 상태 ------------------------------
const S = {
  students: [],
  materials: {},       // { mid: {title,url,curriculum,...}, ... }
  assigns: {},         // { sid: [mid,...] }
  ui: {}
};

// ------------------------------ UI 찾기/생성 ------------------------------
function ensurePanel() {
  // 패널 루트
  const host =
    pick('#assignPanel','[data-assign-panel]','.fm-assign','.assign-card') ||
    (()=>{ const d=document.createElement('div'); d.id='assignPanel'; document.body.appendChild(d); return d; })();

  // 기본 구조가 없으면 최소 패널을 만들어 넣음
  if (!host.dataset._wired) {
    if (!host.querySelector('[data-assign-cur]')) {
      host.innerHTML = `
        <div class="assign-head" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <div class="title">자료 배정</div>
          <button data-assign-do class="btn primary">배정</button>
        </div>

        <div class="assign-grid">
          <div>
            <label class="lbl">커리큘럼</label>
            <select data-assign-cur class="input"><option value="">(전체)</option></select>
          </div>
          <div>
            <label class="lbl">세부 커리큘럼</label>
            <select data-assign-sub class="input"><option value="">(전체)</option></select>
          </div>
        </div>

        <div style="margin:8px 0">
          <div class="lbl">레벨(복수 선택)</div>
          <div data-assign-lv class="chips"></div>
          <button data-assign-lv-all class="btn" style="margin-top:6px">전체</button>
        </div>

        <div class="box">
          <div class="box-head">
            <div>대상 학생 <span data-assign-stu-count style="opacity:.75">(0명)</span></div>
            <div style="display:flex;gap:6px">
              <button data-assign-stu-all class="btn">전체선택</button>
              <button data-assign-stu-clear class="btn">해제</button>
            </div>
          </div>
          <input data-assign-search placeholder="이름 검색" class="input" style="margin-bottom:6px">
          <div data-assign-stu-list class="list two-col"></div>
        </div>

        <div class="box">
          <div class="box-head">
            <div>배정할 자료</div>
            <div style="display:flex;gap:6px">
              <button data-assign-mat-all class="btn">전체선택</button>
              <button data-assign-mat-clear class="btn">해제</button>
            </div>
          </div>
          <div data-assign-mat-list class="list two-col"></div>
        </div>
      `;
    }
  }

  // 요소 매핑(여러 셀렉터 호환)
  S.ui = {
    host: host,
    curSel:  pick('[data-assign-cur]','#amCur'),
    subSel:  pick('[data-assign-sub]','#amSub'),
    lvWrap:  pick('[data-assign-lv]','#amLvWrap'),
    lvAll:   pick('[data-assign-lv-all]','#amSelAllLv'),
    stuList: pick('[data-assign-stu-list]','#amStuList'),
    stuCnt:  pick('[data-assign-stu-count]','#amStuCount'),
    stuAll:  pick('[data-assign-stu-all]','#amStuAll'),
    stuClr:  pick('[data-assign-stu-clear]','#amStuNone'),
    search:  pick('[data-assign-search]','#amSearch'),

    matList: pick('[data-assign-mat-list]','#amMatList'),
    matAll:  pick('[data-assign-mat-all]','#amMatAll'),
    matClr:  pick('[data-assign-mat-clear]','#amMatNone'),

    doBtn:   pick('[data-assign-do]','#sSave')
  };

  host.dataset._wired = '1';
}

// ------------------------------ 데이터 로드 ------------------------------
async function loadAll() {
  const [students, materials, assigns] = await Promise.all([
    jget('/api/students').catch(()=>[]),
    jget('/api/materials').catch(()=> ({})),
    jget('/api/mat-assign').catch(()=> ({})),
  ]);
  S.students  = Array.isArray(students) ? students.slice().sort(byNameKo) : [];
  S.materials = materials || {};
  S.assigns   = assigns || {};
}

// ------------------------------ 렌더 ------------------------------
function uniqueVals(arr){ return Array.from(new Set(arr.filter(v=>v!=null))).map(v=>String(v)); }

function buildFilters() {
  const curVals = uniqueVals(S.students.map(s => (s.curriculum||'').trim()));
  S.ui.curSel.innerHTML = `<option value="">(전체)</option>` + curVals.map(v=>`<option value="${v}">${v||'(미기입)'}</option>`).join('');

  refreshSub();
  renderLevels();
  renderStudents();
  renderMaterials();
}

function refreshSub() {
  const cur = S.ui.curSel.value || '';
  const pool = cur ? S.students.filter(s => (s.curriculum||'').trim()===cur) : S.students;
  const subVals = uniqueVals(pool.map(s => (s.subCurriculum||'').trim()));
  S.ui.subSel.innerHTML = `<option value="">(전체)</option>` + subVals.map(v=>`<option value="${v}">${v||'(미기입)'}</option>`).join('');
}

function renderLevels() {
  const wrap = S.ui.lvWrap;
  if (!wrap) return;
  const lvList = ['상','중상','중','하','(빈값)'];
  wrap.innerHTML = lvList.map(lv => `
    <label class="chip ${lv==='(빈값)'?'dashed':''}">
      <input type="checkbox" class="lvChk" value="${lv}">
      ${lv}
    </label>`).join('');
}

function currentLevelSet(){
  const chks = $$('.lvChk', S.ui.lvWrap);
  const chosen = chks.filter(c=>c.checked).map(c=>c.value);
  return new Set(chosen);
}

function filteredStudents() {
  const cur = (S.ui.curSel.value||'').trim();
  const sub = (S.ui.subSel.value||'').trim();
  const lvSet = currentLevelSet();
  const keyword = (S.ui.search?.value||'').trim();

  return S.students.filter(s=>{
    if (cur && (String(s.curriculum||'').trim()!==cur)) return false;
    if (sub && (String(s.subCurriculum||'').trim()!==sub)) return false;
    if (lvSet.size>0) {
      const lv = String(s.level||'').trim() || '(빈값)';
      if (!lvSet.has(lv)) return false;
    }
    if (keyword && !String(s.name||'').includes(keyword)) return false;
    return true;
  });
}

function renderStudents() {
  const list = S.ui.stuList; if (!list) return;
  const studs = filteredStudents().sort(byNameKo);

  S.ui.stuCnt && (S.ui.stuCnt.textContent = `(${studs.length}명)`);
  list.innerHTML = studs.map(s=>`
    <label style="display:flex;gap:8px;align-items:center;border:1px solid var(--line);border-radius:8px;padding:6px">
      <input type="checkbox" class="faStu" value="${s.id}">
      <div style="font-size:13px;line-height:1.25">
        <div style="font-weight:700">${s.name}</div>
        <div style="opacity:.65">${s.curriculum||''} ${s.subCurriculum||''} · ${s.level||'-'}</div>
      </div>
    </label>
  `).join('');
}

function renderMaterials() {
  const list = S.ui.matList; if (!list) return;
  const entries = Object.entries(S.materials)
    .map(([id, m]) => ({ id, ...(m||{}) }))
    .sort((a,b)=> Number(a.id)-Number(b.id));

  list.innerHTML = entries.map(m=>`
    <label style="display:flex;gap:8px;align-items:center;border:1px solid var(--line);border-radius:8px;padding:6px">
      <input type="checkbox" class="faMat" value="${m.id}">
      <div style="font-size:13px;line-height:1.25">
        <div style="font-weight:700">${m.title||'(제목없음)'}</div>
        <div style="opacity:.65">${m.curriculum||''}</div>
      </div>
    </label>
  `).join('');
}

// ------------------------------ 동작 ------------------------------
function getChecked(selector) {
  return $$(selector).filter(i=>i.checked).map(i=>String(i.value));
}
function setAll(selector, checked) {
  $$(selector).forEach(i=> i.checked = !!checked);
}

async function doAssign() {
  const sidList = getChecked('.faStu');
  const midList = getChecked('.faMat');

  if (!sidList.length) { alert('대상 학생이 없습니다.'); return; }
  if (!midList.length) { alert('배정할 자료를 선택하세요.'); return; }

  // 병합 저장
  const assigns = { ...(S.assigns||{}) };
  for (const sid of sidList) {
    assigns[sid] = uniq((assigns[sid]||[]).map(String).concat(midList));
  }
  await jpost('/api/mat-assign', assigns);
  S.assigns = assigns;
  alert('배정 완료');
}

// ------------------------------ 이벤트 바인딩 ------------------------------
function bindEvents() {
  S.ui.curSel?.addEventListener('change', ()=>{ refreshSub(); renderStudents(); });
  S.ui.subSel?.addEventListener('change', ()=> renderStudents());
  S.ui.lvAll?.addEventListener('click', ()=>{
    $$('.lvChk', S.ui.lvWrap).forEach(c=> c.checked=true);
    renderStudents();
  });
  S.ui.lvWrap?.addEventListener('change', (e)=>{
    if (e.target.classList.contains('lvChk')) renderStudents();
  });
  S.ui.search?.addEventListener('input', ()=> renderStudents());

  S.ui.stuAll?.addEventListener('click', ()=> setAll('.faStu', true));
  S.ui.stuClr?.addEventListener('click', ()=> setAll('.faStu', false));

  S.ui.matAll?.addEventListener('click', ()=> setAll('.faMat', true));
  S.ui.matClr?.addEventListener('click', ()=> setAll('.faMat', false));

  S.ui.doBtn?.addEventListener('click', ()=> doAssign().catch(e=>alert(e)));
}

// ------------------------------ 부팅 ------------------------------
async function initFileAssign() {
  try {
    ensurePanel();
    await loadAll();
    buildFilters();
    bindEvents();
  } catch (e) {
    console.error(e);
    alert('배정 패널 초기화 실패: '+e);
  }
}

window.addEventListener('DOMContentLoaded', initFileAssign);
export { initFileAssign };
