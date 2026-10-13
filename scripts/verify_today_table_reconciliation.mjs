import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

// Source-only VM gate. The small DOM model below is deliberately independent
// of the reconciliation algorithm. It is not a browser/layout/parser test.
const args=process.argv.slice(2), arg=(name,fallback)=>args.includes(name)?args[args.indexOf(name)+1]:fallback;
const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(arg('--root',path.join(here,'..')));
const sourcePath=path.resolve(arg('--source',path.join(root,'static/js/admin/features/today.render.js')));
const temp=path.resolve(process.env.TEMP||process.env.TMP||'');
const out=path.resolve(arg('--out',path.join(temp,'verify-today-table-reconciliation')));
assert.ok(temp&&(out===temp||out.startsWith(temp+path.sep)),'write only in Temp');
fs.mkdirSync(out,{recursive:true});
const bytes=fs.readFileSync(sourcePath), source=bytes.toString('utf8').replaceAll('\r\n','\n');
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
fs.writeFileSync(path.join(out,'today.render.frozen.js'),bytes);
const begin=source.indexOf('function ensureSelfStudyHeader(');
const end=source.indexOf('export function renderToday(',begin);
assert.ok(begin>=0&&end>begin,'actual header/reconciliation source boundaries');
const executedSource=source.slice(begin,end);

// Live collections evaluate on every length/index/iteration access. Moving a
// <td> from a parsed next row therefore changes nextRow.cells immediately.
const live=read=>new Proxy({}, {get(_,key){
  const values=read();
  if(key===Symbol.iterator)return values[Symbol.iterator].bind(values);
  if(key==='length')return values.length;
  if(/^\d+$/.test(String(key)))return values[Number(key)];
  return values[key]?.bind?.(values);
}});
const decode=text=>text.replace(/&(?:amp|lt|gt|quot|#39);/g,x=>({
  '&amp;':'&','&lt;':'<','&gt;':'>','&quot;':'"','&#39;':"'"})[x]);
class Text {
  constructor(text){this.textContent=text;this.nodeType=3;this.parentNode=null;}
  remove(){if(this.parentNode){const p=this.parentNode;p.childNodes.splice(p.childNodes.indexOf(this),1);this.parentNode=null;}}
}
class Element {
  constructor(tag,attrs=[]){this.tagName=tag.toLowerCase();this.nodeType=1;this.attrs=new Map(attrs);this.childNodes=[];this.parentNode=null;this._checked=this.attrs.has('checked');}
  get attributes(){return [...this.attrs].map(([name,value])=>({name,value}));}
  get children(){return this.childNodes.filter(n=>n.nodeType===1);}
  get cells(){return live(()=>this.children.filter(n=>n.tagName==='td'||n.tagName==='th'));}
  get rows(){return live(()=>this.children.filter(n=>n.tagName==='tr'));}
  get tBodies(){return live(()=>this.children.filter(n=>n.tagName==='tbody'));}
  get firstElementChild(){return this.children[0]||null;}
  get nextElementSibling(){const a=this.parentNode?.children||[];return a[a.indexOf(this)+1]||null;}
  get dataset(){const data={};for(const [key,value]of this.attrs)if(key.startsWith('data-'))data[key.slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=value;return data;}
  get className(){return this.getAttribute('class')||'';} set className(value){this.setAttribute('class',value);}
  get hidden(){return this.hasAttribute('hidden');} set hidden(value){if(value)this.setAttribute('hidden','');else this.removeAttribute('hidden');}
  get checked(){return this._checked;} set checked(value){this._checked=Boolean(value);}
  get textContent(){return this.childNodes.map(n=>n.textContent).join('');}
  set textContent(value){this.clear();this.appendChild(new Text(String(value)));}
  hasAttribute(name){return this.attrs.has(name);}
  getAttribute(name){return this.attrs.get(name)??null;}
  setAttribute(name,value){this.attrs.set(name,String(value));}
  removeAttribute(name){this.attrs.delete(name);}
  appendChild(node){return this.insertBefore(node,null);}
  insertBefore(node,cursor){
    if(node===cursor)return node;
    assert.ok(!cursor||cursor.parentNode===this,'DOM insertBefore cursor belongs to parent');
    node.remove();const i=cursor?this.childNodes.indexOf(cursor):this.childNodes.length;
    this.childNodes.splice(i,0,node);node.parentNode=this;return node;
  }
  remove(){Text.prototype.remove.call(this);}
  replaceWith(node){if(!this.parentNode)return;const p=this.parentNode;p.insertBefore(node?.nodeType?node:new Text(String(node)),this);this.remove();}
  clear(){for(const node of this.childNodes)node.parentNode=null;this.childNodes=[];}
  set innerHTML(markup){this.clear();for(const node of parse(markup).childNodes.slice())this.appendChild(node);}
  matches(selector){
    const m=selector.match(/^([\w-]+)?(?:\.([\w-]+))?(?:\[([\w-]+)\])?$/);
    assert.ok(m,'supported selector '+selector);
    return (!m[1]||this.tagName===m[1])&&(!m[2]||this.className.split(/\s+/).includes(m[2]))&&(!m[3]||this.hasAttribute(m[3]));
  }
  querySelectorAll(selector){
    const parts=selector.split(/\s+/),nodes=[];
    const visit=node=>{for(const child of node.children){
      if(child.matches(parts.at(-1))){let parent=child.parentNode,i=parts.length-2;
        while(i>=0&&parent){if(parent.nodeType===1&&parent.matches(parts[i]))i--;parent=parent.parentNode;}
        if(i<0)nodes.push(child);
      }visit(child);
    }};visit(this);return nodes;
  }
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  isEqualNode(other){return !!other&&JSON.stringify(tree(this,false))===JSON.stringify(tree(other,false));}
}
function parse(markup){
  const root=new Element('fragment'),stack=[root],voidTags=new Set(['input','col','br','hr','img']);
  for(const token of String(markup).match(/<!--[\s\S]*?-->|<[^>]+>|[^<]+/g)||[]){
    if(token.startsWith('<!--'))continue;
    if(token.startsWith('</')){assert.equal(stack.at(-1).tagName,token.match(/^<\/([\w-]+)/)[1]);stack.pop();continue;}
    if(token.startsWith('<')){
      const match=token.match(/^<([\w-]+)([\s\S]*?)\/?\s*>$/);assert.ok(match,'literal valid tag');
      const attrs=[];for(const a of match[2].matchAll(/([^\s=\/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g))attrs.push([a[1],decode(a[2]??a[3]??a[4]??'')]);
      const el=new Element(match[1],attrs);stack.at(-1).appendChild(el);
      if(!voidTags.has(el.tagName)&&!token.endsWith('/>'))stack.push(el);
    }else if(token.trim())stack.at(-1).appendChild(new Text(decode(token)));
  }
  assert.equal(stack.length,1,'literal balanced HTML');return root;
}
function tree(node,properties=true){
  if(node.nodeType===3)return node.textContent;
  const result={tag:node.tagName,attrs:[...node.attrs].sort(([a],[b])=>a.localeCompare(b)),children:node.childNodes.map(n=>tree(n,properties))};
  if(properties&&node.tagName==='input')result.checked=node.checked;
  return result;
}
function environment(code=executedSource,templateSupported=true){
  const document={createElement(tag){const el=new Element(tag);if(tag==='template'&&templateSupported){el.content=new Element('fragment');Object.defineProperty(el,'innerHTML',{set(markup){el.content.innerHTML=markup;}});}return el;}};
  const context=vm.createContext({document});vm.runInContext(code,context,{filename:'actual/today.render.reconciliation.js'});return context;
}
const env=environment(), A='2026-10-03',B='2026-10-05';
const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const row=(date,sid,cells,attrs='')=>`<tr data-date="${esc(date)}" data-sid="${esc(sid)}" ${attrs}>${cells.map(text=>`<td>${text}</td>`).join('')}</tr>`;
const R=(sid,text,attrs='',date=A)=>row(date,sid,[text,'수학','13:00'],attrs);
const a=R('1','가학생'),b=R('2','나학생'),c=R('3','다학생');
const table=(rows,header='<th>이름</th><th>과목</th><th>도착</th>',cols='<col style="width:120px"><col style="width:84px"><col style="width:84px">',attrs='',cls='today-table')=>
  `<table class="${cls}" ${attrs}><colgroup>${cols}</colgroup><thead><tr>${header}</tr></thead><tbody>${rows}</tbody></table>`;
const host=markup=>{const el=new Element('div');el.innerHTML=markup;return el;};
const rows=el=>Array.from(el.querySelector('tbody')?.rows||[]);
const textRows=el=>rows(el).map(r=>[r.dataset.date,r.dataset.sid,...Array.from(r.cells,x=>x.textContent)]);
const records=[];
function test(label,before,after,expected,inspect=()=>{},prepare=()=>{},options={}){
  const h=host(before),oldTable=h.querySelector('table'),oldRows=rows(h);prepare(h,oldRows);
  const oracle=host(after),runner=options.env||env;
  runner.replaceStudentTable(h,after,options.class||'today-table');
  if(options.selfHeader){runner.ensureSelfStudyHeader(h);runner.ensureSelfStudyHeader(oracle);}
  assert.deepEqual(textRows(h),expected,label+' literal rows');
  assert.deepEqual(tree(h),tree(oracle),label+' equals original whole-markup replacement DOM');
  inspect(h,oldRows,oldTable);
  records.push({label,beforeMarkupSha256:sha(before),nextMarkupSha256:sha(after),finalDomSha256:sha(JSON.stringify(tree(h)))});
}
const texts=(...items)=>items.map(([sid,name,date=A])=>[date,sid,name,'수학','13:00']);
test('initial table render fallback','오늘 학생 없음',table(a),texts(['1','가학생']));
test('unchanged table retains table rows and all cells',table(a+b),table(a+b),texts(['1','가학생'],['2','나학생']),
  (h,old,t)=>{assert.equal(h.querySelector('table'),t);assert.equal(rows(h)[0],old[0]);assert.equal(rows(h)[1],old[1]);assert.equal(rows(h)[0].cells[1],old[0].savedCell);},
  (_,old)=>{old[0].savedCell=old[0].cells[1];});
test('reorder keeps row identities',table(a+b+c),table(c+a+b),texts(['3','다학생'],['1','가학생'],['2','나학생']),
  (h,old)=>assert.deepEqual(rows(h),[old[2],old[0],old[1]]));
test('prepend new row keeps existing rows',table(a+b),table(c+a+b),texts(['3','다학생'],['1','가학생'],['2','나학생']),
  (h,old)=>{assert.equal(rows(h)[1],old[0]);assert.equal(rows(h)[2],old[1]);});
test('append new row keeps existing rows',table(a+b),table(a+b+c),texts(['1','가학생'],['2','나학생'],['3','다학생']),
  (h,old)=>{assert.equal(rows(h)[0],old[0]);assert.equal(rows(h)[1],old[1]);});
test('delete middle row removes detached stale row',table(a+b+c),table(c+a),texts(['3','다학생'],['1','가학생']),
  (h,old)=>{assert.deepEqual(rows(h),[old[2],old[0]]);assert.equal(old[1].parentNode,null);});
test('same SID on new date creates new row',table(a),table(R('1','가학생','',B)),texts(['1','가학생',B]),
  (h,old)=>{assert.notEqual(rows(h)[0],old[0]);assert.equal(old[0].parentNode,null);});
test('same SID distinct dates reorder independently',table(a+R('1','월학생','',B)),table(R('1','월학생','',B)+a),texts(['1','월학생',B],['1','가학생']),
  (h,old)=>assert.deepEqual(rows(h),[old[1],old[0]]));
test('duplicate keys retain each first unmatched old occurrence',table(R('1','첫째')+R('1','둘째')+b),table(R('1','첫째수정')+R('1','둘째')+b),texts(['1','첫째수정'],['1','둘째'],['2','나학생']),
  (h,old)=>assert.deepEqual(rows(h),old));
test('duplicate keys shrink retains first occurrence',table(R('1','첫째')+R('1','둘째')),table(R('1','남김')),texts(['1','남김']),
  (h,old)=>{assert.equal(rows(h)[0],old[0]);assert.equal(old[1].parentNode,null);});
test('duplicate keys grow uses old row once',table(R('1','첫째')),table(R('1','첫째')+R('1','둘째')+R('1','셋째')),texts(['1','첫째'],['1','둘째'],['1','셋째']),
  (h,old)=>{assert.equal(rows(h)[0],old[0]);assert.equal(new Set(rows(h)).size,3);});
test('all cells replace against live next-row cells',table(row(A,'1',['구이름','영어','10:00'])),table(row(A,'1',['새이름','수학','18:05'])),[[A,'1','새이름','수학','18:05']],
  (h,old)=>{assert.equal(rows(h)[0],old[0]);assert.equal(rows(h)[0].cells.length,3);});
test('changed cell count replaces entire old row',table(row(A,'1',['가','수학'])),table(a),texts(['1','가학생']),
  (h,old)=>{assert.notEqual(rows(h)[0],old[0]);assert.equal(old[0].parentNode,null);});
test('fewer cells replaces entire old row',table(a),table(row(A,'1',['가','수학'])),[[A,'1','가','수학']],
  (h,old)=>{assert.notEqual(rows(h)[0],old[0]);assert.equal(rows(h)[0].cells.length,2);});
const checkbox=checked=>row(A,'1',[`<input type="checkbox" ${checked?'checked':''}>`,'수학','13:00']);
for(const checked of [true,false])test('equal checked attribute repairs dirty property '+checked,table(checkbox(checked)),table(checkbox(checked)),[[A,'1','','수학','13:00']],
  (h,old)=>{const input=rows(h)[0].querySelector('input');assert.equal(input,old[0].savedInput);assert.equal(input.checked,checked);assert.equal(input.hasAttribute('checked'),checked);},
  (_,old)=>{old[0].savedInput=old[0].querySelector('input');old[0].savedInput.checked=!checked;});
test('changed checked attribute replaces cell with authoritative property',table(checkbox(false)),table(checkbox(true)),[[A,'1','','수학','13:00']],
  (h,old)=>{assert.notEqual(rows(h)[0].querySelector('input'),old[0].savedInput);assert.equal(rows(h)[0].querySelector('input').checked,true);},
  (_,old)=>{old[0].savedInput=old[0].querySelector('input');});
const multiple=row(A,'1',['<input type="checkbox" checked><input type="checkbox">','수학','13:00']);
test('multiple equal inputs repair separate dirty properties',table(multiple),table(multiple),[[A,'1','','수학','13:00']],
  h=>assert.deepEqual(h.querySelectorAll('input').map(x=>x.checked),[true,false]),
  h=>{for(const input of h.querySelectorAll('input'))input.checked=!input.checked;});
test('search hidden class aria and hidden restore from new markup',table(R('1','가학생','class="student"')),table(R('1','가학생','class="student"')),texts(['1','가학생']),
  (h,old)=>{assert.equal(rows(h)[0],old[0]);assert.equal(old[0].hidden,false);assert.equal(old[0].className,'student');assert.equal(old[0].getAttribute('aria-hidden'),null);},
  (_,old)=>{old[0].hidden=true;old[0].className='student is-search-hidden';old[0].setAttribute('aria-hidden','true');});
test('row and table attributes replace removed values',table(R('1','가학생','data-old="gone" class="old"'),'','','data-old="gone"'),table(R('1','가학생','data-new="fresh" class="new"'),'','','data-new="fresh"'),texts(['1','가학생']),
  (h,old,t)=>{assert.equal(h.querySelector('table'),t);assert.equal(rows(h)[0],old[0]);assert.equal(old[0].getAttribute('data-old'),null);assert.equal(old[0].getAttribute('data-new'),'fresh');});
test('changed header and widths replace only metadata',table(a),table(a,'<th>학생 이름</th><th>과목</th><th>등원</th>','<col style="width:130px"><col style="width:84px"><col style="width:84px">'),texts(['1','가학생']),
  (h,old,t)=>{assert.equal(h.querySelector('table'),t);assert.equal(rows(h)[0],old[0]);assert.notEqual(h.querySelector('colgroup'),t.savedCols);assert.notEqual(h.querySelector('thead'),t.savedHead);},
  (h,_,t)=>{h.querySelector('table').savedCols=h.querySelector('colgroup');h.querySelector('table').savedHead=h.querySelector('thead');});
test('unchanged header and widths retain metadata',table(a),table(b),texts(['2','나학생']),
  (h,_,t)=>{assert.equal(h.querySelector('colgroup'),t.savedCols);assert.equal(h.querySelector('thead'),t.savedHead);},
  h=>{h.querySelector('table').savedCols=h.querySelector('colgroup');h.querySelector('table').savedHead=h.querySelector('thead');});
const todaySource=source.slice(source.indexOf('export function renderToday('),source.indexOf('export function renderDone('));
const actualCols=todaySource.match(/<colgroup>([\s\S]*?)<\/colgroup>/)[1];
const actualHead=todaySource.match(/<thead>\s*<tr>([\s\S]*?)<\/tr>\s*<\/thead>/)[1];
assert.deepEqual([...actualCols.matchAll(/width:(\d+)px/g)].map(m=>Number(m[1])),[32,72,120,84,168,44,84,84,112,36,36,232,64,56],'literal canonical today widths');
const fullRow=row(A,'1',['','토1','가학생','13:00','출석','자습','숙검','학교','수학','진도','백지','작업','0','문서']);
const oldHead='<th></th><th>구분</th><th>이름</th><th>도착</th><th>출석/연락/숙제</th><th class="today-self-study-head">자습</th><th>숙검요청</th><th>학교</th><th>커리큘럼</th><th>진도</th><th>백지</th><th>작업</th><th>보강</th><th>문서</th>';
test('actual today header self-study reinsertion and fourteen widths',table(fullRow,oldHead,actualCols),table(fullRow,actualHead,actualCols),
  [[A,'1','','토1','가학생','13:00','출석','자습','숙검','학교','수학','진도','백지','작업','0','문서']],
  (h,old)=>{assert.deepEqual(Array.from(h.querySelector('thead tr').cells,x=>x.textContent),['','구분','이름','도착','출석/연락/숙제','자습','숙검요청','학교','커리큘럼','진도','백지','작업','보강','문서']);assert.equal(h.querySelectorAll('col').length,14);assert.equal(rows(h)[0].cells.length,14);assert.equal(rows(h)[0],old[0]);},
  ()=>{}, {selfHeader:true});
test('empty list removes whole old table',table(a+b),'오늘 학생 없음',[],(h,_,t)=>{assert.equal(h.textContent,'오늘 학생 없음');assert.equal(t.parentNode,null);});
test('empty tbody retains table but removes all old rows',table(a+b),table(''),[],(h,old,t)=>{assert.equal(h.querySelector('table'),t);assert.ok(old.every(r=>r.parentNode===null));});
test('missing current body falls back to whole markup',`<table class="today-table"><thead><tr><th>이름</th></tr></thead></table>`,table(a),texts(['1','가학생']));
test('missing next body falls back to whole markup',table(a),'<table class="today-table"><thead><tr><th>이름</th></tr></thead></table>',[]);
test('no template support preserves original fallback',table(a),table(b),texts(['2','나학생']),
  (h,_,t)=>assert.notEqual(h.querySelector('table'),t),()=>{}, {env:environment(executedSource,false)});
test('done table class uses identical keyed reconciliation',table(a+b,undefined,undefined,'','done-table'),table(b+a,undefined,undefined,'','done-table'),texts(['2','나학생'],['1','가학생']),
  (h,old)=>assert.deepEqual(rows(h),[old[1],old[0]]),()=>{}, {class:'done-table'});

// Prove the live-collection fixture detects the former regression, rather than
// merely blessing the production code's own expected output.
const broken=executedSource.replace('const nextCells = Array.from(nextRow.cells);','const nextCells = nextRow.cells;');
assert.notEqual(broken,executedSource,'live-collection negative control applies');
const negative=environment(broken),negativeHost=host(table(row(A,'1',['구이름','영어','10:00'])));
negative.replaceStudentTable(negativeHost,table(row(A,'1',['새이름','수학','18:05'])),'today-table');
assert.notDeepEqual(textRows(negativeHost),[[A,'1','새이름','수학','18:05']],'negative control detects missing Array.from');
const result={ok:true,cases:records.length,negativeControls:1,records,sourcePath,
  sourceSha256:sha(bytes),executedSourceSha256:sha(executedSource),
  currentSourceMatches:sha(fs.readFileSync(sourcePath))===sha(bytes),
  limits:'DOM stub only: live collection movement, node identity, attributes and checked properties. Normalized element/text tree omits structural whitespace. No actual HTML table parser, layout, focus, browser event/listener, Sortable or real search integration evidence.',
  appImports:0,http:0,browser:0,runtimeDataAccess:0,repositoryWrites:0,git:0};
fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
fs.writeFileSync(path.join(out,'report.txt'),`PASS ${result.cases} actual-source reconciliation cases + ${result.negativeControls} live-cell negative control.\nSource SHA-256: ${result.sourceSha256}\nCurrent source matches: ${result.currentSourceMatches}\n${result.limits}\nTemp-only writes; HTTP/browser/app/runtime/Git 0.\n`);
console.log(`PASS ${result.cases} cases + 1 negative control; ${path.join(out,'result.json')}`);
