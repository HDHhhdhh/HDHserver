function truthyFlag(value) {
  return value === true || value === 'true' || value === 1 || value === '1';
}

function canonicalDate(value) {
  const date = String(value || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return '';
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date ? date : '';
}

const MISSING_LEAVE_WARNING_START_DATE = '2026-08-29';

export function doneEntriesFromUnarchivedSummary(summary) {
  if (summary?.rowsAvailable !== true || !Array.isArray(summary?.rows)) return null;

  const latestBySid = new Map();
  summary.rows.forEach((row) => {
    const sid = String(row?.sid || '').trim();
    const date = canonicalDate(row?.date);
    const entry = row?.entry;
    if (!sid || !date || !entry || typeof entry !== 'object') return;
    if (!truthyFlag(entry.done) || truthyFlag(entry.archived)) return;

    const previous = latestBySid.get(sid);
    if (!previous || date > previous[2]) latestBySid.set(sid, [sid, entry, date]);
  });
  return Array.from(latestBySid.values());
}

function warningDates(summary) {
  const dates = [];
  const seen = new Set();
  const append = (value) => {
    const date = canonicalDate(value);
    if (!date || seen.has(date)) return;
    seen.add(date);
    dates.push(date);
  };

  (Array.isArray(summary?.byDate) ? summary.byDate : [])
    .filter(row => Math.max(0, Number(row?.count || 0)) > 0)
    .forEach(row => append(row?.date));
  (Array.isArray(summary?.rows) ? summary.rows : [])
    .forEach(row => append(row?.date));

  return dates.sort((a, b) => b.localeCompare(a));
}

function warningDateTypeText(summary, type) {
  if (Math.max(0, Number(summary?.total || 0)) <= 0) return '';
  const dates = warningDates(summary);
  return dates.length ? `${dates.join(', ')} · ${type}` : '';
}

export function recordCleanupWarningText(summary) {
  if (summary?.rowsAvailable === false) return '';
  return warningDateTypeText(summary, '기록 정리');
}

export function missingLeaveWarningText(summary) {
  if (summary?.rowsAvailable !== true) return '';
  const byDate = (Array.isArray(summary?.byDate) ? summary.byDate : [])
    .filter(row => canonicalDate(row?.date) >= MISSING_LEAVE_WARNING_START_DATE);
  const rows = (Array.isArray(summary?.rows) ? summary.rows : [])
    .filter(row => canonicalDate(row?.date) >= MISSING_LEAVE_WARNING_START_DATE);
  return warningDateTypeText({ ...summary, byDate, rows }, '하원');
}

export function missingLeaveWarningRows(summary, { today = '', excludeDate = '' } = {}) {
  if (summary?.rowsAvailable !== true || !(Number(summary?.total) > 0)) return [];
  const rows = [];
  const seen = new Set();
  for (const row of Array.isArray(summary.rows) ? summary.rows : []) {
    const date = canonicalDate(row?.date);
    const sid = String(row?.sid || '').trim();
    const arriveTime = typeof row?.arriveTime === 'string' ? row.arriveTime.trim() : '';
    const key = JSON.stringify([date, sid]);
    if (!date || date < MISSING_LEAVE_WARNING_START_DATE || !sid || !arriveTime
        || (today && date >= today) || date === excludeDate || seen.has(key)) continue;
    seen.add(key);
    rows.push({ date, sid, arriveTime });
  }
  return rows.sort((a, b) => b.date.localeCompare(a.date) || a.sid.localeCompare(b.sid));
}
