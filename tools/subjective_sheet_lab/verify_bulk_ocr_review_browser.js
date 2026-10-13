"use strict";
const fs=require("fs"),path=require("path"),{spawn}=require("child_process");
const root=process.argv[2];
if(!root) throw new Error("fresh evidence root required");
const chrome="C:/Program Files/Google/Chrome/Application/chrome.exe";
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const child=spawn(chrome,["--headless=new","--remote-debugging-pipe","--disable-background-networking",
  "--disable-component-update","--disable-default-apps","--disable-sync","--no-first-run",
  "--no-default-browser-check","--metrics-recording-only","--disable-gpu","--no-proxy-server",
  "--host-resolver-rules=MAP * ~NOTFOUND","--allow-file-access-from-files",
  "--user-data-dir="+path.join(root,"chrome_profile")],
  {stdio:["ignore","pipe","pipe","pipe","pipe"],windowsHide:true});
let nextId=0,buffer="",sessionId="",externalRequests=0;
const waiting=new Map(),errors=[];
child.stderr.on("data",data=>{if(errors.length<5) errors.push(String(data).slice(0,200));});
child.stdio[4].on("data",chunk=>{
  buffer+=chunk.toString("utf8");
  let at;
  while((at=buffer.indexOf("\0"))>=0) {
    const raw=buffer.slice(0,at);buffer=buffer.slice(at+1);if(!raw)continue;
    const message=JSON.parse(raw);
    if(message.id&&waiting.has(message.id)) {
      const {resolve,reject,timer}=waiting.get(message.id);clearTimeout(timer);waiting.delete(message.id);
      message.error?reject(new Error(message.error.message)):resolve(message.result);
    } else if(message.method==="Network.requestWillBeSent" && /^https?:/.test(message.params.request.url)) externalRequests++;
  }
});
child.on("exit",()=>{for(const entry of waiting.values()){clearTimeout(entry.timer);entry.reject(new Error("owned Chrome exited"));}waiting.clear();});
function send(method,params={},session=sessionId) {
  const id=++nextId;
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{waiting.delete(id);reject(new Error("CDP timeout "+method));},15000);
    waiting.set(id,{resolve,reject,timer});
    child.stdio[3].write(JSON.stringify({id,method,params,...(session?{sessionId:session}:{})})+"\0");
  });
}
async function evaluate(expression) {
  const reply=await send("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});
  if(reply.exceptionDetails) throw new Error(reply.exceptionDetails.exception?.description||reply.exceptionDetails.text);
  return reply.result.value;
}
function assert(value,message){if(!value)throw new Error(message);}
function freshJSON(file,value){fs.writeFileSync(path.join(root,file),JSON.stringify(value,null,2)+"\n",{flag:"wx"});}
async function load(payload) {
  return evaluate("window.OCRLabReview.loadPayload("+JSON.stringify(payload)+",'offline')");
}
async function main() {
  const {targetId}=await send("Target.createTarget",{url:"about:blank"},"");
  const attach=await send("Target.attachToTarget",{targetId,flatten:true},"");sessionId=attach.sessionId;
  await send("Page.enable");await send("Runtime.enable");await send("Network.enable");
  await send("Network.setBlockedURLs",{urls:["http://*","https://*","ws://*","wss://*"]});
  await send("Page.navigate",{url:"file:///C:/server/tools/subjective_sheet_lab/review_ui_mock.html"});
  let ready=false;
  for(let i=0;i<80;i++){try{ready=await evaluate("!!window.OCRLabReview && document.readyState==='complete'");}catch{}if(ready)break;await sleep(100);}
  assert(ready,"lab file UI unavailable");
  assert(await evaluate("window.OCRLabReview.generateFinalPayload()===null"),"empty UI finalized");
  const normal=JSON.parse(fs.readFileSync(path.join(root,"normal_review.json"),"utf8"));
  const visual=JSON.parse(fs.readFileSync(path.join(root,"independent_human_transcription.json"),"utf8")).items.map(i=>i.human_answer);
  const clone=()=>JSON.parse(JSON.stringify(normal)),checks=[];
  for(const count of [0,1,5,6]) {
    const p=clone();p.items[1].candidates=Array.from({length:count},(_,i)=>String(i+1));
    assert(await load(p),"candidate case load failed");
    const result=await evaluate("({buttons:document.querySelectorAll('#question-card-2 [data-candidate]').length,editor:!!document.querySelector('#question-card-2 input[type=text]')})");
    assert(result.buttons===Math.min(count,5),"candidate cap not enforced");
    assert(result.editor===(count===0),"editor default policy violated");
    checks.push({name:"candidates_"+count,status:"pass"});
  }
  {const p=clone();p.items[1].candidates=["1","1"," 1 ","2"];
   assert(await load(p),"duplicate candidates load failed");
   assert(await evaluate("document.querySelectorAll('#question-card-2 [data-candidate]').length")===2,"candidate deduplication failed");}
  assert(await load(normal),"normal UI failed");
  assert(await evaluate("document.getElementById('safeDetails').open===false"),"safe items not collapsed");
  await evaluate("document.querySelector('#question-card-2 [data-no-candidate]').click()");
  assert(await evaluate("!!document.querySelector('#question-card-2 input[type=text]')"),"reject-all did not reveal input");
  await evaluate("(()=>{let e=document.querySelector('#question-card-2 input[type=text]');e.value='-3';e.dispatchEvent(new Event('input',{bubbles:true}));[...document.querySelectorAll('#question-card-2 button')].find(b=>b.textContent==='확정').click();return true})()");
  assert(await evaluate("window.OCRLabReview.snapshot().items.find(i=>i.question_no===2).recognized==='-7'"),"manual edit overwrote recognized");
  checks.push({name:"reject_all_manual_input_raw_history",status:"pass"});
  // A physically retaken crop never becomes a final answer without another recognition result.
  {const p=clone(),i=p.items[2];i.status="retake_required";i.final_answer=null;i.source=null;i.warnings=["low_visibility"];
   assert(await load(p),"retake case failed");
   assert(await evaluate("!document.querySelector('#question-card-3 input[type=text]')"),"retake exposes direct input");
   assert(await evaluate("window.OCRLabReview.generateFinalPayload()===null"),"retake finalized");
   await evaluate("document.querySelector('#question-card-3 button').click()");
   const doc=await send("DOM.getDocument");const query=await send("DOM.querySelector",{nodeId:doc.root.nodeId,selector:"#retakeImageInput"});
   const cropFile=normal.items[2].crop_preview;
   const png=path.join(root,"retake_synthetic.png");fs.writeFileSync(png,Buffer.from(cropFile.split(",")[1],"base64"),{flag:"wx"});
   await send("DOM.setFileInputFiles",{nodeId:query.nodeId,files:[png]});
   await sleep(150);
   assert(await evaluate("window.OCRLabReview.generateFinalPayload()===null"),"uploaded retake incorrectly completed");
   checks.push({name:"retake_only_upload_stays_unresolved",status:"pass"});}
  {const p=clone();p.items[0].expected="DO_NOT_STORE_SENTINEL";
   assert(await load(p)===false,"answer-key input accepted");
   const safe=await evaluate("JSON.stringify(window.OCRLabReview.snapshot())+document.body.innerText");
   assert(!safe.includes("DO_NOT_STORE_SENTINEL"),"answer key retained in state/DOM");
   checks.push({name:"key_rejected_before_state_dom_export",status:"pass"});}
  for(const mutation of [
    p=>p.items[1].question_no=1,p=>p.items.pop(),p=>p.items[0].question_no=1.5,
    p=>p.items[0].status="unknown",p=>p.items[0].identity_sha256="different",
    p=>p.items[0].crop_sha256="0".repeat(64),p=>p.identity.photo_sha256="0".repeat(64),
    p=>p.error="provider_pending"
  ]) {const p=clone();mutation(p);assert(await load(p)===false,"invalid run accepted");}
  {const p=clone();p.demo=true;assert(await load(p),"demo fixture did not load");assert(await evaluate("window.OCRLabReview.generateFinalPayload()===null"),"demo completed");}
  await evaluate("document.getElementById('btnLoad').click()");
  assert(await evaluate("window.OCRLabReview.snapshot().payload===null"),"failure replaced by embedded sample");
  assert(await evaluate("window.OCRLabReview.generateFinalPayload()===null"),"failed load finalized empty state");
  checks.push({name:"mismatch_unknown_demo_failure_blocked",status:"pass"});
  // Review actual controls, not an alternate finalizer.
  assert(await load(normal),"final normal load failed");
  for(let n=2;n<=20;n++) {
    const wanted=visual[n-1];
    await evaluate("(()=>{const card=document.getElementById('question-card-"+n+"');const buttons=[...card.querySelectorAll('[data-candidate]')];const match=buttons.find(b=>b.dataset.candidate==="+JSON.stringify(wanted)+");if(match)match.click();else{card.querySelector('[data-no-candidate]')?.click();const e=document.querySelector('#question-card-"+n+" input[type=text]');if(!e)throw new Error('manual editor absent');e.value="+JSON.stringify(wanted)+";e.dispatchEvent(new Event('input',{bubbles:true}));}const live=document.getElementById('question-card-"+n+"');[...live.querySelectorAll('button')].find(b=>b.textContent==='확정').click();return true})()");
  }
  const final=await evaluate("document.getElementById('btnGeneratePayload').click();window.OCRLabReview.snapshot().finalPayload");
  assert(final&&final.items.length===20,"actual UI export did not finalize 20 items");
  assert(!JSON.stringify(final).includes("expected")&&!JSON.stringify(final).includes("canonical_answer"),"key in export");
  assert(final.items[1].recognized==="-7"&&final.items[1].final_answer==="-3","raw/final contract failed");
  freshJSON("final_review_payload.json",final);
  const viewports=[{name:"desktop",width:1280,height:900,mobile:false,deviceScaleFactor:1},
                   {name:"mobile",width:390,height:844,mobile:true,deviceScaleFactor:1}];
  for(const view of viewports) {
    await send("Emulation.setDeviceMetricsOverride",view);
    await sleep(100);
    const size=await evaluate("({width:innerWidth,scroll:document.documentElement.scrollWidth})");
    assert(size.scroll<=size.width+1,"horizontal overflow "+view.name+": "+JSON.stringify(size));
    const shot=await send("Page.captureScreenshot",{format:"png"});
    fs.writeFileSync(path.join(root,"review_"+view.name+".png"),Buffer.from(shot.data,"base64"),{flag:"wx"});
    // Repeat a real choice and reject-all edit at the mobile viewport.
    if(view.mobile) {
      assert(await load(normal),"mobile run failed");
      await evaluate("document.querySelector('#question-card-2 [data-no-candidate]').click()");
      assert(await evaluate("!!document.querySelector('#question-card-2 input[type=text]')"),"mobile manual interaction failed");
    }
    checks.push({name:view.name+"_render_and_controls",status:"pass",viewport:size});
  }
  assert(externalRequests===0,"HTTP request attempted by lab UI");
  const result={status:"pass",browser:"existing Chrome headless via pipe",network:"HTTP/WebSocket blocked; file/data only",external_requests:externalRequests,checks};
  freshJSON("browser_verification.json",result);
  console.log(JSON.stringify({status:"pass",checks:checks.length,externalRequests}));
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;}).finally(async()=>{
  try{await send("Browser.close",{},"");}catch{}
  if(!child.killed)child.kill();
});
