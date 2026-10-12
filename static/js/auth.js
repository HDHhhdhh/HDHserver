/* global fetch */
const $ = (id) => document.getElementById(id);

// ✅ 토큰을 "마스터(계정)" / "액티브(현재 sid)"로 분리
const LS_TOKEN_ACTIVE = "studentToken";        // 학생 페이지에서 쓰는 토큰(기존 키 유지)
const LS_TOKEN_MASTER = "studentTokenMaster";  // ✅ curris 전체를 가져오기 위한 토큰
const LS_SID = "studentSid";

// ✅ curris 캐시(서버가 가끔 일부만 줄 때 보완용)
const LS_CURRIS = "studentCurrisCache"; // { aidOrSid: [{cur,sid}...] }
let pendingAuthRequests = 0;
let recommendationSequence = 0;
let modalSequence = 0;

function setMsg(text, type = "") {
  const el = $("msg");
  if (!el) return;
  el.className = "msg " + (type || "");
  el.textContent = text || "";
}

function setModalMsg(text, type = "") {
  const el = $("modalMsg");
  if (!el) return;
  el.className = "msg " + (type || "");
  el.textContent = text || "";
}

function setSpin(on) {
  const el = $("spin");
  if (!el) return;
  el.style.display = on ? "block" : "none";
}

function setLoggedInUI(on, whoText = "") {
  const loginBox = $("loginBox");
  const loggedBox = $("loggedBox");

  if (loginBox) loginBox.style.display = on ? "none" : "block";
  if (loggedBox) loggedBox.style.display = on ? "block" : "none";

  const who = $("loggedWho");
  if (who) who.textContent = whoText ? `${whoText} 로그인됨` : "로그인됨";
}

function openModal() {
  const back = $("modalBack");
  if (!back) return;
  modalSequence += 1;
  setModalMsg("", "");
  if ($("curPw")) $("curPw").value = "";
  if ($("newId")) $("newId").value = "";
  if ($("newPw")) $("newPw").value = "";
  back.style.display = "flex";
}

function closeModal() {
  const back = $("modalBack");
  if (!back) return;
  modalSequence += 1;
  back.style.display = "none";
}

function safeJSONParse(raw, fallback) {
  try { return raw ? JSON.parse(raw) : fallback; } catch { return fallback; }
}

function getActiveToken() {
  return localStorage.getItem(LS_TOKEN_ACTIVE) || "";
}
function getMasterToken() {
  // ✅ 마스터가 없으면 액티브를 임시 마스터로 사용(과거 데이터 호환)
  return localStorage.getItem(LS_TOKEN_MASTER) || localStorage.getItem(LS_TOKEN_ACTIVE) || "";
}
function setTokensOnLogin(token) {
  if (!token) return;
  // 로그인 토큰은 보통 계정 권한이 제일 넓으니 master/active 둘 다 세팅
  localStorage.setItem(LS_TOKEN_MASTER, token);
  localStorage.setItem(LS_TOKEN_ACTIVE, token);
}
function setActiveToken(token) {
  if (!token) return;
  localStorage.setItem(LS_TOKEN_ACTIVE, token);
}
function clearTokens() {
  localStorage.removeItem(LS_TOKEN_ACTIVE);
  localStorage.removeItem(LS_TOKEN_MASTER);
}

function loadCurrisCacheMap() {
  return safeJSONParse(localStorage.getItem(LS_CURRIS), {});
}
function saveCurrisCacheMap(map) {
  try { localStorage.setItem(LS_CURRIS, JSON.stringify(map || {})); } catch {}
}
function normalizeCurris(curris) {
  const arr = Array.isArray(curris) ? curris : [];
  const out = [];
  const seen = new Set();
  for (const it of arr) {
    const sid = String(it?.sid || "").trim();
    const cur = String(it?.cur || "").trim();
    if (!sid) continue;
    const key = sid; // sid 기준 dedup
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ sid, cur: cur || sid }); // ✅ cur가 비어도 sid로라도 보여줌
  }
  return out;
}

function getStoredSid() {
  return String(localStorage.getItem(LS_SID) || "").trim();
}

function pickPreferredSid(serverSid, curris) {
  const fromServer = String(serverSid || "").trim();
  const fromStorage = getStoredSid();
  const sidSet = new Set(normalizeCurris(curris).map((x) => x.sid));

  if (fromServer && (!sidSet.size || sidSet.has(fromServer))) return fromServer;
  if (fromStorage && (!sidSet.size || sidSet.has(fromStorage))) return fromStorage;
  if (fromServer) return fromServer;
  return fromStorage;
}

function setCurrentSid(sid) {
  const next = String(sid || "").trim();
  if (!next) return;
  localStorage.setItem(LS_SID, next);
}
function mergeCurrisPreferLonger(incoming, cached) {
  const a = normalizeCurris(incoming);
  const b = normalizeCurris(cached);

  // 서버가 일부만 준 경우(짧아진 경우) 캐시로 보강
  if (a.length && b.length && a.length < b.length) {
    const bySid = new Map(b.map(x => [x.sid, x]));
    for (const x of a) bySid.set(x.sid, x); // 서버값 우선
    return Array.from(bySid.values());
  }
  // 서버가 비었으면 캐시 사용
  if (!a.length && b.length) return b;
  return a;
}

async function api(path, body, token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = "Bearer " + token;

  let res;
  try {
    res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers,
    body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    return { ok: false, status: 0, data: null, networkError: true };
  }

  let data = null;
  try { data = await res.json(); } catch {}
  return { ok: res.ok, status: res.status, data };
}

async function apiWithSpinner(path, body, token) {
  pendingAuthRequests += 1;
  setSpin(true);
  try {
    return await api(path, body, token);
  } finally {
    pendingAuthRequests -= 1;
    setSpin(pendingAuthRequests > 0);
  }
}

function goStudentPageBySid(sid) {
  if (!sid) return;
  window.location.href = `/student/${encodeURIComponent(sid)}`;
}

/* =========================
   ✅ 커리 선택 UI (자동 생성)
   ========================= */

function ensureCuriUI() {
  const host = $("loggedBox") || document.body;
  if ($("curiWrap")) return;

  const wrap = document.createElement("div");
  wrap.id = "curiWrap";
  wrap.style.marginTop = "10px";
  wrap.style.padding = "10px";
  wrap.style.border = "1px solid rgba(0,0,0,.12)";
  wrap.style.borderRadius = "10px";

  wrap.innerHTML = `
    <div style="font-weight:700;margin-bottom:6px;">오늘 커리 선택</div>

    <!-- ✅ 추천 영역(자동) -->
    <div id="curiReco" style="display:none;padding:10px;border-radius:10px;border:1px solid rgba(0,0,0,.12);margin-bottom:10px;">
      <div style="font-weight:800;margin-bottom:6px;">오늘 추천</div>
      <div id="curiRecoText" style="opacity:.85;font-size:13px;margin-bottom:8px;"></div>
      <div style="display:flex;gap:8px;">
        <button id="curiRecoGoBtn" style="flex:1;padding:10px;border-radius:10px;">추천 커리로 이동</button>
        <button id="curiRecoHideBtn" style="padding:10px;border-radius:10px;">숨김</button>
      </div>
    </div>

    <select id="curiSelect" style="width:100%;padding:10px;border-radius:10px;border:1px solid rgba(0,0,0,.2);">
      <option value="">불러오는 중...</option>
    </select>
    <div style="display:flex;gap:8px;margin-top:10px;">
      <button id="curiGoBtn" style="flex:1;padding:10px;border-radius:10px;">이 커리로 이동</button>
      <button id="curiReloadBtn" style="padding:10px;border-radius:10px;">새로고침</button>
    </div>
    <div id="curiHint" style="margin-top:8px;opacity:.75;font-size:12px;"></div>
  `;

  host.appendChild(wrap);
}

function renderCurris(curris, currentSid, cacheKey = "") {
  ensureCuriUI();
  const sel = $("curiSelect");
  const hint = $("curiHint");
  if (!sel) return;

  const arr = normalizeCurris(curris);

  sel.innerHTML = "";
  if (!arr.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "커리 정보가 없음";
    sel.appendChild(opt);
    if (hint) hint.textContent = "서버 /api/auth/me 또는 /api/auth/login 응답에 curris가 필요함.";
    return;
  }

  for (const it of arr) {
    const opt = document.createElement("option");
    opt.value = it.sid;
    opt.textContent = it.cur;
    sel.appendChild(opt);
  }

  const selectedSid = pickPreferredSid(currentSid, arr);
  if (selectedSid) sel.value = selectedSid;

  if (hint) {
    hint.textContent = cacheKey
      ? `커리 선택 후 이동. (curris cache: ${cacheKey})`
      : "커리 선택 후 이동 누르면 해당 커리 학습 페이지로 감.";
  }
}

/* =========================
   ✅ switch + 이동
   ========================= */

async function switchAndGo(targetSid) {
  if (pendingAuthRequests) return;
  const token = getActiveToken();
  if (!token) { setMsg("로그인이 먼저다", "err"); return; }
  if (!targetSid) { setMsg("커리 선택해.", "err"); return; }

  const r = await apiWithSpinner("/api/auth/switch", { sid: targetSid }, token);

  if (r.ok && r.data?.ok) {
    // ✅ switch 토큰은 "현재 sid용"으로만 저장 (master는 유지)
    if (r.data?.token) setActiveToken(r.data.token);
    localStorage.setItem(LS_SID, targetSid);
    goStudentPageBySid(targetSid);
  } else {
    setMsg("커리 전환 실패.", "err");
  }
}

/* =========================
   ✅ (추가) 오늘 추천 커리 계산/표시
   ========================= */

function yoilChar(date = new Date()) {
  const W = "일월화수목금토";
  return W[date.getDay()];
}

function todaySlotLabels() {
  const y = yoilChar();
  return [ `${y}1`, `${y}2` ];
}

function extractScheduleLike(stu) {
  const candidates = [];

  const pushAny = (v) => {
    if (!v) return;
    if (Array.isArray(v)) { v.forEach(x => pushAny(x)); return; }
    if (typeof v === "object") {
      Object.keys(v).forEach(k => { if (v[k]) candidates.push(String(k)); });
      return;
    }
    candidates.push(String(v));
  };

  pushAny(stu.day);
  pushAny(stu.days);
  pushAny(stu.schedule);
  pushAny(stu.schedules);
  pushAny(stu.slots);
  pushAny(stu.slot);
  pushAny(stu.time);
  pushAny(stu.times);
  pushAny(stu.week);
  pushAny(stu.weekday);
  pushAny(stu.yoil);
  pushAny(stu.yoils);

  Object.keys(stu || {}).forEach(k => {
    if (/^(day|yoil|mon|tue|wed|thu|fri|sat|sun)/i.test(k)) pushAny(stu[k]);
  });

  return candidates
    .map(s => s.replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

function scheduleMatchesToday(scheduleStrs) {
  const [t1, t2] = todaySlotLabels();
  const norm = (s) =>
    String(s || "")
      .replace(/\s+/g, "")
      .replace(/요일/g, "")
      .replace(/시/g, "")
      .trim();

  const has = (want) => {
    const w = norm(want);
    return scheduleStrs.some(s => {
      const n = norm(s);
      return n.includes(w);
    });
  };

  const hits = [];
  if (has(t1)) hits.push(t1);
  if (has(t2)) hits.push(t2);
  return hits;
}

async function pickRecommendedSidFromServerData(curris, currentSid) {
  const arr = Array.isArray(curris) ? curris : [];
  if (!arr.length) return null;

  let students = [];
  try {
    // ✅ 여기 학생목록이 권한 필요하면 서버에서 공개/제한된 목록을 주는지 확인 필요
    students = await fetch("/api/students", { cache: "no-store" }).then(r => r.json());
  } catch {
    students = [];
  }
  if (!Array.isArray(students) || !students.length) return null;

  const bySid = new Map(students.map(s => [String(s?.id || ""), s]));
  const candidates = [];

  for (const it of arr) {
    const sid = String(it?.sid || "").trim();
    if (!sid) continue;
    const stu = bySid.get(sid);
    if (!stu) continue;

    const sch = extractScheduleLike(stu);
    const hits = scheduleMatchesToday(sch);

    if (hits.length) {
      candidates.push({
        sid,
        cur: String(it?.cur || "").trim(),
        hits,
        raw: sch,
      });
    }
  }

  if (!candidates.length) return null;

  const curHit = candidates.find(x => x.sid === String(currentSid || ""));
  if (curHit) return curHit;

  const [t1] = todaySlotLabels();
  candidates.sort((a, b) => {
    const a1 = a.hits.includes(t1) ? 0 : 1;
    const b1 = b.hits.includes(t1) ? 0 : 1;
    if (a1 !== b1) return a1 - b1;
    return String(a.cur).localeCompare(String(b.cur), "ko");
  });

  return candidates[0];
}

async function showRecommendation(curris, currentSid) {
  const sequence = ++recommendationSequence;
  const token = getActiveToken();
  ensureCuriUI();

  const box = $("curiReco");
  const txt = $("curiRecoText");
  if (!box || !txt) return;

  if (sessionStorage.getItem("hideCuriReco") === "1") {
    box.style.display = "none";
    return;
  }

  box.dataset.sid = '';
  txt.textContent = '오늘 추천을 확인하는 중…';
  box.style.display = 'block';
  const go = $('curiRecoGoBtn');
  if (go) go.disabled = true;
  const reco = await pickRecommendedSidFromServerData(curris, currentSid);
  if (sequence !== recommendationSequence) return;
  if (token !== getActiveToken() || String(currentSid) !== localStorage.getItem(LS_SID) ||
      sessionStorage.getItem('hideCuriReco') === '1') {
    box.style.display = 'none';
    return;
  }
  if (go) go.disabled = false;

  if (!reco?.sid) {
    box.style.display = "none";
    return;
  }

  const slotText = (reco.hits || []).join(", ");
  txt.textContent = `${reco.cur}  (${slotText || "오늘"})`;

  box.dataset.sid = reco.sid;
  box.style.display = "block";
}

/* =========================
   자동로그인: me로 curris까지 표시
   ========================= */

async function autoLogin() {
  if (pendingAuthRequests) return false;
  const master = getMasterToken();
  const active = getActiveToken();
  if (!master && !active) return;

  // ✅ me는 master로 (없으면 active)
  const r = await apiWithSpinner("/api/auth/me", null, master || active);
  if (r.networkError || r.status >= 500 || (r.ok && !r.data)) {
    setMsg("서버에 연결하지 못했습니다. 다시 시도해 주세요.", "err");
    return false;
  }

  if (r.ok && r.data?.ok && r.data?.sid) {
    const sidFromServer = String(r.data.sid || "");
    const aid = String(r.data.aid || "");

    // ✅ master 토큰이 없었던 옛 세션이면, me가 성공한 토큰을 master로 박아두는게 안정적
    if (!localStorage.getItem(LS_TOKEN_MASTER)) {
      // 여기서 토큰을 새로 안 주면 그냥 active를 master로 사용
      if (active) localStorage.setItem(LS_TOKEN_MASTER, active);
    }

    // ✅ curris: 서버값 + 캐시 보강
    const cacheMap = loadCurrisCacheMap();
    const cacheKey = (aid || sidFromServer || "me").trim();
    const cached = cacheMap[cacheKey] || [];
    const merged = mergeCurrisPreferLonger(r.data?.curris, cached);
    const currentSid = pickPreferredSid(sidFromServer, merged);
    setCurrentSid(currentSid);

    setLoggedInUI(true, aid && aid !== currentSid ? `${aid} (현재: ${currentSid})` : currentSid);
    setMsg("", "");

    if (merged.length) {
      cacheMap[cacheKey] = merged;
      saveCurrisCacheMap(cacheMap);

      renderCurris(merged, currentSid, cacheKey);
      await showRecommendation(merged, currentSid);
    }
  } else {
    clearTokens();
    localStorage.removeItem(LS_SID);
    setLoggedInUI(false);
  }
  return !!(r.ok && r.data?.ok && r.data?.sid);
}

/* =========================
   로그인: login 응답의 curris로 렌더
   ========================= */

async function login() {
  if (pendingAuthRequests) return;
  const id = ($("sid")?.value || "").trim();
  const password = ($("pw")?.value || "").trim();

  if (!id || !password) {
    setMsg("아이디/비밀번호 입력해.", "err");
    return;
  }

  const r = await apiWithSpinner("/api/auth/login", { id, password });

  if (r.ok && r.data?.ok && r.data?.token && r.data?.sid) {
    // ✅ 로그인 토큰은 master+active로 저장
    setTokensOnLogin(r.data.token);

    const sid = String(r.data.sid || "");
    const aid = String(r.data.aid || "");

    // ✅ curris: 서버값 + 캐시 보강
    const cacheMap = loadCurrisCacheMap();
    const cacheKey = (aid || sid || "me").trim();
    const cached = cacheMap[cacheKey] || [];
    const merged = mergeCurrisPreferLonger(r.data?.curris, cached);
    const currentSid = pickPreferredSid(sid, merged);
    setCurrentSid(currentSid);
    setLoggedInUI(true, aid && aid !== currentSid ? `${aid} (현재: ${currentSid})` : currentSid);

    if (merged.length) {
      cacheMap[cacheKey] = merged;
      saveCurrisCacheMap(cacheMap);

      renderCurris(merged, currentSid, cacheKey);
      setMsg("로그인됨. 아래에서 커리 선택하고 이동해.", "ok");
      await showRecommendation(merged, currentSid);
    } else {
      setMsg("로그인됨. 커리 불러오는 중...", "ok");
      await autoLogin();
    }
  } else {
    const m =
      r.data?.error === "unknown id" ? "없는 아이디야." :
      r.data?.error === "bad password" ? "비밀번호 틀림." :
      r.data?.error === "no linked sids" ? "이 계정에 연결된 커리가 없음." :
      "로그인 실패.";
    setMsg(m, "err");
  }
}

function logout() {
  recommendationSequence += 1;
  const recommendation = $('curiReco');
  if (recommendation) recommendation.style.display = 'none';
  clearTokens();
  localStorage.removeItem(LS_SID);
  setLoggedInUI(false);
  setMsg("로그아웃됨.", "ok");
}

async function saveChange() {
  if (pendingAuthRequests) return;
  const saveModalSequence = modalSequence;
  const token = getActiveToken();
  if (!token) {
    setModalMsg("로그인 상태가 아님.", "err");
    return;
  }

  const curPw = ($("curPw")?.value || "").trim();
  const newId = ($("newId")?.value || "").trim();
  const newPw = ($("newPw")?.value || "").trim();

  if (!curPw) {
    setModalMsg("현재 비밀번호는 입력해야 함.", "err");
    return;
  }
  if (!newId && !newPw) {
    setModalMsg("바꿀 내용이 없음.", "err");
    return;
  }

  const r = await apiWithSpinner("/api/auth/change", { curPw, newId, newPw }, token);

  if (r.ok && r.data?.ok) {
    // change가 token을 주면 active 갱신 + master도 같이 갱신(보통 계정 토큰)
    if (r.data?.token) setTokensOnLogin(r.data.token);

    let recommendation = null;
    const rr = await api("/api/auth/me", null, getMasterToken());
    if (rr.ok && rr.data?.ok) {
      const sid = String(rr.data.sid || "");
      const aid = String(rr.data.aid || "");

      const cacheMap = loadCurrisCacheMap();
      const cacheKey = (aid || sid || "me").trim();
      const cached = cacheMap[cacheKey] || [];
      const merged = mergeCurrisPreferLonger(rr.data?.curris, cached);
      const currentSid = pickPreferredSid(sid, merged);
      setCurrentSid(currentSid);
      setLoggedInUI(true, aid && aid !== currentSid ? `${aid} (현재: ${currentSid})` : currentSid);

      if (merged.length) {
        cacheMap[cacheKey] = merged;
        saveCurrisCacheMap(cacheMap);

        renderCurris(merged, currentSid, cacheKey);
        recommendation = showRecommendation(merged, currentSid);
      }
    }

    if (saveModalSequence === modalSequence) {
      setModalMsg("변경 완료.", "ok");
      setTimeout(() => {
        if (saveModalSequence === modalSequence) closeModal();
      }, 300);
    }
    setMsg("아이디/비밀번호 변경됨.", "ok");
    await recommendation;
  } else {
    const m =
      r.data?.error === "bad password" ? "현재 비밀번호가 틀림." :
      r.data?.error === "id taken" ? "이미 있는 아이디임." :
      r.data?.error ? `실패: ${r.data.error}` :
      "변경 실패.";
    setModalMsg(m, "err");
  }
}

function initEvents() {
  $("loginBtn")?.addEventListener("click", login);
  $("pw")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") login();
  });

  $("goBtn")?.addEventListener("click", async () => {
    const targetSid = ($("curiSelect")?.value || "").trim() || localStorage.getItem(LS_SID);
    await switchAndGo(targetSid);
  });

  $("logoutBtn")?.addEventListener("click", logout);
  $("clearBtn")?.addEventListener("click", logout);

  $("changeBtn")?.addEventListener("click", openModal);
  $("closeModalBtn")?.addEventListener("click", closeModal);

  $("modalBack")?.addEventListener("click", (e) => {
    if (e.target === $("modalBack")) closeModal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  $("saveChangeBtn")?.addEventListener("click", saveChange);

  window.addEventListener("storage", (e) => {
    if (e.key !== LS_SID) return;
    const sid = String(e.newValue || "").trim();
    const sel = $("curiSelect");
    if (sel && sid) sel.value = sid;
  });

  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (!t) return;

    if (t.id === "curiGoBtn") {
      const targetSid = ($("curiSelect")?.value || "").trim();
      await switchAndGo(targetSid);
    }

    if (t.id === "curiReloadBtn") {
      if (await autoLogin()) setMsg("커리 갱신됨", "ok");
    }

    if (t.id === "curiRecoGoBtn") {
      const sid = String($("curiReco")?.dataset?.sid || "").trim();
      if (sid) await switchAndGo(sid);
    }

    if (t.id === "curiRecoHideBtn") {
      sessionStorage.setItem("hideCuriReco", "1");
      const box = $("curiReco");
      if (box) box.style.display = "none";
    }
  });
}

initEvents();
autoLogin();
