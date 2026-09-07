function cleanText(value) {
  return String(value ?? '').trim();
}

function hasExplicitHomeworkValue(row) {
  return Boolean(
    cleanText(row?.this)
    || cleanText(row?.pct)
    || cleanText(row?.comment)
    || cleanText(row?.next)
  );
}

export function previousHomeworkText(row) {
  return cleanText(row?.next) || cleanText(row?.this);
}

/**
 * 숙검 완료 시 비어 있는 교재 행만 직전 숙제로 이어받는다.
 * 일반 저장이나 사용자가 일부라도 입력한 행은 건드리지 않는다.
 */
export function projectBlankHomeworkCheckCarryover(rows) {
  if (!Array.isArray(rows)) return [];

  return rows.map(raw => {
    const row = raw && typeof raw === 'object' ? raw : {};
    const previous = cleanText(row.previousThis);
    const canCarry = row.deleted !== true
      && row.sleeping !== true
      && !hasExplicitHomeworkValue(row)
      && previous
      && previous !== '숙제 없음';

    return canCarry
      ? { ...row, this: previous, pct: '0', carriedFromPrevious: true }
      : { ...row, carriedFromPrevious: false };
  });
}
