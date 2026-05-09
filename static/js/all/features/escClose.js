document.addEventListener('keydown',(e)=>{
  if (e.key!=='Escape') return;
  ['progModal','yoilModal'].forEach(id=>{
    const m=document.getElementById(id);
    if (m && m.style.display!=='none') m.style.display='none';
  });
});
