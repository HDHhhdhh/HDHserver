import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ADMIN_CSS_PATH = path.join(ROOT, 'static', 'css', 'admin.css');
const EXPORT_CSS_PATH = path.join(ROOT, 'static', 'css', 'admin-export-logs.css');
const ADMIN_HTML_PATH = path.join(ROOT, 'static', 'admin.html');
const TESTS_HTML_PATH = path.join(ROOT, 'static', 'tests.html');
const TESTS_CSS_PATH = path.join(ROOT, 'static', 'css', 'tests.css');
const POPUP_SOURCE_PATH = path.join(ROOT, 'static', 'js', 'all', 'features', 'studentRecordPopup.js');

const EXPORT_START = 'body.admin.export-logs-open {';
const EXPORT_END = 'body.admin .admin-operation-notes {';
const EXPORT_PRE_SPLIT_SHA256 = 'fe4830147c7a4ee1d25b107a698aeceb7f42a059158e5511278b63f1a6d343ef';
const EXPORT_MODAL_DOM_SHA256 = 'cb46713d6f4c68c6c9d6fd7a783e1c327085144a641dbacdee21c8d1c675aa8f';

const normalize = value => value.replace(/\r\n/g, '\n');
const read = filename => normalize(fs.readFileSync(filename, 'utf8'));
const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');
const lineAt = (source, index) => source.slice(0, index).split('\n').length;

function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, comment => comment.replace(/[^\n]/g, ' '));
}

function matchingBrace(source, open, end) {
  let depth = 1;
  let quote = '';
  let escaped = false;
  for (let index = open + 1; index < end; index += 1) {
    const char = source[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = '';
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (char === '{') depth += 1;
    if (char === '}' && --depth === 0) return index;
  }
  throw new Error(`unclosed CSS block at offset ${open}`);
}

function splitSelectors(header) {
  const selectors = [];
  let start = 0;
  let parentheses = 0;
  let brackets = 0;
  let quote = '';
  let escaped = false;
  for (let index = 0; index < header.length; index += 1) {
    const char = header[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = '';
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (char === '(') parentheses += 1;
    else if (char === ')') parentheses -= 1;
    else if (char === '[') brackets += 1;
    else if (char === ']') brackets -= 1;
    else if (char === ',' && parentheses === 0 && brackets === 0) {
      selectors.push(header.slice(start, index).trim());
      start = index + 1;
    }
  }
  selectors.push(header.slice(start).trim());
  return selectors.filter(Boolean).map(selector => selector.replace(/\s+/g, ' '));
}

function parseCss(rawSource) {
  const source = stripComments(rawSource);
  const rules = [];
  const atRules = [];

  function parseRange(start, end, contexts = []) {
    let cursor = start;
    while (cursor < end) {
      while (cursor < end && /[\s;]/.test(source[cursor])) cursor += 1;
      if (cursor >= end) break;

      let open = cursor;
      let quote = '';
      let escaped = false;
      let parentheses = 0;
      let brackets = 0;
      for (; open < end; open += 1) {
        const char = source[open];
        if (quote) {
          if (escaped) escaped = false;
          else if (char === '\\') escaped = true;
          else if (char === quote) quote = '';
          continue;
        }
        if (char === '"' || char === "'") {
          quote = char;
          continue;
        }
        if (char === '(') parentheses += 1;
        else if (char === ')') parentheses -= 1;
        else if (char === '[') brackets += 1;
        else if (char === ']') brackets -= 1;
        else if (char === '{' && parentheses === 0 && brackets === 0) break;
        else if (char === ';' && parentheses === 0 && brackets === 0) {
          cursor = open + 1;
          open = -1;
          break;
        }
      }
      if (open === -1) continue;
      if (open >= end) break;

      const header = source.slice(cursor, open).trim().replace(/\s+/g, ' ');
      const close = matchingBrace(source, open, end);
      if (header.startsWith('@')) {
        atRules.push({ header, line: lineAt(rawSource, cursor), contexts });
        if (/^@(media|supports|layer|container)\b/i.test(header)) {
          parseRange(open + 1, close, [...contexts, header]);
        }
      } else if (header) {
        rules.push({
          header,
          selectors: splitSelectors(header),
          line: lineAt(rawSource, cursor),
          endLine: lineAt(rawSource, close),
          contexts,
        });
      }
      cursor = close + 1;
    }
  }

  parseRange(0, source.length);
  const selectors = rules.flatMap(rule => rule.selectors.map(selector => ({
    selector,
    line: rule.line,
    endLine: rule.endLine,
    contexts: rule.contexts,
  })));
  return { rules, selectors, atRules };
}

function stylesheetHrefs(html) {
  return [...html.matchAll(/<link\b[^>]*>/gi)]
    .map(match => match[0])
    .filter(tag => /\brel=["']stylesheet["']/i.test(tag))
    .map(tag => tag.match(/\bhref=["']([^"']+)["']/i)?.[1])
    .filter(Boolean);
}

function stylesheetPaths(hrefs) {
  return hrefs.map(href => href.split('?')[0]);
}

function walkRuntimeSources(root) {
  const found = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) found.push(...walkRuntimeSources(fullPath));
    else if (/\.(?:html|js|mjs)$/i.test(entry.name)) found.push(fullPath);
  }
  return found;
}

function relative(filename) {
  return path.relative(ROOT, filename).replaceAll('\\', '/');
}

function countsBy(rows, keyFor) {
  const counts = new Map();
  for (const row of rows) {
    const key = keyFor(row);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return counts;
}

function domainSummary(selectors, name, pattern) {
  const hits = selectors.filter(row => pattern.test(row.selector));
  return {
    name,
    selectorOccurrences: hits.length,
    distinctSelectors: new Set(hits.map(row => row.selector)).size,
    firstLine: hits.length ? Math.min(...hits.map(row => row.line)) : null,
    lastLine: hits.length ? Math.max(...hits.map(row => row.endLine)) : null,
    mediaContexts: new Set(hits.flatMap(row => row.contexts)).size,
  };
}

const adminCss = read(ADMIN_CSS_PATH);
const adminHtml = read(ADMIN_HTML_PATH);
const testsHtml = read(TESTS_HTML_PATH);
const testsCss = read(TESTS_CSS_PATH);
const popupSource = read(POPUP_SOURCE_PATH);
const externalExportCssExists = fs.existsSync(EXPORT_CSS_PATH);
const embeddedStart = adminCss.indexOf(EXPORT_START);
const embeddedEnd = embeddedStart < 0 ? -1 : adminCss.indexOf(EXPORT_END, embeddedStart);

assert.notEqual(
  externalExportCssExists && embeddedStart >= 0,
  true,
  'export-log CSS exists in both admin.css and admin-export-logs.css',
);
assert.ok(
  externalExportCssExists || (embeddedStart >= 0 && embeddedEnd > embeddedStart),
  'export-log CSS has no canonical implementation owner',
);

const exportOwner = externalExportCssExists ? 'static/css/admin-export-logs.css' : 'static/css/admin.css';
const exportCss = externalExportCssExists
  ? read(EXPORT_CSS_PATH)
  : `${adminCss.slice(embeddedStart, embeddedEnd).trimEnd()}\n`;
assert.equal(
  sha256(exportCss),
  EXPORT_PRE_SPLIT_SHA256,
  'export-log CSS no longer matches the independently captured pre-split baseline',
);
assert.equal(exportCss.split('\n').length - 1, 201, 'export-log CSS line count drifted');
assert.equal((exportCss.match(/!important\b/g) || []).length, 0, 'export-log CSS introduced an important declaration');
assert.deepEqual(
  [...exportCss.matchAll(/@media\s*\(([^)]+)\)/g)].map(match => match[1]),
  ['max-width: 640px'],
  'export-log CSS responsive boundary changed',
);
assert.doesNotMatch(exportCss, /@import\b/i, 'export-log CSS must not introduce another cascade layer');

const exportParsed = parseCss(exportCss);
assert.equal(exportParsed.selectors.length, 37, 'export-log CSS selector occurrence count drifted');
for (const { selector } of exportParsed.selectors) {
  assert.ok(selector.startsWith('body.admin'), `export-log selector escaped the admin scope: ${selector}`);
  assert.ok(
    selector === 'body.admin.export-logs-open' || selector.includes('#exportLogsModal'),
    `export-log selector escaped its modal boundary: ${selector}`,
  );
}

const modalStart = adminHtml.indexOf('  <div id="exportLogsModal"');
const modalEnd = adminHtml.indexOf('  <div id="yoilModal"', modalStart);
assert.ok(modalStart >= 0 && modalEnd > modalStart, 'admin export modal DOM boundary is missing');
const exportModalDom = `${adminHtml.slice(modalStart, modalEnd).trimEnd()}\n`;
assert.equal(
  sha256(exportModalDom),
  EXPORT_MODAL_DOM_SHA256,
  'admin export modal DOM changed after the inventory baseline',
);

const adminStylesheets = stylesheetPaths(stylesheetHrefs(adminHtml));
const expectedAdminStylesheets = [
  '/css/main.css',
  '/css/admin.css',
  ...(externalExportCssExists ? ['/css/admin-export-logs.css'] : []),
  '/css/student-work-light.css',
  '/css/student-test-ocr-admin.css',
];
assert.deepEqual(adminStylesheets, expectedAdminStylesheets, 'admin stylesheet load order changed');
assert.deepEqual(
  stylesheetPaths(stylesheetHrefs(testsHtml)),
  ['/css/main.css', '/css/admin.css', '/css/tests.css'],
  'test-management stylesheet load order changed',
);

const popupStylesheetBlock = popupSource.match(/const ADMIN_POPUP_STYLESHEETS = \[([\s\S]*?)\];/u)?.[1] || '';
const popupStylesheets = [...popupStylesheetBlock.matchAll(/["']([^"']+\.css(?:\?[^"']*)?)["']/g)]
  .map(match => match[1].split('?')[0]);
assert.deepEqual(
  popupStylesheets,
  ['/css/main.css', '/css/admin.css', '/css/student-work-light.css'],
  'all-students record popup stylesheet order changed',
);
assert.ok(!popupSource.includes('/css/admin-export-logs.css'), 'admin-only export CSS leaked into the all-students popup');
assert.ok(!testsHtml.includes('/css/admin-export-logs.css'), 'admin-only export CSS leaked into the tests page');

const runtimeSources = walkRuntimeSources(path.join(ROOT, 'static'));
const adminCssConsumers = runtimeSources
  .filter(filename => read(filename).includes('/css/admin.css'))
  .map(relative)
  .sort();
assert.deepEqual(adminCssConsumers, [
  'static/admin.html',
  'static/js/all/features/studentRecordPopup.js',
  'static/tests.html',
], 'admin.css runtime consumer inventory changed');

const exportNamespaceSources = [ADMIN_CSS_PATH, ...(externalExportCssExists ? [EXPORT_CSS_PATH] : []), ...runtimeSources]
  .filter((filename, index, all) => all.indexOf(filename) === index)
  .filter(filename => /export-logs-|exportLogsModal/u.test(read(filename)))
  .map(relative)
  .sort();
assert.deepEqual(exportNamespaceSources, [
  'static/admin.html',
  exportOwner,
  'static/js/admin/features/exportLogs.js',
].sort(), 'export-log CSS namespace gained a cross-surface consumer');

const adminParsed = parseCss(adminCss);
const testsParsed = parseCss(testsCss);
const selectorCounts = countsBy(adminParsed.selectors, row => row.selector);
const duplicateSelectors = [...selectorCounts.entries()]
  .filter(([, count]) => count > 1)
  .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
const testsSelectorSet = new Set(testsParsed.selectors.map(row => row.selector));
const overlapWithTestsCss = [...new Set(adminParsed.selectors.map(row => row.selector))]
  .filter(selector => testsSelectorSet.has(selector))
  .sort();

const domainDefinitions = [
  ['tests-page', /\.tests-page\b/],
  ['admin-simple', /\.admin-simple\b/],
  ['announcement', /\.(?:announcement|ann)-[\w-]+/],
  ['makeup', /\.makeup-[\w-]+/],
  ['assistant-note', /\.assistant-note-[\w-]+/],
  ['student-log', /\.student-log-[\w-]+/],
  ['admin-operation-note', /\.admin-operation-note[s-][\w-]*/],
  ['student-accounts', /\.student-accounts-[\w-]+/],
  ['student-focus-admin', /\.student-focus-admin-[\w-]+/],
  ['export-logs', /(?:\.export-logs-[\w-]+|#exportLogsModal\b)/],
  ['calendar', /(?:#calendar\b|\.fc-[\w-]+)/],
  ['today', /(?:#today(?:Wrap|Tools|Section)?\b|\.today-[\w-]+)/],
];
const domains = domainDefinitions.map(([name, pattern]) => domainSummary(adminParsed.selectors, name, pattern));

const report = {
  inventoryVersion: 1,
  adminCss: {
    bytes: fs.statSync(ADMIN_CSS_PATH).size,
    contentLines: adminCss.endsWith('\n') ? adminCss.split('\n').length - 1 : adminCss.split('\n').length,
    sha256: sha256(fs.readFileSync(ADMIN_CSS_PATH)),
    qualifiedRules: adminParsed.rules.length,
    selectorOccurrences: adminParsed.selectors.length,
    distinctSelectors: new Set(adminParsed.selectors.map(row => row.selector)).size,
    duplicateSelectorNames: duplicateSelectors.length,
    mediaBlocks: adminParsed.atRules.filter(row => /^@media\b/i.test(row.header)).length,
    importantDeclarations: (adminCss.match(/!important\b/g) || []).length,
    testsScopedSelectorOccurrences: adminParsed.selectors.filter(row => /\.tests-page\b/.test(row.selector)).length,
    unscopedSelectorOccurrences: adminParsed.selectors.filter(row => !row.selector.startsWith('body.admin')).length,
    distinctOverlapWithTestsCss: overlapWithTestsCss.length,
  },
  consumers: {
    adminCss: adminCssConsumers,
    adminStylesheets,
    testsStylesheets: stylesheetPaths(stylesheetHrefs(testsHtml)),
    allStudentsPopupStylesheets: popupStylesheets,
  },
  domains,
  duplicateSelectorTop: duplicateSelectors.slice(0, 12).map(([selector, count]) => ({ selector, count })),
  extractionCandidate: {
    domain: 'class-log export modal',
    owner: exportOwner,
    state: externalExportCssExists ? 'extracted' : 'embedded',
    preSplitSha256: EXPORT_PRE_SPLIT_SHA256,
    lines: 201,
    selectorOccurrences: exportParsed.selectors.length,
    modalDomSha256: EXPORT_MODAL_DOM_SHA256,
    runtimeNamespaceSources: exportNamespaceSources,
  },
};

if (process.argv.includes('--json')) {
  console.log(JSON.stringify(report, null, 2));
} else {
  console.log(
    `admin CSS inventory checks passed: ${report.adminCss.contentLines} lines, `
      + `${report.adminCss.selectorOccurrences} selector occurrences, `
      + `${report.consumers.adminCss.length} runtime consumers; `
      + `export-log candidate ${report.extractionCandidate.state} with pre-split hash preserved`,
  );
}
