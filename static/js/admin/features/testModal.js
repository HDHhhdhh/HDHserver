// /js/admin/features/testModal.js
// Admin test assignment popup. Stores assignment status in progress[date][sid].tests
// and optionally writes a readable assignment block into the class log notes.

import { $, CT, toast } from '../core/utils.js';
import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';

const CATEGORY_DEFS = [
  { key: 'REVIEW', label: '복습 테스트', short: '복습', difficulties: ['상', '중상'] },
  { key: 'UNIT', label: '단원평가', short: '단원', difficulties: ['Lv.3', 'Lv.4', 'Lv.5', 'Lv.6'] },
  { key: 'SCHOOL_PAST', label: '학군지 기출', short: '학군지', difficulties: ['상', '중상'] },
  { key: 'ILSAN_PAST', label: '일산 기출', short: '일산', difficulties: ['상', '중상'] },
];
const CATEGORY_BY_KEY = Object.fromEntries(CATEGORY_DEFS.map(x => [x.key, x]));
const CATEGORY_KEYS = CATEGORY_DEFS.map(x => x.key);
const SUBJECTS = ['공수1', '공수2', '대수', '미적분1', '미적분2', '기하', '확통'];

let initialized = false;
let editingSid = null;
let editingDate = null;
let activeStudent = null;
let activeCategory = 'UNIT';
let activeSubject = '공수1';
let activeDifficulty = 'Lv.3';
let activeCatalog = [];
let catalogByKey = new Map();
let initialTestMap = {};
let selectedKeys = new Set();
let submittedIds = new Set();
let submittedNames = new Set();
let testSelectionTouched = false;

async function fetchJSONSafe(url, init = {}) {
  const res = await fetch(url, { cache: 'no-store', ...init });
  const txt = await res.text();
  if (!res.ok) throw new Error(`[testModal] ${init.method || 'GET'} ${url} -> ${res.status}\n${txt.slice(0, 200)}`);
  try { return txt.trim() ? JSON.parse(txt) : {}; }
  catch (e) { throw new Error(`[testModal] Bad JSON from ${url}: ${e?.message}\n${txt.slice(0, 200)}`); }
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (m) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[m]));
}

function canonText(value) {
  return String(value || '').trim().replace(/\s+/g, ' ');
}

function normalizeSubject(value) {
  const compact = String(value || '').trim().replace(/\s+/g, '');
  const aliases = {
    '공통수학1': '공수1',
    '공통수학2': '공수2',
    '미적1': '미적분1',
    '미적분Ⅰ': '미적분1',
    '미적분I': '미적분1',
    '미적2': '미적분2',
    '미적분Ⅱ': '미적분2',
    '미적분II': '미적분2',
    '확률과통계': '확통',
  };
  return aliases[compact] || compact || '공수1';
}

function categoryLabel(key) {
  return CATEGORY_BY_KEY[key]?.label || key || '';
}

function canonicalCategoryKey(key, label = '') {
  const raw = `${key || ''} ${label || ''}`.toUpperCase();
  const ko = `${key || ''} ${label || ''}`.replace(/\s+/g, '');
  if (raw.includes('REVIEW') || ko.includes('복습')) return 'REVIEW';
  if (raw.includes('SCHOOL') || ko.includes('학군지')) return 'SCHOOL_PAST';
  if (raw.includes('ILSAN') || ko.includes('일산')) return 'ILSAN_PAST';
  if (raw.includes('UNIT') || ko.includes('단원')) return 'UNIT';
  return String(key || '').trim();
}

function normalizeDifficulty(categoryKey, raw, name = '') {
  const text = String(raw || '').trim();
  const def = CATEGORY_BY_KEY[categoryKey];
  if (def?.difficulties.includes(text)) return text;

  const source = `${text} ${name}`;
  const lv = source.match(/(?:Lv\.?|LV\.?|레벨)\s*\.?\s*([3-6])/);
  if (lv) return `Lv.${lv[1]}`;
  if (source.includes('중상')) return '중상';
  if (source.includes('상')) return '상';

  return def?.difficulties?.[0] || '';
}

function normalizeRound(value, name = '') {
  const raw = String(value || '').trim();
  const source = `${raw} ${name}`;
  const m = source.match(/(\d{1,2})\s*(?:회차|회)/);
  if (m) return m[1];
  if (/^\d{1,2}$/.test(raw)) return raw;
  return raw || '1';
}

function roundLabel(value) {
  const r = String(value || '').trim();
  if (!r) return '';
  return /회/.test(r) ? r : `${r}회차`;
}

function testKey(test) {
  return [
    categoryLabel(test.categoryKey),
    test.curriculum,
    test.difficulty,
    roundLabel(test.round),
    test.name,
  ].filter(Boolean).join(' / ');
}

function normalizeConfig(cfg) {
  const out = (cfg && typeof cfg === 'object') ? cfg : {};
  if (!out.categories || typeof out.categories !== 'object') out.categories = {};

  CATEGORY_DEFS.forEach(def => {
    if (!out.categories[def.key] || typeof out.categories[def.key] !== 'object') {
      out.categories[def.key] = { label: def.label, tests: [] };
    }
    if (!Array.isArray(out.categories[def.key].tests)) out.categories[def.key].tests = [];
    out.categories[def.key].label = out.categories[def.key].label || def.label;
  });

  return out;
}

function collectCatalog(cfg) {
  const out = [];
  const categories = cfg?.categories || {};

  Object.entries(categories).forEach(([rawKey, cat]) => {
    if (!cat || typeof cat !== 'object') return;
    const categoryKey = canonicalCategoryKey(rawKey, cat.label);
    if (!CATEGORY_BY_KEY[categoryKey]) return;

    const tests = Array.isArray(cat.tests) ? cat.tests : [];
    tests.forEach((rawTest, idx) => {
      if (!rawTest || typeof rawTest !== 'object') return;
      const name = canonText(rawTest.name || rawTest.title || `테스트 ${idx + 1}`);
      const curriculum = normalizeSubject(rawTest.curriculum || rawTest.subject || rawTest.course || activeSubject);
      const difficulty = normalizeDifficulty(categoryKey, rawTest.difficulty || rawTest.level, name);
      const round = normalizeRound(rawTest.round || rawTest.session || rawTest.no, name);
      const id = canonText(rawTest.id) || `t_${categoryKey}_${curriculum}_${difficulty}_${idx}`;

      const test = {
        ...rawTest,
        id,
        name,
        categoryKey,
        curriculum,
        difficulty,
        round,
        problems: Number.isFinite(+rawTest.problems) ? Math.max(1, Number(rawTest.problems)) : 20,
      };
      test._key = testKey(test);
      out.push(test);
    });
  });

  out.sort((a, b) =>
    CATEGORY_KEYS.indexOf(a.categoryKey) - CATEGORY_KEYS.indexOf(b.categoryKey) ||
    SUBJECTS.indexOf(a.curriculum) - SUBJECTS.indexOf(b.curriculum) ||
    String(a.difficulty).localeCompare(String(b.difficulty), 'ko') ||
    Number(a.round || 0) - Number(b.round || 0) ||
    String(a.name).localeCompare(String(b.name), 'ko')
  );

  return out;
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

function pushSubmittedRecord(rec) {
  if (!rec || typeof rec !== 'object') return;
  const id = canonText(rec.testId || rec.id);
  const name = canonText(rec.name || rec.testName || rec.title);
  if (id) submittedIds.add(id);
  if (name) {
    submittedNames.add(name);
    if (name.includes('/')) submittedNames.add(canonText(name.split('/').pop()));
  }
}

function collectSubmittedFromState(sid) {
  submittedIds = new Set();
  submittedNames = new Set();

  const s = String(sid);
  Object.entries(state.logs || {}).forEach(([date, bySid]) => {
    if (editingDate && /^\d{4}-\d{2}-\d{2}$/.test(date) && date > editingDate) return;
    const entry = bySid?.[s];
    const tests = Array.isArray(entry?.tests) ? entry.tests : [];
    tests.forEach(pushSubmittedRecord);
  });
}

async function hydrateForTestPopup(date, sid) {
  const [cfg, logs, progress, testsJson] = await Promise.all([
    fetchJSONSafe('/api/tests-config').catch(() => ({ categories: {} })),
    fetchJSONSafe(`/api/logs?sid=${encodeURIComponent(sid)}`).catch(() => ({})),
    fetchJSONSafe(`/api/progress?sid=${encodeURIComponent(sid)}`).catch(() => ({})),
    fetchJSONSafe('/api/tests').catch(() => ({})),
  ]);

  state.testsConfig = normalizeConfig(cfg);
  window.testsConfig = state.testsConfig;

  state.logs = state.logs || {};
  mergeDateSidMap(state.logs, logs);
  window.logs = state.logs;

  state.progress = state.progress || {};
  mergeDateSidMap(state.progress, progress);
  window.progressData = state.progress;

  collectSubmittedFromState(sid);

  if (testsJson && typeof testsJson === 'object') {
    Object.entries(testsJson).forEach(([dateKey, bySid]) => {
      if (date && /^\d{4}-\d{2}-\d{2}$/.test(dateKey) && dateKey > date) return;
      if (Array.isArray(bySid?.[sid])) bySid[sid].forEach(pushSubmittedRecord);
    });
  }

  activeCatalog = collectCatalog(state.testsConfig);
  catalogByKey = new Map(activeCatalog.map(test => [test._key, test]));
}

function getCurrentProgressTests() {
  const raw = state.progress?.[editingDate]?.[editingSid]?.tests;
  return (raw && typeof raw === 'object') ? raw : {};
}

function isSubmitted(test) {
  if (!test) return false;
  return submittedIds.has(String(test.id || '').trim()) ||
    submittedNames.has(canonText(test.name)) ||
    submittedNames.has(canonText(`${categoryLabel(test.categoryKey)} / ${test.name}`)) ||
    submittedNames.has(canonText(test._key));
}

function visibleTests() {
  return activeCatalog.filter(test =>
    test.categoryKey === activeCategory &&
    normalizeSubject(test.curriculum) === activeSubject &&
    String(test.difficulty || '') === String(activeDifficulty || '')
  );
}

function syncSelectedFromProgress() {
  initialTestMap = { ...getCurrentProgressTests() };
  selectedKeys = new Set(
    Object.entries(initialTestMap)
      .filter(([, status]) => String(status || '').trim() && String(status || '').trim() !== 'none')
      .map(([key]) => key)
  );
}

function renderCategories() {
  const host = $('testCategoryTabs');
  if (!host) return;
  host.innerHTML = CATEGORY_DEFS.map(def => `
    <button type="button" class="test-tab${def.key === activeCategory ? ' is-active' : ''}" data-category="${def.key}">
      ${escapeHtml(def.short)}
    </button>
  `).join('');
}

function renderFilters() {
  const subjectSel = $('testSubject');
  const difficultySel = $('testDifficulty');
  if (subjectSel) {
    subjectSel.innerHTML = SUBJECTS.map(subject =>
      `<option value="${escapeHtml(subject)}"${subject === activeSubject ? ' selected' : ''}>${escapeHtml(subject)}</option>`
    ).join('');
  }

  const difficulties = CATEGORY_BY_KEY[activeCategory]?.difficulties || [];
  if (!difficulties.includes(activeDifficulty)) activeDifficulty = difficulties[0] || '';
  if (difficultySel) {
    difficultySel.innerHTML = difficulties.map(diff =>
      `<option value="${escapeHtml(diff)}"${diff === activeDifficulty ? ' selected' : ''}>${escapeHtml(diff)}</option>`
    ).join('');
  }

  const metaEl = $('testStudentMeta');
  if (metaEl) metaEl.textContent = `학생 레벨: ${activeStudent?.level || '-'}`;
}

function renderList() {
  const list = $('testAssignList');
  if (!list) return;

  const tests = visibleTests();
  const count = $('testVisibleCount');
  if (count) count.textContent = `${tests.length}개`;

  if (!tests.length) {
    list.innerHTML = `
      <div class="test-empty">
        선택한 분류/과목/난이도에 등록된 테스트가 없습니다.
      </div>
    `;
    return;
  }

  list.innerHTML = tests.map(test => {
    const done = isSubmitted(test);
    const checked = done || selectedKeys.has(test._key);
    const status = done ? '완료' : (checked ? '배정' : '미배정');
    return `
      <label class="test-row${checked ? ' is-selected' : ''}${done ? ' is-done' : ''}">
        <input type="checkbox" class="test-check" value="${escapeHtml(test._key)}"
          ${checked ? ' checked' : ''} ${done ? ' disabled' : ''}>
        <span class="test-row-main">
          <strong>${escapeHtml(test.name)}</strong>
          <span>${escapeHtml(categoryLabel(test.categoryKey))} · ${escapeHtml(test.curriculum)} · ${escapeHtml(test.difficulty)} · ${escapeHtml(roundLabel(test.round))}</span>
        </span>
        <span class="test-status">${escapeHtml(status)}</span>
      </label>
    `;
  }).join('');
}

function renderAll() {
  const stuName = activeStudent?.name || '';
  const title = $('testTitle');
  if (title) title.textContent = stuName ? `${stuName} 테스트 배정` : '테스트 배정';

  renderCategories();
  renderFilters();
  renderList();
}

function ensureStyles() {
  if (document.getElementById('testAssignmentModalStyles')) return;
  const s = document.createElement('style');
  s.id = 'testAssignmentModalStyles';
  s.textContent = `
    #testModal{
      position:fixed; inset:0; z-index:99991; display:none;
      justify-content:center; align-items:center; background:rgba(0,0,0,.45);
    }
    #testModal .test-card{
      width:540px; max-width:94vw; height:80vh; max-height:80vh;
      padding:14px; border-radius:8px; overflow:hidden; box-sizing:border-box;
      background:#ffffff; color:#0f172a; box-shadow:0 12px 32px rgba(0,0,0,.28);
      display:flex; flex-direction:column; border:1px solid #e5e7eb;
    }
    body.dark #testModal .test-card{ background:#1e293b; color:#e5e7eb; border-color:#334155; }
    #testModal .test-head{ display:flex; align-items:flex-start; justify-content:space-between; gap:10px; padding-bottom:10px; border-bottom:1px solid #e5e7eb; }
    body.dark #testModal .test-head{ border-bottom-color:#334155; }
    #testModal h3{ margin:0 0 4px; font-size:18px; font-weight:900; }
    #testModal .test-sub{ font-size:12px; color:#64748b; line-height:1.35; }
    body.dark #testModal .test-sub{ color:#94a3b8; }
    #testModal .test-save-btn{
      flex:0 0 auto; min-width:66px; height:38px; padding:0 14px; border-radius:10px;
      border:1px solid #2563eb; background:#2563eb; color:#fff; font-weight:900; cursor:pointer;
    }
    #testModal .test-body{ flex:1 1 auto; min-height:0; overflow:auto; padding-top:10px; display:flex; flex-direction:column; gap:10px; }
    #testModal .test-tabbar{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; }
    #testModal .test-tab{
      min-height:34px; border:1px solid #cbd5e1; border-radius:999px; background:#fff;
      color:#0f172a; font-weight:900; cursor:pointer; font-size:12px;
    }
    #testModal .test-tab.is-active{ background:#2563eb; border-color:#2563eb; color:#fff; }
    body.dark #testModal .test-tab{ background:#0f172a; color:#e5e7eb; border-color:#475569; }
    body.dark #testModal .test-tab.is-active{ background:#2563eb; color:#fff; border-color:#2563eb; }
    #testModal .test-filter-grid{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    #testModal .test-field label{ display:block; margin-bottom:3px; font-size:12px; color:#64748b; font-weight:800; }
    body.dark #testModal .test-field label{ color:#94a3b8; }
    #testModal select{
      width:100%; height:34px; border-radius:8px; border:1px solid #cbd5e1;
      background:#fff; color:#0f172a; padding:0 8px; box-sizing:border-box;
    }
    body.dark #testModal select{ background:#0f172a; color:#e5e7eb; border-color:#475569; }
    #testModal .test-toolbar{ display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; }
    #testModal .test-mini-actions{ display:flex; gap:6px; flex-wrap:wrap; }
    #testModal .test-mini-actions button{
      min-height:30px; padding:0 9px; border:1px solid #cbd5e1; border-radius:8px;
      background:#f8fafc; color:#0f172a; font-weight:800; cursor:pointer; font-size:12px;
    }
    body.dark #testModal .test-mini-actions button{ background:#334155; color:#e5e7eb; border-color:#475569; }
    #testModal .test-list{ display:flex; flex-direction:column; gap:6px; }
    #testModal .test-row{
      display:grid; grid-template-columns:22px minmax(0,1fr) auto; gap:8px; align-items:center;
      min-height:46px; padding:7px 8px; border:1px solid #e5e7eb; border-radius:9px;
      background:#fff; cursor:pointer; box-sizing:border-box;
    }
    body.dark #testModal .test-row{ background:#0b1220; border-color:#334155; }
    #testModal .test-row.is-selected{ background:#10b98118; border-color:#10b98170; }
    #testModal .test-row.is-done{ background:#2563eb18; border-color:#2563eb70; }
    #testModal .test-row-main{ min-width:0; display:flex; flex-direction:column; gap:2px; }
    #testModal .test-row-main strong{ font-size:13px; line-height:1.25; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    #testModal .test-row-main span{ font-size:11px; color:#64748b; line-height:1.25; }
    body.dark #testModal .test-row-main span{ color:#94a3b8; }
    #testModal .test-status{
      justify-self:end; padding:3px 7px; border-radius:999px; background:#f1f5f9; color:#334155;
      font-size:11px; font-weight:900; white-space:nowrap;
    }
    body.dark #testModal .test-status{ background:#1f2937; color:#cbd5e1; }
    #testModal .test-row.is-selected .test-status{ background:#10b981; color:#fff; }
    #testModal .test-row.is-done .test-status{ background:#2563eb; color:#fff; }
    #testModal .test-note-option{
      display:flex; align-items:center; gap:7px; padding:9px 10px; border:1px solid #e5e7eb;
      border-radius:9px; font-size:12px; font-weight:800; background:#f8fafc;
    }
    body.dark #testModal .test-note-option{ background:#0b1220; border-color:#334155; }
    #testModal .test-empty{ padding:14px; border:1px dashed #cbd5e1; border-radius:9px; color:#64748b; font-size:13px; }
    body.dark #testModal .test-empty{ border-color:#475569; color:#94a3b8; }
  `;
  document.head.appendChild(s);
}

function ensureModal() {
  ensureStyles();
  if ($('testModal')) return;
  document.body.insertAdjacentHTML('beforeend', `
    <div id="testModal" aria-label="테스트 배정 팝업">
      <div class="test-card">
        <div class="test-head">
          <div>
            <h3 id="testTitle">테스트 배정</h3>
            <div class="test-sub">
              <span id="testStudentMeta">학생 레벨: -</span>
              <span aria-hidden="true"> · </span>
              <span id="testVisibleCount">0개</span>
            </div>
          </div>
          <button id="testSave" class="test-save-btn" type="button">저장</button>
        </div>

        <div class="test-body">
          <div id="testCategoryTabs" class="test-tabbar"></div>

          <div class="test-filter-grid">
            <div class="test-field">
              <label for="testSubject">과목</label>
              <select id="testSubject"></select>
            </div>
            <div class="test-field">
              <label for="testDifficulty">난이도</label>
              <select id="testDifficulty"></select>
            </div>
          </div>

          <div class="test-toolbar">
            <div class="test-sub">체크된 항목이 오늘 선택 날짜에 배정됩니다.</div>
            <div class="test-mini-actions">
              <button id="testPickAll" type="button">목록 전체 선택</button>
              <button id="testPickNone" type="button">선택 해제</button>
            </div>
          </div>

          <div id="testAssignList" class="test-list"></div>

          <label class="test-note-option">
            <input id="testAppendNotes" type="checkbox" checked>
            <span>상담 기록에 테스트 배정 내역 추가</span>
          </label>
        </div>
      </div>
    </div>
  `);
}

function setModalOpen(open, layout) {
  const modal = $('testModal');
  if (!modal) return;
  modal.classList.toggle('student-work-layout', layout === 'student-work');
  modal.style.display = open ? 'flex' : 'none';
}

function closeModal() {
  const wasUnified = $('testModal')?.classList.contains('student-work-layout');
  setModalOpen(false);
  editingSid = null;
  editingDate = null;
  activeStudent = null;
  activeCatalog = [];
  catalogByKey = new Map();
  initialTestMap = {};
  selectedKeys = new Set();
  testSelectionTouched = false;
  if (wasUnified && !document.querySelector('#vidModal.student-work-layout') && !document.querySelector('#logModal.student-work-layout')) {
    try { window.hideStudentPopupBackdrop?.(); } catch {}
  }
}

function chooseInitialCategory() {
  const hasUnit = activeCatalog.some(t => t.categoryKey === 'UNIT' && t.curriculum === activeSubject);
  if (hasUnit) return 'UNIT';
  const hit = CATEGORY_KEYS.find(key => activeCatalog.some(t => t.categoryKey === key && t.curriculum === activeSubject));
  return hit || 'UNIT';
}

async function openModalForRow(rowOrButton, opts = {}) {
  ensureModal();

  const tr = rowOrButton?.closest?.('tr[data-sid]') || rowOrButton;
  editingSid = String(tr?.dataset?.sid || '').trim();
  editingDate = String(tr?.dataset?.date || getAdminDate()).trim();
  activeStudent = (state.students || []).find(stu => String(stu.id) === editingSid) || null;
  if (!editingSid || !activeStudent) {
    alert('학생 정보를 찾을 수 없습니다.');
    return;
  }

  activeSubject = normalizeSubject(activeStudent.curriculum);
  await hydrateForTestPopup(editingDate, editingSid);
  syncSelectedFromProgress();

  activeCategory = chooseInitialCategory();
  activeDifficulty = CATEGORY_BY_KEY[activeCategory]?.difficulties?.[0] || '';
  testSelectionTouched = false;

  renderAll();
  setModalOpen(true, opts.layout);
}

function selectedAssignmentObjects() {
  return Array.from(selectedKeys).map(key => {
    const test = catalogByKey.get(key);
    if (!test) return { label: key };
    return {
      id: test.id,
      name: test.name,
      category: test.categoryKey,
      categoryLabel: categoryLabel(test.categoryKey),
      curriculum: test.curriculum,
      difficulty: test.difficulty,
      round: String(test.round || ''),
      label: test._key,
    };
  });
}

function buildAssignmentNote(items) {
  if (!items.length) return '';
  const lines = items.map(item => {
    if (!item || !item.name) return `- ${item.label}`;
    return `- ${item.categoryLabel} / ${item.curriculum} / ${item.difficulty} / ${roundLabel(item.round)}: ${item.name}`;
  });
  return `[테스트 배정]\n${lines.join('\n')}`;
}

async function patchLogAssignment(items, appendToNotes) {
  const q = new URLSearchParams({ date: editingDate, sid: editingSid }).toString();
  const latest = await fetchJSONSafe(`/api/logs/entry?${q}`).catch(() => ({}));
  const entry = latest?.entry && typeof latest.entry === 'object' ? latest.entry : {};
  const clear = [];
  const patchEntry = {
    updatedAt: new Date().toISOString(),
  };
  if (items.length) patchEntry.assignedTests = items;
  else clear.push('assignedTests');

  const noteBlock = buildAssignmentNote(items);
  if (noteBlock) patchEntry.testAssignmentNote = noteBlock;
  else clear.push('testAssignmentNote');

  if (appendToNotes && noteBlock) {
    const prevNotes = String(entry.notes || '').trimEnd();
    const prevBlock = String(entry.testAssignmentNote || '').trim();
    const nextNotes = prevBlock && prevNotes.includes(prevBlock)
      ? prevNotes.replace(prevBlock, noteBlock)
      : (prevNotes ? `${prevNotes}\n\n${noteBlock}` : noteBlock);
    patchEntry.notes = nextNotes;
  }

  const body = {
    date: editingDate,
    sid: editingSid,
    entry: patchEntry,
  };
  if (clear.length) body.__clear = clear;
  if (appendToNotes && noteBlock) body.base = { notes: String(entry.notes || '').trim() };

  const saved = await fetchJSONSafe('/api/logs/patch', {
    method: 'POST',
    headers: CT,
    body: JSON.stringify(body),
  });

  if (saved?.entry && typeof saved.entry === 'object') {
    state.logs = state.logs || {};
    state.logs[editingDate] = state.logs[editingDate] || {};
    state.logs[editingDate][editingSid] = saved.entry;
    window.logs = state.logs;
  }
}

async function saveModal(options = {}) {
  if (!editingSid || !editingDate) return [];
  if (!testSelectionTouched) {
    const items = selectedAssignmentObjects();
    if (options.showPopup !== false) toast('변경된 테스트 배정이 없습니다');
    return items;
  }

  const patchTests = {};
  const allKeys = new Set([...Object.keys(initialTestMap), ...selectedKeys]);
  allKeys.forEach(key => {
    const test = catalogByKey.get(key);
    if (test && isSubmitted(test)) {
      patchTests[key] = 'done';
    } else if (selectedKeys.has(key)) {
      patchTests[key] = 'assigned';
    } else {
      patchTests[key] = '';
    }
  });

  state.progress = state.progress || {};
  state.progress[editingDate] = state.progress[editingDate] || {};
  state.progress[editingDate][editingSid] = state.progress[editingDate][editingSid] || {};

  const progressRes = await fetchJSONSafe('/api/progress/patch', {
    method: 'POST',
    headers: CT,
    body: JSON.stringify({
      date: editingDate,
      sid: editingSid,
      progress: { tests: patchTests },
    }),
  });

  if (progressRes?.progress && typeof progressRes.progress === 'object') {
    state.progress[editingDate][editingSid] = progressRes.progress;
    window.progressData = state.progress;
  }

  const items = selectedAssignmentObjects();
  const appendToNotes = Boolean($('testAppendNotes')?.checked);
  await patchLogAssignment(items, appendToNotes);

  if (options.showPopup !== false) toast('테스트 배정 저장됨');
  if (options.refresh !== false) document.dispatchEvent(new CustomEvent('admin:refresh'));
  initialTestMap = { ...getCurrentProgressTests() };
  testSelectionTouched = false;
  return items;
}

function bindEventsOnce() {
  if (initialized) return;
  initialized = true;

  document.body.addEventListener('click', async (e) => {
    const categoryBtn = e.target.closest('#testCategoryTabs .test-tab');
    if (categoryBtn) {
      activeCategory = categoryBtn.dataset.category || activeCategory;
      activeDifficulty = CATEGORY_BY_KEY[activeCategory]?.difficulties?.[0] || '';
      renderAll();
      return;
    }

    if (e.target.closest('#testPickAll')) {
      visibleTests().forEach(test => {
        if (!isSubmitted(test)) selectedKeys.add(test._key);
      });
      testSelectionTouched = true;
      renderList();
      return;
    }

    if (e.target.closest('#testPickNone')) {
      visibleTests().forEach(test => {
        if (!isSubmitted(test)) selectedKeys.delete(test._key);
      });
      testSelectionTouched = true;
      renderList();
      return;
    }

    if (e.target.closest('#testSave')) {
      try {
        await saveModal();
      } catch (err) {
        console.error(err);
        alert(err?.message || '테스트 배정 저장 실패');
      }
      return;
    }

    const standaloneBtn = e.target.closest('.openTestProgress');
    if (standaloneBtn) {
      const tr = standaloneBtn.closest('tr[data-sid]');
      if (tr) await openModalForRow(tr);
    }
  });

  document.body.addEventListener('change', (e) => {
    if (e.target?.id === 'testSubject') {
      activeSubject = normalizeSubject(e.target.value);
      activeDifficulty = CATEGORY_BY_KEY[activeCategory]?.difficulties?.[0] || '';
      renderAll();
      return;
    }

    if (e.target?.id === 'testDifficulty') {
      activeDifficulty = e.target.value || activeDifficulty;
      renderAll();
      return;
    }

    const check = e.target?.closest?.('.test-check');
    if (check) {
      const key = check.value;
      if (check.checked) selectedKeys.add(key);
      else selectedKeys.delete(key);
      testSelectionTouched = true;
      renderList();
    }
  });

  document.body.addEventListener('click', (e) => {
    if (e.target?.id === 'testModal') closeModal();
  });
}

export function initTestModal() {
  ensureModal();
  bindEventsOnce();

  window.openTestAssignmentPopupForRow = openModalForRow;
  window.closeTestAssignmentPopup = closeModal;
  window.saveTestAssignmentPopup = saveModal;
  window._openTest = (sid) => {
    const row = document.querySelector(`tr[data-sid="${CSS.escape(String(sid))}"]`);
    if (row) return openModalForRow(row);
    return openModalForRow({ dataset: { sid: String(sid), date: getAdminDate() }, closest: () => null });
  };
}
