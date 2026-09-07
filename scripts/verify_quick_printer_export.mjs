import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';


const ROOT = path.resolve(import.meta.dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'static', 'admin.html'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'static', 'css', 'admin.css'), 'utf8');
const main = fs.readFileSync(path.join(ROOT, 'static', 'js', 'admin', 'main.js'), 'utf8');
const exporter = fs.readFileSync(
  path.join(ROOT, 'static', 'js', 'admin', 'features', 'quickPrinterExport.js'),
  'utf8',
);
const existingExporter = fs.readFileSync(
  path.join(ROOT, 'static', 'js', 'admin', 'features', 'exportLogs.js'),
  'utf8',
);
const sharedDownload = fs.readFileSync(
  path.join(ROOT, 'static', 'js', 'shared', 'download.js'),
  'utf8',
);
const contractPath = path.join(
  ROOT,
  'static',
  'js',
  'admin',
  'features',
  'quickPrinterExportContract.js',
);
const {
  QUICK_PRINTER_TIME_GROUPS,
  collectQuickPrinterStudents,
  collectQuickPrinterStudentIds,
  filterQuickPrinterStudentIds,
  formatQuickPrinterAutomaticExclusion,
  formatQuickPrinterExportIssues,
  isQuickPrinterDownloadPayload,
  quickPrinterTimeGroupForRow,
  summarizeQuickPrinterTimeGroups,
} = await import(pathToFileURL(contractPath).href);

const logsIndex = html.indexOf('id="exportLogs"');
const rosterIndex = html.indexOf('id="exportRoster"');
const quickIndex = html.indexOf('id="exportQuickPrinterTests"');
assert.ok(logsIndex >= 0, 'existing log export button is missing');
assert.ok(rosterIndex > logsIndex, 'existing roster export button order changed');
assert.ok(quickIndex > rosterIndex, 'test print button is not below the existing export buttons');
assert.match(
  html,
  /<button id="exportQuickPrinterTests" class="btn secondary" type="button">테스트 인쇄<\/button>/,
  'test print button does not reuse the existing export button class',
);
assert.ok(html.includes('&amp;quickPrint=3'), 'admin entry cache key was not advanced');

for (const id of [
  'quickPrinterExportModal',
  'quickPrinterExportForm',
  'quickPrinterExportClose',
  'quickPrinterExportDate',
  'quickPrinterTimeSlot1',
  'quickPrinterTimeConsecutive',
  'quickPrinterTimeSlot2',
  'quickPrinterExportSelectAll',
  'quickPrinterExportCancel',
  'quickPrinterExportSubmit',
  'quickPrinterExportStatus',
  'quickPrinterCarryoverExclusionSummary',
  'quickPrinterIncludeReprints',
]) {
  assert.ok(html.includes(`id="${id}"`), `quick-printer dialog is missing #${id}`);
}
assert.match(
  html,
  /id="quickPrinterExportModal"[\s\S]*?role="dialog"[\s\S]*?aria-modal="true"/,
  'quick-printer target picker lacks dialog semantics',
);
assert.ok(html.includes('1·2타임 (연강)'), 'consecutive-time option is missing');
assert.ok(
  html.includes('이미 출력한 결석 이월 항목도 포함(재인쇄)'),
  'explicit carryover reprint option is missing',
);
assert.ok(
  !/<input id="quickPrinterIncludeReprints"[^>]*\schecked(?:\s|>)/.test(html),
  'carryover reprint option must default off',
);

assert.ok(
  main.includes("import { initQuickPrinterExport } from './features/quickPrinterExport.js?v=20260830-carryover-history1';"),
  'admin entry does not import the quick-printer feature',
);
assert.ok(main.includes('initExport();\ninitQuickPrinterExport();'), 'quick-printer init is not adjacent to existing exports');
assert.ok(
  main.includes('exportLogs.js?v=20260826-roster-current-content2&quickPrinter=1'),
  'existing export module cache key was not advanced without replacing the module',
);

assert.ok(exporter.includes("getAdminDate()"), 'selected administrator operating date is not reused');
assert.ok(!exporter.includes('todayLocalKey'), 'real local date leaked into selected-date export');
assert.ok(
  exporter.includes("const QUICK_PRINTER_EXPORT_URL = '/api/tests/quick-printer-export';"),
  'quick-printer export endpoint changed',
);
assert.ok(
  exporter.includes("const QUICK_PRINTER_PREVIEW_URL = '/api/tests/quick-printer-export/preview';"),
  'quick-printer exclusion preview endpoint is missing',
);
assert.ok(exporter.includes('sendJson('), 'shared JSON request helper is not reused');
assert.ok(exporter.includes('downloadTextFile('), 'existing download helper is not reused');
assert.ok(exporter.includes("button.addEventListener('click', openDialog)"), 'test print button does not open the target picker');
assert.ok(exporter.includes('filterQuickPrinterStudentIds(activeStudents, readSelectedGroups())'), 'selected time groups do not control student IDs');
assert.ok(exporter.includes('activeDate = dateStr'), 'dialog does not freeze the selected operating date');
assert.ok(exporter.includes('includePreviouslyExportedCarryovers: includeReprints'), 'reprint option is not sent as an exact request field');
assert.ok(exporter.includes('isQuickPrinterDownloadPayload(payload)'), 'browser download is not gated by the nonempty BOM payload contract');
assert.ok(sharedDownload.includes('export function downloadTextFile('), 'shared download helper is not exported');
assert.ok(
  existingExporter.includes("from '../../shared/download.js?v=20260828-1'"),
  'existing log/roster exports do not reuse the shared download helper',
);

const todayRows = [
  { dataset: { sid: '20', date: '2026-08-28', slotGroup: '1' } },
  { dataset: { sid: '10', date: '2026-08-28', slotGroup: '1,2' } },
  { dataset: { sid: '40', date: '2026-08-28', slotGroup: '2' } },
  { dataset: { sid: '99', date: '2026-08-27', slotGroup: '1' } },
];
const doneRows = [
  { dataset: { sid: '10', date: '2026-08-28', slotGroup: '1,2' } },
  { dataset: { sid: '30', date: '2026-08-28', slotGroup: '2' } },
  { dataset: { sid: '50', date: '2026-08-28' } },
];
const fakeDocument = {
  querySelectorAll(selector) {
    if (selector.startsWith('#todayWrap')) return todayRows;
    if (selector.startsWith('#doneWrap')) return doneRows;
    return [];
  },
};
assert.deepEqual(
  collectQuickPrinterStudentIds(fakeDocument, '2026-08-28'),
  ['20', '10', '40', '30', '50'],
  'rendered student order/date filter/deduplication changed',
);

assert.equal(
  formatQuickPrinterAutomaticExclusion({
    automaticExclusionStudentCount: 2,
    automaticExclusionCount: 3,
  }),
  '결석 이월 재배정 자동 제외: 2명 · 3건',
  'automatic exclusion summary changed',
);
assert.equal(
  formatQuickPrinterAutomaticExclusion({
    automaticExclusionStudentCount: 2,
    automaticExclusionCount: 3,
  }, true),
  '결석 이월 재배정 자동 제외: 2명 · 3건 · 재인쇄 포함 중',
  'reprint-enabled summary changed',
);
assert.equal(
  isQuickPrinterDownloadPayload({
    rowCount: 0,
    filename: 'empty.csv',
    csv: '\uFEFF주문번호,자료ID\r\n',
  }),
  false,
  'zero-row response can still trigger a download',
);
assert.equal(
  isQuickPrinterDownloadPayload({
    rowCount: 1,
    filename: 'one.csv',
    csv: '\uFEFF주문번호,자료ID\r\n1,A\r\n',
  }),
  true,
  'valid nonempty BOM response no longer triggers a download',
);

const collectedStudents = collectQuickPrinterStudents(fakeDocument, '2026-08-28');
assert.deepEqual(
  filterQuickPrinterStudentIds(collectedStudents, [QUICK_PRINTER_TIME_GROUPS.SLOT1]),
  ['20', '50'],
  'first-time selection includes the wrong students',
);
assert.deepEqual(
  filterQuickPrinterStudentIds(collectedStudents, [QUICK_PRINTER_TIME_GROUPS.CONSECUTIVE]),
  ['10'],
  'consecutive-time selection includes the wrong students',
);
assert.deepEqual(
  filterQuickPrinterStudentIds(collectedStudents, [QUICK_PRINTER_TIME_GROUPS.SLOT2]),
  ['40', '30'],
  'second-time selection includes the wrong students',
);
assert.deepEqual(
  filterQuickPrinterStudentIds(collectedStudents, [
    QUICK_PRINTER_TIME_GROUPS.CONSECUTIVE,
    QUICK_PRINTER_TIME_GROUPS.SLOT2,
  ]),
  ['10', '40', '30'],
  'multi-group selection no longer preserves rendered board order',
);
assert.deepEqual(
  summarizeQuickPrinterTimeGroups(collectedStudents),
  { slot1: 2, consecutive: 1, slot2: 2 },
  'time-group counts do not match the deduplicated board rows',
);
assert.equal(
  quickPrinterTimeGroupForRow({
    dataset: {},
    querySelector: () => ({ textContent: '월1 월2' }),
  }),
  QUICK_PRINTER_TIME_GROUPS.CONSECUTIVE,
  'visible slot-label fallback does not recognize consecutive students',
);

const issueText = formatQuickPrinterExportIssues({
  message: '전체 생성을 중단했습니다.',
  issues: [
    {
      studentName: '한동훈',
      testName: '대수 복습 5회차',
      reason: '정확히 일치하는 자료가 두 개입니다.',
      candidates: [
        {
          materialId: 'QT-REVIEW-1',
          displayName: '대수 복습 5회차',
          relativePath: '대수/중간/5회차.pdf',
        },
      ],
    },
  ],
});
assert.match(issueText, /한동훈 · 대수 복습 5회차/);
assert.match(issueText, /정확히 일치하는 자료가 두 개입니다/);
assert.match(issueText, /\[QT-REVIEW-1\].*대수\/중간\/5회차\.pdf/);

assert.match(
  css,
  /body\.admin\.admin-simple \.hero-actions #exportQuickPrinterTests\s*\{\s*display:\s*none !important;\s*\}/,
  'simple layout does not keep the new export control out of the fixed two-button action area',
);
assert.match(
  css,
  /body\.admin #quickPrinterExportModal \.quick-printer-reprint-option\s*\{/,
  'reprint option styles are not scoped to the existing modal',
);
const quickPrinterCssRules = css.match(/[^{}]*#exportQuickPrinterTests[^{}]*\{[^{}]*\}/g) || [];
assert.equal(quickPrinterCssRules.length, 1, 'test print button received unexpected layout-specific CSS');
assert.ok(!quickPrinterCssRules[0].match(/(?:width|height|grid-template|padding|margin)\s*:/), 'test print CSS changes dimensions');
assert.match(
  css,
  /body\.admin #quickPrinterExportModal \.quick-printer-export-panel\s*\{/,
  'quick-printer target picker styles are not narrowly scoped',
);
assert.match(
  css,
  /body\.admin #quickPrinterExportModal \.quick-printer-time-grid\s*\{[\s\S]*?grid-template-columns:\s*repeat\(3,/,
  'desktop target picker does not keep the three time groups together',
);
assert.match(
  css,
  /@media \(max-width: 640px\)[\s\S]*?#quickPrinterExportModal \.quick-printer-time-grid\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\)/,
  'mobile target picker does not stack the time groups',
);

const todaySectionStart = html.indexOf('id="todaySection"');
const todaySectionEnd = html.indexOf('id="doneSection"');
assert.ok(todaySectionStart >= 0 && todaySectionEnd > todaySectionStart, 'today board DOM anchors are missing');
assert.ok(
  !html.slice(todaySectionStart, todaySectionEnd).includes('exportQuickPrinterTests'),
  'test print button changed the today board DOM dimensions',
);

console.log('quick-printer frontend export contract: OK');
