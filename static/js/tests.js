// /js/tests.js
// Test catalog management for admin `/tests`.
/* global fetch */

const $ = (sel) => document.querySelector(sel);
const CT = { 'Content-Type': 'application/json' };

const CATEGORY_DEFS = [
  { key: 'REVIEW', label: '복습 테스트', difficulties: ['상', '중상'] },
  { key: 'UNIT', label: '단원평가', difficulties: ['Lv.3', 'Lv.4', 'Lv.5', 'Lv.6'] },
  { key: 'SCHOOL_PAST', label: '학군지 기출', difficulties: ['상', '중상'] },
  { key: 'ILSAN_PAST', label: '일산 기출', difficulties: ['상', '중상'] },
];
const CATEGORY_BY_KEY = Object.fromEntries(CATEGORY_DEFS.map(item => [item.key, item]));
const SUBJECTS = ['공수1', '공수2', '대수', '미적분1', '미적분2', '기하', '확통'];
const STUDENT_LEVELS = ['하', '중', '중상', '상'];

const DEFAULT_RULES = {
  REVIEW: defaultTwoBandRules(),
  SCHOOL_PAST: defaultTwoBandRules(),
  ILSAN_PAST: defaultTwoBandRules(),
  UNIT: defaultUnitRules(),
};

let TEST_CFG = { categories: {} };
let TEST_STATS = null;
const ui = {
  category: 'UNIT',
  subject: '공수1',
  selectedId: '',
};

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
    round: normalizeRound(rawTest?.round || rawTest?.session || rawTest?.no, name),
    problems: Number.isFinite(+rawTest?.problems) ? Math.max(1, Number(rawTest.problems)) : 20,
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
    .sort((a, b) =>
      String(a.difficulty).localeCompare(String(b.difficulty), 'ko') ||
      Number(a.round || 0) - Number(b.round || 0) ||
      String(a.name).localeCompare(String(b.name), 'ko')
    );
}

function selectedRawTest() {
  const cat = TEST_CFG.categories?.[ui.category];
  if (!cat || !Array.isArray(cat.tests)) return null;
  return cat.tests.find(test => String(test.id) === String(ui.selectedId)) || null;
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
  const p = Number(test?.problems || 0) || 0;
  if (test?.answerKeys && typeof test.answerKeys === 'object') {
    const a1 = Array.isArray(test.answerKeys['1']) ? test.answerKeys['1'] : new Array(p).fill('');
    const a2 = Array.isArray(test.answerKeys['2']) ? test.answerKeys['2'] : a1;
    const a3 = Array.isArray(test.answerKeys['3']) ? test.answerKeys['3'] : a1;
    return [a1.join(' '), a2.join(' '), a3.join(' ')].join('\n').trimEnd();
  }
  if (test?.answerKey != null) {
    const arr = Array.isArray(test.answerKey) ? test.answerKey : parseAnswerSpec(test.answerKey, p);
    return arr.join(' ');
  }
  return '';
}

function updateDifficultyOptions() {
  const sel = $('#cfgDifficulty');
  if (!sel) return;
  const def = CATEGORY_BY_KEY[ui.category] || CATEGORY_BY_KEY.UNIT;
  sel.innerHTML = def.difficulties.map(diff => `<option value="${escapeAttr(diff)}">${escapeHtml(diff)}</option>`).join('');
}

function updateSubjectOptions() {
  const editor = $('#cfgSubject');
  if (editor) {
    editor.innerHTML = SUBJECTS.map(subject => `<option value="${escapeAttr(subject)}">${escapeHtml(subject)}</option>`).join('');
  }
}

function updateChrome(selected = null) {
  const visible = getVisibleTests();
  const total = CATEGORY_DEFS.reduce((sum, def) => sum + getCategoryTests(def.key).length, 0);

  if ($('#testsTotalPill')) $('#testsTotalPill').textContent = `${total}개`;
  if ($('#testsScopeLabel')) $('#testsScopeLabel').textContent = `${categoryLabel(ui.category)} · ${ui.subject}`;
  if ($('#visibleTestsMeta')) $('#visibleTestsMeta').textContent = `현재 목록 ${visible.length}개`;
  if ($('#testsRangeLabel')) $('#testsRangeLabel').textContent = `${categoryLabel(ui.category)} 규칙`;
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

  listEl.innerHTML = tests.map(test => {
    const stat = TEST_STATS?.by_test?.[canonText(test.name)];
    const statBadge = stat?.count ? `<span class="small"> · ${escapeHtml(stat.avg_pct)}% / ${escapeHtml(stat.count)}명</span>` : '';
    const active = test.id === ui.selectedId ? 'active' : '';
    return `
      <button type="button" data-id="${escapeAttr(test.id)}" class="${active}">
        ${escapeHtml(test.name)}
        <span class="small">(${escapeHtml(test.difficulty)} · ${escapeHtml(test.round)}회차 · ${escapeHtml(test.problems)}문항)</span>
        ${statBadge}
      </button>
    `;
  }).join('');

  listEl.querySelectorAll('button[data-id]').forEach(btn => {
    btn.addEventListener('click', () => {
      ui.selectedId = btn.dataset.id || '';
      renderTestList();
      fillEditor();
    });
  });
}

function fillEditor() {
  updateSubjectOptions();
  updateDifficultyOptions();

  const raw = selectedRawTest();
  const test = raw ? normalizeTest(raw, ui.category) : null;
  if (!test) {
    $('#cfgSubject') && ($('#cfgSubject').value = ui.subject);
    $('#cfgDifficulty') && ($('#cfgDifficulty').value = (CATEGORY_BY_KEY[ui.category]?.difficulties?.[0] || ''));
    $('#cfgRound') && ($('#cfgRound').value = '1');
    $('#cfgName') && ($('#cfgName').value = '');
    $('#cfgProblems') && ($('#cfgProblems').value = '');
    $('#cfgAnswers') && ($('#cfgAnswers').value = '');
    updateChrome(null);
    return;
  }

  if ($('#cfgSubject')) $('#cfgSubject').value = test.curriculum;
  if ($('#cfgDifficulty')) $('#cfgDifficulty').value = test.difficulty;
  if ($('#cfgRound')) $('#cfgRound').value = test.round || '1';
  if ($('#cfgName')) $('#cfgName').value = test.name || '';
  if ($('#cfgProblems')) $('#cfgProblems').value = test.problems || '';
  if ($('#cfgAnswers')) $('#cfgAnswers').value = answerKeysToText(test);
  updateChrome(test);
}

function renderRules() {
  const host = $('#ruleGrid');
  if (!host) return;
  const def = CATEGORY_BY_KEY[ui.category] || CATEGORY_BY_KEY.UNIT;
  const rules = TEST_CFG.autoAssignRules?.[ui.category] || {};

  host.innerHTML = `
    <table class="stats-table" style="min-width:860px;margin:0">
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
  `;
}

function readRulesFromGrid() {
  const def = CATEGORY_BY_KEY[ui.category] || CATEGORY_BY_KEY.UNIT;
  TEST_CFG.autoAssignRules = TEST_CFG.autoAssignRules || {};
  TEST_CFG.autoAssignRules[ui.category] = TEST_CFG.autoAssignRules[ui.category] || {};

  SUBJECTS.forEach(subject => {
    TEST_CFG.autoAssignRules[ui.category][subject] = TEST_CFG.autoAssignRules[ui.category][subject] || {};
    def.difficulties.forEach(difficulty => {
      const levels = Array.from(document.querySelectorAll(`.rule-check[data-subject="${CSS.escape(subject)}"][data-difficulty="${CSS.escape(difficulty)}"]:checked`))
        .map(input => input.dataset.level)
        .filter(Boolean);
      TEST_CFG.autoAssignRules[ui.category][subject][difficulty] = levels;
    });
  });
}

async function saveConfig() {
  const res = await fetch('/api/tests-config', {
    method: 'POST',
    headers: CT,
    body: JSON.stringify(TEST_CFG),
  });
  if (!res.ok) throw new Error(`tests-config save failed: ${res.status}`);
}

async function loadConfigAndStats() {
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
  updateDifficultyOptions();
  renderTestList();
  fillEditor();
  renderRules();
  renderStatsSummary();
  renderStatsTable();
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
    return `
      <article class="summary-card" data-type="${escapeAttr(def.key)}">
        <div class="summary-label">${escapeHtml(def.label)}</div>
        <div class="summary-value">${escapeHtml(metric)}</div>
        <div class="summary-meta">${escapeHtml(meta)}</div>
      </article>
    `;
  });
  box.innerHTML = cards.join('');
}

function fmtPct(value) {
  return (typeof value === 'number' && Number.isFinite(value)) ? `${value.toFixed(1)}%` : '-';
}

function renderStatsTable() {
  const tbody = $('#statsTable tbody');
  if (!tbody) return;
  const stats = TEST_STATS?.by_test || {};
  const rows = CATEGORY_DEFS.flatMap(def => getCategoryTests(def.key).map(test => ({
    ...test,
    typeLabel: def.label,
    stat: stats[canonText(test.name)] || null,
  })));

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-cell">등록된 테스트가 없습니다.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(row => `
    <tr class="data-row">
      <td style="text-align:left;"><span class="type-pill" data-type="${escapeAttr(row.categoryKey)}">${escapeHtml(row.typeLabel)}</span></td>
      <td style="text-align:left;">${escapeHtml(row.curriculum || '-')}</td>
      <td style="text-align:left;">
        <div class="stat-title">
          <span class="stat-main">${escapeHtml(row.name)}</span>
          <span class="stat-sub">${escapeHtml(row.difficulty)} · ${escapeHtml(row.round)}회차</span>
        </div>
      </td>
      <td><span class="level-pill">${escapeHtml(row.difficulty || '-')}</span></td>
      <td>${escapeHtml(row.stat?.count || 0)}</td>
      <td>${escapeHtml(fmtPct(row.stat?.avg_pct))}</td>
      <td>${escapeHtml(fmtPct(row.stat?.min_pct))}</td>
      <td>${escapeHtml(fmtPct(row.stat?.max_pct))}</td>
    </tr>
  `).join('');
}

function bindUI() {
  $('#cfgType')?.addEventListener('change', e => {
    ui.category = e.target.value || 'UNIT';
    ui.selectedId = '';
    updateDifficultyOptions();
    renderTestList();
    fillEditor();
    renderRules();
    renderStatsSummary();
    renderStatsTable();
  });

  $('#cfgCur')?.addEventListener('change', e => {
    ui.subject = normalizeSubject(e.target.value);
    ui.selectedId = '';
    renderTestList();
    fillEditor();
    renderRules();
  });

  $('#cfgSubject')?.addEventListener('change', e => {
    const raw = selectedRawTest();
    if (raw) raw.curriculum = normalizeSubject(e.target.value);
    renderTestList();
  });

  $('#btnNewTest')?.addEventListener('click', () => {
    const cat = TEST_CFG.categories[ui.category];
    const def = CATEGORY_BY_KEY[ui.category] || CATEGORY_BY_KEY.UNIT;
    const difficulty = def.difficulties[0] || '';
    const round = String(getVisibleTests().length + 1);
    const id = `t_${ui.category.toLowerCase()}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const test = {
      id,
      name: `${categoryLabel(ui.category)} ${ui.subject} ${difficulty} ${round}회차`,
      problems: 20,
      curriculum: ui.subject,
      difficulty,
      round,
      answerKeys: { '1': [], '2': [], '3': [] },
      answerKey: [],
    };
    cat.tests.push(test);
    ui.selectedId = id;
    renderTestList();
    fillEditor();
  });

  $('#btnSaveTest')?.addEventListener('click', async () => {
    const cat = TEST_CFG.categories[ui.category];
    if (!cat) return;
    const name = canonText($('#cfgName')?.value || '');
    const problems = Math.max(1, Number($('#cfgProblems')?.value || 0));
    const subject = normalizeSubject($('#cfgSubject')?.value || ui.subject);
    const difficulty = String($('#cfgDifficulty')?.value || '').trim();
    const round = normalizeRound($('#cfgRound')?.value || '1');
    const answers = $('#cfgAnswers')?.value || '';

    if (!name) {
      alert('테스트명을 입력해주세요.');
      return;
    }

    let test = selectedRawTest();
    if (!test) {
      test = { id: `t_${ui.category.toLowerCase()}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}` };
      cat.tests.push(test);
      ui.selectedId = test.id;
    }

    test.name = name;
    test.curriculum = subject;
    test.difficulty = difficulty;
    test.round = round;
    test.problems = problems;
    test.answerKeys = parseAnswerSpec3(answers, problems);
    test.answerKey = test.answerKeys['1'];

    try {
      await saveConfig();
      alert('저장 완료');
      ui.subject = subject;
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

    const cat = TEST_CFG.categories[ui.category];
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

  $('#btnSaveRules')?.addEventListener('click', async () => {
    try {
      readRulesFromGrid();
      await saveConfig();
      alert('규칙 저장 완료');
    } catch (e) {
      console.error(e);
      alert('규칙 저장에 실패했습니다.');
    }
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
