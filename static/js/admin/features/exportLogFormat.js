export const HW_HEADER_LINE = '교재 / 이번 숙제 / 진행률 / 코멘트 / 다음숙제';

const FORMAT_KEYS = ['txt', 'csv'];
const SECTION_KEYS = ['notes', 'tests', 'progress', 'homework'];

export function defaultExportLogOptions() {
  return {
    formats: { txt: true, csv: true },
    sections: { notes: true, tests: true, progress: true, homework: true },
  };
}

export function normalizeExportLogOptions(value) {
  const normalized = defaultExportLogOptions();
  const source = value && typeof value === 'object' ? value : {};
  const formats = source.formats && typeof source.formats === 'object' ? source.formats : {};
  const sections = source.sections && typeof source.sections === 'object' ? source.sections : {};

  FORMAT_KEYS.forEach((key) => {
    if (typeof formats[key] === 'boolean') normalized.formats[key] = formats[key];
  });
  SECTION_KEYS.forEach((key) => {
    if (typeof sections[key] === 'boolean') normalized.sections[key] = sections[key];
  });
  return normalized;
}

export function validateExportLogOptions(value) {
  const options = normalizeExportLogOptions(value);
  if (!FORMAT_KEYS.some(key => options.formats[key])) {
    return { ok: false, code: 'format_required', message: 'TXT 또는 CSV 형식을 하나 이상 선택하세요.', options };
  }
  if (options.formats.txt && !SECTION_KEYS.some(key => options.sections[key])) {
    return { ok: false, code: 'txt_section_required', message: 'TXT에 포함할 내용을 하나 이상 선택하세요.', options };
  }
  return { ok: true, code: 'ok', message: '', options };
}



export function classLogRecordHasSelectedContent(record, value) {
  const { sections } = normalizeExportLogOptions(value);
  return !!(
    (sections.notes && record?.hasSpecial) ||
    (sections.tests && record?.hasTests) ||
    (sections.progress && Array.isArray(record?.diffs) && record.diffs.length) ||
    (sections.homework && record?.hwHasContent)
  );
}

export function filterClassLogRecords(records, value) {
  return (Array.isArray(records) ? records : [])
    .filter(record => classLogRecordHasSelectedContent(record, value));
}

export function renderClassLogText(records, value) {
  const options = normalizeExportLogOptions(value);
  const selected = filterClassLogRecords(records, options);
  let out = '';

  selected.forEach((record) => {
    out += `(${record.headerDate}) ${record.name}\n`;

    if (options.sections.notes && record.hasSpecial) {
      out += `특이사항 : ${record.notes}\n\n`;
    }
    if (options.sections.tests && record.hasTests) {
      out += `테스트 :\n${(record.testLines || []).join('\n')}\n\n`;
    }
    if (options.sections.progress) {
      out += `진도 (${record.curriculum}) : ${(record.diffs || []).join(', ')}\n\n`;
    }
    if (options.sections.homework) {
      if (record.hwHasContent) out += `${record.hwBlock}\n\n\n`;
      else out += `숙제 :\n${HW_HEADER_LINE}\n\n\n`;
    }
  });

  return out;
}

export function csvCell(value) {
  const raw = String(value ?? '');
  // Excel 등에서 셀을 수식으로 실행하지 않도록 사용자 입력을 텍스트로 고정한다.
  const safe = /^[\t\r\n ]*[=+\-@]/u.test(raw) ? `'${raw}` : raw;
  if (/[",\r\n]/.test(safe)) return `"${safe.replace(/"/g, '""')}"`;
  return safe;
}

export function recordsToCsv(records) {
  const columns = [
    'date',
    'sid',
    'name',
    'school',
    'curriculum',
    'notes',
    'tests',
    'progress',
    'homework_row',
    'homework_book',
    'homework_current',
    'homework_progress',
    'homework_comment',
    'homework_next',
  ];

  const lines = [columns.map(csvCell).join(',')];

  for (const record of Array.isArray(records) ? records : []) {
    const homeworkRows = Array.isArray(record?.homeworkRows) ? record.homeworkRows : [];
    const rows = homeworkRows.length ? homeworkRows : [null];
    rows.forEach((homework, index) => {
      lines.push([
        record?.date,
        record?.sid,
        record?.name,
        record?.school,
        record?.curriculum,
        record?.notes,
        (record?.testLines || []).join('\n'),
        (record?.diffs || []).join(', '),
        homework ? String(index + 1) : '',
        homework?.book || '',
        homework?.thisHw || '',
        homework?.pct || '',
        homework?.comment || '',
        homework?.nextHw || '',
      ].map(csvCell).join(','));
    });
  }

  return `\uFEFF${lines.join('\r\n')}\r\n`;
}
