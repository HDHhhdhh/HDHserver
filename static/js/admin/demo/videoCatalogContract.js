function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}

export function demoVideoRevision(rows) {
  // Synthetic tokens preserve the live 64-hex transport without using live data.
  const text = JSON.stringify(canonical(rows));
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) hash = Math.imul(hash ^ text.charCodeAt(index), 16777619);
  return (hash >>> 0).toString(16).padStart(8, '0').repeat(8);
}

export function validateDemoVideoWrite(current, incoming, rawRevision) {
  if (!Array.isArray(incoming) || incoming.some(row => !row || typeof row !== 'object' || Array.isArray(row) || !String(row.id || '').trim())) {
    return { status: 400, error: 'invalid_video_catalog' };
  }
  const byId = new Map(incoming.map(row => [String(row.id).trim(), row]));
  if (byId.size !== incoming.length) return { status: 400, error: 'invalid_video_catalog' };
  if (current.some(row => !byId.has(String(row.id).trim()) || String(row.mid || '') !== String(byId.get(String(row.id).trim()).mid || ''))) {
    return { status: 409, error: 'video_catalog_identity_change_blocked' };
  }
  const expected = String(rawRevision || '').trim().replace(/^"|"$/g, '');
  if (!expected) return null; // The live compatibility mode also allows old callers.
  if (!/^[0-9a-f]{64}$/i.test(expected)) return { status: 428, error: 'video_catalog_revision_required' };
  if (expected.toLowerCase() !== demoVideoRevision(current)) return { status: 409, error: 'video_catalog_revision_conflict' };
  return null;
}
