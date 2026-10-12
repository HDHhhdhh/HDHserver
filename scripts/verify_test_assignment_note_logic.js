const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const sourcePath = process.env.TEST_MODAL_SOURCE
  ? path.resolve(root, process.env.TEST_MODAL_SOURCE)
  : path.join(root, 'static/js/admin/features/testModal.js');

let source = fs.readFileSync(sourcePath, 'utf8');
const importPattern = /^import\s+[\s\S]*?;\r?\n/gm;
const imports = source.match(importPattern) || [];
const preludes = [];
if (imports.some(statement => /from '\.\/testAssignmentRules\.js(?:\?[^']+)?'/.test(statement))) {
  preludes.push(fs.readFileSync(path.join(root, 'static/js/admin/features/testAssignmentRules.js'), 'utf8')
    .replace(/^export\s+/gm, ''));
}
if (imports.some(statement => /from '\.\.\/\.\.\/shared\/testCatalogDisplay\.js'/.test(statement))) {
  preludes.push(fs.readFileSync(path.join(root, 'static/js/shared/testCatalogDisplay.js'), 'utf8')
    .replace(/^export\s+/gm, ''));
}
source = source.replace(importPattern, '').replace(/\bexport\s+/g, '');
source = `${preludes.join('\n')}\n${source}`;
source += `
function __setVerifierState(next) {
  if (Object.prototype.hasOwnProperty.call(next, 'activeCatalog')) activeCatalog = next.activeCatalog;
  if (Object.prototype.hasOwnProperty.call(next, 'catalogByKey')) catalogByKey = next.catalogByKey;
  if (Object.prototype.hasOwnProperty.call(next, 'activeCategory')) activeCategory = next.activeCategory;
  if (Object.prototype.hasOwnProperty.call(next, 'activeSubject')) activeSubject = next.activeSubject;
  if (Object.prototype.hasOwnProperty.call(next, 'activeDifficulty')) activeDifficulty = next.activeDifficulty;
  if (Object.prototype.hasOwnProperty.call(next, 'activeStudent')) activeStudent = next.activeStudent;
  if (Object.prototype.hasOwnProperty.call(next, 'editingDate')) editingDate = next.editingDate;
  if (Object.prototype.hasOwnProperty.call(next, 'editingSid')) editingSid = next.editingSid;
  if (Object.prototype.hasOwnProperty.call(next, 'selectedStatuses')) selectedStatuses = next.selectedStatuses;
  if (Object.prototype.hasOwnProperty.call(next, 'submittedIds')) submittedIds = next.submittedIds;
  if (Object.prototype.hasOwnProperty.call(next, 'submittedNames')) submittedNames = next.submittedNames;
}
function __getVerifierState() {
  return { activeDifficulty, activeRound };
}
`;

const context = {
  window: {},
  document: {
    body: { addEventListener() {}, insertAdjacentHTML() {} },
    addEventListener() {},
    querySelector: () => null,
  },
  localStorage: { getItem: () => null },
  state: { schoolCal: {} },
  $: () => null,
  CT: { 'Content-Type': 'application/json' },
  toast: () => {},
  getAdminDate: () => '2026-06-19',
  console,
  setTimeout,
  URLSearchParams,
  CustomEvent: function CustomEvent() {},
  CSS: { escape: value => String(value) },
};
vm.createContext(context);
vm.runInContext(source, context);

function assertEqual(name, actual, expected) {
  if (actual !== expected) {
    console.error(`FAIL ${name}`);
    console.error(`  expected: ${JSON.stringify(expected)}`);
    console.error(`  actual:   ${JSON.stringify(actual)}`);
    process.exit(1);
  }
  console.log(`PASS ${name}`);
}

const graphRound1 = {
  categoryKey: 'ILSAN_PAST',
  categoryLabel: '일산 기출',
  curriculum: '대수',
  difficulty: '그래프 포함',
  term: '기말고사',
  round: '1',
  name: '삼각함수 그래프 포함 1회차 24 가좌',
  label: '일산 기출 / 대수 / 그래프 포함 / 기말고사 / 1회차 / 삼각함수 그래프 포함 1회차 24 가좌',
  status: 'done',
  statusLabel: '완료',
};

const graphRound2 = {
  ...graphRound1,
  round: '2',
  name: '삼각함수 그래프 포함 2회차 22 대화',
  label: '일산 기출 / 대수 / 그래프 포함 / 기말고사 / 2회차 / 삼각함수 그래프 포함 2회차 22 대화',
  status: 'interrupted',
  statusLabel: '배부',
};

assertEqual(
  'short counseling lines for ilsan graph tests',
  context.buildAssignmentNote([graphRound1, graphRound2]),
  [
    '일산기출(그래프부터) 1회차 24 가좌 (완료)',
    '일산기출(그래프부터) 2회차 22 대화 (배부)',
  ].join('\n')
);

assertEqual(
  'assigned to done counts as same-day completion',
  JSON.stringify(context.dailyAssignmentNoteItems([graphRound1], { [graphRound1.label]: 'assigned' })),
  JSON.stringify([graphRound1])
);

assertEqual(
  'plain assigned test is excluded from counseling note',
  JSON.stringify(context.dailyAssignmentNoteItems([{ ...graphRound2, status: 'assigned', statusLabel: '배정' }], {})),
  JSON.stringify([])
);

assertEqual(
  'distributed test remains in counseling note',
  JSON.stringify(context.dailyAssignmentNoteItems([graphRound2], {})),
  JSON.stringify([graphRound2])
);

assertEqual(
  'assigned to distributed counts as same-day distribution',
  JSON.stringify(context.dailyAssignmentNoteItems([graphRound2], { [graphRound2.label]: 'assigned' })),
  JSON.stringify([graphRound2])
);

assertEqual(
  'already done does not become same-day completion',
  JSON.stringify(context.dailyAssignmentNoteItems([graphRound1], { [graphRound1.label]: 'done' })),
  JSON.stringify([])
);

const unitRound1 = {
  categoryKey: 'UNIT',
  categoryLabel: '단원평가',
  curriculum: '공수1',
  difficulty: 'Lv.3',
  round: '1',
  name: '집합 1',
};
unitRound1._key = context.testKey(unitRound1);

const unitRound2 = {
  ...unitRound1,
  round: '2',
  name: '집합 2',
};
unitRound2._key = context.testKey(unitRound2);

context.__setVerifierState({
  activeCatalog: [unitRound1, unitRound2],
  catalogByKey: new Map([unitRound1, unitRound2].map(test => [test._key, test])),
  activeCategory: 'UNIT',
  activeSubject: '공수1',
  activeDifficulty: 'Lv.3',
  activeStudent: { level: '중' },
  selectedStatuses: new Map([
    [unitRound1._key, 'assigned'],
  ]),
  submittedIds: new Set(),
  submittedNames: new Set(),
});

assertEqual(
  'assigned unit round remains the default visible round',
  context.defaultRoundFor('UNIT', '공수1', 'Lv.3'),
  '1'
);

context.__setVerifierState({
  selectedStatuses: new Map([
    [unitRound1._key, 'interrupted'],
  ]),
});

assertEqual(
  'distributed unit round remains the default visible round',
  context.defaultRoundFor('UNIT', '공수1', 'Lv.3'),
  '1'
);

context.__setVerifierState({
  selectedStatuses: new Map([
    [unitRound1._key, 'skip'],
  ]),
});

assertEqual(
  'all excluded unit round advances to next round',
  context.defaultRoundFor('UNIT', '공수1', 'Lv.3'),
  '2'
);

const levelMatchedRound1 = {
  ...unitRound1,
  difficulty: 'Lv.4',
  round: '1',
  name: '지수 Lv.4',
};
levelMatchedRound1._key = context.testKey(levelMatchedRound1);
const levelMatchedRound2 = {
  ...levelMatchedRound1,
  round: '2',
  name: '로그 Lv.4',
};
levelMatchedRound2._key = context.testKey(levelMatchedRound2);
const levelMismatchedTest = {
  ...unitRound1,
  difficulty: 'Lv.3',
  round: '1',
  name: '다항식의 연산1 Lv.3',
};
levelMismatchedTest._key = context.testKey(levelMismatchedTest);

context.state.testsConfig = {
  autoAssignRules: {
    UNIT: {
      공수1: {
        'Lv.3': ['하'],
        'Lv.4': ['중'],
      },
    },
  },
};
context.state.progress = { '2026-06-19': { 'student-1': { tests: {} } } };
context.state.logs = {};
context.__setVerifierState({
  activeCatalog: [levelMismatchedTest, levelMatchedRound1, levelMatchedRound2],
  catalogByKey: new Map([levelMismatchedTest, levelMatchedRound1, levelMatchedRound2].map(test => [test._key, test])),
  activeCategory: 'UNIT',
  activeSubject: '공수1',
  activeDifficulty: 'Lv.3',
  activeStudent: { level: '중' },
  editingDate: '2026-06-19',
  editingSid: 'student-1',
  selectedStatuses: new Map(),
  submittedIds: new Set(),
  submittedNames: new Set(),
});

context.applyRuleDefaults('UNIT');
assertEqual(
  'untouched popup uses the student-level difficulty first',
  context.__getVerifierState().activeDifficulty,
  'Lv.4'
);
assertEqual(
  'untouched popup starts at round one',
  context.__getVerifierState().activeRound,
  '1'
);

context.syncSelectedFromProgress();
assertEqual(
  'level-mismatched test is white until explicitly selected',
  context.statusForKey(levelMismatchedTest._key),
  ''
);

context.state.progress = {
  '2026-06-19': {
    'student-1': {
      tests: { [levelMatchedRound2._key]: 'assigned' },
    },
  },
};
context.__setVerifierState({ selectedStatuses: new Map() });
context.syncSelectedFromProgress();
context.applyRuleDefaults('UNIT');
assertEqual(
  'existing subject level-round remains the initial popup selection',
  context.__getVerifierState().activeRound,
  '2'
);

async function capturePatchLogAssignment(currentItems, latestEntry) {
  const requests = [];
  context.fetch = async (url, init = {}) => {
    requests.push({ url, init });
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ entry: {} }),
    };
  };
  context.__setVerifierState({ editingDate: '2026-06-19', editingSid: 'student-1' });
  await context.patchLogAssignment(currentItems, true, [], latestEntry);
  if (requests.length !== 1) {
    console.error(`FAIL expected one log patch request, got ${requests.length}`);
    process.exit(1);
  }
  return JSON.parse(requests[0].init.body);
}

(async () => {
  const previousDistributed = {
    ...graphRound2,
    status: 'interrupted',
    statusLabel: '배부',
  };
  const latestEntry = {
    notes: `[테스트 배정]\n${context.buildAssignmentNote([previousDistributed])}`,
    testAssignmentNote: context.buildAssignmentNote([previousDistributed]),
    testAssignmentDailyTests: [previousDistributed],
  };

  const completedBody = await capturePatchLogAssignment([
    { ...graphRound2, status: 'done', statusLabel: '완료' },
  ], latestEntry);
  assertEqual(
    'carried distributed note updates to completion when current status is done',
    completedBody.entry.testAssignmentDailyTests[0].status,
    'done'
  );
  assertEqual(
    'carried distributed note no longer renders as distribution after completion',
    completedBody.entry.testAssignmentNote.includes('(배부)'),
    false
  );

  const assignedBody = await capturePatchLogAssignment([
    { ...graphRound2, status: 'assigned', statusLabel: '배정' },
  ], latestEntry);
  assertEqual(
    'carried distributed note clears when current status is assigned',
    Array.isArray(assignedBody.entry.testAssignmentDailyTests),
    false
  );
  assertEqual(
    'assigned current status clears stale daily note fields',
    assignedBody.__clear.includes('testAssignmentDailyTests') && assignedBody.__clear.includes('testAssignmentNote'),
    true
  );

  const removedBody = await capturePatchLogAssignment([], latestEntry);
  assertEqual(
    'carried distributed note clears when assignment is removed',
    removedBody.__clear.includes('assignedTests') && removedBody.__clear.includes('testAssignmentDailyTests'),
    true
  );
})().catch(error => {
  console.error(error);
  process.exit(1);
});
