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
  let courseBlocked = false;
  let courseBlockMessage = "수업일이 아닌 것 같습니다. 선생님께 문의주세용 ^_^";

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

      const pct = snap.dur > 0 ? (snap.last / snap.dur) : 0;
      let status = null;
      if (pct >= 0.90) status = 'done';
      else if (pct >= 0.05) status = 'interrupted';

      if (status) {
        const res2 = await fetch('/api/watch-status', {
          method: 'POST', headers: CT,
          body: JSON.stringify({
            date: todayLocalKey(),
            sid: canonicalSid,
            mid,
            status
          }),
          keepalive: !!options.keepalive
        });
        if (!res2.ok) console.warn('[watch-status] HTTP', res2.status);
      }
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
      { courseBlocked: false, blockMessage: '' },
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
    courseBlocked = bootstrapMeta?.courseBlocked === true;
    courseBlockMessage = bootstrapMeta?.blockMessage || courseBlockMessage;
    mergeServerWatchIntoLocal((watchRaw && typeof watchRaw.watch === 'object') ? watchRaw.watch : {});

    const nameEl = $('stuName');
    if (nameEl) nameEl.textContent = `${stu.name} (${stu.curriculum})`;

    // 재생 목록 최초 렌더
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
          <input id="matSearch" type="search" placeholder="검색" />
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
      const q = state.query.toLowerCase();

      if (state.mode === 'tree') {
        const cur = getNode(state.curPath) || tree;
        const folders = Array.from(cur.children.values())
          .filter(nd => !q || nd.name.toLowerCase().includes(q))
          .sort((a, b) => a.name.localeCompare(b.name, 'ko'));
        const files = (cur.files || [])
          .filter(f => !q || (f.title || f.name).toLowerCase().includes(q))
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
            if (!q || t.toLowerCase().includes(q)) all.push({ title: t, url: f.url, path: acc.join('/') });
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
        listBox.innerHTML = "<li style='opacity:.65'>오늘 할당된 영상이 없습니다 문의 부탁</li>";
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
        listBox.innerHTML = "<li style='opacity:.65'>오늘 할당된 영상이 없습니다 문의 부탁</li>";
      }
      if (frame) frame.src = "";
      return;
    }

    // 챕터 순 정렬
    myVids.sort((a, b) => (a.chapter ?? 0) - (b.chapter ?? 0));

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
        main.append(`${v.chapter}. ${v.title}`);

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

  const unreadNoticeCount = 1;
  const badge = document.getElementById('badge');
  if (unreadNoticeCount > 0 && badge) {
    badge.textContent = String(unreadNoticeCount);
    badge.style.display = 'inline';
  }
  document.getElementById('setBtn')?.addEventListener('click', () => {
    if (badge) badge.style.display = 'none';
  });

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
   공지 모달(학생 측) – 투표/설문 제출 및 확인
──────────────────────────────────────────────────────────────────────────── */
(() => {
  const CT = { 'Content-Type': 'application/json' };
  const $ = s => document.querySelector(s);
  const SID = window.__STU_SID__ || decodeURIComponent(location.pathname.split('/').pop());

  const modal = $('#announceModal');
  const annTitle = $('#annTitle');
  const annContent = $('#annContent');
  const pollBox = $('#annPoll');
  const pollQ = $('#annPollQ');
  const pollOptsBox = $('#annPollOpts');
  const surveyBox = $('#annSurvey');
  const btnSubmit = $('#annSubmit');
  const btnConfirm = $('#annConfirm');

  if (!modal || !annTitle || !annContent || !btnSubmit || !btnConfirm) {
    console.warn('[announce] required elements not found on this page, skip init');
    return;
  }

  let pending = [];
  let active = null;
  let statusMap = {};

  function isAnswered(v) {
    if (v == null) return false;
    if (Array.isArray(v)) return v.length > 0;
    if (typeof v === 'string') return v.trim().length > 0;
    return true;
  }

  function fieldName(...parts) {
    return parts.map(part => String(part ?? '')).join('_');
  }

  function namedInputs(name) {
    return Array.from(document.getElementsByName(String(name)));
  }

  function appendRequiredBadge(el, required) {
    if (!required) return;
    const reqBadge = document.createElement('span');
    reqBadge.style.color = '#ef4444';
    reqBadge.style.fontWeight = '600';
    reqBadge.textContent = ' (필수)';
    el.appendChild(reqBadge);
  }

  function appendChoice(parent, type, name, value, checked, labelText) {
    const label = document.createElement('label');
    label.style.display = 'block';
    const input = document.createElement('input');
    input.type = type;
    input.name = String(name);
    input.value = String(value);
    input.checked = !!checked;
    label.append(input, ` ${labelText ?? ''}`);
    parent.appendChild(label);
  }

  function loadAnnouncements() {
    Promise.all([
      fetch('/api/announcements', { cache: 'no-store' }).then(r => r.json()),
      fetch(`/api/announce-status?sid=${encodeURIComponent(SID)}`, { cache: 'no-store' }).then(r => r.json())
    ]).then(([anns, stat]) => {
      statusMap = stat || {};

      const mine = (anns || []).filter(a => {
        const t = a.targets;
        return t === 'all' || (Array.isArray(t) && t.includes(SID));
      });

      pending = mine.filter(a => {
        const st = statusMap[a.id] || {};
        const acked = !!st.acked;

        const need = !!a.requireCompletion;
        const hasPoll = !!a.poll;
        const hasSurvey = Array.isArray(a.survey) && a.survey.length > 0;

        let done = true;

        if (hasPoll) {
          const pv = st.poll;
          const pollDone = Array.isArray(pv) ? pv.length > 0 : pv != null;
          if (!pollDone) done = false;
        }

        if (hasSurvey) {
          const sv = st.survey || {};
          for (const q of a.survey) {
            if (q.required) {
              if (!isAnswered(sv[q.id])) { done = false; break; }
            }
          }
        }

        if (need) {
          return !done;
        } else {
          return !acked;
        }
      });

      showNext();
    }).catch(err => {
      console.warn('[announce] loadAnnouncements failed:', err);
    });
  }

  function showNext() {
    if (!pending.length) { modal.style.display = 'none'; active = null; return; }
    active = pending[0];
    renderActive(active);
    modal.style.display = 'flex';
  }

  function renderActive(a) {
    annTitle.textContent = a.title || '공지';
    annContent.textContent = a.content || '';

    if (a.poll && a.poll.question && Array.isArray(a.poll.options)) {
      pollBox.style.display = '';
      pollQ.textContent = a.poll.question;
      const type = a.poll.multiple ? 'checkbox' : 'radio';
      const name = fieldName('poll', a.id);
      const st = statusMap[a.id]?.poll;

      pollOptsBox.textContent = '';
      a.poll.options.forEach((opt, i) => {
        const checked = Array.isArray(st) ? st.includes(i) : (st === i);
        const label = document.createElement('label');
        label.style.display = 'block';
        label.style.margin = '.25rem 0';
        const input = document.createElement('input');
        input.type = type;
        input.name = name;
        input.value = String(i);
        input.checked = checked;
        label.append(input, ` ${opt ?? ''}`);
        pollOptsBox.appendChild(label);
      });
    } else {
      pollBox.style.display = 'none';
      pollOptsBox.innerHTML = '';
    }

    if (Array.isArray(a.survey) && a.survey.length) {
      surveyBox.style.display = '';
      const st = statusMap[a.id]?.survey || {};
      surveyBox.textContent = '';
      a.survey.forEach(q => {
        const val = st[q.id] ?? '';
        const field = fieldName(a.id, q.id);
        const wrap = document.createElement('div');
        wrap.style.margin = '.5rem 0';
        const label = document.createElement('div');
        label.style.fontWeight = '600';
        label.textContent = q.label ?? '';
        appendRequiredBadge(label, q.required);
        wrap.appendChild(label);

        if (q.type === 'radio' && Array.isArray(q.options) && q.options.length) {
          q.options.forEach(op => appendChoice(wrap, 'radio', field, op, val === op, op));
        } else if (q.type === 'checkbox' && Array.isArray(q.options) && q.options.length) {
          const arr = Array.isArray(val) ? val : [];
          q.options.forEach(op => appendChoice(wrap, 'checkbox', field, op, arr.includes(op), op));
        } else {
          const input = document.createElement('input');
          input.type = 'text';
          input.name = field;
          input.value = typeof val === 'string' ? val : '';
          input.style.width = '100%';
          wrap.appendChild(input);
        }
        surveyBox.appendChild(wrap);
      });
    } else {
      surveyBox.style.display = 'none';
      surveyBox.innerHTML = '';
    }
  }

  btnSubmit.onclick = () => {
    if (!active) return;

    let pollAnswer = null;
    if (active.poll && active.poll.question) {
      const name = fieldName('poll', active.id);
      if (active.poll.multiple) {
        pollAnswer = namedInputs(name).filter(i => i.checked)
          .map(i => parseInt(i.value, 10));
      } else {
        const r = namedInputs(name).find(i => i.checked);
        pollAnswer = r ? parseInt(r.value, 10) : null;
      }
    }

    let surveyAnswers = null;
    if (Array.isArray(active.survey) && active.survey.length) {
      surveyAnswers = {};
      for (const q of active.survey) {
        const name = fieldName(active.id, q.id);
        if (q.type === 'checkbox') {
          const arr = namedInputs(name).filter(i => i.checked).map(i => i.value);
          surveyAnswers[q.id] = arr;
        } else if (q.type === 'radio') {
          const r = namedInputs(name).find(i => i.checked);
          surveyAnswers[q.id] = r ? r.value : null;
        } else {
          const t = namedInputs(name)[0];
          surveyAnswers[q.id] = t ? t.value : '';
        }
      }
    }

    fetch('/api/announce-submit', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify({
        sid: SID,
        id: active.id,
        pollAnswer,
        surveyAnswers
      })
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(() => loadAnnouncements())
      .catch(err => {
        console.warn('[announce] submit failed:', err);
        alert('제출 실패');
      });
  };

  btnConfirm.onclick = () => {
    if (!active) return;

    const need = !!active.requireCompletion;
    const st = statusMap[active.id] || {};
    const hasPoll = !!active.poll;
    const hasSurvey = Array.isArray(active.survey) && active.survey.length > 0;

    let done = true;

    if (hasPoll) {
      const pv = st.poll;
      const pollDone = Array.isArray(pv) ? pv.length > 0 : pv != null;
      if (!pollDone) done = false;
    }

    if (hasSurvey) {
      const sv = st.survey || {};
      for (const q of active.survey) {
        if (q.required) {
          if (!isAnswered(sv[q.id])) { done = false; break; }
        }
      }
    }

    if (need && !done) {
      modal.style.display = 'none';
      return;
    }

    fetch('/api/announce-ack', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify({ sid: SID, id: active.id })
    }).then(() => {
      modal.style.display = 'none';
      pending.shift();
      showNext();
    }).catch(err => console.warn('[announce] ack failed:', err));
  };

  loadAnnouncements();
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

        // ✅ 새 스키마
        const answerKeys = (t.answerKeys && typeof t.answerKeys === 'object') ? t.answerKeys : null;
        // ✅ 구 스키마(혹시 남아있으면 fallback 용)
        const answerKey = t.answerKey ?? t.answers ?? null;

        return { id, name, problems, curriculum, answerKeys, answerKey };
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
    for (const [key, cat] of Object.entries(TEST_CFG.categories || {})) {
      const label = String(cat.label || '').trim();
      const k = String(key || '').trim().toUpperCase();
      const lv = label.toUpperCase();

      if (typeVal === '단원평가') {
        if (lv.includes('단원') || lv.includes('UNIT') || k === 'UNIT') hits.push(key);
      } else if (typeVal === 'FINAL') {
        if (lv.includes('FINAL') || k === 'FINAL') hits.push(key);
      } else if (typeVal === 'HELL') {
        if (lv.includes('HELL') || k === 'HELL') hits.push(key);
      }
    }
    return hits;
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
      return same.length ? same : out;
    }
    return out;
  }

  function findTestById(typeVal, testId, myCur) {
    const list = listTestsForType(typeVal, myCur);
    return list.find(t => String(t.id) === String(testId)) || null;
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
                  <option value="단원평가" selected>단원평가</option>
                  <option value="FINAL">APEX FINAL</option>
                  <option value="HELL">APEX HELL</option>
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

    const myCur = getMyCurriculumFromNamebar();

    await loadTestsConfig();

    function renderTestOptions() {
      const type = selType.value;
      const list = listTestsForType(type, myCur);

      if (!list.length) {
        selTestId.innerHTML = `<option value="">(시험 없음)</option>`;
        infoEl.textContent = '등록된 시험이 없습니다. 선생님이 테스트 관리에서 시험/정답을 먼저 등록해야 합니다.';
        return;
      }

      selTestId.innerHTML = list.map(t => {
        const curTag = t.curriculum ? ` (${t.curriculum})` : '';
        return `<option value="${t.id}">${t.name}${curTag}</option>`;
      }).join('');

      updateInfo();
    }

    function updateInfo(extra) {
      const type = selType.value;
      const testId = selTestId.value;
      const round = parseInt(selRound.value, 10) || 1;
      const t = findTestById(type, testId, myCur);

      if (!t) {
        infoEl.textContent = '시험을 선택하세요.';
        return;
      }

      const key = getKeyForRound(t, round);
      const keyOk = Array.isArray(key) && key.length;

      let msg = `문항 수: ${t.problems}문항\n회차: ${round}회차\n`;
      msg += keyOk
        ? '정답키 등록됨 → 제출하면 서버가 자동 채점합니다.'
        : '정답키가 아직 등록되지 않았습니다 → 선생님께 말해 주세요.';

      if (extra) msg += `\n\n${extra}`;
      infoEl.textContent = msg;
    }

    const open = () => {
      renderTestOptions();
      answersTextEl.value = '';
      memoEl.value = '';
      modal.style.display = 'flex';
    };
    const close = () => { modal.style.display = 'none'; };

    btnOpen?.addEventListener('click', open);
    btnClose?.addEventListener('click', close);
    modal.addEventListener('click', (e) => { if (e.target === modal) close(); });

    selType.addEventListener('change', renderTestOptions);
    selTestId.addEventListener('change', updateInfo);
    selRound.addEventListener('change', updateInfo);

    btnSubmit?.addEventListener('click', async () => {
      const type = selType.value;
      const testId = selTestId.value;
      const round = parseInt(selRound.value, 10) || 1;
      const answersText = String(answersTextEl.value || '').trim();
      const memo = String(memoEl.value || '').trim();

      if (!testId) return alert('시험을 선택해주세요.');
      if (!answersText) return alert('답을 입력해주세요.');

      const t = findTestById(type, testId, myCur);
      if (!t) return alert('시험 정보를 찾지 못했습니다.');

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

        alert('제출 완료ヾ(^▽^*)))');
        try { localStorage.setItem('updPing', Date.now().toString()); } catch { }
        close();
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
      const fullName = (type === '단원평가') ? t.name : `${type} / ${t.name}`;

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
      alert('제출 완료ヾ(^▽^*)))');
      close();
    });
  }

  // ───────────── init ─────────────
  injectStyles();
  ensureModal();
  initLogic().catch(err => {
    console.warn('[test submit modal] init failed', err);
  });
})();
