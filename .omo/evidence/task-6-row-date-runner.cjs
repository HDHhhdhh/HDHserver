const fs = require('node:fs');
const { chromium } = require('playwright');

async function main() {
  const adminUrl = process.env.TASK6_ADMIN_URL || 'http://127.0.0.1:8003/admin';
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: true,
  });

  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const calls = [];
    const errors = [];

    page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(`console: ${message.text()}`);
    });

    await page.route('**/api/**', async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const path = url.pathname;
      if (path === '/api/contact/patch') {
        calls.push(JSON.parse(req.postData() || '{}'));
      }

      let body = {};
      if (path === '/api/students' || path === '/api/videos') body = [];
      if (path === '/api/tests-config') body = { categories: {} };
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    });

    await page.route('**/arrive-time/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      });
    });

    await page.goto(adminUrl, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => sessionStorage.setItem('adminSelectedDate', '2026-06-07'));
    await page.waitForSelector('#todayWrap', { timeout: 10000 });

    await page.evaluate(async () => {
      const host = document.getElementById('todayWrap');
      host._todayDelegated = false;
      document._todayDocClickBound = false;
      host.innerHTML = `<table><tbody><tr data-sid="s2" data-date="2026-06-06" data-contact=""><td><label class="c" data-kind="contact" data-on="0"><input class="contactChk" type="checkbox"></label></td></tr></tbody></table>`;
      const mod = await import(`/js/admin/features/today.render.js?task6qa=${Date.now()}`);
      mod.bindTodayTableEvents(async () => {});
    });

    await page.locator('#todayWrap .contactChk').check({ force: true });
    await page.waitForTimeout(100);
    const rowDateRequest = calls[calls.length - 1];
    if (!rowDateRequest || rowDateRequest.date !== '2026-06-06' || rowDateRequest.sid !== 's2' || rowDateRequest.value !== true) {
      throw new Error(`row date request mismatch: ${JSON.stringify(rowDateRequest)}`);
    }
    await page.screenshot({
      path: 'C:/server/.omo/evidence/task-6-whole-project-refactor.png',
      fullPage: true,
    });

    await page.evaluate(() => {
      const tr = document.querySelector('#todayWrap tr[data-sid]');
      tr.removeAttribute('data-date');
      tr.dataset.contact = '';
      const input = tr.querySelector('.contactChk');
      input.checked = false;
      const pill = tr.querySelector('.c');
      if (pill) pill.dataset.on = '0';
    });

    await page.locator('#todayWrap .contactChk').check({ force: true });
    await page.waitForTimeout(100);
    const fallbackRequest = calls[calls.length - 1];
    if (!fallbackRequest || fallbackRequest.date !== '2026-06-07' || fallbackRequest.sid !== 's2' || fallbackRequest.value !== true) {
      throw new Error(`fallback date request mismatch: ${JSON.stringify(fallbackRequest)}`);
    }
    await page.screenshot({
      path: 'C:/server/.omo/evidence/task-6-whole-project-refactor-error.png',
      fullPage: true,
    });

    const result = {
      ok: true,
      rowDateRequest,
      fallbackRequest,
      calls,
      errors,
      screenshots: [
        '.omo/evidence/task-6-whole-project-refactor.png',
        '.omo/evidence/task-6-whole-project-refactor-error.png',
      ],
      adminUrl,
    };
    fs.writeFileSync('C:/server/.omo/evidence/task-6-browser-qa.json', JSON.stringify(result, null, 2), 'utf8');
    console.log(JSON.stringify(result));
  } finally {
    await browser.close().catch(() => {});
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
