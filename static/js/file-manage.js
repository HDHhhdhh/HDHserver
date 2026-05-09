// /js/file-manage.js — 트리/리스트 + 박스선택 + 드래그 이동
// + 이동 모드: 경로 입력 없이 트리/목록 폴더 클릭으로 이동
// + 우측 패널: (A) 추가(배정)  (B) 해제(빼기)
// + 폴더 배정(DIR:상대경로) 토큰 지원
// + 컨텍스트 메뉴: 열기/다운로드/이름변경/새폴더/이동/삭제/배정 담기

const $  = (s, p=document) => p.querySelector(s);
const $$ = (s, p=document) => Array.from(p.querySelectorAll(s));

/* ---------------- global state ---------------- */
let TREE = null;
let CUR  = "";               // 현재 폴더 상대경로
let SELECTED = new Set();    // 파일/폴더 선택 집합

// 배정 패널 상태
let STUDENTS = [];           // /api/students
let ASSIGNS  = {};           // /api/mat-assign  { sid: [token,...] }
let PICKED   = [];           // 추가(배정) 모드에서 담은 항목 (file/dir)
let MODE     = "add";        // "add" | "remove"

// 이동 모드
let MOVE_MODE = false;
let MOVE_SRC_PATHS = [];

/* ---------------- helpers ---------------- */
async function jget(url){
  const r = await fetch(url, { cache:"no-store" });
  const t = await r.text();
  if (!r.ok) throw new Error(t);
  return t ? JSON.parse(t) : {};
}
async function jpost(url, body){
  const r = await fetch(url, {
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body: JSON.stringify(body || {})
  });
  const t = await r.text();
  if (!r.ok) throw new Error(t);
  return t ? JSON.parse(t) : {};
}
function join(a,b){ return a ? `${a.replace(/\/$/,'')}/${b}` : b; }
function prettySize(n){
  if (n==null) return "";
  if (n<1024) return n+" B";
  if (n<1024**2) return (n/1024).toFixed(1)+" KB";
  if (n<1024**3) return (n/1024**2).toFixed(1)+" MB";
  return (n/1024**3).toFixed(1)+" GB";
}
// 표시용 파일명: UUID/긴 타임스탬프 접두 제거
function cleanName(name){
  const base = String(name||"").split("/").pop();
  const s1 = base.replace(/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}[\s_-]*/i,"");
  const s2 = s1.replace(/^[0-9]{13,17}[\s_-]*/,"");
  const s3 = s2.replace(/^[0-9a-z]{20,}[\s_-]*/i,"");
  return s3 || base;
}
function getNodeByPath(path){
  const segs = path.split("/").filter(Boolean);
  let cur = TREE;
  for (const s of segs){
    if (!cur) break;
    cur = (cur.children||[]).find(x => x.name===s);
  }
  return cur;
}
// 배정 토큰 정규화
function _normAssignVal(v){
  if (typeof v !== "string") return { url:null, rel:null, dir:null };
  const s = v.trim(); if (!s) return { url:null, rel:null, dir:null };
  if (s.startsWith("DIR:")) return { url:null, rel:null, dir:s.slice(4).replaceAll("\\","/").replace(/^\/+/,"") };
  if (s.includes("/files/")){
    const after = s.split("/files/")[1] || "";
    const rel = after.replace(/^[\/]+/,"").replaceAll("\\","/");
    return { url:s, rel:rel||null, dir:null };
  }
  const rel = s.replaceAll("\\","/");
  return { url:`/files/${rel}`, rel, dir:null };
}
function _fileKeys(f){
  const rel = (f?.path||"").replaceAll("\\","/");
  const url = f?.url || (rel ? `/files/${rel}` : null);
  return { url, rel };
}

/* ---------------- 이동 모드 UI ---------------- */
function showMoveToast(count) {
  let t = document.getElementById('moveToast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'moveToast';
    Object.assign(t.style, {
      position: 'fixed', left: '50%', top: '16px', transform: 'translateX(-50%)',
      background: 'var(--card-dark)', color: 'var(--text-dark, #e5e7eb)',
      border: '1px solid var(--line)', borderRadius: '12px', padding: '10px 12px',
      zIndex: 10001, boxShadow: '0 10px 24px rgba(0,0,0,.25)', display:'flex', gap:'8px', alignItems:'center'
    });
    t.innerHTML = `
      <b>이동 모드</b>
      <span style="opacity:.8">→ 왼쪽 트리나 가운데 목록에서 <u>대상 폴더</u>를 클릭하세요.</span>
      <span id="mvCnt" class="pill" style="background:#1f2937;color:#cbd5e1;border-radius:999px;padding:2px 8px"></span>
      <button id="mvRoot" class="btn small">루트로 이동</button>
      <button id="mvCancel" class="btn small ghost">취소</button>
    `;
    document.body.appendChild(t);
    document.getElementById('mvRoot').onclick   = ()=> doMoveTo('');
    document.getElementById('mvCancel').onclick = endMoveMode;
  }
  const cnt = t.querySelector('#mvCnt');
  if (cnt) cnt.textContent = `${count}개 선택`;
  t.style.display = 'flex';
}
function hideMoveToast(){
  const t = document.getElementById('moveToast');
  if (t) t.style.display = 'none';
}
function startMoveMode(){
  if (!SELECTED.size) { alert('이동할 항목을 선택하세요.'); return; }
  MOVE_MODE = true;
  MOVE_SRC_PATHS = [...SELECTED];
  showMoveToast(MOVE_SRC_PATHS.length);
}
function endMoveMode(){
  MOVE_MODE = false;
  MOVE_SRC_PATHS = [];
  hideMoveToast();
}
async function doMoveTo(dstPath){
  try{
    await jpost('/api/fs/move', { paths: MOVE_SRC_PATHS, dst: (dstPath||'') });
    endMoveMode();
    await refresh();
  }catch(e){
    endMoveMode();
    alert('이동 실패: ' + e);
  }
}

/* ---------------- tree/list render ---------------- */
function renderTree(){
  const wrap = $("#tree");
  if (!wrap) return;
  wrap.innerHTML = "";

  function nodeHTML(n, depth=0){
    if (n.type !== "dir") return;
    const row = document.createElement("div");
    row.className = "tree-row";
    row.innerHTML = `<div data-path="${n.path}" data-type="dir" style="padding-left:${8+depth*12}px; user-select:none">
      📁 ${n.name || "/"}
    </div>`;

    const target = row.firstElementChild;
    if (n.path === CUR) row.classList.add("sel");

    // 폴더 드롭 이동
    target.addEventListener("dragover", (e)=>{ e.preventDefault(); target.classList.add("drop-target"); });
    target.addEventListener("dragleave", ()=> target.classList.remove("drop-target"));
    target.addEventListener("drop", async (e)=>{
      e.preventDefault(); target.classList.remove("drop-target");
      const txt = e.dataTransfer.getData("application/x-paths");
      if (!txt) return;
      const paths = JSON.parse(txt);
      try{
        await jpost("/api/fs/move", { paths, dst:n.path });
        await refresh();
      }catch(err){ alert("이동 실패: "+err); }
    });

    // 클릭: 이동 모드면 이동, 아니면 열기
    target.addEventListener("click", ()=>{
      if (MOVE_MODE) {
        doMoveTo(n.path);
      } else {
        CUR = n.path;
        updateAll();
      }
    });

    wrap.appendChild(row);
    (n.children||[]).filter(c=>c.type==="dir").forEach(c => nodeHTML(c, depth+1));
  }
  nodeHTML(TREE);
}

function findFolderNode(path){
  let f = TREE;
  if (!path) return f;
  for (const s of path.split("/").filter(Boolean)){
    f = (f.children||[]).find(x => x.type==="dir" && x.name===s) || f;
  }
  return f;
}

let sortState = { key:"name", dir:1 };
function renderList(){
  const wrap = $("#list"); if (!wrap) return;
  SELECTED.clear();
  const folder = findFolderNode(CUR);
  const items = (folder.children||[]).slice().sort((a,b)=>{
    if (a.type!==b.type) return a.type==="dir" ? -1 : 1; // 폴더 우선
    return a.name.localeCompare(b.name,"ko");
  });

  const rows = [`<table><thead>
    <tr>
      <th style="width:28px"></th>
      <th id="thName" style="cursor:pointer">이름</th>
      <th class="right" id="thSize" style="cursor:pointer">크기</th>
      <th class="right" id="thMtime" style="cursor:pointer">수정</th>
    </tr></thead><tbody>`];

  for (const it of items){
    const display = it.type==="file" ? cleanName(it.name) : it.name;
    rows.push(`<tr data-path="${it.path}" data-type="${it.type}" draggable="true">
      <td><input type="checkbox" class="ck"></td>
      <td class="name">${it.type==="file" ? `📄 <a href="${it.url}" target="_blank" draggable="false">${display}</a>` : `📁 ${display}`}</td>
      <td class="right">${it.type==="file" ? prettySize(it.size) : ""}</td>
      <td class="right">${it.mtime ? new Date(it.mtime*1000).toLocaleString() : ""}</td>
    </tr>`);
  }
  rows.push(`</tbody></table>`);
  wrap.innerHTML = rows.join("");

  // 체크 선택
  wrap.querySelector("tbody").addEventListener("change", (e)=>{
    const tr = e.target.closest("tr[data-path]"); if (!tr) return;
    const p = tr.dataset.path;
    if (e.target.checked){ SELECTED.add(p); tr.classList.add("sel"); }
    else { SELECTED.delete(p); tr.classList.remove("sel"); }
  });

  // 더블클릭: 폴더 열기
  wrap.querySelector("tbody").addEventListener("dblclick", (e)=>{
    const tr = e.target.closest("tr[data-path]"); if (!tr) return;
    if (tr.dataset.type==="dir"){ CUR = tr.dataset.path; updateAll(); }
  });

  // 드래그 시작(배정/이동 공통 데이터)
  $$("#list tbody tr").forEach(tr=>{
    tr.addEventListener("dragstart", (e)=>{
      if (_boxSelecting){ e.preventDefault(); return; }
      const p = tr.dataset.path;
      // 단일 드래그면 해당 행만 선택
      if (!SELECTED.has(p)){
        SELECTED.clear(); $$("#list tbody tr.sel").forEach(r=>r.classList.remove("sel"));
        SELECTED.add(p); tr.classList.add("sel");
        tr.querySelector(".ck").checked = true;
      }
      e.dataTransfer.setData("application/x-paths", JSON.stringify([...SELECTED]));
      e.dataTransfer.effectAllowed = "copyMove";
    });
  });

  // 정렬 헤더
  $("#thName").onclick = ()=> sortList("name");
  $("#thSize").onclick = ()=> sortList("size");
  $("#thMtime").onclick = ()=> sortList("mtime");

  enableBoxSelect();

  // 우클릭 메뉴
  wrap.querySelector("tbody").addEventListener("contextmenu", (e)=>{
    const tr = e.target.closest("tr[data-path]"); if (!tr) return;
    e.preventDefault();
    const p = tr.dataset.path;
    if (!SELECTED.has(p)){
      SELECTED.clear(); $$("#list tbody tr.sel").forEach(r=>r.classList.remove("sel"));
      SELECTED.add(p); tr.classList.add("sel");
      tr.querySelector(".ck").checked = true;
    }
    openCtxMenu(e.clientX, e.clientY, tr.dataset);
  });

  // 이동 모드: 목록 폴더 클릭 시 이동
  $("#list tbody")?.addEventListener("click", (e)=>{
    if (!MOVE_MODE) return;
    const tr = e.target.closest("tr[data-path][data-type='dir']");
    if (!tr) return;
    doMoveTo(tr.dataset.path);
  });
}

function sortList(key){
  const tbody = $("#list tbody");
  const rows = Array.from(tbody.children);
  const dir = (sortState.key===key) ? -sortState.dir : 1;
  sortState = { key, dir };

  function get(tr){
    if (key==="name"){
      const isDir = tr.dataset.type==="dir" ? 0 : 1;
      const txt = tr.querySelector(".name")?.textContent?.trim()?.toLowerCase() || "";
      return [isDir, txt];
    }
    if (key==="size"){
      if (tr.dataset.type==="dir") return [-1];
      const node = getNodeByPath(tr.dataset.path);
      return [node?.size ?? 0];
    }
    if (key==="mtime"){
      const node = getNodeByPath(tr.dataset.path);
      return [node?.mtime ?? 0];
    }
    return [0];
  }

  rows.sort((r1,r2)=>{
    const a = get(r1), b = get(r2);
    for (let i=0;i<Math.max(a.length,b.length);i++){
      const x=a[i]??0, y=b[i]??0;
      if (x<y) return -1*dir;
      if (x>y) return 1*dir;
    }
    return 0;
  });
  rows.forEach(r=>tbody.appendChild(r));
}

/* ---------------- state update ---------------- */
function updateAll(){
  $("#curPath") && ($("#curPath").textContent = "/" + CUR);
  renderTree();
  renderList();
}

/* ---------------- server I/O ---------------- */
async function refresh(){
  const data = await jget("/api/fs/tree");
  TREE = data.tree;

  try { STUDENTS = await jget("/api/students"); } catch { STUDENTS = []; }
  try { ASSIGNS  = await jget("/api/mat-assign"); } catch { ASSIGNS = {}; }

  updateAll();
  buildAssignFilters();
  renderAssignStudents();
  renderPickedList();   // add 모드 UI
  if (MODE==="remove") renderAssignedUnion(); // remove 모드 UI
}
async function makeFolder(){
  const name = $("#newFolderName")?.value.trim();
  if (!name) return alert("폴더명을 입력하세요.");
  await jpost("/api/fs/folder", { path: join(CUR, name) });
  $("#newFolderName").value = "";
  await refresh();
}
async function renameOne(){
  if (SELECTED.size !== 1) return alert("이름 변경은 하나만 선택하세요.");
  const [p] = [...SELECTED];
  const base = p.split("/").pop();
  const nm = prompt("새 이름", base);
  if (!nm) return;
  const res = await jpost("/api/fs/rename", { src:p, new_name:nm });
  if (p===CUR) CUR = res.path;
  await refresh();
}
async function deleteItems(){
  if (!SELECTED.size) return;
  if (!confirm(`정말 삭제할까요? (${SELECTED.size}개)`)) return;
  await jpost("/api/fs/delete", { paths:[...SELECTED] });
  await refresh();
}
async function uploadFiles(files){
  if (!files || !files.length) return;
  const fd = new FormData();
  fd.append("dst", CUR);
  for (const f of files) fd.append("files", f);
  const res = await fetch("/api/fs/upload", { method:"POST", body:fd });
  const text = await res.text();
  if (!res.ok) throw new Error(text);
  await refresh();
}

/* ---------------- events ---------------- */
function bind(){
  $("#btnRefresh")?.addEventListener("click", refresh);
  $("#btnMake")?.addEventListener("click", makeFolder);
  $("#btnRename")?.addEventListener("click", renameOne);
  $("#btnMove")?.addEventListener("click", startMoveMode); // 이동 모드
  $("#btnDelete")?.addEventListener("click", deleteItems);

  // 업로드
  $("#btnUpload")?.addEventListener("click", ()=> $("#fileInput").click());
  $("#fileInput")?.addEventListener("change", e=> uploadFiles(e.target.files));

  // 업로드 드롭존
  const drop = $("#drop");
  if (drop){
    ["dragenter","dragover"].forEach(ev => drop.addEventListener(ev, e=>{
      e.preventDefault(); e.dataTransfer.dropEffect="copy"; drop.classList.add("drag");
    }));
    ["dragleave","drop"].forEach(ev => drop.addEventListener(ev, e=>{
      e.preventDefault(); drop.classList.remove("drag");
    }));
    drop.addEventListener("drop", e=>{
      uploadFiles(e.dataTransfer.files).catch(err=>alert("업로드 실패: "+err));
    });
  }

  // 우측 패널 드롭(추가 모드)
  const assignDrop = $("#amMatList");
  if (assignDrop){
    ["dragenter","dragover"].forEach(ev => assignDrop.addEventListener(ev, e=>{
      e.preventDefault(); e.dataTransfer.dropEffect="copy"; assignDrop.classList.add("drop-target");
    }));
    ["dragleave","drop"].forEach(ev => assignDrop.addEventListener(ev, e=>{
      e.preventDefault(); assignDrop.classList.remove("drop-target");
    }));
    assignDrop.addEventListener("drop", (e)=>{
      const txt = e.dataTransfer.getData("application/x-paths");
      if (!txt) return;
      addPickedFromPaths(JSON.parse(txt));
    });
  }

  // 필터
  $("#amCur")?.addEventListener("change", ()=>{ refreshSubOptions(); renderAssignStudents(); if (MODE==="remove") renderAssignedUnion(); });
  $("#amSub")?.addEventListener("change", ()=>{ renderAssignStudents(); if (MODE==="remove") renderAssignedUnion(); });
  $("#amLvAll")?.addEventListener("click", ()=>{
    $$("#amLvWrap input[type='checkbox']").forEach(c=> c.checked=true);
    renderAssignStudents(); if (MODE==="remove") renderAssignedUnion();
  });
  $("#amLvWrap")?.addEventListener("change", (e)=>{
    if (e.target.matches("input[type='checkbox']")){
      renderAssignStudents(); if (MODE==="remove") renderAssignedUnion();
    }
  });

  // 모드 토글
  $("#modeAdd")?.addEventListener("click", ()=> setMode("add"));
  $("#modeRemove")?.addEventListener("click", ()=> setMode("remove"));

  // 추가모드: 배정목록 비우기
  $("#amPickClear")?.addEventListener("click", ()=>{ PICKED.length=0; renderPickedList(); });

  // 해제모드: 셀렉션 보조
  $("#rmAll")?.addEventListener("click", ()=> setAll(".rmItem", true));
  $("#rmNone")?.addEventListener("click", ()=> setAll(".rmItem", false));

  // 실행 버튼
  $("#amDoAssign")?.addEventListener("click", ()=> runAction().catch(e=>alert(e)));

  // 바깥 클릭/ESC → 컨텍스트 닫기/이동모드 취소
  window.addEventListener("click", closeCtxMenu);
  window.addEventListener("keydown", (e)=>{
    if (e.key === "Escape") {
      closeCtxMenu();
      if (MOVE_MODE) endMoveMode();
    }
  });
}

/* ---------------- 박스(러버밴드) 선택 ---------------- */
let _boxSelecting = false;
function enableBoxSelect(){
  const area = $("#list");
  const table = area?.querySelector("tbody");
  if (!table) return;
  let startX=0, startY=0, box=null, selecting=false;

  const rows = () => $$("#list tbody tr");
  const rect = (el)=> el.getBoundingClientRect();
  const intersect = (r1,r2)=> !(r2.left>r1.right || r2.right<r1.left || r2.top>r1.bottom || r2.bottom<r1.top);

  area.addEventListener("mousedown", (e)=>{
    if (e.button!==0) return;
    if (e.target.closest("a, input, textarea, select, button")) return;
    selecting = true; _boxSelecting = true;
    startX = e.clientX; startY = e.clientY;

    box = document.createElement("div");
    Object.assign(box.style,{
      position:"fixed", left:startX+"px", top:startY+"px", width:"0px", height:"0px",
      border:"1px dashed var(--accent)", background:"color-mix(in oklab, var(--accent) 10%, transparent)",
      zIndex:9999, pointerEvents:"none"
    });
    document.body.appendChild(box);

    // 새 시작 → 보조키 없으면 초기화
    if (!e.ctrlKey && !e.metaKey && !e.shiftKey){
      SELECTED.clear();
      rows().forEach(r=>r.classList.remove("sel"));
      $$("#list tbody .ck").forEach(ck=> ck.checked=false);
    }
    e.preventDefault();
  });

  window.addEventListener("mousemove", (e)=>{
    if (!selecting || !box) return;
    const x1 = Math.min(startX, e.clientX), y1 = Math.min(startY, e.clientY);
    const x2 = Math.max(startX, e.clientX), y2 = Math.max(startY, e.clientY);
    Object.assign(box.style,{ left:x1+"px", top:y1+"px", width:(x2-x1)+"px", height:(y2-y1)+"px" });

    const rBox = { left:x1, top:y1, right:x2, bottom:y2 };
    $$("#list tbody tr").forEach(tr=>{
      const r = rect(tr);
      const hit = intersect(rBox, r);
      const path = tr.dataset.path;
      if (hit){ tr.classList.add("sel"); SELECTED.add(path); tr.querySelector(".ck").checked=true; }
      else { tr.classList.remove("sel"); SELECTED.delete(path); tr.querySelector(".ck").checked=false; }
    });
  });

  window.addEventListener("mouseup", ()=>{
    if (!selecting) return;
    selecting=false; _boxSelecting=false;
    box?.remove(); box=null;
  });
}

/* ---------------- 우측 패널 – 필터/학생/모드 ---------------- */
function uniqueNonEmpty(arr){ return Array.from(new Set(arr.map(v=>String(v||"").trim()).filter(Boolean))); }

function buildAssignFilters(){
  const curSel = $("#amCur");
  const subSel = $("#amSub");
  const lvWrap = $("#amLvWrap");
  if (!curSel || !subSel || !lvWrap) return;

  const curList = uniqueNonEmpty(STUDENTS.map(s=>s.curriculum));
  curSel.innerHTML = `<option value="">(전체)</option>` + curList.map(c=>`<option value="${c}">${c}</option>`).join("");

  refreshSubOptions();

  const baseLv = ['상','중상','중','하'];
  const lvVals  = uniqueNonEmpty(STUDENTS.map(s=>s.level));
  const hasEmpty = STUDENTS.some(s=>!String(s.level||"").trim());
  const order = [...baseLv, ...lvVals.filter(v=>!baseLv.includes(v))];
  const final = hasEmpty ? [...order, '(빈값)'] : order;

  lvWrap.innerHTML = final.map(lv=>`
    <label class="chip"><input type="checkbox" class="lvChk" value="${lv}"> ${lv}</label>
  `).join("");
}
function refreshSubOptions(){
  const curSel = $("#amCur");
  const subSel = $("#amSub");
  if (!curSel || !subSel) return;
  const cur = curSel.value;
  const pool = STUDENTS.filter(s => !cur || String(s.curriculum||"").trim()===cur);
  const subList = uniqueNonEmpty(pool.map(s=>s.subCurriculum));
  subSel.innerHTML = `<option value="">(전체)</option>` + subList.map(v=>`<option value="${v}">${v}</option>`).join("");
}
function getSelectedLevels(){
  const chks = $$("#amLvWrap .lvChk");
  const picked = chks.filter(c=>c.checked).map(c=>c.value);
  return new Set(picked);
}
function getFilteredSids(){
  const cur = $("#amCur")?.value ?? "";
  const sub = $("#amSub")?.value ?? "";
  const lvSet = getSelectedLevels();
  return STUDENTS.filter(s=>{
    if (cur && String(s.curriculum||"").trim()!==cur) return false;
    if (sub && String(s.subCurriculum||"").trim()!==sub) return false;
    if (lvSet.size){
      const lv = (String(s.level||"").trim()) || "(빈값)";
      if (!lvSet.has(lv)) return false;
    }
    return true;
  }).map(s => String(s.id));
}
function renderAssignStudents(){
  const list = $("#amStuList"), cnt=$("#amStuCount"); if (!list || !cnt) return;
  const sids = getFilteredSids();
  const map = new Map(STUDENTS.map(s=>[String(s.id), s]));
  const studs = sids.map(id=>map.get(id)).filter(Boolean).sort((a,b)=>String(a.name).localeCompare(String(b.name),'ko'));
  cnt.textContent = `(${studs.length}명)`;
  list.innerHTML = studs.map(s=>`
    <div class="assign-stu">
      <div style="font-weight:700">${s.name}</div>
      <div style="opacity:.65;font-size:12px">
        ${(s.curriculum||'')}${s.subCurriculum?(' · '+s.subCurriculum):''}${s.level?(' · '+s.level):''}
      </div>
    </div>
  `).join("");
}
function setMode(m){
  MODE = m;
  $("#modeAdd")?.classList.toggle("on", m==="add");
  $("#modeRemove")?.classList.toggle("on", m==="remove");
  $("#boxAdd")?.style.setProperty("display", m==="add" ? "" : "none");
  $("#boxRemove")?.style.setProperty("display", m==="remove" ? "" : "none");
  if (m==="remove") renderAssignedUnion();
}

/* ---------------- 추가(배정) 모드: 담기/표시 ---------------- */
function addPickedFromPaths(paths){
  for (const p of paths){
    const node = getNodeByPath(p);
    if (!node) continue;
    if (node.type==="file"){
      if (PICKED.find(x=>x.type==="file" && x.path===node.path)) continue;
      PICKED.push({ type:"file", path:node.path, name:cleanName(node.name), url:node.url, size:node.size, mtime:node.mtime });
    } else if (node.type==="dir"){
      if (PICKED.find(x=>x.type==="dir" && x.path===node.path)) continue;
      PICKED.push({ type:"dir", path:node.path, name:node.name||"/" });
    }
  }
  renderPickedList();
}
function renderPickedList(){
  const box = $("#amMatList"); if (!box) return;
  if (!PICKED.length){
    box.innerHTML = `<div style="opacity:.7">여기에 파일/폴더를 드래그해 배정 목록에 담으세요.</div>`;
    return;
  }
  box.innerHTML = PICKED.map((f,i)=>`
    <label class="chip" data-i="${i}" title="${f.path}" style="justify-content:space-between">
      <span>${f.type==="dir" ? "📁" : "📄"} ${f.name}</span>
      <button class="btn small ghost" data-rm="${i}" style="margin-left:6px">삭제</button>
    </label>
  `).join("");

  box.querySelectorAll("button[data-rm]").forEach(btn=>{
    btn.addEventListener("click", ()=>{
      const i = parseInt(btn.dataset.rm,10);
      if (!Number.isInteger(i)) return;
      PICKED.splice(i,1);
      renderPickedList();
    });
  });
}

/* ---------------- 해제(빼기) 모드: 합집합 목록 ---------------- */
function renderAssignedUnion(){
  const list = $("#amCurList"); if (!list) return;
  const sids = getFilteredSids();
  const set = new Set();
  if (Array.isArray(sids) && sids.length){
    for (const sid of sids){
      const arr = ASSIGNS?.[String(sid)] || [];
      for (const t of arr) set.add(String(t));
    }
  } else {
    for (const arr of Object.values(ASSIGNS||{})) for (const t of (arr||[])) set.add(String(t));
  }
  const tokens = Array.from(set).sort();

  if (!tokens.length){
    list.innerHTML = `<div class="muted">표시할 항목이 없습니다</div>`;
    return;
  }

  list.innerHTML = tokens.map(tok=>{
    const norm = _normAssignVal(tok);
    let icon="📄", title="", sub="";
    if (norm.dir){
      icon="📁"; title = norm.dir; sub = "폴더";
    } else if (norm.rel || norm.url){
      const rel = norm.rel || (norm.url?.split("/files/")[1]||"");
      title = cleanName(decodeURIComponent(rel.split("/").pop()||"파일"));
      sub = rel ? rel : (norm.url||"");
    } else { title = tok; sub="(인식 불가)"; }
    const safeTok = tok.replace(/"/g,"&quot;");
    return `
      <label style="display:flex;gap:8px;align-items:center;border:1px solid var(--line);border-radius:8px;padding:6px">
        <input type="checkbox" class="rmItem" value="${safeTok}">
        <div style="font-size:13px;line-height:1.25">
          <div style="font-weight:700">${icon} ${title}</div>
          <div style="opacity:.65">${sub}</div>
        </div>
      </label>`;
  }).join("");
}
function getChecked(sel){ return $$(sel).filter(i=>i.checked).map(i=>String(i.value)); }
function setAll(sel, on){ $$(sel).forEach(i=> i.checked=!!on); }

/* ---------------- 실행 (모드별 동작) ---------------- */
async function runAction(){
  if (MODE==="add") return doAssignAdd();
  return doAssignRemove();
}

// 추가(배정)
async function doAssignAdd(){
  const sidList = getFilteredSids();
  const isGlobalCancel = sidList.length===0;
  if (!PICKED.length && !isGlobalCancel) return alert("배정할 항목을 먼저 드롭하세요.");

  const btn = $("#amDoAssign"); const orig = btn?.innerHTML;
  if (btn){ btn.disabled=true; btn.innerHTML="배정 중…"; }

  try{
    const cur = await jget("/api/mat-assign").catch(()=> ({}));
    const assigns = (cur && typeof cur==="object") ? {...cur} : {};

    const items = PICKED.map(f=> f.type==="dir" ? `DIR:${f.path}` : (f.url || f.path)).filter(Boolean);
    let addOps=0, removeOps=0;

    // 보정
    for (const sid of sidList) if (!Array.isArray(assigns[sid])) assigns[sid]=[];

    const allSidKeys = new Set([...Object.keys(assigns||{}), ...sidList.map(String)]);
    for (const sid of allSidKeys){
      const arr = Array.isArray(assigns[sid]) ? assigns[sid].slice() : [];
      const set = new Set(arr.map(String));

      if (isGlobalCancel){
        for (const it of items){ if (set.delete(String(it))) removeOps++; }
      } else {
        if (!sidList.includes(String(sid))){
          for (const it of items){ if (set.delete(String(it))) removeOps++; }
        } else {
          for (const it of items){ const s=String(it); if (!set.has(s)){ set.add(s); addOps++; } }
        }
      }
      const next = Array.from(set);
      if (next.length) assigns[sid]=next; else delete assigns[sid];
    }

    await jpost("/api/mat-assign", assigns);
    ASSIGNS = assigns;

    alert(isGlobalCancel
      ? `전체 취소 완료\n- 항목: ${items.length}개\n- 제거: ${removeOps}회`
      : `배정 갱신 완료\n- 대상 학생: ${sidList.length}명\n- 항목: ${items.length}개\n- 추가: ${addOps} / 제거: ${removeOps}`);

    PICKED.length=0; renderPickedList();
    if (MODE==="remove") renderAssignedUnion();
  } catch(err){
    alert("배정 실패: "+(err?.message||err));
  } finally {
    if (btn){ btn.disabled=false; btn.innerHTML=orig; }
  }
}

// 해제(빼기)
async function doAssignRemove(){
  const rmTokens = getChecked(".rmItem");
  if (!rmTokens.length) return alert("해제할 항목을 선택하세요.");

  const sidList = getFilteredSids(); // 0명 → 전원에서 제거
  const isGlobal = sidList.length===0;

  const btn = $("#amDoAssign"); const orig = btn?.innerHTML;
  if (btn){ btn.disabled=true; btn.innerHTML="해제 중…"; }

  try{
    const cur = await jget("/api/mat-assign").catch(()=> ({}));
    const assigns = (cur && typeof cur==="object") ? {...cur} : {};
    let removeOps = 0;

    const targets = isGlobal ? Object.keys(assigns||{}) : sidList.map(String);
    for (const sid of targets){
      const arr = Array.isArray(assigns[sid]) ? assigns[sid].slice() : [];
      const set = new Set(arr.map(String));
      for (const t of rmTokens){
        if (set.delete(String(t))) removeOps++;
      }
      const next = Array.from(set);
      if (next.length) assigns[sid]=next; else delete assigns[sid];
    }

    await jpost("/api/mat-assign", assigns);
    ASSIGNS = assigns;

    alert(isGlobal
      ? `전체 해제 완료\n- 항목: ${rmTokens.length}개\n- 제거: ${removeOps}회`
      : `해제 완료\n- 대상 학생: ${sidList.length}명\n- 항목: ${rmTokens.length}개\n- 제거: ${removeOps}회}`);

    renderAssignedUnion(); // 목록 갱신
  } catch(err){
    alert("해제 실패: "+(err?.message||err));
  } finally {
    if (btn){ btn.disabled=false; btn.innerHTML=orig; }
  }
}

/* ---------------- 컨텍스트 메뉴 ---------------- */
let _ctxEl=null;
function themeColors(){
  const dark = document.body.classList.contains("dark");
  const cs = getComputedStyle(document.body);
  const card = cs.getPropertyValue(dark ? "--card-dark" : "--card-light").trim() || (dark ? "#1e293b" : "#fff");
  const text = cs.getPropertyValue(dark ? "--text-dark" : "--text").trim() || (dark ? "#e5e7eb" : "#111827");
  const line = cs.getPropertyValue("--line").trim() || (dark ? "#334155" : "#e2e8f0");
  return { card, text, line };
}
function ensureCtx(){
  if (_ctxEl) return _ctxEl;
  const {card,text,line} = themeColors();
  const el = document.createElement("div");
  el.id="ctx";
  Object.assign(el.style,{
    position:"fixed", left:"0", top:"0", display:"none",
    minWidth:"200px", padding:"6px", background:card, color:text,
    border:`1px solid ${line}`, borderRadius:"12px", boxShadow:"0 10px 24px rgba(0,0,0,.25)", zIndex:10000
  });
  el.innerHTML = `
    <div data-act="open" class="ctx-i">📂 열기(폴더)</div>
    <div data-act="download" class="ctx-i">⬇️ 다운로드(파일)</div>
    <hr class="ctx-hr">
    <div data-act="rename" class="ctx-i">✏️ 이름 변경</div>
    <div data-act="newdir" class="ctx-i">📁 새 폴더</div>
    <div data-act="move" class="ctx-i">📦 이동…</div>
    <div data-act="delete" class="ctx-i">🗑 삭제</div>
    <hr class="ctx-hr">
    <div data-act="pick" class="ctx-i">🧺 선택을 배정 목록에 담기</div>
  `;
  el.querySelectorAll(".ctx-i").forEach(it=>{
    Object.assign(it.style,{ padding:"8px 10px", borderRadius:"8px", cursor:"pointer", userSelect:"none" });
    it.addEventListener("mouseenter", ()=> it.style.background="rgba(255,255,255,.06)");
    it.addEventListener("mouseleave", ()=> it.style.background="transparent");
  });
  el.querySelectorAll(".ctx-hr").forEach(hr=>{
    Object.assign(hr.style,{ border:"0", borderTop:`1px solid ${line}`, margin:"6px 2px" });
  });
  document.body.appendChild(el);
  _ctxEl = el;
  return el;
}
function closeCtxMenu(){ if (_ctxEl) _ctxEl.style.display="none"; }
function openCtxMenu(x,y,dataset){
  const el = ensureCtx();
  const pad=6, vw=innerWidth, vh=innerHeight;
  el.style.display="block";
  const rect = el.getBoundingClientRect();
  el.style.left = Math.min(x, vw-rect.width-pad) + "px";
  el.style.top  = Math.min(y, vh-rect.height-pad) + "px";

  const isFile = dataset.type==="file";
  const isDir  = dataset.type==="dir";
  el.querySelector('[data-act="open"]').style.display     = isDir ? "block":"none";
  el.querySelector('[data-act="download"]').style.display = (isFile && SELECTED.size===1) ? "block":"none";

  el.onclick = async (evt)=>{
    const act = evt.target?.dataset?.act;
    if (!act) return;
    closeCtxMenu();

    if (act==="open" && isDir){ CUR = dataset.path; updateAll(); return; }
    if (act==="download" && isFile && SELECTED.size===1){
      const node = getNodeByPath(dataset.path); if (node?.url) window.open(node.url,"_blank"); return;
    }
    if (act==="rename"){ await renameOne(); return; }
    if (act==="newdir"){ await makeFolder(); return; }
    if (act==="move"){ startMoveMode(); return; }           // ← 이동 모드
    if (act==="delete"){ await deleteItems(); return; }
    if (act==="pick"){ addPickedFromPaths([...SELECTED]); return; }
  };
}

/* ---------------- boot ---------------- */
window.addEventListener("DOMContentLoaded", ()=>{
  bind();
  refresh().catch(err=>alert("로드 실패: "+err));
});
