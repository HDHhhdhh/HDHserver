import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const date='2026-10-01';
const strip=text=>text.replace(/^import[\s\S]*?;\r?\n/gm,'').replace(/\bexport\s+/g,'');
const read=relative=>fs.readFileSync(path.join(root,relative),'utf8');
const flush=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
const clone=value=>JSON.parse(JSON.stringify(value));
const same=(actual,expected)=>assert.deepEqual(clone(actual),expected);
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
class Element {
 constructor(id) {Object.assign(this,{id,dataset:{},style:{display:'none'},value:'',innerHTML:'',textContent:'',hidden:false,disabled:false,children:[],isConnected:true,scrollHeight:0,clientHeight:0,scrollTop:0});
  this.classList={contains:()=>false,toggle(){},add(){},remove(){}};}
 addEventListener(){} setAttribute(){} removeAttribute(){} focus(){} appendChild(){} remove(){} querySelector(){return null;} querySelectorAll(){return [];}
 getBoundingClientRect(){return {top:0,height:0};}
}
function fixture() {
 const ids=new Map(['testAssignmentModalStyles','testModal','testTitle','testStudentMeta','testVisibleCount','testSave','testCategoryTabs','testSubject','testDifficulty','testTerm','testRound','testDifficultyOverride','testLevelSettingPanel','testLevelSettingCurrent','testLevelSettingOptions','testSelectionMeta','testAssignList','testAppendNotes'].map(id=>[id,new Element(id)]));
 const requests=[], feedback=[];
 const state={students:[{id:'A',name:'A',curriculum:'대수',level:'중'},{id:'B',name:'B',curriculum:'공수1',level:'중'}],logs:{keep:{owner:'baseline'}},progress:{keep:{owner:'baseline'}},testsConfig:{keep:'baseline'},schoolCal:{}};
 const ctx={console,URLSearchParams,Map,Set,Date,JSON,Promise,encodeURIComponent,setTimeout,clearTimeout,requestAnimationFrame:fn=>fn(),
  document:{getElementById:id=>ids.get(id)||null,querySelector:()=>null,querySelectorAll:()=>[],createElement:id=>new Element(id),body:new Element('body'),dispatchEvent(){}},
  state,$:id=>ids.get(id)||null,CT:{'Content-Type':'application/json'},toast:m=>feedback.push(m),alert:m=>feedback.push(m),getAdminDate:()=>date,
  localStorage:{getItem:()=>null,setItem(){}},createUnitTestDisplayNameResolver:()=>test=>test.name,
  CustomEvent:class{},fetch:(url,init={})=>{assert.equal(init.method||'GET','GET','failed hydration made a write');const gate=deferred();requests.push({url,gate});return gate.promise;}};
 ctx.window=ctx;vm.createContext(ctx);
 const source=read('static/js/admin/features/testModal.js');
 const ruleImport=source.match(/^import\s*\{([^}]+)\}\s*from '\.\/testAssignmentRules\.js\?[^']+';/m);
 assert.ok(ruleImport,'actual test rules import must remain addressable');
 const realNames=ruleImport[1].split(',').map(x=>x.trim()).filter(Boolean);
 vm.runInContext('(function(){'+strip(read('static/js/admin/features/testAssignmentRules.js'))+'\nObject.assign(window,{'+realNames.join(',')+'});})();',ctx);
 vm.runInContext(strip(source)+'\nObject.assign(window,{qaOpen:openModalForRow,qaClose:closeModal,qaSave:saveModal});',ctx);
 const row=sid=>({dataset:{sid,date},closest(){return this;}});
 const finish=(request,payload={},status=200)=>request.gate.resolve({ok:status===200,status,json:async()=>clone(payload),text:async()=>JSON.stringify(payload)});
 const resolveAll=(payloads={})=>{for(const request of requests)finish(request,payloads[request.url]||{});};
 return {ctx,state,ids,requests,feedback,row,finish,resolveAll};
}
let cases=0;
for(const failedPath of ['/api/tests-config','/api/logs?sid=A','/api/progress?sid=A','/api/tests']) {
 const f=fixture(),before=clone(f.state),opening=f.ctx.qaOpen(f.row('A'));await flush();
 assert.equal(f.ids.get('testSave').disabled,true);
 for(const r of f.requests)f.finish(r,{},r.url===failedPath?503:200);
 await opening; assert.equal(f.ids.get('testSave').disabled,true);same(f.state,before);
 assert.match(f.ids.get('testAssignList').textContent,/불러오지 못했습니다/);
 await assert.rejects(f.ctx.qaSave(),/불러온 뒤/);assert.equal(f.requests.length,4);cases++;
}
{
 const f=fixture(),before=clone(f.state),opening=f.ctx.qaOpen(f.row('A'));await flush();
 for(const r of f.requests)f.finish(r,r.url==='/api/progress?sid=A'?[]:{});
 await opening;assert.equal(f.ids.get('testSave').disabled,true);same(f.state,before);cases++;
}
{
 const f=fixture(),opening=f.ctx.qaOpen(f.row('A'));await flush();
 await assert.rejects(f.ctx.qaSave(),/불러온 뒤/);assert.equal(f.requests.length,4);
 f.resolveAll();await opening;assert.equal(f.ids.get('testSave').disabled,false);cases++;
}
{
 const f=fixture(),opening=f.ctx.qaOpen(f.row('A'));await flush();
 for(const r of f.requests)f.finish(r,{},503);await opening;
 const retry=f.ctx.qaOpen(f.row('A'));await flush();
 for(const r of f.requests.slice(4))f.finish(r,{});await retry;
 assert.equal(f.ids.get('testSave').disabled,false);assert.equal(f.requests.length,8);cases++;
}
{
 const f=fixture(),before=clone(f.state),opening=f.ctx.qaOpen(f.row('A'));await flush();
 f.ctx.qaClose();f.resolveAll({'/api/logs?sid=A':{[date]:{A:{notes:'late A'}}}});
 await opening;same(f.state,before);assert.equal(f.ids.get('testModal').style.display,'none');cases++;
}
{
 const f=fixture(),a=f.ctx.qaOpen(f.row('A'));await flush();
 for(const r of f.requests)if(!r.url.includes('sid=A'))f.finish(r,{});
 const b=f.ctx.qaOpen(f.row('B'));await flush();
 for(const r of f.requests.filter(r=>r.url.includes('sid=B')))f.finish(r,{[date]:{B:{notes:'B',unknown:'keep'}}});
 await b;const ready=clone(f.state);
 for(const r of f.requests.filter(r=>r.url.includes('sid=A')))f.finish(r,{[date]:{A:{notes:'obsolete A'}}});
 await a;same(f.state,ready);assert.match(f.ids.get('testTitle').textContent,/B/);assert.equal(f.ids.get('testSave').disabled,false);cases++;
}
// Loading authority must not be inferred from a button that another owner locks
// or enables. Use the real open/save functions while transports remain synthetic.
{
 const f=fixture(),opening=f.ctx.qaOpen(f.row('A'));await flush();
 f.ids.get('testSave').disabled=false;
 await assert.rejects(f.ctx.qaSave(),/불러온 뒤/);assert.equal(f.requests.length,4);
 f.resolveAll();await opening;cases++;
}
{
 const f=fixture(),opening=f.ctx.qaOpen(f.row('A'));await flush();
 for(const r of f.requests)f.finish(r,{},503);await opening;
 f.ids.get('testSave').disabled=false;
 await assert.rejects(f.ctx.qaSave(),/불러온 뒤/);assert.equal(f.requests.length,4);cases++;
}
{
 const f=fixture(),opening=f.ctx.qaOpen(f.row('A'));await flush();f.resolveAll();await opening;
 f.ids.get('testSave').disabled=true;
 same(await f.ctx.qaSave({showPopup:false}),[]);assert.equal(f.requests.length,4);
 // A successful earlier session cannot authorize saving a still-loading new one.
 const b=f.ctx.qaOpen(f.row('B'));await flush();f.ids.get('testSave').disabled=false;
 await assert.rejects(f.ctx.qaSave(),/불러온 뒤/);
 for(const r of f.requests.filter(r=>r.url.includes('sid=B')))f.finish(r,{});
 await b;cases++;
}
for(const malformed of [[],null,'bad',{ok:false}]) {
 const f=fixture(),opening=f.ctx.qaOpen(f.row('A'));await flush();
 for(const r of f.requests)f.finish(r,r.url==='/api/tests-config'?malformed:{});
 await opening;assert.equal(f.ids.get('testSave').disabled,true);
 const before=f.requests.length,retry=f.ctx.qaOpen(f.row('A'));await flush();
 assert.equal(f.requests.length,before+1,'malformed authority is removed immediately without waiting for TTL expiry');
 assert.equal(f.requests.at(-1).url,'/api/tests-config');
 f.finish(f.requests.at(-1),{});await retry;
 assert.equal(f.ids.get('testSave').disabled,false,'valid immediate reread recovers the popup');cases++;
}
const logCacheOwnerSource=read('static/js/admin/features/logModal.js');
const logCacheStart=logCacheOwnerSource.indexOf('async function fetchJSONCached(');
const logCacheEnd=logCacheOwnerSource.indexOf('\nfunction mergeDateSidMap(',logCacheStart);
assert.ok(logCacheStart>=0&&logCacheEnd>logCacheStart);
for(const malformed of [[],null,'bad',{ok:false}]) {
 const f=fixture();
 class FrozenDate extends Date { static now(){return 1790812800000;} }
 f.ctx.Date=FrozenDate;
 const otherOwner=vm.createContext({window:f.ctx,Date:FrozenDate,fetch:f.ctx.fetch});
 vm.runInContext(logCacheOwnerSource.slice(logCacheStart,logCacheEnd)+'\nglobalThis.read=fetchJSONCached;',otherOwner);
 const warming=otherOwner.read('/api/progress?sid=A');
 f.finish(f.requests[0],malformed);await warming;await flush();
 const opening=f.ctx.qaOpen(f.row('A'));await flush();
 for(const r of f.requests.slice(1))f.finish(r,{});await opening;
 assert.equal(f.ids.get('testSave').disabled,true,'a malformed shared-cache document from another owner cannot authorize a save');
 const before=f.requests.length,retry=f.ctx.qaOpen(f.row('A'));await flush();
 const fresh=f.requests.slice(before);
 assert.deepEqual(fresh.map(r=>r.url),['/api/progress?sid=A'],'shared malformed cache is evicted without expiring valid sibling documents');
 for(const r of fresh)f.finish(r,{});await retry;
 assert.equal(f.ids.get('testSave').disabled,false,'fresh valid shared authority restores readiness');cases++;
}
console.log('PASS actual test popup hydration: '+cases+' failure/ready/retry/close/reversed-scope/shared-cache cases');
