(function studentFocusModule(global) {
  'use strict';

  const SESSION_ID = /^fcs_[A-Za-z0-9_-]{24,64}$/;
  const SESSION_STATES = new Set(['active', 'finished', 'unknown']);
  const VISIBILITY_STATES = new Set(['visible', 'hidden', 'unknown']);
  const ELIGIBILITY_STATES = new Set(['eligible', 'upcoming', 'unavailable']);
  const SCHEDULE_KINDS = new Set(['regular', 'extra', 'makeup']);
  const SESSION_KEYS = ['endedAt', 'focusMs', 'hiddenCount', 'hiddenMs', 'id', 'lastSeq', 'longestHiddenMs', 'schedule', 'startedAt', 'state', 'unknownMs', 'visibility'];

  class FocusRequestError extends Error {
    constructor(code, status = 0) {
      super(code || 'focus_unavailable');
      this.name = 'FocusRequestError';
      this.code = code || 'focus_unavailable';
      this.status = Number(status) || 0;
    }
  }

  function exactKeys(value, keys) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    const actual = Object.keys(value).sort();
    const expected = [...keys].sort();
    return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
  }

  function iso(value, nullable = false) {
    if (nullable && value === null) return null;
    const text = typeof value === 'string' ? value.trim() : '';
    return text && Number.isFinite(Date.parse(text)) ? text : '';
  }

  function count(value) {
    return Number.isSafeInteger(value) && value >= 0 ? value : null;
  }

  function normalizeSchedule(value) {
    const keys = ['date', 'endAt', 'kind', 'slots', 'startAt', 'timeLabel'];
    if (!exactKeys(value, keys) || !SCHEDULE_KINDS.has(value.kind)) return null;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value.date) || !/^\d{2}:\d{2}$/.test(value.timeLabel)) return null;
    if (!iso(value.startAt) || !iso(value.endAt) || Date.parse(value.endAt) <= Date.parse(value.startAt)) return null;
    if (!Array.isArray(value.slots) || value.slots.length < 1 || value.slots.length > 3) return null;
    if (value.slots.some((slot, index) => ![1, 2, 3].includes(slot) || value.slots.indexOf(slot) !== index)) return null;
    return Object.freeze({
      kind: value.kind, date: value.date, startAt: value.startAt, endAt: value.endAt,
      timeLabel: value.timeLabel, slots: Object.freeze([...value.slots]),
    });
  }

  function normalizeSession(value) {
    if (!exactKeys(value, SESSION_KEYS) || !SESSION_ID.test(value.id)) return null;
    if (!SESSION_STATES.has(value.state) || !VISIBILITY_STATES.has(value.visibility)) return null;
    if (!iso(value.startedAt) || iso(value.endedAt, true) === '' || !normalizeSchedule(value.schedule)) return null;
    const numeric = ['focusMs', 'hiddenCount', 'hiddenMs', 'lastSeq', 'longestHiddenMs', 'unknownMs'];
    if (numeric.some(key => count(value[key]) === null)) return null;
    return Object.freeze({
      id: value.id, state: value.state, startedAt: value.startedAt, endedAt: value.endedAt,
      lastSeq: value.lastSeq, visibility: value.visibility, focusMs: value.focusMs,
      hiddenCount: value.hiddenCount, hiddenMs: value.hiddenMs,
      longestHiddenMs: value.longestHiddenMs, unknownMs: value.unknownMs,
      schedule: normalizeSchedule(value.schedule),
    });
  }

  function normalizeCurrent(value) {
    if (!exactKeys(value, ['eligibility', 'ok', 'serverNow', 'session']) || value.ok !== true || !iso(value.serverNow)) return null;
    const eligibility = value.eligibility;
    if (!exactKeys(eligibility, ['closesAt', 'opensAt', 'schedule', 'state']) || !ELIGIBILITY_STATES.has(eligibility.state)) return null;
    const schedule = eligibility.schedule === null ? null : normalizeSchedule(eligibility.schedule);
    if (eligibility.schedule !== null && !schedule) return null;
    if ((eligibility.opensAt !== null && !iso(eligibility.opensAt)) || (eligibility.closesAt !== null && !iso(eligibility.closesAt))) return null;
    const session = value.session === null ? null : normalizeSession(value.session);
    if (value.session !== null && !session) return null;
    return Object.freeze({
      serverNow: value.serverNow,
      eligibility: Object.freeze({ state: eligibility.state, opensAt: eligibility.opensAt, closesAt: eligibility.closesAt, schedule }),
      session,
    });
  }

  function normalizeMutation(value, { start = false } = {}) {
    const keys = start ? ['ok', 'resumed', 'serverNow', 'session'] : ['ok', 'serverNow', 'session'];
    if (!exactKeys(value, keys) || value.ok !== true || (start && typeof value.resumed !== 'boolean') || !iso(value.serverNow)) return null;
    const session = normalizeSession(value.session);
    return session ? Object.freeze({ serverNow: value.serverNow, session, resumed: start ? value.resumed : false }) : null;
  }

  function formatDuration(milliseconds) {
    const seconds = Math.max(0, Math.floor(Number(milliseconds || 0) / 1000));
    if (seconds < 60) return `${seconds}초`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}분`;
    return `${Math.floor(minutes / 60)}시간 ${minutes % 60}분`;
  }

  async function responseBody(response) {
    try { return await response.json(); }
    catch { return null; }
  }

  function createController(options = {}) {
    const doc = options.documentRef || document;
    const win = options.windowRef || global;
    const request = options.request;
    const onSessionFailure = options.onSessionFailure || (() => false);
    const makeSessionError = options.makeSessionError || ((code, status) => new FocusRequestError(code, status));
    const clock = options.clock || (() => Date.now());
    if (typeof request !== 'function') throw new TypeError('focus request adapter is required');

    const byId = id => doc.getElementById(id);
    const launcher = byId('studentFocusLauncher');
    const startButton = byId('studentFocusStart');
    const launcherStatus = byId('studentFocusLauncherStatus');
    const modal = byId('studentFocusModal');
    const sheet = modal?.querySelector('.student-focus-sheet');
    const liveStatus = byId('studentFocusLiveStatus');
    let current = null;
    let serverOffset = 0;
    let nextSeq = 1;
    let predictedVisibility = 'visible';
    let queue = [];
    let sending = false;
    let flushPromise = null;
    let pendingKeepalive = false;
    let desynced = false;
    let ending = false;
    let opener = null;
    let timer = 0;

    function text(id, value) {
      const node = byId(id);
      if (node) node.textContent = String(value);
    }

    function activeSession() {
      return current?.session?.state === 'active' ? current.session : null;
    }

    function renderStats(session) {
      text('studentFocusTime', formatDuration(session?.focusMs));
      text('studentFocusHiddenCount', `${session?.hiddenCount || 0}회`);
      text('studentFocusHiddenTime', formatDuration(session?.hiddenMs));
      text('studentFocusLongestHidden', formatDuration(session?.longestHiddenMs));
    }

    function updateCountdown() {
      const session = activeSession();
      if (!session) {
        text('studentFocusRemaining', '--:--:--');
        return;
      }
      const remaining = Math.max(0, Date.parse(session.schedule.endAt) - (clock() + serverOffset));
      const total = Math.ceil(remaining / 1000);
      const hours = String(Math.floor(total / 3600)).padStart(2, '0');
      const minutes = String(Math.floor((total % 3600) / 60)).padStart(2, '0');
      const seconds = String(total % 60).padStart(2, '0');
      text('studentFocusRemaining', `${hours}:${minutes}:${seconds}`);
    }

    function render() {
      if (!launcher || !current) return;
      launcher.hidden = false;
      const session = current.session;
      const eligibility = current.eligibility;
      if (session?.state === 'active') {
        launcherStatus.textContent = '집중 세션이 진행 중입니다. 학습 화면으로 다시 열 수 있습니다.';
        startButton.disabled = false;
        startButton.textContent = '집중 화면 열기';
      } else if (session?.state === 'finished') {
        launcherStatus.textContent = '이번 수업의 집중 세션을 마쳤습니다.';
        startButton.disabled = true;
        startButton.textContent = '집중 완료';
      } else if (session?.state === 'unknown') {
        launcherStatus.textContent = '종료 시점을 확인하지 못해 일부 시간이 확인 불가로 남았습니다.';
        startButton.disabled = true;
        startButton.textContent = '확인 불가';
      } else if (eligibility.state === 'eligible') {
        launcherStatus.textContent = `${eligibility.schedule.date} ${eligibility.schedule.timeLabel} 수업 집중을 시작할 수 있습니다.`;
        startButton.disabled = false;
        startButton.textContent = '집중 시작';
      } else if (eligibility.state === 'upcoming') {
        launcherStatus.textContent = `${eligibility.schedule.date} ${eligibility.schedule.timeLabel} 수업 30분 전부터 시작할 수 있습니다.`;
        startButton.disabled = true;
        startButton.textContent = '시작 전';
      } else {
        launcherStatus.textContent = '지금 시작할 수 있는 수업 일정이 없습니다.';
        startButton.disabled = true;
        startButton.textContent = '일정 없음';
      }
      // An acknowledgement can arrive while later transitions are already queued.
      // Preserve that prediction until the queue drains so a rapid visibility
      // change is not mistaken for the just-acknowledged server state.
      if (!sending && queue.length === 0) {
        predictedVisibility = session?.visibility || predictedVisibility;
        nextSeq = session ? session.lastSeq + 1 : 1;
      }
      renderStats(session);
      updateCountdown();
    }

    function applyCurrent(payload) {
      current = payload;
      serverOffset = Date.parse(payload.serverNow) - clock();
      render();
    }

    function applySession(payload) {
      current = Object.freeze({
        serverNow: payload.serverNow,
        eligibility: current?.eligibility || Object.freeze({ state: 'unavailable', opensAt: null, closesAt: null, schedule: null }),
        session: payload.session,
      });
      serverOffset = Date.parse(payload.serverNow) - clock();
      render();
    }

    async function call(url, init = {}) {
      let response;
      try { response = await request(url, init); }
      catch (error) { throw error instanceof Error ? error : new FocusRequestError('focus_unavailable'); }
      const body = await responseBody(response);
      if (!response.ok) throw new FocusRequestError(String(body?.code || 'focus_unavailable'), response.status);
      return body;
    }

    function reportError(error) {
      if ((error?.status === 401 || error?.status === 403) && onSessionFailure(makeSessionError(error.code, error.status))) return;
      if (liveStatus) liveStatus.textContent = '연결을 확인하지 못했습니다. 학습 화면으로 돌아오면 다시 맞춥니다.';
    }

    async function postEvents(events, keepalive = false) {
      const session = activeSession();
      if (!session) return null;
      const body = await call('/api/mobile/focus/events', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, keepalive,
        body: JSON.stringify({ sessionId: session.id, events }),
      });
      const payload = normalizeMutation(body);
      if (!payload) throw new FocusRequestError('focus_malformed');
      applySession(payload);
      return payload.session;
    }

    function flush(keepalive = false) {
      if (keepalive) pendingKeepalive = true;
      if (flushPromise) return flushPromise;
      if (!activeSession() || queue.length === 0) return Promise.resolve();
      sending = true;
      flushPromise = (async () => {
        while (activeSession() && queue.length) {
          const batch = queue.slice(0, 50);
          const useKeepalive = pendingKeepalive;
          pendingKeepalive = false;
          try {
            await postEvents(batch, useKeepalive);
            queue.splice(0, batch.length);
            desynced = false;
          } catch (error) {
            queue = [];
            pendingKeepalive = false;
            desynced = true;
            reportError(error);
            break;
          }
        }
      })().finally(() => {
        sending = false;
        flushPromise = null;
      });
      return flushPromise;
    }

    function capture(type, keepalive = false) {
      if (ending || !activeSession() || !VISIBILITY_STATES.has(type) || type === predictedVisibility) return;
      if (queue.length >= 50) {
        queue = [];
        desynced = true;
        return;
      }
      queue.push({ seq: nextSeq, type });
      nextSeq += 1;
      predictedVisibility = type;
      void flush(keepalive);
    }

    async function repairUnknownBoundary() {
      const session = activeSession();
      if (!session) return;
      const events = [];
      let seq = session.lastSeq + 1;
      if (session.visibility !== 'unknown') events.push({ seq: seq++, type: 'unknown' });
      if (doc.visibilityState !== 'hidden') events.push({ seq: seq++, type: 'visible' });
      if (!events.length) return;
      const repaired = await postEvents(events);
      nextSeq = repaired.lastSeq + 1;
      predictedVisibility = repaired.visibility;
      desynced = false;
    }

    async function load({ repairActive = false } = {}) {
      try {
        const response = await request('/api/mobile/focus/current', { cache: 'no-store' });
        if (response.status === 404) {
          if (launcher) launcher.hidden = true;
          return null;
        }
        const body = await responseBody(response);
        if (!response.ok) throw new FocusRequestError(String(body?.code || 'focus_unavailable'), response.status);
        const payload = normalizeCurrent(body);
        if (!payload) throw new FocusRequestError('focus_malformed');
        applyCurrent(payload);
        if (repairActive && activeSession()) await repairUnknownBoundary();
        return payload;
      } catch (error) {
        reportError(error);
        if (launcher && !current) launcher.hidden = true;
        return null;
      }
    }

    function openModal() {
      if (!modal || !activeSession()) return;
      opener = doc.activeElement;
      modal.hidden = false;
      doc.body.classList.add('student-focus-open');
      byId('studentFocusEndConfirm').hidden = true;
      byId('studentFocusMinimize')?.focus();
      updateCountdown();
    }

    function closeModal({ restore = true } = {}) {
      if (!modal) return;
      modal.hidden = true;
      doc.body.classList.remove('student-focus-open');
      if (restore && opener instanceof win.HTMLElement && opener.isConnected) opener.focus();
    }

    async function start() {
      if (activeSession()) {
        openModal();
        return;
      }
      startButton.disabled = true;
      try {
        const body = await call('/api/mobile/focus/start', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        const payload = normalizeMutation(body, { start: true });
        if (!payload) throw new FocusRequestError('focus_malformed');
        applySession(payload);
        predictedVisibility = payload.session.visibility;
        nextSeq = payload.session.lastSeq + 1;
        openModal();
      } catch (error) {
        reportError(error);
        await load();
      }
    }

    async function end() {
      const session = activeSession();
      if (!session || ending) return;
      ending = true;
      try {
        await flush();
        if (desynced) await load({ repairActive: true });
        if (desynced) return;
        const selected = activeSession();
        if (!selected) return;
        const body = await call('/api/mobile/focus/end', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId: selected.id, seq: selected.lastSeq + 1 }),
        });
        const payload = normalizeMutation(body);
        if (!payload) throw new FocusRequestError('focus_malformed');
        applySession(payload);
        closeModal();
        startButton?.focus();
      } catch (error) {
        reportError(error);
        desynced = true;
        await load({ repairActive: true });
      } finally {
        ending = false;
      }
    }

    function trapFocus(event) {
      if (modal?.hidden || event.key !== 'Tab' || !sheet) return;
      const controls = [...sheet.querySelectorAll('button:not([disabled]):not([hidden]), a[href]:not([hidden])')];
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!controls.includes(doc.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && doc.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && doc.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    }

    startButton?.addEventListener('click', () => void start());
    byId('studentFocusMinimize')?.addEventListener('click', () => closeModal());
    byId('studentFocusEnd')?.addEventListener('click', () => {
      byId('studentFocusEndConfirm').hidden = false;
      byId('studentFocusEndCancel')?.focus();
    });
    byId('studentFocusEndCancel')?.addEventListener('click', () => {
      byId('studentFocusEndConfirm').hidden = true;
      byId('studentFocusEnd')?.focus();
    });
    byId('studentFocusEndConfirmButton')?.addEventListener('click', () => void end());
    modal?.querySelectorAll('.student-focus-shortcuts a').forEach(link => link.addEventListener('click', () => closeModal({ restore: false })));
    modal?.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); closeModal(); }
      else trapFocus(event);
    });
    doc.addEventListener('visibilitychange', () => capture(doc.visibilityState === 'hidden' ? 'hidden' : 'visible', doc.visibilityState === 'hidden'));
    win.addEventListener('pagehide', () => capture('hidden', true));
    win.addEventListener('pageshow', () => { if (desynced) void load({ repairActive: true }); else capture('visible'); });
    win.addEventListener('online', () => { if (desynced) void load({ repairActive: true }); });
    timer = win.setInterval(updateCountdown, 1000);

    return Object.freeze({
      load: () => load({ repairActive: true }),
      destroy: () => { win.clearInterval(timer); closeModal({ restore: false }); },
      state: () => current,
    });
  }

  global.StudentFocus = Object.freeze({
    createController,
    normalizeCurrent,
    normalizeMutation,
  });
})(window);
