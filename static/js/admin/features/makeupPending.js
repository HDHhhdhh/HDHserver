const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const WCHR = '일월화수목금토';

function normDate(value) {
  const s = String(value || '').slice(0, 10);
  return DATE_RE.test(s) ? s : '';
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
    stu?.고등학교 ||
    stu?.중학교 ||
    ''
  ).trim();
}

export function studentCourse(stu) {
  return [stu?.curriculum || stu?.course || stu?.subject || stu?.className, stu?.subCurriculum]
    .map(v => String(v || '').trim())
    .filter(Boolean)
    .join(' ');
}

export function formatMakeupDate(dateStr) {
  const date = normDate(dateStr);
  if (!date) return '';
  const d = new Date(date);
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const yoil = WCHR[d.getDay()] || '';
  return `${month}/${day}(${yoil})`;
}

function byStudentMapFromDates(dateMap) {
  const out = new Map();
  if (!dateMap || typeof dateMap !== 'object') return out;

  for (const [dateRaw, ids] of Object.entries(dateMap)) {
    const date = normDate(dateRaw);
    if (!date || !Array.isArray(ids)) continue;
    ids.forEach(id => {
      const sid = String(id || '').trim();
      if (!sid) return;
      if (!out.has(sid)) out.set(sid, []);
      out.get(sid).push(date);
    });
  }

  for (const dates of out.values()) {
    dates.sort();
  }
  return out;
}

export function buildPendingMakeups({ students = [], absentByDate = {}, extra = {} } = {}) {
  const studentsBySid = new Map((students || []).map(stu => [String(stu?.id), stu]));
  const absencesBySid = byStudentMapFromDates(absentByDate);
  const extrasBySid = byStudentMapFromDates(extra);
  const pending = [];

  for (const [sid, absenceDates] of absencesBySid.entries()) {
    const scheduled = (extrasBySid.get(sid) || []).slice();
    let scheduleIndex = 0;

    for (const absenceDate of absenceDates) {
      while (scheduleIndex < scheduled.length && scheduled[scheduleIndex] <= absenceDate) {
        scheduleIndex += 1;
      }

      if (scheduleIndex < scheduled.length) {
        scheduleIndex += 1;
        continue;
      }

      const stu = studentsBySid.get(String(sid)) || { id: sid, name: sid };
      pending.push({
        sid: String(sid),
        absenceDate,
        student: stu,
        name: String(stu?.name || sid).trim(),
        school: studentSchool(stu),
        course: studentCourse(stu),
      });
    }
  }

  pending.sort((a, b) =>
    String(a.absenceDate).localeCompare(String(b.absenceDate)) ||
    String(a.name).localeCompare(String(b.name), 'ko', { numeric: true }) ||
    String(a.sid).localeCompare(String(b.sid), 'ko', { numeric: true })
  );
  return pending;
}

export function countPendingMakeupsBySid(input) {
  const counts = {};
  buildPendingMakeups(input).forEach(item => {
    counts[item.sid] = (counts[item.sid] || 0) + 1;
  });
  return counts;
}
