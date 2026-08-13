import assert from 'node:assert/strict';
import test from 'node:test';

import { validateSuiteResult } from './result-contract.mjs';

test('accepts a bound positive suite receipt', () => {
  assert.equal(validateSuiteResult('shell', {
    suite: 'student-mobile-app-shell',
    checks: 3,
    passed: true,
  }), 3);
  assert.equal(validateSuiteResult('board', { name: 'board', checks: 1, passed: true }), 1);
});

test('rejects an unbound or malformed receipt', () => {
  const invalid = [
    { suite: 'wrong-suite', checks: 1, passed: true },
    { suite: 'student-mobile-app-shell', checks: 0, passed: true },
    { suite: 'student-mobile-app-shell', checks: true, passed: true },
    { suite: 'student-mobile-app-shell', checks: Number.NaN, passed: true },
    { suite: 'student-mobile-app-shell', checks: 1, passed: false },
    { suite: 'student-mobile-app-shell', assertions: 1, passed: true },
  ];
  for (const receipt of invalid) {
    assert.throws(() => validateSuiteResult('shell', receipt));
  }
  assert.throws(() => validateSuiteResult('missing', { checks: 1, passed: true }));
  assert.throws(() => validateSuiteResult('shell', null));
});
