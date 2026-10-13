import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';

const args = process.argv.slice(2);
const option = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
const repoRoot = path.resolve(option('--repo-root', process.cwd()));
const sourceDir = path.resolve(option('--source-dir', path.join(repoRoot, 'static/js/admin/features')));
const expectation = option('--expect', 'guarded');
assert.ok(['baseline', 'guarded'].includes(expectation));

const clone = value => JSON.parse(JSON.stringify(value));
const turn = () => new Promise(resolve => setImmediate(resolve));
const A = '2026-10-01', B = '2026-10-02';
const feature = name => fs.readFileSync(path.join(fs.existsSync(path.join(sourceDir, name)) ? sourceDir : path.join(repoRoot, 'static/js/admin/features'), name), 'utf8').replace(/\r\n/g,'\n');
const strip = source => source.replace(/^import\s[\s\S]*?;\n/gm,'')
  .replace(/^export\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"];\n/gm,'').replace(/\bexport\s+/g,'');
function harness(candidate, hold=''){
  let selected=A, real=A, version=1, holding=hold, now=1000;
  const failures=new Map(), overrides=new Map(), tokens=Object.fromEntries(['students','videos','updates','absent','schoolCal','weekend','makeupCarryover','extra','todayOrder','logs','logHistory','progress','progressHistory','attendance','contact','arriveTime','arriveHistory'].map(k=>[k,'A-'+k]));
  const reads=[], renders=[], doneRenders=[], warnings=[], events=new Map(), intervals=[], bound=[];
  const state={students:[],videos:[],logs:{},progress:{},updates:{},absentByDate:{},absentSlotsByDate:{},extra:{}};
  const students=n=>[{id:'S1',name:'가연'+n,day1:'목1',day2:'금1'},{id:'S2',name:'다현'+n,day1:'목1',day2:'금1'}];
  const dayProgress={
    S1:{M1:'none',M2:'skip',__manualProgressMids:{M1:true,M2:true},unknown:'보존'},
    S2:{M1:'interrupted',__manualProgressMids:{M1:true}},
  };
  const payload=(url,n)=>{
    const u=new URL(url,'http://fixture.invalid'), d=u.searchParams.get('date')||A;
    if(overrides.has(u.pathname)){const v=overrides.get(u.pathname);return typeof v==='function'?v(u,n):clone(v);}
    if(u.pathname==='/api/admin/revisions')return {date:d,revisions:{...tokens}};
    if(u.pathname==='/api/videos')return [{id:'M1',mid:'M1',title:'합성 영상'}];
    if(u.pathname==='/api/school-calendar')return {};
    if(u.pathname==='/api/students')return students(n);
    if(u.pathname==='/api/absent')return {by_date:{},by_student:{},by_slot:{}};
    if(u.pathname==='/api/updates'||u.pathname==='/api/updates/ensure-today')return {[real]:{S1:{videos:['M1'],source:'auto'}}};
    if(u.pathname==='/api/logs/unarchived-summary'||u.pathname==='/api/arrive-time/missing-leave-summary')return {rowsAvailable:true,rows:[],total:0,byDate:[]};
    if(u.pathname==='/api/logs')return {[d]:{S1:{notes:'한글 메모',done:false},S2:{done:false}}};
    if(u.pathname==='/api/progress'){
      const sid=u.searchParams.get('sid');
      return {[d]:sid?{[sid]:clone(dayProgress[sid])}:clone(dayProgress)};
    }
    if(u.pathname==='/api/today_order')return {[A]:['S2','S1'],[B]:['S2','S1']};
    if(u.pathname==='/api/attendance')return {S1:1};
    if(u.pathname==='/api/contact')return {S2:1};
    if(u.pathname==='/api/arrive-time')return u.searchParams.has('date')?{S1:'13:01',S2:'13:02'}:{[A]:{S1:'13:01',S2:'13:02'},[B]:{S1:'13:01',S2:'13:02'}};
    return {};
  };
  const fetch=(url,init={})=>{
    assert.equal(init.method||'GET',url==='/api/updates/ensure-today'?'POST':'GET'); if(url==='/api/updates/ensure-today') assert.equal(init.body,'{}');
    const value=clone(payload(String(url),version));
    const pathname=new URL(String(url),'http://fixture.invalid').pathname;
    const failure=failures.get(pathname), status=failure?.status||200;
    if(failure){if(--failure.remaining<=0)failures.delete(pathname);}
    let finish;
    const gate=new Promise(resolve=>{finish=()=>resolve({ok:status>=200&&status<300,status,json:async()=>{if(failure?.jsonError)throw new Error('synthetic json failure');return clone(value);}});});
    const read={url:String(url),method:init.method||'GET',version,finish}; reads.push(read);
    const held=holding==='all'||(holding==='students'&&url==='/api/students')||(holding==='updates'&&url.startsWith('/api/updates'));
    if(!held)finish();
    return gate;
  };
  const makeEl=()=>({dataset:{},value:'',hidden:false,children:[],textContent:'',querySelectorAll:()=>[],
    querySelector:()=>({textContent:''}),contains:()=>false,addEventListener(){},remove(){},setAttribute(){},replaceChildren(){this.children=[];},
    classList:{add(){},remove(){},toggle(){},contains:()=>false}});
  const elements=new Map(['todaySearchInput','todayWrap','doneWrap','staleDoneWarning','missingLeaveWarning','todayOperationWarnings'].map(id=>[id,makeEl()]));
  elements.get('todayOperationWarnings').children=[elements.get('staleDoneWarning'),elements.get('missingLeaveWarning')];
  const document={readyState:'complete',body:makeEl(),hidden:false,activeElement:null,
    getElementById:id=>elements.get(id)||null,querySelector:()=>null,querySelectorAll:()=>[],
    addEventListener:(type,fn)=>{if(!events.has(type))events.set(type,[]);events.get(type).push(fn);},
    dispatchEvent:event=>{for(const fn of events.get(event.type)||[])fn(event);}};
  const storage=new Map();
  const window={state,setInterval:fn=>intervals.push(fn),getComputedStyle:()=>({display:'none'}),setTimeout,addEventListener(){}};
  const context=vm.createContext({
    state,window,document,fetch,URLSearchParams,queueMicrotask,setTimeout,clearTimeout,
    Date:class extends Date {static now(){return now;}},
    localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    console:{log(){},warn:(...values)=>warnings.push(values.map(String)),error:(...values)=>warnings.push(values.map(String))},
    CustomEvent:function(type,init){this.type=type;this.detail=init?.detail;},
    getAdminDate:()=>selected,todayLocalKey:()=>real,isSelfStudyScheduledForDate:()=>false,
    api:{get:async(url,init)=>(await fetch(url,init)).json(),getStrict:async(url,label,init)=>{const r=await fetch(url,init);if(!r.ok)throw Object.assign(new Error('synthetic strict error'),{status:r.status});return r.json();},postStrict:async(url,data,label,init)=>(await fetch(url,{...init,method:'POST',body:JSON.stringify(data)})).json()},
    normalizeSearch:value=>String(value||'').trim(),searchKeyForText:String,
    todayStudentSearchKey:()=>'',matchesSearchKey:()=>true,applySearchPlaceholder(){},
    countPendingMakeupsBySid:()=>({}),scheduledMakeupStudentIdsForDate:()=>[],
    bindTodayTableEvents:fn=>bound.push(fn),renderDone:entries=>doneRenders.push(clone(entries)),
    renderToday:(list,date)=>renders.push({date,rows:list.map(s=>({id:s.id,name:s.name,progress:clone(state.progress[date]?.[s.id]||{}),
      attended:context.isAttended(date,s.id),contact:context.isContacted(date,s.id)}))}),
  });
  const stateMethods=['loadWeekendSlots','ensureAttendLoaded','ensureContactLoaded','ensureArriveLoaded','collectUnarchivedLogsByDate',
    'loadOrderMap','applySavedOrder','getSavedOrder','hasWeekday','yoilOf','plannedMinutesFor','isAttended','isContacted','isSelfStudy','isHwChecked',
    'isHwCheckRequested','hwCheckRequestedAt','truthy','labelFor','withStudentLookup'];
  const exported=vm.runInContext('(function(){'+strip(feature('today.state.js'))+'\nreturn {'+stateMethods.join(',')+'};})()',context);
  Object.assign(context,exported);
  const summary=vm.runInContext('(function(){'+strip(feature('todayDoneSummary.js'))+'\nreturn {doneEntriesFromUnarchivedSummary,missingLeaveWarningText,recordCleanupWarningText,missingLeaveWarningRows:typeof missingLeaveWarningRows==="function"?missingLeaveWarningRows:()=>[]};})()',context);
  Object.assign(context,summary);
  vm.runInContext(strip(feature('todayPolling.js')),context,{filename:'todayPolling.js'});
  const original=feature('today.js');
  vm.runInContext(strip(original),context,{filename:'today.js'});
  return {context,reads,renders,doneRenders,warnings,state,bound,auto:()=>intervals[0](),
    setNow:v=>{now=v;},token:(k,v)=>{tokens[k]=v;},override:(p,v)=>overrides.set(p,v),
    fail:(p,status=503,remaining=1,jsonError=false)=>failures.set(p,{status,remaining,jsonError}),
    poller:()=>vm.runInContext('revisionPoller',context),
    load:options=>context.loadTodayAndRender(options),
    count:prefix=>reads.filter(r=>r.url.startsWith(prefix)).length,
    setDate:date=>{selected=date;},setReal:date=>{real=date;},mutate:()=>{version++;},
    release:()=>{holding='';reads.forEach(r=>r.finish());},
    dispatch:(type,detail)=>document.dispatchEvent({type,detail}),
  };
}

// All modules above are whole current entrypoint/owners in a VM. HTTP and DOM
// are literal synthetic adapters; no app/server/browser/runtime file is used.
const warningExpectation=option('--expect-warning-retry','guarded');
assert.ok(['baseline','guarded'].includes(warningExpectation));
const prior='2026-09-30';
const doneSummary={rowsAvailable:true,total:1,byDate:[{date:prior,count:1}],
  rows:[{date:prior,sid:'S1',entry:{done:true,notes:'과거 완료',unknown:false,n:0}}]};
const observations=[];
let passes=0, failures=0;
async function test(name,check){try{const detail=await check();passes++;console.log('PASS '+name);if(detail)observations.push({name,...detail});}catch(error){failures++;console.error('FAIL '+name+' '+error.stack);}}
async function fresh(){const h=harness('guarded');h.override('/api/logs/unarchived-summary',doneSummary);await h.auto();assert.ok(h.poller().lastFull>0,'initial ACK: '+JSON.stringify({ack:h.poller().acknowledged,reads:h.reads.map(r=>r.url),warnings:h.warnings}));h.reads.length=0;h.renders.length=0;h.doneRenders.length=0;h.setNow(31000);return h;}

await test('actual idle timer reads exactly revisions and does not render or fetch payloads',async()=>{
  const h=await fresh();await h.auto();
  assert.deepEqual(h.reads.map(r=>r.url),['/api/admin/revisions?date='+A]);
  assert.equal(h.renders.length,0);return {requests:h.reads.map(r=>r.url)};
});
await test('contact-only change reads contact only and retains cached historical done rows',async()=>{
  const h=await fresh();h.token('contact','B-contact');await h.auto();
  assert.deepEqual(h.reads.map(r=>r.url),['/api/admin/revisions?date='+A,'/api/contact?date='+A]);
  assert.ok(h.doneRenders.length>0);
  assert.ok(h.doneRenders.every(rows=>rows.length===1&&rows[0][0]==='S1'&&rows[0][2]===prior),'historical done row must remain at every render');
  return {requests:h.reads.map(r=>r.url),doneDates:h.doneRenders.map(rows=>rows[0][2])};
});
await test('failed contact uses local fallback without token acknowledgment and retries next timer',async()=>{
  const h=await fresh();h.token('contact','B-contact');h.fail('/api/contact');await h.auto();
  assert.equal(h.poller().acknowledged.contact,'A-contact');h.reads.length=0;h.setNow(61000);await h.auto();
  assert.deepEqual(h.reads.map(r=>r.url),['/api/admin/revisions?date='+A,'/api/contact?date='+A]);
  assert.equal(h.poller().acknowledged.contact,'B-contact');
});
await test('progress-history deletion removes selected SID branches and preserves unrelated SID fields',async()=>{
  const h=await fresh();h.state.progress[prior]={S1:{M1:'done',tests:{T1:'done'}},S2:{M2:'none',unknown:0},OUTSIDE:{unknown:false,n:0}};
  h.override('/api/progress',u=>{
    const sid=u.searchParams.get('sid');
    if(sid==='S1')return {};
    if(sid==='S2')return {[prior]:{S2:{M2:'none',unknown:0}}};
    throw new Error('unexpected date/batch progress request '+u.href);
  });
  h.token('progressHistory','B-progress-history');await h.auto();
  assert.deepEqual(h.reads.map(r=>r.url),['/api/admin/revisions?date='+A,'/api/progress?sid=S2','/api/progress?sid=S1']);
  assert.equal(Object.hasOwn(h.state.progress[prior],'S1'),false);
  assert.deepEqual(clone(h.state.progress[prior].S2),{M2:'none',unknown:0});
  assert.deepEqual(clone(h.state.progress[prior].OUTSIDE),{unknown:false,n:0});
  assert.equal(h.poller().acknowledged.progressHistory,'B-progress-history');
});
await test('exact padded SID history replacement preserves another actual numeric SID',async()=>{
  const h=await fresh();h.state.progress[prior]={'007':{M1:'done'},'7':{M1:'skip',unknown:false,n:0}};
  h.context.replaceProgressHistory(['007'],{});
  assert.equal(Object.hasOwn(h.state.progress[prior],'007'),false);
  assert.deepEqual(clone(h.state.progress[prior]['7']),{M1:'skip',unknown:false,n:0});
});
await test('modal changedStores refresh reads only the two warning endpoints',async()=>{
  const h=await fresh();await h.load({reason:'event',changedStores:['logHistory','arriveHistory']});
  assert.deepEqual(h.reads.map(r=>r.url),['/api/logs/unarchived-summary?exclude_date='+A,'/api/arrive-time/missing-leave-summary?exclude_date='+A]);
});
await test('a failed dependent missing-leave warning retains trigger token and retries before 10 minutes',async()=>{
  const h=await fresh();h.token('students','B-students');h.fail('/api/arrive-time/missing-leave-summary');await h.auto();
  const afterFailure=h.poller().acknowledged.students;
  const first=h.reads.map(r=>r.url);h.reads.length=0;h.setNow(61000);await h.auto();const retry=h.reads.map(r=>r.url);
  if(warningExpectation==='baseline'){
    assert.equal(afterFailure,'B-students');assert.deepEqual(retry,['/api/admin/revisions?date='+A]);
  }else{
    assert.equal(afterFailure,'A-students','students token acknowledged although its dependent warning failed');
    assert.deepEqual(retry,['/api/admin/revisions?date='+A,'/api/students','/api/arrive-time/missing-leave-summary?exclude_date='+A]);
    assert.equal(h.poller().acknowledged.students,'B-students');
  }
  return {expectation:warningExpectation,afterFailure,first,retry};
});
await test('rowsAvailable false dependent warning also retains source token until successful retry',async()=>{
  const h=await fresh();h.token('extra','B-extra');h.override('/api/arrive-time/missing-leave-summary',{rowsAvailable:false,rows:[],total:0});await h.auto();
  const afterFailure=h.poller().acknowledged.extra;
  h.override('/api/arrive-time/missing-leave-summary',{rowsAvailable:true,rows:[],total:0,byDate:[]});h.reads.length=0;h.setNow(61000);await h.auto();
  if(warningExpectation==='baseline'){assert.equal(afterFailure,'B-extra');assert.deepEqual(h.reads.map(r=>r.url),['/api/admin/revisions?date='+A]);}
  else{assert.equal(afterFailure,'A-extra');assert.deepEqual(h.reads.map(r=>r.url),['/api/admin/revisions?date='+A,'/api/extra-attend','/api/arrive-time/missing-leave-summary?exclude_date='+A]);}
});
await test('invalid historical done summary cannot acknowledge logHistory or replace the authoritative cache',async()=>{
  const h=await fresh();h.token('logHistory','B-log-history');h.override('/api/logs/unarchived-summary',{rowsAvailable:false,rows:[],total:0});await h.auto();
  const acknowledged=h.poller().acknowledged.logHistory;
  if(warningExpectation==='baseline')assert.equal(acknowledged,'B-log-history');
  else assert.equal(acknowledged,'A-logHistory','invalid summary acknowledged changed log history');
  h.override('/api/logs/unarchived-summary',doneSummary);h.reads.length=0;h.setNow(61000);await h.auto();
  if(warningExpectation==='guarded')assert.equal(h.count('/api/logs/unarchived-summary'),1);
});
console.log(JSON.stringify({verifier:'whole actual today/today.state/todayDoneSummary/TodayRevisionPoller',warningExpectation,passes,failures,observations}));
if(failures)process.exitCode=1;
