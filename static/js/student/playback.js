(function studentPlaybackModule(global) {
  'use strict';

  const DEFAULT_DONE_RATIO = 0.90;
  const BRIDGE_INTERVAL_MS = 100;
  const BRIDGE_MAX_TRIES = 200;
  const PROGRESS_POLL_MS = 3000;

  function requireFunction(value, name) {
    if (typeof value !== 'function') throw new TypeError(`${name} must be a function`);
    return value;
  }

  function withStartParam(url, seconds, options = {}) {
    if (!seconds || seconds < 5) return url;
    const URLImpl = options.URLImpl || global.URL;
    const origin = options.origin || global.location?.origin || '';
    try {
      const parsed = new URLImpl(url, origin);
      if (!parsed.searchParams.has('start')) parsed.searchParams.set('start', Math.floor(seconds));
      if (!parsed.searchParams.has('t')) parsed.searchParams.set('t', Math.floor(seconds));
      return parsed.toString();
    } catch {
      if (!/#t=\d+/.test(url)) return `${url}#t=${Math.floor(seconds)}`;
      return url;
    }
  }

  function createController(options = {}) {
    const globalRef = options.globalRef || global;
    const locationRef = options.locationRef || globalRef.location || {};
    const getFrame = requireFunction(options.getFrame, 'getFrame');
    const getSid = requireFunction(options.getSid, 'getSid');
    const canPlay = requireFunction(options.canPlay, 'canPlay');
    const showRestrictedNotice = requireFunction(options.showRestrictedNotice, 'showRestrictedNotice');
    const showLoadFailure = requireFunction(options.showLoadFailure, 'showLoadFailure');
    const flushWatch = requireFunction(options.flushWatch, 'flushWatch');
    const setLastMid = requireFunction(options.setLastMid, 'setLastMid');
    const getProgress = requireFunction(options.getProgress, 'getProgress');
    const setProgress = requireFunction(options.setProgress, 'setProgress');
    const request = requireFunction(options.request, 'request');
    const setIntervalImpl = requireFunction(options.setIntervalImpl, 'setIntervalImpl');
    const clearIntervalImpl = requireFunction(options.clearIntervalImpl, 'clearIntervalImpl');
    const setTimeoutImpl = requireFunction(options.setTimeoutImpl, 'setTimeoutImpl');
    const encode = requireFunction(options.encodeURIComponentImpl, 'encodeURIComponentImpl');
    const URLImpl = options.URLImpl || globalRef.URL;
    if (typeof URLImpl !== 'function') throw new TypeError('URLImpl must be a constructor');
    if (typeof globalRef.addEventListener !== 'function') {
      throw new TypeError('globalRef must implement addEventListener');
    }
    if (typeof globalRef.postMessage !== 'function') {
      throw new TypeError('globalRef must implement postMessage');
    }

    const doneRatio = Number.isFinite(Number(options.doneRatio))
      ? Number(options.doneRatio)
      : DEFAULT_DONE_RATIO;
    const log = typeof options.log === 'function' ? options.log : () => {};
    const warn = typeof options.warn === 'function' ? options.warn : () => {};
    const reportError = typeof options.reportError === 'function' ? options.reportError : () => {};
    let activeMid = null;

    function currentMid() {
      return activeMid;
    }

    function repost(type, mid, payload) {
      globalRef.postMessage({ type, mid, ...payload }, '*');
    }

    function attachKollusBridgeToIframe(frameEl, mid, resumeAtSec) {
      if (!frameEl) return;
      if (frameEl.__vgAttached && frameEl.__vgAttached === mid) return;

      let tries = 0;
      const intervalId = setIntervalImpl(() => {
        tries += 1;
        const available = !!(globalRef.VgControllerClient && frameEl.contentWindow);
        if (!available && tries < BRIDGE_MAX_TRIES) return;
        clearIntervalImpl(intervalId);
        if (!available) {
          warn('[KollusBridge] VgControllerClient not available (timeout)');
          return;
        }

        try {
          const controller = new globalRef.VgControllerClient({ target_window: frameEl.contentWindow });
          let lastSent = 0;

          controller.on('ready', function () {
            repost('kollus.ready', mid, {});
            if (typeof controller.seek === 'function' && Number(resumeAtSec) > 5) {
              try { controller.seek(Math.floor(resumeAtSec)); } catch { }
            }

            const poll = async () => {
              try {
                const position = await controller.getPosition?.();
                const duration = await controller.getDuration?.();
                if (Number.isFinite(position) && Number.isFinite(duration) && duration > 0) {
                  const percent = (position / duration) * 100;
                  const ended = percent >= 90 || position >= duration - 1;
                  if (Math.abs(position - lastSent) >= 1) {
                    repost('kollus.progress', mid, {
                      currentTime: position,
                      duration,
                      ended,
                    });
                    lastSent = position;
                  }
                }
              } catch { }
              setTimeoutImpl(poll, PROGRESS_POLL_MS);
            };
            poll();
          });

          controller.on('progress', function (percent, position, duration) {
            repost('kollus.progress', mid, {
              currentTime: Number(position) || 0,
              duration: Number(duration) || 0,
              ended: false,
            });
          });

          controller.on('done', function () {
            repost('kollus.progress', mid, { ended: true });
          });

          controller.on('play', async function () {
            try {
              const position = await controller.getPosition?.();
              const duration = await controller.getDuration?.();
              if (Number.isFinite(position) && Number.isFinite(duration)) {
                repost('kollus.progress', mid, {
                  currentTime: position,
                  duration,
                  ended: false,
                });
              }
            } catch { }
          });

          controller.on('pause', async function () {
            try {
              const position = await controller.getPosition?.();
              const duration = await controller.getDuration?.();
              if (Number.isFinite(position) && Number.isFinite(duration)) {
                repost('kollus.progress', mid, {
                  currentTime: position,
                  duration,
                  ended: false,
                });
              }
            } catch { }
          });

          frameEl.__vgAttached = mid;
          log('[KollusBridge] attached for', mid);
        } catch (error) {
          warn('[KollusBridge] init failed:', error);
        }
      }, BRIDGE_INTERVAL_MS);
    }

    function handleMessage(event) {
      if (event?.source !== globalRef) return;
      const data = event?.data;
      if (!data || typeof data !== 'object') return;
      const mid = String(data.mid ?? '').trim();
      const current = String(activeMid ?? '').trim();
      if (!mid || !current || mid !== current) return;

      if (data.type === 'kollus.ready' && Number.isFinite(Number(data.duration))) {
        setProgress(mid, { dur: Number(data.duration) || undefined });
      }
      if (data.type === 'kollus.progress') {
        const position = Math.max(0, Number(data.currentTime) || 0);
        const duration = Math.max(0, Number(data.duration) || 0);
        const ended = !!data.ended || (duration > 0 && position >= duration - 1);
        const percent = duration > 0 ? (position / duration) : 0;
        setProgress(mid, {
          last: position,
          dur: duration,
          completed: (ended || percent >= doneRatio) || undefined,
        });
      }
    }

    async function play(mid) {
      if (!canPlay()) {
        showRestrictedNotice();
        return;
      }
      if (activeMid && activeMid !== mid) flushWatch();
      activeMid = mid;
      setLastMid(mid);
      const frame = getFrame();
      if (frame) frame.src = '';

      const progress = getProgress(mid);
      const resumeAt = progress?.last || 0;

      try {
        const response = await request(`/api/get-url?mid=${encode(mid)}&sid=${encode(getSid())}`);
        if (!response.ok) {
          if (response.status === 403) showRestrictedNotice();
          throw new Error(response.status === 403 ? 'academy-network-required' : `get-url ${response.status}`);
        }
        let baseUrl = await response.text();
        log('[play] baseUrl from server =', baseUrl);

        if (locationRef.protocol === 'https:' && /^http:\/\//i.test(baseUrl)) {
          baseUrl = baseUrl.replace(/^http:\/\//i, 'https://');
          log('[play] forced https url =', baseUrl);
        }

        const urlWithStart = withStartParam(baseUrl, resumeAt, {
          URLImpl,
          origin: locationRef.origin,
        });
        if (frame) {
          frame.onload = () => attachKollusBridgeToIframe(frame, mid, resumeAt);
          frame.src = urlWithStart;
        }
      } catch (error) {
        reportError(error);
        if (error?.message === 'academy-network-required') return;
        showLoadFailure();
      }
    }

    globalRef.addEventListener('message', handleMessage);

    return Object.freeze({
      attachKollusBridgeToIframe,
      currentMid,
      play,
    });
  }

  global.StudentPlayback = Object.freeze({
    createController,
    withStartParam,
  });
})(window);
