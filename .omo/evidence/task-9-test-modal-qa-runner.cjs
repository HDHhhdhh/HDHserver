const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('C:/tmp/task9-playwright-runtime/node_modules/playwright');

const root = 'C:/server';
const evidenceDir = path.join(root, '.omo/evidence');
const testModalSource = fs.readFileSync(path.join(root, 'static/js/admin/features/testModal.js'), 'utf8');
const chromeCandidates = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const executablePath = chromeCandidates.find((candidate) => fs.existsSync(candidate));
if (!executablePath) throw new Error('Chrome executable not found');

const html = `<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><title>Task 9 Test Modal QA</title></head>
<body>
  <table><tbody>
    <tr data-sid="s1" data-date="2026-06-06"><td>학생</td><td><button class="openTestProgress">tests</button></td></tr>
  </tbody></table>
  <script type="module" src="/task9-harness.js"></script>
</body>
</html>`;

const harness = `
window.__adminDate = '2026-06-07';
window.__toasts = [];
window.__calls = [];
window.__state = {
  students: [{ id: 's1', name: '학생', curriculum: '대수', level: '중' }],
  progress: {},
  logs: {},
  testsConfig: {},
  schoolCal: {},
};
const unitTests = [
  { id: 'unit-new', name: 'Task9 신규 배정', curriculum: '대수', difficulty: 'Lv.3', round: '1', problems: 20 },
  { id: 'unit-extra', name: 'Task9 추가 후보', curriculum: '대수', difficulty: 'Lv.3', round: '1', problems: 20 },
];
const config = {
  categories: {
    UNIT: { label: '단원평가', tests: unitTests },
  },
};
const latestEntry = {
  notes: 'latest notes',
  testAssignmentNote: '',
  testAssignmentDailyTests: [],
  assignedTests: [],
};
const jsonResponse = (payload, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => JSON.stringify(payload),
});
window.fetch = async (url, init = {}) => {
  const parsed = new URL(String(url), window.location.href);
  const body = init.body ? JSON.parse(String(init.body)) : null;
  window.__calls.push({ url: parsed.pathname + parsed.search, method: init.method || 'GET', body });
  if (parsed.pathname === '/api/tests-config') return jsonResponse(config);
  if (parsed.pathname === '/api/logs' && parsed.searchParams.get('sid') === 's1') return jsonResponse(window.__state.logs || {});
  if (parsed.pathname === '/api/progress' && parsed.searchParams.get('sid') === 's1') return jsonResponse(window.__state.progress || {});
  if (parsed.pathname === '/api/tests') return jsonResponse({});
  if (parsed.pathname === '/api/logs/entry') return jsonResponse({ ok: true, entry: latestEntry });
  if (parsed.pathname === '/api/progress/patch') {
    const date = body.date;
    const sid = body.sid;
    window.__state.progress[date] = window.__state.progress[date] || {};
    window.__state.progress[date][sid] = { ...(window.__state.progress[date][sid] || {}), ...(body.progress || {}) };
    return jsonResponse({ progress: window.__state.progress[date][sid] });
  }
  if (parsed.pathname === '/api/logs/patch') {
    const date = body.date;
    const sid = body.sid;
    window.__state.logs[date] = window.__state.logs[date] || {};
    window.__state.logs[date][sid] = { ...(window.__state.logs[date][sid] || {}), ...(body.entry || {}), marker: 'saved' };
    return jsonResponse({ entry: window.__state.logs[date][sid] });
  }
  return jsonResponse({});
};
const { initTestModal } = await import('/static/js/admin/features/testModal.js');
initTestModal();
window.__task9 = {
  async open() {
    await window.openTestAssignmentPopupForRow(document.querySelector('tr[data-sid="s1"]'));
  },
  async save(options = {}) {
    return await window.saveTestAssignmentPopup({ showPopup: false, refresh: false, ...options });
  },
  calls() {
    return window.__calls.slice();
  },
  resetCalls() {
    window.__calls = [];
  },
  setClearedWithStaleLog(label) {
    window.__state.progress = {
      '2026-06-06': { s1: { tests: {}, __testsClearedAt: '2026-06-06T00:00:00.000Z' } },
    };
    window.__state.logs = {
      '2026-06-06': { s1: { assignedTests: [{ label, name: 'stale', status: 'assigned' }] } },
    };
  },
};
`;

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath,
  });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const pageErrors = [];
  const consoleMessages = [];
  page.on('pageerror', (error) => pageErrors.push(String(error && error.message || error)));
  page.on('console', (message) => {
    const type = message.type();
    if (type === 'error' || type === 'warning') consoleMessages.push({ type, text: message.text() });
  });

  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/admin') {
      await route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html });
      return;
    }
    if (url.pathname === '/task9-harness.js') {
      await route.fulfill({ status: 200, contentType: 'text/javascript; charset=utf-8', body: harness });
      return;
    }
    if (url.pathname === '/static/js/admin/features/testModal.js') {
      await route.fulfill({ status: 200, contentType: 'text/javascript; charset=utf-8', body: testModalSource });
      return;
    }
    if (url.pathname === '/static/js/admin/core/utils.js') {
      await route.fulfill({
        status: 200,
        contentType: 'text/javascript; charset=utf-8',
        body: `
          export const CT = { 'Content-Type': 'application/json' };
          export const $ = (id) => document.getElementById(id);
          export function toast(message) { window.__toasts.push(String(message)); }
        `,
      });
      return;
    }
    if (url.pathname === '/static/js/admin/core/state.js') {
      await route.fulfill({
        status: 200,
        contentType: 'text/javascript; charset=utf-8',
        body: `export const state = window.__state;`,
      });
      return;
    }
    if (url.pathname === '/static/js/admin/core/adminDate.js') {
      await route.fulfill({
        status: 200,
        contentType: 'text/javascript; charset=utf-8',
        body: `export function getAdminDate() { return window.__adminDate || '2026-06-07'; }`,
      });
      return;
    }
    await route.fulfill({ status: 404, contentType: 'text/plain', body: `not found: ${url.pathname}` });
  });

  try {
  await page.goto('http://127.0.0.1:19009/admin', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.__task9 && typeof window.__task9.open === 'function');
  await page.evaluate(() => window.__task9.open());
  await page.waitForSelector('#testAssignList .test-row:not([disabled])');
  await page.click('#testAssignList .test-row');
  await page.screenshot({ path: path.join(evidenceDir, 'task-9-whole-project-refactor.png'), fullPage: true });
  await page.evaluate(() => window.__task9.save());
  const calls = await page.evaluate(() => window.__task9.calls());
  const progressPatch = calls.find((call) => call.url === '/api/progress/patch');
  const logPatch = calls.find((call) => call.url === '/api/logs/patch');
  if (!progressPatch) throw new Error('missing /api/progress/patch');
  if (!logPatch) throw new Error('missing /api/logs/patch');
  if (progressPatch.body.date !== '2026-06-06') throw new Error('progress patch did not use row date');
  if (progressPatch.body.sid !== 's1') throw new Error('progress patch did not use row sid');
  const progressTests = progressPatch.body.progress && progressPatch.body.progress.tests;
  const assignedLabels = Object.entries(progressTests || {})
    .filter(([, status]) => status === 'assigned')
    .map(([label]) => label);
  if (assignedLabels.length !== 1) throw new Error('progress patch did not write exactly one assigned test');
  if (logPatch.body.date !== '2026-06-06') throw new Error('log patch did not use row date');
  if (logPatch.body.sid !== 's1') throw new Error('log patch did not use row sid');
  if (Object.prototype.hasOwnProperty.call(logPatch.body.entry || {}, 'tests')) {
    throw new Error('log patch wrote authoritative tests');
  }
  const assignedTests = logPatch.body.entry && logPatch.body.entry.assignedTests;
  if (!Array.isArray(assignedTests) || assignedTests.length !== 1) throw new Error('log patch missing assignedTests metadata');
  if (assignedTests[0].label !== assignedLabels[0]) throw new Error('log metadata label differs from progress authority label');

  await page.evaluate((label) => {
    window.closeTestAssignmentPopup();
    window.__task9.setClearedWithStaleLog(label);
    window.__task9.resetCalls();
  }, assignedLabels[0]);
  await page.evaluate(() => window.__task9.open());
  await page.waitForSelector('#testAssignList .test-row:not([disabled])');
  const selectedAfterClear = await page.locator('#testAssignList .test-row.is-selected').count();
  await page.screenshot({ path: path.join(evidenceDir, 'task-9-whole-project-refactor-error.png'), fullPage: true });
  if (selectedAfterClear !== 0) throw new Error('cleared progress resurrected stale log metadata');

  fs.writeFileSync(path.join(evidenceDir, 'task-9-browser-qa.json'), JSON.stringify({
    ok: true,
    executablePath,
    progressPatch: progressPatch.body,
    logPatch: logPatch.body,
    selectedAfterClear,
    pageErrors,
    consoleMessages,
  }, null, 2), 'utf8');
  console.log('task-9 browser QA PASS');
  } catch (error) {
    fs.writeFileSync(path.join(evidenceDir, 'task-9-browser-qa.json'), JSON.stringify({
      ok: false,
      error: String(error && error.stack || error),
      pageErrors,
      consoleMessages,
    }, null, 2), 'utf8');
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
