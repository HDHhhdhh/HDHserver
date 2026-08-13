const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const calendarPath = path.join(__dirname, '..', 'static', 'js', 'admin', 'features', 'calendar.js');
const source = fs.readFileSync(calendarPath, 'utf8');

function extractFunction(name) {
  const start = source.indexOf(`  function ${name}(`);
  assert.notEqual(start, -1, `${name} must exist in calendar.js`);

  const bodyStart = source.indexOf('{', start);
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start + 2, index + 1);
    }
  }
  throw new Error(`Could not extract ${name}`);
}

const sandbox = {
  MAKEUP_SLOTS: [1, 2],
  WEEKEND: {},
  yoil: () => '금',
};
vm.createContext(sandbox);
vm.runInContext([
  extractFunction('parseSlotNumbers'),
  extractFunction('getRegularSlots'),
  extractFunction('getCountSlots'),
].join('\n'), sandbox);

const date = '2026-07-24';
const sid = 'consecutive-student';
const student = { id: sid, day1: '금1' };

assert.deepEqual(
  Array.from(sandbox.getCountSlots(student, date)),
  [1],
  'a regular one-slot student must count in the configured regular slot',
);

sandbox.WEEKEND[date] = { [sid]: [1, 2] };
assert.deepEqual(
  Array.from(sandbox.getCountSlots(student, date)),
  [1, 2],
  'a date-specific consecutive-class setting must count the student in both time slots',
);

const slotSets = { 1: new Set(), 2: new Set() };
sandbox.getCountSlots(student, date).forEach(slot => slotSets[slot].add(sid));
assert.equal(slotSets[1].size, 1, 'the consecutive student contributes one person to time slot 1');
assert.equal(slotSets[2].size, 1, 'the consecutive student contributes one person to time slot 2');

console.log('admin calendar consecutive counts PASS');
