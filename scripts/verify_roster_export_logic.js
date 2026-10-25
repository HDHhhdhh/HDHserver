const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { performance } = require('perf_hooks');

const root = path.resolve(__dirname, '..');
const sourcePath = path.join(root, 'static/js/admin/features/exportLogs.js');

let source = fs.readFileSync(sourcePath, 'utf8');
source = source.replace(/import[\s\S]*?from '\.\/today\.state\.js';\s*/m, '');
source = source.replace(/import\s*\{[\s\S]*?\}\s*from '\.\/exportLogTargets\.js\?[^']+';\s*/m, '');
source = source.replace(/export function initExport\(/, 'function initExport(');

function makeContext(state) {
  const context = {
    state,
    window: {},
    document: {
      createElement: () => ({ click() {}, remove() {} }),
      body: { appendChild() {} },
    },
    URL: {
      createObjectURL: () => 'blob:test',
      revokeObjectURL() {},
    },
    Blob: function Blob() {},
    setTimeout,
    console,
    $: () => null,
    toast: () => {},
    getAdminDate: () => '2026-06-03',
    loadWeekendSlots: async () => {},
    hasWeekday: () => true,
    yoilOf: () => 'Wed',
    truthy: v => v === true || v === 'true',
    labelFor: () => 'Wed2',
    getSlots: () => [2],
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return context;
}

function labelsFor(state, date, sid = 's1', student = null) {
  return makeContext(state).rosterAssignedTests(date, sid, student).map(item => item.label).sort();
}

function videoTextFor(state, date, sid = 's1') {
  const context = makeContext(state);
  return context.rosterVideoText(date, sid, context.videoMapForRoster());
}

function taskTextFor(state, date, sid = 's1') {
  const context = makeContext(state);
  return context.rosterTaskText(date, { id: sid, subject: '대수' }, context.videoMapForRoster());
}

function exportedTaskTestNames(text) {
  const lines = String(text || '').split(/\r?\n/u);
  const markerIndex = lines.findIndex(value => value === '테스트 :');
  if (markerIndex < 0) return [];
  return lines.slice(markerIndex + 1).map(value => value.trim()).filter(Boolean);
}

function dateKeyFromOffset(offset) {
  const date = new Date(Date.UTC(2026, 0, 1 + offset));
  return date.toISOString().slice(0, 10);
}

function assertEqual(name, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    console.error(`FAIL ${name}`);
    console.error(`  expected: ${e}`);
    console.error(`  actual:   ${a}`);
    process.exit(1);
  }
  console.log(`PASS ${name}`);
}

function assertLessThan(name, actual, threshold) {
  if (!(actual < threshold)) {
    console.error(`FAIL ${name}`);
    console.error(`  expected: < ${threshold}`);
    console.error(`  actual:   ${actual}`);
    process.exit(1);
  }
  console.log(`PASS ${name}`);
}

const reviewOld = 'REVIEW / ALG / high / 6 / old review';
const schoolCarry = 'SCHOOL / ALG / mid / final / 1 / old school';
const unitNew = 'UNIT / ALG / Lv.6 / 1 / new unit';
const schoolHighNew = 'SCHOOL / ALG / high / final / 1 / new school high';
const schoolMidNew = 'SCHOOL / ALG / mid / final / 2 / new school mid';

assertEqual(
  'previous-curriculum assignments stay stored but are excluded from the roster export',
  labelsFor({
    logs: {
      '2026-06-03': {
        s1: {
          testAssignmentDailyTests: [
            { label: 'UNIT / ALG-current / Lv.6 / 1 / current unit', status: 'assigned', categoryKey: 'UNIT', curriculum: 'ALG-current' },
            { label: 'UNIT / ALG-previous / Lv.6 / 1 / previous unit', status: 'assigned', categoryKey: 'UNIT', curriculum: 'ALG-previous' },
          ],
        },
      },
    },
    progress: {
      '2026-06-03': {
        s1: {
          tests: {
            'UNIT / ALG-current / Lv.6 / 1 / current unit': 'assigned',
            'UNIT / ALG-previous / Lv.6 / 1 / previous unit': 'assigned',
          },
        },
      },
    },
    videos: [],
    updates: {},
  }, '2026-06-03', 's1', { id: 's1', curriculum: 'ALG-current' }),
  ['UNIT / ALG-current / Lv.6 / 1 / current unit'],
);

assertEqual(
  'daily slice plus active progress tests are exported',
  labelsFor({
    logs: {
      '2026-06-02': {
        s1: {
          assignedTests: [{ label: reviewOld, status: 'assigned', categoryKey: 'REVIEW' }],
        },
      },
      '2026-06-03': {
        s1: {
          testAssignmentDailyTests: [{ label: unitNew, status: 'assigned', categoryKey: 'UNIT' }],
          assignedTests: [
            { label: reviewOld, status: 'assigned', categoryKey: 'REVIEW' },
            { label: unitNew, status: 'assigned', categoryKey: 'UNIT' },
          ],
        },
      },
    },
    progress: {
      '2026-06-02': { s1: { tests: { [reviewOld]: 'assigned' } } },
      '2026-06-03': { s1: { tests: { [reviewOld]: 'assigned', [unitNew]: 'assigned' } } },
    },
    videos: [],
    updates: {},
  }, '2026-06-03'),
  [reviewOld, unitNew],
);

assertEqual(
  'current date exports all currently assigned tests even when active before',
  labelsFor({
    logs: {
      '2026-06-02': {
        s1: {
          assignedTests: [
            { label: reviewOld, status: 'assigned', categoryKey: 'REVIEW' },
            { label: schoolCarry, status: 'assigned', categoryKey: 'SCHOOL_PAST' },
          ],
        },
      },
      '2026-06-03': {
        s1: {
          assignedTests: [
            { label: reviewOld, status: 'assigned', categoryKey: 'REVIEW' },
            { label: schoolCarry, status: 'assigned', categoryKey: 'SCHOOL_PAST' },
            { label: unitNew, status: 'assigned', categoryKey: 'UNIT' },
            { label: schoolMidNew, status: 'assigned', categoryKey: 'SCHOOL_PAST' },
          ],
        },
      },
    },
    progress: {
      '2026-06-02': { s1: { tests: { [reviewOld]: 'assigned', [schoolCarry]: 'assigned' } } },
      '2026-06-03': {
        s1: {
          tests: {
            [reviewOld]: 'assigned',
            [schoolCarry]: 'assigned',
            [unitNew]: 'assigned',
            [schoolMidNew]: 'assigned',
          },
        },
      },
    },
    videos: [],
    updates: {},
  }, '2026-06-03'),
  [reviewOld, schoolCarry, schoolMidNew, unitNew].sort(),
);

assertEqual(
  'empty target date falls back to all previous assigned tests',
  labelsFor({
    logs: {
      '2026-06-01': {
        s1: {
          assignedTests: [
            { label: reviewOld, status: 'assigned', categoryKey: 'REVIEW' },
            { label: schoolCarry, status: 'assigned', categoryKey: 'SCHOOL_PAST' },
          ],
        },
      },
      '2026-06-02': {
        s1: {
          assignedTests: [
            { label: reviewOld, status: 'assigned', categoryKey: 'REVIEW' },
            { label: schoolCarry, status: 'assigned', categoryKey: 'SCHOOL_PAST' },
            { label: unitNew, status: 'assigned', categoryKey: 'UNIT' },
            { label: schoolHighNew, status: 'assigned', categoryKey: 'SCHOOL_PAST' },
            { label: schoolMidNew, status: 'assigned', categoryKey: 'SCHOOL_PAST' },
          ],
        },
      },
      '2026-06-03': { s1: { notes: 'no tests yet' } },
    },
    progress: {
      '2026-06-01': { s1: { tests: { [reviewOld]: 'assigned', [schoolCarry]: 'assigned' } } },
      '2026-06-02': {
        s1: {
          tests: {
            [reviewOld]: 'assigned',
            [schoolCarry]: 'assigned',
            [unitNew]: 'assigned',
            [schoolHighNew]: 'assigned',
            [schoolMidNew]: 'assigned',
          },
        },
      },
    },
    videos: [],
    updates: {},
  }, '2026-06-03'),
  [reviewOld, schoolCarry, schoolHighNew, schoolMidNew, unitNew].sort(),
);

assertEqual(
  'intermediate student activity does not hide still-assigned fallback tests',
  labelsFor({
    logs: {
      '2026-06-01': {
        s1: {
          assignedTests: [{ label: reviewOld, status: 'assigned', categoryKey: 'REVIEW' }],
        },
      },
      '2026-06-02': { s1: { notes: 'attended, no new tests' } },
    },
    progress: {
      '2026-06-01': { s1: { tests: { [reviewOld]: 'assigned' } } },
      '2026-06-02': { s1: { video42: 'done' } },
    },
    videos: [],
    updates: {},
  }, '2026-06-03'),
  [reviewOld],
);

assertEqual(
  'current explicit skip status blocks fallback resurrection',
  labelsFor({
    logs: {
      '2026-06-02': {
        s1: {
          assignedTests: [{ label: reviewOld, status: 'assigned', categoryKey: 'REVIEW' }],
        },
      },
      '2026-06-03': { s1: {} },
    },
    progress: {
      '2026-06-02': { s1: { tests: { [reviewOld]: 'assigned' } } },
      '2026-06-03': { s1: { tests: { [reviewOld]: 'skip' } } },
    },
    videos: [],
    updates: {},
  }, '2026-06-03'),
  [],
);

assertEqual(
  'completed tests do not export as roster assignments',
  labelsFor({
    logs: {
      '2026-06-03': {
        s1: {
          testAssignmentDailyTests: [
            { label: unitNew, status: 'assigned', categoryKey: 'UNIT' },
            { label: reviewOld, status: 'done', categoryKey: 'REVIEW' },
          ],
          assignedTests: [
            { label: unitNew, status: 'assigned', categoryKey: 'UNIT' },
            { label: reviewOld, status: 'done', categoryKey: 'REVIEW' },
          ],
        },
      },
    },
    progress: {
      '2026-06-03': { s1: { tests: { [unitNew]: 'assigned', [reviewOld]: 'done' } } },
    },
    videos: [],
    updates: {},
  }, '2026-06-03'),
  [unitNew],
);

assertEqual(
  'previous completed test does not block a current reassignment',
  labelsFor({
    logs: {
      '2026-06-02': {
        s1: {
          assignedTests: [{ label: reviewOld, status: 'done', categoryKey: 'REVIEW' }],
        },
      },
      '2026-06-03': {
        s1: {
          testAssignmentDailyTests: [{ label: reviewOld, status: 'assigned', categoryKey: 'REVIEW' }],
          assignedTests: [{ label: reviewOld, status: 'assigned', categoryKey: 'REVIEW' }],
        },
      },
    },
    progress: {
      '2026-06-02': { s1: { tests: { [reviewOld]: 'done' } } },
      '2026-06-03': { s1: { tests: { [reviewOld]: 'assigned' } } },
    },
    videos: [],
    updates: {},
  }, '2026-06-03'),
  [reviewOld],
);

const schoolPastText = taskTextFor({
  logs: {
    '2026-06-03': {
      s1: {
        testAssignmentDailyTests: [
          {
            label: '학군지 기출 / 대수 / 상 / 기말고사 / 1회차 / 압구정고',
            status: 'assigned',
            categoryKey: 'SCHOOL_PAST',
            categoryLabel: '학군지 기출',
            curriculum: '대수',
            difficulty: '상',
            term: '기말고사',
            round: '1',
            name: '압구정고',
          },
          {
            label: '학군지 기출 / 대수 / 상 / 기말고사 / 2회차 / 세화여고',
            status: 'assigned',
            categoryKey: 'SCHOOL_PAST',
            categoryLabel: '학군지 기출',
            curriculum: '대수',
            difficulty: '상',
            term: '기말고사',
            round: '2',
            name: '세화여고',
          },
          {
            label: '일산 기출 / 대수 / 중 / 기말고사 / 1회차 / 저동고',
            status: 'assigned',
            categoryKey: 'ILSAN_PAST',
            categoryLabel: '일산 기출',
            curriculum: '대수',
            difficulty: '중',
            term: '기말고사',
            round: '1',
            name: '저동고',
          },
          {
            label: '일산 기출 / 대수 / 상 / 기말고사 / 2회차 / 운정',
            status: 'assigned',
            categoryKey: 'ILSAN_PAST',
            categoryLabel: '일산 기출',
            curriculum: '대수',
            difficulty: '상',
            term: '기말고사',
            round: '2',
            name: '운정',
          },
          {
            label: '일산 기출 / 대수 / 삼각함수 그래프 포함 / 기말고사 / 1회차 / 삼각함수 그래프 포함 1회차 24 가좌',
            status: 'assigned',
            categoryKey: 'ILSAN_PAST',
            categoryLabel: '일산 기출',
            curriculum: '대수',
            difficulty: '삼각함수 그래프 포함',
            term: '기말고사',
            round: '1',
            name: '삼각함수 그래프 포함 1회차 24 가좌',
          },
        ],
      },
    },
  },
  progress: {
    '2026-06-03': {
      s1: {
        tests: {
          '학군지 기출 / 대수 / 상 / 기말고사 / 1회차 / 압구정고': 'assigned',
          '학군지 기출 / 대수 / 상 / 기말고사 / 2회차 / 세화여고': 'assigned',
          '일산 기출 / 대수 / 중 / 기말고사 / 1회차 / 저동고': 'assigned',
          '일산 기출 / 대수 / 상 / 기말고사 / 2회차 / 운정': 'assigned',
          '일산 기출 / 대수 / 삼각함수 그래프 포함 / 기말고사 / 1회차 / 삼각함수 그래프 포함 1회차 24 가좌': 'assigned',
        },
      },
    },
  },
  videos: [],
  updates: {},
}, '2026-06-03');

const schoolExportedNames = exportedTaskTestNames(schoolPastText);
assertEqual(
  'roster export labels school and Ilsan past tests with source, difficulty, and round',
  schoolExportedNames.slice().sort((a, b) => a.localeCompare(b, 'ko')),
  [
    '학군지(상) 1회차 압구정고',
    '학군지(상) 2회차 세화여고',
    '일산(중상) 1회차 저동고',
    '일산(상) 2회차 운정',
    '일산(그래프 포함) 1회차 24 가좌',
  ]
    .sort((a, b) => a.localeCompare(b, 'ko')),
);
if (/50분|기말고사/u.test(schoolPastText)) {
  console.error('FAIL roster export leaked duration or term metadata');
  console.error(schoolPastText);
  process.exit(1);
}

const greenLabel = 'UNIT / 대수 / Lv.4 / 1 / 초록 테스트';
const orangeLabel = 'UNIT / 대수 / Lv.4 / 2 / 주황 테스트';
const blueLabel = 'UNIT / 대수 / Lv.4 / 3 / 파랑 테스트';
const redLabel = 'UNIT / 대수 / Lv.4 / 4 / 빨강 테스트';
const greenOnlyText = taskTextFor({
  logs: {
    '2026-06-03': {
      s1: {
        testAssignmentDailyTests: [
          { label: greenLabel, name: '초록 테스트', status: 'assigned', categoryKey: 'UNIT', curriculum: '대수' },
          { label: orangeLabel, name: '주황 테스트', status: 'interrupted', categoryKey: 'UNIT', curriculum: '대수' },
          { label: blueLabel, name: '파랑 테스트', status: 'done', categoryKey: 'UNIT', curriculum: '대수' },
          { label: redLabel, name: '빨강 테스트', status: 'skip', categoryKey: 'UNIT', curriculum: '대수' },
        ],
      },
    },
  },
  progress: {
    '2026-06-03': {
      s1: {
        tests: {
          [greenLabel]: 'assigned',
          [orangeLabel]: 'interrupted',
          [blueLabel]: 'done',
          [redLabel]: 'skip',
        },
      },
    },
  },
  videos: [],
  updates: {},
}, '2026-06-03');
assertEqual(
  'roster task export keeps only green assigned test names',
  exportedTaskTestNames(greenOnlyText),
  ['초록 테스트'],
);

assertEqual(
  'video export excludes prior done videos unless the selected date explicitly reopens them',
  videoTextFor({
    logs: {},
    progress: {
      '2026-06-02': { s1: { v41: 'done', v42: 'done' } },
      '2026-06-03': { s1: { v42: 'none', v43: { status: 'done' }, v44: 'interrupted', __manualProgressMids: { v42: true } } },
    },
    videos: [
      { mid: 'v41', chapter: 41, title: 'video 41' },
      { mid: 'v42', chapter: 42, title: 'video 42' },
      { mid: 'v43', chapter: 43, title: 'video 43' },
      { mid: 'v44', chapter: 44, title: 'video 44' },
    ],
    updates: {
      '2026-06-02': { s1: { videos: ['v41', 'v43'], source: 'auto' } },
      '2026-06-03': { s1: { videos: ['v41', 'v42', 'v43', 'v44'], source: 'auto' } },
    },
  }, '2026-06-03'),
  '42차시, 43차시, 44차시',
);

{
  const date = '2026-06-03';
  const dayStart = Date.parse(`${date}T00:00:00+09:00`);
  const state = {
    logs: {},
    progress: {
      '2026-06-01': { s1: { v1: 'done', v2: { status: 'done' }, v3: 'done', v4: 'done', v5: 'done',
        v6: 'done', v7: 'done', v8: 'done', v9: 'done', v10: 'done',
        __videoWatchCycles: { v7: { token: 'continued', startedAt: dayStart - 86400000 },
          v8: { token: 'old', startedAt: dayStart - 86400000 } } } },
      '2026-06-02': { s1: { v1: 'none', v2: 'interrupted',
        __autoWatchProgressMids: { v2: 'interrupted' } } },
      [date]: { s1: { v3: 'none', v4: 'interrupted', v5: 'none', v6: 'interrupted', v7: 'interrupted',
        v8: 'done', v9: 'done', v10: 'none', v11: 'done', v12: 'none',
        __manualProgressMids: { v5: true, v6: true },
        __autoWatchProgressMids: { v4: 'interrupted' },
        __videoWatchCycles: {
          v7: { token: 'continued', startedAt: dayStart + 1000 },
          v8: { token: 'new', startedAt: dayStart + 1000 },
          v9: { token: 'first-observed-late', startedAt: dayStart - 1000 },
          v10: { token: 'new-at-midnight', startedAt: dayStart },
        } } },
      '2026-06-04': { s1: { v12: 'done' } },
    },
    videos: Array.from({ length: 12 }, (_, i) => ({ mid: `v${i + 1}`, chapter: i + 1 })),
    updates: { [date]: { s1: { source: 'manual', videos: Array.from({ length: 12 }, (_, i) => `v${i + 1}`) } } },
  };
  const before = JSON.stringify(state);
  assertEqual(
    'roster excludes historical completion noise and keeps proven same-day reopens and new lessons',
    videoTextFor(state, date),
    '5차시, 6차시, 8차시, 10차시, 11차시, 12차시',
  );
  assertEqual('roster completion projection never rewrites its source records', JSON.stringify(state), before);
}

const combinedVideoAndTestText = taskTextFor({
  logs: {
    '2026-06-03': {
      s1: {
        testAssignmentDailyTests: [
          { label: greenLabel, name: '초록 테스트', status: 'assigned', categoryKey: 'UNIT', curriculum: '대수' },
        ],
      },
    },
  },
  progress: {
    '2026-06-02': {
      s1: { v40: 'done' },
    },
    '2026-06-03': {
      s1: {
        v41: 'done',
        v43: { status: 'done' },
        tests: { [greenLabel]: 'assigned' },
      },
    },
  },
  videos: [
    { mid: 'v40', chapter: 40, title: 'video 40' },
    { mid: 'v41', chapter: 41, title: 'video 41' },
    { mid: 'v43', chapter: 43, title: 'video 43' },
  ],
  updates: {
    '2026-06-03': { s1: { videos: ['v40', 'v41', 'v43'], source: 'manual' } },
  },
}, '2026-06-03');
assertEqual(
  'roster task export removes prior done videos while keeping selected-date videos and tests together',
  [
    combinedVideoAndTestText.includes('영상 : 41차시, 43차시'),
    exportedTaskTestNames(combinedVideoAndTestText),
  ],
  [true, ['초록 테스트']],
);

{
  const students = 160;
  const days = 180;
  const targetDate = dateKeyFromOffset(days - 1);
  const progress = {};
  const logs = {};
  for (let d = 0; d < days; d += 1) {
    progress[dateKeyFromOffset(d)] = {};
    logs[dateKeyFromOffset(d)] = {};
  }
  for (let s = 0; s < students; s += 1) {
    const sid = `s${s}`;
    const round = String((s % 9) + 1);
    const label = `SCHOOL / ALG / high / final / ${round} / school${s}`;
    progress[dateKeyFromOffset(0)][sid] = { tests: { [label]: 'assigned' } };
    logs[dateKeyFromOffset(0)][sid] = {
      assignedTests: [{
        label,
        status: 'assigned',
        categoryKey: 'SCHOOL_PAST',
        difficulty: 'high',
        round,
        name: `school${s}`,
      }],
    };
    for (let d = 1; d < days - 1; d += 1) {
      progress[dateKeyFromOffset(d)][sid] = { video42: 'done' };
      logs[dateKeyFromOffset(d)][sid] = { notes: 'attended' };
    }
    progress[targetDate][sid] = { video99: 'done' };
    logs[targetDate][sid] = { notes: 'export day' };
  }
  const context = makeContext({ progress, logs, videos: [], updates: {} });
  const started = performance.now();
  let count = 0;
  for (let s = 0; s < students; s += 1) {
    count += context.rosterAssignedTests(targetDate, `s${s}`).length;
  }
  assertEqual('large fallback export keeps every carried assignment', count, students);
  assertLessThan(
    'large fallback export avoids repeated historical scans',
    Number((performance.now() - started).toFixed(2)),
    120,
  );
}

(async () => {
  const date = '2026-06-03';
  const context = makeContext({
    students: [
      { id: 'self-study', name: '자습 학생' },
      { id: 'class', name: '수업 학생' },
    ],
    logs: {
      [date]: {
        'self-study': { selfStudy: true },
        class: { selfStudy: false },
      },
    },
    progress: {},
    videos: [],
    updates: {},
  });
  context.fetch = async () => ({ json: async () => ({}) });
  const rows = await context.loadRosterStudents(date);
  assertEqual(
    'self-study students are excluded from roster exports',
    rows.map(student => student.id),
    ['class'],
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

console.log('Roster export regression checks passed.');
