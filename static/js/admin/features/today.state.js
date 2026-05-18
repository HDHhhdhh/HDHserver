// /js/admin/features/today.state.js
// today.js 분리본(상태/서버/헬퍼)
// - weekend-slots / today_order / attendance / contact / arrive-time / logs.patch
// - plannedTimeBase/plannedTimeFor, slot label 계산, 정렬키 등
//
// ✅ FIX (하원 취소 지원)
// - 기존 방어 로직이 "done:false"까지 무시해서 하원 취소가 안 되는 문제 수정
//   -> patch가 done을 명시(done:false 포함)하면 그 값을 존중
//   -> 단, patch가 done을 언급하지 않을 때만(prev done/하원흔적) done 유지
//
// ✅ FIX (arrive-time URL)
// - Flask bp_api_arrive_time가 url_prefix 없이 등록된 경우 실제 경로는 /arrive-time 이므로
//   ARRIVE_URL을 /arrive-time 으로 맞춤 (기존 /api/arrive-time 불일치 가능성)

import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';

const CT = { 'Content-Type': 'application/json' };
const WCHR = '일월화수목금토';

// ─────────────────────────────────────────────
// 기본 예정 등원시간 매핑
// ─────────────────────────────────────────────
export const ARRIVE_TIME_MAP = {
  '토1': '13:00', '토2': '18:00',
  '일1': '13:00', '일2': '18:00',
  '월1': '13:00', '월2': '18:00',
  '화1': '13:00', '화2': '18:00',
  '수1': '13:00', '수2': '18:00',
  '목1': '13:00', '목2': '18:00',
  '금1': '13:00', '금2': '18:00',
};

// ─────────────────────────────────────────────
// 공통 유틸
// ─────────────────────────────────────────────
function safeJSONParse(raw, fallback) {
  try { return raw ? JSON.parse(raw) : fallback; } catch { return fallback; }
}
export function nowHHMM() {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}
export function nowISO() { return new Date().toISOString(); }

export function yoilOf(dateStr) { return WCHR[new Date(dateStr).getDay()]; }
export function getStudent(sid) {
  return (state.students || []).find(x => String(x.id) === String(sid));
}
export function dayValues(stu) {
  return Object.keys(stu)
    .filter(k => /^day\d+$/.test(k) && stu[k])
    .sort((a, b) => parseInt(a.slice(3), 10) - parseInt(b.slice(3), 10))
    .map(k => String(stu[k]));
}
export function hasWeekday(stu, wchr) {
  return dayValues(stu).some(v => String(v).startsWith(wchr));
}

export function truthy(v) {
  return v === true || v === 'true' || v === 1 || v === '1';
}

export function minutesFromTimeStr(str) {
  if (!str) return Number.POSITIVE_INFINITY;
  const m = String(str).trim().match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return Number.POSITIVE_INFINITY;
  const hh = parseInt(m[1], 10);
  const mm = parseInt(m[2], 10);
  if (!Number.isFinite(hh) || !Number.isFinite(mm)) return Number.POSITIVE_INFINITY;
  return hh * 60 + mm;
}

// ─────────────────────────────────────────────
// logs.patch (유실 방지)
// ─────────────────────────────────────────────
export async function patchLog(dateKey, sid, entry, clearKeys = null) {
  const body = { date: dateKey, sid: String(sid), entry: entry || {} };
  if (Array.isArray(clearKeys) && clearKeys.length) body.__clear = clearKeys;

  const res = await fetch('/api/logs/patch', {
    method: 'POST',
    headers: CT,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = '';
    try { msg = await res.text(); } catch {}
    throw new Error(`logs/patch failed: ${res.status} ${msg}`);
  }

  // ── 서버가 JSON을 반환하면(가능한 경우) 그걸 우선 사용
  // (204/빈 응답이면 그냥 무시하고 아래 로컬 merge로 감)
  let serverEntry = null;
  try {
    const txt = await res.text();
    if (txt) {
      const obj = JSON.parse(txt);
      // 형태 유연 대응: {entry:{...}} / {data:{...}} / {...}
      if (obj && typeof obj === 'object') {
        if (obj.entry && typeof obj.entry === 'object') serverEntry = obj.entry;
        else if (obj.data && typeof obj.data === 'object') serverEntry = obj.data;
        else serverEntry = obj;
      }
    }
  } catch { /* ignore */ }

  // 로컬 state 즉시 반영
  state.logs = state.logs || {};
  state.logs[dateKey] = state.logs[dateKey] || {};
  const ksid = String(sid);

  const prev = state.logs[dateKey][ksid] || {};
  const hasServerEntry = !!(serverEntry && typeof serverEntry === 'object');
  const patch = hasServerEntry ? serverEntry : (entry || {});
  const next = hasServerEntry ? { ...serverEntry } : { ...prev, ...patch };

  // clearKeys 반영
  if (Array.isArray(clearKeys)) {
    for (const k of clearKeys) delete next[String(k)];
  }

  // ✅ 핵심: "done 상태에서 부분 patch"로 done이 사라지는 케이스 방지
  // 단, "하원 취소(done:false)"를 지원하려면 done을 명시한 patch는 존중해야 함.
  const clearsDone = Array.isArray(clearKeys) && clearKeys.map(String).includes('done');
  const patchMentionsDone = Object.prototype.hasOwnProperty.call(patch, 'done');
  const prevWasDone = truthy(prev?.done);

  // 하원 흔적: prev 또는 merge된 next 둘 중 하나라도 있으면 "하원 상태로 봄"
  const hasLeaveHint =
    !!(prev?.leaveTime || prev?.leaveAt || prev?.doneTime || next?.leaveTime || next?.leaveAt || next?.doneTime);

  // (A) patch가 done을 언급하지 않으면: 기존 done/하원흔적 있으면 done 유지
  //     (부분 patch가 done을 떨어뜨리는 문제 방지)
  if (!clearsDone && !patchMentionsDone) {
    if (prevWasDone || hasLeaveHint) next.done = true;
  }

  const patchMentionsArchived = Object.prototype.hasOwnProperty.call(patch, 'archived');
  if (patchMentionsDone && truthy(next.done) && !patchMentionsArchived) {
    delete next.archived;
  }

  // (B) ✅ 하원 취소 지원:
  //     patch가 done을 명시(done:false 포함)하면 그 값 그대로 둔다.
  //     (기존처럼 done:false를 강제로 true로 바꾸지 않음)

  state.logs[dateKey][ksid] = next;
}

export function getLeaveTime(dateKey, sid) {
  const e = state.logs?.[dateKey]?.[String(sid)];
  return (e?.leaveTime || e?.doneTime || '').trim();
}
export async function setLeaveTimeRemote(dateKey, sid, value) {
  const v = (value || '').trim();
  if (!v) {
    await patchLog(dateKey, sid, {}, ['leaveTime', 'leaveAt', 'doneTime']);
    return;
  }
  await patchLog(dateKey, sid, { leaveTime: v, leaveAt: nowISO() });
}

export function isHwAssigned(dateKey, sid) {
  const e = state.logs?.[dateKey]?.[String(sid)];
  return !!(e && truthy(e.hwAssigned));
}
export function isHwChecked(dateKey, sid) {
  const e = state.logs?.[dateKey]?.[String(sid)];
  return !!(e && truthy(e.hwChecked));
}
export async function setHomeworkCheckedRemote(dateKey, sid, checked) {
  const on = !!checked;
  if (on) {
    const t = nowHHMM();
    await patchLog(dateKey, sid, {
      hwChecked: true,
      hwCheckedAt: t,
      hwAssigned: true,
      hwAssignedAt: t,
    });
    return;
  }
  await patchLog(dateKey, sid, {
    hwChecked: false,
    hwAssigned: false,
  }, ['hwCheckedAt', 'hwAssignedAt']);
}
export async function setLogFlagRemote(dateKey, sid, field, checked) {
  await patchLog(dateKey, sid, { [field]: checked ? true : false });
}

// ─────────────────────────────────────────────
// weekend-slots
// ─────────────────────────────────────────────
export let WEEKEND_SLOTS = {}; // { "YYYY-MM-DD": { sid: [1,2] | 1 } }

export async function loadWeekendSlots() {
  try {
    WEEKEND_SLOTS = await fetch('/api/weekend-slots', { cache: 'no-store' }).then(r => r.json());
    if (!WEEKEND_SLOTS || typeof WEEKEND_SLOTS !== 'object') WEEKEND_SLOTS = {};
  } catch {
    WEEKEND_SLOTS = {};
  }
}

export function parseSlotsFromText(txt) {
  const nums = (String(txt || '').match(/[1-2]/g) || []).map(n => parseInt(n, 10));
  return Array.from(new Set(nums)).filter(n => n === 1 || n === 2).sort((a, b) => a - b);
}

export function getSlots(dateStr, sid) {
  const raw = WEEKEND_SLOTS?.[dateStr]?.[String(sid)];

  if (Array.isArray(raw)) {
    return raw
      .map(n => parseInt(n, 10))
      .filter(n => Number.isInteger(n) && (n === 1 || n === 2))
      .sort((a, b) => a - b);
  }
  if (Number.isInteger(raw) && (raw === 1 || raw === 2)) return [raw];

  // fallback: 학생 기본 요일 데이터
  const w = yoilOf(dateStr);
  const stu = getStudent(sid);
  if (!stu) return [];

  const nums = dayValues(stu)
    .filter(v => String(v).startsWith(w))
    .map(v => {
      const m = String(v).match(/\d+/);
      return m ? parseInt(m[0], 10) : null;
    })
    .filter(n => Number.isInteger(n) && (n === 1 || n === 2));

  if (nums.length) return Array.from(new Set(nums)).sort((a, b) => a - b);
  return [];
}

export function labelFor(dateStr, sid) {
  const w = yoilOf(dateStr);
  const slots = getSlots(dateStr, sid);
  if (slots.length) return slots.map(n => `${w}${n}`).join('·');

  const stu = getStudent(sid);
  if (!stu) return w;

  const dvals = dayValues(stu).filter(v => String(v).startsWith(w));
  if (!dvals.length) return w;

  const nums = dvals
    .map(v => {
      const m = String(v).match(/\d+/);
      return m ? parseInt(m[0], 10) : null;
    })
    .filter(n => Number.isInteger(n) && (n === 1 || n === 2));

  if (!nums.length) return w;
  const uniq = Array.from(new Set(nums)).sort((a, b) => a - b);
  return uniq.map(n => `${w}${n}`).join('·');
}

export function sortKeyFor(dateStr, sid) {
  const w = yoilOf(dateStr);
  if (w === '토' || w === '일') {
    const slots = getSlots(dateStr, sid);
    if (slots.length) return Math.min(...slots);
  }
  return 99;
}

function plannedKeyFor(dateStr, stu) {
  const w = yoilOf(dateStr);
  if (!stu) return w;

  const slots = getSlots(dateStr, stu.id);
  if (slots.length) return `${w}${Math.min(...slots)}`;

  const dvals = dayValues(stu).filter(v => String(v).startsWith(w));
  if (dvals.length) {
    const raw = dvals[0];
    const m = String(raw).match(/\d+/);
    const num = m ? m[0] : '';
    return num ? `${w}${num}` : w;
  }
  return w;
}

function plannedTimeFromStudent(dateStr, stu) {
  if (!stu) return '';
  const w = yoilOf(dateStr);

  for (let i = 1; i <= 5; i++) {
    const dayVal = (stu[`day${i}`] || '').trim();
    if (!dayVal) continue;
    if (!dayVal.startsWith(w)) continue;

    const t = (stu[`visitTime${i}`] || '').trim();
    if (t) return t;
  }
  return '';
}

// ✅ 기존 표시용: 학생 visitTime 우선 + 없으면 매핑
export function plannedTimeBase(dateStr, sid) {
  const stu = getStudent(sid);
  if (!stu) return '';

  const fromStu = plannedTimeFromStudent(dateStr, stu);
  if (fromStu) return fromStu;

  const key = plannedKeyFor(dateStr, stu);
  if (ARRIVE_TIME_MAP[key]) return ARRIVE_TIME_MAP[key];

  if (key && key.length === 1) {
    const k1 = `${key}1`;
    if (ARRIVE_TIME_MAP[k1]) return ARRIVE_TIME_MAP[k1];
  }

  const ch = key ? key[0] : '';
  if (ch && ARRIVE_TIME_MAP[ch]) return ARRIVE_TIME_MAP[ch];

  return '';
}

// ✅ 구분 변경 시 “1타임=13:00 / 2타임=18:00”만 쓰는 기본값(visitTime 무시)
export function plannedTimeSlotDefault(dateStr, sid) {
  const w = yoilOf(dateStr);

  const slots = getSlots(dateStr, sid);
  if (slots.length) {
    const key = `${w}${Math.min(...slots)}`;
    return ARRIVE_TIME_MAP[key] || '';
  }

  // 슬롯이 없으면 요일 기본값(평일 18:00, 주말은 13:00로 떨어지게 w1 우선)
  const k1 = `${w}1`;
  if (ARRIVE_TIME_MAP[k1]) return ARRIVE_TIME_MAP[k1];
  const k2 = `${w}2`;
  if (ARRIVE_TIME_MAP[k2]) return ARRIVE_TIME_MAP[k2];

  return '';
}

// ✅ [추가] "지금 편집한 라벨 텍스트"로 슬롯을 뽑아 등원시간 기본값 결정
// - 평일 연강(월1월2) -> (월2) 같은 편집은 기존 getSlots()가 못 따라가서 이 함수가 필요함
export function plannedTimeSlotDefaultFromLabel(dateStr, sid, labelText) {
  const w = yoilOf(dateStr);

  // 라벨에서 1/2 슬롯 추출 (예: "월2" / "월1·월2" / "월1월2" / "2" 다 됨)
  const slots = parseSlotsFromText(labelText);
  if (slots.length) {
    const key = `${w}${Math.min(...slots)}`;
    return ARRIVE_TIME_MAP[key] || '';
  }

  // 라벨에 숫자가 없으면 기존 로직으로 fallback
  return plannedTimeSlotDefault(dateStr, sid);
}

// ─────────────────────────────────────────────
// today_order (드래그 순서)
// ─────────────────────────────────────────────
let _orderMap = null; // { "YYYY-MM-DD": ["sid", ...] }

export async function loadOrderMap(options = {}) {
  if (_orderMap && !options.force) return _orderMap;
  try { _orderMap = await fetch('/api/today_order', { cache: 'no-store' }).then(r => r.json()); }
  catch { _orderMap = {}; }
  return _orderMap;
}
export function applySavedOrder(list, dateKey) {
  const saved = (_orderMap?.[dateKey] || []).map(String);
  if (!saved.length) return list;

  const byId = new Map(list.map(s => [String(s.id), s]));
  const used = new Set();
  const ordered = [];

  for (const id of saved) {
    const it = byId.get(id);
    if (it) { ordered.push(it); used.add(id); }
  }
  for (const s of list) if (!used.has(String(s.id))) ordered.push(s);
  return ordered;
}
export async function saveOrder(dateKey, newOrderIds) {
  let latest;
  try { latest = await fetch('/api/today_order', { cache: 'no-store' }).then(r => r.json()); }
  catch { latest = {}; }
  latest[dateKey] = newOrderIds.map(String);
  await fetch('/api/today_order', { method: 'POST', headers: CT, body: JSON.stringify(latest) });
  _orderMap = latest;
}
export async function clearTodayOrder(dateKey) {
  try {
    const latest = await fetch('/api/today_order', { cache: 'no-store' }).then(r => r.json()).catch(() => ({}));
    if (latest && latest[dateKey]) {
      delete latest[dateKey];
      await fetch('/api/today_order', { method: 'POST', headers: CT, body: JSON.stringify(latest) });
      _orderMap = latest;
    }
  } catch {}
}

export async function saveWeekendSlotsFromLabel(sid, labelText, dateKey) {
  const dateStr = dateKey || getAdminDate();

  let weekend = {};
  try { weekend = await fetch('/api/weekend-slots', { cache: 'no-store' }).then(r => r.json()); } catch {}

  const perDay = weekend[dateStr] || {};
  const slots = parseSlotsFromText(labelText);

  if (slots.length) perDay[String(sid)] = slots;
  else delete perDay[String(sid)];

  await fetch('/api/weekend-slots', {
    method: 'POST',
    headers: CT,
    body: JSON.stringify({ [dateStr]: perDay }),
  });

  await clearTodayOrder(dateStr);
  await loadWeekendSlots();
  await loadOrderMap();
}

// ─────────────────────────────────────────────
// attendance (서버 + 로컬백업)
// ─────────────────────────────────────────────
const ATT_URL = '/api/attendance';
const ATT_PREFIX = 'attend_check:';
const _attCache = new Map();      // dateKey -> { sid:1, ... }

function loadAttendMapLocal(dateKey) {
  return safeJSONParse(localStorage.getItem(ATT_PREFIX + dateKey), {});
}
function saveAttendMapLocal(dateKey, map) {
  try { localStorage.setItem(ATT_PREFIX + dateKey, JSON.stringify(map || {})); } catch {}
}
async function fetchAttendDay(dateKey) {
  try {
    const qs = new URLSearchParams({ date: dateKey });
    const obj = await fetch(`${ATT_URL}?${qs.toString()}`, { cache: 'no-store' }).then(r => r.json());
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) return obj;
  } catch {}
  return null;
}
export async function ensureAttendLoaded(dateKey, options = {}) {
  if (_attCache.has(dateKey) && !options.force) return;
  const server = await fetchAttendDay(dateKey);
  if (server) { _attCache.set(dateKey, server); saveAttendMapLocal(dateKey, server); }
  else { const local = loadAttendMapLocal(dateKey); _attCache.set(dateKey, local); }
}
function loadAttendMap(dateKey) {
  if (_attCache.has(dateKey)) return _attCache.get(dateKey);
  return loadAttendMapLocal(dateKey);
}
export function setAttended(dateKey, sid, checked) {
  const m = loadAttendMap(dateKey) || {};
  const k = String(sid);
  if (checked) m[k] = 1;
  else delete m[k];
  _attCache.set(dateKey, m);
  saveAttendMapLocal(dateKey, m);
}
export function isAttended(dateKey, sid) {
  const m = loadAttendMap(dateKey) || {};
  return !!m[String(sid)];
}

// ─────────────────────────────────────────────
// contact (서버 + 로컬백업)
// ─────────────────────────────────────────────
const CONTACT_URL = '/api/contact';
const CONTACT_PREFIX = 'contact_check:';
const _contactCache = new Map();

function loadContactMapLocal(dateKey) {
  return safeJSONParse(localStorage.getItem(CONTACT_PREFIX + dateKey), {});
}
function saveContactMapLocal(dateKey, map) {
  try { localStorage.setItem(CONTACT_PREFIX + dateKey, JSON.stringify(map || {})); } catch {}
}
async function fetchContactDay(dateKey) {
  try {
    const qs = new URLSearchParams({ date: dateKey });
    const obj = await fetch(`${CONTACT_URL}?${qs.toString()}`, { cache: 'no-store' }).then(r => r.json());
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) return obj;
  } catch {}
  return null;
}
export async function ensureContactLoaded(dateKey, options = {}) {
  if (_contactCache.has(dateKey) && !options.force) return;
  const server = await fetchContactDay(dateKey);
  if (server) { _contactCache.set(dateKey, server); saveContactMapLocal(dateKey, server); }
  else { const local = loadContactMapLocal(dateKey); _contactCache.set(dateKey, local); }
}
function loadContactMap(dateKey) {
  if (_contactCache.has(dateKey)) return _contactCache.get(dateKey);
  return loadContactMapLocal(dateKey);
}
export function setContacted(dateKey, sid, checked) {
  const m = loadContactMap(dateKey) || {};
  const k = String(sid);
  if (checked) m[k] = 1;
  else delete m[k];
  _contactCache.set(dateKey, m);
  saveContactMapLocal(dateKey, m);
}
export function isContacted(dateKey, sid) {
  const m = loadContactMap(dateKey) || {};
  return !!m[String(sid)];
}

// ─────────────────────────────────────────────
// arrive-time override (서버 + 로컬백업)
// ─────────────────────────────────────────────
// ✅ 서버 bp_api_arrive_time 경로가 /arrive-time 로 등록된 경우에 맞춤
const ARRIVE_URL = '/arrive-time';
const ARRIVE_PREFIX = 'arrive_time:';
const _arriveCache = new Map();      // dateKey -> { sid:"HH:MM", ... }

function loadArriveMapLocal(dateKey) {
  return safeJSONParse(localStorage.getItem(ARRIVE_PREFIX + dateKey), {});
}
function saveArriveMapLocal(dateKey, map) {
  try { localStorage.setItem(ARRIVE_PREFIX + dateKey, JSON.stringify(map || {})); } catch {}
}
function normalizeDayMap(obj, dateKey) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return null;

  const keys = Object.keys(obj);
  const looksLikeSidMap = keys.length === 0 || keys.every(k => /^\d+$/.test(String(k)));
  if (looksLikeSidMap) return obj;

  if (dateKey && obj[dateKey] && typeof obj[dateKey] === 'object' && !Array.isArray(obj[dateKey])) {
    return obj[dateKey];
  }
  return null;
}
async function fetchArriveDay(dateKey) {
  try {
    const qs = new URLSearchParams({ date: dateKey });
    const obj = await fetch(`${ARRIVE_URL}?${qs.toString()}`, { cache: 'no-store' }).then(r => r.json());
    const day = normalizeDayMap(obj, dateKey);
    if (day) return day;
  } catch {}
  return null;
}
async function fetchArriveAll() {
  try {
    const obj = await fetch(ARRIVE_URL, { cache: 'no-store' }).then(r => r.json());
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) return obj;
  } catch {}
  return null;
}
export async function ensureArriveLoaded(dateKey, options = {}) {
  if (_arriveCache.has(dateKey) && !options.force) return;

  const day = await fetchArriveDay(dateKey);
  if (day) { _arriveCache.set(dateKey, day); saveArriveMapLocal(dateKey, day); return; }

  const all = await fetchArriveAll();
  if (all && all[dateKey] && typeof all[dateKey] === 'object' && !Array.isArray(all[dateKey])) {
    const m = all[dateKey];
    _arriveCache.set(dateKey, m);
    saveArriveMapLocal(dateKey, m);
    return;
  }

  const local = loadArriveMapLocal(dateKey);
  _arriveCache.set(dateKey, local);
}
function loadArriveMap(dateKey) {
  if (_arriveCache.has(dateKey)) return _arriveCache.get(dateKey);
  return loadArriveMapLocal(dateKey);
}
export function getArriveOverride(dateKey, sid) {
  const m = loadArriveMap(dateKey) || {};
  return m[String(sid)] ?? '';
}
export function setArriveOverride(dateKey, sid, value) {
  const m = loadArriveMap(dateKey) || {};
  const k = String(sid);
  const v = (value || '').trim();
  if (v) m[k] = v;
  else delete m[k];

  _arriveCache.set(dateKey, m);
  saveArriveMapLocal(dateKey, m);
}
export function plannedTimeFor(dateStr, sid) {
  const ov = (getArriveOverride(dateStr, sid) || '').trim();
  if (ov) return ov;
  return plannedTimeBase(dateStr, sid);
}
export function plannedMinutesFor(dateStr, sid) {
  return minutesFromTimeStr(plannedTimeFor(dateStr, sid));
}

// ─────────────────────────────────────────────
// 완료 기록 모으기
// - 선택한 날짜 기준
// - done == true && archived != true
// ─────────────────────────────────────────────
export function collectUnarchivedLogsByDate(dateKey) {
  const logs = state.logs || {};
  const date = String(dateKey || '').trim();
  if (!date) return [];

  const out = [];
  const dayMap = logs[date] || {};
  for (const sid of Object.keys(dayMap)) {
    const e = dayMap[sid] || {};
    const done = truthy(e.done);
    const archived = truthy(e.archived);
    if (!done || archived) continue;
    out.push([String(sid), e, date]);
  }

  out.sort((a, b) => {
    const aTime = String(a[1]?.leaveAt || a[1]?.updatedAt || a[1]?.doneTime || '').trim();
    const bTime = String(b[1]?.leaveAt || b[1]?.updatedAt || b[1]?.doneTime || '').trim();
    const timeCmp = bTime.localeCompare(aTime);
    if (timeCmp !== 0) return timeCmp;

    return String(a[0]).localeCompare(String(b[0]));
  });

  return out;
}

export function collectUnarchivedLogsExceptDate(dateKey) {
  const logs = state.logs || {};
  const selectedDate = String(dateKey || '').trim();
  if (!selectedDate) return [];

  const out = [];
  for (const date of Object.keys(logs).sort()) {
    if (date === selectedDate) continue;

    const dayMap = logs[date] || {};
    if (!dayMap || typeof dayMap !== 'object') continue;

    for (const sid of Object.keys(dayMap)) {
      const e = dayMap[sid] || {};
      const done = truthy(e.done);
      const archived = truthy(e.archived);
      if (!done || archived) continue;
      out.push([String(sid), e, date]);
    }
  }

  out.sort((a, b) => {
    const dateCmp = String(b[2]).localeCompare(String(a[2]));
    if (dateCmp !== 0) return dateCmp;
    return String(a[0]).localeCompare(String(b[0]));
  });

  return out;
}

// Backward compatibility: 기존 호출부 이름 유지
export function collectUnarchivedDoneLogsAllDates() {
  return collectUnarchivedLogsByDate(getAdminDate());
}
