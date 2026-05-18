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

export const SEARCH_HELP_TEXT = '초성 검색 · 띄어쓰기=AND';

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

export function matchesSearchKey(searchKey, query) {
  const terms = searchTerms(query);
  if (!terms.length) return true;
  const key = String(searchKey || '');
  return terms.every(term => key.includes(term));
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

export function searchKeyForText(value) {
  const raw = String(value || '');
  return normalizeSearch([
    raw,
    hangulInitials(raw, HANGUL_INITIALS_COMPAT),
    hangulInitials(raw, HANGUL_INITIALS_LEAD),
  ].join(' '));
}

export function studentSearchKey(stu, extraFields = []) {
  if (!stu || typeof stu !== 'object') return '';
  const fields = [
    stu.name,
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
  return searchKeyForText(fields.filter(Boolean).join(' '));
}

const api = {
  expandCompoundInitials,
  normalizeSearch,
  SEARCH_HELP_TEXT,
  searchPlaceholder,
  applySearchPlaceholder,
  searchTerms,
  matchesSearchKey,
  matchesSearchText,
  hangulInitials,
  searchKeyForText,
  studentSearchKey,
};

if (typeof window !== 'undefined') {
  window.SearchUtils = { ...(window.SearchUtils || {}), ...api };
}
