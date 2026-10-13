import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const args = process.argv.slice(2);
const option = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
const repoRoot = path.resolve(option('--repo-root', process.cwd()));
const sourceDir = path.resolve(option('--source-dir', path.join(repoRoot, 'static/js/admin/features')));
const expectation = option('--expect', 'guarded');
assert.ok(['baseline', 'guarded'].includes(expectation));

const clone = value => JSON.parse(JSON.stringify(value));
const turn = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const date = '2026-10-01', sid = '1001';
const query = new URLSearchParams({sid}).toString();
const progressUrl = '/api/progress?' + query;
function harness(proposed) {
  let clock = 1000;
  class Clock extends Date { static now() { return clock; } }
  const reads = [], window = {addEventListener(){}}, state = {students:[], logs:{}, progress:{}};
  const contexts = {};
  for (const owner of ['logModal','videoModal','testModal']) {
    let source = fs.readFileSync(path.join(sourceDir, owner + '.js'), 'utf8');
    source = source.replace(/^import\s[\s\S]*?;\r?\n/gm, '').replace(/\bexport\s+/g, '');
    const context = vm.createContext({
      window, state, Date: Clock, URLSearchParams, setTimeout, clearTimeout, DEFAULT_TERM: '기말',
      getAdminDate: () => date,
      document: {body:{addEventListener(){}}, addEventListener(){}, getElementById:()=>null, querySelector:()=>null, querySelectorAll:()=>[]},
      console: {log(){}, warn(){}, error(){}},
      fetch: (url, init={}) => {
        assert.equal(init.method || 'GET', 'GET');
        assert.equal(init.cache, 'no-store');
        const gate = deferred(); reads.push({url:String(url), gate}); return gate.promise;
      },
    });
    vm.runInContext(source, context, {filename:owner + '.js'});
    contexts[owner] = context;
  }
  window.invalidateVideoAssignmentPopupCache = contexts.videoModal.invalidateVideoModalHydrationCaches;
  const finish = (read, data) => read.gate.resolve({
    ok:true, status:200, json:async()=>clone(data), text:async()=>JSON.stringify(data),
  });
  return {reads, contexts, advance:ms=>{clock+=ms;}, finish,
    cached:(owner,url=progressUrl)=>contexts[owner].fetchJSONCached(url),
    homework:(day=date,student=sid)=>contexts.logModal.fetchCanonicalHomeworkForLogCached(day,student)};
}
async function run(proposed) {
  const observed = {};
  for (const owner of ['logModal','videoModal','testModal','homework']) {
    const h = harness(proposed), load = () => owner==='homework'?h.homework():h.cached(owner);
    const data = owner==='homework'?{ok:true,assignments:[]}:{value:'한글', M1:'none', M2:'skip', unknown:'보존'};
    const a = load(); h.advance(3000); const b = load();
    const pending = h.reads.length;
    h.reads.forEach(read=>h.finish(read,data));
    const results = await Promise.all([a,b]); assert.deepEqual(clone(results[0]),clone(results[1]));
    h.advance(2499); const c = load(); const warm=h.reads.length;
    h.reads.forEach(read=>h.finish(read,data)); await c;
    h.advance(1); const d=load(); const expiry=h.reads.length;
    h.reads.forEach(read=>h.finish(read,data)); await d;
    observed[owner]={pending,warm,expiry};
    if (proposed) assert.deepEqual(observed[owner],{pending:1,warm:1,expiry:2});
    else assert.equal(pending,2);
  }
  {
    const h=harness(proposed), row={dataset:{sid,date}};
    const prefetch=()=>{h.contexts.logModal.prefetchLogModalDataForRow(row); return Promise.all([
      h.contexts.videoModal.prefetchVideoModalDataForRow(row),
      h.contexts.testModal.prefetchTestModalDataForRow(row),
    ]);};
    const a=prefetch(), unique=new Set(h.reads.map(r=>r.url)).size;
    h.advance(3000); const b=prefetch();
    observed.prefetch={unique,requests:h.reads.length};
    h.reads.forEach(read=>h.finish(read,{ok:true,assignments:[]}));
    await Promise.all([a,b]); await turn();
    assert.equal(unique,9); assert.equal(h.reads.length,proposed?9:18);
  }
  for (const owner of ['logModal','videoModal','testModal','homework']) {
    for (const oldFailure of [false,true]) {
      const h=harness(proposed), load=()=>owner==='homework'?h.homework():h.cached(owner);
      const old=load(), settled=Promise.allSettled([old]);
      if (owner==='homework'||owner==='logModal') h.contexts.logModal.invalidateLogModalHydrationCaches(date,sid);
      else if(owner==='videoModal') h.contexts.videoModal.invalidateVideoModalHydrationCaches(date,sid);
      else h.contexts.testModal.invalidateStudentWorkFetchCache(progressUrl);
      const fresh=load(); assert.equal(h.reads.length,2);
      const data=owner==='homework'?{ok:true,assignments:[],pendingOperation:{marker:'새 저장'}}:{marker:'새 저장'};
      h.finish(h.reads[1],data); const result=await fresh;
      if(oldFailure) h.reads[0].gate.reject(new Error('old read failure'));
      else h.finish(h.reads[0],owner==='homework'?{ok:true,assignments:[]}:{marker:'이전'});
      await settled; assert.deepEqual(clone(await load()),clone(result)); assert.equal(h.reads.length,2);
    }
    for(const failure of ['network','http']) {
      const h=harness(proposed), load=()=>owner==='homework'?h.homework():h.cached(owner);
      const settled=Promise.allSettled([load(),load()]); assert.equal(h.reads.length,1);
      if(failure==='network') h.reads[0].gate.reject(new Error('synthetic transport failure'));
      else h.reads[0].gate.resolve({ok:false,status:503,json:async()=>({error:'503'}),text:async()=>'503'});
      assert.ok((await settled).every(r=>r.status==='rejected'));
      const retry=load(); assert.equal(h.reads.length,2);
      h.finish(h.reads[1],owner==='homework'?{ok:true,assignments:[]}:{version:2}); await retry;
    }
  }
  {
    const h=harness(proposed);
    const loads=[h.cached('logModal'),h.cached('videoModal','/api/progress?sid=B'),
      h.cached('testModal','/api/logs?'+query), h.homework(),h.homework('2026-10-02'),h.homework(date,'B')];
    assert.equal(h.reads.length,6);
    h.reads.forEach(r=>h.finish(r,{ok:true,assignments:[]})); await Promise.all(loads);
    h.contexts.logModal.invalidateLogModalHydrationCaches(date,sid);
    await Promise.all([h.cached('videoModal','/api/progress?sid=B'),h.homework('2026-10-02'),h.homework(date,'B')]);
    assert.equal(h.reads.length,6);
  }
  {
    const h=harness(proposed), prefetch=h.cached('videoModal');
    const open=h.contexts.videoModal.fetchJSONForVideoOpen(progressUrl); await turn();
    assert.equal(h.reads.length,1);
    const next=h.contexts.videoModal.fetchJSONForVideoOpen(progressUrl); assert.equal(h.reads.length,2);
    h.finish(h.reads[1],{marker:'새 팝업'}); assert.deepEqual(clone(await next),{marker:'새 팝업'});
    h.finish(h.reads[0],{marker:'이전 prefetch'}); await Promise.all([prefetch,open]);
    const after=h.cached('testModal'); assert.equal(h.reads.length,3); h.finish(h.reads[2],{}); await after;
  }
  {
    const h=harness(proposed), context=h.contexts.logModal;
    const old=context.hydrateProgressHistoryForSid(sid);
    context.invalidateLogModalHydrationCaches(date,sid);
    const fresh=context.hydrateProgressHistoryForSid(sid);
    h.finish(h.reads[1],{[date]:{[sid]:{M1:'none',__manualProgressMids:{M1:true},unknown:'새 저장'}}});
    await fresh;
    h.finish(h.reads[0],{[date]:{[sid]:{M1:'done',unknown:'이전 응답'}}});
    await old;
    observed.latePrefetchConsumer=context.state.progress[date][sid];
    assert.equal(observed.latePrefetchConsumer.M1,(proposed==='epoch'||proposed==='guarded')?'none':'done','late prefetch must not overwrite a newer manual white result when semantic invalidation epochs are guarded');
  }
  {
    const h=harness(proposed), context=h.contexts.testModal, save={disabled:false}, row={dataset:{sid,date}};
    context.state.students=[{id:sid,name:'QA 학생',curriculum:'대수'}];
    context.state.progress={[date]:{[sid]:{tests:{'기존 시험':{status:'assigned'}}}}};
    const rules=fs.readFileSync(path.join(repoRoot, 'static/js/admin/features/testAssignmentRules.js'),'utf8').replace(/\bexport\s+/g,'');
    Object.assign(context,vm.runInContext('(function(){'+rules+'\nreturn {normalizeConfig, collectTestCatalog, isTermCategory, isUnitCategory};})()',context));
    context.$=id=>id==='testSave'?save:{disabled:true};
    vm.runInContext([
      'ensureModal=()=>{};',
      'renderLoadingState=()=>{ $("testSave").disabled=true; };',
      'setModalOpen=renderAll=syncSelectedFromProgress=applyRuleDefaults=()=>{};',
      'activeStudentCurriculumSubject=()=>"대수";',
      'defaultTermFromSchoolCalendar=()=>"기말";',
      'restorePreferredInitialTestView=()=>true;',
    ].join('\n'),context);
    const open=context.openModalForRow(row);
    assert.equal(save.disabled,true,'the real opener begins with editing locked');
    assert.equal(h.reads.length,4);
    h.reads.forEach(read=>read.gate.resolve({ok:false,status:503,json:async()=>({error:'503'}),text:async()=>'503'}));
    await Promise.allSettled([open]);
    observed.failedPopupEditLock={testSaveDisabledAfter503:save.disabled};
    assert.equal(save.disabled,proposed==='guarded','guarded test popup must retain its edit lock after failed hydration');
    if(proposed==='guarded'){
      vm.runInContext('testSelectionTouched = true;',context);
      const beforeSaveReads=h.reads.length;
      const saving=Promise.allSettled([context.saveModal({showPopup:false})]);
      await turn();
      assert.equal(h.reads.length,beforeSaveReads,'programmatic save after failed hydration must not start any read/write command');
      await saving;
    }
  }
  return observed;
}


(async()=>{
  const observations=await run(expectation==='baseline'?false:'guarded');
  console.log(JSON.stringify({verifier:'popup actual-source VM',expectation,sourceDir,
    timing:'injected clock/deferred; no runtime files/HTTP/browser timing',observations}));
})().catch(error=>{console.error(error);process.exitCode=1;});
