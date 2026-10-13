import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source=fs.readFileSync(process.argv[2] || path.join(root,'static/js/file-manage.js'),'utf8');
const deferred=()=> {
  let resolve,reject;
  const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
  return {promise,resolve,reject};
};
const response=(body,{status=200,revision='revision-a'}={})=>({
  ok:status>=200&&status<300,status,
  text:async()=>JSON.stringify(body),
  headers:{get:()=>revision}
});
function harness(fetcher, rows=[]){
  const listeners=new Map(),areaListeners=new Map(),alerts=[],boxes=[];
  const button={disabled:false,innerHTML:'실행'};
  const area={querySelector:()=>({}),addEventListener:(type,fn)=>{
    const list=areaListeners.get(type)||[];list.push(fn);areaListeners.set(type,list);
  }};
  const elementMap=new Map([['#amDoAssign',button],['#list',area]]);
  const document={
    querySelector:selector=>elementMap.get(selector)||null,
    querySelectorAll:selector=>selector==='#list tbody tr' ? rows : selector==='#list tbody .ck' ? rows.map(row=>row.checkbox) : [],
    createElement:()=>({style:{},remove(){this.removed=true;}}),
    body:{appendChild:box=>boxes.push(box)}
  };
  const window={addEventListener:(type,fn)=>{
    const list=listeners.get(type)||[];list.push(fn);listeners.set(type,list);
  }};
  const context=vm.createContext({document,window,fetch:fetcher,alert:value=>alerts.push(value),console});
  vm.runInContext(source+'\nwindow.qa={refresh,runAction,enableBoxSelect,getAssignSnapshot,sortList,selectOnlyFileRow};',context);
  vm.runInContext('renderTree=renderList=buildAssignFilters=renderAssignStudents=renderPickedList=renderAssignedUnion=()=>{};',context);
  return {context,qa:window.qa,button,listeners,areaListeners,boxes,alerts,
    set:code=>vm.runInContext(code,context)};
}
const roster=[{id:'one',name:'하나'},{id:'two',name:'둘'}];
const tree={tree:{type:'dir',name:'',path:'',children:[]}};
{
  const gate=deferred(),starts=[];
  const h=harness(url=>{
    starts.push(url);
    return gate.promise.then(()=>response(url==='/api/fs/tree'?tree:url==='/api/students'?roster:{}));
  });
  const pending=h.qa.refresh();
  assert.deepEqual(starts,['/api/fs/tree','/api/students','/api/mat-assign']);
  assert.equal(h.button.disabled,true);
  gate.resolve();await pending;
  assert.equal(h.button.disabled,false);
}
{
  let failing=false,postCount=0;
  const h=harness(async(url,init)=>{
    if(init?.method==='POST'){postCount++;return response({});}
    if(url==='/api/students'&&failing)throw new Error('synthetic roster failure');
    return response(url==='/api/fs/tree'?tree:url==='/api/students'?roster:{one:['kept']});
  });
  await h.qa.refresh();failing=true;
  await assert.rejects(h.qa.refresh(),/synthetic roster failure/);
  h.set('PICKED=[{type:"file",path:"kept",url:"kept"}];');
  await h.qa.runAction();
  assert.equal(h.button.disabled,true);
  assert.equal(postCount,0,'failed roster load cannot become global removal');
}
{
  const h=harness(async()=>response([]));
  await assert.rejects(h.qa.getAssignSnapshot(),/배정 정보를 읽을 수 없습니다/);
}
{
  const oldGate=deferred();let rosterReads=0;
  const h=harness(async url=>{
    if(url==='/api/students'){
      const read=++rosterReads;
      if(read===1)await oldGate.promise;
      return response(read===1?[{id:'stale'}]:roster);
    }
    return response(url==='/api/fs/tree'?tree:{});
  });
  const older=h.qa.refresh();
  await h.qa.refresh();
  oldGate.resolve();await older;
  assert.equal(h.set('JSON.stringify(STUDENTS.map(row=>row.id))'),JSON.stringify(['one','two']));
}
{
  const readGate=deferred();let assignmentReads=0;const posts=[];
  const h=harness(async(url,init)=>{
    if(init?.method==='POST'){posts.push(JSON.parse(init.body));return response({});}
    if(url==='/api/mat-assign'){
      assignmentReads++;
      if(assignmentReads>1)await readGate.promise;
      return response({outsider:['first','keep'],one:['prior']});
    }
    return response(url==='/api/fs/tree'?tree:roster);
  });
  await h.qa.refresh();
  h.set('PICKED=[{type:"file",path:"first",url:"first"}];');
  const save=h.qa.runAction();
  h.set('PICKED.push({type:"file",path:"later",url:"later"});');
  await h.qa.runAction();
  readGate.resolve();await save;
  assert.equal(posts.length,1,'duplicate saves must share the active command');
  assert.deepEqual(posts[0],{outsider:['keep'],one:['prior','first'],two:['first']});
  assert.equal(h.set('JSON.stringify(PICKED.map(row=>row.path))'),JSON.stringify(['later']));
}
{
  const h=harness(async()=>response({}));
  for(let index=0;index<20;index++)h.qa.enableBoxSelect();
  assert.equal(h.areaListeners.get('mousedown').length,1);
  assert.equal(h.listeners.get('mousemove').length,1);
  assert.equal(h.listeners.get('mouseup').length,1);
  h.areaListeners.get('mousedown')[0]({
    button:0,target:{closest:()=>null},clientX:10,clientY:20,
    ctrlKey:false,metaKey:false,shiftKey:false,preventDefault(){}
  });
  assert.equal(h.boxes.length,1,'one drag creates one selection box after repeated renders');
  h.listeners.get('mouseup')[0]();
  assert.equal(h.boxes[0].removed,true);
}

{
  const postGate=deferred(),treeGate=deferred(),starts=[];
  let saved=false,treeReads=0;
  const h=harness(async(url,init)=>{
    starts.push({url,method:init?.method||'GET'});
    if(init?.method==='POST'){await postGate.promise;saved=true;return response({});}
    if(url==='/api/fs/tree' && ++treeReads>1)await treeGate.promise;
    if(url==='/api/mat-assign')return response({one:saved?['prior','new']:['prior']});
    return response(url==='/api/fs/tree'?tree:roster);
  });
  await h.qa.refresh();
  h.set('PICKED=[{type:"file",path:"new",url:"new"}];');
  const save=h.qa.runAction();
  await new Promise(resolve=>setImmediate(resolve));
  const refresh=h.qa.refresh();
  assert.equal(starts.filter(row=>row.url==='/api/fs/tree').length,1,'refresh must wait for an active assignment commit');
  postGate.resolve();await save;
  treeGate.resolve();await refresh;
  assert.equal(h.set('JSON.stringify(ASSIGNS.one)'),JSON.stringify(['prior','new']),'refresh cannot replace committed assignments with a pre-commit snapshot');
}

{
  const order=[];
  const rows=Array.from({length:500},(_,index)=>{
    const row={dataset:{path:`file-${index}`},top:index*20,selected:false};
    row.checkbox={checked:false};
    row.classList={
      add(){order.push('write');row.selected=true;},
      remove(){order.push('write');row.selected=false;}
    };
    row.querySelector=()=>row.checkbox;
    row.getBoundingClientRect=()=>{
      order.push('read');
      return {left:0,right:100,top:row.top,bottom:row.top+19};
    };
    return row;
  });
  const h=harness(async()=>response({}),rows);
  h.qa.enableBoxSelect();
  h.areaListeners.get('mousedown')[0]({
    button:0,target:{closest:()=>null},clientX:10,clientY:25,
    ctrlKey:false,metaKey:false,shiftKey:false,preventDefault(){}
  });
  h.boxes[0].style=new Proxy({}, {set(target,key,value){order.push('write');target[key]=value;return true;}});
  const move=h.listeners.get('mousemove')[0];
  for (const selected of [['file-1','file-2'],['file-2']]) {
    order.length=0;
    move({clientX:90,clientY:55});
    assert.ok(order.slice(0,500).every(value=>value==='read'),'all current row rectangles must be read before any style/class write');
    assert.ok(order.slice(500).every(value=>value==='write'));
    assert.deepEqual(rows.filter(row=>row.selected).map(row=>row.dataset.path),selected);
    assert.deepEqual(rows.filter(row=>row.checkbox.checked).map(row=>row.dataset.path),selected);
    assert.deepEqual(JSON.parse(h.set('JSON.stringify([...SELECTED])')),selected);
    rows[1].top=10001;
  }
  h.listeners.get('mouseup')[0]();
  assert.equal(h.boxes[0].removed,true);
  assert.equal(h.set('_boxSelecting'),false);
  h.areaListeners.get('mousedown')[0]({
    button:0,target:{closest:selector=>selector.includes('thead')?{}:null},clientX:10,clientY:0,
    ctrlKey:false,metaKey:false,shiftKey:false,preventDefault(){assert.fail('sort header must not begin box selection');}
  });
  assert.equal(h.boxes.length,1);
  assert.deepEqual(JSON.parse(h.set('JSON.stringify([...SELECTED])')),['file-2'],'sorting must not clear an existing box selection on mousedown');
}

{
  const facts = [
    {id:'folder',type:'dir',name:'폴더',mtime:100},
    {id:'a',type:'file',name:'가',size:50,mtime:30},
    {id:'b',type:'file',name:'Z'},
    {id:'c',type:'file',name:'A',size:50,mtime:5},
    {id:'d',type:'file',name:'A',size:50,mtime:5},
    {id:'e',type:'file',name:'0',size:1,mtime:5},
    {id:'f',type:'file',name:'B',size:2},
  ];
  const rows = facts.map(fact => {
    const row={dataset:{path:fact.id,type:fact.type},checkbox:{checked:['a','b'].includes(fact.id)},selected:['a','b'].includes(fact.id)};
    row.classList={add(){row.selected=true;},remove(){row.selected=false;}};
    row.querySelector=selector=>selector==='.ck'?row.checkbox:{textContent:fact.name};
    return row;
  });
  const h=harness(()=>{throw new Error('sort tests cannot use transport');},rows);
  const tbody={children:rows.slice(),appendChild(row){this.children.splice(this.children.indexOf(row),1);this.children.push(row);}};
  h.context.document.querySelector=selector=>selector==='#list tbody'?tbody:null;
  h.context.facts=facts;h.context.lookups=0;
  h.set('TREE={type:"dir",children:facts.map(f=>({...f,name:f.id}))}; SELECTED=new Set(["a","b"]); const readNode=getNodeByPath; getNodeByPath=p=>{lookups++;return readNode(p);};');
  const checkSort=(key,expected)=>{
    h.context.lookups=0;h.qa.sortList(key);
    assert.deepEqual(tbody.children.map(row=>row.dataset.path),expected);
    assert.ok(h.context.lookups<=rows.length,'each row sort key is read at most once per sort');
    assert.deepEqual(JSON.parse(h.set('JSON.stringify([...SELECTED])')),['a','b']);
    assert.deepEqual(rows.filter(row=>row.checkbox.checked).map(row=>row.dataset.path),['a','b']);
    assert.deepEqual(rows.filter(row=>row.selected).map(row=>row.dataset.path),['a','b']);
    assert.equal(new Set(tbody.children).size,rows.length,'sorting moves the original row objects');
  };
  checkSort('size',['folder','b','e','f','a','c','d']);
  checkSort('size',['a','c','d','f','e','b','folder']);
  h.set('TREE.children.find(f=>f.name==="b").size=100; TREE.children.find(f=>f.name==="c").size=1;');
  checkSort('size',['folder','c','e','f','a','d','b']);
  checkSort('mtime',['f','b','c','e','d','a','folder']);
  checkSort('mtime',['folder','a','c','e','d','f','b']);
  checkSort('name',['folder','e','c','d','f','b','a']);
  checkSort('name',['a','b','f','c','d','e','folder']);
  facts[3].name='ZZ';
  checkSort('name',['folder','e','d','f','b','c','a']);
  h.qa.selectOnlyFileRow(rows[6]);
  assert.deepEqual(JSON.parse(h.set('JSON.stringify([...SELECTED])')),['f']);
  assert.deepEqual(rows.filter(row=>row.checkbox.checked).map(row=>row.dataset.path),['f']);
  assert.deepEqual(rows.filter(row=>row.selected).map(row=>row.dataset.path),['f']);
}

for(const modifier of ['ctrlKey','metaKey','shiftKey','none']) {
  const rows=['a','b','c'].map((path,index)=>{
    const row={dataset:{path},selected:index===0,checkbox:{checked:index===0}};
    row.classList={add(){row.selected=true;},remove(){row.selected=false;}};
    row.querySelector=()=>row.checkbox;
    row.getBoundingClientRect=()=>({left:0,right:100,top:index*20,bottom:index*20+19});
    return row;
  });
  const h=harness(async()=>response({}),rows);
  h.set('SELECTED.add("a");');h.qa.enableBoxSelect();
  h.areaListeners.get('mousedown')[0]({button:0,target:{closest:()=>null},clientX:10,clientY:25,ctrlKey:false,metaKey:false,shiftKey:false,[modifier]:true,preventDefault(){}});
  const move=h.listeners.get('mousemove')[0];
  move({clientX:90,clientY:55});
  const first=modifier==='none'?['b','c']:['a','b','c'];
  assert.deepEqual(JSON.parse(h.set('JSON.stringify([...SELECTED].sort())')),first,`${modifier}: preserve the initial selection only for additive box selection`);
  assert.deepEqual(rows.filter(r=>r.selected&&r.checkbox.checked).map(r=>r.dataset.path),first,`${modifier}: DOM and selected paths agree`);
  move({clientX:90,clientY:35});
  const narrowed=modifier==='none'?['b']:['a','b'];
  assert.deepEqual(JSON.parse(h.set('JSON.stringify([...SELECTED].sort())')),narrowed,`${modifier}: remove prior drag hits outside the new box while retaining only the initial additive selection`);
  h.listeners.get('mouseup')[0]();
  move({clientX:90,clientY:55});
  assert.deepEqual(JSON.parse(h.set('JSON.stringify([...SELECTED].sort())')),narrowed,`${modifier}: mouseup ends box selection`);
}
console.log('file-manager checks passed: parallel reads, failure lock, stale load/save, drag rectangles, additive box selection, sort literals/freshness/key counts and selection consistency');
