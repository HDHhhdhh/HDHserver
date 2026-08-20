#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const sourcePath = process.env.STUDENT_JS_SOURCE
  ? path.resolve(root, process.env.STUDENT_JS_SOURCE)
  : path.join(root, 'static', 'js', 'student.js');
const source = fs.readFileSync(sourcePath, 'utf8');

function assertContract(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function extractBlockFromMarker(marker, label) {
  const start = source.indexOf(marker);
  assertContract(start !== -1, `missing ${label}`);

  const openBrace = source.indexOf('{', start);
  assertContract(openBrace !== -1, `missing opening brace for ${label}`);

  let depth = 0;
  for (let index = openBrace; index < source.length; index += 1) {
    const char = source[index];
    if (char === '{') depth += 1;
    if (char === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error(`missing closing brace for ${label}`);
}

function extractFunction(name) {
  return extractBlockFromMarker(`function ${name}`, `function ${name}`);
}

const assignedRound = extractFunction('assignedRound');
const roundLabel = extractFunction('roundLabel');
const availableRoundsForType = extractFunction('availableRoundsForType');
const renderRoundOptions = extractFunction('renderRoundOptions');
const renderTestOptions = extractFunction('renderTestOptions');
const testChangeStart = source.indexOf("selTestId.addEventListener('change'");
const testChangeEnd = source.indexOf("selRound.addEventListener('change'", testChangeStart);
assertContract(testChangeStart !== -1 && testChangeEnd !== -1, 'missing test selection change handler');
const testChangeBlock = source.slice(testChangeStart, testChangeEnd);
const roundChangeBlock = extractBlockFromMarker("selRound.addEventListener('change'", 'round selection change handler');

assertContract(
  source.includes("/^t_training_pack_[a-z0-9_]+_r[12]$/i"),
  'training-pack OCR allowlist must only include round 1 and 2',
);
assertContract(
  availableRoundsForType.includes('listTestsForType(typeVal, currentCur())') &&
    availableRoundsForType.includes('new Set()') &&
    availableRoundsForType.includes("assignedRound(test.round || '1')"),
  'availableRoundsForType must derive available rounds from the selected test list',
);
assertContract(
  renderTestOptions.includes('const selectedTest = findTestById(type, selTestId.value, myCur);') &&
    renderTestOptions.includes('renderRoundOptions(selectedTest?.round || selRound.value);'),
  'renderTestOptions must refresh the round dropdown from the selected test',
);
assertContract(
  testChangeBlock.includes('renderRoundOptions(t?.round || selRound.value);') &&
    !testChangeBlock.includes('if (t?.round) selRound.value = String(t.round);'),
  'test selection changes must refresh round options rather than only assigning the round value',
);
assertContract(
  roundChangeBlock.includes('findSiblingTestByRound') &&
    roundChangeBlock.includes('if (sibling) selTestId.value = sibling.id;'),
  'round selection changes must switch to the sibling test id for that round',
);

const context = {
  selType: { value: 'TRAINING_PACK' },
  selRound: { value: '3', innerHTML: '' },
  currentCur: () => '미적분1',
  listTestsForType: typeVal => {
    if (typeVal === 'TRAINING_PACK') {
      return [
        { id: 't_training_pack_mijeok1_non_frequent_r1', round: '1' },
        { id: 't_training_pack_mijeok1_non_frequent_r2', round: '2' },
      ];
    }
    return [
      { id: 't_unit_mijeok1_01_lv3_r1', round: '1' },
      { id: 't_unit_mijeok1_01_lv3_r2', round: '2' },
      { id: 't_unit_mijeok1_01_lv3_r3', round: '3' },
    ];
  },
  Set,
  Array,
  Number,
  String,
};

vm.createContext(context);
vm.runInContext(
  [assignedRound, roundLabel, availableRoundsForType, renderRoundOptions].join('\n'),
  context,
);

const fallbackRound = context.renderRoundOptions('3');
assertContract(fallbackRound === '1', 'training-pack unavailable round 3 should fall back to round 1');
assertContract(!context.selRound.innerHTML.includes('value="3"'), 'training-pack round dropdown must not render round 3');
assertContract(context.selRound.innerHTML.includes('value="1"'), 'training-pack round dropdown must include round 1');
assertContract(context.selRound.innerHTML.includes('value="2"'), 'training-pack round dropdown must include round 2');

const selectedRound = context.renderRoundOptions('2');
assertContract(selectedRound === '2', 'training-pack round 2 should remain selectable');

context.selType.value = 'UNIT';
const unitRound = context.renderRoundOptions('3');
assertContract(unitRound === '3', 'unit tests may still expose round 3 when configured');
assertContract(context.selRound.innerHTML.includes('value="3"'), 'unit round dropdown should keep configured round 3');

console.log('student training-pack round filter contract ok');
