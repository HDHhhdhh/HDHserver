import assert from 'node:assert/strict';
import fs from 'node:fs';

globalThis.window = {
  addEventListener() {},
};

const { buildRecoveredAbsencePayload, recoverAbsencesForDate } = await import(
  `../static/js/admin/features/absentRecovery.js?verify=${Date.now()}`
);

const targetDate = '2026-08-14';
const source = {
  by_date: {
    [targetDate]: ['sid-a', 'sid-b', 17],
    '2026-08-13': ['sid-a', 'sid-z'],
  },
  by_student: {
    'sid-a': targetDate,
    'sid-b': '2026-08-13',
    17: targetDate,
    'sid-z': '2026-08-13',
  },
  by_slot: {
    [targetDate]: {
      'sid-a': [1, 2],
      'sid-b': [2],
      17: [1],
    },
    '2026-08-13': {
      'sid-a': [2],
      'sid-z': [1],
    },
  },
};
const before = structuredClone(source);

const result = buildRecoveredAbsencePayload(source, targetDate, ['sid-a', 17]);

assert.deepEqual(source, before, 'recovery payload builder mutated its source maps');
assert.deepEqual(result.by_date[targetDate], ['sid-b']);
assert.deepEqual(result.by_date['2026-08-13'], ['sid-a', 'sid-z']);
assert.equal(Object.hasOwn(result.by_student, 'sid-a'), false);
assert.equal(Object.hasOwn(result.by_student, '17'), false);
assert.equal(result.by_student['sid-b'], '2026-08-13', 'a different-date student mapping was removed');
assert.deepEqual(result.by_slot[targetDate], { 'sid-b': [2] });
assert.deepEqual(result.by_slot['2026-08-13'], {
  'sid-a': [2],
  'sid-z': [1],
});

result.by_date['2026-08-13'].push('sid-new');
result.by_slot['2026-08-13']['sid-z'].push(2);
assert.deepEqual(source, before, 'returned maps still alias nested source arrays');

const fullyRemoved = buildRecoveredAbsencePayload({
  by_date: { [targetDate]: ['sid-a'] },
  by_student: { 'sid-a': targetDate },
  by_slot: { [targetDate]: { 'sid-a': [1] } },
}, targetDate, ['sid-a']);
assert.deepEqual(fullyRemoved, {
  by_date: { [targetDate]: [] },
  by_student: {},
  by_slot: {},
});

assert.throws(
  () => buildRecoveredAbsencePayload(source, 'not-a-date', ['sid-a']),
  /날짜/,
  'invalid dates must fail before a whole-map write can be prepared',
);
assert.throws(
  () => buildRecoveredAbsencePayload(source, targetDate, []),
  /학생/,
  'empty recovery selections must fail before a whole-map write can be prepared',
);

const orchestrationCalls = [];
const normalizedSaved = {
  by_date: { [targetDate]: ['sid-b'] },
  by_student: { 'sid-b': '2026-08-13' },
  by_slot: { [targetDate]: { 'sid-b': [2] } },
};
const originalWarn = console.warn;
console.warn = () => {};
let recoveryResult;
try {
  recoveryResult = await recoverAbsencesForDate(targetDate, ['sid-a'], {
    recoverRemote: async (date, sids) => {
      orchestrationCalls.push(['recover', date, sids]);
      return structuredClone(normalizedSaved);
    },
    clearOrder: async (date) => {
      orchestrationCalls.push(['clear', date]);
      throw new Error('order store unavailable');
    },
  });
} finally {
  console.warn = originalWarn;
}
assert.equal(orchestrationCalls[0][0], 'recover');
assert.equal(orchestrationCalls[0][1], targetDate);
assert.deepEqual(orchestrationCalls[0][2], ['sid-a']);
assert.equal(orchestrationCalls[1][0], 'clear');
assert.equal(orchestrationCalls[1][1], targetDate);
assert.deepEqual(recoveryResult.saved, normalizedSaved);
assert.equal(recoveryResult.orderReset, false, 'an order reset failure must not turn a completed absence save into failure');

let clearAfterFailedSave = false;
await assert.rejects(
  recoverAbsencesForDate(targetDate, ['sid-a'], {
    recoverRemote: async () => { throw new Error('save rejected'); },
    clearOrder: async () => { clearAfterFailedSave = true; },
  }),
  /save rejected/,
);
assert.equal(clearAfterFailedSave, false, 'today order must not clear when the absence save fails');

const originalFetch = globalThis.fetch;
const reconcileCalls = [];
globalThis.fetch = async (url, init = {}) => {
  reconcileCalls.push([String(url), String(init.method || 'GET')]);
  if (String(url) === '/api/absent/recover') throw new Error('response lost after commit');
  if (String(url) === '/api/absent') {
    return {
      ok: true,
      status: 200,
      json: async () => structuredClone(normalizedSaved),
      text: async () => '',
    };
  }
  throw new Error(`unexpected request: ${url}`);
};
try {
  const reconciled = await recoverAbsencesForDate(targetDate, ['sid-a'], {
    clearOrder: async () => false,
  });
  assert.deepEqual(reconciled.saved, normalizedSaved, 'lost save responses must reconcile from canonical absence maps');
  assert.deepEqual(reconcileCalls, [
    ['/api/absent/recover', 'POST'],
    ['/api/absent', 'GET'],
  ]);
} finally {
  globalThis.fetch = originalFetch;
}

const recoverySource = fs.readFileSync('static/js/admin/features/absentRecovery.js', 'utf8');
const registerSource = fs.readFileSync('static/js/admin/features/absentRegister.js', 'utf8');
const extraSource = fs.readFileSync('static/js/admin/features/extraModal.js', 'utf8');
assert.match(recoverySource, /orderReset \? '결석 복구됨'/, 'partial order-reset failure must not show full success');
assert.match(recoverySource, /fetchJsonChecked\('\/api\/absent'/, 'ambiguous saves must reconcile against the canonical store');
assert.match(registerSource, /modal\.dataset\.date = dateKey/, 'absence registration must freeze its opening date');
assert.match(registerSource, /String\(modal\.dataset\.date \|\| ''\)\.trim\(\)/, 'absence registration save must reuse its opening date');
assert.match(extraSource, /exModal\.dataset\.date = today/, 'extra-attendance registration must freeze its opening date');
assert.match(extraSource, /String\(exModal\.dataset\.date \|\| ''\)\.trim\(\)/, 'extra-attendance save must reuse its opening date');

console.log('absence recovery payload checks passed');
