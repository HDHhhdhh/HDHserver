(function studentReviewPlaylistModule(global) {
  'use strict';

  const STORAGE_PREFIX = 'student:review-playlist';

  function requireFunction(value, name) {
    if (typeof value !== 'function') throw new TypeError(`${name} must be a function`);
    return value;
  }

  function normalizeMids(value) {
    const seen = new Set();
    const normalized = [];
    if (!Array.isArray(value)) return normalized;
    value.forEach(raw => {
      const mid = String(raw ?? '').trim();
      if (!mid || seen.has(mid)) return;
      seen.add(mid);
      normalized.push(mid);
    });
    return normalized;
  }

  function storageKey(sid, date) {
    return `${STORAGE_PREFIX}:${String(sid)}:${String(date)}`;
  }

  function createController(options = {}) {
    const storage = options.storage;
    if (!storage || typeof storage.getItem !== 'function' || typeof storage.setItem !== 'function') {
      throw new TypeError('storage must implement getItem and setItem');
    }

    const getSid = requireFunction(options.getSid, 'getSid');
    const getDate = requireFunction(options.getDate, 'getDate');
    let authorized = new Set();
    let registered = [];
    const selection = new Set();

    function currentStorageKey() {
      return storageKey(getSid(), getDate());
    }

    function save() {
      try {
        storage.setItem(currentStorageKey(), JSON.stringify(registered));
        return true;
      } catch {
        return false;
      }
    }

    function hydrate(authorizedMids) {
      authorized = new Set(normalizeMids(authorizedMids));
      let parsed = [];
      try {
        const raw = storage.getItem(currentStorageKey());
        if (raw) parsed = JSON.parse(raw);
      } catch {
        parsed = [];
      }

      const normalized = normalizeMids(parsed);
      const next = normalized.filter(mid => authorized.has(mid));
      const changed = JSON.stringify(next) !== JSON.stringify(normalized);
      registered = next;
      selection.clear();
      if (changed) save();
      return registeredMids();
    }

    function registeredMids() {
      return [...registered];
    }

    function isRegistered(rawMid) {
      const mid = String(rawMid ?? '').trim();
      return !!mid && registered.includes(mid);
    }

    function pruneSelection() {
      for (const mid of selection) {
        if (!authorized.has(mid) || registered.includes(mid)) selection.delete(mid);
      }
      return selectedMids();
    }

    function selectedMids() {
      return [...selection].filter(mid => authorized.has(mid) && !registered.includes(mid));
    }

    function isSelected(rawMid) {
      const mid = String(rawMid ?? '').trim();
      return !!mid && selectedMids().includes(mid);
    }

    function setSelected(rawMid, checked) {
      const mid = String(rawMid ?? '').trim();
      if (!mid) return false;
      if (!checked) return selection.delete(mid);
      if (!authorized.has(mid) || registered.includes(mid)) return false;
      const sizeBefore = selection.size;
      selection.add(mid);
      return selection.size !== sizeBefore;
    }

    function registerSelected() {
      const selected = selectedMids();
      if (!selected.length) return [];
      registered = normalizeMids([...registered, ...selected]);
      selection.clear();
      save();
      return selected;
    }

    function unregister(rawMid) {
      const mid = String(rawMid ?? '').trim();
      if (!mid || !registered.includes(mid)) return false;
      registered = registered.filter(registeredMid => registeredMid !== mid);
      selection.delete(mid);
      save();
      return true;
    }

    return Object.freeze({
      currentStorageKey,
      hydrate,
      isRegistered,
      isSelected,
      pruneSelection,
      registerSelected,
      registeredMids,
      selectedMids,
      setSelected,
      unregister,
    });
  }

  global.StudentReviewPlaylist = Object.freeze({
    STORAGE_PREFIX,
    createController,
    normalizeMids,
    storageKey,
  });
})(window);
