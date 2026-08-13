const ORDER_FIELDS = ['sortOrder', 'sourceOrder', 'order', 'sourceIndex', '_catalogIndex'];

function text(value) {
  return String(value ?? '').trim().replace(/\s+/g, ' ');
}

function categoryKeyOf(test) {
  return text(test?.categoryKey || test?.category).toUpperCase();
}

function stripExistingOrdinal(value) {
  return text(value).replace(/^\d+\.\s*/u, '').trim();
}

function orderValue(test) {
  for (const field of ORDER_FIELDS) {
    const raw = test?.[field];
    if (raw === null || raw === undefined || String(raw).trim() === '') continue;
    const value = Number(raw);
    if (Number.isFinite(value)) return value;
  }
  return 999999;
}

function testIdentity(test) {
  const id = text(test?.id);
  if (id) return `id:${id}`;
  return [
    categoryKeyOf(test),
    text(test?.curriculum || test?.subject),
    text(test?.difficulty || test?.level),
    text(test?.round || test?.session || test?.no),
    stripExistingOrdinal(test?.name || test?.title),
  ].join('\u241f');
}

function topicIdentity(test) {
  const sourceId = text(test?.sourceId || test?.source_id).replace(/_r\d+$/i, '');
  if (sourceId) return `source:${sourceId}`;

  const id = text(test?.id).replace(/_r\d+$/i, '');
  if (id) return `id:${id}`;

  return `name:${stripExistingOrdinal(test?.name || test?.title)}`;
}

export function buildUnitTestDisplayNames(tests) {
  const groups = new Map();
  (Array.isArray(tests) ? tests : []).forEach((test, index) => {
    if (categoryKeyOf(test) !== 'UNIT') return;
    const groupKey = [
      text(test?.curriculum || test?.subject),
      text(test?.difficulty || test?.level),
    ].join('\u241f');
    if (!groups.has(groupKey)) groups.set(groupKey, []);
    groups.get(groupKey).push({ test, index });
  });

  const names = new Map();
  groups.forEach(entries => {
    const ordered = entries.slice().sort((a, b) =>
      orderValue(a.test) - orderValue(b.test) || a.index - b.index
    );
    const ordinalByTopic = new Map();

    ordered.forEach(({ test }) => {
      const topic = topicIdentity(test);
      if (!ordinalByTopic.has(topic)) ordinalByTopic.set(topic, ordinalByTopic.size + 1);
      const ordinal = ordinalByTopic.get(topic);
      names.set(testIdentity(test), `${ordinal}. ${stripExistingOrdinal(test?.name || test?.title)}`);
    });
  });

  return names;
}

export function createUnitTestDisplayNameResolver(tests) {
  const names = buildUnitTestDisplayNames(tests);
  return test => {
    const rawName = text(test?.name || test?.title);
    if (categoryKeyOf(test) !== 'UNIT') return rawName;
    return names.get(testIdentity(test)) || rawName;
  };
}
