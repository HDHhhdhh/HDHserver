import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const args = process.argv.slice(2);
const sourcePath = args.includes('--source') ? args[args.indexOf('--source') + 1]
  : 'static/js/admin/features/today.js';
const source = fs.readFileSync(sourcePath, 'utf8');
const statePath = args.includes('--state-source') ? args[args.indexOf('--state-source') + 1]
  : 'static/js/admin/features/today.state.js';
const stateSource = fs.readFileSync(statePath, 'utf8');
const begin = source.indexOf('function compareTodayStudents(');
const end = source.indexOf('// 선택 날짜 명단 계산', begin);
assert.ok(begin >= 0 && end > begin, 'actual today comparator boundary');
const facts = new Map();
const fact = sid => facts.get(String(sid)) || {};
const context = vm.createContext({
  timeGroupRank: (_, sid) => fact(sid).group ?? 0,
  isSelfStudy: (_, sid) => !!fact(sid).self,
  isAttended: (_, sid) => !!fact(sid).attended,
  isHwChecked: (_, sid) => !!fact(sid).checked,
  homeworkRequestRank: (_, stu) => fact(stu.id).request ?? 1,
  hwCheckRequestedAt: (_, sid) => fact(sid).requestedAt ?? '',
  plannedMinutesFor: (_, sid) => fact(sid).minutes ?? 780,
});
vm.runInContext(source.slice(begin, end), context);
const A = '2026-10-02', B = '2026-10-03';
const rows = [{ id: 'S1', name: '가학생' }, { id: 'S2', name: '나학생' },
  { id: 'S3', name: '다학생' }];
let cases = 0;
function check(input, savedOrder, expected, label) {
  const result = context.sortTodayStudents(input.map(row => ({ ...row })), A,
    { preserveCurrentOrder: true, savedOrder });
  assert.deepEqual(Array.from(result, row => row.id), expected, label);
  cases++;
}
check(rows, ['S2', 'S1'], ['S2', 'S1', 'S3'], 'saved rank precedes Korean names');
check([...rows].reverse(), [], ['S1', 'S2', 'S3'], 'no saved order retains alphabetical order');
check(rows, ['unknown', 'S2', 'S2', 'S1'], ['S2', 'S1', 'S3'], 'unknown IDs and duplicate ranks');
check([...rows].reverse(), ['unknown'], ['S1', 'S2', 'S3'], 'no matching rank retains alphabetical order');
check(rows, ['S3'], ['S3', 'S1', 'S2'], 'new unranked students follow ranked peers alphabetically');
check([{id:'S1',name:'동명'}, {id:'S2',name:'동명'}], [], ['S1','S2'], 'legacy same-name input tie');
check([{id:'S2',name:'동명'}, {id:'S1',name:'동명'}], ['S1','S2'], ['S1','S2'], 'manual same-name tie');

// Literal expectations keep each existing automatic priority ahead of a reversed manual order.
const priorities = [
  ['group', {group:0}, {group:1}],
  ['self study', {self:false}, {self:true}],
  ['attendance', {attended:false}, {attended:true}],
  ['homework request', {attended:true,request:0}, {attended:true,request:1}],
  ['request timestamp', {attended:true,request:0,requestedAt:'2026-10-02T12:00:00'},
    {attended:true,request:0,requestedAt:'2026-10-02T13:00:00'}],
  ['missing request timestamp', {attended:true,request:0,requestedAt:'2026-10-02T12:00:00'},
    {attended:true,request:0}],
  ['homework status', {checked:false}, {checked:true}],
  ['planned arrival', {minutes:780}, {minutes:840}],
];
for (const [label, first, second] of priorities) {
  facts.clear(); facts.set('S1', first); facts.set('S2', second);
  check(rows.slice(0,2).reverse(), ['S2','S1'], ['S1','S2'], label);
  facts.clear(); facts.set('S2', first); facts.set('S1', second);
  check(rows.slice(0,2), ['S1','S2'], ['S2','S1'], label + ' opposite IDs');
}
facts.clear();

const stateBegin = stateSource.indexOf('let _orderMap = null;');
const stateEnd = stateSource.indexOf('export async function clearTodayOrder', stateBegin);
assert.ok(stateBegin >= 0 && stateEnd > stateBegin, 'actual order store boundary');
const initial = {[A]:['S2','S1'],[B]:['S3','S1']};
const writes = [];
const stateContext = vm.createContext({
  CT: {'Content-Type':'application/json'},
  fetch: async (url, init = {}) => {
    assert.equal(url, '/api/today_order');
    const method = init.method || 'GET';
    if (method === 'GET') return {ok:true,status:200,json:async()=>initial};
    assert.equal(method, 'PATCH');
    const body = JSON.parse(init.body); writes.push(body);
    return {ok:true,json:async()=>({order:body.order})};
  },
});
vm.runInContext(stateSource.slice(stateBegin, stateEnd).replace(/\bexport\s+/g,''), stateContext);
await stateContext.loadOrderMap();
assert.deepEqual(Array.from(stateContext.getSavedOrder(A)), ['S2','S1']); cases++;
assert.deepEqual(Array.from(stateContext.getSavedOrder(B)), ['S3','S1']); cases++;
assert.deepEqual(Array.from(stateContext.getSavedOrder('2026-10-04')), []); cases++;
const detached = stateContext.getSavedOrder(A); detached.reverse();
assert.deepEqual(Array.from(stateContext.getSavedOrder(A)), ['S2','S1']); cases++;
const loadedMap = await stateContext.loadOrderMap();
await stateContext.saveOrder(A, ['S1','S2']);
assert.deepEqual(Array.from(loadedMap[A]), ['S2','S1'], 'old fetched object remains detached'); cases++;
assert.deepEqual(Array.from(stateContext.getSavedOrder(A)), ['S1','S2'], 'fresh getter sees save replacement'); cases++;
assert.deepEqual(Array.from(stateContext.getSavedOrder(B)), ['S3','S1'], 'other date preserved'); cases++;
assert.deepEqual(writes, [{date:A,order:['S1','S2']}]); cases++;
const applied = stateContext.applySavedOrder(rows, A);
check(Array.from(applied), stateContext.getSavedOrder(A), ['S1','S2','S3'], 'current store rank is used');
assert.match(source, /savedOrder:\s*getSavedOrder\(dateKey\)/, 'render must read current selected date rank'); cases++;
assert.match(source, /from ['"]\.\/today\.state\.js['"]/, 'shared order store has one module identity'); cases++;
const storeEnd = stateSource.indexOf('export async function saveWeekendSlotsFromLabel', stateBegin);
assert.ok(storeEnd > stateEnd, 'actual order read/save/clear boundary');
for (const operation of ['save', 'clear']) {
  for (const readFails of [false, true]) {
    for (const writeFails of [false, true]) {
      let settleRead;
      let holdRead = false;
      const oldMap = {[A]: ['S2', 'S1'], [B]: ['S3', 'S1']};
      const ctx = vm.createContext({
        CT: {'Content-Type': 'application/json'}, URLSearchParams,
        fetch: (url, init = {}) => {
          const method = init.method || 'GET';
          if (method === 'GET') {
            assert.equal(url, '/api/today_order');
            assert.equal(init.cache, 'no-store');
            if (holdRead) return new Promise((resolve, reject) => {
              settleRead = () => readFails ? reject(new Error('held read failed'))
                : resolve({ok:true,status:200,json: async () => JSON.parse(JSON.stringify(oldMap))});
            });
            return Promise.resolve({ok:true,status:200,json: async () => JSON.parse(JSON.stringify(oldMap))});
          }
          assert.equal(method, operation === 'save' ? 'PATCH' : 'DELETE');
          if (operation === 'save') {
            assert.deepEqual(JSON.parse(init.body), {date: A, order: ['S1', 'S2']});
          } else {
            assert.equal(url, '/api/today_order?date=' + A);
          }
          return Promise.resolve({ok: !writeFails, status: writeFails ? 500 : 200,
            json: async () => operation === 'save' ? {order: ['S1', 'S2']} : {cleared: true}});
        },
      });
      vm.runInContext(stateSource.slice(stateBegin, storeEnd).replace(/\bexport\s+/g, ''), ctx);
      await ctx.loadOrderMap();
      holdRead = true;
      const staleRead = ctx.loadOrderMap({force: true});
      const write = operation === 'save' ? ctx.saveOrder(A, ['S1', 'S2']) : ctx.clearTodayOrder(A);
      if (writeFails) await assert.rejects(write, /failed: 500/);
      else await write;
      settleRead();
      await staleRead;
      const expectedA = writeFails ? (readFails ? [] : ['S2', 'S1'])
        : (operation === 'save' ? ['S1', 'S2'] : []);
      const expectedB = writeFails && readFails ? [] : ['S3', 'S1'];
      assert.deepEqual(Array.from(ctx.getSavedOrder(A)), expectedA,
        `${operation}: an older ${readFails ? 'failed' : 'successful'} read cannot undo a confirmed write`);
      assert.deepEqual(Array.from(ctx.getSavedOrder(B)), expectedB, 'unrelated date keeps its confirmed order');
      cases++;
    }
  }
}
console.log(`PASS today manual order: ${cases} cases; automatic priorities, date isolation, fresh saved rank, delayed read/save/clear`);
