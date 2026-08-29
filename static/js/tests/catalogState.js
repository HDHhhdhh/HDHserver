export const ILSAN_GRAPH_DIFFICULTY = '그래프 포함';
export const LEGACY_ILSAN_GRAPH_DIFFICULTY = '삼각함수 그래프 포함';

export const CATEGORY_DEFS = [
  { key: 'REVIEW', label: '복습 테스트', difficulties: ['상', '중상'] },
  { key: 'UNIT', label: '단원평가', difficulties: ['Lv.3', 'Lv.4', 'Lv.5', 'Lv.6'] },
  { key: 'TRAINING_PACK', label: '트레이닝팩', difficulties: ['트팩'] },
  { key: 'SCHOOL_PAST', label: '학군지 기출', difficulties: ['상', '중상'] },
  { key: 'ILSAN_PAST', label: '일산 기출', difficulties: ['중', '중상', ILSAN_GRAPH_DIFFICULTY] },
];

export const CATEGORY_BY_KEY = Object.fromEntries(CATEGORY_DEFS.map(item => [item.key, item]));
export const SUBJECTS = ['공수1', '공수2', '대수', '미적분1', '미적분2', '기하', '확통'];
export const STUDENT_LEVELS = ['하', '중', '중상', '상'];
export const TERM_OPTIONS = ['중간고사', '기말고사'];

export function isUnitCategory(categoryKey) {
  return ['UNIT', 'TRAINING_PACK'].includes(String(categoryKey || ''));
}

export function isPastCategory(categoryKey) {
  return ['SCHOOL_PAST', 'ILSAN_PAST'].includes(String(categoryKey || ''));
}

export function canonText(value) {
  return String(value || '').trim().replace(/\s+/g, ' ');
}

export function normalizeSubject(value) {
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

export function categoryLabel(key) {
  return CATEGORY_BY_KEY[key]?.label || key || '';
}

export function categoryKeyFrom(rawKey, label = '') {
  const raw = `${rawKey || ''} ${label || ''}`.toUpperCase();
  const ko = `${rawKey || ''} ${label || ''}`.replace(/\s+/g, '');
  if (raw.includes('REVIEW') || ko.includes('복습')) return 'REVIEW';
  if (raw.includes('TRAINING') || ko.includes('트레이닝팩') || ko.includes('트팩')) return 'TRAINING_PACK';
  if (raw.includes('SCHOOL') || ko.includes('학군지')) return 'SCHOOL_PAST';
  if (raw.includes('ILSAN') || ko.includes('일산')) return 'ILSAN_PAST';
  if (raw.includes('UNIT') || ko.includes('단원')) return 'UNIT';
  return String(rawKey || '').trim();
}

export function normalizeTerm(value, name = '') {
  const raw = String(value || '').trim();
  const source = `${raw} ${name}`.replace(/\s+/g, '');
  if (/기말|final/i.test(source)) return '기말고사';
  if (/중간|mid/i.test(source)) return '중간고사';
  return raw;
}

export function isIlsanGraphDifficultyText(source) {
  const text = String(source || '');
  return text.includes(ILSAN_GRAPH_DIFFICULTY) ||
    text.includes(LEGACY_ILSAN_GRAPH_DIFFICULTY) ||
    text.includes('그래프');
}

export function normalizeDifficulty(categoryKey, raw, name = '') {
  const text = String(raw || '').trim();
  const source = `${text} ${name}`;
  if (categoryKey === 'ILSAN_PAST' && isIlsanGraphDifficultyText(source)) return ILSAN_GRAPH_DIFFICULTY;
  const def = CATEGORY_BY_KEY[categoryKey];
  if (def?.difficulties.includes(text)) return text;

  const level = source.match(/(?:Lv\.?|LV\.?|레벨)\s*\.?\s*([3-6])/);
  if (level) return `Lv.${level[1]}`;
  if (source.includes('중상')) return '중상';
  if (source.includes('상')) return categoryKey === 'ILSAN_PAST' ? '중상' : '상';
  if (categoryKey === 'ILSAN_PAST' && source.includes('중')) return '중';
  return def?.difficulties?.[0] || '';
}

export function normalizeRound(value, name = '') {
  const raw = String(value || '').trim();
  const source = `${raw} ${name}`;
  const match = source.match(/(\d{1,2})\s*(?:회차|회)/);
  if (match) return match[1];
  if (/^\d{1,2}$/.test(raw)) return raw;
  return raw || '1';
}

export function roundLabel(value) {
  const round = String(value || '').trim();
  if (!round) return '';
  if (round === '-') return '-';
  return /회/.test(round) ? round : `${round}회차`;
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
    const allLevels = STUDENT_LEVELS.slice();
    out[subject] = {
      '중': allLevels.slice(),
      '중상': allLevels.slice(),
      [ILSAN_GRAPH_DIFFICULTY]: allLevels.slice(),
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

function defaultTrainingPackRules() {
  const out = {};
  SUBJECTS.forEach(subject => {
    out[subject] = {
      '트팩': STUDENT_LEVELS.slice(),
    };
  });
  return out;
}

const DEFAULT_RULES = {
  REVIEW: defaultTwoBandRules(),
  SCHOOL_PAST: defaultTwoBandRules(),
  ILSAN_PAST: defaultIlsanRules(),
  UNIT: defaultUnitRules(),
  TRAINING_PACK: defaultTrainingPackRules(),
};

export function ensureConfig(raw) {
  const config = raw && typeof raw === 'object' ? raw : {};
  if (!config.categories || typeof config.categories !== 'object') config.categories = {};

  CATEGORY_DEFS.forEach(def => {
    if (!config.categories[def.key] || typeof config.categories[def.key] !== 'object') {
      config.categories[def.key] = { label: def.label, tests: [] };
    }
    if (!Array.isArray(config.categories[def.key].tests)) config.categories[def.key].tests = [];
    config.categories[def.key].label = config.categories[def.key].label || def.label;
  });

  if (!config.autoAssignRules || typeof config.autoAssignRules !== 'object') config.autoAssignRules = {};
  CATEGORY_DEFS.forEach(def => {
    if (!config.autoAssignRules[def.key] || typeof config.autoAssignRules[def.key] !== 'object') {
      config.autoAssignRules[def.key] = {};
    }
    SUBJECTS.forEach(subject => {
      if (!config.autoAssignRules[def.key][subject] || typeof config.autoAssignRules[def.key][subject] !== 'object') {
        config.autoAssignRules[def.key][subject] = {};
      }
      if (def.key === 'ILSAN_PAST') {
        const subjectRules = config.autoAssignRules[def.key][subject];
        const mergeLevels = (target, ...sources) => {
          const current = Array.isArray(subjectRules[target]) ? subjectRules[target] : [];
          const next = [...current];
          sources.forEach(sourceKey => {
            if (Array.isArray(subjectRules[sourceKey])) next.push(...subjectRules[sourceKey]);
            if (sourceKey !== target) delete subjectRules[sourceKey];
          });
          subjectRules[target] = Array.from(new Set(next.map(String)));
        };
        mergeLevels('중상', '상');
        mergeLevels(ILSAN_GRAPH_DIFFICULTY, LEGACY_ILSAN_GRAPH_DIFFICULTY);
      }
      const defaults = DEFAULT_RULES[def.key]?.[subject] || {};
      Object.entries(defaults).forEach(([difficulty, levels]) => {
        if (def.key === 'ILSAN_PAST') {
          config.autoAssignRules[def.key][subject][difficulty] = levels.slice();
        } else if (!Array.isArray(config.autoAssignRules[def.key][subject][difficulty])) {
          config.autoAssignRules[def.key][subject][difficulty] = levels.slice();
        }
      });
    });
  });
  return config;
}

export function normalizeCatalogTest(rawTest, rawCategoryKey, idx = 0, options = {}) {
  const categoryKey = categoryKeyFrom(rawCategoryKey);
  const name = canonText(rawTest?.name || rawTest?.title || `테스트 ${idx + 1}`);
  const curriculum = normalizeSubject(rawTest?.curriculum || rawTest?.subject || options.fallbackSubject);
  const now = Number(options.now);
  const idStamp = Number.isFinite(now) ? now : 0;
  return {
    ...(rawTest || {}),
    id: canonText(rawTest?.id) || `t_${categoryKey}_${idStamp}_${idx}`,
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

export function catalogSearchText(test, options = {}) {
  const searchKeyForText = typeof options.searchKeyForText === 'function'
    ? options.searchKeyForText
    : value => canonText(value).toLowerCase();
  const displayName = typeof options.displayNameFor === 'function' ? options.displayNameFor(test) : test?.name;
  return searchKeyForText([
    test?.id,
    test?.sourceId,
    test?.name,
    displayName,
    categoryLabel(test?.categoryKey),
    test?.curriculum,
    test?.difficulty,
    test?.term,
    test?.examTerm,
    roundLabel(test?.round || ''),
    test?.problems ? `${test.problems}문항` : '',
  ].map(canonText).join(' '));
}

export function roundSortValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 9999;
}

export function termSortValue(value) {
  const term = normalizeTerm(value);
  const index = TERM_OPTIONS.indexOf(term);
  return index >= 0 ? index : 9999;
}

export function testOrderValue(test) {
  const raw = test?.sortOrder ?? test?.sourceOrder ?? test?.order ?? test?.sourceIndex ?? test?._catalogIndex;
  const number = Number(raw);
  return Number.isFinite(number) ? number : 999999;
}

export function compareCatalogTests(left, right, categoryKey) {
  const difficulty = String(left.difficulty).localeCompare(String(right.difficulty), 'ko');
  if (difficulty) return difficulty;
  if (isPastCategory(categoryKey)) {
    return termSortValue(left.term || '') - termSortValue(right.term || '') ||
      testOrderValue(left) - testOrderValue(right) ||
      roundSortValue(left.round || 0) - roundSortValue(right.round || 0) ||
      String(left.name).localeCompare(String(right.name), 'ko');
  }
  if (isUnitCategory(categoryKey)) {
    return roundSortValue(left.round || 0) - roundSortValue(right.round || 0) ||
      testOrderValue(left) - testOrderValue(right) ||
      String(left.name).localeCompare(String(right.name), 'ko');
  }
  return testOrderValue(left) - testOrderValue(right) ||
    roundSortValue(left.round || 0) - roundSortValue(right.round || 0) ||
    String(left.name).localeCompare(String(right.name), 'ko');
}

export function visibleCatalogTests(tests, filters = {}, options = {}) {
  const matchesSearchKey = typeof options.matchesSearchKey === 'function'
    ? options.matchesSearchKey
    : (key, query) => canonText(key).toLowerCase().includes(canonText(query).toLowerCase());
  const categoryKey = String(filters.category || '');
  return (Array.isArray(tests) ? tests : [])
    .filter(test => normalizeSubject(test.curriculum) === filters.subject)
    .filter(test => !filters.difficulty || String(test.difficulty || '') === String(filters.difficulty))
    .filter(test => !isPastCategory(categoryKey) || !filters.term || String(test.term || '') === String(filters.term))
    .filter(test => !isUnitCategory(categoryKey) || !filters.round || String(test.round || '') === String(filters.round))
    .filter(test => matchesSearchKey(catalogSearchText(test, options), filters.catalogSearch))
    .sort((left, right) => compareCatalogTests(left, right, categoryKey));
}

export function catalogGroupKey(test, categoryKey) {
  if (isPastCategory(categoryKey)) return `${test?.term || '-'}|||${test?.difficulty || '-'}|||`;
  if (isUnitCategory(categoryKey)) return `${test?.difficulty || '-'}|||${test?.round || '-'}`;
  return `${test?.difficulty || '-'}|||`;
}

export function projectCatalogOrderBlock(state = {}) {
  if (state.catalogOrderSaveInFlight) return { kind: 'saving', message: '변경한 시험 순서를 저장하는 중입니다.' };
  if (state.catalogMutationSaveInFlight) return { kind: 'saving', message: '시험 설정 변경을 저장하는 동안에는 순서를 바꿀 수 없습니다.' };
  if (state.ruleSaveTimer || state.ruleSaveInFlight || state.ruleSavePending) {
    return { kind: 'saving', message: '배정 기준 저장이 끝난 뒤 시험 순서를 바꿔주세요.' };
  }
  if (String(state.catalogSearch || '').trim()) {
    return { kind: 'blocked', message: '목록 검색 중에는 순서를 바꿀 수 없습니다. 검색어를 지우면 드래그와 위·아래 이동을 사용할 수 있습니다.' };
  }
  if (isPastCategory(state.category) && state.term) {
    return { kind: 'blocked', message: '고사를 좁혀 본 상태에서는 순서를 바꿀 수 없습니다. 고사에서 전체 고사를 선택하세요.' };
  }
  if (isUnitCategory(state.category) && state.round) {
    return { kind: 'blocked', message: '회차를 좁혀 본 상태에서는 순서를 바꿀 수 없습니다. 회차에서 전체 회차를 선택하세요.' };
  }
  return null;
}

export function normalizeRevision(value) {
  const revision = String(value || '').trim().toLowerCase();
  return /^[0-9a-f]{64}$/.test(revision) ? revision : '';
}

function revisionHeaders(revision) {
  const headers = { 'Content-Type': 'application/json' };
  const normalized = normalizeRevision(revision);
  if (normalized) headers['X-Tests-Config-Revision'] = normalized;
  return headers;
}

export function wholeConfigWriteRequest(config, revision, removedTestIds = []) {
  const payload = { ...(config && typeof config === 'object' ? config : {}) };
  if (Array.isArray(removedTestIds) && removedTestIds.length) {
    payload.__removedTestIds = removedTestIds.map(id => String(id));
  }
  return {
    method: 'POST',
    headers: revisionHeaders(revision),
    body: JSON.stringify(payload),
  };
}

export function testDefinitionWriteRequest(test, categoryKey, categoryLabelValue, clearFields, revision) {
  return {
    method: 'PATCH',
    headers: revisionHeaders(revision),
    body: JSON.stringify({
      categoryKey,
      categoryLabel: categoryLabelValue,
      test,
      clearFields: Array.isArray(clearFields) ? clearFields : [],
    }),
  };
}

export function captureCatalogMutationSnapshot(config, revision, selectedId) {
  return {
    config: JSON.parse(JSON.stringify(config && typeof config === 'object' ? config : {})),
    revision: normalizeRevision(revision),
    selectedId: String(selectedId || ''),
  };
}
