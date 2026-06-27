export function elementFromEvent(target) {
  return target?.nodeType === 1 ? target : target?.parentElement || null;
}

export function findFeatureForTarget({ target, features, doc, rootWindow, rootClass }) {
  let best = null;
  for (const [featureIndex, feature] of features.entries()) {
    const candidate = matchingAnchor({ target, feature, featureIndex, doc, rootWindow, rootClass });
    if (candidate && (!best || compareCandidates(candidate, best) < 0)) {
      best = candidate;
    }
  }
  return best ? { feature: best.feature, anchor: best.anchor } : null;
}

export function findTarget({ feature, doc, rootWindow, rootClass }) {
  const selectors = Array.isArray(feature?.target) ? feature.target : [];
  for (const selector of selectors) {
    try {
      const candidates = doc.querySelectorAll(selector);
      for (const candidate of candidates) {
        if (isUsableTarget({ element: candidate, rootWindow, rootClass })) return candidate;
      }
    } catch {
    }
  }
  return doc.querySelector('main') || doc.body;
}

export function isUsableTarget({ element, rootWindow, rootClass }) {
  if (!element || !element.isConnected || element.closest?.(`.${rootClass}`)) return false;
  const rect = element.getBoundingClientRect();
  const style = rootWindow.getComputedStyle(element);
  return rect.width > 0
    && rect.height > 0
    && style.display !== 'none'
    && style.visibility !== 'hidden'
    && style.opacity !== '0';
}

function matchingAnchor({ target, feature, featureIndex, doc, rootWindow, rootClass }) {
  const selectors = Array.isArray(feature?.target) ? feature.target : [];
  let best = null;
  for (const [selectorIndex, selector] of selectors.entries()) {
    const anchor = anchorFromSelector({ target, selector, doc, rootWindow, rootClass });
    if (!anchor) continue;
    const candidate = {
      feature,
      anchor,
      rank: rankCandidate({ target, anchor, feature, selector, selectorIndex, featureIndex }),
    };
    if (!best || compareCandidates(candidate, best) < 0) best = candidate;
  }
  return best;
}

function anchorFromSelector({ target, selector, doc, rootWindow, rootClass }) {
  try {
    const closest = target.closest(selector);
    if (isUsableTarget({ element: closest, rootWindow, rootClass })) return closest;
    const candidates = doc.querySelectorAll(selector);
    for (const candidate of candidates) {
      const candidateVisible = isUsableTarget({ element: candidate, rootWindow, rootClass });
      if (candidateVisible && candidate.contains(target)) return candidate;
    }
  } catch {
  }
  return null;
}

function rankCandidate({ target, anchor, feature, selector, selectorIndex, featureIndex }) {
  const rect = anchor.getBoundingClientRect();
  return {
    priority: Number.isFinite(Number(feature?.priority)) ? Number(feature.priority) : 0,
    distance: ancestorDistance(target, anchor),
    area: Math.max(1, Math.round(rect.width * rect.height)),
    specificity: selectorSpecificity(selector),
    selectorIndex,
    featureIndex,
  };
}

function compareCandidates(a, b) {
  const aRank = a.rank;
  const bRank = b.rank;
  if (aRank.priority !== bRank.priority) return bRank.priority - aRank.priority;
  if (aRank.distance !== bRank.distance) return aRank.distance - bRank.distance;
  if (aRank.area !== bRank.area) return aRank.area - bRank.area;
  if (aRank.specificity !== bRank.specificity) return bRank.specificity - aRank.specificity;
  if (aRank.selectorIndex !== bRank.selectorIndex) return aRank.selectorIndex - bRank.selectorIndex;
  return aRank.featureIndex - bRank.featureIndex;
}

function ancestorDistance(target, anchor) {
  let distance = 0;
  let current = target;
  while (current && current !== anchor) {
    current = current.parentElement;
    distance += 1;
  }
  return current === anchor ? distance : Number.MAX_SAFE_INTEGER;
}

function selectorSpecificity(selector) {
  const text = String(selector || '');
  const idCount = (text.match(/#[\w-]+/g) || []).length;
  const classAttrCount = (text.match(/(\.[\w-]+|\[[^\]]+\]|:[\w-]+)/g) || []).length;
  const elementCount = (text
    .replace(/#[\w-]+/g, ' ')
    .replace(/(\.[\w-]+|\[[^\]]+\]|:[\w-]+)/g, ' ')
    .match(/\b[a-z][\w-]*\b/gi) || []).length;
  return idCount * 100 + classAttrCount * 10 + elementCount;
}
