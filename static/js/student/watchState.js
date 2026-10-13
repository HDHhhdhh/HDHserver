(function studentWatchStateModule(global) {
  'use strict';

  const WATCH_DONE_RATIO = 0.90;
  const WATCH_UPDATED_AT_MIN_MS = 1_000_000_000_000;
  const DEFAULT_SYNC_DEBOUNCE_MS = 1500;

  function requireFunction(value, name) {
    if (typeof value !== 'function') throw new TypeError(`${name} must be a function`);
    return value;
  }

  function normalizeUpdatedAt(value, fallback = 0) {
    const parsed = Number(value);
    const updatedAt = Number.isFinite(parsed) ? Math.floor(parsed) : 0;
    return updatedAt >= WATCH_UPDATED_AT_MIN_MS ? updatedAt : fallback;
  }

  function normalizeRecord(entry) {
    const source = entry && typeof entry === 'object' ? entry : {};
    const last = Math.max(0, Number(source.last) || 0);
    const dur = Math.max(0, Number(source.dur) || 0);
    const completed = !!source.completed
      || (dur > 0 && last >= Math.max(dur - 1, Math.floor(dur * WATCH_DONE_RATIO)));

    return {
      last: Math.floor(last),
      dur: Math.floor(dur),
      completed,
      updatedAt: normalizeUpdatedAt(source.updatedAt),
      ...(source.cycleToken ? { cycleToken: String(source.cycleToken) } : {}),
    };
  }

  function mergeRecords(base, patch, now = Date.now()) {
    const incoming = normalizeRecord(patch);
    const current = normalizeRecord(incoming.cycleToken && incoming.cycleToken !== base?.cycleToken ? {} : base);
    const last = Math.max(current.last, incoming.last);
    const dur = Math.max(current.dur, incoming.dur);
    const completed = current.completed
      || incoming.completed
      || (dur > 0 && last >= Math.max(dur - 1, Math.floor(dur * WATCH_DONE_RATIO)));

    return {
      last,
      dur,
      completed,
      updatedAt: Math.max(current.updatedAt, incoming.updatedAt, now),
      ...((incoming.cycleToken || current.cycleToken) ? { cycleToken: incoming.cycleToken || current.cycleToken } : {}),
    };
  }

  function progressStorageKey(sid, mid) {
    return `stu:${sid}:watch:${mid}`;
  }

  function lastMidStorageKey(sid) {
    return `stu:${sid}:last_video_mid`;
  }

  function wholeNonNegative(value) {
    return Math.max(0, Math.floor(Number(value) || 0));
  }

  function createController(options = {}) {
    const storage = options.storage;
    if (!storage || typeof storage.getItem !== 'function' || typeof storage.setItem !== 'function') {
      throw new TypeError('storage must implement getItem and setItem');
    }

    const getSid = requireFunction(options.getSid, 'getSid');
    const getCanonicalSid = requireFunction(options.getCanonicalSid, 'getCanonicalSid');
    const getDate = requireFunction(options.getDate, 'getDate');
    const getCurrentMid = requireFunction(options.getCurrentMid, 'getCurrentMid');
    const canSync = requireFunction(options.canSync, 'canSync');
    const request = requireFunction(options.request, 'request');
    const setTimer = requireFunction(options.setTimer, 'setTimer');
    const clearTimer = requireFunction(options.clearTimer, 'clearTimer');
    const now = requireFunction(options.now, 'now');
    const onProgressChange = typeof options.onProgressChange === 'function'
      ? options.onProgressChange
      : () => {};
    const onSyncError = typeof options.onSyncError === 'function'
      ? options.onSyncError
      : () => {};
    const headers = options.headers || { 'Content-Type': 'application/json' };
    const debounceMs = Number.isFinite(Number(options.debounceMs))
      ? Math.max(0, Number(options.debounceMs))
      : DEFAULT_SYNC_DEBOUNCE_MS;
    const syncTimers = new Map();
    const maxSyncTimers = new Map();
    const lastSent = new Map();
    const blockedCycles = new Set();

    function getProgress(mid) {
      try {
        const raw = storage.getItem(progressStorageKey(getSid(), mid));
        return raw ? JSON.parse(raw) : null;
      } catch {
        return null;
      }
    }

    function storeProgress(mid, next) {
      try {
        storage.setItem(progressStorageKey(getSid(), mid), JSON.stringify(next));
      } catch { }
    }

    function clearSyncTimers(mid) {
      clearTimer(syncTimers.get(mid));
      clearTimer(maxSyncTimers.get(mid));
      syncTimers.delete(mid);
      maxSyncTimers.delete(mid);
    }

    function enqueueSync(mid) {
      // Continuous one-second player events must not postpone saving forever.
      if (!maxSyncTimers.has(mid)) {
        maxSyncTimers.set(mid, setTimer(() => syncNow(mid), 10000));
      }
      if (syncTimers.has(mid)) clearTimer(syncTimers.get(mid));
      const timer = setTimer(() => syncNow(mid), debounceMs);
      syncTimers.set(mid, timer);
    }

    function setProgress(mid, patch, setOptions = {}) {
      if (blockedCycles.has(mid)) return getProgress(mid);
      const next = mergeRecords(getProgress(mid) || {}, patch, now());
      storeProgress(mid, next);
      try { onProgressChange(); } catch { }
      if (setOptions.sync !== false) enqueueSync(mid);
      return next;
    }

    function setLastMid(mid) {
      try { storage.setItem(lastMidStorageKey(getSid()), mid); } catch { }
    }

    function getLastMid() {
      try { return storage.getItem(lastMidStorageKey(getSid())) || null; } catch { return null; }
    }

    function mergeServerWatchIntoLocal(watchMap) {
      if (!watchMap || typeof watchMap !== 'object') return;

      Object.entries(watchMap).forEach(([mid, record]) => {
        const key = String(mid || '').trim();
        if (!key) return;
        const local = getProgress(key);
        const changedCycle = (local?.cycleToken || '') !== (record?.cycleToken || '');
        const next = mergeRecords(changedCycle ? {} : local, record, now());
        if (changedCycle) {
          clearSyncTimers(key);
        }
        blockedCycles.delete(key);
        storeProgress(key, next);
        lastSent.set(key, {
          last: next.last,
          dur: next.dur,
          completed: !!next.completed,
          updatedAt: normalizeUpdatedAt(next.updatedAt),
          ...(next.cycleToken ? { cycleToken: next.cycleToken } : {}),
        });
      });

      try { onProgressChange(); } catch { }
    }

    function clearProgress(mid) {
      clearSyncTimers(mid);
      try { storage.removeItem(progressStorageKey(getSid(), mid)); } catch { }
      lastSent.delete(mid);
    }

    function reloadForWatchCycle(mid, record) {
      blockedCycles.add(mid);
      clearSyncTimers(mid);
      storeProgress(mid, normalizeRecord(record));
      lastSent.delete(mid);
      options.onCycleChanged?.(mid);
    }

    function acceptPlaybackWatch(mid, record) {
      if ((record?.cycleToken || '') !== (getProgress(mid)?.cycleToken || '')) {
        // Retire the old iframe/pollers before accepting any new-cycle events.
        reloadForWatchCycle(mid, record);
        return false;
      }
      mergeServerWatchIntoLocal({ [mid]: record });
      return true;
    }

    async function syncNow(mid, syncOptions = {}) {
      clearSyncTimers(mid);
      if (!canSync(mid) || blockedCycles.has(mid)) return;
      const progress = getProgress(mid);
      if (!progress) return;
      const currentTime = now();
      const snapshot = {
        last: wholeNonNegative(progress.last),
        dur: wholeNonNegative(progress.dur),
        completed: !!progress.completed,
        updatedAt: normalizeUpdatedAt(progress.updatedAt, currentTime),
        ...(progress.cycleToken ? { cycleToken: progress.cycleToken } : {}),
      };
      const previous = lastSent.get(mid);
      if (previous
        && previous.last === snapshot.last
        && previous.dur === snapshot.dur
        && previous.completed === snapshot.completed
        && previous.cycleToken === snapshot.cycleToken) return;

      const payload = {
        date: getDate(),
        sid: String(getCanonicalSid() || '').trim(),
        mid,
        last: snapshot.last,
        dur: snapshot.dur,
        completed: snapshot.completed,
        updatedAt: snapshot.updatedAt,
        ...(snapshot.cycleToken ? { cycleToken: snapshot.cycleToken } : {}),
      };

      try {
        const response = await request('/api/watch', {
          method: 'POST',
          headers,
          body: JSON.stringify(payload),
          keepalive: !!syncOptions.keepalive,
        });
        if ((getProgress(mid)?.cycleToken || '') !== (snapshot.cycleToken || '')) return;
        if (response.ok) lastSent.set(mid, snapshot);
        else if (response.status === 409) {
          const result = await response.json();
          if (result?.code === 'watch_cycle_changed') {
            reloadForWatchCycle(mid, result.watch);
          }
        }
      } catch (error) {
        try { onSyncError(error); } catch { }
      }
    }

    async function flushSyncQueue(syncOptions = {}) {
      const mids = new Set([...syncTimers.keys(), ...maxSyncTimers.keys()]);
      const currentMid = getCurrentMid();
      if (currentMid) mids.add(currentMid);
      if (!mids.size) return;

      mids.forEach(mid => {
        clearSyncTimers(mid);
      });

      await Promise.allSettled([...mids].map(mid => syncNow(mid, syncOptions)));
    }

    return Object.freeze({
      acceptPlaybackWatch,
      clearProgress,
      flushSyncQueue,
      getLastMid,
      getProgress,
      mergeServerWatchIntoLocal,
      setLastMid,
      setProgress,
      syncNow,
    });
  }

  global.StudentWatchState = Object.freeze({
    WATCH_DONE_RATIO,
    WATCH_UPDATED_AT_MIN_MS,
    createController,
    lastMidStorageKey,
    mergeRecords,
    normalizeRecord,
    normalizeUpdatedAt,
    progressStorageKey,
  });
})(window);
