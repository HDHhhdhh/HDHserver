#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const DEFAULT_SHELL = path.join(ROOT, 'static', 'student.html');
const REQUIRED_IDS = [
  'previousVideos',
  'previousVideosToggle',
  'previousVideosPanel',
  'previousVideosRegister',
  'previousVidList',
  'previousVideosSummary',
];
const EXISTING_IDS = ['playerBox', 'player', 'vidList'];
const EXPECTED_TOGGLE_LABEL = '영상 복습';
const OLD_DISCLOSURE_LABEL = ['이전', '영상', '열람'].join(' ');
const EXPECTED_REGISTER_LABEL = '\uC601\uC0C1 \uB4F1\uB85D';
const REVIEW_SUMMARY_FORBIDDEN_COPY = /\uC644\uB8CC|\uC2DC\uCCAD\s*\uC911\uB2E8?|\uCC28\uC2DC\s*\d+/;

const VOID_TAGS = new Set([
  'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
  'meta', 'param', 'source', 'track', 'wbr',
]);

function parseAttributes(raw) {
  const attrs = new Map();
  const attrPattern = /([:\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
  let match;
  while ((match = attrPattern.exec(raw))) {
    const name = match[1].toLowerCase();
    if (!attrs.has(name)) attrs.set(name, match[2] ?? match[3] ?? match[4] ?? '');
  }
  return attrs;
}

function parseHtml(source) {
  const elements = [];
  const stack = [];
  const tagPattern = /<!--[\s\S]*?-->|<\/?([a-z][\w:-]*)([^<>]*?)>/gi;
  let match;

  while ((match = tagPattern.exec(source))) {
    if (!match[1]) continue;
    const whole = match[0];
    const tagName = match[1].toLowerCase();
    const isClosing = whole.startsWith('</');
    if (isClosing) {
      for (let i = stack.length - 1; i >= 0; i -= 1) {
        if (stack[i].tagName === tagName) {
          const element = stack[i];
          element.closeStart = match.index;
          element.closeEnd = tagPattern.lastIndex;
          stack.length = i;
          break;
        }
      }
      continue;
    }

    const element = {
      tagName,
      attrs: parseAttributes(match[2] || ''),
      parent: stack[stack.length - 1] || null,
      start: match.index,
      openEnd: tagPattern.lastIndex,
      closeStart: null,
      closeEnd: null,
      children: [],
    };
    if (element.parent) element.parent.children.push(element);
    elements.push(element);
    const selfClosing = /\/\s*>$/.test(whole) || VOID_TAGS.has(tagName);
    if (!selfClosing) stack.push(element);
  }
  return elements;
}

function attr(element, name) {
  return element?.attrs.get(String(name).toLowerCase()) ?? null;
}

function hasAttr(element, name) {
  return element?.attrs.has(String(name).toLowerCase()) === true;
}

function idOf(element) {
  return attr(element, 'id');
}

function hasClass(element, className) {
  return String(attr(element, 'class') || '').split(/\s+/).includes(className);
}

function descendants(element) {
  const result = [];
  const visit = node => {
    for (const child of node.children || []) {
      result.push(child);
      visit(child);
    }
  };
  visit(element);
  return result;
}

function isDescendant(element, ancestor) {
  let current = element?.parent || null;
  while (current) {
    if (current === ancestor) return true;
    current = current.parent;
  }
  return false;
}

function textContent(element, source) {
  if (!element || element.closeStart === null) return '';
  return source.slice(element.openEnd, element.closeStart)
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<[^>]*>/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function getById(elements, id) {
  return elements.filter(element => idOf(element) === id);
}

function assert(condition, message, checks) {
  if (!condition) throw new Error(message);
  checks.push(message);
}

function runHtmlContract(filePath = DEFAULT_SHELL) {
  const source = fs.readFileSync(filePath, 'utf8');
  const elements = parseHtml(source);
  const checks = [];
  const byId = new Map();

  for (const element of elements) {
    const id = idOf(element);
    if (!id) continue;
    if (!byId.has(id)) byId.set(id, []);
    byId.get(id).push(element);
  }

  for (const id of [...REQUIRED_IDS, ...EXISTING_IDS]) {
    const matches = byId.get(id) || [];
    assert(matches.length === 1, `id #${id} must occur exactly once (found ${matches.length})`, checks);
  }
  for (const [id, matches] of byId.entries()) {
    assert(matches.length === 1, `document id #${id} must be unique (found ${matches.length})`, checks);
  }

  const wrapper = getById(elements, 'previousVideos')[0];
  const toggle = getById(elements, 'previousVideosToggle')[0];
  const panel = getById(elements, 'previousVideosPanel')[0];
  const register = getById(elements, 'previousVideosRegister')[0];
  const list = getById(elements, 'previousVidList')[0];
  const summary = getById(elements, 'previousVideosSummary')[0];
  const playerBox = getById(elements, 'playerBox')[0];
  const player = getById(elements, 'player')[0];
  const vidList = getById(elements, 'vidList')[0];
  const playlistWrap = elements.find(element => hasClass(element, 'playlist-wrap'));

  assert(wrapper.tagName === 'section' || wrapper.tagName === 'div' || wrapper.tagName === 'aside',
    '#previousVideos must be a semantic container element', checks);
  assert(hasClass(wrapper, 'previous-videos'), '#previousVideos must expose the .previous-videos styling hook', checks);
  assert(hasClass(toggle, 'previous-videos-toggle'), '#previousVideosToggle must expose the .previous-videos-toggle styling hook', checks);
  assert(hasClass(panel, 'previous-videos-panel'), '#previousVideosPanel must expose the .previous-videos-panel styling hook', checks);
  assert(hasClass(register, 'previous-videos-register'), '#previousVideosRegister must expose the .previous-videos-register styling hook', checks);
  assert(hasClass(list, 'previous-videos-list'), '#previousVidList must expose the .previous-videos-list styling hook', checks);
  assert(hasClass(summary, 'previous-videos-summary'), '#previousVideosSummary must expose the .previous-videos-summary styling hook', checks);
  assert(playlistWrap, '.playlist-wrap must exist for the previous-video footer', checks);
  assert(isDescendant(playlistWrap, playerBox), '.playlist-wrap must remain inside #playerBox', checks);
  assert(isDescendant(wrapper, playerBox), '#previousVideos must remain inside #playerBox', checks);
  assert(wrapper.parent === playlistWrap, '#previousVideos must be a direct child of .playlist-wrap', checks);
  assert(vidList.parent === playlistWrap, '#vidList must be a direct child of .playlist-wrap', checks);
  assert(wrapper.start > vidList.closeEnd, '#previousVideos source must follow #vidList', checks);
  const vidListIndex = playlistWrap.children.indexOf(vidList);
  const wrapperIndex = playlistWrap.children.indexOf(wrapper);
  assert(wrapperIndex === vidListIndex + 1,
    '#previousVideos must immediately follow #vidList in .playlist-wrap DOM order', checks);
  assert(isDescendant(toggle, wrapper), '#previousVideosToggle must be inside #previousVideos', checks);
  assert(isDescendant(panel, wrapper), '#previousVideosPanel must be inside #previousVideos', checks);
  assert(isDescendant(register, panel), '#previousVideosRegister must be inside the controlled panel', checks);
  assert(isDescendant(list, panel), '#previousVidList must be inside the controlled panel', checks);
  assert(isDescendant(summary, panel), '#previousVideosSummary must be inside the controlled panel', checks);

  assert(toggle.tagName === 'button', '#previousVideosToggle must use a native button', checks);
  assert(attr(toggle, 'type') === 'button', '#previousVideosToggle must declare type="button"', checks);
  assert(hasAttr(toggle, 'disabled'), '#previousVideosToggle must start disabled', checks);
  assert(attr(toggle, 'aria-expanded') === 'false', '#previousVideosToggle must start aria-expanded="false"', checks);
  assert(attr(toggle, 'aria-controls') === 'previousVideosPanel', '#previousVideosToggle must control #previousVideosPanel', checks);
  assert(register.tagName === 'button', '#previousVideosRegister must use a native button', checks);
  assert(attr(register, 'type') === 'button', '#previousVideosRegister must declare type="button"', checks);
  assert(hasAttr(register, 'disabled'), '#previousVideosRegister must start disabled', checks);
  assert(textContent(register, source) === EXPECTED_REGISTER_LABEL,
    `#previousVideosRegister must show the exact label ${JSON.stringify(EXPECTED_REGISTER_LABEL)}`, checks);
  const componentText = textContent(wrapper, source);
  assert(textContent(toggle, source) === EXPECTED_TOGGLE_LABEL,
    `#previousVideosToggle must show the exact label ${JSON.stringify(EXPECTED_TOGGLE_LABEL)}`, checks);
  assert(!componentText.includes(OLD_DISCLOSURE_LABEL),
    '#previousVideos component must not retain the old disclosure label', checks);

  assert(hasAttr(panel, 'hidden'), '#previousVideosPanel must start hidden', checks);
  assert(attr(summary, 'role') === 'status', '#previousVideosSummary must expose role="status"', checks);
  assert(attr(summary, 'aria-live') === 'polite', '#previousVideosSummary must expose aria-live="polite"', checks);
  assert(list.children.length === 0 && textContent(list, source) === '',
    '#previousVidList must start empty without placeholder rows', checks);

  assert(playerBox.tagName === 'div', '#playerBox existing hook must remain a div', checks);
  assert(player.tagName === 'iframe', '#player existing hook must remain the iframe player', checks);
  assert(vidList.tagName === 'ul', '#vidList existing hook must remain a ul playlist', checks);

  const componentElements = [wrapper, ...descendants(wrapper)];
  const inlineAttributes = componentElements.flatMap(element => [...element.attrs.keys()]
    .filter(name => name === 'style' || /^on/i.test(name)));
  assert(inlineAttributes.length === 0,
    `new previous-video shell cannot use inline style or event handlers (found ${inlineAttributes.join(', ') || 'none'})`, checks);
  const forbiddenMediaOrModal = componentElements.filter(element =>
    ['iframe', 'video', 'dialog'].includes(element.tagName)
    || attr(element, 'role') === 'dialog'
    || hasAttr(element, 'aria-modal'));
  assert(forbiddenMediaOrModal.length === 0,
    `new previous-video shell cannot introduce a second player or modal (found ${forbiddenMediaOrModal.length})`, checks);

  return {
    mode: 'html',
    file: path.relative(ROOT, filePath),
    checks,
    counts: Object.fromEntries([...REQUIRED_IDS, ...EXISTING_IDS].map(id => [id, (byId.get(id) || []).length])),
  };
}

function runStyleContract(filePath = path.join(ROOT, 'static', 'css', 'student.css')) {
  const source = fs.readFileSync(filePath, 'utf8');
  const checks = [];
  const rowBlock = source.match(/body\.student-page \.previous-video-row\s*\{([\s\S]*?)\}/);
  const checkboxBlock = source.match(/body\.student-page \.previous-video-row input\s*\{([\s\S]*?)\}/);
  const registerBlock = source.match(/body\.student-page \.previous-videos-register\s*\{([\s\S]*?)\}/);
  const titleBlock = source.match(/body\.student-page \.previous-video-title\s*\{([\s\S]*?)\}/);
  const titleToken = source.match(/--stu-review-title-size\s*:\s*([^;]+)\s*;/);
  assert(rowBlock, '.previous-video-row must have a scoped student-page rule', checks);
  assert(rowBlock && /display\s*:\s*flex\s*;/.test(rowBlock[1]),
    '.previous-video-row must remain a compact flex row', checks);
  assert(rowBlock && /min-height\s*:\s*var\(--stu-review-tap-min-height\)\s*;/.test(rowBlock[1]),
    '.previous-video-row must keep a 44px minimum target', checks);
  assert(rowBlock && /gap\s*:\s*var\(--stu-review-gap\)\s*;/.test(rowBlock[1]),
    '.previous-video-row must keep the checkbox/title token gap', checks);
  assert(rowBlock && /align-items\s*:\s*center\s*;/.test(rowBlock[1]),
    '.previous-video-row must vertically align checkbox and title', checks);
  assert(checkboxBlock && /width\s*:\s*18px\s*;/.test(checkboxBlock[1])
    && /height\s*:\s*18px\s*;/.test(checkboxBlock[1]),
  'review rows must use a visible native checkbox target', checks);
  assert(titleBlock, '.previous-video-title must have a scoped student-page rule', checks);
  assert(titleBlock && !/font-weight\s*:/.test(titleBlock[1])
    && !titleBlock[1].includes('var(--stu-review-control-weight)'),
  '.previous-video-title must inherit regular row typography instead of the heavy control weight', checks);
  assert(registerBlock && /justify-self\s*:\s*end\s*;/.test(registerBlock[1]),
    'register action must align to the panel edge', checks);
  assert(titleToken && titleToken[1].trim() === '13px',
    '--stu-review-title-size must keep the compact 13px admin-like title scale', checks);
  return {
    mode: 'style',
    file: path.relative(ROOT, filePath),
    checks,
  };
}

class FixtureClassList {
  constructor(owner) {
    this.owner = owner;
  }
  _tokens() {
    return new Set(String(this.owner.className || '').split(/\s+/).filter(Boolean));
  }
  _write(tokens) {
    this.owner.className = [...tokens].join(' ');
  }
  add(...names) {
    const tokens = this._tokens();
    names.forEach(name => tokens.add(name));
    this._write(tokens);
  }
  remove(...names) {
    const tokens = this._tokens();
    names.forEach(name => tokens.delete(name));
    this._write(tokens);
  }
  toggle(name, force) {
    const tokens = this._tokens();
    const next = force === undefined ? !tokens.has(name) : !!force;
    if (next) tokens.add(name); else tokens.delete(name);
    this._write(tokens);
    return next;
  }
  contains(name) {
    return this._tokens().has(name);
  }
}

class FixtureElement {
  constructor(tagName, ownerDocument) {
    this.tagName = String(tagName || 'div').toUpperCase();
    this.ownerDocument = ownerDocument;
    this.parentElement = null;
    this.children = [];
    this.attrs = new Map();
    this.dataset = {};
    this._text = '';
    this._innerHTML = '';
    this._className = '';
    this.classList = new FixtureClassList(this);
    this.listeners = new Map();
    this.style = {};
    this.hidden = false;
    this.disabled = false;
    this.value = '';
    this.checked = false;
    this.src = '';
  }
  get id() { return this.attrs.get('id') || ''; }
  set id(value) { this.setAttribute('id', value); }
  get type() { return this.getAttribute('type') || ''; }
  set type(value) { this.setAttribute('type', value); }
  get className() { return this._className; }
  set className(value) {
    this._className = String(value || '');
    if (this._className) this.attrs.set('class', this._className);
    else this.attrs.delete('class');
  }
  get textContent() {
    return this._text + this.children.map(child => child.textContent || '').join('');
  }
  set textContent(value) {
    this._text = String(value ?? '');
    this.children = [];
    this._innerHTML = '';
  }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(value) {
    this._innerHTML = String(value ?? '');
    this._text = '';
    this.children = [];
  }
  setAttribute(name, value) {
    const key = String(name).toLowerCase();
    const normalized = String(value ?? '');
    this.attrs.set(key, normalized);
    if (key === 'class') this._className = normalized;
    if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = normalized;
  }
  getAttribute(name) {
    const key = String(name).toLowerCase();
    if (this.attrs.has(key)) return this.attrs.get(key);
    if (key.startsWith('data-')) {
      const dataKey = key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      return this.dataset[dataKey] ?? null;
    }
    return null;
  }
  hasAttribute(name) { return this.attrs.has(String(name).toLowerCase()); }
  removeAttribute(name) {
    const key = String(name).toLowerCase();
    this.attrs.delete(key);
    if (key.startsWith('data-')) delete this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())];
  }
  appendChild(child) {
    if (child === undefined || child === null) return child;
    if (typeof child === 'string') {
      this._text += child;
      return child;
    }
    child.parentElement = this;
    this.children.push(child);
    return child;
  }
  append(...items) { items.forEach(item => this.appendChild(item)); }
  insertAdjacentElement(_position, element) { this.appendChild(element); return element; }
  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  }
  dispatchEvent(event) {
    const next = event || { type: 'click' };
    if (!next.target) next.target = this;
    next.preventDefault ||= (() => {});
    next.cancelBubble = next.cancelBubble === true;
    const originalStopPropagation = next.stopPropagation;
    next.stopPropagation = () => {
      next.cancelBubble = true;
      if (typeof originalStopPropagation === 'function') originalStopPropagation();
    };
    if (next.type === 'keydown' && (next.key === 'Enter' || next.key === ' ')) {
      this.click();
      return true;
    }
    for (const handler of this.listeners.get(next.type) || []) handler(next);
    if (next.type === 'click' && typeof this.onclick === 'function') this.onclick(next);
    if (next.type === 'click' && !next.cancelBubble && this.parentElement) {
      this.parentElement.dispatchEvent(next);
    }
    return true;
  }
  click() {
    if (this.disabled) return;
    if (this.tagName === 'INPUT' && this.type.toLowerCase() === 'checkbox') {
      this.checked = !this.checked;
      this.dispatchEvent({ type: 'click', target: this, preventDefault() {}, stopPropagation() {} });
      this.dispatchEvent({ type: 'change', target: this, preventDefault() {}, stopPropagation() {} });
      return;
    }
    this.dispatchEvent({ type: 'click', target: this, preventDefault() {}, stopPropagation() {} });
  }
  focus() { this.ownerDocument.activeElement = this; }
  contains(node) {
    if (node === this) return true;
    return this.children.some(child => child.contains(node));
  }
  closest(selector) {
    let current = this;
    while (current) {
      if (current.matches(selector)) return current;
      current = current.parentElement;
    }
    return null;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    const found = [];
    const visit = node => {
      for (const child of node.children) {
        if (child.matches(selector)) found.push(child);
        visit(child);
      }
    };
    visit(this);
    return found;
  }
  matches(selector) {
    const raw = String(selector || '').trim();
    if (!raw) return false;
    if (raw.startsWith('#')) return this.id === raw.slice(1);
    const classMatch = raw.match(/^\.([\w-]+)$/);
    if (classMatch) return this.classList.contains(classMatch[1]);
    const tagMatch = raw.match(/^([\w-]+)?(?:\[([^=\]]+)(?:=["']?([^\]"']+)["']?)?\])?$/);
    if (!tagMatch) return false;
    if (tagMatch[1] && this.tagName.toLowerCase() !== tagMatch[1].toLowerCase()) return false;
    if (!tagMatch[2]) return true;
    const value = this.getAttribute(tagMatch[2]);
    return value !== null && (tagMatch[3] === undefined || value === tagMatch[3]);
  }
}

class FixtureDocument {
  constructor() {
    this.body = new FixtureElement('body', this);
    this.head = new FixtureElement('head', this);
    this.activeElement = null;
    this.listeners = new Map();
  }
  createElement(tagName) { return new FixtureElement(tagName, this); }
  getElementById(id) {
    const target = String(id);
    return this.querySelector(`#${target}`);
  }
  querySelector(selector) {
    if (selector === 'body') return this.body;
    if (selector === 'head') return this.head;
    return this.body.querySelector(selector) || this.head.querySelector(selector);
  }
  querySelectorAll(selector) { return [...this.body.querySelectorAll(selector), ...this.head.querySelectorAll(selector)]; }
  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  }
}

function appendFixture(parent, tag, id, className) {
  const node = parent.ownerDocument.createElement(tag);
  if (id) node.id = id;
  if (className) node.className = className;
  parent.appendChild(node);
  return node;
}

function buildStudentFixtureDom() {
  const document = new FixtureDocument();
  const playerBox = appendFixture(document.body, 'div', 'playerBox');
  const playerCard = appendFixture(playerBox, 'article', '', 'player-card');
  appendFixture(playerCard, 'iframe', 'player');
  const playlist = appendFixture(playerBox, 'aside', '', 'playlist-wrap');
  appendFixture(playlist, 'h3');
  appendFixture(playlist, 'ul', 'vidList');
  const review = appendFixture(playlist, 'section', 'previousVideos', 'previous-videos');
  const toggle = appendFixture(review, 'button', 'previousVideosToggle', 'previous-videos-toggle');
  toggle.type = 'button';
  toggle.disabled = true;
  toggle.setAttribute('aria-expanded', 'false');
  toggle.setAttribute('aria-controls', 'previousVideosPanel');
  toggle.textContent = '영상 복습';
  const panel = appendFixture(review, 'div', 'previousVideosPanel', 'previous-videos-panel');
  panel.hidden = true;
  const summary = appendFixture(panel, 'p', 'previousVideosSummary', 'previous-videos-summary');
  summary.setAttribute('role', 'status');
  summary.setAttribute('aria-live', 'polite');
  const register = appendFixture(panel, 'button', 'previousVideosRegister', 'previous-videos-register');
  register.type = 'button';
  register.disabled = true;
  register.textContent = '\uC601\uC0C1 \uB4F1\uB85D';
  appendFixture(panel, 'ul', 'previousVidList', 'previous-videos-list');
  appendFixture(document.body, 'span', 'stuName');
  return document;
}

function makeResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => typeof body === 'string' ? body : JSON.stringify(body),
  };
}

function makeFixtureDateConstructor(isoDate) {
  const NativeDate = Date;
  const fixedEpoch = NativeDate.parse(`${isoDate}T12:00:00+09:00`);
  class FixtureDate extends NativeDate {
    constructor(...args) {
      super(...(args.length ? args : [fixedEpoch]));
    }
    static now() {
      return fixedEpoch;
    }
  }
  return FixtureDate;
}

function readStudentBootstrapSource() {
  const sourcePath = process.env.STUDENT_SOURCE_OVERRIDE
    ? path.resolve(process.env.STUDENT_SOURCE_OVERRIDE)
    : path.join(ROOT, 'static', 'js', 'student.js');
  const source = fs.readFileSync(sourcePath, 'utf8');
  const start = source.indexOf('(() => {', source.indexOf('window.todayLocalKey'));
  const end = source.indexOf('\n})();', start);
  if (start < 0 || end < 0) throw new Error('unable to isolate student bootstrap IIFE');
  return source.slice(0, end + '\n})();'.length);
}

async function runStudentFixture(options = {}) {
  const date = '2026-08-03';
  const fixtureDate = options.fixtureDate || date;
  const FixtureDate = makeFixtureDateConstructor(fixtureDate);
  const sid = '7';
  const document = buildStudentFixtureDom();
  const requestLog = [];
  const alerts = [];
  const storage = new Map(Object.entries(options.initialStorage || {}));
  const listeners = new Map();
  const student = { id: sid, name: '테스트 학생', curriculum: 'ALG', subCurriculum: 'A', day1: '월1' };
  const defaultBootstrap = {
    ok: true,
    students: [student],
    videos: options.videos || [],
    reviewVideos: options.reviewVideos,
    updates: { [date]: { [sid]: options.assignment || [] } },
    materials: {},
    assigns: { [sid]: [] },
    absent: { by_date: { [date]: options.absent || [] } },
    logs: { [date]: { [sid]: options.logEntry || {} } },
    academyAccessAllowed: options.academyAccessAllowed !== false,
    outsideAcademyBlocked: options.academyAccessAllowed === false,
    courseBlocked: options.courseBlocked === true,
    selfStudy: options.selfStudy !== false,
    ghostStudent: options.ghostStudent === true,
    academyOnlyMessage: '학원 Wi-Fi에서만 영상을 볼 수 있습니다.',
  };
  const bootstrap = options.bootstrap === undefined ? defaultBootstrap : options.bootstrap;
  const window = {
    __STU_SID__: sid,
    Date: FixtureDate,
    innerWidth: 1280,
    navigator: {},
    location: { pathname: `/student/${sid}`, search: '', hash: '', origin: 'http://localhost' },
    document,
    addEventListener(type, handler) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(handler);
    },
    dispatchEvent(event) {
      for (const handler of listeners.get(event.type) || []) handler(event);
    },
    postMessage() {},
  };
  const localStorage = {
    getItem(key) { return storage.has(String(key)) ? storage.get(String(key)) : null; },
    setItem(key, value) { storage.set(String(key), String(value)); },
    removeItem(key) { storage.delete(String(key)); },
  };
  const history = { replaceState() {} };
  const fetch = async (url, init = {}) => {
    const method = String(init.method || 'GET').toUpperCase();
    const target = String(url);
    requestLog.push({ url: target, method, body: init.body || null });
    if (target.startsWith('/api/student/bootstrap')) {
      const status = options.bootstrapStatus || 200;
      return makeResponse(bootstrap, status);
    }
    if (target.startsWith('/api/watch/latest')) return makeResponse({ watch: options.watch || {} });
    if (target.startsWith('/api/get-url')) return makeResponse('https://video.example.test/embed');
    if (target.startsWith('/api/watch')) return makeResponse({ ok: true });

    return makeResponse({});
  };
  const context = {
    window,
    document,
    location: window.location,
    localStorage,
    history,
    fetch,
    URL,
    URLSearchParams,
    decodeURIComponent,
    encodeURIComponent,
    Date: FixtureDate,
    Math,
    Number,
    String,
    Set,
    Map,
    Array,
    Object,
    JSON,
    Promise,
    console: { log() {}, warn() {}, error() {} },
    alert(message) { alerts.push(String(message)); },
    setTimeout() { return 1; },
    clearTimeout() {},
    setInterval() { return 1; },
    clearInterval() {},
  };
  vm.runInNewContext(readStudentBootstrapSource(), context, { filename: 'static/js/student.js' });
  await new Promise(resolve => setImmediate(resolve));
  await Promise.resolve();
  await new Promise(resolve => setImmediate(resolve));
  return { document, window, requestLog, alerts, storage, context, fixtureSelfStudy: bootstrap?.selfStudy };
}

function reviewRows(document) {
  return document.getElementById('previousVidList')?.querySelectorAll('label[data-mid]') || [];
}

function requestCount(log, prefix) {
  return log.filter(entry => entry.url.startsWith(prefix)).length;
}

function fixtureProgress(fixture, mid) {
  const key = `stu:7:watch:${String(mid || '').trim()}`;
  const raw = fixture.storage.get(key);
  return raw ? JSON.parse(raw) : null;
}

function assertNoPlaybackFields(element, label) {
  for (const field of ['href', 'src', 'data-url', 'data-playback-url', 'target']) {
    assert(element?.getAttribute(field) === null, `${label} must not expose ${field}`, []);
  }
}

function expectedReviewTitle(item) {
  const chapter = String(item?.chapter ?? '').trim();
  const title = String(item?.title || item?.name || '').trim();
  return `${chapter ? `${chapter}. ` : ''}${title || String(item?.mid || '')}`.trim();
}

function assertTitleOnlyReviewRows(rows, sourceItems, label = 'review rows') {
  const expectedByMid = new Map();
  for (const item of sourceItems) {
    const mid = String(item?.mid ?? '').trim();
    if (mid && !expectedByMid.has(mid)) expectedByMid.set(mid, expectedReviewTitle(item));
  }
  const forbiddenRowCopy = REVIEW_SUMMARY_FORBIDDEN_COPY;
  for (const row of rows) {
    const expected = expectedByMid.get(row.dataset.mid);
    assert(row.tagName === 'LABEL', `${label} must use semantic label rows`, []);
    const titleNodes = row.querySelectorAll('.previous-video-title');
    assert(titleNodes.length === 1, `${label} must expose exactly one visible title node per row`, []);
    const inputs = row.querySelectorAll('input[type="checkbox"]');
    assert(inputs.length === 1, `${label} must expose exactly one native checkbox per row`, []);
    assert(inputs[0].dataset.mid === row.dataset.mid && inputs[0].type === 'checkbox',
      `${label} checkbox must carry the normalized row MID`, []);
    assert(row.children.length === 2 && titleNodes[0] === row.children[1],
      `${label} must contain only a checkbox and title node`, []);
    assert(row.textContent === expected && titleNodes[0].textContent === expected,
      `${label} title text must be exactly the chapter-prefixed title`, []);
    assert(row.querySelectorAll('.previous-video-meta').length === 0,
      `${label} must not render previous-video metadata nodes`, []);
    assert(row.querySelectorAll('.previous-video-status').length === 0,
      `${label} must not render previous-video status nodes`, []);
    assert(!forbiddenRowCopy.test(row.textContent),
      `${label} must not render 차시 N, 완료, or 시청 중 row copy`, []);
  }
}


async function runDomContractCurrent() {
  const checks = [];
  const rowsFixture = [
    {
      mid: 'second-done-mid',
      title: 'Third lesson',
      chapter: '3',
      reviewStatus: 'done',
      exNum: { 하: '13' },
    },
    { mid: 'orange-mid', title: 'Second lesson', chapter: '2', reviewStatus: 'interrupted' },
    { mid: 'done-mid', title: 'First lesson', chapter: '1', reviewStatus: 'done' },
    { mid: 'second-done-mid', title: 'Third duplicate', reviewStatus: 'done' },
    { mid: 'wrong-status', title: 'Skipped lesson', reviewStatus: 'skip' },
    { mid: 'assigned-status', title: 'Assigned lesson', reviewStatus: 'assigned' },
    { mid: '   ', title: 'Missing MID', reviewStatus: 'done' },
    null,
  ];
  const source = readStudentBootstrapSource();
  for (const token of ['/api/updates/' + 'self-study', 'updateTodayAssignmentCache', 'isSelfStudyOnStudentDate']) {
    assert(!source.includes(token), `student registration flow must not contain ${token}`, checks);
  }

  const fixture = await runStudentFixture({ reviewVideos: rowsFixture });
  const toggle = fixture.document.getElementById('previousVideosToggle');
  const panel = fixture.document.getElementById('previousVideosPanel');
  const register = fixture.document.getElementById('previousVideosRegister');
  const wrapper = fixture.document.getElementById('previousVideos');
  const summary = fixture.document.getElementById('previousVideosSummary');
  const rows = reviewRows(fixture.document);
  assert(rows.length === 2
    && rows.map(row => row.dataset.mid).join('|') === 'done-mid|second-done-mid'
    && !rows.some(row => row.dataset.mid === 'orange-mid'),
  'chooser must render only deduped completed blue rows in ascending chapter order', checks);
  assertTitleOnlyReviewRows(rows, rowsFixture);
  assertNoPlaybackFields(rows.find(row => row.dataset.mid === 'done-mid'), 'review rows');
  assert(register?.disabled === true && register.hidden === false,
    'register must be visible but disabled until a new eligible checkbox is selected', checks);
  assert(summary.textContent === '등록할 영상은 체크하고, 등록 취소는 체크를 해제하세요',
    'chooser summary must explain local registration and cancellation', checks);
  assert(!REVIEW_SUMMARY_FORBIDDEN_COPY.test(summary.textContent),
    'review summary must not expose completion/interruption/chapter wording', checks);
  assert(toggle.textContent === '영상 복습 (2)' && toggle.disabled === false,
    'chooser must expose the count label and enable the toggle', checks);

  const beforeToggle = fixture.requestLog.length;
  toggle.click();
  assert(panel.hidden === false && toggle.getAttribute('aria-expanded') === 'true',
    'toggle must only open the controlled panel', checks);
  assert(fixture.requestLog.length === beforeToggle, 'toggle must not issue playback or watch requests', checks);
  toggle.dispatchEvent({ type: 'keydown', key: 'Enter' });
  toggle.dispatchEvent({ type: 'keydown', key: ' ' });
  assert(panel.hidden === false && toggle.getAttribute('aria-expanded') === 'true'
    && fixture.requestLog.length === beforeToggle,
  'keyboard disclosure activation must remain toggle-only with stable ARIA state', checks);

  const secondDone = rows.find(row => row.dataset.mid === 'second-done-mid');
  const reviewGetUrlBeforeRowClick = requestCount(fixture.requestLog, '/api/get-url');
  secondDone.click();
  secondDone.querySelector('.previous-video-title').click();
  assert(requestCount(fixture.requestLog, '/api/get-url') === reviewGetUrlBeforeRowClick,
    'chooser row/title clicks must never play or issue get-url requests', checks);
  secondDone.querySelector('input[type="checkbox"]').click();
  assert(register.disabled === false, 'register must enable when a fresh eligible checkbox is checked', checks);
  const requestCountBeforeRegistration = fixture.requestLog.length;
  register.click();
  await new Promise(resolve => setImmediate(resolve));
  assert(fixture.requestLog.length === requestCountBeforeRegistration,
    'local registration must not write or fetch a server assignment', checks);
  assert(register.disabled === true, 'register must disable after the checked MID is registered', checks);
  const registeredRows = reviewRows(fixture.document);
  assert(registeredRows.length === rows.length
    && registeredRows.map(row => row.dataset.mid).join('|') === rows.map(row => row.dataset.mid).join('|'),
  'registration must keep every fresh server review row visible', checks);
  const registeredSecondDoneCheckbox = registeredRows.find(row => row.dataset.mid === 'second-done-mid')
    ?.querySelector('input[type="checkbox"]');
  assert(registeredSecondDoneCheckbox?.checked === true && registeredSecondDoneCheckbox.disabled === false
    && String(registeredSecondDoneCheckbox.getAttribute('aria-label') || '').includes('등록 취소'),
  'registered chooser rows must stay checked and expose an accessible cancellation action', checks);
  const registeredMids = fixture.document.getElementById('vidList')
    .querySelectorAll('li[data-mid]').map(item => item.dataset.mid);
  assert(registeredMids.includes('second-done-mid'), 'registration must append the checked review MID to the playlist', checks);
  const registeredReviewItem = fixture.document.getElementById('vidList')
    .querySelectorAll('li[data-mid]')
    .find(item => item.dataset.mid === 'second-done-mid');
  const registeredReviewEssay = registeredReviewItem?.querySelector('.essay-badge');
  assert(registeredReviewEssay?.textContent === '[서술형 13번]',
    'registered review videos must show their level-specific subjective problem number', checks);
  const reviewStorageKey = 'student:review-playlist:7:2026-08-03';
  assert(fixture.storage.get(reviewStorageKey)
    && JSON.parse(fixture.storage.get(reviewStorageKey)).join('|') === 'second-done-mid',
  'registered review selection must persist under the SID/date-scoped localStorage key', checks);
  const cancellationRequestCount = fixture.requestLog.length;
  registeredSecondDoneCheckbox.click();
  await new Promise(resolve => setImmediate(resolve));
  const cancelledSecondDoneRow = reviewRows(fixture.document)
    .find(row => row.dataset.mid === 'second-done-mid');
  const cancelledSecondDoneCheckbox = cancelledSecondDoneRow?.querySelector('input[type="checkbox"]');
  const cancelledPlaylistMids = fixture.document.getElementById('vidList')
    .querySelectorAll('li[data-mid]').map(item => item.dataset.mid);
  assert(cancelledSecondDoneCheckbox?.checked === false && cancelledSecondDoneCheckbox.disabled === false
    && !cancelledPlaylistMids.includes('second-done-mid')
    && JSON.parse(fixture.storage.get(reviewStorageKey)).length === 0,
  'unchecking a registered review row must cancel the local registration and restore its chooser state', checks);
  assert(fixture.requestLog.length === cancellationRequestCount,
    'review cancellation must not fetch or write any server state', checks);
  cancelledSecondDoneCheckbox.click();
  assert(register.disabled === false,
    'a cancelled review row must be immediately selectable for registration again', checks);
  register.click();
  await new Promise(resolve => setImmediate(resolve));
  assert(fixture.document.getElementById('vidList').querySelectorAll('li[data-mid="second-done-mid"]').length === 1
    && JSON.parse(fixture.storage.get(reviewStorageKey)).join('|') === 'second-done-mid'
    && fixture.requestLog.length === cancellationRequestCount,
  'a cancelled review video must support clean local re-registration without server requests', checks);
  const registrationRequestCount = fixture.requestLog.length;
  register.click();
  await new Promise(resolve => setImmediate(resolve));
  assert(fixture.requestLog.length === registrationRequestCount,
    'repeated registration must be idempotent with no additional requests', checks);
  assert(fixture.document.getElementById('vidList').querySelectorAll('li[data-mid]').length === registeredMids.length,
    'repeated registration must not duplicate playlist rows', checks);

  const finishedAssignment = await runStudentFixture({
    assignment: { videos: ['assigned-mid', 'done-mid'], source: 'auto' },
    videos: [
      { mid: 'assigned-mid', title: 'Assigned today', chapter: '1' },
      {
        mid: 'done-mid',
        title: 'Finished today',
        chapter: '2',
        todayAutoAssignmentStatus: 'done',
      },
    ],
    reviewVideos: [],
    selfStudy: false,
    logEntry: { archived: true, done: true },
    initialStorage: {
      'stu:7:watch:done-mid': JSON.stringify({ last: 100, dur: 100, completed: true, updatedAt: 1 }),
    },
  });
  const finishedPlaylistMids = finishedAssignment.document.getElementById('vidList')
    .querySelectorAll('li[data-mid]').map(item => item.dataset.mid);
  const finishedRow = finishedAssignment.document.getElementById('vidList')
    .querySelector('li[data-mid="done-mid"]');
  assert(finishedPlaylistMids.join('|') === 'assigned-mid|done-mid'
    && finishedRow?.querySelector('.badge-done')?.textContent === '완료'
    && !reviewRows(finishedAssignment.document).some(row => row.dataset.mid === 'done-mid'),
  'a completed blue video from today automatic assignment must remain in the current playlist after class archival without review duplication', checks);

  const completingAssignment = await runStudentFixture({
    assignment: { videos: ['fresh-auto-mid'], source: 'auto' },
    videos: [{ mid: 'fresh-auto-mid', title: 'Completes now', chapter: '1' }],
    reviewVideos: [],
    selfStudy: false,
  });
  completingAssignment.window.dispatchEvent({
    type: 'message',
    source: completingAssignment.window,
    data: {
      type: 'kollus.progress',
      mid: 'fresh-auto-mid',
      currentTime: 95,
      duration: 100,
      ended: false,
    },
  });
  await new Promise(resolve => setImmediate(resolve));
  const completingRow = completingAssignment.document.getElementById('vidList')
    .querySelector('li[data-mid="fresh-auto-mid"]');
  assert(completingRow?.querySelector('.badge-done')?.textContent === '완료'
    && fixtureProgress(completingAssignment, 'fresh-auto-mid')?.completed === true,
  'an automatic video completed during playback must stay rendered and turn blue immediately', checks);

  const reopenedAssignment = await runStudentFixture({
    assignment: ['reopened-mid'],
    videos: [{ mid: 'reopened-mid', title: 'Reopened today', chapter: '3' }],
    reviewVideos: [],
    watch: {
      'reopened-mid': { last: 100, dur: 100, completed: true, updatedAt: 2 },
    },
    initialStorage: {
      'stu:7:watch:reopened-mid': JSON.stringify({ last: 100, dur: 100, completed: true, updatedAt: 1 }),
    },
  });
  const reopenedPlaylist = reopenedAssignment.document.getElementById('vidList')
    .querySelectorAll('li[data-mid]').map(item => item.dataset.mid);
  assert(reopenedPlaylist.join('|') === 'reopened-mid'
    && fixtureProgress(reopenedAssignment, 'reopened-mid') === null,
  'a server-authorized green assignment must clear stale completed watch cache and remain in the playlist', checks);

  const regular = await runStudentFixture({ selfStudy: false, reviewVideos: rowsFixture });
  const regularRows = reviewRows(regular.document);
  assert(regularRows.length === 2
    && regularRows[0].querySelector('input[type="checkbox"]')
    && regular.document.getElementById('previousVideosRegister').hidden === false,
  'regular days must expose the same checkbox chooser and registration control', checks);
  const selfStudy = await runStudentFixture({ selfStudy: true, reviewVideos: rowsFixture });
  const selfStudyRows = reviewRows(selfStudy.document);
  assert(selfStudyRows.length === regularRows.length
    && selfStudyRows.map(row => row.dataset.mid).join('|') === regularRows.map(row => row.dataset.mid).join('|'),
  'self-study days must use the same server review chooser contract', checks);

  const staleStorageKey = 'student:review-playlist:7:2026-08-03';
  const stale = await runStudentFixture({
    assignment: ['today-mid'],
    videos: [{ mid: 'today-mid', title: 'Today', chapter: '1' }],
    reviewVideos: [{ mid: 'fresh-mid', title: 'Fresh', chapter: '2', reviewStatus: 'done' }],
    initialStorage: { [staleStorageKey]: JSON.stringify(['stale-mid', 'fresh-mid', 'fresh-mid']) },
  });
  const stalePlaylistMids = stale.document.getElementById('vidList').querySelectorAll('li[data-mid]').map(item => item.dataset.mid);
  assert(stalePlaylistMids.join('|') === 'today-mid|fresh-mid',
    'fresh server review membership may append from localStorage even without today assignment', checks);
  assert(JSON.parse(stale.storage.get(staleStorageKey)).join('|') === 'fresh-mid',
    'localStorage-only or duplicate MIDs must be pruned against the fresh server review set', checks);

  const ordered = await runStudentFixture({
    assignment: ['today-mid'],
    videos: [{ mid: 'today-mid', title: 'Today', chapter: '1' }],
    reviewVideos: [
      { mid: 'first-mid', title: 'First', chapter: '2', reviewStatus: 'done' },
      { mid: 'second-mid', title: 'Second', chapter: '3', reviewStatus: 'done' },
    ],
  });
  const orderedRows = reviewRows(ordered.document);
  orderedRows.find(row => row.dataset.mid === 'second-mid').querySelector('input[type="checkbox"]').click();
  orderedRows.find(row => row.dataset.mid === 'first-mid').querySelector('input[type="checkbox"]').click();
  const orderedGetUrlBefore = requestCount(ordered.requestLog, '/api/get-url');
  const orderedRequestLogBefore = ordered.requestLog.length;
  ordered.document.getElementById('previousVideosRegister').click();
  await new Promise(resolve => setImmediate(resolve));
  const orderedPlaylistMids = ordered.document.getElementById('vidList').querySelectorAll('li[data-mid]').map(item => item.dataset.mid);
  assert(orderedPlaylistMids.join('|') === 'today-mid|second-mid|first-mid',
    'registration must append in checkbox selection order after today rows', checks);
  assert(ordered.requestLog.length === orderedRequestLogBefore
    && requestCount(ordered.requestLog, '/api/get-url') === orderedGetUrlBefore,
    'registration must preserve current autoplay state without a new playback request', checks);

  const noToday = await runStudentFixture({
    assignment: [],
    videos: [],
    reviewVideos: [{ mid: 'standalone-mid', title: 'Standalone', chapter: '4', reviewStatus: 'done' }],
  });
  const standaloneRow = reviewRows(noToday.document)[0];
  standaloneRow.querySelector('input[type="checkbox"]').click();
  const noTodayBefore = noToday.requestLog.length;
  noToday.document.getElementById('previousVideosRegister').click();
  await new Promise(resolve => setImmediate(resolve));
  const standalonePlaylist = noToday.document.getElementById('vidList').querySelectorAll('li[data-mid]');
  assert(standalonePlaylist.length === 1 && standalonePlaylist[0].dataset.mid === 'standalone-mid'
    && noToday.requestLog.length === noTodayBefore && requestCount(noToday.requestLog, '/api/get-url') === 0,
    'local registration must append a standalone review MID without server or playback requests', checks);

  const missing = await runStudentFixture({ videos: [{ mid: 'catalog-only', title: 'Catalog only' }], reviewVideos: [] });
  assert(missing.document.getElementById('previousVideos').hidden === false
    && missing.document.getElementById('previousVideosToggle').disabled === true
    && reviewRows(missing.document).length === 0,
  'empty reviewVideos must not synthesize membership from catalog or progress', checks);
  const malformed = await runStudentFixture({ reviewVideos: { mid: 'not-an-array', reviewStatus: 'done' } });
  assert(malformed.document.getElementById('previousVideos').hidden === true
    && reviewRows(malformed.document).length === 0,
  'malformed reviewVideos must hide the review surface', checks);
  const failedBootstrap = await runStudentFixture({
    bootstrapStatus: 404,
    reviewVideos: rowsFixture,
  });
  const retiredBootstrapPrefixes = [
    '/api/students',
    '/api/videos',
    '/api/updates',
    '/api/materials',
    '/api/mat-assign',
    '/api/absent',
    '/api/logs',
  ];
  assert(failedBootstrap.alerts.some(message => message.includes('데이터 로드 실패') && message.includes('bootstrap 404'))
    && retiredBootstrapPrefixes.every(prefix => requestCount(failedBootstrap.requestLog, prefix) === 0)
    && failedBootstrap.document.getElementById('previousVideosToggle').disabled === true
    && reviewRows(failedBootstrap.document).length === 0,
  'failed bootstrap must surface an error and never call the retired multi-GET fallback', checks);

  const outside = await runStudentFixture({
    academyAccessAllowed: false,
    reviewVideos: [{ mid: 'restricted-mid', title: 'Restricted', reviewStatus: 'done' }],
  });
  const outsideRow = outside.document.getElementById('previousVidList').querySelector('button[data-mid]');
  const outsideRegister = outside.document.getElementById('previousVideosRegister');
  const outsideBefore = outside.requestLog.length;
  outsideRow.click();
  assert(outsideRow.dataset.playbackRestricted === 'true'
    && outsideRegister.hidden === true && outsideRegister.disabled === true
    && outside.requestLog.length === outsideBefore
    && requestCount(outside.requestLog, '/api/get-url') === 0,
  'outside-academy review choices must remain title-only and non-actionable without playback or watch mutation', checks);

  for (const [label, options] of Object.entries({
    courseBlocked: { courseBlocked: true },
    absent: { absent: ['7'] },
    archived: { logEntry: { archived: true } },
    ghost: { ghostStudent: true },
  })) {
    const blocked = await runStudentFixture({ ...options, reviewVideos: rowsFixture });
    assert(blocked.document.getElementById('previousVideos').hidden === true
      && reviewRows(blocked.document).length === 0,
    `${label} review fixture must hide the review surface`, checks);
  }

  const active = await runStudentFixture({
    assignment: ['shared-mid'],
    videos: [{ mid: 'shared-mid', title: 'Today video', chapter: '1' }],
    reviewVideos: [{ mid: 'shared-mid', title: 'Review video', reviewStatus: 'done' }],
  });
  const currentItem = active.document.getElementById('vidList').querySelector('li[data-mid]');
  const reviewItem = reviewRows(active.document)[0];
  assert(currentItem?.classList.contains('active') && reviewItem?.classList.contains('is-active'),
    'current and review lists must share the active state after the existing first-video selection', checks);
  const activeGetUrlBefore = requestCount(active.requestLog, '/api/get-url');
  reviewItem.querySelector('input[type="checkbox"]').click();
  active.document.getElementById('previousVideosRegister').click();
  await new Promise(resolve => setImmediate(resolve));
  const activePlaylistItems = active.document.getElementById('vidList').querySelectorAll('li[data-mid="shared-mid"]');
  const activeCurrentItem = active.document.getElementById('vidList').querySelector('li[data-mid="shared-mid"]');
  const activeReviewItem = reviewRows(active.document).find(row => row.dataset.mid === 'shared-mid');
  assert(activePlaylistItems.length === 1
    && activeCurrentItem?.classList.contains('active')
    && activeReviewItem?.classList.contains('is-active')
    && activeReviewItem.getAttribute('aria-current') === 'true'
    && requestCount(active.requestLog, '/api/get-url') === activeGetUrlBefore,
  'registering a duplicate current MID must preserve today order, active state, and autoplay exactly once', checks);
  const duplicateCancellationRequests = active.requestLog.length;
  activeReviewItem.querySelector('input[type="checkbox"]').click();
  await new Promise(resolve => setImmediate(resolve));
  const activeAfterCancellation = active.document.getElementById('vidList')
    .querySelectorAll('li[data-mid="shared-mid"]');
  const activeReviewAfterCancellation = reviewRows(active.document)
    .find(row => row.dataset.mid === 'shared-mid');
  assert(activeAfterCancellation.length === 1
    && activeAfterCancellation[0].classList.contains('active')
    && activeReviewAfterCancellation?.querySelector('input[type="checkbox"]')?.checked === false
    && active.requestLog.length === duplicateCancellationRequests,
  'cancelling a duplicate review registration must preserve the active today assignment without playback requests', checks);

  const current = await runStudentFixture({
    assignment: ['current-mid'],
    videos: [{ mid: 'current-mid', title: 'Today video', chapter: '1' }],
    reviewVideos: [],
  });
  assert(requestCount(current.requestLog, '/api/get-url') === 1
    && current.document.getElementById('vidList').querySelector('li[data-mid]')?.classList.contains('active'),
  'today playlist must retain first-video auto-play and active ordering', checks);
  assert(wrapper && summary, 'review fixture hooks must remain mounted', checks);
  return {
    mode: 'dom',
    checks,
    rows: rows.map(row => row.dataset.mid),
    stored: JSON.parse(fixture.storage.get('student:review-playlist:7:2026-08-03')),
    orderedPlaylist: orderedPlaylistMids,
    todayAutoPlayGetUrlCount: requestCount(current.requestLog, '/api/get-url'),
  };
}

function parseArgs(argv) {
  const args = { mode: 'all', file: DEFAULT_SHELL };
  for (const value of argv) {
    if (value.startsWith('--contract=')) args.mode = value.slice('--contract='.length);
    if (value.startsWith('--file=')) args.file = path.resolve(process.cwd(), value.slice('--file='.length));
  }
  return args;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.mode === 'html') {
    const result = runHtmlContract(args.file);
    console.log(JSON.stringify(result, null, 2));
    console.log('student previous-video HTML contract ok');
    return;
  }
  if (args.mode === 'style') {
    const result = runStyleContract();
    console.log(JSON.stringify(result, null, 2));
    console.log('student previous-video style contract ok');
    return;
  }
  if (args.mode === 'all') {
    const html = runHtmlContract(args.file);
    console.log(JSON.stringify(html, null, 2));
    console.log('student previous-video HTML contract ok');
    const style = runStyleContract();
    console.log(JSON.stringify(style, null, 2));
    console.log('student previous-video style contract ok');
  }
  if (args.mode === 'dom' || args.mode === 'all') {
    return runDomContractCurrent().then(result => {
      console.log(JSON.stringify(result, null, 2));
      console.log('student previous-video DOM contract ok');
    });
  }
  throw new Error(`unsupported contract mode: ${args.mode}`);
}

if (require.main === module) {
  try {
    Promise.resolve(main()).catch(error => {
      console.error(`student previous-video DOM contract failed: ${error.message}`);
      process.exitCode = 1;
    });
  } catch (error) {
    console.error(`student previous-video HTML contract failed: ${error.message}`);
    process.exitCode = 1;
  }
}

module.exports = { parseHtml, runHtmlContract, runStyleContract, runDomContract: runDomContractCurrent, runStudentFixture };
