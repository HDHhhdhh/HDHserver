import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { projectDailyMetrics, projectPendingWork, trailingDates } from '../static/js/admin/features/operationsProjection.js';
import { recordSaveEvent } from '../static/js/admin/features/saveOperations.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
assert.deepEqual(trailingDates('2026-03-02', 3), ['2026-02-28','2026-03-01','2026-03-02']);
assert.deepEqual(trailingDates('2024-03-01', 2), ['2024-02-29','2024-03-01']);
assert.throws(() => trailingDates('2026-02-30'));
const input = {
  date:'2026-10-24', attendance:{a:true,b:'1',c:false,d:'false'},
  logs:{'2026-10-24':{a:{hwAssigned:true,hwChecked:true},b:{hwCheckRequested:true},c:{notes:'not a homework record'},d:{hwChecked:'false'}},'2026-10-23':{e:{hwChecked:true}}},
  progress:{'2026-10-24':{a:{m1:'done',m2:'assigned',m3:'skip',__manualProgressMids:['m1'],tests:{test:'done'}},b:{m4:{state:'interrupted'},m5:{status:'done'},notes:'unrelated'}}},
};
const original = JSON.stringify(input);
assert.deepEqual(projectDailyMetrics(input), {date:'2026-10-24',attended:2,homeworkTotal:2,homeworkChecked:1,homeworkRate:50,videoTotal:4,videosDone:2,videoRate:50});
assert.equal(JSON.stringify(input), original);
assert.equal(projectDailyMetrics({date:'2026-10-25',attendance:{},logs:{},progress:{}}).homeworkRate, null);

const roster = [{id:'a',name:'가람',whiteReviewPending:true},{id:'b',name:'나래'},{id:'c',name:'다온'},{id:'d',name:'라온'}];
const rows = [
  {sid:'a',date:'2026-10-24',attended:true,hwRequested:true},
  {sid:'a',date:'2026-10-23',done:true},
  {sid:'b',date:'2026-10-24',attended:true,selfStudy:true},
  {sid:'c',date:'2026-10-24',attended:false},
  {sid:'d',date:'2026-10-24',attended:true,hwChecked:true},
];
const queue = projectPendingWork({rows,students:roster,updates:{'2026-10-24':{a:{videos:['one','one','two','three','missing']},b:{videos:['unknown']}}},progress:{'2026-10-24':{a:{one:'done',two:'skip',three:'interrupted'}}}});
assert.deepEqual(queue.map(row => row.id), ['homework:2026-10-24:a','review:a','video:2026-10-24:a']);
assert.match(queue[2].detail, /1개/);
assert.equal(queue[1].date, '2026-10-24');

const event = (type,stage='preflight',extra={}) => ({id:'op-123456789',sid:'a',date:'2026-10-24',at:1,type,stage,...extra});
let history = recordSaveEvent([], event('start', 'preflight', {notes:'private',homeworkTable:['private']}));
history = recordSaveEvent(history,event('running','video'));
history = recordSaveEvent(history,event('complete','video'));
history = recordSaveEvent(history,event('failed','record'));
assert.equal(history[0].status,'failed');
assert.deepEqual(history[0].stages,{video:'complete',record:'failed'});
assert.ok(!JSON.stringify(history).includes('private'));
assert.deepEqual(recordSaveEvent(history,event('success','test')),history);
assert.deepEqual(recordSaveEvent([],event('complete','record')),[]);
let many=[];
for(let index=0;index<40;index++) many=recordSaveEvent(many,event('start','preflight',{id:'operation-'+index}));
assert.equal(many.length,30);

const manifest=JSON.parse(fs.readFileSync(path.join(root,'static/vendor/admin-toolkit-manifest.json'),'utf8'));
for(const item of manifest) assert.equal(createHash('sha256').update(fs.readFileSync(path.join(root,'static/vendor',item.file))).digest('hex'),item.sha256,item.file);
assert.equal(manifest.length,9);
console.log('PASS operations toolkit: literal metrics, missing data, date bounds, queue scope, partial-save journal, privacy and pinned asset integrity.');
await import('./verify_admin_toolkit_async.mjs');
