const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const renderPath = path.join(__dirname, '..', 'static', 'js', 'admin', 'features', 'today.render.js');
const source = fs.readFileSync(renderPath, 'utf8');

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} must exist in today.render.js`);

  const bodyStart = source.indexOf('{', start);
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error(`Could not extract ${name}`);
}

const sandbox = { HOMEWORK_LEAVE_SLOT_BOUNDARY_MINUTES: 18 * 60 };
vm.createContext(sandbox);
vm.runInContext([
  extractFunction('currentOpsSlot'),
  extractFunction('homeworkLeaveSlotNumbers'),
  extractFunction('shouldIncludeHomeworkLeaveRow'),
].join('\n'), sandbox);

const rowFor = ({ hw = false, selfStudy = false, slotGroup = '' } = {}) => ({
  dataset: {
    hw: hw ? '1' : '',
    selfStudy: selfStudy ? '1' : '',
    slotGroup,
  },
});

assert.equal(
  sandbox.currentOpsSlot(new Date(2026, 7, 3, 17, 59)),
  1,
  'before 18:00 the homework leave policy must use time slot 1',
);
assert.equal(
  sandbox.currentOpsSlot(new Date(2026, 7, 3, 18, 0)),
  2,
  'at 18:00 the homework leave policy must use time slot 2',
);

assert.equal(
  sandbox.shouldIncludeHomeworkLeaveRow(rowFor({ hw: true, slotGroup: '1' }), 1),
  true,
  'a checked single-slot-1 student must leave during time slot 1',
);
assert.equal(
  sandbox.shouldIncludeHomeworkLeaveRow(rowFor({ hw: true, slotGroup: '1,2' }), 1),
  false,
  'a checked consecutive student must stay during time slot 1',
);
assert.equal(
  sandbox.shouldIncludeHomeworkLeaveRow(rowFor({ hw: true, slotGroup: '1,2' }), 2),
  true,
  'a checked consecutive student must leave during time slot 2',
);
assert.equal(
  sandbox.shouldIncludeHomeworkLeaveRow(rowFor({ selfStudy: true, slotGroup: '2' }), 1),
  true,
  'a self-study student must leave even without homework completion',
);
assert.equal(
  sandbox.shouldIncludeHomeworkLeaveRow(rowFor({ selfStudy: true, slotGroup: '1,2' }), 1),
  false,
  'a self-study consecutive student must stay during time slot 1',
);
assert.equal(
  sandbox.shouldIncludeHomeworkLeaveRow(rowFor({ selfStudy: true, slotGroup: '1,2' }), 2),
  true,
  'a self-study consecutive student must leave during time slot 2',
);
assert.equal(
  sandbox.shouldIncludeHomeworkLeaveRow(rowFor({ slotGroup: '1' }), 1),
  false,
  'an unchecked, non-self-study student must remain out of the target set',
);

console.log('homework leave policy PASS');
