import { $, CT, toast } from '../core/utils.js';
import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import { setAttended, setContacted } from './today.state.js';
import { normalizeSearch, studentSearchKey } from '../../shared/search.js';

async function clearTodayOrder(dateStr) {
  try {
    const map = await fetch('/api/today_order', { cache: 'no-store' }).then(r => r.json()).catch(() => ({}));
    if (map && map[dateStr]) {
      delete map[dateStr];
      await fetch('/api/today_order', { method: 'POST', headers: CT, body: JSON.stringify(map) });
    }
  } catch { /* ignore */ }
}

function ensureWindowStateAlias() {
  window.state = window.state || state;
  window.state.absences = state.absences;
  window.state.absentByDate = state.absentByDate;
}

function normalizeAbsentByDateMap(value) {
  const out = {};
  if (!value || typeof value !== 'object') return out;
  for (const [date, ids] of Object.entries(value)) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(date))) continue;
    const arr = Array.isArray(ids) ? ids : [];
    out[date] = Array.from(new Set(arr.map(x => String(x).trim()).filter(Boolean)));
  }
  return out;
}

function normalizeAbsencesByStudent(value) {
  const out = {};
  if (!value || typeof value !== 'object') return out;
  for (const [sid, date] of Object.entries(value)) {
    if (!sid || typeof date !== 'string') continue;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) continue;
    out[String(sid)] = date;
  }
  return out;
}

function applyAbsentPayload(payload) {
  state.absentByDate = normalizeAbsentByDateMap(payload?.by_date || payload?.absentByDate || {});
  state.absences = normalizeAbsencesByStudent(payload?.by_student || payload?.absences || {});
  ensureWindowStateAlias();
}

async function loadAbsentPayload() {
  try {
    const payload = await fetch('/api/absent', { cache: 'no-store' }).then(r => r.json());
    applyAbsentPayload(payload);
    return payload;
  } catch {
    return {
      by_date: state.absentByDate || {},
      by_student: state.absences || {},
    };
  }
}

async function loadExtraAttendMap() {
  try {
    const extra = await fetch('/api/extra-attend', { cache: 'no-store' }).then(r => r.json());
    if (extra && typeof extra === 'object') state.extra = extra;
  } catch { /* keep state.extra */ }
  return state.extra || {};
}

function escapeAttr(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function dayValues(stu) {
  return Object.keys(stu || {})
    .filter(k => /^day\d+$/.test(k) && stu[k])
    .sort((a, b) => parseInt(a.slice(3), 10) - parseInt(b.slice(3), 10))
    .map(k => String(stu[k]));
}

function hasRegularOnDate(stu, dateStr) {
  const wchr = '일월화수목금토'[new Date(dateStr).getDay()];
  return dayValues(stu).some(v => v.startsWith(wchr));
}

function collectAbsenceCandidates(dateStr, extraMap) {
  const absentSet = new Set((state.absentByDate?.[dateStr] || []).map(String));
  const extraSet = new Set((extraMap?.[dateStr] || []).map(String));
  const bySid = new Map();

  for (const stu of state.students || []) {
    const sid = String(stu?.id ?? '');
    if (!sid || absentSet.has(sid)) continue;
    if (hasRegularOnDate(stu, dateStr) || extraSet.has(sid)) {
      bySid.set(sid, stu);
    }
  }

  return Array.from(bySid.values())
    .sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'ko'));
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: CT,
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${url} ${res.status}`);
  return res;
}

async function patchFlagRemote(kind, date, sid, checked) {
  const url = kind === 'att' ? '/api/attendance/patch' : '/api/contact/patch';
  await postJSON(url, { date, sid: String(sid), value: !!checked });
}

function ensure() {
  if ($('#absentRegisterModal')) return;

  document.body.insertAdjacentHTML('beforeend', `
    <div id="absentRegisterModal" class="absent-backdrop" style="display:none" aria-modal="true" role="dialog">
      <div class="absent-panel">
        <div class="absent-topbar">
          <div class="absent-head">
            <h3 class="absent-title">결석 등록</h3>
            <div class="absent-actions absent-actions-top">
              <button type="button" class="absent-btn primary absent-save">저장</button>
              <button type="button" class="absent-btn absent-close">닫기</button>
            </div>
          </div>
          <div class="absent-search-row">
            <input type="search" id="absentSearch" class="absent-search" placeholder="학생 이름 검색" autocomplete="off">
            <button type="button" id="absentSearchPick" class="absent-btn">선택</button>
          </div>
          <div id="absentSearchHint" class="absent-search-hint" aria-live="polite"></div>
        </div>
        <div id="absentZone"></div>
        <div class="absent-actions absent-actions-bottom">
          <button type="button" class="absent-btn primary absent-save">저장</button>
          <button type="button" class="absent-btn absent-close">닫기</button>
        </div>
      </div>
    </div>
  `);

  const s = document.createElement('style');
  s.id = 'absentRegisterTheme';
  s.textContent = `
  #absentRegisterModal.absent-backdrop{
    position:fixed; inset:0; display:flex; align-items:center; justify-content:center;
    background:rgba(0,0,0,.45); z-index:9999;
  }
  #absentRegisterModal .absent-panel{
    width:546px; max-width:96vw; height:min(842px, 92vh); max-height:92vh;
    display:flex; flex-direction:column; overflow:hidden;
    border-radius:16px; padding:18px; box-sizing:border-box;
    border:1px solid var(--line, #334155);
    background:var(--card-dark, #0f172a);
    color:var(--text-dark, #e5e7eb);
    box-shadow:0 12px 34px rgba(0,0,0,.34);
  }
  body:not(.dark) #absentRegisterModal .absent-panel{
    background:var(--card-light, #ffffff);
    color:var(--text, #0f172a);
    border-color:var(--line, #e5e7eb);
  }
  #absentRegisterModal .absent-topbar{
    flex:0 0 auto;
    position:sticky; top:-18px; z-index:2;
    margin:-18px -18px 13px; padding:18px 18px 13px;
    background:var(--card-dark, #0f172a);
    border-bottom:1px solid color-mix(in oklab, var(--line, #334155) 80%, transparent);
  }
  body:not(.dark) #absentRegisterModal .absent-topbar{
    background:var(--card-light, #ffffff);
    border-bottom-color:color-mix(in oklab, var(--line, #e5e7eb) 80%, transparent);
  }
  #absentRegisterModal .absent-head{ display:flex; align-items:center; justify-content:space-between; gap:13px }
  #absentRegisterModal .absent-title{ margin:0; font-size:21px; font-weight:800 }
  #absentRegisterModal .absent-actions{ display:flex; gap:10px; justify-content:flex-end; margin-top:13px }
  #absentRegisterModal .absent-actions-top{ margin-top:0; flex-shrink:0 }
  #absentRegisterModal .absent-search-row{ display:flex; gap:10px; margin-top:13px }
  #absentRegisterModal .absent-search{
    min-width:0; flex:1; height:47px; box-sizing:border-box;
    border:1px solid var(--line, #334155);
    border-radius:13px; padding:0 13px;
    font-size:17px;
    background:color-mix(in oklab, var(--card-dark, #0f172a) 90%, #ef4444);
    color:var(--text-dark, #e5e7eb);
    outline:none;
  }
  body:not(.dark) #absentRegisterModal .absent-search{
    background:color-mix(in oklab, #ffffff 92%, #ef4444);
    color:var(--text, #0f172a);
    border-color:var(--line, #e5e7eb);
  }
  #absentRegisterModal .absent-search:focus{
    border-color:#dc2626;
    box-shadow:0 0 0 2px rgba(220,38,38,.22);
  }
  #absentRegisterModal .absent-search::placeholder{ color:currentColor; opacity:.55 }
  #absentRegisterModal .absent-search-row .absent-btn{ height:47px; white-space:nowrap }
  #absentRegisterModal .absent-search-hint{
    min-height:21px; margin-top:7px; font-size:16px; line-height:21px; opacity:.7;
  }
  #absentRegisterModal .absent-btn{
    border:1px solid var(--line, #334155);
    background:color-mix(in oklab, var(--card-dark, #0f172a) 85%, #ef4444);
    color:var(--text-dark, #e5e7eb);
    border-radius:13px; padding:9px 16px; cursor:pointer; font-weight:600;
    font-size:17px;
  }
  body:not(.dark) #absentRegisterModal .absent-btn{
    background:color-mix(in oklab, #ffffff 85%, #ef4444);
    color:var(--text, #0f172a); border-color:var(--line, #e5e7eb);
  }
  #absentRegisterModal .absent-btn.primary{
    background:#dc2626; color:#fff; border-color:transparent;
  }
  #absentRegisterModal .absent-btn:disabled{
    opacity:.45; cursor:not-allowed;
  }
  #absentZone{ flex:1 1 auto; min-height:0; overflow:auto; display:flex; flex-direction:column; gap:8px; }
  #absentZone .row{
    display:flex; align-items:center; justify-content:space-between; gap:13px;
    padding:10px 13px; border-radius:16px; border:1px solid var(--line,#334155);
    background:color-mix(in oklab, var(--card-dark,#0f172a) 92%, #0000);
    transition:background .15s ease, border-color .15s ease;
  }
  #absentZone .row.is-filtered-out{ display:none !important; }
  body:not(.dark) #absentZone .row{
    background:color-mix(in oklab, var(--card-light,#fff) 96%, #0000);
    border-color:var(--line,#e5e7eb);
  }
  #absentZone .row.on{
    background:color-mix(in oklab, #dc2626 16%, var(--card-dark,#0f172a));
    border-color:color-mix(in oklab, #dc2626 46%, var(--line,#334155));
  }
  body:not(.dark) #absentZone .row.on{
    background:color-mix(in oklab, #dc2626 11%, var(--card-light,#fff));
    border-color:color-mix(in oklab, #dc2626 44%, var(--line,#e5e7eb));
  }
  #absentZone .row label{ display:flex; align-items:center; gap:10px; cursor:pointer; flex:1; color:inherit; font-size:17px }
  #absentZone .row small{ opacity:.75; color:inherit }
  #absentZone input[type="checkbox"]{
    width:21px; height:21px; accent-color:#dc2626; margin:0;
  }
  #absentZone .empty{
    padding:24px 13px; border-radius:16px; border:1px dashed var(--line,#334155); opacity:.72;
  }
  #absentRegisterModal .absent-actions-bottom{ flex:0 0 auto; }
  `;
  document.head.appendChild(s);
}

export function initAbsentRegister() {
  ensure();

  const modal = $('absentRegisterModal');
  const zone = $('absentZone');
  const search = $('absentSearch');
  const pick = $('absentSearchPick');
  const hint = $('absentSearchHint');
  const btn = $('absentRegisterBtn');
  if (!btn) return;

  const getRows = () => Array.from(document.querySelectorAll('#absentZone .row'));

  function setStudentSelected(row, selected) {
    const chk = row?.querySelector('.chk-sid');
    if (!chk) return;
    chk.checked = selected;
    row.classList.toggle('on', selected);
  }

  function applySearchFilter() {
    const needle = normalizeSearch(search?.value);
    let visible = 0;

    for (const row of getRows()) {
      const key = row.dataset.searchKey || normalizeSearch(row.textContent || '');
      const matches = !needle || key.includes(needle);
      row.hidden = !matches;
      row.classList.toggle('is-filtered-out', !matches);
      row.setAttribute('aria-hidden', matches ? 'false' : 'true');
      if (matches) visible += 1;
    }

    if (pick) pick.disabled = !needle || visible === 0;
    if (hint) hint.textContent = needle ? (visible ? `${visible}명` : '검색 결과 없음') : '';
  }

  function pickSearchStudent() {
    const needle = normalizeSearch(search?.value);
    if (!needle) return;

    const matches = getRows().filter(row => !row.hidden);
    const exact = matches.find(row => normalizeSearch(row.querySelector('.student-name')?.textContent) === needle);
    const row = exact || matches[0];
    if (!row) return;

    setStudentSelected(row, true);
    row.scrollIntoView({ block: 'nearest' });

    const name = row.querySelector('.student-name')?.textContent || '';
    if (hint) hint.textContent = name ? `${name} 선택됨` : '선택됨';
  }

  search?.addEventListener('input', applySearchFilter);
  search?.addEventListener('search', applySearchFilter);
  search?.addEventListener('compositionend', applySearchFilter);
  search?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      pickSearchStudent();
    } else if (e.key === 'Escape') {
      search.value = '';
      applySearchFilter();
    }
  });
  pick?.addEventListener('click', pickSearchStudent);

  btn.addEventListener('click', async () => {
    const dateKey = getAdminDate();
    await loadAbsentPayload();
    const extraMap = await loadExtraAttendMap();
    const candidates = collectAbsenceCandidates(dateKey, extraMap);

    if (!candidates.length) {
      zone.innerHTML = '<div class="empty">결석 등록할 학생이 없습니다.</div>';
    } else {
      zone.innerHTML = candidates.map(s => {
        const sid = String(s.id);
        return `
          <div class="row" data-sid="${sid}" data-search-key="${escapeAttr(studentSearchKey(s))}">
            <label>
              <input type="checkbox" class="chk-sid">
              <span class="student-name">${s.name || ''}</span>
              <small>${s.curriculum || ''}${s.subCurriculum ? ' · ' + s.subCurriculum : ''}</small>
            </label>
          </div>`;
      }).join('');
    }

    if (search) search.value = '';
    applySearchFilter();
    modal.style.display = 'flex';
    requestAnimationFrame(() => search?.focus());
  });

  document.body.addEventListener('click', (e) => {
    const closeBtn = e.target.closest?.('#absentRegisterModal .absent-close');
    if (closeBtn) modal.style.display = 'none';
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (modal.style.display === 'none') return;
    modal.style.display = 'none';
  });

  document.body.addEventListener('change', (e) => {
    const chk = e.target.closest('#absentZone .chk-sid');
    if (!chk) return;
    setStudentSelected(chk.closest('.row'), chk.checked);
  });

  document.body.addEventListener('click', async (e) => {
    const saveBtn = e.target.closest?.('#absentRegisterModal .absent-save');
    if (!saveBtn) return;

    const dateKey = getAdminDate();
    const rows = Array.from(document.querySelectorAll('#absentZone .row'));
    const selectedIds = rows
      .filter(r => r.querySelector('.chk-sid')?.checked)
      .map(r => String(r.dataset.sid))
      .filter(Boolean);

    if (!selectedIds.length) {
      toast('선택된 학생이 없습니다.');
      return;
    }

    saveBtn.disabled = true;
    try {
      for (const sid of selectedIds) {
        await patchFlagRemote('att', dateKey, sid, false);
        await patchFlagRemote('contact', dateKey, sid, false);
        setAttended(dateKey, sid, false);
        setContacted(dateKey, sid, false);
      }

      const latest = await loadAbsentPayload();
      const byDate = normalizeAbsentByDateMap(latest?.by_date || {});
      const byStudent = normalizeAbsencesByStudent(latest?.by_student || {});
      const daySet = new Set((byDate[dateKey] || []).map(String));

      selectedIds.forEach(sid => {
        daySet.add(String(sid));
        byStudent[String(sid)] = dateKey;
      });
      byDate[dateKey] = Array.from(daySet);

      const res = await postJSON('/api/absent', {
        by_date: byDate,
        by_student: byStudent,
      });
      const saved = await res.json().catch(() => ({ by_date: byDate, by_student: byStudent }));
      applyAbsentPayload(saved);

      await clearTodayOrder(dateKey);

      toast(`${selectedIds.length}명 결석 등록`);
      modal.style.display = 'none';
      document.dispatchEvent(new CustomEvent('attendance:updated'));
      document.dispatchEvent(new CustomEvent('admin:refresh'));
      if (typeof window.recalcCalendarCounts === 'function') window.recalcCalendarCounts();
    } catch (err) {
      console.error(err);
      alert('결석 등록 실패');
    } finally {
      saveBtn.disabled = false;
    }
  });
}
