const fs = require('fs');
const path = require('path');

const playwrightPath = process.env.TASK8_PLAYWRIGHT_PATH ||
  'C:/tmp/task8-playwright-runtime/node_modules/playwright';
const { chromium } = require(playwrightPath);

const root = 'C:/server';
const evidenceDir = path.join(root, '.omo/evidence');
const sourcePath = path.join(root, 'static/js/admin/features/videoModal.js');
const screenshotPath = path.join(evidenceDir, 'task-8-whole-project-refactor.png');
const errorScreenshotPath = path.join(evidenceDir, 'task-8-whole-project-refactor-error.png');
const jsonPath = path.join(evidenceDir, 'task-8-browser-qa.json');

const source = fs.readFileSync(sourcePath, 'utf8')
  .replace(
    "import { $, CT, toast } from '../core/utils.js';",
    "const CT = { 'Content-Type': 'application/json' }; const $ = (id) => document.getElementById(id); const toast = (msg) => window.__toasts.push(String(msg));",
  )
  .replace("import { state } from '../core/state.js';", "const state = window.__state;")
  .replace(
    "import { getAdminDate } from '../core/adminDate.js';",
    "const getAdminDate = () => window.__adminDate || '2026-06-07';",
  )
  .replace(
    "import { applySearchPlaceholder, matchesSearchKey, searchKeyForText } from '../../shared/search.js';",
    "const applySearchPlaceholder = () => {}; const matchesSearchKey = (hay, query) => String(hay || '').includes(String(query || '').toLowerCase()); const searchKeyForText = (value) => String(value || '').toLowerCase();",
  );

const harnessHtml = `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>Task 8 Video Modal QA</title>
  <style>
    body { margin: 0; font-family: Arial, "Malgun Gothic", sans-serif; background: #f4f6f8; color: #111827; }
    main { padding: 24px; }
    table { border-collapse: collapse; background: white; border: 1px solid #d1d5db; }
    td { padding: 10px 14px; border-bottom: 1px solid #e5e7eb; }
    button { height: 34px; border: 1px solid #2563eb; background: #2563eb; color: white; border-radius: 6px; font-weight: 800; cursor: pointer; }
    #qaStatus { margin-top: 14px; font-weight: 800; }
  </style>
</head>
<body>
  <main>
    <table>
      <tr id="qaRow" data-sid="007" data-date="2026-06-06">
        <td>학생7</td>
        <td>2026-06-06</td>
        <td><button class="editVid" type="button">영상</button></td>
      </tr>
    </table>
    <div id="qaStatus">running</div>
  </main>
  <script type="module" src="/task8-harness.js"></script>
</body>
</html>`;

const harnessScript = `
const clone = (value) => JSON.parse(JSON.stringify(value));
window.__adminDate = '2026-06-07';
window.__toasts = [];
window.__calls = [];
window.__pageErrors = [];
window.__consoleMessages = [];
window.__backendUpdates = { '2026-06-06': { '007': { videos: ['m1'], source: 'manual' } } };
window.__latestLogEntry = {};
window.__state = {
  students: [{ id: '007', name: '학생7', curriculum: 'ALG', subCurriculum: 'BASE', day1: '토 13:00' }],
  videos: [
    { mid: 'm1', title: '일차함수', chapter: '1', curriculum: 'ALG', subCurriculum: 'BASE' },
    { mid: 'm2', title: '이차함수', chapter: '2', curriculum: 'ALG', subCurriculum: 'BASE' },
    { mid: 'extra-1', title: '확장 영상', chapter: '7', curriculum: 'ALG', subCurriculum: 'EXTRA' },
  ],
  updates: {},
  logs: {},
  progress: { '2026-06-06': { '007': { m1: 'done', m2: 'skip' } } },
  extra: { '2026-06-06': [] },
  absentByDate: {},
};

const response = (payload, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: { 'content-type': 'application/json; charset=utf-8' },
});
const recordCall = (url, init = {}) => {
  const body = init.body ? JSON.parse(String(init.body)) : null;
  const call = { url: String(url), method: init.method || 'GET', cache: init.cache || '', body };
  window.__calls.push(call);
  return call;
};
window.fetch = async (url, init = {}) => {
  const call = recordCall(url, init);
  const value = String(url);
  if (value === '/api/updates') return response({ ok: true, updates: clone(window.__backendUpdates) });
  if (value === '/api/extra-attend') return response({ ok: true, extra: { '2026-06-06': [] } });
  if (value.startsWith('/api/logs/entry?')) return response({ ok: true, entry: clone(window.__latestLogEntry) });
  if (value.startsWith('/api/watch/latest?')) {
    return response({ ok: true, watch: { m2: { last: 100, dur: 100, completed: true } } });
  }
  if (value === '/api/updates/patch') {
    const { date, sid, entry, remove } = call.body || {};
    window.__backendUpdates[date] = window.__backendUpdates[date] || {};
    if (remove) delete window.__backendUpdates[date][sid];
    else window.__backendUpdates[date][sid] = { ...(window.__backendUpdates[date][sid] || {}), ...(entry || {}) };
    return response({ ok: true });
  }
  if (value === '/api/logs/patch') {
    window.__latestLogEntry = { ...window.__latestLogEntry, ...(call.body?.entry || {}) };
    return response({ ok: true, entry: clone(window.__latestLogEntry) });
  }
  return response({ ok: true });
};

const { initVideoModal } = await import('/videoModal-under-test.js');
initVideoModal();

window.__runTask8Qa = async () => {
  const row = document.getElementById('qaRow');
  await window.openVideoAssignmentPopupForRow(row);
  const firstOpenChecked = document.querySelector('#chkZone input[value="m1"]')?.checked === true;
  const autoPatchOnManualOpen = window.__calls.some((call) => call.url === '/api/updates/patch');
  if (!firstOpenChecked) throw new Error('manual assignment did not remain checked on open');
  if (autoPatchOnManualOpen) throw new Error('manual assignment open triggered auto updates patch');

  window.__calls = [];
  await window.saveVideoAssignmentPopup({ showPopup: false, refresh: false });
  const manualPatch = window.__calls.find((call) => call.url === '/api/updates/patch');
  if (manualPatch?.body?.date !== '2026-06-06') throw new Error('manual save did not use row date');
  if (manualPatch?.body?.sid !== '007') throw new Error('manual save did not use sid');
  if (manualPatch?.body?.entry?.source !== 'manual') throw new Error('manual save did not preserve source');
  if (manualPatch?.body?.entry?.videos?.[0] !== 'm1') throw new Error('manual save did not preserve selected video');

  window.closeVideoAssignmentPopup();
  window.__calls = [];
  await window.openVideoAssignmentPopupForRow(row);
  const reopenedChecked = document.querySelector('#chkZone input[value="m1"]')?.checked === true;
  const reopenAutoPatch = window.__calls.some((call) => call.url === '/api/updates/patch');
  if (!reopenedChecked) throw new Error('manual assignment did not remain checked after reopen');
  if (reopenAutoPatch) throw new Error('manual assignment reopen triggered auto updates patch');

  window.__calls = [];
  await window.saveVideoAssignmentPopup({ showPopup: false, refresh: false, forceEmpty: true });
  const forcePatch = window.__calls.find((call) => call.url === '/api/updates/patch');
  if (forcePatch?.body?.date !== '2026-06-06') throw new Error('force-empty save did not use row date');
  if (forcePatch?.body?.sid !== '007') throw new Error('force-empty save did not use sid');
  if (!Array.isArray(forcePatch?.body?.entry?.videos)) throw new Error('force-empty save did not send videos array');
  if (forcePatch.body.entry.videos.length !== 0) throw new Error('force-empty videos array was not empty');
  if (forcePatch.body.entry.source !== 'manual') throw new Error('force-empty save did not record manual source');
  if (Object.prototype.hasOwnProperty.call(forcePatch.body, 'remove')) throw new Error('force-empty save used remove:true');

  document.getElementById('qaStatus').textContent = 'PASS';
  return {
    ok: true,
    firstOpenChecked,
    manualPatch: manualPatch.body,
    forcePatch: forcePatch.body,
    backendUpdates: clone(window.__backendUpdates),
    toasts: window.__toasts.slice(),
  };
};
`;

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.TASK8_CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const pageErrors = [];
  const consoleMessages = [];
  page.on('pageerror', (err) => pageErrors.push(String(err?.message || err)));
  page.on('console', (msg) => consoleMessages.push({ type: msg.type(), text: msg.text() }));

  await page.route('**/admin', (route) => route.fulfill({
    status: 200,
    contentType: 'text/html; charset=utf-8',
    body: harnessHtml,
  }));
  await page.route('**/task8-harness.js', (route) => route.fulfill({
    status: 200,
    contentType: 'application/javascript; charset=utf-8',
    body: harnessScript,
  }));
  await page.route('**/videoModal-under-test.js', (route) => route.fulfill({
    status: 200,
    contentType: 'application/javascript; charset=utf-8',
    body: source,
  }));

  let result;
  try {
    await page.goto('http://127.0.0.1:8788/admin', { waitUntil: 'domcontentloaded' });
    result = await page.evaluate(() => window.__runTask8Qa());
    await page.screenshot({ path: screenshotPath, fullPage: true });
    await page.screenshot({ path: errorScreenshotPath, fullPage: true });
  } catch (err) {
    await page.screenshot({ path: errorScreenshotPath, fullPage: true }).catch(() => {});
    result = { ok: false, error: String(err?.message || err) };
  }

  result.pageErrors = pageErrors;
  result.consoleMessages = consoleMessages;
  fs.writeFileSync(jsonPath, JSON.stringify(result, null, 2), 'utf8');
  await context.close();
  await browser.close();

  if (!result.ok || pageErrors.length) {
    console.error(JSON.stringify(result, null, 2));
    process.exit(1);
  }
  console.log('task-8 browser QA PASS');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
