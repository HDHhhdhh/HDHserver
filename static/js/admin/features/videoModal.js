// /js/admin/features/videoModal.js
// 영상 배정 모달 (NO absences fetch - avoids "absent revive")
// - 챕터 번호 기준 정렬
// - sid 키 정규화
// - 드래그 다중 선택 유지
// - ✅ updates 저장 포맷을 "배열"로 통일
// - ✅ A:Ble 자동배정 1개 / APEX 자동배정 2개
// - ✅ 자동배정은 "오늘 학생 표(오늘 수업 대상)"에만 적용
// - ✅ 결석 데이터는 "절대 fetch/overwrite 하지 않음" (state.absentByDate 읽기만)

import { $, CT, toast, todayLocalKey } from '../core/utils.js';
import { state } from '../core/state.js';

let editingSid = null;

function ensureModal() {
  if ($('#vidModal')) return;
  document.body.insertAdjacentHTML('beforeend', `
    <div id="vidModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);justify-content:center;align-items:center;z-index:9998">
      <div style="background:#fff;padding:1rem;border-radius:8px;max-height:80%;overflow:auto;width:360px">
        <h3 id="mTitle" style="margin-top:0"></h3>
        <div id="chkZone"></div>
        <div style="text-align:right;margin-top:.6rem">
          <button id="mSave">저장</button>
          <button id="mClose">닫기</button>
        </div>
      </div>
    </div>`);
}

/* ───────────── 공통 fetch helpers ───────────── */
async function getJSON(url) {
  const res = await fetch(url, { cache: 'no-store' });
  let data = null;
  try { data = await res.json(); } catch {}
  return { res, data };
}

function unwrapOkPayload(data, keyHint) {
  if (!data || typeof data !== 'object') return null;

  if (data.ok === true) {
    if (keyHint && data[keyHint] && typeof data[keyHint] === 'object') return data[keyHint];
    const cloned = { ...data };
    delete cloned.ok;
    delete cloned.error;
    return cloned;
  }
  return data;
}

/* ───────────── 최소 hydrate (결석 제외) ───────────── */
async function hydrateUpdates() {
  try {
    const { res, data } = await getJSON('/api/updates');
    if (!res.ok) return false;

    const obj = unwrapOkPayload(data, 'updates');
    if (obj && typeof obj === 'object') {
      state.updates = obj;
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

async function hydrateLogsEntry(today, sid) {
  // 있으면 사용, 없으면 무시
  try {
    const q = new URLSearchParams({ date: String(today), sid: String(sid) }).toString();
    const { res, data } = await getJSON(`/api/logs/entry?${q}`);
    if (!res.ok) return false;

    const entry = (data?.ok === true)
      ? (data.entry && typeof data.entry === 'object' ? data.entry : {})
      : (data && typeof data === 'object' ? data : {});

    state.logs = state.logs || {};
    state.logs[today] = state.logs[today] || {};
    state.logs[today][String(sid)] = entry;
    return true;
  } catch {
    return false;
  }
}

async function hydrateExtraAttend(today) {
  // 있으면 사용, 없으면 무시
  const candidates = ['/api/extra-attend', '/api/extra', '/api/extra_attend', '/api/extra-attend/all'];
  for (const url of candidates) {
    try {
      const { res, data } = await getJSON(url);
      if (!res.ok) continue;

      const obj = unwrapOkPayload(data, 'extra') || unwrapOkPayload(data, 'data') || data;
      if (obj && typeof obj === 'object') {
        state.extra = obj;
        if (!Array.isArray(state.extra[today])) state.extra[today] = state.extra[today] || [];
        return true;
      }
    } catch {}
  }
  return false;
}

async function hydrateProgressMaybe() {
  try {
    if (state.progress && typeof state.progress === 'object' && Object.keys(state.progress).length) return true;

    const { res, data } = await getJSON('/api/progress');
    if (!res.ok) return false;

    const obj = unwrapOkPayload(data, 'progress') || unwrapOkPayload(data, 'data') || data;
    if (obj && typeof obj === 'object') {
      state.progress = obj;
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

async function hydrateForVideoModal(today, sid) {
  await Promise.allSettled([
    hydrateUpdates(),
    hydrateLogsEntry(today, sid),
    hydrateExtraAttend(today),
    hydrateProgressMaybe(),
  ]);
}

/* ───────────── 챕터 정렬 ───────────── */
const chapNum = v => {
  const c = (v?.chapter ?? 0);
  const n = Number(c);
  return Number.isNaN(n)
    ? parseFloat(String(c).replace(/[^0-9.]/g, '')) || 0
    : n;
};

const byChapterAsc = (a, b) =>
  chapNum(a) - chapNum(b) ||
  String(a.title || '').localeCompare(String(b.title || ''), 'ko') ||
  String(a.mid).localeCompare(String(b.mid));

/* ───────────── updates 읽기/쓰기 ───────────── */
function readAssignFor(updates, day, sid) {
  const dmap = updates?.[day] || {};
  const k1 = String(sid);
  const k2 = Number.isFinite(+sid) ? String(+sid) : null;
  const raw = dmap[k1] ?? (k2 != null ? dmap[k2] : undefined);

  if (Array.isArray(raw)) return raw.map(String);
  if (raw && Array.isArray(raw.videos)) return raw.videos.map(String);
  return [];
}

function writeAssignFor(updates, day, sid, arr) {
  const k = String(sid);
  updates[day] = updates[day] || {};
  const dmap = updates[day];

  const numKey = Number.isFinite(+sid) ? String(+sid) : null;
  if (numKey && numKey !== k && dmap[numKey] !== undefined) delete dmap[numKey];

  dmap[k] = arr.map(String);
}

/* ───────────── 오늘 학생 표(오늘 수업 대상) 판정 ───────────── */
/** today.js의 computeTodayList와 동일 기준(결석/완료/정규/보강) */
function isTodayStudent(stu) {
  if (!stu) return false;

  const today = todayLocalKey();
  const WCHR = '일월화수목금토';
  const wchr = WCHR[new Date(today).getDay()];
  const sid = String(stu.id ?? '');
  if (!sid) return false;

  const dayValues = (s) => Object.keys(s || {})
    .filter(k => /^day\d+$/.test(k) && s[k])
    .sort((a, b) => parseInt(a.slice(3), 10) - parseInt(b.slice(3), 10))
    .map(k => String(s[k]));

  const hasWeekday = (s, w) => dayValues(s).some(v => String(v).startsWith(w));

  // ✅ 결석 제외: 영상 모달은 state.absentByDate를 "읽기만" 한다
  const absentByDate = (state.absentByDate && typeof state.absentByDate === 'object') ? state.absentByDate : {};
  const absentSet = new Set((absentByDate[today] || []).map(String));
  if (absentSet.has(sid)) return false;

  // ✅ 오늘 done:true 제외
  const logsToday = (state.logs && state.logs[today]) ? state.logs[today] : {};
  if (logsToday?.[sid]?.done === true) return false;

  // 정규 등원 or 보강이면 포함
  const regular = hasWeekday(stu, wchr);

  const extra = state.extra || {};
  const extraIds = Array.isArray(extra[today]) ? extra[today].map(String) : [];
  const isExtra = extraIds.includes(sid);

  return regular || isExtra;
}

/* ───────────── 메인 ───────────── */
export function initVideoModal() {
  ensureModal();

  const vidModal = $('vidModal');
  const mTitle = $('mTitle');
  const chkZone = $('chkZone');

  document.body.addEventListener('click', async (e) => {
    const btn = e.target.closest('.editVid');
    if (!btn) return;

    editingSid = btn.closest('tr')?.dataset.sid;
    const stu = state.students.find(x => String(x.id) === String(editingSid));
    if (!stu) { alert('학생 정보를 찾을 수 없습니다.'); return; }

    const today = todayLocalKey();

    // ✅ 결석 관련 fetch 없음. 필요한 것만 hydrate.
    await hydrateForVideoModal(today, editingSid);

    mTitle.textContent = `${stu.name} – ${stu.curriculum} (${stu.subCurriculum || '전체'})`;

    const curKey = (stu.curriculum || '').trim().toLowerCase();
    const subKey = (stu.subCurriculum || '').trim().toLowerCase();

    // ① 과목+소과목 필터
    let curVids = (state.videos || [])
      .filter(v =>
        String(v.curriculum || '').trim().toLowerCase() === curKey &&
        String(v.subCurriculum || '').trim().toLowerCase() === subKey
      )
      .slice()
      .sort(byChapterAsc);

    // fallback: 소과목 안 맞으면 과목만
    if (!curVids.length) {
      curVids = (state.videos || [])
        .filter(v => String(v.curriculum || '').trim().toLowerCase() === curKey)
        .slice()
        .sort(byChapterAsc);
    }

    let assigned = readAssignFor(state.updates, today, editingSid);

    // ✅ 자동배정 허용 조건: "오늘 학생 표(오늘 수업 대상)"인 경우에만
    const allowAutoAssign = isTodayStudent(stu);

    // ② 기본 자동 추천 (비어 있을 때만) + 오늘 수업 대상일 때만
    if (assigned.length === 0 && allowAutoAssign) {
      const lastStatus = {};
      const datesAsc = Object.keys(state.progress || {}).sort();
      for (const d of datesAsc) {
        const perSid = state.progress[d]?.[editingSid];
        if (!perSid) continue;
        for (const [mid, st] of Object.entries(perSid)) {
          if (mid === 'tests') continue;
          lastStatus[mid] = st;
        }
      }

      const blocked = {};
      for (const [mid, st] of Object.entries(lastStatus)) {
        if (st === 'done' || st === 'skip') blocked[mid] = true;
      }

      // ✅ 자동배정 개수 규칙
      const subRaw = (stu.subCurriculum || '').trim();
      const maxAssign =
        subRaw === 'A:Ble' ? 1 :
        subRaw === 'APEX' ? 2 :
        2;

      const toAssign = [];
      for (const v of curVids) {
        if (!blocked[v.mid]) toAssign.push(String(v.mid));
        if (toAssign.length >= maxAssign) break;
      }

      assigned = toAssign;

      // ✅ 배열 포맷으로 저장
      state.updates = state.updates || {};
      writeAssignFor(state.updates, today, editingSid, assigned);
      fetch('/api/updates', {
        method: 'POST',
        headers: CT,
        body: JSON.stringify(state.updates)
      }).catch(() => {});
    }

    // ③ 체크박스 렌더
    const note = (!allowAutoAssign && assigned.length === 0)
      ? `<div style="margin:0 0 8px 0;padding:8px 10px;border-radius:10px;background:rgba(59,130,246,.12);font-size:12px;line-height:1.35">
           자동배정은 <b>오늘 학생 표(오늘 수업 대상)</b>일 때만 작동합니다. (지금은 자동배정 안 함)
         </div>`
      : '';

    chkZone.innerHTML = curVids.length
      ? note + curVids.map(v => `
        <label style="display:block;user-select:none;cursor:pointer">
          <input type="checkbox" value="${v.mid}"
            ${assigned.includes(String(v.mid)) ? 'checked' : ''}>
          ${v.chapter}. ${v.title}
        </label>
      `).join('')
      : `<div style="padding:6px 4px;color:#666;font-size:13px">
          해당 과목 영상이 없습니다.
        </div>`;

    vidModal.style.display = 'flex';
  });

  /* ───────────── 닫기 ───────────── */
  document.body.addEventListener('click', (e) => {
    if (e.target.id === 'mClose' || e.target.id === 'vidModal') {
      $('vidModal').style.display = 'none';
    }
  });

  /* ───────────── 드래그 다중 선택 ───────────── */
  let pointerDown = false;
  let dragActive = false;
  let dragCheckValue = null;
  let startCheckbox = null;
  let startChecked = false;
  let suppressClickOnce = false;

  function findCheckboxFromEventTarget(target) {
    const label = target.closest('label');
    if (!label) return null;
    return label.querySelector('input[type="checkbox"]');
  }

  chkZone.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    const cb = findCheckboxFromEventTarget(e.target);
    if (!cb) return;

    pointerDown = true;
    dragActive = false;
    dragCheckValue = null;
    startCheckbox = cb;
    startChecked = cb.checked;
  });

  chkZone.addEventListener('mousemove', (e) => {
    if (!pointerDown) return;
    const cb = findCheckboxFromEventTarget(e.target);
    if (!cb) return;

    if (!dragActive) {
      dragActive = true;
      dragCheckValue = !startChecked;
      if (startCheckbox) startCheckbox.checked = dragCheckValue;
    }

    cb.checked = dragCheckValue;
    e.preventDefault();
  });

  chkZone.addEventListener('mouseover', (e) => {
    if (!pointerDown) return;
    const cb = findCheckboxFromEventTarget(e.target);
    if (!cb) return;

    if (!dragActive) {
      dragActive = true;
      dragCheckValue = !startChecked;
      if (startCheckbox) startCheckbox.checked = dragCheckValue;
    }

    cb.checked = dragCheckValue;
    e.preventDefault();
  });

  chkZone.addEventListener('click', (e) => {
    if (!suppressClickOnce) return;
    const cb = findCheckboxFromEventTarget(e.target);
    if (!cb) return;
    e.preventDefault();
    e.stopPropagation();
    suppressClickOnce = false;
  });

  document.addEventListener('mouseup', () => {
    if (!pointerDown) return;
    pointerDown = false;
    if (dragActive) suppressClickOnce = true;

    dragActive = false;
    dragCheckValue = null;
    startCheckbox = null;
  });

  /* ───────────── 저장 ───────────── */
  $('mSave').onclick = () => {
    const today = todayLocalKey();
    const selected = Array.from(
      document.querySelectorAll('#chkZone input[type="checkbox"]:checked')
    ).map(b => String(b.value));

    state.updates = state.updates || {};

    if (selected.length) {
      writeAssignFor(state.updates, today, editingSid, selected);
    } else {
      state.updates[today] = state.updates[today] || {};
      delete state.updates[today][String(editingSid)];
    }

    fetch('/api/updates', {
      method: 'POST',
      headers: CT,
      body: JSON.stringify(state.updates)
    })
      .then(() => fetch('/api/updates', { cache: 'no-store' }))
      .then(r => r.json())
      .then(u => {
        const obj = unwrapOkPayload(u, 'updates') || u;
        if (obj && typeof obj === 'object') state.updates = obj;
        toast('저장 완료');
        $('vidModal').style.display = 'none';
        document.dispatchEvent(new CustomEvent('admin:refresh'));
      })
      .catch(() => toast('저장 실패'));
  };
}
