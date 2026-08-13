document.addEventListener('keydown',(e)=>{
  if (e.key!=='Escape') return;
  ['progModal','yoilModal','miniProgModal'].forEach(id=>{
    const m=document.getElementById(id);
    if (!m || m.style.display==='none') return;
    m.style.display='none';
    if (id==='miniProgModal') m.dataset.sid='';
  });
});
