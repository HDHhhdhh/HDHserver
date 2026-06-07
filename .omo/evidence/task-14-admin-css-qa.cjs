const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const outDir = path.resolve('.omo/evidence');
const baseUrl = 'http://127.0.0.1:8003';
const cases = [
  { name: 'desktop-light', width: 1440, height: 900, dark: false, screenshot: 'task-14-whole-project-refactor.png' },
  { name: 'desktop-dark', width: 1440, height: 900, dark: true, screenshot: 'task-14-admin-desktop-dark.png' },
  { name: 'mobile-light', width: 390, height: 844, dark: false, screenshot: 'task-14-admin-mobile-light.png', isMobile: true },
  { name: 'mobile-dark', width: 390, height: 844, dark: true, screenshot: 'task-14-admin-mobile-dark.png', isMobile: true },
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const statuses = [];
  try {
    for (const item of cases) {
      const context = await browser.newContext({
        viewport: { width: item.width, height: item.height },
        isMobile: !!item.isMobile,
        deviceScaleFactor: 1,
        locale: 'ko-KR',
      });
      await context.addInitScript((dark) => {
        localStorage.theme = dark ? 'dark' : 'light';
      }, item.dark);
      const page = await context.newPage();
      page.setDefaultTimeout(20000);
      await page.goto(`${baseUrl}/admin`, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('body.admin .topbar');
      await page.waitForSelector('body.admin #todayWrap');
      await page.waitForSelector('body.admin #logModal', { state: 'attached' });
      await page.evaluate((dark) => {
        document.body.classList.toggle('dark', dark);
        const toggle = document.getElementById('darkToggle');
        if (toggle) toggle.checked = dark;
        const modal = document.getElementById('logModal');
        if (modal) modal.style.display = 'flex';
        const title = document.getElementById('logTitle');
        if (title) title.textContent = '상담 기록 QA';
        const notes = document.getElementById('logNotes');
        if (notes) notes.value = '한글 상담 메모';
        const hw = document.getElementById('logHw');
        if (hw) hw.value = '숙제 확인';
      }, item.dark);
      await page.waitForTimeout(350);
      const status = await page.evaluate((name) => {
        const rectOf = (selector) => {
          const el = document.querySelector(selector);
          if (!el) return null;
          const rect = el.getBoundingClientRect();
          return {
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            top: Math.round(rect.top),
            left: Math.round(rect.left),
            right: Math.round(rect.right),
            bottom: Math.round(rect.bottom),
          };
        };
        const bodyStyle = getComputedStyle(document.body);
        const panel = rectOf('#logModal .modal-panel');
        const viewport = { width: innerWidth, height: innerHeight };
        const modalWithinViewport = !!panel && panel.width > 0 && panel.height > 0 && panel.left >= -1 && panel.top >= -1 && panel.right <= viewport.width + 1 && panel.bottom <= viewport.height + 1;
        const text = document.body.innerText || '';
        return {
          name,
          bodyClass: document.body.className,
          fontFamily: bodyStyle.fontFamily,
          hasKoreanFont: /Noto Sans KR|Apple SD Gothic Neo|Malgun Gothic/.test(bodyStyle.fontFamily),
          topbar: rectOf('.topbar'),
          todayWrap: rectOf('#todayWrap'),
          logModal: rectOf('#logModal'),
          logPanel: panel,
          modalWithinViewport,
          containsKorean: text.includes('운영 콘솔 온라인') && text.includes('상담 기록 QA'),
        };
      }, item.name);
      assert(status.bodyClass.includes('admin'), `${item.name}: body.admin missing`);
      assert(status.hasKoreanFont, `${item.name}: Korean font stack missing`);
      assert(status.topbar && status.topbar.width > 0 && status.topbar.height > 0, `${item.name}: topbar invisible`);
      assert(status.todayWrap && status.todayWrap.width > 0 && status.todayWrap.height > 0, `${item.name}: todayWrap invisible`);
      assert(status.logPanel && status.logPanel.width > 0 && status.logPanel.height > 0, `${item.name}: log modal invisible`);
      assert(status.modalWithinViewport, `${item.name}: log modal outside viewport`);
      assert(status.containsKorean, `${item.name}: Korean QA text missing`);
      const screenshotPath = path.join(outDir, item.screenshot);
      await page.screenshot({ path: screenshotPath, fullPage: false });
      assert(fs.statSync(screenshotPath).size > 10_000, `${item.name}: screenshot too small`);
      statuses.push(status);
      await context.close();
    }
  } finally {
    await browser.close();
  }
  const statusPath = path.join(outDir, 'task-14-admin-css-status.json');
  fs.writeFileSync(statusPath, `${JSON.stringify(statuses, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(statuses));
})().catch((error) => {
  console.error(error.stack || String(error));
  process.exit(1);
});
