const isObject = (value) => value && typeof value === 'object' && !Array.isArray(value);
const GRADE_PHASE_DELIM = '::';
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

function mergeNonBlank(base, override) {
  const merged = { ...(base || {}) };
  for (const [key, value] of Object.entries(override || {})) {
    if (value == null) continue;
    if (typeof value === 'string' && !value.trim()) continue;
    merged[key] = value;
  }
  return merged;
}

function firstNonBlank(...values) {
  for (const value of values) {
    if (typeof value === 'string') {
      if (value.trim()) return value;
      continue;
    }
    if (value != null && value !== '') return value;
  }
  return '';
}

function pickScheduleFields(entry = {}) {
  const out = {};
  for (const key of SCHEDULE_KEYS) {
    out[key] = String(entry?.[key] ?? '').trim();
  }
  return out;
}

function hasAnyScheduleValue(entry = {}) {
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
  if (idx < 0) {
    return { grade: key, phase: '' };
  }

  return {
    grade: key.slice(0, idx).trim(),
    phase: key.slice(idx + GRADE_PHASE_DELIM.length).trim(),
  };
}

function uniqueNonBlankStrings(values = []) {
  const seen = new Set();
  const out = [];
  for (const value of values) {
    const v = String(value ?? '').trim();
    if (!v || seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

export function isSchoolCalendarV2(payload) {
  return isObject(payload) && isObject(payload.years);
}

export function normalizeGradeLabel(value) {
  const compact = String(value ?? '').trim().replace(/\s+/g, '');
  const gradeMatch = compact.match(/^(?:고|중)?([1-3])(?:학년)?$/);
  return gradeMatch ? `${gradeMatch[1]}학년` : compact;
}

export function getActiveSchoolCalendarYear(payload) {
  if (!isSchoolCalendarV2(payload)) return '';

  const years = payload.years || {};
  const keys = Object.keys(years);
  if (!keys.length) return String(payload.activeYear || '');

  const active = String(payload.activeYear || '');
  if (active && years[active]) return active;

  return keys.sort((a, b) => String(a).localeCompare(String(b), 'ko')).at(-1) || active;
}

export function getSchoolCalendarSchoolMap(payload, year = getActiveSchoolCalendarYear(payload)) {
  if (isSchoolCalendarV2(payload)) {
    const bundle = payload.years?.[String(year)] || {};
    return isObject(bundle.schools) ? bundle.schools : {};
  }

  return isObject(payload) ? payload : {};
}

export function resolveSchoolCalendarEntries(payload, schoolName, grade = '') {
  const name = String(schoolName ?? '').trim();
  if (!name) return [];

  const schoolMap = getSchoolCalendarSchoolMap(payload);
  const raw = schoolMap[name];
  if (!isObject(raw)) return [];

  if (!isObject(raw.common) && !isObject(raw.grades)) {
    const fields = pickScheduleFields(raw);
    return hasAnyScheduleValue(fields)
      ? [{ grade: String(grade || '').trim(), phase: '', ...raw }]
      : [];
  }

  const common = isObject(raw.common) ? raw.common : {};
  const commonFields = pickScheduleFields(common);
  const grades = isObject(raw.grades) ? raw.grades : {};
  const normalizedGrade = normalizeGradeLabel(grade);

  if (!normalizedGrade) {
    return hasAnyScheduleValue(commonFields)
      ? [{ grade: '', phase: '', ...common }]
      : [];
  }

  const matched = [];
  for (const [key, entry] of Object.entries(grades)) {
    if (!isObject(entry)) continue;
    const token = parseGradeToken(key, entry);
    if (normalizeGradeLabel(token.grade) !== normalizedGrade) continue;
    const fields = mergeNonBlank(common, entry);
    matched.push({
      grade: token.grade,
      phase: token.phase,
      ...fields,
    });
  }

  if (matched.length) {
    matched.sort((a, b) => String(a.phase || '').localeCompare(String(b.phase || ''), 'ko'));
    return matched;
  }

  return hasAnyScheduleValue(commonFields)
    ? [{ grade: String(grade || '').trim(), phase: '', ...common }]
    : [];
}

export function resolveSchoolCalendarEntry(payload, schoolName, grade = '') {
  const entries = resolveSchoolCalendarEntries(payload, schoolName, grade);
  if (!entries.length) return {};

  if (entries.length === 1) {
    const { grade: _grade, phase: _phase, ...single } = entries[0] || {};
    return single;
  }

  // 같은 학교/학년에 여러 시기(트랙) 데이터가 있으면 충돌 값은 " / "로 합쳐서 보여준다.
  const merged = {};
  for (const key of SCHEDULE_KEYS) {
    const values = uniqueNonBlankStrings(entries.map((entry) => entry?.[key]));
    if (!values.length) continue;
    merged[key] = values.length === 1 ? values[0] : values.join(' / ');
  }
  return merged;
}

export function flattenSchoolCalendarRows(payload, year = getActiveSchoolCalendarYear(payload), options = {}) {
  const splitByGrade = !!options?.splitByGrade;
  const schoolMap = getSchoolCalendarSchoolMap(payload, year);
  const rows = [];

  for (const [school, entry] of Object.entries(schoolMap).sort(([a], [b]) => a.localeCompare(b, 'ko'))) {
    if (!isObject(entry)) continue;

    if (!isObject(entry.common) && !isObject(entry.grades)) {
      rows.push({
        school,
        grade: '',
        phase: '',
        textbook: entry.textbook || '',
        semesterStart: entry.semesterStart || '',
        midterm: entry.midterm || '',
        midtermMath: entry.midtermMath || '',
        midtermRange: entry.midtermRange || '',
        midtermNote: entry.midtermNote || '',
        final: entry.final || '',
        finalMath: entry.finalMath || '',
        finalRange: entry.finalRange || '',
        finalNote: entry.finalNote || '',
      });
      continue;
    }

    const common = pickScheduleFields(isObject(entry.common) ? entry.common : {});
    const grades = isObject(entry.grades) ? entry.grades : {};

    if (!splitByGrade) {
      const gradeEntries = Object.values(grades).filter(isObject);
      const pick = (key) => firstNonBlank(common[key], ...gradeEntries.map((gradeEntry) => gradeEntry[key]));
      rows.push({
        school,
        grade: '',
        phase: '',
        textbook: pick('textbook'),
        semesterStart: pick('semesterStart'),
        midterm: pick('midterm'),
        midtermMath: pick('midtermMath'),
        midtermRange: pick('midtermRange'),
        midtermNote: pick('midtermNote'),
        final: pick('final'),
        finalMath: pick('finalMath'),
        finalRange: pick('finalRange'),
        finalNote: pick('finalNote'),
      });
      continue;
    }

    if (hasAnyScheduleValue(common)) {
      rows.push({
        school,
        grade: '',
        phase: '',
        ...common,
      });
    }

    for (const [gradeKey, gradeEntry] of Object.entries(grades)) {
      if (!isObject(gradeEntry)) continue;
      const token = parseGradeToken(gradeKey, gradeEntry);
      const gradeFields = pickScheduleFields(gradeEntry);
      const hasMetadata = String(gradeEntry?.__grade ?? '').trim() || String(gradeEntry?.__phase ?? '').trim();
      // 과거 버전의 "빈 학년 placeholder"는 목록에서 숨긴다.
      if (!hasAnyScheduleValue(gradeFields) && !hasMetadata) continue;
      const merged = mergeNonBlank(common, gradeFields);
      rows.push({
        school,
        grade: token.grade,
        phase: token.phase,
        ...merged,
      });
    }
  }

  if (splitByGrade) {
    rows.sort((a, b) => {
      const schoolCmp = String(a.school || '').localeCompare(String(b.school || ''), 'ko');
      if (schoolCmp !== 0) return schoolCmp;
      const gradeCmp = String(a.grade || '').localeCompare(String(b.grade || ''), 'ko');
      if (gradeCmp !== 0) return gradeCmp;
      return String(a.phase || '').localeCompare(String(b.phase || ''), 'ko');
    });
  } else {
    rows.sort((a, b) => String(a.school || '').localeCompare(String(b.school || ''), 'ko'));
  }

  return rows;
}
