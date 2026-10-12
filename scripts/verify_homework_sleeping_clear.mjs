import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourceOption = process.argv.indexOf('--source');
const sourcePath = sourceOption < 0 ? path.join(root, 'static/js/admin/features/logModal.js') : process.argv[sourceOption + 1];
const source = fs.readFileSync(sourcePath, 'utf8');
const functionSource = name => {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing actual function ${name}`);
  const next = source.indexOf('\nfunction ', start + 1);
  return source.slice(start, next < 0 ? source.length : next);
};
const names = ['isQuestionPlaceholder', 'looksCorruptedPlaceholderText', 'cleanHwText',
  'homeworkBookKey', 'normalizeSleepingHomeworkBooks', 'sameSleepingHomeworkBooks',
  'entryHasSleepingHomeworkBooks', 'resolveSleepingHomeworkBooks', 'normHwRows',
  'activeHwRows', 'normalizeHwRowsForCompare', 'sameHwRows', 'hwRowToSummary',
  'buildHwSummary', 'buildLogSavePatch', 'applyLogSaveResult'];
const clone = value => JSON.parse(JSON.stringify(value));
const key = 'sleepingHomeworkBooks';
const date = '2026-10-02', sid = 'qa-sleep', otherSid = 'qa-other';
const ctx = vm.createContext({
  HOMEWORK_SLEEPING_BOOKS_KEY: key,
  logModalSnapshot: {notes:'', homeworkTable:[], sleepingHomeworkBooks:['교재 B']},
  logModalServerSnapshot: {notes:'', homeworkTable:[], sleepingHomeworkBooks:['교재 B']},
  logModalCarriedTestAssignment: null,
  state: {logs:{}},
});
vm.runInContext(names.map(functionSource).join('\n'), ctx, {filename:sourcePath});
let cases = 0;
const check = (actual, expected, message) => { assert.deepEqual(clone(actual), expected, message); cases++; };
const makePatch = sleepingHomeworkBooks => clone(ctx.buildLogSavePatch({
  notesNow:'', hwRows:[], sleepingHomeworkBooks, prevLog:{}, doneFlag:false, summary:'',
}));
const wake = makePatch([]);
check(wake.entry, {[key]:[]}, 'last wake retains an explicit empty property');
check(wake.clearKeys, [key], 'last wake explicitly clears the existing meaningful value');
check(wake.base, {[key]:['교재 B']}, 'clear retains the conflict-check base');
check(wake.contentChanged, true, 'wake is an actual content edit');
const unchanged = makePatch(['교재 B']);
check(unchanged, {entry:{}, clearKeys:[], base:{}, contentChanged:false}, 'unchanged books do not write');
ctx.logModalSnapshot.sleepingHomeworkBooks = ['교재 A', '교재 B'];
ctx.logModalServerSnapshot.sleepingHomeworkBooks = ['교재 A', '교재 B'];
const partial = makePatch(['교재 B']);
check(partial.entry, {[key]:['교재 B']}, 'partial wake preserves the remaining book');
check(partial.clearKeys, [], 'partial wake does not clear all books');
ctx.logModalSnapshot.sleepingHomeworkBooks = [];
ctx.logModalServerSnapshot.sleepingHomeworkBooks = [];
check(makePatch([]), {entry:{}, clearKeys:[], base:{}, contentChanged:false}, 'already awake is a no-op');
check(makePatch([' 교재 A ', '교재A', '교재 B']).entry, {[key]:['교재 A','교재 B']}, 'normalization preserves the book names');

const current = {notes:'메모 보존', done:true, [key]:['교재 B'], unknown:{nested:7}, homeworkTable:[{book:'교재 B',next:'2단원'}]};
// The server oracle imports only the pure merger. No Flask app, paths, stores or HTTP.
const incoming = {...wake.entry, __clear:wake.clearKeys};
const python = spawnSync(process.env.PYTHON || 'python', ['-c',
  'import json,sys; from core.log_rules import merge_log_entry_safe; x=json.load(sys.stdin); print(json.dumps([merge_log_entry_safe(x["current"], p) for p in x["patches"]],ensure_ascii=False))'],
  {cwd:root, input:JSON.stringify({current, patches:[incoming, {[key]:[]}, {...partial.entry,__clear:partial.clearKeys}]}), encoding:'utf8'});
assert.equal(python.status, 0, python.stderr);
const [serverWake, ordinaryEmpty, serverPartial] = JSON.parse(python.stdout);
check(serverWake, {...current,[key]:[]}, 'the actual server merger applies the explicit clear narrowly');
check(ordinaryEmpty, current, 'ordinary empty patches retain the existing merge-safe behavior');
check(serverPartial, {...current,[key]:['교재 B']}, 'partial wake retains unrelated data');
ctx.state.logs = {'2026-10-01':{[sid]:{[key]:['교재 B']}}, [date]:{[sid]:clone(current), [otherSid]:{[key]:['다른 교재'],unknown:'keep'}}};
ctx.applyLogSaveResult({date,sid,entry:wake.entry,clearKeys:wake.clearKeys,returned:null,doneFlag:false,prevDone:true});
check(ctx.state.logs[date][sid], {...current,[key]:[]}, 'older ok-only response keeps the explicit empty marker and unknown fields');
check(ctx.state.logs[date][otherSid], {[key]:['다른 교재'],unknown:'keep'}, 'the neighboring SID is untouched');
check(ctx.resolveSleepingHomeworkBooks({logEntry:ctx.state.logs[date][sid],dates:['2026-10-01',date],today:date,sid}), [], 'last wake blocks carryover from yesterday');
check(ctx.resolveSleepingHomeworkBooks({logEntry:{},dates:['2026-10-01',date],today:date,sid}), ['교재 B'], 'missing property still permits the documented carryover');
ctx.applyLogSaveResult({date,sid,entry:wake.entry,clearKeys:wake.clearKeys,returned:serverWake,doneFlag:false,prevDone:true});
check(ctx.state.logs[date][sid], serverWake, 'canonical response is authoritative');
check(ctx.resolveSleepingHomeworkBooks({logEntry:serverWake,dates:['2026-10-01',date],today:date,sid}), [], 'reload of the actual merge result remains awake');
ctx.applyLogSaveResult({date,sid,entry:{notes:'새 메모'},clearKeys:[],returned:null,doneFlag:false,prevDone:true});
check(ctx.state.logs[date][sid], {...serverWake,notes:'새 메모'}, 'a later notes-only save does not revive sleeping books');
ctx.applyLogSaveResult({date,sid,entry:{},clearKeys:['notes'],returned:null,doneFlag:false,prevDone:true});
const withoutNotes = {...serverWake}; delete withoutNotes.notes;
check(ctx.state.logs[date][sid], withoutNotes, 'the empty sleeping marker does not interfere with another explicit clear');
check(ctx.state.logs['2026-10-01'][sid], {[key]:['교재 B']}, 'historical data is untouched');
console.log(`homework sleeping clear: ${cases} cases PASS (actual browser helpers + pure server merger; no runtime I/O)`);
