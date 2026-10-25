const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const WCHR = '일월화수목금토';
const ACTIVATION_STORAGE_KEY = 'adminMakeupPendingActivationDate';

function normDate(value) {
  const s = String(value || '').slice(0, 10);
  return DATE_RE.test(s) ? s : '';
}

export function makeupHistoryForItem(item, carryover = {}) {
  const key = makeupOriginalAbsenceId(item);
  const events = carryover?.scheduleHistory?.[key];
  if (Array.isArray(events) && events.length) return events;
  const schedule = item?.scheduledMakeup;
  return schedule ? [{ ...schedule, action: 'scheduled', recordedAt: '', legacy: true }] : [];
}

export function makeupChangeCount(item) {
  return (item?.scheduleHistory || []).filter(event => event.action === 'rescheduled').length;
}

export function formatMakeupPlannerLabel(item) {
  const student = item?.student || {};
  const name = baseNameForExport(student, item?.name || item?.sid) || '-';
  const schoolGrade = `${schoolForExport(student)}${gradeNumberForExport(student)}`;
  const course = courseForExport(item?.course).replace(/^미적분/, '미적');
  return `${name}${schoolGrade ? `(${schoolGrade})` : ''} | ${course || '-'} | ${formatMakeupDate(item?.absenceDate)} 결석 | 변경 ${makeupChangeCount(item)}회`;
}

function withMakeupHistory(item, carryover) {
  const events = makeupHistoryForItem(item, carryover);
  return events.length ? { ...item, scheduleHistory: events } : item;
}

function missedScheduleSlots(item, absentByDate, absentSlotsByDate) {
  const date = item.scheduledMakeup?.makeupDate;
  const slots = parseSlotNumbers(absentSlotsByDate?.[date]?.[item.sid]);
  const wholeDay = (absentByDate?.[date] || []).map(String).includes(item.sid);
  return parseSlotNumbers(item.scheduledMakeup?.makeupTimes).filter(slot => wholeDay || slots.includes(slot));
}

function rebookingProjection(carryover, students, absentByDate, absentSlotsByDate) {
  const scheduled = buildScheduledMakeupRows({ carryover, students });
  const claims = new Map();
  const slotsByDate = {};
  const addSlot = (date, sid, slot) => {
    const day = slotsByDate[date] ||= {};
    day[sid] = [...new Set([...(day[sid] || []), slot])];
  };
  const key = (date, sid, slot) => `${date}|${sid}|${slot}`;
  for (const item of scheduled) {
    for (const slot of parseSlotNumbers(item.scheduledMakeup.makeupTimes)) {
      const id = key(item.scheduledMakeup.makeupDate, item.sid, slot);
      claims.set(id, (claims.get(id) || 0) + 1);
      addSlot(item.scheduledMakeup.makeupDate, item.sid, slot);
    }
  }
  const linked = new Set();
  for (const events of Object.values(carryover?.scheduleHistory || {})) {
    if (!Array.isArray(events)) continue;
    for (const event of events) {
      for (const slot of parseSlotNumbers(event.missedSlots)) {
        linked.add(key(event.makeupDate, event.studentId, slot));
        addSlot(event.makeupDate, event.studentId, slot);
      }
    }
  }
  const pending = [];
  for (const item of scheduled) {
    const date = item.scheduledMakeup.makeupDate;
    const missed = missedScheduleSlots(item, absentByDate, absentSlotsByDate)
      .filter(slot => claims.get(key(date, item.sid, slot)) === 1);
    if (!missed.length || date === item.absenceDate) continue;
    missed.forEach(slot => linked.add(key(date, item.sid, slot)));
    pending.push({ ...item, rebooking: true, missedMakeupDate: date });
  }
  return { pending, linked, slotsByDate, scheduled };
}

export function nextLocalDateKey(offsetDays = 1) {
  const d = new Date();
  d.setDate(d.getDate() + Number(offsetDays || 0));
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, '0'),
    String(d.getDate()).padStart(2, '0'),
  ].join('-');
}

export function makeupPendingActivationDate(anchorDate = '', pendingDates = []) {
  const anchor = normDate(anchorDate) || nextLocalDateKey(0);
  const stored = readStoredActivationDate();
  if (stored) return stored;

  const dates = (Array.isArray(pendingDates) ? pendingDates : [])
    .map(normDate)
    .filter(Boolean)
    .sort();
  let start = anchor;
  if (dates.length && !dates.some(date => date >= anchor)) {
    start = dates.filter(date => date <= anchor).pop() || anchor;
  }

  writeStoredActivationDate(start);
  return start;
}

function readStoredActivationDate() {
  try {
    if (typeof localStorage === 'undefined') return '';
    return normDate(localStorage.getItem(ACTIVATION_STORAGE_KEY));
  } catch {
    return '';
  }
}

function writeStoredActivationDate(date) {
  const value = normDate(date);
  if (!value) return;
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(ACTIVATION_STORAGE_KEY, value);
    }
  } catch {}
}

export function studentSchool(stu) {
  return String(
    stu?.school ||
    stu?.schoolName ||
    stu?.highSchool ||
    stu?.middleSchool ||
    stu?.high ||
    stu?.middle ||
    stu?.schoolHigh ||
    stu?.schoolMiddle ||
    stu?.['학교'] ||
    stu?.['고등학교'] ||
    stu?.['중학교'] ||
    ''
  ).trim();
}

export function studentCourse(stu) {
  return [stu?.curriculum || stu?.course || stu?.subject || stu?.className, stu?.subCurriculum]
    .map(v => String(v || '').trim())
    .filter(Boolean)
    .join(' ');
}

function schoolForExport(stu) {
  return studentSchool(stu)
    .replace(/고등학교$/u, '')
    .replace(/중학교$/u, '')
    .replace(/[고중]$/u, '');
}

function gradeNumberForExport(stu) {
  const raw = String(stu?.grade || stu?.gradeLevel || stu?.['학년'] || '').trim();
  const m = raw.match(/\d+/);
  return m ? m[0] : raw;
}

function baseNameForExport(stu, fallbackName = '') {
  return String(stu?.name || fallbackName || '')
    .trim()
    .replace(/\s*[\(\[][^()\[\]]+[\)\]]\s*$/u, '')
    .trim();
}

function chatNameForExport(stu, fallbackName = '') {
  const school = schoolForExport(stu);
  const grade = gradeNumberForExport(stu);
  const name = baseNameForExport(stu, fallbackName);
  return `A ${school}${grade}${school || grade ? ' ' : ''}${name}`.trim();
}

function studentKeyForExport(item) {
  const stu = item?.student || {};
  const school = schoolForExport(stu);
  const grade = gradeNumberForExport(stu);
  const name = baseNameForExport(stu, item?.name || item?.sid);
  return [school, grade, name].filter(Boolean).join('|') || String(item?.sid || '').trim();
}

function courseForExport(course) {
  const text = String(course || '').trim();
  if (!text) return '';
  return text.split(/\s+/)[0] || text;
}

export function formatMakeupDate(dateStr) {
  const date = normDate(dateStr);
  if (!date) return '';
  const [year, monthNum, dayNum] = date.split('-').map(Number);
  const d = new Date(year, monthNum - 1, dayNum);
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const yoil = WCHR[d.getDay()] || '';
  return `${month}/${day}(${yoil})`;
}

export function formatMakeupCopyText(item = {}) {
  const name = String(item?.name || item?.student?.name || item?.sid || '-').trim() || '-';
  const date = normDate(item?.absenceDate);
  const parts = [name];

  if (date) {
    const [year, monthNum, dayNum] = date.split('-').map(Number);
    const d = new Date(year, monthNum - 1, dayNum);
    parts.push(`${monthNum}/${dayNum}`);

    const slot = item?.dateOnly === true ? '' : (parseSlotNumbers(item?.slot)[0] || '');
    if (slot) parts.push(`${WCHR[d.getDay()] || ''}${slot}`);
  }

  parts.push('결석');
  return `${parts.filter(Boolean).join(' ')} >>`;
}

export function parseSlotNumbers(raw) {
  const values = Array.isArray(raw) ? raw : [raw];
  const slots = values.flatMap(value => {
    const matches = String(value ?? '').match(/\d+/g) || [];
    return matches.map(n => parseInt(n, 10));
  }).filter(n => n === 1 || n === 2 || n === 3);
  return Array.from(new Set(slots)).sort((a, b) => a - b);
}

function normalizeSchedule(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const originalAbsenceId = String(raw.originalAbsenceId || raw.original_absence_id || '').trim();
  const studentId = String(raw.studentId || raw.student_id || '').trim();
  const makeupDate = normDate(raw.makeupDate || raw.makeup_date);
  const status = String(raw.status || 'scheduled').trim().toLowerCase();
  if (status !== 'scheduled' || !originalAbsenceId || !studentId || !makeupDate) return null;
  const makeupTimes = parseSlotNumbers(raw.makeupTimes || raw.makeup_times || raw.slots || raw.slot);
  const ownedSlots = parseSlotNumbers(raw.ownedSlots || raw.owned_slots);
  return {
    originalAbsenceId,
    studentId,
    makeupDate,
    makeupTimes: makeupTimes.length ? makeupTimes : [1],
    status,
    createdAt: String(raw.createdAt || raw.created_at || '').trim(),
    updatedAt: String(raw.updatedAt || raw.updated_at || '').trim(),
    createdBy: String(raw.createdBy || raw.created_by || '').trim(),
    ownedExtra: raw.ownedExtra === true || raw.owned_extra === true,
    ownedSlots,
  };
}

function explicitScheduleValue(row) {
  if (!row || typeof row !== 'object') return undefined;
  if (Object.prototype.hasOwnProperty.call(row, 'scheduledMakeup')) return row.scheduledMakeup;
  if (Object.prototype.hasOwnProperty.call(row, 'scheduled_makeup')) return row.scheduled_makeup;
  return undefined;
}

export function makeupOriginalAbsenceId(item) {
  const source = String(item?.source || 'absence').trim() || 'absence';
  const absenceDate = normDate(item?.absenceDate);
  const sid = String(item?.sid || '').trim();
  if (!absenceDate || !sid) return '';
  if (source === 'manual') {
    const manualKey = String(item?.manualKey || '').trim();
    return `manual|${absenceDate}|${manualKey || sid}`;
  }
  const slot = item?.dateOnly ? '' : (parseSlotNumbers(item?.slot)[0] || '');
  return `absence|${absenceDate}|${sid}${slot ? `|${slot}` : ''}`;
}

function dayValues(stu) {
  return Object.keys(stu || {})
    .filter(k => /^day\d+$/.test(k) && stu[k])
    .sort((a, b) => parseInt(a.slice(3), 10) - parseInt(b.slice(3), 10))
    .map(k => String(stu[k]));
}

function regularSlotsForStudent(stu, dateStr) {
  const date = normDate(dateStr);
  if (!date) return [];
  const w = WCHR[new Date(date).getDay()] || '';
  return parseSlotNumbers(dayValues(stu).filter(value => String(value).startsWith(w)));
}

function carriedRowValue(carryover, date, sid, slot) {
  const rows = (carryover?.by_absence || carryover || {})?.[date] || {};
  const legacy = rows[String(sid)];
  if (legacy) return legacy;
  if (slot) return rows[`${sid}|${slot}`];
  return null;
}

function isCarriedRow(row) {
  if (!row) return false;
  if (row === true) return true;
  if (typeof row === 'object') return row.state === 'carried' || row.carried === true;
  return false;
}

function scheduleFromPrecreditNote(row, { originalAbsenceId = '', studentId = '' } = {}) {
  if (!row || typeof row !== 'object' || !isCarriedRow(row)) return null;
  if (
    Object.prototype.hasOwnProperty.call(row, 'scheduledMakeup') ||
    Object.prototype.hasOwnProperty.call(row, 'scheduled_makeup')
  ) return null;

  const matches = Array.from(String(row.note || '').matchAll(
    /직보[ \t]*추가등원[ \t]*예약으로[ \t]*1회[ \t]*차감:[ \t]*(\d{4}-\d{2}-\d{2})[ \t]*([123])타임[^\r\n()[\]]*\(([^()\r\n]+)\)\.[^\r\n]*?실제 이행 완료 표시는 아님\.[ \t]*\[approved-[a-z0-9-]+-\d{8}\]/gu
  ));
  if (matches.length !== 1) return null;
  const match = matches[0];
  const makeupDate = normDate(match?.[1]);
  const makeupSlot = parseSlotNumbers(match?.[2])[0];
  const normalizedStudentId = String(studentId || '').trim();
  const normalizedOriginalAbsenceId = String(originalAbsenceId || '').trim();
  const creditedStudentId = String(match?.[3] || '').trim();
  if (!makeupDate || !makeupSlot || !normalizedStudentId || !normalizedOriginalAbsenceId || !creditedStudentId) return null;

  const [source, absenceDate, absenceStudentId, absenceSlotRaw, ...extraParts] = normalizedOriginalAbsenceId.split('|');
  const absenceSlot = parseSlotNumbers(absenceSlotRaw)[0];
  const notePrefix = String(row.note || '').slice(0, match.index);
  const matchingAbsenceClause = new RegExp(
    `결석[^\\r\\n/]*${absenceDate}[ \\t]*${absenceSlot}[ \\t]*타임[^\\r\\n/]*\\/[ \\t]*$`,
    'u'
  );
  if (
    source !== 'absence' || extraParts.length || absenceStudentId !== normalizedStudentId ||
    !absenceDate || !absenceSlot || !matchingAbsenceClause.test(notePrefix)
  ) return null;
  const ownsAttendance = creditedStudentId === normalizedStudentId;

  const normalized = normalizeSchedule({
    originalAbsenceId: normalizedOriginalAbsenceId,
    studentId: normalizedStudentId,
    makeupDate,
    makeupTimes: [makeupSlot],
    status: 'scheduled',
    createdAt: String(row.createdAt || row.created_at || '').trim(),
    updatedAt: String(row.updatedAt || row.updated_at || '').trim(),
    createdBy: 'direct-credit-note',
    ownedExtra: ownsAttendance,
    ownedSlots: ownsAttendance ? [makeupSlot] : [],
  });
  return normalized ? {
    ...normalized,
    derivedFromPrecreditNote: true,
    creditedStudentId,
  } : null;
}

function isOpenRow(row) {
  if (!row || typeof row !== 'object') return false;
  return row.state === 'open' || row.open === true || row.pending === true;
}

function pushDemand(out, seen, item) {
  const sid = String(item.sid || '').trim();
  const absenceDate = normDate(item.absenceDate);
  const dateOnly = item.dateOnly === true;
  const slot = dateOnly ? '' : (parseSlotNumbers(item.slot)[0] || 1);
  if (!sid || !absenceDate) return;
  const key = `${item.source || 'absence'}|${absenceDate}|${sid}|${dateOnly ? 'date' : slot}|${item.manualKey || ''}`;
  if (seen.has(key)) return;
  seen.add(key);
  out.push({ ...item, sid, absenceDate, slot, dateOnly });
}

function buildAbsenceDemandRows({ studentsBySid, absentByDate = {}, absentSlotsByDate = {}, makeupSlotsByDate = {} }) {
  const out = [];
  const seen = new Set();
  const add = (date, sid, slots) => {
    const stu = studentsBySid.get(String(sid)) || { id: sid, name: sid };
    const finalSlots = parseSlotNumbers(slots);
    (finalSlots.length ? finalSlots : [1]).forEach(slot => pushDemand(out, seen, {
      source: 'absence',
      sid,
      absenceDate: date,
      slot,
      student: stu,
      name: String(stu?.name || sid).trim(),
      school: studentSchool(stu),
      course: studentCourse(stu),
    }));
  };

  if (absentByDate && typeof absentByDate === 'object') {
    for (const [dateRaw, ids] of Object.entries(absentByDate)) {
      const date = normDate(dateRaw);
      if (!date || !Array.isArray(ids)) continue;
      ids.forEach(id => {
        const sid = String(id || '').trim();
        if (!sid) return;
        const stu = studentsBySid.get(sid) || { id: sid, name: sid };
        const slots = parseSlotNumbers(absentSlotsByDate?.[date]?.[sid]);
        add(date, sid, slots.length ? slots : [...regularSlotsForStudent(stu, date), ...(makeupSlotsByDate?.[date]?.[sid] || [])]);
      });
    }
  }

  if (absentSlotsByDate && typeof absentSlotsByDate === 'object') {
    for (const [dateRaw, sidMap] of Object.entries(absentSlotsByDate)) {
      const date = normDate(dateRaw);
      if (!date || !sidMap || typeof sidMap !== 'object') continue;
      for (const [sidRaw, slotsRaw] of Object.entries(sidMap)) {
        const sid = String(sidRaw || '').trim();
        if (!sid) continue;
        add(date, sid, parseSlotNumbers(slotsRaw));
      }
    }
  }

  return out;
}

function buildManualDemandRows({ studentsBySid, manualMakeups = {} }) {
  const out = [];
  const seen = new Set();
  if (!manualMakeups || typeof manualMakeups !== 'object') return out;
  for (const [dateRaw, rows] of Object.entries(manualMakeups)) {
    const date = normDate(dateRaw);
    if (!date || !rows || typeof rows !== 'object') continue;
    for (const [manualKeyRaw, value] of Object.entries(rows)) {
      const manualKey = String(manualKeyRaw || '').trim();
      const row = value && typeof value === 'object' ? value : {};
      if (!manualKey || isCarriedRow(row)) continue;
      const sid = String(row.sid || '').trim();
      if (!sid) continue;
      const stu = studentsBySid.get(sid) || { id: sid, name: sid };
      const regularSlots = regularSlotsForStudent(stu, date);
      const slots = parseSlotNumbers(row.slots ?? row.slot);
      const dateOnly = row.dateOnly === true || row.date_only === true || row.slotless === true;
      if (dateOnly) {
        pushDemand(out, seen, {
          source: 'manual',
          manualKey,
          sid,
          absenceDate: date,
          dateOnly: true,
          student: stu,
          name: String(stu?.name || sid).trim(),
          school: studentSchool(stu),
          course: String(row.course || studentCourse(stu) || '').trim(),
        });
        continue;
      }
      (slots.length ? slots : regularSlots.length ? regularSlots : [1]).forEach(slot => pushDemand(out, seen, {
        source: 'manual',
        manualKey,
        sid,
        absenceDate: date,
        slot,
        student: stu,
        name: String(stu?.name || sid).trim(),
        school: studentSchool(stu),
        course: String(row.course || studentCourse(stu) || '').trim(),
      }));
    }
  }
  return out;
}

export function buildScheduledMakeupRows({ students = [], carryover = {} } = {}) {
  const studentsBySid = new Map((students || []).map(stu => [String(stu?.id), stu]));
  const out = [];
  const seen = new Set();
  const byAbsence = carryover?.by_absence && typeof carryover.by_absence === 'object'
    ? carryover.by_absence
    : {};

  Object.entries(byAbsence).forEach(([dateRaw, rows]) => {
    const absenceDate = normDate(dateRaw);
    if (!absenceDate || !rows || typeof rows !== 'object') return;
    Object.entries(rows).forEach(([rowKeyRaw, value]) => {
      const rowKey = String(rowKeyRaw || '').trim();
      const row = value && typeof value === 'object' ? value : {};
      const [rowSid, rowSlot] = rowKey.split('|');
      if (!rowKey || !rowSid) return;
      const originalAbsenceId = `absence|${absenceDate}|${rowSid}${rowSlot ? `|${rowSlot}` : ''}`;
      const schedule = normalizeSchedule(explicitScheduleValue(row))
        || scheduleFromPrecreditNote(row, { originalAbsenceId, studentId: rowSid });
      if (!schedule) return;
      const sid = String(schedule.studentId || rowSid || '').trim();
      if (!sid) return;
      const slot = parseSlotNumbers(rowSlot || schedule.originalAbsenceId.split('|').pop())[0] || '';
      const stu = studentsBySid.get(sid) || { id: sid, name: sid };
      const item = {
        source: 'absence',
        scheduled: true,
        carryoverKey: rowKey,
        sid,
        absenceDate,
        slot,
        dateOnly: !slot,
        student: stu,
        name: String(stu?.name || sid).trim(),
        school: studentSchool(stu),
        course: studentCourse(stu),
        originalAbsenceId: schedule.originalAbsenceId,
        scheduledMakeup: schedule,
      };
      const key = makeupOriginalAbsenceId(item);
      if (!key || seen.has(key)) return;
      seen.add(key);
      out.push(item);
    });
  });

  const manual = carryover?.manual && typeof carryover.manual === 'object' ? carryover.manual : {};
  Object.entries(manual).forEach(([dateRaw, rows]) => {
    const absenceDate = normDate(dateRaw);
    if (!absenceDate || !rows || typeof rows !== 'object') return;
    Object.entries(rows).forEach(([manualKeyRaw, value]) => {
      const manualKey = String(manualKeyRaw || '').trim();
      const row = value && typeof value === 'object' ? value : {};
      const rawSchedule = explicitScheduleValue(row);
      const sid = String(rawSchedule?.studentId || rawSchedule?.student_id || row.sid || '').trim();
      const schedule = normalizeSchedule(rawSchedule)
        || scheduleFromPrecreditNote(row, {
          originalAbsenceId: `manual|${absenceDate}|${manualKey}`,
          studentId: sid,
        });
      if (!manualKey || !sid || !schedule) return;
      const stu = studentsBySid.get(sid) || { id: sid, name: sid };
      const dateOnly = row.dateOnly === true || row.date_only === true || row.slotless === true;
      const slot = dateOnly ? '' : (parseSlotNumbers(row.slots ?? row.slot)[0] || parseSlotNumbers(schedule.makeupTimes)[0] || 1);
      const item = {
        source: 'manual',
        scheduled: true,
        manualKey,
        sid,
        absenceDate,
        slot,
        dateOnly,
        student: stu,
        name: String(stu?.name || sid).trim(),
        school: studentSchool(stu),
        course: String(row.course || studentCourse(stu) || '').trim(),
        originalAbsenceId: schedule.originalAbsenceId,
        scheduledMakeup: schedule,
      };
      const key = makeupOriginalAbsenceId(item);
      if (!key || seen.has(key)) return;
      seen.add(key);
      out.push(item);
    });
  });

  return out.map(item => withMakeupHistory(item, carryover)).sort((a, b) =>
    String(a.scheduledMakeup?.makeupDate || '').localeCompare(String(b.scheduledMakeup?.makeupDate || '')) ||
    String(a.absenceDate || '').localeCompare(String(b.absenceDate || '')) ||
    String(a.name || '').localeCompare(String(b.name || ''), 'ko', { numeric: true }) ||
    Number(a.slot || 0) - Number(b.slot || 0)
  );
}

export function scheduledMakeupStudentIdsForDate({ students = [], carryover = {}, date = '' } = {}) {
  const dateKey = normDate(date);
  if (!dateKey) return [];
  return Array.from(new Set(
    buildScheduledMakeupRows({ students, carryover })
      .filter(row => normDate(row.scheduledMakeup?.makeupDate) === dateKey)
      .map(row => String(row.sid || '').trim())
      .filter(Boolean)
  ));
}

export function scheduledMakeupSlotsByDate({ students = [], carryover = {} } = {}) {
  const result = {};
  for (const row of buildScheduledMakeupRows({ students, carryover })) {
    if (row.scheduledMakeup?.derivedFromPrecreditNote) continue;
    const date = normDate(row.scheduledMakeup?.makeupDate);
    const sid = String(row.sid || '').trim();
    if (!date || !sid) continue;
    const day = result[date] ||= {};
    day[sid] = [...new Set([...(day[sid] || []), ...parseSlotNumbers(row.scheduledMakeup?.makeupTimes)])];
  }
  return result;
}

export function buildActiveScheduledMakeupRows({ operatingDate = '', absentByDate = {}, absentSlotsByDate = {}, ...input } = {}) {
  const referenceDate = normDate(operatingDate);
  const projection = rebookingProjection(input.carryover || {}, input.students || [], absentByDate, absentSlotsByDate);
  const pendingIds = new Set(projection.pending.map(makeupOriginalAbsenceId));
  const scheduledRows = projection.scheduled.filter(item => !pendingIds.has(makeupOriginalAbsenceId(item)))
    .map(item => missedScheduleSlots(item, absentByDate, absentSlotsByDate).length ? { ...item, needsAbsenceReview: true } : item);
  if (!referenceDate) return scheduledRows;
  return scheduledRows.filter(row => row.needsAbsenceReview || normDate(row.scheduledMakeup?.makeupDate) >= referenceDate);
}

export function buildScheduledMakeupCalendarSummary(rows) {
  const scheduledRows = Array.isArray(rows) ? rows : [];
  const previewRows = scheduledRows.slice(0, 2);
  const total = scheduledRows.length;
  return { previewRows, total, remaining: total - previewRows.length };
}

function scheduledSupplyCounts({ studentsBySid, extra = {}, weekendSlots = {} }) {
  const counts = new Map();
  if (!extra || typeof extra !== 'object') return counts;

  const add = (sid, amount = 1) => {
    counts.set(sid, (counts.get(sid) || 0) + amount);
  };

  Object.entries(extra).sort(([a], [b]) => String(a).localeCompare(String(b))).forEach(([dateRaw, ids]) => {
    const date = normDate(dateRaw);
    if (!date || !Array.isArray(ids)) return;
    ids.map(id => String(id || '').trim()).filter(Boolean).forEach(sid => {
      const stu = studentsBySid.get(sid) || { id: sid };
      const rawSlots = parseSlotNumbers(weekendSlots?.[date]?.[sid]);
      const regular = new Set(regularSlotsForStudent(stu, date));
      const makeupSlots = rawSlots.filter(slot => !regular.has(slot));
      add(sid, makeupSlots.length || rawSlots.length || 1);
    });
  });

  return counts;
}

export function buildPendingMakeups({
  students = [],
  absentByDate = {},
  absentSlotsByDate = {},
  extra = {},
  weekendSlots = {},
  carryover = {},
  manualMakeups = {},
  minAbsenceDate = '',
} = {}) {
  const studentsBySid = new Map((students || []).map(stu => [String(stu?.id), stu]));
  const minDate = normDate(minAbsenceDate);
  const rebooking = rebookingProjection(carryover, students, absentByDate, absentSlotsByDate);
  const demandRows = [
    ...buildAbsenceDemandRows({ studentsBySid, absentByDate, absentSlotsByDate, makeupSlotsByDate: rebooking.slotsByDate }),
    ...buildManualDemandRows({ studentsBySid, manualMakeups }),
  ].sort((a, b) =>
    String(a.absenceDate).localeCompare(String(b.absenceDate)) ||
    String(a.name).localeCompare(String(b.name), 'ko', { numeric: true }) ||
    String(a.sid).localeCompare(String(b.sid), 'ko', { numeric: true }) ||
    Number(a.slot || 0) - Number(b.slot || 0)
  );

  const supply = scheduledSupplyCounts({ studentsBySid, extra, weekendSlots });
  const pending = [];

  demandRows.forEach(item => {
    if (minDate && item.absenceDate < minDate) return;
    if (item.source !== 'manual' && rebooking.linked.has(`${item.absenceDate}|${item.sid}|${item.slot}`)) return;
    if (item.source === 'manual') {
      pending.push(item);
      return;
    }
    const carryoverRow = carriedRowValue(carryover, item.absenceDate, item.sid, item.slot);
    if (carryoverRow?.state === 'self-study') return;
    if (isCarriedRow(carryoverRow)) return;
    if (isOpenRow(carryoverRow)) {
      pending.push(item);
      return;
    }
    const sid = String(item.sid);
    const available = supply.get(sid) || 0;
    if (available > 0) {
      supply.set(sid, available - 1);
      return;
    }
    pending.push(item);
  });

  return [...pending, ...rebooking.pending].map(item => withMakeupHistory(item, carryover));
}

export function buildCarryForwardPendingMakeups(input = {}) {
  return buildPendingMakeups({ ...input, minAbsenceDate: '' });
}

export function countPendingMakeupsBySid(input) {
  const counts = {};
  const rows = buildPendingMakeups({ ...input, minAbsenceDate: '' });
  rows.forEach(item => {
    counts[item.sid] = (counts[item.sid] || 0) + 1;
  });
  return counts;
}

function csvCell(value) {
  const s = String(value ?? '');
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function exportSlotLabel(slot) {
  const n = Number(slot);
  return n === 1 || n === 2 ? `${n}타임` : '';
}

export function buildMakeupExportRows(items = []) {
  const groups = new Map();
  (items || []).forEach(item => {
    const key = studentKeyForExport(item);
    if (!key) return;
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        student: item.student || {},
        name: baseNameForExport(item.student || {}, item.name || item.sid),
        entries: [],
      });
    }
    groups.get(key).entries.push(item);
  });

  return Array.from(groups.values()).map(group => {
    const entries = group.entries
      .slice()
      .sort((a, b) =>
        String(a.absenceDate || '').localeCompare(String(b.absenceDate || '')) ||
        String(a.course || '').localeCompare(String(b.course || ''), 'ko', { numeric: true }) ||
        Number(a.slot || 0) - Number(b.slot || 0)
      );
    const seenDetails = new Set();
    const details = [];
    entries.forEach(item => {
      const date = formatMakeupDate(item.absenceDate);
      const course = courseForExport(item.course);
      const duplicateKey = `${item.absenceDate || ''}|${course}`;
      const needsSlot = !!item.slot && item.dateOnly !== true;
      const slot = needsSlot ? exportSlotLabel(item.slot) : '';
      const detail = [date, course, slot].filter(Boolean).join(' ').trim();
      const detailKey = `${duplicateKey}|${needsSlot ? item.slot || '' : ''}`;
      if (!detail || seenDetails.has(detailKey)) return;
      seenDetails.add(detailKey);
      details.push(detail);
    });

    return {
      time: '',
      chatName: chatNameForExport(group.student, group.name),
      text: `📢 보강 잡아주세요!\n\n${details.join(', ')} 결석분에 대한 보강 날짜 알려주세요~`,
    };
  });
}

export function makeupExportRowsToCsv(rows = []) {
  const columns = ['타임', '대화명', '텍스트'];
  const lines = [columns.map(csvCell).join(',')];
  (rows || []).forEach(row => {
    lines.push([
      row.time || '',
      row.chatName || '',
      row.text || '',
    ].map(csvCell).join(','));
  });
  return `\uFEFF${lines.join('\r\n')}\r\n`;
}
