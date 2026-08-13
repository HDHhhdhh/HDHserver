const HANGUL_BASE = 0xac00;
const HANGUL_END = 0xd7a3;

const HANGUL_INITIALS_COMPAT = [
  'ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ',
  'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ',
];

const HANGUL_INITIALS_LEAD = [
  0x1100, 0x1101, 0x1102, 0x1103, 0x1104, 0x1105, 0x1106, 0x1107, 0x1108,
  0x1109, 0x110a, 0x110b, 0x110c, 0x110d, 0x110e, 0x110f, 0x1110, 0x1111, 0x1112,
].map(code => String.fromCharCode(code));

const HANGUL_MEDIALS_COMPAT = [
  '\u314f', '\u3150', '\u3151', '\u3152', '\u3153', '\u3154', '\u3155',
  '\u3156', '\u3157', '\u3158', '\u3159', '\u315a', '\u315b', '\u315c',
  '\u315d', '\u315e', '\u315f', '\u3160', '\u3161', '\u3162', '\u3163',
];

const HANGUL_FINALS_COMPAT = [
  '', '\u3131', '\u3132', '\u3133', '\u3134', '\u3135', '\u3136',
  '\u3137', '\u3139', '\u313a', '\u313b', '\u313c', '\u313d', '\u313e',
  '\u313f', '\u3140', '\u3141', '\u3142', '\u3144', '\u3145', '\u3146',
  '\u3147', '\u3148', '\u314a', '\u314b', '\u314c', '\u314d', '\u314e',
];

const DUBEOLSIK_COMPAT_BY_KEY = new Map([
  ['r', '\u3131'], ['R', '\u3132'], ['s', '\u3134'], ['e', '\u3137'], ['E', '\u3138'],
  ['f', '\u3139'], ['a', '\u3141'], ['q', '\u3142'], ['Q', '\u3143'], ['t', '\u3145'],
  ['T', '\u3146'], ['d', '\u3147'], ['w', '\u3148'], ['W', '\u3149'], ['c', '\u314a'],
  ['z', '\u314b'], ['x', '\u314c'], ['v', '\u314d'], ['g', '\u314e'],
  ['k', '\u314f'], ['o', '\u3150'], ['i', '\u3151'], ['O', '\u3152'], ['j', '\u3153'],
  ['p', '\u3154'], ['u', '\u3155'], ['P', '\u3156'], ['h', '\u3157'], ['y', '\u315b'],
  ['n', '\u315c'], ['b', '\u3160'], ['m', '\u3161'], ['l', '\u3163'],
]);

const COMPOUND_INITIALS = new Map([
  ['ㄳ', 'ㄱㅅ'],
  ['ㄵ', 'ㄴㅈ'],
  ['ㄶ', 'ㄴㅎ'],
  ['ㄺ', 'ㄹㄱ'],
  ['ㄻ', 'ㄹㅁ'],
  ['ㄼ', 'ㄹㅂ'],
  ['ㄽ', 'ㄹㅅ'],
  ['ㄾ', 'ㄹㅌ'],
  ['ㄿ', 'ㄹㅍ'],
  ['ㅀ', 'ㄹㅎ'],
  ['ㅄ', 'ㅂㅅ'],
]);

const COMPOUND_VOWEL_BY_PAIR = new Map([
  ['\u3157\u314f', '\u3158'], ['\u3157\u3150', '\u3159'], ['\u3157\u3163', '\u315a'],
  ['\u315c\u3153', '\u315d'], ['\u315c\u3154', '\u315e'], ['\u315c\u3163', '\u315f'],
  ['\u3161\u3163', '\u3162'],
]);

const COMPOUND_FINAL_BY_PAIR = new Map(
  Array.from(COMPOUND_INITIALS, ([compound, expanded]) => [expanded, compound])
);

const INITIAL_INDEX_BY_COMPAT = new Map(HANGUL_INITIALS_COMPAT.map((ch, index) => [ch, index]));
const MEDIAL_INDEX_BY_COMPAT = new Map(HANGUL_MEDIALS_COMPAT.map((ch, index) => [ch, index]));
const FINAL_INDEX_BY_COMPAT = new Map(HANGUL_FINALS_COMPAT.map((ch, index) => [ch, index]));

function isCompatVowel(ch) {
  return MEDIAL_INDEX_BY_COMPAT.has(ch);
}

export function expandCompoundInitials(value) {
  return Array.from(String(value || ''))
    .map(ch => COMPOUND_INITIALS.get(ch) || ch)
    .join('');
}

export function normalizeSearch(value) {
  return expandCompoundInitials(value)
    .normalize('NFKC')
    .toLowerCase()
    .replace(/\s+/g, '');
}

export const SEARCH_HELP_TEXT = '초성/영타 검색 · 띄어쓰기=AND';

export function searchPlaceholder(label = '검색') {
  const head = String(label || '검색').trim() || '검색';
  return `${head} (${SEARCH_HELP_TEXT})`;
}

export function applySearchPlaceholder(input, label = '검색') {
  if (!input) return;
  input.placeholder = searchPlaceholder(label);
  input.dataset.searchHelp = SEARCH_HELP_TEXT;
}

export function searchTerms(value) {
  return String(value || '')
    .trim()
    .split(/\s+/)
    .map(normalizeSearch)
    .filter(Boolean);
}

export function dubeolsikKeysToCompatJamo(value) {
  return Array.from(String(value || ''))
    .map(ch => DUBEOLSIK_COMPAT_BY_KEY.get(ch) || ch)
    .join('');
}

export function composeCompatJamo(value) {
  const chars = Array.from(String(value || ''));
  let out = '';

  for (let i = 0; i < chars.length;) {
    const initialIndex = INITIAL_INDEX_BY_COMPAT.get(chars[i]);
    if (initialIndex == null || !isCompatVowel(chars[i + 1])) {
      out += chars[i] || '';
      i += 1;
      continue;
    }

    let medial = chars[i + 1];
    let consumed = 2;
    const compoundVowel = COMPOUND_VOWEL_BY_PAIR.get(`${medial}${chars[i + 2] || ''}`);
    if (compoundVowel) {
      medial = compoundVowel;
      consumed = 3;
    }

    const medialIndex = MEDIAL_INDEX_BY_COMPAT.get(medial);
    let finalIndex = 0;
    const finalOne = chars[i + consumed];
    if (FINAL_INDEX_BY_COMPAT.has(finalOne)) {
      const finalTwo = chars[i + consumed + 1];
      const afterFinalTwo = chars[i + consumed + 2];
      const compoundFinal = COMPOUND_FINAL_BY_PAIR.get(`${finalOne}${finalTwo || ''}`);

      if (isCompatVowel(finalTwo)) {
        finalIndex = 0;
      } else if (compoundFinal && !isCompatVowel(afterFinalTwo)) {
        finalIndex = FINAL_INDEX_BY_COMPAT.get(compoundFinal) || 0;
        consumed += 2;
      } else {
        finalIndex = FINAL_INDEX_BY_COMPAT.get(finalOne) || 0;
        consumed += 1;
      }
    }

    out += String.fromCharCode(HANGUL_BASE + ((initialIndex * 21 + medialIndex) * 28) + finalIndex);
    i += consumed;
  }

  return out;
}

export function searchTermVariants(value) {
  const raw = String(value || '');
  const variants = [normalizeSearch(raw)];
  if (/^[A-Za-z]+$/.test(raw) && raw.length >= 2) {
    const jamo = dubeolsikKeysToCompatJamo(raw);
    const lowerJamo = dubeolsikKeysToCompatJamo(raw.toLowerCase());
    variants.push(
      normalizeSearch(jamo),
      normalizeSearch(composeCompatJamo(jamo)),
      normalizeSearch(lowerJamo),
      normalizeSearch(composeCompatJamo(lowerJamo)),
    );
  }
  return Array.from(new Set(variants.filter(Boolean)));
}

export function searchTermVariantGroups(value) {
  return String(value || '')
    .trim()
    .split(/\s+/)
    .map(searchTermVariants)
    .filter(group => group.length);
}

export function matchesSearchKey(searchKey, query) {
  const termGroups = searchTermVariantGroups(query);
  if (!termGroups.length) return true;
  const key = String(searchKey || '');
  return termGroups.every(group => group.some(term => key.includes(term)));
}

export function matchesSearchText(value, query) {
  return matchesSearchKey(searchKeyForText(value), query);
}

export function hangulInitials(value, initials = HANGUL_INITIALS_COMPAT) {
  return Array.from(String(value || '')).map(ch => {
    const code = ch.charCodeAt(0);
    if (code < HANGUL_BASE || code > HANGUL_END) return ch;
    return initials[Math.floor((code - HANGUL_BASE) / 588)] || ch;
  }).join('');
}

function searchTokens(value) {
  return String(value || '')
    .trim()
    .split(/\s+/)
    .map(token => token.trim())
    .filter(Boolean);
}

function searchKeyPartsForText(value, { initials = true } = {}) {
  const tokens = searchTokens(value);
  const parts = [];

  tokens.forEach(token => {
    parts.push(normalizeSearch(token));
    if (!initials) return;
    parts.push(
      normalizeSearch(hangulInitials(token, HANGUL_INITIALS_COMPAT)),
      normalizeSearch(hangulInitials(token, HANGUL_INITIALS_LEAD)),
    );
  });

  return Array.from(new Set(parts.filter(Boolean)));
}

export function searchKeyForText(value) {
  return searchKeyPartsForText(value).join('|');
}

export function studentSearchKey(stu, extraFields = []) {
  if (!stu || typeof stu !== 'object') return '';
  const detailFields = [
    stu.id,
    stu.school,
    stu.schoolName,
    stu.highSchool,
    stu.middleSchool,
    stu.high,
    stu.middle,
    stu.schoolHigh,
    stu.schoolMiddle,
    stu.highschool,
    stu.middleschool,
    stu.high_school,
    stu.middle_school,
    stu.고등학교,
    stu.중학교,
    stu.grade,
    stu.gradeLevel,
    stu.studentGrade,
    stu.학년,
    stu.level,
    stu.curriculum,
    stu.subCurriculum,
    stu.subject,
    stu.course,
    stu.day1,
    stu.day2,
    stu.day3,
    stu.day4,
    stu.day5,
    stu.subBook1,
    stu.subBook2,
    ...extraFields,
  ];
  return [
    ...searchKeyPartsForText(stu.name, { initials: true }),
    ...detailFields.flatMap(value => searchKeyPartsForText(value, { initials: false })),
  ].join('|');
}

const api = {
  expandCompoundInitials,
  normalizeSearch,
  SEARCH_HELP_TEXT,
  searchPlaceholder,
  applySearchPlaceholder,
  searchTerms,
  searchTermVariants,
  searchTermVariantGroups,
  matchesSearchKey,
  matchesSearchText,
  dubeolsikKeysToCompatJamo,
  composeCompatJamo,
  hangulInitials,
  searchKeyForText,
  studentSearchKey,
};

if (typeof window !== 'undefined') {
  window.SearchUtils = { ...(window.SearchUtils || {}), ...api };
}
