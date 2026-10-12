import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const option=process.argv.indexOf('--source');
const file=option<0?path.join(root,'static/js/student.js'):process.argv[option+1];
const source=fs.readFileSync(file,'utf8');
const start=source.indexOf("    const fbBtn = document.querySelector('#submitFeedback');");
const end=source.indexOf("    window.addEventListener('storage'",start);
assert.ok(start>=0&&end>start,'actual feedback initializer exists');
const flush=async()=>{for(let i=0;i<24;i++)await Promise.resolve();};
function fixture() {
  const button={disabled:false,attrs:{},addEventListener(type,fn){this[type]=fn;},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];}};
  const box={value:'첫 의견'},alerts=[],requests=[];
  const ctx=vm.createContext({stu:{name:'QA 합성 학생'},alert:m=>alerts.push(m),
    document:{querySelector:q=>q==='#submitFeedback'?button:q==='#feedbackBox'?box:null},
    studentAppRequest(url,opts){
      let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
      requests.push({url,method:opts.method,body:JSON.parse(opts.body),resolve,reject});return promise;
    },
  });
  vm.runInContext(source.slice(start,end),ctx,{filename:file});
  return {button,box,alerts,requests,click:()=>button.click()};
}
let cases=0;
{
  const f=fixture();f.box.value='   ';f.click();
  assert.deepEqual(f.alerts,['내용을 입력해주세요!']);assert.equal(f.requests.length,0);assert.equal(f.button.disabled,false);cases++;
}
{
  const f=fixture();f.click();f.click();
  assert.equal(f.requests.length,1,'pending submissions share one UI command');
  assert.deepEqual(f.requests[0].body,{name:'QA 합성 학생',text:'첫 의견'});
  assert.equal(f.button.disabled,true);assert.equal(f.button.attrs['aria-busy'],'true');
  f.requests[0].resolve({ok:false,status:500});await flush();
  assert.deepEqual(f.alerts,['전송에 실패했습니다. 나중에 다시 시도해주세요.']);
  assert.equal(f.box.value,'첫 의견','HTTP failure retains the draft');assert.equal(f.button.disabled,false);assert.equal(f.button.attrs['aria-busy'],undefined);
  f.click();assert.equal(f.requests.length,2,'retry issues a fresh command');
  f.requests[1].resolve({ok:true,status:201});await flush();
  assert.equal(f.alerts.at(-1),'소중한 의견 감사합니다!');assert.equal(f.box.value,'');assert.equal(f.button.disabled,false);cases++;
}
{
  const f=fixture();f.click();f.box.value='응답 대기 중 새 의견';
  f.requests[0].resolve({ok:true,status:200});await flush();
  assert.equal(f.box.value,'응답 대기 중 새 의견','a successful old request cannot clear a newer draft');assert.equal(f.button.disabled,false);cases++;
}
{
  const f=fixture();f.click();f.requests[0].reject(new Error('synthetic network failure'));await flush();
  assert.equal(f.box.value,'첫 의견');assert.equal(f.button.disabled,false);assert.deepEqual(f.alerts,['전송에 실패했습니다. 나중에 다시 시도해주세요.']);cases++;
}
{
  const f=fixture();f.box.value='  한글 & <기호>  ';f.click();
  assert.equal(f.requests[0].url,'/api/feedback');assert.equal(f.requests[0].method,'POST');assert.equal(f.requests[0].body.text,'한글 & <기호>');
  f.requests[0].resolve({ok:true,status:204});await flush();assert.equal(f.box.value,'');assert.equal(f.alerts.at(-1),'소중한 의견 감사합니다!');cases++;
}
console.log(`student feedback save: ${cases} cases PASS (actual initializer/listener; synthetic transport; no HTTP or runtime writes)`);
