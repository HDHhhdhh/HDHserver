const CLEARABLE_TEST_FIELDS = new Set(['term', 'examTerm']);
const SOURCE_FILE_FIELDS = ['sourceFiles', 'source_files'];

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function testId(test) {
  const raw = test?.id;
  if (typeof raw !== 'string' && typeof raw !== 'number') return '';
  return String(raw).trim();
}

function invalid(error = 'invalid test patch') {
  return { ok: false, status: 400, error };
}

export function patchDemoTestConfig(currentConfig, payload) {
  const categoryKey = String(payload?.categoryKey || '').trim();
  const categoryLabel = String(payload?.categoryLabel || '').trim();
  const incomingTest = payload?.test;
  const clearFields = payload?.clearFields ?? [];
  const categories = currentConfig?.categories;

  if (
    !categoryKey
    || !incomingTest
    || typeof incomingTest !== 'object'
    || Array.isArray(incomingTest)
    || !categories
    || typeof categories !== 'object'
    || Array.isArray(categories)
    || !Array.isArray(clearFields)
  ) {
    return invalid();
  }

  const id = testId(incomingTest);
  if (!id) return invalid('test patch requires an id');

  const normalizedClearFields = [];
  for (const rawField of clearFields) {
    if (typeof rawField !== 'string') return invalid('invalid clear fields');
    const field = rawField.trim();
    if (!CLEARABLE_TEST_FIELDS.has(field)) return invalid('invalid clear fields');
    if (!normalizedClearFields.includes(field)) normalizedClearFields.push(field);
  }

  const matches = [];
  for (const [sourceKey, category] of Object.entries(categories)) {
    if (!category || typeof category !== 'object' || Array.isArray(category)) return invalid('invalid category');
    if (category.tests != null && !Array.isArray(category.tests)) return invalid('invalid test list');
    (category.tests || []).forEach((test, index) => {
      if (test && typeof test === 'object' && !Array.isArray(test) && testId(test) === id) {
        matches.push({ sourceKey, index, test });
      }
    });
  }
  if (matches.length > 1) return invalid('test patch id is ambiguous');

  const nextConfig = clone(currentConfig);
  const nextCategories = nextConfig.categories;
  const currentTest = matches[0]?.test;
  const nextIncoming = clone(incomingTest);
  if (currentTest) {
    SOURCE_FILE_FIELDS.forEach(field => {
      if (
        currentTest[field]
        && typeof currentTest[field] === 'object'
        && !Array.isArray(currentTest[field])
        && nextIncoming[field]
        && typeof nextIncoming[field] === 'object'
        && !Array.isArray(nextIncoming[field])
      ) {
        nextIncoming[field] = { ...clone(currentTest[field]), ...nextIncoming[field] };
      }
    });
  }
  const savedTest = currentTest ? { ...clone(currentTest), ...nextIncoming } : nextIncoming;
  normalizedClearFields.forEach(field => delete savedTest[field]);

  if (matches.length) {
    const { sourceKey, index } = matches[0];
    const sourceTests = nextCategories[sourceKey]?.tests;
    if (!Array.isArray(sourceTests)) return invalid('invalid source test list');
    if (sourceKey === categoryKey) {
      sourceTests[index] = savedTest;
      return { ok: true, status: 200, config: nextConfig, test: clone(savedTest) };
    }
    sourceTests.splice(index, 1);
  }

  let targetCategory = nextCategories[categoryKey];
  if (targetCategory == null) {
    targetCategory = {
      label: categoryLabel || categoryKey,
      tests: [],
    };
    nextCategories[categoryKey] = targetCategory;
  }
  if (!targetCategory || typeof targetCategory !== 'object' || Array.isArray(targetCategory)) {
    return invalid('invalid target category');
  }
  if (targetCategory.tests == null) targetCategory.tests = [];
  if (!Array.isArray(targetCategory.tests)) return invalid('invalid target test list');
  if (categoryLabel && !String(targetCategory.label || '').trim()) targetCategory.label = categoryLabel;
  targetCategory.tests.push(savedTest);
  return { ok: true, status: 200, config: nextConfig, test: clone(savedTest) };
}
