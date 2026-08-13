import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const formatPath = path.join(ROOT, 'static', 'js', 'admin', 'features', 'exportLogFormat.js');
const exporterPath = path.join(ROOT, 'static', 'js', 'admin', 'features', 'exportLogs.js');
const htmlPath = path.join(ROOT, 'static', 'admin.html');
const cssPath = path.join(ROOT, 'static', 'css', 'admin.css');
const mainPath = path.join(ROOT, 'static', 'js', 'admin', 'main.js');

const format = await import(`${pathToFileURL(formatPath).href}?verify=${Date.now()}`);
const exporterSource = fs.readFileSync(exporterPath, 'utf8');
const formatSource = fs.readFileSync(formatPath, 'utf8');
const htmlSource = fs.readFileSync(htmlPath, 'utf8');
const cssSource = fs.readFileSync(cssPath, 'utf8');
const mainSource = fs.readFileSync(mainPath, 'utf8');

let checks = 0;
function ok(value, message) {
  checks += 1;
  assert.ok(value, message);
}
function equal(actual, expected, message) {
  checks += 1;
  assert.deepEqual(actual, expected, message);
}

const defaults = format.defaultExportLogOptions();
equal(defaults, {
  formats: { txt: true, csv: true },
  sections: { notes: true, tests: true, progress: true, homework: true },
}, 'default options no longer preserve the former dual export');

const normalized = format.normalizeExportLogOptions({
  formats: { txt: false, csv: true, pdf: true },
  sections: { notes: false, tests: true, progress: 'false', homework: true, privateNotes: true },
  studentName: 'must-not-persist',
});
equal(normalized, {
  formats: { txt: false, csv: true },
  sections: { notes: false, tests: true, progress: true, homework: true },
}, 'option normalization accepted unknown or non-boolean data');
ok(!JSON.stringify(normalized).includes('must-not-persist'), 'normalized preferences retained student data');
ok(!Object.hasOwn(normalized.formats, 'pdf'), 'unknown format survived normalization');
ok(!Object.hasOwn(normalized.sections, 'privateNotes'), 'unknown section survived normalization');
equal(format.normalizeExportLogOptions(null), defaults, 'null options did not fall back safely');

equal(
  format.validateExportLogOptions({ formats: { txt: false, csv: false } }).code,
  'format_required',
  'zero-format selection was accepted',
);
equal(
  format.validateExportLogOptions({
    formats: { txt: true, csv: false },
    sections: { notes: false, tests: false, progress: false, homework: false },
  }).code,
  'txt_section_required',
  'TXT without a section was accepted',
);
ok(format.validateExportLogOptions({
  formats: { txt: false, csv: true },
  sections: { notes: false, tests: false, progress: false, homework: false },
}).ok, 'CSV-only export incorrectly requires TXT sections');

const records = [
  {
    date: '2026-08-12',
    sid: 'sid-a',
    name: '김하늘',
    school: '빛가람고',
    curriculum: '대수 정규',
    notes: '발표 좋음',
    testLines: ['단원 90 (오답: 2)'],
    diffs: ['1차시', '2차시(중단)'],
    homeworkRows: [
      { book: '교재', thisHw: '10쪽', pct: '50%', comment: '확인', nextHw: '12쪽' },
      { book: '부교재', thisHw: '3번', pct: '', comment: '', nextHw: '4번' },
    ],
    hwBlock: `숙제 :\n${format.HW_HEADER_LINE}\n교재 / 10쪽 / 50% / 확인 / 12쪽`,
    hwHasContent: true,
    hasSpecial: true,
    hasTests: true,
    headerDate: '8/12',
  },
  {
    date: '2026-08-13',
    sid: 'sid-b',
    name: '이바다',
    school: '하늘고',
    curriculum: '미적분 심화',
    notes: '연락 필요',
    testLines: [],
    diffs: [],
    homeworkRows: [],
    hwBlock: `숙제 :\n${format.HW_HEADER_LINE}\n`,
    hwHasContent: false,
    hasSpecial: true,
    hasTests: false,
    headerDate: '8/13',
  },
];

const expectedDefaultText =
  `(8/12) 김하늘\n` +
  `특이사항 : 발표 좋음\n\n` +
  `테스트 : 단원 90 (오답: 2)\n\n` +
  `진도 (대수 정규) : 1차시, 2차시(중단)\n\n` +
  `숙제 :\n${format.HW_HEADER_LINE}\n교재 / 10쪽 / 50% / 확인 / 12쪽\n\n\n` +
  `(8/13) 이바다\n` +
  `특이사항 : 연락 필요\n\n` +
  `진도 (미적분 심화) : \n\n` +
  `숙제 :\n${format.HW_HEADER_LINE}\n\n\n`;
equal(format.renderClassLogText(records, defaults), expectedDefaultText, 'default TXT output changed');

const onlySection = section => ({
  formats: { txt: true, csv: false },
  sections: {
    notes: section === 'notes',
    tests: section === 'tests',
    progress: section === 'progress',
    homework: section === 'homework',
  },
});

const notesText = format.renderClassLogText(records, onlySection('notes'));
ok(notesText.includes('특이사항 : 발표 좋음'), 'notes selection omitted notes');
ok(notesText.includes('(8/13) 이바다'), 'notes selection dropped a notes-only record');
ok(!notesText.includes('테스트 :'), 'notes-only TXT leaked tests');
ok(!notesText.includes('진도 ('), 'notes-only TXT leaked progress');
ok(!notesText.includes('숙제 :'), 'notes-only TXT leaked homework');

const testsText = format.renderClassLogText(records, onlySection('tests'));
ok(testsText.includes('(8/12) 김하늘'), 'tests-only TXT dropped matching record');
ok(!testsText.includes('이바다'), 'tests-only TXT retained an empty record');
ok(testsText.includes('테스트 : 단원 90'), 'tests-only TXT omitted test content');

const progressText = format.renderClassLogText(records, onlySection('progress'));
ok(progressText.includes('진도 (대수 정규)'), 'progress-only TXT omitted progress');
ok(!progressText.includes('이바다'), 'progress-only TXT retained a record with no progress change');

const homeworkText = format.renderClassLogText(records, onlySection('homework'));
ok(homeworkText.includes('교재 / 10쪽'), 'homework-only TXT omitted homework');
ok(!homeworkText.includes('이바다'), 'homework-only TXT retained a record with no homework');
equal(format.filterClassLogRecords(records, onlySection('tests')).length, 1, 'selected-section filtering is incorrect');

const csv = format.recordsToCsv(records);
ok(csv.startsWith('\uFEFFdate,sid,name,school,curriculum,notes,tests,progress,homework_row,'), 'CSV BOM/header contract changed');
ok(csv.endsWith('\r\n'), 'CSV no longer ends with CRLF');
equal(csv.split('\r\n').length, 5, 'CSV homework row expansion changed');
ok(csv.includes('2026-08-12,sid-a,김하늘,빛가람고'), 'CSV lost the first record');
ok(csv.includes('2026-08-13,sid-b,이바다,하늘고'), 'CSV lost the no-homework record');
equal(format.csvCell('한글,쉼표'), '"한글,쉼표"', 'CSV comma escaping changed');
equal(format.csvCell('따옴표"값'), '"따옴표""값"', 'CSV quote escaping changed');
equal(format.csvCell('줄1\n줄2'), '"줄1\n줄2"', 'CSV newline escaping changed');
equal(format.csvCell('=HYPERLINK("https://invalid")'), '"\'=HYPERLINK(""https://invalid"")"', 'CSV formula was not neutralized');
equal(format.csvCell('  @SUM(1,2)'), '"\'  @SUM(1,2)"', 'space-prefixed CSV formula was not neutralized');
equal(format.csvCell('-1'), "'-1", 'minus-prefixed CSV formula was not neutralized');

for (const id of [
  'exportLogsModal', 'exportLogsForm', 'exportLogsClose', 'exportLogsFormatTxt', 'exportLogsFormatCsv',
  'exportLogsTxtSections', 'exportLogsSectionNotes', 'exportLogsSectionTests', 'exportLogsSectionProgress',
  'exportLogsSectionHomework', 'exportLogsReset', 'exportLogsCancel', 'exportLogsSubmit', 'exportLogsStatus',
]) {
  ok(htmlSource.includes(`id="${id}"`), `admin shell is missing #${id}`);
}
ok(/id="exportLogsModal"[\s\S]*role="dialog"[\s\S]*aria-modal="true"/.test(htmlSource), 'export modal lacks dialog semantics');
ok(htmlSource.includes('설정은 현재 페이지에서만 유지됩니다.'), 'UI does not disclose preference lifetime');
ok(htmlSource.includes('CSV 열 구조는 기존 연동을 위해 고정됩니다.'), 'UI does not disclose stable CSV schema');
ok(cssSource.includes('body.admin #exportLogsModal .export-logs-panel'), 'export modal styles are not narrowly scoped');
ok(cssSource.includes('@media (max-width: 640px)'), 'export modal has no mobile breakpoint');
ok(mainSource.includes("exportLogs.js?v=20260813-phase12"), 'admin entry lacks Phase 12 export cache bust');

ok(exporterSource.includes("btn.addEventListener('click', openDialog)"), 'button does not open the settings dialog');
ok(exporterSource.includes('async function exportClassLogs(rawOptions, { signal } = {})'), 'export execution was not isolated from dialog open');
ok(exporterSource.indexOf("btn.addEventListener('click', openDialog)") > exporterSource.indexOf('async function exportClassLogs'), 'dialog wiring is malformed');
ok(exporterSource.includes("if (options.formats.txt)"), 'TXT format selection is ignored');
ok(exporterSource.includes("if (options.formats.csv)"), 'CSV format selection is ignored');
ok(exporterSource.includes('recordsToCsv(records)'), 'CSV projection no longer uses the stable full record schema');
ok(!exporterSource.includes('localStorage') && !exporterSource.includes('sessionStorage'), 'export preferences leaked into browser storage');
ok(!exporterSource.includes('assistantStudentNotes') && !formatSource.includes('assistantStudentNotes'), 'assistant notes entered the export surface');
ok(exporterSource.includes("event.key === 'Escape'"), 'export dialog has no Escape handler');
ok(exporterSource.includes("event.key !== 'Tab'"), 'export dialog has no focus trap');
ok(exporterSource.includes('if (exportInFlight) return'), 'export dialog lacks duplicate-submit protection');

async function verifyBusyEscapeAbortsAndRestoresFocus() {
  class FakeClassList {
    constructor() { this.values = new Set(); }
    add(value) { this.values.add(value); }
    remove(value) { this.values.delete(value); }
    toggle(value, force) {
      if (force === true) this.values.add(value);
      else if (force === false) this.values.delete(value);
      else if (this.values.has(value)) this.values.delete(value);
      else this.values.add(value);
    }
    contains(value) { return this.values.has(value); }
  }

  class FakeElement {
    constructor(id, owner) {
      this.id = id;
      this.owner = owner;
      this.listeners = new Map();
      this.classList = new FakeClassList();
      this.style = {};
      this.hidden = id === 'exportLogsModal';
      this.disabled = false;
      this.checked = true;
      this.textContent = '';
      this.attributes = new Map();
      this.offsetParent = {};
    }
    addEventListener(type, callback) {
      const listeners = this.listeners.get(type) || [];
      listeners.push(callback);
      this.listeners.set(type, listeners);
    }
    dispatch(type, event = {}) {
      for (const callback of this.listeners.get(type) || []) callback({ target: this, ...event });
    }
    focus() { this.owner.activeElement = this; }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    contains(target) { return this === target || this.owner.modalChildren.has(target); }
    querySelectorAll() { return [...this.owner.modalChildren]; }
  }

  const ids = [
    'exportLogs', 'exportLogsModal', 'exportLogsForm', 'exportLogsClose', 'exportLogsCancel',
    'exportLogsReset', 'exportLogsSubmit', 'exportLogsStatus', 'exportLogsFormatTxt',
    'exportLogsFormatCsv', 'exportLogsTxtSections', 'exportLogsSectionNotes',
    'exportLogsSectionTests', 'exportLogsSectionProgress', 'exportLogsSectionHomework',
  ];
  const fakeDocument = {
    activeElement: null,
    modalChildren: new Set(),
    listeners: new Map(),
    body: { classList: new FakeClassList(), appendChild() {} },
    addEventListener(type, callback) { this.listeners.set(type, callback); },
    getElementById(id) { return this.elements.get(id) || null; },
  };
  fakeDocument.elements = new Map(ids.map(id => [id, new FakeElement(id, fakeDocument)]));
  const modal = fakeDocument.elements.get('exportLogsModal');
  for (const [id, element] of fakeDocument.elements) {
    if (!['exportLogs', 'exportLogsModal'].includes(id)) fakeDocument.modalChildren.add(element);
  }
  const opener = fakeDocument.elements.get('exportLogs');
  fakeDocument.activeElement = opener;

  const abortedSignals = [];
  globalThis.window = { addEventListener() {} };
  globalThis.document = fakeDocument;
  globalThis.sessionStorage = { getItem() { return null; }, setItem() {} };
  globalThis.requestAnimationFrame = callback => { callback(); return 1; };
  globalThis.fetch = (_url, { signal } = {}) => new Promise((_resolve, reject) => {
    abortedSignals.push(signal);
    signal.addEventListener('abort', () => {
      const error = new Error('aborted');
      error.name = 'AbortError';
      reject(error);
    }, { once: true });
  });

  const exporter = await import(`${pathToFileURL(exporterPath).href}?busy=${Date.now()}`);
  exporter.initExport();
  opener.dispatch('click');
  const form = fakeDocument.elements.get('exportLogsForm');
  form.dispatch('submit', { preventDefault() {} });
  const submit = fakeDocument.elements.get('exportLogsSubmit');
  equal(submit.attributes.get('aria-disabled'), 'true', 'busy submit is not exposed as unavailable');
  ok(!fakeDocument.elements.get('exportLogsClose').disabled, 'busy dialog disabled its close button');

  const escape = { key: 'Escape', preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } };
  modal.dispatch('keydown', escape);
  await new Promise(resolve => setTimeout(resolve, 0));

  equal(abortedSignals.length, 2, 'submit did not start both guarded export reads');
  ok(abortedSignals.every(signal => signal.aborted), 'Escape did not abort every export read');
  ok(modal.hidden && modal.style.display === 'none', 'Escape did not close the busy dialog');
  ok(!fakeDocument.body.classList.contains('export-logs-open'), 'Escape left the page scroll lock active');
  equal(fakeDocument.activeElement, opener, 'Escape did not restore focus to the opener');
  equal(modal.attributes.get('aria-busy'), 'false', 'aborted export left the dialog busy');
}

await verifyBusyEscapeAbortsAndRestoresFocus();

console.log(JSON.stringify({
  ok: true,
  checks,
  defaultFormats: defaults.formats,
  defaultSections: defaults.sections,
  csvColumns: 14,
  privacy: 'memory-only preferences; assistant notes excluded; CSV formulas neutralized',
}, null, 2));
