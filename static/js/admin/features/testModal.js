// /js/admin/features/testModal.js
// Admin test assignment popup. Stores assignment status in progress[date][sid].tests
// and optionally writes a readable assignment block into the class log notes.

import { $, CT, toast } from '../core/utils.js';
import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import { createAssignmentDragAutoScroll } from './assignmentDragAutoScroll.js?v=20261007';
import { createUnitTestDisplayNameResolver } from '../../shared/testCatalogDisplay.js';

import {
  CATEGORY_DEFS, CATEGORY_BY_KEY,
  CATEGORY_KEYS, ROUND_OPTIONS,
  TERM_OPTIONS, DEFAULT_TERM,
  isUnitCategory, isTermCategory, canonText, normalizeSubject,
  categoryLabel, canonicalCategoryKey, isIlsanGraphDifficultyText,
  normalizeRound, roundLabel, normalizeTerm, normalizeAssignmentStatus,
  testStatusLabel, nextStatusOf, nextExcludedStatusOf, nextKeyboardStatusOf,
  isInProgressTestStatus, isResolvedTestStatus, isExplicitBlankTestStatus,
  normalizeConfig, collectTestCatalog,
} from './testAssignmentRules.js?v=20260907-ilsan-level-r1';
const SCHOOL_CAL_PAGE_STORAGE_KEY = 'schoolCal.selectedPage.v1';
const TEST_ASSIGN_CLEAR_KEY = '__testsClearedAt';
const TEST_ASSIGN_CHANGE_ORDER_KEY = '__testAssignmentChangeOrder';
const TEST_ASSIGN_TOUCHED_KEYS_KEY = '__testAssignmentTouchedKeys';
const TEST_ASSIGN_DAILY_ITEMS_KEY = 'testAssignmentDailyTests';
const STUDENT_TEST_LEVEL_DEFAULTS_FIELD = 'testLevelDefaults';
const STUDENT_LEVEL_SETTING_CATEGORY = 'UNIT';
const TEST_RECENT_VIEW_STORAGE_PREFIX = 'admin.testAssignment.recentView.v1';

let initialized = false;
let editingSid = null;
let editingDate = null;
let testModalReady = false;
const testSaveFlights = new Map();
let activeStudent = null;
let activeCategory = 'UNIT';
let activeSubject = '공수1';
let activeDifficulty = 'Lv.3';
let activeRound = '1';
let activeTerm = DEFAULT_TERM;
let levelSettingOpen = false;
let activeCatalog = [];
let catalogByKey = new Map();
let initialTestMap = {};
let selectedStatuses = new Map();
let multiSelectedKeys = new Set();
let explicitBlankKeys = new Set();
let touchedTestKeys = new Set();
let testChangeOrderByKey = {};
let pendingCenteredTestKey = '';
let submittedIds = new Set();
let submittedNames = new Set();
let testSelectionTouched = false;
let testOpenSeq = 0;
let stopTestAssignmentDrag = () => {};


function isLockConflictResponse(status, text) {
  const body = String(text || '').toLowerCase();
  return status === 409 && (
    body.includes('lock timeout')
    || body.includes('lock_timeout')
    || body.includes('.lock')
  );
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function fetchJSONSafe(url, init = {}) {
  const {
    lockRetryDelays = [700, 1300, 2200],
    ...fetchInit
  } = init || {};

  for (let attempt = 0; attempt <= lockRetryDelays.length; attempt++) {
    const res = await fetch(url, { cache: 'no-store', ...fetchInit });
    const txt = await res.text();
    if (!res.ok) {
      if (isLockConflictResponse(res.status, txt) && attempt < lockRetryDelays.length) {
        await sleep(lockRetryDelays[attempt]);
        continue;
      }
      throw new Error(`[testModal] ${fetchInit.method || 'GET'} ${url} -> ${res.status}\n${txt.slice(0, 200)}`);
    }
    try { return txt.trim() ? JSON.parse(txt) : {}; }
    catch (e) { throw new Error(`[testModal] Bad JSON from ${url}: ${e?.message}\n${txt.slice(0, 200)}`); }
  }
  throw new Error(`[testModal] ${fetchInit.method || 'GET'} ${url} failed after lock retries`);
}

function requireTestPopupDocument(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.ok === false) {
    throw new Error('시험 조회 응답이 올바르지 않습니다.');
  }
  return value;
}

async function fetchJSONCached(url, ttlMs = 2500) {
  const cache = window.__studentWorkFetchCache || (window.__studentWorkFetchCache = new Map());
  const epochs = window.__studentWorkFetchEpochs || (window.__studentWorkFetchEpochs = new Map());
  const readEpoch = epochs.get(url) || 0;
  const now = Date.now();
  const hit = cache.get(url);
  if (hit && (hit.pending || (now - hit.ts) < ttlMs)) {
    return hit.promise.then(requireTestPopupDocument).catch(error => {
      if (cache.get(url)?.promise === hit.promise) cache.delete(url);
      throw error;
    });
  }

  const pending = fetchJSONSafe(url).then(requireTestPopupDocument);
  const promise = pending.then(value => {
    if ((epochs.get(url) || 0) !== readEpoch) {
      throw new Error('팝업 데이터가 변경되었습니다. 다시 열어 주세요.');
    }
    return value;
  });
  cache.set(url, { ts: now, promise, pending: true });
  promise.then(() => {
    if (cache.get(url)?.promise === promise) {
      cache.set(url, { ts: Date.now(), promise, pending: false });
    }
  }, () => {});
  promise.catch(() => {
    if (cache.get(url)?.promise === promise) cache.delete(url);
  });
  return promise;
}

function invalidateStudentWorkFetchCache(url) {
  const epochs = window.__studentWorkFetchEpochs || (window.__studentWorkFetchEpochs = new Map());
  epochs.set(url, (epochs.get(url) || 0) + 1);
  window.__studentWorkFetchCache?.delete?.(url);
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


function statusForKey(key) {
  return normalizeAssignmentStatus(selectedStatuses.get(key));
}


function setTestStatus(key, status) {
  const k = String(key || '').trim();
  if (!k) return;
  const normalized = normalizeAssignmentStatus(status);
  if (normalized) {
    selectedStatuses.set(k, normalized);
    explicitBlankKeys.delete(k);
  } else {
    selectedStatuses.delete(k);
  }
}

function markTestTouched(key) {
  const normalizedKey = String(key || '').trim();
  if (normalizedKey) touchedTestKeys.add(normalizedKey);
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
  const studentDefault = studentTestLevelDefault(categoryKey, subject, student);
  if (studentDefault) return [studentDefault];
  if (categoryKey === 'ILSAN_PAST') return difficulties.slice();
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

function studentTestLevelDefault(categoryKey, subject, student = activeStudent) {
  const difficulties = CATEGORY_BY_KEY[categoryKey]?.difficulties || [];
  const stored = student?.[STUDENT_TEST_LEVEL_DEFAULTS_FIELD];
  const categoryDefaults = stored && typeof stored === 'object' && !Array.isArray(stored)
    ? stored[categoryKey]
    : null;
  const difficulty = categoryDefaults && typeof categoryDefaults === 'object'
    ? String(categoryDefaults[normalizeSubject(subject)] || '').trim()
    : '';
  return difficulties.includes(difficulty) ? difficulty : '';
}

function copyStudentTestLevelDefaults(student = activeStudent) {
  const stored = student?.[STUDENT_TEST_LEVEL_DEFAULTS_FIELD];
  if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return {};
  return Object.fromEntries(Object.entries(stored).map(([categoryKey, values]) => [
    categoryKey,
    values && typeof values === 'object' && !Array.isArray(values) ? { ...values } : values,
  ]));
}

async function saveStudentTestLevelDefault(categoryKey, subject, difficulty) {
  const sid = String(editingSid || '').trim();
  const student = activeStudent;
  if (!sid || !student) throw new Error('학생별 테스트 레벨 기본값을 저장할 학생이 없습니다.');

  const previous = student[STUDENT_TEST_LEVEL_DEFAULTS_FIELD];
  const next = copyStudentTestLevelDefaults(student);
  const categoryDefaults = next[categoryKey] && typeof next[categoryKey] === 'object' && !Array.isArray(next[categoryKey])
    ? { ...next[categoryKey] }
    : {};
  categoryDefaults[normalizeSubject(subject)] = difficulty;
  next[categoryKey] = categoryDefaults;
  student[STUDENT_TEST_LEVEL_DEFAULTS_FIELD] = next;

  try {
    const { ensureOk, sendJson } = await import('../../shared/api.js');
    const response = await sendJson('/api/update', {
      id: sid,
      field: STUDENT_TEST_LEVEL_DEFAULTS_FIELD,
      value: next,
    }, { cache: 'no-store' });
    await ensureOk(response, '학생별 테스트 레벨 기본값 저장');
  } catch (error) {
    if (previous === undefined) delete student[STUDENT_TEST_LEVEL_DEFAULTS_FIELD];
    else student[STUDENT_TEST_LEVEL_DEFAULTS_FIELD] = previous;
    throw error;
  }

  return next;
}

function visibleDifficultyValues() {
  if (activeCategory === 'ILSAN_PAST') {
    return (CATEGORY_BY_KEY.ILSAN_PAST?.difficulties || []).slice();
  }
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

function unitTestsForRound(categoryKey, subject, difficulty, round) {
  if (!isUnitCategory(categoryKey)) return [];
  const normalizedRound = String(round || '1');
  return activeCatalog.filter(test =>
    test.categoryKey === categoryKey &&
    normalizeSubject(test.curriculum) === normalizeSubject(subject) &&
    String(test.difficulty || '') === String(difficulty || '') &&
    normalizeRound(test.round || '') === normalizedRound
  );
}

function isUnitRoundFullyResolved(categoryKey, subject, difficulty, round) {
  const tests = unitTestsForRound(categoryKey, subject, difficulty, round);
  return tests.length > 0 && tests.every(test => isSubmitted(test) || isResolvedTestStatus(statusForKey(test._key)));
}

function hasInProgressUnitRoundStatus(categoryKey, subject, difficulty, round) {
  return unitTestsForRound(categoryKey, subject, difficulty, round)
    .some(test => !isSubmitted(test) && isInProgressTestStatus(statusForKey(test._key)));
}

function defaultRoundFor(categoryKey, subject, difficulty) {
  if (!isUnitCategory(categoryKey)) return '';
  const rounds = roundOptionsFor(categoryKey, subject, difficulty);
  const activeRound = rounds.find(round =>
    hasInProgressUnitRoundStatus(categoryKey, subject, difficulty, round)
  );
  if (activeRound) return activeRound;
  const firstUnresolvedRound = rounds.find(round =>
    !isUnitRoundFullyResolved(categoryKey, subject, difficulty, round)
  );
  return firstUnresolvedRound || rounds[rounds.length - 1] || '1';
}

function applyRuleDefaults(categoryKey = activeCategory) {
  const activeTest = firstInProgressAssignmentTest(categoryKey);
  activeDifficulty = ruleDefaultDifficulty(categoryKey, activeSubject, activeStudent);
  if (activeTest?.difficulty) activeDifficulty = activeTest.difficulty;
  if (isTermCategory(categoryKey)) {
    activeTerm = activeTest?.term || (TERM_OPTIONS.includes(activeTerm) ? activeTerm : defaultTermFromSchoolCalendar());
  }
  activeRound = defaultRoundFor(categoryKey, activeSubject, activeDifficulty);
}

function collectCatalog(cfg) {
  return collectTestCatalog(cfg, activeSubject);
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

function entryForDateSid(source, date, sid) {
  const bySid = source?.[date];
  if (!bySid || typeof bySid !== 'object') return {};
  const sidKey = String(sid || '').trim();
  const direct = bySid[sidKey];
  if (direct && typeof direct === 'object') return direct;
  return {};
}

function currentProgressEntry() {
  return entryForDateSid(state.progress, editingDate, editingSid);
}

function currentLogEntry() {
  return entryForDateSid(state.logs, editingDate, editingSid);
}

function logAssignmentStatusMap(entry) {
  const out = {};
  [TEST_ASSIGN_DAILY_ITEMS_KEY, 'assignedTests'].forEach(field => {
    const items = entry?.[field];
    if (!Array.isArray(items)) return;
    items.forEach(item => {
      if (!item || typeof item !== 'object') return;
      const label = assignmentLabel(item);
      const status = normalizeAssignmentStatus(item.status || 'assigned');
      if (label && status) out[label] = status;
    });
  });
  return out;
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

function testPopupReadUrls(sid) {
  const sidKey = String(sid || '').trim();
  return [
    '/api/tests-config',
    `/api/logs?sid=${encodeURIComponent(sidKey)}`,
    `/api/progress?sid=${encodeURIComponent(sidKey)}`,
    '/api/tests',
  ];
}

function prefetchTestModalDataForRow(row) {
  const sid = String(row?.dataset?.sid || '').trim();
  if (!sid) return Promise.resolve([]);
  return Promise.allSettled(testPopupReadUrls(sid).map(url => fetchJSONCached(url)));
}

async function hydrateForTestPopup(date, sid, isCurrent = () => true) {
  const [cfg, logs, progress, testsJson] = await Promise.all([
    fetchJSONCached('/api/tests-config'),
    fetchJSONCached(`/api/logs?sid=${encodeURIComponent(sid)}`),
    fetchJSONCached(`/api/progress?sid=${encodeURIComponent(sid)}`),
    fetchJSONCached('/api/tests'),
  ]);
  if (!isCurrent()) return false;
  if ([cfg, logs, progress, testsJson].some(value => !value || typeof value !== 'object' || Array.isArray(value))) {
    throw new Error('시험 조회 응답이 올바르지 않습니다.');
  }

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

  const curriculumSubject = activeStudentCurriculumSubject();
  activeCatalog = collectCatalog(state.testsConfig).filter(test =>
    curriculumSubject && normalizeSubject(test.curriculum) === curriculumSubject
  );
  catalogByKey = new Map(activeCatalog.map(test => [test._key, test]));
  return true;
}

function getCurrentProgressTests() {
  const currentEntry = currentProgressEntry();
  const currentTests = currentEntry?.tests;
  const currentLogTests = logAssignmentStatusMap(currentLogEntry());
  if (currentTests && typeof currentTests === 'object' && Object.keys(currentTests).length) {
    return { ...currentLogTests, ...currentTests };
  }
  if (currentEntry && typeof currentEntry === 'object' && currentEntry[TEST_ASSIGN_CLEAR_KEY]) {
    return {};
  }
  if (Object.keys(currentLogTests).length) {
    return currentLogTests;
  }

  const sid = String(editingSid || '').trim();
  const date = String(editingDate || '').trim();
  if (!sid || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return {};

  const dates = Object.keys(state.progress || {})
    .filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d) && d < date)
    .sort()
    .reverse();

  for (const d of dates) {
    const entry = entryForDateSid(state.progress, d, sid);
    if (!entry || typeof entry !== 'object') continue;
    const tests = entry.tests;
    if (tests && typeof tests === 'object' && Object.keys(tests).length) return tests;
    if (entry[TEST_ASSIGN_CLEAR_KEY]) return {};
  }
  return {};
}

function progressEntryForCurrentTestHistory() {
  const currentEntry = currentProgressEntry();
  const currentTests = currentEntry?.tests;
  if (currentTests && typeof currentTests === 'object' && Object.keys(currentTests).length) {
    return currentEntry;
  }
  if (currentEntry && typeof currentEntry === 'object' && currentEntry[TEST_ASSIGN_CLEAR_KEY]) {
    return null;
  }
  if (Object.keys(logAssignmentStatusMap(currentLogEntry())).length) return null;

  const sid = String(editingSid || '').trim();
  const date = String(editingDate || '').trim();
  if (!sid || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;

  const dates = Object.keys(state.progress || {})
    .filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d) && d < date)
    .sort()
    .reverse();
  for (const d of dates) {
    const entry = entryForDateSid(state.progress, d, sid);
    if (!entry || typeof entry !== 'object') continue;
    if (entry[TEST_ASSIGN_CLEAR_KEY]) return null;
    if (entry.tests && typeof entry.tests === 'object' && Object.keys(entry.tests).length) return entry;
  }
  return null;
}

function currentTestChangeOrderMap() {
  const raw = progressEntryForCurrentTestHistory()?.[TEST_ASSIGN_CHANGE_ORDER_KEY];
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  return Object.fromEntries(Object.entries(raw).flatMap(([key, value]) => {
    const order = Number(value);
    return String(key || '').trim() && Number.isFinite(order) && order > 0
      ? [[String(key), order]]
      : [];
  }));
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
  testChangeOrderByKey = currentTestChangeOrderMap();
  selectedStatuses = new Map();
  multiSelectedKeys = new Set();
  explicitBlankKeys = new Set();
  touchedTestKeys = new Set();
  pendingCenteredTestKey = '';
  Object.entries(initialTestMap).forEach(([key, status]) => {
    if (isExplicitBlankTestStatus(status) || status === '') {
      explicitBlankKeys.add(key);
      return;
    }
    setTestStatus(key, normalizeAssignmentStatus(status));
  });
}

function selectedTestCount() {
  return Array.from(multiSelectedKeys).filter(key => {
    const test = catalogByKey.get(key);
    return test && !isSubmitted(test);
  }).length;
}

function renderMultiSelectionMeta() {
  const meta = $('testSelectionMeta');
  if (!meta) return;
  const count = selectedTestCount();
  meta.textContent = count
    ? `선택 ${count}개 · ←/→로 상태 변경`
    : 'Ctrl+클릭으로 다중 선택 · ←/→로 상태 변경';
}

function applyTestRowSelection(row) {
  if (!row) return;
  const selected = multiSelectedKeys.has(row.dataset.testKey || '');
  row.classList.toggle('is-multi-selected', selected);
  row.dataset.selection = selected ? 'selected' : 'none';
  row.setAttribute('aria-selected', selected ? 'true' : 'false');
}

function toggleMultiSelection(row) {
  if (!row || row.disabled) return;
  const key = row.dataset.testKey || '';
  if (!key) return;
  rememberCurrentTestView(catalogByKey.get(key));
  if (multiSelectedKeys.has(key)) multiSelectedKeys.delete(key);
  else multiSelectedKeys.add(key);
  applyTestRowSelection(row);
  renderMultiSelectionMeta();
}

function clearMultiSelection() {
  multiSelectedKeys.clear();
  document.querySelectorAll('#testAssignList .test-row').forEach(applyTestRowSelection);
  renderMultiSelectionMeta();
}

function applyKeyboardStatusToSelection(direction) {
  const keys = Array.from(multiSelectedKeys).filter(key => {
    const test = catalogByKey.get(key);
    return test && !isSubmitted(test);
  });
  if (!keys.length) return false;

  keys.forEach(key => {
    const next = nextKeyboardStatusOf(statusForKey(key), direction);
    setTestStatus(key, next);
    if (next) explicitBlankKeys.delete(key);
    else explicitBlankKeys.add(key);
  });

  document.querySelectorAll('#testAssignList .test-row').forEach(row => {
    if (multiSelectedKeys.has(row.dataset.testKey || '') && !row.disabled) {
      applyTestRowStatus(row, statusForKey(row.dataset.testKey || ''));
    }
  });
  testSelectionTouched = true;
  renderMultiSelectionMeta();
  return true;
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

function syncLevelSettingButton() {
  const button = $('testDifficultyOverride');
  if (!button) return;
  button.disabled = false;
  button.classList.toggle('is-active', levelSettingOpen);
  button.setAttribute('aria-pressed', levelSettingOpen ? 'true' : 'false');
  button.title = levelSettingOpen
    ? '학생별 기본 레벨을 고르세요'
    : '학생별 기본 테스트 레벨 설정';
}

function renderLevelSettingPanel() {
  const panel = $('testLevelSettingPanel');
  const optionsHost = $('testLevelSettingOptions');
  if (!panel || !optionsHost) return;

  const levels = CATEGORY_BY_KEY[STUDENT_LEVEL_SETTING_CATEGORY]?.difficulties || ['Lv.3', 'Lv.4', 'Lv.5', 'Lv.6'];
  const stored = studentTestLevelDefault(STUDENT_LEVEL_SETTING_CATEGORY, activeSubject, activeStudent);
  const effective = stored || ruleDefaultDifficulty(STUDENT_LEVEL_SETTING_CATEGORY, activeSubject, activeStudent);
  panel.hidden = !levelSettingOpen;
  optionsHost.innerHTML = levels.map(level => {
    const active = level === effective;
    return `
      <button type="button" class="test-level-setting-option${active ? ' is-active' : ''}"
        data-test-level-setting="${escapeHtml(level)}" aria-pressed="${active ? 'true' : 'false'}">
        ${escapeHtml(level)}
      </button>
    `;
  }).join('');

  const current = $('testLevelSettingCurrent');
  if (current) current.textContent = effective ? `현재 기본값: ${effective}` : '기본값을 선택하세요.';
}

function renderFilters() {
  const subjectSel = $('testSubject');
  const difficultySel = $('testDifficulty');
  const roundSel = $('testRound');
  const termSel = $('testTerm');
  if (subjectSel) {
    const curriculumSubject = activeStudentCurriculumSubject();
    activeSubject = curriculumSubject || activeSubject;
    subjectSel.innerHTML = activeSubject
      ? `<option value="${escapeHtml(activeSubject)}" selected>${escapeHtml(activeSubject)}</option>`
      : '<option value="">현재 커리큘럼 없음</option>';
    subjectSel.disabled = true;
  }

  const difficulties = CATEGORY_BY_KEY[activeCategory]?.difficulties || [];
  if (!difficulties.includes(activeDifficulty)) {
    activeDifficulty = ruleDefaultDifficulty(activeCategory, activeSubject, activeStudent) || difficulties[0] || '';
  }
  if (difficultySel) {
    difficultySel.innerHTML = difficulties.map(diff =>
      `<option value="${escapeHtml(diff)}"${diff === activeDifficulty ? ' selected' : ''}>${escapeHtml(diff)}</option>`
    ).join('');
  }

  syncLevelSettingButton();

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
  renderLevelSettingPanel();
}

function applyTestRowStatus(row, status, options = {}) {
  if (!row || row.disabled) return;
  const key = row.dataset.testKey || '';
  const next = normalizeAssignmentStatus(status);
  setTestStatus(key, next);
  if (options.touch !== false) markTestTouched(key);
  if (next) explicitBlankKeys.delete(key);
  else if (options.touch !== false || isExplicitBlankTestStatus(initialTestMap[key]) || initialTestMap[key] === '') {
    explicitBlankKeys.add(key);
  }
  row.dataset.state = next || 'none';
  row.classList.toggle('is-selected', !!next);
  const statusEl = row.querySelector('.test-status');
  if (statusEl) statusEl.textContent = testStatusLabel(next);
  if (options.remember !== false) rememberCurrentTestView(catalogByKey.get(key));
}

function centerTestRowInScroller(row, scroller) {
  if (!row || !scroller) return false;
  const scrollHeight = Number(scroller.scrollHeight) || 0;
  const clientHeight = Number(scroller.clientHeight) || 0;
  if (!clientHeight || scrollHeight <= clientHeight + 1) return false;

  const rowRect = row.getBoundingClientRect?.();
  const scrollerRect = scroller.getBoundingClientRect?.();
  if (!rowRect || !scrollerRect) return false;
  const rowHeight = Number(rowRect.height) || Math.max(0, Number(rowRect.bottom) - Number(rowRect.top));
  const scrollerHeight = Number(scrollerRect.height) || clientHeight;
  const currentTop = Number(scroller.scrollTop) || 0;
  const targetTop = currentTop
    + (Number(rowRect.top) + rowHeight / 2)
    - (Number(scrollerRect.top) + scrollerHeight / 2);
  scroller.scrollTop = Math.max(0, Math.min(scrollHeight - clientHeight, targetTop));
  return true;
}

function centerPendingTestRow() {
  const key = String(pendingCenteredTestKey || '').trim();
  pendingCenteredTestKey = '';
  if (!key) return false;
  const list = $('testAssignList');
  const rows = Array.from(list?.querySelectorAll?.('.test-row') || []);
  const row = rows.find(candidate => String(candidate.dataset?.testKey || '') === key);
  return centerTestRowInScroller(row, list);
}

function renderList() {
  stopTestAssignmentDrag();
  const list = $('testAssignList');
  if (!list) return;

  const tests = visibleTests();
  const count = $('testVisibleCount');
  if (count) count.textContent = `${tests.length}개`;

  renderMultiSelectionMeta();
  if (!tests.length) {
    list.innerHTML = `
      <div class="test-empty">
        선택한 분류/과목/난이도/회차에 등록된 테스트가 없습니다.
      </div>
    `;
    return;
  }

  const displayNameFor = createUnitTestDisplayNameResolver(activeCatalog);
  list.innerHTML = tests.map(test => {
    const done = isSubmitted(test);
    const rowStatus = statusForKey(test._key);
    const checked = done || !!rowStatus;
    const stateName = done ? 'done' : (rowStatus || 'none');
    const status = testStatusLabel(rowStatus, done);
    const multiSelected = multiSelectedKeys.has(test._key);
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
      <button type="button" class="test-row${checked ? ' is-selected' : ''}${done ? ' is-done' : ''}${multiSelected ? ' is-multi-selected' : ''}"
        data-test-key="${escapeHtml(test._key)}" data-state="${escapeHtml(stateName)}"
        data-category="${escapeHtml(test.categoryKey)}" data-curriculum="${escapeHtml(test.curriculum)}"
        data-difficulty="${escapeHtml(test.difficulty)}" data-term="${escapeHtml(test.term || '')}"
        data-selection="${multiSelected ? 'selected' : 'none'}" aria-selected="${multiSelected ? 'true' : 'false'}"
        data-round="${escapeHtml(test.round || '')}" ${done ? ' disabled' : ''}>
        <span class="test-row-main">
          <strong>${escapeHtml(displayNameFor(test))}</strong>
          <span class="test-row-meta">
            <span class="test-meta-text">${escapeHtml(baseMeta)}</span>
            <span class="test-difficulty-badge is-${escapeHtml(tone)}">${escapeHtml(test.difficulty)}</span>
            ${tailMeta ? `<span class="test-meta-text">${escapeHtml(tailMeta)}</span>` : ''}
          </span>
        </span>
        <span class="test-row-statuses">
          <span class="test-selection-status">선택</span>
          <span class="test-status">${escapeHtml(status)}</span>
        </span>
      </button>
    `;
  }).join('');
  centerPendingTestRow();
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
    #testModal .test-body{ flex:1 1 auto; min-height:0; overflow:hidden; padding-top:10px; display:flex; flex-direction:column; gap:10px; }
    #testModal .test-tabbar{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; }
    #testModal .test-tab{
      min-height:34px; border:1px solid #cbd5e1; border-radius:999px; background:#fff;
      color:#0f172a; font-weight:900; cursor:pointer; font-size:12px;
    }
    #testModal .test-tab.is-active{ background:#2563eb; border-color:#2563eb; color:#fff; }
    body.dark #testModal .test-tab{ background:#0f172a; color:#e5e7eb; border-color:#475569; }
    body.dark #testModal .test-tab.is-active{ background:#2563eb; color:#fff; border-color:#2563eb; }
    #testModal .test-filter-grid{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }
    #testModal .test-field label,
    #testModal .test-field-label{ display:block; margin-bottom:3px; font-size:12px; color:#64748b; font-weight:800; }
    body.dark #testModal .test-field label,
    body.dark #testModal .test-field-label{ color:#94a3b8; }
    #testModal select{
      width:100%; height:34px; border-radius:8px; border:1px solid #cbd5e1;
      background:#fff; color:#0f172a; padding:0 8px; box-sizing:border-box;
    }
    body.dark #testModal select{ background:#0f172a; color:#e5e7eb; border-color:#475569; }
    #testModal .test-override-btn{
      width:100%; height:34px; border-radius:8px; border:1px solid #cbd5e1;
      background:#f8fafc; color:#334155; font-weight:900; cursor:pointer;
    }
    #testModal .test-override-btn.is-active{ border-color:#7c3aed; background:#7c3aed; color:#fff; }
    body.dark #testModal .test-override-btn{ background:#0f172a; color:#e5e7eb; border-color:#475569; }
    body.dark #testModal .test-override-btn.is-active{ background:#8b5cf6; border-color:#8b5cf6; color:#fff; }
    #testModal .test-level-setting-panel{
      display:flex; flex-direction:column; gap:7px; padding:9px 10px;
      border:1px solid #c4b5fd; border-radius:9px; background:#f5f3ff;
    }
    #testModal .test-level-setting-panel[hidden]{ display:none; }
    body.dark #testModal .test-level-setting-panel{ border-color:#6d28d9; background:#2e1065; }
    #testModal .test-level-setting-head{ display:flex; align-items:center; justify-content:space-between; gap:8px; }
    #testModal .test-level-setting-head strong{ font-size:12px; }
    #testModal .test-level-setting-options{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; }
    #testModal .test-level-setting-option{
      height:32px; border:1px solid #c4b5fd; border-radius:8px; background:#fff;
      color:#5b21b6; font-weight:900; cursor:pointer;
    }
    #testModal .test-level-setting-option.is-active{ border-color:#7c3aed; background:#7c3aed; color:#fff; }
    #testModal .test-level-setting-option:disabled{ cursor:wait; opacity:.65; }
    body.dark #testModal .test-level-setting-option{ border-color:#8b5cf6; background:#1e1b4b; color:#ddd6fe; }
    body.dark #testModal .test-level-setting-option.is-active{ border-color:#8b5cf6; background:#8b5cf6; color:#fff; }
    #testModal .test-toolbar{ display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; }
    #testModal .test-mini-actions{ display:flex; gap:6px; flex-wrap:wrap; }
    #testModal .test-toolbar-copy{ min-width:0; display:flex; flex-direction:column; gap:2px; }
    #testModal .test-selection-meta{ color:#7c3aed; font-size:11px; font-weight:900; line-height:1.3; }
    body.dark #testModal .test-selection-meta{ color:#c4b5fd; }
    #testModal .test-mini-actions button{
      min-height:30px; padding:0 9px; border:1px solid #cbd5e1; border-radius:8px;
      background:#f8fafc; color:#0f172a; font-weight:800; cursor:pointer; font-size:12px;
    }
    body.dark #testModal .test-mini-actions button{ background:#334155; color:#e5e7eb; border-color:#475569; }
    #testModal .test-list{ flex:1 1 auto; min-height:0; overflow:auto; display:flex; flex-direction:column; gap:6px; padding-right:2px; }
    #testModal.student-work-layout .test-tabbar{
      grid-template-columns:repeat(2,minmax(0,1fr));
    }
    #testModal.student-work-layout .test-filter-grid{
      grid-template-columns:repeat(2,minmax(0,1fr));
      gap:7px;
    }
    #testModal.student-work-layout .test-toolbar{
      align-items:stretch;
      flex-direction:column;
    }
    #testModal.student-work-layout .test-mini-actions{
      display:grid;
      grid-template-columns:repeat(2,minmax(0,1fr));
    }
    #testModal.student-work-layout .test-mini-actions button{ width:100%; padding:0 5px; }
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
    #testModal .test-row[data-state="assigned"]{ background:#10b98118; border-color:#10b98170; }
    #testModal .test-row[data-state="done"]{ background:#2563eb18; border-color:#2563eb70; }
    #testModal .test-row[data-state="interrupted"]{ background:#f59e0b22; border-color:#f59e0b70; }
    #testModal .test-row[data-state="skip"]{ background:#ef444422; border-color:#ef444470; }
    #testModal .test-row.is-done{ background:#2563eb18; border-color:#2563eb70; }
    #testModal .test-row-main{ min-width:0; display:flex; flex-direction:column; gap:2px; }
    #testModal .test-row[data-selection="selected"]{ outline:2px solid #7c3aed; outline-offset:1px; }
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
    #testModal .test-row-statuses{ justify-self:end; display:flex; align-items:center; gap:5px; }
    #testModal .test-selection-status,
    #testModal .test-status{
      justify-self:end; padding:3px 7px; border-radius:999px; background:#f1f5f9; color:#334155;
      font-size:11px; font-weight:900; white-space:nowrap;
    }
    body.dark #testModal .test-status{ background:#1f2937; color:#cbd5e1; }
    #testModal .test-row[data-state="assigned"] .test-status{ background:#10b981; color:#fff; }
    #testModal .test-selection-status{ display:none; background:#7c3aed; color:#fff; }
    #testModal .test-row[data-selection="selected"] .test-selection-status{ display:inline-flex; }
    body.dark #testModal .test-selection-status{ background:#8b5cf6; color:#fff; }
    #testModal .test-row[data-state="done"] .test-status{ background:#2563eb; color:#fff; }
    #testModal .test-row[data-state="interrupted"] .test-status{ background:#f59e0b; color:#111827; }
    #testModal .test-row[data-state="skip"] .test-status{ background:#ef4444; color:#fff; }
    #testModal .test-row[data-state="none"] .test-status{ display:none; }
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
      #testModal .test-level-setting-options{ grid-template-columns:repeat(2,minmax(0,1fr)); }
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
          <input id="testAppendNotes" type="checkbox" hidden aria-hidden="true">
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
            <div class="test-field">
              <span class="test-field-label">학생 기본 레벨</span>
              <button id="testDifficultyOverride" class="test-override-btn" type="button" aria-pressed="false" title="학생별 기본 테스트 레벨을 설정">레벨 설정</button>
            </div>
          </div>

          <div id="testLevelSettingPanel" class="test-level-setting-panel" hidden>
            <div class="test-level-setting-head">
              <strong>학생별 기본 테스트 레벨</strong>
              <span id="testLevelSettingCurrent" class="test-sub"></span>
            </div>
            <div id="testLevelSettingOptions" class="test-level-setting-options"></div>
          </div>

          <div class="test-toolbar">
            <div class="test-toolbar-copy">
              <div class="test-sub">색상 표시된 항목이 오늘 선택 날짜에 배정됩니다.</div>
              <div id="testSelectionMeta" class="test-selection-meta" aria-live="polite">Ctrl+클릭으로 다중 선택 · ←/→로 상태 변경</div>
            </div>
            <div class="test-mini-actions">
              <button id="testPickAll" type="button">목록 전체 선택</button>
              <button id="testPickNone" type="button">선택 해제</button>
            </div>
          </div>
          <div id="testAssignList" class="test-list"></div>

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
  if ($('testModal')) { $('testModal').inert = false; $('testModal').removeAttribute('aria-busy'); }
  const title = $('testTitle');
  const meta = $('testStudentMeta');
  const count = $('testVisibleCount');
  const save = $('testSave');
  if (title) title.textContent = student ? `${student.name || ''} 테스트 배정` : '테스트 배정';
  if (meta) meta.textContent = '불러오는 중...';
  if (count) count.textContent = '';
  const selectionMeta = $('testSelectionMeta');
  if (selectionMeta) selectionMeta.textContent = '';
  if (save) {
    save.disabled = true;
    save.textContent = '저장';
    save.removeAttribute('aria-busy');
  }
  const tabs = $('testCategoryTabs');
  if (tabs) tabs.innerHTML = '<button type="button" class="test-tab is-active" disabled>불러오는 중</button>';
  ['testSubject', 'testDifficulty', 'testTerm', 'testRound'].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.disabled = true;
    el.innerHTML = '<option>불러오는 중</option>';
  });
  const overrideBtn = $('testDifficultyOverride');
  if (overrideBtn) {
    overrideBtn.disabled = true;
    overrideBtn.classList.remove('is-active');
    overrideBtn.setAttribute('aria-pressed', 'false');
  }
  levelSettingOpen = false;
  renderLevelSettingPanel();
  const list = $('testAssignList');
  if (list) list.innerHTML = '<div class="test-empty">테스트 목록을 불러오는 중...</div>';
}

function closeModal() {
  stopTestAssignmentDrag();
  testOpenSeq += 1;
  testModalReady = false;
  const wasUnified = $('testModal')?.classList.contains('student-work-layout');
  setModalOpen(false);
  editingSid = null;
  editingDate = null;
  activeStudent = null;
  activeCatalog = [];
  levelSettingOpen = false;
  catalogByKey = new Map();
  initialTestMap = {};
  selectedStatuses = new Map();
  explicitBlankKeys = new Set();
  multiSelectedKeys = new Set();
  touchedTestKeys = new Set();
  testChangeOrderByKey = {};
  pendingCenteredTestKey = '';
  testSelectionTouched = false;
  activeRound = '1';
  activeTerm = defaultTermFromSchoolCalendar();
  if (wasUnified && !document.querySelector('#vidModal.student-work-layout') && !document.querySelector('#logModal.student-work-layout')) {
    try { window.hideStudentPopupBackdrop?.(); } catch {}
  }
}

function firstInProgressAssignmentTest(categoryKey = '') {
  const targetCategory = String(categoryKey || '').trim();
  return activeCatalog.find(test =>
    (!targetCategory || test.categoryKey === targetCategory) &&
    normalizeSubject(test.curriculum) === normalizeSubject(activeSubject) &&
    !isSubmitted(test) &&
    isInProgressTestStatus(statusForKey(test._key))
  ) || null;
}

function chooseInitialCategory() {
  const activeTest = firstInProgressAssignmentTest();
  if (activeTest?.categoryKey) return activeTest.categoryKey;
  const hasUnit = activeCatalog.some(t =>
    t.categoryKey === 'UNIT' && normalizeSubject(t.curriculum) === normalizeSubject(activeSubject)
  );
  if (hasUnit) return 'UNIT';
  const hit = CATEGORY_KEYS.find(key => activeCatalog.some(t =>
    t.categoryKey === key && normalizeSubject(t.curriculum) === normalizeSubject(activeSubject)
  ));
  return hit || 'UNIT';
}

function activeStudentCurriculumSubject() {
  const rawSubject = String(activeStudent?.curriculum || '').trim();
  return rawSubject ? normalizeSubject(rawSubject) : '';
}

function recentTestViewStorageKey(sid = editingSid) {
  const normalizedSid = String(sid || '').trim();
  return normalizedSid
    ? `${TEST_RECENT_VIEW_STORAGE_PREFIX}:${encodeURIComponent(normalizedSid)}`
    : '';
}

function testViewFromTest(test) {
  if (!test) return null;
  const categoryKey = canonicalCategoryKey(test.categoryKey, test.categoryLabel);
  return {
    categoryKey,
    subject: normalizeSubject(test.curriculum),
    difficulty: String(test.difficulty || '').trim(),
    term: isTermCategory(categoryKey) ? normalizeTerm(test.term, test.name) : '',
    round: isUnitCategory(categoryKey) ? normalizeRound(test.round, test.name) : '',
  };
}

function currentTestView() {
  return {
    categoryKey: activeCategory,
    subject: activeSubject,
    difficulty: activeDifficulty,
    term: isTermCategory(activeCategory) ? activeTerm : '',
    round: isUnitCategory(activeCategory) ? activeRound : '',
  };
}

function testMatchesView(test, view) {
  if (!test || !view) return false;
  if (test.categoryKey !== view.categoryKey) return false;
  if (normalizeSubject(test.curriculum) !== normalizeSubject(view.subject)) return false;
  if (String(test.difficulty || '') !== String(view.difficulty || '')) return false;
  if (isTermCategory(view.categoryKey) && normalizeTerm(test.term, test.name) !== view.term) return false;
  if (isUnitCategory(view.categoryKey) && normalizeRound(test.round, test.name) !== view.round) return false;
  return true;
}

function normalizeRecentTestView(rawView, requiredSubject = '') {
  if (!rawView || typeof rawView !== 'object' || Array.isArray(rawView)) return null;
  const categoryKey = canonicalCategoryKey(rawView.categoryKey || rawView.category, rawView.categoryLabel);
  const rawSubject = String(rawView.subject || rawView.curriculum || '').trim();
  const difficulty = String(rawView.difficulty || '').trim();
  const difficulties = CATEGORY_BY_KEY[categoryKey]?.difficulties || [];
  if (!CATEGORY_BY_KEY[categoryKey] || !rawSubject || !difficulties.includes(difficulty)) return null;

  const subject = normalizeSubject(rawSubject);
  const curriculumSubject = String(requiredSubject || '').trim()
    ? normalizeSubject(requiredSubject)
    : '';
  if (curriculumSubject && subject !== curriculumSubject) return null;

  const candidate = {
    categoryKey,
    subject,
    difficulty,
    term: isTermCategory(categoryKey) ? normalizeTerm(rawView.term, '') : '',
    round: isUnitCategory(categoryKey) ? normalizeRound(rawView.round, '') : '',
  };
  const matchingTest = activeCatalog.find(test => testMatchesView(test, candidate));
  return matchingTest ? testViewFromTest(matchingTest) : null;
}

function readRecentTestView(sid = editingSid, requiredSubject = '') {
  const key = recentTestViewStorageKey(sid);
  if (!key) return null;
  try {
    return normalizeRecentTestView(JSON.parse(localStorage.getItem(key) || 'null'), requiredSubject);
  } catch {
    return null;
  }
}

function rememberCurrentTestView(test = null) {
  const key = recentTestViewStorageKey();
  if (!key) return;
  const curriculumSubject = activeStudentCurriculumSubject();
  const view = normalizeRecentTestView(
    test ? testViewFromTest(test) : currentTestView(),
    curriculumSubject,
  );
  if (!view) return;
  try {
    localStorage.setItem(key, JSON.stringify({ ...view, updatedAt: new Date().toISOString() }));
  } catch {}
}

function latestAssignmentTestFromHistory(requiredSubject = '', requiredCategory = '') {
  const curriculumSubject = String(requiredSubject || '').trim()
    ? normalizeSubject(requiredSubject)
    : '';
  const categoryKey = String(requiredCategory || '').trim()
    ? canonicalCategoryKey(requiredCategory)
    : '';
  const orderedKeys = Array.from(new Set([
    ...Object.keys(initialTestMap || {}),
    ...Array.from(selectedStatuses.keys()),
  ]));
  const candidates = [];

  orderedKeys.forEach((key, legacyIndex) => {
    const rawStatus = Object.prototype.hasOwnProperty.call(initialTestMap, key)
      ? initialTestMap[key]
      : selectedStatuses.get(key);
    const status = normalizeAssignmentStatus(rawStatus);
    if (isExplicitBlankTestStatus(rawStatus) || status === 'skip' || !status) return;
    const test = catalogByKey.get(key);
    if (
      test &&
      (!curriculumSubject || normalizeSubject(test.curriculum) === curriculumSubject) &&
      (!categoryKey || test.categoryKey === categoryKey)
    ) {
      const order = Number(testChangeOrderByKey?.[key]);
      candidates.push({
        test,
        order: Number.isFinite(order) && order > 0 ? order : 0,
        legacyIndex,
      });
    }
  });
  if (!candidates.length) return null;

  const hasExplicitOrder = candidates.some(candidate => candidate.order > 0);
  candidates.sort((left, right) => {
    if (hasExplicitOrder && right.order !== left.order) return right.order - left.order;
    if (
      hasExplicitOrder
      && left.order > 0
      && left.order === right.order
      && left.test.categoryKey !== right.test.categoryKey
    ) {
      if (left.test.categoryKey === 'UNIT') return -1;
      if (right.test.categoryKey === 'UNIT') return 1;
    }
    return right.legacyIndex - left.legacyIndex;
  });
  return candidates[0].test;
}

function applyTestView(view, requiredSubject = '') {
  if (!view) return false;
  const viewSubject = normalizeSubject(view.subject);
  const curriculumSubject = String(requiredSubject || '').trim()
    ? normalizeSubject(requiredSubject)
    : '';
  if (curriculumSubject && viewSubject !== curriculumSubject) return false;
  activeCategory = view.categoryKey;
  activeSubject = curriculumSubject || viewSubject;
  activeDifficulty = view.difficulty;
  if (isTermCategory(activeCategory)) activeTerm = view.term;
  activeRound = isUnitCategory(activeCategory) ? view.round : '';
  return true;
}

function restorePreferredInitialTestView(requiredSubject = activeStudentCurriculumSubject()) {
  const curriculumSubject = String(requiredSubject || '').trim()
    ? normalizeSubject(requiredSubject)
    : '';
  const recentAssignment = latestAssignmentTestFromHistory(curriculumSubject);
  if (recentAssignment) {
    applyTestView(testViewFromTest(recentAssignment), curriculumSubject);
    pendingCenteredTestKey = recentAssignment._key;
    return 'assignment';
  }

  const storedView = readRecentTestView(editingSid, curriculumSubject);
  if (storedView) {
    applyTestView(storedView, curriculumSubject);
    return 'stored';
  }
  return '';
}

function restorePreferredCategoryTestView(categoryKey, requiredSubject = activeSubject) {
  const targetCategory = canonicalCategoryKey(categoryKey);
  const subject = normalizeSubject(requiredSubject);
  const recentAssignment = latestAssignmentTestFromHistory(subject, targetCategory);
  if (recentAssignment) {
    applyTestView(testViewFromTest(recentAssignment), subject);
    pendingCenteredTestKey = recentAssignment._key;
    return 'assignment';
  }

  const storedView = readRecentTestView(editingSid, subject);
  if (storedView?.categoryKey === targetCategory) {
    applyTestView(storedView, subject);
    return 'stored';
  }
  return '';
}

async function openModalForRow(rowOrButton, opts = {}) {
  stopTestAssignmentDrag();
  ensureModal();
  const openSeq = ++testOpenSeq;
  testModalReady = false;

  const tr = rowOrButton?.closest?.('tr[data-sid]') || rowOrButton;
  editingSid = String(tr?.dataset?.sid || '').trim();
  editingDate = String(tr?.dataset?.date || getAdminDate()).trim();
  activeStudent = (state.students || []).find(stu => String(stu.id) === editingSid) || null;
  if (!editingSid || !activeStudent) {
    alert('학생 정보를 찾을 수 없습니다.');
    return;
  }

  const curriculumSubject = activeStudentCurriculumSubject();
  activeSubject = curriculumSubject || normalizeSubject(activeStudent.curriculum);
  renderLoadingState(activeStudent);
  levelSettingOpen = false;
  setModalOpen(true, opts.layout);
  const targetSid = editingSid;
  const targetDate = editingDate;
  const isCurrent = () => openSeq === testOpenSeq && editingSid === targetSid && editingDate === targetDate;
  try {
    const hydrated = await hydrateForTestPopup(targetDate, targetSid, isCurrent);
    if (!isCurrent() || hydrated === false) return;
  } catch (error) {
    if (!isCurrent()) return;
    const message = '시험 데이터를 불러오지 못했습니다. 닫은 뒤 다시 열어 주세요.';
    const meta = $('testStudentMeta');
    if (meta) meta.textContent = message;
    const list = $('testAssignList');
    if (list) list.textContent = message;
    toast(message);
    return;
  }
  activeTerm = defaultTermFromSchoolCalendar();
  syncSelectedFromProgress();

  if (!restorePreferredInitialTestView(curriculumSubject)) {
    activeCategory = chooseInitialCategory();
    applyRuleDefaults(activeCategory);
  }
  testSelectionTouched = false;

  renderAll();
  const subjectEl = $('testSubject');
  if (subjectEl) subjectEl.disabled = true;
  const difficultyEl = $('testDifficulty');
  if (difficultyEl) difficultyEl.disabled = false;
  const termEl = $('testTerm');
  const overrideBtn = $('testDifficultyOverride');
  if (overrideBtn) overrideBtn.disabled = false;
  if (termEl) termEl.disabled = !isTermCategory(activeCategory);
  const roundEl = $('testRound');
  if (roundEl) roundEl.disabled = !isUnitCategory(activeCategory);
  const save = $('testSave');
  testModalReady = true;
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

function isAssignmentNoteStatus(status) {
  const normalized = normalizeAssignmentStatus(status);
  return normalized === 'interrupted' || normalized === 'done';
}

export function shouldIncludeInAssignmentNote(item) {
  const rawStatus = item && Object.prototype.hasOwnProperty.call(item, 'status') ? item.status : 'assigned';
  return isAssignmentNoteStatus(rawStatus);
}

export function assignmentLabel(item) {
  return String(item?.label || '').trim();
}

function escapeRegExp(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function compactAssignmentCategoryLabel(item) {
  const categoryKey = String(item?.categoryKey || item?.category || '').trim();
  const label = String(item?.categoryLabel || categoryLabel(categoryKey) || '').replace(/\s+/g, '');
  return label || categoryKey;
}

function isIlsanGraphAssignmentItem(item) {
  const categoryKey = String(item?.categoryKey || item?.category || '').trim();
  return categoryKey === 'ILSAN_PAST' && isIlsanGraphDifficultyText(`${item?.difficulty || ''} ${item?.name || ''} ${item?.label || ''}`);
}

function assignmentRecordPrefix(item) {
  if (isIlsanGraphAssignmentItem(item)) return '일산기출(그래프부터)';
  const prefix = compactAssignmentCategoryLabel(item);
  const difficulty = String(item?.difficulty || '').trim();
  return prefix && difficulty ? `${prefix}(${difficulty})` : prefix;
}

function assignmentRecordName(item) {
  const label = assignmentLabel(item);
  let name = String(item?.name || '').trim();
  if (!name && label) {
    name = label.split('/').map(part => part.trim()).filter(Boolean).pop() || label;
  }
  if (isIlsanGraphAssignmentItem(item)) {
    name = name.replace(/^삼각함수\s*그래프\s*포함\s*/u, '').trim();
  }

  const round = roundLabel(item?.round);
  if (round) {
    name = name.replace(new RegExp(`^${escapeRegExp(round)}\\s*`, 'u'), '').trim();
  }
  const rawRound = String(item?.round || '').trim();
  if (rawRound && rawRound !== round) {
    name = name.replace(new RegExp(`^${escapeRegExp(rawRound)}\\s*회차\\s*`, 'u'), '').trim();
  }
  return name;
}

function assignmentRecordStatusLabel(status) {
  const normalized = normalizeAssignmentStatus(status) || 'assigned';
  if (normalized === 'done') return '완료';
  if (normalized === 'assigned' || normalized === 'interrupted') return '배부';
  return '';
}

function mergeAssignmentItemsByLabel(...groups) {
  const byLabel = new Map();
  groups.flat().forEach(item => {
    if (!item || typeof item !== 'object') return;
    const label = assignmentLabel(item);
    if (!label) return;
    byLabel.set(label, { ...(byLabel.get(label) || {}), ...item, label });
  });
  return Array.from(byLabel.values());
}

export function dailyAssignmentNoteItems(items, initialStatusMap = {}) {
  return (items || []).filter(item => {
    const current = normalizeAssignmentStatus(item?.status) || 'assigned';
    if (!isAssignmentNoteStatus(current)) return false;
    const previous = normalizeAssignmentStatus(initialStatusMap?.[assignmentLabel(item)]);
    if (current === 'done') return previous === 'assigned';
    return !isAssignmentNoteStatus(previous);
  });
}

export function buildAssignmentNote(items) {
  const noteItems = (items || []).filter(shouldIncludeInAssignmentNote);
  if (!noteItems.length) return '';
  const lines = noteItems.map(item => {
    if (!item) return '';
    const status = assignmentRecordStatusLabel(item.status);
    if (!status) return '';
    const parts = [
      assignmentRecordPrefix(item),
      roundLabel(item.round),
      assignmentRecordName(item),
    ].filter(Boolean);
    const body = parts.length ? parts.join(' ') : assignmentLabel(item);
    return body ? `${body} (${status})` : '';
  }).filter(Boolean);
  return lines.join('\n');
}

export function stripAssignmentNoteBlocks(notes) {
  return String(notes || '')
    .replace(/(?:^|\n+)\[테스트 배정\]\n(?:- [^\n]*(?:\n|$))+/g, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function replaceAssignmentNoteBlock(notes, previousBlock, nextBlock) {
  const current = String(notes || '').trimEnd();
  const previous = String(previousBlock || '').trim();
  const replacement = String(nextBlock || '').trim();
  if (!current) return replacement;

  let base = current;
  if (previous) {
    base = base.split(previous).join('');
  }
  base = stripAssignmentNoteBlocks(base);
  if (!replacement) return base;
  return `${base ? `${base}\n\n` : ''}${replacement}`.trim();
}

function buildLogAssignmentPatchBody(date, sid, patchEntry, clear, entry, notesChanged) {
  const body = {
    date,
    sid,
    entry: patchEntry,
  };
  if (clear.length) body.__clear = clear;
  if (notesChanged) {
    body.base = { notes: String(entry.notes || '').trim() };
  }
  return body;
}

async function fetchLatestLogEntryForAssignment(date, sid) {
  const q = new URLSearchParams({ date, sid }).toString();
  const latest = await fetchJSONSafe(`/api/logs/entry?${q}`);
  return latest?.entry && typeof latest.entry === 'object' ? latest.entry : {};
}

async function patchLogAssignment(items, appendToNotes, newlyAddedItems = [], latestEntry = null, date = editingDate, sid = editingSid) {
  const entry = latestEntry && typeof latestEntry === 'object'
    ? latestEntry
    : await fetchLatestLogEntryForAssignment(date, sid);
  const clear = [];
  const logItems = (items || []).filter(item => normalizeAssignmentStatus(item?.status) !== 'skip');
  const currentItemsByLabel = new Map(logItems.map(item => [assignmentLabel(item), item]).filter(([label]) => label));
  const currentLabels = new Set(currentItemsByLabel.keys());
  const previousDailyItems = Array.isArray(entry?.[TEST_ASSIGN_DAILY_ITEMS_KEY])
    ? entry[TEST_ASSIGN_DAILY_ITEMS_KEY].map(item => {
      const label = assignmentLabel(item);
      const currentItem = currentItemsByLabel.get(label);
      const currentStatus = normalizeAssignmentStatus(currentItem?.status) || 'assigned';
      if (!currentItem || !isAssignmentNoteStatus(currentStatus)) return null;
      return { ...item, ...currentItem, label, status: currentStatus, statusLabel: testStatusLabel(currentStatus) };
    }).filter(Boolean)
    : [];
  const dailyItems = mergeAssignmentItemsByLabel(previousDailyItems, newlyAddedItems)
    .filter(item => currentLabels.has(assignmentLabel(item)))
    .filter(shouldIncludeInAssignmentNote);
  const patchEntry = {
    updatedAt: new Date().toISOString(),
  };
  if (logItems.length) patchEntry.assignedTests = logItems;
  else clear.push('assignedTests');

  const noteBlock = buildAssignmentNote(dailyItems);
  if (dailyItems.length) {
    patchEntry[TEST_ASSIGN_DAILY_ITEMS_KEY] = dailyItems;
    patchEntry.testAssignmentNote = noteBlock;
  } else {
    clear.push(TEST_ASSIGN_DAILY_ITEMS_KEY, 'testAssignmentNote');
  }

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

  const body = buildLogAssignmentPatchBody(date, sid, patchEntry, clear, entry, notesChanged);

  const saved = await fetchJSONSafe('/api/logs/patch', {
    method: 'POST',
    headers: CT,
    body: JSON.stringify(body),
  });

  if (saved?.entry && typeof saved.entry === 'object') {
    state.logs = state.logs || {};
    state.logs[date] = state.logs[date] || {};
    state.logs[date][sid] = saved.entry;
    window.logs = state.logs;
  }
}

function collectTestStatusPatch() {
  const patchTests = {};
  const allKeys = new Set([...Object.keys(initialTestMap), ...selectedStatuses.keys(), ...explicitBlankKeys]);
  allKeys.forEach(key => {
    const test = catalogByKey.get(key);
    if (test && isSubmitted(test)) {
      patchTests[key] = 'done';
    } else if (explicitBlankKeys.has(key)) {
      patchTests[key] = { status: 'none', explicitBlank: true };
    } else {
      patchTests[key] = statusForKey(key) || '';
    }
  });
  return patchTests;
}

function hasAnyAssignedTestStatus(patchTests) {
  return Object.values(patchTests || {}).some(status => !!normalizeAssignmentStatus(status));
}

function ensureProgressEntryForTestSave(date, sid) {
  state.progress = state.progress || {};
  state.progress[date] = state.progress[date] || {};
  state.progress[date][sid] = state.progress[date][sid] || {};
  return state.progress[date][sid];
}

function buildTestProgressPatchBody(date, sid, patchTests, hasAnyTestStatus) {
  const touchedKeys = Array.from(touchedTestKeys).filter(key =>
    Object.prototype.hasOwnProperty.call(patchTests || {}, key)
  );
  return {
    date,
    sid,
    progress: {
      tests: patchTests,
      [TEST_ASSIGN_CLEAR_KEY]: hasAnyTestStatus ? '' : new Date().toISOString(),
      ...(touchedKeys.length ? { [TEST_ASSIGN_TOUCHED_KEYS_KEY]: touchedKeys } : {}),
    },
  };
}

function applyTestProgressPatchResult(date, sid, progressRes) {
  if (progressRes?.progress && typeof progressRes.progress === 'object') {
    state.progress = state.progress || {};
    state.progress[date] = state.progress[date] || {};
    state.progress[date][sid] = progressRes.progress;
    window.progressData = state.progress;
  }
}

function showTestSaveSuccess() {
  if (typeof window.showStudentPopupSaveResult === 'function') {
    window.showStudentPopupSaveResult('저장 완료');
  } else {
    toast('저장 완료');
  }
}

async function saveModal(options = {}) {
  stopTestAssignmentDrag();
  if (!editingSid || !editingDate) return [];
  if (!testModalReady) throw new Error('시험 데이터를 불러온 뒤 저장해 주세요.');
  const sid = editingSid;
  const date = editingDate;
  const seq = testOpenSeq;
  const flightKey = JSON.stringify([seq, date, sid]);
  if (testSaveFlights.has(flightKey)) return testSaveFlights.get(flightKey);
  if (!testSelectionTouched) {
    const items = selectedAssignmentObjects();
    if (options.showPopup !== false) showTestSaveSuccess();
    return items;
  }

  const patchTests = collectTestStatusPatch();
  const hasAnyTestStatus = hasAnyAssignedTestStatus(patchTests);
  const items = selectedAssignmentObjects();
  const newlyAddedItems = dailyAssignmentNoteItems(items, initialTestMap);
  const appendToNotes = Boolean($('testAppendNotes')?.checked);
  // Freeze the complete command, including touched keys, before the first await.
  const progressBody = JSON.stringify(buildTestProgressPatchBody(date, sid, patchTests, hasAnyTestStatus));
  const stillCurrent = () => testOpenSeq === seq && editingSid === sid && editingDate === date;
  const modal = $('testModal');
  const save = $('testSave');
  const saveCaption = save?.textContent;
  const saveWasDisabled = Boolean(save?.disabled);
  if (save) {
    save.textContent = '저장 중…';
    save.disabled = true;
    save.setAttribute('aria-busy', 'true');
  }
  if (modal) { modal.inert = true; modal.setAttribute('aria-busy', 'true'); }
  const flight = (async () => {
    let progressSaved = false;
    try {
      const latestLogEntry = await fetchLatestLogEntryForAssignment(date, sid);
      ensureProgressEntryForTestSave(date, sid);
      const progressRes = await fetchJSONSafe('/api/progress/patch', {
        method: 'POST', headers: CT, body: progressBody,
      });
      progressSaved = true;
      applyTestProgressPatchResult(date, sid, progressRes);
      invalidateStudentWorkFetchCache(`/api/progress?sid=${encodeURIComponent(sid)}`);
      window.invalidateVideoAssignmentPopupCache?.(date, sid);
      await patchLogAssignment(items, appendToNotes, newlyAddedItems, latestLogEntry, date, sid);
      if (stillCurrent()) {
        initialTestMap = { ...getCurrentProgressTests() };
        testChangeOrderByKey = currentTestChangeOrderMap();
        touchedTestKeys = new Set();
        testSelectionTouched = false;
        if (options.showPopup !== false) showTestSaveSuccess();
      }
      if (options.refresh !== false) document.dispatchEvent(new CustomEvent('admin:refresh'));
      return items;
    } catch (error) {
      if (progressSaved) throw new Error(`테스트 상태는 저장됐지만 상담 기록 저장에 실패했습니다. 다시 저장해 주세요. ${error?.message || ''}`);
      throw error;
    } finally {
      invalidateStudentWorkFetchCache(`/api/logs?sid=${encodeURIComponent(sid)}`);
      window.invalidateVideoAssignmentPopupCache?.(date, sid);
      if (stillCurrent() && modal) { modal.inert = false; modal.removeAttribute('aria-busy'); }
      if (stillCurrent() && save) {
        save.textContent = saveCaption;
        save.disabled = saveWasDisabled;
        save.removeAttribute('aria-busy');
      }
      testSaveFlights.delete(flightKey);
    }
  })();
  testSaveFlights.set(flightKey, flight);
  return flight;
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
  let suppressContextOnce = false;
  let dragRows = [];
  let dragInitialStatuses = [];
  let lastDragIndex = -1;
  let dragAutoScroll = null;
  let dragOpenSeq = 0;

  function finishDrag(cancelled = false) {
    dragAutoScroll?.stop();
    if (!cancelled && pointerDown && dragActive) {
      if (dragButton === 0) suppressClickOnce = true;
      if (dragButton === 2) suppressContextOnce = true;
    }
    if (cancelled) suppressClickOnce = suppressContextOnce = false;
    pointerDown = dragActive = false;
    dragTarget = null;
    dragButton = 0;
    startStatus = '';
    startIndex = lastDragIndex = -1;
    dragRows = [];
    dragInitialStatuses = [];
  }
  stopTestAssignmentDrag = () => finishDrag(true);

  const testRowFromTarget = (target) => target?.closest?.('#testAssignList .test-row');
  const rebuildDragRows = () => {
    dragRows = Array.from(document.querySelectorAll('#testAssignList .test-row:not(:disabled)'));
    dragInitialStatuses = dragRows.map(row => statusForKey(row.dataset.testKey));
    lastDragIndex = -1;
  };

  function applyDragRange(currentRow) {
    if (!pointerDown || !dragActive) return;
    const curIndex = dragRows.indexOf(currentRow);
    if (curIndex === -1 || startIndex === -1) return;
    if (curIndex === lastDragIndex) return;
    lastDragIndex = curIndex;

    const lo = Math.min(startIndex, curIndex);
    const hi = Math.max(startIndex, curIndex);
    let lastViewRow = null;
    dragRows.forEach((row, idx) => {
      const initial = dragInitialStatuses[idx] || '';
      const inRange = idx >= lo && idx <= hi;
      const next = inRange ? dragTarget : initial;
      applyTestRowStatus(row, next, { touch: inRange, remember: false });
      if (!row.disabled && row.dataset.testKey) lastViewRow = row;
    });
    if (lastViewRow) rememberCurrentTestView(catalogByKey.get(lastViewRow.dataset.testKey));
  }

  function handleDragMove(e) {
    if (!pointerDown) return;
    if (e.type === 'mousemove' && typeof e.buttons === 'number' && !(e.buttons & (dragButton === 2 ? 2 : 1))) {
      finishDrag();
      return;
    }
    const hit = testRowFromTarget(e.target);
    if (dragActive && (!hit || hit.disabled)) return;
    const row = hit && !hit.disabled ? hit : dragRows[startIndex];
    if (!row) return;

    if (!dragActive) {
      dragActive = true;
      dragTarget = dragButton === 2 ? nextExcludedStatusOf(startStatus) : nextStatusOf(startStatus);
      dragAutoScroll ||= createAssignmentDragAutoScroll({
        rowSelector: '#testAssignList .test-row:not(:disabled)',
        scrollerForRow: row => row.closest('#testAssignList'),
        isActive: () => pointerDown && dragActive && dragOpenSeq === testOpenSeq && dragRows[startIndex]?.isConnected,
        onRow: row => { applyDragRange(row); testSelectionTouched = true; },
        onStop: () => finishDrag(),
      });
      dragAutoScroll.start(e, row, dragButton);
    }
    applyDragRange(row);
    testSelectionTouched = true;
    e.preventDefault();
  }

  document.body.addEventListener('click', async (e) => {
    const levelSettingButton = e.target.closest('#testDifficultyOverride');
    if (levelSettingButton) {
      levelSettingOpen = !levelSettingOpen;
      syncLevelSettingButton();
      renderLevelSettingPanel();
      return;
    }

    const levelOption = e.target.closest('#testLevelSettingOptions [data-test-level-setting]');
    if (levelOption) {
      const difficulty = String(levelOption.dataset.testLevelSetting || '').trim();
      const levels = CATEGORY_BY_KEY[STUDENT_LEVEL_SETTING_CATEGORY]?.difficulties || [];
      if (!levels.includes(difficulty)) return;

      const settingOpenSeq = testOpenSeq;
      const optionsHost = $('testLevelSettingOptions');
      optionsHost?.querySelectorAll('button').forEach(button => { button.disabled = true; });
      try {
        await saveStudentTestLevelDefault(STUDENT_LEVEL_SETTING_CATEGORY, activeSubject, difficulty);
        if (settingOpenSeq !== testOpenSeq) return;
        levelSettingOpen = false;
        syncLevelSettingButton();
        renderLevelSettingPanel();
        toast(`학생별 기본 테스트 레벨을 ${difficulty}로 저장했습니다.`);
      } catch (error) {
        if (settingOpenSeq !== testOpenSeq) return;
        console.error(error);
        toast('학생별 기본 테스트 레벨 저장에 실패했습니다.');
        renderLevelSettingPanel();
      } finally {
        if (settingOpenSeq === testOpenSeq && levelSettingOpen) {
          $('testLevelSettingOptions')?.querySelectorAll('button').forEach(button => {
            button.disabled = false;
          });
        }
      }
      return;
    }

    const categoryBtn = e.target.closest('#testCategoryTabs .test-tab');
    if (categoryBtn) {
      activeCategory = categoryBtn.dataset.category || activeCategory;
      levelSettingOpen = false;
      clearMultiSelection();
      if (!restorePreferredCategoryTestView(activeCategory, activeSubject)) {
        applyRuleDefaults(activeCategory);
      }
      rememberCurrentTestView();
      renderAll();
      return;
    }

    if (e.target.closest('#testPickAll')) {
      visibleTests().forEach(test => {
        if (!isSubmitted(test)) {
          setTestStatus(test._key, 'assigned');
          markTestTouched(test._key);
        }
      });
      rememberCurrentTestView();
      testSelectionTouched = true;
      renderList();
      return;
    }

    if (e.target.closest('#testPickNone')) {
      visibleTests().forEach(test => {
        if (!isSubmitted(test)) {
          setTestStatus(test._key, 'skip');
          markTestTouched(test._key);
        }
      });
      rememberCurrentTestView();
      testSelectionTouched = true;
      renderList();
      return;
    }

    if (e.target.closest('#testSave')) {
      try {
        await saveModal();
      } catch (err) {
        console.error(err);
        if (typeof window.showStudentPopupSaveResult === 'function') {
          window.showStudentPopupSaveResult('저장 실패', true);
        }
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
      if (e.ctrlKey || e.metaKey) {
        toggleMultiSelection(row);
        return;
      }
      if (suppressClickOnce) {
        suppressClickOnce = false;
        return;
      }
      const key = row.dataset.testKey || '';
      lastDragIndex = -1;
      applyTestRowStatus(row, nextStatusOf(statusForKey(key)));
      testSelectionTouched = true;
    }
  });

  document.body.addEventListener('mousedown', (e) => {
    if (e.button !== 0 && e.button !== 2) return;
    finishDrag(true);
    const row = testRowFromTarget(e.target);
    if (!row || row.disabled) return;
    if (e.ctrlKey || e.metaKey) return;
    if (e.button === 2) e.preventDefault();

    rebuildDragRows();
    startIndex = dragRows.indexOf(row);
    if (startIndex === -1) return;

    pointerDown = true;
    dragOpenSeq = testOpenSeq;
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
    if (suppressContextOnce) {
      suppressContextOnce = false;
      return;
    }
    const key = row.dataset.testKey || '';
    lastDragIndex = -1;
    applyTestRowStatus(row, nextExcludedStatusOf(statusForKey(key)));
    testSelectionTouched = true;
  });

  document.addEventListener('mouseup', () => {
    finishDrag();
  });

  document.body.addEventListener('change', (e) => {
    if (e.target?.id === 'testSubject') {
      activeSubject = activeStudentCurriculumSubject();
      e.target.value = activeSubject;
      return;
    }

    if (e.target?.id === 'testDifficulty') {
      activeDifficulty = e.target.value || activeDifficulty;
      clearMultiSelection();
      activeRound = defaultRoundFor(activeCategory, activeSubject, activeDifficulty);
      rememberCurrentTestView();
      renderAll();
      return;
    }

    if (e.target?.id === 'testTerm') {
      activeTerm = TERM_OPTIONS.includes(e.target.value) ? e.target.value : defaultTermFromSchoolCalendar();
      clearMultiSelection();
      rememberCurrentTestView();
      renderList();
      return;
    }

    if (e.target?.id === 'testRound') {
      activeRound = String(e.target.value || '1');
      clearMultiSelection();
      rememberCurrentTestView();
      renderList();
    }
  });

  document.body.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const modal = $('testModal');
    if (!modal || modal.style.display === 'none' || !multiSelectedKeys.size) return;
    if (!modal.contains(document.activeElement)) return;
    if (document.activeElement?.matches?.('#testModal select, #testModal input, #testModal textarea, #testModal button:not(.test-row), [contenteditable="true"]')) return;

    if (applyKeyboardStatusToSelection(e.key === 'ArrowRight' ? 1 : -1)) {
      lastDragIndex = -1;
      e.preventDefault();
      e.stopPropagation();
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
  window.prefetchTestAssignmentPopupForRow = prefetchTestModalDataForRow;
  window.closeTestAssignmentPopup = closeModal;
  window.saveTestAssignmentPopup = saveModal;
  window._openTest = (sid) => {
    const row = document.querySelector(`tr[data-sid="${CSS.escape(String(sid))}"]`);
    if (row) return openModalForRow(row);
    return openModalForRow({ dataset: { sid: String(sid), date: getAdminDate() }, closest: () => null });
  };
}
