const fs = require('fs/promises');
const path = require('path');
const { chromium } = require('playwright');

const base = process.env.SHARED_CSS_QA_ORIGIN || 'http://127.0.0.1:8003';
const evidenceDir = path.resolve(__dirname);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function json(body) {
  return {
    status: 200,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify(body),
  };
}

function studentFixture() {
  return {
    id: '007',
    name: '김테스트',
    curriculum: '국어',
    school: '테스트중',
    grade: '1',
    day1: '월',
    time1: '13:00',
    day2: '',
    time2: '',
  };
}

function testsConfigFixture() {
  return {
    categories: {
      UNIT: {
        label: '단원평가',
        subjects: ['국어'],
        tests: [
          {
            id: 'unit-qa',
            name: 'UNIT-LINK-QA-2026-06-06',
            subject: '국어',
            curriculum: '국어',
            difficulty: 'Lv.3',
            round: 1,
            problems: 3,
            answers: ['1', '2', '3'],
          },
        ],
      },
      REVIEW: { label: '복습', subjects: ['국어'], tests: [] },
      SCHOOL_PAST: { label: '학군지', subjects: ['국어'], tests: [] },
      ILSAN_PAST: { label: '일산', subjects: ['국어'], tests: [] },
    },
  };
}

function studentBootstrapFixture(assignedTests) {
  return {
    ok: true,
    student: studentFixture(),
    students: [studentFixture()],
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

async function installApiStubs(context) {
  await context.route('**/api/**', route => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;
    if (pathname === '/api/students') return route.fulfill(json([studentFixture()]));
    if (pathname === '/api/videos') return route.fulfill(json([]));
    if (pathname === '/api/progress') return route.fulfill(json({}));
    if (pathname === '/api/school-calendar') return route.fulfill(json({}));
    if (pathname === '/api/student/bootstrap') {
      return route.fulfill(json(studentBootstrapFixture([
        {
          id: 'UNIT-LINK-QA-2026-06-06',
          name: 'UNIT-LINK-QA-2026-06-06 국어 확인',
          categoryLabel: '단원평가',
          curriculum: '국어',
          difficulty: '기본',
          round: '1회차',
          status: 'assigned',
          statusLabel: '배정',
          answerUrl: 'https://drive.google.com/file/d/qa-answer/view',
        },
      ])));
    }
    if (pathname === '/api/watch/latest') return route.fulfill(json({ ok: true, watch: {} }));
    if (pathname === '/api/auth/me') return route.fulfill(json({ ok: true, authenticated: false }));
    if (pathname === '/api/announcements') return route.fulfill(json({ ok: true, announcements: [] }));
    if (pathname === '/api/announce-status') return route.fulfill(json({ ok: true, status: {} }));
    if (pathname === '/api/tests-config') return route.fulfill(json(testsConfigFixture()));
    if (pathname === '/api/tests-stats') return route.fulfill(json({ ok: true, items: [], rows: [], summary: {} }));
    if (pathname === '/api/tests-records') return route.fulfill(json({ ok: true, items: [], rows: [] }));
    return route.fulfill(json({ ok: true }));
  });
}

function rectsOverlap(a, b) {
  if (!a || !b) return false;
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

async function inspectPage(page, selectors, viewportWidth) {
  for (const selector of selectors.required) {
    await page.waitForSelector(selector, { state: 'attached', timeout: 10000 });
  }
  const state = await page.evaluate((selectorsArg) => {
    const rectFor = (selector) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return {
        selector,
        text: element.textContent || '',
        display: style.display,
        visibility: style.visibility,
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
      title: document.title,
      bodyClass: document.body.className,
      bodyText: document.body.innerText,
      bodyFont: getComputedStyle(document.body).fontFamily,
      rects: selectorsArg.measure.map(rectFor).filter(Boolean),
    };
  }, selectors);

  assert(state.bodyText.trim().length > 20, `${selectors.name} page text is unexpectedly sparse`);
  assert(
    state.bodyFont.includes('Noto Sans KR') || state.bodyFont.includes('Apple SD Gothic Neo') || state.bodyFont.includes('Malgun Gothic') || state.bodyFont.includes('IBM Plex Sans KR'),
    `${selectors.name} is missing a Korean-capable font stack: ${state.bodyFont}`,
  );
  for (const rect of state.rects) {
    assert(rect.display !== 'none' && rect.visibility !== 'hidden', `${rect.selector} is hidden`);
    assert(rect.width > 0 && rect.height > 0, `${rect.selector} is blank`);
    assert(rect.left >= -2, `${rect.selector} extends past left viewport`);
    assert(rect.right <= viewportWidth + 2 || rect.scrollWidth > rect.clientWidth, `${rect.selector} extends past right viewport without scroll containment`);
  }
  for (let i = 0; i < state.rects.length; i += 1) {
    for (let j = i + 1; j < state.rects.length; j += 1) {
      const a = state.rects[i];
      const b = state.rects[j];
      if (a.selector.includes('table') || b.selector.includes('table')) continue;
      assert(!rectsOverlap(a, b), `${selectors.name} overlap: ${a.selector} and ${b.selector}`);
    }
  }
  return state;
}

async function runCase(browser, qaCase) {
  const context = await browser.newContext({ viewport: qaCase.viewport, deviceScaleFactor: 1 });
  await installApiStubs(context);
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto(`${base}${qaCase.path}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(400);
  const state = await inspectPage(page, qaCase.selectors, qaCase.viewport.width);
  const buffer = await page.screenshot({
    path: path.join(evidenceDir, qaCase.screenshot),
    fullPage: true,
  });
  assert(buffer.length > 10000, `${qaCase.screenshot} looks too small to be useful`);
  assert(pageErrors.length === 0, `${qaCase.name} page errors: ${pageErrors.join('; ')}`);
  await context.close();
  return { name: qaCase.name, path: qaCase.path, viewport: qaCase.viewport, state };
}

(async () => {
  await fs.mkdir(evidenceDir, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const cases = [
      {
        name: 'students-desktop',
        path: '/students',
        viewport: { width: 1440, height: 900 },
        screenshot: 'task-16-students-1440.png',
        selectors: {
          name: 'students',
          required: ['body.all-page .topbar', '#allPageShell', '#allWrap'],
          measure: ['body.all-page .topbar', '#allWrap'],
        },
      },
      {
        name: 'students-mobile',
        path: '/students',
        viewport: { width: 390, height: 844 },
        screenshot: 'task-16-students-390.png',
        selectors: {
          name: 'students-mobile',
          required: ['body.all-page .topbar', '#allPageShell', '#allWrap'],
          measure: ['body.all-page .topbar', '#allWrap'],
        },
      },
      {
        name: 'tests-desktop',
        path: '/tests',
        viewport: { width: 1440, height: 900 },
        screenshot: 'task-16-tests-1440.png',
        selectors: {
          name: 'tests',
          required: ['body.admin.tests-page .topbar', '#testsRoot', '#testList', '#ruleGrid', '#statsTable'],
          measure: ['body.admin.tests-page .topbar', '#testList', '#ruleGrid', '.stats-table-wrap'],
        },
      },
      {
        name: 'tests-mobile',
        path: '/tests',
        viewport: { width: 390, height: 844 },
        screenshot: 'task-16-tests-390.png',
        selectors: {
          name: 'tests-mobile',
          required: ['body.admin.tests-page .topbar', '#testsRoot', '#testList', '#ruleGrid', '#statsTable'],
          measure: ['body.admin.tests-page .topbar', '#testList', '#ruleGrid', '.stats-table-wrap'],
        },
      },
      {
        name: 'student-desktop',
        path: '/student/007?date=2026-06-06',
        viewport: { width: 1440, height: 900 },
        screenshot: 'task-16-student-1440.png',
        selectors: {
          name: 'student',
          required: ['body.student-page .student-shell', '#playerBox', '#assignedTestsPanel'],
          measure: ['body.student-page .student-topbar', '.hero-bar', '#playerBox', '#assignedTestsPanel'],
        },
      },
      {
        name: 'student-mobile',
        path: '/student/007?date=2026-06-06',
        viewport: { width: 390, height: 844 },
        screenshot: 'task-16-student-390.png',
        selectors: {
          name: 'student-mobile',
          required: ['body.student-page .student-shell', '#playerBox', '#assignedTestsPanel'],
          measure: ['body.student-page .student-topbar', '.hero-bar', '#playerBox', '#assignedTestsPanel'],
        },
      },
    ];
    const results = [];
    for (const qaCase of cases) {
      results.push(await runCase(browser, qaCase));
    }
    await fs.writeFile(
      path.join(evidenceDir, 'task-16-shared-css-status.json'),
      JSON.stringify({ ok: true, base, cases: results }, null, 2),
      'utf8',
    );
    console.log(JSON.stringify({ ok: true, base, cases: results.map(result => result.name) }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
