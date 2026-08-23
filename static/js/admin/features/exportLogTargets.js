function truthy(value) {
  return value === true || value === 'true';
}

export function collectUnarchivedDoneLatestPerStudent(logs = {}) {
  const dates = Object.keys(logs && typeof logs === 'object' ? logs : {}).sort();
  const latestBySid = new Map();

  for (const date of dates) {
    const dayMap = logs?.[date];
    if (!dayMap || typeof dayMap !== 'object') continue;
    for (const [sidRaw, rawEntry] of Object.entries(dayMap)) {
      const sid = String(sidRaw || '').trim();
      const entry = rawEntry && typeof rawEntry === 'object' ? rawEntry : {};
      if (!sid || !truthy(entry.done) || truthy(entry.archived)) continue;
      latestBySid.set(sid, { sid, date, entry });
    }
  }

  return Array.from(latestBySid.values());
}

export function collectUnarchivedLogsForDate(logs = {}, dateRaw = '') {
  const date = String(dateRaw || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(date)) return [];
  const dayMap = logs?.[date];
  if (!dayMap || typeof dayMap !== 'object') return [];

  return Object.entries(dayMap).flatMap(([sidRaw, rawEntry]) => {
    const sid = String(sidRaw || '').trim();
    const entry = rawEntry && typeof rawEntry === 'object' ? rawEntry : {};
    if (!sid || truthy(entry.archived) || !truthy(entry.hwChecked)) return [];
    return [{ sid, date, entry }];
  });
}
