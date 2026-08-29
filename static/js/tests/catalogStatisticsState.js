import {
  canonText,
  isPastCategory,
  normalizeTerm,
  roundLabel,
  roundSortValue,
  termSortValue,
} from './catalogState.js?v=20260829-catalog-state-r1';

export const STATS_TYPE_LABELS = Object.freeze({
  REVIEW: '복테',
  TRAINING_PACK: '트팩',
  SCHOOL_PAST: '학군지',
  ILSAN_PAST: '일산',
});

export function statsTypeLabel(definition) {
  return STATS_TYPE_LABELS[String(definition?.key || '')] || definition?.label || '';
}

export function formatPercent(value) {
  return (typeof value === 'number' && Number.isFinite(value)) ? `${value.toFixed(1)}%` : '-';
}

export function formatNumber(value) {
  return (typeof value === 'number' && Number.isFinite(value)) ? value.toFixed(1) : '-';
}

export function statsSignature(test, defaultCategory = '') {
  const categoryKey = test?.categoryKey || defaultCategory || '';
  return [
    categoryKey,
    test?.curriculum || '',
    canonText(test?.name),
    isPastCategory(categoryKey) ? normalizeTerm(test?.term || test?.examTerm || '', test?.name) : '',
    String(test?.round || '').trim(),
  ].join('\u241f');
}

export function statForTest(test, stats, defaultCategory = '') {
  const byId = stats?.by_test_id || {};
  if (test?.id && byId[test.id]) return byId[test.id];
  const bySignature = stats?.by_test_signature || {};
  const signature = statsSignature(test, defaultCategory);
  if (signature && bySignature[signature]) return bySignature[signature];
  return stats?.by_test?.[canonText(test?.name)] || null;
}

export function defaultStatsCompare(left, right) {
  return String(left.curriculum || '').localeCompare(String(right.curriculum || ''), 'ko') ||
    String(left.difficulty || '').localeCompare(String(right.difficulty || ''), 'ko') ||
    termSortValue(left.term || left.examTerm || '') - termSortValue(right.term || right.examTerm || '') ||
    roundSortValue(left.round || 0) - roundSortValue(right.round || 0) ||
    String(left.name || '').localeCompare(String(right.name || ''), 'ko');
}

export function statsCount(row) {
  const count = Number(row?.stat?.count || 0);
  return Number.isFinite(count) ? count : 0;
}

export function statsAverage(row, emptyValue) {
  const average = Number(row?.stat?.avg_pct);
  return Number.isFinite(average) ? average : emptyValue;
}

export function statsSearchText(row, searchKeyForText) {
  return searchKeyForText([
    row.typeLabel,
    row.typeSearchLabel,
    row.curriculum,
    row.name,
    row.displayName,
    row.difficulty,
    row.term,
    row.examTerm,
    roundLabel(row.round || ''),
    row.problems ? `${row.problems}문항` : '',
  ].map(canonText).join(' '));
}

export function compareStatsRows(left, right, sort = 'default') {
  switch (sort) {
    case 'name':
      return String(left.name || '').localeCompare(String(right.name || ''), 'ko') || defaultStatsCompare(left, right);
    case 'taken_desc':
      return statsCount(right) - statsCount(left) || defaultStatsCompare(left, right);
    case 'taken_asc':
      return statsCount(left) - statsCount(right) || defaultStatsCompare(left, right);
    case 'avg_desc':
      return statsAverage(right, -1) - statsAverage(left, -1) || defaultStatsCompare(left, right);
    case 'avg_asc':
      return statsAverage(left, 101) - statsAverage(right, 101) || defaultStatsCompare(left, right);
    case 'round':
      return roundSortValue(left.round || 0) - roundSortValue(right.round || 0) || defaultStatsCompare(left, right);
    default:
      return defaultStatsCompare(left, right);
  }
}

export function projectStatsRows({
  tests = [],
  definition = {},
  stats = null,
  queryText = '',
  sort = 'default',
  displayNameFor = test => String(test?.name || ''),
  searchKeyForText = value => String(value || ''),
  matchesSearchKey = (key, query) => String(key || '').includes(String(query || '')),
} = {}) {
  return tests.map(test => ({
    ...test,
    displayName: displayNameFor(test),
    typeLabel: statsTypeLabel(definition),
    typeSearchLabel: definition.label,
    stat: statForTest(test, stats, definition.key),
  }))
    .filter(row => matchesSearchKey(statsSearchText(row, searchKeyForText), queryText))
    .sort((left, right) => compareStatsRows(left, right, sort));
}

export function projectStatsSummary({
  categoryDefinitions = [],
  summary = {},
  categoryCounts = {},
  activeCategory = '',
} = {}) {
  return categoryDefinitions.map(definition => {
    const row = summary?.[definition.key];
    const count = categoryCounts?.[definition.key] || 0;
    return {
      key: definition.key,
      label: definition.label,
      metric: row?.count ? `${Number(row.avg_pct || 0).toFixed(1)}%` : `${count}개`,
      meta: row?.count ? `응시 ${row.count}건` : '등록 테스트',
      active: activeCategory === definition.key,
    };
  });
}

export function wrongListText(wrong) {
  if (!Array.isArray(wrong) || !wrong.length) return '틀린 문항 없음';
  const numbers = wrong.map(value => String(value).trim()).filter(Boolean).join(', ');
  return numbers ? `틀린 문항 ${numbers}` : '틀린 문항 없음';
}

export function projectWrongDetails(details, wrong = []) {
  const sourceRows = Array.isArray(details)
    ? details.filter(row => row && typeof row === 'object')
    : [];
  const wrongNumbers = Array.isArray(wrong)
    ? wrong.map(value => String(value).trim()).filter(Boolean)
    : [];
  const rows = sourceRows.map(row => {
    const questionNo = String(row.questionNo ?? row.question_no ?? '').trim();
    return {
      questionLabel: questionNo ? `${questionNo}번` : '-',
      myAnswer: String(row.myAnswer ?? row.my_answer ?? '').trim() || '-',
      correctAnswer: String(row.correctAnswer ?? row.correct_answer ?? '').trim() || '-',
    };
  });
  return {
    rows,
    emptyMessage: !rows.length && wrongNumbers.length
      ? '이전 제출 기록이라 내 답 비교가 없습니다.'
      : '',
  };
}

export function projectStatsDetail({
  selected,
  stat = {},
  detail = null,
  displayNameFor = test => String(test?.name || ''),
} = {}) {
  if (!selected) return null;
  const records = Array.isArray(detail?.records) ? detail.records : [];
  const detailAnswerUrl = String(detail?.answerUrl || '').trim();
  return {
    title: selected.displayName || displayNameFor(selected),
    subtitle: [
      selected.curriculum || '-',
      isPastCategory(selected.categoryKey) ? (selected.term || selected.examTerm || '') : '',
      selected.difficulty || '-',
      roundLabel(selected.round || '-'),
    ].filter(Boolean).join(' · '),
    metrics: [
      { label: '응시', value: stat.count || 0 },
      { label: '평균', value: formatPercent(stat.avg_pct) },
      { label: '표준편차', value: formatNumber(stat.stddev_pct) },
      { label: '중앙값', value: formatPercent(stat.median_pct) },
      { label: '최대', value: formatPercent(stat.max_pct) },
      { label: '최소', value: formatPercent(stat.min_pct) },
    ],
    answerLink: detailAnswerUrl ? { url: detailAnswerUrl, label: '전체 답지 보기' } : null,
    records: records.map(record => ({
      studentName: record.studentName || record.sid || '-',
      level: record.level || '-',
      percent: formatPercent(record.pct),
      score: `${record.correct ?? '-'} / ${record.total ?? '-'}`,
      wrongText: wrongListText(record.wrong),
      wrongDetails: projectWrongDetails(record.wrongDetails, record.wrong),
      createdDate: (record.createdAt || '').slice(0, 10) || '-',
    })),
  };
}
