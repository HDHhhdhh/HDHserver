// /js/tests.js
// Test catalog management for admin `/tests`.
/* global fetch */

import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from './shared/search.js';
import { createUnitTestDisplayNameResolver } from './shared/testCatalogDisplay.js';
import {
  CATEGORY_BY_KEY,
  CATEGORY_DEFS,
  ILSAN_GRAPH_DIFFICULTY,
  STUDENT_LEVELS,
  SUBJECTS,
  TERM_OPTIONS,
  canonText,
  captureCatalogMutationSnapshot,
  catalogGroupKey,
  categoryKeyFrom,
  categoryLabel,
  ensureConfig,
  isPastCategory,
  isUnitCategory,
  normalizeCatalogTest,
  normalizeDifficulty,
  normalizeRevision,
  normalizeRound,
  normalizeSubject,
  normalizeTerm,
  projectCatalogOrderBlock,
  roundLabel,
  roundSortValue,
  termSortValue,
  testDefinitionWriteRequest,
  visibleCatalogTests,
  wholeConfigWriteRequest,
} from './tests/catalogState.js?v=20260829-catalog-state-r1';
import {
  ANSWER_MODE_OPTIONS,
  answerKeyFromCsvRow,
  answerKeysToText,
  answerModeConsistencyIssue,
  answerModeSummary,
  answerModesForTest,
  answerModesFromCsvRow,
  buildTestCatalogCsvTemplate,
  csvAnswerRounds,
  hasRoundAnswerColumns,
  headerKey,
  normalizeAnswerMode,
  parseCsv,
  projectAnswerRound,
  rowObject,
} from './tests/catalogEditorState.js?v=20260829-catalog-editor-state-r1';
import {
  formatPercent,
  projectStatsDetail,
  projectStatsRows,
  projectStatsSummary,
  statForTest,
} from './tests/catalogStatisticsState.js?v=20260829-catalog-statistics-state-r1';

const $ = (sel) => document.querySelector(sel);
const MISSING_ANSWER_LINK_STATUS = 'missing';

let TEST_CFG = { categories: {} };
let TEST_CFG_REVISION = '';
let TEST_STATS = null;
let TEST_STATS_DETAIL = null;
let statsLoadVersion = 0;
let ruleSaveTimer = null;
let ruleSaveInFlight = false;
let ruleSavePending = false;
let ruleSaveToastTimer = null;
let catalogOrderSaveInFlight = false;
let catalogMutationSaveInFlight = false;
let catalogOrderFeedback = null;
let draggedCatalogIndex = null;
const ui = {
  category: 'UNIT',
  subject: '공수1',
  difficulty: '',
  term: '',
  round: '',
  catalogSearch: '',
  selectedId: '',
  statsCategory: 'UNIT',
  statsTestId: '',
  statsSearch: '',
  statsSort: 'default',
};

async function fetchJSONSafe(url, init = {}) {
  const res = await fetch(url, { cache: 'no-store', ...init });
  const body = await res.text();
  if (!res.ok) throw new Error(`[tests] ${init.method || 'GET'} ${url} -> ${res.status}\n${body.slice(0, 500)}`);
  try { return body.trim() ? JSON.parse(body) : {}; }
  catch (e) { throw new Error(`[tests] Bad JSON from ${url}: ${e?.message}\n${body.slice(0, 500)}`); }
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

function escapeAttr(s) {
  return escapeHtml(s).replace(/"/g, '&quot;');
}


function editCategoryValue() {
  return categoryKeyFrom($('#cfgEditType')?.value || ui.category || 'UNIT');
}

function roundHelpText(categoryKey) {
  if (String(categoryKey || '') === 'TRAINING_PACK') {
    return '트레이닝팩은 같은 단원 안의 세트 번호를 1회차, 2회차로 구분합니다.';
  }
  return isUnitCategory(categoryKey)
    ? '단원평가는 같은 이름의 시험을 다른 문제로 반복하는 세트 번호입니다.'
    : '복습테스트와 기출은 학생이 순서대로 보게 되는 시험 목록 순번입니다.';
}

function normalizeTest(rawTest, rawCategoryKey, idx = 0) {
  return normalizeCatalogTest(rawTest, rawCategoryKey, idx, {
    fallbackSubject: ui.subject,
    now: Date.now(),
  });
}

function getCategoryTests(categoryKey = ui.category) {
  const cat = TEST_CFG.categories?.[categoryKey];
  if (!cat || !Array.isArray(cat.tests)) return [];
  return cat.tests.map((test, idx) => normalizeTest(test, categoryKey, idx));
}

function displayTestName(test) {
  return createUnitTestDisplayNameResolver(getCategoryTests('UNIT'))(test);
}

function getVisibleTests() {
  const displayNameFor = createUnitTestDisplayNameResolver(getCategoryTests('UNIT'));
  return visibleCatalogTests(getCategoryTests(ui.category), ui, {
    displayNameFor,
    matchesSearchKey,
    searchKeyForText,
  });
}

async function fetchTestsConfig() {
  const res = await fetch('/api/tests-config', { cache: 'no-store' });
  const body = await res.text();
  if (!res.ok) throw new Error(`[tests] GET /api/tests-config -> ${res.status}\n${body.slice(0, 500)}`);
  TEST_CFG_REVISION = normalizeRevision(res.headers?.get?.('X-Tests-Config-Revision'));
  try { return body.trim() ? JSON.parse(body) : {}; }
  catch (e) { throw new Error(`[tests] Bad JSON from /api/tests-config: ${e?.message}\n${body.slice(0, 500)}`); }
}

function selectedTestRef() {
  const selectedId = String(ui.selectedId || '');
  if (!selectedId) return null;
  for (const def of CATEGORY_DEFS) {
    const cat = TEST_CFG.categories?.[def.key];
    if (!cat || !Array.isArray(cat.tests)) continue;
    const test = cat.tests.find(item => String(item?.id) === selectedId);
    if (test) return { categoryKey: def.key, cat, test };
  }
  return null;
}

function currentAnswerModes(problems) {
  const total = Math.max(0, Number(problems ?? $('#cfgProblems')?.value ?? 0) || 0);
  const values = Array.from(document.querySelectorAll('#cfgAnswerModes select[data-question-no]'))
    .slice(0, total)
    .map(select => normalizeAnswerMode(select.value));
  while (values.length < total) values.push('');
  return values;
}

function updateAnswerModeSummary(modes = currentAnswerModes()) {
  const summary = $('#cfgAnswerModeSummary');
  if (!summary) return;
  summary.textContent = answerModeSummary(modes).text;
}

function renderAnswerModeEditor(test = selectedTestRef()?.test || null, seedModes = null) {
  const host = $('#cfgAnswerModes');
  if (!host) return;
  const problems = Math.max(0, Number($('#cfgProblems')?.value || test?.problems || 0) || 0);
  const round = String($('#cfgRound')?.value || test?.round || '1').trim() || '1';
  const modes = Array.isArray(seedModes)
    ? answerModesForTest({ answerModes: seedModes, problems, round }, problems, round)
    : answerModesForTest(test, problems, round);
  if (!problems) {
    host.innerHTML = '<div class="answer-mode-empty">문항 수를 입력하면 유형 편집기가 표시됩니다.</div>';
    updateAnswerModeSummary([]);
    return;
  }
  host.innerHTML = modes.map((mode, index) => `
    <div class="answer-mode-row">
      <label for="cfgAnswerMode${index + 1}">${index + 1}번</label>
      <select id="cfgAnswerMode${index + 1}" data-question-no="${index + 1}">
        ${ANSWER_MODE_OPTIONS.map(option => `<option value="${option.value}"${option.value === mode ? ' selected' : ''}>${option.label}</option>`).join('')}
      </select>
    </div>
  `).join('');
  updateAnswerModeSummary(modes);
}

function updateDifficultyOptions(categoryKey = editCategoryValue()) {
  const sel = $('#cfgDifficulty');
  if (!sel) return;
  const def = CATEGORY_BY_KEY[categoryKeyFrom(categoryKey)] || CATEGORY_BY_KEY.UNIT;
  const current = sel.value;
  sel.innerHTML = def.difficulties.map(diff => `<option value="${escapeAttr(diff)}">${escapeHtml(diff)}</option>`).join('');
  sel.value = def.difficulties.includes(current) ? current : (def.difficulties[0] || '');
  const help = $('#cfgRoundHelp');
  if (help) help.textContent = roundHelpText(def.key);
}

function updateListDifficultyOptions() {
  const sel = $('#cfgDifficultyFilter');
  if (!sel) return;
  const def = CATEGORY_BY_KEY[ui.category] || CATEGORY_BY_KEY.UNIT;
  const difficulties = def.difficulties || [];
  if (!difficulties.includes(ui.difficulty)) ui.difficulty = difficulties[0] || '';
  sel.innerHTML = difficulties.map(diff => `<option value="${escapeAttr(diff)}">${escapeHtml(diff)}</option>`).join('');
  sel.value = ui.difficulty;
}

function catalogOrderBlock() {
  return projectCatalogOrderBlock({
    catalogOrderSaveInFlight,
    catalogMutationSaveInFlight,
    ruleSaveTimer,
    ruleSaveInFlight,
    ruleSavePending,
    catalogSearch: ui.catalogSearch,
    category: ui.category,
    term: ui.term,
    round: ui.round,
  });
}

function canReorderCatalog() {
  return !catalogOrderBlock();
}

function clearCatalogOrderFeedback() {
  catalogOrderFeedback = null;
}

function catalogMutationControlsLocked() {
  if (!catalogOrderSaveInFlight && !catalogMutationSaveInFlight) return false;
  updateCatalogOrderHint();
  return true;
}

function beginCatalogMutationSave() {
  if (catalogMutationControlsLocked()) return false;
  if (ruleSaveTimer || ruleSaveInFlight || ruleSavePending) {
    catalogOrderFeedback = { kind: 'saving', message: '배정 기준 저장이 끝난 뒤 시험 설정을 저장해주세요.' };
    updateCatalogOrderHint();
    return false;
  }
  catalogMutationSaveInFlight = true;
  syncCatalogMutationControls();
  updateCatalogOrderHint();
  return true;
}

function endCatalogMutationSave() {
  catalogMutationSaveInFlight = false;
  renderTestList();
  flushDeferredRuleSave();
}

function syncCatalogSearchControl() {
  const input = $('#cfgCatalogSearch');
  if (!input) return;
  applySearchPlaceholder(input, '시험명, ID, 과목, 난이도 검색');
  if (input.value !== ui.catalogSearch) input.value = ui.catalogSearch;
}

function setCatalogOrderControlLock(control, locked) {
  if (!control) return;
  if (locked) {
    if (!Object.prototype.hasOwnProperty.call(control.dataset, 'catalogOrderWasDisabled')) {
      control.dataset.catalogOrderWasDisabled = control.disabled ? 'true' : 'false';
    }
    control.disabled = true;
    return;
  }
  if (!Object.prototype.hasOwnProperty.call(control.dataset, 'catalogOrderWasDisabled')) return;
  control.disabled = control.dataset.catalogOrderWasDisabled === 'true';
  delete control.dataset.catalogOrderWasDisabled;
}

function syncCatalogMutationControls() {
  const locked = catalogOrderSaveInFlight || catalogMutationSaveInFlight;
  [
    '#cfgType', '#cfgCur', '#cfgDifficultyFilter', '#cfgTermFilter', '#cfgRoundFilter', '#cfgCatalogSearch',
    '#cfgEditType', '#cfgSubject', '#cfgDifficulty', '#cfgTerm', '#cfgRound', '#cfgName', '#cfgProblems', '#cfgAnswers',
    '#btnImportCsv', '#csvFile', '#btnNewTest', '#btnSaveTest', '#btnDeleteTest',
    '#btnReloadStats', '#statRecent',
  ].forEach(selector => setCatalogOrderControlLock($(selector), locked));
  document.querySelectorAll('.rule-check').forEach(control => setCatalogOrderControlLock(control, locked));
}

function updateCatalogOrderHint() {
  const hint = $('#catalogOrderHint');
  if (!hint) return;
  const block = catalogOrderBlock();
  const status = block || catalogOrderFeedback || {
    kind: 'ready',
    message: '같은 그룹 안에서 드래그하거나 위·아래 버튼을 눌러 순서를 변경할 수 있습니다.',
  };
  hint.textContent = status.message;
  hint.dataset.kind = status.kind;
}

function availableRounds() {
  const rounds = new Set();
  getCategoryTests(ui.category)
    .filter(test => normalizeSubject(test.curriculum) === ui.subject)
    .filter(test => !ui.difficulty || String(test.difficulty || '') === String(ui.difficulty))
    .forEach(test => {
      const round = String(test.round || '').trim();
      if (round) rounds.add(round);
    });
  return Array.from(rounds).sort((a, b) => roundSortValue(a) - roundSortValue(b) || String(a).localeCompare(String(b), 'ko'));
}

function nextRoundFor(categoryKey, subject, difficulty) {
  const rounds = getCategoryTests(categoryKey)
    .filter(test => normalizeSubject(test.curriculum) === normalizeSubject(subject))
    .filter(test => !difficulty || String(test.difficulty || '') === String(difficulty))
    .map(test => roundSortValue(test.round || 0))
    .filter(value => Number.isFinite(value) && value < 9999);
  const maxRound = rounds.length ? Math.max(...rounds) : 0;
  return String(maxRound + 1);
}

function updateRoundOptions() {
  const sel = $('#cfgRoundFilter');
  if (!sel) return;
  if (!isUnitCategory(ui.category)) {
    ui.round = '';
    sel.disabled = true;
    sel.innerHTML = '<option value="">전체 순번</option>';
    sel.value = '';
    return;
  }
  sel.disabled = false;
  const rounds = availableRounds();
  if (ui.round && !rounds.includes(ui.round)) ui.round = '';
  sel.innerHTML = [
    '<option value="">전체 회차</option>',
    ...rounds.map(round => `<option value="${escapeAttr(round)}">${escapeHtml(roundLabel(round))}</option>`),
  ].join('');
  sel.value = ui.round;
}

function availableTerms() {
  const terms = new Set();
  getCategoryTests(ui.category)
    .filter(test => normalizeSubject(test.curriculum) === ui.subject)
    .filter(test => !ui.difficulty || String(test.difficulty || '') === String(ui.difficulty))
    .forEach(test => {
      const term = normalizeTerm(test.term || '', test.name);
      if (term) terms.add(term);
    });
  const out = TERM_OPTIONS.filter(term => terms.has(term));
  return out.length ? out : TERM_OPTIONS.slice();
}

function updateTermOptions() {
  const group = $('#cfgTermFilterGroup');
  const sel = $('#cfgTermFilter');
  if (!group || !sel) return;
  if (!isPastCategory(ui.category)) {
    ui.term = '';
    group.hidden = true;
    sel.disabled = true;
    sel.innerHTML = '<option value="">전체 고사</option>';
    sel.value = '';
    return;
  }
  group.hidden = false;
  sel.disabled = false;
  const terms = availableTerms();
  if (ui.term && !terms.includes(ui.term)) ui.term = '';
  sel.innerHTML = [
    '<option value="">전체 고사</option>',
    ...terms.map(term => `<option value="${escapeAttr(term)}">${escapeHtml(term)}</option>`),
  ].join('');
  sel.value = ui.term;
}

function updateSubjectOptions() {
  const editor = $('#cfgSubject');
  if (editor) {
    editor.innerHTML = SUBJECTS.map(subject => `<option value="${escapeAttr(subject)}">${escapeHtml(subject)}</option>`).join('');
  }
}

function updateEditCategoryOptions(selectedKey = editCategoryValue()) {
  const sel = $('#cfgEditType');
  if (!sel) return;
  const key = categoryKeyFrom(selectedKey);
  sel.innerHTML = CATEGORY_DEFS.map(def =>
    `<option value="${escapeAttr(def.key)}">${escapeHtml(def.label)}</option>`
  ).join('');
  sel.value = CATEGORY_BY_KEY[key] ? key : ui.category;
  updateDifficultyOptions(sel.value);
  updateEditTermOptions(sel.value);
}

function updateEditTermOptions(categoryKey = editCategoryValue()) {
  const row = $('#cfgTermRow');
  const sel = $('#cfgTerm');
  if (!row || !sel) return;
  const show = isPastCategory(categoryKey);
  row.hidden = !show;
  sel.disabled = !show;
  sel.innerHTML = TERM_OPTIONS.map(term => `<option value="${escapeAttr(term)}">${escapeHtml(term)}</option>`).join('');
  if (!TERM_OPTIONS.includes(sel.value)) sel.value = TERM_OPTIONS[0] || '';
}

function updateChrome(selected = null, displayNameFor = displayTestName) {
  const visible = getVisibleTests();
  const total = CATEGORY_DEFS.reduce((sum, def) => sum + getCategoryTests(def.key).length, 0);
  const scope = [
    categoryLabel(ui.category),
    ui.subject,
    ui.difficulty || '난이도 전체',
    isPastCategory(ui.category) ? (ui.term || '전체 고사') : '',
    isUnitCategory(ui.category) ? (ui.round ? roundLabel(ui.round) : '전체 회차') : '전체 순번',
  ].filter(Boolean).join(' · ');

  if ($('#testsTotalPill')) $('#testsTotalPill').textContent = `${total}개`;
  if ($('#testsScopeLabel')) $('#testsScopeLabel').textContent = scope;
  if ($('#visibleTestsMeta')) $('#visibleTestsMeta').textContent = `현재 목록 ${visible.length}개`;
  if ($('#testsRangeLabel')) $('#testsRangeLabel').textContent = '4개 분류 기준';
  if ($('#editorSelectionLabel')) $('#editorSelectionLabel').textContent = selected ? displayNameFor(selected) : '선택된 테스트 없음';
  syncCatalogSearchControl();
  syncCatalogMutationControls();
  updateCatalogOrderHint();
}

function renderTestList() {
  const listEl = $('#testList');
  if (!listEl) return;

  const tests = getVisibleTests();
  const selected = tests.find(test => test.id === ui.selectedId) || null;
  const displayNameFor = createUnitTestDisplayNameResolver(getCategoryTests('UNIT'));
  updateChrome(selected, displayNameFor);

  if (!tests.length) {
    const emptyText = String(ui.catalogSearch || '').trim()
      ? '목록 검색 결과가 없습니다.'
      : '등록된 테스트가 없습니다. 새 테스트를 추가하세요.';
    listEl.innerHTML = `<div style="font-size:12px; opacity:.7; padding:4px;">${escapeHtml(emptyText)}</div>`;
    return;
  }

  listEl.innerHTML = renderGroupedTestList(tests, displayNameFor);

  listEl.querySelectorAll('button.test-select-button[data-id]').forEach(btn => {
    btn.addEventListener('click', () => {
      ui.selectedId = btn.dataset.id || '';
      renderTestList();
      fillEditor();
    });
  });

  listEl.querySelectorAll('button.test-order-button[data-move]').forEach(btn => {
    btn.addEventListener('click', () => {
      const catalogIndex = Number(btn.dataset.catalogIndex);
      const direction = btn.dataset.move === 'up' ? -1 : 1;
      void moveCatalogTestByKeyboard(catalogIndex, direction);
    });
  });

  bindCatalogDragAndDrop(listEl);
}

function renderGroupedTestList(tests, displayNameFor = displayTestName) {
  const groups = new Map();
  tests.forEach(test => {
    const key = catalogGroupKey(test, ui.category);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(test);
  });

  return Array.from(groups.entries()).map(([key, items]) => {
    const [partA, partB, partC] = key.split('|||');
    const head = isPastCategory(ui.category)
      ? `${partA || '고사 미분류'} · ${partB || '-'} · 전체 순번`
      : `${partA || '-'} · ${partB ? roundLabel(partB) : '전체 순번'}`;
    return `
      <section class="test-list-group">
        <div class="test-list-group-head">
          <span>${escapeHtml(head)}</span>
          <span class="test-list-group-count">${items.length}개</span>
        </div>
        <div class="test-list-group-body">
          ${items.map((test, index) => renderTestButton(test, displayNameFor, {
            groupKey: key,
            index,
            count: items.length,
          })).join('')}
        </div>
      </section>
    `;
  }).join('');
}

function answerLinkStatus(test) {
  return String(test?.answerLinkStatus ?? test?.answer_link_status ?? '').trim().toLowerCase();
}

function renderTestButton(test, displayNameFor = displayTestName, order = {}) {
  const stat = statForTest(test, TEST_STATS, ui.category);
  const statBadge = stat?.count ? `<span class="small"> · ${escapeHtml(stat.avg_pct)}% / ${escapeHtml(stat.count)}명</span>` : '';
  const answerLinkBadge = answerLinkStatus(test) === MISSING_ANSWER_LINK_STATUS
    ? '<span class="test-link-status is-missing" title="Drive 해설 PDF가 연결되지 않았습니다.">해설 미연결</span>'
    : '';
  const active = test.id === ui.selectedId ? 'active' : '';
  const reorderEnabled = canReorderCatalog() && order.count > 1;
  const canMoveUp = reorderEnabled && order.index > 0;
  const canMoveDown = reorderEnabled && order.index < order.count - 1;
  const displayName = displayNameFor(test);
  return `
    <div class="test-list-item" data-catalog-index="${escapeAttr(test._catalogIndex)}"
      data-group-key="${escapeAttr(order.groupKey || catalogGroupKey(test, ui.category))}">
      <span class="test-drag-handle" draggable="${reorderEnabled ? 'true' : 'false'}"
        aria-hidden="true" aria-disabled="${reorderEnabled ? 'false' : 'true'}"
        title="같은 그룹 안에서 드래그해 순서 변경">⋮⋮</span>
      <button type="button" data-id="${escapeAttr(test.id)}" data-catalog-index="${escapeAttr(test._catalogIndex)}"
        class="test-select-button ${active}">
        ${escapeHtml(displayName)}
        <span class="small">(${escapeHtml(test.problems)}문항)</span>
        ${answerLinkBadge}
        ${statBadge}
      </button>
      <span class="test-order-controls" aria-label="${escapeAttr(`${displayName} 순서 변경`)}">
        <button type="button" class="test-order-button" data-move="up"
          data-catalog-index="${escapeAttr(test._catalogIndex)}" aria-label="${escapeAttr(`${displayName} 위로 이동`)}"
          title="위로 이동" ${canMoveUp ? '' : 'disabled'}>↑</button>
        <button type="button" class="test-order-button" data-move="down"
          data-catalog-index="${escapeAttr(test._catalogIndex)}" aria-label="${escapeAttr(`${displayName} 아래로 이동`)}"
          title="아래로 이동" ${canMoveDown ? '' : 'disabled'}>↓</button>
      </span>
    </div>
  `;
}

function clearCatalogDropIndicators(listEl = $('#testList')) {
  listEl?.querySelectorAll?.('.test-list-item').forEach(item => {
    item.classList.remove('is-dragging', 'is-drop-before', 'is-drop-after');
  });
}

function bindCatalogDragAndDrop(listEl) {
  listEl.querySelectorAll('.test-drag-handle[draggable="true"]').forEach(handle => {
    handle.addEventListener('dragstart', event => {
      const row = handle.closest('.test-list-item');
      const catalogIndex = Number(row?.dataset.catalogIndex);
      if (!Number.isInteger(catalogIndex) || !canReorderCatalog()) {
        event.preventDefault();
        return;
      }
      draggedCatalogIndex = catalogIndex;
      row.classList.add('is-dragging');
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', String(catalogIndex));
      }
    });

    handle.addEventListener('dragend', () => {
      draggedCatalogIndex = null;
      clearCatalogDropIndicators(listEl);
    });
  });

  listEl.querySelectorAll('.test-list-item').forEach(row => {
    row.addEventListener('dragover', event => {
      const source = listEl.querySelector(`.test-list-item[data-catalog-index="${draggedCatalogIndex}"]`);
      if (!source || source === row || source.dataset.groupKey !== row.dataset.groupKey || !canReorderCatalog()) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
      clearCatalogDropIndicators(listEl);
      source.classList.add('is-dragging');
      const rect = row.getBoundingClientRect();
      const placement = event.clientY < rect.top + rect.height / 2 ? 'before' : 'after';
      row.classList.add(placement === 'before' ? 'is-drop-before' : 'is-drop-after');
    });

    row.addEventListener('drop', event => {
      const sourceIndex = draggedCatalogIndex;
      const targetIndex = Number(row.dataset.catalogIndex);
      const placement = row.classList.contains('is-drop-after') ? 'after' : 'before';
      event.preventDefault();
      draggedCatalogIndex = null;
      clearCatalogDropIndicators(listEl);
      if (!Number.isInteger(sourceIndex) || !Number.isInteger(targetIndex)) return;
      void persistCatalogReorder(sourceIndex, targetIndex, placement, 'drag');
    });
  });
}

function catalogOrderSnapshot(cat, rawTests) {
  return {
    tests: cat.tests.slice(),
    sortOrders: rawTests.map(test => ({
      test,
      hadValue: Object.prototype.hasOwnProperty.call(test, 'sortOrder'),
      value: test.sortOrder,
    })),
  };
}

function restoreCatalogOrder(cat, snapshot) {
  cat.tests.splice(0, cat.tests.length, ...snapshot.tests);
  snapshot.sortOrders.forEach(({ test, hadValue, value }) => {
    if (hadValue) test.sortOrder = value;
    else delete test.sortOrder;
  });
}

function applyRawCatalogGroupOrder(cat, orderedRawTests) {
  const groupSet = new Set(orderedRawTests);
  let orderedIndex = 0;
  cat.tests.forEach((test, index) => {
    if (!groupSet.has(test)) return;
    cat.tests[index] = orderedRawTests[orderedIndex];
    orderedIndex += 1;
  });
  orderedRawTests.forEach((test, index) => {
    test.sortOrder = index;
  });
}

function sameRawTestOrder(left, right) {
  return left.length === right.length && left.every((test, index) => test === right[index]);
}

function focusCatalogOrderControl(rawTest, requestedMove = '') {
  const cat = TEST_CFG.categories?.[ui.category];
  const catalogIndex = cat?.tests?.indexOf(rawTest) ?? -1;
  if (catalogIndex < 0) return;
  const requested = requestedMove === 'up' || requestedMove === 'down'
    ? $(`#testList .test-order-button[data-move="${requestedMove}"][data-catalog-index="${catalogIndex}"]:not(:disabled)`)
    : null;
  const fallback = $(`#testList .test-select-button[data-catalog-index="${catalogIndex}"]`);
  (requested || fallback)?.focus?.();
}

function flushDeferredRuleSave() {
  if (!ruleSavePending || ruleSaveInFlight || catalogOrderSaveInFlight) return;
  ruleSavePending = false;
  void saveRulesFromGrid();
}

async function persistCatalogReorder(sourceCatalogIndex, targetCatalogIndex, placement = 'before', focusMove = '') {
  if (!canReorderCatalog()) {
    updateCatalogOrderHint();
    return false;
  }
  const categoryKey = ui.category;
  const cat = TEST_CFG.categories?.[categoryKey];
  if (!cat || !Array.isArray(cat.tests)) return false;

  const visibleTests = getVisibleTests();
  const source = visibleTests.find(test => test._catalogIndex === sourceCatalogIndex);
  const target = visibleTests.find(test => test._catalogIndex === targetCatalogIndex);
  if (!source || !target || source === target) return false;

  const groupKey = catalogGroupKey(source, ui.category);
  if (catalogGroupKey(target, ui.category) !== groupKey) return false;
  const groupTests = visibleTests.filter(test => catalogGroupKey(test, ui.category) === groupKey);
  const orderedRawTests = groupTests.map(test => cat.tests[test._catalogIndex]);
  if (orderedRawTests.some(test => !test || typeof test !== 'object')) return false;

  const sourceRaw = cat.tests[source._catalogIndex];
  const targetRaw = cat.tests[target._catalogIndex];
  const nextRawTests = orderedRawTests.filter(test => test !== sourceRaw);
  const targetIndex = nextRawTests.indexOf(targetRaw);
  if (targetIndex < 0) return false;
  nextRawTests.splice(targetIndex + (placement === 'after' ? 1 : 0), 0, sourceRaw);
  if (sameRawTestOrder(orderedRawTests, nextRawTests)) return false;

  const snapshot = catalogOrderSnapshot(cat, orderedRawTests);
  applyRawCatalogGroupOrder(cat, nextRawTests);
  catalogOrderSaveInFlight = true;
  catalogOrderFeedback = null;
  renderTestList();

  try {
    await saveConfig();
    catalogOrderSaveInFlight = false;
    catalogOrderFeedback = { kind: 'success', message: '시험 순서를 저장했습니다.' };
    renderTestList();
    focusCatalogOrderControl(sourceRaw, focusMove);
    flushDeferredRuleSave();
    return true;
  } catch (error) {
    if (TEST_CFG.categories?.[categoryKey] === cat) restoreCatalogOrder(cat, snapshot);
    catalogOrderSaveInFlight = false;
    catalogOrderFeedback = error?.status === 409
      ? { kind: 'error', message: '다른 곳에서 설정이 변경되어 최신 목록을 다시 불러왔습니다. 순서를 다시 확인해주세요.' }
      : { kind: 'error', message: '순서 저장에 실패해 이전 순서로 되돌렸습니다.' };
    console.error('[tests] catalog reorder failed', error);
    renderTestList();
    focusCatalogOrderControl(sourceRaw, focusMove);
    flushDeferredRuleSave();
    return false;
  }
}

async function moveCatalogTestByKeyboard(catalogIndex, direction) {
  if (!canReorderCatalog() || !Number.isInteger(catalogIndex)) return false;
  const visibleTests = getVisibleTests();
  const source = visibleTests.find(test => test._catalogIndex === catalogIndex);
  if (!source) return false;
  const groupTests = visibleTests.filter(test => catalogGroupKey(test, ui.category) === catalogGroupKey(source, ui.category));
  const sourceIndex = groupTests.findIndex(test => test._catalogIndex === catalogIndex);
  const target = groupTests[sourceIndex + direction];
  if (!target) return false;
  const move = direction < 0 ? 'up' : 'down';
  return persistCatalogReorder(catalogIndex, target._catalogIndex, direction < 0 ? 'before' : 'after', move);
}

function fillEditor() {
  updateSubjectOptions();

  const ref = selectedTestRef();
  const categoryKey = ref?.categoryKey || ui.category;
  updateEditCategoryOptions(categoryKey);

  const raw = ref?.test || null;
  const test = raw ? normalizeTest(raw, categoryKey) : null;
  if (!test) {
    $('#cfgEditType') && ($('#cfgEditType').value = ui.category);
    updateDifficultyOptions();
    updateEditTermOptions(ui.category);
    $('#cfgTerm') && ($('#cfgTerm').value = TERM_OPTIONS.includes(ui.term) ? ui.term : (TERM_OPTIONS[0] || ''));
    $('#cfgSubject') && ($('#cfgSubject').value = ui.subject);
    $('#cfgDifficulty') && ($('#cfgDifficulty').value = (CATEGORY_BY_KEY[ui.category]?.difficulties?.[0] || ''));
    $('#cfgRound') && ($('#cfgRound').value = '1');
    $('#cfgName') && ($('#cfgName').value = '');
    $('#cfgProblems') && ($('#cfgProblems').value = '');
    $('#cfgAnswers') && ($('#cfgAnswers').value = '');
    renderAnswerModeEditor(null);
    updateChrome(null);
    setTestSaveStatus('ready', '변경 없음');
    return;
  }

  if ($('#cfgEditType')) $('#cfgEditType').value = categoryKey;
  updateDifficultyOptions(categoryKey);
  updateEditTermOptions(categoryKey);
  if ($('#cfgSubject')) $('#cfgSubject').value = test.curriculum;
  if ($('#cfgDifficulty')) $('#cfgDifficulty').value = test.difficulty;
  if ($('#cfgTerm')) $('#cfgTerm').value = TERM_OPTIONS.includes(test.term) ? test.term : (TERM_OPTIONS[0] || '');
  if ($('#cfgRound')) $('#cfgRound').value = test.round || '1';
  if ($('#cfgName')) $('#cfgName').value = test.name || '';
  if ($('#cfgProblems')) $('#cfgProblems').value = test.problems || '';
  if ($('#cfgAnswers')) $('#cfgAnswers').value = answerKeysToText(test);
  renderAnswerModeEditor(raw);
  updateChrome(test);
  setTestSaveStatus('ready', '저장된 상태');
}

function renderRules() {
  const host = $('#ruleGrid');
  if (!host) return;

  host.innerHTML = `
    <div class="rule-grid-inner">
      ${CATEGORY_DEFS.map(def => renderRuleSection(def)).join('')}
    </div>
  `;
}

function renderRuleSection(def) {
  const rules = TEST_CFG.autoAssignRules?.[def.key] || {};
  const difficultyLabel = def.difficulties.join(' · ');
  return `
    <section class="rule-section" data-rule-category="${escapeAttr(def.key)}">
      <div class="rule-section-head">
        <div class="rule-section-title">
          <strong>${escapeHtml(def.label)}</strong>
          <span>과목별 테스트 난이도와 학생 정보 레벨 연결</span>
        </div>
        <span class="rule-section-meta">${escapeHtml(difficultyLabel)}</span>
      </div>
      <table class="stats-table" style="margin:0">
        <thead>
          <tr>
            <th style="text-align:left;">과목</th>
            <th style="text-align:left;">테스트 난이도</th>
            ${STUDENT_LEVELS.map(level => `<th>${escapeHtml(level)}</th>`).join('')}
          </tr>
        </thead>
        <tbody>
          ${SUBJECTS.map(subject => def.difficulties.map((difficulty, index) => {
            const levels = Array.isArray(rules?.[subject]?.[difficulty]) ? rules[subject][difficulty].map(String) : [];
            return `
              <tr>
                ${index === 0 ? `<td rowspan="${def.difficulties.length}" style="text-align:left;font-weight:800;">${escapeHtml(subject)}</td>` : ''}
                <td style="text-align:left;"><span class="level-pill">${escapeHtml(difficulty)}</span></td>
                ${STUDENT_LEVELS.map(level => `
                  <td style="text-align:center;">
                    <label class="rule-check-target" aria-label="${escapeAttr(`${subject} ${difficulty} ${level} 배정`)}">
                      <input type="checkbox" class="rule-check"
                        data-category="${escapeAttr(def.key)}"
                        data-subject="${escapeAttr(subject)}"
                        data-difficulty="${escapeAttr(difficulty)}"
                        data-level="${escapeAttr(level)}"
                        ${levels.includes(level) ? 'checked' : ''}>
                    </label>
                  </td>
                `).join('')}
              </tr>
            `;
          }).join('')).join('')}
        </tbody>
      </table>
    </section>
  `;
}

function readRulesFromGrid() {
  TEST_CFG.autoAssignRules = TEST_CFG.autoAssignRules || {};

  CATEGORY_DEFS.forEach(def => {
    TEST_CFG.autoAssignRules[def.key] = TEST_CFG.autoAssignRules[def.key] || {};
    SUBJECTS.forEach(subject => {
      TEST_CFG.autoAssignRules[def.key][subject] = TEST_CFG.autoAssignRules[def.key][subject] || {};
      def.difficulties.forEach(difficulty => {
        const levels = Array.from(document.querySelectorAll(`.rule-check[data-category="${CSS.escape(def.key)}"][data-subject="${CSS.escape(subject)}"][data-difficulty="${CSS.escape(difficulty)}"]:checked`))
          .map(input => input.dataset.level)
          .filter(Boolean);
        TEST_CFG.autoAssignRules[def.key][subject][difficulty] = levels;
      });
    });
  });
}

function ruleSaveToast() {
  let toast = $('#ruleSaveToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'ruleSaveToast';
    toast.className = 'rule-save-toast';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    document.body.appendChild(toast);
  }
  return toast;
}

function showRuleSavePopup(message = '저장됐음', kind = 'success') {
  const toast = ruleSaveToast();
  toast.textContent = message;
  toast.dataset.kind = kind;
  toast.classList.add('is-visible');
  if (ruleSaveToastTimer) clearTimeout(ruleSaveToastTimer);
  ruleSaveToastTimer = setTimeout(() => {
    toast.classList.remove('is-visible');
  }, 1800);
}

function setTestSaveStatus(kind = 'ready', message = '') {
  const status = $('#testSaveStatus');
  if (status) {
    status.dataset.kind = kind;
    status.textContent = message || '변경 없음';
  }
  const button = $('#btnSaveTest');
  if (button) button.textContent = kind === 'saving' ? '저장 중…' : '저장';
}

function markTestEditorDirty() {
  if (catalogMutationSaveInFlight) return;
  setTestSaveStatus('dirty', '저장 안 됨');
}

function testSaveClock(date = new Date()) {
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map(value => String(value).padStart(2, '0'))
    .join(':');
}

async function saveRulesFromGrid() {
  if (catalogOrderSaveInFlight || catalogMutationSaveInFlight) {
    ruleSavePending = true;
    return;
  }
  if (ruleSaveInFlight) {
    ruleSavePending = true;
    return;
  }

  ruleSaveInFlight = true;
  try {
    readRulesFromGrid();
    await saveConfig();
    showRuleSavePopup();
  } catch (e) {
    console.error(e);
    showRuleSavePopup('규칙 저장 실패', 'error');
  } finally {
    ruleSaveInFlight = false;
    if (ruleSavePending) {
      ruleSavePending = false;
      saveRulesFromGrid();
    }
  }
}

function scheduleRulesAutosave() {
  if (ruleSaveTimer) clearTimeout(ruleSaveTimer);
  if (catalogOrderSaveInFlight || catalogMutationSaveInFlight) {
    ruleSaveTimer = null;
    ruleSavePending = true;
    return;
  }
  ruleSaveTimer = setTimeout(() => {
    ruleSaveTimer = null;
    saveRulesFromGrid();
  }, 350);
}

async function saveConfig(removedTestIds = []) {
  const request = wholeConfigWriteRequest(TEST_CFG, TEST_CFG_REVISION, removedTestIds);
  const res = await fetch('/api/tests-config', request);
  if (!res.ok) {
    if (res.status === 409 || res.status === 428) await loadConfigAndStats();
    const error = new Error(`tests-config save failed: ${res.status}`);
    error.status = res.status;
    throw error;
  }
  const revision = normalizeRevision(res.headers?.get?.('X-Tests-Config-Revision'));
  if (revision) TEST_CFG_REVISION = revision;
}

function captureTestCatalogMutationSnapshot() {
  return captureCatalogMutationSnapshot(TEST_CFG, TEST_CFG_REVISION, ui.selectedId);
}

function restoreTestCatalogMutationSnapshot(snapshot) {
  TEST_CFG = ensureConfig(snapshot?.config || { categories: {} });
  TEST_CFG_REVISION = String(snapshot?.revision || '');
  ui.selectedId = String(snapshot?.selectedId || '');
  renderTestList();
  renderRules();
  renderStatsSummary();
}

async function saveTestDefinition(test, categoryKey, categoryLabel, clearFields = []) {
  const request = testDefinitionWriteRequest(
    test,
    categoryKey,
    categoryLabel,
    clearFields,
    TEST_CFG_REVISION,
  );
  const res = await fetch('/api/tests-config/test', request);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const error = new Error(`tests-config test save failed: ${res.status}`);
    error.status = res.status;
    throw error;
  }
  const revision = normalizeRevision(res.headers?.get?.('X-Tests-Config-Revision'));
  if (revision) TEST_CFG_REVISION = revision;
  return data?.test && typeof data.test === 'object' ? data.test : test;
}

function downloadCsvTemplate() {
  const csv = buildTestCatalogCsvTemplate(ILSAN_GRAPH_DIFFICULTY);
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'test_catalog_template.csv';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function findExistingTest(cat, patch) {
  const tests = Array.isArray(cat.tests) ? cat.tests : [];
  if (patch.id) {
    const byId = tests.find(test => String(test?.id || '').trim() === patch.id);
    if (byId) return byId;
  }
  return tests.find(test =>
    canonText(test?.name) === patch.name &&
    normalizeSubject(test?.curriculum || test?.subject) === patch.curriculum &&
    String(normalizeDifficulty(patch.categoryKey, test?.difficulty || test?.level, test?.name)).trim() === patch.difficulty &&
    String(normalizeRound(test?.round || test?.session || test?.no, test?.name)).trim() === patch.round &&
    (!isPastCategory(patch.categoryKey) || normalizeTerm(test?.term || test?.examTerm || test?.examPeriod || test?.exam_period, test?.name) === patch.term)
  ) || null;
}

function reportCsvParseWarning(message, error) {
  console.warn(message, error);
}

async function importTestsFromCsv(file) {
  const rows = parseCsv(await file.text());
  if (rows.length < 2) {
    alert('가져올 시험 행이 없습니다.');
    return;
  }

  const headers = rows[0].map(headerKey);
  if (!headers.includes('name')) {
    alert('CSV 첫 줄에 시험명 열이 필요합니다.');
    return;
  }

  let added = 0;
  let updated = 0;
  let skipped = 0;
  const errors = [];
  let lastCategory = ui.category;
  let lastSubject = ui.subject;
  let lastDifficulty = ui.difficulty;
  let lastTerm = ui.term;
  let lastRound = ui.round;

  rows.slice(1).forEach((cells, idx) => {
    const sourceOrder = idx + 1;
    const row = rowObject(headers, cells);
    const name = canonText(row.name);
    if (!name) {
      skipped += 1;
      errors.push(`${idx + 2}행: 시험명 없음`);
      return;
    }

    const categoryKey = categoryKeyFrom(row.category || ui.category);
    const def = CATEGORY_BY_KEY[categoryKey];
    if (!def) {
      skipped += 1;
      errors.push(`${idx + 2}행: 알 수 없는 분류 "${row.category}"`);
      return;
    }

    const subject = normalizeSubject(row.subject || ui.subject);
    if (!SUBJECTS.includes(subject)) {
      skipped += 1;
      errors.push(`${idx + 2}행: 알 수 없는 과목 "${row.subject}"`);
      return;
    }

    const difficulty = normalizeDifficulty(categoryKey, row.difficulty, name);
    const term = isPastCategory(categoryKey) ? normalizeTerm(row.term || row.examTerm || row.examPeriod || row.exam_period, name) : '';
    const csvRound = normalizeRound(row.round || '1', name);
    const problemsRaw = Number(row.problems || 20);
    const problems = Number.isFinite(problemsRaw) ? Math.max(1, Math.min(100, Math.trunc(problemsRaw))) : 20;
    const rawId = canonText(row.id);
    const baseId = rawId || `t_${categoryKey.toLowerCase()}_${Date.now()}_${idx}_${Math.random().toString(36).slice(2, 7)}`;
    const orderRaw = Number(row.sourceOrder || sourceOrder);
    const rowOrder = Number.isFinite(orderRaw) ? orderRaw : sourceOrder;
    const csvRounds = isUnitCategory(categoryKey) && hasRoundAnswerColumns(row) ? csvAnswerRounds(row) : [];
    const rounds = csvRounds.length ? csvRounds : [csvRound];

    const cat = TEST_CFG.categories[categoryKey] = TEST_CFG.categories[categoryKey] || { label: def.label, tests: [] };
    if (!Array.isArray(cat.tests)) cat.tests = [];
    cat.label = cat.label || def.label;

    rounds.forEach(round => {
      const answerKey = answerKeyFromCsvRow(row, round, problems, reportCsvParseWarning);
      const answerModes = answerModesFromCsvRow(row, round, problems, reportCsvParseWarning);
      const answerModeIssue = answerModeConsistencyIssue(answerKey, answerModes);
      if (answerModeIssue) {
        skipped += 1;
        errors.push(`${idx + 2}행 ${round}회차: ${answerModeIssue}`);
        return;
      }
      const patch = {
        id: rounds.length > 1 ? `${baseId}_r${round}` : baseId,
        sourceId: rounds.length > 1 ? baseId : canonText(row.sourceId || row.source_id || ''),
        name,
        categoryKey,
        problems,
        curriculum: subject,
        difficulty,
        sortOrder: rowOrder,
        sourceOrder: rowOrder,
        round,
        answerKeys: { [round]: answerKey },
        answerModes: { [round]: answerModes },
        answerKey,
      };
      if (term) {
        patch.term = term;
        patch.examTerm = term;
      }

      const existing = findExistingTest(cat, patch);
      if (existing) {
        if (!rawId && rounds.length === 1) patch.id = canonText(existing.id) || patch.id;
        Object.assign(existing, patch);
        updated += 1;
      } else {
        cat.tests.push(patch);
        added += 1;
      }
    });
    lastCategory = categoryKey;
    lastSubject = subject;
    lastDifficulty = difficulty;
    lastTerm = term;
    lastRound = rounds[rounds.length - 1] || csvRound;
  });

  if (!added && !updated) {
    alert(`가져온 시험이 없습니다.${errors.length ? `\n${errors.slice(0, 5).join('\n')}` : ''}`);
    return;
  }

  await saveConfig();
  ui.category = lastCategory;
  ui.subject = lastSubject;
  ui.difficulty = lastDifficulty;
  ui.term = isPastCategory(lastCategory) ? lastTerm : '';
  ui.round = lastRound;
  ui.selectedId = '';
  $('#cfgType') && ($('#cfgType').value = ui.category);
  $('#cfgCur') && ($('#cfgCur').value = ui.subject);
  await loadConfigAndStats();

  const detail = errors.length ? `\n건너뜀 ${skipped}건\n${errors.slice(0, 5).join('\n')}` : '';
  alert(`CSV 가져오기 완료\n추가 ${added}건 · 업데이트 ${updated}건${detail}`);
}

async function loadConfigAndStats() {
  const statsVersion = ++statsLoadVersion;
  TEST_STATS_DETAIL = null;
  ui.statsTestId = '';
  TEST_STATS = null;
  const testList = $('#testList');
  testList?.setAttribute('aria-busy', 'true');
  try {
    TEST_CFG = ensureConfig(await fetchTestsConfig());
  } catch {
    TEST_CFG_REVISION = '';
    TEST_CFG = ensureConfig({ categories: {} });
  }

  const typeSel = $('#cfgType');
  const curSel = $('#cfgCur');
  if (typeSel) typeSel.value = ui.category;
  if (curSel) curSel.value = ui.subject;

  updateSubjectOptions();
  updateListDifficultyOptions();
  updateTermOptions();
  updateRoundOptions();
  updateEditCategoryOptions(ui.category);
  renderTestList();
  fillEditor();
  renderRules();
  syncCatalogMutationControls();
  renderStatsSummary();
  renderStatsTable();
  renderStatsDetail();
  testList?.setAttribute('aria-busy', 'false');

  await new Promise(resolve => setTimeout(resolve, 0));
  let nextStats = null;
  try {
    const recent = Number($('#statRecent')?.value || '30') || 30;
    nextStats = await fetchJSONSafe(`/api/tests-stats?recent_days=${recent}&include_wrong=0`);
  } catch {
    nextStats = null;
  }
  if (statsVersion !== statsLoadVersion) return;
  TEST_STATS = nextStats;
  renderTestList();
  renderStatsSummary();
  renderStatsTable();
  renderStatsDetail();
}

async function loadStatsOnly() {
  const statsVersion = ++statsLoadVersion;
  TEST_STATS_DETAIL = null;
  ui.statsTestId = '';
  let nextStats = null;
  try {
    const recent = Number($('#statRecent')?.value || '30') || 30;
    nextStats = await fetchJSONSafe(`/api/tests-stats?recent_days=${recent}&include_wrong=0`);
  } catch {
    nextStats = null;
  }
  if (statsVersion !== statsLoadVersion) return;
  TEST_STATS = nextStats;
  renderStatsSummary();
  renderStatsTable();
  renderStatsDetail();
}

function renderStatsSummary() {
  const box = $('#statsSummary');
  if (!box) return;
  const categoryCounts = Object.fromEntries(
    CATEGORY_DEFS.map(definition => [definition.key, getCategoryTests(definition.key).length]),
  );
  const cards = projectStatsSummary({
    categoryDefinitions: CATEGORY_DEFS,
    summary: TEST_STATS?.summary || {},
    categoryCounts,
    activeCategory: ui.statsCategory,
  }).map(card => {
    const active = card.active ? ' is-active' : '';
    return `
      <button type="button" class="summary-card${active}" data-type="${escapeAttr(card.key)}" data-stats-category="${escapeAttr(card.key)}">
        <div class="summary-label">${escapeHtml(card.label)}</div>
        <div class="summary-value">${escapeHtml(card.metric)}</div>
        <div class="summary-meta">${escapeHtml(card.meta)}</div>
      </button>
    `;
  });
  box.innerHTML = cards.join('');
  box.querySelectorAll('[data-stats-category]').forEach(button => {
    button.addEventListener('click', () => {
      ui.statsCategory = button.dataset.statsCategory || 'UNIT';
      ui.statsTestId = '';
      TEST_STATS_DETAIL = null;
      renderStatsSummary();
      renderStatsTable();
      renderStatsDetail();
    });
  });
}

function syncStatsControls() {
  const search = $('#statSearch');
  if (search) {
    applySearchPlaceholder(search, '시험명, 과목, 레벨 검색');
    if (search.value !== ui.statsSearch) search.value = ui.statsSearch;
  }
  const sort = $('#statSort');
  if (sort) sort.value = ui.statsSort;
}


function renderStatsTable() {
  const tbody = $('#statsTable tbody');
  if (!tbody) return;
  syncStatsControls();
  const def = CATEGORY_BY_KEY[ui.statsCategory] || CATEGORY_BY_KEY.UNIT;
  const queryText = ui.statsSearch || '';
  const displayNameFor = createUnitTestDisplayNameResolver(getCategoryTests('UNIT'));
  const rows = projectStatsRows({
    tests: getCategoryTests(def.key),
    definition: def,
    stats: TEST_STATS,
    queryText,
    sort: ui.statsSort,
    displayNameFor,
    searchKeyForText,
    matchesSearchKey,
  });

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-cell">${queryText.trim() ? '검색 결과가 없습니다.' : '등록된 테스트가 없습니다.'}</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(row => `
    <tr class="data-row ${row.id === ui.statsTestId ? 'is-active' : ''}" data-stat-test-id="${escapeAttr(row.id)}">
      <td style="text-align:left;"><span class="type-pill" data-type="${escapeAttr(row.categoryKey)}">${escapeHtml(row.typeLabel)}</span></td>
      <td style="text-align:left;">${escapeHtml(row.curriculum || '-')}</td>
      <td style="text-align:left;">
        <div class="stat-title">
          <span class="stat-main">${escapeHtml(row.displayName)}</span>
          <span class="stat-sub">${escapeHtml([isPastCategory(row.categoryKey) ? (row.term || row.examTerm || '') : '', row.problems ? `${row.problems}문항` : ''].filter(Boolean).join(' · '))}</span>
        </div>
      </td>
      <td><span class="level-pill">${escapeHtml(row.difficulty || '-')}</span></td>
      <td>${escapeHtml(roundLabel(row.round || '-'))}</td>
      <td>${escapeHtml(row.stat?.count || 0)}</td>
      <td>${escapeHtml(formatPercent(row.stat?.avg_pct))}</td>
    </tr>
  `).join('');

  tbody.querySelectorAll('[data-stat-test-id]').forEach(rowEl => {
    rowEl.addEventListener('click', () => {
      const testId = rowEl.dataset.statTestId || '';
      const row = rows.find(item => item.id === testId);
      ui.statsTestId = testId;
      TEST_STATS_DETAIL = null;
      openStatsDetailModal(row);
      renderStatsTable();
      renderStatsDetail(row, true);
    });
  });
}

async function loadStatsDetail(test) {
  if (!test?.id) return null;
  const recent = Number($('#statRecent')?.value || '30') || 30;
  const params = new URLSearchParams({ test_id: test.id, recent_days: String(recent) });
  return fetchJSONSafe(`/api/tests-records?${params.toString()}`);
}

function detailMetric(label, value) {
  return `
    <div class="detail-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}

function wrongDetailListHtml(projection) {
  const rows = projection?.rows || [];
  if (projection?.emptyMessage) {
    return `<p class="wrong-detail-empty">${escapeHtml(projection.emptyMessage)}</p>`;
  }
  if (!rows.length) return '';
  const items = rows.map(row => {
    return `
      <li>
        <span class="wrong-detail-no">${escapeHtml(row.questionLabel)}</span>
        <b class="wrong-detail-answer wrong-detail-mine">
          <span class="wrong-detail-label">내 답</span>
          <strong>${escapeHtml(row.myAnswer)}</strong>
        </b>
        <em class="wrong-detail-answer wrong-detail-correct">
          <span class="wrong-detail-label">정답</span>
          <strong>${escapeHtml(row.correctAnswer)}</strong>
        </em>
      </li>
    `;
  }).join('');
  return `
    <details class="wrong-detail-list">
      <summary>틀린 문항 내 답/정답 비교</summary>
      <ul>${items}</ul>
    </details>
  `;
}

function statsDetailHost() {
  return $('#statsDetailModalBody') || $('#statsDetail');
}

function openStatsDetailModal(test) {
  const modal = $('#statsDetailModal');
  if (!modal) return;
  const title = $('#statsDetailModalTitle');
  if (title) title.textContent = test ? (test.displayName || displayTestName(test)) : '테스트 통계';
  modal.hidden = false;
  modal.setAttribute('aria-hidden', 'false');
  document.body.classList.add('stats-modal-open');
  requestAnimationFrame(() => modal.querySelector('.stats-detail-dialog')?.focus());
}

function closeStatsDetailModal() {
  const modal = $('#statsDetailModal');
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  modal.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('stats-modal-open');
}

function initStatsDetailModal() {
  const modal = $('#statsDetailModal');
  if (!modal) return;
  modal.addEventListener('click', event => {
    if (!event.target?.closest?.('[data-stats-detail-close]')) return;
    closeStatsDetailModal();
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || modal.hidden) return;
    closeStatsDetailModal();
  });
}

function renderStatsDetail(test = null, fetchDetail = false) {
  const host = statsDetailHost();
  if (!host) return;

  const selected = test || getCategoryTests(ui.statsCategory).find(item => item.id === ui.statsTestId);
  if (!selected) {
    host.innerHTML = '';
    return;
  }

  const stat = statForTest(selected, TEST_STATS, ui.statsCategory) || {};
  if (fetchDetail) {
    TEST_STATS_DETAIL = { records: [] };
    renderStatsDetail(selected, false);
    loadStatsDetail(selected).then(detail => {
      TEST_STATS_DETAIL = detail;
      renderStatsDetail(selected, false);
    }).catch(err => {
      console.error(err);
    });
    return;
  }

  const presentation = projectStatsDetail({
    selected,
    stat,
    detail: TEST_STATS_DETAIL,
    displayNameFor: displayTestName,
  });
  const studentRows = presentation.records.map(record => `
    <tr>
      <td style="text-align:left;">${escapeHtml(record.studentName)}</td>
      <td>${escapeHtml(record.level)}</td>
      <td>${escapeHtml(record.percent)}</td>
      <td>
        <div class="score-with-wrong">
          <strong>${escapeHtml(record.score)}</strong>
          <span>${escapeHtml(record.wrongText)}</span>
          ${wrongDetailListHtml(record.wrongDetails)}
        </div>
      </td>
      <td style="text-align:left;">${escapeHtml(record.createdDate)}</td>
    </tr>
  `).join('');

  host.innerHTML = `
    <section class="stats-detail-panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">${escapeHtml(presentation.title)}</div>
          <div class="panel-subtitle">${escapeHtml(presentation.subtitle)}</div>
        </div>
      </div>
      <div class="detail-metrics">
        ${presentation.metrics.map(metric => detailMetric(metric.label, metric.value)).join('')}
      </div>
      ${presentation.answerLink ? `
        <div class="detail-answer-link-row">
          <a class="detail-answer-link" href="${escapeAttr(presentation.answerLink.url)}" target="_blank" rel="noopener noreferrer">
            ${escapeHtml(presentation.answerLink.label || '답지 보기')}
          </a>
        </div>
      ` : ''}
      <div class="panel-table-wrap">
        <table class="stats-table detail-student-table">
          <thead>
            <tr>
              <th>학생</th>
              <th>레벨</th>
              <th>점수</th>
              <th>채점 결과</th>
              <th>응시일</th>
            </tr>
          </thead>
          <tbody>
            ${studentRows || '<tr><td colspan="5" class="empty-cell">응시 기록이 없습니다.</td></tr>'}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function bindUI() {
  const editorPanel = document.querySelector('.editor-panel');
  const editorFieldSelector = [
    '#cfgEditType', '#cfgSubject', '#cfgDifficulty', '#cfgTerm', '#cfgRound',
    '#cfgName', '#cfgProblems', '#cfgAnswers', '#cfgAnswerModes select',
  ].join(',');
  const handleEditorChange = (event) => {
    if (event.target?.matches?.(editorFieldSelector)) markTestEditorDirty();
  };
  editorPanel?.addEventListener('input', handleEditorChange);
  editorPanel?.addEventListener('change', handleEditorChange);

  $('#cfgType')?.addEventListener('change', e => {
    clearCatalogOrderFeedback();
    ui.category = e.target.value || 'UNIT';
    ui.difficulty = '';
    ui.term = '';
    ui.round = '';
    ui.selectedId = '';
    updateListDifficultyOptions();
    updateTermOptions();
    updateRoundOptions();
    updateEditCategoryOptions(ui.category);
    renderTestList();
    fillEditor();
    renderRules();
    renderStatsSummary();
    renderStatsTable();
  });

  $('#cfgCur')?.addEventListener('change', e => {
    clearCatalogOrderFeedback();
    ui.subject = normalizeSubject(e.target.value);
    ui.term = '';
    ui.round = '';
    ui.selectedId = '';
    updateListDifficultyOptions();
    updateTermOptions();
    updateRoundOptions();
    renderTestList();
    fillEditor();
    renderRules();
  });

  $('#cfgDifficultyFilter')?.addEventListener('change', e => {
    clearCatalogOrderFeedback();
    ui.difficulty = String(e.target.value || '').trim();
    ui.term = '';
    ui.round = '';
    ui.selectedId = '';
    updateTermOptions();
    updateRoundOptions();
    renderTestList();
    fillEditor();
  });

  $('#cfgRoundFilter')?.addEventListener('change', e => {
    clearCatalogOrderFeedback();
    ui.round = String(e.target.value || '').trim();
    ui.selectedId = '';
    renderTestList();
    fillEditor();
  });

  $('#cfgEditType')?.addEventListener('change', e => {
    const key = categoryKeyFrom(e.target.value || ui.category);
    updateDifficultyOptions(key);
    updateEditTermOptions(key);
  });

  $('#cfgProblems')?.addEventListener('input', () => {
    renderAnswerModeEditor(selectedTestRef()?.test || null, currentAnswerModes());
  });

  $('#cfgRound')?.addEventListener('change', () => {
    renderAnswerModeEditor(selectedTestRef()?.test || null);
  });

  $('#cfgAnswerModes')?.addEventListener('change', () => {
    updateAnswerModeSummary();
  });

  $('#cfgTermFilter')?.addEventListener('change', e => {
    clearCatalogOrderFeedback();
    ui.term = String(e.target.value || '').trim();
    ui.selectedId = '';
    renderTestList();
    fillEditor();
  });

  $('#cfgCatalogSearch')?.addEventListener('input', e => {
    clearCatalogOrderFeedback();
    ui.catalogSearch = String(e.target.value || '');
    renderTestList();
  });

  $('#statSearch')?.addEventListener('input', e => {
    ui.statsSearch = String(e.target.value || '').trim();
    ui.statsTestId = '';
    TEST_STATS_DETAIL = null;
    closeStatsDetailModal();
    renderStatsTable();
    renderStatsDetail();
  });

  $('#statSort')?.addEventListener('change', e => {
    ui.statsSort = String(e.target.value || 'default');
    renderStatsTable();
  });

  $('#btnCsvTemplate')?.addEventListener('click', downloadCsvTemplate);

  $('#btnImportCsv')?.addEventListener('click', () => {
    if (catalogMutationControlsLocked()) return;
    const input = $('#csvFile');
    if (!input) return;
    input.value = '';
    input.click();
  });

  $('#csvFile')?.addEventListener('change', async (e) => {
    const file = e.target?.files?.[0];
    if (!file) return;
    if (!beginCatalogMutationSave()) {
      e.target.value = '';
      return;
    }
    try {
      await importTestsFromCsv(file);
    } catch (err) {
      console.error(err);
      alert(err?.message || 'CSV 가져오기에 실패했습니다.');
    } finally {
      endCatalogMutationSave();
      e.target.value = '';
    }
  });

  $('#btnNewTest')?.addEventListener('click', () => {
    if (catalogMutationControlsLocked()) return;
    const def = CATEGORY_BY_KEY[ui.category] || CATEGORY_BY_KEY.UNIT;
    const difficulty = def.difficulties.includes(ui.difficulty) ? ui.difficulty : (def.difficulties[0] || '');
    const term = isPastCategory(ui.category) ? (ui.term || TERM_OPTIONS[0] || '') : '';
    const round = isUnitCategory(ui.category) ? (ui.round || '1') : nextRoundFor(ui.category, ui.subject, difficulty);
    const draftName = `${categoryLabel(ui.category)} ${ui.subject} ${term ? `${term} ` : ''}${difficulty} ${round}회차`;
    ui.selectedId = '';
    ui.difficulty = difficulty;
    ui.term = term;
    ui.round = isUnitCategory(ui.category) ? round : '';
    updateListDifficultyOptions();
    updateTermOptions();
    updateRoundOptions();
    renderTestList();
    fillEditor();
    if ($('#cfgEditType')) $('#cfgEditType').value = ui.category;
    updateDifficultyOptions(ui.category);
    updateEditTermOptions(ui.category);
    if ($('#cfgSubject')) $('#cfgSubject').value = ui.subject;
    if ($('#cfgDifficulty')) $('#cfgDifficulty').value = difficulty;
    if ($('#cfgTerm')) $('#cfgTerm').value = TERM_OPTIONS.includes(term) ? term : (TERM_OPTIONS[0] || '');
    if ($('#cfgRound')) $('#cfgRound').value = round;
    if ($('#cfgName')) $('#cfgName').value = draftName;
    if ($('#cfgProblems')) $('#cfgProblems').value = '20';
    if ($('#cfgAnswers')) $('#cfgAnswers').value = '';
    renderAnswerModeEditor(null, new Array(20).fill(''));
    markTestEditorDirty();
  });

  $('#btnSaveTest')?.addEventListener('click', async () => {
    const targetCategory = editCategoryValue();
    const targetDef = CATEGORY_BY_KEY[targetCategory] || CATEGORY_BY_KEY.UNIT;
    const name = canonText($('#cfgName')?.value || '');
    const problems = Math.max(1, Number($('#cfgProblems')?.value || 0));
    const subject = normalizeSubject($('#cfgSubject')?.value || ui.subject);
    const difficulty = String($('#cfgDifficulty')?.value || '').trim();
    const term = isPastCategory(targetCategory) ? normalizeTerm($('#cfgTerm')?.value || ui.term, name) : '';
    const round = normalizeRound($('#cfgRound')?.value || '1');
    const answers = $('#cfgAnswers')?.value || '';
    const answerModes = currentAnswerModes(problems);
    const answerProjection = projectAnswerRound(selectedTestRef()?.test || null, {
      answers,
      problems,
      round,
      modes: answerModes,
    });
    const answerKey = answerProjection.answerKey;

    if (!name) {
      setTestSaveStatus('error', '테스트명을 입력해주세요');
      $('#cfgName')?.focus?.();
      return;
    }

    const answerModeIssue = answerProjection.issue;
    if (answerModeIssue) {
      setTestSaveStatus('error', answerModeIssue);
      $('#cfgAnswers')?.focus?.();
      return;
    }

    if (!beginCatalogMutationSave()) {
      setTestSaveStatus('error', '다른 저장 완료 후 다시 눌러주세요');
      return;
    }
    setTestSaveStatus('saving', '저장 중…');
    const catalogSnapshot = captureTestCatalogMutationSnapshot();

    try {
      const cat = TEST_CFG.categories[targetCategory] = TEST_CFG.categories[targetCategory]
        || { label: targetDef.label, tests: [] };
      cat.label = cat.label || targetDef.label;
      if (!Array.isArray(cat.tests)) cat.tests = [];
      const ref = selectedTestRef();
      let test = ref?.test || null;
      if (!test) {
        test = { id: `t_${targetCategory.toLowerCase()}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}` };
        cat.tests.push(test);
        ui.selectedId = test.id;
      } else if (ref.categoryKey !== targetCategory) {
        ref.cat.tests = (ref.cat.tests || []).filter(item => item !== test);
        cat.tests.push(test);
      }

      test.name = name;
      test.category = targetCategory;
      test.categoryKey = targetCategory;
      test.curriculum = subject;
      test.difficulty = difficulty;
      if (term) {
        test.term = term;
        test.examTerm = term;
      } else {
        delete test.term;
        delete test.examTerm;
      }
      test.round = round;
      test.problems = problems;
      test.answerKey = answerKey;
      test.answerKeys = answerProjection.answerKeys;
      test.answerModes = answerProjection.answerModes;

      const clearFields = term ? [] : ['term', 'examTerm'];
      const savedTest = await saveTestDefinition(
        test,
        targetCategory,
        cat.label || targetDef.label,
        clearFields,
      );
      if (savedTest !== test) Object.assign(test, savedTest);
      ui.category = targetCategory;
      ui.subject = subject;
      ui.difficulty = difficulty;
      ui.term = isPastCategory(targetCategory) ? term : '';
      ui.round = isUnitCategory(targetCategory) ? round : '';
      $('#cfgType') && ($('#cfgType').value = targetCategory);
      $('#cfgCur') && ($('#cfgCur').value = subject);
      updateListDifficultyOptions();
      updateTermOptions();
      updateRoundOptions();
      updateEditCategoryOptions(targetCategory);
      renderTestList();
      fillEditor();
      renderRules();
      renderStatsSummary();
      setTestSaveStatus('success', `저장 완료 · ${testSaveClock()}`);
    } catch (e) {
      console.error(e);
      if (e?.status === 409 || e?.status === 428) {
        ui.selectedId = catalogSnapshot.selectedId;
        await loadConfigAndStats();
        setTestSaveStatus('error', '목록 변경 감지 · 최신 상태를 다시 불러왔습니다');
      } else {
        restoreTestCatalogMutationSnapshot(catalogSnapshot);
        setTestSaveStatus('error', '저장 실패 · 입력은 유지됐습니다');
      }
    } finally {
      endCatalogMutationSave();
    }
  });

  $('#btnDeleteTest')?.addEventListener('click', async () => {
    if (!ui.selectedId) {
      alert('삭제할 테스트를 선택해주세요.');
      return;
    }
    if (!confirm('정말 이 테스트 정의를 삭제할까요? 제출 기록은 유지됩니다.')) return;
    if (!beginCatalogMutationSave()) return;
    try {
      const ref = selectedTestRef();
      const cat = ref?.cat || TEST_CFG.categories[ui.category];
      if (!cat || !Array.isArray(cat.tests)) return;
      const deletedTestId = String(ui.selectedId);
      cat.tests = (cat.tests || []).filter(test => String(test.id) !== deletedTestId);
      ui.selectedId = '';
      await saveConfig([deletedTestId]);
      alert('삭제 완료');
      await loadConfigAndStats();
    } catch (e) {
      console.error(e);
      alert('삭제에 실패했습니다.');
    } finally {
      endCatalogMutationSave();
    }
  });

  $('#ruleGrid')?.addEventListener('change', e => {
    if (!e.target?.matches?.('.rule-check')) return;
    scheduleRulesAutosave();
  });

  $('#btnReloadStats')?.addEventListener('click', () => {
    if (catalogMutationControlsLocked()) return;
    loadStatsOnly();
  });
  $('#statRecent')?.addEventListener('change', () => {
    if (catalogMutationControlsLocked()) return;
    loadStatsOnly();
  });
}

window.addEventListener('DOMContentLoaded', () => {
  bindUI();
  initStatsDetailModal();
  loadConfigAndStats().catch(err => {
    console.error(err);
    alert('테스트 설정/통계 로드에 실패했습니다.');
  });
});
