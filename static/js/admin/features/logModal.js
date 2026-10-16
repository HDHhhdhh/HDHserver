// /js/admin/features/logModal.js
/* global fetch */

import { $, toast } from '../core/utils.js';
import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import { classifySaveConflict } from '../core/saveConflict.js';
import { initTestModal } from './testModal.js?v=20260907-ilsan-level-r1&whiteRetest=20260928&testSaveReady=20261002&uiPerf=20261002&dragScroll=20261007';
import {
  placeSleepingHomeworkRowsLast,
  previousHomeworkText,
  projectBlankHomeworkCheckCarryover,
} from './homeworkCarryover.js?v=20260914-sleep-last1';

console.log('[logModal] HW-TABLE v6.7 (progress patch mode + SQLite-friendly logs patch)');

let editingLogSid = null;
let editingLogDate = null;
let logModalSnapshot = { notes: '', homeworkTable: [], sleepingHomeworkBooks: [] };
let logModalServerSnapshot = { notes: '', homeworkTable: [], sleepingHomeworkBooks: [] };
const PROGRESS_MANUAL_META_KEY = '__manualProgressMids';
const TEST_ASSIGN_DAILY_ITEMS_KEY = 'testAssignmentDailyTests';
const TEST_ASSIGN_ABSENCE_CARRYOVER_KEY = 'testAssignmentAbsenceCarryover';
const TEST_ASSIGN_ABSENCE_SOURCE_KEY = 'testAssignmentAbsenceSourceDate';
const HOMEWORK_SLEEPING_BOOKS_KEY = 'sleepingHomeworkBooks';
let logOpenSeq = 0;
let logModalReady = true;
let logModalCarriedTestAssignment = null;
let logModalAccessMode = 'full';
let saveAllStudentPopupPromise = null;
let logRecordActionPromise = null;
const canonicalHomeworkFetchCache = new Map();
const canonicalHomeworkFetchEpochs = new Map();
let canonicalHomework = createCanonicalHomeworkState();
let homeworkRemoveSelectionActive = false;
let homeworkReorderActive = false;

function createCanonicalHomeworkState() {
  return {
    mode: 'legacy',
    assignments: [],
    exactLogRows: [],
    removedAssignmentIds: new Set(),
    operationId: null,
    pendingPayload: null,
    error: '',
  };
}

function resetCanonicalHomeworkState(mode = 'legacy') {
  canonicalHomework = createCanonicalHomeworkState();
  canonicalHomework.mode = mode;
  homeworkRemoveSelectionActive = false;
  homeworkReorderActive = false;
}

function createHomeworkOperationId() {
  const randomUuid = globalThis?.crypto?.randomUUID;
  if (typeof randomUuid === 'function') return randomUuid.call(globalThis.crypto);
  return `hw-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function homeworkLocalDateTimeToKst(value) {
  const raw = String(value || '').trim();
  if (!raw) return null;
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) throw new Error('숙제 기한 형식이 올바르지 않습니다.');
  const dueAt = `${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:00+09:00`;
  const parsed = Date.parse(dueAt);
  const roundTrip = Number.isFinite(parsed)
    ? new Date(parsed + (9 * 60 * 60 * 1000)).toISOString().slice(0, 16)
    : '';
  if (roundTrip !== raw) throw new Error('숙제 기한을 확인해 주세요.');
  return dueAt;
}

function homeworkDueAtToLocalInput(value) {
  const parsed = Date.parse(String(value || ''));
  if (!Number.isFinite(parsed)) return '';
  return new Date(parsed + (9 * 60 * 60 * 1000)).toISOString().slice(0, 16);
}

function homeworkEffectiveStatus(assignment, now = new Date()) {
  const status = ['assigned', 'completed', 'cancelled'].includes(String(assignment?.status))
    ? String(assignment.status)
    : 'assigned';
  if (status !== 'assigned') return status;
  const dueAt = Date.parse(String(assignment?.dueAt || ''));
  const nowMs = now instanceof Date ? now.getTime() : Date.parse(String(now || ''));
  return Number.isFinite(dueAt) && Number.isFinite(nowMs) && dueAt <= nowMs ? 'overdue' : 'assigned';
}

function mergeHomeworkLogRow(originalRow, managedFields, assignmentId) {
  const original = originalRow && typeof originalRow === 'object' && !Array.isArray(originalRow) ? originalRow : {};
  const managed = managedFields && typeof managedFields === 'object' && !Array.isArray(managedFields) ? managedFields : {};
  const next = { ...original, ...managed };
  delete next._ph;
  delete next._canonical;
  const id = String(assignmentId || '').trim();
  if (id) next.assignmentId = id;
  else delete next.assignmentId;
  return next;
}

function normalizeHomeworkAssignment(row) {
  const value = row && typeof row === 'object' ? row : {};
  const revision = Number(value.revision);
  const assignment = {
    id: String(value.id || value.assignmentId || '').trim(),
    sourceRowId: String(value.sourceRowId || value.source_row_id || '').trim(),
    title: String(value.title || '').trim(),
    book: String(value.book || '').trim(),
    scope: String(value.scope || '').trim(),
    dueAt: String(value.dueAt || '').trim() || null,
    status: ['assigned', 'completed', 'cancelled'].includes(String(value.status)) ? String(value.status) : 'assigned',
    revision: Number.isInteger(revision) && revision >= 1 ? revision : null,
  };
  assignment.effectiveStatus = homeworkEffectiveStatus(assignment);
  return assignment;
}

function setHomeworkElementText(element, value, { asValue = false } = {}) {
  if (asValue) element.value = String(value ?? '');
  else element.textContent = String(value ?? '');
  return element;
}

function isContextMenuOnlyAccess() {
  return logModalAccessMode === 'all-students-readonly';
}

function pad2(n) { return String(n).padStart(2, '0'); }
function nowHHMM() {
  const d = new Date();
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}
function nowISO() { return new Date().toISOString(); }

/**
 * ✅ PATCH (SQLite/JSON 둘 다 허용)
 * - 서버가 {ok:true}만 줘도 OK
 * - 서버가 {ok:true, entry:{...}}로 최신 entry를 반환해도 그걸 받아서 state에 반영 가능하게 return
 * - 서버가 409(동시 저장 충돌/락)를 주면 경고 + 자동 재시도
 */
async function patchLogEntry(date, sid, entry, clearKeys, options = {}) {
  const body = { date, sid, entry: entry || {} };
  if (Array.isArray(clearKeys) && clearKeys.length) body.__clear = clearKeys;
  if (options.base && typeof options.base === 'object' && Object.keys(options.base).length) {
    body.base = options.base;
  }

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const delays = [900, 1400, 2200];
  let lastErrMsg = null;

  for (let attempt = 0; attempt <= delays.length; attempt++) {
    const res = await fetch('/api/logs/patch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    let data = null;
    try { data = await res.json(); } catch {}

    if (res.status === 409) {
      const conflict = classifySaveConflict(data, '숙제');
      const msg = conflict.message;
      lastErrMsg = msg;

      if (!conflict.retryable) {
        const latestEntry = (data && data.entry && typeof data.entry === 'object') ? data.entry : null;
        if (latestEntry) {
          state.logs = state.logs || {};
          state.logs[String(date)] = state.logs[String(date)] || {};
          state.logs[String(date)][String(sid)] = latestEntry;
        }
        throw new Error(msg);
      }

      try { toast(msg); } catch {}

      if (attempt < delays.length) {
        await sleep(delays[attempt]);
        continue;
      }
      throw new Error(`저장 충돌로 실패(재시도 초과): ${msg}`);
    }

    if (!res.ok || !data?.ok) {
      const msg = data?.error ? `patch 실패: ${data.error}` : `patch 실패 (${res.status})`;
      throw new Error(msg);
    }

    if (options.commitOutcome && typeof options.commitOutcome === 'object') {
      options.commitOutcome.sqlite = data.sqlite === true;
      options.commitOutcome.json = data.json === true;
    }
    const returnedEntry = (data && data.entry && typeof data.entry === 'object') ? data.entry : null;
    return returnedEntry;
  }

  throw new Error(lastErrMsg || 'patch 실패');
}

/**
 * ✅ progress patch
 * - 전체 state.progress 저장 금지
 * - date/sid 1건만 서버에 patch
 * - 409면 자동 재시도
 */
async function patchProgressEntry(date, sid, progressMap) {
  const body = { date, sid, progress: progressMap || {} };

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const delays = [900, 1400, 2200];
  let lastErrMsg = null;

  for (let attempt = 0; attempt <= delays.length; attempt++) {
    const res = await fetch('/api/progress/patch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    let data = null;
    try { data = await res.json(); } catch {}

    if (res.status === 409) {
      const conflict = classifySaveConflict(data, '진도');
      const msg = conflict.message;
      lastErrMsg = msg;

      if (!conflict.retryable) throw new Error(msg);

      try { toast(msg); } catch {}

      if (attempt < delays.length) {
        await sleep(delays[attempt]);
        continue;
      }
      throw new Error(`진도 저장 충돌로 실패(재시도 초과): ${msg}`);
    }

    if (!res.ok || !data?.ok) {
      const msg = data?.error ? `progress patch 실패: ${data.error}` : `progress patch 실패 (${res.status})`;
      throw new Error(msg);
    }

    return (data && typeof data.progress === 'object') ? data.progress : (progressMap || {});
  }

  throw new Error(lastErrMsg || 'progress patch 실패');
}

/**
 * ✅ 모달 열 때 서버에서 해당 1건을 가져오기
 * - 1) /api/logs/entry?date&sid
 * - 2) 없으면 /api/logs fallback
 */
async function fetchLogEntryFromServer(date, sid) {
  const t = String(date);
  const s = String(sid);

  {
    const q = new URLSearchParams({ date: t, sid: s }).toString();
    const res = await fetch(`/api/logs/entry?${q}`, { cache: 'no-store' });

    if (res.ok) {
      let data = null;
      try { data = await res.json(); } catch {}
      if (data?.ok) {
        if (data.entry != null && (typeof data.entry !== 'object' || Array.isArray(data.entry))) {
          throw new Error('logs.entry 응답 형식이 올바르지 않습니다.');
        }
        const entry = (data && data.entry && typeof data.entry === 'object') ? data.entry : {};
        return entry;
      }
    } else if (res.status !== 404) {
      let data = null;
      try { data = await res.json(); } catch {}
      const msg = data?.error ? `logs.entry 실패: ${data.error}` : `logs.entry 실패 (${res.status})`;
      throw new Error(msg);
    }
  }

  {
    const res = await fetch('/api/logs', { cache: 'no-store' });
    if (!res.ok) throw new Error(`logs.get 실패 (${res.status})`);

    let all = null;
    try { all = await res.json(); } catch {}
    if (!all || typeof all !== 'object' || Array.isArray(all) || all.ok === false) {
      throw new Error('logs.get 응답 형식이 올바르지 않습니다.');
    }
    const entry = (all && all[t] && typeof all[t] === 'object' && all[t][s] && typeof all[t][s] === 'object')
      ? all[t][s]
      : {};
    return entry;
  }
}

async function fetchCanonicalHomeworkForLog(date, sid) {
  const query = new URLSearchParams({ date: String(date), sid: String(sid) }).toString();
  const res = await fetch(`/api/admin/student-homework?${query}`, { cache: 'no-store' });
  if (res.status === 404) return { mode: 'legacy', assignments: [], pendingOperation: null };

  let data = null;
  try { data = await res.json(); } catch {}
  if (!res.ok || !data?.ok) {
    const reasons = {
      admin_auth_required: '관리자 인증을 다시 확인해 주세요.',
      academy_network_required: '숙제 상세는 허용된 학원망에서만 조회할 수 있습니다.',
      homework_not_initialized: '서버의 숙제 저장소가 준비되지 않았습니다. 관리자 확인이 필요합니다.',
      homework_unavailable: '서버에서 숙제 상세를 읽지 못했습니다. 다시 불러와 주세요.',
    };
    const reason = reasons[data?.code] || data?.error || data?.message
      || '서버 응답을 확인하지 못했습니다. 다시 불러와 주세요.';
    const message = `숙제 상세 조회 실패 (${res.status}): ${reason}`;
    throw new Error(message);
  }

  const assignments = (Array.isArray(data.assignments) ? data.assignments : [])
    .map(row => normalizeHomeworkAssignment(row));
  return {
    mode: 'canonical',
    assignments,
    pendingOperation: data.pendingOperation && typeof data.pendingOperation === 'object'
      ? data.pendingOperation
      : null,
  };
}

function canonicalHomeworkFetchKey(date, sid) {
  return `${String(date)}::${String(sid)}`;
}

function fetchCanonicalHomeworkForLogCached(date, sid, ttlMs = 2500) {
  const key = canonicalHomeworkFetchKey(date, sid);
  const epochs = canonicalHomeworkFetchEpochs;
  const readEpoch = epochs.get(key) || 0;
  const now = Date.now();
  const hit = canonicalHomeworkFetchCache.get(key);
  if (hit && (hit.pending || (now - hit.ts) < ttlMs)) return hit.promise;

  const pending = fetchCanonicalHomeworkForLog(date, sid);
  const promise = pending.then(value => {
    if ((epochs.get(key) || 0) !== readEpoch) {
      throw new Error('팝업 데이터가 변경되었습니다. 다시 열어 주세요.');
    }
    return value;
  });
  canonicalHomeworkFetchCache.set(key, { ts: now, promise, pending: true });
  promise.then(() => {
    if (canonicalHomeworkFetchCache.get(key)?.promise === promise) {
      canonicalHomeworkFetchCache.set(key, { ts: Date.now(), promise, pending: false });
    }
  }, () => {});
  promise.catch(() => {
    if (canonicalHomeworkFetchCache.get(key)?.promise === promise) {
      canonicalHomeworkFetchCache.delete(key);
    }
  });
  return promise;
}

function invalidateLogModalHydrationCaches(date, sid) {
  const sidText = String(sid);
  const query = new URLSearchParams({ sid: sidText }).toString();
  const sharedCache = window.__studentWorkFetchCache;
  if (sharedCache && typeof sharedCache.delete === 'function') {
    invalidateStudentWorkFetchCache(`/api/logs?${query}`);
    invalidateStudentWorkFetchCache(`/api/progress?${query}`);
  }
  const homeworkKey = canonicalHomeworkFetchKey(date, sidText);
  canonicalHomeworkFetchEpochs.set(homeworkKey, (canonicalHomeworkFetchEpochs.get(homeworkKey) || 0) + 1);
  canonicalHomeworkFetchCache.delete(homeworkKey);
  window.invalidateVideoAssignmentPopupCache?.(date, sidText);
}

async function fetchLatestCarriedTestLogEntry(date, sid) {
  const q = new URLSearchParams({ date: String(date), sid: String(sid) }).toString();
  let res = null;
  try {
    res = await fetch(`/api/logs/entry?${q}`, { cache: 'no-store' });
  } catch (err) {
    const detail = err?.message ? `: ${err.message}` : '';
    throw new Error(`/api/logs/entry 최신 로그 조회 실패${detail}`);
  }

  let data = null;
  try {
    data = await res.json();
  } catch {
    throw new Error(`/api/logs/entry 최신 로그 응답 JSON 파싱 실패 (${res.status})`);
  }

  if (!res.ok || data?.ok !== true) {
    const detail = data?.error ? `: ${data.error}` : ` (${res.status})`;
    throw new Error(`/api/logs/entry 최신 로그 조회 실패${detail}`);
  }

  return (data.entry && typeof data.entry === 'object') ? data.entry : {};
}

function invalidateStudentWorkFetchCache(url) {
  const epochs = window.__studentWorkFetchEpochs || (window.__studentWorkFetchEpochs = new Map());
  epochs.set(url, (epochs.get(url) || 0) + 1);
  window.__studentWorkFetchCache?.delete?.(url);
}

async function fetchJSONCached(url, ttlMs = 2500) {
  const cache = window.__studentWorkFetchCache || (window.__studentWorkFetchCache = new Map());
  const epochs = window.__studentWorkFetchEpochs || (window.__studentWorkFetchEpochs = new Map());
  const readEpoch = epochs.get(url) || 0;
  const now = Date.now();
  const hit = cache.get(url);
  if (hit && (hit.pending || (now - hit.ts) < ttlMs)) return hit.promise;

  const pending = fetch(url, { cache: 'no-store' }).then(async (res) => {
    if (!res.ok) throw new Error(`[logModal] GET ${url} -> ${res.status}`);
    try {
      return await res.json();
    } catch (error) {
      throw new Error(`[logModal] GET ${url} returned invalid JSON: ${error?.message || error}`);
    }
  });
  const promise = pending.then(value => {
    if ((epochs.get(url) || 0) !== readEpoch) {
      throw new Error('팝업 데이터가 변경되었습니다. 다시 열어 주세요.');
    }
    return value;
  });
  cache.set(url, { ts: now, promise, pending: true });
  promise.then(() => {
    if (cache.get(url)?.promise === promise) {
      cache.set(url, { ts: Date.now(), promise, pending: false });
    }
  }, () => {});
  promise.catch(() => {
    if (cache.get(url)?.promise === promise) cache.delete(url);
  });
  return promise;
}

function mergeDateSidMap(target, incoming) {
  if (!incoming || typeof incoming !== 'object') return;
  Object.entries(incoming).forEach(([date, bySid]) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(date))) return;
    if (!bySid || typeof bySid !== 'object') return;

    target[date] = target[date] || {};
    Object.entries(bySid).forEach(([sid, entry]) => {
      if (entry && typeof entry === 'object') {
        target[date][String(sid)] = entry;
      }
    });
  });
}

async function hydrateLogHistoryForSid(sid, isCurrent = () => true) {
  const s = String(sid);
  if (!s) return false;

  try {
    const q = new URLSearchParams({ sid: s }).toString();
    const data = await fetchJSONCached(`/api/logs?${q}`);
    if (!data || typeof data !== 'object' || Array.isArray(data) || data.ok === false) return false;
    if (!isCurrent()) return false;
    state.logs = state.logs || {};
    mergeDateSidMap(state.logs, data);
    window.logs = state.logs;
    return true;
  } catch (e) {
    console.warn('[logModal] hydrateLogHistoryForSid failed:', e);
    return false;
  }
}

async function hydrateProgressHistoryForSid(sid, isCurrent = () => true) {
  const s = String(sid);
  if (!s) return false;

  try {
    const q = new URLSearchParams({ sid: s }).toString();
    const data = await fetchJSONCached(`/api/progress?${q}`);
    if (!data || typeof data !== 'object' || Array.isArray(data) || data.ok === false) return false;
    if (!isCurrent()) return false;
    state.progress = state.progress || {};
    mergeDateSidMap(state.progress, data);
    window.progressData = state.progress;
    return true;
  } catch (e) {
    console.warn('[logModal] hydrateProgressHistoryForSid failed:', e);
    return false;
  }
}

function prefetchLogModalDataForRow(row) {
  const sid = String(row?.dataset?.sid || '').trim();
  const date = String(row?.dataset?.date || getAdminDate()).trim();
  if (!sid || !date) return;
  void Promise.allSettled([
    hydrateLogHistoryForSid(sid),
    hydrateProgressHistoryForSid(sid),
    fetchCanonicalHomeworkForLogCached(date, sid),
  ]);
}

async function hydrateTodayLogFromServer(today, sid, isCurrent = () => true) {
  const t = String(today);
  const s = String(sid);

  try {
    const entry = await fetchLogEntryFromServer(t, s);
    if (!isCurrent()) return { ok: false, entry: {} };
    state.logs = state.logs || {};
    state.logs[t] = state.logs[t] || {};
    state.logs[t][s] = entry;
    return { ok: true, entry };
  } catch (e) {
    console.warn('[logModal] hydrateTodayLogFromServer failed:', e);
    return { ok: false, entry: (state.logs?.[t] || {})[s] || {} };
  }
}

function injectStyles() {
  const old = document.getElementById('logModalStyles');
  if (old) old.remove();

  const s = document.createElement('style');
  s.id = 'logModalStyles';
  s.textContent = `
    #logModal{position:fixed; inset:0; z-index:99999; background:rgba(0,0,0,.45); display:none; align-items:center; justify-content:center}
    #logModal .log-card{
      position:relative; width:760px; max-width:96vw; max-height:82vh; overflow:auto;
      padding:0; border-radius:12px; border:1px solid #243047; background:#111827; color:#e5e7eb;
      box-shadow:0 12px 34px rgba(0,0,0,.34);
    }
    body.dark #logModal .log-card{ background:#0f172a; color:#e5e7eb; border-color:#334155; }



    #logModal label{ display:block; margin:10px 0 8px; font-size:28px; }

    #assistantStudentNotesHost{
      flex:1 1 auto;
      min-height:0;
      overflow:hidden;
    }
    #logModal .assistant-student-notes{
      display:flex !important;
      flex-direction:column !important;
      height:100%;
      min-height:0;
      box-sizing:border-box;
      margin:0 !important;
      padding:16px !important;
      border:1px solid #243047 !important;
      border-radius:12px;
      background:#111827;
      color:#e5e7eb;
    }
    #logModal .assistant-note-thread{
      flex:1 1 auto;
      min-height:180px;
      max-height:none !important;
      overflow:auto;
    }
    #logModal .assistant-note-compose{ flex:0 0 auto; }

    #logModal textarea,
    #logModal input:not([type="range"]){
      width:100%;
      box-sizing:border-box;
      border-radius:10px;
      padding:8px 10px;
      outline:none;
      border:1px solid #cbd5e1;
      background:#ffffff;
      color:#0f172a;
    }
    body.dark #logModal textarea,
    body.dark #logModal input:not([type="range"]){
      border-color:#475569;
      background:#0b1220;
      color:#e5e7eb;
    }
    #logModal #logNotes{
      height:min(48vh, var(--student-log-notes-h, 416px));
      min-height:260px;
      resize:vertical;
      font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',sans-serif;
      font-size:25px;
      line-height:1.35;
    }

    #logModal.student-work-layout .log-card{
      display:flex !important;
      flex-direction:column !important;
      overflow:hidden !important;
    }
    #logModal.student-work-layout .log-card > :not(#assistantStudentNotesHost){
      flex:0 0 auto;
    }
    #logModal.student-work-layout #assistantStudentNotesHost{
      flex:1 1 auto;
      min-height:0;
    }
    #logModal.student-work-layout .notes-label{
      display:flex;
      flex:1 1 auto;
      flex-direction:column;
      min-height:0;
      overflow:hidden;
    }
    #logModal.student-work-layout #logNotes{
      flex:1 1 auto;
      height:auto !important;
      min-height:0 !important;
      overflow:auto;
      resize:none;
    }
    #logProgress{
      display:grid; grid-template-columns:repeat(auto-fill, minmax(82px,1fr));
      gap:8px; margin:8px 0 2px;
    }
    #logProgress .progress-cell{
      display:flex; align-items:center; justify-content:center;
      min-height:44px; padding:8px; border-radius:10px; box-sizing:border-box;
      border:1px solid #e5e7eb; background:#ffffff; color:#0f172a;
      font-size:14px; user-select:none; cursor:pointer; pointer-events:auto; position:relative;
      transition:filter .12s ease, border-color .12s ease;
    }
    body.dark #logProgress .progress-cell{ border-color:#334155; background:#0b1220; color:#e5e7eb; }
    #logProgress .progress-cell:hover{ filter:brightness(1.05); }

    #logProgress .progress-cell[data-state="done"]{ background:#10b98122; border-color:#10b98155; }
    body.dark #logProgress .progress-cell[data-state="done"]{
      background:color-mix(in srgb, #008558ff 18%, transparent); border-color:#0ea56e;
    }
    #logProgress .progress-cell[data-state="interrupted"]{ background:#f59e0b22; border-color:#f59e0b66; }
    body.dark #logProgress .progress-cell[data-state="interrupted"]{
      background:color-mix(in srgb, #fffb00ff 20%, transparent); border-color:#d97706;
    }
    #logProgress .progress-cell[data-state="skip"]{ background:#ef444422; border-color:#ef444466; color:#111; }
    body.dark #logProgress .progress-cell[data-state="skip"]{
      background:color-mix(in srgb, #ff0000ff 20%, transparent); border-color:#b91c1c; color:#fee2e2;
    }

    #hwWrap{ margin-top:6px; }
    #hwBox{
      border:1px solid #e5e7eb;
      border-radius:12px;
      overflow:hidden;
      background:#fff;
    }
    body.dark #hwBox{ border-color:#334155; background:#0b1220; }

    .hwHeader{
      padding:10px 10px;
      background:#f8fafc;
      border-bottom:1px solid #e5e7eb;
    }
    body.dark .hwHeader{
      background:#0b1220;
      border-bottom-color:#334155;
    }

    .hwHeaderTop, .hwHeaderBot{
      display:grid;
      gap:8px 12px;
      align-items:start;
    }
    .hwHeaderTop{ grid-template-columns: 1.1fr 1fr; }
    .hwHeaderBot{ grid-template-columns: 1fr 1fr; margin-top:8px; }

    .hwHeader .h{
      font-size:12px;
      color:#64748b;
      font-weight:900;
      white-space:nowrap;
    }
    body.dark .hwHeader .h{ color:#94a3b8; }
    .hwHeader .h-del{ text-align:right; opacity:.65; }

    #hwBody{
      padding:10px 10px;
      display:flex;
      flex-direction:column;
      gap:12px;
    }
    #hwBody.is-hydrating :is(.hwItem,input,select,button){
      animation:none !important;
      transition:none !important;
    }

    .hwItem{ display:flex; flex-direction:column; gap:8px; }
    .hwItem.is-sleeping{ background:#f3f4f6; color:#64748b; }
    .hwItem.is-sleeping input:disabled,
    .hwItem.is-sleeping select:disabled{ background:#e9edf2; color:#7c8796; opacity:1; }
    .hw-book-input-row{ display:flex; align-items:center; gap:6px; min-width:0; }
    .hw-book-input-row > .hwBook{ flex:1 1 auto; min-width:0; }
    .hw-book-sleep-toggle{
      flex:0 0 auto;
      min-width:36px;
      height:24px;
      padding:0 7px;
      border:1px solid #cbd5e1;
      border-radius:999px;
      background:#fff;
      color:#64748b;
      font-size:10px;
      font-weight:800;
      line-height:1;
      cursor:pointer;
    }
    .hw-book-sleep-toggle[aria-pressed="true"]{ border-color:#9ca3af; background:#e5e7eb; color:#374151; }
    .hw-book-sleep-toggle:hover:not(:disabled),
    .hw-book-sleep-toggle:focus-visible{ border-color:#64748b; color:#334155; }
    .hw-book-sleep-toggle:disabled{ opacity:.45; cursor:default; }
    body.dark .hwItem.is-sleeping{ background:#1f2937; color:#94a3b8; }
    body.dark .hwItem.is-sleeping input:disabled,
    body.dark .hwItem.is-sleeping select:disabled{ background:#273244; color:#a7b1c2; }
    body.dark .hw-book-sleep-toggle{ border-color:#475569; background:#111827; color:#cbd5e1; }
    body.dark .hw-book-sleep-toggle[aria-pressed="true"]{ border-color:#64748b; background:#334155; color:#f1f5f9; }
    .hw-order-row{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      min-height:24px;
      color:#64748b;
      font-size:11px;
      font-weight:800;
    }
    .hw-order-row[hidden]{ display:none !important; }
    .hw-order-controls{ display:inline-flex; align-items:center; gap:4px; }
    .hw-order-btn{
      width:26px;
      min-width:26px;
      height:24px;
      min-height:24px;
      padding:0;
      border:1px solid #cbd5e1;
      border-radius:6px;
      background:#fff;
      color:#475569;
      font-size:14px;
      font-weight:900;
      line-height:1;
      cursor:pointer;
    }
    .hw-order-btn:hover,.hw-order-btn:focus-visible{ border-color:#60a5fa; color:#1d4ed8; }
    .hw-order-btn:disabled{ opacity:.32; cursor:default; }
    #hwBody.is-reordering .hwItem{ outline:1px solid #bfdbfe; outline-offset:1px; }
    body.dark .hw-order-row{ color:#94a3b8; }
    body.dark .hw-order-btn{ border-color:#475569; background:#1f2937; color:#e5e7eb; }
    body.dark #hwBody.is-reordering .hwItem{ outline-color:#475569; }

    .hwTop{
      display:grid;
      grid-template-columns: 1.1fr 1fr;
      gap:8px 12px;
      align-items:start;
    }
    .hwBot{
      display:grid;
      grid-template-columns: 1fr 1fr;
      gap:8px 12px;
      align-items:start;
    }

    .hwDelCell{
      display:flex;
      justify-content:flex-end;
      align-self:start;
      padding-top:2px;
    }

    #hwBody input{ height:36px; border-radius:10px; padding:7px 10px; box-sizing:border-box; }
    #hwBody input::placeholder{ color:#94a3b8; }
    body.dark #hwBody input::placeholder{ color:#64748b; }

    .thisCell{
      display:grid;
      grid-template-columns: 1fr 210px;
      gap:10px;
      align-items:start;
      min-width:0;
    }
    .thisCell .thisInputWrap{ min-width:0; }
    .thisCell .thisInputWrap input{ min-width:0; }

    .pctWrap{
      position:relative;
      padding-top:16px;
      min-width:0;
    }

    .pctBubble{
      position:absolute;
      top:0;
      left:0;
      transform:translateX(-50%);
      padding:2px 7px;
      border-radius:999px;
      font-size:12px;
      font-weight:900;
      background:#ffffff;
      border:1px solid #e5e7eb;
      color:#0f172a;
      pointer-events:none;
      white-space:nowrap;
    }
    body.dark .pctBubble{
      background:#0f172a;
      border-color:#334155;
      color:#e5e7eb;
    }
    .pctBubble.is-ph{ opacity:.55; font-weight:800; }

    .hwPctRange{
      width:100%;
      height:46px; padding:0; border:0; outline:none;
      background:transparent;
      cursor:grab;
      -webkit-appearance:none;
      appearance:none;
      touch-action:none;
    }
    .hwPctRange:active{ cursor:grabbing; }

    .hwPctRange::-webkit-slider-runnable-track{
      height:14px;
      border-radius:999px;
      background:#e5e7eb;
    }
    body.dark .hwPctRange::-webkit-slider-runnable-track{ background:#334155; }
    .hwPctRange::-webkit-slider-thumb{
      -webkit-appearance:none;
      width:30px; height:30px;
      border-radius:50%;
      background:#0f172a;
      border:2px solid #fff;
      margin-top:-8px;
    }
    body.dark .hwPctRange::-webkit-slider-thumb{
      background:#e5e7eb;
      border-color:#0b1220;
    }

    .hwPctRange::-moz-range-track{
      height:14px; border-radius:999px; background:#e5e7eb;
    }
    body.dark .hwPctRange::-moz-range-track{ background:#334155; }
    .hwPctRange::-moz-range-thumb{
      width:30px; height:30px; border-radius:50%;
      background:#0f172a; border:2px solid #fff;
    }

    .hw-actions{ display:flex; justify-content:flex-end; gap:8px; margin-top:8px; }
    .hw-actions button{
      height:34px; padding:0 10px; border-radius:10px;
      border:1px solid #e5e7eb; background:#f8fafc; color:#0f172a; cursor:pointer;
      font-weight:900;
    }
    body.dark .hw-actions button{ border-color:#334155; background:#1f2937; color:#e5e7eb; }

    .hw-del-btn{
      height:34px; width:34px; border-radius:10px;
      border:1px solid #e5e7eb; background:#fff; cursor:pointer;
    }
    body.dark .hw-del-btn{ border-color:#334155; background:#0b1220; color:#e5e7eb; }

    #logModal .actions{ display:flex; gap:12px; justify-content:flex-end; margin:0; flex-wrap:wrap; }
    #logModal .actions button{
      height:54px; min-width:96px; padding:0 18px; border-radius:14px; border:1px solid #e5e7eb; background:#f8fafc; color:#0f172a; cursor:pointer;
      font-size:var(--assistant-note-body-font-size, 26px); font-weight:900; line-height:1; white-space:nowrap;
    }
    #logModal .actions #logCompleteBtn{ min-width:180px; }
    body.dark #logModal .actions button{ border-color:#334155; background:#1f2937; color:#e5e7eb; }
    #adminSchoolTip.student-work-layout > :not(.student-tooltip-homework){ flex:0 0 auto; }
    #adminSchoolTip .student-tooltip-homework{
      flex:1 1 auto;
      min-height:0;
      display:flex;
      flex-direction:column;
      overflow:hidden;
      margin-top:6px;
      padding-top:6px;
      border-top:1px solid rgba(255,255,255,.16);
    }
    #adminSchoolTip .student-tooltip-homework-heading{
      flex:0 0 auto;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:4px;
      margin-bottom:4px;
    }
    #adminSchoolTip .student-tooltip-homework-heading h3{ margin:0; font-size:13px; }
    #adminSchoolTip .student-tooltip-homework-actions{
      min-width:0;
      display:flex;
      align-items:center;
      justify-content:flex-end;
      gap:3px;
    }
    #adminSchoolTip .student-tooltip-homework-actions button{
      width:auto !important;
      min-width:0 !important;
      height:20px !important;
      min-height:20px !important;
      padding:0 5px;
      border:1px solid #475569;
      border-radius:5px;
      background:#1f2937;
      color:#f8fafc;
      font-size:9px;
      font-weight:900;
      line-height:1;
      white-space:nowrap;
      cursor:pointer;
    }
    #adminSchoolTip .student-tooltip-homework-actions #logCompleteBtn{
      border-color:#34d399;
      background:#064e3b;
      color:#d1fae5;
    }
    #adminSchoolTip .student-tooltip-homework-actions button:disabled{ opacity:.5; cursor:default; }
    #adminSchoolTip .student-tooltip-homework-host{
      flex:1 1 auto;
      min-height:0;
      overflow-x:hidden;
      overflow-y:auto;
      overscroll-behavior:contain;
      scrollbar-gutter:stable;
      padding-right:2px;
    }
    #adminSchoolTip .student-tooltip-homework-loading{ margin:0; opacity:.72; font-size:11px; }
    #adminSchoolTip #hwWrap{ margin:0; color:#e5e7eb; }
    #adminSchoolTip #hwBox{ border-color:#334155; border-radius:6px; background:#0b1220; overflow:visible; }
    #adminSchoolTip .hwHeader{ display:none; }
    #adminSchoolTip #hwBody{ padding:4px; gap:4px; }
    #adminSchoolTip .hwItem{
      gap:4px;
      padding:4px;
      border:1px solid #334155;
      border-radius:6px;
      background:#111827;
    }
    #adminSchoolTip .hwTop,
    #adminSchoolTip .hwBot{
      display:flex;
      flex-direction:column;
      gap:3px;
    }
    #adminSchoolTip .thisCell{ grid-template-columns:1fr; gap:3px; }
    #adminSchoolTip :is(.hw-book,.hw-this,.hw-cmt,.hw-next)::before{
      display:block;
      margin:0 0 1px;
      color:#94a3b8;
      font-size:9px;
      font-weight:900;
      line-height:1.1;
    }
    #adminSchoolTip .hw-book::before{ content:'교재'; }
    #adminSchoolTip .hw-this::before{ content:'이번 숙제 / 진행률'; }
    #adminSchoolTip .hw-cmt::before{ content:'코멘트'; }
    #adminSchoolTip .hw-next::before{ content:'다음 숙제'; }
    #adminSchoolTip #hwBody input:not([type="range"]){
      width:100%;
      height:26px !important;
      min-height:26px !important;
      box-sizing:border-box;
      padding:2px 6px;
      border:1px solid #475569;
      border-radius:4px;
      background:#0b1220;
      color:#f8fafc;
      font-size:11px;
    }
    #adminSchoolTip .hwCanonical{ padding:6px; border-radius:6px; }
    #adminSchoolTip .hwCanonicalGrid{
      min-width:0;
      display:grid;
      grid-template-columns:repeat(2,minmax(0,1fr));
      gap:5px 6px;
    }
    #adminSchoolTip .hwCanonicalField{
      min-width:0;
      display:grid;
      gap:3px;
    }
    #adminSchoolTip .hwCanonicalLabel{ font-size:10px; }
    #adminSchoolTip .hwCanonical :where(input,select){
      height:26px !important;
      min-height:26px !important;
      padding-block:2px;
    }
    #adminSchoolTip .hwCanonicalMeta{
      display:flex;
      flex-wrap:wrap;
      align-items:center;
      gap:4px;
      margin-top:4px;
      font-size:10px;
    }
    #adminSchoolTip .pctWrap{ padding-top:7px; }
    #adminSchoolTip .pctBubble{ max-width:100%; box-sizing:border-box; padding:1px 4px; font-size:10px; }
    #adminSchoolTip .hwPctRange{
      height:20px !important;
      min-height:20px !important;
    }
    #adminSchoolTip .hwPctRange::-webkit-slider-runnable-track{ height:6px; }
    #adminSchoolTip .hwPctRange::-webkit-slider-thumb{
      width:16px;
      height:16px;
      margin-top:-5px;
    }
    #adminSchoolTip .hwPctRange::-moz-range-track{ height:6px; }
    #adminSchoolTip .hwPctRange::-moz-range-thumb{ width:16px; height:16px; }
    #adminSchoolTip .hwDelCell{ width:100%; padding:0; justify-content:flex-end; }
    #adminSchoolTip .hwBot > .hwDelCell{ display:none; }
    #adminSchoolTip .hw-del-btn{
      width:18px !important;
      min-width:18px !important;
      height:18px !important;
      min-height:18px !important;
      padding:0;
      border-color:#475569;
      border-radius:5px;
      background:#1f2937;
      color:#e5e7eb;
      font-size:10px;
      line-height:1;
    }
    #adminSchoolTip .hw-actions{ display:none !important; }
    #adminSchoolTip .hw-actions button{
      min-width:0;
      height:20px;
      padding:0 6px;
      border-color:#475569;
      background:#1f2937;
      color:#f8fafc;
      font-size:9px;
    }
    #logModal [hidden]{ display:none !important; }
    #logModal[data-access-mode="all-students-readonly"] :where(textarea, input:disabled){ cursor:default; }
    #logModal[data-access-mode="all-students-readonly"] #logProgress .progress-cell{ cursor:context-menu; }
    #logModal[data-access-mode="all-students-readonly"] #logNotes{
      resize:none;
      background:#f8fafc;
      border-style:dashed;
      word-break:keep-all;
      overflow-wrap:break-word;
    }
    body.dark #logModal[data-access-mode="all-students-readonly"] #logNotes{ background:#111827; }
    #logModal[data-access-mode="all-students-readonly"] .hwPctRange:disabled{
      opacity:.58;
      filter:grayscale(1);
      cursor:default;
    }
    #logModal[data-access-mode="all-students-readonly"] .hwPctRange:disabled::-webkit-slider-thumb{
      background:#94a3b8;
    }
    #logModal[data-access-mode="all-students-readonly"] .hwPctRange:disabled::-moz-range-thumb{
      background:#94a3b8;
    }

    @media (max-width:520px){
      #logModal{ align-items:stretch; }
      #logModal .log-card{
        width:100%; max-width:100vw; max-height:100dvh;
        padding:0; border-radius:0;
      }
      #logModal #logNotes{
        height:40vh; min-height:220px;
        font-size:17px; line-height:1.45;
      }
      #logProgress{ grid-template-columns:repeat(3,minmax(0,1fr)); }
      .hwHeaderTop, .hwTop{ grid-template-columns:minmax(0,1fr) minmax(0,1fr) 36px; }
      .hwHeaderBot, .hwBot{ grid-template-columns:minmax(0,1fr) minmax(0,1fr) 36px; }
      .thisCell{ grid-template-columns:1fr; }
    }
  `;
  document.head.appendChild(s);
}

function modalTemplateHTML() {
  return `
      <div id="logModal" aria-label="학생 조교 메모 팝업">
        <div class="log-card">
          <div id="assistantStudentNotesHost" class="assistant-student-notes-host"></div>

          <div id="logLegacyWorkspace" hidden aria-hidden="true">
            <textarea id="logNotes" rows="1" tabindex="-1"></textarea>
            <div id="logProgress"></div>
            <div id="hwWrap">
              <div id="hwBox">
                <div class="hwHeader" aria-label="숙제 헤더">
                  <div class="hwHeaderTop">
                    <div class="h">교재</div>
                    <div class="h">이번 숙제 / 진행률</div>

                  </div>
                  <div class="hwHeaderBot">
                    <div class="h">코멘트</div>
                    <div class="h">다음 숙제</div>

                  </div>
                </div>
                <div id="hwBody" aria-label="숙제 목록"></div>
              </div>

              <div class="hw-actions">
                <button type="button" id="logCompleteBtn">숙제 검사 완료</button>
                <button type="button" id="hwAddRow">+ 추가</button>
                <button type="button" id="hwReorderRows" aria-pressed="false">↕ 순서</button>
                <button type="button" id="hwRemoveRow">- 제거</button>
                <button type="button" id="logSave">저장</button>
              </div>
            </div>
          </div>
        </div>
      </div>`;
}

function ensureModal() {
  document.getElementById('logModal')?.remove();
  injectStyles();
  document.body.insertAdjacentHTML('beforeend', modalTemplateHTML());
}

function nextRegularAttendanceDate(student) {
  const dayFields = ['day1', 'day2', 'day3', 'day4', 'day5'];
  const truthyFlag = value => value === true || value === 'true' || value === 1 || value === '1';
  const rawSelfStudyDays = student?.selfStudyDays;
  const selfStudyDays = new Set();
  if (Array.isArray(rawSelfStudyDays)) {
    rawSelfStudyDays.forEach((field) => {
      if (dayFields.includes(String(field || '').trim())) selfStudyDays.add(String(field || '').trim());
    });
  } else if (rawSelfStudyDays && typeof rawSelfStudyDays === 'object') {
    Object.entries(rawSelfStudyDays).forEach(([field, value]) => {
      if (dayFields.includes(field) && truthyFlag(value)) selfStudyDays.add(field);
    });
  } else {
    dayFields.forEach((field) => {
      if (truthyFlag(student?.[`${field}SelfStudy`])) selfStudyDays.add(field);
    });
  }
  const days = dayFields
    .filter(field => !selfStudyDays.has(field))
    .map(field => String(student?.[field] || '').trim())
    .filter(Boolean)
    .slice(0, 4);
  if (!days.length) return '';
  const weekdayChars = '일월화수목금토';
  const now = new Date();
  const pad = value => String(value).padStart(2, '0');
  for (let offset = 1; offset <= 7; offset += 1) {
    const candidate = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset);
    const weekday = weekdayChars[candidate.getDay()];
    if (!days.some(value => String(value || '').includes(weekday))) continue;
    return `${candidate.getFullYear()}-${pad(candidate.getMonth() + 1)}-${pad(candidate.getDate())}`;
  }
  return '';
}

function mountAssistantThread(student) {
  const host = $('assistantStudentNotesHost');
  if (!host || !student) return;
  const renderTemplate = globalThis.assistantStudentNotesTemplate;
  if (typeof renderTemplate !== 'function') return;
  host.innerHTML = renderTemplate({
    studentId: String(student.id || ''),
    nextReminderDate: nextRegularAttendanceDate(student),
    existingReadOnly: isContextMenuOnlyAccess(),
  });
  const root = host.querySelector('#assistantStudentNotes');
  if (!root) return;
  document.dispatchEvent(new CustomEvent('admin:assistant-notes-mount', {
    detail: { root, studentId: String(student.id || '') },
  }));
}

function parkHomeworkWorkspace() {
  resetHomeworkInteractionModes();
  const workspace = $('logLegacyWorkspace');
  const homework = $('hwWrap');
  const actions = homework?.querySelector('.hw-actions');
  if (actions) {
    actions.hidden = false;
    const addRow = $('hwAddRow');
    const reorderRows = $('hwReorderRows');
    const removeRow = $('hwRemoveRow');
    const complete = $('logCompleteBtn');
    const save = $('logSave');
    if (complete) {
      complete.textContent = '숙제 검사 완료';
      actions.append(complete);
    }
    if (addRow) {
      addRow.textContent = '+ 추가';
      actions.append(addRow);
    }
    if (reorderRows) {
      reorderRows.textContent = '↕ 순서';
      actions.append(reorderRows);
    }
    if (removeRow) {
      removeRow.textContent = '- 제거';
      actions.append(removeRow);
    }
    if (save) {
      save.hidden = isContextMenuOnlyAccess();
      actions.append(save);
    }
  }
  if (workspace && homework && homework.parentElement !== workspace) workspace.appendChild(homework);
}

function mountHomeworkInTooltip() {
  resetHomeworkInteractionModes();
  const host = $('tooltipHomeworkHost');
  const actionHost = $('tooltipHomeworkActions');
  const homework = $('hwWrap');
  if (!host || !homework) return false;
  host.replaceChildren(homework);
  const nativeActions = homework.querySelector('.hw-actions');
  if (nativeActions) nativeActions.hidden = true;
  if (actionHost) {
    const complete = $('logCompleteBtn');
    const addRow = $('hwAddRow');
    const reorderRows = $('hwReorderRows');
    const removeRow = $('hwRemoveRow');
    const save = $('logSave');
    actionHost.replaceChildren();
    if (complete) {
      complete.textContent = '숙검 완료';
      actionHost.append(complete);
    }
    if (addRow) {
      addRow.textContent = '교재 추가';
      actionHost.append(addRow);
    }
    if (reorderRows) {
      reorderRows.textContent = '교재 순서';
      actionHost.append(reorderRows);
    }
    if (removeRow) {
      removeRow.textContent = '교재 제거';
      actionHost.append(removeRow);
    }
    if (save) save.hidden = true;
  }
  return true;
}

function shouldSkipForLow(stu, v) {
  if (!stu || stu.level !== '하') return false;
  const ex = v && v.exNum;
  if (!ex || typeof ex !== 'object') return false;
  return Number(ex['하']) === 0;
}

async function fetchWatchForSid(sid, date = '') {
  const key = String(sid || '').trim();
  if (!key) return {};
  try {
    const params = new URLSearchParams({ sid: key });
    const dateKey = String(date || '').trim();
    if (dateKey) params.set('date', dateKey);
    const payload = await fetch(`/api/watch/latest?${params.toString()}`, { cache: 'no-store' }).then(r => r.json());
    return (payload && typeof payload.watch === 'object') ? payload.watch : {};
  } catch {
    return {};
  }
}

/* 숙제 helpers */
function escapeAttr(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function isQuestionPlaceholder(s) {
  const text = String(s ?? '').replace(/\s+/g, '');
  return text.length >= 2 && /^[?]+$/.test(text);
}

function looksCorruptedPlaceholderText(s) {
  const text = String(s ?? '').trim();
  if ((text.match(/\?/g) || []).length < 2) return false;
  return !/[A-Za-z가-힣一-龥]/.test(text);
}

function cleanHwText(s) {
  const text = String(s ?? '').trim();
  return (isQuestionPlaceholder(text) || looksCorruptedPlaceholderText(text)) ? '' : text;
}

function homeworkBookKey(book) {
  return cleanHwText(book).replace(/\s+/g, '').toLocaleLowerCase('ko-KR');
}

function normalizeSleepingHomeworkBooks(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const books = [];
  value.forEach(raw => {
    const book = cleanHwText(raw);
    const key = homeworkBookKey(book);
    if (!book || !key || seen.has(key)) return;
    seen.add(key);
    books.push(book);
  });
  return books;
}

function sameSleepingHomeworkBooks(a, b) {
  return JSON.stringify(normalizeSleepingHomeworkBooks(a))
    === JSON.stringify(normalizeSleepingHomeworkBooks(b));
}

function entryHasSleepingHomeworkBooks(entry) {
  return Boolean(entry && typeof entry === 'object'
    && Object.prototype.hasOwnProperty.call(entry, HOMEWORK_SLEEPING_BOOKS_KEY));
}

function resolveSleepingHomeworkBooks({ logEntry, dates, today, sid }) {
  if (entryHasSleepingHomeworkBooks(logEntry)) {
    return normalizeSleepingHomeworkBooks(logEntry[HOMEWORK_SLEEPING_BOOKS_KEY]);
  }
  for (let i = dates.length - 1; i >= 0; i--) {
    const date = dates[i];
    if (date >= today) continue;
    const previous = (state.logs?.[date] || {})[sid];
    if (!entryHasSleepingHomeworkBooks(previous)) continue;
    return normalizeSleepingHomeworkBooks(previous[HOMEWORK_SLEEPING_BOOKS_KEY]);
  }
  return [];
}

function normHwRows(x) {
  if (!Array.isArray(x)) return [];
  return x.map(r => ({
    ...((r && typeof r === 'object' && !Array.isArray(r)) ? r : {}),
    book: cleanHwText(r?.book),
    this: cleanHwText(r?.this),
    pct: (r?.pct === '' || r?.pct == null) ? '' : String(r.pct).trim(),
    comment: cleanHwText(r?.comment),
    next: cleanHwText(r?.next),
    _deleted: !!(r?._deleted || r?._del || r?.deleted),
  }));
}

function activeHwRows(x) {
  return normHwRows(x).filter(r => !r._deleted);
}

function entryHwRows(entry) {
  if (!entry || typeof entry !== 'object') return [];

  if (Array.isArray(entry.homeworkTable) && entry.homeworkTable.length) {
    const first = entry.homeworkTable[0] || {};
    if (Object.prototype.hasOwnProperty.call(first, 'book') || Object.prototype.hasOwnProperty.call(first, 'this')) {
      return activeHwRows(entry.homeworkTable);
    }
    return normOldHwRows4(entry.homeworkTable);
  }

  if (typeof entry.homework === 'string' && entry.homework.trim()) {
    return [{ book: '', this: '', pct: '', comment: entry.homework.trim(), next: '', _deleted: false }];
  }

  return [];
}

function normOldHwRows4(x) {
  if (!Array.isArray(x)) return [];
  return x.map(r => ({
    book: cleanHwText(r?.name),
    this: cleanHwText(r?.unit),
    pct: (r?.pct === '' || r?.pct == null) ? '' : String(r.pct).trim(),
    comment: cleanHwText(r?.rem),
    next: '',
    _deleted: false,
  }));
}

function snap10(n) {
  n = Number(n);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n / 10) * 10));
}

function mergeHwRows({ todayRows, latestRows, bookCarryRows }) {
  const a = activeHwRows(todayRows);
  const b = activeHwRows(latestRows);
  const c = activeHwRows(bookCarryRows);

  const n = Math.max(a.length, b.length, c.length, 1);
  const out = [];

  for (let i = 0; i < n; i++) {
    const t = a[i] || { book: '', this: '', pct: '', comment: '', next: '', _deleted: false };
    const l = b[i] || { book: '', this: '', pct: '', comment: '', next: '', _deleted: false };
    const bc = c[i] || { book: '', this: '', pct: '', comment: '', next: '', _deleted: false };

    const phThis = previousHomeworkText(l);
    const hasTodayRow = i < a.length;

    out.push({
      ...(hasTodayRow ? t : {}),
      _deleted: !!t._deleted,
      book: (hasTodayRow ? (t.book || '') : (bc.book || '')),
      this: t.this || '',
      pct: t.pct || '',
      comment: t.comment || '',
      next: t.next || '',
      _ph: { this: phThis || '', pct: l.pct || '', comment: l.comment || '', next: l.next || '' }
    });
  }
  return out;
}

function projectHomeworkRowsFromLogState(today, sid) {
  const dates = Object.keys(state.logs || {})
    .filter(date => /^\d{4}-\d{2}-\d{2}$/.test(date) && date <= today)
    .sort();
  const logEntry = (state.logs?.[today] || {})[sid] || {};
  const todayRows = entryHwRows(logEntry);
  let latestRows = [];
  let bookCarryRows = [];

  for (let i = dates.length - 1; i >= 0; i -= 1) {
    const date = dates[i];
    if (date >= today) continue;
    const previous = (state.logs?.[date] || {})[sid];
    if (!previous) continue;

    if (Array.isArray(previous.homeworkTable) && previous.homeworkTable.length) {
      const first = previous.homeworkTable[0] || {};
      const rows = Object.prototype.hasOwnProperty.call(first, 'book')
        || Object.prototype.hasOwnProperty.call(first, 'this')
        ? activeHwRows(previous.homeworkTable)
        : normOldHwRows4(previous.homeworkTable);

      if (!latestRows.length && hasMeaningfulHwRows(rows)) latestRows = rows;
      if (!bookCarryRows.length && rows.some(row => cleanHwText(row.book))) {
        bookCarryRows = rows.map(row => ({
          book: row.book,
          this: '',
          pct: '',
          comment: '',
          next: '',
          _deleted: false,
        }));
      }
      if (latestRows.length && bookCarryRows.length) break;
    }

    if (typeof previous.homework === 'string' && previous.homework.trim()) {
      if (!latestRows.length) {
        latestRows = [{
          book: '',
          this: '',
          pct: '',
          comment: previous.homework.trim(),
          next: '',
          _deleted: false,
        }];
      }
      if (latestRows.length) break;
    }
  }

  const sleepingHomeworkBooks = resolveSleepingHomeworkBooks({ logEntry, dates, today, sid });
  return {
    dates,
    logEntry,
    todayRows,
    sleepingHomeworkBooks,
    mergedRows: mergeHwRows({ todayRows, latestRows, bookCarryRows }),
  };
}

function configuredHomeworkBookRows(student) {
  const seen = new Set();
  const numberedBooks = Object.keys(student || {})
    .filter(key => /^subBook\d+$/.test(key))
    .sort((a, b) => Number(a.slice(7)) - Number(b.slice(7)))
    .map(key => student[key]);
  return [
    ...numberedBooks,
    student?.currentBook,
    student?.textbook,
    student?.mathTextbook,
    student?.book,
    student?.mathBook,
  ]
    .map(cleanHwText)
    .filter(book => {
      const key = homeworkBookKey(book);
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map(book => ({ book, this: '', pct: '', comment: '', next: '', _deleted: false }));
}

function updatePctBubble(wrapEl, value, { isPlaceholder = false } = {}) {
  if (!wrapEl) return;
  const bubble = wrapEl.querySelector('.pctBubble');
  if (!bubble) return;

  const v = snap10(value);
  bubble.textContent = `${v}%`;
  bubble.classList.toggle('is-ph', !!isPlaceholder);
  bubble.style.left = `${v}%`;
  bubble.style.transform = `translateX(${-v}%)`;
}

function assignmentForHomeworkRow(row, claimedIds) {
  const rowId = String(row?.assignmentId || '').trim();
  const assignment = rowId
    ? canonicalHomework.assignments.find(item => String(item.id) === rowId)
    : null;
  if (assignment?.id) claimedIds.add(String(assignment.id));
  return assignment || null;
}

function defaultHomeworkTitle(row) {
  return cleanHwText(row?.next)
    || cleanHwText(row?.this)
    || cleanHwText(row?.comment)
    || cleanHwText(row?.book)
    || '';
}

function homeworkOrderControlsHtml(rowIndex) {
  const number = Number(rowIndex) + 1;
  return `
    <div class="hw-order-row" hidden>
      <span class="hw-order-label">${number}번째 교재</span>
      <span class="hw-order-controls">
        <button type="button" class="hw-order-btn" data-direction="up" aria-label="${number}번째 교재 위로 이동" title="위로">↑</button>
        <button type="button" class="hw-order-btn" data-direction="down" aria-label="${number}번째 교재 아래로 이동" title="아래로">↓</button>
      </span>
    </div>`;
}

function appendCanonicalHomeworkEditor(item, row, assignment, rowIndex) {
  const doc = item.ownerDocument || document;
  const normalized = assignment ? normalizeHomeworkAssignment(assignment) : null;
  const editor = doc.createElement('section');
  editor.className = 'hwCanonical';
  editor.setAttribute('aria-label', `${rowIndex + 1}번째 숙제 상세`);

  const grid = doc.createElement('div');
  grid.className = 'hwCanonicalGrid';
  editor.append(grid);

  const appendField = (labelText, control) => {
    const label = doc.createElement('label');
    label.className = 'hwCanonicalField';
    const labelNode = doc.createElement('span');
    labelNode.className = 'hwCanonicalLabel';
    setHomeworkElementText(labelNode, labelText);
    label.append(labelNode, control);
    grid.append(label);
  };

  const title = doc.createElement('input');
  title.type = 'text';
  title.className = 'hwTitle';
  title.maxLength = 200;
  title.placeholder = '예: 쎈 B단계';
  setHomeworkElementText(title, normalized?.title || defaultHomeworkTitle(row), { asValue: true });
  appendField('숙제명', title);

  const scope = doc.createElement('input');
  scope.type = 'text';
  scope.className = 'hwScope';
  scope.maxLength = 1000;
  scope.placeholder = '예: 42~47쪽';
  setHomeworkElementText(scope, normalized?.scope || cleanHwText(row?.next) || cleanHwText(row?.this), { asValue: true });
  appendField('범위', scope);

  const due = doc.createElement('input');
  due.type = 'datetime-local';
  due.className = 'hwDueAt';
  setHomeworkElementText(due, homeworkDueAtToLocalInput(normalized?.dueAt), { asValue: true });
  appendField('기한', due);

  const status = doc.createElement('select');
  status.className = 'hwStatus';
  [
    ['assigned', '진행 중'],
    ['completed', '완료'],
    ['cancelled', '취소'],
  ].forEach(([value, text]) => {
    const option = doc.createElement('option');
    option.value = value;
    setHomeworkElementText(option, text);
    status.append(option);
  });
  status.value = normalized?.status || 'assigned';
  appendField('상태', status);

  const meta = doc.createElement('div');
  meta.className = 'hwCanonicalMeta';
  const hint = doc.createElement('span');
  hint.className = 'hwDueHint';
  setHomeworkElementText(hint, normalized?.dueAt ? '기한 알림 대상' : '기한 없음 — 알림 제외');
  meta.append(hint);
  const overdue = doc.createElement('span');
  overdue.className = 'hwOverdueBadge';
  setHomeworkElementText(overdue, '기한 지남');
  overdue.setAttribute('role', 'status');
  overdue.hidden = !(normalized && homeworkEffectiveStatus(normalized) === 'overdue');
  meta.append(overdue);
  editor.append(meta);

  const refreshDueMeta = () => {
    setHomeworkElementText(hint, due.value ? '기한 알림 대상' : '기한 없음 — 알림 제외');
    const dueMs = Date.parse(due.value ? `${due.value}:00+09:00` : '');
    overdue.hidden = status.value !== 'assigned' || !Number.isFinite(dueMs) || dueMs > Date.now();
  };
  due.addEventListener('input', () => {
    item.__homeworkCanonicalDirty = true;
    refreshDueMeta();
    if (!canonicalHomework.pendingPayload) canonicalHomework.operationId = null;
  });
  [title, scope, status].forEach(control => control.addEventListener('input', () => {
    item.__homeworkCanonicalDirty = true;
    if (control === status) refreshDueMeta();
    if (!canonicalHomework.pendingPayload) canonicalHomework.operationId = null;
  }));

  const readOnly = isContextMenuOnlyAccess();
  [title, scope, due, status].forEach(control => { control.disabled = readOnly; });
  item.__homeworkAssignment = normalized;
  item.__homeworkCanonicalDirty = false;
  item.__homeworkSourceRowId = String(
    normalized?.sourceRowId
    || normalized?.id
    || row?.assignmentId
    || `row_${createHomeworkOperationId()}`
  );
  item.append(editor);
}

function setHomeworkItemSleeping(item, sleeping) {
  if (!item) return;
  const next = Boolean(sleeping);
  item.dataset.sleeping = next ? '1' : '0';
  item.classList.toggle('is-sleeping', next);
}

function collectSleepingHomeworkBooks() {
  const seen = new Set();
  const books = [];
  visibleHomeworkRows().forEach(item => {
    if (item.dataset.sleeping !== '1') return;
    const book = cleanHwText(item.querySelector('.hwBook')?.value);
    const key = homeworkBookKey(book);
    if (!book || !key || seen.has(key)) return;
    seen.add(key);
    books.push(book);
  });
  return books;
}

function syncHomeworkSleepingControls() {
  const readOnly = isContextMenuOnlyAccess();
  const retryLocked = Boolean(canonicalHomework.pendingPayload);
  const homeworkBlocked = ['loading', 'error', 'conflict'].includes(canonicalHomework.mode);
  const interactionLocked = homeworkRemoveSelectionActive || homeworkReorderActive;
  document.querySelectorAll('#hwBody .hwItem').forEach(item => {
    const sleeping = item.dataset.sleeping === '1';
    const book = cleanHwText(item.querySelector('.hwBook')?.value);
    item.classList.toggle('is-sleeping', sleeping);
    item.querySelectorAll('input, select, textarea').forEach(control => {
      control.disabled = readOnly || retryLocked || homeworkBlocked || sleeping;
    });
    const toggle = item.querySelector('.hw-book-sleep-toggle');
    if (!toggle) return;
    toggle.textContent = sleeping ? '재움' : '재우기';
    toggle.hidden = interactionLocked;
    toggle.disabled = readOnly || retryLocked || homeworkBlocked || interactionLocked || !book;
    toggle.setAttribute('aria-pressed', sleeping ? 'true' : 'false');
    toggle.setAttribute('aria-label', book
      ? `${book} 교재 ${sleeping ? '다시 사용' : '재우기'}`
      : '교재명을 입력한 뒤 재울 수 있습니다');
    toggle.title = sleeping ? '클릭하여 다시 사용' : '클릭하여 잠시 재우기';
  });
}

function renderHwTable(mergedRows, sleepingBooks = []) {
  const host = $('hwBody');
  if (!host) return;

  const rows = placeSleepingHomeworkRowsLast(mergedRows, sleepingBooks);
  const sleepingBookKeys = new Set(normalizeSleepingHomeworkBooks(sleepingBooks).map(homeworkBookKey));
  const renderKey = JSON.stringify({
    rows,
    sleepingBooks: normalizeSleepingHomeworkBooks(sleepingBooks),
    canonicalAssignments: canonicalHomework.mode === 'canonical' ? canonicalHomework.assignments : null,
  });
  if (host.__homeworkRenderKey === renderKey) {
    syncHomeworkRemovalControls();
    syncHomeworkSleepingControls();
    return;
  }
  const hydratingExistingRows = typeof host.__homeworkRenderKey === 'string'
    && host.classList.contains('is-hydrating');
  host.__homeworkRenderKey = renderKey;
  const n = Math.max(rows.length, 1);

  const hasPrevAny = rows.some(r => {
    const ph = r?._ph || {};
    return !!(
      (ph.this || '').trim() ||
      (ph.pct || '').toString().trim() ||
      (ph.comment || '').trim() ||
      (ph.next || '').trim()
    );
  });
  const EMPTY_PH_TEXT = '숙제 없음';

  const rowView = (i) => {
    const r = rows[i] || { book: '', this: '', pct: '', comment: '', next: '', _deleted: false, _ph: {} };
    const ph = r._ph || {};

    const bookVal = (r.book || '').trim();
    const thisVal = (r.this || '').trim();
    const cmtVal = (r.comment || '').trim();
    const nextVal = (r.next || '').trim();

    const phThis = hasPrevAny ? (ph.this || '') : EMPTY_PH_TEXT;
    const phCmt = hasPrevAny ? (ph.comment || '') : EMPTY_PH_TEXT;
    const phNext = hasPrevAny ? (ph.next || '') : EMPTY_PH_TEXT;

    const pctToday = (r.pct === '' || r.pct == null) ? '' : String(snap10(r.pct));
    const pctPh = (ph.pct === '' || ph.pct == null) ? '' : String(snap10(ph.pct));

    const displayPct = pctToday !== '' ? pctToday : (pctPh !== '' ? pctPh : '0');
    const emptyFlag = (pctToday === '') ? '1' : '0';

    const deleted = !!r._deleted;
    const sleeping = Boolean(bookVal && sleepingBookKeys.has(homeworkBookKey(bookVal)));
    return { bookVal, thisVal, cmtVal, nextVal, phThis, phCmt, phNext, displayPct, emptyFlag, deleted, sleeping };
  };

  const itemHtml = (i) => {
    const { bookVal, thisVal, cmtVal, nextVal, phThis, phCmt, phNext, displayPct, emptyFlag, deleted, sleeping } = rowView(i);
    const removeChoiceHtml = `<button type="button" class="hw-remove-choice" aria-label="${i + 1}번째 교재 선택 제거" hidden>선택</button>`;
    const delAttr = deleted ? '1' : '0';
    const hideStyle = deleted ? 'style="display:none"' : '';

    return `
      <div class="hwItem${sleeping ? ' is-sleeping' : ''}" data-idx="${i}" data-deleted="${delAttr}" data-sleeping="${sleeping ? '1' : '0'}" ${hideStyle}>
        ${homeworkOrderControlsHtml(i)}
        <div class="hwTop">
          <div class="hw-book">
            <div class="hw-book-input-row">
              <input class="hwBook" type="text" value="${escapeAttr(bookVal)}" placeholder="">
              ${removeChoiceHtml}
            </div>
            <button type="button" class="hw-book-sleep-toggle" aria-pressed="${sleeping ? 'true' : 'false'}">재우기</button>
          </div>

          <div class="hw-this">
            <div class="thisCell">
              <div class="thisInputWrap">
                <input class="hwThis" type="text" value="${escapeAttr(thisVal)}" placeholder="${escapeAttr(phThis)}">
              </div>

              <div class="pctWrap" data-empty="${emptyFlag}">
                <span class="pctBubble"></span>
                <input class="hwPctRange" type="range" min="0" max="100" step="10"
                       value="${escapeAttr(displayPct)}" aria-label="진행률 슬라이더">
              </div>
            </div>
          </div>


        </div>

        <div class="hwBot">
          <div class="hw-cmt">
            <input class="hwComment" type="text" value="${escapeAttr(cmtVal)}" placeholder="${escapeAttr(phCmt)}">
          </div>

          <div class="hw-next">
            <input class="hwNext" type="text" value="${escapeAttr(nextVal)}" placeholder="${escapeAttr(phNext)}">
          </div>


        </div>
      </div>`;
  };

  const existingItems = hydratingExistingRows ? Array.from(host.querySelectorAll('.hwItem')) : [];
  const canHydrateInPlace = existingItems.length === n && existingItems.every((item, index) => (
    !item.querySelector('.hwCanonical')
    && homeworkBookKey(item.querySelector('.hwBook')?.value) === homeworkBookKey(rows[index]?.book)
    && ['.hwBook', '.hwThis', '.hwComment', '.hwNext', '.hwPctRange', '.pctWrap']
      .every(selector => item.querySelector(selector))
  ));
  if (canHydrateInPlace) {
    // Loading controls are locked: hydrate their values without replacing the visible inputs.
    existingItems.forEach((item, index) => {
      const view = rowView(index);
      [
        ['.hwBook', view.bookVal, ''],
        ['.hwThis', view.thisVal, view.phThis],
        ['.hwComment', view.cmtVal, view.phCmt],
        ['.hwNext', view.nextVal, view.phNext],
      ].forEach(([selector, value, placeholder]) => {
        const input = item.querySelector(selector);
        input.value = value;
        input.placeholder = placeholder;
      });
      item.querySelector('.hwPctRange').value = view.displayPct;
      item.querySelector('.pctWrap').dataset.empty = view.emptyFlag;
      item.dataset.deleted = view.deleted ? '1' : '0';
      item.style.display = view.deleted ? 'none' : '';
      setHomeworkItemSleeping(item, view.sleeping);
    });
  } else {
    host.innerHTML = Array.from({ length: n }, (_, i) => itemHtml(i)).join('');
  }
  resetHomeworkInteractionModes();

  const claimedIds = new Set();
  host.querySelectorAll('.hwItem').forEach((item, index) => {
    const row = rows[index] || {};
    item.__homeworkOriginalRow = mergeHomeworkLogRow(row, {}, row?.assignmentId);
    if (canonicalHomework.mode !== 'canonical') return;
    const assignment = assignmentForHomeworkRow(row, claimedIds);
    if (row?.assignmentId && !assignment) {
      canonicalHomework.mode = 'conflict';
      canonicalHomework.error = '로그에 연결된 숙제 상세를 찾지 못했습니다. 자동 복구하지 않고 저장을 중단했습니다.';
    }
    appendCanonicalHomeworkEditor(item, row, assignment, index);
  });
  if (canonicalHomework.mode === 'canonical') {
    const unlinked = canonicalHomework.assignments.filter(assignment => (
      assignment?.id && !claimedIds.has(String(assignment.id))
    ));
    unlinked.filter(assignment => assignment.status === 'cancelled').forEach(assignment => {
      canonicalHomework.removedAssignmentIds.add(String(assignment.id));
    });
    if (unlinked.some(assignment => assignment.status !== 'cancelled')) {
      canonicalHomework.mode = 'conflict';
      canonicalHomework.error = '로그 행과 연결되지 않은 숙제가 있습니다. 자동으로 취소하지 않고 저장을 중단했습니다.';
    }
  }

  host.querySelectorAll('.pctWrap').forEach(wrap => {
    const range = wrap.querySelector('.hwPctRange');
    if (!range) return;
    const isPh = (wrap.dataset.empty === '1');
    updatePctBubble(wrap, range.value, { isPlaceholder: isPh });
  });
  syncHomeworkSleepingControls();
}

function addHwRow(bookCarry = '') {
  const host = $('hwBody');
  if (!host) return;

  const rowIndex = host.querySelectorAll('.hwItem').length;
  const removeChoiceHtml = `<button type="button" class="hw-remove-choice" aria-label="${rowIndex + 1}번째 교재 선택 제거" hidden>선택</button>`;

  host.insertAdjacentHTML('beforeend', `
    <div class="hwItem" data-idx="" data-deleted="0" data-sleeping="0">
      ${homeworkOrderControlsHtml(rowIndex)}
      <div class="hwTop">
        <div class="hw-book">
          <div class="hw-book-input-row">
            <input class="hwBook" type="text" value="${escapeAttr(bookCarry)}" placeholder="">
            ${removeChoiceHtml}
          </div>
          <button type="button" class="hw-book-sleep-toggle" aria-pressed="false">재우기</button>
        </div>

        <div class="hw-this">
          <div class="thisCell">
            <div class="thisInputWrap">
              <input class="hwThis" type="text" value="" placeholder="">
            </div>

            <div class="pctWrap" data-empty="1">
              <span class="pctBubble"></span>
              <input class="hwPctRange" type="range" min="0" max="100" step="10" value="0" aria-label="진행률 슬라이더">
            </div>
          </div>
        </div>


      </div>

      <div class="hwBot">
        <div class="hw-cmt">
          <input class="hwComment" type="text" value="" placeholder="">
        </div>

        <div class="hw-next">
          <input class="hwNext" type="text" value="" placeholder="">
        </div>


      </div>
    </div>
  `);

  const lastWrap = host.querySelector('.hwItem:last-child .pctWrap');
  if (lastWrap) {
    const range = lastWrap.querySelector('.hwPctRange');
    updatePctBubble(lastWrap, range?.value ?? 0, { isPlaceholder: true });
  }
  const item = host.querySelector('.hwItem:last-child');
  if (item) {
    const row = { book: cleanHwText(bookCarry), this: '', pct: '', comment: '', next: '', _deleted: false };
    item.__homeworkOriginalRow = {};
    if (canonicalHomework.mode === 'canonical') {
      appendCanonicalHomeworkEditor(item, row, null, host.querySelectorAll('.hwItem').length - 1);
    }
  }
  syncHomeworkRemovalControls();
  syncHomeworkSleepingControls();
}

function visibleHomeworkRows(host = $('hwBody')) {
  if (!host) return [];
  return Array.from(host.querySelectorAll('.hwItem'))
    .filter(item => item.dataset.deleted !== '1' && item.style.display !== 'none');
}

function syncHomeworkRemovalControls() {
  const host = $('hwBody');
  const removeRow = $('hwRemoveRow');
  const addRow = $('hwAddRow');
  const reorderRows = $('hwReorderRows');
  const readOnly = isContextMenuOnlyAccess();
  const retryLocked = Boolean(canonicalHomework.pendingPayload);
  const homeworkBlocked = ['loading', 'error', 'conflict'].includes(canonicalHomework.mode);
  const removing = homeworkRemoveSelectionActive && !readOnly && !retryLocked && !homeworkBlocked;
  const reordering = homeworkReorderActive && !readOnly && !retryLocked && !homeworkBlocked && !removing;
  homeworkRemoveSelectionActive = removing;
  homeworkReorderActive = reordering;

  host?.classList.toggle('is-remove-selecting', removing);
  host?.classList.toggle('is-reordering', reordering);
  const visibleRows = visibleHomeworkRows(host);
  visibleRows.forEach((item, index) => {
    item.dataset.idx = String(index);
    const book = cleanHwText(item.querySelector('.hwBook')?.value);
    const itemLabel = `${index + 1}번째 교재${book ? ` ${book}` : ''}`;
    const orderRow = item.querySelector('.hw-order-row');
    if (orderRow) orderRow.hidden = !reordering;
    const orderLabel = item.querySelector('.hw-order-label');
    if (orderLabel) orderLabel.textContent = `${index + 1}번째 교재`;
    const canonicalEditor = item.querySelector('.hwCanonical');
    if (canonicalEditor) canonicalEditor.setAttribute('aria-label', `${index + 1}번째 숙제 상세`);
    const moveUp = item.querySelector('.hw-order-btn[data-direction="up"]');
    const moveDown = item.querySelector('.hw-order-btn[data-direction="down"]');
    if (moveUp) {
      moveUp.disabled = retryLocked || homeworkBlocked || index === 0;
      moveUp.setAttribute('aria-label', `${itemLabel} 위로 이동`);
    }
    if (moveDown) {
      moveDown.disabled = retryLocked || homeworkBlocked || index === visibleRows.length - 1;
      moveDown.setAttribute('aria-label', `${itemLabel} 아래로 이동`);
    }
    const deleteButton = item.querySelector('.hw-book-delete');
    if (deleteButton) {
      deleteButton.hidden = readOnly || removing || reordering || index < 2;
      deleteButton.disabled = retryLocked || homeworkBlocked;
      deleteButton.setAttribute('aria-label', `${index + 1}번째 교재 칸 삭제`);
    }
    const choiceButton = item.querySelector('.hw-remove-choice');
    if (choiceButton) {
      choiceButton.hidden = readOnly || !removing || reordering;
      choiceButton.disabled = retryLocked || homeworkBlocked;
      choiceButton.setAttribute('aria-label', `${itemLabel} 선택 제거`);
    }
  });

  if (removeRow) {
    removeRow.textContent = removing
      ? '취소'
      : (removeRow.closest('#tooltipHomeworkActions') ? '교재 제거' : '- 제거');
    removeRow.setAttribute('aria-pressed', removing ? 'true' : 'false');
    removeRow.disabled = retryLocked || homeworkBlocked || reordering;
  }
  if (addRow) addRow.disabled = readOnly || retryLocked || homeworkBlocked || removing || reordering;
  if (reorderRows) {
    reorderRows.hidden = readOnly;
    reorderRows.textContent = reordering
      ? '순서 완료'
      : (reorderRows.closest('#tooltipHomeworkActions') ? '교재 순서' : '↕ 순서');
    reorderRows.setAttribute('aria-pressed', reordering ? 'true' : 'false');
    reorderRows.disabled = readOnly || retryLocked || homeworkBlocked || removing || visibleRows.length < 2;
  }
  syncHomeworkSleepingControls();
}

function setHomeworkRemoveSelection(active) {
  if (active) homeworkReorderActive = false;
  homeworkRemoveSelectionActive = Boolean(active);
  syncHomeworkRemovalControls();
}

function setHomeworkReorderMode(active) {
  if (active) homeworkRemoveSelectionActive = false;
  homeworkReorderActive = Boolean(active);
  syncHomeworkRemovalControls();
}

function resetHomeworkInteractionModes() {
  homeworkRemoveSelectionActive = false;
  homeworkReorderActive = false;
  syncHomeworkRemovalControls();
}

function moveHomeworkRow(item, direction) {
  if (isContextMenuOnlyAccess() || !homeworkReorderActive || !item) return false;
  if (canonicalHomework.pendingPayload || canonicalHomework.mode === 'error' || canonicalHomework.mode === 'conflict') return false;
  const host = $('hwBody');
  if (!host || item.parentElement !== host) return false;
  const rows = visibleHomeworkRows(host);
  const index = rows.indexOf(item);
  const offset = direction === 'up' ? -1 : (direction === 'down' ? 1 : 0);
  const targetIndex = index + offset;
  if (!offset || index < 0 || targetIndex < 0 || targetIndex >= rows.length) return false;

  const target = rows[targetIndex];
  if (offset < 0) host.insertBefore(item, target);
  else host.insertBefore(item, target.nextElementSibling);
  canonicalHomework.operationId = null;
  syncHomeworkRemovalControls();
  return true;
}
function ensureMinimumHomeworkRows(minimum = 2) {
  const host = $('hwBody');
  if (!host) return;
  while (visibleHomeworkRows(host).length < minimum) addHwRow('');
}

function removeHomeworkRow(item) {
  if (isContextMenuOnlyAccess() || !item) return false;
  const assignmentId = String(item.__homeworkAssignment?.id || item.__homeworkOriginalRow?.assignmentId || '').trim();
  if (assignmentId) canonicalHomework.removedAssignmentIds.add(assignmentId);
  if (!canonicalHomework.pendingPayload) canonicalHomework.operationId = null;
  item.remove();
  ensureMinimumHomeworkRows(2);
  syncHomeworkRemovalControls();
  return true;
}

function collectHwTable() {
  const host = $('hwBody');
  if (!host) return [];
  const out = [];

  host.querySelectorAll('.hwItem').forEach(item => {
    if (item.dataset.deleted === '1' || item.style.display === 'none') return;
    if (canonicalHomework.mode === 'canonical' && item.querySelector('.hwStatus')?.value === 'cancelled') {
      const assignmentId = String(item.__homeworkAssignment?.id || item.__homeworkOriginalRow?.assignmentId || '').trim();
      if (assignmentId) canonicalHomework.removedAssignmentIds.add(assignmentId);
      return;
    }

    const book = cleanHwText(item.querySelector('.hwBook')?.value);
    const thisHw = cleanHwText(item.querySelector('.hwThis')?.value);
    const comment = cleanHwText(item.querySelector('.hwComment')?.value);
    const next = cleanHwText(item.querySelector('.hwNext')?.value);

    const wrap = item.querySelector('.pctWrap');
    const range = item.querySelector('.hwPctRange');
    const raw = range ? snap10(range.value) : 0;

    const empty = (wrap?.dataset?.empty === '1');
    const pct = empty ? '' : String(raw);

    const assignmentId = String(item.__homeworkAssignment?.id || item.__homeworkOriginalRow?.assignmentId || '').trim();
    const row = mergeHomeworkLogRow(item.__homeworkOriginalRow, {
      book,
      this: thisHw,
      pct,
      comment,
      next,
      _deleted: false,
    }, assignmentId);
    const canonicalMeaningful = canonicalHomework.mode === 'canonical'
      && Boolean(item.__homeworkAssignment?.id || item.__homeworkCanonicalDirty);
    if (!isMeaningfulHwRow(row) && !canonicalMeaningful) return;
    out.push(row);
  });

  return out;
}

function applyBlankHomeworkCheckCarryoverToForm() {
  const items = visibleHomeworkRows();
  const projected = projectBlankHomeworkCheckCarryover(items.map(item => {
    const wrap = item.querySelector('.pctWrap');
    const range = item.querySelector('.hwPctRange');
    return {
      book: cleanHwText(item.querySelector('.hwBook')?.value),
      this: cleanHwText(item.querySelector('.hwThis')?.value),
      pct: wrap?.dataset?.empty === '1' ? '' : String(snap10(range?.value || 0)),
      comment: cleanHwText(item.querySelector('.hwComment')?.value),
      next: cleanHwText(item.querySelector('.hwNext')?.value),
      previousThis: cleanHwText(item.querySelector('.hwThis')?.placeholder),
      sleeping: item.dataset.sleeping === '1',
      deleted: item.dataset.deleted === '1',
    };
  }));

  let applied = 0;
  projected.forEach((row, index) => {
    if (!row.carriedFromPrevious) return;
    const item = items[index];
    if (!item) return;

    const thisInput = item.querySelector('.hwThis');
    const wrap = item.querySelector('.pctWrap');
    const range = item.querySelector('.hwPctRange');
    if (!thisInput || !wrap || !range) return;

    thisInput.value = row.this;
    range.value = '0';
    wrap.dataset.empty = '0';
    updatePctBubble(wrap, 0, { isPlaceholder: false });

    if (canonicalHomework.mode === 'canonical') {
      const title = item.querySelector('.hwTitle');
      const scope = item.querySelector('.hwScope');
      const book = cleanHwText(item.querySelector('.hwBook')?.value);
      if (title && (!cleanHwText(title.value) || cleanHwText(title.value) === book)) {
        title.value = row.this;
      }
      if (scope && !cleanHwText(scope.value)) scope.value = row.this;
      item.__homeworkCanonicalDirty = true;
      if (!canonicalHomework.pendingPayload) canonicalHomework.operationId = null;
    }
    applied += 1;
  });

  return applied;
}

function collectCanonicalHomeworkRows() {
  if (canonicalHomework.mode !== 'canonical') return [];
  const rows = [];
  let rowIndex = 0;
  document.querySelectorAll('#hwBody .hwItem').forEach(item => {
    if (item.dataset.deleted === '1' || item.style.display === 'none') return;
    if (item.querySelector('.hwStatus')?.value === 'cancelled') {
      const assignmentId = String(item.__homeworkAssignment?.id || item.__homeworkOriginalRow?.assignmentId || '').trim();
      if (assignmentId) canonicalHomework.removedAssignmentIds.add(assignmentId);
      return;
    }
    const book = cleanHwText(item.querySelector('.hwBook')?.value);
    const thisHw = cleanHwText(item.querySelector('.hwThis')?.value);
    const comment = cleanHwText(item.querySelector('.hwComment')?.value);
    const next = cleanHwText(item.querySelector('.hwNext')?.value);
    const pctWrap = item.querySelector('.pctWrap');
    const pctRange = item.querySelector('.hwPctRange');
    const pct = pctWrap?.dataset?.empty === '1' ? '' : String(snap10(pctRange?.value || 0));
    const assignment = item.__homeworkAssignment || {};
    const title = cleanHwText(item.querySelector('.hwTitle')?.value) || defaultHomeworkTitle({ book, this: thisHw, comment, next }) || '숙제';
    const scope = cleanHwText(item.querySelector('.hwScope')?.value);
    const dueAt = homeworkLocalDateTimeToKst(item.querySelector('.hwDueAt')?.value || '');
    const status = String(item.querySelector('.hwStatus')?.value || 'assigned');
    const legacyMeaningful = isMeaningfulHwRow({ book, this: thisHw, pct, comment, next, _deleted: false });
    if (!legacyMeaningful && !assignment.id && !item.__homeworkCanonicalDirty) return;
    const sourceRowId = String(item.__homeworkSourceRowId || assignment.sourceRowId || assignment.id || `row_${createHomeworkOperationId()}`);
    item.__homeworkSourceRowId = sourceRowId;
    rows.push({
      rowIndex,
      sourceRowId,
      assignmentId: String(assignment.id || item.__homeworkOriginalRow?.assignmentId || '').trim() || null,
      expectedRevision: Number.isInteger(Number(assignment.revision)) && Number(assignment.revision) >= 1
        ? Number(assignment.revision)
        : null,
      title,
      book,
      scope,
      dueAt,
      status,
    });
    rowIndex += 1;
  });
  return rows;
}

function setCanonicalRetryLock(locked) {
  if (locked) resetHomeworkInteractionModes();
  const readOnly = isContextMenuOnlyAccess();
  const notes = $('logNotes');
  if (notes) notes.readOnly = readOnly || locked;
  document.querySelectorAll('#hwBody input, #hwBody select, #hwBody button').forEach(control => {
    control.disabled = readOnly || locked;
  });
  const addRow = $('hwAddRow');
  if (addRow) addRow.disabled = locked;
  syncHomeworkRemovalControls();
  const save = $('logSave');
  if (save && !readOnly) save.textContent = locked ? '같은 작업 재시도' : '저장';
}
async function commitCanonicalHomework(payload) {
  canonicalHomework.pendingPayload = canonicalHomework.pendingPayload || payload;
  const requestPayload = canonicalHomework.pendingPayload;
  setCanonicalRetryLock(true);
  const saveButton = $('logSave');
  const completeButton = $('logCompleteBtn');
  const saveWasDisabled = Boolean(saveButton?.disabled);
  const completeWasDisabled = Boolean(completeButton?.disabled);
  const restoreButtonDisabledState = () => {
    if (saveButton) saveButton.disabled = saveWasDisabled;
    if (completeButton) completeButton.disabled = completeWasDisabled;
  };
  if (saveButton) {
    saveButton.disabled = true;
    saveButton.textContent = '저장 중…';
  }
  if (completeButton) completeButton.disabled = true;
  let res = null;
  try {
    res = await fetch('/api/admin/student-homework/commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestPayload),
    });
  } catch {
    restoreButtonDisabledState();
    setCanonicalRetryLock(true);
    const error = new Error('저장 응답을 확인하지 못했습니다. 같은 작업을 다시 시도해 주세요.');
    error.code = 'homework_commit_network_error';
    error.retryable = true;
    throw error;
  }
  restoreButtonDisabledState();
  let data = null;
  try { data = await res.json(); } catch {}

  if (res.status === 409) {
    const retryable = data?.retryable === true;
    const isPartial = data?.code === 'partial_failure' && retryable;
    if (isPartial) {
      canonicalHomework.operationId = String(data?.operationId || requestPayload.operationId);
      canonicalHomework.pendingPayload = requestPayload;
      setCanonicalRetryLock(true);
    } else {
      canonicalHomework.mode = 'conflict';
      canonicalHomework.pendingPayload = null;
      canonicalHomework.operationId = null;
      setCanonicalRetryLock(true);
      const save = $('logSave');
      if (save) save.textContent = '닫고 다시 확인';
      const latestEntry = data?.entry && typeof data.entry === 'object' ? data.entry : null;
      if (latestEntry) {
        const date = String(requestPayload.date);
        const sid = String(requestPayload.sid);
        state.logs = state.logs || {};
        state.logs[date] = state.logs[date] || {};
        state.logs[date][sid] = latestEntry;
      }
    }
    const error = new Error(data?.error || data?.message || (isPartial
      ? '일부 저장이 완료되지 않았습니다. 같은 작업을 다시 시도해 주세요.'
      : '다른 화면에서 숙제가 변경되었습니다. 닫은 뒤 다시 열어 주세요.'));
    error.code = data?.code || 'homework_conflict';
    error.retryable = retryable;
    throw error;
  }

  if (!res.ok || !data?.ok) {
    const error = new Error(data?.error || data?.message || `숙제 저장 실패 (${res.status})`);
    error.code = data?.code || 'homework_commit_failed';
    error.retryable = data?.retryable === true || res.status >= 500;
    if (error.retryable) {
      setCanonicalRetryLock(true);
    } else {
      canonicalHomework.pendingPayload = null;
      canonicalHomework.operationId = null;
      setCanonicalRetryLock(false);
    }
    throw error;
  }

  canonicalHomework.pendingPayload = null;
  canonicalHomework.operationId = null;
  setCanonicalRetryLock(false);
  return data;
}

function normalizeHwRowsForCompare(rows) {
  return activeHwRows(rows).map(r => ({
    book: cleanHwText(r.book),
    this: cleanHwText(r.this),
    pct: r.pct === '' ? '' : String(r.pct || '').trim(),
    comment: cleanHwText(r.comment),
    next: cleanHwText(r.next),
    _deleted: !!r._deleted,
  }));
}

function isMeaningfulHwRow(row) {
  if (!row || row._deleted) return false;
  return !!(
    String(row.this || '').trim() ||
    (row.pct === '' ? '' : String(row.pct || '').trim()) ||
    String(row.comment || '').trim() ||
    String(row.next || '').trim()
  );
}

function hasMeaningfulHwRows(rows) {
  return normalizeHwRowsForCompare(rows).some(isMeaningfulHwRow);
}

function sameHwRows(a, b) {
  return JSON.stringify(normalizeHwRowsForCompare(a)) === JSON.stringify(normalizeHwRowsForCompare(b));
}

function hwRowToSummary(r) {
  if (r?._deleted) return '';
  const book = (r.book || '').trim();
  const thisHw = (r.this || '').trim();
  const pct = (r.pct === '' ? '' : `${String(r.pct).trim()}%`);
  const cmt = (r.comment || '').trim();
  const next = (r.next || '').trim();

  const parts = [];
  if (book) parts.push(`[${book}]`);
  if (thisHw) parts.push(thisHw);
  if (pct) parts.push(pct);
  if (cmt) parts.push(`(${cmt})`);
  if (next) parts.push(`→ ${next}`);
  return parts.join(' ');
}

function buildHwSummary(rows) {
  const lines = (rows || [])
    .map(hwRowToSummary)
    .map(s => s.trim())
    .filter(Boolean);
  return lines.join(' / ');
}

function stripGeneratedTestAssignmentBlocks(notes) {
  return String(notes || '')
    .replace(/(?:^|\n+)\[테스트 배정\]\n(?:- [^\n]*(?:\n|$))+/g, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function assignmentLabel(item) {
  if (!item || typeof item !== 'object') return '';
  const label = String(item.label || '').trim();
  if (label) return label;
  return [
    item.categoryLabel || item.category,
    item.curriculum,
    item.difficulty,
    item.term,
    item.round,
    item.name,
  ].map(v => String(v || '').trim()).filter(Boolean).join(' / ');
}

function normalizeAssignmentStatus(status) {
  if (status && typeof status === 'object') status = status.status;
  const s = String(status || '').trim();
  if (['assigned', 'done', 'interrupted', 'skip'].includes(s)) return s;
  return s ? 'assigned' : '';
}

function mergeAssignmentItemsByLabel(...groups) {
  const byLabel = new Map();
  groups.flat().forEach(item => {
    if (!item || typeof item !== 'object') return;
    const label = assignmentLabel(item);
    const status = normalizeAssignmentStatus(item.status);
    if (!label || !status || status === 'skip') return;
    byLabel.set(label, { ...(byLabel.get(label) || {}), ...item, label, status });
  });
  return Array.from(byLabel.values());
}

function assignmentRoundLabel(round) {
  const raw = String(round || '').trim();
  if (!raw) return '';
  return /회/.test(raw) ? raw : `${raw}회차`;
}

function buildCarriedAssignmentNote(items) {
  const noteItems = mergeAssignmentItemsByLabel(items);
  if (!noteItems.length) return '';
  const lines = noteItems.map(item => {
    if (!item.name) return `- ${assignmentLabel(item)}`;
    const parts = [
      item.categoryLabel || item.category,
      item.curriculum,
      item.difficulty,
      item.term,
      assignmentRoundLabel(item.round),
    ].filter(Boolean);
    return `- ${parts.join(' / ')}: ${item.name}`;
  });
  return `[테스트 배정]\n${lines.join('\n')}`;
}

function appendCarriedAssignmentNote(notes, block) {
  const cleanNotes = stripGeneratedTestAssignmentBlocks(notes);
  const noteBlock = String(block || '').trim();
  if (!noteBlock) return cleanNotes;
  return `${cleanNotes ? `${cleanNotes}\n\n` : ''}${noteBlock}`.trim();
}

function logEntryForSid(dateKey, sid) {
  const day = state.logs?.[dateKey];
  if (!day || typeof day !== 'object') return {};
  const sidKey = String(sid || '');
  const direct = day[sidKey];
  if (direct && typeof direct === 'object') return direct;
  return {};
}

function carryoverTestItems(entry) {
  const carryover = entry?.[TEST_ASSIGN_ABSENCE_CARRYOVER_KEY];
  const items = carryover?.assignedTests;
  return Array.isArray(items) ? mergeAssignmentItemsByLabel(items) : [];
}

function isSidAbsentOn(dateKey, sid) {
  return new Set((state.absentByDate?.[dateKey] || []).map(String)).has(String(sid));
}

function carryoverConsumedBefore({ sourceDate, targetDate, sid }) {
  return Object.keys(state.logs || {})
    .filter(date => /^\d{4}-\d{2}-\d{2}$/.test(date) && date > sourceDate && date < targetDate)
    .some(date => String(logEntryForSid(date, sid)?.[TEST_ASSIGN_ABSENCE_SOURCE_KEY] || '') === sourceDate);
}

function findAbsentTestCarryoverForLog(dateKey, sid) {
  const targetDate = String(dateKey || '');
  const sidKey = String(sid || '');
  if (!targetDate || !sidKey) return null;

  const currentEntry = logEntryForSid(targetDate, sidKey);
  const currentDailyItems = Array.isArray(currentEntry?.[TEST_ASSIGN_DAILY_ITEMS_KEY])
    ? currentEntry[TEST_ASSIGN_DAILY_ITEMS_KEY]
    : [];
  if (currentDailyItems.length && !currentEntry?.[TEST_ASSIGN_ABSENCE_SOURCE_KEY]) return null;

  const dates = Object.keys(state.logs || {})
    .filter(date =>
      /^\d{4}-\d{2}-\d{2}$/.test(date) &&
      date < targetDate &&
      isSidAbsentOn(date, sidKey)
    )
    .sort()
    .reverse();

  for (const sourceDate of dates) {
    const items = carryoverTestItems(logEntryForSid(sourceDate, sidKey));
    if (!items.length) continue;
    if (carryoverConsumedBefore({ sourceDate, targetDate, sid: sidKey })) continue;
    return { sourceDate, items };
  }
  return null;
}

function collectChangedProgressPatch() {
  const changed = {};
  document.querySelectorAll('#logProgress .progress-cell').forEach(cell => {
    const st = cell.dataset.state || 'none';
    const initial = cell.dataset.initial || 'none';
    const mid = String(cell.dataset.mid);

    if (st !== initial) changed[mid] = st;
  });
  return changed;
}

function ensureProgressEntryForSave(date, sid) {
  if (!state.progress) state.progress = {};
  state.progress[date] = state.progress[date] || {};
  if (!state.progress[date][sid] || typeof state.progress[date][sid] !== 'object') {
    state.progress[date][sid] = {};
  }
  return state.progress[date][sid];
}

async function saveChangedProgressPatch(date, sid, changedProg) {
  ensureProgressEntryForSave(date, sid);
  if (!Object.keys(changedProg).length) return;

  const mergedProgress = await patchProgressEntry(date, sid, changedProg);
  state.progress[date][sid] = mergedProgress || {};
}

function collectPriorProgressByMid(date, sid) {
  const oldTotal = {};
  Object.keys(state.progress || {})
    .filter(d => d < date)
    .forEach(d => {
      Object.entries(state.progress[d]?.[sid] || {}).forEach(([mid, st]) => {
        const key = String(mid);
        if (key.startsWith('__') || key === 'tests') return;
        oldTotal[key] = st;
      });
    });
  return oldTotal;
}

function videoProgressLabel(mid, st) {
  if (st === 'none') return null;
  const video = state.videos.find(v => String(v.mid) === String(mid));
  if (!video) return null;
  const base = `${video.chapter}차시`;
  return st === 'done' ? base : (st === 'interrupted' ? `${base}(중단)` : (st === 'skip' ? `${base}(건너뜀)` : null));
}

function summarizeProgressPatch(changedProg, oldTotal) {
  return Object.entries(changedProg)
    .filter(([mid, st]) => oldTotal[String(mid)] !== st && st !== 'none')
    .map(([mid, st]) => videoProgressLabel(mid, st))
    .filter(Boolean)
    .join(', ');
}

function buildLogSavePatch({
  notesNow,
  hwRows,
  sleepingHomeworkBooks,
  prevLog,
  doneFlag,
  summary,
  homeworkCheckedAt = '',
}) {
  const clearKeys = [];
  const entry = {};
  const base = {};
  let contentChanged = false;

  if (notesNow !== String(logModalSnapshot.notes || '')) {
    base.notes = String(logModalServerSnapshot.notes || '');
    contentChanged = true;
    if (notesNow) entry.notes = notesNow;
    else clearKeys.push('notes');
  }

  if (!sameHwRows(hwRows, logModalSnapshot.homeworkTable)) {
    base.homeworkTable = normalizeHwRowsForCompare(logModalServerSnapshot.homeworkTable);
    contentChanged = true;
    if (hwRows.length) {
      entry.homework = buildHwSummary(hwRows);
      entry.homeworkTable = hwRows;
    } else {
      clearKeys.push('homework', 'homeworkTable');
    }
  }

  const sleepingBooksNow = normalizeSleepingHomeworkBooks(sleepingHomeworkBooks);
  if (!sameSleepingHomeworkBooks(sleepingBooksNow, logModalSnapshot.sleepingHomeworkBooks)) {
    base[HOMEWORK_SLEEPING_BOOKS_KEY] = normalizeSleepingHomeworkBooks(
      logModalServerSnapshot.sleepingHomeworkBooks,
    );
    entry[HOMEWORK_SLEEPING_BOOKS_KEY] = sleepingBooksNow;
    if (!sleepingBooksNow.length) clearKeys.push(HOMEWORK_SLEEPING_BOOKS_KEY);
    contentChanged = true;
  }

  if (logModalCarriedTestAssignment?.items?.length) {
    const carriedItems = mergeAssignmentItemsByLabel(logModalCarriedTestAssignment.items);
    const mergedAssignedItems = mergeAssignmentItemsByLabel(
      Array.isArray(prevLog.assignedTests) ? prevLog.assignedTests : [],
      carriedItems,
    );
    const mergedDailyItems = mergeAssignmentItemsByLabel(
      Array.isArray(prevLog[TEST_ASSIGN_DAILY_ITEMS_KEY]) ? prevLog[TEST_ASSIGN_DAILY_ITEMS_KEY] : [],
      carriedItems,
    );
    const mergedNoteBlock = buildCarriedAssignmentNote(mergedDailyItems);
    entry.assignedTests = mergedAssignedItems;
    entry[TEST_ASSIGN_DAILY_ITEMS_KEY] = mergedDailyItems;
    if (mergedNoteBlock) entry.testAssignmentNote = mergedNoteBlock;
    entry[TEST_ASSIGN_ABSENCE_SOURCE_KEY] = logModalCarriedTestAssignment.sourceDate;
  }

  if (summary) entry.topic = summary;
  if (homeworkCheckedAt) {
    entry.hwAssigned = true;
    entry.hwAssignedAt = homeworkCheckedAt;
    entry.hwChecked = true;
    entry.hwCheckedAt = homeworkCheckedAt;
  }
  if (doneFlag) {
    entry.done = true;
    entry.leaveTime = nowHHMM();
    entry.leaveAt = nowISO();
  }

  return { entry, clearKeys, base, contentChanged };
}

function applyLogSaveResult({ date, sid, entry, clearKeys, returned, doneFlag, prevDone }) {
  state.logs = state.logs || {};
  state.logs[date] = state.logs[date] || {};
  if (returned) {
    state.logs[date][sid] = returned;
    return;
  }

  if (!Object.keys(entry).length && !clearKeys.length) return;

  const next = { ...(state.logs[date][sid] || {}), ...entry };
  clearKeys.forEach(k => { delete next[String(k)]; });
  if (clearKeys.includes(HOMEWORK_SLEEPING_BOOKS_KEY) && Array.isArray(entry[HOMEWORK_SLEEPING_BOOKS_KEY])) {
    next[HOMEWORK_SLEEPING_BOOKS_KEY] = entry[HOMEWORK_SLEEPING_BOOKS_KEY];
  }
  if (!doneFlag && prevDone) next.done = true;
  state.logs[date][sid] = next;
}

function setLogModalSnapshots(notes, homeworkTable, sleepingHomeworkBooks) {
  logModalSnapshot = {
    notes,
    homeworkTable,
    sleepingHomeworkBooks: normalizeSleepingHomeworkBooks(sleepingHomeworkBooks),
  };
  logModalServerSnapshot = {
    notes,
    homeworkTable: normalizeHwRowsForCompare(homeworkTable),
    sleepingHomeworkBooks: normalizeSleepingHomeworkBooks(sleepingHomeworkBooks),
  };
}

export function initLogModal() {
  ensureModal();
  initTestModal();

  const logModal = $('logModal');

  const logNotes = $('logNotes');
  const logSave = $('logSave');

  const progEl = $('logProgress');
  const logComplete = $('logCompleteBtn');
  const applyReadOnlyRecordAccess = () => {
    const readOnly = isContextMenuOnlyAccess();
    const retryLocked = Boolean(canonicalHomework.pendingPayload);
    const homeworkBlocked = ['loading', 'error', 'conflict'].includes(canonicalHomework.mode);
    logModal.dataset.accessMode = logModalAccessMode;
    logNotes.readOnly = readOnly || retryLocked || homeworkBlocked;
    logNotes.setAttribute('aria-readonly', readOnly || retryLocked || homeworkBlocked ? 'true' : 'false');
    document.querySelectorAll('#hwBody input, #hwBody select').forEach(input => {
      input.disabled = readOnly || retryLocked || homeworkBlocked;
    });
    syncHomeworkRemovalControls();
    const addRow = $('hwAddRow');
    if (addRow) {
      addRow.hidden = readOnly;
      addRow.disabled = retryLocked || homeworkBlocked || homeworkRemoveSelectionActive;
    }
    const removeRow = $('hwRemoveRow');
    if (removeRow) {
      removeRow.hidden = readOnly;
      removeRow.disabled = retryLocked || homeworkBlocked;
    }
    if (logComplete) logComplete.hidden = readOnly;
    if (logSave) {
      logSave.hidden = readOnly;
      logSave.textContent = homeworkBlocked ? '닫고 다시 확인' : (retryLocked ? '같은 작업 재시도' : '저장');
    }
    const progressLabel = progEl.previousElementSibling;
    if (progressLabel?.tagName === 'LABEL') {
      progressLabel.textContent = readOnly ? '진도 (우클릭만 변경 가능)' : '진도';
    }
  };
  const resetLogModalScroll = () => {
    const card = logModal?.querySelector('.log-card');
    if (card) card.scrollTop = 0;
    if (logModal) logModal.scrollTop = 0;
    if (logNotes) logNotes.scrollTop = 0;
  };

  if (!window.__hwDelDelegatedBound) {
    window.__hwDelDelegatedBound = true;
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('button.hw-del-btn, button.hw-remove-choice, button.hw-order-btn, button.hw-book-sleep-toggle');
      if (!btn) return;
      if (!btn.closest('#hwWrap')) return;
      if (isContextMenuOnlyAccess()) return;

      e.preventDefault();
      e.stopPropagation();

      const item = btn.closest('.hwItem');
      if (!item) return;

      if (btn.classList.contains('hw-book-sleep-toggle')) {
        setHomeworkItemSleeping(item, item.dataset.sleeping !== '1');
        if (!canonicalHomework.pendingPayload) canonicalHomework.operationId = null;
        syncHomeworkSleepingControls();
        return;
      }

      if (btn.classList.contains('hw-order-btn')) {
        moveHomeworkRow(item, btn.dataset.direction);
        return;
      }

      const selectedFromHeader = btn.classList.contains('hw-remove-choice');
      if (selectedFromHeader && !homeworkRemoveSelectionActive) return;
      if (removeHomeworkRow(item) && selectedFromHeader) setHomeworkRemoveSelection(false);
    }, true);
  }

  document.getElementById('hwBody')?.addEventListener('input', (e) => {
    if (isContextMenuOnlyAccess()) return;
    if (canonicalHomework.mode === 'canonical' && !canonicalHomework.pendingPayload) {
      canonicalHomework.operationId = null;
    }
    const t = e.target;
    if (t.classList.contains('hwBook')) syncHomeworkSleepingControls();
    if (!t.classList.contains('hwPctRange')) return;
    const wrap = t.closest('.pctWrap');
    if (!wrap) return;
    wrap.dataset.empty = '0';
    updatePctBubble(wrap, t.value, { isPlaceholder: false });
  });

  document.getElementById('hwBody')?.addEventListener('change', (e) => {
    if (isContextMenuOnlyAccess()) return;
    const t = e.target;
    if (!t.classList.contains('hwPctRange')) return;
    const wrap = t.closest('.pctWrap');
    if (!wrap) return;
    const v = snap10(t.value);
    t.value = String(v);
    wrap.dataset.empty = '0';
    updatePctBubble(wrap, v, { isPlaceholder: false });
  });

  $('hwAddRow')?.addEventListener('click', () => {
    if (isContextMenuOnlyAccess()) return;
    const lastBook = Array.from(document.querySelectorAll('#hwBody .hwBook'))
      .map(i => (i.value || '').trim())
      .filter(Boolean)
      .slice(-1)[0] || '';
    addHwRow(lastBook);
  });

  $('hwRemoveRow')?.addEventListener('click', () => {
    if (isContextMenuOnlyAccess()) return;
    setHomeworkRemoveSelection(!homeworkRemoveSelectionActive);
  });

  $('hwReorderRows')?.addEventListener('click', () => {
    if (isContextMenuOnlyAccess()) return;
    setHomeworkReorderMode(!homeworkReorderActive);
  });

  const nextStateOf = (s) =>
    s === 'none' ? 'done'
      : s === 'done' ? 'interrupted'
        : s === 'interrupted' ? 'none'
          : 'none';

  const updateCellState = (cell, next) => {
    if (!cell) return;
    cell.dataset.state = next;
    cell.dataset.explicitNone = next === 'none' ? '1' : '';
    cell.dataset.cleared = (next === 'none' && cell.dataset.initial !== 'none') ? '1' : '';
  };

  let pointerDown = false;
  let dragActive = false;
  let dragTarget = null;
  let dragButton = 0;
  let startState = 'none';
  let startIndex = -1;
  let suppressClickOnce = false;

  let dragCells = [];
  let dragInitialStates = [];

  const rebuildDragCells = () => {
    dragCells = Array.from(progEl.querySelectorAll('.progress-cell'));
    dragInitialStates = dragCells.map(c => c.dataset.state || 'none');
  };

  function applyDragRange(currentCell) {
    if (!pointerDown || !dragActive) return;
    const curIndex = dragCells.indexOf(currentCell);
    if (curIndex === -1 || startIndex === -1) return;

    const lo = Math.min(startIndex, curIndex);
    const hi = Math.max(startIndex, curIndex);

    dragCells.forEach((cell, idx) => {
      const initial = dragInitialStates[idx] || 'none';
      const next = (idx >= lo && idx <= hi) ? dragTarget : initial;
      updateCellState(cell, next);
    });
  }

  const handleMove = (e) => {
    if (!pointerDown) return;
    if (isContextMenuOnlyAccess() && dragButton !== 2) return;
    const cell = e.target.closest('.progress-cell');
    if (!cell) return;

    if (!dragActive) {
      dragActive = true;
      dragTarget = dragButton === 2 ? 'skip' : nextStateOf(startState);
    }
    applyDragRange(cell);
    e.preventDefault();
  };

  progEl.addEventListener('mousemove', handleMove);
  progEl.addEventListener('mouseover', handleMove);

  document.addEventListener('mouseup', () => {
    if (!pointerDown) return;
    pointerDown = false;
    if (dragActive && dragButton === 0) suppressClickOnce = true;

    dragActive = false;
    dragTarget = null;
    dragButton = 0;
    startState = 'none';
    startIndex = -1;
  });

  progEl.addEventListener('mousedown', (e) => {
    if (e.button !== 0 && e.button !== 2) return;
    if (isContextMenuOnlyAccess() && e.button !== 2) return;
    const cell = e.target.closest('.progress-cell');
    if (!cell) return;

    if (e.button === 2) e.preventDefault();

    rebuildDragCells();
    startIndex = dragCells.indexOf(cell);
    if (startIndex === -1) return;

    pointerDown = true;
    dragActive = false;
    dragTarget = null;
    dragButton = e.button;
    startState = cell.dataset.state || 'none';
  });

  async function openLogModalForRow(rowOrButton, opts = {}) {
    if (logRecordActionPromise || saveAllStudentPopupPromise) return;
    const openSeq = ++logOpenSeq;
    const tr = rowOrButton?.closest?.('tr[data-sid]') || rowOrButton;
    editingLogSid = tr?.dataset?.sid;
    editingLogDate = tr?.dataset?.date || getAdminDate();
    logModalAccessMode = opts.accessMode === 'all-students-readonly'
      ? 'all-students-readonly'
      : 'full';
    resetCanonicalHomeworkState('loading');
    applyReadOnlyRecordAccess();

    const stu = state.students.find(x => String(x.id) === String(editingLogSid));
    if (!stu) { alert('학생 정보를 찾을 수 없습니다.'); return; }

    const prepareUnifiedHomework = opts.layout === 'student-work';
    parkHomeworkWorkspace();

    mountAssistantThread(stu);
    const today = editingLogDate;
    const sid = String(editingLogSid);
    const isCurrentOpen = () => openSeq === logOpenSeq && sid === String(editingLogSid) && today === editingLogDate;

    logModalReady = false;
    logModalSnapshot = { notes: '', homeworkTable: [], sleepingHomeworkBooks: [] };
    logModalServerSnapshot = { notes: '', homeworkTable: [], sleepingHomeworkBooks: [] };
    logModalCarriedTestAssignment = null;
    $('hwWrap')?.querySelector('.hwCanonicalError')?.remove();
    logModal.classList.toggle('student-work-layout', opts.layout === 'student-work');
    logNotes.value = '불러오는 중...';
    logNotes.disabled = true;
    if (logSave) logSave.disabled = true;
    if (logComplete) logComplete.disabled = true;
    progEl.innerHTML = '<div class="log-loading">진도 불러오는 중...</div>';
    const homeworkBody = $('hwBody');
    if (homeworkBody) {
      homeworkBody.__homeworkRenderKey = null;
      homeworkBody.classList.add('is-hydrating');
      homeworkBody.setAttribute('aria-busy', 'true');
    }
    const cachedHomework = projectHomeworkRowsFromLogState(today, sid);
    const cachedRows = cachedHomework.mergedRows.some(row => cleanHwText(row.book))
      ? cachedHomework.mergedRows
      : configuredHomeworkBookRows(stu);
    renderHwTable(cachedRows.length ? cachedRows : cachedHomework.mergedRows, cachedHomework.sleepingHomeworkBooks);
    resetLogModalScroll();
    logModal.style.display = 'flex';

    const showHomeworkTooltip = () => {
      try {
        if (!opts.tooltipAlreadyShown && window.showStudentTooltipForSid) {
          window.showStudentTooltipForSid(sid, {
            variant: 'log',
            fixed: true,
            layout: prepareUnifiedHomework ? 'student-work' : undefined,
          });
        }
        mountHomeworkInTooltip();
        applyReadOnlyRecordAccess();
      } catch (err) {
        console.warn('[logModal] show homework tooltip failed:', err);
      }
    };
    showHomeworkTooltip();

    const progressHydrationPromise = hydrateProgressHistoryForSid(sid, isCurrentOpen);
    const logHydrationPromise = (async () => {
      const historyLoaded = await hydrateLogHistoryForSid(sid, isCurrentOpen);
      if (!isCurrentOpen()) return false;
      if (historyLoaded) return true;
      const fallback = await hydrateTodayLogFromServer(today, sid, isCurrentOpen);
      return fallback.ok;
    })();
    const hydrationResults = await Promise.allSettled([
      logHydrationPromise,
      fetchCanonicalHomeworkForLogCached(today, sid),
    ]);
    if (openSeq !== logOpenSeq || sid !== String(editingLogSid) || today !== editingLogDate) return;
    const logHydrationReady = hydrationResults[0]?.status === 'fulfilled' && hydrationResults[0].value === true;
    if (!logHydrationReady) {
      canonicalHomework.mode = 'error';
      canonicalHomework.error = '로그를 불러오지 못해 숙제 편집과 저장을 사용할 수 없습니다. 다시 불러와 주세요.';
      logNotes.value = '';
      logNotes.disabled = true;
      if (logSave) logSave.disabled = true;
      if (logComplete) logComplete.disabled = true;
      applyReadOnlyRecordAccess();
      if (homeworkBody) {
        homeworkBody.classList.remove('is-hydrating');
        homeworkBody.removeAttribute('aria-busy');
      }
      const warning = document.createElement('p');
      warning.className = 'hwCanonicalError';
      warning.setAttribute('role', 'alert');
      warning.textContent = canonicalHomework.error + ' ';
      const retry = document.createElement('button');
      retry.id = 'logLoadRetry';
      retry.type = 'button';
      retry.textContent = '다시 불러오기';
      retry.addEventListener('click', () => {
        if (!isCurrentOpen()) return;
        invalidateLogModalHydrationCaches(today, sid);
        void openLogModalForRow(tr, opts);
      });
      warning.append(retry);
      $('hwWrap')?.prepend(warning);
      return;
    }
    const canonicalResult = hydrationResults[1];
    if (canonicalResult?.status === 'fulfilled') {
      const payload = canonicalResult.value || {};
      canonicalHomework.mode = payload.mode === 'canonical' ? 'canonical' : 'legacy';
      canonicalHomework.assignments = Array.isArray(payload.assignments) ? payload.assignments : [];
      canonicalHomework.operationId = String(payload.pendingOperation?.operationId || '').trim() || null;
      if (canonicalHomework.mode === 'canonical' && payload.pendingOperation) {
        canonicalHomework.mode = 'conflict';
        canonicalHomework.error = '이 날짜에 미완료 저장 작업이 있습니다. 새 작업으로 덮어쓰지 않고 저장을 중단했습니다.';
      }
    } else {
      canonicalHomework.mode = 'error';
      canonicalHomework.error = canonicalResult?.reason?.message || '숙제 상세를 불러오지 못했습니다.';
    }
    logNotes.disabled = false;
    if (logSave) logSave.disabled = false;
    if (logComplete) logComplete.disabled = false;
    logModalReady = true;

    const homework = projectHomeworkRowsFromLogState(today, sid);
    const { logEntry, todayRows, sleepingHomeworkBooks } = homework;
    canonicalHomework.exactLogRows = Array.isArray(logEntry.homeworkTable)
      ? JSON.parse(JSON.stringify(logEntry.homeworkTable))
      : [];
    const todayNotes = cleanHwText(logEntry.notes);
    logModalCarriedTestAssignment = findAbsentTestCarryoverForLog(today, sid);

    // 상담 입력 UI는 제거되었으므로 과거 상담 문구를 숙제 저장에 재사용하지 않는다.
    logNotes.value = cleanHwText(todayNotes);
    logNotes.placeholder = '';

    renderHwTable(homework.mergedRows, sleepingHomeworkBooks);
    const homeworkSaveBlocked = !isContextMenuOnlyAccess()
      && ['loading', 'error', 'conflict'].includes(canonicalHomework.mode);
    if (logSave) logSave.disabled = homeworkSaveBlocked;
    if (logComplete) logComplete.disabled = homeworkSaveBlocked;
    if (canonicalHomework.mode === 'error' || canonicalHomework.mode === 'conflict') {
      const warning = document.createElement('p');
      warning.className = 'hwCanonicalError';
      warning.setAttribute('role', 'alert');
      warning.textContent = canonicalHomework.error
        || '숙제 상세를 불러오지 못해 저장을 잠시 사용할 수 없습니다. 닫은 뒤 다시 시도해 주세요.';
      if (canonicalHomework.mode === 'error') {
        const retry = document.createElement('button');
        retry.id = 'logLoadRetry';
        retry.type = 'button';
        retry.textContent = '다시 불러오기';
        retry.addEventListener('click', () => {
          if (!isCurrentOpen()) return;
          invalidateLogModalHydrationCaches(today, sid);
          void openLogModalForRow(tr, opts);
        });
        warning.append(retry);
      }
      $('hwWrap')?.prepend(warning);
    }
    applyReadOnlyRecordAccess();
    if (homeworkBody) {
      homeworkBody.classList.remove('is-hydrating');
      homeworkBody.removeAttribute('aria-busy');
    }

    logModalSnapshot = {
      // "최근 특이사항 미리 채움"은 오늘 서버값과는 다를 수 있으므로,
      // 변경 기준은 오늘 서버값을 스냅샷으로 둔다.
      notes: (todayNotes || '').trim(),
      homeworkTable: collectHwTable(),
      sleepingHomeworkBooks: collectSleepingHomeworkBooks(),
    };
    logModalServerSnapshot = {
      notes: (logEntry.notes || '').trim(),
      homeworkTable: normalizeHwRowsForCompare(todayRows),
      sleepingHomeworkBooks: entryHasSleepingHomeworkBooks(logEntry)
        ? normalizeSleepingHomeworkBooks(logEntry[HOMEWORK_SLEEPING_BOOKS_KEY])
        : [],
    };

    await progressHydrationPromise;
    if (openSeq !== logOpenSeq || sid !== String(editingLogSid) || today !== editingLogDate) return;

    const dates = Array.from(new Set([
      ...Object.keys(state.progress || {}),
      ...Object.keys(state.logs || {}),
    ]))
      .filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d) && d <= today)
      .sort();

    const progEntry = {};
    const explicitNoneMids = new Set();
    dates.forEach(d => {
      const day = (state.progress?.[d] || {})[sid] || {};
      const manualMeta = (day[PROGRESS_MANUAL_META_KEY] && typeof day[PROGRESS_MANUAL_META_KEY] === 'object')
        ? day[PROGRESS_MANUAL_META_KEY]
        : {};
      Object.entries(day).forEach(([mid, st]) => {
        const key = String(mid);
        if (key.startsWith('__') || key === 'tests') return;
        const value = String(st || 'none');
        if (value === 'none') {
          if (manualMeta[key]) {
            progEntry[key] = value;
            explicitNoneMids.add(key);
          }
          return;
        }
        progEntry[key] = value;
        explicitNoneMids.delete(key);
      });
    });

    progEl.innerHTML = '';
    state.videos
      .filter(v => v.curriculum === stu.curriculum && v.subCurriculum === stu.subCurriculum)
      .sort((a, b) => (a.chapter ?? 0) - (b.chapter ?? 0))
      .forEach(v => {
        const cell = document.createElement('div');
        cell.className = 'progress-cell';
        cell.textContent = `${v.chapter}차시`;
        cell.dataset.mid = String(v.mid);

        const autoSkip = shouldSkipForLow(stu, v);
        const midKey = String(v.mid);
        const hasExplicitNone = explicitNoneMids.has(midKey);
        const initial = hasExplicitNone ? 'none' : (progEntry[midKey] || (autoSkip ? 'skip' : 'none'));
        cell.dataset.initial = initial;
        cell.dataset.state = initial;
        cell.dataset.explicitNone = hasExplicitNone ? '1' : '';
        cell.dataset.cleared = '';

        cell.addEventListener('click', () => {
          if (isContextMenuOnlyAccess()) return;
          if (suppressClickOnce) { suppressClickOnce = false; return; }
          const s = cell.dataset.state || 'none';
          updateCellState(cell, nextStateOf(s));
        });

        cell.addEventListener('contextmenu', ev => {
          ev.preventDefault();
          updateCellState(cell, 'skip');
        });

        progEl.append(cell);
      });

    logModal.classList.toggle('student-work-layout', opts.layout === 'student-work');
    logModal.style.display = 'flex';
    resetLogModalScroll();
    requestAnimationFrame(() => {
      if (openSeq !== logOpenSeq || sid !== String(editingLogSid) || today !== editingLogDate) return;
      resetLogModalScroll();
    });

  }

  window.openRecordPopupForRow = openLogModalForRow;

  async function openStudentPopupsForRow(rowOrButton, opts = {}) {
    if (logRecordActionPromise || saveAllStudentPopupPromise) return;
    const tr = rowOrButton?.closest?.('tr[data-sid]') || rowOrButton;
    if (!tr?.dataset?.sid) return;

    if (window.showStudentPopupBackdrop) {
      try { window.showStudentPopupBackdrop(); } catch {}
    }
    const logOptions = {
      layout: 'student-work',
    };
    if (opts.accessMode) logOptions.accessMode = opts.accessMode;

    const openTasks = [
      openLogModalForRow(tr, logOptions).catch((err) => {
        console.warn('[logModal] open log popup failed:', err);
      }),
    ];
    if (window.openVideoAssignmentPopupForRow) {
      openTasks.push(window.openVideoAssignmentPopupForRow(tr, {
        layout: 'student-work',
        accessMode: opts.accessMode,
      }).catch((err) => {
        console.warn('[logModal] open video popup failed:', err);
      }));
    }
    if (window.openTestAssignmentPopupForRow) {
      openTasks.push(window.openTestAssignmentPopupForRow(tr, { layout: 'student-work' }).catch((err) => {
        console.warn('[logModal] open test popup failed:', err);
      }));
    }

    await Promise.allSettled(openTasks);
  }

  window.openStudentPopupsForRow = openStudentPopupsForRow;

  let homeworkPrefetchTimer = null;
  let homeworkPrefetchButton = null;
  const openButtonFromEvent = event => event.target?.closest?.('.editLog,.openStudentPopups') || null;
  const prefetchForButton = button => {
    const row = button?.closest?.('tr[data-sid]');
    if (!row) return;
    prefetchLogModalDataForRow(row);
    void window.prefetchVideoAssignmentPopupForRow?.(row);
    void window.prefetchTestAssignmentPopupForRow?.(row);
  };

  document.body.addEventListener('pointerover', event => {
    const button = openButtonFromEvent(event);
    if (!button || button.contains(event.relatedTarget)) return;
    if (homeworkPrefetchTimer) window.clearTimeout(homeworkPrefetchTimer);
    homeworkPrefetchButton = button;
    homeworkPrefetchTimer = window.setTimeout(() => {
      homeworkPrefetchTimer = null;
      prefetchForButton(homeworkPrefetchButton);
      homeworkPrefetchButton = null;
    }, 120);
  }, { passive: true });

  document.body.addEventListener('pointerout', event => {
    const button = openButtonFromEvent(event);
    if (!button || button.contains(event.relatedTarget) || button !== homeworkPrefetchButton) return;
    if (homeworkPrefetchTimer) window.clearTimeout(homeworkPrefetchTimer);
    homeworkPrefetchTimer = null;
    homeworkPrefetchButton = null;
  }, { passive: true });

  document.body.addEventListener('pointerdown', event => {
    const button = openButtonFromEvent(event);
    if (!button) return;
    if (homeworkPrefetchTimer) window.clearTimeout(homeworkPrefetchTimer);
    homeworkPrefetchTimer = null;
    homeworkPrefetchButton = null;
    prefetchForButton(button);
  }, { passive: true });

  document.body.addEventListener('focusin', event => {
    prefetchForButton(openButtonFromEvent(event));
  });

  document.body.addEventListener('click', async (e) => {
    const btn = e.target.closest('.editLog,.openStudentPopups');
    if (!btn) return;

    const tr = btn.closest('tr[data-sid]');
    if (!tr) return;

    const unified = btn.classList.contains('openStudentPopups');
    if (!unified) {
      await openLogModalForRow(tr);
      return;
    }

    await openStudentPopupsForRow(tr);
  });

  logNotes.addEventListener('input', () => {
    if (canonicalHomework.mode === 'canonical' && !canonicalHomework.pendingPayload) {
      canonicalHomework.operationId = null;
    }
  });

  const close = (event = null, { saveCompleted = false } = {}) => {
    if (!saveCompleted && (logRecordActionPromise || saveAllStudentPopupPromise)) return;
    if (event?.detail?.saveAll) {
      void saveAllStudentPopupChangesAndClose();
      return;
    }
    logOpenSeq += 1;
    const wasUnified = logModal.classList.contains('student-work-layout');
    parkHomeworkWorkspace();
    logModal.style.display = 'none';
    logModal.classList.remove('student-work-layout');
    editingLogSid = null;
    editingLogDate = null;
    logModalReady = false;
    logModalSnapshot = { notes: '', homeworkTable: [], sleepingHomeworkBooks: [] };
    logModalServerSnapshot = { notes: '', homeworkTable: [], sleepingHomeworkBooks: [] };
    logModalCarriedTestAssignment = null;
    logModalAccessMode = 'full';
    resetCanonicalHomeworkState();
    try { if (window.hideStudentTooltip) window.hideStudentTooltip(); } catch {}
    if (wasUnified) {
      try { if (window.closeVideoAssignmentPopup) window.closeVideoAssignmentPopup(); } catch {}
      try { if (window.closeTestAssignmentPopup) window.closeTestAssignmentPopup(); } catch {}
    }
    try { if (window.hideStudentPopupBackdrop) window.hideStudentPopupBackdrop(); } catch {}
  };
  window.closeStudentWorkPopups = close;
  window.isStudentPopupSavePending = () => Boolean(logRecordActionPromise || saveAllStudentPopupPromise);
  logModal.addEventListener('admin:assistant-notes-close', close);

  function assertRecordSaveReady() {
    if (!logModalReady) throw new Error('기록 팝업을 다시 불러온 뒤 저장해 주세요.');
    if (!isContextMenuOnlyAccess() && canonicalHomework.mode === 'error') {
      throw new Error(canonicalHomework.error || '숙제 상세를 불러오지 못했습니다. 닫은 뒤 다시 시도해 주세요.');
    }
    if (!isContextMenuOnlyAccess() && canonicalHomework.mode === 'conflict') {
      throw new Error(canonicalHomework.error || '다른 화면에서 숙제가 변경되었습니다. 닫은 뒤 다시 열어 주세요.');
    }
    if (!isContextMenuOnlyAccess() && canonicalHomework.mode === 'loading') {
      throw new Error('숙제 상세를 불러오는 중입니다. 잠시 후 다시 시도해 주세요.');
    }
  }

  async function saveBase(doneFlag, options = {}) {
    assertRecordSaveReady();
    const today = editingLogDate || getAdminDate();
    const sid = String(editingLogSid);
    const homeworkCheckedAt = options.homeworkChecked === true ? nowHHMM() : '';

    const prevLog = (state.logs?.[today] || {})[sid] || {};
    const prevDone =
      prevLog?.done === true || prevLog?.done === 'true' || prevLog?.done === 1 || prevLog?.done === '1';

    const saveSequence = logOpenSeq;
    const changedProg = collectChangedProgressPatch();
    await saveChangedProgressPatch(today, sid, changedProg);
    if (saveSequence !== logOpenSeq || sid !== String(editingLogSid) || today !== editingLogDate) {
      throw new Error('저장 중 대상이 바뀌었습니다. 원래 학생의 팝업을 다시 열어 확인해 주세요.');
    }

    if (isContextMenuOnlyAccess()) {
      return {};
    }

    const oldTotal = collectPriorProgressByMid(today, sid);
    const summary = summarizeProgressPatch(changedProg, oldTotal);

    if (options.homeworkChecked === true) {
      applyBlankHomeworkCheckCarryoverToForm();
    }
    const hwRows = collectHwTable();
    const sleepingHomeworkBooks = collectSleepingHomeworkBooks();
    const notesNow = cleanHwText(logNotes.value);
    const { entry, clearKeys, base, contentChanged } = buildLogSavePatch({
      notesNow,
      hwRows,
      sleepingHomeworkBooks,
      prevLog,
      doneFlag,
      summary,
      homeworkCheckedAt,
    });

    let returned = null;
    const commitOutcome = { sqlite: false, json: false };
    if (canonicalHomework.mode === 'canonical') {
      const canonicalRows = collectCanonicalHomeworkRows();
      if (hwRows.length) {
        entry.homework = buildHwSummary(hwRows);
        entry.homeworkTable = hwRows;
        for (let i = clearKeys.length - 1; i >= 0; i--) {
          if (clearKeys[i] === 'homework' || clearKeys[i] === 'homeworkTable') clearKeys.splice(i, 1);
        }
      } else {
        entry.homeworkTable = [];
        if (!clearKeys.includes('homework')) clearKeys.push('homework');
        if (!clearKeys.includes('homeworkTable')) clearKeys.push('homeworkTable');
      }
      base.homeworkTable = normalizeHwRowsForCompare(logModalServerSnapshot.homeworkTable);
      entry.updatedAt = nowISO();
      canonicalHomework.operationId = canonicalHomework.operationId || createHomeworkOperationId();
      const commitPayload = {
        operationId: canonicalHomework.operationId,
        date: today,
        sid,
        logPatch: {
          entry,
          clearKeys,
          base,
          baseHomeworkTableExact: canonicalHomework.exactLogRows,
        },
        homeworkRows: canonicalRows,
        removedAssignmentIds: Array.from(canonicalHomework.removedAssignmentIds),
      };
      const committed = await commitCanonicalHomework(commitPayload);
      commitOutcome.sqlite = committed?.log?.sqlite === true;
      commitOutcome.json = committed?.log?.json === true;
      returned = (committed?.entry && typeof committed.entry === 'object')
        ? committed.entry
        : ((committed?.log?.entry && typeof committed.log.entry === 'object') ? committed.log.entry : null);
    } else if (Object.keys(entry).length || clearKeys.length) {
      entry.updatedAt = nowISO();
      returned = await patchLogEntry(today, sid, entry, clearKeys, { ...(contentChanged ? { base } : {}), commitOutcome });
    }

    applyLogSaveResult({ date: today, sid, entry, clearKeys, returned, doneFlag, prevDone });

    setLogModalSnapshots(notesNow, hwRows, sleepingHomeworkBooks);
    invalidateLogModalHydrationCaches(today, sid);

    return { homeworkCheckedAt, carryoverCommitScope: commitOutcome.sqlite && commitOutcome.json
      ? { date: today, sid, seq: saveSequence } : null };
  }

  async function saveRecordPopupForCurrent(options = {}) {
    if (!logModalReady) throw new Error('기록 팝업을 불러오는 중입니다.');
    return await saveBase(false, options);
  }

  window.saveRecordPopup = saveRecordPopupForCurrent;

  async function reapplyCarriedTestAssignmentForCurrent(options = {}) {
    if (!logModalCarriedTestAssignment?.items?.length) return;
    const today = editingLogDate || getAdminDate();
    const sid = String(editingLogSid || '');
    if (!today || !sid) return;

    const latestEntry = await fetchLatestCarriedTestLogEntry(today, sid);
    const carriedItems = mergeAssignmentItemsByLabel(logModalCarriedTestAssignment.items);
    const mergedAssignedItems = mergeAssignmentItemsByLabel(
      Array.isArray(latestEntry.assignedTests) ? latestEntry.assignedTests : [],
      carriedItems,
    );
    const mergedDailyItems = mergeAssignmentItemsByLabel(
      Array.isArray(latestEntry[TEST_ASSIGN_DAILY_ITEMS_KEY]) ? latestEntry[TEST_ASSIGN_DAILY_ITEMS_KEY] : [],
      carriedItems,
    );
    const noteBlock = buildCarriedAssignmentNote(mergedDailyItems);
    const nextNotes = noteBlock ? appendCarriedAssignmentNote(latestEntry.notes || '', noteBlock) : String(latestEntry.notes || '').trim();
    const prevNotes = String(latestEntry.notes || '').trim();
    const entry = {
      assignedTests: mergedAssignedItems,
      [TEST_ASSIGN_DAILY_ITEMS_KEY]: mergedDailyItems,
      [TEST_ASSIGN_ABSENCE_SOURCE_KEY]: logModalCarriedTestAssignment.sourceDate,
      updatedAt: nowISO(),
    };
    if (noteBlock) entry.testAssignmentNote = noteBlock;
    if (nextNotes !== prevNotes) entry.notes = nextNotes;

    const scope = options.commitScope;
    const identical = Object.entries(entry).every(([key, value]) => key === 'updatedAt'
      || (Object.prototype.hasOwnProperty.call(latestEntry, key)
        && JSON.stringify(latestEntry[key]) === JSON.stringify(value)));
    if (scope && scope.date === today && scope.sid === sid && scope.seq === logOpenSeq && identical) return;

    const saved = await patchLogEntry(
      today,
      sid,
      entry,
      [],
      nextNotes !== prevNotes ? { base: { notes: latestEntry.notes || '' } } : {},
    );

    if (saved && typeof saved === 'object') {
      state.logs = state.logs || {};
      state.logs[today] = state.logs[today] || {};
      state.logs[today][sid] = saved;
      window.logs = state.logs;
    }
  }

  async function waitForStudentPopupSaveReady(selector, label) {
    const control = document.querySelector(selector);
    if (!control) return;
    const deadline = Date.now() + 10000;
    while (control.disabled && Date.now() < deadline) {
      await new Promise(resolve => window.setTimeout(resolve, 50));
    }
    if (control.disabled) {
      throw new Error(`${label} 팝업을 불러오는 중입니다. 잠시 후 다시 시도해 주세요.`);
    }
  }

  function lockStudentPopupControls(selectors) {
    const controls = selectors
      .flatMap(selector => Array.from(document.querySelectorAll(selector)))
      .filter(Boolean);
    const previous = controls.map(control => [control, control.disabled]);
    controls.forEach(control => { control.disabled = true; });
    return () => {
      previous.forEach(([control, disabled]) => {
        if (control.isConnected) control.disabled = disabled;
      });
    };
  }

  function runLogRecordAction(button, pendingLabel, action) {
    if (logRecordActionPromise) return logRecordActionPromise;
    if (saveAllStudentPopupPromise) return saveAllStudentPopupPromise;

    const priorLabel = String(button?.textContent || '');
    const unlock = lockStudentPopupControls([
      '#assistantStudentNotes [data-note-save-close]',
      '#assistantStudentNotes [data-note-close]',
      '#logSave',
      '#logCompleteBtn',
    ]);
    if (button) {
      button.setAttribute('aria-busy', 'true');
      button.textContent = pendingLabel;
    }

    logRecordActionPromise = (async () => {
      await action();
    })().finally(() => {
      unlock();
      if (button) button.removeAttribute('aria-busy');
      if (logModal.style.display !== 'none') {
        if (button === logSave) applyReadOnlyRecordAccess();
        else if (button) button.textContent = priorLabel;
      }
      logRecordActionPromise = null;
    });
    return logRecordActionPromise;
  }

  async function saveAllStudentPopupChangesAndClose() {
    if (saveAllStudentPopupPromise) return saveAllStudentPopupPromise;
    if (logRecordActionPromise) return logRecordActionPromise;

    saveAllStudentPopupPromise = (async () => {
      const saveSequence = logOpenSeq;
      const saveSid = String(editingLogSid);
      const saveDate = editingLogDate;
      const assertSaveTarget = () => {
        if (saveSequence !== logOpenSeq || saveSid !== String(editingLogSid) || saveDate !== editingLogDate) {
          throw new Error('저장 중 대상이 바뀌었습니다. 원래 학생의 팝업을 다시 열어 확인해 주세요.');
        }
      };
      const unified = logModal.classList.contains('student-work-layout');
      const saveButton = document.querySelector('#assistantStudentNotes [data-note-save-close]');
      const saveLabel = saveButton?.textContent;
      if (saveButton) {
        saveButton.textContent = '저장 중…';
        saveButton.setAttribute('aria-busy', 'true');
      }
      const closeUnlock = lockStudentPopupControls([
        '#assistantStudentNotes [data-note-save-close]',
        '#assistantStudentNotes [data-note-close]',
      ]);
      let allUnlock = null;
      try {
        assertRecordSaveReady();
        await waitForStudentPopupSaveReady('#logSave', '숙제');
        assertSaveTarget();
        if (unified) {
          await waitForStudentPopupSaveReady('#mSave', '영상 배정');
          await waitForStudentPopupSaveReady('#testSave', '테스트 배정');
          assertSaveTarget();
          assertRecordSaveReady();
          allUnlock = lockStudentPopupControls([
            '#assistantStudentNotes [data-note-save-close]',
            '#assistantStudentNotes [data-note-close]',
            '#logSave',
            '#logCompleteBtn',
            '#mSave',
            '#testSave',
          ]);
          if (typeof window.saveVideoAssignmentPopup === 'function') {
            await window.saveVideoAssignmentPopup({ showPopup: false, refresh: false, skipUnchanged: true });
          }
        }
        assertSaveTarget();
        const recordResult = await saveRecordPopupForCurrent();
        assertSaveTarget();
        if (!isContextMenuOnlyAccess()) {
          await reapplyCarriedTestAssignmentForCurrent({ commitScope: recordResult?.carryoverCommitScope });
        }
        assertSaveTarget();
        // The log save can merge an absence carryover captured when the popup opened.
        // Persist the current test UI last so an explicit removal remains authoritative.
        if (unified && typeof window.saveTestAssignmentPopup === 'function') {
          await window.saveTestAssignmentPopup({ showPopup: false, refresh: false });
        }
        assertSaveTarget();
        close(null, { saveCompleted: true });
        if (typeof window.showStudentPopupSaveResult === 'function') {
          window.showStudentPopupSaveResult('저장 완료');
        } else {
          toast('저장 완료');
        }
        document.dispatchEvent(new CustomEvent('admin:refresh', { detail: { changedStores: ['logHistory', 'arriveHistory'] } }));
      } catch (error) {
        console.error('[logModal] save all student popup changes failed:', error);
        alert(error?.message || '모든 팝업 변경사항 저장에 실패했습니다. 팝업을 닫지 않았습니다.');
      } finally {
        allUnlock?.();
        closeUnlock();
        if (saveButton) {
          saveButton.textContent = saveLabel;
          saveButton.removeAttribute('aria-busy');
        }
      }
    })().finally(() => {
      saveAllStudentPopupPromise = null;
    });
    return saveAllStudentPopupPromise;
  }

  logSave.addEventListener('click', async () => {
    void runLogRecordAction(logSave, '저장 중…', async () => {
      try {
        await saveRecordPopupForCurrent();
        toast(isContextMenuOnlyAccess() ? '영상 제외 상태 저장됨' : '숙제 저장됨');
        close(null, { saveCompleted: true });
        document.dispatchEvent(new CustomEvent('admin:refresh', { detail: { changedStores: ['logHistory', 'arriveHistory'] } }));
      } catch (err) {
        if (err?.message) {
          alert(err.message);
          return;
        }
        console.error(err);
        alert('저장 실패');
      }
    });
  });

  logComplete.addEventListener('click', () => {
    void runLogRecordAction(logComplete, '처리 중…', async () => {
      try {
        await saveRecordPopupForCurrent({ homeworkChecked: true });
        close(null, { saveCompleted: true });
        if (typeof window.showStudentPopupSaveResult === 'function') {
          window.showStudentPopupSaveResult('저장 완료');
        } else {
          toast('저장 완료');
        }
        document.dispatchEvent(new CustomEvent('admin:refresh', { detail: { changedStores: ['logHistory', 'arriveHistory'] } }));
      } catch (err) {
        if (err?.message) {
          alert(err.message);
          return;
        }
        console.error(err);
        alert('숙제 검사 완료 저장 실패');
      }
    });
  });
}

/* 자동 판정 애드온 */
(() => {
  const TH_DONE = 90, TH_INTERRUPTED = 5;

  const pctOf = (w) => (!w || !Number(w.dur))
    ? 0
    : Math.max(0, Math.min(100, Math.floor(((Number(w.last) || 0) / Number(w.dur)) * 100)));
  const autoState = (w) => (!w)
    ? null
    : (w.completed || pctOf(w) >= TH_DONE) ? 'done'
      : (pctOf(w) >= TH_INTERRUPTED) ? 'interrupted'
        : null;

  function applyAutoWhenReady(watchByMid, isCurrent) {
    let tries = 0;
    const tick = () => {
      if (!isCurrent()) return;
      const grid = document.getElementById('logProgress');
      if (!grid || !grid.children.length) {
        if (tries++ < 10) return setTimeout(tick, 100);
        return;
      }
      grid.querySelectorAll('.progress-cell[data-mid]').forEach(cell => {
        const mid = String(cell.dataset.mid);
        const w = watchByMid[mid];
        const st = autoState(w);
        if (!st) return;

        // 이미 사람이 지정한 상태(done/interrupted/skip)가 있으면 자동값으로 덮지 않는다.
        if (cell.dataset.explicitNone === '1') return;
        const current = String(cell.dataset.state || 'none');
        if (current !== 'none') return;

        cell.dataset.initial = st;
        cell.dataset.state = st;
        cell.dataset.cleared = '';
      });
    };
    tick();
  }

  document.body.addEventListener('click', async (e) => {
    const btn = e.target.closest('.editLog,.openStudentPopups');
    if (!btn) return;

    const tr = btn.closest('tr[data-sid]');
    const sid = tr?.dataset?.sid;
    if (!sid) return;
    // The primary open listener updates this scope later in the same click.
    await Promise.resolve();
    const date = tr?.dataset?.date || getAdminDate();
    const openSeq = logOpenSeq;
    const isCurrent = () => openSeq === logOpenSeq
      && String(editingLogSid) === String(sid) && editingLogDate === date
      && document.getElementById('logModal')?.style.display !== 'none';
    if (!isCurrent()) return;
    const raw = await fetchWatchForSid(sid, date);
    if (!isCurrent()) return;

    const watchByMid = {};
    Object.keys(raw).forEach(k => { watchByMid[String(k)] = raw[k]; });

    requestAnimationFrame(() => {
      if (isCurrent()) applyAutoWhenReady(watchByMid, isCurrent);
    });
  }, false);
})();
