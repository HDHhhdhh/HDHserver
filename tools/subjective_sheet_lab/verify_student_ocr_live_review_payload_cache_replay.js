const fs = require('fs');
const vm = require('vm');

const STUDENT_JS_PATH = 'C:/server/static/js/student.js';
const PAYLOAD_PATH = 'C:/server/tools/subjective_sheet_lab/gangyuhyun849_live_review_payload_cache_replay_20260703.json';
const ALLOWED_TEST_ID = 't_unit_daesu_01_lv3_r1';
const EXPECTED_REVIEW_QUESTIONS = [9, 14, 16, 17];
const CONFIRMED_REPLACEMENTS = new Map([[9, '3'], [14, '4'], [16, '1'], [17, '3']]);
const AUTO_CONFIRM_POLICY_VERSION = 'gemini_flash_lite_policy_d_boundary_v1';
const CROP_PREVIEW = 'data:image/png;base64,iVBORw0KGgo=';

function versionedAutoConfirmPayload(payload) {
  const normalized = JSON.parse(JSON.stringify(payload));
  normalized.auto_confirm_policy_version = AUTO_CONFIRM_POLICY_VERSION;
  normalized.items = normalized.items.map(item => {
    if (item.review_state === 'auto_confirm' || item.status !== 'safe_auto_grade') return item;
    const candidate = String(item.final_answer || item.recognized || '').trim();
    return {
      question_no: item.question_no,
      review_state: 'auto_confirm',
      candidate,
      warning: [],
      crop_preview: CROP_PREVIEW,
      allow_edit: true,
      requires_confirmation: false,
      retake_reason: '',
      recognized: candidate,
      candidates: [candidate],
      resolution: 'auto_confirm',
      final_answer: candidate,
      source: 'policy_backed_ui_fixture',
      auto_confirm_evidence: {
        policy_version: AUTO_CONFIRM_POLICY_VERSION,
        truth_used_by_gate: false,
        parser_pass: true,
        historical_agreement: true,
        model_confidence: 'high',
        original_confidence: 'high',
        enhanced_confidence: 'high',
        original_candidate: candidate,
        enhanced_candidate: candidate,
      },
    };
  });
  return normalized;
}

function makeElement(id = '') {
  return {
    id,
    style: {},
    dataset: {},
    children: [],
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
    addEventListener() {},
    setAttribute(name, value) { this[name] = String(value); },
    removeAttribute(name) { delete this[name]; },
    focus() {},
    setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
    scrollIntoView() {},
    dispatchEvent() { return true; },
    querySelector(selector) {
      const nodes = collectNodes(this);
      if (selector === '.ts-ocr-card') return nodes.find(node => node.className === 'ts-ocr-card') || null;
      const match = selector.match(/^\[data-question-no="(\d+)"\]$/);
      if (!match) return null;
      return nodes.find(node => node.dataset && node.dataset.questionNo === match[1]) || null;
    },
  };
}

function collectNodes(node, out = []) {
  if (!node || typeof node !== 'object') return out;
  out.push(node);
  if (Array.isArray(node.children)) node.children.forEach(child => collectNodes(child, out));
  return out;
}

function collectByClass(node, className) {
  return collectNodes(node).filter(item => item.className === className);
}

function createContext() {
  const ids = new Map();
  const getElement = id => {
    if (!ids.has(id)) ids.set(id, makeElement(id));
    return ids.get(id);
  };
  [
    'openTestSubmit', 'testSubmitModal', 'tsClose', 'tsSubmit', 'tsType',
    'tsTestId', 'tsRound', 'tsAnswersText', 'tsMemo', 'tsInfo',
    'tsAnswerLinkArea', 'tsOcrReviewImage', 'tsOcrReviewOpen',
    'tsOcrStatus', 'tsOcrReviewPanel',
  ].forEach(getElement);
  getElement('tsTestId').value = ALLOWED_TEST_ID;
  getElement('tsRound').value = '1';
  getElement('stuName').textContent = '\uac15\uaddc\ud604849';
  const documentStub = {
    body: makeElement('body'),
    head: makeElement('head'),
    createElement: () => makeElement(),
    getElementById: getElement,
  };
  documentStub.body.insertAdjacentHTML = () => {};
  const fetchCalls = [];
  const context = {
    window: {
      __OCR_TEST_SHEET_ENABLED__: true,
      __STU_SID__: '\uac15\uaddc\ud604849',
      __ASSIGNED_TESTS__: [{ id: ALLOWED_TEST_ID, name: 'test', round: '1' }],
      __STUDENT_ACCESS__: {},
    },
    document: documentStub,
    location: { pathname: '/student/\uac15\uaddc\ud604849', search: '?ocr=1' },
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
      const value = String(url || '');
      fetchCalls.push(value);
      if (value.includes('/api/submit-test')) throw new Error('submit-test must not be called');
      return { ok: true, json: async () => ({ categories: {} }), text: async () => '{}' };
    },
    alert: message => { throw new Error(`unexpected alert: ${message}`); },
    __fetchCalls: fetchCalls,
  };
  context.window.window = context.window;
  context.window.document = documentStub;
  context.window.localStorage = context.localStorage;
  context.window.location = context.location;
  context.window.setTimeout = setTimeout;
  context.window.Event = context.Event;
  return context;
}

function loadHook() {
  const source = fs.readFileSync(STUDENT_JS_PATH, 'utf8');
  const markerIndex = source.lastIndexOf("const CT = { 'Content-Type': 'application/json' };");
  if (markerIndex < 0) throw new Error('test submit modal marker not found');
  const iifeStart = source.lastIndexOf('(() => {', markerIndex);
  if (iifeStart < 0) throw new Error('test submit modal IIFE start not found');
  const context = createContext();
  const prelude = `
window.__OCR_TEST_SHEET_ENABLED__ = true;
const OCR_PHASE1_ALLOWED_TEST_IDS = new Set(['${ALLOWED_TEST_ID}']);
function isOcrPhase1AllowedTestId(testId) {
  return OCR_PHASE1_ALLOWED_TEST_IDS.has(String(testId || '').trim());
}
`;
  vm.createContext(context);
  vm.runInContext(prelude + source.slice(iifeStart), context, { filename: 'student.js' });
  const hook = context.window.__OCR_PHASE2_REVIEW_TEST_HOOK__ || context.window.__OCR_PHASE1_TEST_HOOK__;
  if (!hook) throw new Error('OCR test hook missing');
  return { hook, context };
}

function fixedPayload(payload) {
  return versionedAutoConfirmPayload({
    ...payload,
    items: payload.items.map(item => {
      if (!CONFIRMED_REPLACEMENTS.has(item.question_no)) return item;
      const finalAnswer = CONFIRMED_REPLACEMENTS.get(item.question_no);
      return {
        ...item,
        status: 'safe_auto_grade',
        recognized: finalAnswer,
        warnings: [],
        final_answer: finalAnswer,
        source: 'safe_auto_grade',
      };
    }),
  });
}

function reviewQuestionsFrom(panel) {
  return collectByClass(panel, 'ts-ocr-card')
    .map(card => Number(card.dataset.questionNo))
    .sort((left, right) => left - right);
}

function assertSameQuestions(actual, expected) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`reviewed questions ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`);
  }
}

function main() {
  const payloadWrapper = JSON.parse(fs.readFileSync(PAYLOAD_PATH, 'utf8'));
  const payload = versionedAutoConfirmPayload(payloadWrapper.review_payload);
  const { hook, context } = loadHook();
  const panel = hook.renderPayloadForTest(payload);
  const reviewedQuestions = reviewQuestionsFrom(panel);
  assertSameQuestions(reviewedQuestions, EXPECTED_REVIEW_QUESTIONS);
  const partialLines = hook.convertToAnswersText(payload).split('\n');
  const blankBeforeConfirmation = partialLines
    .map((line, index) => line ? null : index + 1)
    .filter(questionNo => questionNo !== null);
  if (partialLines.length !== 20) {
    throw new Error('unconfirmed review payload should still produce 20 answer lines');
  }
  if (partialLines.filter(Boolean).length !== 16) {
    throw new Error('unconfirmed review payload should partially fill 16 safe answers');
  }
  if (JSON.stringify(blankBeforeConfirmation) !== JSON.stringify(EXPECTED_REVIEW_QUESTIONS)) {
    throw new Error(`blank questions before confirmation ${JSON.stringify(blankBeforeConfirmation)} != ${JSON.stringify(EXPECTED_REVIEW_QUESTIONS)}`);
  }
  const fixed = fixedPayload(payload);
  const lines = hook.convertToAnswersText(fixed).split('\n');
  if (lines.length !== 20 || lines.some(line => !line)) throw new Error('fixed payload did not produce 20 non-empty lines');
  for (const [questionNo, expectedValue] of CONFIRMED_REPLACEMENTS) {
    if (lines[questionNo - 1] !== expectedValue) {
      throw new Error(`q${String(questionNo).padStart(3, '0')} expected line value ${expectedValue}, got ${lines[questionNo - 1]}`);
    }
  }
  hook.applyAnswersTextForTest(fixed);
  const state = hook.getAnswersTextState();
  if (state.value.split('\n').length !== 20) throw new Error('answersText was not filled with 20 lines');
  if (context.__fetchCalls.some(url => url.includes('/api/submit-test'))) throw new Error('/api/submit-test was called');
  console.log(JSON.stringify({
    ok: true,
    reviewCardCount: reviewedQuestions.length,
    reviewedQuestions,
    confirmedLineValues: Object.fromEntries(EXPECTED_REVIEW_QUESTIONS.map(questionNo => [questionNo, lines[questionNo - 1]])),
    partialFillBeforeConfirmation: true,
    partialFilledLineCount: partialLines.filter(Boolean).length,
    blankBeforeConfirmationQuestions: blankBeforeConfirmation,
    answersTextLineCount: lines.length,
    submitTestCalls: 0,
    tsSubmitClicks: 0,
    geminiCalls: 0,
  }, null, 2));
}

main();
