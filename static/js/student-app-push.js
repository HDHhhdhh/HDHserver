import { normalizeState } from './student-app-contract.js';

function normalizedCapabilities(value) {
  const source = value && typeof value === 'object' ? value : {};
  return Object.fromEntries(['serviceWorker', 'pushManager', 'notification', 'standalone'].map(key => [key, source[key] === true]));
}

function supported(capabilities) {
  return capabilities.serviceWorker && capabilities.pushManager && capabilities.notification;
}

function revoked(error) {
  return Number(error?.status) === 401 || error?.code === 'unauthenticated';
}

function sessionSeed(state, capabilities) {
  return `session:${state.sessionSid}|sw:${Number(capabilities.serviceWorker)}|pm:${Number(capabilities.pushManager)}|nt:${Number(capabilities.notification)}|sa:${Number(capabilities.standalone)}`;
}

function subscriptionBody(subscription) {
  const raw = typeof subscription?.toJSON === 'function' ? subscription.toJSON() : subscription;
  const endpoint = typeof raw?.endpoint === 'string' ? raw.endpoint : '';
  const p256dh = typeof raw?.keys?.p256dh === 'string' ? raw.keys.p256dh : '';
  const auth = typeof raw?.keys?.auth === 'string' ? raw.keys.auth : '';
  if (!endpoint || !p256dh || !auth) throw new Error('invalid subscription');
  return { endpoint, keys: { p256dh, auth } };
}

function pending(state, capabilities, mode, extra = {}) {
  const installation = ['ios_install', 'manual_install', 'install_dismissed', 'install_complete'].includes(mode);
  return normalizeState({ ...state, ...extra, status: installation || supported(capabilities) ? 'push_required' : 'unsupported_bypass', pushMode: mode, capabilities });
}

function ready(state, extra = {}) {
  return normalizeState({ ...state, ...extra, status: 'ready' });
}

function signedOut() {
  return { status: 'signed_out' };
}

function capabilityLabel(expiresAt, now) {
  const hours = Math.max(1, Math.ceil((expiresAt - now) / 3600));
  return `알림 미지원 · 서버 우회 ${hours}시간 남음`;
}

export function createPushGate({ api, platform, now = () => Date.now() / 1000 }) {
  if (!api || !platform) throw new Error('push gate dependencies are required');

  async function context(state, capabilities) {
    let registration = null;
    let subscription = null;
    if (capabilities.serviceWorker) registration = await platform.register();
    if (registration && capabilities.pushManager) subscription = await platform.getSubscription(registration);
    const seed = subscription?.endpoint || sessionSeed(state, capabilities);
    return { registration, subscription, deviceId: await platform.deviceId(seed) };
  }

  async function statusFor(state, capabilities) {
    const selected = await context(state, capabilities);
    const status = await api.getPushStatus(selected.deviceId);
    return { ...selected, status };
  }

  async function assess(input) {
    const state = normalizeState(input);
    if (state.status !== 'ready') return state;
    const capabilities = normalizedCapabilities(platform.capabilities());
    if (platform.isIos && !capabilities.standalone) {
      return pending(state, capabilities, 'ios_install', { message: 'Safari 공유 메뉴에서 홈 화면에 추가한 뒤 설치된 앱을 다시 열어 주세요.' });
    }
    if (!platform.isMobile && supported(capabilities) && !capabilities.standalone) {
      return ready(state, {
        capabilities,
        notificationState: 'browser',
        notificationLabel: '브라우저에서 이용 중 · 앱 설치 없이 사용 가능',
      });
    }
    if (supported(capabilities) && !capabilities.standalone && !platform.hasInstallPrompt()) {
      return pending(state, capabilities, 'manual_install', { message: '브라우저 메뉴에서 홈 화면에 설치한 뒤 앱을 다시 열어 주세요.' });
    }
    try {
      const selected = await statusFor(state, capabilities);
      const expiry = Number(selected.status?.bypassExpiresAt);
      if (!supported(capabilities)) {
        if (Number.isFinite(expiry) && expiry > now()) return ready(state, { capabilities, deviceId: selected.deviceId, bypassExpiresAt: expiry, notificationState: 'unsupported', notificationLabel: capabilityLabel(expiry, now()) });
        return pending(state, capabilities, 'unsupported', { deviceId: selected.deviceId, message: '이 기기는 웹 알림을 지원하지 않아 24시간 기본 방식으로 계속할 수 있습니다.' });
      }
      const permission = platform.notificationPermission();
      if (selected.subscription && permission === 'granted') {
        if (!selected.status?.subscribed) await api.subscribePush({ deviceId: selected.deviceId, subscription: subscriptionBody(selected.subscription) }, state.csrfToken || '');
        return ready(state, { capabilities, deviceId: selected.deviceId, notificationState: 'granted', notificationLabel: '학습 알림 켜짐' });
      }
      const mode = permission === 'denied' ? 'permission_denied' : 'permission_default';
      return pending(state, capabilities, mode, { deviceId: selected.deviceId, notificationState: permission });
    } catch (error) {
      return revoked(error) ? signedOut() : pending(state, capabilities, 'retry', { message: '알림 상태를 확인하지 못했습니다. 다시 시도해 주세요.' });
    }
  }

  async function activate(input) {
    const state = normalizeState(input);
    const capabilities = normalizedCapabilities(platform.capabilities());
    if (platform.isIos && !capabilities.standalone) return pending(state, capabilities, 'ios_install', { message: 'Safari 공유 메뉴의 “홈 화면에 추가”를 완료한 뒤 설치된 앱에서 다시 확인해 주세요.' });
    if (!supported(capabilities)) {
      try {
        const deviceId = state.deviceId || await platform.deviceId(sessionSeed(state, capabilities));
        const result = await api.bypassPush({ deviceId, capabilities }, state.csrfToken || '');
        const expiry = Number(result?.bypassExpiresAt);
        if (!Number.isFinite(expiry) || expiry <= now()) throw new Error('invalid bypass expiry');
        return ready(state, { capabilities, deviceId, bypassExpiresAt: expiry, notificationState: 'unsupported', notificationLabel: capabilityLabel(expiry, now()) });
      } catch (error) {
        return revoked(error) ? signedOut() : pending(state, capabilities, 'retry', { message: '기본 방식 연결을 확인하지 못했습니다. 다시 시도해 주세요.' });
      }
    }
    if (!capabilities.standalone) {
      if (!platform.hasInstallPrompt()) return pending(state, capabilities, 'manual_install', { message: '브라우저 메뉴에서 홈 화면에 설치한 뒤 앱을 다시 열어 주세요.' });
      const outcome = await platform.promptInstall();
      if (outcome !== 'accepted') return pending(state, capabilities, 'install_dismissed', { message: '설치를 완료해야 학습 알림을 설정할 수 있습니다.' });
      return pending(state, capabilities, 'install_complete', { message: '설치가 완료되었습니다. 홈 화면의 학생 앱을 열고 알림 설정을 계속해 주세요.' });
    }
    try {
      let permission = platform.notificationPermission();
      if (permission === 'denied') return pending(state, capabilities, 'permission_denied', { notificationState: permission, message: '브라우저 설정에서 이 사이트의 알림을 허용한 뒤 다시 시도해 주세요.' });
      if (permission === 'default') permission = await platform.requestPermission();
      if (permission !== 'granted') {
        const mode = permission === 'denied' ? 'permission_denied' : 'permission_default';
        const message = permission === 'denied' ? '브라우저 설정에서 이 사이트의 알림을 허용한 뒤 다시 시도해 주세요.' : '알림 허용을 완료하지 않았습니다. 다시 눌러 설정해 주세요.';
        return pending(state, capabilities, mode, { notificationState: permission, message });
      }
      const registration = await platform.register();
      let subscription = await platform.getSubscription(registration);
      if (!subscription) subscription = await platform.subscribe(registration, await api.getPushPublicKey());
      const body = subscriptionBody(subscription);
      const deviceId = await platform.deviceId(body.endpoint);
      await api.subscribePush({ deviceId, subscription: body }, state.csrfToken || '');
      return ready(state, { capabilities, deviceId, notificationState: 'granted', notificationLabel: '학습 알림 켜짐' });
    } catch (error) {
      return revoked(error) ? signedOut() : pending(state, capabilities, 'retry', { notificationState: platform.notificationPermission(), message: '알림 구독에 실패했습니다. 연결과 브라우저 설정을 확인한 뒤 다시 시도해 주세요.' });
    }
  }

  return Object.freeze({ assess, activate });
}

function iosDevice(navigatorRef) {
  const ua = String(navigatorRef?.userAgent || '');
  return /iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && Number(navigatorRef?.maxTouchPoints) > 1);
}

export function detectInstallEnvironment(windowRef = window) {
  const navigatorRef = windowRef?.navigator;
  const ua = String(navigatorRef?.userAgent || '');
  const brands = Array.isArray(navigatorRef?.userAgentData?.brands)
    ? navigatorRef.userAgentData.brands.map(item => String(item?.brand || '')).join(' ')
    : '';
  const ios = iosDevice(navigatorRef);
  const platform = ios ? 'ios'
    : /Android/i.test(ua) ? 'android'
      : /Windows/i.test(ua) ? 'windows'
        : /CrOS/i.test(ua) ? 'chromeos'
          : /Macintosh|Mac OS X/i.test(ua) ? 'macos'
            : /Linux/i.test(ua) ? 'linux'
              : 'other';
  const inApp = /;\s*wv\)|Instagram|FBAN|FBAV|KAKAOTALK|NAVER\(inapp/i.test(ua);
  const browser = inApp ? 'in_app'
    : /EdgiOS|EdgA|Edg\//i.test(ua) || /Microsoft Edge/i.test(brands) ? 'edge'
      : /SamsungBrowser/i.test(ua) ? 'samsung'
        : /CriOS|Chrome|Chromium/i.test(ua) || /Google Chrome|Chromium/i.test(brands) ? 'chrome'
          : /FxiOS|Firefox/i.test(ua) ? 'firefox'
            : /Safari/i.test(ua) && /AppleWebKit/i.test(ua) ? 'safari'
              : 'other';
  const standalone = windowRef?.matchMedia?.('(display-mode: standalone)')?.matches === true
    || navigatorRef?.standalone === true;
  return Object.freeze({ platform, browser, standalone, mobile: ios || platform === 'android' || /Mobile/i.test(ua) });
}

function base64Url(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function applicationServerKey(value) {
  const normalized = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
  const raw = atob(padded);
  return Uint8Array.from(raw, character => character.charCodeAt(0));
}

export function createBrowserPushPlatform(windowRef = window) {
  const navigatorRef = windowRef.navigator;
  let installEvent = null;
  let installationNotified = false;
  const installedListeners = new Set();
  const notifyInstalled = () => {
    installEvent = null;
    if (installationNotified) return;
    installationNotified = true;
    for (const listener of [...installedListeners]) {
      try { listener(); } catch { /* installation state remains authoritative */ }
    }
  };
  windowRef.addEventListener?.('beforeinstallprompt', event => {
    event.preventDefault();
    if (!installationNotified) installEvent = event;
  });
  windowRef.addEventListener?.('appinstalled', notifyInstalled);
  const displayMode = windowRef.matchMedia?.('(display-mode: standalone)');
  const onDisplayModeChange = event => { if (event?.matches === true) notifyInstalled(); };
  if (typeof displayMode?.addEventListener === 'function') displayMode.addEventListener('change', onDisplayModeChange);
  else if (typeof displayMode?.addListener === 'function') displayMode.addListener(onDisplayModeChange);
  const standalone = () => windowRef.matchMedia?.('(display-mode: standalone)')?.matches === true || navigatorRef.standalone === true;
  const environment = detectInstallEnvironment(windowRef);
  return Object.freeze({
    isIos: environment.platform === 'ios',
    isMobile: environment.mobile,
    installEnvironment: () => detectInstallEnvironment(windowRef),
    capabilities: () => ({ serviceWorker: !!navigatorRef.serviceWorker, pushManager: typeof windowRef.PushManager !== 'undefined', notification: typeof windowRef.Notification !== 'undefined', standalone: standalone() }),
    hasInstallPrompt: () => installEvent !== null,
    promptInstall: async () => { if (!installEvent) return 'unavailable'; const event = installEvent; installEvent = null; await event.prompt(); return (await event.userChoice)?.outcome || 'dismissed'; },
    onInstalled: listener => {
      if (typeof listener !== 'function') return () => {};
      installedListeners.add(listener);
      return () => installedListeners.delete(listener);
    },
    register: () => navigatorRef.serviceWorker.register('/sw.js', { scope: '/' }),
    getSubscription: registration => registration.pushManager.getSubscription(),
    notificationPermission: () => windowRef.Notification?.permission || 'unsupported',
    requestPermission: () => windowRef.Notification.requestPermission(),
    subscribe: (registration, key) => registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: applicationServerKey(key) }),
    deviceId: async seed => {
      const subtle = windowRef.crypto?.subtle;
      if (!subtle) throw new Error('secure digest unavailable');
      const digest = await subtle.digest('SHA-256', new TextEncoder().encode(`student-app-device:v1:${seed}`));
      return base64Url(new Uint8Array(digest));
    },
  });
}
