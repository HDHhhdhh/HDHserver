export const QUICK_PRINTER_TIME_GROUPS = Object.freeze({
  SLOT1: 'slot1',
  CONSECUTIVE: 'consecutive',
  SLOT2: 'slot2',
});

export const QUICK_PRINTER_TIME_GROUP_VALUES = Object.freeze(
  Object.values(QUICK_PRINTER_TIME_GROUPS),
);

function rowSlotNumbers(row) {
  const stored = String(row?.dataset?.slotGroup || '').trim();
  const label = stored
    ? ''
    : String(
      row?.querySelector?.('.slotLabel, .slotLabelReadonly')?.textContent || '',
    ).trim();

  return Array.from(new Set((stored || label).match(/[1-3]/g) || []))
    .map(Number)
    .filter(slot => slot === 1 || slot === 2 || slot === 3)
    .sort((left, right) => left - right);
}

export function quickPrinterTimeGroupForRow(row) {
  const slots = rowSlotNumbers(row);
  if (slots.length >= 2) return QUICK_PRINTER_TIME_GROUPS.CONSECUTIVE;
  if (slots.length === 1 && slots[0] === 2) return QUICK_PRINTER_TIME_GROUPS.SLOT2;
  if (slots.length === 1 && slots[0] !== 1) return QUICK_PRINTER_TIME_GROUPS.CONSECUTIVE;
  // Rows without a usable slot are kept with the first-time fallback used by the board.
  return QUICK_PRINTER_TIME_GROUPS.SLOT1;
}

export function collectQuickPrinterStudents(documentRef, dateStr) {
  const targetDate = String(dateStr || '').trim();
  const selectors = [
    '#todayWrap tr[data-sid][data-date]',
    '#doneWrap tr[data-sid][data-date]',
  ];
  const students = [];
  const seen = new Set();

  selectors.forEach(selector => {
    const rows = Array.from(documentRef?.querySelectorAll?.(selector) || []);
    rows.forEach(row => {
      if (String(row?.dataset?.date || '').trim() !== targetDate) return;
      const sid = String(row?.dataset?.sid || '').trim();
      if (!sid || seen.has(sid)) return;
      seen.add(sid);
      students.push({
        sid,
        timeGroup: quickPrinterTimeGroupForRow(row),
      });
    });
  });

  return students;
}

export function filterQuickPrinterStudentIds(students, selectedGroups = QUICK_PRINTER_TIME_GROUP_VALUES) {
  const allowed = new Set(
    Array.from(selectedGroups || []).filter(group => QUICK_PRINTER_TIME_GROUP_VALUES.includes(group)),
  );
  return Array.from(students || [])
    .filter(student => allowed.has(student?.timeGroup))
    .map(student => String(student?.sid || '').trim())
    .filter(Boolean);
}

export function summarizeQuickPrinterTimeGroups(students) {
  const counts = Object.fromEntries(QUICK_PRINTER_TIME_GROUP_VALUES.map(group => [group, 0]));
  Array.from(students || []).forEach(student => {
    if (Object.prototype.hasOwnProperty.call(counts, student?.timeGroup)) {
      counts[student.timeGroup] += 1;
    }
  });
  return counts;
}

export function formatQuickPrinterAutomaticExclusion(payload, includeReprints = false) {
  const studentCount = Math.max(0, Number(payload?.automaticExclusionStudentCount) || 0);
  const assignmentCount = Math.max(0, Number(payload?.automaticExclusionCount) || 0);
  const suffix = includeReprints && assignmentCount ? ' · 재인쇄 포함 중' : '';
  return `결석 이월 재배정 자동 제외: ${studentCount}명 · ${assignmentCount}건${suffix}`;
}

export function isQuickPrinterDownloadPayload(payload) {
  return Number(payload?.rowCount) > 0
    && typeof payload?.csv === 'string'
    && payload.csv.startsWith('\uFEFF')
    && Boolean(String(payload?.filename || '').trim());
}

export function collectQuickPrinterStudentIds(
  documentRef,
  dateStr,
  selectedGroups = QUICK_PRINTER_TIME_GROUP_VALUES,
) {
  return filterQuickPrinterStudentIds(
    collectQuickPrinterStudents(documentRef, dateStr),
    selectedGroups,
  );
}

export function formatQuickPrinterExportIssues(payload, maxIssues = 12) {
  const message = String(payload?.message || '테스트 인쇄 CSV를 만들 수 없습니다.').trim();
  const issues = Array.isArray(payload?.issues) ? payload.issues : [];
  if (!issues.length) return message;

  const limit = Math.max(1, Number(maxIssues) || 12);
  const lines = [message, ''];
  issues.slice(0, limit).forEach((issue, index) => {
    const student = String(issue?.studentName || issue?.studentId || '').trim();
    const testName = String(issue?.testName || issue?.testLabel || issue?.testId || '').trim();
    const reason = String(issue?.reason || issue?.code || '매칭 실패').trim();
    lines.push(`${index + 1}. ${student ? `${student} · ` : ''}${testName || '시험 정보 없음'}`);
    lines.push(`   원인: ${reason}`);

    const candidates = Array.isArray(issue?.candidates) ? issue.candidates : [];
    candidates.slice(0, 5).forEach(candidate => {
      const materialId = String(candidate?.materialId || candidate?.testId || '').trim();
      const displayName = String(candidate?.displayName || candidate?.testName || '').trim();
      const relativePath = String(candidate?.relativePath || '').trim();
      const details = [displayName, relativePath].filter(Boolean).join(' · ');
      lines.push(`   후보: ${materialId ? `[${materialId}] ` : ''}${details || '세부 정보 없음'}`);
    });
  });
  if (issues.length > limit) lines.push('', `외 ${issues.length - limit}건`);
  return lines.join('\n');
}
