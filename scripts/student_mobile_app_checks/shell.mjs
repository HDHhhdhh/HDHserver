import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
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
const appModules = Object.freeze([
  files.js,
  path.join(root, 'static', 'js', 'student-app-api.js'),
  path.join(root, 'static', 'js', 'student-app-contract.js'),
  path.join(root, 'static', 'js', 'student-app-push.js'),
]);
const studentPageFiles = Object.freeze({
  html: path.join(root, 'static', 'student.html'),
  css: path.join(root, 'static', 'css', 'student.css'),
  js: path.join(root, 'static', 'js', 'student.js'),
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

async function loadStudentAppFunctions() {
  return import(`${pathToFileURL(files.js).href}?shell-check=${Date.now()}`);
}

export async function runShellChecks() {
  const source = await Promise.all(Object.values(files).map(utf8));
  const [html, css, js, manifestSource, sw, offline] = source;
  const moduleSources = await Promise.all(appModules.map(utf8));
  const allAppJs = moduleSources.join('\n');
  const [studentHtml, studentCss, studentJs] = await Promise.all(Object.values(studentPageFiles).map(utf8));
  const appExports = await loadStudentAppFunctions();
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
    assert.match(html, /apple-mobile-web-app-capable["'][^>]+content=["']yes["']/i);
    assert.match(html, /rel=["']apple-touch-icon["'][^>]+href=["']\/icons\/student-app-192\.png["']/i);
    assert.match(html, /data-install-guide-open[^>]+aria-haspopup=["']dialog["'][^>]+aria-controls=["']student-app-install-dialog["']/i);
    assert.match(html, /data-install-guide\s+hidden/i);
    assert.match(html, /id=["']student-app-install-dialog["'][^>]+role=["']dialog["'][^>]+aria-modal=["']true["']/i);
    assert.match(html, /data-install-steps[^>]+tabindex=["']-1["']/i);
    assert.ok((html.match(/data-install-dismiss/g) ?? []).length >= 2, 'install guide requires explicit dismiss controls');
  });

  check('HTML has a recoverable Korean fallback', () => {
    assert.match(html, /학생 앱|로그인|오류/);
    assert.match(offline, /오프라인|연결|다시 시도/);
    assert.match(html, /href=["']\/app["']/);
    assert.match(offline, /href=["']\/app["']/);
    assert.doesNotMatch(html, /href=["']\/student-app\.html["']/);
    assert.doesNotMatch(offline, /href=["']\/student-app\.html["']/);
  });

  check('CSS defines mobile-first state and focus primitives', () => {
    for (const state of ['signed_out', 'activation_code_required', 'credentials_required', 'push_required', 'unsupported_bypass', 'ready', 'error']) {
      assertIncludes(css, `[data-state="${state}"]`, `CSS state ${state}`);
    }
    assert.match(css, /:focus-visible\s*\{/);
    assert.match(css, /@media\s*\([^)]*min-width\s*:\s*48rem/);
    assert.match(css, /--app-max\s*:\s*32rem/);
    assert.match(css, /min-block-size:\s*100vh;[\s\S]*min-block-size:\s*100dvh;/);
    assert.match(css, /min-block-size:\s*min\(520px,\s*70vh\);[\s\S]*min-block-size:\s*min\(520px,\s*70dvh\);/);
    assert.match(css, /body\.student-app-page\s*\{[^}]*padding:\s*max\([^;]+safe-area-inset-top[^;]+safe-area-inset-right[^;]+safe-area-inset-bottom[^;]+safe-area-inset-left[^;]+;/s);
    assert.match(css, /@media\s*\(min-width:\s*48rem\)[\s\S]*?body\.student-app-page\s*\{[^}]*padding-inline:\s*max\([^;]+safe-area-inset-left[^;]+max\([^;]+safe-area-inset-right[^;]+;/s);
    assert.doesNotMatch(css, /\.student-app-state\s*\{[^}]*grid-template-columns\s*:/s);
    assert.match(css, /\.student-app-install-overlay\s*\{[^}]*position:\s*fixed[^}]*z-index:\s*20/s);
    assert.match(css, /\.student-app-install-link\s*\{[^}]*min-block-size:\s*44px/s);
    assert.match(css, /\[data-install-guide\]\[hidden\]\s*\{[^}]*display:\s*none\s*!important/s);
  });

  check('Authenticated public student page preserves the mobile shell ratio', () => {
    assert.match(studentHtml, /viewport-fit=cover/);
    assert.match(studentHtml, /rel=["']manifest["'][^>]+href=["']\/manifest\.webmanifest["']/i);
    assert.match(studentHtml, /id=["']setBtn["'][^>]+aria-controls=["']setPanel["'][^>]+aria-expanded=["']false["']/i);
    assert.match(studentHtml, /apple-mobile-web-app-capable["'][^>]+content=["']yes["']/i);
    assert.match(studentHtml, /rel=["']apple-touch-icon["'][^>]+href=["']\/icons\/student-app-192\.png["']/i);
    assert.match(studentJs, /classList\.toggle\(['"]student-app-mobile-surface['"],\s*STUDENT_APP_PUBLIC_MODE\)/);
    assert.match(studentJs, /function\s+setSettingsPanelOpen\s*\(/);
    assert.match(studentCss, /body\.student-page\.student-app-mobile-surface\s+\.student-shell\s*\{[^}]*width:\s*min\(100%,\s*32rem\)/s);
    assert.match(studentCss, /body\.student-page\s+#player\s*\{[^}]*min-height:\s*280px/s);
    assert.match(studentCss, /body\.student-page\.student-app-mobile-surface\s+#player\s*\{[^}]*height:\s*auto[^}]*aspect-ratio:\s*16\s*\/\s*9[^}]*min-height:\s*0/s);
    assert.match(studentCss, /body\.student-page\.student-app-mobile-surface\s*\{[^}]*box-sizing:\s*border-box[^}]*margin:\s*0/s);
    assert.match(studentCss, /student-app-mobile-surface\s+\.student-session-recovery\s*\{[^}]*width:\s*min\(100%,\s*32rem\)/s);
    assert.match(studentCss, /@media\s*\(orientation:\s*landscape\)\s*and\s*\(max-height:[^)]+\)[\s\S]*#announceModal\s+\.announce-card\s*\{[\s\S]*overflow-y:\s*auto\s*!important/s);
  });

  check('JS contains the full typed state contract', () => {
    for (const state of ['signed_out', 'activation_code_required', 'credentials_required', 'push_required', 'unsupported_bypass', 'ready', 'error']) {
      assertIncludes(js, `'${state}'`, `JS state ${state}`);
    }
    assert.match(js, /export\s+(?:async\s+)?function\s+createStudentApp/);
    assert.match(js, /student-app-state/);
    assert.match(js, /focus\(\)/);
    assert.match(js, /aria-live/);
    assert.match(js, /export\s+function\s+initInstallGuide/);
    assert.match(js, /detectInstallEnvironment/);
    assert.match(js, /environment\.standalone/);
    assert.match(js, /bootStudentAppShell\(\);/);
    const installGuideScope = js.slice(js.indexOf('export function initInstallGuide'), js.indexOf('function element'));
    assert.doesNotMatch(installGuideScope, /\n\s*open\(\);\s*\n\s*return Object\.freeze/, 'install guide must not open during shell boot');
    const bootScope = js.slice(js.indexOf('export function bootStudentAppShell'), js.indexOf('function bootBrowserShell'));
    assert.doesNotMatch(bootScope, /\.open\s*\(/, 'browser shell boot must not open the install guide');
    const browserBootScope = js.slice(js.indexOf('function bootBrowserShell'), js.indexOf("if (typeof document !== 'undefined')"));
    assert.doesNotMatch(browserBootScope, /\.open\s*\(/, 'browser auto-boot wrapper must not open the install guide');
  });

  check('Auth flow exposes staged, validatable form semantics', () => {
    assert.match(js, /student-app-steps/);
    assert.match(js, /student-app-form/);
    assert.match(js, /addEventListener\(['"]submit['"]/);
    assert.match(js, /checkValidity\(\)/);
    assert.match(js, /reportValidity\(\)/);
    assert.match(css, /\.student-app-steps\s*\{/);
    assert.match(css, /\.student-app-form\s*\{/);
  });

  check('Public student home exposes an authoritative daily overview', () => {
    const studentDataScopeStart = studentJs.indexOf('/* ───────────── 공통 util ───────────── */');
    const studentDataScopeEnd = studentJs.indexOf('/* STUDENT_APP_ANNOUNCEMENT_DEEP_LINK_START */');
    assert.ok(studentDataScopeStart >= 0 && studentDataScopeEnd > studentDataScopeStart);
    const studentDataScope = studentJs.slice(studentDataScopeStart, studentDataScopeEnd);
    assert.match(studentHtml, /id=["']studentTodayOverview["'][^>]*hidden/i);
    assert.match(studentHtml, /<main\b[^>]*id=["']studentMain["'][^>]*>[\s\S]*?id=["']studentTodayOverview["']/i);
    assert.match(studentHtml, /id=["']studentTodaySummary["'][^>]*role=["']status["']/i);
    assert.match(studentHtml, /aria-label=["']오늘 학습 빠른 이동["']/i);
    assert.match(studentHtml, /id=["']studentVideoPanel["']/i);
    assert.match(studentDataScope, /function\s+renderStudentTodayOverview\s*\(/);
    assert.match(studentDataScope, /if\s*\(!STUDENT_APP_PUBLIC_MODE\)\s*return/);
    assert.match(studentDataScope, /homeworkBooksCache/);
    assert.match(studentDataScope, /assignedTestsCache/);
    assert.match(studentDataScope, /student-app:announcement-summary/);
    assert.match(studentDataScope, /summary\.textContent\s*!==\s*nextSummary/);
    assert.doesNotMatch(studentJs.slice(studentDataScopeEnd), /function\s+renderStudentTodayOverview\s*\(/);
    assert.match(studentCss, /body\.student-page\.student-app-mobile-surface\s+\.student-today-overview\s*\{/s);
  });

  check('Authenticated student controls keep semantic labels and touch targets', () => {
    assert.match(studentHtml, /<h1\b[^>]*id=["']stuName["']/i);
    assert.match(studentHtml, /id=["']setPanel["'][^>]+aria-labelledby=["']studentSettingsTitle["']/i);
    assert.match(studentHtml, /id=["']setPanelClose["'][^>]+aria-label=["']설정 닫기["']/i);
    assert.match(studentHtml, /<label[^>]+for=["']feedbackBox["'][^>]*>건의사항<\/label>/i);
    assert.match(studentHtml, /<iframe[^>]+id=["']player["'][^>]+title=["']학생 학습 영상["']/i);
    assert.match(studentJs, /createElement\(['"]button['"]\)[\s\S]*?className\s*=\s*['"]video-row-action['"]/);
    assert.match(studentCss, /\.video-row-action\s*\{[^}]*min-height:\s*44px/s);
    assert.match(studentCss, /\.student-settings-close\s*\{[^}]*color:\s*var\(--stu-text\)[^}]*box-shadow:\s*none/s);
    assert.match(studentCss, /body\.student-page\.student-app-mobile-surface\s+:where\([\s\S]*?#setPanel button,[\s\S]*?#announceModal button[\s\S]*?\)\s*\{[^}]*min-height:\s*44px/s);
    assert.match(studentCss, /\.announce-image-dots\s+button\s*\{[^}]*width:\s*24px[^}]*height:\s*24px/s);
    assert.match(studentCss, /--stu-on-accent:\s*#(?:ffffff|0d1219)/i);
    assert.match(studentCss, /#vidList\s+li\.active\s*\{[^}]*color:\s*var\(--stu-on-accent\)\s*!important/s);
    assert.match(studentCss, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  });

  check('Announcement dialogs isolate and restore keyboard focus', () => {
    assert.match(studentHtml, /id=["']announceModal["'][^>]+aria-hidden=["']true["']/i);
    assert.match(studentHtml, /id=["']annModalHeading["'][^>]+tabindex=["']-1["']/i);
    assert.match(studentJs, /function\s+trapDialogFocus\s*\(/);
    assert.match(studentJs, /!controls\.includes\(document\.activeElement\)/);
    assert.match(studentJs, /toggleAttribute\(['"]inert['"],\s*dialogOpen\)/);
    assert.match(studentJs, /function\s+openAnnouncementDialog\s*\(/);
    assert.match(studentJs, /function\s+closeAnnouncementDialog\s*\(/);
    assert.match(studentJs, /modal\.addEventListener\(['"]keydown['"]/);
    assert.match(studentJs, /historyModal\.addEventListener\(['"]keydown['"]/);
  });

  check('DOM state matrix exposes one role/action and moves focus', () => {
    const { createStudentApp, normalizeState, STATES } = appExports;
    assert.equal(JSON.stringify(STATES), JSON.stringify(['signed_out', 'activation_code_required', 'credentials_required', 'push_required', 'unsupported_bypass', 'ready', 'error']));
    assert.equal(normalizeState({ status: 'ready', sessionSid: '../secret' }).status, 'error');
    for (const state of STATES) {
      const documentRef = new FakeDocument();
      const app = createStudentApp({ document: documentRef, root: documentRef.root, autoBootstrap: false, pushGate: { assess: async value => value, activate: async value => value }, initialState: state === 'ready' ? { status: state, sessionSid: 'student-1' } : { status: state } });
      const section = documentRef.root.children[0];
      assert.equal(section.dataset.state, state);
      assert.equal(section.getAttribute('role'), 'region');
      assert.equal(section.getAttribute('aria-labelledby'), 'student-app-state-title');
      assert.equal(section.querySelectorAll('[data-primary-action]').length, 1);
      assert.equal(section.querySelector('[data-app-status]').getAttribute('role'), 'status');
      assert.equal(section.querySelector('[data-app-status]').getAttribute('aria-live'), 'polite');
      assert.ok(documentRef.activeElement === section.querySelector('[data-primary-action]') || documentRef.activeElement?.id === 'student-id' || documentRef.activeElement?.id === 'activation-code' || documentRef.activeElement?.id === 'credentials-id');
      app.destroy();
    }
  });

  await checkAsync('Injected adapter drives ready navigation and malformed responses to retry', async () => {
    const { createStudentApp } = appExports;
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
    const pushGate = { assess: async value => value, activate: async value => value };
    const app = createStudentApp({ document: documentRef, root: documentRef.root, autoBootstrap: false, api, pushGate, navigate: (url) => navigated.push(url), initialState: { status: 'signed_out' } });
    await documentRef.root.querySelector('[data-primary-action]').click();
    assert.equal(app.getState().status, 'ready');
    await documentRef.root.querySelector('[data-primary-action]').click();
    assert.deepEqual(navigated, ['/student/student-1']);
    app.destroy();

    const malformedDocument = new FakeDocument();
    const malformedApi = { ...api, signIn: async () => ({ status: 'ready' }) };
    const malformedApp = createStudentApp({ document: malformedDocument, root: malformedDocument.root, autoBootstrap: false, api: malformedApi, pushGate, initialState: { status: 'signed_out' } });
    await malformedDocument.root.querySelector('[data-primary-action]').click();
    assert.equal(malformedApp.getState().status, 'error');
    assert.equal(malformedDocument.root.querySelectorAll('[data-primary-action]').length, 1);
    assert.equal(malformedDocument.root.querySelector('[data-primary-action]').dataset.primaryAction, 'retry');
    malformedApp.destroy();
  });

  check('JS limits production URLs to the mobile/auth/push/student contracts', () => {
    const urls = [...allAppJs.matchAll(/['"`]\/(?:api|student)[^'"`]*/g)].map((match) => match[0]);
    assert.ok(urls.length > 0, 'expected at least one production URL contract');
    for (const url of urls) {
      assert.match(url, /^['"`]\/(?:api\/mobile\/(?:auth|push)\/|student\/)/, `URL contract ${url}`);
    }
    assert.doesNotMatch(allAppJs, /localStorage|sessionStorage|indexedDB/i);
    assert.match(allAppJs, /requestPermission:\s*\(\)\s*=>\s*windowRef\.Notification\.requestPermission\(\)/);
    assert.match(allAppJs, /activate[\s\S]*platform\.requestPermission\(\)/);
    assert.doesNotMatch(allAppJs.slice(allAppJs.indexOf('async function assess'), allAppJs.indexOf('async function activate')), /requestPermission\(/);
  });

  check('Manifest is standalone, scoped, localized, and responsive', () => {
    assert.equal(manifest.start_url, '/app');
    assert.equal(manifest.scope, '/');
    assert.equal(manifest.display, 'standalone');
    assert.equal(manifest.lang, 'ko');
    assert.equal(manifest.orientation, 'any');
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
    assert.match(sw, /student-app-shell-v11/);
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
    for (const moduleUrl of ['/js/student-app-api.js', '/js/student-app-contract.js', '/js/student-app-push.js']) assert.ok(installed.includes(moduleUrl));
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
        keys: async () => ['other-app-cache', 'student-app-shell-v0', 'student-app-shell-v1', 'student-app-shell-v2'],
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
    assert.deepEqual(deleted, ['student-app-shell-v0', 'student-app-shell-v1', 'student-app-shell-v2']);
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
  await fs.mkdir(path.dirname(SHELL_ARTIFACT), { recursive: true });
  await fs.writeFile(SHELL_ARTIFACT, `${JSON.stringify(artifact, null, 2)}\n`, 'utf8');
  return artifact;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const result = await runShellChecks();
    console.log(`student-mobile-app shell: ${result.checks} assertions passed`);
    console.log(`artifact: ${path.relative(root, SHELL_ARTIFACT)}`);
  } catch (error) {
    console.error(`student-mobile-app shell: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
