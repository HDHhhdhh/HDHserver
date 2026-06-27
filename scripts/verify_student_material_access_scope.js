const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const sourcePath = path.join(root, 'static', 'js', 'student.js');
const source = fs.readFileSync(sourcePath, 'utf8');

const BLOCK_MESSAGE = '영상 재생과 테스트 답지는 학원 Wi-Fi에서만 볼 수 있습니다.';
const SID = 'browser-qa-student';
const MATERIAL_URL = '/files/browser-qa/material.pdf';

class ClassList {
  constructor(owner) {
    this.owner = owner;
    this.values = new Set();
  }

  add(...names) {
    names.filter(Boolean).forEach(name => this.values.add(String(name)));
    this.owner._className = Array.from(this.values).join(' ');
  }

  remove(...names) {
    names.forEach(name => this.values.delete(String(name)));
    this.owner._className = Array.from(this.values).join(' ');
  }

  contains(name) {
    return this.values.has(String(name));
  }

  toggle(name, force) {
    const key = String(name);
    const next = force === undefined ? !this.values.has(key) : !!force;
    if (next) this.values.add(key);
    else this.values.delete(key);
    this.owner._className = Array.from(this.values).join(' ');
    return next;
  }

  setFromString(value) {
    this.values = new Set(String(value || '').split(/\s+/).filter(Boolean));
    this.owner._className = Array.from(this.values).join(' ');
  }
}

function dataAttrToKey(name) {
  return String(name || '').replace(/^data-/, '').replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
}

function dataKeyToAttr(name) {
  return String(name || '').replace(/[A-Z]/g, ch => `-${ch.toLowerCase()}`);
}

class Element {
  constructor(tagName, documentRef) {
    this.tagName = String(tagName || '').toUpperCase();
    this.nodeName = this.tagName;
    this.ownerDocument = documentRef;
    this.parentNode = null;
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.classList = new ClassList(this);
    this._className = '';
    this._textContent = '';
    this.hidden = false;
    this.value = '';
    this.checked = false;
  }

  set id(value) {
    this.setAttribute('id', value);
  }

  get id() {
    return this.attributes.get('id') || '';
  }

  set className(value) {
    this.classList.setFromString(value);
  }

  get className() {
    return this._className;
  }

  set textContent(value) {
    this._textContent = String(value || '');
    this.children = [];
  }

  get textContent() {
    return [this._textContent, ...this.children.map(child => child.textContent)].join('');
  }

  set innerText(value) {
    this.textContent = value;
  }

  get innerText() {
    const parts = [];
    if (this._textContent) parts.push(this._textContent);
    this.children.forEach(child => {
      const text = child.innerText;
      if (text) parts.push(text);
    });
    return parts.join('\n');
  }

  set innerHTML(value) {
    this.children = [];
    this._textContent = '';
    this.appendElementsFromHtml(value);
  }

  appendElementsFromHtml(value) {
    const html = String(value || '');
    const idRegex = /<([a-zA-Z0-9-]+)([^>]*)\sid=["']([^"']+)["'][^>]*>/g;
    let match;
    while ((match = idRegex.exec(html))) {
      const child = this.ownerDocument.createElement(match[1]);
      child.setAttribute('id', match[3]);
      const classMatch = match[2].match(/\sclass=["']([^"']+)["']/);
      if (classMatch) child.className = classMatch[1];
      const typeMatch = match[2].match(/\stype=["']([^"']+)["']/);
      if (typeMatch) child.setAttribute('type', typeMatch[1]);
      this.appendChild(child);
    }
  }

  get innerHTML() {
    return this.innerText;
  }

  setAttribute(name, value) {
    const key = String(name);
    const text = String(value);
    this.attributes.set(key, text);
    if (key === 'id') this.ownerDocument.registerId(text, this);
    if (key === 'class') this.className = text;
    if (key.startsWith('data-')) this.dataset[dataAttrToKey(key)] = text;
    if (key === 'href') this.href = text;
    if (key === 'download') this.download = text;
    if (key === 'type') this.type = text;
  }

  getAttribute(name) {
    const key = String(name);
    if (key.startsWith('data-')) return this.dataset[dataAttrToKey(key)] ?? null;
    if (key === 'class') return this.className || null;
    if (key === 'href') return this.href ?? null;
    if (key === 'download') return this.download ?? null;
    return this.attributes.has(key) ? this.attributes.get(key) : null;
  }

  removeAttribute(name) {
    const key = String(name);
    this.attributes.delete(key);
    if (key.startsWith('data-')) delete this.dataset[dataAttrToKey(key)];
  }

  append(...items) {
    items.forEach(item => {
      if (typeof item === 'string') {
        const text = this.ownerDocument.createElement('#text');
        text.textContent = item;
        this.appendChild(text);
      } else if (item) {
        this.appendChild(item);
      }
    });
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    this.ownerDocument.registerTree(child);
    return child;
  }

  insertAdjacentElement(_position, element) {
    if (!this.parentNode) return this.appendChild(element);
    const siblings = this.parentNode.children;
    const index = siblings.indexOf(this);
    element.parentNode = this.parentNode;
    siblings.splice(index < 0 ? siblings.length : index, 0, element);
    this.ownerDocument.registerTree(element);
    return element;
  }

  insertAdjacentHTML(_position, html) {
    this.appendElementsFromHtml(html);
  }

  addEventListener(type, listener) {
    const key = String(type);
    if (!this.listeners.has(key)) this.listeners.set(key, []);
    this.listeners.get(key).push(listener);
  }

  dispatchEvent(event) {
    const evt = event || {};
    evt.target = evt.target || this;
    evt.currentTarget = this;
    evt.defaultPrevented = false;
    evt.propagationStopped = false;
    evt.preventDefault = evt.preventDefault || function preventDefault() { this.defaultPrevented = true; };
    evt.stopPropagation = evt.stopPropagation || function stopPropagation() { this.propagationStopped = true; };

    const listeners = this.listeners.get(evt.type) || [];
    listeners.forEach(listener => listener.call(this, evt));
    const handler = this[`on${evt.type}`];
    if (typeof handler === 'function') handler.call(this, evt);
    if (!evt.propagationStopped && this.parentNode) this.parentNode.dispatchEvent(evt);
    return !evt.defaultPrevented;
  }

  click() {
    return this.dispatchEvent({ type: 'click', target: this });
  }

  closest(selector) {
    let cur = this;
    while (cur) {
      if (matchesSelector(cur, selector)) return cur;
      cur = cur.parentNode;
    }
    return null;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    return querySelectorAllFrom(this.children, selector);
  }
}

function matchesSelector(element, selector) {
  const raw = String(selector || '').trim();
  if (!raw || !element) return false;
  if (raw.startsWith('#')) return element.id === raw.slice(1);
  if (raw.startsWith('.')) return element.classList.contains(raw.slice(1));

  const attrMatch = raw.match(/^([a-zA-Z0-9#._-]+)?\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\]$/);
  if (attrMatch) {
    const tag = attrMatch[1] || '';
    const attr = attrMatch[2];
    const expected = attrMatch[3];
    if (tag && !matchesSelector(element, tag)) return false;
    const actual = attr.startsWith('data-')
      ? element.dataset[dataAttrToKey(attr)]
      : element.getAttribute(attr);
    if (expected === undefined) return actual !== undefined && actual !== null;
    return String(actual) === expected;
  }

  if (raw.includes('.')) {
    const [tag, className] = raw.split('.', 2);
    return matchesSelector(element, tag) && element.classList.contains(className);
  }

  return element.tagName.toLowerCase() === raw.toLowerCase();
}

function collectDescendants(nodes, out = []) {
  nodes.forEach(node => {
    out.push(node);
    collectDescendants(node.children || [], out);
  });
  return out;
}

function querySelectorAllFrom(nodes, selector) {
  const parts = String(selector || '').trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return [];
  let current = collectDescendants(nodes);
  for (const part of parts) {
    current = current.filter(node => matchesSelector(node, part));
    if (part !== parts[parts.length - 1]) {
      current = current.flatMap(node => collectDescendants(node.children || []));
    }
  }
  return current;
}

class DocumentStub {
  constructor() {
    this.ids = new Map();
    this.documentElement = new Element('html', this);
    this.head = new Element('head', this);
    this.body = new Element('body', this);
    this.documentElement.append(this.head, this.body);
  }

  createElement(tagName) {
    return new Element(tagName, this);
  }

  registerId(id, element) {
    if (id) this.ids.set(String(id), element);
  }

  registerTree(element) {
    if (element.id) this.registerId(element.id, element);
    (element.children || []).forEach(child => this.registerTree(child));
  }

  getElementById(id) {
    return this.ids.get(String(id)) || null;
  }

  querySelector(selector) {
    if (selector === 'head') return this.head;
    if (selector === 'body') return this.body;
    return this.documentElement.querySelector(selector);
  }

  querySelectorAll(selector) {
    return this.documentElement.querySelectorAll(selector);
  }

  addEventListener() {}
}

function makeResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  };
}

function createBaseDocument() {
  const document = new DocumentStub();
  [
    'clock',
    'noticeBtn',
    'noticeBadge',
    'setBtn',
    'setPanel',
    'darkToggle',
    'feedbackBox',
    'submitFeedback',
    'goLogin',
    'stuName',
    'openTestSubmit',
    'studentHomeworkPanel',
    'studentHomeworkBooks',
    'player',
    'vidList',
    'assignedTestsPanel',
    'assignedTestList',
    'matList',
  ].forEach(id => {
    const tag = id === 'player' ? 'iframe' : id.endsWith('List') || id === 'vidList' ? 'ul' : 'div';
    const element = document.createElement(tag);
    element.id = id;
    document.body.appendChild(element);
  });
  return document;
}

async function main() {
  const alerts = [];
  const document = createBaseDocument();
  const storage = new Map();
  const location = {
    pathname: `/student/${SID}`,
    search: '',
    hash: '',
    protocol: 'http:',
    origin: 'http://127.0.0.1:8003',
    href: `http://127.0.0.1:8003/student/${SID}`,
    replace(next) {
      this.href = next;
    },
  };
  const bootstrap = {
    ok: true,
    date: '2026-06-27',
    students: [{ id: SID, name: '브라우저검증', curriculum: '대수', level: '중', day1: '토1' }],
    student: { id: SID, name: '브라우저검증', curriculum: '대수', level: '중', day1: '토1' },
    videos: [{ mid: 'qa-video-1', title: '제한 영상', curriculum: '대수', chapter: 1 }],
    updates: { '2026-06-27': { [SID]: ['qa-video-1'] } },
    materials: { 'mat-1': { title: '모바일 다운로드 확인.pdf', url: MATERIAL_URL } },
    assigns: { [SID]: ['mat-1'] },
    absent: { by_date: { '2026-06-27': [] }, by_student: {} },
    logs: { '2026-06-27': {} },
    assignedTests: [{
      id: 'qa-test-1',
      name: '제한 테스트',
      categoryLabel: '단원평가',
      status: 'assigned',
      answerUrl: 'https://drive.google.com/file/d/example/view',
      answerRestricted: true,
    }],
    homeworkBooks: [],
    academyAccessAllowed: false,
    outsideAcademyBlocked: true,
    networkBlocked: true,
    academyOnlyMessage: BLOCK_MESSAGE,
  };

  const context = {
    window: {},
    document,
    location,
    history: { replaceState() {} },
    navigator: { userAgent: 'KAKAOTALK verifier' },
    localStorage: {
      getItem: key => storage.get(String(key)) || null,
      setItem: (key, value) => storage.set(String(key), String(value)),
      removeItem: key => storage.delete(String(key)),
    },
    alert: message => alerts.push(String(message)),
    fetch: async url => {
      const text = String(url);
      if (text.startsWith('/api/student/bootstrap')) return makeResponse(bootstrap);
      if (text.startsWith('/api/watch/latest')) return makeResponse({ ok: true, watch: {} });
      if (text.startsWith('/api/get-url')) return makeResponse('academy network required', 403);
      return makeResponse({});
    },
    console,
    URL,
    URLSearchParams,
    Date,
    Map,
    Set,
    Promise,
    JSON,
    Math,
    Number,
    String,
    Array,
    Object,
    RegExp,
    decodeURIComponent,
    encodeURIComponent,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval: () => {},
    CustomEvent: function CustomEvent(type, init = {}) { return { type, ...init }; },
    CSS: { escape: value => String(value) },
  };
  context.window = context;
  context.window.addEventListener = () => {};
  context.window.dispatchEvent = () => {};
  context.window.postMessage = () => {};
  context.window.open = () => null;

  vm.createContext(context);
  vm.runInContext(source, context, { filename: 'static/js/student.js' });
  await new Promise(resolve => setTimeout(resolve, 50));

  if (alerts.length) {
    throw new Error(`student page showed academy alert on load: ${JSON.stringify(alerts)}`);
  }

  for (let i = 0; i < 2; i += 1) {
    const folder = document.getElementById('matList').querySelector('li[data-type="dir"]');
    if (!folder) throw new Error(`material folder level ${i + 1} did not render`);
    folder.click();
  }

  const materialLink = document.getElementById('matList').querySelector('a');
  if (!materialLink) throw new Error('material download link did not render');
  if (materialLink.href !== MATERIAL_URL) {
    throw new Error(`material link href changed: ${materialLink.href}`);
  }
  if (materialLink.download !== '') {
    throw new Error(`material link download attribute changed: ${JSON.stringify(materialLink.download)}`);
  }
  if (alerts.length) {
    throw new Error(`material navigation showed academy alert: ${JSON.stringify(alerts)}`);
  }

  const videoRow = document.getElementById('vidList').querySelector('li[data-mid]');
  if (!videoRow) throw new Error('restricted video row did not render');
  videoRow.click();
  if (!alerts.includes(BLOCK_MESSAGE)) {
    throw new Error(`restricted video click did not show academy alert: ${JSON.stringify(alerts)}`);
  }

  const beforeTestClick = alerts.length;
  const testButton = document.getElementById('assignedTestList').querySelector('.assigned-test-btn');
  if (!testButton) throw new Error('restricted assigned-test button did not render');
  testButton.click();
  if (alerts.length !== beforeTestClick + 1 || alerts[alerts.length - 1] !== BLOCK_MESSAGE) {
    throw new Error(`restricted test click did not show academy alert: ${JSON.stringify(alerts)}`);
  }

  console.log('student material access runtime contract ok');
}

main().catch(error => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
