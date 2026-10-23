import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { projectDailyMetrics, trailingDates } from '../static/js/admin/features/operationsProjection.js';

const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  const nodes = new Map(), reads = [], drawings = [], closeEvents = [];
  const element = (tag = '') => {
    const el = { dataset: {}, style: {}, open:false, textContent:'', value:'', disabled:false, listeners:{},
      setAttribute(){}, removeAttribute(){}, append(){}, replaceChildren(){}, focus(){},
      addEventListener(type,fn){ (this.listeners[type] ||= []).push(fn); },
      click(){ this.listeners.click?.forEach(fn=>fn()); },
      showModal(){ this.open=true; }, close(){ this.open=false; closeEvents.push(()=>this.listeners.close?.forEach(fn=>fn())); },
      querySelectorAll(selector){ return selector==='[data-ops-tab]' ? tabs : selector==='[data-ops-panel]' ? panels : []; },
    };
    Object.defineProperty(el,'id',{set(value){nodes.set(value,el);},get(){return [...nodes].find(([,value])=>value===el)?.[0];}});
    return el;
  };
  const tabs = ['pending','stats','history','health'].map(tab=>Object.assign(element(),{dataset:{opsTab:tab}}));
  const panels = tabs.map(tab=>Object.assign(element(),{dataset:{opsPanel:tab.dataset.opsTab}}));
  for(const id of ['todayWrap','opsToolkitNotice','opsStatsRefresh','opsStatsStatus','opsStatsRows','opsWorkSearch','opsWorkKind','opsWorkCount','opsWorkRefresh','opsWeeklyChart','opsToolkitClose','opsSaveHistory']) nodes.set(id,element());
  const document = {createElement:element,head:element(),body:element(),getElementById:id=>nodes.get(id),querySelector:()=>element(),querySelectorAll:()=>[],addEventListener(){}};
  document.body.classList={contains:()=>false};
  const chart={clear(){},resize(){},setOption(options){drawings.push(options);}};
  const context=vm.createContext({document,location:{pathname:'/admin'},state:{students:[]},window:{},console,
    ResizeObserver:class{observe(){}},MutationObserver:class{observe(){}},setInterval:()=>1,clearInterval(){},setTimeout,clearTimeout,
    getAdminDate:()=> '2026-10-24',matchesSearchText:()=>true,SEARCH_HELP_TEXT:'검색',
    projectPendingWork:()=>[],projectDailyMetrics,trailingDates,getSaveOperations:()=>[],saveStageLabel:String,
    loadToolkitLibrary:async name=>name==='echarts'?{init:()=>chart}:function(){},
    api:{getStrict:url=>new Promise((resolve,reject)=>reads.push({url,resolve,reject}))},
  });
  const source=fs.readFileSync(new URL('../static/js/admin/features/operationsToolkit.js',import.meta.url),'utf8')
    .replace(/^import .+;\r?\n/gm,'').replace(/\bexport /g,'');
  vm.runInContext(source+'\ninitOperationsToolkit();',context);
  const open=()=>nodes.get('operationsToolkitOpen').click();
  const select=name=>tabs.find(tab=>tab.dataset.opsTab===name).click();
  const resolve=read=>{
    const date=new URL(read.url,'http://qa').searchParams.get('date');
    read.resolve(read.url.startsWith('/api/attendance')?{a:true}:read.url.startsWith('/api/logs')?{[date]:{a:{hwChecked:true}}}:{[date]:{a:{v:'done'}}});
  };
  return {nodes,reads,drawings,closeEvents,open,select,resolve};
}

{
  const f=fixture(); f.open(); f.nodes.get('operationsToolkit').close(); f.open(); f.select('stats');
  f.closeEvents.splice(0).forEach(fn=>fn());
  for(let day=0;day<7;day++) { await tick(); assert.equal(f.reads.length,(day+1)*3); f.reads.slice(day*3,day*3+3).forEach(f.resolve); }
  await tick();
  assert.equal(f.drawings.length,1,'a previous close event must not cancel the reopened statistics');
  assert.deepEqual(Array.from(f.drawings[0].series[0].data),[1,1,1,1,1,1,1]);
  assert.equal(f.nodes.get('opsStatsRefresh').disabled,false);
  assert.match(f.nodes.get('opsStatsStatus').textContent,/2026-10-18 ~ 2026-10-24/);
}
{
  const f=fixture(); f.open(); f.select('stats'); await tick(); f.select('history');
  f.reads.forEach(f.resolve); await tick();
  assert.equal(f.drawings.length,0,'late statistics responses cannot draw over a different tab');
  assert.equal(f.reads.length,3,'cancelled date batches stop before the next date');
  f.select('stats'); await tick();
  f.reads[3].reject(new Error('synthetic outage')); f.reads.slice(4).forEach(f.resolve); await tick();
  assert.match(f.nodes.get('opsStatsStatus').textContent,/불러오지 못했습니다/);
  assert.equal(f.nodes.get('opsStatsRefresh').disabled,false,'failed load allows retry');
}
console.log('PASS toolkit async: queued close/reopen, stale tab responses, bounded date reads and failed-load retry.');
