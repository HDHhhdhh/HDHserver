// === assign-panel.js (전체 교체) ==================================
// 현재 폴더 파일을 "배정할 자료"로 보여주고, 저장 시 /api/materials에 없으면 자동 등록 후
// 해당 material id들로 /api/mat-assign(state.assigns) 갱신

// 유틸
const $$ = (id) => document.getElementById(id);
const CT = { 'Content-Type': 'application/json' };
const W = window;

// 파일명 정리(앞의 UUID/긴타임스탬프 제거)
function prettyName(name) {
  const base = String(name || '').split('/').pop();
  const s1 = base.replace(/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}[\s_-]*/i, '');
  const s2 = s1.replace(/^[0-9]{13,17}[\s_-]*/, '');
  const s3 = s2.replace(/^[0-9a-z]{20,}[\s_-]*/i, '');
  return s3 || base;
}

// 전역 상태(외부 state가 있으면 그대로 사용)
const state = W.state || (W.state = {});
function byNameKo(a,b){ return String(a.name).localeCompare(String(b.name),'ko'); }

// ─────────────────────────────────────────────────────────────
// 현재 폴더(CUR) 찾기: #curPath 텍스트("/a/b") → "a/b"
// ─────────────────────────────────────────────────────────────
function getCurPath() {
  const el = document.querySelector('#curPath');
  if (!el) return '';
  const raw = (el.textContent || '').trim();
  return raw.startsWith('/') ? raw.slice(1) : raw;
}

// 트리에서 경로에 해당하는 노드 찾기
function findNodeByPath(tree, rel) {
  if (!tree) return null;
  if (!rel) return tree;
  const segs = rel.split('/').filter(Boolean);
  let node = tree;
  for (const s of segs) {
    node = (node.children || []).find(x => x.type === 'dir' && x.name === s);
    if (!node) return null;
  }
  return node;
}

// 현재 폴더의 파일 목록 가져오기 (트리 재조회)
async function listFilesInCurrentFolder() {
  const { tree } = await fetch('/api/fs/tree', { cache:'no-store' }).then(r => r.json());
  const cur = getCurPath();
  const node = findNodeByPath(tree, cur) || tree;
  const files = (node.children || []).filter(x => x.type === 'file')
    .map(x => ({ id: x.path, name: x.name, path: x.path, url: x.url, size: x.size, mtime: x.mtime }))
    .sort(byNameKo);
  return files;
}

// /api/materials 로드
async function loadMaterialsMap() {
  try { return await fetch('/api/materials', { cache:'no-store' }).then(r => r.json()); }
  catch { return {}; }
}

// /api/materials에 해당 파일(url=/files/rel) 이 이미 있나 확인하고 없으면 생성
async function ensureMaterialForPath(relPath, displayTitle) {
  const mats = await loadMaterialsMap();
  const url = `/files/${relPath}`;
  // 이미 있는지 찾기
  for (const [mid, m] of Object.entries(mats)) {
    if ((m?.url) === url) return String(mid);
  }
  // 신규 id 채번(숫자 최대+1)
  const nums = Object.keys(mats).filter(k => /^\d+$/.test(k)).map(k => parseInt(k,10));
  const nextId = String((nums.length ? Math.max(...nums) : 0) + 1);
  mats[nextId] = {
    title: displayTitle || relPath.split('/').pop(),
    url,
    curriculum: '' // 필요시 패널에서 선택한 커리 붙이고 싶으면 여기에 세팅
  };
  await fetch('/api/materials', { method:'POST', headers:CT, body: JSON.stringify(mats) });
  return nextId;
}

// ─────────────────────────────────────────────────────────────
// “배정할 자료” 렌더 (현재 폴더 파일들로 채움)
// ─────────────────────────────────────────────────────────────
async function renderAssignMaterials() {
  const box = $$('amMatList');
  if (!box) return;

  const files = await listFilesInCurrentFolder(); // [{path,name,url,...}]
  if (!files.length) {
    box.innerHTML = `<div style="opacity:.7;padding:6px">현재 폴더에 파일이 없습니다.</div>`;
    return;
  }

  box.innerHTML = files.map(f => `
    <label style="display:flex;align-items:center;gap:8px;border:1px solid var(--line);border-radius:8px;padding:6px">
      <input type="checkbox" class="amMatFs" value="${f.path}" data-title="${prettyName(f.name)}">
      <div style="font-size:13px;line-height:1.3">
        <div style="font-weight:700">${prettyName(f.name)}</div>
        <div style="opacity:.65">${f.url}</div>
      </div>
    </label>
  `).join('');

  // “전체/해제” 버튼(있다면) 동작
  $$('amMatAll')?.addEventListener('click', () => {
    box.querySelectorAll('.amMatFs').forEach(ch => (ch.checked = true));
  });
  $$('amMatNone')?.addEventListener('click', () => {
    box.querySelectorAll('.amMatFs').forEach(ch => (ch.checked = false));
  });
}

// ─────────────────────────────────────────────────────────────
// 학생 필터(커리/세부/레벨) - 기존 state.students 이용
// ─────────────────────────────────────────────────────────────
function uniq(arr){ return Array.from(new Set(arr.filter(Boolean))); }
function getFilteredSids() {
  const cur = $$('amCur')?.value ?? '';
  const sub = $$('amSub')?.value ?? '';
  const chosenLv = Array.from(document.querySelectorAll('.amLv:checked')).map(i => i.value);
  const studs = (state.students || []).slice().sort(byNameKo).filter(s => {
    if (cur && String(s.curriculum||'').trim() !== cur) return false;
    if (sub && String(s.subCurriculum||'').trim() !== sub) return false;
    const lv = String(s.level||'').trim();
    if (!chosenLv.length) return true;
    if (lv && chosenLv.includes(lv)) return true;
    if (!lv && chosenLv.includes('(빈값)')) return true;
    return false;
  });
  return studs.map(s => String(s.id));
}

function renderTargets() {
  const wrap = $$('amStuList'); if (!wrap) return;
  const ids = getFilteredSids();
  const studs = (state.students||[]).slice().sort(byNameKo)
    .filter(s => ids.includes(String(s.id)));
  wrap.innerHTML = studs.map(s => `
    <div style="border:1px solid var(--line);border-radius:8px;padding:6px">
      <div style="font-weight:700">${s.name}</div>
      <div style="opacity:.65;font-size:12px">${s.curriculum||''} ${s.subCurriculum||''} · ${s.level||'-'}</div>
    </div>
  `).join('');
  const cnt = $$('amStuCount'); if (cnt) cnt.textContent = `(${studs.length}명)`;
}

function buildFilters() {
  const studs = (state.students || []).slice().sort(byNameKo);
  const curSel = $$('amCur'); const subSel = $$('amSub');

  if (curSel) {
    const curList = uniq(studs.map(s => (s.curriculum||'').trim()));
    curSel.innerHTML = [`<option value="">(전체)</option>`, ...curList.map(c => `<option value="${c}">${c||'(미기입)'}</option>`)].join('');
  }
  function refreshSub() {
    if (!subSel) return;
    const cur = curSel?.value || '';
    const pool = studs.filter(s => !cur || (s.curriculum||'').trim() === cur);
    const subs = uniq(pool.map(s => (s.subCurriculum||'').trim()));
    subSel.innerHTML = [`<option value="">(전체)</option>`, ...subs.map(v => `<option value="${v}">${v||'(미기입)'}</option>`)].join('');
  }
  refreshSub();
  curSel?.addEventListener('change', () => { refreshSub(); renderTargets(); });
  subSel?.addEventListener('change', renderTargets);

  document.querySelectorAll('.amLv').forEach(chk => chk.addEventListener('change', renderTargets));
  $$('amSelAllLv')?.addEventListener('click', () => {
    document.querySelectorAll('.amLv').forEach(ch => ch.checked = true);
    renderTargets();
  });

  renderTargets();
}

// ─────────────────────────────────────────────────────────────
// 저장: 체크된 파일(경로) → material id로 보장 → assigns 저장
// ─────────────────────────────────────────────────────────────
async function saveAssignFromFS() {
  const sids = getFilteredSids();
  const picked = Array.from(document.querySelectorAll('.amMatFs:checked'))
    .map(el => ({ rel: el.value, title: el.dataset.title || '' }));
  if (!sids.length) { alert('대상 학생이 없습니다.'); return; }
  if (!picked.length) { alert('배정할 자료를 선택하세요.'); return; }

  // 파일 경로별로 material id 확보
  const ids = [];
  for (const p of picked) {
    const mid = await ensureMaterialForPath(p.rel, p.title);
    ids.push(mid);
  }

  // assigns 병합 저장
  const assigns = state.assigns || {};
  for (const sid of sids) {
    const prev = (assigns[sid] || []).map(String);
    const next = Array.from(new Set([...prev, ...ids]));
    assigns[sid] = next;
  }
  state.assigns = assigns;
  await fetch('/api/mat-assign', { method:'POST', headers:CT, body: JSON.stringify(assigns) });
  alert('배정 완료');
}

// ─────────────────────────────────────────────────────────────
// init
// ─────────────────────────────────────────────────────────────
export async function initAssignPanelFS() {
  // 필터/대상 학생
  buildFilters();
  // 현재 폴더의 파일로 “배정할 자료” 채우기
  await renderAssignMaterials();

  // 저장 버튼
  document.body.addEventListener('click', (e) => {
    if (e.target && e.target.id === 'sSave') {
      saveAssignFromFS().catch(err => alert('저장 실패: ' + err));
    }
  });

  // 폴더 이동 시 자동 갱신(파일관리에서 #curPath 텍스트가 바뀌면 호출해줘도 됨)
  const obs = new MutationObserver(() => renderAssignMaterials());
  const cur = document.querySelector('#curPath');
  if (cur) obs.observe(cur, { childList:true, characterData:true, subtree:true });
}

// 자동 실행(모듈이 아니라면 즉시)
if (!('module' in document.createElement('script'))) {
  initAssignPanelFS();
}
