const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const sourcePath = path.join(root, 'static/js/admin/features/exportLogs.js');

let source = fs.readFileSync(sourcePath, 'utf8');
source = source.replace(/import[\s\S]*?from '\.\/today\.state\.js';\s*/m, '');
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

function labelsFor(state, date, sid = 's1') {
  return makeContext(state).rosterAssignedTests(date, sid).map(item => item.label).sort();
}

function videoTextFor(state, date, sid = 's1') {
  const context = makeContext(state);
  return context.rosterVideoText(date, sid, context.videoMapForRoster());
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

const reviewOld = 'REVIEW / ALG / high / 6 / old review';
const schoolCarry = 'SCHOOL / ALG / mid / final / 1 / old school';
const unitNew = 'UNIT / ALG / Lv.6 / 1 / new unit';
const schoolHighNew = 'SCHOOL / ALG / high / final / 1 / new school high';
const schoolMidNew = 'SCHOOL / ALG / mid / final / 2 / new school mid';

assertEqual(
  'daily slice wins over cumulative progress/log state',
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
  [unitNew],
);

assertEqual(
  'current date uses only labels newly added versus prior active tests',
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
  [schoolMidNew, unitNew].sort(),
);

assertEqual(
  'empty target date falls back to previous assignment date delta only',
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
  [schoolHighNew, schoolMidNew, unitNew].sort(),
);

assertEqual(
  'intermediate student activity blocks tomorrow from re-exporting old fallback tests',
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
  [],
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

assertEqual(
  'video export uses all videos assigned on the selected date, including repeated auto assignments',
  videoTextFor({
    logs: {},
    progress: {},
    videos: [
      { mid: 'v41', chapter: 41, title: 'video 41' },
      { mid: 'v43', chapter: 43, title: 'video 43' },
      { mid: 'v44', chapter: 44, title: 'video 44' },
    ],
    updates: {
      '2026-06-02': { s1: { videos: ['v41', 'v43'], source: 'auto' } },
      '2026-06-03': { s1: { videos: ['v41', 'v43', 'v44'], source: 'auto' } },
    },
  }, '2026-06-03'),
  '41차시, 43차시, 44차시',
);

console.log('Roster export regression checks passed.');
