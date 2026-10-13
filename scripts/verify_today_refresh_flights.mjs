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
  let selected=A, real=A, version=1, holding=hold;
  const reads=[], renders=[], events=new Map(), intervals=[], bound=[];
  const state={students:[],videos:[],logs:{},progress:{},updates:{},absentByDate:{},absentSlotsByDate:{},extra:{}};
  const students=n=>[{id:'S1',name:'가연'+n,day1:'목1',day2:'금1'},{id:'S2',name:'다현'+n,day1:'목1',day2:'금1'}];
  const dayProgress={
    S1:{M1:'none',M2:'skip',__manualProgressMids:{M1:true,M2:true},unknown:'보존'},
    S2:{M1:'interrupted',__manualProgressMids:{M1:true}},
  };
  const payload=(url,n)=>{
    const u=new URL(url,'http://fixture.invalid'), d=u.searchParams.get('date')||A;
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
    if(u.pathname==='/api/arrive-time')return {S1:'13:01',S2:'13:02'};
    return {};
  };
  const fetch=(url,init={})=>{
    assert.equal(init.method||'GET',url==='/api/updates/ensure-today'?'POST':'GET'); if(url==='/api/updates/ensure-today') assert.equal(init.body,'{}');
    const value=clone(payload(String(url),version));
    let finish;
    const gate=new Promise(resolve=>{finish=()=>resolve({ok:true,status:200,json:async()=>clone(value)});});
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
    localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    console:{log(){},warn(){},error(){}},
    CustomEvent:function(type,init){this.type=type;this.detail=init?.detail;},
    getAdminDate:()=>selected,todayLocalKey:()=>real,isSelfStudyScheduledForDate:()=>false,
    api:{get:async(url,init)=>(await fetch(url,init)).json(),getStrict:async(url,label,init)=>(await fetch(url,init)).json(),postStrict:async(url,data,label,init)=>(await fetch(url,{...init,method:'POST',body:JSON.stringify(data)})).json()},
    normalizeSearch:value=>String(value||'').trim(),searchKeyForText:String,
    todayStudentSearchKey:()=>'',matchesSearchKey:()=>true,applySearchPlaceholder(){},
    countPendingMakeupsBySid:()=>({}),scheduledMakeupStudentIdsForDate:()=>[],
    bindTodayTableEvents:fn=>bound.push(fn),renderDone(){},
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
  return {context,reads,renders,state,bound,auto:()=>intervals[0](),
    load:options=>context.loadTodayAndRender(options),
    count:prefix=>reads.filter(r=>r.url.startsWith(prefix)).length,
    setDate:date=>{selected=date;},setReal:date=>{real=date;},mutate:()=>{version++;},
    release:()=>{holding='';reads.forEach(r=>r.finish());},
    dispatch:(type,detail)=>document.dispatchEvent({type,detail}),
  };
}
async function drain(){for(let i=0;i<4;i++)await turn();}
async function run(candidate){
  const observed={};
  {
    const h=harness(candidate,'all'), options={force:true,forceDatePayloads:true,reason:'auto'};
    const pending=[h.load(options),h.load(options),h.load(options)];
    await drain(); const initial=h.reads.length; h.release(); await Promise.all(pending); await drain();
    const reference=harness(candidate); await reference.load(options); await drain();
    assert.deepEqual(clone(h.renders),clone(reference.renders));
    assert.equal(h.renders.length,1);
    assert.deepEqual(clone(h.renders[0].rows.map(r=>r.id)),['S2','S1']);
    assert.equal(h.renders[0].rows[1].progress.M1,'none');
    assert.equal(h.renders[0].rows[1].progress.M2,'skip');
    observed.identical={initialRequests:initial,totalRequests:h.reads.length,tableRenders:h.renders.length};
    assert.equal(initial,candidate?11:30);
    assert.equal(h.reads.slice(0,initial).filter(r=>r.url==='/api/today_order').length,candidate?1:0,
      'independent order read starts before the held required reads settle');
    const count=h.count('/api/extra-attend');
    await h.load(options); await drain(); assert.equal(h.count('/api/extra-attend'),count+1,'completed today results are not a TTL cache');
  }
  {
    const h=harness(candidate,'all'), a=h.load({force:true,reason:'date'});
    await drain(); h.setDate(B); const b=h.load({force:true,reason:'date'}); await drain();
    h.release(); await Promise.all([a,b]); await drain();
    assert.ok(h.renders.every(r=>r.date===B));
    observed.dateSwitch={assignmentReads:h.count('/api/updates'),ensurePosts:h.reads.filter(r=>r.method==='POST').length,renderDates:h.renders.map(r=>r.date)}; assert.equal(observed.dateSwitch.ensurePosts,0,'selected date changes never initialize real-today assignments');
  }
  {
    const h=harness(candidate); await h.load(); await drain();
    const before=h.count('/api/logs?date=')+h.count('/api/progress?date=');
    await h.load({force:true}); await drain();
    assert.equal(h.count('/api/logs?date=')+h.count('/api/progress?date='),before,'ordinary force does not force dated logs/progress');
    await h.load({force:true,forceDatePayloads:true}); await drain();
    assert.equal(h.count('/api/logs?date=')+h.count('/api/progress?date='),before+2);
    const readonly=h.count('/api/updates'); await h.load({force:true,reason:'event'}); await drain();
    assert.equal(h.count('/api/updates'),readonly,'save refresh is not an auto-assignment boundary');
  }
  {
    const h=harness(candidate,'all'), weak=h.load({force:false}); await drain();
    const strong=h.load({force:true,forceDatePayloads:true}); await drain();
    h.release(); await Promise.all([weak,strong]); await drain();
    assert.equal(h.renders.length,1); assert.equal(h.count('/api/logs?date='),2,'force strengths must not share the older result');
  }
  {
    const h=harness(candidate,'students'), old=h.load({force:true}); await drain();
    h.mutate(); h.dispatch('admin:refresh',{force:true}); await drain();
    let held=h.reads.filter(r=>r.url==='/api/students');
    const beforeRelease=held.length;
    if(held.length>1){held[1].finish();await drain();}
    held[0].finish(); await old; h.release(); await drain();
    assert.equal(h.count('/api/students'),2,'post-save refresh starts an independent read');
    observed.mutation={requestsBeforeOldRelease:beforeRelease,finalStudentName:h.state.students.find(s=>s.id==='S1')?.name,
      tableStudentName:h.renders.at(-1)?.rows.find(s=>s.id==='S1')?.name};
    if(candidate) assert.equal(observed.mutation.finalStudentName,'가연2');
    else assert.equal(observed.mutation.finalStudentName,'가연1','baseline reproduces shared-state reversal');
  }
  {
    const h=harness(candidate,'students'), old=h.load({force:true}); await drain();
    h.mutate(); const saved=h.bound[0]({force:true}); await drain();
    h.release(); await Promise.all([old,saved]); await drain();
    assert.equal(h.count('/api/students'),2,'row-save callback cannot join the pre-save request');
    assert.equal(h.renders.at(-1).rows.find(s=>s.id==='S1').name,'가연2');
  }
  {
    const h=harness(candidate,'updates');h.setReal(B);
    const a=h.auto(),b=h.auto();await drain();
    observed.midnight={bareUpdatesWhilePending:h.count('/api/updates')};
    assert.equal(h.count('/api/updates'),candidate?1:2);
    h.release();await Promise.all([a,b]);await drain();
    assert.ok(h.state.updates[B]);
    assert.equal(h.count('/api/updates?'),0,'assignment refresh uses explicit GET or POST, without query side effects');
  }
  {
    const h=harness(candidate,'updates'), old=h.load({force:true,reason:'date'});await drain();
    h.state.updates={[A]:{S1:{videos:['M2'],source:'manual'}}};
    h.dispatch('admin:refresh',{force:true});await drain();
    h.release();await old;await drain();
    observed.assignmentAfterSave=h.state.updates[A].S1;
    assert.equal(h.state.updates[A].S1.source,candidate?'manual':'auto','an old boundary read must not restore the pre-save snapshot');
  }
  {
    const h=harness(candidate,'updates');h.setReal(B);
    const old=h.auto();await drain();
    h.setReal('2026-10-03');const fresh=h.auto();await drain();
    const requests=h.reads.filter(r=>r.url.startsWith('/api/updates'));
    requests[1].finish();await drain();requests[0].finish();h.release();await Promise.all([old,fresh]);await drain();
    observed.boundaryReversal={dates:Object.keys(h.state.updates),bareUpdates:h.count('/api/updates')};
    assert.deepEqual(Object.keys(h.state.updates),['2026-10-03']);
    assert.equal(h.count('/api/updates'),candidate?2:3);
  }
  {
    const h=harness(candidate), original=h.context.renderToday;let fail=true;
    h.context.renderToday=(...args)=>{if(fail){fail=false;throw new Error('synthetic render failure');}return original(...args);};
    const failed=await Promise.allSettled([h.load(),h.load()]);
    assert.ok(failed.some(r=>r.status==='rejected'));
    await h.load();await drain();assert.equal(h.renders.length,1,'rejected work must be retryable');
  }
  return observed;
}


(async()=>{
  const observations=await run(expectation==='baseline'?false:'guarded');
  console.log(JSON.stringify({verifier:'today.js + actual today.state loaders VM',expectation,sourceDir,
    timing:'deferred transport; no runtime files/HTTP/browser latency',observations}));
})().catch(error=>{console.error(error);process.exitCode=1;});
