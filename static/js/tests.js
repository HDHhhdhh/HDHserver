// /js/tests.js
// Test catalog management for admin `/tests`.
/* global fetch */

import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from './shared/search.js';

const $ = (sel) => document.querySelector(sel);
const CT = { 'Content-Type': 'application/json' };

const CATEGORY_DEFS = [
  { key: 'REVIEW', label: '복습 테스트', difficulties: ['상', '중상'] },
  { key: 'UNIT', label: '단원평가', difficulties: ['Lv.3', 'Lv.4', 'Lv.5', 'Lv.6'] },
  { key: 'SCHOOL_PAST', label: '학군지 기출', difficulties: ['상', '중상'] },
  { key: 'ILSAN_PAST', label: '일산 기출', difficulties: ['상', '중'] },
];
const CATEGORY_BY_KEY = Object.fromEntries(CATEGORY_DEFS.map(item => [item.key, item]));
const STATS_TYPE_LABELS = {
  REVIEW: '복테',
  SCHOOL_PAST: '학군지',
  ILSAN_PAST: '일산',
};
const SUBJECTS = ['공수1', '공수2', '대수', '미적분1', '미적분2', '기하', '확통'];
const STUDENT_LEVELS = ['하', '중', '중상', '상'];
const TERM_OPTIONS = ['중간고사', '기말고사'];

const DEFAULT_RULES = {
  REVIEW: defaultTwoBandRules(),
  SCHOOL_PAST: defaultTwoBandRules(),
  ILSAN_PAST: defaultIlsanRules(),
  UNIT: defaultUnitRules(),
};

let TEST_CFG = { categories: {} };
let TEST_STATS = null;
let TEST_STATS_DETAIL = null;
let ruleSaveTimer = null;
let ruleSaveInFlight = false;
let ruleSavePending = false;
let ruleSaveToastTimer = null;
const ui = {
  category: 'UNIT',
  subject: '공수1',
  difficulty: '',
  term: '',
  round: '',
  selectedId: '',
  statsCategory: 'UNIT',
  statsTestId: '',
  statsSearch: '',
  statsSort: 'default',
};

function isUnitCategory(categoryKey) {
  return String(categoryKey || '') === 'UNIT';
}

function isPastCategory(categoryKey) {
  return ['SCHOOL_PAST', 'ILSAN_PAST'].includes(String(categoryKey || ''));
}

function statsTypeLabel(def) {
  return STATS_TYPE_LABELS[String(def?.key || '')] || def?.label || '';
}

function normalizeTerm(value, name = '') {
  const raw = String(value || '').trim();
  const source = `${raw} ${name}`.replace(/\s+/g, '');
  if (/기말|final/i.test(source)) return '기말고사';
  if (/중간|mid/i.test(source)) return '중간고사';
  return raw;
}

function defaultTwoBandRules() {
  const out = {};
  SUBJECTS.forEach(subject => {
    out[subject] = {
      '상': ['상', '중상'],
      '중상': ['중', '하'],
    };
  });
  return out;
}

function defaultIlsanRules() {
  const out = {};
  SUBJECTS.forEach(subject => {
    out[subject] = {
      '상': ['상', '중상'],
      '중': ['중', '하'],
    };
  });
  return out;
}

function defaultUnitRules() {
  const out = {};
  SUBJECTS.forEach(subject => {
    out[subject] = {
      'Lv.3': ['하'],
      'Lv.4': ['중'],
      'Lv.5': ['중상'],
      'Lv.6': ['상'],
    };
  });
  return out;
}

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

function categoryKeyFrom(rawKey, label = '') {
  const raw = `${rawKey || ''} ${label || ''}`.toUpperCase();
  const ko = `${rawKey || ''} ${label || ''}`.replace(/\s+/g, '');
  if (raw.includes('REVIEW') || ko.includes('복습')) return 'REVIEW';
  if (raw.includes('SCHOOL') || ko.includes('학군지')) return 'SCHOOL_PAST';
  if (raw.includes('ILSAN') || ko.includes('일산')) return 'ILSAN_PAST';
  if (raw.includes('UNIT') || ko.includes('단원')) return 'UNIT';
  return String(rawKey || '').trim();
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
  if (r === '-') return '-';
  return /회/.test(r) ? r : `${r}회차`;
}

function editCategoryValue() {
  return categoryKeyFrom($('#cfgEditType')?.value || ui.category || 'UNIT');
}

function roundHelpText(categoryKey) {
  return isUnitCategory(categoryKey)
    ? '단원평가는 같은 이름의 시험을 다른 문제로 반복하는 세트 번호입니다.'
    : '복습테스트와 기출은 학생이 순서대로 보게 되는 시험 목록 순번입니다.';
}

function ensureConfig(raw) {
  const cfg = (raw && typeof raw === 'object') ? raw : {};
  if (!cfg.categories || typeof cfg.categories !== 'object') cfg.categories = {};

  CATEGORY_DEFS.forEach(def => {
    if (!cfg.categories[def.key] || typeof cfg.categories[def.key] !== 'object') {
      cfg.categories[def.key] = { label: def.label, tests: [] };
    }
    if (!Array.isArray(cfg.categories[def.key].tests)) cfg.categories[def.key].tests = [];
    cfg.categories[def.key].label = cfg.categories[def.key].label || def.label;
  });

  if (!cfg.autoAssignRules || typeof cfg.autoAssignRules !== 'object') cfg.autoAssignRules = {};
  CATEGORY_DEFS.forEach(def => {
    if (!cfg.autoAssignRules[def.key] || typeof cfg.autoAssignRules[def.key] !== 'object') {
      cfg.autoAssignRules[def.key] = {};
    }
    SUBJECTS.forEach(subject => {
      if (!cfg.autoAssignRules[def.key][subject] || typeof cfg.autoAssignRules[def.key][subject] !== 'object') {
        cfg.autoAssignRules[def.key][subject] = {};
      }
      if (def.key === 'ILSAN_PAST' && Array.isArray(cfg.autoAssignRules[def.key][subject]['중상'])) {
        const prev = cfg.autoAssignRules[def.key][subject]['중상'];
        const current = Array.isArray(cfg.autoAssignRules[def.key][subject]['중'])
          ? cfg.autoAssignRules[def.key][subject]['중']
          : [];
        cfg.autoAssignRules[def.key][subject]['중'] = Array.from(new Set([...current, ...prev].map(String)));
        delete cfg.autoAssignRules[def.key][subject]['중상'];
      }
      const defaults = DEFAULT_RULES[def.key]?.[subject] || {};
      Object.entries(defaults).forEach(([difficulty, levels]) => {
        if (!Array.isArray(cfg.autoAssignRules[def.key][subject][difficulty])) {
          cfg.autoAssignRules[def.key][subject][difficulty] = levels.slice();
        }
      });
    });
  });

  return cfg;
}

function normalizeTest(rawTest, rawCategoryKey, idx = 0) {
  const categoryKey = categoryKeyFrom(rawCategoryKey);
  const name = canonText(rawTest?.name || rawTest?.title || `테스트 ${idx + 1}`);
  const curriculum = normalizeSubject(rawTest?.curriculum || rawTest?.subject || ui.subject);
  return {
    ...(rawTest || {}),
    id: canonText(rawTest?.id) || `t_${categoryKey}_${Date.now()}_${idx}`,
    name,
    categoryKey,
    curriculum,
    difficulty: normalizeDifficulty(categoryKey, rawTest?.difficulty || rawTest?.level, name),
    term: isPastCategory(categoryKey) ? normalizeTerm(rawTest?.term || rawTest?.examTerm || rawTest?.examPeriod || rawTest?.exam_period, name) : '',
    round: normalizeRound(rawTest?.round || rawTest?.session || rawTest?.no, name),
    problems: Number.isFinite(+rawTest?.problems) ? Math.max(1, Number(rawTest.problems)) : 20,
    _catalogIndex: idx,
  };
}

function getCategoryTests(categoryKey = ui.category) {
  const cat = TEST_CFG.categories?.[categoryKey];
  if (!cat || !Array.isArray(cat.tests)) return [];
  return cat.tests.map((test, idx) => normalizeTest(test, categoryKey, idx));
}

function getVisibleTests() {
  return getCategoryTests(ui.category)
    .filter(test => normalizeSubject(test.curriculum) === ui.subject)
    .filter(test => !ui.difficulty || String(test.difficulty || '') === String(ui.difficulty))
    .filter(test => !isPastCategory(ui.category) || !ui.term || String(test.term || '') === String(ui.term))
    .filter(test => !isUnitCategory(ui.category) || !ui.round || String(test.round || '') === String(ui.round))
    .sort(compareTestsForList);
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

function selectedRawTest() {
  return selectedTestRef()?.test || null;
}

function parseAnswerSpec(text, problems) {
  if (Array.isArray(text)) return text.slice(0, problems);
  const s = String(text ?? '').trim();
  if (!s) return new Array(problems).fill('');
  let arr;
  if (/[\s,]/.test(s)) arr = s.split(/[\s,]+/).map(v => v.trim()).filter(Boolean);
  else arr = s.split('').map(v => v.trim()).filter(Boolean);
  if (arr.length > problems) arr = arr.slice(0, problems);
  if (arr.length < problems) arr = arr.concat(new Array(problems - arr.length).fill(''));
  return arr;
}

function parseAnswerSpec3(text, problems) {
  const lines = String(text ?? '').replace(/\r\n/g, '\n').split('\n').slice(0, 3);
  if (lines.length <= 1) {
    const base = parseAnswerSpec(lines[0] || '', problems);
    return { '1': base, '2': base.slice(), '3': base.slice() };
  }
  const one = parseAnswerSpec(lines[0] || '', problems);
  return {
    '1': one,
    '2': parseAnswerSpec(lines[1] || '', problems),
    '3': parseAnswerSpec(lines[2] || '', problems),
  };
}

function answerKeysToText(test) {
  return answerKeyForTest(test).join(' ');
}

function answerKeyForTest(test) {
  const p = Number(test?.problems || 0) || 0;
  const round = String(test?.round || '1').trim() || '1';
  if (test?.answerKeys && typeof test.answerKeys === 'object') {
    const exact = Array.isArray(test.answerKeys[round]) ? test.answerKeys[round] : null;
    if (exact) return parseAnswerSpec(exact, p);
    const firstKey = Object.keys(test.answerKeys).find(key => Array.isArray(test.answerKeys[key]));
    if (firstKey) return parseAnswerSpec(test.answerKeys[firstKey], p);
  }
  if (test?.answerKey != null) {
    return Array.isArray(test.answerKey) ? parseAnswerSpec(test.answerKey, p) : parseAnswerSpec(test.answerKey, p);
  }
  return new Array(p).fill('');
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

function roundSortValue(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 9999;
}

function termSortValue(value) {
  const term = normalizeTerm(value);
  const idx = TERM_OPTIONS.indexOf(term);
  return idx >= 0 ? idx : 9999;
}

function testOrderValue(test) {
  const raw = test?.sortOrder ?? test?.sourceOrder ?? test?.order ?? test?.sourceIndex ?? test?._catalogIndex;
  const n = Number(raw);
  return Number.isFinite(n) ? n : 999999;
}

function compareTestsForList(a, b) {
  const difficulty = String(a.difficulty).localeCompare(String(b.difficulty), 'ko');
  if (difficulty) return difficulty;
  if (isPastCategory(ui.category)) {
    return termSortValue(a.term || '') - termSortValue(b.term || '') ||
      testOrderValue(a) - testOrderValue(b) ||
      roundSortValue(a.round || 0) - roundSortValue(b.round || 0) ||
      String(a.name).localeCompare(String(b.name), 'ko');
  }
  if (isUnitCategory(ui.category)) {
    return roundSortValue(a.round || 0) - roundSortValue(b.round || 0) ||
      testOrderValue(a) - testOrderValue(b) ||
      String(a.name).localeCompare(String(b.name), 'ko');
  }
  return testOrderValue(a) - testOrderValue(b) ||
    roundSortValue(a.round || 0) - roundSortValue(b.round || 0) ||
    String(a.name).localeCompare(String(b.name), 'ko');
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

function updateChrome(selected = null) {
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
  if ($('#editorSelectionLabel')) $('#editorSelectionLabel').textContent = selected?.name || '선택된 테스트 없음';
}

function renderTestList() {
  const listEl = $('#testList');
  if (!listEl) return;

  const tests = getVisibleTests();
  const selected = tests.find(test => test.id === ui.selectedId) || null;
  updateChrome(selected);

  if (!tests.length) {
    listEl.innerHTML = `<div style="font-size:12px; opacity:.7; padding:4px;">등록된 테스트가 없습니다. 새 테스트를 추가하세요.</div>`;
    return;
  }

  listEl.innerHTML = renderGroupedTestList(tests);

  listEl.querySelectorAll('button[data-id]').forEach(btn => {
    btn.addEventListener('click', () => {
      ui.selectedId = btn.dataset.id || '';
      renderTestList();
      fillEditor();
    });
  });
}

function renderGroupedTestList(tests) {
  const groups = new Map();
  tests.forEach(test => {
    const key = isPastCategory(ui.category)
      ? `${test.term || '-'}|||${test.difficulty || '-'}|||`
      : isUnitCategory(ui.category)
      ? `${test.difficulty || '-'}|||${test.round || '-'}`
      : `${test.difficulty || '-'}|||`;
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
          ${items.map(test => renderTestButton(test)).join('')}
        </div>
      </section>
    `;
  }).join('');
}

function renderTestButton(test) {
  const stat = statForTest(test);
  const statBadge = stat?.count ? `<span class="small"> · ${escapeHtml(stat.avg_pct)}% / ${escapeHtml(stat.count)}명</span>` : '';
  const active = test.id === ui.selectedId ? 'active' : '';
  return `
    <button type="button" data-id="${escapeAttr(test.id)}" class="${active}">
      ${escapeHtml(test.name)}
      <span class="small">(${escapeHtml(test.problems)}문항)</span>
      ${statBadge}
    </button>
  `;
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
    updateChrome(null);
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
  updateChrome(test);
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
                    <input type="checkbox" class="rule-check"
                      data-category="${escapeAttr(def.key)}"
                      data-subject="${escapeAttr(subject)}"
                      data-difficulty="${escapeAttr(difficulty)}"
                      data-level="${escapeAttr(level)}"
                      ${levels.includes(level) ? 'checked' : ''}>
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

async function saveRulesFromGrid() {
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
  ruleSaveTimer = setTimeout(() => {
    ruleSaveTimer = null;
    saveRulesFromGrid();
  }, 350);
}

async function saveConfig() {
  const res = await fetch('/api/tests-config', {
    method: 'POST',
    headers: CT,
    body: JSON.stringify(TEST_CFG),
  });
  if (!res.ok) throw new Error(`tests-config save failed: ${res.status}`);
}

function csvCell(value) {
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function downloadCsvTemplate() {
  const rows = [
    ['분류', '과목', '난이도', '고사', '회차', '시험명', '문항수', '정답', '1회차정답', '2회차정답', '3회차정답'],
    ['복습 테스트', '대수', '상', '', '1', '대수 복습 상 1회차', '20', '1 2 3 4', '', '', ''],
    ['단원평가', '공수1', 'Lv.4', '', '1', '원의 방정식 Lv.4', '20', '', '1,3,4,2', '1,3,4,2', '1,3,4,2'],
    ['학군지 기출', '공수1', '상', '중간고사', '1', '학군지 기출 공수1 중간고사 상 1회차', '20', '1 2 3 4', '', '', ''],
    ['일산 기출', '대수', '중', '기말고사', '1', '일산 기출 대수 기말고사 중 1회차', '20', '1 2 3 4', '', '', ''],
  ];
  const csv = `\uFEFF${rows.map(row => row.map(csvCell).join(',')).join('\r\n')}`;
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

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const next = text[i + 1];
    if (quoted) {
      if (ch === '"' && next === '"') {
        cell += '"';
        i += 1;
      } else if (ch === '"') {
        quoted = false;
      } else {
        cell += ch;
      }
      continue;
    }

    if (ch === '"') {
      quoted = true;
    } else if (ch === ',') {
      row.push(cell);
      cell = '';
    } else if (ch === '\n') {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else if (ch !== '\r') {
      cell += ch;
    }
  }

  row.push(cell);
  rows.push(row);
  return rows.filter(items => items.some(item => String(item || '').trim()));
}

function headerKey(value) {
  const s = String(value || '').replace(/^\uFEFF/, '').trim().toLowerCase().replace(/\s+/g, '');
  const aliases = {
    id: 'id',
    testid: 'id',
    테스트id: 'id',
    분류: 'category',
    구분: 'category',
    category: 'category',
    type: 'category',
    과목: 'subject',
    subject: 'subject',
    curriculum: 'subject',
    course: 'subject',
    난이도: 'difficulty',
    레벨: 'difficulty',
    difficulty: 'difficulty',
    level: 'difficulty',
    고사: 'term',
    시험기간: 'term',
    학기고사: 'term',
    term: 'term',
    examterm: 'term',
    examperiod: 'term',
    exam_period: 'term',
    period: 'term',
    회차: 'round',
    round: 'round',
    session: 'round',
    no: 'round',
    시험명: 'name',
    테스트명: 'name',
    name: 'name',
    title: 'name',
    순번: 'sourceOrder',
    정렬순서: 'sourceOrder',
    sourceorder: 'sourceOrder',
    source_order: 'sourceOrder',
    sortorder: 'sourceOrder',
    sort_order: 'sourceOrder',
    sourceid: 'sourceId',
    source_id: 'sourceId',
    문항수: 'problems',
    문제수: 'problems',
    problems: 'problems',
    '1회차정답': 'answers1',
    '1회정답': 'answers1',
    answer1: 'answers1',
    answers1: 'answers1',
    '2회차정답': 'answers2',
    '2회정답': 'answers2',
    answer2: 'answers2',
    answers2: 'answers2',
    '3회차정답': 'answers3',
    '3회정답': 'answers3',
    answer3: 'answers3',
    answers3: 'answers3',
    정답: 'answers',
    answers: 'answers',
    answer: 'answers',
    answersjson: 'answersJson',
    answers_json: 'answersJson',
    answerkeyjson: 'answersJson',
    answer_key_json: 'answersJson',
  };
  return aliases[s] || s;
}

function rowObject(headers, cells) {
  const out = {};
  headers.forEach((header, idx) => {
    if (!header) return;
    out[header] = String(cells[idx] ?? '').trim();
  });
  return out;
}

function hasRoundAnswerColumns(row) {
  return ['1', '2', '3'].some(round => String(row[`answers${round}`] || '').trim());
}

function answerKeyFromCsvRow(row, round, problems) {
  const direct = String(row[`answers${round}`] || '').trim();
  if (direct) return parseAnswerSpec(direct, problems);
  const jsonText = String(row.answersJson || '').trim();
  if (jsonText) {
    try {
      const parsed = JSON.parse(jsonText);
      if (Array.isArray(parsed)) return parseAnswerSpec(parsed, problems);
    } catch (err) {
      console.warn('[tests] answers_json parse failed', err);
    }
  }
  return parseAnswerSpec(row.answers || '', problems);
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
    const rounds = categoryKey === 'UNIT' && hasRoundAnswerColumns(row) ? ['1', '2', '3'] : [csvRound];

    const cat = TEST_CFG.categories[categoryKey] = TEST_CFG.categories[categoryKey] || { label: def.label, tests: [] };
    if (!Array.isArray(cat.tests)) cat.tests = [];
    cat.label = cat.label || def.label;

    rounds.forEach(round => {
      const answerKey = answerKeyFromCsvRow(row, round, problems);
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
  TEST_STATS_DETAIL = null;
  ui.statsTestId = '';
  TEST_CFG = ensureConfig(await fetchJSONSafe('/api/tests-config').catch(() => ({ categories: {} })));

  const typeSel = $('#cfgType');
  const curSel = $('#cfgCur');
  if (typeSel) typeSel.value = ui.category;
  if (curSel) curSel.value = ui.subject;

  try {
    const recent = Number($('#statRecent')?.value || '30') || 30;
    TEST_STATS = await fetchJSONSafe(`/api/tests-stats?recent_days=${recent}&include_wrong=0`);
  } catch {
    TEST_STATS = null;
  }

  updateSubjectOptions();
  updateListDifficultyOptions();
  updateTermOptions();
  updateRoundOptions();
  updateEditCategoryOptions(ui.category);
  renderTestList();
  fillEditor();
  renderRules();
  renderStatsSummary();
  renderStatsTable();
  renderStatsDetail();
}

function renderStatsSummary() {
  const box = $('#statsSummary');
  if (!box) return;
  const summary = TEST_STATS?.summary || {};
  const cards = CATEGORY_DEFS.map(def => {
    const row = summary[def.key];
    const count = getCategoryTests(def.key).length;
    const metric = row?.count ? `${Number(row.avg_pct || 0).toFixed(1)}%` : `${count}개`;
    const meta = row?.count ? `응시 ${row.count}건` : '등록 테스트';
    const active = ui.statsCategory === def.key ? ' is-active' : '';
    return `
      <button type="button" class="summary-card${active}" data-type="${escapeAttr(def.key)}" data-stats-category="${escapeAttr(def.key)}">
        <div class="summary-label">${escapeHtml(def.label)}</div>
        <div class="summary-value">${escapeHtml(metric)}</div>
        <div class="summary-meta">${escapeHtml(meta)}</div>
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

function fmtPct(value) {
  return (typeof value === 'number' && Number.isFinite(value)) ? `${value.toFixed(1)}%` : '-';
}

function fmtNumber(value) {
  return (typeof value === 'number' && Number.isFinite(value)) ? value.toFixed(1) : '-';
}

function statsSignature(test) {
  return [
    test?.categoryKey || ui.statsCategory || '',
    test?.curriculum || '',
    canonText(test?.name),
    isPastCategory(test?.categoryKey || ui.statsCategory) ? normalizeTerm(test?.term || test?.examTerm || '', test?.name) : '',
    String(test?.round || '').trim(),
  ].join('\u241f');
}

function statForTest(test) {
  const byId = TEST_STATS?.by_test_id || {};
  if (test?.id && byId[test.id]) return byId[test.id];
  const bySignature = TEST_STATS?.by_test_signature || {};
  const sig = statsSignature(test);
  if (sig && bySignature[sig]) return bySignature[sig];
  return TEST_STATS?.by_test?.[canonText(test?.name)] || null;
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

function defaultStatsCompare(a, b) {
  return String(a.curriculum || '').localeCompare(String(b.curriculum || ''), 'ko') ||
    String(a.difficulty || '').localeCompare(String(b.difficulty || ''), 'ko') ||
    termSortValue(a.term || a.examTerm || '') - termSortValue(b.term || b.examTerm || '') ||
    roundSortValue(a.round || 0) - roundSortValue(b.round || 0) ||
    String(a.name || '').localeCompare(String(b.name || ''), 'ko');
}

function statsCount(row) {
  const count = Number(row?.stat?.count || 0);
  return Number.isFinite(count) ? count : 0;
}

function statsAvg(row, emptyValue) {
  const avg = Number(row?.stat?.avg_pct);
  return Number.isFinite(avg) ? avg : emptyValue;
}

function statsSearchText(row) {
  return searchKeyForText([
    row.typeLabel,
    row.typeSearchLabel,
    row.curriculum,
    row.name,
    row.difficulty,
    row.term,
    row.examTerm,
    roundLabel(row.round || ''),
    row.problems ? `${row.problems}문항` : '',
  ].map(canonText).join(' '));
}

function compareStatsRows(a, b) {
  switch (ui.statsSort) {
    case 'name':
      return String(a.name || '').localeCompare(String(b.name || ''), 'ko') || defaultStatsCompare(a, b);
    case 'taken_desc':
      return statsCount(b) - statsCount(a) || defaultStatsCompare(a, b);
    case 'taken_asc':
      return statsCount(a) - statsCount(b) || defaultStatsCompare(a, b);
    case 'avg_desc':
      return statsAvg(b, -1) - statsAvg(a, -1) || defaultStatsCompare(a, b);
    case 'avg_asc':
      return statsAvg(a, 101) - statsAvg(b, 101) || defaultStatsCompare(a, b);
    case 'round':
      return roundSortValue(a.round || 0) - roundSortValue(b.round || 0) || defaultStatsCompare(a, b);
    default:
      return defaultStatsCompare(a, b);
  }
}

function renderStatsTable() {
  const tbody = $('#statsTable tbody');
  if (!tbody) return;
  syncStatsControls();
  const def = CATEGORY_BY_KEY[ui.statsCategory] || CATEGORY_BY_KEY.UNIT;
  const queryText = ui.statsSearch || '';
  const rows = getCategoryTests(def.key).map(test => ({
    ...test,
    typeLabel: statsTypeLabel(def),
    typeSearchLabel: def.label,
    stat: statForTest(test),
  }))
    .filter(row => matchesSearchKey(statsSearchText(row), queryText))
    .sort(compareStatsRows);

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
          <span class="stat-main">${escapeHtml(row.name)}</span>
          <span class="stat-sub">${escapeHtml([isPastCategory(row.categoryKey) ? (row.term || row.examTerm || '') : '', row.problems ? `${row.problems}문항` : ''].filter(Boolean).join(' · '))}</span>
        </div>
      </td>
      <td><span class="level-pill">${escapeHtml(row.difficulty || '-')}</span></td>
      <td>${escapeHtml(roundLabel(row.round || '-'))}</td>
      <td>${escapeHtml(row.stat?.count || 0)}</td>
      <td>${escapeHtml(fmtPct(row.stat?.avg_pct))}</td>
    </tr>
  `).join('');

  tbody.querySelectorAll('[data-stat-test-id]').forEach(rowEl => {
    rowEl.addEventListener('click', () => {
      const testId = rowEl.dataset.statTestId || '';
      const row = rows.find(item => item.id === testId);
      ui.statsTestId = testId;
      TEST_STATS_DETAIL = null;
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

function renderStatsDetail(test = null, fetchDetail = false) {
  const host = $('#statsDetail');
  if (!host) return;

  const selected = test || getCategoryTests(ui.statsCategory).find(item => item.id === ui.statsTestId);
  if (!selected) {
    host.innerHTML = `
      <div class="stats-detail-empty">
        통계 표에서 시험을 선택하면 평균, 표준편차, 최고/최저/중앙값과 학생별 점수를 볼 수 있습니다.
      </div>
    `;
    return;
  }

  const stat = statForTest(selected) || {};
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

  const records = Array.isArray(TEST_STATS_DETAIL?.records) ? TEST_STATS_DETAIL.records : [];
  const studentRows = records.map(rec => `
    <tr>
      <td style="text-align:left;">${escapeHtml(rec.studentName || rec.sid || '-')}</td>
      <td>${escapeHtml(rec.level || '-')}</td>
      <td>${escapeHtml(fmtPct(rec.pct))}</td>
      <td>${escapeHtml(`${rec.correct ?? '-'} / ${rec.total ?? '-'}`)}</td>
      <td style="text-align:left;">${escapeHtml((rec.createdAt || '').slice(0, 10) || '-')}</td>
    </tr>
  `).join('');

  host.innerHTML = `
    <section class="stats-detail-panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">${escapeHtml(selected.name)}</div>
          <div class="panel-subtitle">${escapeHtml([selected.curriculum || '-', isPastCategory(selected.categoryKey) ? (selected.term || selected.examTerm || '') : '', selected.difficulty || '-', roundLabel(selected.round || '-')].filter(Boolean).join(' · '))}</div>
        </div>
      </div>
      <div class="detail-metrics">
        ${detailMetric('응시', stat.count || 0)}
        ${detailMetric('평균', fmtPct(stat.avg_pct))}
        ${detailMetric('표준편차', fmtNumber(stat.stddev_pct))}
        ${detailMetric('중앙값', fmtPct(stat.median_pct))}
        ${detailMetric('최대', fmtPct(stat.max_pct))}
        ${detailMetric('최소', fmtPct(stat.min_pct))}
      </div>
      <div class="panel-table-wrap">
        <table class="stats-table detail-student-table">
          <thead>
            <tr>
              <th>학생</th>
              <th>레벨</th>
              <th>점수</th>
              <th>정답</th>
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
  $('#cfgType')?.addEventListener('change', e => {
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

  $('#cfgTermFilter')?.addEventListener('change', e => {
    ui.term = String(e.target.value || '').trim();
    ui.selectedId = '';
    renderTestList();
    fillEditor();
  });

  $('#statSearch')?.addEventListener('input', e => {
    ui.statsSearch = String(e.target.value || '').trim();
    ui.statsTestId = '';
    TEST_STATS_DETAIL = null;
    renderStatsTable();
    renderStatsDetail();
  });

  $('#statSort')?.addEventListener('change', e => {
    ui.statsSort = String(e.target.value || 'default');
    renderStatsTable();
  });

  $('#cfgSubject')?.addEventListener('change', e => {
    const raw = selectedRawTest();
    if (raw) raw.curriculum = normalizeSubject(e.target.value);
    renderTestList();
  });

  $('#btnCsvTemplate')?.addEventListener('click', downloadCsvTemplate);

  $('#btnImportCsv')?.addEventListener('click', () => {
    const input = $('#csvFile');
    if (!input) return;
    input.value = '';
    input.click();
  });

  $('#csvFile')?.addEventListener('change', async (e) => {
    const file = e.target?.files?.[0];
    if (!file) return;
    try {
      await importTestsFromCsv(file);
    } catch (err) {
      console.error(err);
      alert(err?.message || 'CSV 가져오기에 실패했습니다.');
    } finally {
      e.target.value = '';
    }
  });

  $('#btnNewTest')?.addEventListener('click', () => {
    const cat = TEST_CFG.categories[ui.category] = TEST_CFG.categories[ui.category] || { label: categoryLabel(ui.category), tests: [] };
    cat.label = cat.label || categoryLabel(ui.category);
    if (!Array.isArray(cat.tests)) cat.tests = [];
    const def = CATEGORY_BY_KEY[ui.category] || CATEGORY_BY_KEY.UNIT;
    const difficulty = def.difficulties.includes(ui.difficulty) ? ui.difficulty : (def.difficulties[0] || '');
    const term = isPastCategory(ui.category) ? (ui.term || TERM_OPTIONS[0] || '') : '';
    const round = isUnitCategory(ui.category) ? (ui.round || '1') : nextRoundFor(ui.category, ui.subject, difficulty);
    const id = `t_${ui.category.toLowerCase()}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const test = {
      id,
      name: `${categoryLabel(ui.category)} ${ui.subject} ${term ? `${term} ` : ''}${difficulty} ${round}회차`,
      category: ui.category,
      categoryKey: ui.category,
      problems: 20,
      curriculum: ui.subject,
      difficulty,
      round,
      answerKeys: { [round]: [] },
      answerKey: [],
    };
    if (term) {
      test.term = term;
      test.examTerm = term;
    }
    cat.tests.push(test);
    ui.selectedId = id;
    ui.difficulty = difficulty;
    ui.term = term;
    ui.round = isUnitCategory(ui.category) ? round : '';
    updateListDifficultyOptions();
    updateTermOptions();
    updateRoundOptions();
    renderTestList();
    fillEditor();
  });

  $('#btnSaveTest')?.addEventListener('click', async () => {
    const targetCategory = editCategoryValue();
    const targetDef = CATEGORY_BY_KEY[targetCategory] || CATEGORY_BY_KEY.UNIT;
    const cat = TEST_CFG.categories[targetCategory] = TEST_CFG.categories[targetCategory] || { label: targetDef.label, tests: [] };
    if (!cat) return;
    cat.label = cat.label || targetDef.label;
    if (!Array.isArray(cat.tests)) cat.tests = [];
    const name = canonText($('#cfgName')?.value || '');
    const problems = Math.max(1, Number($('#cfgProblems')?.value || 0));
    const subject = normalizeSubject($('#cfgSubject')?.value || ui.subject);
    const difficulty = String($('#cfgDifficulty')?.value || '').trim();
    const term = isPastCategory(targetCategory) ? normalizeTerm($('#cfgTerm')?.value || ui.term, name) : '';
    const round = normalizeRound($('#cfgRound')?.value || '1');
    const answers = $('#cfgAnswers')?.value || '';

    if (!name) {
      alert('테스트명을 입력해주세요.');
      return;
    }

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
    test.answerKey = parseAnswerSpec(answers, problems);
    test.answerKeys = { [round]: test.answerKey };

    try {
      await saveConfig();
      alert('저장 완료');
      ui.category = targetCategory;
      ui.subject = subject;
      ui.difficulty = difficulty;
      ui.term = isPastCategory(targetCategory) ? term : '';
      ui.round = isUnitCategory(targetCategory) ? round : '';
      $('#cfgType') && ($('#cfgType').value = targetCategory);
      $('#cfgCur') && ($('#cfgCur').value = subject);
      await loadConfigAndStats();
    } catch (e) {
      console.error(e);
      alert('저장에 실패했습니다.');
    }
  });

  $('#btnDeleteTest')?.addEventListener('click', async () => {
    if (!ui.selectedId) {
      alert('삭제할 테스트를 선택해주세요.');
      return;
    }
    if (!confirm('정말 이 테스트 정의를 삭제할까요? 제출 기록은 유지됩니다.')) return;

    const ref = selectedTestRef();
    const cat = ref?.cat || TEST_CFG.categories[ui.category];
    if (!cat || !Array.isArray(cat.tests)) return;
    cat.tests = (cat.tests || []).filter(test => String(test.id) !== String(ui.selectedId));
    ui.selectedId = '';
    try {
      await saveConfig();
      alert('삭제 완료');
      await loadConfigAndStats();
    } catch (e) {
      console.error(e);
      alert('삭제에 실패했습니다.');
    }
  });

  $('#ruleGrid')?.addEventListener('change', e => {
    if (!e.target?.matches?.('.rule-check')) return;
    scheduleRulesAutosave();
  });

  $('#btnReloadStats')?.addEventListener('click', () => loadConfigAndStats());
  $('#statRecent')?.addEventListener('change', () => loadConfigAndStats());
}

window.addEventListener('DOMContentLoaded', () => {
  bindUI();
  loadConfigAndStats().catch(err => {
    console.error(err);
    alert('테스트 설정/통계 로드에 실패했습니다.');
  });
});
