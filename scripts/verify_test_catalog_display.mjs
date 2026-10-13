import assert from 'node:assert/strict';

import {
  buildUnitTestDisplayNames,
  createUnitTestDisplayNameResolver,
} from '../static/js/shared/testCatalogDisplay.js';

const tests = [
  {
    id: 'unit-later_r1',
    sourceId: 'unit-later',
    categoryKey: 'UNIT',
    curriculum: '대수',
    difficulty: 'Lv.3',
    round: '1',
    name: '9. 뒤 주제',
    sourceOrder: 20,
  },
  {
    id: 'unit-first_r1',
    sourceId: 'unit-first_r1',
    categoryKey: 'UNIT',
    curriculum: '대수',
    difficulty: 'Lv.3',
    round: '1',
    name: '1. 첫 주제',
    sourceOrder: '10',
  },
  {
    id: 'unit-first_r2',
    sourceId: 'unit-first_r2',
    categoryKey: 'UNIT',
    curriculum: '대수',
    difficulty: 'Lv.3',
    round: '2',
    name: '첫 주제',
    sourceOrder: 11,
  },
  {
    id: 'unit-other-level',
    categoryKey: 'UNIT',
    curriculum: '대수',
    difficulty: 'Lv.4',
    round: '1',
    name: '다른 난이도',
  },
  {
    id: 'review-raw',
    categoryKey: 'REVIEW',
    curriculum: '대수',
    difficulty: '상',
    name: '  복습   원문  ',
  },
];

const before = structuredClone(tests);
const displayNameFor = createUnitTestDisplayNameResolver(tests);
const names = buildUnitTestDisplayNames(tests);

assert.equal(displayNameFor(tests[0]), '2. 뒤 주제');
assert.equal(displayNameFor(tests[1]), '1. 첫 주제');
assert.equal(displayNameFor(tests[2]), '1. 첫 주제');
assert.equal(displayNameFor(tests[3]), '1. 다른 난이도');
assert.equal(displayNameFor(tests[4]), '복습 원문');
assert.equal(names.size, 4);
assert.deepEqual(tests, before, 'display-name projection must not mutate the catalog');
assert.equal(createUnitTestDisplayNameResolver(null)({ categoryKey: 'UNIT', name: '원문' }), '원문');

console.log('test catalog display checks passed');
