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
  extractFunction('rowSid'),
  extractFunction('normalizeLeaveIdentityPart'),
  extractFunction('studentSchoolForLeaveIdentity'),
  extractFunction('studentLeaveIdentityKey'),
  extractFunction('leaveIdentityForRow'),
  extractFunction('currentOpsSlot'),
  extractFunction('homeworkLeaveSlotNumbers'),
  extractFunction('homeworkLeaveRowsByStudent'),
  extractFunction('homeworkLeaveSlotNumbersForRows'),
  extractFunction('shouldIncludeHomeworkLeaveRows'),
  extractFunction('shouldIncludeHomeworkLeaveRow'),
  extractFunction('homeworkLeaveTargetRows'),
  extractFunction('linkedLeaveRows'),
].join('\n'), sandbox);

const rowFor = ({
  sid = 'student-a',
  date = '2026-08-03',
  identity = '',
  hw = false,
  selfStudy = false,
  slotGroup = '',
} = {}) => ({
  dataset: {
    sid,
    date,
    studentIdentity: identity,
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

const linkedIdentity = sandbox.studentLeaveIdentityKey({
  id: 'linked-slot-1',
  name: '한나윤',
  school: '운정고',
  grade: '고2',
});
assert.equal(
  linkedIdentity,
  sandbox.studentLeaveIdentityKey({
    id: 'linked-slot-2',
    name: '한나윤',
    school: '운정고',
    grade: '고2',
  }),
  'separate course SIDs for the same name, school, and grade must share one leave identity',
);
assert.notEqual(
  linkedIdentity,
  sandbox.studentLeaveIdentityKey({
    id: 'same-name-other-school',
    name: '한나윤',
    school: '다른고',
    grade: '고2',
  }),
  'a same-name student at another school must not be grouped for leave',
);
const linkedSlotOne = rowFor({
  sid: 'linked-slot-1',
  identity: linkedIdentity,
  hw: true,
  slotGroup: '1',
});
const linkedSlotTwo = rowFor({
  sid: 'linked-slot-2',
  identity: linkedIdentity,
  slotGroup: '2',
});
const unrelated = rowFor({
  sid: 'unrelated-slot-2',
  identity: 'person:other|school|grade',
  slotGroup: '2',
});

assert.deepEqual(
  Array.from(sandbox.homeworkLeaveTargetRows([linkedSlotOne, linkedSlotTwo, unrelated], 1), row => row.dataset.sid),
  [],
  'split-SID consecutive students must stay until their later slot',
);
assert.deepEqual(
  Array.from(sandbox.homeworkLeaveTargetRows([linkedSlotOne, linkedSlotTwo, unrelated], 2), row => row.dataset.sid).sort(),
  ['linked-slot-1', 'linked-slot-2'],
  'the final-slot bulk leave must include every visible SID for the same student',
);
assert.deepEqual(
  Array.from(sandbox.linkedLeaveRows(linkedSlotTwo, [linkedSlotOne, linkedSlotTwo, unrelated], 1), row => row.dataset.sid),
  ['linked-slot-2'],
  'an individual leave during the first slot must not end the linked later class',
);
assert.deepEqual(
  Array.from(sandbox.linkedLeaveRows(linkedSlotTwo, [linkedSlotOne, linkedSlotTwo, unrelated], 2), row => row.dataset.sid).sort(),
  ['linked-slot-1', 'linked-slot-2'],
  'an individual leave after the final slot must end every linked class row',
);

console.log('homework leave policy PASS');
