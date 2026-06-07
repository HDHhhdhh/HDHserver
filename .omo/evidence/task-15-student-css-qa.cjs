const fs = require('fs/promises');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.STUDENT_QA_URL || 'http://127.0.0.1:8003/student/007?date=2026-06-06';
const evidenceDir = path.resolve(__dirname);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function assignedTestFixture() {
  return {
    id: 'UNIT-LINK-QA-2026-06-06',
    testId: 'UNIT-LINK-QA-2026-06-06',
    name: 'UNIT-LINK-QA-2026-06-06 국어 독해 확인 테스트',
    label: 'UNIT-LINK-QA-2026-06-06 국어 독해 확인 테스트',
    categoryLabel: '단원평가',
    curriculum: '국어',
    difficulty: '기본',
    round: '1회차',
    status: 'assigned',
    statusLabel: '배정',
    answerUrl: 'https://drive.google.com/file/d/qa-answer/view',
    answerRestricted: false,
    submissionRestricted: false,
  };
}

function bootstrapBody(assignedTests) {
  return {
    ok: true,
    student: {
      id: '007',
      name: '김테스트',
      curriculum: '국어',
      schedule: {},
    },
    students: [
      {
        id: '007',
        name: '김테스트',
        curriculum: '국어',
        schedule: {},
      },
    ],
    videos: [],
    updates: {},
    materials: {},
    assigns: {},
    absent: {},
    logs: {},
    assignedTests,
    homeworkBooks: [],
    academyAccessAllowed: true,
    courseBlocked: false,
    courseVideosCompleted: false,
    testSubmissionBlocked: false,
  };
}

async function installRoutes(context, assignedTests) {
  await context.route('**/api/student/bootstrap?*', route => route.fulfill({
    status: 200,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify(bootstrapBody(assignedTests)),
  }));
  await context.route('**/api/watch/latest?*', route => route.fulfill({
    status: 200,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify({ ok: true, watch: {} }),
  }));
  await context.route('**/api/auth/me', route => route.fulfill({
    status: 200,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify({ ok: true, authenticated: false }),
  }));
  await context.route('**/api/announcements?*', route => route.fulfill({
    status: 200,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify({ ok: true, announcements: [] }),
  }));
  await context.route('**/api/announce-status?*', route => route.fulfill({
    status: 200,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify({ ok: true, status: {} }),
  }));
}

function overlaps(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

async function inspectAssignedPanel(page, expectVisible) {
  await page.waitForFunction(() => Array.isArray(window.__ASSIGNED_TESTS__), null, { timeout: 10000 });
  await page.waitForSelector('#assignedTestsPanel', { state: 'attached' });
  const state = await page.evaluate(() => {
    const panel = document.querySelector('#assignedTestsPanel');
    const button = document.querySelector('#assignedTestsPanel .assigned-test-btn');
    const name = document.querySelector('#assignedTestsPanel .assigned-test-name');
    const meta = document.querySelector('#assignedTestsPanel .assigned-test-meta');
    const status = document.querySelector('#assignedTestsPanel .assigned-test-status');
    const bodyFont = getComputedStyle(document.body).fontFamily;
    const panelStyle = panel ? getComputedStyle(panel) : null;
    const rectFor = element => {
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        top: rect.top,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
      };
    };
    return {
      bodyText: document.body.innerText,
      assignedCount: Array.isArray(window.__ASSIGNED_TESTS__) ? window.__ASSIGNED_TESTS__.length : -1,
      panelHidden: panel ? panel.hidden : true,
      panelDisplayed: panelStyle ? panelStyle.display !== 'none' && panelStyle.visibility !== 'hidden' : false,
      bodyFont,
      panel: rectFor(panel),
      button: rectFor(button),
      name: rectFor(name),
      meta: rectFor(meta),
      status: rectFor(status),
      buttonText: button ? button.innerText : '',
      viewportWidth: window.innerWidth,
    };
  });

  if (expectVisible) {
    assert(state.assignedCount === 1, `expected one assigned test, got ${state.assignedCount}`);
    assert(!state.panelHidden && state.panelDisplayed, 'assigned tests panel should be visible');
    assert(state.buttonText.includes('UNIT-LINK-QA-2026-06-06'), 'assigned test label should render');
    assert(state.bodyText.includes('오늘 테스트'), 'Korean panel title should render');
    assert(state.bodyFont.includes('Noto Sans KR') || state.bodyFont.includes('Apple SD Gothic Neo') || state.bodyFont.includes('Malgun Gothic') || state.bodyFont.includes('IBM Plex Sans KR'), `missing Korean font stack: ${state.bodyFont}`);
    for (const [label, rect] of Object.entries({ panel: state.panel, button: state.button, name: state.name, meta: state.meta, status: state.status })) {
      assert(rect, `${label} rect missing`);
      assert(rect.left >= -1, `${label} extends past left viewport`);
      assert(rect.right <= state.viewportWidth + 1, `${label} extends past right viewport`);
      assert(rect.scrollWidth <= rect.clientWidth + 2, `${label} has horizontal text overflow`);
    }
    assert(!overlaps(state.name, state.status), 'assigned test name and status overlap');
  } else {
    assert(state.assignedCount === 0, `expected no assigned tests, got ${state.assignedCount}`);
    assert(state.panelHidden || !state.panelDisplayed, 'assigned tests panel should be hidden with no tests');
  }

  return state;
}

async function runCase(browser, qaCase) {
  const context = await browser.newContext({ viewport: qaCase.viewport, deviceScaleFactor: 1 });
  await installRoutes(context, qaCase.assignedTests);
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  const state = await inspectAssignedPanel(page, qaCase.expectVisible);
  for (const screenshotName of qaCase.screenshots) {
    const buffer = await page.screenshot({
      path: path.join(evidenceDir, screenshotName),
      fullPage: true,
    });
    assert(buffer.length > 10000, `${screenshotName} looks too small to be useful`);
  }
  assert(pageErrors.length === 0, `page errors: ${pageErrors.join('; ')}`);
  await context.close();
  return { name: qaCase.name, viewport: qaCase.viewport, state };
}

(async () => {
  await fs.mkdir(evidenceDir, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const cases = [
      {
        name: 'desktop-assigned',
        viewport: { width: 1440, height: 900 },
        assignedTests: [assignedTestFixture()],
        expectVisible: true,
        screenshots: ['task-15-student-css-1440.png', 'task-15-whole-project-refactor.png'],
      },
      {
        name: 'mobile-assigned',
        viewport: { width: 390, height: 844 },
        assignedTests: [assignedTestFixture()],
        expectVisible: true,
        screenshots: ['task-15-student-css-390.png'],
      },
      {
        name: 'mobile-empty',
        viewport: { width: 390, height: 844 },
        assignedTests: [],
        expectVisible: false,
        screenshots: ['task-15-whole-project-refactor-error.png'],
      },
    ];
    const results = [];
    for (const qaCase of cases) {
      results.push(await runCase(browser, qaCase));
    }
    await fs.writeFile(
      path.join(evidenceDir, 'task-15-student-css-status.json'),
      JSON.stringify({ baseUrl, cases: results }, null, 2),
      'utf8',
    );
    console.log(JSON.stringify({ ok: true, baseUrl, cases: results.map(result => result.name) }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
