const fs = require('fs');

const [
  ,
  ,
  cdpPortArg,
  pageUrl,
  imagePath,
  teacherDecisionsPath,
  resultPath,
  initialScreenshotPath,
  finalScreenshotPath,
] = process.argv;

const cdpPort = Number(cdpPortArg);
const teacherDecisions = JSON.parse(fs.readFileSync(teacherDecisionsPath, 'utf8'));
const teacherByQuestion = new Map(
  teacherDecisions.answers.map(item => [Number(item.question_no), item]),
);

let ws;
let sessionId;
let nextId = 1;
const pending = new Map();

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function httpJson(url) {
  const response = await fetch(url);
  return response.json();
}

async function waitForCdp() {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    try {
      return await httpJson(`http://127.0.0.1:${cdpPort}/json/version`);
    } catch {
      await sleep(250);
    }
  }
  throw new Error('CDP did not become ready');
}

function connect(url) {
  return new Promise((resolve, reject) => {
    ws = new WebSocket(url);
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', event => reject(new Error(String(event.message || 'websocket error'))));
    ws.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (!message.id || !pending.has(message.id)) return;
      const slot = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) slot.reject(new Error(`${message.error.message || 'CDP error'} ${JSON.stringify(message.error)}`));
      else slot.resolve(message.result || {});
    });
  });
}

function call(method, params = {}) {
  const id = nextId++;
  const message = { id, method, params };
  if (sessionId) message.sessionId = sessionId;
  ws.send(JSON.stringify(message));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function evaluate(expression, timeoutMs = 30_000) {
  const timeout = new Promise((_, reject) => {
    setTimeout(() => reject(new Error(`Runtime.evaluate timeout: ${expression.slice(0, 100)}`)), timeoutMs);
  });
  const result = await Promise.race([
    call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }),
    timeout,
  ]);
  if (result.exceptionDetails) throw new Error(`evaluation failed: ${JSON.stringify(result.exceptionDetails)}`);
  return result.result && result.result.value;
}

async function waitForExpression(expression, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await evaluate(expression, 5_000);
      if (last) return last;
    } catch (error) {
      last = error.message;
    }
    await sleep(250);
  }
  throw new Error(`waitForExpression timed out: ${expression}; last=${JSON.stringify(last)}`);
}

async function captureScreenshot(targetPath) {
  const result = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  fs.writeFileSync(targetPath, Buffer.from(result.data, 'base64'));
}

function routeEntries(fetchLog) {
  return fetchLog.filter(entry => entry.url.includes('/api/ocr-test-sheet-review'));
}

async function writeResult(result) {
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf8');
}

async function main() {
  const version = await waitForCdp();
  await connect(version.webSocketDebuggerUrl);
  const created = await call('Target.createTarget', { url: 'about:blank' });
  const attached = await call('Target.attachToTarget', { targetId: created.targetId, flatten: true });
  sessionId = attached.sessionId;
  await call('Runtime.enable');
  await call('Page.enable');
  await call('DOM.enable');
  await call('Network.enable');
  await call('Emulation.setDeviceMetricsOverride', {
    width: 1280,
    height: 900,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await call('Page.navigate', { url: pageUrl });
  await waitForExpression('document.readyState === "complete"', 60_000);
  await waitForExpression('Boolean(window.__OCR_PHASE2_REVIEW_TEST_HOOK__ && document.getElementById("tsAnswersText"))', 60_000);

  const prep = await evaluate(`(() => {
    const hook = window.__OCR_PHASE2_REVIEW_TEST_HOOK__;
    window.__pilotFetchLog = [];
    window.__pilotSubmitClicks = 0;
    window.__pilotPageErrors = [];
    window.addEventListener('error', event => window.__pilotPageErrors.push(String(event.error || event.message || 'page error')));
    window.addEventListener('unhandledrejection', event => window.__pilotPageErrors.push(String(event.reason || 'unhandled rejection')));
    const submit = document.getElementById('tsSubmit');
    if (submit) {
      submit.disabled = true;
      submit.addEventListener('click', event => {
        window.__pilotSubmitClicks += 1;
        event.preventDefault();
        event.stopImmediatePropagation();
      }, true);
    }
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const url = String(args[0] && args[0].url || args[0] || '');
      const method = String(args[1] && args[1].method || 'GET').toUpperCase();
      const entry = { url, method, status: null, ok: null, bodyText: '', error: null };
      window.__pilotFetchLog.push(entry);
      try {
        const response = await originalFetch(...args);
        entry.status = response.status;
        entry.ok = response.ok;
        if (url.includes('/api/ocr-test-sheet-review')) entry.bodyText = await response.clone().text();
        return response;
      } catch (error) {
        entry.error = String(error && error.message || error);
        throw error;
      }
    };
    const test = {
      id: 't_unit_daesu_01_lv3_r1',
      testId: 't_unit_daesu_01_lv3_r1',
      round: '1',
      problems: 20,
      categoryKey: 'UNIT',
      categoryLabel: 'unit'
    };
    const opened = hook.startAssignedCaptureForTest(test);
    return {
      featureEnabled: window.__OCR_TEST_SHEET_ENABLED === true,
      opened,
      state: hook.getAssignedCaptureStateForTest(test),
      submitDisabled: submit ? submit.disabled === true : false,
    };
  })()`);

  await waitForExpression(`(() => {
    const hook = window.__OCR_PHASE2_REVIEW_TEST_HOOK__;
    const test = { id: 't_unit_daesu_01_lv3_r1', testId: 't_unit_daesu_01_lv3_r1', round: '1', categoryKey: 'UNIT' };
    const state = hook.getAssignedCaptureStateForTest(test);
    return state.enabled === true && state.eligible === true && state.selectedTestId === 't_unit_daesu_01_lv3_r1' && String(state.selectedRound) === '1';
  })()`, 20_000);

  const documentNode = await call('DOM.getDocument', { depth: 1, pierce: true });
  const input = await call('DOM.querySelector', { nodeId: documentNode.root.nodeId, selector: '#tsOcrReviewImage' });
  if (!input.nodeId) throw new Error('OCR image input not found');
  await call('DOM.setFileInputFiles', { nodeId: input.nodeId, files: [imagePath] });
  const fileState = await evaluate(`(() => {
    const input = document.getElementById('tsOcrReviewImage');
    return {
      fileCount: input && input.files ? input.files.length : 0,
      fileName: input && input.files && input.files[0] ? input.files[0].name : '',
      fileSize: input && input.files && input.files[0] ? input.files[0].size : 0,
    };
  })()`);
  if (fileState.fileCount !== 1) throw new Error(`file input was not populated: ${JSON.stringify(fileState)}`);

  await evaluate('window.__OCR_PHASE2_REVIEW_TEST_HOOK__.openRouteFlow()', 240_000);
  await waitForExpression(`(() => {
    const calls = (window.__pilotFetchLog || []).filter(entry => entry.url.includes('/api/ocr-test-sheet-review'));
    return calls.length === 1 && calls[0].status !== null;
  })()`, 240_000);

  const routeSnapshot = await evaluate(`(() => {
    const fetchLog = window.__pilotFetchLog || [];
    const calls = fetchLog.filter(entry => entry.url.includes('/api/ocr-test-sheet-review'));
    const route = calls[0] || null;
    let parsedBody = null;
    try { parsedBody = route && route.bodyText ? JSON.parse(route.bodyText) : null; } catch {}
    return {
      fetchLog,
      route,
      parsedBody,
      payload: window.__OCR_PHASE2_REVIEW_TEST_HOOK__.getCurrentPayload(),
      reviewMeta: window.__OCR_PHASE2_REVIEW_TEST_HOOK__.getLastReviewMeta(),
      statusText: document.getElementById('tsOcrStatus')?.textContent || '',
      panelHidden: document.getElementById('tsOcrReviewPanel')?.hidden !== false,
    };
  })()`);

  if (!routeSnapshot.payload) {
    await captureScreenshot(initialScreenshotPath);
    await writeResult({
      ok: false,
      blocked: true,
      prep,
      fileState,
      routeSnapshot,
      submitClicks: await evaluate('window.__pilotSubmitClicks || 0'),
    });
    await call('Browser.close').catch(() => {});
    return;
  }

  const initialState = await evaluate(`(() => {
    const hook = window.__OCR_PHASE2_REVIEW_TEST_HOOK__;
    const payload = hook.getCurrentPayload();
    return {
      payload,
      itemCount: payload.items.length,
      questionNumbers: payload.items.map(item => item.question_no),
      initialCandidateCount: payload.items.filter(item => Array.isArray(item.candidates) && item.candidates.length > 0).length,
      initialBlankCount: payload.items.filter(item => !Array.isArray(item.candidates) || item.candidates.length === 0).length,
      automaticFinalAnswerCount: payload.items.filter(item => item.final_answer).length,
      unsafeAutoFillCount: payload.items.filter(item => ['safe_auto_grade', 'auto_grade', 'automatic'].includes(item.status)).length,
      forbiddenKeys: hook.findForbiddenKeys(payload),
      forbiddenPathValues: hook.findForbiddenPathValues(payload),
      unresolved: hook.getUnresolvedStateForTest(),
      firstNavigation: hook.focusNextUnresolvedForTest(),
      cardCount: document.querySelectorAll('.ts-ocr-card').length,
      panelHidden: document.getElementById('tsOcrReviewPanel')?.hidden === true,
    };
  })()`);
  await captureScreenshot(initialScreenshotPath);

  const decisionObject = Object.fromEntries(
    [...teacherByQuestion.entries()].map(([questionNo, decision]) => [questionNo, decision]),
  );
  const confirmationState = await evaluate(`(() => {
    const decisions = ${JSON.stringify(decisionObject)};
    const hook = window.__OCR_PHASE2_REVIEW_TEST_HOOK__;
    const initial = hook.getCurrentPayload();
    const candidateCorrectQuestions = [];
    const candidateCorrectedQuestions = [];
    const directInputQuestions = [];
    const confirmedQuestions = [];
    const unresolvedQuestions = [];
    const failures = [];

    for (const initialItem of initial.items) {
      const questionNo = Number(initialItem.question_no);
      const decision = decisions[String(questionNo)];
      if (!decision || decision.confirm !== true) {
        unresolvedQuestions.push(questionNo);
        continue;
      }
      const answer = String(decision.answer || '').trim();
      const mode = String(initialItem.answer_mode || 'answer_value');
      if (!answer || (mode === 'choice_number' && !/^[1-5]$/.test(answer))) {
        unresolvedQuestions.push(questionNo);
        continue;
      }
      const initialCandidates = Array.isArray(initialItem.candidates) ? initialItem.candidates.map(String) : [];
      const hadCandidate = initialCandidates.length > 0;
      const matchingCandidate = initialCandidates.includes(answer);
      const card = document.querySelector('.ts-ocr-card[data-question-no="' + questionNo + '"]');
      if (!card) {
        failures.push('missing card q' + questionNo);
        continue;
      }
      const input = card.querySelector('.ts-ocr-current');
      const confirm = card.querySelector('.ts-ocr-confirm');
      if (!input || !confirm) {
        failures.push('missing input/confirm q' + questionNo);
        continue;
      }
      if (matchingCandidate) {
        const candidate = [...card.querySelectorAll('.ts-ocr-candidate')]
          .find(button => button.textContent === '인식 후보 ' + answer);
        if (!candidate) {
          failures.push('missing matching candidate button q' + questionNo);
          continue;
        }
        candidate.click();
        candidateCorrectQuestions.push(questionNo);
      } else if (mode === 'choice_number') {
        const choice = card.querySelector('.ts-ocr-choice[data-value="' + answer + '"]');
        if (!choice) {
          failures.push('missing choice button q' + questionNo);
          continue;
        }
        choice.click();
        directInputQuestions.push(questionNo);
        if (hadCandidate) candidateCorrectedQuestions.push(questionNo);
      } else {
        input.value = answer;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        directInputQuestions.push(questionNo);
        if (hadCandidate) candidateCorrectedQuestions.push(questionNo);
      }
      confirm.click();
      const confirmedItem = hook.getCurrentPayload().items.find(item => Number(item.question_no) === questionNo);
      if (confirmedItem && String(confirmedItem.final_answer || '') === answer) confirmedQuestions.push(questionNo);
      else failures.push('confirmation failed q' + questionNo);
    }

    return {
      initialCandidateCount: initial.items.filter(item => Array.isArray(item.candidates) && item.candidates.length > 0).length,
      candidateCorrectCount: candidateCorrectQuestions.length,
      candidateCorrectQuestions,
      candidateCorrectedCount: candidateCorrectedQuestions.length,
      candidateCorrectedQuestions,
      directInputCount: directInputQuestions.length,
      directInputQuestions,
      teacherConfirmedCount: confirmedQuestions.length,
      confirmedQuestions,
      unresolvedQuestions,
      failures,
      afterConfirmation: hook.getUnresolvedStateForTest(),
      nextUnresolved: hook.focusNextUnresolvedForTest(),
    };
  })()`);

  const partialFillState = await evaluate(`(() => {
    const apply = document.querySelector('.ts-ocr-apply');
    if (!apply || apply.disabled) throw new Error('partial fill button missing or disabled');
    apply.click();
    const hook = window.__OCR_PHASE2_REVIEW_TEST_HOOK__;
    const answerState = hook.getAnswersTextState();
    const lines = answerState.value.split('\\n');
    return {
      answerState,
      lineCount: lines.length,
      filledCount: lines.filter(Boolean).length,
      blankCount: lines.filter(line => !line).length,
      blankQuestions: lines.map((line, index) => line ? null : index + 1).filter(Boolean),
      unresolved: hook.getUnresolvedStateForTest(),
    };
  })()`);

  const deletionState = await evaluate(`(() => {
    const hook = window.__OCR_PHASE2_REVIEW_TEST_HOOK__;
    const before = hook.getAnswersTextState();
    const lines = before.value.split('\\n');
    const questionNo = lines.findIndex(Boolean) + 1;
    if (questionNo < 1) throw new Error('no confirmed answer available for deletion test');
    const saved = lines[questionNo - 1];
    lines[questionNo - 1] = '';
    hook.setAnswersTextForTest(lines.join('\\n'));
    const afterDelete = hook.getUnresolvedStateForTest();
    const deletedLineCount = hook.getAnswersTextState().value.split('\\n').length;
    lines[questionNo - 1] = saved;
    hook.setAnswersTextForTest(lines.join('\\n'));
    const afterRestore = hook.getUnresolvedStateForTest();
    const restoredLineCount = hook.getAnswersTextState().value.split('\\n').length;
    return { questionNo, afterDelete, afterRestore, deletedLineCount, restoredLineCount };
  })()`);

  const finalState = await evaluate(`(() => {
    const hook = window.__OCR_PHASE2_REVIEW_TEST_HOOK__;
    const fetchLog = window.__pilotFetchLog || [];
    const answers = hook.getAnswersTextState();
    const lines = answers.value.split('\\n');
    const bodyText = document.body.innerText || '';
    const forbiddenTokens = ['expected', 'canonical_answer', 'accepted_answers', 'answer_key', 'answer-key', 'grading'];
    const answerKeyLeak = forbiddenTokens.some(token => bodyText.toLowerCase().includes(token));
    const pathLeak = /[A-Za-z]:[\\\\/]/.test(bodyText) || /server-ocr|phase2c_route_uploads|crop_benchmark_inputs/i.test(bodyText);
    const resourceUrls = performance.getEntriesByType('resource').map(entry => String(entry.name || ''));
    const externalResourceUrls = resourceUrls.filter(url => /^https?:/i.test(url) && !url.startsWith('http://127.0.0.1:'));
    return {
      lineCount: lines.length,
      filledCount: lines.filter(Boolean).length,
      blankCount: lines.filter(line => !line).length,
      blankQuestions: lines.map((line, index) => line ? null : index + 1).filter(Boolean),
      answersEditable: document.getElementById('tsAnswersText')?.disabled !== true,
      reviewRouteCalls: fetchLog.filter(entry => entry.url.includes('/api/ocr-test-sheet-review')).length,
      reviewRouteStatuses: fetchLog.filter(entry => entry.url.includes('/api/ocr-test-sheet-review')).map(entry => entry.status),
      submitTestCalls: fetchLog.filter(entry => entry.url.includes('/api/submit-test')).length,
      legacyOcrCalls: fetchLog.filter(entry => entry.url.includes('/api/ocr-test-sheet') && !entry.url.includes('/api/ocr-test-sheet-review')).length,
      providerLikeBrowserCalls: fetchLog.filter(entry => /gemini|generativelanguage|provider/i.test(entry.url)).length,
      externalBrowserResourceCalls: externalResourceUrls.length,
      externalResourceUrls,
      submitClicks: window.__pilotSubmitClicks || 0,
      pageErrors: window.__pilotPageErrors || [],
      answerKeyLeak: answerKeyLeak ? 1 : 0,
      pathLeak: pathLeak ? 1 : 0,
      productionFeatureEnabledOnlyByQuery: window.__OCR_TEST_SHEET_ENABLED__ === true,
      source: hook.getCurrentPayload()?.source || '',
    };
  })()`);
  await captureScreenshot(finalScreenshotPath);

  await writeResult({
    ok: true,
    blocked: false,
    prep,
    fileState,
    routeSnapshot,
    initialState,
    confirmationState,
    partialFillState,
    deletionState,
    finalState,
  });
  await call('Browser.close').catch(() => {});
  try {
    if (ws && ws.readyState === WebSocket.OPEN) ws.close();
  } catch {}
  process.exit(0);
}

main().catch(async error => {
  try {
    await writeResult({ ok: false, blocked: false, error: String(error && error.stack || error) });
  } catch {}
  try {
    if (ws && ws.readyState === WebSocket.OPEN) ws.close();
  } catch {}
  process.exit(1);
});
