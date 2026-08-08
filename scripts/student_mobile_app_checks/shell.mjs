import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..', '..');

export const SHELL_ARTIFACT = process.env.STUDENT_APP_SHELL_EVIDENCE ?? path.join(
  root,
  '.omo',
  'evidence',
  'student-mobile-app-v2',
  'task-4',
  'sw-canonical-remediation-l2-shell-check.json',
);
const files = Object.freeze({
  html: path.join(root, 'static', 'student-app.html'),
  css: path.join(root, 'static', 'css', 'student-app.css'),
  js: path.join(root, 'static', 'js', 'student-app.js'),
  manifest: path.join(root, 'static', 'manifest.webmanifest'),
  serviceWorker: path.join(root, 'static', 'sw.js'),
  offline: path.join(root, 'static', 'offline.html'),
});

const utf8 = async (filename) => fs.readFile(filename, 'utf8');

function assertIncludes(source, needle, label) {
  assert.ok(source.includes(needle), `${label}: expected ${needle}`);
}

function pngSize(buffer) {
  assert.equal(buffer.subarray(0, 8).toString('hex'), '89504e470d0a1a0a', 'PNG signature');
  assert.equal(buffer.readUInt32BE(12), 0x49484452, 'PNG IHDR chunk');
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

class FakeElement {
  constructor(documentRef, tagName) {
    this.ownerDocument = documentRef;
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = Object.create(null);
    this.listeners = new Map();
    this.value = '';
    this.textContent = '';
    this.id = '';
    this.className = '';
    this.tabIndex = 0;
    this.disabled = false;
  }

  append(...nodes) {
    for (const node of nodes) { node.parentNode = this; this.children.push(node); }
  }

  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
  focus() { this.ownerDocument.activeElement = this; }
  click() { return this.listeners.get('click')?.({ currentTarget: this }); }

  matches(selector) {
    if (selector.startsWith('#')) return this.id === selector.slice(1);
    if (selector.startsWith('.')) return this.className.split(/\s+/).includes(selector.slice(1));
    const dataMatch = selector.match(/^\[data-([^=\]]+)(?:=["']?([^\]"']+)["']?)?\]$/);
    if (dataMatch) { const key = dataMatch[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()); return Object.prototype.hasOwnProperty.call(this.dataset, key) && (!dataMatch[2] || this.dataset[key] === dataMatch[2]); }
    return false;
  }

  querySelector(selector) { for (const child of this.children) { if (child.matches(selector)) return child; const nested = child.querySelector(selector); if (nested) return nested; } return null; }

  querySelectorAll(selector) { return this.children.flatMap((child) => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
}

class FakeDocument {
  constructor() {
    this.activeElement = null;
    this.root = new FakeElement(this, 'main');
    this.root.id = 'student-app';
  }

  createElement(tagName) { return new FakeElement(this, tagName); }
  getElementById(id) { return id === 'student-app' ? this.root : this.root.querySelector(`#${id}`); }
}

function loadStudentAppFunctions(source) {
  const transformed = source
    .replace(/export function /g, 'function ')
    .replace(/export \{ STATES \};?/, '')
    .concat('\nglobalThis.__studentAppExports = { createStudentApp, normalizeState, STATES };');
  const context = { console, document: undefined, navigator: undefined, window: undefined, fetch: undefined };
  vm.createContext(context);
  vm.runInContext(transformed, context, { filename: 'static/js/student-app.js' });
  return context.__studentAppExports;
}

export async function runShellChecks() {
  const source = await Promise.all(Object.values(files).map(utf8));
  const [html, css, js, manifestSource, sw, offline] = source;
  const manifest = JSON.parse(manifestSource);
  const iconPaths = [
    path.join(root, 'static', 'icons', 'student-app-192.png'),
    path.join(root, 'static', 'icons', 'student-app-512.png'),
    path.join(root, 'static', 'icons', 'student-app-maskable-512.png'),
  ];
  const icons = await Promise.all(iconPaths.map((filename) => fs.readFile(filename)));

  const checks = [];
  let installReceipt = { requests: [], fetches: [], rawAliasRequests: 0, rawAliasFetches: 0 };
  const check = (name, callback) => {
    callback();
    checks.push(name);
  };
  const checkAsync = async (name, callback) => {
    await callback();
    checks.push(name);
  };

  check('HTML has accessible app shell landmarks', () => {
    assert.match(html, /<main\b[^>]*id=["']student-app["'][^>]*>/i);
    assert.match(html, /aria-live=["']polite["']/i);
    assert.match(html, /role=["']status["']/i);
    assert.match(html, /<noscript\b/i);
    assert.match(html, /rel=["']manifest["'][^>]*href=["']\/manifest\.webmanifest["']/i);
    assert.match(html, /<script[^>]+type=["']module["'][^>]+src=["']\/js\/student-app\.js["']/i);
  });

  check('HTML has a recoverable Korean fallback', () => {
    assert.match(html, /학생 앱|로그인|오류/);
    assert.match(offline, /오프라인|연결|다시 시도/);
  });

  check('CSS defines mobile-first state and focus primitives', () => {
    for (const state of ['signed_out', 'activation_code_required', 'credentials_required', 'push_required', 'unsupported_bypass', 'ready', 'error']) {
      assertIncludes(css, `[data-state="${state}"]`, `CSS state ${state}`);
    }
    assert.match(css, /:focus-visible\s*\{/);
    assert.match(css, /@media\s*\([^)]*min-width\s*:\s*48rem/);
  });

  check('JS contains the full typed state contract', () => {
    for (const state of ['signed_out', 'activation_code_required', 'credentials_required', 'push_required', 'unsupported_bypass', 'ready', 'error']) {
      assertIncludes(js, `'${state}'`, `JS state ${state}`);
    }
    assert.match(js, /export\s+(?:async\s+)?function\s+createStudentApp/);
    assert.match(js, /student-app-state/);
    assert.match(js, /focus\(\)/);
    assert.match(js, /aria-live/);
  });

  check('DOM state matrix exposes one role/action and moves focus', () => {
    const { createStudentApp, normalizeState, STATES } = loadStudentAppFunctions(js);
    assert.equal(JSON.stringify(STATES), JSON.stringify(['signed_out', 'activation_code_required', 'credentials_required', 'push_required', 'unsupported_bypass', 'ready', 'error']));
    assert.equal(normalizeState({ status: 'ready', sessionSid: '../secret' }).status, 'error');
    for (const state of STATES) {
      const documentRef = new FakeDocument();
      const app = createStudentApp({ document: documentRef, root: documentRef.root, autoBootstrap: false, initialState: state === 'ready' ? { status: state, sessionSid: 'student-1' } : { status: state } });
      const section = documentRef.root.children[0];
      assert.equal(section.dataset.state, state);
      assert.equal(section.getAttribute('role'), 'region');
      assert.equal(section.getAttribute('aria-labelledby'), 'student-app-state-title');
      assert.equal(section.querySelectorAll('[data-primary-action]').length, 1);
      assert.equal(section.querySelector('[data-app-status]').getAttribute('role'), 'status');
      assert.equal(section.querySelector('[data-app-status]').getAttribute('aria-live'), 'polite');
      assert.ok(documentRef.activeElement === section.querySelector('[data-primary-action]') || documentRef.activeElement?.id === 'activation-code' || documentRef.activeElement?.id === 'credentials-id');
      app.destroy();
    }
  });

  await checkAsync('Injected adapter drives ready navigation and malformed responses to retry', async () => {
    const { createStudentApp } = loadStudentAppFunctions(js);
    const documentRef = new FakeDocument();
    const navigated = [];
    const api = {
      getInitialState: async () => ({ status: 'signed_out' }),
      signIn: async () => ({ status: 'ready', sessionSid: 'student-1' }),
      activate: async () => ({ status: 'credentials_required' }),
      submitCredentials: async () => ({ status: 'push_required' }),
      setupPush: async () => ({ status: 'ready', sessionSid: 'student-1' }),
      continueUnsupported: async () => ({ status: 'ready', sessionSid: 'student-1' }),
    };
    const app = createStudentApp({ document: documentRef, root: documentRef.root, autoBootstrap: false, api, navigate: (url) => navigated.push(url), initialState: { status: 'signed_out' } });
    await documentRef.root.querySelector('[data-primary-action]').click();
    assert.equal(app.getState().status, 'ready');
    await documentRef.root.querySelector('[data-primary-action]').click();
    assert.deepEqual(navigated, ['/student/student-1']);
    app.destroy();

    const malformedDocument = new FakeDocument();
    const malformedApi = { ...api, signIn: async () => ({ status: 'ready' }) };
    const malformedApp = createStudentApp({ document: malformedDocument, root: malformedDocument.root, autoBootstrap: false, api: malformedApi, initialState: { status: 'signed_out' } });
    await malformedDocument.root.querySelector('[data-primary-action]').click();
    assert.equal(malformedApp.getState().status, 'error');
    assert.equal(malformedDocument.root.querySelectorAll('[data-primary-action]').length, 1);
    assert.equal(malformedDocument.root.querySelector('[data-primary-action]').dataset.primaryAction, 'retry');
    malformedApp.destroy();
  });

  check('JS limits production URLs to the mobile/auth/push/student contracts', () => {
    const urls = [...js.matchAll(/['"`]\/(?:api|student)[^'"`]*/g)].map((match) => match[0]);
    assert.ok(urls.length > 0, 'expected at least one production URL contract');
    for (const url of urls) {
      assert.match(url, /^['"`]\/(?:api\/mobile\/(?:auth|push)\/|student\/)/, `URL contract ${url}`);
    }
    assert.doesNotMatch(js, /localStorage|sessionStorage|indexedDB/i);
    assert.doesNotMatch(js, /Notification\.requestPermission/);
  });

  check('Manifest is standalone, scoped, localized, and responsive', () => {
    assert.equal(manifest.start_url, '/app');
    assert.equal(manifest.scope, '/');
    assert.equal(manifest.display, 'standalone');
    assert.equal(manifest.lang, 'ko');
    assert.ok(['portrait', 'landscape', 'any'].includes(manifest.orientation));
    assert.match(String(manifest.description), /학생|학습|모바일/);
    assert.deepEqual(manifest.icons.map((icon) => icon.sizes), ['192x192', '512x512', '512x512']);
    assert.equal(manifest.icons[2].purpose, 'maskable');
  });

  check('Icons are real PNGs with required dimensions and purposes', () => {
    assert.deepEqual(pngSize(icons[0]), { width: 192, height: 192 });
    assert.deepEqual(pngSize(icons[1]), { width: 512, height: 512 });
    assert.deepEqual(pngSize(icons[2]), { width: 512, height: 512 });
    assert.match(manifest.icons[0].src, /student-app-192\.png$/);
    assert.match(manifest.icons[1].src, /student-app-512\.png$/);
    assert.match(manifest.icons[2].src, /student-app-maskable-512\.png$/);
  });

  check('Service worker caches only the static shell', () => {
    assert.match(sw, /student-app-shell-v\d+/);
    assert.match(sw, /['"]\/app['"]/);
    assert.doesNotMatch(sw, /['"]\/student-app\.html['"]/);
    assert.match(sw, /offline\.html/);
    assert.match(sw, /network-first/i);
    assert.match(sw, /network-only/i);
    assert.doesNotMatch(sw, /cache\.put\([^)]*api/i);
    assert.doesNotMatch(sw, /cache\.put\([^)]*\/files\//i);
    assert.doesNotMatch(sw, /cache\.put\([^)]*(?:video|answer|data)/i);
  });

  await checkAsync('Service worker install prefetches canonical app shell only', async () => {
    const installEvents = [];
    const installed = [];
    const installFetches = [];
    const fetchInstallResource = async (request) => {
      installFetches.push(new URL(request, 'https://academy.test').pathname);
      return new Response('network', { status: 200 });
    };
    const installContext = {
      console,
      URL,
      Response,
      Request,
      self: {
        location: { origin: 'https://academy.test' },
        addEventListener: (type, callback) => installEvents.push({ type, callback }),
        skipWaiting: async () => {},
        clients: { claim: async () => {} },
      },
      caches: {
        open: async () => ({
          addAll: async (urls) => {
            installed.push(...urls);
            for (const url of urls) assert.ok((await fetchInstallResource(url)).ok);
          },
          put: async () => {},
        }),
        keys: async () => [],
        delete: async () => true,
        match: async () => undefined,
      },
      fetch: fetchInstallResource,
    };
    vm.createContext(installContext);
    vm.runInContext(sw, installContext, { filename: 'static/sw.js' });
    const installHandler = installEvents.find((event) => event.type === 'install')?.callback;
    assert.equal(typeof installHandler, 'function');
    let installPromise;
    installHandler({ waitUntil: (promise) => { installPromise = promise; } });
    await installPromise;
    assert.ok(installed.includes('/app'));
    assert.equal(installed.filter((url) => url === '/student-app.html').length, 0);
    assert.ok(installFetches.includes('/app'));
    assert.equal(installFetches.filter((url) => url === '/student-app.html').length, 0);
    installReceipt = {
      requests: [...installed],
      fetches: [...installFetches],
      rawAliasRequests: installed.filter((url) => url === '/student-app.html').length,
      rawAliasFetches: installFetches.filter((url) => url === '/student-app.html').length,
    };
  });

  await checkAsync('Service worker runtime skips Cache API for forbidden requests', async () => {
    const events = [];
    const cacheCalls = [];
    const context = {
      console,
      URL,
      Response,
      Request,
      self: {
        location: { origin: 'https://academy.test' },
        addEventListener: (type, callback) => events.push({ type, callback }),
        skipWaiting: async () => {},
        clients: { claim: async () => {} },
      },
      caches: {
        open: async () => ({ addAll: async () => {}, put: async () => cacheCalls.push('put') }),
        keys: async () => [],
        delete: async () => true,
        match: async () => undefined,
      },
      fetch: async () => new Response('network', { status: 200 }),
    };
    vm.createContext(context);
    vm.runInContext(sw, context, { filename: 'static/sw.js' });
    const fetchHandler = events.find((event) => event.type === 'fetch')?.callback;
    assert.equal(typeof fetchHandler, 'function');
    for (const pathname of ['/api/mobile/auth/session', '/files/student.pdf', '/video/lesson.mp4', '/answer/lesson.pdf', '/data/student.json']) {
      const request = new Request(`https://academy.test${pathname}`, { method: 'GET', headers: { Accept: 'application/json' } });
      const event = { request, respondWith: () => { throw new Error(`forbidden request was intercepted: ${pathname}`); } };
      fetchHandler(event);
    }
    const rawAliasResponses = [];
    const rawAliasRequest = new Request('https://academy.test/student-app.html', { method: 'GET', headers: { Accept: 'text/html' } });
    fetchHandler({ request: rawAliasRequest, respondWith: (promise) => rawAliasResponses.push(promise) });
    assert.equal(rawAliasResponses.length, 1);
    await rawAliasResponses[0];
    assert.deepEqual(cacheCalls, []);
  });

  await checkAsync('Service worker activation preserves unrelated cache namespaces', async () => {
    const activationEvents = [];
    const deleted = [];
    const activationContext = {
      console,
      URL,
      Response,
      Request,
      self: {
        location: { origin: 'https://academy.test' },
        addEventListener: (type, callback) => activationEvents.push({ type, callback }),
        skipWaiting: async () => {},
        clients: { claim: async () => {} },
      },
      caches: {
        open: async () => ({ addAll: async () => {}, put: async () => {} }),
        keys: async () => ['other-app-cache', 'student-app-shell-v0', 'student-app-shell-v1'],
        delete: async (key) => { deleted.push(key); return true; },
        match: async () => undefined,
      },
      fetch: async () => new Response('network', { status: 200 }),
    };
    vm.createContext(activationContext);
    vm.runInContext(sw, activationContext, { filename: 'static/sw.js' });
    const activateHandler = activationEvents.find((event) => event.type === 'activate')?.callback;
    assert.equal(typeof activateHandler, 'function');
    let activationPromise;
    activateHandler({ waitUntil: (promise) => { activationPromise = promise; } });
    await activationPromise;
    assert.deepEqual(deleted, ['student-app-shell-v0']);
  });

  await checkAsync('Service worker network-first fallback serves offline guidance', async () => {
    const fallbackEvents = [];
    let matchCount = 0;
    const fallbackContext = {
      console,
      URL,
      Response,
      Request,
      self: {
        location: { origin: 'https://academy.test' },
        addEventListener: (type, callback) => fallbackEvents.push({ type, callback }),
        skipWaiting: async () => {},
        clients: { claim: async () => {} },
      },
      caches: {
        open: async () => ({ addAll: async () => {}, put: async () => {} }),
        keys: async () => [],
        delete: async () => true,
        match: async () => {
          matchCount += 1;
          return matchCount === 2 ? new Response('offline guidance', { status: 200 }) : undefined;
        },
      },
      fetch: async () => { throw new Error('offline fixture'); },
    };
    vm.createContext(fallbackContext);
    vm.runInContext(sw, fallbackContext, { filename: 'static/sw.js' });
    const fetchHandler = fallbackEvents.find((event) => event.type === 'fetch')?.callback;
    const request = new Request('https://academy.test/app', { method: 'GET', headers: { Accept: 'text/html' } });
    const responses = [];
    fetchHandler({ request, respondWith: (promise) => responses.push(promise) });
    assert.equal(responses.length, 1);
    const response = await responses[0];
    assert.equal(await response.text(), 'offline guidance');
  });

  const artifact = {
    suite: 'student-mobile-app-shell',
    generatedAt: new Date().toISOString(),
    checks: checks.length,
    files: Object.fromEntries(Object.entries(files).map(([key, filename]) => [key, path.relative(root, filename)])),
    iconDimensions: icons.map((buffer) => pngSize(buffer)),
    manifest: {
      start_url: manifest.start_url,
      scope: manifest.scope,
      display: manifest.display,
      lang: manifest.lang,
      orientation: manifest.orientation,
    },
    serviceWorkerInstall: installReceipt,
    checksPassed: checks,
  };
  const payload = `${JSON.stringify(artifact, null, 2)}\n`;
  let artifactPath = SHELL_ARTIFACT;
  try {
    await fs.mkdir(path.dirname(artifactPath), { recursive: true });
    await fs.writeFile(artifactPath, payload, 'utf8');
  } catch (error) {
    if (!['EACCES', 'EPERM'].includes(error?.code)) throw error;
    const fallbackDir = await fs.mkdtemp(path.join(os.tmpdir(), 'student-mobile-app-shell-'));
    artifactPath = path.join(fallbackDir, path.basename(SHELL_ARTIFACT));
    await fs.writeFile(artifactPath, payload, 'utf8');
  }
  return { ...artifact, artifactPath };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const result = await runShellChecks();
    console.log(`student-mobile-app shell: ${result.checks} assertions passed`);
    console.log(`artifact: ${path.relative(root, result.artifactPath)}`);
  } catch (error) {
    console.error(`student-mobile-app shell: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
