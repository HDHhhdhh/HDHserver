import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

const root = path.resolve(process.argv[2] || path.join(path.dirname(fileURLToPath(import.meta.url)), '..'));
const proposedPath = process.argv[3] || path.join(root, 'static/js/admin/features/logModal.js');
const proposed = fs.readFileSync(proposedPath, 'utf8');
const original = fs.readFileSync(path.join(root, 'static/js/admin/features/logModal.js'), 'utf8');
const driver = fs.readFileSync(path.join(root, 'scripts/verify_admin_popup_async_scope.mjs'), 'utf8').replaceAll('\r\n','\n');
let helpers = driver.slice(driver.indexOf('const clone ='), driver.indexOf('\nconst row ='));
assert.ok(helpers.includes('function logHarness()'));
// Reuse only the existing DOM/layout harness. Do not stub actual authority loaders,
// cache/epoch, log projection, input locking or the open/close/save owners.
helpers = helpers
  .replace('parkHomeworkWorkspace=mountAssistantThread=mountHomeworkInTooltip=renderHwTable=syncHomeworkRemovalControls=()=>{};', 'parkHomeworkWorkspace=mountAssistantThread=mountHomeworkInTooltip=renderHwTable=()=>{};')
  .replace("    'hydrateLogHistoryForSid=hydrateProgressHistoryForSid=async()=>true;',\n", '')
  .replace("    'fetchCanonicalHomeworkForLogCached=async()=>({mode:\"legacy\"});',\n", '')
  .replace("    'projectHomeworkRowsFromLogState=(date,sid)=>({logEntry:state.logs[date]?.[sid]||{},todayRows:[],sleepingHomeworkBooks:[],mergedRows:[]});',\n", '')
  .replace("    'invalidateLogModalHydrationCaches=()=>{};',\n", '');
assert.ok(!helpers.includes('hydrateLogHistoryForSid=hydrateProgressHistoryForSid'), 'real hydrators stay in the fixture');
assert.ok(!helpers.includes('fetchCanonicalHomeworkForLogCached=async'), 'real canonical compatibility loader stays in the fixture');
assert.ok(!helpers.includes('projectHomeworkRowsFromLogState=(date,sid)=>'), 'real log/homework projection stays in the fixture');
assert.ok(!helpers.includes('invalidateLogModalHydrationCaches=()=>{}'), 'real semantic cache invalidation stays in the fixture');
const cloned = value => JSON.parse(JSON.stringify(value));
let cases = 0, assertions = 0;
const same = (actual, expected, message) => { assert.deepEqual(cloned(actual), expected, message); assertions++; };
const turn = async () => { for (let i=0;i<40;i++) await Promise.resolve(); };
const DATE = '2026-10-01', BDATE = '2026-10-02';
const row = (sid='A', date=DATE) => ({dataset:{sid,date}});
const make = (source=proposed) => {
  const stripped = source.replace(/^import\s[\s\S]*?;\r?\n/gm,'').replace(/\bexport\s+/g,'');
  const factory = new Function('read','vm','A_DATE','B_DATE', helpers + '\nreturn {logHarness,element};')(() => stripped, vm, DATE, BDATE);
  const h = factory.logHarness(), ctx = h.context, reads=[], reveals=[], renderModes=[];
  let clock = Date.UTC(2026,9,1), mounts=0;
  class FixtureDate extends Date { constructor(...xs){super(...(xs.length?xs:[clock]));} static now(){return clock;} }
  Object.assign(ctx,{URLSearchParams, Date:FixtureDate});
  const decorate = node => {
    node.children=[];node.attrs={};node.closest=()=>null;
    node.append=(...xs)=>xs.forEach(x=>{x.parent=node;node.children.push(x);});
    node.prepend=x=>{x.parent=node;node.children.unshift(x);};
    node.remove=()=>{if(node.parent)node.parent.children=node.parent.children.filter(x=>x!==node);};
    node.setAttribute=(key,value)=>{node.attrs[key]=String(value);};
    node.removeAttribute=key=>{delete node.attrs[key];};
    node.querySelector=q=>node.children.find(x=>q==='button'?x.tagName==='BUTTON':q==='.hwCanonicalError'?x.className==='hwCanonicalError':false)||null;
    return node;
  };
  for(const node of h.ids.values())decorate(node);
  for(const id of ['hwAddRow','hwRemoveRow','hwReorderRows'])h.ids.set(id,decorate(factory.element(id)));
  const inputs=['hwBook','hwThis','hwPctRange','hwNext'].map(id=>decorate(factory.element(id)));
  ctx.document.createElement=tag=>{const node=decorate(factory.element());node.tagName=tag.toUpperCase();return node;};
  const queryAll=ctx.document.querySelectorAll;
  ctx.document.querySelectorAll=q=>q==='#hwBody input, #hwBody select'?inputs:queryAll(q);
  ctx.__mount=()=>{mounts++;};
  ctx.__render=()=>renderModes.push(vm.runInContext('canonicalHomework.mode',ctx));
  vm.runInContext('mountAssistantThread=()=>__mount(); renderHwTable=()=>__render();',ctx);
  h.window.showStudentTooltipForSid=sid=>reveals.push({
    sid, ready:vm.runInContext('logModalReady',ctx),
    mode:vm.runInContext('canonicalHomework.mode',ctx),
    renderedMode:renderModes.at(-1),
  });
  ctx.fetch=(url,init={})=>{
    assert.equal(init.method||'GET','GET','load verification can issue only synthetic GETs');
    assert.equal(init.cache,'no-store');
    let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
    reads.push({url:String(url),resolve,reject});return promise;
  };
  const finish=(request,data,status=200)=>request.resolve({ok:status>=200&&status<300,status,json:async()=>cloned(data),text:async()=>JSON.stringify(data)});
  const pending=url=>reads.findLast(r=>r.url===url);
  const start=(sid='A',date=DATE,opts={})=>h.window.openRecordPopupForRow(row(sid,date),opts);
  const finishInitial=(sid='A',date=DATE,history=true,override=null)=>{
    finish(pending('/api/progress?sid='+sid),{[date]:{[sid]:{MID:'none',__manualProgressMids:{MID:true},unknown:'진도 보존'}}});
    finish(pending('/api/admin/student-homework?date='+date+'&sid='+sid),{},404);
    finish(pending('/api/logs?sid='+sid),override?override.data:history?{[date]:{[sid]:{notes:sid+' 권위 메모',homeworkTable:[],unknown:{keep:'한글'}}}}:{error:'injected history500'},override?override.status:history?200:500);
  };
  const ready=()=>vm.runInContext('logModalReady',ctx);
  const warning=()=>h.ids.get('hwWrap').querySelector('.hwCanonicalError');
  return {...h,ctx,reads,reveals,renderModes,inputs,finish,pending,start,finishInitial,ready,warning,mounts:()=>mounts,advance:ms=>{clock+=ms;}};
};

{
  const f=make(), opening=f.window.openStudentPopupsForRow(row());
  same(f.reveals,[{sid:'A',ready:false,mode:'loading',renderedMode:'loading'}],'unified opener shows cached homework immediately, before any authority resolves');
  same(f.inputs.map(x=>x.disabled),[true,true,true,true],'immediate cached display never unlocks editing without authority');
  same(f.opening.map(x=>x.step),['video-open','test-open'],'video/test launches stay independent of homework readiness');
  f.finish(f.pending('/api/logs?sid=A'),{[DATE]:{A:{notes:'authority',homeworkTable:[]}}});await turn();
  same(f.reveals.length,1,'waiting for canonical authority must not hide or republish the tooltip');
  f.finish(f.pending('/api/admin/student-homework?date='+DATE+'&sid=A'),{ok:true,assignments:[]});await turn();
  same([f.ready(),f.renderModes.at(-1),f.reveals.length],[true,'canonical',1],'authority updates already-visible homework without waiting for progress or republishing the tooltip');
  f.finish(f.pending('/api/progress?sid=A'),{});await opening;
  same(f.reveals.length,1,'late progress must not republish the unified homework tooltip');cases++;
}
{
  const f=make(), opening=f.start('A',DATE,{layout:'student-work'});
  f.finishInitial('A',DATE,false);await turn();
  f.finish(f.pending('/api/logs/entry?date='+DATE+'&sid=A'),{error:'entry500'},500);await opening;
  same(f.reveals.map(x=>[x.sid,x.ready,x.mode]),[['A',false,'loading']],'unified error/retry remains in the already-visible target panel');
  same([!!f.warning(),f.ids.get('logSave').disabled,f.inputs[1].disabled],[true,true,true],'failed unified reveal remains visibly locked');cases++;
}
{
  const f=make(), old=f.start('A',DATE,{layout:'student-work'}), fresh=f.start('B',BDATE,{layout:'student-work'});
  f.finishInitial('B',BDATE);await fresh;f.finishInitial('A',DATE);await old;
  same(f.reveals.map(x=>x.sid),['A','B'],'late old student must not republish or replace the current unified panel');cases++;
}
{
  const f=make(), opening=f.start('A',DATE,{layout:'student-work'});
  f.window.closeStudentWorkPopups();f.finishInitial();await opening;
  same(f.reveals.map(x=>x.sid),['A'],'closing after immediate display must not reopen the unified tooltip');cases++;
}
{
  const f=make(), opening=f.start();
  same(f.reveals.map(x=>[x.sid,x.mode]),[['A','loading']],'standalone legacy popup retains its immediate loading presentation');
  f.finishInitial();await opening;cases++;
}

// Exercise the actual renderer's hydration branch with a minimal synthetic DOM.
// Preview nodes are seeded literally; a whole-table write clears them and is counted.
const makeRender = (books=['교재 A']) => {
  const f=make();
  class Node {
    constructor(tag='div',classes='') {
      this.tagName=tag.toUpperCase();this.classes=new Set(classes.split(/\s+/).filter(Boolean));
      this.children=[];this.dataset={};this.style={};this.attrs={};this.value='';this.disabled=false;this.listeners={};
      this.classList={contains:x=>this.classes.has(x),add:(...xs)=>xs.forEach(x=>this.classes.add(x)),remove:(...xs)=>xs.forEach(x=>this.classes.delete(x)),toggle:(x,on)=>{if(on===undefined)on=!this.classes.has(x);if(on)this.classes.add(x);else this.classes.delete(x);return on;}};
      this.ownerDocument=f.ctx.document;
    }
    set className(x){this.classes=new Set(x.split(/\s+/).filter(Boolean));}
    get className(){return [...this.classes].join(' ');}
    append(...xs){xs.forEach(x=>{x.parent=this;this.children.push(x);});}
    setAttribute(k,v){this.attrs[k]=String(v);}
    removeAttribute(k){delete this.attrs[k];}
    addEventListener(k,fn){(this.listeners[k]||=[]).push(fn);}
    remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);}
    querySelectorAll(selector){
      const matches=node=>selector.split(',').some(part=>{const q=part.trim().split(/\s+/).at(-1);return q.startsWith('.')?node.classes.has(q.slice(1)):node.tagName===q.toUpperCase();});
      const found=[];const walk=node=>node.children.forEach(child=>{if(matches(child))found.push(child);walk(child);});walk(this);return found;
    }
    querySelector(q){return this.querySelectorAll(q)[0]||null;}
  }
  const host=new Node('div','is-hydrating');host.__homeworkRenderKey='literal cached preview';
  let writes=0;Object.defineProperty(host,'innerHTML',{get:()=>'',set:()=>{writes++;host.children=[];}});
  books.forEach(book=>{
    const item=new Node('div','hwItem');item.dataset={deleted:'0',sleeping:'0'};
    for(const cls of ['hwBook','hwThis','hwComment','hwNext']){const input=new Node('input',cls);input.value=cls==='hwBook'?book:'';item.append(input);}
    const wrap=new Node('div','pctWrap');wrap.dataset.empty='1';wrap.append(new Node('span','pctBubble'),new Node('input','hwPctRange'));item.append(wrap);host.append(item);
  });
  f.ids.set('hwBody',host);
  const queryAll=f.ctx.document.querySelectorAll;
  f.ctx.document.querySelectorAll=q=>q.startsWith('#hwBody ')?host.querySelectorAll(q.replaceAll(/#hwBody\s+/g,'')):queryAll(q);
  f.ctx.document.createElement=tag=>new Node(tag);
  const actualFunction=name=>{const start=proposed.indexOf(`function ${name}(`),end=proposed.indexOf('\nfunction ',start+1);assert.ok(start>=0);return proposed.slice(start,end<0?undefined:end);};
  vm.runInContext(actualFunction('renderHwTable')+'\n'+actualFunction('collectHwTable'),f.ctx);
  return {...f,host,render:(rows,sleeping=[])=>f.ctx.renderHwTable(rows,sleeping),tableWrites:()=>writes};
};
{
  const f=makeRender(), item=f.host.querySelector('.hwItem'), book=item.querySelector('.hwBook'), current=item.querySelector('.hwThis');
  f.render([{book:'교재 A',this:'현재 숙제',pct:'',next:'다음 숙제',unknown:{latest:true},_ph:{this:'지난 숙제',pct:'60',next:'이전 다음 숙제'}}]);
  same(f.tableWrites(),0,'same-book hydration never replaces the preview table');
  assert.equal(f.host.querySelector('.hwBook'),book);assert.equal(f.host.querySelector('.hwThis'),current);assertions+=2;
  same([current.value,current.placeholder,item.querySelector('.hwNext').value,item.querySelector('.hwPctRange').value,item.querySelector('.pctWrap').dataset.empty],['현재 숙제','지난 숙제','다음 숙제','60','1'],'same nodes receive authoritative values and previous-homework placeholders');
  same(f.ctx.collectHwTable()[0].unknown,{latest:true},'in-place hydration refreshes unknown metadata used by save');cases++;
}
{
  const f=makeRender(), item=f.host.querySelector('.hwItem'), input=item.querySelector('.hwThis');
  f.ctx.__assignments=[{id:'new-id',sourceRowId:'source-row',revision:7,title:'권위 숙제',scope:'20쪽',status:'assigned',dueAt:null}];
  vm.runInContext("canonicalHomework.mode='canonical';canonicalHomework.assignments=__assignments;",f.ctx);
  f.render([{book:'교재 A',this:'권위 내용',assignmentId:'new-id',unknown:{keep:'latest'}}]);
  same(f.tableWrites(),0,'canonical hydration appends details without replacing gray legacy inputs');
  assert.equal(item.querySelector('.hwThis'),input);assertions++;
  same([item.querySelectorAll('.hwCanonical').length,item.__homeworkAssignment.id,item.__homeworkAssignment.revision,item.__homeworkSourceRowId],[1,'new-id',7,'source-row'],'canonical editor receives current identity/revision/source metadata');
  same(f.ctx.collectHwTable()[0].assignmentId,'new-id','legacy log projection keeps the current canonical link');cases++;
}
{
  const f=makeRender();vm.runInContext("logModalAccessMode='all-students-readonly';canonicalHomework.mode='legacy';",f.ctx);
  f.render([{book:'교재 A',this:'권위 내용'}],['교재 A']);
  same([f.tableWrites(),f.host.querySelector('.hwItem').dataset.sleeping],[0,'1'],'sleep/read-only hydration preserves the row and sleeping state');
  same(f.host.querySelectorAll('input').every(x=>x.disabled),true,'reused read-only/sleeping inputs remain locked');cases++;
}
for(const shape of ['new-session','new-book','row-count','not-hydrating']) {
  const f=makeRender();let rows=[{book:'교재 A'}];
  if(shape==='new-session')f.host.__homeworkRenderKey=null;
  if(shape==='new-book')rows=[{book:'다른 교재'}];
  if(shape==='row-count')rows.push({book:'교재 B'});
  if(shape==='not-hydrating')f.host.classList.remove('is-hydrating');
  f.render(rows);
  same(f.tableWrites(),1,'whole-table generation remains the fallback for '+shape);cases++;
}
{
  const f=makeRender();vm.runInContext("canonicalHomework.mode='canonical';",f.ctx);
  f.render([{book:'교재 A',assignmentId:'missing-link'}]);
  same(vm.runInContext('canonicalHomework.mode',f.ctx),'conflict','node reuse cannot bypass missing canonical-link protection');cases++;
}

// Before the proposed fix, the actual module reproduces F05 without any write.
if(!original.includes('const logHydrationReady = hydrationResults[0]')) {
  const f=make(original), opening=f.start();f.finishInitial('A',DATE,false);await turn();
  f.finish(f.pending('/api/logs/entry?date='+DATE+'&sid=A'),{error:'injected entry500'},500);await opening;
  same([f.ready(),f.ids.get('logSave').disabled,f.ids.get('logCompleteBtn').disabled,f.inputs[1].disabled],[true,false,false,false],'negative control: old actual opener unlocks after both log reads fail');cases++;
}
{
  const f=make(), opening=f.start();
  same([f.ready(),f.ids.get('logSave').disabled,f.ids.get('logCompleteBtn').disabled],[false,true,true],'loading begins with mutation blocked');
  same(f.inputs.map(x=>x.disabled),[true,true,true,true],'loading homework controls remain disabled');
  f.finishInitial();await opening;
  same([f.ready(),f.ids.get('logSave').disabled,f.ids.get('logCompleteBtn').disabled],[true,false,false],'history authority alone preserves the legacy successful path');
  same(f.reads.map(x=>x.url).sort(),['/api/admin/student-homework?date='+DATE+'&sid=A','/api/logs?sid=A','/api/progress?sid=A'].sort(),'successful history needs no fallback GET');
  same(f.ctx.state.logs[DATE].A,{notes:'A 권위 메모',homeworkTable:[],unknown:{keep:'한글'}},'actual merge receives scoped authority and keeps unknown fields');cases++;
}
{
  const f=make(), opening=f.start();f.finishInitial('A',DATE,false);await turn();
  f.finish(f.pending('/api/logs/entry?date='+DATE+'&sid=A'),{ok:true,entry:{notes:'정상 fallback',homeworkTable:[],unknown:{keep:12}}});await opening;
  same([f.ready(),f.inputs[1].disabled],[true,false],'history failure plus entry success remains editable');
  same(f.ids.get('logNotes').value,'정상 fallback','entry fallback displays authoritative notes');
  same(f.ctx.state.logs[DATE].A.unknown,{keep:12},'entry fallback retains unknown metadata');cases++;
}
{
  const f=make(), opening=f.start();f.finishInitial('A',DATE,false);await turn();
  f.finish(f.pending('/api/logs/entry?date='+DATE+'&sid=A'),{},404);await turn();
  f.finish(f.pending('/api/logs'),{[DATE]:{A:{notes:'404 전체 로그 fallback',homeworkTable:[],unknown:'보존'}}});await opening;
  same([f.ready(),f.ids.get('logNotes').value],[true,'404 전체 로그 fallback'],'old entry endpoint 404 retains the documented whole-log fallback');cases++;
}
{
  const f=make(), opening=f.start();f.finishInitial('A',DATE,false);await turn();
  f.finish(f.pending('/api/logs/entry?date='+DATE+'&sid=A'),{error:'injected entry500'},500);await opening;
  same([f.ready(),f.ids.get('logSave').disabled,f.ids.get('logCompleteBtn').disabled],[false,true,true],'both log authorities failing preserves the ready lock');
  same(f.inputs.map(x=>x.disabled),[true,true,true,true],'both failures block homework editing');
  same(f.mounts(),1,'the separate assistant thread still mounts');
  assert.match(f.warning()?.textContent||'',/로그.*불러오지 못/);assertions++;
  await assert.rejects(f.window.saveRecordPopup(),/불러/);assertions++;
  f.ids.get('logCompleteBtn').listeners.click[0]();await turn();
  same(f.writes,[],'programmatic homework-complete handler cannot start progress/log writes');
  // External DOM changes cannot substitute for authority before video is saved.
  f.ids.get('logSave').disabled=false;f.ids.get('logModal').classList.add('student-work-layout');
  f.window.closeStudentWorkPopups({detail:{saveAll:true}});await turn();
  same(f.writes,[],'unified save rejects log-not-ready before any video/test/log/progress write');
  const retry=f.warning().querySelector('button');assert.ok(retry?.listeners.click?.length===1);assertions++;
  const previousReads=f.reads.length;retry.listeners.click[0]();await turn();
  same(f.reads.length-previousReads,3,'actual retry invalidates warm caches and starts scoped fresh reads');
  f.finishInitial();await turn();
  same([f.ready(),f.ids.get('logSave').disabled,f.ids.get('logCompleteBtn').disabled],[true,false,false],'retry success restores editing and completion');
  same(f.warning(),null,'successful retry removes the failure warning');
  same(f.inputs.map(x=>x.disabled),[false,false,false,false],'retry unlocks homework controls');cases++;
}
{
  const f=make();f.ctx.prefetchLogModalDataForRow(row());f.finishInitial();await turn();
  const before=f.reads.length;await f.start();
  same(f.reads.length,before,'a successful scoped prefetch remains valid warm authority');
  same(f.ready(),true,'warm prefetch succeeds without changing existing TTL behavior');cases++;
}
{
  const f=make(), old=f.start('A',DATE), fresh=f.start('B',BDATE);
  f.finishInitial('B',BDATE,true);await fresh;
  const accepted=cloned(f.ctx.state), note=f.ids.get('logNotes').value;
  f.finishInitial('A',DATE,true);await old;
  same(f.ctx.state,accepted,'late old history/progress do not write shared state after target switch');
  same(f.ids.get('logNotes').value,note,'late A reply cannot replace B notes');
  same(f.ready(),true,'late A cannot clear B readiness');cases++;
}
{
  const f=make(), old=f.start();f.window.closeStudentWorkPopups();
  const before=cloned(f.ctx.state);f.finishInitial('A',DATE,false);await old;
  same(f.reads.filter(r=>r.url.includes('/api/logs/entry')).length,0,'a closed failed history does not start a stale fallback');
  same(f.ctx.state,before,'closed progress/history replies do not mutate state');
  same([f.ready(),f.ids.get('logModal').style.display],[false,'none'],'closed session stays closed');cases++;
}
{
  const f=make(), opening=f.start();f.finishInitial('A',DATE,false);await turn();
  const fallback=f.pending('/api/logs/entry?date='+DATE+'&sid=A');f.window.closeStudentWorkPopups();
  const before=cloned(f.ctx.state);f.finish(fallback,{ok:true,entry:{notes:'closed stale entry',unknown:'old'}});await opening;
  same(f.ctx.state,before,'late entry fallback cannot write after close');
  same(f.warning(),null,'late failure or success cannot attach a warning after close');cases++;
}
{
  const f=make(), opening=f.start('A',DATE,{accessMode:'all-students-readonly'});f.finishInitial('A',DATE,false);await turn();
  f.finish(f.pending('/api/logs/entry?date='+DATE+'&sid=A'),{error:'entry500'},500);await opening;
  await assert.rejects(f.window.saveRecordPopup(),/불러/);assertions++;
  same(f.writes,[],'all-students context cannot save unhydrated progress');
  same(f.mounts(),1,'all-students separate assistant thread remains mounted');cases++;
}
for(const malformed of [null,[],'not a map',{ok:false,error:'shape failure'}]) {
  const f=make(), opening=f.start();f.finishInitial('A',DATE,false,{data:malformed,status:200});await turn();
  const fallback=f.pending('/api/logs/entry?date='+DATE+'&sid=A');
  assert.ok(fallback,'malformed history must invoke the existing entry fallback');assertions++;
  f.finish(fallback,{error:'entry500'},500);await opening;
  same([f.ready(),f.ids.get('logSave').disabled,f.ids.get('logCompleteBtn').disabled],[false,true,true],'malformed history plus failed fallback cannot substitute empty authority');
  same(f.inputs.map(x=>x.disabled),[true,true,true,true],'malformed authority keeps homework editing blocked');
  await assert.rejects(f.window.saveRecordPopup(),/불러/);assertions++;
  same(f.writes,[],'malformed authority cannot begin a save');cases++;
}
for(const malformed of [[], 'not an entry']) {
  const f=make(), opening=f.start();f.finishInitial('A',DATE,false);await turn();
  f.finish(f.pending('/api/logs/entry?date='+DATE+'&sid=A'),{ok:true,entry:malformed});await opening;
  same([f.ready(),f.ids.get('logSave').disabled],[false,true],'explicit malformed entry must retain the authority lock');
  same(f.reads.filter(x=>x.url==='/api/logs').length,0,'explicit malformed entry is not treated as an absent old endpoint');cases++;
}
for(const malformed of [null,[],'not a map',{ok:false,error:'shape failure'}]) {
  const f=make(), opening=f.start();f.finishInitial('A',DATE,false);await turn();
  f.finish(f.pending('/api/logs/entry?date='+DATE+'&sid=A'),{},404);await turn();
  f.finish(f.pending('/api/logs'),malformed);await opening;
  same([f.ready(),f.ids.get('logSave').disabled],[false,true],'malformed whole-log fallback remains a failed authority');
  same(f.inputs[1].disabled,true,'malformed whole-log fallback cannot unlock homework');cases++;
}
{
  const f=make();f.ctx.state.logs[DATE].A={notes:'캐시 보존',homeworkTable:[],unknown:{keep:'빈 map 기존 merge'}};
  const opening=f.start();f.finishInitial('A',DATE,true,{data:{},status:200});await opening;
  same([f.ready(),f.ids.get('logSave').disabled],[true,false],'legitimate empty history map is a successful read');
  same(f.ctx.state.logs[DATE].A,{notes:'캐시 보존',homeworkTable:[],unknown:{keep:'빈 map 기존 merge'}},'empty history map retains the existing narrow merge semantics');cases++;
}
{
  const f=make(), opening=f.start();f.finishInitial('A',DATE,false);await turn();
  f.finish(f.pending('/api/logs/entry?date='+DATE+'&sid=A'),{},404);await turn();
  f.finish(f.pending('/api/logs'),{});await opening;
  same([f.ready(),f.ids.get('logSave').disabled],[true,false],'legitimate empty whole-log fallback remains successful');
  same(f.ctx.state.logs[DATE].A,{},'legitimate absent target remains an authoritative empty entry');cases++;
}
{
  const f=make(), opening=f.start();f.ctx.getAdminDate=()=>BDATE;f.finishInitial();await opening;
  f.edit('A');await f.window.saveRecordPopup();
  same(f.writes.map(x=>[x.step,x.date,x.sid]),[['progress',DATE,'A'],['log',DATE,'A']],'successful save preserves row-frozen date/SID after date-bar change');cases++;
}
console.log(JSON.stringify({ok:true,suite:'actual-log-popup-hydration',cases,assertions,source:proposedPath,sha256:crypto.createHash('sha256').update(proposed).digest('hex'),evidence:'actual module loaders/cache/epoch/projection/open/close/locking/save owners; layout stubs and synthetic GET/write ledgers; no HTTP, browser or runtime I/O'},null,2));
