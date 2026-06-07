const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const BASE = process.env.F3_LIVE_BASE || 'http://127.0.0.1:8003';
const DATE = '2026-06-06';
const SID = '007';
const ANSWER_URL = 'https://drive.google.com/file/d/TEST_SOLUTION_FILE_ID_20260606/view';

const screenshots = {
  adminOpen: '.omo/evidence/f3-live-admin-unified-open.png',
  adminSaved: '.omo/evidence/f3-live-admin-unified-saved.png',
  adminReloaded: '.omo/evidence/f3-live-admin-unified-reloaded.png',
  adminForceEmpty: '.omo/evidence/f3-live-admin-force-empty.png',
  studentAllowed: '.omo/evidence/f3-live-student-answer-allowed.png',
  studentRestricted: '.omo/evidence/f3-live-student-answer-restricted.png',
};

const calls = [];
const pageErrors = [];
const consoleMessages = [];
const patches = {
  progress: [],
  logs: [],
  updates: [],
};

let studentRestricted = false;
const student = {
  id: SID,
  name: '라이브QA',
  school: 'QA중',
  curriculum: '수학',
  subCurriculum: '대수',
  level: '중',
  day1: '토1',
};
const videos = [
  { mid: 'm1', title: '라이브 QA 영상', curriculum: '수학', subCurriculum: '대수', chapter: 1, exNum: 1 },
];
const testItem = {
  id: 'unit-live',
  sourceId: 'unit-live',
  name: '라이브 QA 테스트',
  category: 'UNIT',
  categoryLabel: '단원평가',
  curriculum: '수학',
  difficulty: '기본',
  round: '1',
  label: 'UNIT-LINK-QA-2026-06-06',
  status: 'assigned',
  answerUrl: ANSWER_URL,
};
const testsConfig = {
  categories: {
    UNIT: {
      label: '단원평가',
      tests: [testItem],
    },
  },
};
const logs = {
  [DATE]: {
    [SID]: {
      notes: '라이브 QA 메모',
      homeworkTable: [],
      assignedTests: [testItem],
      testAssignmentDailyTests: [testItem],
    },
  },
};
const progress = {
  [DATE]: {
    [SID]: {
      m1: 'done',
      tests: { [testItem.label]: 'assigned' },
    },
  },
};
const updates = {
  [DATE]: {
    [SID]: { videos: ['m1'], source: 'manual' },
  },
};

function jsonResponse(payload, status = 200) {
  return {
    status,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify(payload),
  };
}

function fullCalendarStubSource() {
  return `
    window.FullCalendar = {
      Calendar: class {
        constructor(el, options) {
          this.el = el;
          this.options = options || {};
          const current = new Date('${DATE}T00:00:00');
          this.view = {
            currentStart: current,
            currentEnd: current,
            activeStart: current,
            activeEnd: current,
          };
        }
        render() {}
        destroy() {}
        removeAllEvents() {}
        addEventSource() {}
        addEvent() {}
        getEvents() { return []; }
        refetchEvents() {}
        updateSize() {}
        today() {}
        gotoDate() {}
      }
    };
  `;
}

function mergeProgressPatch(body) {
  const date = String(body.date || DATE);
  const sid = String(body.sid || SID);
  progress[date] = progress[date] || {};
  progress[date][sid] = progress[date][sid] || {};
  const target = progress[date][sid];
  for (const [key, value] of Object.entries(body.progress || {})) {
    if (key === 'tests' && value && typeof value === 'object') {
      target.tests = { ...(target.tests || {}), ...value };
    } else {
      target[key] = value;
      if (value === 'none') {
        target.__manualProgressMids = target.__manualProgressMids || {};
        target.__manualProgressMids[key] = true;
      }
    }
  }
  return target;
}

function mergeLogPatch(body) {
  const date = String(body.date || DATE);
  const sid = String(body.sid || SID);
  logs[date] = logs[date] || {};
  const current = logs[date][sid] || {};
  const next = { ...current, ...(body.entry || {}) };
  for (const key of body.__clear || []) delete next[String(key)];
  logs[date][sid] = next;
  return next;
}

async function routeFixture(route) {
  const request = route.request();
  const url = new URL(request.url());
  calls.push({ method: request.method(), path: url.pathname, query: url.search });

  if (!request.url().startsWith(BASE)) {
    if (url.pathname.endsWith('.js')) {
      await route.fulfill({
        status: 200,
        contentType: 'text/javascript',
        body: fullCalendarStubSource(),
      });
      return;
    }
    await route.fulfill({ status: 204, body: '' });
    return;
  }

  if (url.pathname === '/api/students') {
    await route.fulfill(jsonResponse([student]));
    return;
  }
  if (url.pathname === '/api/videos') {
    await route.fulfill(jsonResponse(videos));
    return;
  }
  if (url.pathname === '/api/materials' || url.pathname === '/api/mat-assign' || url.pathname === '/api/extra-attend') {
    await route.fulfill(jsonResponse({}));
    return;
  }
  if (url.pathname === '/api/updates') {
    await route.fulfill(jsonResponse(updates));
    return;
  }
  if (url.pathname === '/api/absent') {
    await route.fulfill(jsonResponse({ by_date: {}, by_student: {}, by_slot: {} }));
    return;
  }
  if (url.pathname === '/api/school-calendar' || url.pathname === '/api/weekend-slots' || url.pathname === '/api/today_order' || url.pathname === '/api/makeup-carryover') {
    await route.fulfill(jsonResponse({}));
    return;
  }
  if (url.pathname.startsWith('/npm/fullcalendar')) {
    if (url.pathname.endsWith('.js')) {
      await route.fulfill({ status: 200, contentType: 'text/javascript', body: fullCalendarStubSource() });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'text/css', body: '' });
    return;
  }
  if (url.pathname === '/api/tests-config') {
    await route.fulfill(jsonResponse(testsConfig));
    return;
  }
  if (url.pathname === '/api/attendance' || url.pathname === '/api/contact' || url.pathname === '/arrive-time') {
    await route.fulfill(jsonResponse({}));
    return;
  }
  if (url.pathname === '/api/logs/entry') {
    const date = url.searchParams.get('date') || DATE;
    const sid = url.searchParams.get('sid') || SID;
    await route.fulfill(jsonResponse({ ok: true, source: 'json', entry: logs[date]?.[sid] || {} }));
    return;
  }
  if (url.pathname === '/api/logs') {
    await route.fulfill(jsonResponse(logs));
    return;
  }
  if (url.pathname === '/api/progress') {
    const date = url.searchParams.get('date');
    const sid = url.searchParams.get('sid');
    if (date && sid) {
      await route.fulfill(jsonResponse({ [date]: { [sid]: progress[date]?.[sid] || {} } }));
      return;
    }
    if (date) {
      await route.fulfill(jsonResponse({ [date]: progress[date] || {} }));
      return;
    }
    await route.fulfill(jsonResponse(progress));
    return;
  }
  if (url.pathname === '/api/watch/latest') {
    await route.fulfill(jsonResponse({ ok: true, watch: { m1: { last: 100, dur: 100 } } }));
    return;
  }
  if (url.pathname === '/api/student/bootstrap') {
    const assigned = {
      ...testItem,
      answerUrl: ANSWER_URL,
      answerRestricted: studentRestricted,
      sourceFiles: studentRestricted ? {} : { solutionFileId: 'TEST_SOLUTION_FILE_ID_20260606' },
    };
    await route.fulfill(jsonResponse({
      ok: true,
      student,
      videos,
      updates,
      progress,
      logs,
      testsConfig,
      assignedTests: [assigned],
      academyAccessAllowed: !studentRestricted,
      outsideAcademyBlocked: studentRestricted,
    }));
    return;
  }
  if (request.method() !== 'GET' && url.pathname === '/api/progress/patch') {
    const body = JSON.parse(request.postData() || '{}');
    patches.progress.push(body);
    const entry = mergeProgressPatch(body);
    await route.fulfill(jsonResponse({ ok: true, progress: entry }));
    return;
  }
  if (request.method() !== 'GET' && url.pathname === '/api/logs/patch') {
    const body = JSON.parse(request.postData() || '{}');
    patches.logs.push(body);
    const entry = mergeLogPatch(body);
    await route.fulfill(jsonResponse({ ok: true, entry, sqlite: true, json: true }));
    return;
  }
  if (request.method() !== 'GET' && url.pathname === '/api/updates/patch') {
    const body = JSON.parse(request.postData() || '{}');
    patches.updates.push(body);
    const date = String(body.date || DATE);
    const sid = String(body.sid || SID);
    updates[date] = updates[date] || {};
    updates[date][sid] = body.entry || {};
    await route.fulfill(jsonResponse({ ok: true, updates }));
    return;
  }
  if (request.method() !== 'GET') {
    await route.fulfill(jsonResponse({ ok: true }));
    return;
  }
  await route.continue();
}

async function visibleState(page, selector) {
  return page.locator(selector).evaluate((el) => {
    const style = getComputedStyle(el);
    return style.display !== 'none' && style.visibility !== 'hidden' && el.getBoundingClientRect().width > 0;
  });
}

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await context.addInitScript((date) => {
    window.FullCalendar = window.FullCalendar || {
      Calendar: class {
        constructor() {
          const current = new Date(`${date}T00:00:00`);
          this.view = {
            currentStart: current,
            currentEnd: current,
            activeStart: current,
            activeEnd: current,
          };
        }
        render() {}
        destroy() {}
        removeAllEvents() {}
        addEventSource() {}
        addEvent() {}
        getEvents() { return []; }
        refetchEvents() {}
        updateSize() {}
        today() {}
        gotoDate() {}
      },
    };
    window.sessionStorage.setItem('adminSelectedDate', date);
  }, DATE);
  const page = await context.newPage();
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) {
      consoleMessages.push({ type: message.type(), text: message.text() });
    }
  });
  await page.route('**/*', routeFixture);

  await page.goto(`${BASE}/admin`, { waitUntil: 'domcontentloaded' });
  const row = page.locator(`tr[data-sid="${SID}"][data-date="${DATE}"]`).first();
  await row.waitFor({ state: 'visible', timeout: 15000 });
  await row.locator('.openStudentPopups').click();
  await page.locator('#logModal.student-work-layout').waitFor({ state: 'visible', timeout: 15000 });
  await page.locator('#vidModal.student-work-layout').waitFor({ state: 'visible', timeout: 15000 });
  await page.locator('#testModal.student-work-layout').waitFor({ state: 'visible', timeout: 15000 });
  await page.screenshot({ path: screenshots.adminOpen, fullPage: true });

  const cell = page.locator('#logProgress .progress-cell[data-mid="m1"]').first();
  await cell.waitFor({ state: 'visible', timeout: 15000 });
  const initialCellState = await cell.getAttribute('data-state');
  if (initialCellState === 'done') {
    await cell.click();
    await cell.click();
  } else if (initialCellState !== 'none') {
    await cell.click();
  }
  assert.equal(await cell.getAttribute('data-state'), 'none');

  const firstVideoChecked = await page.locator('#chkZone input[type="checkbox"][value="m1"]').first().isChecked();
  assert.equal(firstVideoChecked, true);
  const testRows = await page.locator('#testAssignList .test-row').count();
  assert.ok(testRows >= 1, 'live admin test modal must render at least one test row');
  await page.locator('#testAssignList .test-row').first().click();

  await page.locator('#logSave').click();
  await page.waitForFunction(() => window.__f3Saved = true, null, { timeout: 250 }).catch(() => {});
  await page.waitForTimeout(800);
  await page.screenshot({ path: screenshots.adminSaved, fullPage: true });

  const manualWhitePatch = patches.progress.find((body) => body?.progress?.m1 === 'none');
  assert.ok(manualWhitePatch, 'live /admin log save must patch manual white progress');
  const manualUpdatePatch = patches.updates.find((body) => body?.entry?.source === 'manual');
  assert.ok(manualUpdatePatch, 'live /admin video save must preserve manual source');
  const testProgressPatch = patches.progress.find((body) => body?.progress?.tests);
  assert.ok(testProgressPatch, 'live /admin test save must patch progress tests');

  await page.reload({ waitUntil: 'domcontentloaded' });
  const reopenedRow = page.locator(`tr[data-sid="${SID}"][data-date="${DATE}"]`).first();
  await reopenedRow.waitFor({ state: 'visible', timeout: 15000 });
  await reopenedRow.locator('.openStudentPopups').click();
  await page.locator('#logModal.student-work-layout').waitFor({ state: 'visible', timeout: 15000 });
  await page.locator('#vidModal.student-work-layout').waitFor({ state: 'visible', timeout: 15000 });
  const reloadedCell = page.locator('#logProgress .progress-cell[data-mid="m1"]').first();
  await reloadedCell.waitFor({ state: 'visible', timeout: 15000 });
  const reloadedCellState = await reloadedCell.getAttribute('data-state');
  const reloadedNotes = await page.locator('#logNotes').inputValue();
  const reloadedHomeworkText = await page.locator('#logModal').innerText();
  assert.equal(reloadedCellState, 'none');
  assert.ok(!/[?]{3,}/.test(`${reloadedNotes}\n${reloadedHomeworkText}`), 'live reload/reopen must not show ??? or ????');
  await page.screenshot({ path: screenshots.adminReloaded, fullPage: true });

  const updatesBeforeForceEmpty = patches.updates.length;
  const forceEmptyResult = await page.evaluate(() => {
    if (typeof window.saveVideoAssignmentPopup !== 'function') {
      throw new Error('saveVideoAssignmentPopup is not exposed');
    }
    return window.saveVideoAssignmentPopup({ showPopup: false, refresh: false, forceEmpty: true });
  });
  await page.waitForTimeout(500);
  const forceEmptyPatch = patches.updates
    .slice(updatesBeforeForceEmpty)
    .find((body) => Array.isArray(body?.entry?.videos) && body.entry.videos.length === 0 && body.entry.source === 'manual');
  assert.ok(forceEmptyPatch, 'live /admin forceEmpty save must clear videos with manual source');
  assert.equal(forceEmptyPatch.date, DATE);
  assert.equal(forceEmptyPatch.sid, SID);
  await page.screenshot({ path: screenshots.adminForceEmpty, fullPage: true });

  studentRestricted = false;
  const allowedPage = await context.newPage();
  allowedPage.on('pageerror', (error) => pageErrors.push(`student allowed: ${error.message}`));
  await allowedPage.route('**/*', routeFixture);
  await allowedPage.goto(`${BASE}/student/${SID}?date=${DATE}`, { waitUntil: 'domcontentloaded' });
  await allowedPage.locator('#assignedTestsPanel').waitFor({ state: 'visible', timeout: 15000 });
  const allowedAction = allowedPage.locator('#assignedTestsPanel [data-answer-url]').first();
  await allowedAction.waitFor({ state: 'visible', timeout: 15000 });
  const allowedStatus = await allowedAction.evaluate((el) => ({
    tagName: el.tagName,
    href: el.getAttribute('href') || '',
    dataAnswerUrl: el.getAttribute('data-answer-url') || '',
    dataRestricted: el.getAttribute('data-answer-restricted') || '',
  }));
  assert.equal(allowedStatus.tagName, 'A');
  assert.equal(allowedStatus.dataAnswerUrl, ANSWER_URL);
  await allowedPage.screenshot({ path: screenshots.studentAllowed, fullPage: true });

  studentRestricted = true;
  const restrictedPage = await context.newPage();
  restrictedPage.on('pageerror', (error) => pageErrors.push(`student restricted: ${error.message}`));
  await restrictedPage.route('**/*', routeFixture);
  await restrictedPage.goto(`${BASE}/student/${SID}?date=${DATE}`, { waitUntil: 'domcontentloaded' });
  await restrictedPage.locator('#assignedTestsPanel').waitFor({ state: 'visible', timeout: 15000 });
  const restrictedAction = restrictedPage.locator('#assignedTestsPanel [data-answer-restricted="1"]').first();
  await restrictedAction.waitFor({ state: 'visible', timeout: 15000 });
  const restrictedStatus = await restrictedAction.evaluate((el) => ({
    tagName: el.tagName,
    href: el.getAttribute('href') || '',
    dataAnswerUrl: el.getAttribute('data-answer-url') || '',
    dataRestricted: el.getAttribute('data-answer-restricted') || '',
  }));
  assert.equal(restrictedStatus.tagName, 'BUTTON');
  assert.equal(restrictedStatus.href, '');
  assert.equal(restrictedStatus.dataRestricted, '1');
  await restrictedPage.screenshot({ path: screenshots.studentRestricted, fullPage: true });

  const status = {
    ok: true,
    base: BASE,
    admin: {
      targetUrl: `${BASE}/admin`,
      selectedDate: DATE,
      viewport: { width: 1280, height: 900 },
      modals: {
        logVisible: await visibleState(page, '#logModal'),
        videoVisible: await visibleState(page, '#vidModal'),
        testVisible: await visibleState(page, '#testModal'),
      },
      patches,
      reloadProof: {
        cellState: reloadedCellState,
        notesContainsMojibakePlaceholders: /[?]{3,}/.test(`${reloadedNotes}\n${reloadedHomeworkText}`),
      },
      forceEmpty: {
        result: forceEmptyResult,
        patch: forceEmptyPatch,
      },
      passFail: 'PASS: live /admin opened unified log/video/test modals; save patched manual white progress, manual video source, progress tests, reload/reopen preserved data-state none, and forceEmpty cleared videos with manual source.',
    },
    student: {
      targetUrl: `${BASE}/student/${SID}?date=${DATE}`,
      selectedDate: DATE,
      viewport: { width: 1280, height: 900 },
      allowedStatus,
      restrictedStatus,
      passFail: 'PASS: live student route rendered allowed answer link and restricted non-navigating button.',
    },
    screenshots,
    calls,
    pageErrors,
    consoleMessages,
  };
  assert.deepEqual(pageErrors, []);
  fs.writeFileSync('.omo/evidence/f3-live-routes-status.json', JSON.stringify(status, null, 2), 'utf8');
  console.log('f3-live-routes-qa-ok');
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
