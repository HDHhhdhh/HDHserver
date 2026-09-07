import {
  getActiveSchoolCalendarSemester,
  getActiveSchoolCalendarYear,
  isSchoolCalendarV2,
} from '../shared/schoolCalendar.js';


const SCHEDULE_KEYS = [
  'textbook',
  'semesterStart',
  'midterm',
  'midtermMath',
  'midtermRange',
  'midtermNote',
  'final',
  'finalMath',
  'finalRange',
  'finalNote',
];
const GRADE_PHASE_DELIM = '::';

export function isSchoolCalendarRecord(value) {
  return value && typeof value === 'object' && !Array.isArray(value);
}

function normalizeScheduleFields(entry = {}) {
  const out = {};
  for (const key of SCHEDULE_KEYS) {
    out[key] = String(entry?.[key] ?? '').trim();
  }
  return out;
}

export function normalizeSchoolCalendarCommon(entry = {}) {
  const out = normalizeScheduleFields(entry);
  out.textbook = '';
  out.midtermMath = '';
  out.midtermRange = '';
  out.midtermNote = '';
  out.finalMath = '';
  out.finalRange = '';
  out.finalNote = '';
  return out;
}

export function normalizeSchoolCalendarGrade(entry = {}) {
  const out = normalizeScheduleFields(entry);
  out.semesterStart = '';
  out.midterm = '';
  out.final = '';
  return out;
}

export function hasSchoolCalendarScheduleValue(entry = {}) {
  return SCHEDULE_KEYS.some((key) => String(entry?.[key] ?? '').trim());
}

function parseGradeToken(rawKey, gradeEntry = {}) {
  const key = String(rawKey ?? '').trim();
  const explicitGrade = String(gradeEntry?.__grade ?? '').trim();
  const explicitPhase = String(gradeEntry?.__phase ?? '').trim();

  if (explicitGrade || explicitPhase) {
    return {
      grade: explicitGrade || key,
      phase: explicitPhase,
    };
  }

  const idx = key.indexOf(GRADE_PHASE_DELIM);
  if (idx < 0) return { grade: key, phase: '' };

  return {
    grade: key.slice(0, idx).trim(),
    phase: key.slice(idx + GRADE_PHASE_DELIM.length).trim(),
  };
}

export function cloneSchoolCalendarRow(school, { nextGradeId } = {}) {
  if (typeof nextGradeId !== 'function') throw new TypeError('nextGradeId must be a function');
  return {
    id: school.id,
    school: String(school.school || '').trim(),
    common: normalizeSchoolCalendarCommon(school.common || {}),
    grades: (school.grades || []).map((gradeRow) => ({
      id: gradeRow.id || nextGradeId(),
      grade: String(gradeRow.grade || '').trim(),
      phase: String(gradeRow.phase || '').trim(),
      fields: normalizeSchoolCalendarGrade(gradeRow.fields || {}),
    })),
  };
}

export function getSchoolCalendarYearBundle(payload, year) {
  if (!isSchoolCalendarV2(payload)) return {};
  return isSchoolCalendarRecord(payload.years?.[String(year)])
    ? payload.years[String(year)]
    : {};
}

export function getSchoolCalendarMapForSelection(payload, year, semester) {
  const yearBundle = getSchoolCalendarYearBundle(payload, year);
  const semesters = isSchoolCalendarRecord(yearBundle.semesters) ? yearBundle.semesters : {};
  const semesterBundle = semesters[String(semester)];
  if (isSchoolCalendarRecord(semesterBundle?.schools)) return semesterBundle.schools;
  if (String(semester) === '1' && isSchoolCalendarRecord(yearBundle.schools)) return yearBundle.schools;
  return {};
}

export function loadSchoolCalendarRows(payload, {
  year,
  semester,
  nextSchoolId,
  nextGradeId,
} = {}) {
  if (typeof nextSchoolId !== 'function') throw new TypeError('nextSchoolId must be a function');
  if (typeof nextGradeId !== 'function') throw new TypeError('nextGradeId must be a function');

  const schoolMap = getSchoolCalendarMapForSelection(payload, year, semester);
  const rows = [];
  const expandedSchoolIds = [];

  for (const [schoolName, entry] of Object.entries(schoolMap)) {
    if (!isSchoolCalendarRecord(entry)) continue;

    if (!isSchoolCalendarRecord(entry.common) && !isSchoolCalendarRecord(entry.grades)) {
      rows.push({
        id: nextSchoolId(),
        school: schoolName,
        common: normalizeSchoolCalendarCommon(entry),
        grades: [],
      });
      continue;
    }

    const common = normalizeSchoolCalendarCommon(
      isSchoolCalendarRecord(entry.common) ? entry.common : {},
    );
    const grades = [];
    const rawGrades = isSchoolCalendarRecord(entry.grades) ? entry.grades : {};

    Object.entries(rawGrades).forEach(([gradeKey, gradeEntry]) => {
      if (!isSchoolCalendarRecord(gradeEntry)) return;
      const token = parseGradeToken(gradeKey, gradeEntry);
      const fields = normalizeSchoolCalendarGrade(gradeEntry);
      const hasMeta = token.grade || token.phase;
      if (!hasMeta && !hasSchoolCalendarScheduleValue(fields)) return;
      grades.push({
        id: nextGradeId(),
        grade: token.grade,
        phase: token.phase,
        fields,
      });
    });

    grades.sort((a, b) => {
      const gradeComparison = String(a.grade || '').localeCompare(String(b.grade || ''), 'ko');
      if (gradeComparison !== 0) return gradeComparison;
      return String(a.phase || '').localeCompare(String(b.phase || ''), 'ko');
    });

    const schoolId = nextSchoolId();
    rows.push({
      id: schoolId,
      school: schoolName,
      common,
      grades,
    });
    if (grades.length > 0) expandedSchoolIds.push(schoolId);
  }

  rows.sort((a, b) => String(a.school || '').localeCompare(String(b.school || ''), 'ko'));
  return { rows, expandedSchoolIds };
}

export function buildSchoolCalendarDocument({
  calendarDoc,
  schools,
  activeYear,
  activeSemester,
  activeExam,
  fallbackYear,
} = {}) {
  const yearKey = String(
    activeYear || getActiveSchoolCalendarYear(calendarDoc) || fallbackYear || '',
  );
  const semesterKey = String(activeSemester || '1');
  const existingSchools = getSchoolCalendarMapForSelection(calendarDoc, yearKey, semesterKey);
  const nextSchools = {};

  (schools || []).forEach((schoolEntry) => {
    const schoolName = String(schoolEntry.school || '').trim();
    if (!schoolName) return;

    const existing = isSchoolCalendarRecord(existingSchools[schoolName])
      ? { ...existingSchools[schoolName] }
      : {};
    delete existing.common;
    delete existing.grades;

    const grades = {};
    (schoolEntry.grades || []).forEach((gradeRow) => {
      const grade = String(gradeRow.grade || '').trim();
      const phase = String(gradeRow.phase || '').trim();
      const fields = normalizeSchoolCalendarGrade(gradeRow.fields || {});

      if (!grade && !phase && !hasSchoolCalendarScheduleValue(fields)) return;
      if (!grade) return;

      const key = phase ? `${grade}${GRADE_PHASE_DELIM}${phase}` : grade;
      if (!key) return;

      grades[key] = {
        ...fields,
        __grade: grade,
        __phase: phase,
      };
    });

    nextSchools[schoolName] = {
      ...existing,
      common: normalizeSchoolCalendarCommon(schoolEntry.common || {}),
      grades,
    };
  });

  const base = isSchoolCalendarV2(calendarDoc) ? calendarDoc : {};
  const years = { ...(base.years || {}) };
  const yearBundle = isSchoolCalendarRecord(years[yearKey]) ? { ...years[yearKey] } : {};
  const semesters = isSchoolCalendarRecord(yearBundle.semesters)
    ? { ...yearBundle.semesters }
    : {};
  const semesterBundle = isSchoolCalendarRecord(semesters[semesterKey])
    ? { ...semesters[semesterKey] }
    : {};

  semesters[semesterKey] = {
    ...semesterBundle,
    schools: nextSchools,
  };

  const nextYearBundle = {
    ...yearBundle,
    activeSemester: semesterKey,
    activeExam,
    semesters,
  };

  if (semesterKey === '1') nextYearBundle.schools = nextSchools;
  years[yearKey] = nextYearBundle;

  return {
    ...base,
    version: 2,
    activeYear: yearKey,
    activeSemester: semesterKey,
    activeExam,
    years,
  };
}

export function withActiveSchoolCalendarPage(calendarDoc, { year, semester, exam } = {}) {
  const base = isSchoolCalendarRecord(calendarDoc) ? calendarDoc : {};
  const years = isSchoolCalendarRecord(base.years) ? { ...base.years } : {};
  const yearBundle = isSchoolCalendarRecord(years[year]) ? { ...years[year] } : {};

  years[year] = {
    ...yearBundle,
    activeSemester: semester,
    activeExam: exam,
  };

  return {
    ...base,
    version: 2,
    activeYear: year,
    activeSemester: semester,
    activeExam: exam,
    years,
  };
}

export function coerceSchoolCalendarSemester(value) {
  return String(value) === '2' ? '2' : '1';
}

export function coerceSchoolCalendarExam(value) {
  return value === 'final' ? 'final' : 'mid';
}

export function resolveSchoolCalendarPageSelection(calendarDoc, stored = {}, fallbackYear = '') {
  const year = String(getActiveSchoolCalendarYear(calendarDoc) || stored.year || fallbackYear);
  const bundle = getSchoolCalendarYearBundle(calendarDoc, year);
  const rootIsSelectedYear = year === String(calendarDoc?.activeYear || '');
  const semester = isSchoolCalendarV2(calendarDoc)
    ? getActiveSchoolCalendarSemester(calendarDoc, year)
    : coerceSchoolCalendarSemester(stored.semester);
  const exam = coerceSchoolCalendarExam(bundle.activeExam
    || (rootIsSelectedYear ? calendarDoc.activeExam : '') || stored.exam || 'final');
  return { year, semester, exam };
}
