import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveSchoolCalendarEntries } from '../static/js/shared/schoolCalendar.js';

import {
  buildSchoolCalendarDocument,
  cloneSchoolCalendarRow,
  coerceSchoolCalendarExam,
  coerceSchoolCalendarSemester,
  loadSchoolCalendarRows,
  resolveSchoolCalendarPageSelection,
  withActiveSchoolCalendarPage,
} from '../static/js/school-calendar/state.js';


const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const EMPTY_COMMON = {
  textbook: '',
  semesterStart: '',
  midterm: '',
  midtermMath: '',
  midtermRange: '',
  midtermNote: '',
  final: '',
  finalMath: '',
  finalRange: '',
  finalNote: '',
};

const SOURCE_DOCUMENT = {
  version: 2,
  activeYear: '2026',
  activeSemester: '2',
  activeExam: 'final',
  rootExtra: { keep: true },
  years: {
    2025: { untouched: 'older year' },
    2026: {
      activeSemester: '2',
      activeExam: 'final',
      yearExtra: 'keep year metadata',
      semesters: {
        2: {
          semesterExtra: 'keep semester metadata',
          schools: {
            나학교: {
              schoolExtra: 'keep school metadata',
              common: {
                semesterStart: ' 3/4 ',
                final: ' 6/30 ',
              },
              grades: {
                '2학년::미적분': {
                  __grade: '2학년',
                  __phase: '미적분',
                  textbook: ' YBM ',
                  finalMath: ' 6/28 ',
                  finalNote: ' 서술형 ',
                },
                '': {},
              },
            },
            가학교: {
              semesterStart: ' 3/2 ',
              final: ' 6/29 ',
            },
          },
        },
      },
    },
  },
};

function deterministicIds(prefix) {
  let sequence = 0;
  return () => `${prefix}${++sequence}`;
}

function verifyLiteralLoadProjection() {
  const loaded = loadSchoolCalendarRows(SOURCE_DOCUMENT, {
    year: '2026',
    semester: '2',
    nextSchoolId: deterministicIds('s'),
    nextGradeId: deterministicIds('g'),
  });

  assert.deepEqual(loaded, {
    rows: [
      {
        id: 's2',
        school: '가학교',
        common: {
          ...EMPTY_COMMON,
          semesterStart: '3/2',
          final: '6/29',
        },
        grades: [],
      },
      {
        id: 's1',
        school: '나학교',
        common: {
          ...EMPTY_COMMON,
          semesterStart: '3/4',
          final: '6/30',
        },
        grades: [
          {
            id: 'g1',
            grade: '2학년',
            phase: '미적분',
            fields: {
              ...EMPTY_COMMON,
              textbook: 'YBM',
              semesterStart: '',
              final: '',
              finalMath: '6/28',
              finalNote: '서술형',
            },
          },
        ],
      },
    ],
    expandedSchoolIds: ['s1'],
  });
}

function verifyLiteralDocumentBuild() {
  const next = buildSchoolCalendarDocument({
    calendarDoc: SOURCE_DOCUMENT,
    schools: [
      {
        id: 's2',
        school: '가학교',
        common: { semesterStart: '3/5', final: '7/1' },
        grades: [],
      },
      {
        id: 's1',
        school: '나학교',
        common: { semesterStart: '3/4', final: '6/30' },
        grades: [
          {
            id: 'g1',
            grade: '2학년',
            phase: '미적분',
            fields: { textbook: 'YBM2', finalMath: '7/2', finalNote: '서술형 포함' },
          },
          {
            id: 'g2',
            grade: '',
            phase: '저장 금지',
            fields: { textbook: 'ignored' },
          },
        ],
      },
    ],
    activeYear: '2026',
    activeSemester: '2',
    activeExam: 'mid',
    fallbackYear: '2099',
  });

  assert.deepEqual(next, {
    version: 2,
    activeYear: '2026',
    activeSemester: '2',
    activeExam: 'mid',
    rootExtra: { keep: true },
    years: {
      2025: { untouched: 'older year' },
      2026: {
        activeSemester: '2',
        activeExam: 'mid',
        yearExtra: 'keep year metadata',
        semesters: {
          2: {
            semesterExtra: 'keep semester metadata',
            schools: {
              가학교: {
                semesterStart: ' 3/2 ',
                final: ' 6/29 ',
                common: {
                  ...EMPTY_COMMON,
                  semesterStart: '3/5',
                  final: '7/1',
                },
                grades: {},
              },
              나학교: {
                schoolExtra: 'keep school metadata',
                common: {
                  ...EMPTY_COMMON,
                  semesterStart: '3/4',
                  final: '6/30',
                },
                grades: {
                  '2학년::미적분': {
                    ...EMPTY_COMMON,
                    textbook: 'YBM2',
                    semesterStart: '',
                    final: '',
                    finalMath: '7/2',
                    finalNote: '서술형 포함',
                    __grade: '2학년',
                    __phase: '미적분',
                  },
                },
              },
            },
          },
        },
      },
    },
  });

  assert.equal(next.years['2026'].schools, undefined, 'semester 2 must not create the legacy semester-1 mirror');
}

function verifySemesterOneMirrorAndActivePage() {
  const built = buildSchoolCalendarDocument({
    calendarDoc: {},
    schools: [{ id: 's1', school: '새학교', common: {}, grades: [] }],
    activeYear: '',
    activeSemester: '1',
    activeExam: 'final',
    fallbackYear: '2030',
  });
  const expectedSchools = {
    새학교: {
      common: EMPTY_COMMON,
      grades: {},
    },
  };
  assert.deepEqual(built, {
    version: 2,
    activeYear: '2030',
    activeSemester: '1',
    activeExam: 'final',
    years: {
      2030: {
        activeSemester: '1',
        activeExam: 'final',
        schools: expectedSchools,
        semesters: {
          1: { schools: expectedSchools },
        },
      },
    },
  });

  const active = withActiveSchoolCalendarPage(SOURCE_DOCUMENT, {
    year: '2027',
    semester: '2',
    exam: 'mid',
  });
  assert.deepEqual(active, {
    ...SOURCE_DOCUMENT,
    activeYear: '2027',
    activeSemester: '2',
    activeExam: 'mid',
    years: {
      ...SOURCE_DOCUMENT.years,
      2027: {
        activeSemester: '2',
        activeExam: 'mid',
      },
    },
  });
}

function verifySelectionCoercion() {
  assert.equal(coerceSchoolCalendarSemester('2'), '2');
  assert.equal(coerceSchoolCalendarSemester(2), '2');
  assert.equal(coerceSchoolCalendarSemester('3'), '1');
  assert.equal(coerceSchoolCalendarExam('final'), 'final');
  assert.equal(coerceSchoolCalendarExam('mid'), 'mid');
  assert.equal(coerceSchoolCalendarExam('other'), 'mid');
}

function verifyLiteralEditableClone() {
  const source = {
    id: 's9',
    school: '  복제 학교  ',
    common: { semesterStart: ' 3/6 ', final: ' 7/3 ' },
    grades: [
      {
        id: '',
        grade: ' 1학년 ',
        phase: ' 수학1 ',
        fields: { textbook: ' 비상 ', midtermMath: ' 4/24 ' },
      },
    ],
  };
  const cloned = cloneSchoolCalendarRow(source, { nextGradeId: deterministicIds('cg') });
  assert.deepEqual(cloned, {
    id: 's9',
    school: '복제 학교',
    common: {
      ...EMPTY_COMMON,
      semesterStart: '3/6',
      final: '7/3',
    },
    grades: [
      {
        id: 'cg1',
        grade: '1학년',
        phase: '수학1',
        fields: {
          ...EMPTY_COMMON,
          textbook: '비상',
          semesterStart: '',
          midterm: '',
          midtermMath: '4/24',
          final: '',
        },
      },
    ],
  });
  assert.equal(source.school, '  복제 학교  ', 'the projection must not mutate the caller state');
}

function verifyPageStateBoundary() {
  const source = fs.readFileSync(path.join(ROOT, 'static/js/school-cal.js'), 'utf8');
  assert.match(source, /from '\.\/school-calendar\/state\.js'/);
  assert.match(source, /loadSchoolCalendarRows\(/);
  assert.match(source, /buildSchoolCalendarDocument\(/);
  assert.doesNotMatch(source, /function normalizeScheduleFields\(/);
  assert.doesNotMatch(source, /function parseGradeToken\(/);
  assert.doesNotMatch(source, /const SCHEDULE_KEYS\s*=/);
}

verifyLiteralLoadProjection();
verifyLiteralDocumentBuild();
verifySemesterOneMirrorAndActivePage();
verifySelectionCoercion();
verifyLiteralEditableClone();
verifyPageStateBoundary();

{
  const saved = { activeYear: '2026', activeSemester: '2', activeExam: 'mid', years: {
    '2026': { activeSemester: '2', activeExam: 'mid', semesters: {
      '1': { schools: { '검증학교': { common: { final: '6/30' } } } },
      '2': { schools: { '검증학교': { common: { midterm: '10/13' } } } },
    } },
  } };
  const before = JSON.stringify(saved);
  assert.deepEqual(resolveSchoolCalendarPageSelection(saved,
    { year: '2025', semester: '1', exam: 'final' }, '2026'),
  { year: '2026', semester: '2', exam: 'mid' }, 'shared active page wins over stale browser selection');
  assert.deepEqual(resolveSchoolCalendarPageSelection(saved, {}, '2026'),
    { year: '2026', semester: '2', exam: 'mid' }, 'a fresh browser uses the same active page');
  assert.deepEqual(resolveSchoolCalendarEntries(saved, '검증학교', '1학년'),
    [{ grade: '1학년', phase: '', midterm: '10/13' }],
    'shared admin/all popup consumers resolve semester two, not semester-one final');
  const historical = withActiveSchoolCalendarPage(saved, { year: '2026', semester: '1', exam: 'final' });
  assert.deepEqual(resolveSchoolCalendarPageSelection(historical,
    { year: '2026', semester: '2', exam: 'mid' }, '2026'),
  { year: '2026', semester: '1', exam: 'final' }, 'explicit later history selection remains supported');
  assert.deepEqual(resolveSchoolCalendarEntries(historical, '검증학교', '1학년'),
    [{ grade: '1학년', phase: '', final: '6/30' }], 'semester-one historical schedule remains intact');
  assert.deepEqual(resolveSchoolCalendarPageSelection({},
    { year: '2025', semester: '2', exam: 'mid' }, '2026'),
  { year: '2025', semester: '2', exam: 'mid' }, 'legacy documents retain local selection fallback');
  assert.equal(JSON.stringify(saved), before, 'page selection does not rewrite dates or rows');
}

console.log(JSON.stringify({
  ok: true,
  independentObservations: [
    'literal v2 document -> editable rows projection',
    'literal editable rows -> revisioned document projection',
    'unknown root/year/semester/school metadata preservation',
    'semester-1 compatibility mirror only',
    'active-page update without unrelated-year replacement',
    'server-authoritative active selection despite stale browser preferences',
    'editable-row cloning without caller mutation',
  ],
  supplementaryBoundaryGuards: [
    'the page entry delegates projection and does not retain the extracted state primitives',
  ],
}, null, 2));
