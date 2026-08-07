import { toast } from '../core/utils.js';
import { ensureProgressForSid, state } from '../core/state.js';
import { localDateKey } from '../core/date.js';

let editingSid = null;

(function mount(){
  if (document.getElementById('progModal')) return;
  document.body.insertAdjacentHTML('beforeend', `
    <div id="progModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);justify-content:center;align-items:center;z-index:9999">
      <div style="background:#fff;padding:1rem;border-radius:10px;max-height:80%;overflow:auto;width:360px">
        <h3 id="progTitle" style="margin-top:0">진도</h3>
        <div id="progZone" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(60px,1fr));gap:.5rem;"></div>
        <div style="text-align:right;margin-top:.6rem">
          <button type="button" id="progSave">저장</button>
          <button type="button" id="progClose">닫기</button>
        </div>
      </div>
    </div>`);
})();

const modal = document.getElementById('progModal');
const title = document.getElementById('progTitle');
const zone  = document.getElementById('progZone');

document.addEventListener('click', async (e)=>{
  const btn = e.target.closest('button.showProg');
  if (!btn) return;

  editingSid = btn.dataset.id;
  await ensureProgressForSid(editingSid);
  const tr = btn.closest('tr');
  const cur = (tr?.dataset.curriculum||'').trim();
  const sub = (tr?.dataset.subcurriculum||'').trim();
  const stu = state.students.find(s=>String(s.id)===String(editingSid));
  title.textContent = `${stu?.name||''} – ${cur}${sub?' '+sub:''}`;

  const curKey = cur.toLowerCase();
  const subKey = sub.toLowerCase();
  const curVids = state.videos
    .filter(v => (v.curriculum||'').trim().toLowerCase()===curKey &&
                 (v.subCurriculum||'').trim().toLowerCase()===subKey)
    .sort((a,b)=>a.chapter-b.chapter);

  const today = localDateKey();
  const dates = Object.keys(state.progress||{}).filter(d=>d<=today).sort();
  const progEntry = {};
  dates.forEach(d=>{
    const dayProg = (state.progress[d]||{})[editingSid] || {};
    Object.entries(dayProg).forEach(([mid, st]) => progEntry[mid]=st);
  });

  zone.innerHTML = '';
  curVids.forEach(v=>{
    const cell = document.createElement('div');
    cell.className = 'progress-cell';
    cell.textContent = `${v.chapter}차시`;
    cell.dataset.mid   = v.mid;
    cell.dataset.state = progEntry[v.mid] || 'none';
    cell.addEventListener('click', ()=>{
      const s = cell.dataset.state;
      cell.dataset.state = s==='none' ? 'done' : s==='done' ? 'interrupted' : 'none';
    });
    cell.addEventListener('contextmenu', (ev)=>{ ev.preventDefault(); cell.dataset.state='skip'; });
    zone.appendChild(cell);
  });

  modal.style.display = 'flex';
});

document.addEventListener('click', (e)=>{
  if (e.target.id==='progClose') modal.style.display='none';
  if (e.target===modal) modal.style.display='none';
  if (e.target.id==='progSave') save();
});

function save(){
  if (!editingSid) return;
  const today = localDateKey();
  const newProg = {};
  zone.querySelectorAll('.progress-cell').forEach(cell=>{
    const st = cell.dataset.state;
    if (st && st!=='none') newProg[cell.dataset.mid]=st;
  });

  state.progress = state.progress || {};
  state.progress[today] = state.progress[today] || {};
  state.progress[today][editingSid] = newProg;
  window.progressData = state.progress;

  fetch('/api/progress/patch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      date: today,
      sid: String(editingSid),
      progress: newProg,
    }),
  })
    .then(async (r) => {
      const body = await r.json().catch(() => ({}));
      if (!r.ok || !body?.ok) throw new Error(body?.error || r.status);
      state.progress[today][editingSid] = body.progress || newProg;
      window.progressData = state.progress;
      toast('진도 저장됨');
      modal.style.display = 'none';
    })
    .catch(()=>alert('진도 저장 실패'));
}
