(function studentTestPresentationModule(global) {
  'use strict';

  const ASSIGNED_TEST_STATUSES = new Set(['interrupted', 'skip', 'done', 'assigned']);

  function normalizeStatus(status) {
    const value = String(status || '').trim();
    if (ASSIGNED_TEST_STATUSES.has(value)) return value;
    return value ? 'assigned' : '';
  }

  function statusLabel(status) {
    const value = normalizeStatus(status);
    if (value === 'done') return '완료';
    if (value === 'interrupted') return '배부';
    if (value === 'skip') return '제외';
    return value ? '배정' : '';
  }

  function difficultyLabel(item) {
    const category = `${item?.categoryKey || ''} ${item?.categoryLabel || ''} ${item?.category || ''} ${item?.label || ''}`;
    const difficulty = String(item?.difficulty || '').trim();
    if (category.includes('ILSAN') || category.includes('일산')) {
      if (difficulty === '중상' || difficulty === '상' || difficulty === '그래프 포함') return difficulty;
      if (difficulty.includes('그래프')) return '그래프 포함';
      if (difficulty === '중') return '중상';
    }
    return difficulty;
  }

  function normalizeAssignedTests(items) {
    const seen = new Set();
    return (Array.isArray(items) ? items : []).map(item => {
      if (!item || typeof item !== 'object') return null;
      const id = String(item.id || item.testId || '').trim();
      const label = String(item.label || '').trim();
      const name = String(item.name || item.testName || label || '').trim();
      if (!id && !label && !name) return null;
      const status = normalizeStatus(item.status) || 'assigned';
      const key = id || label || name;
      if (seen.has(key)) return null;
      seen.add(key);
      return {
        ...item,
        id,
        label,
        name,
        categoryLabel: String(item.categoryLabel || item.category || '').trim(),
        curriculum: String(item.curriculum || '').trim(),
        difficulty: difficultyLabel(item),
        round: String(item.round || '').trim(),
        status,
        statusLabel: item.statusLabel || statusLabel(status),
      };
    }).filter(Boolean);
  }

  function answerUrl(test) {
    return String(test?.answerUrl || test?.answer_url || test?.solutionUrl || test?.solution_url || '').trim();
  }

  function isAnswerRestricted(test, resolvedAnswerUrl, academyAccessAllowed) {
    return test?.answerRestricted === true || (!academyAccessAllowed && !!resolvedAnswerUrl);
  }

  function canOpenAnswer(resolvedAnswerUrl, academyAccessAllowed) {
    return !!academyAccessAllowed && !!resolvedAnswerUrl;
  }

  function roundLabel(round) {
    const value = String(round || '').trim();
    return value ? (value.includes('회') ? value : `${value}회차`) : '';
  }

  function metaText(test) {
    return [
      test?.categoryLabel,
      test?.curriculum,
      test?.difficulty,
      roundLabel(test?.round),
    ].filter(Boolean).join(' · ');
  }

  function viewModel(test, { academyAccessAllowed = false } = {}) {
    if (!test || typeof test !== 'object') return null;
    const resolvedAnswerUrl = answerUrl(test);
    const status = normalizeStatus(test.status) || 'assigned';
    return Object.freeze({
      id: String(test.id || '').trim(),
      name: test.name || test.label || '배정 테스트',
      metaText: metaText(test),
      status,
      statusLabel: test.statusLabel || statusLabel(status),
      answerUrl: resolvedAnswerUrl,
      answerRestricted: isAnswerRestricted(test, resolvedAnswerUrl, academyAccessAllowed),
      canOpenAnswerUrl: canOpenAnswer(resolvedAnswerUrl, academyAccessAllowed),
    });
  }

  function pendingCount(items) {
    return (Array.isArray(items) ? items : []).filter(item => {
      return !['done', 'skip'].includes(normalizeStatus(item?.status));
    }).length;
  }

  function shouldOpenAnswerInSameTab({ width = 0, coarsePointer = false, touchPoints = 0 } = {}) {
    const viewportWidth = Number(width || 0);
    const viewportLooksMobileOrTablet = viewportWidth > 0 && viewportWidth <= 1024;
    return viewportLooksMobileOrTablet || !!coarsePointer || Number(touchPoints || 0) > 0;
  }

  global.StudentTestPresentation = Object.freeze({
    answerUrl,
    canOpenAnswer,
    difficultyLabel,
    isAnswerRestricted,
    metaText,
    normalizeAssignedTests,
    normalizeStatus,
    pendingCount,
    roundLabel,
    shouldOpenAnswerInSameTab,
    statusLabel,
    viewModel,
  });
})(window);
