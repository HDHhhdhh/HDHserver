function truthyFlag(value) {
  return value === true || value === 'true' || value === 1 || value === '1';
}

function canonicalDate(value) {
  const date = String(value || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return '';
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date ? date : '';
}

export function doneEntriesFromUnarchivedSummary(summary) {
  if (summary?.rowsAvailable !== true || !Array.isArray(summary?.rows)) return null;

  const latestBySid = new Map();
  summary.rows.forEach((row) => {
    const sid = String(row?.sid || '').trim();
    const date = canonicalDate(row?.date);
    const entry = row?.entry;
    if (!sid || !/^\d{4}-\d{2}-\d{2}$/.test(date) || !entry || typeof entry !== 'object') return;
    if (!truthyFlag(entry.done) || truthyFlag(entry.archived)) return;

    const previous = latestBySid.get(sid);
    if (!previous || date > previous[2]) latestBySid.set(sid, [sid, entry, date]);
  });
  return Array.from(latestBySid.values());
}
