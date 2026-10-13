import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';

const paths = ['static/js/admin/features/today.js', 'static/js/shared/search.js',
  'static/js/admin/features/todaySearch.js', 'scripts/verify_today_refresh_flights.mjs'];
const original = Object.fromEntries(paths.map(p => [p, fs.readFileSync(p, 'utf8')]));
const strip = s => s.replace(/^import\s[\s\S]*?;\r?\n/gm, '').replace(/\bexport\s+/g, '');
const marker = original[paths[3]].indexOf('async function run(candidate)');
assert.ok(marker > 0, 'existing refresh fixture entry must exist');
const fixture = vm.runInNewContext('(function(){' + strip(original[paths[3]].slice(0, marker))
  + '\nreturn {harness,drain};})()', {assert, fs, vm, path, process, URL, URLSearchParams,
    setImmediate, setTimeout, clearTimeout, queueMicrotask, console});
const h = fixture.harness(true), c = h.context;
Object.assign(c, vm.runInContext('(function(){' + strip(original[paths[1]])
  + '\n' + strip(original[paths[2]]) + '\nreturn {todayStudentSearchKey,matchesSearchKey,'
  + 'normalizeSearch,searchKeyForText,applySearchPlaceholder};})()', c));
assert.equal(typeof c.todayRowSearchKey, 'function');
assert.equal(typeof c.applyTodaySearchFilter, 'function');

// Only search DOM is stubbed; actual today.js and existing transport fixture run unchanged.
const hosts = {today:{rows:[],dataset:{},contains:()=>false}, done:{rows:[],dataset:{},contains:()=>false}};
for (const host of Object.values(hosts)) host.querySelectorAll = () => host.rows;
function row(id, kind = 'today', texts = [id]) {
  const classes = new Set(), attrs = new Map();
  return {dataset:{sid:id,date:kind === 'today' ? '2026-10-01' : '2026-09-30'}, hidden:false,
    cells:texts.map(textContent => ({textContent})),
    classList:{contains:k=>classes.has(k),remove:k=>classes.delete(k),
      toggle:(k,on)=>on ? classes.add(k) : classes.delete(k)},
    getAttribute:k=>attrs.get(k) ?? null, setAttribute:(k,v)=>attrs.set(k,String(v)),
    closest:s=>s === (kind === 'done' ? '#doneWrap' : '#todayWrap') ? hosts[kind] : null};
}
function control(value = '') {
  const listeners = {};
  return {value,dataset:{},listeners,insertAdjacentElement(){},
    addEventListener:(name,fn)=>(listeners[name] ||= []).push(fn),
    emit:(name,event={})=>{for (const fn of listeners[name] || []) fn(event);}};
}
const input = control(), field = control('all'), hint = {textContent:''};
const elements = {todayWrap:hosts.today,doneWrap:hosts.done,
  todaySearchInput:input,todaySearchField:field,todaySearchHint:hint};
const oldGet = c.document.getElementById;
let mounting = true;
c.document.getElementById = id => mounting && id === 'todaySearchInput'
  ? null : elements[id] || oldGet(id);
c.document.createElement = () => ({querySelector:s=>elements[s.slice(1)] || null});
c.ensureTodaySearchControls({appendChild(){mounting=false;}});
for (const event of ['input','search','compositionend','keydown']) {
  assert.equal(input.listeners[event].length, 1, event + ' listener');
}
const rows = () => [...hosts.today.rows,...hosts.done.rows];
const visible = () => rows().filter(r=>!r.hidden && !r.classList.contains('is-search-hidden'))
  .map(r=>(r.closest('#doneWrap') ? 'done:' : 'today:') + r.dataset.sid);
function check(query, mode, expected, event = 'input') {
  input.value=query; field.value=mode; input.emit(event);
  assert.deepEqual(visible(), expected, mode + ':' + query + ' independent IDs');
  const expectedHint = query.trim() ? expected.filter(id=>id.startsWith('today:')).length
    + '/' + hosts.today.rows.length + '명 · 하원 ' + expected.filter(id=>id.startsWith('done:')).length
    + '/' + hosts.done.rows.length : '';
  assert.equal(hint.textContent, expectedHint, 'independent count');
  for (const r of rows()) {
    assert.equal(r.classList.contains('is-search-hidden'), r.hidden);
    assert.equal(r.getAttribute('aria-hidden'), r.hidden ? 'true' : 'false');
  }
}
h.state.students = [
  {id:'A',personId:'P',name:'노윤우',school:'정발고',curriculum:'미적분1',subCurriculum:'APEX'},
  {id:'B',personId:'Q',name:'이주빈',school:'백석고',curriculum:'대수',subCurriculum:'A:Ble'},
  {id:'C',personId:'P',name:'노윤우',school:'정발고',curriculum:'기하',subCurriculum:'APEX'},
];
hosts.today.rows = h.state.students.map(s=>row(s.id,'today',[s.name,s.school,s.curriculum]));
hosts.done.rows = [row('A','done',['노윤우','정발고','미적분1']),row('Ghost','done',['옛이름','유령학교'])];
const acd = ['today:A','today:C','done:A'], ad = ['today:A','done:A'];
for (const query of ['ㅈㅂㄱ','wqr']) check(query,'school',acd);
check('ㄴㅇㅇ','name',acd); check('ㅈㅂㄱ','name',[]);
for (const query of ['ㅁㅈㅂ','alwjrqns']) check(query,'curriculum',ad);
check('ㅇㅈㅂ','all',['today:B']); check('ㅇㅈㅂ','school',[]);
check('ㄴㅇㅇ ㅈㅂㄱ','all',acd); check('정발고 미적분1','all',ad);
check('ㅈㅂㄱ 대수','all',[]);
for (const event of ['input','search','compositionend']) check('wqr','all',acd,event);
input.value='wqr'; field.value='school'; field.emit('change');
assert.deepEqual(visible(),acd);
const fields = ['name','id','school','schoolName','highSchool','middleSchool','high','middle',
  'schoolHigh','schoolMiddle','highschool','middleschool','high_school','middle_school','고등학교','중학교',
  'grade','gradeLevel','studentGrade','학년','level','curriculum','subCurriculum','subject','course',
  'day1','day2','day3','day4','day5','subBook1','subBook2'];
assert.equal(fields.length,32);
for (const fieldName of fields) {
  const student = {id:'Probe',name:'기준',[fieldName]:'이전값'}, r = row('Probe');
  assert.ok(c.todayRowSearchKey(r,student,'all').includes('이전값'),fieldName);
  student[fieldName]='새로운값';
  const key=c.todayRowSearchKey(r,student,'all');
  assert.ok(!key.includes('이전값') && key.includes('새로운값'),fieldName + ' immediate change');
}
check('ㄴㅇㅇ','name',acd);
h.state.students = h.state.students.map(s=>s.id==='A' ? {...s,name:'교체이름'} : s);
check('교체이름','name',ad); check('ㄴㅇㅇ','name',['today:C']);
h.state.students = h.state.students.filter(s=>s.id!=='A');
check('교체이름','name',[]); check('정발고','school',['today:C']);
check('노윤우 정발고','all',acd); check('유령학교','all',['done:Ghost']);
hosts.done.rows[1].cells[1].textContent='바뀐학교';
check('유령학교','all',[]); check('바뀐학교','all',['done:Ghost']);
check('바뀐학교','school',[]); check('노윤우','all',acd);
const target = hosts.today.rows[2];
target.hidden=true; check('노윤우','all',acd);
target.classList.toggle('is-search-hidden',true); check('노윤우','all',acd);
target.setAttribute('aria-hidden','true'); check('노윤우','all',acd);

// Keep the existing entrypoint render observer while exposing the search rows.
const observeRender = c.renderToday;
c.renderToday = (list,date,...args) => {
  observeRender(list,date,...args);
  hosts.today.rows=list.map(s=>{const r=row(s.id,'today',[s.name,s.school || '',s.curriculum || '']);
    r.dataset.date=date; return r;});
};
c.renderDone = entries => {hosts.done.rows=entries.map(([id])=>row(id,'done'));};
input.value='가연1'; field.value='name';
await h.load({force:true,forceDatePayloads:true,reason:'auto'});
await fixture.drain();
assert.deepEqual(visible(),['today:S1'],'filter applied by actual render entrypoint');
assert.equal(hint.textContent,'1/2명 · 하원 0/0');
assert.deepEqual(JSON.parse(JSON.stringify(h.renders.at(-1).rows.map(r=>r.id))),['S2','S1']);
h.mutate(); h.dispatch('admin:refresh',{force:true});
await fixture.drain();
assert.deepEqual(visible(),[],'admin refresh replaced matching profile');
assert.equal(h.state.students.find(s=>s.id==='S1').name,'가연2');
check('가연2','name',['today:S1']);
hosts.today.rows.find(r=>r.dataset.sid==='S1').hidden=true;
check('가연2','name',['today:S1'],'compositionend');
h.setDate('2026-10-02');
await h.load({force:true,forceDatePayloads:true,reason:'date'}); await fixture.drain();
assert.deepEqual(visible(),['today:S1'],'new dated render applied the current query');
assert.ok(hosts.today.rows.every(r=>r.dataset.date==='2026-10-02'));
input.emit('keydown',{key:'Escape'});
assert.equal(input.value,''); assert.equal(hint.textContent,'');
assert.deepEqual(visible(),['today:S2','today:S1']);
for (const r of rows()) assert.equal(r.getAttribute('aria-hidden'),'false');
const visibleRow = hosts.today.rows[0];
visibleRow.setAttribute('aria-hidden','true');
input.emit('search');
assert.deepEqual(visible(),['today:S2','today:S1']);
assert.equal(visibleRow.hidden,false);
assert.equal(visibleRow.classList.contains('is-search-hidden'),false);
assert.equal(visibleRow.getAttribute('aria-hidden'),'false','empty search repairs an aria-only stale state');
for (const p of paths) assert.equal(fs.readFileSync(p,'utf8'),original[p],'source changed while verifying');
console.log('today search actual-source gate passed: literals, 32 fields, listeners, refresh entrypoint');
