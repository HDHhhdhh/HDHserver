/* student.js – 단일 플레이어 + 재생 목록 + 자료 다운로드 + 설정 패널 + 건의사항 제출 + 공지모달 + 오늘 자동배정 보정
   + (추가) 마지막 재생 기억 + 로컬 진행도(완주) 저장 + Kollus postMessage 대응(가능할 때만)
   + (표시개선) 파일명 표시에서 UUID/타임스탬프 접두어 제거(표시 전용, 실제 URL/경로는 그대로)
   + (Kollus 연동) VG Controller 브릿지: 플레이어 이벤트(progress/ready/done) → 우리 postMessage 포맷으로 재발행
*/
function resolveStudentId() {
  const lastSeg = decodeURIComponent(location.pathname.split("/").pop() || "");
  // /student/123 처럼 마지막 세그먼트가 숫자면 그걸 sid로 사용
  if (/^\d+$/.test(lastSeg)) return lastSeg;

  // 그 외(정적 html 등)는 ?sid=123 에서 읽어옴
  const q = new URLSearchParams(location.search);
  const fromQuery = q.get("sid");
  if (fromQuery) return decodeURIComponent(fromQuery);

  // 그래도 없으면 일단 마지막 세그먼트 그대로 (완전 비상용)
  return lastSeg || "";
}

// 전역으로 공유해서 아래 IIFE들에서 같이 씀
window.__STU_SID__ = resolveStudentId();
try {
  if (window.__STU_SID__) localStorage.setItem("studentSid", String(window.__STU_SID__));
} catch {}

const STUDENT_SEARCH_HELP_TEXT = '초성/영타 검색 · 띄어쓰기=AND';
const STUDENT_HANGUL_INITIALS = [
  '\u3131', '\u3132', '\u3134', '\u3137', '\u3138', '\u3139', '\u3141', '\u3142', '\u3143',
  '\u3145', '\u3146', '\u3147', '\u3148', '\u3149', '\u314a', '\u314b', '\u314c', '\u314d', '\u314e',
];
const STUDENT_HANGUL_MEDIALS = [
  '\u314f', '\u3150', '\u3151', '\u3152', '\u3153', '\u3154', '\u3155',
  '\u3156', '\u3157', '\u3158', '\u3159', '\u315a', '\u315b', '\u315c',
  '\u315d', '\u315e', '\u315f', '\u3160', '\u3161', '\u3162', '\u3163',
];
const STUDENT_HANGUL_FINALS = [
  '', '\u3131', '\u3132', '\u3133', '\u3134', '\u3135', '\u3136',
  '\u3137', '\u3139', '\u313a', '\u313b', '\u313c', '\u313d', '\u313e',
  '\u313f', '\u3140', '\u3141', '\u3142', '\u3144', '\u3145', '\u3146',
  '\u3147', '\u3148', '\u314a', '\u314b', '\u314c', '\u314d', '\u314e',
];
const STUDENT_DUBEOLSIK_COMPAT_BY_KEY = new Map([
  ['r', '\u3131'], ['R', '\u3132'], ['s', '\u3134'], ['e', '\u3137'], ['E', '\u3138'],
  ['f', '\u3139'], ['a', '\u3141'], ['q', '\u3142'], ['Q', '\u3143'], ['t', '\u3145'],
  ['T', '\u3146'], ['d', '\u3147'], ['w', '\u3148'], ['W', '\u3149'], ['c', '\u314a'],
  ['z', '\u314b'], ['x', '\u314c'], ['v', '\u314d'], ['g', '\u314e'],
  ['k', '\u314f'], ['o', '\u3150'], ['i', '\u3151'], ['O', '\u3152'], ['j', '\u3153'],
  ['p', '\u3154'], ['u', '\u3155'], ['P', '\u3156'], ['h', '\u3157'], ['y', '\u315b'],
  ['n', '\u315c'], ['b', '\u3160'], ['m', '\u3161'], ['l', '\u3163'],
]);
const STUDENT_COMPOUND_INITIALS = new Map([
  ['\u3133', '\u3131\u3145'],
  ['\u3135', '\u3134\u3148'],
  ['\u3136', '\u3134\u314e'],
  ['\u313a', '\u3139\u3131'],
  ['\u313b', '\u3139\u3141'],
  ['\u313c', '\u3139\u3142'],
  ['\u313d', '\u3139\u3145'],
  ['\u313e', '\u3139\u314c'],
  ['\u313f', '\u3139\u314d'],
  ['\u3140', '\u3139\u314e'],
  ['\u3144', '\u3142\u3145'],
]);
const STUDENT_COMPOUND_VOWEL_BY_PAIR = new Map([
  ['\u3157\u314f', '\u3158'], ['\u3157\u3150', '\u3159'], ['\u3157\u3163', '\u315a'],
  ['\u315c\u3153', '\u315d'], ['\u315c\u3154', '\u315e'], ['\u315c\u3163', '\u315f'],
  ['\u3161\u3163', '\u3162'],
]);
const STUDENT_COMPOUND_FINAL_BY_PAIR = new Map(
  Array.from(STUDENT_COMPOUND_INITIALS, ([compound, expanded]) => [expanded, compound])
);
const STUDENT_INITIAL_INDEX = new Map(STUDENT_HANGUL_INITIALS.map((ch, index) => [ch, index]));
const STUDENT_MEDIAL_INDEX = new Map(STUDENT_HANGUL_MEDIALS.map((ch, index) => [ch, index]));
const STUDENT_FINAL_INDEX = new Map(STUDENT_HANGUL_FINALS.map((ch, index) => [ch, index]));

function studentSearchPlaceholder(label = '검색') {
  return window.SearchUtils?.searchPlaceholder?.(label) || `${label} (${STUDENT_SEARCH_HELP_TEXT})`;
}

function studentNormalizeSearch(value) {
  if (window.SearchUtils?.normalizeSearch) return window.SearchUtils.normalizeSearch(value);
  return Array.from(String(value || ''))
    .map(ch => STUDENT_COMPOUND_INITIALS.get(ch) || ch)
    .join('')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/\s+/g, '');
}

function studentSearchTerms(value) {
  if (window.SearchUtils?.searchTerms) return window.SearchUtils.searchTerms(value);
  return String(value || '').trim().split(/\s+/).map(studentNormalizeSearch).filter(Boolean);
}

function studentIsCompatVowel(ch) {
  return STUDENT_MEDIAL_INDEX.has(ch);
}

function studentDubeolsikKeysToCompatJamo(value) {
  return Array.from(String(value || ''))
    .map(ch => STUDENT_DUBEOLSIK_COMPAT_BY_KEY.get(ch) || ch)
    .join('');
}

function studentComposeCompatJamo(value) {
  const chars = Array.from(String(value || ''));
  let out = '';

  for (let i = 0; i < chars.length;) {
    const initialIndex = STUDENT_INITIAL_INDEX.get(chars[i]);
    if (initialIndex == null || !studentIsCompatVowel(chars[i + 1])) {
      out += chars[i] || '';
      i += 1;
      continue;
    }

    let medial = chars[i + 1];
    let consumed = 2;
    const compoundVowel = STUDENT_COMPOUND_VOWEL_BY_PAIR.get(`${medial}${chars[i + 2] || ''}`);
    if (compoundVowel) {
      medial = compoundVowel;
      consumed = 3;
    }

    const medialIndex = STUDENT_MEDIAL_INDEX.get(medial);
    let finalIndex = 0;
    const finalOne = chars[i + consumed];
    if (STUDENT_FINAL_INDEX.has(finalOne)) {
      const finalTwo = chars[i + consumed + 1];
      const afterFinalTwo = chars[i + consumed + 2];
      const compoundFinal = STUDENT_COMPOUND_FINAL_BY_PAIR.get(`${finalOne}${finalTwo || ''}`);

      if (studentIsCompatVowel(finalTwo)) {
        finalIndex = 0;
      } else if (compoundFinal && !studentIsCompatVowel(afterFinalTwo)) {
        finalIndex = STUDENT_FINAL_INDEX.get(compoundFinal) || 0;
        consumed += 2;
      } else {
        finalIndex = STUDENT_FINAL_INDEX.get(finalOne) || 0;
        consumed += 1;
      }
    }

    out += String.fromCharCode(0xac00 + ((initialIndex * 21 + medialIndex) * 28) + finalIndex);
    i += consumed;
  }

  return out;
}

function studentSearchTermVariants(value) {
  const raw = String(value || '');
  const variants = [studentNormalizeSearch(raw)];
  if (/^[A-Za-z]+$/.test(raw) && raw.length >= 2) {
    const jamo = studentDubeolsikKeysToCompatJamo(raw);
    const lowerJamo = studentDubeolsikKeysToCompatJamo(raw.toLowerCase());
    variants.push(
      studentNormalizeSearch(jamo),
      studentNormalizeSearch(studentComposeCompatJamo(jamo)),
      studentNormalizeSearch(lowerJamo),
      studentNormalizeSearch(studentComposeCompatJamo(lowerJamo)),
    );
  }
  return Array.from(new Set(variants.filter(Boolean)));
}

function studentSearchTermVariantGroups(value) {
  return String(value || '')
    .trim()
    .split(/\s+/)
    .map(studentSearchTermVariants)
    .filter(group => group.length);
}

function studentHangulInitials(value) {
  return Array.from(String(value || '')).map(ch => {
    const code = ch.charCodeAt(0);
    if (code < 0xac00 || code > 0xd7a3) return ch;
    return STUDENT_HANGUL_INITIALS[Math.floor((code - 0xac00) / 588)] || ch;
  }).join('');
}

function studentSearchKeyForText(value) {
  if (window.SearchUtils?.searchKeyForText) return window.SearchUtils.searchKeyForText(value);
  const raw = String(value || '');
  return studentNormalizeSearch([raw, studentHangulInitials(raw)].join(' '));
}

function studentMatchesSearchKey(key, query) {
  if (window.SearchUtils?.matchesSearchKey) return window.SearchUtils.matchesSearchKey(key, query);
  const termGroups = studentSearchTermVariantGroups(query);
  if (!termGroups.length) return true;
  const hay = String(key || '');
  return termGroups.every(group => group.some(term => hay.includes(term)));
}


// ===== [중요] HTML <head>에 아래 스크립트를 추가해야 VG Controller가 동작합니다 =====
// <script src="https://file.kollus.com/vgcontroller/vg-controller-client.latest.min.js" crossorigin="anonymous"></script>

window.todayLocalKey = function () {
  const now = new Date();
  const tz = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - tz).toISOString().slice(0, 10);
};

(() => {
  /* ───────────── 공통 util ───────────── */
  const $ = id => document.getElementById(id);
  const CT = { "Content-Type": "application/json" };
  const LS_TOKEN_ACTIVE = "studentToken";
  const LS_TOKEN_MASTER = "studentTokenMaster";
  const sid = window.__STU_SID__ || decodeURIComponent(location.pathname.split("/").pop());
  let currentMid = null;

  function todayLocalKey() {
    const now = new Date();
    const tz = now.getTimezoneOffset() * 60000;
    return new Date(now.getTime() - tz).toISOString().slice(0, 10);
  }

  // (표시 전용) 파일명에서 UUID/긴 타임스탬프 접두 제거
  function cleanDisplayName(name) {
    const base = String(name || "").split("/").pop();
    const s1 = base.replace(/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}[\s_-]*/i, "");
    const s2 = s1.replace(/^[0-9]{13,17}[\s_-]*/, "");
    const s3 = s2.replace(/^[0-9a-z]{20,}[\s_-]*/i, "");
    return s3 || base;
  }

  // 전역 캐시
  let vidsCache = [];        // /api/videos
  let updatesCache = {};     // /api/updates
  let stuCache = null;       // 내 학생 객체 (stu)
  let absentByDateCache = {}; // { "YYYY-MM-DD": [sid,...] }
  let logsCache = {};         // /api/logs 전체
  let assignedTestsCache = [];
  let courseBlocked = false;
  let courseBlockMessage = "수업일이 아닌 것 같습니다. 선생님께 문의주세용 ^_^";
  let courseVideosCompleted = false;
  const COURSE_VIDEOS_COMPLETED_MESSAGE = "진도를 마쳤습니다. 필요한 영상이 있으면 선생님께 문의 주세요 ^_^";
  window.__ASSIGNED_TESTS__ = [];

  /* ───────────── 진행도 저장/복구(로컬) ───────────── */
  const LSKeys = {
    lastMid: (sid) => `stu:${sid}:last_video_mid`,
    prog: (sid, mid) => `stu:${sid}:watch:${mid}`, // {last, dur, completed, updatedAt}
  };

  function getProgress(mid) {
    try {
      const raw = localStorage.getItem(LSKeys.prog(sid, mid));
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  }

  function normalizeProgressRecord(entry) {
    if (!entry || typeof entry !== 'object') entry = {};

    const last = Math.max(0, Number(entry.last) || 0);
    const dur = Math.max(0, Number(entry.dur) || 0);
    const updatedAt = Math.max(0, Number(entry.updatedAt) || 0);
    const completed = !!entry.completed || (dur > 0 && last >= Math.max(dur - 1, Math.floor(dur * 0.90)));

    return {
      last: Math.floor(last),
      dur: Math.floor(dur),
      completed,
      updatedAt,
    };
  }

  function mergeProgressRecord(base, patch) {
    const a = normalizeProgressRecord(base);
    const b = normalizeProgressRecord(patch);

    const last = Math.max(a.last, b.last);
    const dur = Math.max(a.dur, b.dur);
    const completed = a.completed || b.completed || (dur > 0 && last >= Math.max(dur - 1, Math.floor(dur * 0.90)));

    return {
      last,
      dur,
      completed,
      updatedAt: Math.max(a.updatedAt, b.updatedAt, Date.now()),
    };
  }

  function storeProgress(mid, next) {
    try { localStorage.setItem(LSKeys.prog(sid, mid), JSON.stringify(next)); } catch { }
  }

  function setProgress(mid, patch, options = {}) {
    const cur = getProgress(mid) || {};
    const next = mergeProgressRecord(cur, patch);
    storeProgress(mid, next);
    try { updateListCompletionBadges(); } catch { }

    if (options.sync !== false) enqueueSync(mid);
    return next;
  }
  function setLastMid(mid) {
    try { localStorage.setItem(LSKeys.lastMid(sid), mid); } catch { }
  }
  function getLastMid() {
    try { return localStorage.getItem(LSKeys.lastMid(sid)) || null; } catch { return null; }
  }

  function fmtPct(n) {
    if (!Number.isFinite(n)) return '';
    return `${Math.max(0, Math.min(100, Math.round(n)))}%`;
  }

  /* ───────────── 서버 동기화 (/api/watch) ───────────── */
  const SYNC_DEBOUNCE_MS = 1500;      // 너무 자주 쏘지 않도록 디바운스
  const _syncTimers = new Map();      // mid -> timeout id
  const _lastSent = new Map();        // mid -> { last, dur, completed, updatedAt } (보낸 스냅샷)

  function mergeServerWatchIntoLocal(watchMap) {
    if (!watchMap || typeof watchMap !== 'object') return;

    Object.entries(watchMap).forEach(([mid, rec]) => {
      const key = String(mid || '').trim();
      if (!key) return;
      const next = mergeProgressRecord(getProgress(key), rec);
      storeProgress(key, next);
      _lastSent.set(key, {
        last: next.last | 0,
        dur: next.dur | 0,
        completed: !!next.completed,
        updatedAt: next.updatedAt | 0,
      });
    });

    try { updateListCompletionBadges(); } catch { }
  }

  function enqueueSync(mid) {
    if (_syncTimers.has(mid)) clearTimeout(_syncTimers.get(mid));
    const t = setTimeout(() => doSync(mid), SYNC_DEBOUNCE_MS);
    _syncTimers.set(mid, t);
  }

  async function doSync(mid, options = {}) {
    _syncTimers.delete(mid);
    const prog = getProgress(mid);
    if (!prog) return;
    const now = Date.now();
    const snap = {
      last: prog.last | 0,
      dur: prog.dur | 0,
      completed: !!prog.completed,
      updatedAt: (prog.updatedAt | 0) || now
    };

    const prev = _lastSent.get(mid);
    if (prev && prev.last === snap.last && prev.dur === snap.dur && prev.completed === snap.completed) return;

    const canonicalSid = String(stuCache?.id || sid || '').trim();
    const payload = {
      date: todayLocalKey(),
      sid: canonicalSid,
      mid,
      last: snap.last,
      dur: snap.dur,
      completed: snap.completed,
      updatedAt: snap.updatedAt
    };

    try {
      const res1 = await fetch('/api/watch', {
        method: 'POST', headers: CT, body: JSON.stringify(payload), keepalive: !!options.keepalive
      });
      if (res1.ok) _lastSent.set(mid, snap);
    } catch (e) {
      console.warn('[watch sync] failed', e);
    }
  }

  async function flushSyncQueue(options = {}) {
    const mids = new Set(_syncTimers.keys());
    if (currentMid) mids.add(currentMid);
    if (!mids.size) return;

    mids.forEach(mid => {
      try { clearTimeout(_syncTimers.get(mid)); } catch { }
      _syncTimers.delete(mid);
    });

    await Promise.allSettled([...mids].map(mid => doSync(mid, options)));
  }

  function flushCurrentWatch() {
    flushSyncQueue({ keepalive: true });
  }

  window.addEventListener('beforeunload', flushCurrentWatch);
  window.addEventListener('pagehide', flushCurrentWatch, { capture: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushCurrentWatch();
  });

  /* ───────────── 설정 패널 & 다크모드 ───────────── */
  const setBtn = $('setBtn');
  const setPanel = $('setPanel');
  const darkTgl = $('darkToggle');

  setBtn?.addEventListener('click', e => {
    e.stopPropagation();
    setPanel?.classList.toggle('open');
  });
  document.addEventListener('click', e => {
    if (!setPanel || !setBtn) return;
    if (!setPanel.contains(e.target) && !setBtn.contains(e.target)) {
      setPanel.classList.remove('open');
    }
  });

  if (localStorage.theme === "dark") {
    document.body.classList.add("dark");
    if (darkTgl) darkTgl.checked = true;
  }
  if (darkTgl) {
    darkTgl.onchange = () => {
      document.body.classList.toggle("dark", darkTgl.checked);
      localStorage.theme = darkTgl.checked ? 'dark' : 'light';
    };
  }

  function essayBandOf(level) {
    if (level === '상' || level === '중상') return '상';
    if (level === '중') return '중';
    return '하';
  }

  /* ───────────── 헤더 시계 ───────────── */
  const clk = $('clock');
  if (clk) {
    const fmt2 = n => String(n).padStart(2, '0');
    const tick = () => {
      const d = new Date(), w = '일월화수목금토'[d.getDay()];
      const date = `${d.getFullYear()}.${fmt2(d.getMonth() + 1)}.${fmt2(d.getDate())}`;
      const time = `${fmt2(d.getHours())}<span class="colon">:</span>${fmt2(d.getMinutes())}`;
      clk.innerHTML = `
        <span class="date">${date}</span>
        <span class="day">(${w})</span>
        <span class="time">${time}</span>
      `;
    };
    tick();
    setInterval(tick, 60 * 1000);
  }

  /* ───────────── 데이터 로드 ───────────── */
  async function loadInitialData() {
    const today = todayLocalKey();
    const watchReq = fetch(`/api/watch/latest?sid=${encodeURIComponent(sid)}`)
      .then(r => r.json()).catch(() => ({}));

    try {
      const q = new URLSearchParams({ sid: String(sid), date: today }).toString();
      const res = await fetch(`/api/student/bootstrap?${q}`, { cache: 'no-store' });
      if (res.ok) {
        const b = await res.json();
        return [
          Array.isArray(b.students) ? b.students : (b.student ? [b.student] : []),
          Array.isArray(b.videos) ? b.videos : [],
          b.updates || {},
          b.materials || {},
          b.assigns || {},
          b.absent || {},
          b.logs || {},
          await watchReq,
          {
            courseBlocked: b.courseBlocked === true,
            blockMessage: b.blockMessage || '',
            courseVideosCompleted: b.courseVideosCompleted === true,
            assignedTests: Array.isArray(b.assignedTests) ? b.assignedTests : [],
          },
        ];
      }
      if (res.status !== 404) throw new Error(`bootstrap ${res.status}`);
    } catch (err) {
      console.warn('[student] bootstrap failed, using legacy load:', err);
    }

    return Promise.all([
      fetch("/api/students").then(r => r.json()),
      fetch("/api/videos").then(r => r.json()),
      fetch("/api/updates").then(r => r.json()).catch(() => ({})),
      fetch("/api/materials").then(r => r.json()).catch(() => ({})),
      fetch("/api/mat-assign").then(r => r.json()).catch(() => ({})),
      fetch("/api/absent").then(r => r.json()).catch(() => ({})),
      fetch(`/api/logs?date=${encodeURIComponent(today)}`).then(r => r.json()).catch(() => ({})),
      watchReq,
      { courseBlocked: false, blockMessage: '', courseVideosCompleted: false, assignedTests: [] },
    ]);
  }

  loadInitialData().then(init).catch(err => alert("데이터 로드 실패\n" + err));

  /* ───────────── 자동배정 헬퍼 ───────────── */

  // 오늘 요일 기준으로 정규 수업 있는지
  function hasRegularToday(stu, todayStr) {
    if (!stu) return false;
    const wchr = '일월화수목금토'[new Date(todayStr).getDay()];
    const vals = Object.keys(stu)
      .filter(k => /^day\d+$/.test(k) && stu[k])
      .map(k => String(stu[k]));
    return vals.some(v => String(v).startsWith(wchr));
  }

  // /api/absent 응답에서 by_date 부분만 뽑기
  function normalizeAbsentByDate(payload) {
    if (!payload || typeof payload !== 'object') return {};
    if (payload.by_date && typeof payload.by_date === 'object') return payload.by_date;
    if (payload.byDate && typeof payload.byDate === 'object') return payload.byDate;
    return payload;
  }

  // “오늘 학생표 기준으로 자동배정 허용해도 되는지” 판단
  function isAllowedTodayForAutoAssign(sidVal, today) {
    if (!stuCache) return false;
    const sidStr = String(sidVal);

    // 1) 오늘 요일에 정규 수업이 있어야 함
    if (!hasRegularToday(stuCache, today)) return false;

    // 2) 결석 리스트에 있으면 안 됨
    const absList = (absentByDateCache[today] || []);
    const absSet = new Set(absList.map(String));
    if (absSet.has(sidStr)) return false;

    // 3) 오늘 로그가 done=true면 자유의 몸 → 안 됨
    // 3) 오늘 로그가 archived=true면 안 됨 (done은 허용!)
    const logsToday = (logsCache || {})[today] || {};
    const entry = logsToday[sidStr] || logsToday[sidVal] || {};
    const archived = entry.archived === true || entry.archived === 'true';
    if (archived) return false;

    return true;

  }

  // updates 전체에서 이 sid의 "마지막 배정" 찾기 (sid 키 숫자/문자 둘 다 허용)
  function getLastAssignedVideosForSid(sidVal, updatesObj) {
    const sidStr = String(sidVal);
    const sidNum = Number.isFinite(+sidVal) ? String(+sidVal) : null;
    const days = Object.keys(updatesObj || {}).sort();
    for (let i = days.length - 1; i >= 0; i--) {
      const day = days[i];
      const perDay = updatesObj[day] || {};
      const raw = perDay[sidStr] ?? (sidNum != null ? perDay[sidNum] : undefined);
      if (!raw) continue;
      if (Array.isArray(raw)) return raw.slice();
      if (raw && Array.isArray(raw.videos)) return raw.videos.slice();
    }
    return null;
  }

  // “오늘 학생표에 있는 애”만 자동 배정 (자동배정 로직 내부에서만 today 허용 체크)
  async function ensureTodayAssignmentIfMissing() {
    const today = todayLocalKey();
    const dayMap = updatesCache[today] || {};
    const sidStr = String(sid);
    const sidNum = Number.isFinite(+sid) ? String(+sid) : null;

    const rawToday = dayMap[sidStr] ?? (sidNum != null ? dayMap[sidNum] : undefined);
    const hasToday = Array.isArray(rawToday)
      ? rawToday.length > 0
      : Array.isArray(rawToday?.videos)
        ? rawToday.videos.length > 0
        : (rawToday !== undefined); // 혹시라도 값만 있으면 "있다"로 간주

    if (hasToday) return false;

    // 오늘 학생표 대상이 아니면 자동 배정 금지 (수동 배정은 보여줘야 함)
    if (!isAllowedTodayForAutoAssign(sid, today)) return false;

    const last = getLastAssignedVideosForSid(sid, updatesCache);
    if (!last || !last.length) return false;

    const nextUpdates = { ...(updatesCache || {}) };
    const todayMap = { ...(nextUpdates[today] || {}) };
    todayMap[sidStr] = last.map(String);
    nextUpdates[today] = todayMap;

    await fetch('/api/updates/patch', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify({ date: today, sid: sidStr, videos: last.map(String) })
    });

    updatesCache = nextUpdates;
    return true;
  }

  /* ───────────── [추가] updates에서 배정 읽기 공통 함수 ───────────── */
  function getAssignedVideos(updatesObj, day, sidVal) {
    const dayMap = (updatesObj && updatesObj[day]) ? updatesObj[day] : {};
    const k1 = String(sidVal);
    const k2 = Number.isFinite(+sidVal) ? String(+sidVal) : null;

    const raw = dayMap[k1] ?? (k2 != null ? dayMap[k2] : undefined);

    if (Array.isArray(raw)) return raw.map(String);
    if (raw && Array.isArray(raw.videos)) return raw.videos.map(String);
    return [];
  }

  function videoChapterRank(v) {
    const raw = String(v?.chapter ?? '').trim();
    const n = Number.parseFloat(raw.replace(/[^0-9.]/g, ''));
    return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
  }

  function isSupplementVideo(v) {
    if (v?.isExtraAssignment === true) return true;
    if (v?.isExtraAssignment === false) return false;

    const stuCur = String(stuCache?.curriculum || '').trim();
    const stuSub = String(stuCache?.subCurriculum || '').trim();
    const vidCur = String(v?.curriculum || '').trim();
    const vidSub = String(v?.subCurriculum || '').trim();

    if (stuCur && vidCur && stuCur !== vidCur) return true;
    if (stuSub && vidSub && stuSub !== vidSub) return true;
    return false;
  }

  function assignedVideoTitle(v) {
    const prefix = isSupplementVideo(v) ? '(보충) ' : '';
    const chapter = String(v?.chapter ?? '').trim();
    const title = String(v?.title || v?.name || '').trim();
    return `${prefix}${chapter ? `${chapter}. ` : ''}${title || String(v?.mid || '')}`.trim();
  }

  function normalizeAssignedTestStatus(status) {
    const s = String(status || '').trim();
    if (s === 'interrupted' || s === 'skip' || s === 'done' || s === 'assigned') return s;
    return s ? 'assigned' : '';
  }

  function assignedTestStatusLabel(status) {
    const s = normalizeAssignedTestStatus(status);
    if (s === 'interrupted') return '배부';
    if (s === 'skip') return '제외';
    return s ? '배정' : '';
  }

  function assignedTestDifficultyLabel(item) {
    const category = `${item?.categoryKey || ''} ${item?.categoryLabel || ''} ${item?.category || ''} ${item?.label || ''}`;
    const difficulty = String(item?.difficulty || '').trim();
    if (category.includes('ILSAN') || category.includes('일산')) {
      return difficulty === '중상' ? '중' : difficulty;
    }
    return difficulty;
  }

  function normalizeAssignedTests(items) {
    const seen = new Set();
    return (Array.isArray(items) ? items : []).map(item => {
      if (!item || typeof item !== 'object') return null;
      const id = String(item.id || item.testId || '').trim();
      const label = String(item.label || '').trim();
      const name = String(item.name || item.testName || label || '').trim();
      if (!id && !label && !name) return null;
      const status = normalizeAssignedTestStatus(item.status) || 'assigned';
      const key = id || label || name;
      if (seen.has(key)) return null;
      seen.add(key);
      return {
        ...item,
        id,
        label,
        name,
        categoryLabel: String(item.categoryLabel || item.category || '').trim(),
        curriculum: String(item.curriculum || '').trim(),
        difficulty: assignedTestDifficultyLabel(item),
        round: String(item.round || '').trim(),
        status,
        statusLabel: item.statusLabel || assignedTestStatusLabel(status),
      };
    }).filter(Boolean);
  }

  function renderAssignedTests() {
    const panel = $('assignedTestsPanel');
    const list = $('assignedTestList');
    const openBtn = $('openTestSubmit');
    const hasTests = assignedTestsCache.length > 0;

    if (openBtn) openBtn.hidden = !hasTests;
    if (panel) panel.hidden = !hasTests;
    if (!hasTests || !list) return;

    list.textContent = '';
    assignedTestsCache.forEach(test => {
      const li = document.createElement('li');
      const answerUrl = String(test.answerUrl || test.answer_url || '').trim();
      const btn = document.createElement(answerUrl ? 'a' : 'button');
      if (answerUrl) {
        btn.href = answerUrl;
        btn.target = '_blank';
        btn.rel = 'noopener noreferrer';
      } else {
        btn.type = 'button';
      }
      btn.className = 'assigned-test-btn';
      btn.dataset.testId = test.id || '';
      btn.dataset.status = normalizeAssignedTestStatus(test.status) || 'assigned';
      if (answerUrl) btn.dataset.answerUrl = answerUrl;

      const main = document.createElement('span');
      main.className = 'assigned-test-main';

      const name = document.createElement('span');
      name.className = 'assigned-test-name';
      name.textContent = test.name || test.label || '배정 테스트';

      const meta = document.createElement('span');
      meta.className = 'assigned-test-meta';
      meta.textContent = [
        test.categoryLabel,
        test.curriculum,
        test.difficulty,
        test.round ? (String(test.round).includes('회') ? test.round : `${test.round}회차`) : '',
      ].filter(Boolean).join(' · ');

      const status = document.createElement('span');
      status.className = 'assigned-test-status';
      status.textContent = test.statusLabel || assignedTestStatusLabel(test.status);

      main.append(name, meta);
      btn.append(main, status);
      if (!answerUrl) {
        btn.addEventListener('click', () => {
          const openSubmit = () => {
            if (typeof window.openAssignedTestSubmit === 'function') {
              window.openAssignedTestSubmit(test.id || test.label || '');
            }
          };
          if (typeof window.openAssignedTestAnswerLink === 'function') {
            Promise.resolve(window.openAssignedTestAnswerLink(test))
              .then(opened => { if (!opened) openSubmit(); })
              .catch(() => openSubmit());
            return;
          }
          openSubmit();
        });
      }

      li.appendChild(btn);
      list.appendChild(li);
    });
  }

  async function recoverStudentSid(stuArr, missingSid) {
    const byId = new Map((Array.isArray(stuArr) ? stuArr : []).map(s => [String(s?.id || ""), s]));
    const missing = String(missingSid || "").trim();

    try {
      const storedSid = String(localStorage.getItem("studentSid") || "").trim();
      if (storedSid && storedSid !== missing && byId.has(storedSid)) {
        return storedSid;
      }
    } catch {}

    let token = "";
    try {
      token = String(
        localStorage.getItem(LS_TOKEN_MASTER)
        || localStorage.getItem(LS_TOKEN_ACTIVE)
        || ""
      ).trim();
    } catch {}
    if (!token) return "";

    try {
      const res = await fetch("/api/auth/me", {
        cache: "no-store",
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) return "";

      const candidates = [
        String(data?.sid || "").trim(),
        ...((Array.isArray(data?.curris) ? data.curris : []).map(x => String(x?.sid || "").trim()))
      ].filter(Boolean);

      return candidates.find(x => x !== missing && byId.has(x)) || "";
    } catch {
      return "";
    }
  }

  /* ───────────── main ───────────── */
  async function init([stuArr, vids, upd, mats, assigns, absentRaw, logsRaw, watchRaw, bootstrapMeta]) {
    let stu = stuArr.find(s => String(s.id) === String(sid));
    if (!stu) {
      const recoveredSid = await recoverStudentSid(stuArr, sid);
      if (recoveredSid) {
        try { localStorage.setItem("studentSid", recoveredSid); } catch {}
        location.replace(`/student/${encodeURIComponent(recoveredSid)}`);
        return;
      }
      alert("학생 정보가 없습니다");
      return;
    }

    // 캐시에 보관
    stuCache = stu;
    vidsCache = vids || [];
    updatesCache = upd || {};
    absentByDateCache = normalizeAbsentByDate(absentRaw);
    logsCache = logsRaw || {};
    assignedTestsCache = normalizeAssignedTests(bootstrapMeta?.assignedTests);
    window.__ASSIGNED_TESTS__ = assignedTestsCache;
    courseBlocked = bootstrapMeta?.courseBlocked === true;
    courseBlockMessage = bootstrapMeta?.blockMessage || courseBlockMessage;
    courseVideosCompleted = bootstrapMeta?.courseVideosCompleted === true;
    mergeServerWatchIntoLocal((watchRaw && typeof watchRaw.watch === 'object') ? watchRaw.watch : {});

    const nameEl = $('stuName');
    if (nameEl) nameEl.textContent = `${stu.name} (${stu.curriculum})`;

    // 재생 목록 최초 렌더
    renderAssignedTests();
    renderAssignedList();

    const listBox = $('vidList');
    if (listBox) {
      listBox.onclick = e => {
        const li = e.target.closest('li[data-mid]');
        if (!li) return;
        listBox.querySelectorAll('li').forEach(x => x.classList.remove('active'));
        li.classList.add('active');
        play(li.dataset.mid);
      };
    }

    /* ─────────────────────────────────────────────────────────────
       [자료 다운로드] — 혼합 배정(숫자 ID + /files/URL) 완전 지원
       (표시 개선) title은 materials.title 우선, 없으면 URL 파일명에서 UUID/타임스탬프 접두 제거
    ──────────────────────────────────────────────────────────────*/

    function getAssignedRaw(assignsObj, sid) {
      if (!assignsObj) return [];
      const k1 = String(sid);
      const k2 = Number.isNaN(Number(sid)) ? null : Number(sid);
      let v = assignsObj[k1];
      if (!v && k2 != null) v = assignsObj[k2];
      if (Array.isArray(v)) return v.slice();
      if (v && Array.isArray(v.materials)) return v.materials.slice();
      return [];
    }

    function indexMaterials(matsMap) {
      const byId = new Map();
      for (const [key, val] of Object.entries(matsMap || {})) {
        const m = { key, ...(val || {}) };
        const candidates = [
          m.id, m.mid, key,
          typeof m.id === 'number' ? String(m.id) : null,
          typeof key === 'string' ? key : null
        ].filter(x => x !== undefined && x !== null);
        for (const c of candidates) byId.set(String(c), m);
      }
      return byId;
    }

    const rawAssigned = getAssignedRaw(assigns, sid);
    const matIndex = indexMaterials(mats);

    function normalizeAssignedItem(item) {
      if (item && typeof item === 'object') {
        const idOrUrl = item.id ?? item.url ?? item.path ?? item;
        return normalizeAssignedItem(idOrUrl);
      }
      const s = String(item || '').trim();
      if (!s) return null;

      if (s.includes('/files/')) {
        const url = s;
        const rawName = decodeURIComponent(url.split('/').pop() || '파일');
        return { title: cleanDisplayName(rawName), url, _from: 'url' };
      }

      const hit = matIndex.get(s);
      if (hit && hit.url) {
        const baseTitle = hit.title || decodeURIComponent(hit.url.split('/').pop() || '파일');
        return { title: cleanDisplayName(baseTitle), url: hit.url, _from: 'id' };
      }

      if (/\.(pdf|png|jpe?g|pptx?|docx?)$/i.test(s)) {
        const url = s.startsWith('/files/') ? s : `/files/${s.replace(/^\/+/, '')}`;
        const rawName = decodeURIComponent(url.split('/').pop() || '파일');
        return { title: cleanDisplayName(rawName), url, _from: 'url' };
      }

      return null;
    }

    const myMats = rawAssigned.map(normalizeAssignedItem).filter(Boolean);

    const matListEl = $('matList');
    if (matListEl) {
      if (!document.getElementById('mat-browser-style')) {
        const st = document.createElement('style');
        st.id = 'mat-browser-style';
        st.textContent = `
          .mbox{display:flex;gap:8px;align-items:center;margin:6px 0 10px}
          .mbox .crumb{display:flex;gap:6px;flex-wrap:wrap;font-size:14px}
          .mbox .crumb a{cursor:pointer;text-decoration:underline}
          .mbox .sep{opacity:.5}
          .mbox .right{margin-left:auto;display:flex;gap:8px;align-items:center}
          .mbox input[type="search"]{height:30px;border:1px solid var(--line);border-radius:8px;background:transparent;padding:0 8px;color:inherit}
          .mbox .toggle{border:1px solid var(--line);border-radius:8px;padding:4px 8px;background:transparent;cursor:pointer}
          .mat-folder,.mat-file{display:flex;align-items:center;gap:6px}
          .muted{opacity:.65}
          .badge-done{margin-left:.5rem; font-size:.9em; color:var(--accent)}
        `;
        document.head.appendChild(st);
      }
      const ctrl = document.createElement('div');
      ctrl.className = 'mbox';
      ctrl.innerHTML = `
        <div class="crumb" id="matCrumb"></div>
        <div class="right">
          <input id="matSearch" type="search" placeholder="${studentSearchPlaceholder('검색')}" />
          <button id="matMode" class="toggle" aria-pressed="false">폴더 보기</button>
        </div>
      `;
      matListEl.insertAdjacentElement('beforebegin', ctrl);
    }

    function pathOfUrl(u) {
      try { return new URL(u, location.origin).pathname; }
      catch { const a = document.createElement('a'); a.href = u; return a.pathname || u; }
    }

    const tree = { name: '/', children: new Map(), files: [] };
    myMats.forEach(m => {
      const p = pathOfUrl(m.url);
      const segs = String(p || '').split('/').filter(Boolean);
      const fname = decodeURIComponent(segs.pop() || m.title || (m.url || '').split('/').pop());
      let cur = tree;
      for (const s of segs) {
        if (!cur.children.has(s)) cur.children.set(s, { name: s, children: new Map(), files: [] });
        cur = cur.children.get(s);
      }
      cur.files.push({ title: m.title || cleanDisplayName(fname), url: m.url, name: fname });
    });

    const state = { curPath: [], mode: 'tree', query: '' };

    function getNode(segs) {
      let cur = tree;
      for (const s of segs) { cur = cur.children.get(s); if (!cur) return null; }
      return cur;
    }
    function setMode(m) {
      state.mode = m;
      const b = $('matMode');
      if (b) { b.textContent = (m === 'tree') ? '폴더 보기' : '전체 보기'; b.setAttribute('aria-pressed', String(m !== 'tree')); }
      renderMat(); pushHistory();
    }
    function setPath(segs) { state.curPath = segs.slice(); renderMat(); pushHistory(); }
    function setQuery(q) { state.query = q.trim(); renderMat(); }

    function pushHistory() {
      const q = new URLSearchParams(location.search);
      q.set('mpath', state.curPath.join('/')); q.set('mmode', state.mode);
      history.replaceState({ mpath: state.curPath, mmode: state.mode }, '', `${location.pathname}?${q.toString()}${location.hash || ''}`);
    }
    (function applyHistory() {
      try {
        const q = new URLSearchParams(location.search);
        const mpath = (q.get('mpath') || '').split('/').filter(Boolean);
        const mmode = q.get('mmode');
        if (mpath.length) state.curPath = mpath;
        if (mmode === 'flat') state.mode = 'flat';
      } catch { }
    })();

    function renderCrumb() {
      const el = $('matCrumb'); if (!el) return;
      el.textContent = '';
      const root = document.createElement('a');
      root.dataset.idx = '-1';
      root.textContent = '/';
      el.appendChild(root);
      state.curPath.forEach((s, i) => {
        const sep = document.createElement('span');
        sep.className = 'sep';
        sep.textContent = '›';
        const link = document.createElement('a');
        link.dataset.idx = String(i);
        link.textContent = s;
        el.append(' ', sep, ' ', link);
      });
      el.querySelectorAll('a[data-idx]').forEach(a => {
        a.addEventListener('click', () => {
          const idx = +a.dataset.idx;
          if (idx < 0) setPath([]); else setPath(state.curPath.slice(0, idx + 1));
        });
      });
    }

    function liFolder(name, count) {
      const li = document.createElement('li');
      li.className = 'mat-folder';
      li.dataset.type = 'dir';
      li.dataset.name = String(name || '');

      const icon = document.createElement('span');
      icon.textContent = '📁';
      const label = document.createElement('span');
      label.textContent = String(name || '');
      const badge = document.createElement('span');
      badge.className = 'muted';
      badge.textContent = `(${count})`;

      li.append(icon, label, badge);
      return li;
    }
    function liFile(title, url, pathHint) {
      const disp = cleanDisplayName(title);
      const li = document.createElement('li');
      li.className = 'mat-file';
      li.dataset.type = 'file';

      const icon = document.createElement('span');
      icon.textContent = '📄';
      const link = document.createElement('a');
      link.href = String(url || '');
      link.download = '';
      link.textContent = disp;

      li.append(icon, link);
      if (pathHint) {
        const hint = document.createElement('span');
        hint.className = 'muted';
        hint.style.marginLeft = '6px';
        hint.textContent = `(${pathHint})`;
        li.append(hint);
      }
      return li;
    }

    function appendEmptyMatMessage(list, text) {
      const li = document.createElement('li');
      li.className = 'muted';
      li.textContent = text;
      list.appendChild(li);
    }

    function renderMat() {
      const list = $('matList'); if (!list) return;
      renderCrumb();
      const q = state.query;

      if (state.mode === 'tree') {
        const cur = getNode(state.curPath) || tree;
        const folders = Array.from(cur.children.values())
          .filter(nd => studentMatchesSearchKey(studentSearchKeyForText(nd.name), q))
          .sort((a, b) => a.name.localeCompare(b.name, 'ko'));
        const files = (cur.files || [])
          .filter(f => studentMatchesSearchKey(studentSearchKeyForText([f.title, f.name].join(' ')), q))
          .sort((a, b) => (a.title || a.name).localeCompare(b.title || b.name, 'ko'));

        list.textContent = '';
        folders.forEach(nd => list.appendChild(liFolder(nd.name, nd.files.length + nd.children.size)));
        files.forEach(f => list.appendChild(liFile(f.title || f.name, f.url)));
        if (!folders.length && !files.length) appendEmptyMatMessage(list, '이 폴더에 항목이 없습니다');

        list.querySelectorAll('li[data-type="dir"]').forEach(li => {
          li.addEventListener('click', () => setPath([...state.curPath, li.getAttribute('data-name')]));
        });
      } else {
        const all = [];
        (function walk(nd, acc = []) {
          for (const f of (nd.files || [])) {
            const t = f.title || f.name;
            if (studentMatchesSearchKey(studentSearchKeyForText([t, acc.join('/')].join(' ')), q)) {
              all.push({ title: t, url: f.url, path: acc.join('/') });
            }
          }
          for (const ch of nd.children.values()) walk(ch, [...acc, ch.name]);
        })(tree, []);
        all.sort((a, b) => a.title.localeCompare(b.title, 'ko'));
        list.textContent = '';
        all.forEach(f => list.appendChild(liFile(f.title, f.url, f.path)));
        if (!all.length) appendEmptyMatMessage(list, '표시할 파일이 없습니다');
      }
    }

    $('matSearch')?.addEventListener('input', e => setQuery(e.target.value || ''));
    $('matMode')?.addEventListener('click', () => setMode(state.mode === 'tree' ? 'flat' : 'tree'));
    setMode(state.mode);
    setPath(state.curPath);

    /* ───────────── 건의사항 제출 ───────────── */
    const fbBtn = document.querySelector('#submitFeedback');
    if (fbBtn) {
      fbBtn.addEventListener('click', () => {
        const text = document.querySelector('#feedbackBox')?.value.trim();
        if (!text) return alert('내용을 입력해주세요!');
        const name = stu?.name || '익명';

        fetch('/api/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, text })
        }).then(() => {
          alert('소중한 의견 감사합니다!');
          const box = document.querySelector('#feedbackBox');
          if (box) box.value = '';
        }).catch(() => {
          alert('전송에 실패했습니다. 나중에 다시 시도해주세요.');
        });
      });
    }

    window.addEventListener('storage', (e) => {
      if (e.key === 'updPing') location.reload();
    });
  }

  // 오늘 배정 리스트 그리는 함수
  async function renderAssignedList() {
    if (!stuCache) return;
    const listBox = $('vidList');
    const frame = $('player');

    const today = todayLocalKey();

    if (courseBlocked) {
      if (listBox) {
        listBox.textContent = '';
        const li = document.createElement('li');
        li.style.opacity = '.75';
        li.textContent = courseBlockMessage;
        listBox.appendChild(li);
      }
      if (frame) frame.src = "";
      return;
    }

    // ❌ 결석이면 오늘 영상 표시 금지
    {
      const absList = (absentByDateCache?.[today] || []);
      const absSet = new Set(absList.map(String));
      if (absSet.has(String(sid))) {
        if (listBox) listBox.innerHTML = "<li style='opacity:.65'>오늘 결석 처리되었습니다</li>";
        if (frame) frame.src = "";
        return;
      }
    }

    // ❌ archived이면 오늘 영상 표시 금지 (done 여부와 무관)
    {
      const logsToday = (logsCache || {})[today] || {};
      const entry = logsToday[String(sid)] || logsToday[sid] || {};
      const archived = entry.archived === true || entry.archived === 'true';
      if (archived) {
        if (listBox) listBox.innerHTML = "<li style='opacity:.65'>오늘 영상이 없습니다</li>";
        if (frame) frame.src = "";
        return;
      }
    }


    // 🔐 여기서는 "오늘 학생 여부"로 막지 않는다.
    //     수동 배정이 있으면 무조건 보여주고,
    //     자동배정만 ensureTodayAssignmentIfMissing 내부에서 제한한다.
    const chosen = getAssignedVideos(updatesCache, today, sid);

    // 1) 오늘 배정이 아예 없는 경우 → 자동배정 시도 (조건에 맞을 때만)
    if (!chosen.length) {
      // ✅ 유령 배정 생성 방지: 학생 페이지에서 자동배정 금지
      // const fixed = await ensureTodayAssignmentIfMissing();
      // if (fixed) return renderAssignedList();

      if (listBox) {
        const msg = courseVideosCompleted
          ? COURSE_VIDEOS_COMPLETED_MESSAGE
          : "오늘 할당된 영상이 없습니다 문의 부탁";
        listBox.innerHTML = `<li style='opacity:.65'>${msg}</li>`;
      }
      if (frame) frame.src = "";
      return;
    }


    // 2) 여기부터는 chosen에 뭔가 있으니까, 무조건 보여줌 (보강 포함)
    const chosenStrs = new Set(chosen.map(String));

    // ✅ [중요] mid/id 불일치로 비는 경우 방지: (mid || id)로 매칭
    let myVids = (vidsCache || []).filter(v => {
      const kMid = String(v?.mid ?? '');
      const kId = String(v?.id ?? '');
      return (kMid && chosenStrs.has(kMid)) || (kId && chosenStrs.has(kId));
    });

    if (!myVids.length) {
      // 매칭되는 영상이 정말 하나도 없을 때만 빈 상태 처리
      if (listBox) {
        const msg = courseVideosCompleted
          ? COURSE_VIDEOS_COMPLETED_MESSAGE
          : "오늘 할당된 영상이 없습니다 문의 부탁";
        listBox.innerHTML = `<li style='opacity:.65'>${msg}</li>`;
      }
      if (frame) frame.src = "";
      return;
    }

    // 보충 영상은 먼저 보여주고, 각 그룹 안에서는 차시 순서를 유지한다.
    myVids.sort((a, b) => {
      const extraDiff = Number(isSupplementVideo(b)) - Number(isSupplementVideo(a));
      if (extraDiff) return extraDiff;
      const chapterDiff = videoChapterRank(a) - videoChapterRank(b);
      if (chapterDiff) return chapterDiff;
      return String(a.title || a.mid || '').localeCompare(String(b.title || b.mid || ''), 'ko');
    });

    if (listBox) {
      listBox.textContent = '';
      myVids.forEach((v, i) => {
        const num = v.exNum?.[essayBandOf(stuCache.level)] || '';
        const prog = getProgress(v.mid);
        const done = prog?.completed;
        const pct = (prog?.dur > 0)
          ? Math.min(100, Math.round((prog.last || 0) / prog.dur * 100))
          : 0;

        const li = document.createElement('li');
        li.dataset.mid = String(v.mid ?? '');
        if (i === 0) li.className = 'active';

        const main = document.createElement('span');
        main.className = 'video-main';
        main.append(assignedVideoTitle(v));

        if (done || pct) {
          const badge = document.createElement('span');
          badge.className = 'badge-done';
          badge.textContent = done ? '✅' : fmtPct(pct);
          if (!done) badge.title = '진행도';
          main.append(' ', badge);
        }
        li.appendChild(main);

        if (num) {
          const essay = document.createElement('span');
          essay.className = 'essay-badge';
          essay.textContent = `[서술형 ${num}번]`;
          li.appendChild(essay);
        }

        listBox.appendChild(li);
      });
    }

    const preferMid = getLastMid();
    const firstMid = (preferMid && myVids.some(x => String(x.mid) === String(preferMid)))
      ? preferMid
      : myVids[0]?.mid;

    if (firstMid && firstMid !== currentMid) {
      const listBox2 = $('vidList');
      if (listBox2) {
        listBox2.querySelectorAll('li').forEach(x =>
          x.classList.toggle('active', x.dataset.mid === String(firstMid))
        );
      }
      play(firstMid);
    }
  }

  function updateListCompletionBadges() {
    const listBox = $('vidList');
    if (!listBox) return;
    listBox.querySelectorAll('li[data-mid]').forEach(li => {
      const mid = li.dataset.mid;
      const prog = getProgress(mid);
      const done = prog?.completed;
      const pct = (prog?.dur > 0) ? Math.min(100, Math.round((prog.last || 0) / prog.dur * 100)) : 0;

      if (done) {
        li.title = '완료됨';
      } else if (pct) {
        li.title = `진행도 ${pct}%`;
      } else {
        li.removeAttribute('title');
      }
    });
  }

  /* ───────────── Kollus 플레이어 교체 + 진행도(옵션) ───────────── */
  function withStartParam(url, seconds) {
    if (!seconds || seconds < 5) return url;
    try {
      const u = new URL(url, location.origin);
      if (!u.searchParams.has('start')) u.searchParams.set('start', Math.floor(seconds));
      if (!u.searchParams.has('t')) u.searchParams.set('t', Math.floor(seconds));
      return u.toString();
    } catch {
      if (!/#t=\d+/.test(url)) return url + `#t=${Math.floor(seconds)}`;
      return url;
    }
  }

  function attachKollusBridgeToIframe(frameEl, mid, resumeAtSec) {
    if (!frameEl) return;
    if (frameEl.__vgAttached && frameEl.__vgAttached === mid) return;

    function repost(type, payload) {
      window.postMessage({ type, mid, ...payload }, '*');
    }

    let tries = 0;
    const MAX_TRIES = 200;
    const iv = setInterval(() => {
      tries++;
      const ok = !!(window.VgControllerClient && frameEl.contentWindow);
      if (!ok && tries < MAX_TRIES) return;
      clearInterval(iv);
      if (!ok) {
        console.warn('[KollusBridge] VgControllerClient not available (timeout)');
        return;
      }

      try {
        const controller = new VgControllerClient({ target_window: frameEl.contentWindow });
        let lastSent = 0;

        controller.on('ready', function () {
          repost('kollus.ready', {});
          if (typeof controller.seek === 'function' && Number(resumeAtSec) > 5) {
            try { controller.seek(Math.floor(resumeAtSec)); } catch { }
          }

          const poll = async () => {
            try {
              const pos = await controller.getPosition?.();
              const dur = await controller.getDuration?.();
              if (Number.isFinite(pos) && Number.isFinite(dur) && dur > 0) {
                const pct = (pos / dur) * 100;
                const ended = pct >= 90 || pos >= dur - 1;
                if (Math.abs(pos - lastSent) >= 1) {
                  repost('kollus.progress', { currentTime: pos, duration: dur, ended });
                  lastSent = pos;
                }
              }
            } catch { }
            setTimeout(poll, 3000);
          };
          poll();
        });

        controller.on('progress', function (percent, position, duration) {
          const cur = Number(position) || 0;
          const dur = Number(duration) || 0;
          repost('kollus.progress', { currentTime: cur, duration: dur, ended: false });
        });

        controller.on('done', function () {
          repost('kollus.progress', { ended: true });
        });

        controller.on('play', async function () {
          try {
            const pos = await controller.getPosition?.();
            const dur = await controller.getDuration?.();
            if (Number.isFinite(pos) && Number.isFinite(dur)) {
              repost('kollus.progress', { currentTime: pos, duration: dur, ended: false });
            }
          } catch { }
        });

        controller.on('pause', async function () {
          try {
            const pos = await controller.getPosition?.();
            const dur = await controller.getDuration?.();
            if (Number.isFinite(pos) && Number.isFinite(dur)) {
              repost('kollus.progress', { currentTime: pos, duration: dur, ended: false });
            }
          } catch { }
        });

        frameEl.__vgAttached = mid;
        console.log('[KollusBridge] attached for', mid);
      } catch (e) {
        console.warn('[KollusBridge] init failed:', e);
      }
    }, 100);
  }

  window.addEventListener('message', (e) => {
    const data = e?.data;
    if (!data || typeof data !== 'object') return;
    if (data.type === 'kollus.ready' && data.mid) {
      if (Number.isFinite(Number(data.duration))) {
        setProgress(data.mid, { dur: Number(data.duration) || undefined });
      }
    }
    if (data.type === 'kollus.progress' && data.mid) {
      const cur = Math.max(0, Number(data.currentTime) || 0);
      const dur = Math.max(0, Number(data.duration) || 0);
      const ended = !!data.ended || (dur > 0 && cur >= dur - 1);
      const pct = dur > 0 ? (cur / dur) : 0;
      const doneByPct = pct >= 0.90;
      setProgress(data.mid, {
        last: cur,
        dur,
        completed: (ended || doneByPct) || undefined
      });
    }
  });

  async function play(mid) {
    if (currentMid && currentMid !== mid) {
      flushSyncQueue();
    }
    currentMid = mid;
    setLastMid(mid);
    const frame = $('player');
    if (frame) frame.src = "";

    const prog = getProgress(mid);
    const resumeAt = prog?.last || 0;

    try {
      let baseUrl = await fetch(`/api/get-url?mid=${encodeURIComponent(mid)}&sid=${encodeURIComponent(sid)}`).then(r => r.text());
      console.log('[play] baseUrl from server =', baseUrl);

      if (location.protocol === 'https:' && /^http:\/\//i.test(baseUrl)) {
        baseUrl = baseUrl.replace(/^http:\/\//i, 'https://');
        console.log('[play] forced https url =', baseUrl);
      }

      let urlWithStart = withStartParam(baseUrl, resumeAt);

      if (frame) {
        frame.onload = () => {
          attachKollusBridgeToIframe(frame, mid, resumeAt);
        };
        frame.src = urlWithStart;
      }
    } catch (err) {
      console.error(err);
      alert("영상을 불러오지 못했습니다.");
    }
  }
})();

/* ────────────────────────────────────────────────────────────────────────────
   공지 팝업 / 공지함
──────────────────────────────────────────────────────────────────────────── */
(() => {
  const CT = { 'Content-Type': 'application/json' };
  const $ = s => document.querySelector(s);
  const SID = window.__STU_SID__ || decodeURIComponent(location.pathname.split('/').pop());

  const modal = $('#announceModal');
  const historyModal = $('#announceHistoryModal');
  const noticeBtn = $('#noticeBtn');
  const badge = $('#noticeBadge');
  const annTitle = $('#annTitle');
  const annContent = $('#annContent');
  const annImageSection = $('#annImageSection');
  const annImageCarousel = $('#annImageCarousel');
  const annImageTrack = $('#annImageTrack');
  const annImagePrev = $('#annImagePrev');
  const annImageNext = $('#annImageNext');
  const annImageDots = $('#annImageDots');
  const annImageCounter = $('#annImageCounter');
  const annCreatedAt = $('#annCreatedAt');
  const annReply = $('#annReply');
  const annAnonymous = $('#annAnonymous');
  const annSendReply = $('#annSendReply');
  const annReplyStatus = $('#annReplyStatus');
  const annRead = $('#annRead');
  const annSurvey = $('#annSurvey');
  const annSurveyQuestions = $('#annSurveyQuestions');
  const annSurveyError = $('#annSurveyError');
  const annSurveySubmit = $('#annSurveySubmit');
  const annSurveyMeta = $('#annSurveyMeta');
  const historyList = $('#annHistoryList');
  const historyClose = $('#annHistoryClose');
  const ANN_REPLY_LIMIT = 3;

  if (!modal || !historyModal || !noticeBtn || !annTitle || !annContent || !annRead) {
    console.warn('[announce] required elements not found on this page, skip init');
    return;
  }

  let announcements = [];
  let statusMap = {};
  let pending = [];
  let active = null;
  let activeFromHistory = false;
  let loading = false;
  let imageCarouselIndex = 0;
  let imagePointerStartX = 0;
  let imagePointerStartY = 0;
  let imagePointerMoved = false;
  let imagePointerActive = false;

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[ch]));
  }

  function formatDateTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${mm}/${dd} ${hh}:${mi}`;
  }

  function formatPopupCreatedAt(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const month = d.getMonth() + 1;
    const date = d.getDate();
    const hour12 = d.getHours() % 12 || 12;
    const minute = String(d.getMinutes()).padStart(2, '0');
    return `${month}월 ${date}일 ${hour12}:${minute}`;
  }

  function timeLeftText(expiresAt) {
    const end = new Date(expiresAt).getTime();
    if (!Number.isFinite(end)) return '4시간 동안 표시';
    const ms = end - Date.now();
    if (ms <= 0) return '만료됨';
    const mins = Math.ceil(ms / 60000);
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    if (h <= 0) return `${m}분 남음`;
    return `${h}시간 ${m}분 남음`;
  }

  function normalizeAnnouncementImage(image) {
    if (!image || typeof image !== 'object') return null;
    const url = String(image.originalUrl || image.sourceUrl || image.fullUrl || image.url || '').trim();
    if (!url) return null;
    return {
      url,
      alt: '',
    };
  }

  function normalizeAnnouncementImages(ann) {
    const rawImages = Array.isArray(ann?.images) ? ann.images : [];
    const images = rawImages.map(normalizeAnnouncementImage).filter(Boolean);
    if (!images.length) {
      const image = normalizeAnnouncementImage(ann?.image);
      if (image) images.push(image);
    }
    const seen = new Set();
    return images.filter((image) => {
      if (!image.url || seen.has(image.url)) return false;
      seen.add(image.url);
      return true;
    });
  }

  function getSurvey(ann) {
    const survey = ann?.survey;
    if (!survey || typeof survey !== 'object' || !Array.isArray(survey.questions)) return null;
    if (survey.status && survey.status !== 'public') return null;
    return survey;
  }

  function isSurveyAnnouncement(ann) {
    return !!getSurvey(ann);
  }

  function hasSurveySubmission(ann) {
    const status = statusMap?.[ann?.id] || {};
    if (status.surveySubmittedAt && status.surveyAnswers && typeof status.surveyAnswers === 'object') return true;
    return Array.isArray(status.surveyResponses) && status.surveyResponses.some(row => row && typeof row.answers === 'object');
  }

  function replyRowsForStatus(status) {
    const rows = Array.isArray(status?.replies)
      ? status.replies.filter(row => row && String(row.reply || '').trim())
      : [];
    const legacyReply = String(status?.reply || '').trim();
    const legacyAt = String(status?.repliedAt || '');
    if (legacyReply && !rows.some(row => String(row.reply || '').trim() === legacyReply && String(row.repliedAt || '') === legacyAt)) {
      rows.push({ reply: legacyReply, anonymous: !!status?.anonymous, repliedAt: legacyAt });
    }
    return rows;
  }

  function replyCountFor(ann) {
    return replyRowsForStatus(statusMap?.[ann?.id] || {}).length;
  }

  function replyLimitMessage(count) {
    if (count <= 1) return '2번 더 답장 가능!';
    if (count === 2) return '마지막 답장 남음!';
    return '이제 쉿!';
  }

  function syncReplyLimitUi() {
    if (!active || !annReply || !annSendReply) return;
    const isMaxed = replyCountFor(active) >= ANN_REPLY_LIMIT;
    annReply.disabled = isMaxed;
    annSendReply.disabled = isMaxed;
    annReply.placeholder = isMaxed ? '답장은 최대 3회까지 가능합니다.' : '답장을 입력하세요.';
  }

  function isComplete(ann) {
    const survey = getSurvey(ann);
    if (survey && ann?.requireCompletion !== false) return hasSurveySubmission(ann);
    return isAcked(ann);
  }

  function surveyTypeText(type) {
    return {
      single: '하나만 선택',
      multiple: '복수 선택 가능',
      short: '짧은 답변',
      long: '긴 답변',
    }[type] || '질문';
  }

  function surveyOptionText(question, value) {
    const options = Array.isArray(question?.options) ? question.options : [];
    const found = options.find(option => String(option?.id) === String(value));
    return found?.text || value || '';
  }

  function setBadge(count) {
    if (!badge) return;
    if (!count) {
      badge.hidden = true;
      badge.textContent = '0';
      return;
    }
    badge.hidden = false;
    badge.textContent = String(count);
  }

  function isAcked(ann) {
    return !!statusMap?.[ann?.id]?.acked;
  }

  function updatePending() {
    pending = announcements.filter(ann => !isComplete(ann));
    setBadge(pending.length);
  }

  function renderSurvey(ann) {
    if (!annSurvey || !annSurveyQuestions) return;
    const survey = getSurvey(ann);
    const status = statusMap?.[ann?.id] || {};
    const submitted = hasSurveySubmission(ann);
    modal.classList.toggle('has-survey', !!survey);

    if (!survey) {
      annSurvey.hidden = true;
      annSurveyQuestions.innerHTML = '';
      if (annSurveyError) annSurveyError.textContent = '';
      return;
    }

    annSurvey.hidden = false;
    if (annSurveyMeta) {
      annSurveyMeta.textContent = submitted && !survey.allowMultiple
        ? '이미 제출한 설문입니다.'
        : `${survey.anonymous ? '익명 응답' : '실명 응답'} · ${survey.allowMultiple ? '여러 번 제출 가능' : '1회 제출'}`;
    }

    const latestAnswers = status.surveyAnswers && typeof status.surveyAnswers === 'object'
      ? status.surveyAnswers
      : {};
    const readonly = submitted && !survey.allowMultiple;

    annSurveyQuestions.innerHTML = survey.questions.map((question, qIndex) => {
      const qid = String(question.id || `q${qIndex + 1}`);
      const type = question.type || 'single';
      const required = question.required !== false;
      const value = latestAnswers[qid];
      const disabled = readonly ? 'disabled' : '';
      const requiredMark = required ? '<b>필수</b>' : '<b class="optional">선택</b>';

      if (type === 'single' || type === 'multiple') {
        const options = Array.isArray(question.options) ? question.options : [];
        const selected = type === 'multiple'
          ? new Set(Array.isArray(value) ? value.map(String) : [])
          : new Set(value ? [String(value)] : []);
        return `
          <fieldset class="announce-survey-question" data-survey-qid="${escapeHtml(qid)}" data-survey-type="${escapeHtml(type)}" ${required ? 'data-required="true"' : ''}>
            <legend>
              <span>${escapeHtml(question.text || '질문')}</span>
              <em>${requiredMark}${escapeHtml(surveyTypeText(type))}</em>
            </legend>
            <div class="announce-survey-options">
              ${options.map((option, optIndex) => {
                const oid = String(option.id || `o${optIndex + 1}`);
                const inputType = type === 'single' ? 'radio' : 'checkbox';
                return `
                  <label class="announce-survey-option">
                    <input type="${inputType}" name="survey_${escapeHtml(qid)}" value="${escapeHtml(oid)}" ${selected.has(oid) ? 'checked' : ''} ${disabled}>
                    <span>${escapeHtml(option.text || '')}</span>
                  </label>
                `;
              }).join('')}
            </div>
          </fieldset>
        `;
      }

      const textValue = typeof value === 'string' ? value : '';
      return `
        <fieldset class="announce-survey-question" data-survey-qid="${escapeHtml(qid)}" data-survey-type="${escapeHtml(type)}" ${required ? 'data-required="true"' : ''}>
          <legend>
            <span>${escapeHtml(question.text || '질문')}</span>
            <em>${requiredMark}${escapeHtml(surveyTypeText(type))}</em>
          </legend>
          ${type === 'long'
            ? `<textarea rows="4" placeholder="답변을 입력하세요." ${disabled}>${escapeHtml(textValue)}</textarea>`
            : `<input type="text" value="${escapeHtml(textValue)}" placeholder="답변을 입력하세요." ${disabled}>`}
        </fieldset>
      `;
    }).join('');

    if (annSurveyError) annSurveyError.textContent = submitted && !survey.allowMultiple ? '제출 완료된 설문입니다.' : '';
    if (annSurveySubmit) {
      annSurveySubmit.hidden = readonly;
      annSurveySubmit.disabled = readonly;
      annSurveySubmit.textContent = survey.allowMultiple && submitted ? '추가 제출' : '설문 제출';
    }
  }

  function updateImageCarousel(nextIndex = imageCarouselIndex) {
    const slides = Array.from(annImageTrack?.children || []);
    const total = slides.length;
    if (!annImageTrack || !total) return;

    imageCarouselIndex = Math.max(0, Math.min(nextIndex, total - 1));
    annImageTrack.style.transform = `translateX(${-imageCarouselIndex * 100}%)`;
    slides.forEach((slide, index) => {
      slide.toggleAttribute('aria-hidden', index !== imageCarouselIndex);
    });

    const activeSlide = slides[imageCarouselIndex];
    const ratio = activeSlide?.dataset?.imageRatio || '16 / 9';
    annImageCarousel?.style.setProperty('--ann-active-image-ratio', ratio);

    if (annImageCounter) {
      annImageCounter.textContent = total > 1 ? `${imageCarouselIndex + 1} / ${total}` : '';
    }
    if (annImagePrev) annImagePrev.hidden = total <= 1;
    if (annImageNext) annImageNext.hidden = total <= 1;
    if (annImageDots) {
      annImageDots.hidden = total <= 1;
      annImageDots.querySelectorAll('button').forEach((dot, index) => {
        dot.classList.toggle('is-active', index === imageCarouselIndex);
        dot.setAttribute('aria-current', index === imageCarouselIndex ? 'true' : 'false');
      });
    }
  }

  function moveImageCarousel(delta) {
    const total = annImageTrack?.children?.length || 0;
    if (total <= 1) return;
    updateImageCarousel((imageCarouselIndex + delta + total) % total);
  }

  function shouldIgnoreImageGestureTarget(target) {
    return !!target?.closest?.('.announce-image-nav, .announce-image-dots');
  }

  function beginImageGesture(clientX, clientY) {
    imagePointerStartX = clientX;
    imagePointerStartY = clientY;
    imagePointerMoved = false;
  }

  function finishImageGesture(clientX, clientY, ev) {
    const dx = clientX - imagePointerStartX;
    const dy = clientY - imagePointerStartY;
    if (Math.abs(dx) < 42 || Math.abs(dx) < Math.abs(dy) * 1.15) return false;
    ev?.preventDefault?.();
    imagePointerMoved = true;
    moveImageCarousel(dx < 0 ? 1 : -1);
    return true;
  }

  function clearImageCarousel() {
    imageCarouselIndex = 0;
    if (!annImageSection || !annImageTrack) return;
    annImageSection.hidden = true;
    annImageTrack.innerHTML = '';
    if (annImageDots) annImageDots.innerHTML = '';
    if (annImageCounter) annImageCounter.textContent = '';
    if (annImagePrev) annImagePrev.hidden = true;
    if (annImageNext) annImageNext.hidden = true;
    if (annImageDots) annImageDots.hidden = true;
    annImageCarousel?.style.removeProperty('--ann-active-image-ratio');
  }

  function renderImageCarousel(images, title) {
    if (!annImageSection || !annImageTrack || !annImageCarousel) return;
    if (!images.length) {
      clearImageCarousel();
      return;
    }

    imageCarouselIndex = 0;
    annImageSection.hidden = false;
    annImageTrack.innerHTML = images.map((image, index) => `
      <div class="announce-image-slide" data-image-ratio="16 / 9" role="group" aria-label="이미지 ${index + 1} / ${images.length}">
        <a class="announce-image-frame" href="${escapeHtml(image.url)}" target="_blank" rel="noopener noreferrer">
          <img src="${escapeHtml(image.url)}" alt="${escapeHtml(image.alt || title || '공지 이미지')}" draggable="false">
        </a>
      </div>
    `).join('');
    if (annImageDots) {
      annImageDots.innerHTML = images.map((_, index) => `
        <button type="button" aria-label="이미지 ${index + 1} 보기" ${index === 0 ? 'aria-current="true"' : 'aria-current="false"'}></button>
      `).join('');
    }

    const removeFailedImage = (img) => {
      const slide = img.closest('.announce-image-slide');
      slide?.remove();
      if (!annImageTrack.children.length) {
        clearImageCarousel();
        modal.classList.remove('has-image');
        return;
      }
      Array.from(annImageTrack.children).forEach((item, idx) => {
        item.setAttribute('aria-label', `이미지 ${idx + 1} / ${annImageTrack.children.length}`);
      });
      if (annImageDots) {
        annImageDots.innerHTML = Array.from(annImageTrack.children).map((_, index) => `
          <button type="button" aria-label="이미지 ${index + 1} 보기" ${index === 0 ? 'aria-current="true"' : 'aria-current="false"'}></button>
        `).join('');
      }
      updateImageCarousel(Math.min(imageCarouselIndex, annImageTrack.children.length - 1));
    };

    annImageTrack.querySelectorAll('img').forEach((img, index) => {
      const syncRatio = () => {
        if (!img.naturalWidth || !img.naturalHeight) return;
        const slide = img.closest('.announce-image-slide');
        if (!slide) return;
        slide.dataset.imageRatio = `${img.naturalWidth} / ${img.naturalHeight}`;
        if (index === imageCarouselIndex) updateImageCarousel(imageCarouselIndex);
      };
      img.addEventListener('load', syncRatio, { once: true });
      img.addEventListener('error', () => removeFailedImage(img), { once: true });
      if (img.complete && img.naturalWidth) syncRatio();
      else if (img.complete) removeFailedImage(img);
    });

    updateImageCarousel(0);
  }

  function renderActive(ann, options = {}) {
    active = ann || null;
    activeFromHistory = !!options.fromHistory;
    if (!active) return;
    const images = normalizeAnnouncementImages(active);
    annTitle.textContent = active.title || '공지';
    annContent.textContent = active.content || '';
    modal.classList.toggle('has-image', !!images.length);
    renderImageCarousel(images, active.title);
    if (annCreatedAt) annCreatedAt.textContent = formatPopupCreatedAt(active.createdAt);
    if (annReply) annReply.value = statusMap?.[active.id]?.reply || '';
    if (annAnonymous) annAnonymous.checked = !!statusMap?.[active.id]?.anonymous;
    if (annReplyStatus) annReplyStatus.textContent = '';
    renderSurvey(active);
    syncReplyLimitUi();
    if (annRead) annRead.textContent = isSurveyAnnouncement(active) && !hasSurveySubmission(active) ? '설문 제출 필요' : '읽었습니다.';
    modal.style.display = 'flex';
  }

  function showNextPending() {
    updatePending();
    if (!pending.length) {
      modal.style.display = 'none';
      active = null;
      activeFromHistory = false;
      return;
    }
    renderActive(pending[0]);
  }

  async function fetchJSON(url, init) {
    const res = await fetch(url, init);
    if (!res.ok) {
      let text = '';
      try { text = await res.text(); } catch {}
      throw new Error(text || `${url} ${res.status}`);
    }
    return res.json();
  }

  async function loadAnnouncements({ showPopup = true } = {}) {
    if (loading) return;
    loading = true;
    try {
      const [anns, stat] = await Promise.all([
        fetchJSON(`/api/announcements?sid=${encodeURIComponent(SID)}`, { cache: 'no-store' }),
        fetchJSON(`/api/announce-status?sid=${encodeURIComponent(SID)}`, { cache: 'no-store' }),
      ]);
      announcements = Array.isArray(anns) ? anns : [];
      statusMap = stat && typeof stat === 'object' ? stat : {};
      updatePending();
      renderHistory();
      if (showPopup) showNextPending();
    } catch (err) {
      console.warn('[announce] load failed:', err);
      if (historyList) historyList.innerHTML = '<div class="muted">공지를 불러오지 못했습니다.</div>';
    } finally {
      loading = false;
    }
  }

  async function ackActive() {
    if (!active) return;
    if (isSurveyAnnouncement(active) && active.requireCompletion !== false && !hasSurveySubmission(active)) {
      if (annReplyStatus) annReplyStatus.textContent = '설문을 먼저 제출해 주세요.';
      if (annSurveyError) annSurveyError.textContent = '필수 설문은 제출 전까지 닫을 수 없습니다.';
      annSurvey?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      annSurveyQuestions?.querySelector('input:not(:disabled), textarea:not(:disabled)')?.focus?.();
      return;
    }
    const id = active.id;
    const shouldContinuePending = !activeFromHistory;
    try {
      await fetchJSON('/api/announce-ack', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify({ sid: SID, id }),
      });
      statusMap[id] = { ...(statusMap[id] || {}), acked: true };
      modal.style.display = 'none';
      active = null;
      activeFromHistory = false;
      updatePending();
      renderHistory();
      if (shouldContinuePending) showNextPending();
    } catch (err) {
      console.warn('[announce] ack failed:', err);
      if (annReplyStatus) annReplyStatus.textContent = '읽음 처리에 실패했습니다. 다시 눌러 주세요.';
    }
  }

  function collectSurveyAnswers({ focusInvalid = false } = {}) {
    if (!active || !annSurveyQuestions) return null;
    const survey = getSurvey(active);
    if (!survey) return null;

    const answers = {};
    for (const question of survey.questions) {
      const qid = String(question.id || '');
      const type = question.type || 'single';
      const required = question.required !== false;
      const field = annSurveyQuestions.querySelector(`[data-survey-qid="${CSS.escape(qid)}"]`);
      if (!field) continue;

      let value = null;
      if (type === 'single') {
        value = field.querySelector('input[type="radio"]:checked')?.value || '';
      } else if (type === 'multiple') {
        value = Array.from(field.querySelectorAll('input[type="checkbox"]:checked')).map(input => input.value);
      } else {
        value = (field.querySelector('textarea, input[type="text"]')?.value || '').trim();
      }

      const missing = type === 'multiple' ? !value.length : !String(value || '').trim();
      field.classList.toggle('is-invalid', required && missing);
      if (required && missing) {
        if (annSurveyError) annSurveyError.textContent = '필수 질문에 모두 응답해 주세요.';
        if (focusInvalid) field.querySelector('input, textarea')?.focus?.();
        return null;
      }

      if (!missing) answers[qid] = value;
    }

    if (annSurveyError) annSurveyError.textContent = '';
    return answers;
  }

  async function submitSurvey() {
    if (!active || !annSurveySubmit) return;
    const survey = getSurvey(active);
    if (!survey) return;
    if (hasSurveySubmission(active) && !survey.allowMultiple) {
      if (annSurveyError) annSurveyError.textContent = '이미 제출한 설문입니다.';
      return;
    }
    const surveyAnswers = collectSurveyAnswers({ focusInvalid: true });
    if (!surveyAnswers) return;

    annSurveySubmit.disabled = true;
    try {
      const saved = await fetchJSON('/api/announce-submit', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify({
          sid: SID,
          id: active.id,
          surveyAnswers,
        }),
      });
      const currentStatus = statusMap[active.id] || {};
      const surveyEntry = saved?.survey || {
        answers: surveyAnswers,
        anonymous: !!survey.anonymous,
        submittedAt: new Date().toISOString(),
      };
      const surveyResponses = Array.isArray(currentStatus.surveyResponses) ? currentStatus.surveyResponses.slice() : [];
      surveyResponses.push(surveyEntry);
      statusMap[active.id] = {
        ...currentStatus,
        acked: true,
        surveyAnswers,
        surveyAnonymous: !!survey.anonymous,
        surveySubmittedAt: surveyEntry.submittedAt,
        surveyResponses,
      };
      renderSurvey(active);
      updatePending();
      renderHistory();
      if (annReplyStatus) annReplyStatus.textContent = '설문을 제출했습니다.';
      if (!activeFromHistory) {
        const submittedAnnId = active.id;
        window.setTimeout(() => {
          if (active?.id !== submittedAnnId) return;
          modal.style.display = 'none';
          active = null;
          showNextPending();
        }, 650);
      }
    } catch (err) {
      console.warn('[announce] survey submit failed:', err);
      if (annSurveyError) annSurveyError.textContent = '설문 제출에 실패했습니다.';
    } finally {
      annSurveySubmit.disabled = false;
    }
  }

  async function submitReply() {
    if (!active || !annReply) return;
    const currentCount = replyCountFor(active);
    if (currentCount >= ANN_REPLY_LIMIT) {
      alert('이제 쉿!');
      syncReplyLimitUi();
      return;
    }
    const reply = annReply.value.trim();
    if (!reply) {
      annReply.focus();
      if (annReplyStatus) annReplyStatus.textContent = '답장을 입력해 주세요.';
      return;
    }
    annSendReply.disabled = true;
    try {
      const saved = await fetchJSON('/api/announce-submit', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify({
          sid: SID,
          id: active.id,
          reply,
          anonymous: !!annAnonymous?.checked,
        }),
      });
      const currentStatus = statusMap[active.id] || {};
      const replyEntry = saved?.reply || {
        reply,
        anonymous: !!annAnonymous?.checked,
        repliedAt: new Date().toISOString(),
      };
      const replies = replyRowsForStatus(currentStatus).slice();
      replies.push(replyEntry);
      statusMap[active.id] = {
        ...currentStatus,
        reply,
        anonymous: !!annAnonymous?.checked,
        repliedAt: replyEntry.repliedAt,
        replies,
      };
      annReply.value = '';
      if (annReplyStatus) annReplyStatus.textContent = '답장을 보냈습니다.';
      const nextCount = replyCountFor(active);
      alert(replyLimitMessage(nextCount));
      syncReplyLimitUi();
      renderHistory();
    } catch (err) {
      console.warn('[announce] reply failed:', err);
      if (err?.message?.includes('reply limit') || err?.message?.includes('429')) {
        alert('이제 쉿!');
        syncReplyLimitUi();
      }
      if (annReplyStatus) annReplyStatus.textContent = '전송에 실패했습니다.';
    } finally {
      syncReplyLimitUi();
    }
  }

  function renderHistory() {
    if (!historyList) return;
    if (!announcements.length) {
      historyList.innerHTML = '<div class="announce-history-empty">최근 4시간 안에 도착한 공지가 없습니다.</div>';
      return;
    }
    historyList.innerHTML = announcements.map(ann => {
      const status = statusMap[ann.id] || {};
      const survey = getSurvey(ann);
      const surveyDone = survey && hasSurveySubmission(ann);
      const surveyLabel = survey
        ? `<span class="announce-history-survey-badge">${surveyDone ? '설문 완료' : '설문 대기'}</span>`
        : '';
      const answerSummary = survey && status.surveyAnswers && typeof status.surveyAnswers === 'object'
        ? survey.questions.map(question => {
            const value = status.surveyAnswers[String(question.id || '')];
            if (value == null || value === '' || (Array.isArray(value) && !value.length)) return '';
            const text = Array.isArray(value)
              ? value.map(item => surveyOptionText(question, item)).filter(Boolean).join(', ')
              : (question.type === 'single' ? surveyOptionText(question, value) : String(value));
            return text ? `${question.text}: ${text}` : '';
          }).filter(Boolean).slice(0, 2).join(' · ')
        : '';
      const images = normalizeAnnouncementImages(ann);
      const imageLabel = images.length
        ? `<span class="announce-history-image-badge">${images.length > 1 ? `이미지 ${images.length}장` : '이미지 첨부'}</span>`
        : '';
      const badges = `${surveyLabel}${imageLabel}`;
      const replySummary = status.reply
        ? `<span class="announce-history-note">내 답장: ${escapeHtml(status.reply)}</span>`
        : '';
      const surveySummary = answerSummary
        ? `<span class="announce-history-note">내 설문: ${escapeHtml(answerSummary)}</span>`
        : '';
      return `
        <button class="announce-history-item" type="button" data-ann-history-id="${escapeHtml(ann.id)}">
          <div class="announce-history-item-head">
            <div class="announce-history-main">
              <strong class="announce-history-title">${escapeHtml(ann.title || (survey ? '설문조사' : '공지'))}</strong>
              <span class="announce-history-meta">${escapeHtml(formatDateTime(ann.createdAt))} · ${escapeHtml(timeLeftText(ann.expiresAt))}</span>
            </div>
            ${badges ? `<div class="announce-history-badges">${badges}</div>` : ''}
          </div>
          <p class="announce-history-content">${escapeHtml(ann.content || '')}</p>
          ${surveySummary || replySummary ? `<div class="announce-history-foot">${surveySummary}${replySummary}</div>` : ''}
        </button>
      `;
    }).join('');
  }

  function openHistoryAnnouncement(id) {
    const ann = announcements.find(item => String(item?.id) === String(id));
    if (!ann) return;
    historyModal.style.display = 'none';
    renderActive(ann, { fromHistory: true });
  }

  noticeBtn.addEventListener('click', async () => {
    await loadAnnouncements({ showPopup: false });
    historyModal.style.display = 'flex';
  });

  historyClose?.addEventListener('click', () => {
    historyModal.style.display = 'none';
  });

  historyModal.addEventListener('click', (ev) => {
    if (ev.target === historyModal) historyModal.style.display = 'none';
  });

  historyList?.addEventListener('click', (ev) => {
    const item = ev.target.closest('[data-ann-history-id]');
    if (!item) return;
    openHistoryAnnouncement(item.dataset.annHistoryId || '');
  });

  historyList?.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    const item = ev.target.closest('[data-ann-history-id]');
    if (!item) return;
    ev.preventDefault();
    openHistoryAnnouncement(item.dataset.annHistoryId || '');
  });

  annImagePrev?.addEventListener('click', (ev) => {
    ev.preventDefault();
    moveImageCarousel(-1);
  });

  annImageNext?.addEventListener('click', (ev) => {
    ev.preventDefault();
    moveImageCarousel(1);
  });

  annImageDots?.addEventListener('click', (ev) => {
    const dot = ev.target.closest('button');
    if (!dot) return;
    const dots = Array.from(annImageDots.querySelectorAll('button'));
    const index = dots.indexOf(dot);
    if (index >= 0) updateImageCarousel(index);
  });

  annImageCarousel?.addEventListener('pointerdown', (ev) => {
    if (shouldIgnoreImageGestureTarget(ev.target)) return;
    ev.preventDefault();
    imagePointerActive = true;
    beginImageGesture(ev.clientX, ev.clientY);
    annImageCarousel.setPointerCapture?.(ev.pointerId);
  });

  annImageCarousel?.addEventListener('pointerup', (ev) => {
    if (shouldIgnoreImageGestureTarget(ev.target)) return;
    annImageCarousel.releasePointerCapture?.(ev.pointerId);
    finishImageGesture(ev.clientX, ev.clientY, ev);
    window.setTimeout(() => {
      imagePointerActive = false;
    }, 0);
  });

  annImageCarousel?.addEventListener('mousedown', (ev) => {
    if (imagePointerActive || shouldIgnoreImageGestureTarget(ev.target)) return;
    ev.preventDefault();
    beginImageGesture(ev.clientX, ev.clientY);
  });

  annImageCarousel?.addEventListener('mouseup', (ev) => {
    if (imagePointerActive || shouldIgnoreImageGestureTarget(ev.target)) return;
    finishImageGesture(ev.clientX, ev.clientY, ev);
  });

  annImageCarousel?.addEventListener('touchstart', (ev) => {
    if (shouldIgnoreImageGestureTarget(ev.target)) return;
    const touch = ev.touches?.[0];
    if (!touch) return;
    beginImageGesture(touch.clientX, touch.clientY);
  }, { passive: true });

  annImageCarousel?.addEventListener('touchend', (ev) => {
    if (shouldIgnoreImageGestureTarget(ev.target)) return;
    const touch = ev.changedTouches?.[0];
    if (!touch) return;
    finishImageGesture(touch.clientX, touch.clientY, ev);
  });

  annImageCarousel?.addEventListener('click', (ev) => {
    if (!imagePointerMoved) return;
    ev.preventDefault();
    ev.stopPropagation();
    imagePointerMoved = false;
  }, true);

  annImageCarousel?.addEventListener('keydown', (ev) => {
    if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
    ev.preventDefault();
    moveImageCarousel(ev.key === 'ArrowLeft' ? -1 : 1);
  });

  modal.addEventListener('click', (ev) => {
    if (ev.target === modal) ackActive();
  });

  annRead.addEventListener('click', ackActive);
  annSendReply?.addEventListener('click', submitReply);
  annSurveySubmit?.addEventListener('click', submitSurvey);
  annSurveyQuestions?.addEventListener('input', () => {
    if (annSurveyError) annSurveyError.textContent = '';
    annSurveyQuestions.querySelectorAll('.is-invalid').forEach(field => field.classList.remove('is-invalid'));
  });
  annSurveyQuestions?.addEventListener('change', () => {
    if (annSurveyError) annSurveyError.textContent = '';
    annSurveyQuestions.querySelectorAll('.is-invalid').forEach(field => field.classList.remove('is-invalid'));
  });
  annReply?.addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') {
      ev.preventDefault();
      submitReply();
    }
  });

  loadAnnouncements({ showPopup: true });
  window.setInterval(() => {
    if (!document.hidden) loadAnnouncements({ showPopup: !active });
  }, 30000);
})();

/* ─────────────────────────────────────────────
 * 학생 제출용: 테스트 성적 제출 모달  (회차 1~3 + 서버 자동 채점)
 *  - tests-config.json:
 *    test.answerKeys = { "1":[...], "2":[...], "3":[...] }
 *  - 학생 제출:
 *    POST /api/submit-test { sid, testId, round, answersText, memo }
 *    -> 서버가 회차별 정답으로 채점하고 score/wrong/pct 저장
 *  - 서버가 아직 구버전이면(채점 실패) 클라에서 fallback 채점 후 기존 방식으로 저장
 * ────────────────────────────────────────────*/
(() => {
  const CT = { 'Content-Type': 'application/json' };
  const TEST_TYPE_OPTIONS = [
    { value: 'UNIT', label: '단원평가', keys: ['UNIT', '단원평가'] },
    { value: 'REVIEW', label: '복습 테스트', keys: ['REVIEW'] },
    { value: 'SCHOOL_PAST', label: '학군지 기출', keys: ['SCHOOL_PAST'] },
    { value: 'ILSAN_PAST', label: '일산 기출', keys: ['ILSAN_PAST'] },
    { value: 'FINAL', label: 'APEX FINAL', keys: ['FINAL'] },
    { value: 'HELL', label: 'APEX HELL', keys: ['HELL'] },
  ];
  let TEST_ANSWER_LINK_MAP = {};
  let answerLinkMapPromise = null;
  let answerLinkMapLoaded = false;

  // ✅ sid는 이미 위에서 window.__STU_SID__ 세팅해둔 거 우선 사용
  const sid = window.__STU_SID__ || (() => {
    const lastSeg = decodeURIComponent(location.pathname.split("/").pop() || "");
    const q = new URLSearchParams(location.search);
    return q.get("sid") || lastSeg || "";
  })();

  async function fetchJSONSafe(url, init = {}) {
    const res = await fetch(url, { cache: "no-store", ...init });
    const body = await res.text();
    if (!res.ok) throw new Error(`[student tests] ${init.method || "GET"} ${url} -> ${res.status}\n${body.slice(0, 300)}`);
    try { return body.trim() ? JSON.parse(body) : {}; }
    catch (e) { throw new Error(`[student tests] Bad JSON from ${url}: ${e?.message}\n${body.slice(0, 300)}`); }
  }

  function todayLocalKey() {
    const now = new Date();
    const tz = now.getTimezoneOffset() * 60000;
    return new Date(now.getTime() - tz).toISOString().slice(0, 10);
  }

  // ✅ DOM에서 "(공수1)" 같은 커리 텍스트를 파싱해서 필터용으로만 씀
  function getMyCurriculumFromNamebar() {
    const el = document.getElementById('stuName');
    const s = (el?.textContent || '').trim();
    const m = s.match(/\(([^)]+)\)\s*$/);
    return m ? m[1].trim() : '';
  }

  function getAssignedTestsForSubmit() {
    return Array.isArray(window.__ASSIGNED_TESTS__) ? window.__ASSIGNED_TESTS__ : [];
  }

  function assignedRound(value) {
    const raw = String(value || '').trim();
    const m = raw.match(/(\d{1,2})/);
    return m ? m[1] : raw;
  }

  function typeLabel(typeVal) {
    return TEST_TYPE_OPTIONS.find(opt => opt.value === typeVal || opt.keys.includes(typeVal))?.label || typeVal || '';
  }

  // ───────────── tests-config 로드/정규화 ─────────────
  let TEST_CFG = { categories: {} };

  function normalizeCfg(x) {
    const cfg = (x && typeof x === 'object') ? x : {};
    if (!cfg.categories || typeof cfg.categories !== 'object') cfg.categories = {};

    for (const [k, v] of Object.entries(cfg.categories)) {
      const cat = cfg.categories[k] = (v && typeof v === 'object') ? v : {};
      cat.label = (typeof cat.label === 'string' && cat.label.trim()) ? cat.label : k;
      if (!Array.isArray(cat.tests)) cat.tests = [];

      cat.tests = cat.tests.map(t => {
        if (!t || typeof t !== 'object') return null;
        const id = String(t.id || '').trim();
        const name = String(t.name || '').trim();
        if (!id || !name) return null;

        const problems = Number.isFinite(+t.problems) ? Math.max(1, +t.problems) : 20;
        const curriculum = String(t.curriculum || '').trim() || '';
        const difficulty = String(t.difficulty || t.level || '').trim() || '';
        const round = String(t.round || t.session || t.no || '1').trim() || '1';

        // ✅ 새 스키마
        const answerKeys = (t.answerKeys && typeof t.answerKeys === 'object') ? t.answerKeys : null;
        // ✅ 구 스키마(혹시 남아있으면 fallback 용)
        const answerKey = t.answerKey ?? t.answers ?? null;

        return {
          id,
          sourceId: String(t.sourceId || t.source_id || '').trim(),
          name,
          problems,
          curriculum,
          difficulty,
          round,
          categoryKey: String(k || '').trim(),
          categoryLabel: cat.label,
          answerKeys,
          answerKey,
        };
      }).filter(Boolean);
    }
    return cfg;
  }

  async function loadTestsConfig() {
    // /api/tests-config 가 정석. 혹시 없으면 예전처럼 파일로도 한번 시도.
    try {
      TEST_CFG = normalizeCfg(await fetchJSONSafe('/api/tests-config'));
      return;
    } catch { }
    try {
      TEST_CFG = normalizeCfg(await fetchJSONSafe('/api/tests-config.json'));
    } catch {
      TEST_CFG = { categories: {} };
    }
  }

  function resolveCategoryKeysByType(typeVal) {
    const hits = [];
    const option = TEST_TYPE_OPTIONS.find(opt => opt.value === typeVal || opt.keys.includes(typeVal));
    for (const [key, cat] of Object.entries(TEST_CFG.categories || {})) {
      const label = String(cat.label || '').trim();
      const k = String(key || '').trim().toUpperCase();
      const lv = label.toUpperCase();

      if (option) {
        if (option.keys.some(rawKey => k === String(rawKey).toUpperCase())) hits.push(key);
        else if (option.keys.some(rawKey => lv.includes(String(rawKey).toUpperCase()))) hits.push(key);
        else if (option.label && label.includes(option.label.replace('APEX ', ''))) hits.push(key);
      } else if (typeVal === '단원평가') {
        if (lv.includes('단원') || lv.includes('UNIT') || k === 'UNIT') hits.push(key);
      } else if (typeVal === 'FINAL') {
        if (lv.includes('FINAL') || k === 'FINAL') hits.push(key);
      } else if (typeVal === 'HELL') {
        if (lv.includes('HELL') || k === 'HELL') hits.push(key);
      }
    }
    return hits;
  }

  function assignedMatchesTest(test) {
    const assigned = getAssignedTestsForSubmit();
    if (!assigned.length || !test) return false;
    return assigned.some(item => {
      const assignedId = String(item.id || item.testId || '').trim();
      if (assignedId && assignedId === String(test.id || '').trim()) return true;

      const itemName = String(item.name || item.testName || '').trim();
      const itemLabel = String(item.label || '').trim();
      const nameOk = itemName
        ? itemName === String(test.name || '').trim()
        : (itemLabel && itemLabel.includes(String(test.name || '').trim()));
      if (!nameOk) return false;

      const roundOk = !item.round || !test.round || assignedRound(item.round) === assignedRound(test.round);
      const curOk = !item.curriculum || !test.curriculum || String(item.curriculum) === String(test.curriculum);
      const diffOk = !item.difficulty || !test.difficulty || String(item.difficulty) === String(test.difficulty);
      return roundOk && curOk && diffOk;
    });
  }

  function listTestsForType(typeVal, myCur) {
    const keys = resolveCategoryKeysByType(typeVal);
    const out = [];
    for (const k of keys) {
      const cat = TEST_CFG.categories[k];
      for (const t of (cat?.tests || [])) out.push(t);
    }

    // 커리 정보가 있으면 커리 일치하는 시험을 우선 보여주고, 없으면 전체
    if (myCur) {
      const same = out.filter(t => !t.curriculum || t.curriculum === myCur);
      const scoped = same.length ? same : out;
      return scoped.filter(assignedMatchesTest);
    }
    return out.filter(assignedMatchesTest);
  }

  function findTestById(typeVal, testId, myCur) {
    const list = listTestsForType(typeVal, myCur);
    return list.find(t => String(t.id) === String(testId)) || null;
  }

  function listAssignedConfiguredTests(myCur) {
    const out = [];
    TEST_TYPE_OPTIONS.forEach(opt => {
      listTestsForType(opt.value, myCur).forEach(test => out.push(test));
    });
    return out;
  }

  function typeValueForTest(test) {
    const key = String(test?.categoryKey || '').trim().toUpperCase();
    const label = String(test?.categoryLabel || '').trim().toUpperCase();
    const hit = TEST_TYPE_OPTIONS.find(opt =>
      opt.keys.some(rawKey => key === String(rawKey).toUpperCase() || label.includes(String(rawKey).toUpperCase())) ||
      (opt.label && String(test?.categoryLabel || '').includes(opt.label.replace('APEX ', '')))
    );
    return hit?.value || 'UNIT';
  }

  function roundLabel(round) {
    const r = String(round || '').trim();
    return r ? (/회/.test(r) ? r : `${r}회차`) : '';
  }

  function findSiblingTestByRound(typeVal, test, round, myCur) {
    if (!test) return null;
    const targetRound = String(round || '').trim();
    return listTestsForType(typeVal, myCur).find(item =>
      String(item.name || '') === String(test.name || '') &&
      String(item.curriculum || '') === String(test.curriculum || '') &&
      String(item.difficulty || '') === String(test.difficulty || '') &&
      String(item.round || '') === targetRound
    ) || null;
  }

  function allConfiguredTests() {
    const out = [];
    Object.values(TEST_CFG.categories || {}).forEach(cat => {
      (cat?.tests || []).forEach(test => out.push(test));
    });
    return out;
  }

  function unitCategoryLike(item, configuredTest = null) {
    const source = [
      item?.categoryKey,
      item?.category,
      item?.categoryLabel,
      item?.label,
      configuredTest?.categoryKey,
      configuredTest?.categoryLabel,
    ].map(v => String(v || '')).join(' ');
    return /\bUNIT\b/i.test(source) || source.includes('단원평가') || source.includes('단원');
  }

  function findConfiguredTestForAssignment(item) {
    if (!item || typeof item !== 'object') return null;
    const assignedId = String(item.id || item.testId || '').trim();
    const assignedSourceId = assignedId.replace(/_r[123]$/, '');
    const itemName = String(item.name || item.testName || '').trim();
    const itemLabel = String(item.label || '').trim();
    const round = assignedRound(item.round);

    const tests = allConfiguredTests();
    if (assignedId) {
      const byId = tests.find(test =>
        String(test.id || '') === assignedId ||
        String(test.sourceId || '') === assignedId ||
        String(test.sourceId || '') === assignedSourceId
      );
      if (byId) return byId;
    }

    return tests.find(test => {
      const testName = String(test.name || '').trim();
      const nameOk = itemName ? itemName === testName : (itemLabel && itemLabel.includes(testName));
      if (!nameOk) return false;
      if (round && assignedRound(test.round) !== round) return false;
      if (item.curriculum && String(item.curriculum) !== String(test.curriculum || '')) return false;
      if (item.difficulty && String(item.difficulty) !== String(test.difficulty || '')) return false;
      return true;
    }) || null;
  }

  // ───────────── 답안 파싱/클라 채점(fallback용) ─────────────
  function parseAnswerSpec(text, problems) {
    const s = String(text ?? '').trim();
    if (!s) return new Array(problems).fill('');
    let arr;
    if (/[\s,]/.test(s)) arr = s.split(/[\s,]+/).map(v => v.trim()).filter(Boolean);
    else arr = s.split('').map(v => v.trim()).filter(Boolean);

    if (arr.length > problems) arr = arr.slice(0, problems);
    if (arr.length < problems) arr = arr.concat(new Array(problems - arr.length).fill(''));
    return arr;
  }

  function getKeyForRound(test, roundNo) {
    const r = String(roundNo === 2 ? 2 : roundNo === 3 ? 3 : 1);

    if (test?.answerKeys && typeof test.answerKeys === 'object') {
      const k = test.answerKeys[r];
      if (Array.isArray(k)) return k.map(x => String(x ?? '').trim());
    }

    // legacy
    if (Array.isArray(test?.answerKey)) return test.answerKey.map(x => String(x ?? '').trim());
    if (typeof test?.answerKey === 'string') return parseAnswerSpec(test.answerKey, test.problems);

    return null;
  }

  function normalizeAnswerRound(round) {
    const r = String(round || '1').trim();
    return (r === '2' || r === '3') ? r : '1';
  }

  function getAnswerLinkForRound(testId, round, sourceId = '') {
    const id = String(testId || '').trim();
    const r = normalizeAnswerRound(round);
    const source = String(sourceId || '').trim() || id.replace(/_r[123]$/, '');
    const entry = TEST_ANSWER_LINK_MAP[id]?.[r] || TEST_ANSWER_LINK_MAP[source]?.[r];
    const answerUrl = (entry && typeof entry === 'object') ? (entry.answerUrl ?? entry.answer_url ?? entry.url ?? entry.link) : entry;
    return answerUrl ? String(answerUrl).trim() : null;
  }

  async function getAssignedAnswerLink(item) {
    if (!Object.keys(TEST_CFG.categories || {}).length) {
      await loadTestsConfig();
    }
    await loadAnswerLinkMap();

    const configuredTest = findConfiguredTestForAssignment(item);
    const round = normalizeAnswerRound(item?.round || configuredTest?.round || '1');
    const candidates = [
      [item?.id || item?.testId, item?.sourceId || item?.source_id],
      [configuredTest?.id, configuredTest?.sourceId],
      [item?.sourceId || item?.source_id, ''],
    ];

    for (const [testId, sourceId] of candidates) {
      const url = getAnswerLinkForRound(testId, round, sourceId);
      if (url) return { url, configuredTest };
    }
    return { url: null, configuredTest };
  }

  window.openAssignedTestAnswerLink = async (item = {}) => {
    if (!unitCategoryLike(item)) return false;

    const popup = window.open('about:blank', '_blank');
    if (popup) popup.opener = null;

    try {
      const { url, configuredTest } = await getAssignedAnswerLink(item);
      if (!unitCategoryLike(item, configuredTest) || !url) {
        if (popup) popup.close();
        return false;
      }
      if (popup) {
        popup.location.replace(url);
      } else {
        window.location.assign(url);
      }
      return true;
    } catch (err) {
      if (popup) popup.close();
      console.warn('[test answer links] open failed', err);
      return false;
    }
  };

  function normalizeAnswerLinkMap(raw) {
    const out = {};
    const put = (testId, round, answerUrl) => {
      const id = String(testId || '').trim();
      const r = normalizeAnswerRound(round);
      const url = String(answerUrl || '').trim();
      if (!id || !r || !url) return;
      out[id] = out[id] || {};
      out[id][r] = url;
    };

    const putRows = rows => {
      rows.forEach(item => {
        if (!item || typeof item !== 'object') return;
        put(item.testId ?? item.test_id ?? item.id, item.round, item.answerUrl ?? item.answer_url ?? item.url ?? item.link);
      });
    };

    if (Array.isArray(raw)) {
      putRows(raw);
      return out;
    }

    if (!raw || typeof raw !== 'object') return out;
    if (Array.isArray(raw.links)) {
      putRows(raw.links);
      return out;
    }
    if (Array.isArray(raw.items)) {
      putRows(raw.items);
      return out;
    }

    Object.entries(raw).forEach(([testId, rounds]) => {
      if (!rounds || typeof rounds !== 'object') return;
      const roundMap = rounds.rounds || rounds.answers || rounds;
      if (!roundMap || typeof roundMap !== 'object') return;
      Object.entries(roundMap).forEach(([round, entry]) => {
        const answerUrl = (entry && typeof entry === 'object') ? (entry.answerUrl ?? entry.answer_url ?? entry.url ?? entry.link) : entry;
        put(testId, round, answerUrl);
      });
    });

    return out;
  }

  async function loadAnswerLinkMap() {
    if (answerLinkMapLoaded) return TEST_ANSWER_LINK_MAP;
    if (!answerLinkMapPromise) {
      answerLinkMapPromise = fetch('/js/test_answer_link_map.json', { cache: 'no-store' })
        .then(res => {
          if (!res.ok) throw new Error(String(res.status));
          return res.json();
        })
        .then(data => {
          TEST_ANSWER_LINK_MAP = normalizeAnswerLinkMap(data);
          return TEST_ANSWER_LINK_MAP;
        })
        .catch(err => {
          console.warn('[test answer links] load failed', err);
          TEST_ANSWER_LINK_MAP = {};
          return TEST_ANSWER_LINK_MAP;
        })
        .finally(() => {
          answerLinkMapLoaded = true;
        });
    }
    return answerLinkMapPromise;
  }

  function gradeClientSide(answersText, keyArr, problems) {
    const ans = parseAnswerSpec(answersText, problems);
    const key = (keyArr || []).slice(0, problems);
    if (key.length < problems) key.push(...new Array(problems - key.length).fill(''));

    const wrong = [];
    let correct = 0;

    for (let i = 0; i < problems; i++) {
      const a = String(ans[i] ?? '').replace(/\s+/g, '').toUpperCase();
      const k = String(key[i] ?? '').replace(/\s+/g, '').toUpperCase();

      if (!k) { // 키 비면 틀림 처리(원하면 여기 바꿔도 됨)
        wrong.push(i + 1);
        continue;
      }
      if (a === k) correct++;
      else wrong.push(i + 1);
    }

    const pct = problems ? +(correct / problems * 100).toFixed(2) : 0;
    return { correct, total: problems, wrong, pct };
  }

  // ───────────── UI ─────────────
  function injectStyles() {
    if (document.getElementById('test-submit-styles')) return;
    const s = document.createElement('style');
    s.id = 'test-submit-styles';
    s.textContent = `
    :root{
      --ts-card-bg:#ffffff; --ts-card-fg:#0f172a; --ts-border:#e5e7eb; --ts-muted:#6b7280;
      --ts-field-bg:#ffffff; --ts-focus:#2563eb; --ts-primary:#2563eb; --ts-primary-fg:#ffffff;
      --ts-backdrop:rgba(0,0,0,.45);
    }
    body.dark{
      --ts-card-bg:#0f172a; --ts-card-fg:#e5e7eb; --ts-border:#334155; --ts-muted:#94a3b8;
      --ts-field-bg:#0b1220; --ts-focus:#60a5fa; --ts-backdrop:rgba(0,0,0,.55);
      --ts-primary:#2563eb; --ts-primary-fg:#ffffff;
    }
    #testSubmitModal{ position:fixed; inset:0; z-index:99999; display:none; justify-content:center; align-items:center; background:var(--ts-backdrop); }
    #testSubmitModal .ts-card{ width:480px; max-width:92vw; border-radius:14px; padding:14px;
      box-shadow:0 12px 32px rgba(0,0,0,.35); background:var(--ts-card-bg); color:var(--ts-card-fg);
      border:1px solid var(--ts-border); max-height:80vh; overflow:auto; }
    #testSubmitModal .ts-head{ display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
    #testSubmitModal h3{ margin:0; font-size:18px; font-weight:800; }
    #testSubmitModal label{ font-size:12px; color:var(--ts-muted); display:block; margin-bottom:6px; }
    #testSubmitModal select, #testSubmitModal textarea{
      width:100%; box-sizing:border-box; border:1px solid var(--ts-border); border-radius:10px;
      background:var(--ts-field-bg); color:var(--ts-card-fg); outline:none;
    }
    #testSubmitModal select{ height:36px; padding:0 10px; }
    #testSubmitModal textarea{ padding:8px 10px; resize:vertical; min-height:82px; }
    #testSubmitModal select:focus, #testSubmitModal textarea:focus{
      border-color:var(--ts-focus); box-shadow:0 0 0 3px color-mix(in srgb, var(--ts-focus) 30%, transparent);
    }
    #testSubmitModal .ts-grid{ display:grid; gap:10px; }
    #testSubmitModal .ts-row3{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
    @media (max-width:520px){ #testSubmitModal .ts-row3{ grid-template-columns:1fr; } }
    #testSubmitModal .ts-info{ margin-top:6px; font-size:13px; color:var(--ts-muted); white-space:pre-wrap; }
    #testSubmitModal .ts-answer-link{ display:none; margin-top:8px; font-size:13px; color:var(--ts-muted); }
    #testSubmitModal .ts-answer-link a{
      display:inline-flex; align-items:center; justify-content:center; height:38px; padding:0 14px;
      border-radius:10px; background:var(--ts-primary); color:var(--ts-primary-fg); text-decoration:none; font-weight:800;
    }
    #testSubmitModal .ts-actions{ display:flex; gap:8px; justify-content:flex-end; margin-top:12px; }
    #testSubmitModal .ts-submit{
      height:38px; padding:0 14px; border:none; border-radius:10px; cursor:pointer; font-weight:800;
      background:var(--ts-primary); color:var(--ts-primary-fg);
    }
    #testSubmitModal .ts-close{ border:none; background:transparent; font-size:20px; cursor:pointer; color:var(--ts-card-fg); }
    `;
    document.head.appendChild(s);
  }

  function ensureModal() {
    if (document.getElementById('testSubmitModal')) return;

    document.body.insertAdjacentHTML('beforeend', `
      <div id="testSubmitModal">
        <div class="ts-card">
          <div class="ts-head">
            <h3>테스트 성적 제출</h3>
            <button id="tsClose" class="ts-close" aria-label="close">✕</button>
          </div>

          <div class="ts-grid">
            <div class="ts-row3">
              <div>
                <label>종류</label>
                <select id="tsType">
                  <option value="UNIT" selected>단원평가</option>
                </select>
              </div>
              <div>
                <label>시험</label>
                <select id="tsTestId"></select>
              </div>
              <div>
                <label>회차</label>
                <select id="tsRound">
                  <option value="1" selected>1회차</option>
                  <option value="2">2회차</option>
                  <option value="3">3회차</option>
                </select>
              </div>
            </div>

            <div>
              <label>답 입력 (공백/쉼표/붙여쓰기 모두 가능)</label>
              <textarea id="tsAnswersText" placeholder="예) 1 3 2 4 5 ... 또는 13245..."></textarea>
              <div id="tsInfo" class="ts-info"></div>
              <div id="tsAnswerLinkArea" class="ts-answer-link"></div>
            </div>

            <div>
              <label>메모(선택)</label>
              <textarea id="tsMemo" rows="2" placeholder="메모가 있으면 적어주세요"></textarea>
            </div>
          </div>

          <div class="ts-actions">
            <button id="tsSubmit" class="ts-submit">제출</button>
          </div>
        </div>
      </div>
    `);
  }

  async function initLogic() {
    const btnOpen = document.getElementById('openTestSubmit'); // ✅ HTML에 이미 있음
    const modal = document.getElementById('testSubmitModal');
    const btnClose = document.getElementById('tsClose');
    const btnSubmit = document.getElementById('tsSubmit');

    const selType = document.getElementById('tsType');
    const selTestId = document.getElementById('tsTestId');
    const selRound = document.getElementById('tsRound');

    const answersTextEl = document.getElementById('tsAnswersText');
    const memoEl = document.getElementById('tsMemo');
    const infoEl = document.getElementById('tsInfo');
    const answerLinkArea = document.getElementById('tsAnswerLinkArea');

    const currentCur = () => getMyCurriculumFromNamebar();

    await loadTestsConfig();

    function renderTypeOptions(preselectType = '') {
      const myCur = currentCur();
      const available = TEST_TYPE_OPTIONS.filter(opt => listTestsForType(opt.value, myCur).length);
      if (!available.length) {
        selType.innerHTML = `<option value="">(배정 없음)</option>`;
        return '';
      }

      selType.innerHTML = available.map(opt =>
        `<option value="${opt.value}">${opt.label}</option>`
      ).join('');
      selType.value = available.some(opt => opt.value === preselectType)
        ? preselectType
        : available[0].value;
      return selType.value;
    }

    function renderTestOptions(preselectTestId = '') {
      const myCur = currentCur();
      const type = selType.value;
      const list = listTestsForType(type, myCur);

      if (!list.length) {
        selTestId.innerHTML = `<option value="">(시험 없음)</option>`;
        infoEl.textContent = '오늘 배정된 시험이 없습니다.';
        return;
      }

      selTestId.innerHTML = list.map(t => {
        const curTag = t.curriculum ? ` (${t.curriculum})` : '';
        const meta = [t.difficulty, roundLabel(t.round)].filter(Boolean).join(' · ');
        return `<option value="${t.id}">${t.name}${curTag}${meta ? ` · ${meta}` : ''}</option>`;
      }).join('');

      if (preselectTestId && list.some(t => String(t.id) === String(preselectTestId))) {
        selTestId.value = String(preselectTestId);
      }

      updateInfo();
    }

    function updateInfo(extra) {
      const myCur = currentCur();
      const type = selType.value;
      const testId = selTestId.value;
      const t = findTestById(type, testId, myCur);
      const round = parseInt(t?.round || selRound.value, 10) || 1;

      if (!t) {
        infoEl.textContent = '시험을 선택하세요.';
        return;
      }

      if (selRound && String(selRound.value || '') !== String(round)) {
        selRound.value = String(round);
      }

      const key = getKeyForRound(t, round);
      const keyOk = Array.isArray(key) && key.length;

      let msg = `${typeLabel(type)}\n문항 수: ${t.problems}문항\n회차: ${round}회차\n`;
      msg += keyOk
        ? '정답키 등록됨 → 제출하면 서버가 자동 채점합니다.'
        : '정답키가 아직 등록되지 않았습니다 → 선생님께 말해 주세요.';

      if (extra) msg += `\n\n${extra}`;
      infoEl.textContent = msg;
    }

    function resetAnswerLink() {
      if (!answerLinkArea) return;
      answerLinkArea.style.display = 'none';
      answerLinkArea.replaceChildren();
    }

    async function renderAnswerLink(testId, round) {
      if (!answerLinkArea) return;
      answerLinkArea.replaceChildren();

      await loadAnswerLinkMap();
      const answerUrl = getAnswerLinkForRound(testId, round);
      answerLinkArea.style.display = 'block';

      if (!answerUrl) {
        answerLinkArea.textContent = '해설지 링크 준비 중';
        return;
      }

      const a = document.createElement('a');
      a.href = answerUrl;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = '해설지 보기';
      answerLinkArea.appendChild(a);
    }

    const open = (preselectTestId = '') => {
      const assigned = getAssignedTestsForSubmit();
      if (!assigned.length) return;
      const myCur = currentCur();
      const fallback = listAssignedConfiguredTests(myCur)[0] || null;
      const requested = preselectTestId
        ? listAssignedConfiguredTests(myCur).find(t => String(t.id) === String(preselectTestId)) || fallback
        : fallback;
      const nextType = requested ? typeValueForTest(requested) : '';

      renderTypeOptions(nextType);
      renderTestOptions(requested?.id || preselectTestId);
      answersTextEl.value = '';
      memoEl.value = '';
      resetAnswerLink();
      void loadAnswerLinkMap();
      modal.style.display = 'flex';
    };
    const close = () => { modal.style.display = 'none'; };

    btnOpen?.addEventListener('click', () => open());
    btnClose?.addEventListener('click', close);
    modal.addEventListener('click', (e) => { if (e.target === modal) close(); });

    selType.addEventListener('change', () => {
      resetAnswerLink();
      renderTestOptions();
    });
    selTestId.addEventListener('change', () => {
      resetAnswerLink();
      const t = findTestById(selType.value, selTestId.value, currentCur());
      if (t?.round) selRound.value = String(t.round);
      updateInfo();
    });
    selRound.addEventListener('change', () => {
      resetAnswerLink();
      const myCur = currentCur();
      const current = findTestById(selType.value, selTestId.value, myCur);
      const sibling = findSiblingTestByRound(selType.value, current, selRound.value, myCur);
      if (sibling) selTestId.value = sibling.id;
      updateInfo();
    });

    window.openAssignedTestSubmit = (testId = '') => open(testId);

    btnSubmit?.addEventListener('click', async () => {
      const type = selType.value;
      const testId = selTestId.value;
      const answersText = String(answersTextEl.value || '').trim();
      const memo = String(memoEl.value || '').trim();
      resetAnswerLink();

      if (!testId) return alert('시험을 선택해주세요.');
      if (!answersText) return alert('답을 입력해주세요.');

      const t = findTestById(type, testId, currentCur());
      if (!t) return alert('시험 정보를 찾지 못했습니다.');
      const round = parseInt(t.round || selRound.value, 10) || 1;
      if (selRound) selRound.value = String(round);

      // ✅ 1) 서버 자동 채점/저장
      try {
        const res = await fetch('/api/submit-test', {
          method: 'POST',
          headers: CT,
          body: JSON.stringify({
            sid,
            testId,
            round,
            answersText,
            memo
          })
        });

        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json().catch(() => ({}));

        // 응답 예: { ok:true, score:"18/20", wrong:[...], pct:90 }
        const score = data.score || '';
        const pct = (typeof data.pct === 'number') ? data.pct : null;
        const wrong = Array.isArray(data.wrong) ? data.wrong : [];

        let extra = `제출 완료\n점수: ${score}`;
        if (pct != null) extra += ` (${pct.toFixed(1)}%)`;
        if (wrong.length) extra += `\n오답: ${wrong.join(', ')}`;
        updateInfo(extra);
        await renderAnswerLink(testId, round);

        try { localStorage.setItem('updPing', Date.now().toString()); } catch { }
        return;
      } catch (e) {
        console.warn('[submit-test] server grade failed, fallback to client side', e);
      }

      // ✅ 2) fallback: 클라 채점 후 기존 방식으로 저장(서버가 구버전일 때 대비)
      const key = getKeyForRound(t, round);
      if (!key) {
        alert('정답키가 없어서 제출할 수 없습니다. 선생님께 정답 등록 요청하세요.');
        return;
      }

      const graded = gradeClientSide(answersText, key, t.problems);
      const score = `${graded.correct}/${graded.total}`;
      const fullName = (type === 'UNIT' || type === '단원평가') ? t.name : `${typeLabel(type)} / ${t.name}`;

      // 구버전 서버는 name/score/wrong로 저장되던 방식
      const payload = { sid, name: fullName, score, wrong: graded.wrong, memo };

      try {
        const res = await fetch('/api/submit-test', { method: 'POST', headers: CT, body: JSON.stringify(payload) });
        if (!res.ok) throw new Error(String(res.status));
      } catch {
        // 마지막 백업: logs.json 직접 머지
        try {
          const today = todayLocalKey();
          const logs = await fetch(`/api/logs/entry?date=${encodeURIComponent(today)}&sid=${encodeURIComponent(sid)}`, { cache: 'no-store' })
            .then(r => r.json()).catch(() => ({}));
          const entry = (logs && logs.entry && typeof logs.entry === 'object') ? logs.entry : {};
          const tests = Array.isArray(entry.tests) ? entry.tests.slice() : [];
          tests.push({ name: fullName, score, wrong: graded.wrong, memo, createdAt: new Date().toISOString() });
          const ok = await fetch('/api/logs/patch', {
            method: 'POST',
            headers: CT,
            body: JSON.stringify({ date: today, sid, entry: { tests } })
          });
          if (!ok.ok) throw new Error(String(ok.status));
        } catch {
          alert('제출 실패: 나중에 다시 시도해주세요.');
          return;
        }
      }

      // tests.json 집계용(가능하면)
      try {
        await fetch('/api/tests', {
          method: 'POST', headers: CT,
          body: JSON.stringify({
            [todayLocalKey()]: {
              [sid]: [{
                name: fullName,
                score,
                wrong: graded.wrong,
                memo,
                createdAt: new Date().toISOString()
              }]
            }
          })
        });
      } catch { }

      try { localStorage.setItem('updPing', Date.now().toString()); } catch { }
      let extra = `제출 완료\n점수: ${score}`;
      if (typeof graded.pct === 'number') extra += ` (${graded.pct.toFixed(1)}%)`;
      if (graded.wrong.length) extra += `\n오답: ${graded.wrong.join(', ')}`;
      updateInfo(extra);
      await renderAnswerLink(testId, round);
    });
  }

  // ───────────── init ─────────────
  injectStyles();
  ensureModal();
  void loadAnswerLinkMap();
  initLogic().catch(err => {
    console.warn('[test submit modal] init failed', err);
  });
})();
