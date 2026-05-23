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
  { key: 'ILSAN_PAST', label: '일산 기출', short: '일산', difficulties: ['상', '중'] },
];
const CATEGORY_BY_KEY = Object.fromEntries(CATEGORY_DEFS.map(x => [x.key, x]));
const CATEGORY_KEYS = CATEGORY_DEFS.map(x => x.key);
const SUBJECTS = ['공수1', '공수2', '대수', '미적분1', '미적분2', '기하', '확통'];
const ROUND_OPTIONS = ['1', '2', '3'];
const TERM_OPTIONS = ['중간고사', '기말고사'];
const DEFAULT_TERM = TERM_OPTIONS[1] || TERM_OPTIONS[0];
const SCHOOL_CAL_PAGE_STORAGE_KEY = 'schoolCal.selectedPage.v1';
const TEST_ASSIGN_CLEAR_KEY = '__testsClearedAt';
const TEST_STATUS_LABELS = {
  assigned: '배정',
  done: '배정',
  interrupted: '배부',
  skip: '제외',
};

let initialized = false;
let editingSid = null;
let editingDate = null;
let activeStudent = null;
let activeCategory = 'UNIT';
let activeSubject = '공수1';
let activeDifficulty = 'Lv.3';
let activeRound = '1';
let activeTerm = DEFAULT_TERM;
let activeCatalog = [];
let catalogByKey = new Map();
let initialTestMap = {};
let selectedKeys = new Set();
let selectedStatuses = new Map();
let submittedIds = new Set();
let submittedNames = new Set();
let testSelectionTouched = false;
let defaultExclusionsApplied = false;
let testOpenSeq = 0;

function isUnitCategory(categoryKey) {
  return String(categoryKey || '') === 'UNIT';
}

function isTermCategory(categoryKey) {
  const key = String(categoryKey || '');
  return key === 'SCHOOL_PAST' || key === 'ILSAN_PAST';
}

async function fetchJSONSafe(url, init = {}) {
  const res = await fetch(url, { cache: 'no-store', ...init });
  const txt = await res.text();
  if (!res.ok) throw new Error(`[testModal] ${init.method || 'GET'} ${url} -> ${res.status}\n${txt.slice(0, 200)}`);
  try { return txt.trim() ? JSON.parse(txt) : {}; }
  catch (e) { throw new Error(`[testModal] Bad JSON from ${url}: ${e?.message}\n${txt.slice(0, 200)}`); }
}

async function fetchJSONCached(url, ttlMs = 2500) {
  const cache = window.__studentWorkFetchCache || (window.__studentWorkFetchCache = new Map());
  const now = Date.now();
  const hit = cache.get(url);
  if (hit && (now - hit.ts) < ttlMs) return hit.promise;

  const promise = fetchJSONSafe(url).catch(() => ({}));
  cache.set(url, { ts: now, promise });
  return promise;
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
  if (categoryKey === 'ILSAN_PAST' && text === '중상') return '중';
  const def = CATEGORY_BY_KEY[categoryKey];
  if (def?.difficulties.includes(text)) return text;

  const source = `${text} ${name}`;
  const lv = source.match(/(?:Lv\.?|LV\.?|레벨)\s*\.?\s*([3-6])/);
  if (lv) return `Lv.${lv[1]}`;
  if (source.includes('중상')) return categoryKey === 'ILSAN_PAST' ? '중' : '중상';
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

function normalizeTerm(value, name = '') {
  const source = `${value || ''} ${name || ''}`.trim();
  if (!source) return DEFAULT_TERM;
  if (TERM_OPTIONS.includes(source)) return source;
  const lower = source.toLowerCase();
  if (lower.includes('final') || lower.includes('end') || source.includes(TERM_OPTIONS[1])) return TERM_OPTIONS[1] || DEFAULT_TERM;
  if (lower.includes('mid') || lower.includes('middle') || source.includes(TERM_OPTIONS[0])) return TERM_OPTIONS[0] || DEFAULT_TERM;
  return DEFAULT_TERM;
}

function readSchoolCalendarPageSelection() {
  try {
    const raw = JSON.parse(localStorage.getItem(SCHOOL_CAL_PAGE_STORAGE_KEY) || '{}');
    return raw && typeof raw === 'object' ? raw : {};
  } catch {
    return {};
  }
}

function termFromSchoolCalendarExam(value) {
  const raw = String(value || '').trim();
  const lower = raw.toLowerCase();
  if (!raw) return '';
  if (lower === 'final' || lower.includes('final') || lower.includes('end')) return TERM_OPTIONS[1] || DEFAULT_TERM;
  if (lower === 'mid' || lower.includes('mid') || lower.includes('middle')) return TERM_OPTIONS[0] || DEFAULT_TERM;
  return normalizeTerm(raw, '');
}

function defaultTermFromSchoolCalendar() {
  const stored = readSchoolCalendarPageSelection();
  const cal = state.schoolCal && typeof state.schoolCal === 'object' ? state.schoolCal : {};
  const years = cal.years && typeof cal.years === 'object' ? cal.years : {};
  const activeYear = String(stored.year || cal.activeYear || Object.keys(years).sort().at(-1) || '');
  const yearBundle = activeYear && years[activeYear] && typeof years[activeYear] === 'object'
    ? years[activeYear]
    : {};
  return termFromSchoolCalendarExam(stored.exam || cal.activeExam || yearBundle.activeExam) || DEFAULT_TERM;
}

function normalizeAssignmentStatus(status) {
  const s = String(status || '').trim();
  if (!s || s === 'none') return '';
  if (s === 'assigned' || s === 'done' || s === 'interrupted' || s === 'skip') return s;
  return 'assigned';
}

function testStatusLabel(status, submitted = false) {
  if (submitted) return '완료';
  const s = normalizeAssignmentStatus(status);
  return s ? (TEST_STATUS_LABELS[s] || '배정') : '미배정';
}

function nextStatusOf(status) {
  const s = normalizeAssignmentStatus(status);
  if (!s) return 'assigned';
  if (s === 'skip') return 'assigned';
  if (s === 'assigned' || s === 'done') return 'interrupted';
  return '';
}

function statusForKey(key) {
  return normalizeAssignmentStatus(selectedStatuses.get(key));
}

function setTestStatus(key, status) {
  const k = String(key || '').trim();
  if (!k) return;
  const normalized = normalizeAssignmentStatus(status);
  if (normalized) {
    selectedStatuses.set(k, normalized);
    selectedKeys.add(k);
  } else {
    selectedStatuses.delete(k);
    selectedKeys.delete(k);
  }
}

function testKey(test) {
  return [
    categoryLabel(test.categoryKey),
    test.curriculum,
    test.difficulty,
    isTermCategory(test.categoryKey) ? test.term : '',
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

  const ilsanRules = out.autoAssignRules?.ILSAN_PAST;
  if (ilsanRules && typeof ilsanRules === 'object') {
    Object.values(ilsanRules).forEach(subjectRules => {
      if (!subjectRules || typeof subjectRules !== 'object' || !Array.isArray(subjectRules['중상'])) return;
      const current = Array.isArray(subjectRules['중']) ? subjectRules['중'] : [];
      subjectRules['중'] = Array.from(new Set([...current, ...subjectRules['중상']].map(String)));
      delete subjectRules['중상'];
    });
  }

  return out;
}

function ruleDefaultDifficulty(categoryKey, subject, student = activeStudent) {
  const hits = ruleDefaultDifficulties(categoryKey, subject, student);
  return hits[0] || '';
}

function ruleLevelsForDifficulty(categoryKey, subject, difficulty) {
  const rules = state.testsConfig?.autoAssignRules?.[categoryKey]?.[subject];
  if (!rules || typeof rules !== 'object') return null;
  const levels = rules?.[difficulty];
  return Array.isArray(levels) ? levels : null;
}

function autoAssignRuleAllowsDifficulty(categoryKey, subject, difficulty, student = activeStudent) {
  const level = canonText(student?.level);
  if (!level) return null;
  const levels = ruleLevelsForDifficulty(categoryKey, subject, difficulty);
  if (!levels) return null;
  return levels.map(canonText).includes(level);
}

function ruleDefaultDifficulties(categoryKey, subject, student = activeStudent) {
  const def = CATEGORY_BY_KEY[categoryKey] || CATEGORY_BY_KEY.UNIT;
  const difficulties = def?.difficulties || [];
  const level = canonText(student?.level);
  const rules = state.testsConfig?.autoAssignRules?.[categoryKey]?.[subject];
  if (level && rules && typeof rules === 'object') {
    const hits = difficulties.filter(diff =>
      autoAssignRuleAllowsDifficulty(categoryKey, subject, diff, student) === true
    );
    if (hits.length) return hits;
  }
  return difficulties[0] ? [difficulties[0]] : [];
}

function visibleDifficultyValues() {
  const assignedDifficulties = ruleDefaultDifficulties(activeCategory, activeSubject, activeStudent);
  if (
    !isUnitCategory(activeCategory) &&
    assignedDifficulties.length > 1 &&
    assignedDifficulties.includes(activeDifficulty)
  ) {
    return assignedDifficulties;
  }
  return activeDifficulty ? [activeDifficulty] : [];
}

function difficultyBadgeTone(categoryKey, difficulty) {
  const difficulties = CATEGORY_BY_KEY[categoryKey]?.difficulties || [];
  const index = Math.max(0, difficulties.findIndex(diff => String(diff) === String(difficulty)));
  return index === 0 ? 'high' : index === 1 ? 'middle' : 'base';
}

function shouldDefaultExcludeTest(test) {
  if (!test) return false;
  const subject = normalizeSubject(test.curriculum);
  const allowed = autoAssignRuleAllowsDifficulty(test.categoryKey, subject, test.difficulty, activeStudent);
  return allowed === false;
}

function roundOptionsFor(categoryKey, subject, difficulty) {
  if (!isUnitCategory(categoryKey)) return [];
  const rounds = new Set();
  activeCatalog
    .filter(test =>
      test.categoryKey === categoryKey &&
      normalizeSubject(test.curriculum) === normalizeSubject(subject) &&
      String(test.difficulty || '') === String(difficulty || '')
    )
    .forEach(test => {
      const round = normalizeRound(test.round || '');
      if (round) rounds.add(round);
    });

  const out = Array.from(rounds).sort((a, b) =>
    Number(a || 0) - Number(b || 0) || String(a).localeCompare(String(b), 'ko')
  );
  return out.length ? out : ROUND_OPTIONS.slice();
}

function defaultRoundFor(categoryKey, subject, difficulty) {
  if (!isUnitCategory(categoryKey)) return '';
  const rounds = roundOptionsFor(categoryKey, subject, difficulty);
  return rounds.includes('1') ? '1' : (rounds[0] || '1');
}

function applyRuleDefaults(categoryKey = activeCategory) {
  activeDifficulty = ruleDefaultDifficulty(categoryKey, activeSubject, activeStudent);
  activeRound = defaultRoundFor(categoryKey, activeSubject, activeDifficulty);
  if (isTermCategory(categoryKey) && !TERM_OPTIONS.includes(activeTerm)) activeTerm = defaultTermFromSchoolCalendar();
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
      const term = isTermCategory(categoryKey)
        ? normalizeTerm(rawTest.term || rawTest.examTerm || rawTest.semesterTerm, name)
        : '';
      const id = canonText(rawTest.id) || `t_${categoryKey}_${curriculum}_${difficulty}_${idx}`;

      const test = {
        ...rawTest,
        id,
        name,
        categoryKey,
        curriculum,
        difficulty,
        round,
        term,
        problems: Number.isFinite(+rawTest.problems) ? Math.max(1, Number(rawTest.problems)) : 20,
        _catalogIndex: idx,
      };
      test._key = testKey(test);
      out.push(test);
    });
  });

  const rankIn = (list, value) => {
    const index = list.indexOf(value);
    return index >= 0 ? index : list.length;
  };
  const orderValue = (test) => {
    const raw = test?.sortOrder ?? test?.sourceOrder ?? test?.order ?? test?.sourceIndex ?? test?._catalogIndex;
    const n = Number(raw);
    return Number.isFinite(n) ? n : 999999;
  };

  out.sort((a, b) => {
    const base =
      rankIn(CATEGORY_KEYS, a.categoryKey) - rankIn(CATEGORY_KEYS, b.categoryKey) ||
      rankIn(SUBJECTS, a.curriculum) - rankIn(SUBJECTS, b.curriculum) ||
      String(a.difficulty).localeCompare(String(b.difficulty), 'ko');
    if (base) return base;
    if (isUnitCategory(a.categoryKey) && isUnitCategory(b.categoryKey)) {
      return Number(a.round || 0) - Number(b.round || 0) ||
        orderValue(a) - orderValue(b) ||
        String(a.name).localeCompare(String(b.name), 'ko');
    }
    return orderValue(a) - orderValue(b) ||
      Number(a.round || 0) - Number(b.round || 0) ||
      String(a.name).localeCompare(String(b.name), 'ko');
  });

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
    const round = normalizeRound(rec.round || rec.testMeta?.round || '');
    if (round) {
      submittedNames.add(`${name}|||${round}`);
      if (name.includes('/')) submittedNames.add(`${canonText(name.split('/').pop())}|||${round}`);
    } else {
      submittedNames.add(name);
      if (name.includes('/')) submittedNames.add(canonText(name.split('/').pop()));
    }
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
    fetchJSONCached(`/api/logs?sid=${encodeURIComponent(sid)}`),
    fetchJSONCached(`/api/progress?sid=${encodeURIComponent(sid)}`),
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
  const currentEntry = state.progress?.[editingDate]?.[editingSid];
  const currentTests = currentEntry?.tests;
  if (currentTests && typeof currentTests === 'object' && Object.keys(currentTests).length) {
    return currentTests;
  }
  if (currentEntry && typeof currentEntry === 'object' && currentEntry[TEST_ASSIGN_CLEAR_KEY]) {
    return {};
  }

  const sid = String(editingSid || '').trim();
  const date = String(editingDate || '').trim();
  if (!sid || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return {};

  const dates = Object.keys(state.progress || {})
    .filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d) && d < date)
    .sort()
    .reverse();

  for (const d of dates) {
    const entry = state.progress?.[d]?.[sid];
    if (!entry || typeof entry !== 'object') continue;
    if (entry[TEST_ASSIGN_CLEAR_KEY]) return {};
    const tests = entry.tests;
    if (tests && typeof tests === 'object' && Object.keys(tests).length) return tests;
  }
  return {};
}

function isSubmitted(test) {
  if (!test) return false;
  const name = canonText(test.name);
  const round = normalizeRound(test.round || '');
  return submittedIds.has(String(test.id || '').trim()) ||
    submittedNames.has(`${name}|||${round}`) ||
    submittedNames.has(canonText(`${categoryLabel(test.categoryKey)} / ${test.name}`)) ||
    submittedNames.has(canonText(test._key));
}

function visibleTests() {
  const visibleDifficulties = visibleDifficultyValues();
  return activeCatalog.filter(test =>
    test.categoryKey === activeCategory &&
    normalizeSubject(test.curriculum) === activeSubject &&
    visibleDifficulties.includes(String(test.difficulty || '')) &&
    (!isTermCategory(activeCategory) || String(test.term || DEFAULT_TERM) === String(activeTerm || DEFAULT_TERM)) &&
    (!isUnitCategory(activeCategory) || normalizeRound(test.round || '') === String(activeRound || '1'))
  );
}

function syncSelectedFromProgress() {
  initialTestMap = { ...getCurrentProgressTests() };
  selectedKeys = new Set();
  selectedStatuses = new Map();
  defaultExclusionsApplied = false;
  Object.entries(initialTestMap).forEach(([key, status]) => {
    setTestStatus(key, normalizeAssignmentStatus(status));
  });
  activeCatalog.forEach(test => {
    if (!test?._key || selectedStatuses.has(test._key) || isSubmitted(test) || !shouldDefaultExcludeTest(test)) return;
    setTestStatus(test._key, 'skip');
    defaultExclusionsApplied = true;
  });
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
  const roundSel = $('testRound');
  const termSel = $('testTerm');
  if (subjectSel) {
    subjectSel.innerHTML = SUBJECTS.map(subject =>
      `<option value="${escapeHtml(subject)}"${subject === activeSubject ? ' selected' : ''}>${escapeHtml(subject)}</option>`
    ).join('');
  }

  const difficulties = CATEGORY_BY_KEY[activeCategory]?.difficulties || [];
  if (!difficulties.includes(activeDifficulty)) {
    activeDifficulty = ruleDefaultDifficulty(activeCategory, activeSubject, activeStudent);
  }
  if (difficultySel) {
    difficultySel.innerHTML = difficulties.map(diff =>
      `<option value="${escapeHtml(diff)}"${diff === activeDifficulty ? ' selected' : ''}>${escapeHtml(diff)}</option>`
    ).join('');
  }

  const rounds = roundOptionsFor(activeCategory, activeSubject, activeDifficulty);
  if (roundSel) {
    const roundField = roundSel.closest?.('.test-field');
    const showRound = isUnitCategory(activeCategory);
    if (roundField) roundField.style.display = showRound ? '' : 'none';
    roundSel.disabled = !showRound;
    if (showRound) {
      if (!rounds.includes(String(activeRound))) {
        activeRound = defaultRoundFor(activeCategory, activeSubject, activeDifficulty);
      }
      roundSel.innerHTML = rounds.map(round =>
        `<option value="${round}"${round === activeRound ? ' selected' : ''}>${roundLabel(round)}</option>`
      ).join('');
    } else {
      activeRound = '';
      roundSel.innerHTML = '<option value="">전체 순번</option>';
    }
  }

  if (termSel) {
    const termField = termSel.closest?.('.test-field');
    const showTerm = isTermCategory(activeCategory);
    if (termField) termField.style.display = showTerm ? '' : 'none';
    termSel.disabled = !showTerm;
    if (showTerm) {
      if (!TERM_OPTIONS.includes(activeTerm)) activeTerm = defaultTermFromSchoolCalendar();
      termSel.innerHTML = TERM_OPTIONS.map(term =>
        `<option value="${escapeHtml(term)}"${term === activeTerm ? ' selected' : ''}>${escapeHtml(term)}</option>`
      ).join('');
    } else {
      termSel.innerHTML = '<option value="">전체 고사</option>';
    }
  }

  const metaEl = $('testStudentMeta');
  if (metaEl) metaEl.textContent = `학생 레벨: ${activeStudent?.level || '-'}`;
}

function applyTestRowStatus(row, status) {
  if (!row || row.disabled) return;
  const key = row.dataset.testKey || '';
  const next = normalizeAssignmentStatus(status);
  setTestStatus(key, next);
  row.dataset.state = next || 'none';
  row.classList.toggle('is-selected', !!next);
  const statusEl = row.querySelector('.test-status');
  if (statusEl) statusEl.textContent = testStatusLabel(next);
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
        선택한 분류/과목/난이도/회차에 등록된 테스트가 없습니다.
      </div>
    `;
    return;
  }

  list.innerHTML = tests.map(test => {
    const done = isSubmitted(test);
    const rowStatus = statusForKey(test._key);
    const checked = done || !!rowStatus;
    const stateName = done ? 'done' : (rowStatus || 'none');
    const status = testStatusLabel(rowStatus, done);
    const baseMeta = [
      categoryLabel(test.categoryKey),
      test.curriculum,
    ].filter(Boolean).join(' · ');
    const tailMeta = [
      isTermCategory(test.categoryKey) ? test.term : '',
      isUnitCategory(test.categoryKey) ? roundLabel(test.round) : '',
    ].filter(Boolean).join(' · ');
    const tone = difficultyBadgeTone(test.categoryKey, test.difficulty);
    return `
      <button type="button" class="test-row${checked ? ' is-selected' : ''}${done ? ' is-done' : ''}"
        data-test-key="${escapeHtml(test._key)}" data-state="${escapeHtml(stateName)}"
        data-category="${escapeHtml(test.categoryKey)}" data-curriculum="${escapeHtml(test.curriculum)}"
        data-difficulty="${escapeHtml(test.difficulty)}" data-term="${escapeHtml(test.term || '')}"
        data-round="${escapeHtml(test.round || '')}" ${done ? ' disabled' : ''}>
        <span class="test-row-main">
          <strong>${escapeHtml(test.name)}</strong>
          <span class="test-row-meta">
            <span class="test-meta-text">${escapeHtml(baseMeta)}</span>
            <span class="test-difficulty-badge is-${escapeHtml(tone)}">${escapeHtml(test.difficulty)}</span>
            ${tailMeta ? `<span class="test-meta-text">${escapeHtml(tailMeta)}</span>` : ''}
          </span>
        </span>
        <span class="test-status">${escapeHtml(status)}</span>
      </button>
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
    #testModal .test-filter-grid{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }
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
      display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:center; text-align:left;
      min-height:46px; padding:7px 8px; border:1px solid #e5e7eb; border-radius:9px;
      background:#fff; color:inherit; cursor:pointer; box-sizing:border-box; user-select:none;
      font:inherit; transition-property:background-color,border-color,box-shadow,transform;
      transition-duration:.14s; transition-timing-function:cubic-bezier(.2,0,0,1);
    }
    body.dark #testModal .test-row{ background:#0b1220; border-color:#334155; }
    #testModal .test-row:not(:disabled):hover{ border-color:#93c5fd; box-shadow:0 4px 12px rgba(15,23,42,.08); }
    #testModal .test-row:not(:disabled):active{ transform:scale(.997); }
    #testModal .test-row:disabled{ cursor:default; opacity:1; }
    #testModal .test-row[data-state="assigned"],
    #testModal .test-row[data-state="done"]{ background:#10b98118; border-color:#10b98170; }
    #testModal .test-row[data-state="interrupted"]{ background:#f59e0b22; border-color:#f59e0b70; }
    #testModal .test-row[data-state="skip"]{ background:#ef444422; border-color:#ef444470; }
    #testModal .test-row.is-done{ background:#2563eb18; border-color:#2563eb70; }
    #testModal .test-row-main{ min-width:0; display:flex; flex-direction:column; gap:2px; }
    #testModal .test-row-main strong{ font-size:13px; line-height:1.25; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    #testModal .test-row-meta{
      min-width:0; display:flex; align-items:center; gap:5px; font-size:11px;
      color:#64748b; line-height:1.25; white-space:nowrap; overflow:hidden;
    }
    body.dark #testModal .test-row-meta{ color:#94a3b8; }
    #testModal .test-meta-text{ min-width:0; overflow:hidden; text-overflow:ellipsis; }
    #testModal .test-difficulty-badge{
      flex:0 0 auto; display:inline-flex; align-items:center; justify-content:center;
      height:18px; min-width:26px; padding:0 6px; border-radius:999px;
      border:1px solid #cbd5e1; background:#f8fafc; color:#334155;
      font-size:10px; line-height:1; font-weight:900; letter-spacing:0;
    }
    #testModal .test-difficulty-badge.is-high{ border-color:#bfdbfe; background:#eff6ff; color:#1d4ed8; }
    #testModal .test-difficulty-badge.is-middle{ border-color:#fed7aa; background:#fff7ed; color:#c2410c; }
    body.dark #testModal .test-difficulty-badge{ border-color:#475569; background:#111827; color:#cbd5e1; }
    body.dark #testModal .test-difficulty-badge.is-high{ border-color:#1d4ed8; background:#1e3a8a66; color:#bfdbfe; }
    body.dark #testModal .test-difficulty-badge.is-middle{ border-color:#c2410c; background:#7c2d1266; color:#fed7aa; }
    #testModal .test-status{
      justify-self:end; padding:3px 7px; border-radius:999px; background:#f1f5f9; color:#334155;
      font-size:11px; font-weight:900; white-space:nowrap;
    }
    body.dark #testModal .test-status{ background:#1f2937; color:#cbd5e1; }
    #testModal .test-row[data-state="assigned"] .test-status,
    #testModal .test-row[data-state="done"] .test-status{ background:#10b981; color:#fff; }
    #testModal .test-row[data-state="interrupted"] .test-status{ background:#f59e0b; color:#111827; }
    #testModal .test-row[data-state="skip"] .test-status{ background:#ef4444; color:#fff; }
    #testModal .test-row.is-done .test-status{ background:#2563eb; color:#fff; }
    #testModal .test-note-option{
      display:flex; align-items:center; gap:7px; padding:9px 10px; border:1px solid #e5e7eb;
      border-radius:9px; font-size:12px; font-weight:800; background:#f8fafc;
    }
    body.dark #testModal .test-note-option{ background:#0b1220; border-color:#334155; }
    #testModal .test-empty{ padding:14px; border:1px dashed #cbd5e1; border-radius:9px; color:#64748b; font-size:13px; }
    body.dark #testModal .test-empty{ border-color:#475569; color:#94a3b8; }
    @media (max-width:560px){
      #testModal .test-filter-grid{ grid-template-columns:1fr; }
    }
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
            <div class="test-field">
              <label for="testTerm">고사</label>
              <select id="testTerm"></select>
            </div>
            <div class="test-field">
              <label for="testRound">회차</label>
              <select id="testRound"></select>
            </div>
          </div>

          <div class="test-toolbar">
            <div class="test-sub">색상 표시된 항목이 오늘 선택 날짜에 배정됩니다.</div>
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

function renderLoadingState(student) {
  const title = $('testTitle');
  const meta = $('testStudentMeta');
  const count = $('testVisibleCount');
  const save = $('testSave');
  if (title) title.textContent = student ? `${student.name || ''} 테스트 배정` : '테스트 배정';
  if (meta) meta.textContent = '불러오는 중...';
  if (count) count.textContent = '';
  if (save) save.disabled = true;
  const tabs = $('testCategoryTabs');
  if (tabs) tabs.innerHTML = '<button type="button" class="test-tab is-active" disabled>불러오는 중</button>';
  ['testSubject', 'testDifficulty', 'testTerm', 'testRound'].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.disabled = true;
    el.innerHTML = '<option>불러오는 중</option>';
  });
  const list = $('testAssignList');
  if (list) list.innerHTML = '<div class="test-empty">테스트 목록을 불러오는 중...</div>';
}

function closeModal() {
  testOpenSeq += 1;
  const wasUnified = $('testModal')?.classList.contains('student-work-layout');
  setModalOpen(false);
  editingSid = null;
  editingDate = null;
  activeStudent = null;
  activeCatalog = [];
  catalogByKey = new Map();
  initialTestMap = {};
  selectedKeys = new Set();
  selectedStatuses = new Map();
  testSelectionTouched = false;
  defaultExclusionsApplied = false;
  activeRound = '1';
  activeTerm = defaultTermFromSchoolCalendar();
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
  const openSeq = ++testOpenSeq;

  const tr = rowOrButton?.closest?.('tr[data-sid]') || rowOrButton;
  editingSid = String(tr?.dataset?.sid || '').trim();
  editingDate = String(tr?.dataset?.date || getAdminDate()).trim();
  activeStudent = (state.students || []).find(stu => String(stu.id) === editingSid) || null;
  if (!editingSid || !activeStudent) {
    alert('학생 정보를 찾을 수 없습니다.');
    return;
  }

  activeSubject = normalizeSubject(activeStudent.curriculum);
  renderLoadingState(activeStudent);
  setModalOpen(true, opts.layout);
  await hydrateForTestPopup(editingDate, editingSid);
  if (openSeq !== testOpenSeq || editingSid !== String(tr?.dataset?.sid || '').trim()) return;
  activeTerm = defaultTermFromSchoolCalendar();
  syncSelectedFromProgress();

  activeCategory = chooseInitialCategory();
  applyRuleDefaults(activeCategory);
  testSelectionTouched = false;

  renderAll();
  ['testSubject', 'testDifficulty'].forEach((id) => {
    const el = $(id);
    if (el) el.disabled = false;
  });
  const termEl = $('testTerm');
  if (termEl) termEl.disabled = !isTermCategory(activeCategory);
  const roundEl = $('testRound');
  if (roundEl) roundEl.disabled = !isUnitCategory(activeCategory);
  const save = $('testSave');
  if (save) save.disabled = false;
  setModalOpen(true, opts.layout);
}

function selectedAssignmentObjects() {
  const order = new Map(activeCatalog.map((test, idx) => [test._key, idx]));
  return Array.from(selectedStatuses.entries()).sort((a, b) =>
    (order.get(a[0]) ?? 999999) - (order.get(b[0]) ?? 999999)
  ).map(([key, rawStatus]) => {
    const status = normalizeAssignmentStatus(rawStatus) || 'assigned';
    const test = catalogByKey.get(key);
    if (!test) return { label: key, status, statusLabel: testStatusLabel(status) };
    return {
      id: test.id,
      name: test.name,
      category: test.categoryKey,
      categoryLabel: categoryLabel(test.categoryKey),
      curriculum: test.curriculum,
      difficulty: test.difficulty,
      term: isTermCategory(test.categoryKey) ? test.term : '',
      round: String(test.round || ''),
      label: test._key,
      status,
      statusLabel: testStatusLabel(status),
    };
  });
}

function shouldIncludeInAssignmentNote(item) {
  const status = normalizeAssignmentStatus(item?.status) || 'assigned';
  return status === 'assigned' || status === 'done';
}

function buildAssignmentNote(items) {
  const noteItems = (items || []).filter(shouldIncludeInAssignmentNote);
  if (!noteItems.length) return '';
  const lines = noteItems.map(item => {
    if (!item || !item.name) return `- ${item.label}`;
    const status = item.status && item.status !== 'assigned' ? ` (${item.statusLabel || testStatusLabel(item.status)})` : '';
    const parts = [item.categoryLabel, item.curriculum, item.difficulty];
    if (item.term) parts.push(item.term);
    if (item.round) parts.push(roundLabel(item.round));
    return `- ${parts.filter(Boolean).join(' / ')}: ${item.name}${status}`;
  });
  return `[테스트 배정]\n${lines.join('\n')}`;
}

function replaceAssignmentNoteBlock(notes, previousBlock, nextBlock) {
  const current = String(notes || '').trimEnd();
  const previous = String(previousBlock || '').trim();
  const replacement = String(nextBlock || '').trim();
  if (!current) return replacement;

  let next = current;
  if (previous && next.includes(previous)) {
    next = next.replace(previous, replacement);
  } else {
    let matched = false;
    next = next.replace(/(^|\n{2,})\[테스트 배정\]\n(?:- [^\n]*(?:\n|$))+/g, (match, prefix = '') => {
      matched = true;
      if (replacement) return `${prefix}${replacement}`;
      return prefix ? '\n\n' : '';
    });
    if (!matched && replacement) next = `${next}\n\n${replacement}`;
  }

  return next.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
}

async function patchLogAssignment(items, appendToNotes) {
  const q = new URLSearchParams({ date: editingDate, sid: editingSid }).toString();
  const latest = await fetchJSONSafe(`/api/logs/entry?${q}`).catch(() => ({}));
  const entry = latest?.entry && typeof latest.entry === 'object' ? latest.entry : {};
  const clear = [];
  const logItems = (items || []).filter(item => normalizeAssignmentStatus(item?.status) !== 'skip');
  const patchEntry = {
    updatedAt: new Date().toISOString(),
  };
  if (logItems.length) patchEntry.assignedTests = logItems;
  else clear.push('assignedTests');

  const noteBlock = buildAssignmentNote(logItems);
  if (noteBlock) patchEntry.testAssignmentNote = noteBlock;
  else clear.push('testAssignmentNote');

  let notesChanged = false;
  if (appendToNotes) {
    const prevNotes = String(entry.notes || '').trimEnd();
    const prevBlock = String(entry.testAssignmentNote || '').trim();
    const nextNotes = replaceAssignmentNoteBlock(prevNotes, prevBlock, noteBlock);
    if (nextNotes.trim() !== prevNotes.trim()) {
      if (nextNotes.trim()) patchEntry.notes = nextNotes.trim();
      else clear.push('notes');
      notesChanged = true;
    }
  }

  const body = {
    date: editingDate,
    sid: editingSid,
    entry: patchEntry,
  };
  if (clear.length) body.__clear = clear;
  if (notesChanged) {
    body.base = { notes: String(entry.notes || '').trim() };
  }

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
  if (!testSelectionTouched && !defaultExclusionsApplied) {
    const items = selectedAssignmentObjects();
    if (options.showPopup !== false) toast('변경된 테스트 배정이 없습니다');
    return items;
  }

  const patchTests = {};
  const allKeys = new Set([...Object.keys(initialTestMap), ...selectedStatuses.keys()]);
  allKeys.forEach(key => {
    const test = catalogByKey.get(key);
    if (test && isSubmitted(test)) {
      patchTests[key] = 'done';
    } else {
      patchTests[key] = statusForKey(key) || '';
    }
  });
  const hasAnyTestStatus = Object.values(patchTests).some(status => !!normalizeAssignmentStatus(status));

  state.progress = state.progress || {};
  state.progress[editingDate] = state.progress[editingDate] || {};
  state.progress[editingDate][editingSid] = state.progress[editingDate][editingSid] || {};

  const progressRes = await fetchJSONSafe('/api/progress/patch', {
    method: 'POST',
    headers: CT,
    body: JSON.stringify({
      date: editingDate,
      sid: editingSid,
      progress: {
        tests: patchTests,
        [TEST_ASSIGN_CLEAR_KEY]: hasAnyTestStatus ? '' : new Date().toISOString(),
      },
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
  defaultExclusionsApplied = false;
  return items;
}

function bindEventsOnce() {
  if (initialized) return;
  initialized = true;

  let pointerDown = false;
  let dragActive = false;
  let dragTarget = null;
  let dragButton = 0;
  let startStatus = '';
  let startIndex = -1;
  let suppressClickOnce = false;
  let dragRows = [];
  let dragInitialStatuses = [];

  const testRowFromTarget = (target) => target?.closest?.('#testAssignList .test-row');
  const rebuildDragRows = () => {
    dragRows = Array.from(document.querySelectorAll('#testAssignList .test-row:not(:disabled)'));
    dragInitialStatuses = dragRows.map(row => statusForKey(row.dataset.testKey));
  };

  function applyDragRange(currentRow) {
    if (!pointerDown || !dragActive) return;
    const curIndex = dragRows.indexOf(currentRow);
    if (curIndex === -1 || startIndex === -1) return;

    const lo = Math.min(startIndex, curIndex);
    const hi = Math.max(startIndex, curIndex);
    dragRows.forEach((row, idx) => {
      const initial = dragInitialStatuses[idx] || '';
      const next = (idx >= lo && idx <= hi) ? dragTarget : initial;
      applyTestRowStatus(row, next);
    });
  }

  function handleDragMove(e) {
    if (!pointerDown) return;
    const row = testRowFromTarget(e.target);
    if (!row || row.disabled) return;

    if (!dragActive) {
      dragActive = true;
      dragTarget = dragButton === 2 ? 'skip' : nextStatusOf(startStatus);
    }
    applyDragRange(row);
    testSelectionTouched = true;
    e.preventDefault();
  }

  document.body.addEventListener('click', async (e) => {
    const categoryBtn = e.target.closest('#testCategoryTabs .test-tab');
    if (categoryBtn) {
      activeCategory = categoryBtn.dataset.category || activeCategory;
      applyRuleDefaults(activeCategory);
      renderAll();
      return;
    }

    if (e.target.closest('#testPickAll')) {
      visibleTests().forEach(test => {
        if (!isSubmitted(test)) setTestStatus(test._key, 'assigned');
      });
      testSelectionTouched = true;
      renderList();
      return;
    }

    if (e.target.closest('#testPickNone')) {
      visibleTests().forEach(test => {
        if (!isSubmitted(test)) setTestStatus(test._key, 'skip');
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

    const row = testRowFromTarget(e.target);
    if (row && !row.disabled) {
      if (suppressClickOnce) {
        suppressClickOnce = false;
        return;
      }
      const key = row.dataset.testKey || '';
      applyTestRowStatus(row, nextStatusOf(statusForKey(key)));
      testSelectionTouched = true;
    }
  });

  document.body.addEventListener('mousedown', (e) => {
    if (e.button !== 0 && e.button !== 2) return;
    const row = testRowFromTarget(e.target);
    if (!row || row.disabled) return;
    if (e.button === 2) e.preventDefault();

    rebuildDragRows();
    startIndex = dragRows.indexOf(row);
    if (startIndex === -1) return;

    pointerDown = true;
    dragActive = false;
    dragTarget = null;
    dragButton = e.button;
    startStatus = statusForKey(row.dataset.testKey);
  });

  document.body.addEventListener('mousemove', handleDragMove);
  document.body.addEventListener('mouseover', handleDragMove);

  document.body.addEventListener('contextmenu', (e) => {
    const row = testRowFromTarget(e.target);
    if (!row || row.disabled) return;
    e.preventDefault();
    applyTestRowStatus(row, 'skip');
    testSelectionTouched = true;
  });

  document.addEventListener('mouseup', () => {
    if (!pointerDown) return;
    pointerDown = false;
    if (dragActive && dragButton === 0) suppressClickOnce = true;

    dragActive = false;
    dragTarget = null;
    dragButton = 0;
    startStatus = '';
    startIndex = -1;
  });

  document.body.addEventListener('change', (e) => {
    if (e.target?.id === 'testSubject') {
      activeSubject = normalizeSubject(e.target.value);
      applyRuleDefaults(activeCategory);
      renderAll();
      return;
    }

    if (e.target?.id === 'testDifficulty') {
      activeDifficulty = e.target.value || activeDifficulty;
      activeRound = defaultRoundFor(activeCategory, activeSubject, activeDifficulty);
      renderAll();
      return;
    }

    if (e.target?.id === 'testTerm') {
      activeTerm = TERM_OPTIONS.includes(e.target.value) ? e.target.value : defaultTermFromSchoolCalendar();
      renderList();
      return;
    }

    if (e.target?.id === 'testRound') {
      activeRound = String(e.target.value || '1');
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
