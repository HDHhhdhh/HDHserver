// Test assignment normalization and transitions. No DOM, transport or ambient state.
// normalizeConfig intentionally repairs the supplied configuration in place.

export const ILSAN_GRAPH_DIFFICULTY = '그래프 포함';
export const LEGACY_ILSAN_GRAPH_DIFFICULTY = '삼각함수 그래프 포함';
export const CATEGORY_DEFS = [
  { key: 'REVIEW', label: '복습 테스트', short: '복습', difficulties: ['상', '중상'] },
  { key: 'UNIT', label: '단원평가', short: '단원', difficulties: ['Lv.3', 'Lv.4', 'Lv.5', 'Lv.6'] },
  { key: 'SCHOOL_PAST', label: '학군지 기출', short: '학군지', difficulties: ['상', '중상'] },
  { key: 'ILSAN_PAST', label: '일산 기출', short: '일산', difficulties: ['중상', '상', ILSAN_GRAPH_DIFFICULTY] },
];
export const CATEGORY_BY_KEY = Object.fromEntries(CATEGORY_DEFS.map(x => [x.key, x]));
export const CATEGORY_KEYS = CATEGORY_DEFS.map(x => x.key);
export const SUBJECTS = ['공수1', '공수2', '대수', '미적분1', '미적분2', '기하', '확통'];
export const STUDENT_LEVELS = ['하', '중', '중상', '상'];
export const ROUND_OPTIONS = ['1', '2', '3'];
export const TERM_OPTIONS = ['중간고사', '기말고사'];
export const DEFAULT_TERM = TERM_OPTIONS[1] || TERM_OPTIONS[0];
export const TEST_STATUS_LABELS = {
  assigned: '배정',
  done: '완료',
  interrupted: '배부',
  skip: '제외',
};
export const TEST_KEYBOARD_STATUS_ORDER = ['', 'interrupted', 'assigned', 'done', 'skip'];

export function isUnitCategory(categoryKey) {
  return String(categoryKey || '') === 'UNIT';
}

export function isTermCategory(categoryKey) {
  const key = String(categoryKey || '');
  return key === 'SCHOOL_PAST' || key === 'ILSAN_PAST';
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

export function canonicalCategoryKey(key, label = '') {
  const raw = `${key || ''} ${label || ''}`.toUpperCase();
  const ko = `${key || ''} ${label || ''}`.replace(/\s+/g, '');
  if (raw.includes('REVIEW') || ko.includes('복습')) return 'REVIEW';
  if (raw.includes('SCHOOL') || ko.includes('학군지')) return 'SCHOOL_PAST';
  if (raw.includes('ILSAN') || ko.includes('일산')) return 'ILSAN_PAST';
  if (raw.includes('UNIT') || ko.includes('단원')) return 'UNIT';
  return String(key || '').trim();
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
  if (categoryKey === 'ILSAN_PAST' && ['중상', '상', ILSAN_GRAPH_DIFFICULTY].includes(text)) return text;
  if (categoryKey === 'ILSAN_PAST' && isIlsanGraphDifficultyText(source)) return ILSAN_GRAPH_DIFFICULTY;
  const def = CATEGORY_BY_KEY[categoryKey];
  if (def?.difficulties.includes(text)) return text;

  const lv = source.match(/(?:Lv\.?|LV\.?|레벨)\s*\.?\s*([3-6])/);
  if (lv) return `Lv.${lv[1]}`;
  if (source.includes('중상')) return '중상';
  if (source.includes('상')) return '상';
  if (categoryKey === 'ILSAN_PAST' && source.includes('중')) return '중상';

  return def?.difficulties?.[0] || '';
}

export function normalizeRound(value, name = '') {
  const raw = String(value || '').trim();
  const source = `${raw} ${name}`;
  const m = source.match(/(\d{1,2})\s*(?:회차|회)/);
  if (m) return m[1];
  if (/^\d{1,2}$/.test(raw)) return raw;
  return raw || '1';
}

export function roundLabel(value) {
  const r = String(value || '').trim();
  if (!r) return '';
  return /회/.test(r) ? r : `${r}회차`;
}

export function normalizeTerm(value, name = '') {
  const source = `${value || ''} ${name || ''}`.trim();
  if (!source) return DEFAULT_TERM;
  if (TERM_OPTIONS.includes(source)) return source;
  const lower = source.toLowerCase();
  if (lower.includes('final') || lower.includes('end') || source.includes(TERM_OPTIONS[1])) return TERM_OPTIONS[1] || DEFAULT_TERM;
  if (lower.includes('mid') || lower.includes('middle') || source.includes(TERM_OPTIONS[0])) return TERM_OPTIONS[0] || DEFAULT_TERM;
  return DEFAULT_TERM;
}

export function normalizeAssignmentStatus(status) {
  const raw = status && typeof status === 'object' ? status.status : status;
  const s = String(raw || '').trim();
  if (!s || s === 'none') return '';
  if (s === 'assigned' || s === 'done' || s === 'interrupted' || s === 'skip') return s;
  return 'assigned';
}

export function testStatusLabel(status, submitted = false) {
  if (submitted) return '완료';
  const s = normalizeAssignmentStatus(status);
  return s ? (TEST_STATUS_LABELS[s] || '배정') : '';
}

export function nextStatusOf(status) {
  const s = normalizeAssignmentStatus(status);
  if (!s || s === 'skip') return 'assigned';
  if (s === 'assigned') return 'interrupted';
  if (s === 'interrupted') return 'done';
  return '';
}

export function nextExcludedStatusOf(status) {
  return normalizeAssignmentStatus(status) === 'skip' ? '' : 'skip';
}

export function nextKeyboardStatusOf(status, direction = 1) {
  const normalized = normalizeAssignmentStatus(status);
  const currentIndex = Math.max(0, TEST_KEYBOARD_STATUS_ORDER.indexOf(normalized));
  const step = Number(direction) < 0 ? -1 : 1;
  const nextIndex = (currentIndex + step + TEST_KEYBOARD_STATUS_ORDER.length) % TEST_KEYBOARD_STATUS_ORDER.length;
  return TEST_KEYBOARD_STATUS_ORDER[nextIndex];
}

export function isInProgressTestStatus(status) {
  const normalized = normalizeAssignmentStatus(status);
  return normalized === 'assigned' || normalized === 'interrupted';
}

export function isResolvedTestStatus(status) {
  const normalized = normalizeAssignmentStatus(status);
  return normalized === 'done' || normalized === 'skip';
}

export function isExplicitBlankTestStatus(status) {
  if (!status || typeof status !== 'object') return false;
  return normalizeAssignmentStatus(status) === '' && status.explicitBlank === true;
}

export function testKey(test) {
  return [
    categoryLabel(test.categoryKey),
    test.curriculum,
    test.difficulty,
    isTermCategory(test.categoryKey) ? test.term : '',
    roundLabel(test.round),
    test.name,
  ].filter(Boolean).join(' / ');
}

export function normalizeConfig(cfg) {
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
      if (!subjectRules || typeof subjectRules !== 'object') return;
      const mergeLevels = (target, ...sources) => {
        const current = Array.isArray(subjectRules[target]) ? subjectRules[target] : [];
        const next = [...current];
        sources.forEach(sourceKey => {
          if (Array.isArray(subjectRules[sourceKey])) next.push(...subjectRules[sourceKey]);
          if (sourceKey !== target) delete subjectRules[sourceKey];
        });
        subjectRules[target] = Array.from(new Set(next.map(String)));
      };
      mergeLevels('중상', '중');
      mergeLevels(ILSAN_GRAPH_DIFFICULTY, LEGACY_ILSAN_GRAPH_DIFFICULTY);
      CATEGORY_BY_KEY.ILSAN_PAST.difficulties.forEach(difficulty => {
        subjectRules[difficulty] = STUDENT_LEVELS.slice();
      });
    });
  }

  return out;
}

export function collectTestCatalog(cfg, fallbackSubject = '공수1') {
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
      const curriculum = normalizeSubject(rawTest.curriculum || rawTest.subject || rawTest.course || fallbackSubject);
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
    const aDifficulties = CATEGORY_BY_KEY[a.categoryKey]?.difficulties || [];
    const bDifficulties = CATEGORY_BY_KEY[b.categoryKey]?.difficulties || [];
    const base =
      rankIn(CATEGORY_KEYS, a.categoryKey) - rankIn(CATEGORY_KEYS, b.categoryKey) ||
      rankIn(SUBJECTS, a.curriculum) - rankIn(SUBJECTS, b.curriculum) ||
      rankIn(aDifficulties, a.difficulty) - rankIn(bDifficulties, b.difficulty) ||
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
