function cleanText(value) {
  return String(value ?? '').trim();
}

function displayHomeworkBookKey(value) {
  return cleanText(value).replace(/\s+/g, '').toLocaleLowerCase('ko-KR');
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
 * 툴팁을 새로 열 때만 재운 교재를 아래로 모은다.
 * 각 그룹 안의 사용자 지정 순서는 그대로 유지한다.
 */
export function placeSleepingHomeworkRowsLast(rows, sleepingBooks) {
  if (!Array.isArray(rows)) return [];

  const sleepingKeys = new Set(
    (Array.isArray(sleepingBooks) ? sleepingBooks : [])
      .map(displayHomeworkBookKey)
      .filter(Boolean),
  );
  const awake = [];
  const sleeping = [];

  rows.forEach(row => {
    const key = displayHomeworkBookKey(row?.book);
    (key && sleepingKeys.has(key) ? sleeping : awake).push(row);
  });

  return [...awake, ...sleeping];
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
