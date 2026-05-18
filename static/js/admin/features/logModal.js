// /js/admin/features/logModal.js
/* global fetch */

import { $, toast, postJSON } from '../core/utils.js';
import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import { initTestModal } from './testModal.js';

console.log('[logModal] HW-TABLE v6.7 (progress patch mode + SQLite-friendly logs patch)');

let editingLogSid = null;
let editingLogDate = null;
let logModalSnapshot = { notes: '', homeworkTable: [] };
let logModalServerSnapshot = { notes: '', homeworkTable: [] };
const PROGRESS_MANUAL_META_KEY = '__manualProgressMids';
let logOpenSeq = 0;
let logModalReady = true;
let logKeybound = false; // Ctrl/Cmd+Enter 전역 바인딩 중복 방지

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
      resize:vertical;
      font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic','맑은 고딕',sans-serif;
      font-size:28px;
      line-height:1.35;
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
    .hwHeaderTop{ grid-template-columns: 1.1fr 1fr 44px; }
    .hwHeaderBot{ grid-template-columns: 1fr 1fr 44px; margin-top:8px; }

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
                <div class="hwHeaderTop">
                  <div class="h">교재</div>
                  <div class="h">이번 숙제 / 진행률</div>
                  <div class="h h-del"></div>
                </div>
                <div class="hwHeaderBot">
                  <div class="h">코멘트</div>
                  <div class="h">다음 숙제</div>
                  <div class="h h-del"></div>
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

function ensureModal() {
  document.getElementById('logModal')?.remove();
  injectStyles();
  document.body.insertAdjacentHTML('beforeend', modalTemplateHTML());
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
  const resetLogModalScroll = () => {
    const card = logModal?.querySelector('.log-card');
    if (card) card.scrollTop = 0;
    if (logModal) logModal.scrollTop = 0;
    if (logNotes) logNotes.scrollTop = 0;
  };

  if (!window.__hwDelDelegatedBound) {
    window.__hwDelDelegatedBound = true;
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('button.hw-del-btn');
      if (!btn) return;
      if (!btn.closest('#logModal')) return;

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
    const t = e.target;
    if (!t.classList.contains('hwPctRange')) return;
    const wrap = t.closest('.pctWrap');
    if (!wrap) return;
    wrap.dataset.empty = '0';
    updatePctBubble(wrap, t.value, { isPlaceholder: false });
  });

  document.getElementById('hwBody')?.addEventListener('change', (e) => {
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

    const stu = state.students.find(x => String(x.id) === String(editingLogSid));
    if (!stu) { alert('학생 정보를 찾을 수 없습니다.'); return; }

    logTitle.textContent = `${stu.name} – ${stu.curriculum}`;
    const today = editingLogDate;
    const sid = String(editingLogSid);

    logModalReady = false;
    logModalSnapshot = { notes: '', homeworkTable: [] };
    logModalServerSnapshot = { notes: '', homeworkTable: [] };
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

    // 오늘 특이사항이 비어 있으면, 가장 최근 특이사항을 실제 텍스트로 미리 채운다.
    if (!todayNotes.trim()) {
      for (let i = dates.length - 1; i >= 0; i--) {
        const d = dates[i];
        if (d >= today) continue;
        const prev = (state.logs[d] || {})[sid];
        const prevNotes = cleanHwText(prev?.notes);
        if (prevNotes.trim()) {
          seededNotes = prevNotes;
          break;
        }
      }
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

    const openTasks = [
      openLogModalForRow(tr, { layout: 'student-work', tooltipAlreadyShown: true }).catch((err) => {
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
  });

  const close = () => {
    logOpenSeq += 1;
    const wasUnified = logModal.classList.contains('student-work-layout');
    logModal.style.display = 'none';
    logModal.classList.remove('student-work-layout');
    editingLogSid = null;
    editingLogDate = null;
    logModalReady = false;
    logModalSnapshot = { notes: '', homeworkTable: [] };
    logModalServerSnapshot = { notes: '', homeworkTable: [] };
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
    return cells.length > 0 && cells.every(cell => String(cell.dataset.state || 'none') === 'done');
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

    const changedProg = {};
    document.querySelectorAll('#logProgress .progress-cell').forEach(cell => {
      const st = cell.dataset.state || 'none';
      const initial = cell.dataset.initial || 'none';
      const mid = String(cell.dataset.mid);

      if (st !== initial) changedProg[mid] = st;
    });

    if (!state.progress) state.progress = {};
    state.progress[today] = state.progress[today] || {};
    if (!state.progress[today][sid] || typeof state.progress[today][sid] !== 'object') {
      state.progress[today][sid] = {};
    }

    if (Object.keys(changedProg).length) {
      const mergedProgress = await patchProgressEntry(today, sid, changedProg);
      state.progress[today][sid] = mergedProgress || {};
    }

    const oldDates = Object.keys(state.progress).filter(d => d < today);
    const oldTotal = {};
    oldDates.forEach(d => {
      Object.entries(state.progress[d]?.[sid] || {}).forEach(([mid, st]) => {
        const key = String(mid);
        if (key.startsWith('__') || key === 'tests') return;
        oldTotal[key] = st;
      });
    });
    const label = (mid, st) => {
      if (st === 'none') return null;
      const v = state.videos.find(v => String(v.mid) === String(mid));
      if (!v) return null;
      const base = `${v.chapter}차시`;
      return st === 'done' ? base : (st === 'interrupted' ? `${base}(중단)` : (st === 'skip' ? `${base}(건너뜀)` : null));
    };
    const summary = Object.entries(changedProg)
      .filter(([mid, st]) => oldTotal[String(mid)] !== st && st !== 'none')
      .map(([mid, st]) => label(mid, st))
      .filter(Boolean)
      .join(', ');

    const hwRows = collectHwTable();
    const notesNow = cleanHwText(logNotes.value);
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

    if (summary) entry.topic = summary;
    if (doneFlag) entry.done = true;

    if (doneFlag) {
      entry.leaveTime = nowHHMM();
      entry.leaveAt = nowISO();
    }

    let returned = null;
    if (Object.keys(entry).length || clearKeys.length) {
      entry.updatedAt = nowISO();
      returned = await patchLogEntry(today, sid, entry, clearKeys, contentChanged ? { base } : {});
    }

    state.logs = state.logs || {};
    state.logs[today] = state.logs[today] || {};
    if (returned) {
      state.logs[today][sid] = returned;
    } else if (Object.keys(entry).length || clearKeys.length) {
      const next = { ...(state.logs[today][sid] || {}), ...entry };
      clearKeys.forEach(k => { delete next[String(k)]; });
      if (!doneFlag && prevDone) next.done = true;
      state.logs[today][sid] = next;
    }

    const allProgressDone = isCurrentLogProgressAllDone();
    if (allProgressDone) {
      await clearVideoAssignmentForDateSid(today, sid);
    }

    logModalSnapshot = {
      notes: notesNow,
      homeworkTable: hwRows,
    };
    logModalServerSnapshot = {
      notes: notesNow,
      homeworkTable: normalizeHwRowsForCompare(hwRows),
    };

    return { allProgressDone };
  }

  async function saveRecordPopupForCurrent() {
    if (!logModalReady) throw new Error('기록 팝업을 불러오는 중입니다.');
    return await saveBase(false);
  }

  window.saveRecordPopup = saveRecordPopupForCurrent;

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
      toast('수업 기록 저장됨');
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

    const raw = await fetchWatchForSid(sid);

    const watchByMid = {};
    Object.keys(raw).forEach(k => { watchByMid[String(k)] = raw[k]; });

    requestAnimationFrame(() => applyAutoWhenReady(watchByMid));
  }, false);
})();
