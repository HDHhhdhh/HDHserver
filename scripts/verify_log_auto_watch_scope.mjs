import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const root=process.argv.find(x=>x.startsWith('--source-root='))?.slice(14)||process.cwd();
const source=fs.readFileSync(root+'/static/js/admin/features/logModal.js','utf8');
const start=source.indexOf('async function fetchWatchForSid('), end=source.indexOf('/* 숙제 helpers */',start);
const tail=source.slice(source.indexOf('/* 자동 판정 애드온 */'));
assert(start>=0&&end>start&&tail.includes('document.body.addEventListener'));
const vulnerable=process.argv.includes('--expect-vulnerable');
for(const scenario of ['late-fetch-sid','late-fetch-date','late-frame','late-retry','aba','closed','current','same-click-current']){
  let listener,release,grid; const frames=[],timers=[],urls=[];
  const cells=[
    {dataset:{mid:'m1',state:'none',initial:'none',cleared:'1',unknown:'keep'}},
    {dataset:{mid:'m2',state:'none',initial:'none',cleared:'1',explicitNone:'1',unknown:'manual'}},
    {dataset:{mid:'m3',state:'skip',initial:'skip',cleared:'',unknown:'skip-owner'}}];
  const input={value:'B 미저장 입력'}, inputBefore=input.value;
  const makeGrid=()=>({children:cells,querySelectorAll:()=>cells,isConnected:true});
  grid=makeGrid(); const modal={style:{display:'block'},hidden:false};
  const ctx=vm.createContext({URLSearchParams,console,editingLogSid:'A',editingLogDate:'2026-10-01',logOpenSeq:1,logModalReady:true,
    getAdminDate:()=> '2026-10-01',window:{},document:{body:{addEventListener:(type,fn)=>{assert.equal(type,'click');listener=fn}},
    getElementById:id=>id==='logProgress'?grid:id==='logModal'?modal:null},
    fetch:url=>{urls.push(String(url));return new Promise(resolve=>{release=resolve})},
    queueMicrotask,requestAnimationFrame:fn=>frames.push(fn),setTimeout:fn=>timers.push(fn)});
  vm.runInContext(source.slice(start,end)+'\n'+tail,ctx);
  const row={dataset:{sid:'A',date:'2026-10-01'}},button={closest:()=>row};
  if(scenario==='same-click-current'){ctx.editingLogSid=null;ctx.editingLogDate=null;ctx.logOpenSeq=0}
  const pending=listener({target:{closest:()=>button}});
  if(scenario==='same-click-current'){ctx.logOpenSeq++;ctx.editingLogSid='A';ctx.editingLogDate='2026-10-01'}
  await Promise.resolve();
  const change=()=>{
    ctx.logOpenSeq++;ctx.editingLogSid=null;ctx.editingLogDate=null;modal.style.display='none';
    if(scenario!=='closed'){
      ctx.logOpenSeq++;ctx.editingLogSid=scenario==='late-fetch-date'?'A':'B';ctx.editingLogDate=scenario==='late-fetch-date'?'2026-10-02':'2026-10-01';
      if(scenario==='aba'){ctx.logOpenSeq++;ctx.editingLogSid='A'}
      modal.style.display='block';
    } grid=makeGrid();
  };
  if(scenario.startsWith('late-fetch'))change();
  release({json:async()=>({watch:{m1:{last:100,dur:100},m2:{completed:true},m3:{last:100,dur:100}}})});
  await pending;
  if(scenario==='late-retry'){grid=null;while(frames.length)frames.shift()();assert.equal(timers.length,1);change()}
  else if(['late-frame','aba','closed'].includes(scenario))change();
  while(frames.length)frames.shift()();while(timers.length)timers.shift()();
  const expected=(scenario==='current'||scenario==='same-click-current'||vulnerable)?'done':'none';
  assert.equal(cells[0].dataset.state,expected,scenario);
  assert.deepEqual(cells[0].dataset,{mid:'m1',state:expected,initial:expected,cleared:expected==='done'?'':'1',unknown:'keep'});
  assert.deepEqual(cells[1].dataset,{mid:'m2',state:'none',initial:'none',cleared:'1',explicitNone:'1',unknown:'manual'});
  assert.deepEqual(cells[2].dataset,{mid:'m3',state:'skip',initial:'skip',cleared:'',unknown:'skip-owner'});
  assert.equal(input.value,inputBefore);
  assert.equal(urls.length,1);const query=new URLSearchParams(urls[0].split('?')[1]);assert.equal(query.get('sid'),'A');assert.equal(query.get('date'),'2026-10-01');
  console.log((vulnerable&&scenario!=='current'&&scenario!=='same-click-current'?'REPRO ':'PASS ')+scenario);
}
