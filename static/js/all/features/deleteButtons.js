function getWrap(){ return document.getElementById('allWrap') || document.getElementById('studentsWrap') || document.getElementById('listWrap') || document.body; }
function getTable(){ const w=getWrap(); return w ? (w.querySelector('table') || w.querySelector('.all-table')) : null; }

function parseRowInfo(tr){
  let sid = tr.dataset.sid
    || tr.querySelector('.stuName, .stu-name, a[data-sid]')?.dataset?.sid
    || (tr.querySelector('a[href*="/student/"]')?.getAttribute('href')||'').split('/').pop()
    || tr.querySelector('[data-id]')?.dataset?.id || '';
  sid=(sid||'').trim();
  const name=(tr.querySelector('.stuName, .stu-name, a[href*="/student/"]')?.textContent || tr.cells?.[0]?.textContent || '').trim();
  return { sid, name };
}

function injectDeleteColumn(){
  const table=getTable(); if(!table) return;
  const theadRow=table.tHead?.rows?.[0] || table.querySelector('thead tr');
  if (theadRow && !theadRow.querySelector('.col-del')) {
    const th=document.createElement('th'); th.textContent='Del'; th.className='col-del'; th.style.width='48px'; theadRow.appendChild(th);
  }
  const tb=table.tBodies?.[0]||table.querySelector('tbody'); if(!tb) return;
  Array.from(tb.rows).forEach(tr=>{
    if (tr.classList.contains('grp') || tr.querySelector('.btn-del-stu')) return;
    const td=document.createElement('td'); td.style.textAlign='center';
    const btn=document.createElement('button'); btn.type='button'; btn.className='btn-del-stu'; btn.title='학생 삭제'; btn.textContent='🗑'; btn.style.cssText='cursor:pointer';
    const { sid }=parseRowInfo(tr); if (sid) btn.dataset.sid=sid;
    td.appendChild(btn); tr.appendChild(td);
  });
}

export function hookDeleteButtons(){
  const tryOnce=()=>{ const t=getTable(); if(!t) return false; injectDeleteColumn(); return true; };
  if (tryOnce()) return;
  const wrap=getWrap();
  const mo=new MutationObserver(()=>{ if(tryOnce()) mo.disconnect(); });
  mo.observe(wrap,{childList:true,subtree:true});
}

document.addEventListener('click', async (e)=>{
  const btn=e.target.closest('.btn-del-stu'); if(!btn) return;
  const tr=btn.closest('tr'); const { sid, name }=parseRowInfo(tr);
  if (!sid) { alert('학생 ID를 찾을 수 없습니다.'); return; }
  if (!confirm(`정말 "${name||sid}" 학생을 삭제할까요?\n(되돌릴 수 없습니다)`)) return;
  try{
    let res = await fetch(`/api/students/${encodeURIComponent(sid)}`, { method:'DELETE' });
    if (!res.ok) {
      res = await fetch('/api/delete-student', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ id:sid }) });
    }
    if (!res.ok) throw new Error(`서버 응답 ${res.status}`);
    if (Array.isArray(window.students)) window.students = window.students.filter(s=>String(s.id)!==String(sid));
    tr.remove();
    (window.toast ? toast('삭제 완료') : alert('삭제 완료'));
  }catch(err){ console.error(err); alert('삭제 실패: '+err.message); }
});
