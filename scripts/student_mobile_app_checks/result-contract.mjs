const identities = Object.freeze({
  shell: Object.freeze({ field: 'suite', value: 'student-mobile-app-shell' }),
  'admin-accounts': Object.freeze({ field: 'suite', value: 'student-mobile-app-admin-accounts' }),
  'student-data': Object.freeze({ field: 'suite', value: 'student-mobile-app-student-data' }),
  dashboard: Object.freeze({ field: 'suite', value: 'student-mobile-app-dashboard' }),
  homework: Object.freeze({ field: 'suite', value: 'student-mobile-app-homework' }),
  notifications: Object.freeze({ field: 'suite', value: 'student-mobile-app-notifications' }),
  board: Object.freeze({ field: 'name', value: 'board' }),
  focus: Object.freeze({ field: 'suite', value: 'student-mobile-app-focus' }),
  'academy-gates': Object.freeze({ field: 'suite', value: 'student-mobile-app-academy-gates' }),
  'pwa-flow': Object.freeze({ field: 'suite', value: 'student-mobile-app-pwa-flow' }),
});

export function validateSuiteResult(name, result) {
  const identity = identities[name];
  if (!identity) throw new Error(`suite ${name} has no result identity contract`);
  if (result === null || typeof result !== 'object' || Array.isArray(result)) {
    throw new Error(`suite ${name} returned a non-object result`);
  }
  if (result[identity.field] !== identity.value) {
    throw new Error(
      `suite ${name} reported ${identity.field} ${JSON.stringify(result[identity.field])}; expected ${JSON.stringify(identity.value)}`,
    );
  }
  if (!Number.isSafeInteger(result.checks) || result.checks <= 0) {
    throw new Error(`suite ${name} returned a non-positive integer check count`);
  }
  if (Object.hasOwn(result, 'passed') && result.passed !== true) {
    throw new Error(`suite ${name} did not report passed:true`);
  }
  return result.checks;
}

export const expectedSuiteIdentities = identities;
