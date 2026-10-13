const WCHR = '일월화수목금토';

function canonicalDate(value) {
  const date = String(value || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return '';
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date ? date : '';
}

function text(value) {
  return String(value || '').trim();
}

function scheduledMakeupStudentIds(carryover, dateKey) {
  const out = new Set();
  const accept = (raw, fallbackSid = '') => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return;
    const sid = text(raw.studentId || raw.student_id || raw.sid || fallbackSid);
    const date = canonicalDate(text(raw.makeupDate || raw.makeup_date).slice(0, 10));
    const status = text(raw.status || 'scheduled').toLowerCase();
    if (sid && date === dateKey && status === 'scheduled') out.add(sid);
  };
  const scanRows = (rows) => {
    if (!rows || typeof rows !== 'object' || Array.isArray(rows)) return;
    Object.entries(rows).forEach(([rowKey, value]) => {
      if (!value || typeof value !== 'object' || Array.isArray(value)) return;
      accept(value.scheduledMakeup || value.scheduled_makeup || value, text(value.sid || rowKey).split('|')[0]);
    });
  };

  if (Array.isArray(carryover)) carryover.forEach(row => accept(row));
  if (!carryover || typeof carryover !== 'object' || Array.isArray(carryover)) return out;
  if (Array.isArray(carryover.schedules)) carryover.schedules.forEach(row => accept(row));

  const sections = [];
  if (carryover.by_absence && typeof carryover.by_absence === 'object') sections.push(carryover.by_absence);
  if (carryover.manual && typeof carryover.manual === 'object') sections.push(carryover.manual);
  if (!Object.prototype.hasOwnProperty.call(carryover, 'by_absence')) sections.push(carryover);
  sections.forEach(section => Object.values(section || {}).forEach(scanRows));
  return out;
}

export function effectiveDemoRosterStudentIds(store, rawDate) {
  const dateKey = canonicalDate(rawDate);
  if (!dateKey) return new Set();
  const weekday = WCHR[new Date(`${dateKey}T00:00:00Z`).getUTCDay()] || '';
  const students = Array.isArray(store?.students) ? store.students : [];
  const extraRows = store?.extraAttend?.[dateKey];
  const extraIds = new Set(
    (Array.isArray(extraRows) ? extraRows : Object.keys(extraRows || {}))
      .map(text)
      .filter(Boolean),
  );
  const makeupIds = scheduledMakeupStudentIds(store?.makeupCarryover || {}, dateKey);
  const absentIds = new Set(
    (Array.isArray(store?.absent?.by_date?.[dateKey]) ? store.absent.by_date[dateKey] : [])
      .map(text)
      .filter(Boolean),
  );
  Object.entries(store?.absent?.by_student || {}).forEach(([sid, date]) => {
    if (canonicalDate(date) === dateKey) absentIds.add(text(sid));
  });

  return new Set(students
    .filter(student => {
      const sid = text(student?.id);
      if (!sid || absentIds.has(sid)) return false;
      const regular = Object.entries(student || {}).some(([key, value]) =>
        /^day\d+$/.test(key) && text(value).startsWith(weekday));
      return regular || extraIds.has(sid) || makeupIds.has(sid);
    })
    .map(student => text(student.id)));
}
