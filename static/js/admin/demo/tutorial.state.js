const HELP_STORAGE_KEY = 'academy.adminDemo.featureHelp.v1';

function defaultState() {
  return {
    version: 1,
    seenByPage: {},
  };
}

export function loadState(rootWindow) {
  try {
    const raw = rootWindow.sessionStorage.getItem(HELP_STORAGE_KEY);
    if (!raw) return defaultState();
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.version !== 1) return defaultState();
    return {
      ...defaultState(),
      ...parsed,
      seenByPage: parsed.seenByPage || {},
    };
  } catch {
    return defaultState();
  }
}

export function saveState(rootWindow, state) {
  try {
    rootWindow.sessionStorage.setItem(HELP_STORAGE_KEY, JSON.stringify(state));
  } catch {
  }
}
