function normalizeIds(value) {
  const list = Array.isArray(value) ? value : [];
  return Array.from(new Set(list.map(item => String(item || '').trim()).filter(Boolean)));
}

export function mergeExtraAttendanceSelection(latestIds, baselineIds, selectedIds) {
  const latest = new Set(normalizeIds(latestIds));
  const baseline = new Set(normalizeIds(baselineIds));
  const selected = new Set(normalizeIds(selectedIds));

  const addedIds = Array.from(selected).filter(sid => !baseline.has(sid));
  const removedIds = Array.from(baseline).filter(sid => !selected.has(sid));

  addedIds.forEach(sid => latest.add(sid));
  removedIds.forEach(sid => latest.delete(sid));

  return {
    selectedIds: Array.from(latest),
    addedIds,
    removedIds,
  };
}

export function legacyExtraAttendanceIds(students, selectedIds) {
  const currentIds = new Set((Array.isArray(students) ? students : [])
    .map(student => String(student?.id || '').trim())
    .filter(Boolean));
  return normalizeIds(selectedIds).filter(sid => !currentIds.has(sid));
}

export function legacyStudentName(sid) {
  const value = String(sid || '').trim();
  return value.replace(/\d+$/u, '').trim() || value;
}
