const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const uiEnhancePath = path.join(__dirname, '..', 'static', 'js', 'admin', 'features', 'uiEnhance.js');
const source = fs.readFileSync(uiEnhancePath, 'utf8');

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} must exist in uiEnhance.js`);

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

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext([
  extractFunction('slotGroupsFromRow'),
  extractFunction('homeworkSlotFromRow'),
].join('\n'), sandbox);

const rowFor = slotGroup => ({
  dataset: { slotGroup },
  querySelector() { return null; },
  cells: [],
});

assert.equal(sandbox.homeworkSlotFromRow(rowFor('1')), 1, 'a time-slot-1 student stays in homework slot 1');
assert.equal(sandbox.homeworkSlotFromRow(rowFor('2')), 2, 'a time-slot-2 student stays in homework slot 2');
assert.equal(
  sandbox.homeworkSlotFromRow(rowFor('1,2')),
  2,
  'a consecutive-class student is counted only in time slot 2 for remaining-homework metrics',
);
assert.match(
  source,
  /\.filter\(row => homeworkSlotFromRow\(row\) === slot\)/,
  'remaining-homework rows must use the single-slot homework policy',
);

console.log('admin homework slot counts PASS');
