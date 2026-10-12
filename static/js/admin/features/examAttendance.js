import { buildPendingMakeups, buildScheduledMakeupRows, parseSlotNumbers } from './makeupPending.js';
import { regularAttendanceDaysForStudent } from '../../shared/selfStudy.js';

const WCHR = '일월화수목금토';
const isMap = value => value && typeof value === 'object' && !Array.isArray(value);
const dateKey = date => [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');

export function buildExamAttendance({ students, attendanceDays, referenceDate, examDate, snapshot = {} }) {
  if (!examDate || !referenceDate) return null;
  if (examDate <= referenceDate) return { total: 0, regular: 0, makeup: 0, pending: 0 };
  const { absentByDate = {}, absentSlotsByDate = {}, extra = {}, weekendSlots = {}, carryover = {} } = snapshot || {};
  const ids = new Set(students.map(student => String(student.id)));
  const start = dateKey(referenceDate);
  const end = dateKey(examDate);
  const inRange = date => date > start && date < end;
  const absent = (date, sid, slot) => (absentByDate[date] || []).map(String).includes(sid)
    || parseSlotNumbers(absentSlotsByDate[date]?.[sid]).includes(slot);
  const regularSlots = (student, date) => {
    const weekday = WCHR[new Date(date + 'T00:00:00').getDay()];
    const labels = regularAttendanceDaysForStudent(student).filter(value => value.startsWith(weekday));
    if (!labels.length) return [];
    const slots = parseSlotNumbers(labels);
    return slots.length ? slots : [1];
  };
  const regularSessions = new Set();
  const weekdays = new Set(attendanceDays.map(value => String(value).trim()[0]));
  const cursor = new Date(referenceDate);
  cursor.setDate(cursor.getDate() + 1);
  while (cursor < examDate) {
    const date = dateKey(cursor);
    if (weekdays.has(WCHR[cursor.getDay()])) {
      for (const student of students) {
        const sid = String(student.id);
        for (const slot of regularSlots(student, date)) {
          if (!absent(date, sid, slot)) regularSessions.add([date, sid, slot].join('|'));
        }
      }
    }
    cursor.setDate(cursor.getDate() + 1);
  }
  const regular = regularSessions.size;

  // A reservation and its extra-attendance reflection are the same date/SID/slot.
  const makeupSlots = new Set();
  const add = (date, sid, slots) => {
    if (!inRange(date) || !ids.has(sid)) return;
    const student = students.find(row => String(row.id) === sid);
    const regularOnDate = regularSlots(student, date);
    for (const slot of slots) {
      if (!regularOnDate.includes(slot) && !absent(date, sid, slot)) makeupSlots.add([date, sid, slot].join('|'));
    }
  };
  const scheduled = buildScheduledMakeupRows({ students, carryover }).filter(row => ids.has(row.sid));
  for (const row of scheduled) {
    add(row.scheduledMakeup.makeupDate, row.sid, row.scheduledMakeup.makeupTimes);
  }
  for (const [date, rawIds] of Object.entries(extra)) {
    if (!inRange(date) || !Array.isArray(rawIds)) continue;
    for (const sid of new Set(rawIds.map(String))) {
      const slots = parseSlotNumbers(weekendSlots[date]?.[sid]);
      const linked = scheduled.filter(row => row.sid === sid && row.scheduledMakeup.makeupDate === date);
      // A linked reservation already supplies the authoritative slots if reflection is incomplete.
      if (slots.length) add(date, sid, slots);
      else if (!linked.length) add(date, sid, [1]);
    }
  }
  const pending = buildPendingMakeups({
    students, absentByDate, absentSlotsByDate, extra, weekendSlots, carryover,
    manualMakeups: carryover.manual || {},
  }).filter(row => ids.has(String(row.sid)) && row.absenceDate < end).length;
  return { total: regular + makeupSlots.size, regular, makeup: makeupSlots.size, pending };
}

export function createExamAttendanceLoader(read, { now = Date.now, ttlMs = 5000 } = {}) {
  let cached = null;
  let loadedAt = 0;
  let pending = null;
  let generation = 0;
  const fresh = () => cached && now() - loadedAt < ttlMs;
  return {
    peek: () => fresh() ? cached : null,
    invalidate() { generation += 1; cached = null; pending = null; },
    load() {
      if (fresh()) return Promise.resolve(cached);
      if (pending) return pending;
      const epoch = generation;
      const request = Promise.all([
        '/api/absent', '/api/extra-attend', '/api/weekend-slots', '/api/makeup-carryover',
      ].map(url => read(url))).then(([absence, extra, weekendSlots, carryover]) => {
        if (![absence, extra, weekendSlots, carryover].every(isMap)) throw new Error('Invalid exam attendance snapshot');
        const absentByDate = absence.by_date || absence.absentByDate || {};
        const absentSlotsByDate = absence.by_slot || {};
        if (![absentByDate, absentSlotsByDate].every(isMap)) throw new Error('Invalid absence snapshot');
        const result = { absentByDate, absentSlotsByDate, extra, weekendSlots, carryover };
        if (epoch === generation) { cached = result; loadedAt = now(); }
        return result;
      }).finally(() => { if (pending === request) pending = null; });
      pending = request;
      return request;
    },
  };
}
