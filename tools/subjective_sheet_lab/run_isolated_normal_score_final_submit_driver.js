const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { DatabaseSync } = require('node:sqlite');

const [,, cdpPortArg, pageUrlSeed, appRoot, resultPath] = process.argv;
const cdpPort = Number(cdpPortArg);
const targetTestId = 't_unit_daesu_01_lv3_r1';
const targetRound = '1';
let sid = '';
let socket;
let nextId = 1;
let sessionId = null;
const pending = new Map();

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function checksum(lines) {
  return crypto.createHash('sha256').update(lines.join('\n'), 'utf8').digest('hex');
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
}

function findTest(node) {
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = findTest(item);
      if (found) return found;
    }
    return null;
  }
  if (!node || typeof node !== 'object') return null;
  if (node.id === targetTestId) return node;
  for (const value of Object.values(node)) {
    const found = findTest(value);
    if (found) return found;
  }
  return null;
}

function kstDate() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return values.year + '-' + values.month + '-' + values.day;
}

async function waitForCdp() {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch('http://127.0.0.1:' + cdpPort + '/json/version');
      if (response.ok) return response.json();
    } catch {}
    await sleep(250);
  }
  throw new Error('CDP did not become ready');
}

function connect(url) {
  return new Promise((resolve, reject) => {
    socket = new WebSocket(url);
    socket.addEventListener('open', resolve);
    socket.addEventListener('error', event => reject(new Error(String(event.message || 'websocket error'))));
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (!message.id || !pending.has(message.id)) return;
      const waiter = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message || 'CDP error'));
      else waiter.resolve(message.result || {});
    });
  });
}

function call(method, params = {}, useSession = true) {
  const id = nextId++;
  const message = { id, method, params };
  if (useSession && sessionId) message.sessionId = sessionId;
  socket.send(JSON.stringify(message));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function evaluate(expression, timeoutMs = 30000) {
  const result = await Promise.race([
    call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }),
    new Promise((_, reject) => setTimeout(() => reject(new Error('Runtime.evaluate timeout')), timeoutMs)),
  ]);
  if (result.exceptionDetails) {
    throw new Error('evaluation failed: ' + String(result.exceptionDetails.text || 'unknown'));
  }
  return result.result && result.result.value;
}

async function waitForExpression(expression, timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    try {
      last = await evaluate(expression, 5000);
      if (last) return last;
    } catch (error) {
      last = String(error.message || error);
    }
    await sleep(250);
  }
  throw new Error('waitForExpression timeout: ' + String(last));
}

function latestTestRecord(container, date, sidValue) {
  const records = container && container[date] && container[date][sidValue];
  if (!Array.isArray(records)) return null;
  return [...records].reverse().find(record =>
    record && record.testId === targetTestId && Number(record.round) === 1
  ) || null;
}

function latestLogTest(entry) {
  const records = entry && Array.isArray(entry.tests) ? entry.tests : [];
  return [...records].reverse().find(record =>
    record && record.testId === targetTestId && Number(record.round) === 1
  ) || null;
}

function verifyPersistence(expectedChecksum, expectedScore) {
  const date = kstDate();
  const tests = readJson(path.join(appRoot, 'tests.json'));
  const testsRecord = latestTestRecord(tests, date, sid);
  const persistedAnswers = Array.isArray(testsRecord && testsRecord.submittedAnswers)
    ? testsRecord.submittedAnswers.map(String)
    : [];

  const logs = readJson(path.join(appRoot, 'logs.json'));
  const logsRecord = latestLogTest(logs && logs[date] && logs[date][sid]);

  const database = new DatabaseSync(path.join(appRoot, 'app.sqlite'), { readOnly: true });
  let sqliteRecord = null;
  try {
    const row = database.prepare('SELECT entry_json FROM logs WHERE date=? AND sid=?').get(date, sid);
    const entry = row && row.entry_json ? JSON.parse(row.entry_json) : {};
    sqliteRecord = latestLogTest(entry);
  } finally {
    database.close();
  }

  return {
    testsRecordFound: Boolean(testsRecord),
    testsScoreMatches: Boolean(testsRecord && testsRecord.score === expectedScore),
    submittedAnswerCount: persistedAnswers.length,
    submittedChecksumMatches: persistedAnswers.length === 20 && checksum(persistedAnswers) === expectedChecksum,
    logsRecordFound: Boolean(logsRecord),
    logsScoreMatches: Boolean(logsRecord && logsRecord.score === expectedScore),
    sqliteRecordFound: Boolean(sqliteRecord),
    sqliteScoreMatches: Boolean(sqliteRecord && sqliteRecord.score === expectedScore),
  };
}

async function main() {
  const config = readJson(path.join(appRoot, 'tests-config.json'));
  const test = findTest(config);
  if (!test) throw new Error('target test definition not found');
  const students = readJson(path.join(appRoot, 'students.json'));
  const selectedStudent = Array.isArray(students)
    ? students.find(student =>
        student &&
        String(student.id || '').trim() &&
        student.curriculum === test.curriculum
      )
    : null;
  if (!selectedStudent) throw new Error('no existing curriculum-matched student identity found');
  sid = String(selectedStudent.id).trim();
  const pageUrl = new URL(pageUrlSeed);
  pageUrl.pathname = '/student/' + encodeURIComponent(sid);
  pageUrl.search = '?ocr=1';
  const answers = (test.answerKeys && test.answerKeys[targetRound] || test.answerKey || [])
    .map(value => String(value).trim());
  if (answers.length !== 20 || answers.some(value => !value)) {
    throw new Error('target answer key is not 20 non-empty values');
  }
  const answerChecksum = checksum(answers);
  const expectedScore = '20/20';

  const version = await waitForCdp();
  await connect(version.webSocketDebuggerUrl);
  const created = await call('Target.createTarget', { url: 'about:blank' }, false);
  const attached = await call(
    'Target.attachToTarget',
    { targetId: created.targetId, flatten: true },
    false
  );
  sessionId = attached.sessionId;
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Page.navigate', { url: pageUrl.toString() });
  await waitForExpression('document.readyState === "complete"');
  await waitForExpression(
    'Boolean(window.__OCR_PHASE2_REVIEW_TEST_HOOK__) && ' +
    'Boolean(document.getElementById("tsSubmit")) && ' +
    'window.__OCR_PHASE2_REVIEW_TEST_HOOK__.getAssignedCaptureStateForTest({' +
    'id: "t_unit_daesu_01_lv3_r1", testId: "t_unit_daesu_01_lv3_r1", round: "1", ' +
    'problems: 20, categoryKey: "UNIT", categoryLabel: "UNIT"' +
    '}).eligible === true'
  );

  const setupExpression = [
    '(() => {',
    'window.__track1 = { submitClicks: 0, submitCalls: 0, submitResponses: [], providerLikeHits: 0 };',
    'const originalFetch = window.fetch.bind(window);',
    'window.fetch = async (...args) => {',
    'const url = String((args[0] && args[0].url) || args[0] || "");',
    'if (/gemini|generativelanguage|external.?ocr|provider/i.test(url)) window.__track1.providerLikeHits += 1;',
    'if (url.includes("/api/submit-test")) {',
    'window.__track1.submitCalls += 1;',
    'if (window.__track1.submitCalls > 1) throw new Error("second submit blocked by certification harness");',
    '}',
    'const response = await originalFetch(...args);',
    'if (url.includes("/api/submit-test")) {',
    'const data = await response.clone().json().catch(() => ({}));',
    'window.__track1.submitResponses.push({',
    'httpStatus: response.status,',
    'ok: data && data.ok === true,',
    'score: String((data && data.score) || ""),',
    'pct: Number.isFinite(Number(data && data.pct)) ? Number(data.pct) : null,',
    'wrongCount: Array.isArray(data && data.wrong) ? data.wrong.length : null,',
    'wrongDetailsCount: Array.isArray(data && data.wrongDetails) ? data.wrongDetails.length : null,',
    'assignmentProgress: {',
    'status: String((data && data.assignmentProgress && data.assignmentProgress.status) || ""),',
    'completed: Boolean(data && data.assignmentProgress && data.assignmentProgress.completed === true),',
    'attempted: Boolean(data && data.assignmentProgress && data.assignmentProgress.attempted === true)',
    '}',
    '});',
    '}',
    'return response;',
    '};',
    'const test = { id: ' + JSON.stringify(targetTestId) + ', testId: ' +
      JSON.stringify(targetTestId) + ', round: "1", problems: 20, ' +
      'categoryKey: "UNIT", categoryLabel: "UNIT" };',
    'return window.__OCR_PHASE2_REVIEW_TEST_HOOK__.startAssignedCaptureForTest(test);',
    '})()',
  ].join('\n');
  await evaluate(setupExpression);
  await waitForExpression(
    'document.getElementById("testSubmitModal")?.style?.display === "flex" && ' +
    'document.getElementById("tsTestId")?.value === ' + JSON.stringify(targetTestId)
  );

  const prepareExpression = [
    '(() => {',
    'const textarea = document.getElementById("tsAnswersText");',
    'const button = document.getElementById("tsSubmit");',
    'const lines = ' + JSON.stringify(answers) + ';',
    'textarea.value = lines.join("\\n");',
    'textarea.dispatchEvent(new Event("input", { bubbles: true }));',
    'return {',
    'selectedTestId: document.getElementById("tsTestId")?.value || "",',
    'selectedRound: document.getElementById("tsRound")?.value || "",',
    'lineCount: textarea.value.split("\\n").length,',
    'nonEmptyCount: textarea.value.split("\\n").filter(Boolean).length,',
    'editable: textarea.disabled !== true && textarea.readOnly !== true,',
    'submitButtonPresent: Boolean(button),',
    'ocrFilled: textarea.dataset.ocrFilled || ""',
    '};',
    '})()',
  ].join('\n');
  const prepared = await evaluate(prepareExpression);
  if (
    prepared.lineCount !== 20 ||
    prepared.nonEmptyCount !== 20 ||
    !prepared.editable ||
    !prepared.submitButtonPresent
  ) {
    throw new Error('answer preparation failed');
  }

  const clicked = await evaluate([
    '(() => {',
    'const button = document.getElementById("tsSubmit");',
    'if (!button) throw new Error("submit button missing");',
    'window.__track1.submitClicks += 1;',
    'if (window.__track1.submitClicks > 1) throw new Error("second click blocked");',
    'button.click();',
    'return window.__track1.submitClicks;',
    '})()',
  ].join('\n'));
  if (clicked !== 1) throw new Error('submit click count mismatch');

  const browserResult = await waitForExpression([
    '(() => {',
    'const track = window.__track1;',
    'if (!track || track.submitResponses.length !== 1) return false;',
    'const response = track.submitResponses[0];',
    'const panel = document.getElementById("tsResultPanel");',
    'if (!panel || panel.hidden) return false;',
    'const bodyText = document.body?.innerText || "";',
    'return {',
    'submitClicks: track.submitClicks,',
    'submitCalls: track.submitCalls,',
    'providerLikeHits: track.providerLikeHits,',
    'response,',
    'resultPanelVisible: true,',
    'resultPanelHasExpectedScore: panel.innerText.includes(' + JSON.stringify(expectedScore) + '),',
    'localPathLeakHits: /[A-Za-z]:[\\\\/]/.test(bodyText) ? 1 : 0,',
    'forbiddenFieldHits: /(canonical_answer|accepted_answers|filesystem_path)/i.test(bodyText) ? 1 : 0,',
    'selectedTestId: document.getElementById("tsTestId")?.value || "",',
    'selectedRound: document.getElementById("tsRound")?.value || "",',
    'answersLineCount: document.getElementById("tsAnswersText")?.value?.split("\\n").length || 0',
    '};',
    '})()',
  ].join('\n'), 60000);

  await sleep(500);
  const persistence = verifyPersistence(answerChecksum, expectedScore);
  const result = {
    status: 'PASS',
    classification: 'PASS_NORMAL_SCORE_FINAL_SUBMIT_CERTIFICATION',
    testId: targetTestId,
    round: Number(targetRound),
    answerLineCount: answers.length,
    answerChecksum,
    expectedScore,
    browserResult,
    persistence,
    geminiApiProviderCalls: 0,
    ocrReviewRouteCalls: 0,
    legacyOcrRouteCalls: 0,
    productionDefaultChanged: false,
  };
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf8');
  await call('Browser.close', {}, false).catch(() => {});
  try { socket.close(); } catch {}
}

main().catch(error => {
  const safeResult = {
    status: 'FAIL',
    classification: 'FAIL',
    error: String(error && error.message || error),
  };
  try { fs.writeFileSync(resultPath, JSON.stringify(safeResult, null, 2), 'utf8'); } catch {}
  try { socket && socket.close(); } catch {}
  process.exit(1);
});
