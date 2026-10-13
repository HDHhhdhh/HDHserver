const EXPORT_PATH = '/api/tests/quick-printer-export';
const PREVIEW_PATH = '/api/tests/quick-printer-export/preview';
const AUTO_CARRYOVER_COUNTS = Object.freeze({
  'demo-s001': 2,
  'demo-s005': 1,
});

function text(value) {
  return String(value || '').trim();
}

function uniqueStudentIds(values, store) {
  const known = new Set((store?.students || []).map(student => text(student?.id)).filter(Boolean));
  const seen = new Set();
  return (Array.isArray(values) ? values : []).map(text).filter(sid => {
    if (!sid || !known.has(sid) || seen.has(sid)) return false;
    seen.add(sid);
    return true;
  });
}

function csvCell(value) {
  const raw = String(value ?? '');
  return /[",\r\n]/.test(raw) ? `"${raw.replaceAll('"', '""')}"` : raw;
}

function csvForRows(rows) {
  const lines = ['주문번호,자료ID,학생이름,부수,메모'];
  rows.forEach(row => {
    lines.push([
      row.orderId,
      row.materialId,
      row.studentName,
      '1',
      '',
    ].map(csvCell).join(','));
  });
  return `\uFEFF${lines.join('\r\n')}\r\n`;
}

function exclusionMessage(studentCount, assignmentCount) {
  return `결석 이월 재배정 ${assignmentCount}건(${studentCount}명)은 이전 CSV 내보내기 이력이 있어 자동 제외되었습니다. 재인쇄 옵션을 켜면 포함할 수 있습니다.`;
}

export function applyDemoQuickPrinterRequest({ method, path, body, store, createdAt }) {
  if (String(method || '').toUpperCase() !== 'POST') return null;
  if (path !== EXPORT_PATH && path !== PREVIEW_PATH) return null;
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    return { status: 400, changed: false, payload: { ok: false, code: 'invalid_payload', message: 'JSON 요청 본문이 필요합니다.' } };
  }
  if (
    Object.prototype.hasOwnProperty.call(body, 'includePreviouslyExportedCarryovers') &&
    typeof body.includePreviouslyExportedCarryovers !== 'boolean'
  ) {
    return { status: 400, changed: false, payload: { ok: false, code: 'invalid_reprint_option', message: '재인쇄 포함 옵션은 JSON boolean이어야 합니다.' } };
  }

  const date = text(body.date);
  const studentIds = uniqueStudentIds(body.studentIds, store);
  const includeReprints = body.includePreviouslyExportedCarryovers === true;
  const preview = path === PREVIEW_PATH;
  if (!date || !studentIds.length) {
    return { status: 422, changed: false, payload: { ok: false, code: 'no_board_students', message: '현재 운영판에 내보낼 학생이 없습니다.' } };
  }

  const studentById = new Map((store.students || []).map(student => [text(student?.id), student]));
  const freshRows = [];
  const carryoverRows = [];
  studentIds.forEach(sid => {
    const studentName = text(studentById.get(sid)?.name) || sid;
    const carryoverCount = Number(AUTO_CARRYOVER_COUNTS[sid] || 0);
    for (let index = 0; index < carryoverCount; index += 1) {
      carryoverRows.push({
        sid,
        studentName,
        orderId: `DEMO-CARRYOVER-${date.replaceAll('-', '')}-${sid}-${index + 1}`,
        materialId: `DEMO-CARRYOVER-${sid}-${index + 1}`,
      });
    }
    if (!carryoverCount) {
      freshRows.push({
        sid,
        studentName,
        orderId: `DEMO-ASSIGN-${date.replaceAll('-', '')}-${sid}`,
        materialId: `DEMO-FRESH-${sid}`,
      });
    }
  });

  const automaticExclusionStudentCount = new Set(carryoverRows.map(row => row.sid)).size;
  const automaticExclusionCount = carryoverRows.length;
  const rows = includeReprints ? [...freshRows, ...carryoverRows] : freshRows;
  const message = automaticExclusionCount
    ? exclusionMessage(automaticExclusionStudentCount, automaticExclusionCount)
    : '';
  const base = {
    automaticExclusionCount,
    automaticExclusionStudentCount,
    includedReprints: includeReprints,
    rowCount: rows.length,
    studentCount: new Set(rows.map(row => row.sid)).size,
    date,
    ...(message ? { message } : {}),
  };

  if (!rows.length) {
    if (preview && automaticExclusionCount) {
      return { status: 200, changed: false, payload: { ok: true, demo: true, ...base } };
    }
    return {
      status: 422,
      changed: false,
      payload: {
        ok: false,
        demo: true,
        code: automaticExclusionCount
          ? 'no_new_assignments_after_carryover_exclusion'
          : 'no_assigned_tests',
        message: message || `${date} 운영판에 초록색으로 배정된 테스트가 없습니다.`,
        ...base,
      },
    };
  }

  if (preview) {
    return { status: 200, changed: false, payload: { ok: true, demo: true, ...base } };
  }

  store.quickPrinterExports = Array.isArray(store.quickPrinterExports) ? store.quickPrinterExports : [];
  store.quickPrinterExports.push({
    date,
    studentIds: rows.map(row => row.sid),
    rowCount: rows.length,
    includeReprints,
    createdAt: typeof createdAt === 'function' ? createdAt() : new Date().toISOString(),
  });
  return {
    status: 200,
    changed: true,
    payload: {
      ok: true,
      demo: true,
      ...base,
      filename: `빠른인쇄기_테스트인쇄_${date.replaceAll('-', '')}.csv`,
      csv: csvForRows(rows),
    },
  };
}

export const DEMO_QUICK_PRINTER_PATHS = Object.freeze({
  export: EXPORT_PATH,
  preview: PREVIEW_PATH,
});
