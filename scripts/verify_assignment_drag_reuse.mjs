import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
function section(source, start, end) {
  const a=source.indexOf(start), b=source.indexOf(end,a+start.length);
  assert.ok(a>=0 && b>a, 'actual source section must exist');
  return source.slice(a,b);
}
for (const kind of ['video','test']) {
  const source=fs.readFileSync(path.join(root,'static/js/admin/features/'+(kind==='video'?'videoModal':'testModal')+'.js'),'utf8').replaceAll('\r\n','\n');
  const rows=['none','assigned','done','interrupted','skip'].map((state,index)=>({dataset:{state,testKey:String(index),mid:String(index)}}));
  const listeners=[],calls=[],views=[];
  const modal={style:{display:'flex'},contains:()=>true};
  const ctx=vm.createContext({pointerDown:true,dragActive:true,startIndex:0,lastDragIndex:-1,
    dragRows:rows,dragInitialStates:rows.map(row=>row.dataset.state),dragInitialStatuses:rows.map(row=>row.dataset.state),
    dragTargetState:'assigned',dragTarget:'assigned',vidModal:modal,
    activeVideoMultiSelectedMids:new Set(['0']),multiSelectedKeys:new Set(['0']),
    catalogByKey:new Map(rows.map(row=>[row.dataset.testKey,{id:row.dataset.testKey}])),
    rememberCurrentTestView:test=>views.push(test?.id),
    document:{activeElement:{matches:()=>false},body:{addEventListener:(_,fn)=>listeners.push(fn)}},
    $:()=>modal,
    applyVideoRowState:(row,state)=>{row.dataset.state=state;calls.push({mid:row.dataset.mid,state});},
    applyTestRowStatus:(row,state,options)=>{row.dataset.state=state;calls.push({key:row.dataset.testKey,state,touch:options.touch,remember:options.remember});},
    applyKeyboardVideoStatusToSelection:()=>{rows[0].dataset.state='done';return true;},
    applyKeyboardStatusToSelection:()=>{rows[0].dataset.state='done';return true;},
  });
  const rangeName=kind==='video'?'applyVideoDragRange':'applyDragRange';
  const moveName=kind==='video'?'handleVideoDragMove':'handleDragMove';
  vm.runInContext(section(source,'  function '+rangeName+'(','  function '+moveName+'('),ctx);
  const keyEnd=kind==='video'?'  async function saveVideoAssignmentForCurrent(' : "  document.body.addEventListener('click', (e) => {\n    if (e.target?.id === 'testModal')";
  vm.runInContext(section(source,"  document.body.addEventListener('keydown', (e) => {",keyEnd),ctx);
  for(let i=0;i<300;i++)ctx[rangeName](rows[3]);
  assert.equal(calls.length,5,'repeated endpoint must reuse the completed range');
  assert.deepEqual(rows.map(row=>row.dataset.state),['assigned','assigned','assigned','assigned','skip']);
  if(kind==='test') {
    assert.deepEqual(calls.map(row=>row.touch),[true,true,true,true,false]);
    assert.deepEqual(calls.map(row=>row.remember),[false,false,false,false,false]);
    assert.deepEqual(views,['4'],'one view persistence per range keeps the prior last-row value');
  }
  ctx[rangeName]({dataset:{}});assert.equal(calls.length,5,'foreign rows cannot reuse or alter range state');
  let prevented=0;
  listeners[0]({key:'ArrowRight',preventDefault(){prevented++;},stopPropagation(){}});
  assert.equal(rows[0].dataset.state,'done');assert.equal(prevented,1);
  ctx[rangeName](rows[3]);
  assert.equal(calls.length,10,'a keyboard state change invalidates endpoint reuse');
  assert.deepEqual(rows.map(row=>row.dataset.state),['assigned','assigned','assigned','assigned','skip']);
  ctx[rangeName](rows[1]);
  assert.deepEqual(rows.map(row=>row.dataset.state),['assigned','assigned','done','interrupted','skip']);
  ctx.pointerDown=false;ctx[rangeName](rows[4]);assert.equal(calls.length,15,'mouseup disables range application');
  if(kind==='test')assert.deepEqual(views,['4','4','4'],'only completed range changes remember a view');
}
console.log('PASS assignment drag reuse: literal ranges, 300 repeated endpoints, foreign rows, keyboard invalidation, reverse and mouseup');

function autoScrollFixture() {
  const handlers = new Map(), frames = new Map();
  let frameId = 0, time = 0, active = true, stops = 0;
  const selected = [];
  const listen = scope => ({
    addEventListener(type, fn) { const key = scope + type; if (!handlers.has(key)) handlers.set(key, new Set()); handlers.get(key).add(fn); },
    removeEventListener(type, fn) { handlers.get(scope + type)?.delete(fn); },
  });
  const fire = (scope, type, event = {}) => { for (const fn of [...(handlers.get(scope + type) || [])]) fn(event); };
  const scrollers = [0, 220].map(left => {
    let top = 0;
    const box = { isConnected: true, visible: true, rows: [],
      get scrollTop() { return top; }, set scrollTop(value) { top = Math.max(0, Math.min(1800, value)); },
      getClientRects() { return this.visible ? [{}] : []; },
      getBoundingClientRect: () => ({top:100,bottom:300,left,right:left+200}),
      contains(row) { return this.rows.includes(row); },
    };
    box.rows = Array.from({length:100}, (_, index) => ({index, disabled:index>=20 && index<25, isConnected:true,
      closest: () => box.rows[index], box}));
    return box;
  });
  const document = {...listen('doc'), hidden:false, elementFromPoint(x, y) {
    const box = scrollers.find((_, index) => x >= index*220 && x < index*220+200);
    if (!box || y < 100 || y >= 300) return null;
    const offset = y - 100 + box.scrollTop;
    return offset % 20 > 16 ? null : box.rows[Math.floor(offset / 20)] || null;
  }};
  const window = {...listen('win'), innerHeight:600};
  const context = vm.createContext({document, window,
    requestAnimationFrame: fn => { frames.set(++frameId, fn); return frameId; },
    cancelAnimationFrame: id => frames.delete(id),
  });
  vm.runInContext(fs.readFileSync(path.join(root,'static/js/admin/features/assignmentDragAutoScroll.js'),'utf8').replace(/^export /gm,''),context);
  const controller = context.createAssignmentDragAutoScroll({rowSelector:'.row',scrollerForRow:row=>row.box,
    isActive:()=>active,onRow:row=>selected.push(row),onStop:()=>{active=false;stops++;}});
  const event = (x=50,y=298,buttons=1,target=scrollers[0].rows[8]) => ({clientX:x,clientY:y,buttons,target});
  const step = (count=1) => { for(let i=0;i<count && frames.size;i++) { const [id,fn]=frames.entries().next().value;frames.delete(id);fn(time+=16); } };
  return {controller,scrollers,document,event,step,selected,frames,fire,
    get stops(){return stops;},set active(value){active=value;}};
}

for (const button of [0,2]) {
  const f=autoScrollFixture(), box=f.scrollers[0], mask=button===2?2:1;
  f.controller.start(f.event(50,298,mask),box.rows[8],button);
  f.step(400);
  assert.equal(box.scrollTop,1800,'stationary pointer reaches the bottom');
  assert.equal(f.selected.at(-1).index,99,'range follows rows revealed by scrolling, including a row gap');
  assert.ok(!f.selected.some(row=>row.disabled),'disabled rows are never endpoints');
  assert.equal(f.frames.size,0,'the bound does not keep a frame loop alive');
  f.fire('doc','mousemove',f.event(50,102,mask,box));f.step(400);
  assert.equal(box.scrollTop,0,'reverse movement reaches the top');
  assert.equal(f.selected.at(-1).index,0);
  f.fire('doc','mousemove',f.event(270,298,mask,f.scrollers[1].rows[8]));f.step(10);
  assert.ok(f.scrollers[1].scrollTop>0,'the second video list owns its scroll');
  assert.equal(box.scrollTop,0,'switching lists does not scroll the first list');
  f.fire('doc','mouseup');const stopped=f.scrollers[1].scrollTop;f.step(20);
  assert.equal(f.scrollers[1].scrollTop,stopped);assert.equal(f.stops,1);
  assert.equal(f.frames.size,0);
}
for (const exit of ['blur','hidden','buttons','detached','invisible','session','stop']) {
  const f=autoScrollFixture(), box=f.scrollers[0];
  f.controller.start(f.event(),box.rows[8]);f.step(4);
  if(exit==='blur')f.fire('win','blur');
  if(exit==='hidden'){f.document.hidden=true;f.fire('doc','visibilitychange');}
  if(exit==='buttons')f.fire('doc','mousemove',f.event(50,298,0));
  if(exit==='detached')box.isConnected=false;
  if(exit==='invisible')box.visible=false;
  if(exit==='session')f.active=false;
  if(exit==='stop')f.controller.stop();
  f.step();const stopped=box.scrollTop;f.step(20);
  assert.equal(box.scrollTop,stopped,exit+' must end scrolling');assert.equal(f.frames.size,0);
  assert.equal(f.stops,exit==='stop'?0:1);
}
{
  const f=autoScrollFixture(),box=f.scrollers[0];
  f.controller.start(f.event(50,200),box.rows[5]);f.step(10);assert.equal(box.scrollTop,0,'center is idle');
  f.fire('doc','mousemove',f.event(50,298));f.step(10);assert.ok(box.scrollTop>0,'edge resumes from idle');
  f.fire('doc','mousemove',f.event(500,298,1,box));f.step();const paused=box.scrollTop;f.step(10);
  assert.equal(box.scrollTop,paused,'horizontal exit pauses scrolling');
  f.controller.stop();
}
console.log('PASS assignment edge scroll: held pointer, both directions/buttons/lists, row gaps, disabled rows, idle/resume, release/blur/hidden/lost buttons/detached/hidden list/stale session/explicit stop');

for (const kind of ['test','video']) {
  const source=fs.readFileSync(path.join(root,'static/js/admin/features/'+kind+'Modal.js'),'utf8').replaceAll('\r\n','\n');
  const row={disabled:false,isConnected:true,dataset:{state:'none',testKey:'0'}};
  const listeners=new Map();let applied=0,stopped=0,started=0;
  const ctx=vm.createContext({pointerDown:true,dragActive:true,dragButton:2,dragRows:[row],startIndex:0,
    dragAutoScroll:null,dragOpenSeq:1,testOpenSeq:1,videoOpenSeq:1,startStatus:'',startState:'none',
    suppressClickOnce:false,suppressContextOnce:false,lastDragIndex:-1,dragTarget:null,dragTargetState:null,
    dragInitialStatuses:[],dragInitialStates:[],testSelectionTouched:false,
    testRowFromTarget:()=>row,videoRowFromEventTarget:()=>row,
    applyDragRange:()=>applied++,applyVideoDragRange:()=>applied++,
    nextExcludedStatusOf:()=> 'skip',nextExcludedVideoState:()=> 'skip',
    nextStatusOf:()=> 'assigned',nextVideoRowState:()=> 'assigned',
    createAssignmentDragAutoScroll:()=>({start(){started++;},stop(){stopped++;}}),
    rebuildDragRows:()=>{},rebuildVideoDragRows:()=>{},statusForKey:()=>'',
    document:{body:{addEventListener:(type,fn)=>listeners.set(type,fn)}},
    chkZone:{addEventListener:(type,fn)=>listeners.set(type,fn)},
  });
  const finishName=kind==='test'?'finishDrag':'finishVideoDrag';
  const finishEnd=kind==='test'?'  stopTestAssignmentDrag =' : '  const videoRowFromEventTarget =';
  vm.runInContext(section(source,'  function '+finishName+'(',finishEnd),ctx);
  const moveName=kind==='test'?'handleDragMove':'handleVideoDragMove';
  const moveEnd=kind==='test'?"  document.body.addEventListener('click', async" : "  chkZone.addEventListener('mousedown'";
  vm.runInContext(section(source,'  function '+moveName+'(',moveEnd),ctx);
  ctx[moveName]({type:'mouseover',buttons:1,target:row,preventDefault(){}});
  assert.equal(ctx.pointerDown,true,'scroll-generated hover must not end a right drag');assert.equal(applied,1);
  ctx[moveName]({type:'mousemove',buttons:0,target:row,preventDefault(){}});
  assert.equal(ctx.pointerDown,false,'real movement with released button ends dragging');assert.equal(applied,1);
  ctx.pointerDown=true;ctx.dragActive=false;
  ctx.dragRows=[row];ctx.startIndex=0;ctx.dragButton=2;
  ctx.testRowFromTarget=ctx.videoRowFromEventTarget=()=>null;
  ctx[moveName]({type:'mousemove',buttons:2,target:{},preventDefault(){}});
  assert.equal(started,1,'first movement into a gap starts from the anchor');assert.equal(ctx.dragActive,true);
  ctx[finishName]();assert.equal(ctx.suppressContextOnce,true,'same-gesture context action stays suppressed');
  ctx.testRowFromTarget=ctx.videoRowFromEventTarget=()=>row;
  const downStart=kind==='test'?"  document.body.addEventListener('mousedown'," : "  chkZone.addEventListener('mousedown',";
  const downEnd=kind==='test'?"  document.body.addEventListener('mousemove'," : "  document.addEventListener('mousemove',";
  vm.runInContext(section(source,downStart,downEnd),ctx);
  listeners.get('mousedown')({button:2,ctrlKey:true,target:row});
  assert.equal(ctx.suppressContextOnce,false,'new gesture clears an unconsumed context suppression');
  assert.equal(ctx.pointerDown,false,'Ctrl/Cmd selection does not start status dragging');
  assert.ok(stopped>=1);
}
console.log('PASS actual modal drag handlers: right-button hover, lost-button move, first gap, same-gesture suppression, fresh gesture and Ctrl separation');
