const isMap = value => !!value && typeof value === 'object' && !Array.isArray(value);

function dateKey(value) {
  const date = String(value || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return '';
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date ? date : '';
}

export function patchDemoExtraAttendance(store, body) {
  if (!isMap(body)) return { error: 'invalid JSON body' };
  const delta = Object.hasOwn(body, 'deltas');
  if (delta && ['date', 'dates', 'sids'].some(key => Object.hasOwn(body, key))) return { error: 'mixed extra attendance patch' };
  const rawDates = delta ? body.deltas : (Object.hasOwn(body, 'dates') ? body.dates : { [body.date]: body.sids });
  if (!isMap(rawDates) || !Object.keys(rawDates).length) return { error: 'date patch is required' };
  const current = store.extraAttend || {};
  if (!isMap(current)) return { error: 'extra attendance unavailable' };
  const dates = {};
  for (const [rawDate, value] of Object.entries(rawDates)) {
    const date = dateKey(rawDate);
    if (!date || (delta ? !isMap(value) : !Array.isArray(value))) return { error: 'invalid date or sids' };
    if (current[date] !== undefined && !Array.isArray(current[date])) return { error: 'extra attendance unavailable' };
    if (!delta) {
      if (value.some(sid => sid && typeof sid === 'object')) return { error: 'invalid sid' };
      dates[date] = [...new Set(value.map(sid => String(sid || '').trim()).filter(Boolean))];
      continue;
    }
    let next = [...(current[date] || [])];
    const seen = new Set();
    for (const [rawSid, present] of Object.entries(value)) {
      const sid = String(rawSid || '').trim();
      if (!sid || typeof present !== 'boolean' || seen.has(sid)) return { error: 'invalid SID delta' };
      seen.add(sid);
      if (present && !next.some(item => String(item).trim() === sid)) next.push(sid);
      else if (!present) next = next.filter(item => String(item).trim() !== sid);
    }
    dates[date] = next;
  }
  const changedDates = Object.keys(dates).filter(date => JSON.stringify(current[date] || []) !== JSON.stringify(dates[date])).sort();
  if (changedDates.length) {
    const next = { ...current };
    changedDates.forEach(date => {
      if (dates[date].length) next[date] = dates[date];
      else delete next[date];
    });
    store.extraAttend = next;
  }
  return { dates, changedDates, changed: !!changedDates.length };
}
