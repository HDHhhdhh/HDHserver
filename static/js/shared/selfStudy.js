export const SELF_STUDY_DAYS_FIELD = 'selfStudyDays';
export const DAY_FIELDS = ['day1', 'day2', 'day3', 'day4', 'day5'];

const WEEKDAY_CHARS = '\uC77C\uC6D4\uD654\uC218\uBAA9\uAE08\uD1A0';

export function truthyFlag(value) {
  return value === true || value === 'true' || value === 1 || value === '1';
}

export function selfStudyDaysForStudent(student) {
  const raw = student?.[SELF_STUDY_DAYS_FIELD];
  const out = {};

  if (Array.isArray(raw)) {
    raw.forEach((field) => {
      const key = String(field || '').trim();
      if (DAY_FIELDS.includes(key)) out[key] = true;
    });
    return out;
  }

  if (raw && typeof raw === 'object') {
    Object.entries(raw).forEach(([field, value]) => {
      const key = String(field || '').trim();
      if (DAY_FIELDS.includes(key) && truthyFlag(value)) out[key] = true;
    });
    return out;
  }

  DAY_FIELDS.forEach((field) => {
    if (truthyFlag(student?.[`${field}SelfStudy`])) out[field] = true;
  });

  return out;
}

export function isSelfStudyDayField(student, field) {
  const key = String(field || '').trim();
  if (!DAY_FIELDS.includes(key)) return false;
  return truthyFlag(selfStudyDaysForStudent(student)[key]);
}

export function nextSelfStudyDays(student, field, enabled) {
  const key = String(field || '').trim();
  const next = { ...selfStudyDaysForStudent(student) };
  if (!DAY_FIELDS.includes(key)) return next;
  if (enabled) next[key] = true;
  else delete next[key];
  return next;
}

export function weekdayForDate(dateStr) {
  const raw = String(dateStr || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return '';
  const date = new Date(`${raw}T00:00:00`);
  if (Number.isNaN(date.getTime())) return '';
  return WEEKDAY_CHARS[date.getDay()] || '';
}

export function dayFieldMatchesDate(student, field, dateStr) {
  const weekday = weekdayForDate(dateStr);
  if (!weekday) return false;
  const value = String(student?.[field] || '').trim();
  return value.startsWith(weekday);
}

export function isSelfStudyScheduledForDate(student, dateStr) {
  if (!student || typeof student !== 'object') return false;
  return DAY_FIELDS.some((field) => (
    dayFieldMatchesDate(student, field, dateStr)
    && isSelfStudyDayField(student, field)
  ));
}
