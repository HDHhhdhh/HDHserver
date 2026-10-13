export const VIDEO_CORRECTION_DRAFT_KIND = 'academy-video-catalog-correction';
export const VIDEO_CORRECTION_DRAFT_SCHEMA_VERSION = 1;

function rowsByStableId(rows) {
  const out = new Map();
  (Array.isArray(rows) ? rows : []).forEach(row => {
    const id = String(row?.id ?? '').trim();
    if (id) out.set(id, row);
  });
  return out;
}

function cloneRows(rows) {
  return JSON.parse(JSON.stringify(Array.isArray(rows) ? rows : []));
}

export function protectedVideoIdentityChanges(previousRows, nextRows) {
  const previous = rowsByStableId(previousRows);
  const incoming = rowsByStableId(nextRows);
  const removedIds = [...previous.keys()].filter(id => !incoming.has(id));
  const midChanges = [];
  previous.forEach((oldRow, id) => {
    const nextRow = incoming.get(id);
    if (!nextRow) return;
    const oldMid = String(oldRow?.mid ?? '').trim();
    const newMid = String(nextRow?.mid ?? '').trim();
    if (oldMid !== newMid) midChanges.push({ id, oldMid, newMid });
  });
  return { removedIds, midChanges };
}

export function videoCorrectionSummary(previousRows, nextRows) {
  const previous = rowsByStableId(previousRows);
  const incoming = rowsByStableId(nextRows);
  const protectedChanges = protectedVideoIdentityChanges(previousRows, nextRows);
  const newIds = [...incoming.keys()].filter(id => !previous.has(id));
  const modifiedIds = [];
  previous.forEach((oldRow, id) => {
    const nextRow = incoming.get(id);
    if (nextRow && JSON.stringify(oldRow) !== JSON.stringify(nextRow)) modifiedIds.push(id);
  });
  return { ...protectedChanges, newIds, modifiedIds };
}

export function buildVideoCorrectionDraft(baseVideos, nextVideos, createdAt = new Date().toISOString()) {
  return {
    kind: VIDEO_CORRECTION_DRAFT_KIND,
    schemaVersion: VIDEO_CORRECTION_DRAFT_SCHEMA_VERSION,
    createdAt: String(createdAt),
    baseVideos: cloneRows(baseVideos),
    nextVideos: cloneRows(nextVideos),
  };
}