const fs = require('fs');
const vm = require('vm');

const STUDENT_JS_PATH = 'C:/server/static/js/student.js';
const source = fs.readFileSync(STUDENT_JS_PATH, 'utf8');
const modalMarker = "const CT = { 'Content-Type': 'application/json' };";
const markerIndex = source.lastIndexOf(modalMarker);
if (markerIndex < 0) throw new Error('test submit modal IIFE marker not found');
const iifeStart = source.lastIndexOf('(() => {', markerIndex);
if (iifeStart < 0) throw new Error('test submit modal IIFE start not found');

function makeElement(id = '') {
  return {
    id,
    style: {},
    dataset: {},
    children: [],
    listeners: {},
    hidden: false,
    disabled: false,
    value: '',
    files: [],
    className: '',
    textContent: '',
    innerHTML: '',
    selectionStart: 0,
    selectionEnd: 0,
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    replaceChildren(...nodes) { this.children = [...nodes]; },
    addEventListener(type, handler) { this.listeners[type] = handler; },
    setAttribute(name, value) { this[name] = String(value); },
    removeAttribute(name) { delete this[name]; },
    focus() {},
    setSelectionRange(start, end) {
      this.selectionStart = start;
      this.selectionEnd = end;
    },
    scrollIntoView() {},
    dispatchEvent() { return true; },
  };
}

function defaultAssignedTests() {
  return [{
    id: 't_unit_daesu_01_lv3_r1',
    sourceId: 't_unit_daesu_01_lv3',
    name: '\uc9c0\uc218 1',
    label: '\uc9c0\uc218 1 Lv.3',
    curriculum: '\ub300\uc218',
    round: '1',
    difficulty: 'Lv.3',
  }];
}

function createDeferred() {
  let resolve;
  const promise = new Promise(next => { resolve = next; });
  return { promise, resolve };
}

function createContext(assignedTests = defaultAssignedTests(), options = {}) {
  const ids = new Map();
  const getElement = id => {
    if (!ids.has(id)) ids.set(id, makeElement(id));
    return ids.get(id);
  };

  [
    'openTestSubmit',
    'testSubmitModal',
    'tsClose',
    'tsSubmit',
    'tsType',
    'tsTestId',
    'tsRound',
    'tsAnswersText',
    'tsMemo',
    'tsInfo',
    'tsAnswerLinkArea',
    'tsOcrReviewImage',
    'tsOcrReviewOpen',
    'tsOcrStatus',
    'tsOcrReviewPanel',
  ].forEach(getElement);
  getElement('stuName').textContent = '\uac15\uaddc\ud604 (\ubbf8\uc801\ubd842)';

  const documentStub = {
    body: makeElement('body'),
    head: makeElement('head'),
    createElement: () => makeElement(),
    getElementById: getElement,
  };
  documentStub.body.insertAdjacentHTML = () => {};

  const testsConfig = {
    categories: {
      UNIT: {
        label: '\ub2e8\uc6d0\ud3c9\uac00',
        tests: [
          {
            id: 't_unit_mijeok_dummy_r1',
            sourceId: 't_unit_mijeok_dummy',
            name: '\ubbf8\uc801\ubd84 \ub354\ubbf8',
            curriculum: '\ubbf8\uc801\ubd842',
            categoryKey: 'UNIT',
            categoryLabel: '\ub2e8\uc6d0\ud3c9\uac00',
            problems: 20,
            difficulty: 'Lv.3',
            round: '1',
            answerKeys: { '1': Array(20).fill('1') },
          },
          {
            id: 't_unit_daesu_01_lv3_r1',
            sourceId: 't_unit_daesu_01_lv3',
            name: '\uc9c0\uc218 1',
            curriculum: '\ub300\uc218',
            categoryKey: 'UNIT',
            categoryLabel: '\ub2e8\uc6d0\ud3c9\uac00',
            problems: 20,
            difficulty: 'Lv.3',
            round: '1',
            answerKeys: { '1': Array(20).fill('1') },
          },
        ],
      },
    },
  };
  const fetchCalls = [];
  const testsConfigGate = options.deferTestsConfig ? createDeferred() : null;
  const context = {
    window: {
      __OCR_TEST_SHEET_ENABLED__: true,
      __STU_SID__: '\uac15\uaddc\ud604849',
      __ASSIGNED_TESTS__: assignedTests,
      __STUDENT_ACCESS__: {},
    },
    document: documentStub,
    location: { pathname: '/student/%EA%B0%95%EA%B7%9C%ED%98%84849', search: '?ocr=1' },
    localStorage: { setItem() {}, getItem() { return null; } },
    console,
    setTimeout,
    clearTimeout,
    Event: class Event {
      constructor(type, init = {}) {
        this.type = type;
        this.bubbles = Boolean(init.bubbles);
      }
    },
    fetch: async (url, options = {}) => {
      const path = String(url || '');
      fetchCalls.push({ path, body: options.body || '' });
      if (path.includes('/api/submit-test')) {
        throw new Error('/api/submit-test must not be called while opening the modal');
      }
      return {
        ok: true,
        text: async () => {
          if (testsConfigGate) await testsConfigGate.promise;
          return JSON.stringify(testsConfig);
        },
        json: async () => {
          if (testsConfigGate) await testsConfigGate.promise;
          return testsConfig;
        },
      };
    },
    alert: message => { throw new Error(`unexpected alert: ${message}`); },
    __fetchCalls: fetchCalls,
    __releaseTestsConfig: () => { if (testsConfigGate) testsConfigGate.resolve(); },
  };
  context.window.window = context.window;
  context.window.document = documentStub;
  context.window.localStorage = context.localStorage;
  context.window.location = context.location;
  context.window.setTimeout = setTimeout;
  context.window.Event = context.Event;
  context.window.alert = context.alert;
  return context;
}

async function flush() {
  await Promise.resolve();
  await new Promise(resolve => setTimeout(resolve, 0));
}

async function loadModalContext(assignedTests = defaultAssignedTests(), options = {}) {
  const context = createContext(assignedTests, options);
  const code = `
window.__OCR_TEST_SHEET_ENABLED__ = true;
window.__STU_SID__ = '\\uac15\\uaddc\\ud604849';
const OCR_PHASE1_ALLOWED_TEST_IDS = new Set(['t_unit_daesu_01_lv3_r1', 't_unit_daesu_02_lv3_r1', 't_unit_mijeok1_01_lv3_r1']);
function isOcrPhase1AllowedTestId(testId) {
  const normalized = String(testId || '').trim();
  return OCR_PHASE1_ALLOWED_TEST_IDS.has(normalized) || /^t_unit_[a-z0-9_]+_r[123]$/i.test(normalized) || /^t_training_pack_[a-z0-9_]+_r[12]$/i.test(normalized);
}
function isOcrPhase1AllowedTest(test) {
  const testId = test?.id || test?.testId;
  if (isOcrPhase1AllowedTestId(testId)) return true;
  const categoryKey = String(test?.categoryKey || test?.category || '').trim().toUpperCase();
  const categoryLabel = String(test?.categoryLabel || test?.label || '').trim();
  const problems = Number(test?.problems);
  const trainingPackLike = categoryKey === 'TRAINING_PACK' || categoryLabel.includes('트레이닝팩') || categoryLabel.includes('트팩');
  const unitLike = categoryKey === 'UNIT' || categoryLabel.includes('단원') || trainingPackLike;
  const roundMatch = String(test?.round || '').trim().match(trainingPackLike ? /^([12])(?:\\D|$)/ : /^([123])(?:\\D|$)/);
  const twentyProblems = !Number.isFinite(problems) || problems === 20;
  return unitLike && twentyProblems && Boolean(roundMatch);
}
` + source.slice(iifeStart);

  vm.createContext(context);
  vm.runInContext(code, context, { filename: 'student.js' });
  if (!options.skipInitialFlush) await flush();
  return context;
}

async function verifyAssignedShortcut() {
  const context = await loadModalContext();

  const openButton = context.document.getElementById('openTestSubmit');
  if (typeof openButton.listeners.click !== 'function') throw new Error('open test submit listener missing');
  const hook = context.window.__OCR_PHASE2_REVIEW_TEST_HOOK__;
  if (!hook) throw new Error('Phase2 review test hook missing');
  if (typeof hook.getAssignedCaptureStateForTest !== 'function') throw new Error('assigned capture state hook missing');
  if (typeof hook.startAssignedCaptureForTest !== 'function') throw new Error('assigned capture start hook missing');
  const assignedTest = context.window.__ASSIGNED_TESTS__[0];
  const beforeState = hook.getAssignedCaptureStateForTest(assignedTest);
  if (!beforeState.enabled || !beforeState.eligible || !beforeState.hasStartCapture) {
    throw new Error(`assigned OCR shortcut was not ready: ${JSON.stringify(beforeState)}`);
  }
  const shortcutOpened = hook.startAssignedCaptureForTest(assignedTest);
  if (shortcutOpened !== true) throw new Error(`assigned OCR shortcut returned ${shortcutOpened}`);
  await flush();

  const modal = context.document.getElementById('testSubmitModal');
  const type = context.document.getElementById('tsType');
  const testId = context.document.getElementById('tsTestId');
  const round = context.document.getElementById('tsRound');
  const info = context.document.getElementById('tsInfo');
  const ocrButton = context.document.getElementById('tsOcrReviewOpen');
  const submitCalls = context.__fetchCalls.filter(call => call.path.includes('/api/submit-test'));
  const reviewRouteCalls = context.__fetchCalls.filter(call => call.path.includes('/api/ocr-test-sheet-review'));

  if (modal.style.display !== 'flex') throw new Error(`modal did not open: ${modal.style.display}`);
  if (type.value !== 'UNIT') throw new Error(`expected UNIT type, got ${type.value}`);
  if (testId.value !== 't_unit_daesu_01_lv3_r1') throw new Error(`expected assigned daesu test, got ${testId.value}`);
  if (round.value !== '1') throw new Error(`expected round 1, got ${round.value}`);
  if ((info.textContent || '').includes('\uc624\ub298 \ubc30\uc815\ub41c \uc2dc\ud5d8\uc774 \uc5c6\uc2b5\ub2c8\ub2e4')) {
    throw new Error(`modal incorrectly reported no assignment: ${info.textContent}`);
  }
  if (ocrButton.hidden || ocrButton.disabled) {
    throw new Error(`OCR button should be available for allowlisted assignment: hidden=${ocrButton.hidden} disabled=${ocrButton.disabled}`);
  }
  if (submitCalls.length !== 0) throw new Error(`/api/submit-test was called ${submitCalls.length} time(s)`);
  if (reviewRouteCalls.length !== 0) throw new Error(`/api/ocr-test-sheet-review was called ${reviewRouteCalls.length} time(s)`);

  return {
    selectedTestId: testId.value,
    selectedRound: round.value,
    assignedOcrShortcutOpened: shortcutOpened,
    ocrButtonAvailable: true,
    submitTestCalls: submitCalls.length,
    ocrReviewRouteCalls: reviewRouteCalls.length,
  };
}

async function verifyOcrQaFallbackWithoutAssignedTests() {
  const context = await loadModalContext([]);
  const opened = context.window.openAssignedTestSubmit();
  await flush();
  const modal = context.document.getElementById('testSubmitModal');
  const testId = context.document.getElementById('tsTestId');
  const round = context.document.getElementById('tsRound');
  const ocrButton = context.document.getElementById('tsOcrReviewOpen');
  const submitCalls = context.__fetchCalls.filter(call => call.path.includes('/api/submit-test'));
  const reviewRouteCalls = context.__fetchCalls.filter(call => call.path.includes('/api/ocr-test-sheet-review'));

  if (opened !== true) throw new Error(`OCR QA fallback modal returned ${opened}`);
  if (modal.style.display !== 'flex') throw new Error(`OCR QA fallback modal did not open: ${modal.style.display}`);
  if (testId.value !== 't_unit_mijeok_dummy_r1') throw new Error(`OCR QA fallback selected ${testId.value}`);
  if (round.value !== '1') throw new Error(`OCR QA fallback round ${round.value}`);
  if (ocrButton.hidden || ocrButton.disabled) {
    throw new Error(`OCR QA fallback button unavailable: hidden=${ocrButton.hidden} disabled=${ocrButton.disabled}`);
  }
  if (submitCalls.length !== 0) throw new Error(`/api/submit-test was called ${submitCalls.length} time(s)`);
  if (reviewRouteCalls.length !== 0) throw new Error(`/api/ocr-test-sheet-review was called ${reviewRouteCalls.length} time(s)`);

  return {
    selectedTestId: testId.value,
    selectedRound: round.value,
    ocrButtonAvailable: true,
    submitTestCalls: submitCalls.length,
    ocrReviewRouteCalls: reviewRouteCalls.length,
  };
}

async function verifyOcrQaFallbackWithLateTestsConfig() {
  const context = await loadModalContext([], { deferTestsConfig: true, skipInitialFlush: true });
  const opened = context.window.openAssignedTestSubmit();
  await flush();

  const modal = context.document.getElementById('testSubmitModal');
  const testId = context.document.getElementById('tsTestId');
  const round = context.document.getElementById('tsRound');
  const ocrButton = context.document.getElementById('tsOcrReviewOpen');
  const beforeSelectedTestId = testId.value;

  if (opened !== true) throw new Error(`late tests-config OCR QA modal returned ${opened}`);
  if (modal.style.display !== 'flex') throw new Error(`late tests-config modal did not open: ${modal.style.display}`);

  context.__releaseTestsConfig();
  await flush();
  await flush();

  const submitCalls = context.__fetchCalls.filter(call => call.path.includes('/api/submit-test'));
  const reviewRouteCalls = context.__fetchCalls.filter(call => call.path.includes('/api/ocr-test-sheet-review'));

  if (testId.value !== 't_unit_mijeok_dummy_r1') {
    throw new Error(`late tests-config fallback selected ${testId.value || '(empty)'}`);
  }
  if (round.value !== '1') throw new Error(`late tests-config fallback round ${round.value}`);
  if (ocrButton.hidden || ocrButton.disabled) {
    throw new Error(`late tests-config OCR button unavailable: hidden=${ocrButton.hidden} disabled=${ocrButton.disabled}`);
  }
  if (submitCalls.length !== 0) throw new Error(`/api/submit-test was called ${submitCalls.length} time(s)`);
  if (reviewRouteCalls.length !== 0) throw new Error(`/api/ocr-test-sheet-review was called ${reviewRouteCalls.length} time(s)`);

  return {
    beforeSelectedTestId,
    selectedTestId: testId.value,
    selectedRound: round.value,
    ocrButtonAvailable: true,
    submitTestCalls: submitCalls.length,
    ocrReviewRouteCalls: reviewRouteCalls.length,
  };
}

function verifyStaticOcrQaButtonContract() {
  if (!/canOpenOcrQaSubmit/.test(source)) throw new Error('static OCR QA open button fallback missing');
  if (!/getAssignedTestsForSubmit\(\)[\s\S]*?allConfiguredTests\(\)/.test(source)) {
    throw new Error('static OCR QA assignment fallback missing');
  }
}

async function main() {
  verifyStaticOcrQaButtonContract();
  const assignedShortcut = await verifyAssignedShortcut();
  const noAssignedFallback = await verifyOcrQaFallbackWithoutAssignedTests();
  const lateTestsConfigFallback = await verifyOcrQaFallbackWithLateTestsConfig();

  console.log(JSON.stringify({
    ok: true,
    currentCurriculum: 'mijeok2',
    assignedTestCurriculum: 'daesu',
    assignedShortcut,
    noAssignedFallback,
    lateTestsConfigFallback,
    geminiCalls: 0,
  }, null, 2));
}

main().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
