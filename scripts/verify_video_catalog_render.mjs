import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {performance} from 'node:perf_hooks';
import {fileURLToPath} from 'node:url';
import {searchKeyForText,matchesSearchKey} from '../static/js/shared/search.js';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
function renderer(sourcePath,rows,query=''){
  const source=fs.readFileSync(sourcePath,'utf8').replaceAll('\r\n','\n');
  const start=source.indexOf('    function drawVid() {');
  const end=source.indexOf('\n    const videoSection',start);
  assert.ok(start>=0&&end>start,'real drawVid function must be available');
  const table={innerHTML:'',querySelectorAll:()=>[]};
  const document={getElementById:id=>({value:id==='videoSearch'?query:''})};
  let searchCalls=0;
  const draw=new Function('videos','vidTable','document','searchKeyForText','matchesSearchKey',
    source.slice(start,end)+'\nreturn drawVid;')(
    rows,table,document,text=>{searchCalls++;return searchKeyForText(text);},matchesSearchKey
  );
  return {draw,table,searchCalls:()=>searchCalls};
}
const current=path.join(root,'static/js/video-manage.js');
const rows=[
  {id:3,curriculum:'대수',subCurriculum:'APEX',chapter:3,title:'셋',url:'https://example.invalid/three'},
  {id:1,curriculum:'대수',subCurriculum:'APEX',chapter:1,title:'하나',url:'https://example.invalid/one'},
  {id:2,curriculum:'대수',subCurriculum:'APEX',chapter:2,title:'둘',url:'https://example.invalid/two'}
];
const indexes=html=>Array.from(html.matchAll(/data-idx="(\d+)"/g),match=>Number(match[1]));
for(const query of ['', '   ']){
  const result=renderer(current,rows,query);result.draw();
  assert.deepEqual(indexes(result.table.innerHTML),[1,2,0]);
  assert.equal(result.searchCalls(),0,'an empty search has no normalization work');
}
const filtered=renderer(current,rows,'하나');filtered.draw();
assert.deepEqual(indexes(filtered.table.innerHTML),[1]);
const duplicates=renderer(current,[rows[0],{...rows[0],title:'같은 ID'}]);duplicates.draw();
assert.deepEqual(indexes(duplicates.table.innerHTML),[0,0],'legacy duplicate IDs retain the first-index lookup');
assert.deepEqual(rows.map(row=>row.id),[3,1,2]);
console.log('video render checks passed: order, index identity, empty/active search and legacy duplicate IDs');

if(process.argv[2]){
  const generated=Array.from({length:3000},(_,index)=>({
    id:index+1,curriculum:'대수',subCurriculum:'APEX',chapter:3000-index,
    title:'합성 영상 '+index,url:'https://example.invalid/video/'+index,mid:'synthetic-'+index,exNum:{상:3}
  }));
  const before=renderer(process.argv[2],generated),after=renderer(current,generated);
  before.draw();after.draw();
  assert.equal(after.table.innerHTML,before.table.innerHTML,'all rendered rows must stay byte-identical');
  const samples={before:[],after:[]};
  for(let index=0;index<35;index++){
    const order=index%2?[['after',after],['before',before]]:[['before',before],['after',after]];
    for(const [label,run] of order){
      const started=performance.now();run.draw();const elapsed=performance.now()-started;
      if(index>=5)samples[label].push(elapsed);
    }
  }
  const stats=values=>{
    const sorted=values.slice().sort((a,b)=>a-b);
    return {medianMs:sorted[Math.floor(sorted.length/2)],p95Ms:sorted[Math.ceil(sorted.length*.95)-1]};
  };
  console.log(JSON.stringify({kind:'synthetic-js-render',rows:3000,warmup:5,samples:30,
    excludes:['network','DOM insertion','layout','paint'],before:stats(samples.before),after:stats(samples.after)}));
}
