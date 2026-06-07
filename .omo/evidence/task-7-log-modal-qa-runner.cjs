const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('C:/tmp/task7-playwright-runtime/node_modules/playwright');

const ROOT = process.cwd();
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const DATE = '2026-06-06';
const SID = 's1';

function buildHarnessModule() {
  const sourcePath = path.join(ROOT, 'static/js/admin/features/logModal.js');
  const source = fs.readFileSync(sourcePath, 'utf8')
    .replace(
      "import { $, toast, postJSON } from '../core/utils.js';",
      "const $ = (id) => document.getElementById(id); const toast = (msg) => { window.__toasts.push(String(msg)); }; const postJSON = async (url, body = {}) => { const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); return await res.json().catch(() => ({})); };",
    )
    .replace(
      "import { state } from '../core/state.js';",
      'const state = window.__state;',
    )
    .replace(
      "import { getAdminDate } from '../core/adminDate.js';",
      `const getAdminDate = () => '${DATE}';`,
    )
    .replace(
      "import { initTestModal } from './testModal.js';",
      'const initTestModal = () => {};',
    );

  return `${source}
export function initHarness() {
  initLogModal();
}`;
}

async function main() {
  const backend = {
    logs: {
      [DATE]: {
        [SID]: { notes: 'keep notes', homeworkTable: [] },
      },
    },
    progress: {
      [DATE]: {
        [SID]: { m1: 'done' },
      },
    },
    watch: {
      m1: { last: 95, dur: 100, completed: true, updatedAt: 1 },
    },
    calls: [],
  };
  const harnessModule = buildHarnessModule();
  const pageErrors = [];
  const consoleMessages = [];

  const browser = await chromium.launch({
    executablePath: CHROME,
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => consoleMessages.push({ type: message.type(), text: message.text() }));

  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    backend.calls.push({ method: request.method(), path: url.pathname, query: url.search });

    if (url.pathname === '/task-7-log-modal-qa') {
      await route.fulfill({
        contentType: 'text/html',
        body: `<!doctype html>
<html>
<head><meta charset="utf-8"><title>task-7-log-modal-qa</title></head>
<body>
  <table><tbody>
    <tr data-sid="${SID}" data-date="${DATE}"><td><button class="editLog">open</button></td></tr>
  </tbody></table>
  <script>
    window.__toasts = [];
    window.__state = {
      students: [{ id: '${SID}', name: 'Student One', curriculum: 'ALG', subCurriculum: 'BASE', level: '중' }],
      videos: [{ mid: 'm1', curriculum: 'ALG', subCurriculum: 'BASE', chapter: 1 }],
      logs: {},
      progress: {},
      absentByDate: {},
      updates: {},
    };
    window.alert = (message) => { window.__lastAlert = String(message); };
    window.showStudentTooltipForSid = () => {};
    window.hideStudentTooltip = () => {};
    window.hideStudentPopupBackdrop = () => {};
  </script>
  <script type="module">
    import { initHarness } from '/logModal-harness.mjs';
    initHarness();
    window.__harnessReady = true;
  </script>
</body>
</html>`,
      });
      return;
    }

    if (url.pathname === '/logModal-harness.mjs') {
      await route.fulfill({ contentType: 'text/javascript', body: harnessModule });
      return;
    }

    if (url.pathname === '/api/logs/entry') {
      const date = url.searchParams.get('date') || DATE;
      const sid = url.searchParams.get('sid') || SID;
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, entry: backend.logs[date]?.[sid] || {} }),
      });
      return;
    }

    if (url.pathname === '/api/logs') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(backend.logs) });
      return;
    }

    if (url.pathname === '/api/progress') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(backend.progress) });
      return;
    }

    if (url.pathname === '/api/watch/latest') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, watch: backend.watch }),
      });
      return;
    }

    if (url.pathname === '/api/progress/patch') {
      const body = JSON.parse(request.postData() || '{}');
      const date = body.date || DATE;
      const sid = body.sid || SID;
      backend.progress[date] = backend.progress[date] || {};
      backend.progress[date][sid] = backend.progress[date][sid] || {};
      for (const [mid, status] of Object.entries(body.progress || {})) {
        backend.progress[date][sid][mid] = status;
        if (status === 'none') {
          backend.progress[date][sid].__manualProgressMids = backend.progress[date][sid].__manualProgressMids || {};
          backend.progress[date][sid].__manualProgressMids[mid] = true;
        }
      }
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, progress: backend.progress[date][sid] }),
      });
      return;
    }

    if (url.pathname === '/api/logs/patch') {
      const body = JSON.parse(request.postData() || '{}');
      const date = body.date || DATE;
      const sid = body.sid || SID;
      backend.logs[date] = backend.logs[date] || {};
      const next = { ...(backend.logs[date][sid] || {}), ...(body.entry || {}) };
      for (const key of body.__clear || []) delete next[String(key)];
      backend.logs[date][sid] = next;
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, entry: next }),
      });
      return;
    }

    if (url.pathname === '/api/updates/patch') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true }) });
      return;
    }

    await route.fulfill({ status: 404, contentType: 'text/plain', body: `not found: ${url.pathname}` });
  });

  await page.goto('http://127.0.0.1/task-7-log-modal-qa');
  await page.waitForFunction(() => window.__harnessReady === true);

  await page.locator('button.editLog').click();
  const cell = page.locator('#logProgress .progress-cell[data-mid="m1"]');
  await cell.waitFor({ state: 'visible' });
  assert.equal(await cell.getAttribute('data-state'), 'done');

  await cell.click();
  assert.equal(await cell.getAttribute('data-state'), 'interrupted');
  await cell.click();
  assert.equal(await cell.getAttribute('data-state'), 'none');
  assert.equal(await cell.getAttribute('data-explicit-none'), '1');

  await page.locator('#logSave').click();
  await page.waitForFunction(() => getComputedStyle(document.querySelector('#logModal')).display === 'none');
  assert.equal(backend.progress[DATE][SID].m1, 'none');
  assert.equal(backend.progress[DATE][SID].__manualProgressMids?.m1, true);

  await page.reload();
  await page.waitForFunction(() => window.__harnessReady === true);
  await page.locator('button.editLog').click();
  await cell.waitFor({ state: 'visible' });
  assert.equal(await cell.getAttribute('data-state'), 'none');
  assert.equal(await cell.getAttribute('data-explicit-none'), '1');

  await page.screenshot({ path: '.omo/evidence/task-7-whole-project-refactor.png', fullPage: true });
  fs.writeFileSync(
    path.join(ROOT, '.omo/evidence/task-7-browser-qa.json'),
    JSON.stringify({
      ok: true,
      backendProgress: backend.progress[DATE][SID],
      apiCalls: backend.calls,
      pageErrors,
      consoleMessages,
    }, null, 2),
    'utf8',
  );

  assert.deepEqual(pageErrors, []);
  await browser.close();
  console.log('task-7 browser QA PASS');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
