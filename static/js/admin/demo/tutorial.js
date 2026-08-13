import { PAGE_FEATURES, resolvePageKey } from './tutorial.features.js';
import { loadState, saveState } from './tutorial.state.js';
import { CENTER_CLASS, POPOVER_CLASS, ROOT_CLASS, injectStyles } from './tutorial.styles.js';
import { renderHelpCenter, renderHelpPopover } from './tutorial.render.js';
import { findFeatureForTarget, findTarget, isUsableTarget, elementFromEvent } from './tutorial.targets.js';

export function installDemoTutorial({ window: rootWindow = window, demo = {} } = {}) {
  const doc = rootWindow.document;
  if (!doc?.body || doc.body.dataset.adminDemoFeatureHelpInstalled === '1') return;
  doc.body.dataset.adminDemoFeatureHelpInstalled = '1';
  injectStyles(doc);

  const pageKey = resolvePageKey(rootWindow.location.pathname);
  const page = PAGE_FEATURES[pageKey] || PAGE_FEATURES.admin;
  const state = loadState(rootWindow);
  const api = createFeatureHelpApi(rootWindow, demo, pageKey, page, state);
  rootWindow.__adminDemoTutorial = api;
  rootWindow.__adminDemoFeatureHelp = api;
  rootWindow.addEventListener('admin-demo:tutorial-open', () => api.open());
  rootWindow.addEventListener('keydown', event => {
    if (event.key === 'Escape') api.close();
  });
  rootWindow.addEventListener('resize', () => api.reposition(), { passive: true });
  rootWindow.addEventListener('scroll', () => api.reposition(), { passive: true, capture: true });
  doc.addEventListener('click', event => api.handleInteraction(event), true);
  api.mount();
}

function createFeatureHelpApi(rootWindow, demo, pageKey, page, state) {
  const doc = rootWindow.document;
  let host = null;
  let popover = null;
  let center = null;
  let activeAnchor = null;

  function mount() {
    host = doc.createElement('div');
    host.className = ROOT_CLASS;
    doc.body.appendChild(host);
  }

  function seenSet() {
    const ids = state.seenByPage[pageKey];
    return new Set(Array.isArray(ids) ? ids : []);
  }

  function persist() {
    saveState(rootWindow, state);
  }

  function markSeen(featureId) {
    const ids = seenSet();
    ids.add(featureId);
    state.seenByPage[pageKey] = [...ids];
    persist();
    renderCenter();
  }

  function resetPage() {
    state.seenByPage[pageKey] = [];
    persist();
    renderCenter();
    demo.showMessage?.('이 페이지 기능 설명을 다시 표시합니다.', { quiet: true });
  }

  function handleInteraction(event) {
    const target = elementFromEvent(event.target);
    if (!target || target.closest(`.${ROOT_CLASS}`) || target.closest('#adminDemoIndicator')) return;
    const hit = findFeatureForTarget({ target, features: page.features, doc, rootWindow, rootClass: ROOT_CLASS });
    if (!hit || seenSet().has(hit.feature.id)) return;
    markSeen(hit.feature.id);
    showFeature(hit.feature, hit.anchor);
  }

  function open() {
    closePopover();
    closeCenter();
    if (!host) mount();
    center = doc.createElement('section');
    center.className = CENTER_CLASS;
    center.setAttribute('role', 'dialog');
    center.setAttribute('aria-modal', 'false');
    center.setAttribute('aria-label', '데모 기능 도움말');
    host.appendChild(center);
    renderCenter();
  }

  function renderCenter() {
    if (!center) return;
    renderHelpCenter({
      center,
      page,
      seen: seenSet(),
      onClose: closeCenter,
      onReset: resetPage,
      onShowFeature: feature => {
        closeCenter();
        showFeature(feature, findTarget({ feature, doc, rootWindow, rootClass: ROOT_CLASS }), { intentional: true });
      },
    });
  }

  function showFeature(feature, anchor, options = {}) {
    if (!host) mount();
    closePopover();
    activeAnchor = isUsableTarget({ element: anchor, rootWindow, rootClass: ROOT_CLASS })
      ? anchor
      : doc.querySelector('main') || doc.body;
    popover = renderHelpPopover({
      doc,
      feature,
      popoverClass: POPOVER_CLASS,
      intentional: !!options.intentional,
      onClose: closePopover,
    });
    host.appendChild(popover);
    positionPopover();
  }

  function close() {
    closePopover();
    closeCenter();
  }

  function closePopover() {
    popover?.remove();
    popover = null;
    activeAnchor = null;
  }

  function closeCenter() {
    center?.remove();
    center = null;
  }

  function reposition() {
    if (popover && activeAnchor?.isConnected) positionPopover();
  }

  function positionPopover() {
    if (!popover || !activeAnchor) return;
    const viewportWidth = rootWindow.innerWidth || doc.documentElement.clientWidth || 0;
    const viewportHeight = rootWindow.innerHeight || doc.documentElement.clientHeight || 0;
    const rect = activeAnchor.getBoundingClientRect();
    const width = Math.min(340, Math.max(260, viewportWidth - 24));
    popover.style.width = `${width}px`;
    popover.style.left = '12px';
    popover.style.top = '12px';

    const measured = popover.getBoundingClientRect();
    const gap = 10;
    const left = clamp(rect.left, 12, viewportWidth - width - 12);
    const below = rect.bottom + gap;
    const above = rect.top - measured.height - gap;
    const canUseBelow = below + measured.height <= viewportHeight - 12;
    const top = canUseBelow ? below : clamp(above, 12, viewportHeight - measured.height - 12);
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  }

  return {
    mount,
    open,
    close,
    reset: resetPage,
    handleInteraction,
    reposition,
    show: featureId => {
      const feature = page.features.find(item => item.id === featureId);
      if (feature) showFeature(feature, findTarget({ feature, doc, rootWindow, rootClass: ROOT_CLASS }), { intentional: true });
    },
  };
}

function clamp(value, min, max) {
  if (max < min) return min;
  return Math.max(min, Math.min(max, value));
}
