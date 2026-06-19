const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const sourcePath = path.join(root, 'static/js/admin/features/testModal.js');

let source = fs.readFileSync(sourcePath, 'utf8');
source = source.replace(/import[\s\S]*?from '\.\.\/core\/adminDate\.js';\s*/m, '');
source = source.replace(/\bexport\s+/g, '');

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
  status: 'assigned',
  statusLabel: '배정',
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
  'new assigned test counts as same-day distribution',
  JSON.stringify(context.dailyAssignmentNoteItems([graphRound2], {})),
  JSON.stringify([graphRound2])
);

assertEqual(
  'already done does not become same-day completion',
  JSON.stringify(context.dailyAssignmentNoteItems([graphRound1], { [graphRound1.label]: 'done' })),
  JSON.stringify([])
);
