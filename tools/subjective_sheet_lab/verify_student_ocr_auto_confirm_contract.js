const fs = require('fs');
const vm = require('vm');
const {
  AUTO_CONFIRM_POLICY_VERSION,
  buildAutoConfirmReviewPayload,
} = require('./auto_confirm_review_payload_adapter');

const STUDENT_JS_PATH = 'C:/server/static/js/student.js';
const source = fs.readFileSync(STUDENT_JS_PATH, 'utf8');
const markerIndex = source.lastIndexOf("const CT = { 'Content-Type': 'application/json' };");
if (markerIndex < 0) throw new Error('test submit modal IIFE marker not found');
const iifeStart = source.lastIndexOf('(() => {', markerIndex);
if (iifeStart < 0) throw new Error('test submit modal IIFE start not found');

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function matchesSelector(node, selector) {
  if (!node || typeof node !== 'object') return false;
  if (selector === 'button') return node.tagName === 'BUTTON';
  const dataQuestion = selector.match(/^\[data-question-no="(\d+)"\]$/);
  if (dataQuestion) return node.dataset?.questionNo === dataQuestion[1];
  const focused = selector.match(/^\.([a-z0-9-]+)\[data-ocr-focus="true"\]$/i);
  if (focused) {
    return String(node.className || '').split(/\s+/).includes(focused[1]) && node.dataset?.ocrFocus === 'true';
  }
  if (selector.startsWith('.')) return String(node.className || '').split(/\s+/).includes(selector.slice(1));
  return false;
}

function findAll(node, selector, out = []) {
  if (matchesSelector(node, selector)) out.push(node);
  if (Array.isArray(node?.children)) node.children.forEach(child => findAll(child, selector, out));
  return out;
}

function makeElement(id = '', tagName = '') {
  return {
    id,
    tagName,
    style: {},
    dataset: {},
    children: [],
    listeners: {},
    hidden: false,
    disabled: false,
    readOnly: false,
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
    querySelector(selector) { return findAll(this, selector)[0] || null; },
    querySelectorAll(selector) { return findAll(this, selector); },
    focus() {},
    scrollIntoView() {},
    setSelectionRange(start, end) {
      this.selectionStart = start;
      this.selectionEnd = end;
    },
    dispatchEvent(event = {}) {
      const handler = this.listeners[event.type || 'input'];
      if (typeof handler === 'function') handler(event);
      return true;
    },
  };
}

function createContext(ocrEnabled = true) {
  const ids = new Map();
  const getElement = id => {
    if (!ids.has(id)) ids.set(id, makeElement(id));
    return ids.get(id);
  };
  [
    'openTestSubmit', 'testSubmitModal', 'tsClose', 'tsSubmit', 'tsType', 'tsTestId',
    'tsRound', 'tsAnswersText', 'tsMemo', 'tsInfo', 'tsAnswerLinkArea',
    'tsOcrReviewImage', 'tsOcrReviewOpen', 'tsOcrStatus', 'tsOcrReviewPanel', 'stuName',
  ].forEach(getElement);
  getElement('tsType').value = 'UNIT';
  getElement('tsTestId').value = 't_unit_daesu_01_lv3_r1';
  getElement('tsRound').value = '1';
  getElement('stuName').textContent = 'pilot';
  let insertedHtml = '';
  const fetchCalls = [];
  const documentStub = {
    body: makeElement('body', 'BODY'),
    head: makeElement('head', 'HEAD'),
    createElement: tag => makeElement('', String(tag || '').toUpperCase()),
    getElementById: getElement,
  };
  documentStub.body.insertAdjacentHTML = (_position, html) => { insertedHtml += String(html || ''); };
  const testsConfig = {
    categories: {
      UNIT: {
        label: 'UNIT',
        tests: [{
          id: 't_unit_daesu_01_lv3_r1',
          name: 'Daesu 01',
          problems: 20,
          round: '1',
        }],
      },
    },
  };
  const context = {
    window: {
      __OCR_TEST_SHEET_ENABLED__: ocrEnabled,
      __STU_SID__: 'pilot',
      __ASSIGNED_TESTS__: [{ id: 't_unit_daesu_01_lv3_r1', name: 'Daesu 01', round: '1' }],
      __STUDENT_ACCESS__: {},
    },
    document: documentStub,
    location: { pathname: '/student/pilot', search: ocrEnabled ? '?ocr=1' : '' },
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
    DataTransfer: class DataTransfer {
      constructor() {
        this.items = { add() {} };
        this.files = [];
      }
    },
    fetch: async url => {
      const path = String(url || '');
      fetchCalls.push(path);
      if (path.includes('/api/submit-test')) throw new Error('submit-test must stay at zero');
      if (path.includes('/api/ocr-test-sheet')) throw new Error('OCR routes must stay at zero');
      return { ok: true, json: async () => testsConfig, text: async () => JSON.stringify(testsConfig) };
    },
    alert: () => {},
    __fetchCalls: fetchCalls,
    __insertedHtml: () => insertedHtml,
  };
  context.window.window = context.window;
  context.window.document = context.document;
  context.window.location = context.location;
  context.window.localStorage = context.localStorage;
  context.window.setTimeout = setTimeout;
  context.window.Event = context.Event;
  context.window.DataTransfer = context.DataTransfer;
  return context;
}

function loadHook(ocrEnabled = true) {
  const context = createContext(ocrEnabled);
  const prelude = `
window.__OCR_TEST_SHEET_ENABLED__ = ${ocrEnabled ? 'true' : 'false'};
const OCR_PHASE1_ALLOWED_TEST_IDS = new Set(['t_unit_daesu_01_lv3_r1']);
function isOcrPhase1AllowedTestId(testId) {
  return OCR_PHASE1_ALLOWED_TEST_IDS.has(String(testId || '').trim());
}
`;
  vm.createContext(context);
  vm.runInContext(prelude + source.slice(iifeStart), context, { filename: 'student.js' });
  return { context, hook: context.window.__OCR_PHASE2_REVIEW_TEST_HOOK__ };
}

function buildPayload() {
  const cropPreview = 'data:image/png;base64,iVBORw0KGgo=';
  const items = Array.from({ length: 20 }, (_unused, index) => {
    const questionNo = index + 1;
    if (questionNo === 2) {
      return { question_no: questionNo, review_state: 'review_recommended', candidate: '1', crop_preview: cropPreview };
    }
    if (questionNo === 3) {
      return { question_no: questionNo, review_state: 'direct_input', candidate: '', crop_preview: cropPreview };
    }
    if (questionNo === 4) {
      return { question_no: questionNo, review_state: 'retake_required', candidate: '', crop_preview: cropPreview, retake_reason: 'blur' };
    }
    return { question_no: questionNo, review_state: 'auto_confirm', candidate: '1', crop_preview: cropPreview };
  });
  return buildAutoConfirmReviewPayload({
    testId: 't_unit_daesu_01_lv3_r1',
    round: '1',
    items,
  });
}

function assertVersionedAutoConfirm(hook, context, payload) {
  if (hook.getAutoConfirmPolicyVersionForTest() !== AUTO_CONFIRM_POLICY_VERSION) {
    throw new Error('UI policy version does not match the lab adapter');
  }
  const panel = hook.renderPayloadForTest(payload);
  const current = hook.getCurrentPayload();
  const autoItems = current.items.filter(item => item.resolution === 'auto_confirm');
  if (autoItems.length !== 17) throw new Error(`expected 17 auto-confirm items, got ${autoItems.length}`);
  const answers = hook.getAnswersTextState();
  const lines = answers.value.split('\n');
  if (lines.length !== 20) throw new Error(`expected 20 answer lines, got ${lines.length}`);
  if (lines.filter(Boolean).length !== 17) throw new Error('only versioned auto-confirm items may auto-fill');
  if (context.document.getElementById('tsAnswersText').readOnly) throw new Error('auto-filled textarea must remain editable');
  if (findAll(panel, '.ts-ocr-state-summary').length !== 1) throw new Error('self-review summary is missing');
  const guard = hook.getSubmitGuardStateForTest('t_unit_daesu_01_lv3_r1', '1');
  if (guard.blocked || !guard.requiresConfirmation || guard.questionNumbers.join(',') !== '2,3,4') {
    throw new Error(`unresolved submit readiness mismatch: ${JSON.stringify(guard)}`);
  }
  const blankState = hook.getBlankAnswerStateForTest(lines.join('\n'), 20);
  if (blankState.blocked || !blankState.requiresConfirmation || blankState.questionNumbers.join(',') !== '2,3,4') {
    throw new Error(`blank-answer readiness mismatch: ${JSON.stringify(blankState)}`);
  }
  const requestText = hook.serializeAnswersTextForSubmitForTest(lines.join('\n'), 20);
  if (requestText.split('\n').length !== 17 || /^(2|3|4):/m.test(requestText)) {
    throw new Error(`blank positions were not omitted safely from the numbered request: ${requestText}`);
  }
  const emptyState = hook.getBlankAnswerStateForTest('', 20);
  if (emptyState.count !== 20 || hook.serializeAnswersTextForSubmitForTest('', 20) !== '') {
    throw new Error('fully blank answer sheet is not submit-ready');
  }
  if (hook.answerCountValidationMessage('', 20) || hook.answerCountValidationMessage('1\n\n3', 20)) {
    throw new Error('blank or partial answer sheet is still rejected by answer-count validation');
  }

  const editedLines = [...lines];
  editedLines[0] = '2';
  hook.setAnswersTextForTest(editedLines.join('\n'));
  const edited = hook.getCurrentPayload().items[0];
  if (edited.resolution !== 'student_edited' || edited.final_answer !== '2') {
    throw new Error('editing an auto-confirmed answer did not preserve the student edit');
  }
}

function assertFailClosedContracts(hook, payload) {
  const unversioned = clone(payload);
  delete unversioned.auto_confirm_policy_version;
  const unversionedResult = hook.validateActionablePayloadForTest(unversioned);
  if (unversionedResult.items.some(item => item.resolution === 'auto_confirm')) {
    throw new Error('unversioned auto-confirm payload was accepted');
  }
  if (unversionedResult.items.filter(item => item.review_state === 'review_recommended').length < 18) {
    throw new Error('unversioned candidates were not downgraded to review');
  }

  const legacy = {
    source: 'historical_cache',
    test_id: 't_unit_daesu_01_lv3_r1',
    round: '1',
    problem_count: 20,
    items: Array.from({ length: 20 }, (_unused, index) => ({
      question_no: index + 1,
      status: 'safe_auto_grade',
      recognized: '1',
      warnings: [],
      candidates: [],
      final_answer: '1',
      source: 'safe_auto_grade',
    })),
  };
  const legacyResult = hook.validateActionablePayloadForTest(legacy);
  if (legacyResult.items.some(item => item.resolution === 'auto_confirm')) {
    throw new Error('historical safe_auto_grade cache was relabeled as auto-confirm');
  }
}

function assertSubmitHandlerWiring() {
  const handlerIndex = source.indexOf("btnSubmit?.addEventListener('click'");
  const guardIndex = source.indexOf('ocrReviewSubmissionBlockState(', handlerIndex);
  const blankStateIndex = source.indexOf('submitBlankAnswerState(', handlerIndex);
  const confirmIndex = source.indexOf('window.confirm(', handlerIndex);
  const serializerIndex = source.indexOf('submitAnswersTextForRequest(', handlerIndex);
  const submitFetchIndex = source.indexOf("fetch('/api/submit-test'", handlerIndex);
  if ([handlerIndex, guardIndex, blankStateIndex, confirmIndex, serializerIndex, submitFetchIndex].some(index => index < 0)) {
    throw new Error('submit handler blank-answer wiring is incomplete');
  }
  if (!(guardIndex < blankStateIndex && blankStateIndex < confirmIndex && confirmIndex < serializerIndex && serializerIndex < submitFetchIndex)) {
    throw new Error('submit handler does not confirm blanks and serialize positions before submit fetch');
  }
  if (!source.slice(serializerIndex, submitFetchIndex + 800).includes('answersText: requestAnswersText')) {
    throw new Error('submit request does not use the position-preserving answer serialization');
  }
  for (const name of ['ocrReviewRender', 'ocrReviewRenderReviewCard', 'ocrReviewRenderBlockedCard', 'ocrReviewRenderSafeAutoList']) {
    const count = (source.match(new RegExp(`function ${name}\\(`, 'g')) || []).length;
    if (count !== 1) throw new Error(`${name} must have exactly one active declaration, got ${count}`);
  }
}

function main() {
  const payload = buildPayload();
  const { hook, context } = loadHook(true);
  if (!hook) throw new Error('hidden OCR hook is missing');
  assertVersionedAutoConfirm(hook, context, payload);
  assertFailClosedContracts(hook, payload);
  assertSubmitHandlerWiring();

  const featureOff = loadHook(false);
  if (featureOff.hook) throw new Error('feature-off page exposed the OCR hook');
  if (featureOff.context.__insertedHtml().includes('tsOcrReviewPanel')) throw new Error('feature-off page exposed OCR markup');

  const forbiddenCalls = context.__fetchCalls.filter(path =>
    path.includes('/api/submit-test') || path.includes('/api/ocr-test-sheet'));
  if (forbiddenCalls.length) throw new Error(`forbidden route calls: ${forbiddenCalls.join(',')}`);
  console.log(JSON.stringify({
    ok: true,
    policyVersion: AUTO_CONFIRM_POLICY_VERSION,
    autoConfirmCount: 17,
    answerLineCount: 20,
    filledCount: 17,
    blankCount: 3,
    unresolvedSubmitAllowedWithConfirmation: true,
    blankSheetSubmitAllowedWithConfirmation: true,
    blankPositionSerialization: 'numbered_non_empty_answers',
    legacyAutoConfirmCount: 0,
    providerCalls: 0,
    ocrRouteCalls: 0,
    submitTestCalls: 0,
    tsSubmitClicks: 0,
    productionDefault: 'NO-GO',
  }, null, 2));
}

main();
