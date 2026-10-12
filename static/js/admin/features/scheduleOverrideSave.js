function hasEntries(value) {
  return !!value && typeof value === 'object' && Object.keys(value).length > 0;
}

export function splitWeekendPatchByFinalExtra(extraMap = {}, weekendPatch = {}) {
  const beforeExtra = {};
  const afterExtra = {};

  Object.entries(weekendPatch || {}).forEach(([date, mapping]) => {
    if (!mapping || typeof mapping !== 'object') return;
    const selected = new Set((extraMap?.[date] || []).map(String));
    Object.entries(mapping).forEach(([sid, value]) => {
      const target = selected.has(String(sid)) ? beforeExtra : afterExtra;
      target[date] = { ...(target[date] || {}), [sid]: value };
    });
  });

  return { beforeExtra, afterExtra };
}

export async function saveScheduleOverridesFailClosed({
  extraMap,
  weekendPatch,
  saveExtra,
  saveWeekend,
}) {
  const { beforeExtra, afterExtra } = splitWeekendPatchByFinalExtra(extraMap, weekendPatch);
  if (hasEntries(beforeExtra)) await saveWeekend(beforeExtra);
  await saveExtra();
  if (hasEntries(afterExtra)) await saveWeekend(afterExtra);
}
