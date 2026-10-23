const KEY = 'academy.adminSaveOperations.v1';
const DEMO_KEY = 'academy.adminDemo.saveOperations.v1';
const STAGES = { preflight: '저장 준비', video: '영상', record: '숙제·기록', carryover: '결석 이월', test: '시험' };
let records = [], initialized = false, storage = null, storageKey = KEY;
const copy = value => JSON.parse(JSON.stringify(value));

export function recordSaveEvent(history, event) {
  if (!event || !/^[a-zA-Z0-9-]{8,100}$/.test(event.id || '') || !STAGES[event.stage]) return history;
  if (!['start', 'running', 'complete', 'failed', 'success'].includes(event.type)) return history;
  const next = copy(history);
  let record = next.find(item => item.id === event.id);
  if (!record) {
    if (event.type !== 'start') return history;
    record = { id: event.id, sid: String(event.sid || '').slice(0, 128), date: String(event.date || '').slice(0, 10), startedAt: event.at, status: 'running', stages: {} };
    next.unshift(record);
  }
  if (record.status !== 'running') return history;
  record.updatedAt = event.at;
  if (event.type === 'running' || event.type === 'complete') record.stages[event.stage] = event.type;
  if (event.type === 'failed') { record.status = 'failed'; record.stages[event.stage] = 'failed'; }
  if (event.type === 'success') record.status = 'success';
  return next.slice(0, 30);
}

export function initSaveOperations() {
  if (initialized) return;
  initialized = true;
  storageKey = location.pathname.startsWith('/demo/') ? DEMO_KEY : KEY;
  try {
    storage = sessionStorage;
    const saved = JSON.parse(storage.getItem(storageKey) || '[]');
    if (Array.isArray(saved)) records = saved.filter(item => item && typeof item.id === 'string' && item.stages && typeof item.stages === 'object').slice(0, 30)
      .map(item => ({ ...item, status: item.status === 'running' ? 'interrupted' : item.status }));
  } catch { records = []; }
  document.addEventListener('admin:save-operation', event => {
    records = recordSaveEvent(records, event.detail);
    // Store only IDs, stages and timestamps. Never persist homework, notes or drafts.
    try { storage?.setItem(storageKey, JSON.stringify(records)); } catch { /* Saving must survive disabled browser storage. */ }
    document.dispatchEvent(new CustomEvent('admin:save-history'));
  });
}

export function getSaveOperations() { return copy(records); }
export function saveStageLabel(stage) { return STAGES[stage] || stage; }
