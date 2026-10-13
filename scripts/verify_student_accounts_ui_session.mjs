import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const args=process.argv.slice(2);
const sourcePath=args.includes('--source')?args[args.indexOf('--source')+1]:'static/js/admin/features/studentAccounts.js';
const source=fs.readFileSync(sourcePath,'utf8').replace(/^import\s[\s\S]*?;\r?\n/gm,'').replace(/\bexport\s+/g,'');
const turn=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const ids=['studentAccountsOpen','studentAccountsModal','studentAccountsClose','studentAccountsSearch',
  'studentAccountsFilter','studentAccountsRefresh','studentAccountsStatus','studentAccountsList',
  'studentActivationCodePanel','studentActivationCodeValue','studentActivationCodeCopy','studentActivationCodeDismiss'];
const nodes=new Map(),reads=[],actions=[],copies=[];
const document={activeElement:null,getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),
  body:{classList:{add(){},remove(){}}},handlers:{},addEventListener(type,fn){(this.handlers[type]||=[]).push(fn);}};
class Element {
  constructor(id){Object.assign(this,{id,dataset:{},hidden:false,disabled:false,isConnected:true,style:{},value:'',textContent:'',children:[],handlers:{}});}
  addEventListener(type,fn){(this.handlers[type]||=[]).push(fn);}
  emit(type,event={}){for(const fn of this.handlers[type]||[])fn({target:this,...event});}
  append(...children){for(const child of children){child.parent=this;this.children.push(child);}}
  replaceChildren(...children){this.children=[];this.append(...children);}
  focus(){document.activeElement=this;}
  getClientRects(){for(let el=this;el;el=el.parent)if(el.hidden||el.style.display==='none')return [];return [{}];}
  querySelectorAll(){return [...nodes.values()].filter(node=>node.parent===this&&!node.disabled).filter(node=>node.id!=='studentAccountsStatus'&&node.id!=='studentAccountsList'&&node.id!=='studentActivationCodeValue'&&node.id!=='studentActivationCodePanel');}
}
for(const id of ids)nodes.set(id,new Element(id));
const n=id=>nodes.get(id),modal=n('studentAccountsModal'),search=n('studentAccountsSearch');
for(const id of ids.filter(id=>!['studentAccountsOpen','studentAccountsModal'].includes(id)))n(id).parent=modal;
n('studentActivationCodeCopy').parent=n('studentActivationCodePanel');
n('studentActivationCodeDismiss').parent=n('studentActivationCodePanel');
n('studentAccountsFilter').value='all';
modal.hidden=true;n('studentActivationCodePanel').hidden=true;
const fetchJsonChecked=(url,_label,options)=>{
  assert.equal(url,'/api/student-accounts');assert.equal(options.credentials,'same-origin');assert.equal(options.cache,'no-store');
  let resolve,reject;const result=new Promise((yes,no)=>{resolve=yes;reject=no;});reads.push({resolve,reject});return result;
};
const deferred=collection=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});collection.push({resolve,reject});return promise;};
const context=vm.createContext({document,fetchJsonChecked,console,ensureOk(){},
  sendJson(url,body){assert.match(url,/^\/api\/student-accounts\/SIMULATED-ONLY\/activation-code$/);assert.deepEqual(Array.from(body.sids),['OWN-S1']);return deferred(actions);},
  navigator:{clipboard:{writeText(value){assert.match(value,/^\d{6}$/);return deferred(copies);}}}});
vm.runInContext(source,context);context.initStudentAccounts();context.initStudentAccounts();
let cases=0;
const check=(actual,expected,label)=>{assert.deepEqual(actual,expected,label);cases++;};
const payload=name=>({groups:[{identity:{name,school:'학교',grade:'고1',sids:['OWN-S1']},account:null}]});
const text=element=>[element.textContent,...element.children.map(text)].join(' ');
const open=()=>{n('studentAccountsOpen').focus();n('studentAccountsOpen').emit('click');};
const close=()=>n('studentAccountsClose').emit('click');
open();check(reads.length,1,'one listener after repeated init');close();open();check(reads.length,2,'reopen gets own read');
reads[1].resolve(payload('새 목록'));await turn();check(text(n('studentAccountsList')).includes('새 목록'),true,'new response visible');
reads[0].resolve(payload('오래된 목록'));await turn();check(text(n('studentAccountsList')).includes('새 목록'),true,'late old success cannot replace reopened list');
check(text(n('studentAccountsList')).includes('오래된 목록'),false,'stale row excluded');
close();open();const old=reads.at(-1);close();open();const current=reads.at(-1);
old.reject(new Error('injected old failure'));await turn();check(n('studentAccountsRefresh').disabled,true,'old failure/finally cannot unlock newer read');
check(n('studentAccountsStatus').textContent,'계정 목록을 불러오는 중입니다.','old failure cannot replace loading status');
current.resolve(payload('현재 목록'));await turn();check(n('studentAccountsRefresh').disabled,false,'current read unlocks refresh');
check(text(n('studentAccountsList')).includes('현재 목록'),true,'current list remains');
close();open();const closed=reads.at(-1);close();const before=text(n('studentAccountsList'));
closed.resolve(payload('닫힌 조회'));await turn();check(modal.hidden,true,'closed read never reopens modal');
check(text(n('studentAccountsList')),before,'closed read does not rewrite hidden list');
open();reads.at(-1).reject(new Error('injected current failure'));await turn();
check(n('studentAccountsStatus').textContent,'계정 목록을 불러오지 못했습니다.','current error reports failure');
check(n('studentAccountsRefresh').disabled,false,'current failure permits retry');
n('studentAccountsRefresh').emit('click');reads.at(-1).resolve(payload('재시도 목록'));await turn();
check(text(n('studentAccountsList')).includes('재시도 목록'),true,'retry recovers list');
const key=(key,shiftKey=false)=>{const result={prevented:false,stopped:false};modal.emit('keydown',{key,shiftKey,preventDefault(){result.prevented=true;},stopPropagation(){result.stopped=true;}});return result;};
n('studentAccountsClose').focus();let event=key('Tab',true);
check(document.activeElement.id,'studentAccountsRefresh','reverse Tab wraps from first to last visible control');
check(event.prevented,true,'reverse Tab default prevented');
n('studentAccountsRefresh').focus();event=key('Tab');check(document.activeElement.id,'studentAccountsClose','forward Tab wraps');
check(event.prevented,true,'forward Tab default prevented');
search.focus();event=key('Tab');check(event.prevented,false,'interior Tab keeps native traversal');
document.activeElement=n('studentAccountsOpen');event=key('Tab');check(document.activeElement.id,'studentAccountsClose','escaped focus recaptured');
n('studentAccountsRefresh').disabled=true;n('studentAccountsClose').focus();key('Tab',true);
check(document.activeElement.id,'studentAccountsFilter','disabled refresh excluded');n('studentAccountsRefresh').disabled=false;
search.focus();event=key('Escape');check(modal.hidden,true,'Escape closes through owner');
check(document.activeElement.id,'studentAccountsOpen','Escape returns focus to opener');
check(event.prevented,true,'Escape default prevented');check(event.stopped,true,'Escape does not reach background handler');
event=key('Tab');check(event.prevented,false,'hidden modal ignores keyboard');
open();reads.at(-1).resolve(payload('배경 닫기'));await turn();modal.emit('click');
check(modal.hidden,true,'backdrop closes through owner');
check(document.activeElement.id,'studentAccountsOpen','backdrop restores opener');
const activation={groups:[{identity:{name:'가상 UI 학생',aid:'SIMULATED-ONLY',sids:['OWN-S1']},account:null,activationCodeRequired:true}]};
const activationButton=()=>{const walk=el=>[el,...el.children.flatMap(walk)];return walk(n('studentAccountsList')).find(el=>el.dataset.accountAction==='activation-code');};
const response=()=>({json:async()=>({activationCode:'654321',expiresAt:1790949999})});
open();reads.at(-1).resolve(activation);await turn();activationButton().emit('click');
close();open();reads.at(-1).resolve(payload('새 세션'));await turn();const newStatus=n('studentAccountsStatus').textContent;
actions.at(-1).resolve(response());await turn();check(n('studentActivationCodePanel').hidden,true,'late action cannot reveal code in reopened session');
check(n('studentAccountsStatus').textContent,newStatus,'late action cannot overwrite new status');
close();open();reads.at(-1).resolve(activation);await turn();activationButton().emit('click');
actions.at(-1).resolve(response());await turn();check(n('studentActivationCodePanel').hidden,false,'current simulated response reveals panel');
n('studentActivationCodeCopy').emit('click');close();open();reads.at(-1).resolve(payload('복사 뒤 새 세션'));await turn();
const copyStatus=n('studentAccountsStatus').textContent;copies.at(-1).resolve();await turn();
check(n('studentActivationCodePanel').hidden,true,'late copy leaves new session code panel hidden');
check(n('studentAccountsStatus').textContent,copyStatus,'late copy cannot overwrite new status');
close();open();reads.at(-1).resolve(activation);await turn();activationButton().emit('click');
actions.at(-1).resolve(response());await turn();n('studentActivationCodeCopy').emit('click');copies.at(-1).reject(new Error('simulated clipboard unavailable'));await turn();
check(n('studentActivationCodePanel').hidden,false,'current copy failure retains code for manual copy');
check(n('studentAccountsStatus').textContent,'자동 복사가 차단되었습니다. 표시된 코드를 직접 복사해 주세요.','copy failure feedback');
n('studentActivationCodeDismiss').emit('click');check(n('studentActivationCodeValue').textContent,'','dismiss clears local code');
check(n('studentActivationCodePanel').hidden,true,'dismiss hides code');
check(actions.length,3,'exact simulated actions');check(copies.length,2,'exact simulated copies');
context.sendJson=(url,body)=>{
  assert.match(url,/^\/api\/student-accounts\/SIMULATED-[AB]\/activation-code$/);
  return deferred(actions);
};
const walkAccounts=el=>[el,...el.children.flatMap(walkAccounts)];
const twoGroups={groups:['A','B'].map(name=>({identity:{name:`QA ${name}`,aid:`SIMULATED-${name}`,sids:[`QA-${name}`]},account:null,activationCodeRequired:true}))};
const actionFor=aid=>walkAccounts(n('studentAccountsList')).find(el=>el.dataset.accountAction==='activation-code'&&el.dataset.aid===aid);
close();open();reads.at(-1).resolve(twoGroups);await turn();
actionFor('SIMULATED-A').emit('click');const olderAction=actions.at(-1);
actionFor('SIMULATED-B').emit('click');const newerAction=actions.at(-1);
newerAction.resolve({json:async()=>({activationCode:'222222',expiresAt:1790949999})});await turn();
check(n('studentActivationCodeValue').textContent,'222222','newest requested account owns the local code panel');
olderAction.resolve({json:async()=>({activationCode:'111111',expiresAt:1790949999})});await turn();
check(n('studentActivationCodeValue').textContent,'222222','older same-session reply cannot overwrite another account code');
actionFor('SIMULATED-A').emit('click');const olderFailure=actions.at(-1);
actionFor('SIMULATED-B').emit('click');const newerSuccess=actions.at(-1);
newerSuccess.resolve({json:async()=>({activationCode:'333333',expiresAt:1790949999})});await turn();
const latestStatus=n('studentAccountsStatus').textContent;
olderFailure.reject(new Error('older account failure'));await turn();
check(n('studentActivationCodeValue').textContent,'333333','older account failure leaves the latest code intact');
check(n('studentAccountsStatus').textContent,latestStatus,'older account failure leaves the latest feedback intact');
close();
console.log(`PASS student accounts UI session: ${cases} cases; stale GET/action/copy, retry, focus boundaries, idempotence; real HTTP/credential writes 0`);
