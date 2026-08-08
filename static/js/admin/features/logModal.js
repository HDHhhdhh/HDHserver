// /js/admin/features/logModal.js
/* global fetch */

import { $, toast, postJSON } from '../core/utils.js';
import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import { initTestModal } from './testModal.js';
import { createStudentLog } from './studentLogs.js';

console.log('[logModal] HW-TABLE v6.7 (progress patch mode + SQLite-friendly logs patch)');

let editingLogSid = null;
let editingLogDate = null;
let logModalSnapshot = { notes: '', homeworkTable: [] };
let logModalServerSnapshot = { notes: '', homeworkTable: [] };
const PROGRESS_MANUAL_META_KEY = '__manualProgressMids';
const TEST_ASSIGN_DAILY_ITEMS_KEY = 'testAssignmentDailyTests';
const TEST_ASSIGN_ABSENCE_CARRYOVER_KEY = 'testAssignmentAbsenceCarryover';
const TEST_ASSIGN_ABSENCE_SOURCE_KEY = 'testAssignmentAbsenceSourceDate';
const VIDEO_PROGRESS_FINISHED_STATUSES = new Set(['done', 'skip']);
let logOpenSeq = 0;
let logModalReady = true;
let logModalCarriedTestAssignment = null;
let logKeybound = false; // Ctrl/Cmd+Enter 전역 바인딩 중복 방지
let logModalAccessMode = 'full';

function isContextMenuOnlyAccess() {
  return logModalAccessMode === 'all-students-readonly';
}

function pad2(n) { return String(n).padStart(2, '0'); }
function nowHHMM() {
  const d = new Date();
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}
function nowISO() { return new Date().toISOString(); }

function isFinishedVideoProgressStatus(status) {
  return VIDEO_PROGRESS_FINISHED_STATUSES.has(String(status || '').trim());
}

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
      const msg = data?.error || '다른 사용자가 저장 중입니다. 잠시 후 자동으로 다시 저장합니다.';
      lastErrMsg = msg;

      if (data?.retryable === false) {
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
      const msg = data?.error || '다른 사용자가 진도 저장 중입니다. 잠시 후 자동으로 다시 저장합니다.';
      lastErrMsg = msg;

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
async function clearVideoAssignmentForDateSid(date, sid) {
  const t = String(date || '').trim();
  const s = String(sid || '').trim();
  if (!t || !s) return;

  state.updates = state.updates || {};
  state.updates[t] = state.updates[t] || {};
  delete state.updates[t][s];
  if (/^\d+$/.test(s)) delete state.updates[t][String(Number(s))];
  if (!Object.keys(state.updates[t]).length) delete state.updates[t];

  const res = await fetch('/api/updates/patch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: t, sid: s, remove: true }),
  });
  if (!res.ok) throw new Error('video assignment clear failed');
}

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
    const entry = (all && all[t] && typeof all[t] === 'object' && all[t][s] && typeof all[t][s] === 'object')
      ? all[t][s]
      : {};
    return entry;
  }
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

async function fetchJSONCached(url, ttlMs = 2500) {
  const cache = window.__studentWorkFetchCache || (window.__studentWorkFetchCache = new Map());
  const now = Date.now();
  const hit = cache.get(url);
  if (hit && (now - hit.ts) < ttlMs) return hit.promise;

  const promise = fetch(url, { cache: 'no-store' }).then(async (res) => {
    if (!res.ok) return {};
    return await res.json().catch(() => ({}));
  });
  cache.set(url, { ts: now, promise });
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

async function hydrateLogHistoryForSid(sid) {
  const s = String(sid);
  if (!s) return false;

  try {
    const q = new URLSearchParams({ sid: s }).toString();
    const data = await fetchJSONCached(`/api/logs?${q}`);
    state.logs = state.logs || {};
    mergeDateSidMap(state.logs, data);
    window.logs = state.logs;
    return true;
  } catch (e) {
    console.warn('[logModal] hydrateLogHistoryForSid failed:', e);
    return false;
  }
}

async function hydrateProgressHistoryForSid(sid) {
  const s = String(sid);
  if (!s) return false;

  try {
    const q = new URLSearchParams({ sid: s }).toString();
    const data = await fetchJSONCached(`/api/progress?${q}`);
    state.progress = state.progress || {};
    mergeDateSidMap(state.progress, data);
    window.progressData = state.progress;
    return true;
  } catch (e) {
    console.warn('[logModal] hydrateProgressHistoryForSid failed:', e);
    return false;
  }
}

async function hydrateTodayLogFromServer(today, sid) {
  const t = String(today);
  const s = String(sid);

  try {
    const entry = await fetchLogEntryFromServer(t, s);
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
      padding:12px; border-radius:12px; border:1px solid #e5e7eb; background:#ffffff; color:#0f172a;
      box-shadow:0 12px 34px rgba(0,0,0,.34);
    }
    body.dark #logModal .log-card{ background:#0f172a; color:#e5e7eb; border-color:#334155; }

    #logModal .log-header-row{
      position:sticky;
      top:0;
      z-index:6;
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:12px;
      margin:-2px 0 10px;
      padding:2px 0 10px;
      background:#ffffff;
      border-bottom:1px solid rgba(226,232,240,.9);
    }
    body.dark #logModal .log-header-row{
      background:#0f172a;
      border-bottom-color:#334155;
    }
    #logModal h3{ margin:6px 0 0; font-size:36px; font-weight:900; line-height:1.12; }
    #logModal label{ display:block; margin:10px 0 8px; font-size:14px; }

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
      overflow-y:auto;
      resize:vertical;
      font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',sans-serif;
      font-size:28px;
      line-height:1.35;
    }
    #logModal.student-work-layout #logNotes{
      height:min(42vh, var(--student-log-notes-h, 416px));
      max-height:min(42vh, var(--student-log-notes-h, 416px));
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
      height:50px;
      min-height:50px;
      box-sizing:border-box;
      display:flex;
      align-items:center;
      padding:8px 10px;
      background:#f8fafc;
      border-bottom:1px solid #e5e7eb;
    }
    body.dark .hwHeader{
      background:#0b1220;
      border-bottom-color:#334155;
    }

    #hwBody{
      padding:10px 10px;
      display:flex;
      flex-direction:column;
      gap:12px;
    }

    .hwItem{ display:flex; flex-direction:column; gap:8px; }

    .hwTop{
      display:grid;
      grid-template-columns: 1.1fr 1fr 44px;
      gap:8px 12px;
      align-items:start;
    }
    .hwBot{
      display:grid;
      grid-template-columns: 1fr 1fr 44px;
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
      font-size:20px; font-weight:900; white-space:nowrap;
    }
    #logModal .actions #logCompleteBtn{ min-width:180px; }
    body.dark #logModal .actions button{ border-color:#334155; background:#1f2937; color:#e5e7eb; }
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

    .hwHeader{ position:relative; }
    .hwHeaderActions{
      width:100%;
      display:flex;
      justify-content:flex-end;
      margin-top:0;
    }
    .hw-insufficient-btn{
      min-height:34px;
      padding:0 10px;
      border:1px solid #93c5fd;
      border-radius:10px;
      background:#eff6ff;
      color:#1d4ed8;
      cursor:pointer;
      font-size:12px;
      font-weight:900;
    }
    .hw-insufficient-btn:hover{ background:#dbeafe; }
    .hw-insufficient-btn:disabled{ cursor:default; opacity:.5; }
    body.dark .hw-insufficient-btn{
      border-color:#365d91;
      background:#172554;
      color:#bfdbfe;
    }

    #homeworkInsufficientModal{
      position:fixed;
      inset:0;
      z-index:100010;
      display:flex;
      align-items:center;
      justify-content:center;
      padding:16px;
      background:rgba(2,6,23,.68);
    }
    #homeworkInsufficientModal[hidden]{ display:none !important; }
    .homework-insufficient-card{
      width:min(480px, calc(100vw - 32px));
      padding:20px;
      border:1px solid #dbe4ef;
      border-radius:14px;
      background:#fff;
      color:#0f172a;
      box-shadow:0 24px 70px rgba(0,0,0,.34);
    }
    .homework-insufficient-card h3{
      margin:0 0 12px;
      font-size:18px;
      font-weight:900;
      line-height:1.25;
    }
    .homework-insufficient-form{
      display:grid;
      grid-template-columns:minmax(0,1fr) auto;
      gap:8px;
      align-items:center;
    }
    .homework-insufficient-form input{
      width:100%;
      min-height:42px;
      box-sizing:border-box;
      padding:0 12px;
      border:1px solid #cbd5e1;
      border-radius:10px;
      background:#fff;
      color:#0f172a;
      outline:none;
      font:inherit;
      font-size:14px;
    }
    .homework-insufficient-form input:focus-visible{
      border-color:#3b82f6;
      box-shadow:0 0 0 3px rgba(59,130,246,.18);
    }
    .homework-insufficient-form button{
      min-height:42px;
      padding:0 15px;
      border:1px solid #2563eb;
      border-radius:10px;
      background:#2563eb;
      color:#fff;
      cursor:pointer;
      font:inherit;
      font-size:14px;
      font-weight:900;
    }
    .homework-insufficient-form button:disabled{ cursor:wait; opacity:.55; }
    .homework-insufficient-cancel{
      display:block;
      margin:10px auto 0;
      border:0;
      background:transparent;
      color:#64748b;
      cursor:pointer;
      font:inherit;
      font-size:12px;
      font-weight:800;
    }
    body.dark .homework-insufficient-card{
      border-color:#334155;
      background:#0f172a;
      color:#e5e7eb;
    }
    body.dark .homework-insufficient-form input{
      border-color:#475569;
      background:#0b1220;
      color:#e5e7eb;
    }
    body.dark .homework-insufficient-cancel{ color:#94a3b8; }

    @media (max-width:520px){
      #logModal{ align-items:stretch; }
      #logModal .log-card{
        width:100%; max-width:100vw; max-height:100dvh;
        padding:12px; border-radius:0;
      }
      #logModal .log-header-row{ display:block; }
      #logModal h3{
        margin:0; font-size:24px; line-height:1.2;
        word-break:keep-all; overflow-wrap:normal;
      }
      #logModal .actions{
        display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
        gap:8px; margin-top:12px;
      }
      #logModal .actions button{
        width:100%; min-width:0; height:44px;
        padding:0 10px; border-radius:10px; font-size:16px;
      }
      #logModal #logNotes{
        height:40vh; min-height:220px;
        font-size:20px; line-height:1.45;
      }
      #logProgress{ grid-template-columns:repeat(3,minmax(0,1fr)); }
      .hwTop{ grid-template-columns:minmax(0,1fr) minmax(0,1fr) 36px; }
      .hwBot{ grid-template-columns:minmax(0,1fr) minmax(0,1fr) 36px; }
      .thisCell{ grid-template-columns:1fr; }
    }
  `;
  document.head.appendChild(s);
}

function modalTemplateHTML() {
  return `
      <div id="logModal" aria-label="기록 팝업">
        <div class="log-card">
          <div class="log-header-row">
            <h3 id="logTitle">수업 기록</h3>
            <div class="actions" aria-label="기록 작업">
              <button type="button" id="logCompleteBtn">숙제 검사 완료</button>
              <button type="button" id="logSave">저장</button>
              <button type="button" id="logClose">닫기</button>
            </div>
          </div>

          <label class="notes-label">상담 기록<br><textarea id="logNotes" rows="16" placeholder=""></textarea></label>

          <label>진도</label>
          <div id="logProgress"></div>

          <label>숙제</label>
          <div id="hwWrap">
            <div id="hwBox">
              <div class="hwHeader" aria-label="숙제 헤더">
                <div class="hwHeaderActions">
                  <button type="button" id="hwInsufficientBtn" class="hw-insufficient-btn">숙제 미흡 알림</button>
                </div>
              </div>
              <div id="hwBody" aria-label="숙제 목록"></div>
            </div>

            <div class="hw-actions">
              <button type="button" id="hwAddRow">+ 추가</button>
            </div>
          </div>

        </div>
      </div>`;
}

function homeworkInsufficientModalTemplateHTML() {
  return `
      <div id="homeworkInsufficientModal" hidden aria-label="숙제 미흡 알림 입력">
        <section class="homework-insufficient-card" role="dialog" aria-modal="true" aria-labelledby="homeworkInsufficientTitle">
          <h3 id="homeworkInsufficientTitle">숙제 미흡 알림</h3>
          <form id="homeworkInsufficientForm" class="homework-insufficient-form">
            <input id="homeworkInsufficientInput" type="text" maxlength="300" autocomplete="off" placeholder="간단한 코멘트를 입력하세요" aria-label="숙제 미흡 코멘트">
            <button id="homeworkInsufficientConfirm" type="submit">확인</button>
          </form>
          <button id="homeworkInsufficientCancel" class="homework-insufficient-cancel" type="button">취소</button>
        </section>
      </div>`;
}

function ensureModal() {
  document.getElementById('logModal')?.remove();
  document.getElementById('homeworkInsufficientModal')?.remove();
  injectStyles();
  document.body.insertAdjacentHTML('beforeend', `${modalTemplateHTML()}${homeworkInsufficientModalTemplateHTML()}`);
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

function normHwRows(x) {
  if (!Array.isArray(x)) return [];
  return x.map(r => ({
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

    const phThis = (l.next || '').trim() ? l.next : (l.this || '');
    const hasTodayRow = i < a.length;

    out.push({
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

function updatePctBubble(wrapEl, value, { isPlaceholder = false } = {}) {
  if (!wrapEl) return;
  const bubble = wrapEl.querySelector('.pctBubble');
  if (!bubble) return;

  const v = snap10(value);
  bubble.textContent = `${v}%`;
  bubble.classList.toggle('is-ph', !!isPlaceholder);
  bubble.style.left = `${Math.max(0, Math.min(100, v))}%`;
}

function renderHwTable(mergedRows) {
  const host = $('hwBody');
  if (!host) return;

  const rows = Array.isArray(mergedRows) ? mergedRows : [];
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

  const itemHtml = (i) => {
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
    const delAttr = deleted ? '1' : '0';
    const hideStyle = deleted ? 'style="display:none"' : '';

    return `
      <div class="hwItem" data-idx="${i}" data-deleted="${delAttr}" ${hideStyle}>
        <div class="hwTop">
          <div class="hw-book">
            <input class="hwBook" type="text" value="${escapeAttr(bookVal)}" placeholder="">
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

          <div class="hwDelCell">
            <button type="button" class="hw-del-btn" title="삭제">✕</button>
          </div>
        </div>

        <div class="hwBot">
          <div class="hw-cmt">
            <input class="hwComment" type="text" value="${escapeAttr(cmtVal)}" placeholder="${escapeAttr(phCmt)}">
          </div>

          <div class="hw-next">
            <input class="hwNext" type="text" value="${escapeAttr(nextVal)}" placeholder="${escapeAttr(phNext)}">
          </div>

          <div class="hwDelCell">
            <button type="button" class="hw-del-btn" title="삭제">✕</button>
          </div>
        </div>
      </div>`;
  };

  host.innerHTML = Array.from({ length: n }, (_, i) => itemHtml(i)).join('');

  host.querySelectorAll('.pctWrap').forEach(wrap => {
    const range = wrap.querySelector('.hwPctRange');
    if (!range) return;
    const isPh = (wrap.dataset.empty === '1');
    updatePctBubble(wrap, range.value, { isPlaceholder: isPh });
  });
}

function addHwRow(bookCarry = '') {
  const host = $('hwBody');
  if (!host) return;

  host.insertAdjacentHTML('beforeend', `
    <div class="hwItem" data-idx="" data-deleted="0">
      <div class="hwTop">
        <div class="hw-book">
          <input class="hwBook" type="text" value="${escapeAttr(bookCarry)}" placeholder="">
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

        <div class="hwDelCell">
          <button type="button" class="hw-del-btn" title="삭제">✕</button>
        </div>
      </div>

      <div class="hwBot">
        <div class="hw-cmt">
          <input class="hwComment" type="text" value="" placeholder="">
        </div>

        <div class="hw-next">
          <input class="hwNext" type="text" value="" placeholder="">
        </div>

        <div class="hwDelCell">
          <button type="button" class="hw-del-btn" title="삭제">✕</button>
        </div>
      </div>
    </div>
  `);

  const lastWrap = host.querySelector('.hwItem:last-child .pctWrap');
  if (lastWrap) {
    const range = lastWrap.querySelector('.hwPctRange');
    updatePctBubble(lastWrap, range?.value ?? 0, { isPlaceholder: true });
  }
}

function collectHwTable() {
  const host = $('hwBody');
  if (!host) return [];
  const out = [];

  host.querySelectorAll('.hwItem').forEach(item => {
    if (item.dataset.deleted === '1' || item.style.display === 'none') return;

    const book = cleanHwText(item.querySelector('.hwBook')?.value);
    const thisHw = cleanHwText(item.querySelector('.hwThis')?.value);
    const comment = cleanHwText(item.querySelector('.hwComment')?.value);
    const next = cleanHwText(item.querySelector('.hwNext')?.value);

    const wrap = item.querySelector('.pctWrap');
    const range = item.querySelector('.hwPctRange');
    const raw = range ? snap10(range.value) : 0;

    const empty = (wrap?.dataset?.empty === '1');
    const pct = empty ? '' : String(raw);

    const row = { book, this: thisHw, pct, comment, next, _deleted: false };
    if (!isMeaningfulHwRow(row)) return;
    out.push(row);
  });

  return out;
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

/* hw flags PATCH */
async function markHwFlagsRemote(dateKey, sid, { assigned, checked }) {
  const date = dateKey || getAdminDate();
  const ksid = String(sid);
  const t = nowHHMM();

  const entry = {};
  if (assigned) {
    entry.hwAssigned = true;
    entry.hwAssignedAt = t;
  }
  if (checked) {
    entry.hwChecked = true;
    entry.hwCheckedAt = t;
    entry.hwAssigned = true;
    entry.hwAssignedAt = t;
  }

  const returned = await patchLogEntry(date, ksid, entry);

  state.logs = state.logs || {};
  state.logs[date] = state.logs[date] || {};
  state.logs[date][ksid] = returned
    ? returned
    : { ...(state.logs[date][ksid] || {}), ...entry };
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
  const matchedSid = Object.keys(day).find(key => String(key) === sidKey);
  const entry = matchedSid ? day[matchedSid] : null;
  return (entry && typeof entry === 'object') ? entry : {};
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

function buildLogSavePatch({ notesNow, hwRows, prevLog, doneFlag, summary }) {
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
  if (!doneFlag && prevDone) next.done = true;
  state.logs[date][sid] = next;
}

function setLogModalSnapshots(notes, homeworkTable) {
  logModalSnapshot = {
    notes,
    homeworkTable,
  };
  logModalServerSnapshot = {
    notes,
    homeworkTable: normalizeHwRowsForCompare(homeworkTable),
  };
}

export function initLogModal() {
  ensureModal();
  initTestModal();

  const logModal = $('logModal');
  const logTitle = $('logTitle');
  const logNotes = $('logNotes');
  const logSave = $('logSave');
  const logClose = $('logClose');
  const progEl = $('logProgress');
  const logComplete = $('logCompleteBtn');
  const homeworkInsufficientModal = $('homeworkInsufficientModal');
  const homeworkInsufficientForm = $('homeworkInsufficientForm');
  const homeworkInsufficientInput = $('homeworkInsufficientInput');
  const homeworkInsufficientConfirm = $('homeworkInsufficientConfirm');
  const homeworkInsufficientBtn = $('hwInsufficientBtn');
  const applyReadOnlyRecordAccess = () => {
    const readOnly = isContextMenuOnlyAccess();
    logModal.dataset.accessMode = logModalAccessMode;
    logNotes.readOnly = readOnly;
    logNotes.setAttribute('aria-readonly', readOnly ? 'true' : 'false');
    document.querySelectorAll('#hwBody input').forEach(input => {
      input.disabled = readOnly;
    });
    document.querySelectorAll('#hwBody .hw-del-btn').forEach(button => {
      button.hidden = readOnly;
    });
    const addRow = $('hwAddRow');
    if (addRow) addRow.hidden = readOnly;
    if (logComplete) logComplete.hidden = readOnly;
    if (homeworkInsufficientBtn) {
      homeworkInsufficientBtn.hidden = readOnly;
      homeworkInsufficientBtn.disabled = readOnly;
    }
    if (logSave) logSave.textContent = readOnly ? '영상 진도 저장' : '저장';
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

  const closeHomeworkInsufficientModal = ({ clearInput = true } = {}) => {
    if (homeworkInsufficientModal) homeworkInsufficientModal.hidden = true;
    if (clearInput && homeworkInsufficientInput) homeworkInsufficientInput.value = '';
    if (homeworkInsufficientConfirm) homeworkInsufficientConfirm.disabled = false;
  };

  const openHomeworkInsufficientModal = () => {
    if (isContextMenuOnlyAccess() || !logModalReady || !editingLogSid) return;
    if (!homeworkInsufficientModal || !homeworkInsufficientInput) return;
    homeworkInsufficientInput.value = '';
    homeworkInsufficientModal.hidden = false;
    requestAnimationFrame(() => homeworkInsufficientInput.focus());
  };

  const submitHomeworkInsufficientLog = async () => {
    const sid = String(editingLogSid || '').trim();
    const stu = state.students.find(x => String(x.id) === sid);
    const comment = String(homeworkInsufficientInput?.value || '').replace(/\s+/g, ' ').trim();
    if (!sid || !stu || !comment || !editingLogDate) return;
    if (homeworkInsufficientConfirm) homeworkInsufficientConfirm.disabled = true;
    try {
      const log = await createStudentLog({
        sid,
        studentName: String(stu.name || sid).trim() || sid,
        kind: 'homework_insufficient',
        comment,
        date: editingLogDate,
      });
      closeHomeworkInsufficientModal();
      window.dispatchEvent(new CustomEvent('student-log:created', { detail: log }));
      toast('학생 로그를 등록했습니다.');
    } catch (error) {
      console.error('[logModal] homework insufficient log failed:', error);
      if (homeworkInsufficientConfirm) homeworkInsufficientConfirm.disabled = false;
      alert(error?.message || '학생 로그를 등록하지 못했습니다.');
    }
  };

  homeworkInsufficientBtn?.addEventListener('click', openHomeworkInsufficientModal);
  homeworkInsufficientForm?.addEventListener('submit', (event) => {
    event.preventDefault();
    void submitHomeworkInsufficientLog();
  });
  homeworkInsufficientInput?.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    void submitHomeworkInsufficientLog();
  });
  homeworkInsufficientModal?.addEventListener('click', (event) => {
    if (event.target === homeworkInsufficientModal) closeHomeworkInsufficientModal();
  });
  homeworkInsufficientModal?.querySelector('#homeworkInsufficientCancel')?.addEventListener('click', () => {
    closeHomeworkInsufficientModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && homeworkInsufficientModal && !homeworkInsufficientModal.hidden) {
      event.preventDefault();
      closeHomeworkInsufficientModal();
    }
  }, true);

  if (!window.__hwDelDelegatedBound) {
    window.__hwDelDelegatedBound = true;
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('button.hw-del-btn');
      if (!btn) return;
      if (!btn.closest('#logModal')) return;
      if (isContextMenuOnlyAccess()) return;

      e.preventDefault();
      e.stopPropagation();

      const item = btn.closest('.hwItem');
      if (!item) return;

      item.remove();

      const host = document.getElementById('hwBody');
      if (host) {
        const hasRows = Array.from(host.querySelectorAll('.hwItem'))
          .some(x => x.style.display !== 'none');
        if (!hasRows) addHwRow('');
      }
    }, true);
  }

  document.getElementById('hwBody')?.addEventListener('input', (e) => {
    if (isContextMenuOnlyAccess()) return;
    const t = e.target;
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
    const openSeq = ++logOpenSeq;
    const tr = rowOrButton?.closest?.('tr[data-sid]') || rowOrButton;
    editingLogSid = tr?.dataset?.sid;
    editingLogDate = tr?.dataset?.date || getAdminDate();
    logModalAccessMode = opts.accessMode === 'all-students-readonly'
      ? 'all-students-readonly'
      : 'full';
    applyReadOnlyRecordAccess();

    const stu = state.students.find(x => String(x.id) === String(editingLogSid));
    if (!stu) { alert('학생 정보를 찾을 수 없습니다.'); return; }

    logTitle.textContent = `${stu.name} – ${stu.curriculum}`;
    const today = editingLogDate;
    const sid = String(editingLogSid);

    logModalReady = false;
    logModalSnapshot = { notes: '', homeworkTable: [] };
    logModalServerSnapshot = { notes: '', homeworkTable: [] };
    logModalCarriedTestAssignment = null;
    logModal.classList.toggle('student-work-layout', opts.layout === 'student-work');
    logNotes.value = '불러오는 중...';
    logNotes.disabled = true;
    if (logSave) logSave.disabled = true;
    if (logComplete) logComplete.disabled = true;
    progEl.innerHTML = '<div class="log-loading">진도 불러오는 중...</div>';
    renderHwTable([]);
    logModal.style.display = 'flex';
    resetLogModalScroll();

    await Promise.allSettled([
      hydrateTodayLogFromServer(today, sid),
      hydrateLogHistoryForSid(sid),
      hydrateProgressHistoryForSid(sid),
    ]);
    if (openSeq !== logOpenSeq || sid !== String(editingLogSid) || today !== editingLogDate) return;
    logNotes.disabled = false;
    if (logSave) logSave.disabled = false;
    if (logComplete) logComplete.disabled = false;
    logModalReady = true;

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

    const logEntry = (state.logs[today] || {})[sid] || {};
    const todayNotes = cleanHwText(logEntry.notes);
    let seededNotes = todayNotes;
    logModalCarriedTestAssignment = findAbsentTestCarryoverForLog(today, sid);

    // 오늘 특이사항이 비어 있으면, 가장 최근 특이사항을 실제 텍스트로 미리 채운다.
    if (!todayNotes.trim()) {
      for (let i = dates.length - 1; i >= 0; i--) {
        const d = dates[i];
        if (d >= today) continue;
        const prev = (state.logs[d] || {})[sid];
        const prevNotes = stripGeneratedTestAssignmentBlocks(cleanHwText(prev?.notes));
        if (prevNotes.trim()) {
          seededNotes = prevNotes;
          break;
        }
      }
    }

    const carriedNoteBlock = buildCarriedAssignmentNote(logModalCarriedTestAssignment?.items || []);
    if (carriedNoteBlock) {
      seededNotes = appendCarriedAssignmentNote(seededNotes, carriedNoteBlock);
    }

    logNotes.value = cleanHwText(seededNotes);
    logNotes.placeholder = '';

    const todayRows = entryHwRows(logEntry);

    let latestRows = [];
    let bookCarryRows = [];

    for (let i = dates.length - 1; i >= 0; i--) {
      const d = dates[i];
      if (d >= today) continue;
      const prev = (state.logs[d] || {})[sid];
      if (!prev) continue;

      if (Array.isArray(prev.homeworkTable) && prev.homeworkTable.length) {
        let rows = [];
        const first = prev.homeworkTable[0] || {};
        if (Object.prototype.hasOwnProperty.call(first, 'book') || Object.prototype.hasOwnProperty.call(first, 'this')) {
          rows = activeHwRows(prev.homeworkTable);
        } else {
          rows = normOldHwRows4(prev.homeworkTable);
        }

        if (latestRows.length === 0 && hasMeaningfulHwRows(rows)) latestRows = rows;

        if (bookCarryRows.length === 0 && rows.some(r => (r.book || '').trim())) {
          bookCarryRows = rows.map(r => ({ book: r.book, this: '', pct: '', comment: '', next: '', _deleted: false }));
        }

        if (latestRows.length && bookCarryRows.length) break;
      }

      if (typeof prev.homework === 'string' && prev.homework.trim()) {
        if (latestRows.length === 0) latestRows = [{ book: '', this: '', pct: '', comment: prev.homework.trim(), next: '', _deleted: false }];
        if (latestRows.length) break;
      }
    }

    const merged = mergeHwRows({ todayRows, latestRows, bookCarryRows });
    renderHwTable(merged);
    applyReadOnlyRecordAccess();

    logModalSnapshot = {
      // "최근 특이사항 미리 채움"은 오늘 서버값과는 다를 수 있으므로,
      // 변경 기준은 오늘 서버값을 스냅샷으로 둔다.
      notes: (todayNotes || '').trim(),
      homeworkTable: collectHwTable(),
    };
    logModalServerSnapshot = {
      notes: (logEntry.notes || '').trim(),
      homeworkTable: normalizeHwRowsForCompare(todayRows),
    };

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
    requestAnimationFrame(resetLogModalScroll);

    try {
      if (!opts.tooltipAlreadyShown && window.showStudentTooltipForSid) {
        window.showStudentTooltipForSid(editingLogSid, {
          variant: 'log',
          fixed: true,
          layout: opts.layout === 'student-work' ? 'student-work' : undefined,
        });
      }
    } catch (err) {
      console.warn('[logModal] show tooltip failed:', err);
    }
  }

  window.openRecordPopupForRow = openLogModalForRow;

  async function openStudentPopupsForRow(rowOrButton, opts = {}) {
    const tr = rowOrButton?.closest?.('tr[data-sid]') || rowOrButton;
    if (!tr?.dataset?.sid) return;

    if (window.showStudentPopupBackdrop) {
      try { window.showStudentPopupBackdrop(); } catch {}
    }
    try {
      window.showStudentTooltipForSid?.(tr.dataset.sid, {
        variant: 'log',
        fixed: true,
        layout: 'student-work',
      });
    } catch {}

    const logOptions = {
      layout: 'student-work',
      tooltipAlreadyShown: true,
    };
    if (opts.accessMode) logOptions.accessMode = opts.accessMode;

    const openTasks = [
      openLogModalForRow(tr, logOptions).catch((err) => {
        console.warn('[logModal] open log popup failed:', err);
      }),
    ];
    if (window.openVideoAssignmentPopupForRow) {
      openTasks.push(window.openVideoAssignmentPopupForRow(tr, { layout: 'student-work' }).catch((err) => {
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

  const close = () => {
    logOpenSeq += 1;
    closeHomeworkInsufficientModal();
    const wasUnified = logModal.classList.contains('student-work-layout');
    logModal.style.display = 'none';
    logModal.classList.remove('student-work-layout');
    editingLogSid = null;
    editingLogDate = null;
    logModalReady = false;
    logModalSnapshot = { notes: '', homeworkTable: [] };
    logModalServerSnapshot = { notes: '', homeworkTable: [] };
    logModalCarriedTestAssignment = null;
    logModalAccessMode = 'full';
    try { if (window.hideStudentTooltip) window.hideStudentTooltip(); } catch {}
    if (wasUnified) {
      try { if (window.closeVideoAssignmentPopup) window.closeVideoAssignmentPopup(); } catch {}
      try { if (window.closeTestAssignmentPopup) window.closeTestAssignmentPopup(); } catch {}
    }
    try { if (window.hideStudentPopupBackdrop) window.hideStudentPopupBackdrop(); } catch {}
  };
  window.closeStudentWorkPopups = close;
  logClose.addEventListener('click', close);

  function isCurrentLogProgressAllDone() {
    const cells = Array.from(document.querySelectorAll('#logProgress .progress-cell[data-mid]'));
    return cells.length > 0 && cells.every(cell => isFinishedVideoProgressStatus(cell.dataset.state));
  }

  function clearVideoAssignmentIfAllDone(saveResult) {
    if (!saveResult?.allProgressDone) return false;
    if (typeof window.hasManualVideoAssignmentSelection === 'function' && window.hasManualVideoAssignmentSelection()) {
      return false;
    }
    if (typeof window.clearVideoAssignmentPopupForCurrent === 'function') {
      window.clearVideoAssignmentPopupForCurrent();
    }
    return true;
  }

  async function saveBase(doneFlag) {
    const today = editingLogDate || getAdminDate();
    const sid = String(editingLogSid);

    const prevLog = (state.logs?.[today] || {})[sid] || {};
    const prevDone =
      prevLog?.done === true || prevLog?.done === 'true' || prevLog?.done === 1 || prevLog?.done === '1';

    const changedProg = collectChangedProgressPatch();
    await saveChangedProgressPatch(today, sid, changedProg);

    if (isContextMenuOnlyAccess()) {
      return { allProgressDone: false };
    }

    const oldTotal = collectPriorProgressByMid(today, sid);
    const summary = summarizeProgressPatch(changedProg, oldTotal);

    const hwRows = collectHwTable();
    const notesNow = cleanHwText(logNotes.value);
    const { entry, clearKeys, base, contentChanged } = buildLogSavePatch({
      notesNow,
      hwRows,
      prevLog,
      doneFlag,
      summary,
    });

    let returned = null;
    if (Object.keys(entry).length || clearKeys.length) {
      entry.updatedAt = nowISO();
      returned = await patchLogEntry(today, sid, entry, clearKeys, contentChanged ? { base } : {});
    }

    applyLogSaveResult({ date: today, sid, entry, clearKeys, returned, doneFlag, prevDone });

    const allProgressDone = isCurrentLogProgressAllDone();
    if (allProgressDone) {
      await clearVideoAssignmentForDateSid(today, sid);
    }

    setLogModalSnapshots(notesNow, hwRows);

    return { allProgressDone };
  }

  async function saveRecordPopupForCurrent() {
    if (!logModalReady) throw new Error('기록 팝업을 불러오는 중입니다.');
    return await saveBase(false);
  }

  window.saveRecordPopup = saveRecordPopupForCurrent;

  async function reapplyCarriedTestAssignmentForCurrent() {
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

  logSave.addEventListener('click', async () => {
    try {
      const saveResult = await saveRecordPopupForCurrent();
      const unified = logModal.classList.contains('student-work-layout');
      if (unified && typeof window.saveVideoAssignmentPopup === 'function') {
        await window.saveVideoAssignmentPopup({
          showPopup: false,
          refresh: false,
          forceEmpty: clearVideoAssignmentIfAllDone(saveResult),
        });
      }
      if (unified && typeof window.saveTestAssignmentPopup === 'function') {
        await window.saveTestAssignmentPopup({ showPopup: false, refresh: false });
      }
      if (!isContextMenuOnlyAccess()) {
        await reapplyCarriedTestAssignmentForCurrent();
      }
      toast(isContextMenuOnlyAccess() ? '영상 진도 저장됨' : '수업 기록 저장됨');
      close();
      document.dispatchEvent(new CustomEvent('admin:refresh'));
    } catch (err) {
      if (err?.message) {
        alert(err.message);
        return;
      }
      console.error(err);
      alert('저장 실패');
    }
  });

  logComplete.addEventListener('click', async () => {
    try {
      const saveResult = await saveRecordPopupForCurrent();
      const unified = logModal.classList.contains('student-work-layout');
      if (unified && typeof window.saveVideoAssignmentPopup === 'function') {
        await window.saveVideoAssignmentPopup({
          showPopup: false,
          refresh: false,
          forceEmpty: clearVideoAssignmentIfAllDone(saveResult),
        });
      }
      if (unified && typeof window.saveTestAssignmentPopup === 'function') {
        await window.saveTestAssignmentPopup({ showPopup: false, refresh: false });
      }
      await reapplyCarriedTestAssignmentForCurrent();
      const today = editingLogDate || getAdminDate();
      await markHwFlagsRemote(today, editingLogSid, { assigned: true, checked: true });
      toast(`숙제 검사 완료 (${nowHHMM()})`);
      close();
      document.dispatchEvent(new CustomEvent('admin:refresh'));
    } catch (err) {
      if (err?.message) {
        alert(err.message);
        return;
      }
      console.error(err);
      alert('숙제 검사 완료 저장 실패');
    }
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

  function applyAutoWhenReady(watchByMid) {
    let tries = 0;
    const tick = () => {
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

    const date = tr?.dataset?.date || editingLogDate || getAdminDate();
    const raw = await fetchWatchForSid(sid, date);

    const watchByMid = {};
    Object.keys(raw).forEach(k => { watchByMid[String(k)] = raw[k]; });

    requestAnimationFrame(() => applyAutoWhenReady(watchByMid));
  }, false);
})();
