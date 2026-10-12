import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createHash } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { fileURLToPath } from 'node:url';
import {
  searchKeyForText,
  matchesSearchKey,
  applySearchPlaceholder,
} from '../static/js/shared/search.js';
import { nextVideoId } from '../static/js/shared/videoIds.js';
import {
  parseYouTubeUrl,
  GICHUL_COURSE,
} from '../static/js/shared/videoSources.js';
import {
  buildVideoCorrectionDraft,
  protectedVideoIdentityChanges,
  videoCorrectionSummary,
} from '../static/js/shared/videoCatalogIdentity.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const hash = value => createHash('sha256').update(value).digest('hex');

function parseOptions(argv) {
  const options = {
    source: 'static/js/video-manage.js',
    before: null,
    sizes: [50],
    bench: false,
    warmup: 5,
    samples: 30,
    expectOptimized: false,
  };

  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (key === '--bench') {
      options.bench = true;
    } else if (key === '--expect-optimized') {
      options.expectOptimized = true;
    } else if (
      ['--source', '--before', '--sizes', '--warmup', '--samples'].includes(key)
    ) {
      const value = argv[++i];
      assert.ok(value && !value.startsWith('--'), 'missing value for ' + key);
      if (key === '--source') options.source = value;
      else if (key === '--before') options.before = value;
      else if (key === '--sizes') options.sizes = value.split(',').map(Number);
      else options[key.slice(2)] = Number(value);
    } else {
      throw new Error('unknown option: ' + key);
    }
  }

  assert.ok(
    options.sizes.length &&
      options.sizes.every(n => Number.isInteger(n) && n >= 3),
    '--sizes requires comma-separated integers >= 3',
  );
  assert.ok(Number.isInteger(options.warmup) && options.warmup >= 0);
  assert.ok(Number.isInteger(options.samples) && options.samples >= 1);
  return options;
}

function readSource(label, file) {
  const absolute = path.resolve(ROOT, file);
  const raw = fs.readFileSync(absolute);
  const source = raw.toString('utf8').replaceAll('\r\n', '\n');
  assert.ok(
    source.includes('function drawVid() {'),
    'expected real video-manage entrypoint',
  );
  return { label, path: absolute, hash: hash(raw), source };
}

function syntheticRows(count) {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    mid: 'synthetic-' + (i + 1),
    curriculum: '기하',
    subCurriculum: 'APEX',
    chapter: i + 1,
    title:
      '합성 기하 영상 ' +
      (i + 1) +
      (i === count - 1 ? ' 대상마지막' : ''),
    url:
      'https://v.kr.kollus.com/player?mid=synthetic-' +
      (i + 1) +
      '&token=fixture',
    exNum: { 상: 3, 중: 2, 하: 1 },
    unknown: { keep: [i + 1, '보존'], extra: true },
  }));
}

function makeHarness(source, fixture, { youtube = true } = {}) {
  const clone = value => JSON.parse(JSON.stringify(value));
  const freshMetrics = () => ({
    draws: 0,
    fullSyncs: 0,
    rowSyncs: 0,
    rowEnumerations: 0,
    rowReads: 0,
    innerTextReads: 0,
    urlParses: 0,
    providerParses: 0,
    searchKeys: 0,
    listenerBinds: 0,
    stringifyCalls: 0,
    stringifyMs: 0,
    stringifyBytes: 0,
    correctionSummaries: 0,
    correctionSummaryMs: 0,
  });

  let metrics = freshMetrics();
  let now = 0;
  let timerId = 0;
  let serverRows = clone(fixture);
  let confirm = true;

  const timers = new Map();
  const elements = new Map();
  const posts = [];
  const alerts = [];
  const downloads = [];
  const blobs = [];
  const logs = [];

  class Element {
    constructor(tag, id = '') {
      this.tagName = tag;
      this.id = id;
      this.parentElement = null;
      this.children = [];
      this.listeners = [];
      this.dataset = {};
      this.style = {};
      this.attributes = {};
      this.value = '';
      this._text = '';
      this._html = '';
      this.disabled = false;
      this.hidden = false;
      this.onclick = null;
      if (id) elements.set(id, this);
    }

    addEventListener(type, fn, capture = false) {
      this.listeners.push({
        type,
        fn,
        capture: Boolean(capture === true || capture?.capture),
      });
      metrics.listenerBinds++;
    }

    setAttribute(name, value) {
      this.attributes[name] = String(value);
    }

    focus() {
      document.activeElement = this;
    }

    matches(selector) {
      return (
        selector === 'td[contenteditable]' &&
        this.tagName === 'td' &&
        this.editable
      );
    }

    closest(selector) {
      let current = this;
      while (current) {
        if (selector === 'tr' && current.tagName === 'tr') return current;
        if (selector === '.delV' && current.className === 'delV') return current;
        current = current.parentElement;
      }
      return null;
    }

    appendChild(element) {
      if (element.parentElement) element.remove();
      element.parentElement = this;
      this.children.push(element);
      return element;
    }

    prepend(element) {
      element.parentElement = this;
      this.children.unshift(element);
    }

    remove() {
      const parent = this.parentElement;
      if (parent) parent.children = parent.children.filter(x => x !== this);
      this.parentElement = null;
    }

    get innerText() {
      metrics.innerTextReads++;
      return this._text;
    }

    set innerText(value) {
      this._text = String(value);
    }

    get textContent() {
      return this._text;
    }

    set textContent(value) {
      this._text = String(value);
    }

    get innerHTML() {
      return this._html;
    }

    set innerHTML(value) {
      this._html = String(value);
      this.children = [];

      if (this.id === 'vidTable') {
        for (const match of this._html.matchAll(
          /<tr([^>]*)>([\s\S]*?)<\/tr>/g,
        )) {
          const idx = match[1].match(/data-idx="(\d+)"/);
          if (!idx) continue;

          const tr = new Element('tr');
          tr.dataset.idx = idx[1];
          this.appendChild(tr);

          for (const cell of match[2].matchAll(
            /<td([^>]*)>([\s\S]*?)<\/td>/g,
          )) {
            const td = new Element('td');
            td.editable = /contenteditable/.test(cell[1]);
            td._text = cell[2]
              .replace(/<[^>]*>/g, '')
              .replaceAll('&amp;', '&')
              .trim();
            tr.appendChild(td);

            if (/class="delV"/.test(cell[2])) {
              const button = new Element('button');
              button.className = 'delV';
              td.appendChild(button);
            }
          }
        }
      } else {
        for (const match of this._html.matchAll(
          /<(select|input)[^>]*id="([^"]+)"[^>]*>/g,
        )) {
          const child = new Element(match[1], match[2]);
          this.appendChild(child);
        }
      }
    }

    querySelectorAll(selector) {
      const all = [];
      const walk = element => {
        element.children.forEach(child => {
          all.push(child);
          walk(child);
        });
      };
      walk(this);

      if (selector === '.delV') {
        return all.filter(element => element.className === 'delV');
      }
      if (selector === 'td[contenteditable]') {
        return all.filter(
          element => element.tagName === 'td' && element.editable,
        );
      }
      if (selector === 'tr[data-idx]') {
        return all.filter(
          element => element.tagName === 'tr' && 'idx' in element.dataset,
        );
      }
      return [];
    }

    dispatch(type, properties = {}) {
      const event = {
        type,
        target: this,
        key: '',
        isComposing: false,
        preventDefault() {},
        ...properties,
      };

      const ancestry = [];
      let parent = this.parentElement;
      while (parent) {
        ancestry.push(parent);
        parent = parent.parentElement;
      }

      for (const ancestor of ancestry.slice().reverse()) {
        for (const listener of ancestor.listeners.slice()) {
          if (listener.type === type && listener.capture) listener.fn(event);
        }
      }

      for (const listener of this.listeners.slice()) {
        if (listener.type === type) listener.fn(event);
      }

      if (type === 'click' && typeof this.onclick === 'function') {
        this.onclick(event);
      }

      if (type !== 'blur') {
        for (const ancestor of ancestry) {
          for (const listener of ancestor.listeners.slice()) {
            if (listener.type === type && !listener.capture) listener.fn(event);
          }
        }
      }
    }

    click() {
      if (this.disabled) return;
      if (this.tagName === 'a' && this.download) {
        downloads.push({ name: this.download, href: this.href });
        return;
      }
      this.dispatch('click');
    }
  }

  const document = {
    activeElement: null,
    getElementById: id => elements.get(id) || null,
    createElement: tag => new Element(tag),
    querySelectorAll: selector => {
      assert.equal(selector, '#vidTable tr[data-idx]');
      const rows = elements.get('vidTable').children;
      metrics.rowEnumerations++;
      metrics.rowReads += rows.length;
      return rows;
    },
    body: new Element('body'),
  };

  const ids = [
    'vidTable',
    'saveVid',
    'videoCorrectionMode',
    'videoCorrectionDownload',
    'videoCorrectionCancel',
    'videoCorrectionStatus',
    'videoSafetyNotice',
    'videoSection',
    'vCur',
    'subVidSel',
    'exNumHigh',
    'exNumMid',
    'exNumLow',
    'vChap',
    'vTitle',
    'vUrl',
    'addVid',
    'toggleVid',
  ];

  for (const id of ids) {
    const tag =
      id === 'vidTable'
        ? 'table'
        : id.includes('Vid') || id.includes('Correction')
          ? 'button'
          : 'div';
    document.body.appendChild(new Element(tag, id));
  }
  elements.get('videoSection').appendChild(elements.get('vidTable'));

  class CountURL extends URL {
    constructor(...args) {
      super(...args);
      metrics.urlParses++;
    }

    static createObjectURL(blob) {
      return 'blob:fixture-' + blobs.indexOf(blob);
    }

    static revokeObjectURL() {}
  }

  class CaptureBlob extends Blob {
    constructor(parts, options) {
      super(parts, options);
      blobs.push(this);
    }
  }

  const context = {
    document,
    window: { confirm: () => confirm },
    location: { origin: 'https://academy.example.invalid' },
    URL: CountURL,
    Blob: CaptureBlob,
    Date,
    WeakMap,
    Map,
    Set,
    JSON: {
      parse: JSON.parse,
      stringify(value, ...args) {
        const started = performance.now();
        const out = JSON.stringify(value, ...args);
        metrics.stringifyCalls++;
        metrics.stringifyMs += performance.now() - started;
        metrics.stringifyBytes += out?.length || 0;
        return out;
      },
    },
    console: {
      error: (...args) => logs.push(
        args.map(arg => arg instanceof Error ? arg.message : String(arg)).join(' '),
      ),
      log() {},
    },
    alert: message => alerts.push(message),
    setTimeout: (fn, delay) => {
      const id = ++timerId;
      timers.set(id, { due: now + delay, fn });
      return id;
    },
    clearTimeout: id => timers.delete(id),
    applySearchPlaceholder,
    matchesSearchKey,
    nextVideoId,
    GICHUL_COURSE,
    searchKeyForText: text => {
      metrics.searchKeys++;
      return searchKeyForText(text);
    },
    parseYouTubeUrl: (...args) => {
      metrics.providerParses++;
      return parseYouTubeUrl(...args);
    },
    protectedVideoIdentityChanges,
    buildVideoCorrectionDraft,
    videoCorrectionSummary: (...args) => {
      const started = performance.now();
      const result = videoCorrectionSummary(...args);
      metrics.correctionSummaries++;
      metrics.correctionSummaryMs += performance.now() - started;
      return result;
    },
    fetch: (url, options = {}) => {
      assert.equal(
        url,
        '/api/videos',
        'no unrelated endpoint or real request may be issued',
      );
      if (options.method === 'POST') {
        return new Promise((resolve, reject) => {
          posts.push({ body: options.body, resolve, reject, done: false });
        });
      }
      assert.equal(options.cache, 'no-store');
      return Promise.resolve({
        ok: true,
        headers: {
          get: name => name === 'X-Video-Providers'
            ? youtube ? 'kollus,youtube' : 'kollus'
            : null,
        },
        json: async () => clone(serverRows),
      });
    },
    metrics: {
      get current() {
        return metrics;
      },
    },
  };

  const instrumented = source
    .replace(/^import .*;\n/gm, '')
    .replace(
      'function drawVid() {',
      'function drawVid() { metrics.current.draws++;',
    )
    .replace(
      'function syncVisibleVideoRowsFromTable() {',
      'function syncVisibleVideoRowsFromTable() { metrics.current.fullSyncs++;',
    )
    .replace(
      'function syncVideoRowFromTable(tr) {',
      'function syncVideoRowFromTable(tr) { metrics.current.rowSyncs++;',
    );

  vm.runInNewContext(instrumented, context, {
    filename: 'actual-video-manage-entrypoint.js',
  });

  const settle = async () => {
    for (let i = 0; i < 18; i++) await Promise.resolve();
  };

  const advance = async milliseconds => {
    const target = now + milliseconds;
    for (;;) {
      const next = [...timers.entries()]
        .filter(([, timer]) => timer.due <= target)
        .sort((a, b) => a[1].due - b[1].due || a[0] - b[0])[0];
      if (!next) break;

      now = next[1].due;
      timers.delete(next[0]);
      next[1].fn();
      await settle();
    }
    now = target;
    await settle();
  };

  const complete = async (
    index,
    { status = 204, payload = {}, reject = false } = {},
  ) => {
    const post = posts[index];
    assert.ok(post && !post.done, 'pending POST ' + index);
    post.done = true;

    if (reject) {
      post.reject(new Error('fixture network failure'));
    } else {
      if (status >= 200 && status < 300) {
        serverRows = JSON.parse(post.body);
      }
      post.resolve({
        ok: status >= 200 && status < 300,
        status,
        json: async () => payload,
      });
    }
    await settle();
  };

  const rowByIdx = index => elements.get('vidTable').children.find(
    row => +row.dataset.idx === index,
  );

  return {
    elements,
    document,
    posts,
    alerts,
    downloads,
    blobs,
    logs,
    settle,
    advance,
    complete,
    setConfirm: value => { confirm = value; },
    serverRows: () => clone(serverRows),
    metrics: () => ({ ...metrics }),
    reset: () => { metrics = freshMetrics(); },
    cell: (index, column) => {
      const row = rowByIdx(index);
      assert.ok(row, 'visible row ' + index);
      return row.children[column];
    },
    edit: (index, column, value, blur = true) => {
      const td = rowByIdx(index)?.children[column];
      assert.ok(td, 'visible cell ' + index + '/' + column);
      td.innerText = value;
      if (blur) td.dispatch('blur');
      return td;
    },
    search: (query, type = 'input', properties = {}) => {
      const input = elements.get('videoSearch');
      input.value = query;
      input.focus();
      input.dispatch(type, properties);
    },
    filter: (id, value) => {
      const element = elements.get(id);
      element.value = value;
      element.dispatch('change');
    },
    visible: () => elements.get('vidTable').children.map(
      row => +row.dataset.idx,
    ),
    titles: () => elements.get('vidTable').children.map(
      row => row.children[7]._text,
    ),
    click: id => elements.get(id).click(),
    forceSave: () => elements.get('saveVid').onclick(),
  };
}

async function loaded(source, rows, options) {
  const harness = makeHarness(source, rows, options);
  await harness.settle();
  return harness;
}

function payloadAt(harness, index) {
  return JSON.parse(harness.posts[index].body);
}

function same(actual, expected, message) {
  assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected, message);
}

async function contractTests(source, label) {
  const outcomes = [];

  let h = await loaded(source, syntheticRows(3));
  same(h.visible(), [0, 1, 2], label + ' initial chapter order');
  h.reset();
  h.edit(0, 7, ' 첫 수정 ');

  await h.advance(799);
  assert.equal(h.posts.length, 0);
  await h.advance(1);
  assert.equal(h.posts.length, 1);

  const firstExpected = syntheticRows(3);
  firstExpected[0].title = '첫 수정';
  same(
    payloadAt(h, 0),
    firstExpected,
    '800ms first payload and unknown metadata literal',
  );

  h.click('videoCorrectionMode');
  assert.equal(h.alerts.at(-1), '일반 저장이 끝난 뒤 다시 시도하세요.');

  h.edit(1, 7, '둘째 수정');
  await h.advance(800);
  assert.equal(h.posts.length, 1, 'single in-flight POST');

  h.click('saveVid');
  h.edit(2, 7, '포커스 중 셋째', false);
  await h.complete(0);
  assert.equal(
    h.posts.length,
    2,
    'queued manual save starts on flight completion',
  );

  const secondExpected = syntheticRows(3);
  secondExpected[0].title = '첫 수정';
  secondExpected[1].title = '둘째 수정';
  secondExpected[2].title = '포커스 중 셋째';
  same(
    payloadAt(h, 1),
    secondExpected,
    'queue must read last unblurred DOM edit',
  );
  same(
    payloadAt(h, 0),
    firstExpected,
    'earlier POST body immutable during later edits',
  );

  await h.complete(1);
  h.click('saveVid');
  assert.equal(h.posts.length, 2, 'manual no-op has no POST');
  assert.equal(h.document.body.children.at(-1).textContent, '변경사항 없음');

  const reload = await loaded(source, h.serverRows());
  same(
    reload.titles(),
    ['첫 수정', '둘째 수정', '포커스 중 셋째'],
    'reload persistence in synthetic fetch',
  );
  outcomes.push({
    case: '800ms queue/manual priority/latest DOM/reload/no-op',
    pass: true,
    postCount: 2,
  });

  h = await loaded(source, syntheticRows(2));
  h.edit(0, 7, '실패 후 보존');
  await h.advance(800);

  const failExpected = syntheticRows(2);
  failExpected[0].title = '실패 후 보존';
  await h.complete(0, {
    status: 503,
    payload: { message: 'fixture 503' },
  });

  same(
    h.titles(),
    ['실패 후 보존', '합성 기하 영상 2 대상마지막'],
    '503 keeps draft',
  );
  assert.equal(h.elements.get('videoSafetyNotice').dataset.state, 'blocked');

  h.click('saveVid');
  assert.equal(h.posts.length, 2);
  same(payloadAt(h, 1), failExpected, 'manual retry literal');

  await h.complete(1);
  h.click('videoCorrectionMode');
  h.forceSave();
  assert.equal(h.posts.length, 2, 'correction guard prevents forced POST');
  same(
    h.titles(),
    ['실패 후 보존', '합성 기하 영상 2 대상마지막'],
    'saved retry is correction base',
  );
  outcomes.push({
    case: '503 retains draft/retry/saved-snapshot boundary',
    pass: true,
  });

  h = await loaded(source, syntheticRows(2));
  h.edit(0, 7, '409 입력');
  await h.advance(800);
  await h.complete(0, {
    status: 409,
    payload: {
      error: 'video_catalog_identity_change_blocked',
      removedIds: [],
      midChanges: [
        { id: '1', oldMid: 'synthetic-1', newMid: 'blocked' },
      ],
      message: 'fixture blocked',
    },
  });

  same(
    h.titles(),
    ['합성 기하 영상 1', '합성 기하 영상 2 대상마지막'],
    '409 restores last successful base',
  );
  assert.equal(h.elements.get('videoSafetyNotice').dataset.state, 'blocked');
  outcomes.push({ case: 'server identity 409 rollback', pass: true });

  h = await loaded(source, syntheticRows(2));
  h.edit(
    0,
    8,
    'https://v.kr.kollus.com/player?mid=synthetic-1&token=renewed',
  );
  h.click('saveVid');
  assert.equal(h.posts.length, 1);

  const urlExpected = syntheticRows(2);
  urlExpected[0].url =
    'https://v.kr.kollus.com/player?mid=synthetic-1&token=renewed';
  same(
    payloadAt(h, 0),
    urlExpected,
    'same MID signature URL remains allowed',
  );
  await h.complete(0);

  h.edit(0, 8, 'https://v.kr.kollus.com/player?mid=blocked-new');
  await h.advance(800);
  assert.equal(h.posts.length, 1, 'normal protected MID no POST');
  same(h.titles(), ['합성 기하 영상 1', '합성 기하 영상 2 대상마지막']);
  assert.equal(
    h.cell(0, 8)._text,
    urlExpected[0].url,
    'MID restore latest saved signed URL',
  );

  const deleteButton = h.cell(1, 9).children[0];
  deleteButton.click();
  await h.advance(800);
  assert.equal(h.posts.length, 1, 'normal removal no POST');
  same(h.visible(), [0, 1]);
  outcomes.push({
    case: 'same-MID URL/client MID and removal protection',
    pass: true,
  });

  h = await loaded(source, syntheticRows(2));
  h.click('videoCorrectionMode');
  assert.equal(h.elements.get('saveVid').disabled, true);

  h.edit(0, 8, 'https://v.kr.kollus.com/player?mid=corrected-synthetic');
  h.edit(0, 7, '수정안 제목');
  h.cell(1, 9).children[0].click();
  await h.advance(200);
  assert.equal(h.posts.length, 0, 'correction blur/delete no POST');

  h.edit(0, 3, '0', false);
  h.click('videoCorrectionDownload');
  assert.equal(h.downloads.length, 1);

  const draft = JSON.parse(await h.blobs.at(-1).text());
  same(draft.baseVideos, syntheticRows(2), 'draft base lastSaved literal');

  const draftExpected = syntheticRows(2).slice(0, 1);
  Object.assign(draftExpected[0], {
    mid: 'corrected-synthetic',
    url: 'https://v.kr.kollus.com/player?mid=corrected-synthetic',
    title: '수정안 제목',
    chapter: 1,
  });
  same(
    draft.nextVideos,
    draftExpected,
    'correction export final unblurred DOM and unknown metadata',
  );
  assert.equal(draft.kind, 'academy-video-catalog-correction');
  assert.equal(draft.schemaVersion, 1);
  assert.match(
    h.elements.get('videoCorrectionStatus').textContent,
    /MID 변경 1건 · 삭제 1건/,
  );

  h.setConfirm(false);
  h.click('videoCorrectionCancel');
  assert.equal(h.elements.get('saveVid').disabled, true);
  h.setConfirm(true);
  h.click('videoCorrectionCancel');
  same(h.titles(), ['합성 기하 영상 1', '합성 기하 영상 2 대상마지막']);
  assert.equal(h.posts.length, 0);
  assert.equal(h.elements.get('saveVid').disabled, false);
  outcomes.push({
    case: 'correction enter/edit/delete/final export/cancel/no-POST',
    pass: true,
  });

  const hiddenRows = [
    {
      id: 1,
      mid: 'synthetic-1',
      curriculum: '기하',
      subCurriculum: 'APEX',
      chapter: 1,
      title: '표시 대상',
      url: 'https://v.kr.kollus.com/player?mid=synthetic-1',
      exNum: { 상: 3 },
      extra: '그대로',
    },
    {
      id: 2,
      mid: 'synthetic-2',
      curriculum: '대수',
      subCurriculum: 'A:Ble',
      chapter: 0,
      title: '숨김 대상',
      url: 'https://v.kr.kollus.com/player?mid=synthetic-2',
      exNum: { 상: 0, legacy: 'keep' },
      unknown: { untouched: true },
    },
  ];

  h = await loaded(source, hiddenRows);
  h.filter('curriculumFilter', '기하');
  same(h.visible(), [0]);
  h.edit(0, 3, '0');
  h.edit(0, 4, '4.5');
  h.edit(0, 5, '');
  h.edit(0, 6, '');
  h.search('표시');
  h.edit(0, 7, '새키 대상');

  h.search('표시');
  same(h.visible(), [], 'old mutable search key invalidated');
  h.search('새키');
  same(h.visible(), [0], 'new mutable search key visible');
  h.click('saveVid');
  assert.equal(h.posts.length, 1);

  same(
    payloadAt(h, 0),
    [
      {
        id: 1,
        mid: 'synthetic-1',
        curriculum: '기하',
        subCurriculum: 'APEX',
        chapter: 1,
        title: '새키 대상',
        url: 'https://v.kr.kollus.com/player?mid=synthetic-1',
        exNum: { 상: 4.5 },
        extra: '그대로',
      },
      hiddenRows[1],
    ],
    'hidden row byte values/coercion/exNum/unknown literal',
  );

  await h.complete(0);
  h.edit(0, 4, '');
  h.click('saveVid');
  assert.equal(h.posts.length, 2);
  const withoutEx = payloadAt(h, 1)[0];
  assert.equal(
    Object.hasOwn(withoutEx, 'exNum'),
    false,
    'blank exNum property deleted',
  );
  same(payloadAt(h, 1)[1], hiddenRows[1]);
  await h.complete(1);

  h.filter('curriculumFilter', '');
  h.search('ㄷㅅ a:ble');
  same(h.visible(), [1], 'Hangul initials plus AND disambiguation');
  h.search('eotn');
  same(h.visible(), [1], 'Dubeolsik English typing');
  h.search('숨김 대상');
  same(h.visible(), [1], 'AND fields preserve result');
  h.search('synthetic-2');
  same(h.visible(), [1], 'MID/URL search');
  h.search('anything', 'keydown', { key: 'Escape' });
  same(h.visible(), [0, 1], 'Escape resets with curriculum/chapter order');
  outcomes.push({
    case:
      'filtered hidden row/coercion/empty-exNum/search-key invalidation/' +
      'initials/Dubeolsik/AND/MID/Escape',
    pass: true,
  });

  const duplicates = [
    {
      id: 4,
      mid: 'synthetic-a',
      curriculum: '기하',
      subCurriculum: 'APEX',
      chapter: 1,
      title: '첫 중복',
      url: 'https://v.kr.kollus.com/player?mid=synthetic-a',
    },
    {
      id: 4,
      mid: 'synthetic-b',
      curriculum: '기하',
      subCurriculum: 'APEX',
      chapter: 2,
      title: '끝 중복',
      url: 'https://v.kr.kollus.com/player?mid=synthetic-b',
    },
  ];

  h = await loaded(source, duplicates);
  same(h.visible(), [0, 0]);
  const duplicateFirst = h.cell(0, 7);
  duplicateFirst.innerText = '첫 입력';
  duplicateFirst.dispatch('blur');
  h.search('첫 입력');
  same(h.visible(), [], 'legacy duplicate whole-table last writer preserved');
  h.search('끝 중복');
  same(h.visible(), [0, 0], 'legacy duplicate first-index remains');
  outcomes.push({
    case: 'legacy duplicate IDs: first-index and blur last writer',
    pass: true,
  });

  const addInputs = {
    vCur: '기하',
    subVidSel: '기출엄선',
    vChap: '1',
    vTitle: '새 YouTube',
    vUrl: 'https://youtu.be/NSorUwxBPGg?t=90',
  };

  h = await loaded(source, syntheticRows(1), { youtube: false });
  for (const [id, value] of Object.entries(addInputs)) {
    h.elements.get(id).value = value;
  }
  h.click('addVid');
  await h.advance(800);
  assert.equal(h.posts.length, 0);
  assert.equal(
    h.alerts.at(-1),
    'YouTube 기능의 서버 반영 후 등록할 수 있습니다.',
  );

  h = await loaded(source, syntheticRows(1), { youtube: true });
  for (const [id, value] of Object.entries(addInputs)) {
    h.elements.get(id).value = value;
  }
  h.click('addVid');
  await h.advance(800);
  assert.equal(h.posts.length, 1);

  same(
    payloadAt(h, 0),
    [
      syntheticRows(1)[0],
      {
        id: 2,
        mid: 'ytv_NSorUwxBPGg_r2',
        curriculum: '기하',
        subCurriculum: '기출엄선',
        chapter: 1,
        title: '새 YouTube',
        url: 'https://www.youtube.com/watch?v=NSorUwxBPGg&t=90',
        provider: 'youtube',
        youtubeKind: 'video',
        youtubeId: 'NSorUwxBPGg',
        youtubeStart: 90,
      },
    ],
    'new ID and canonical provider literal payload',
  );
  await h.complete(0);
  h.click('saveVid');
  assert.equal(h.posts.length, 1, 'provider normal mode no-op');
  outcomes.push({
    case: 'numeric new ID/YouTube capability and canonical MID/payload',
    pass: true,
  });

  h = await loaded(source, syntheticRows(3));
  h.search('mid=synthetic-1&token=fixture');
  same(h.visible(), [0]);
  h.edit(0, 7, '편집 후 숨김');
  h.search('대상마지막');
  same(h.visible(), [2]);
  h.click('saveVid');

  const invisibleExpected = syntheticRows(3);
  invisibleExpected[0].title = '편집 후 숨김';
  same(
    payloadAt(h, 0),
    invisibleExpected,
    'search-hidden draft remains authoritative',
  );

  h.edit(2, 7, 'queued network retry');
  await h.advance(800);
  assert.equal(h.posts.length, 1);
  await h.complete(0, { reject: true });
  assert.equal(
    h.posts.length,
    2,
    'queued save retries against preserved lastSaved base',
  );

  const retryExpected = syntheticRows(3);
  retryExpected[0].title = '편집 후 숨김';
  retryExpected[2].title = 'queued network retry';
  same(payloadAt(h, 1), retryExpected);
  await h.complete(1);

  h.search('편집 후');
  same(h.visible(), [0]);
  h.edit(0, 7, '아직 미저장');
  h.click('videoCorrectionMode');
  h.search('편집 후');
  same(
    h.visible(),
    [0],
    'correction enter restores saved snapshot and searchable object generation',
  );

  h.click('videoCorrectionCancel');
  h.search('queued network');
  same(
    h.visible(),
    [2],
    'correction cancel preserves lastSaved committed generation',
  );
  outcomes.push({
    case:
      'search-hidden edit/latest retry after queued network failure/' +
      'snapshot cache generation',
    pass: true,
  });

  return { label, outcomes, caseCount: outcomes.length };
}

async function cacheBoundaryTests(
  source,
  label,
  expectOptimized = false,
) {
  const n = 50;
  let h = await loaded(source, syntheticRows(n));
  h.search('합성');
  h.reset();
  h.edit(0, 7, '캐시 새표적');
  h.search('합성');
  assert.equal(h.visible().length, n - 1);

  const changed = h.metrics();
  if (expectOptimized) {
    assert.equal(changed.searchKeys, 1, 'one modified row key generation');
  }

  h.reset();
  h.click('saveVid');
  assert.equal(h.posts.length, 1);
  await h.complete(0);
  h.search('합성');

  const saved = h.metrics();
  if (expectOptimized) {
    assert.equal(
      saved.searchKeys,
      0,
      'full final save keeps unchanged cached keys',
    );
  }

  h.search('캐시 새표적');
  same(h.visible(), [0]);
  h.reset();
  h.edit(0, 8, 'https://v.kr.kollus.com/player?mid=blocked-cache-key');
  await h.advance(800);
  assert.equal(h.posts.length, 1, 'client protected MID no new POST');
  h.search('blocked-cache-key');
  same(
    h.visible(),
    [],
    'MID rollback must evict mutated object search key',
  );
  h.search('캐시 새표적');
  same(h.visible(), [0], 'MID rollback restores new saved title');

  h.search('합성');
  h.reset();
  h.edit(1, 7, 'server failure cached key');
  h.click('saveVid');
  assert.equal(h.posts.length, 2);
  await h.complete(1, {
    status: 409,
    payload: {
      error: 'video_catalog_identity_change_blocked',
      removedIds: [],
      midChanges: [],
      message: 'synthetic server conflict',
    },
  });

  h.search('server failure cached key');
  same(
    h.visible(),
    [],
    'server restore cache follows cloned lastSaved',
  );
  h.search('캐시 새표적');
  same(h.visible(), [0]);

  h.search('합성');
  h.click('videoCorrectionMode');
  h.edit(1, 7, 'correction cached only');
  h.search('correction cached only');
  same(h.visible(), [1]);
  h.click('videoCorrectionCancel');

  h.search('correction cached only');
  same(
    h.visible(),
    [],
    'correction cancel cache follows restored cloned snapshot',
  );
  h.search('캐시 새표적');
  same(h.visible(), [0]);

  return {
    label,
    case:
      'changed-row-only cache generation; full-save cache preservation; ' +
      'client MID/server409/correction clone restore',
    changedKeys: changed.searchKeys,
    keysAfterFinalFullSave: saved.searchKeys,
    pass: true,
  };
}

async function queueAtScale(
  source,
  label,
  n,
  expectOptimized = false,
) {
  const h = await loaded(source, syntheticRows(n));
  h.reset();
  h.edit(0, 7, 'scale first');
  await h.advance(799);
  assert.equal(h.posts.length, 0);
  await h.advance(1);
  assert.equal(h.posts.length, 1);

  const first = syntheticRows(n);
  first[0].title = 'scale first';
  same(payloadAt(h, 0), first);

  h.edit(1, 7, 'scale second');
  await h.advance(800);
  assert.equal(h.posts.length, 1);
  h.click('saveVid');
  h.edit(2, 7, 'scale unblurred latest', false);
  await h.complete(0);
  assert.equal(h.posts.length, 2);

  const expected = syntheticRows(n);
  expected[0].title = 'scale first';
  expected[1].title = 'scale second';
  expected[2].title = 'scale unblurred latest';
  same(payloadAt(h, 1), expected);
  same(payloadAt(h, 0), first, 'first POST body immutable');

  await h.complete(1);
  const finalFeedback = h.document.body.children.at(-1).textContent;
  assert.equal(
    finalFeedback,
    '영상 저장 완료',
    'manual upgrade controls queued feedback',
  );

  h.click('saveVid');
  assert.equal(h.posts.length, 2);
  const counts = h.metrics();
  if (expectOptimized) {
    assert.equal(
      counts.innerTextReads,
      n * 40 + 16,
      'two blur/five authoritative final-save boundaries',
    );
  }

  const reload = await loaded(source, h.serverRows());
  same(
    reload.titles().slice(0, 3),
    ['scale first', 'scale second', 'scale unblurred latest'],
  );

  return {
    label,
    rows: n,
    postCount: 2,
    debounceMs: 800,
    manualPriority: finalFeedback,
    payloadSha256: hash(JSON.stringify(expected)),
    counts,
    pass: true,
  };
}

async function correctionAtScale(
  source,
  label,
  n,
  expectOptimized = false,
) {
  const h = await loaded(source, syntheticRows(n));
  h.click('videoCorrectionMode');
  h.reset();
  h.edit(0, 7, '수정안 blur');

  const blur = h.metrics();
  if (expectOptimized) assert.equal(blur.innerTextReads, 8);
  assert.equal(blur.correctionSummaries, 1);

  await h.advance(199);
  assert.equal(h.posts.length, 0);
  h.reset();
  await h.advance(1);

  const timer = h.metrics();
  assert.equal(
    timer.innerTextReads,
    8 * n,
    '200ms correction status keeps authoritative full sync',
  );
  assert.equal(timer.correctionSummaries, 1);

  h.edit(0, 7, '수정안 unblurred export', false);
  h.reset();
  h.click('videoCorrectionDownload');

  const download = h.metrics();
  if (expectOptimized) assert.equal(download.innerTextReads, 8 * n);
  const draft = JSON.parse(await h.blobs.at(-1).text());
  same(draft.baseVideos, syntheticRows(n));

  const target = syntheticRows(n);
  target[0].title = '수정안 unblurred export';
  same(draft.nextVideos, target);
  assert.equal(draft.kind, 'academy-video-catalog-correction');
  assert.equal(draft.schemaVersion, 1);
  assert.equal(h.posts.length, 0);

  h.reset();
  h.forceSave();
  const forcedSave = h.metrics();
  if (expectOptimized) assert.equal(forcedSave.innerTextReads, 8 * n);
  assert.equal(h.posts.length, 0);

  h.click('videoCorrectionCancel');
  assert.equal(h.posts.length, 0);

  return {
    label,
    rows: n,
    blur,
    timer,
    download,
    forcedSave,
    postCount: 0,
    draftNextSha256: hash(JSON.stringify(target)),
    pass: true,
  };
}

const stats = values => {
  const sorted = values.slice().sort((a, b) => a - b);
  return {
    sampleCount: values.length,
    p50Ms: sorted[Math.ceil(sorted.length * 0.5) - 1],
    p95Ms: sorted[Math.ceil(sorted.length * 0.95) - 1],
  };
};

async function measureVariant(
  source,
  label,
  count,
  warmup = 5,
  sampleCount = 30,
) {
  let h = await loaded(source, syntheticRows(count));
  h.reset();

  const blurStart = performance.now();
  h.edit(0, 7, '단일 수정');
  const oneBlurCpuMs = performance.now() - blurStart;
  const oneBlur = h.metrics();

  await h.advance(799);
  assert.equal(h.posts.length, 0);
  h.reset();
  const saveStart = performance.now();
  await h.advance(1);
  const finalSaveVmCpuMs = performance.now() - saveStart;
  assert.equal(h.posts.length, 1);
  const finalSave = h.metrics();

  const expected = syntheticRows(count);
  expected[0].title = '단일 수정';
  same(payloadAt(h, 0), expected, 'scale literal final POST ' + count);
  await h.complete(0);

  h = await loaded(source, syntheticRows(count));
  const blurSamples = [];
  for (let i = 0; i < warmup + sampleCount; i++) {
    if (i === warmup) h.reset();
    const started = performance.now();
    h.edit(0, 7, '반복 편집 ' + i);
    if (i >= warmup) blurSamples.push(performance.now() - started);
  }
  const blurRepeated = { ...stats(blurSamples), counts: h.metrics() };

  h = await loaded(source, syntheticRows(count));
  h.reset();
  for (const query of ['ㅎ', '하', '합', '합성']) {
    h.search(query, 'input', { isComposing: true });
  }
  h.search('합성', 'compositionend');
  h.search('합성', 'input');
  h.search('합성', 'search');

  assert.equal(h.visible().length, count, 'final IME logical result');
  assert.equal(
    h.document.activeElement,
    h.elements.get('videoSearch'),
    'search focus logical event path',
  );
  const ime = h.metrics();

  const searches = {};
  for (const [name, query, expectedCount] of [
    ['broad', '합성', count],
    ['narrow', '합성 대상마지막', 1],
  ]) {
    h = await loaded(source, syntheticRows(count));
    h.reset();

    const coldStart = performance.now();
    h.search(query);
    const cold = {
      vmCpuMs: performance.now() - coldStart,
      counts: h.metrics(),
    };
    assert.equal(h.visible().length, expectedCount);

    for (let i = 0; i < warmup; i++) h.search(query);
    h.reset();

    const samples = [];
    for (let i = 0; i < sampleCount; i++) {
      const started = performance.now();
      h.search(query);
      samples.push(performance.now() - started);
      assert.equal(h.visible().length, expectedCount);
    }

    searches[name] = {
      query,
      expectedRows: expectedCount,
      cold,
      warm: { ...stats(samples), counts: h.metrics() },
    };
  }

  return {
    label,
    count,
    oneBlur: { vmCpuMs: oneBlurCpuMs, counts: oneBlur },
    autoSave: {
      debounceMs: 800,
      postCount: 1,
      finalSaveVmCpuMs,
      counts: finalSave,
      payloadSha256: hash(JSON.stringify(expected)),
    },
    blurRepeated,
    ime,
    searches,
  };
}

const options = parseOptions(process.argv.slice(2));
const sources = [];
if (options.before) sources.push(readSource('before', options.before));
sources.push(readSource('source', options.source));

const results = [];
for (const input of sources) {
  const optimized = options.expectOptimized && input.label === 'source';
  const lifecycle = await contractTests(input.source, input.label);
  const cache = await cacheBoundaryTests(
    input.source,
    input.label,
    optimized,
  );
  const queued = [];
  const correction = [];

  for (const n of options.sizes) {
    queued.push(await queueAtScale(
      input.source,
      input.label,
      n,
      optimized,
    ));
    correction.push(await correctionAtScale(
      input.source,
      input.label,
      n,
      optimized,
    ));
  }

  results.push({
    source: input.path,
    sourceSha256: input.hash,
    label: input.label,
    functionalCaseGroups:
      lifecycle.caseCount + 1 + queued.length + correction.length,
    lifecycle,
    cache,
    queued,
    correction,
  });
}

if (results.length === 2) {
  for (let i = 0; i < options.sizes.length; i++) {
    assert.equal(
      results[0].queued[i].payloadSha256,
      results[1].queued[i].payloadSha256,
    );
    assert.equal(
      results[0].correction[i].draftNextSha256,
      results[1].correction[i].draftNextSha256,
    );
  }
}

console.log(JSON.stringify({
  kind: 'actual-entrypoint-synthetic-VM-regression',
  sizes: options.sizes,
  expectOptimized: options.expectOptimized,
  exclusions: [
    'real browser DOM/layout/paint',
    'native IME',
    'real network',
    'real timer wall-clock delay',
  ],
  persistentWrites: 0,
  results,
}, null, 2));

if (options.bench) {
  const measurements = [];
  for (const count of options.sizes) {
    for (const input of sources) {
      const result = await measureVariant(
        input.source,
        input.label,
        count,
        options.warmup,
        options.samples,
      );
      measurements.push(result);
      console.log(JSON.stringify({
        progress: { rows: count, variant: input.label },
        measurement: result,
      }));
    }
  }

  console.log(JSON.stringify({
    kind: 'actual-entrypoint-synthetic-VM-proxy-DOM-benchmark',
    sizes: options.sizes,
    warmup: options.warmup,
    samples: options.samples,
    exclusions: [
      'real DOM',
      'layout',
      'paint',
      'browser/native IME',
      'network',
      'real debounce wall-clock delay',
    ],
    conclusion:
      'VM CPU and operation counts only; never browser latency or rollout evidence',
    persistentWrites: 0,
    measurements,
  }));
}
