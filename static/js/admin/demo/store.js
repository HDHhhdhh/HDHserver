import { buildInitialDemoData } from './data.js';

export const DEMO_STORAGE_KEY = 'academy.adminDemo.v1';
export const DEMO_SCHEMA_VERSION = 4;

const DEFAULT_DEMO_NOW = '2026-06-17T00:00:00+09:00';

function canUseStorage(storage) {
  if (!storage || typeof storage.getItem !== 'function' || typeof storage.setItem !== 'function') {
    return false;
  }
  try {
    const probeKey = `${DEMO_STORAGE_KEY}.probe`;
    storage.setItem(probeKey, '1');
    storage.removeItem?.(probeKey);
    return true;
  } catch {
    return false;
  }
}

function sessionStore() {
  const storage = globalThis?.sessionStorage;
  return canUseStorage(storage) ? storage : null;
}

function coerceNow(now) {
  if (now instanceof Date && Number.isFinite(now.getTime())) return now;
  const parsed = new Date(now ?? DEFAULT_DEMO_NOW);
  if (Number.isFinite(parsed.getTime())) return parsed;
  return new Date(DEFAULT_DEMO_NOW);
}

export function cloneDemoValue(value) {
  if (typeof structuredClone === 'function') return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

export function isCurrentDemoStore(store) {
  if (!store || typeof store !== 'object' || Array.isArray(store)) return false;
  if (store.schemaVersion !== DEMO_SCHEMA_VERSION) return false;
  if (!Array.isArray(store.students)) return false;
  if (!Array.isArray(store.videos)) return false;
  if (!Array.isArray(store.studentAccounts)) return false;
  if (!store.focusSummaries || typeof store.focusSummaries !== 'object' || Array.isArray(store.focusSummaries)) return false;
  if (!Array.isArray(store.homeworkAssignments)) return false;
  if (!store.homeworkOperations || typeof store.homeworkOperations !== 'object' || Array.isArray(store.homeworkOperations)) return false;
  if (!Array.isArray(store.quickPrinterExports)) return false;
  return store.students.every(student =>
    student
    && typeof student === 'object'
    && String(student.id || '').startsWith('demo-')
  );
}

export function createInitialDemoStore(now = DEFAULT_DEMO_NOW) {
  return buildInitialDemoData(coerceNow(now), DEMO_SCHEMA_VERSION);
}

function normalizedForSave(store) {
  const next = store && typeof store === 'object' ? cloneDemoValue(store) : createInitialDemoStore();
  next.schemaVersion = DEMO_SCHEMA_VERSION;
  return next;
}

export function saveDemoStore(store) {
  const next = normalizedForSave(store);
  const storage = sessionStore();
  if (storage) {
    storage.setItem(DEMO_STORAGE_KEY, JSON.stringify(next));
  }
  return cloneDemoValue(next);
}

export function resetDemoStore(now = DEFAULT_DEMO_NOW) {
  const next = createInitialDemoStore(now);
  const storage = sessionStore();
  if (storage) {
    storage.setItem(DEMO_STORAGE_KEY, JSON.stringify(next));
  }
  return cloneDemoValue(next);
}

export function loadDemoStore(now = DEFAULT_DEMO_NOW) {
  const storage = sessionStore();
  if (!storage) return createInitialDemoStore(now);

  const raw = storage.getItem(DEMO_STORAGE_KEY);
  if (!raw) return resetDemoStore(now);

  try {
    const parsed = JSON.parse(raw);
    if (isCurrentDemoStore(parsed)) return cloneDemoValue(parsed);
  } catch {
  }

  return resetDemoStore(now);
}

export function updateDemoStore(updater, now = DEFAULT_DEMO_NOW) {
  const draft = loadDemoStore(now);
  const result = typeof updater === 'function' ? updater(draft) : draft;
  return saveDemoStore(result || draft);
}

export function replaceDateSidEntry(store, collectionName, date, sid, patch) {
  const next = cloneDemoValue(store || createInitialDemoStore());
  const key = String(collectionName || '');
  const dateKey = String(date || next.demoDate || '');
  const sidKey = String(sid || '');
  if (!key || !dateKey || !sidKey) return next;
  next[key] = next[key] && typeof next[key] === 'object' ? next[key] : {};
  next[key][dateKey] = next[key][dateKey] && typeof next[key][dateKey] === 'object' ? next[key][dateKey] : {};
  const previous = next[key][dateKey][sidKey] && typeof next[key][dateKey][sidKey] === 'object'
    ? next[key][dateKey][sidKey]
    : {};
  next[key][dateKey][sidKey] = { ...previous, ...(patch || {}) };
  return next;
}
