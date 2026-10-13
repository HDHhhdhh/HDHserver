import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = process.argv[2] ? path.resolve(process.argv[2]) : path.join(root, 'static/js/admin/features/escClose.js');
const source = fs.readFileSync(sourcePath, 'utf8').replace(/^export /gm, '');
let assertions = 0;
const equal = (actual, expected, message) => { assert.equal(actual, expected, message); assertions++; };

function fixture() {
  const ids = new Map(), listeners = [], frames = [], closed = [];
  const document = {activeElement:null,
    addEventListener(type, fn, options) { listeners.push({type,fn,capture:options===true || options?.capture===true}); },
    getElementById:id=>ids.get(id)||null,
    querySelectorAll:()=>[...ids.values()].filter(el=>el.modal),
  };
  function element(id, {type='', tag='INPUT', role='', modal=false} = {}) {
    const el = {id,type,tag,role,modal,value:'초안 '+id,disabled:false,readOnly:false,visible:true,
      style:{display:'block'},events:[],inputCount:0,focusCount:0,scrollCount:0,selectCount:0,
      classList:{contains:()=>false},
      matches(selector) {
        if(selector.includes('input[type="search"]'))return tag==='INPUT' && (type==='search' || role==='searchbox');
        if(tag==='INPUT')return ![...selector.matchAll(/:not\(\[type="([^"]+)"\]\)/g)].some(([, excluded])=>excluded===type);
        return ['TEXTAREA','SELECT'].includes(tag) || tag==='EDITABLE';
      },
      closest(selector) { return this.matches(selector) ? this : null; },
      getBoundingClientRect:()=>({width:el.visible?100:0,height:el.visible?30:0}),
      focus() { document.activeElement=this;this.focusCount++; },
      select() { this.selectCount++; },
      scrollIntoView() { this.scrollCount++; },
      addEventListener(type,fn) { this.events.push({type,fn}); },
      dispatchEvent(event) { if(event.type==='input')this.inputCount++; for(const entry of this.events)if(entry.type===event.type)entry.fn(event); },
    };
    if(id)ids.set(id,el);return el;
  }
  const body=element('body',{tag:'BODY'}),today=element('todaySearchInput',{type:'search'});
  document.activeElement=body;
  const window={closeExtraAttendancePopup() { closed.push('extra'); const modal=ids.get('extraModal');modal.style.display='none';modal.visible=false; }};
  const ctx=vm.createContext({document,window,
    getComputedStyle:el=>({display:el.visible?el.style.display:'none',visibility:'visible',opacity:'1',position:'static'}),
    requestAnimationFrame:fn=>frames.push(fn),
    Event:class{constructor(type,options={}){this.type=type;Object.assign(this,options);}},console,
  });
  vm.runInContext(source+'\ninitEscClose();',ctx);
  function escape(target=document.activeElement, options={}) {
    const event={key:'Escape',target,defaultPrevented:false,isComposing:false,stopped:false,
      preventDefault(){this.defaultPrevented=true;},stopImmediatePropagation(){this.stopped=true;},...options};
    for(const listener of listeners)if(listener.type==='keydown'&&listener.capture&&!event.stopped)listener.fn(event);
    for(const listener of target?.events||[])if(listener.type==='keydown'&&!event.stopped)listener.fn(event);
    for(const listener of listeners)if(listener.type==='keydown'&&!listener.capture&&!event.stopped)listener.fn(event);
    return event;
  }
  return {ctx,document,window,element,today,body,frames,closed,escape,flush:()=>{while(frames.length)frames.shift()();}};
}

const searchIds=['todaySearchInput','exSearch','absentSearch','manualMakeupSearch','makeupPlannerSearch',
  'makeupStatusSearch','selectionSearchInput','extraVideoSearch','annDirectSearch','studentAccountsSearch',''];
for(const id of searchIds) {
  const f=fixture(), input=id==='todaySearchInput'?f.today:f.element(id,{type:'search'});
  f.element('extraModal',{tag:'DIV',modal:true});
  const other=f.element('anotherSearch',{type:'search'}),otherDraft=other.value,todayDraft=f.today.value;
  let localKeys=0,selectionCancelled=0,filterRuns=0;
  input.addEventListener('input',()=>filterRuns++);
  input.addEventListener('keydown',()=>{localKeys++;selectionCancelled++;});
  f.document.activeElement=input;
  const event=f.escape();
  equal(input.value,'',id+' clears itself');equal(f.document.activeElement,input,'focus stays on search');
  equal(input.inputCount,1,'filter is notified once');equal(filterRuns,1,'existing filter runs once');
  equal(input.scrollCount,0,'search Escape does not scroll the page');equal(localKeys,0,'local Escape cannot close/cancel');
  equal(selectionCancelled,0,'makeup selection stays intact');equal(f.closed.length,0,'popup owner is not closed');
  equal(f.frames.length,0,'student-name navigation is not queued');equal(other.value,otherDraft,'other queries survive');
  if(input!==f.today)equal(f.today.value,todayDraft,'student-name query survives');
  equal(event.defaultPrevented,true,'native search Escape is consumed');equal(event.stopped,true,'propagation is consumed');
  f.escape();equal(input.inputCount,2,'empty repeated Escape stays in the same search');equal(f.closed.length,0,'empty search does not close');
}
{
  const f=fixture();f.document.activeElement=f.today;
  const before=f.today.value,event=f.escape(f.today,{isComposing:true});
  equal(f.today.value,before,'IME Escape preserves the query');equal(f.today.inputCount,0,'IME does not refresh filter');
  equal(event.defaultPrevented,false,'native IME cancellation remains available');equal(event.stopped,true,'app handlers cannot clear IME input');
}
{
  const f=fixture(),search=f.element('accessibleSearch',{type:'text',role:'searchbox'});
  f.document.activeElement=search;f.escape(f.body);
  equal(search.value,'','focused searchbox fallback clears');equal(f.document.activeElement,search,'focused searchbox fallback retains focus');
}
{
  const f=fixture();f.escape();equal(f.frames.length,1,'blank Escape queues name-search navigation');f.flush();
  equal(f.today.value,'','blank Escape clears name search');equal(f.document.activeElement,f.today,'blank Escape focuses name search');
  equal(f.today.scrollCount,1,'blank Escape preserves the page navigation');
}
for(const tag of ['INPUT','TEXTAREA','SELECT','EDITABLE']) {
  const f=fixture(),editor=f.element('draft',{tag});f.document.activeElement=editor;const draft=editor.value;f.escape();f.flush();
  equal(f.document.activeElement,editor,'non-search editor is not blank space');equal(editor.value,draft,'editor draft survives');
  equal(f.today.inputCount,0,'editor Escape does not clear name search');
}
for(const type of ['checkbox','radio']) {
  for(const checked of [false,true]) {
    const f=fixture(),control=f.element('contactControl',{type});
    control.checked=checked;f.document.activeElement=control;
    const originalValue=control.value;let changes=0;
    control.addEventListener('change',()=>changes++);
    f.escape();equal(f.frames.length,1,'checkbox/radio Escape queues name-search navigation');f.flush();
    equal(f.document.activeElement,f.today,'checkbox/radio focus moves to name search');
    equal(control.checked,checked,'Escape preserves the checked state');equal(control.value,originalValue,'Escape preserves the control value');
    equal(control.inputCount,0,'Escape emits no control input');equal(changes,0,'Escape emits no control change');
    equal(f.today.inputCount,1,'only the name-search filter is notified');
  }
}
for(const type of ['text','number','date','range','file']) {
  const f=fixture(),editor=f.element('valueEditor',{type});f.document.activeElement=editor;const draft=editor.value;
  f.escape();f.flush();equal(f.document.activeElement,editor,'value editing keeps focus');equal(editor.value,draft,'value editing keeps its draft');
}
for(const pending of [false,true]) {
  const f=fixture(),modal=f.element('extraModal',{tag:'DIV',modal:true});
  f.window.isStudentPopupSavePending=()=>pending;
  f.escape(f.body);
  equal(f.closed.length,pending?0:1,'outside-search Escape keeps popup save/close ownership');
  equal(modal.style.display,pending?'block':'none','pending popup stays open');equal(f.frames.length,0,'popup Escape does not jump to name search');
}
{
  const f=fixture(),search=f.element('laterSearch',{type:'search'});f.escape();f.document.activeElement=search;f.flush();
  equal(f.document.activeElement,search,'a newer focus is not stolen by queued navigation');equal(f.today.inputCount,0,'queued navigation does not erase another context');
}
for(const tag of ['BUTTON','A']) {
  const f=fixture(),control=f.element('laterControl',{tag});f.escape();f.document.activeElement=control;f.flush();
  equal(f.document.activeElement,control,'a newer button/link focus is not stolen');equal(f.today.inputCount,0,'button/link focus cancels queued navigation');
}
{
  const f=fixture();f.escape();f.element('newModal',{tag:'DIV',modal:true});f.flush();
  equal(f.document.activeElement,f.body,'a new popup cancels queued navigation');equal(f.today.inputCount,0,'popup context stays in place');
}
{
  const f=fixture();f.escape(f.body,{defaultPrevented:true});f.flush();equal(f.today.inputCount,0,'an earlier owner is respected');
}
console.log(`PASS admin Escape search: ${assertions} assertions, 11 searches, checkbox/radio state/event invariance, capture propagation, repeated empty, IME, editor drafts, blank navigation, modal/pending ownership and stale focus`);
