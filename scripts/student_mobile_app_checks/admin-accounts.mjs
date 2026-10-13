import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..', '..');
const files = Object.freeze({
  html: path.join(root, 'static', 'admin.html'),
  css: path.join(root, 'static', 'css', 'admin.css'),
  main: path.join(root, 'static', 'js', 'admin', 'main.js'),
  feature: path.join(root, 'static', 'js', 'admin', 'features', 'studentAccounts.js'),
  demoData: path.join(root, 'static', 'js', 'admin', 'demo', 'data.js'),
  demoStore: path.join(root, 'static', 'js', 'admin', 'demo', 'store.js'),
  demoFetch: path.join(root, 'static', 'js', 'admin', 'demo', 'fetch.js'),
});

const artifactPath = process.env.STUDENT_APP_ADMIN_ACCOUNTS_EVIDENCE ?? path.join(
  root,
  '.omo',
  'evidence',
  'student-mobile-app-v2',
  'task-8',
  'admin-accounts-check.json',
);

const read = (filename) => fs.readFile(filename, 'utf8');

function demoRuntimeScript() {
  return `
    import assert from 'node:assert/strict';
    import { pathToFileURL } from 'node:url';
    const values = new Map();
    globalThis.sessionStorage = {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, String(value)),
      removeItem: key => values.delete(key),
    };
    let liveFetches = 0;
    const root = {
      location: { origin: 'https://demo.test', pathname: '/demo/rh3123' },
      Response, Request, Headers,
    };
    const originalFetch = async () => { liveFetches += 1; return new Response('live'); };
    const module = await import(pathToFileURL(process.argv[1]).href);
    const fetchDemo = module.createDemoFetch({ root, originalFetch, now: '2026-06-17T00:00:00+09:00' });
    const listResponse = await fetchDemo('/api/student-accounts');
    assert.equal(listResponse.status, 200);
    const initial = await listResponse.json();
    assert.equal(initial.ok, true);
    assert.ok(Array.isArray(initial.groups) && initial.groups.length >= 3);
    const candidate = initial.groups.find(group => group.activationCodeRequired);
    assert.equal(candidate?.account, null);
    const accountKey = candidate.account?.aid || candidate.identity.name;
    assert.ok(accountKey);
    const aid = encodeURIComponent(accountKey);
    const exactSids = candidate.identity.sids;
    const mismatch = await fetchDemo('/api/student-accounts/' + aid + '/activation-code', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sids: [...exactSids, 'demo-wrong'] }),
    });
    assert.equal(mismatch.status, 400);
    const issued = await fetchDemo('/api/student-accounts/' + aid + '/activation-code', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sids: exactSids }),
    });
    assert.equal(issued.status, 200);
    const issuePayload = await issued.json();
    assert.match(issuePayload.activationCode, /^\\d{6}$/);
    assert.ok(issuePayload.expiresAt);
    assert.doesNotMatch([...values.values()].join(''), new RegExp(issuePayload.activationCode));
    const active = initial.groups.find(group => group.account?.status === 'active');
    const activeAid = encodeURIComponent(active.account.aid);
    const disabled = await fetchDemo('/api/student-accounts/' + activeAid + '/disable', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    assert.equal(disabled.status, 200);
    const after = await (await fetchDemo('/api/student-accounts')).json();
    const changed = after.groups.find(group => group.account?.aid === active.account.aid);
    assert.equal(changed.account.status, 'disabled');
    assert.equal(changed.account.activeSessionCount, 0);
    assert.equal(changed.account.activePushSubscriptionCount, 0);
    assert.equal((await fetchDemo('/api/student-accounts/missing/unknown', { method: 'POST', body: '{}' })).status, 404);
    const studentsBefore = await (await fetchDemo('/api/students')).json();
    const addedStudent = await (await fetchDemo('/api/add-student', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'QA demo only', curriculum: '공수1' }),
    })).json();
    assert.match(addedStudent.id, /^demo-s/);
    const studentsAfter = await (await fetchDemo('/api/students')).json();
    assert.equal(studentsAfter.length, studentsBefore.length + 1);
    assert.ok(studentsAfter.some(student => student.id === addedStudent.id));
    assert.equal(liveFetches, 0);
  `;
}

export async function runChecks() {
  const [html, css, main, feature, demoData, demoStore, demoFetch] = await Promise.all(
    Object.values(files).map(read),
  );
  const passed = [];
  const check = (name, callback) => { callback(); passed.push(name); };

  check('admin shell exposes an accessible account-management dialog', () => {
    for (const id of ['studentAccountsOpen', 'studentAccountsModal', 'studentAccountsClose', 'studentAccountsSearch', 'studentAccountsFilter', 'studentAccountsRefresh', 'studentAccountsStatus', 'studentAccountsList', 'studentActivationCodePanel', 'studentActivationCodeCopy']) {
      assert.match(html, new RegExp(`id=["']${id}["']`), `missing #${id}`);
    }
    assert.match(html, /role=["']dialog["']/);
    assert.match(html, /aria-modal=["']true["']/);
  });

  check('feature is initialized from the admin entrypoint', () => {
    assert.match(main, /import\(['"]\.\/features\/studentAccounts\.js['"]\)\.then\(module => module\.initStudentAccounts\(\)\)/);
    assert.match(main, /initStudentAccounts\(\)/);
    assert.match(feature, /export\s+function\s+initStudentAccounts/);
  });

  check('feature uses shared checked JSON requests and every account action', () => {
    assert.match(feature, /shared\/api\.js/);
    assert.match(feature, /fetchJsonChecked/);
    assert.match(feature, /sendJson/);
    assert.match(feature, /ensureOk/);
    for (const action of ['reset', 'disable', 'enable', 'revoke-sessions', 'activation-code']) {
      assert.match(feature, new RegExp(action));
    }
    assert.match(feature, /!account\s*&&\s*group\.activationCodeRequired/);
    assert.match(feature, /account\?\.aid\s*\|\|\s*group\?\.identity\?\.aid\s*\|\|\s*group\?\.identity\?\.name/);
    assert.match(feature, /accountStatus\(group\)\s*===\s*['"]disabled['"][\s\S]*계정 활성화[\s\S]*else/);
  });

  check('destructive actions confirm and activation code is copy-once', () => {
    assert.match(feature, /confirm\s*\(/);
    assert.match(feature, /clipboard\.writeText/);
    assert.match(feature, /clearActivationCode/);
    assert.doesNotMatch(feature, /console\.(?:log|info|debug).*activation|dataset\.(?:code|activation)|localStorage/i);
  });

  check('account CSS is fully admin/component namespaced', () => {
    const rules = css.match(/[^{}]+\{[^{}]*\}/g)?.filter(rule => rule.includes('student-accounts')) ?? [];
    assert.ok(rules.length >= 8);
    for (const rule of rules) assert.match(rule.split('{')[0], /body\.admin/);
  });

  check('demo fixtures and schema include account state', () => {
    assert.match(demoData, /studentAccounts\s*:/);
    assert.match(demoData, /activationCodeRequired/);
    assert.match(demoStore, /DEMO_SCHEMA_VERSION\s*=\s*5/);
    assert.match(demoStore, /Array\.isArray\(store\.studentAccounts\)/);
  });

  check('demo API owns account reads and all five mutations', () => {
    assert.match(demoFetch, /path\s*===\s*['"]\/api\/student-accounts['"]/);
    for (const action of ['reset', 'disable', 'enable', 'revoke-sessions', 'activation-code']) {
      assert.match(demoFetch, new RegExp(`['"]${action}['"]`));
    }
    assert.match(demoFetch, /exactSid|exactSids|sameSid/i);
  });

  check('demo account flow never falls through or persists a raw code', () => {
    const moduleMode = Number(process.versions.node.split('.')[0]) < 24
      ? ['--experimental-default-type=module']
      : [];
    const result = spawnSync(process.execPath, [
      ...moduleMode,
      '-e',
      demoRuntimeScript(),
      files.demoFetch,
    ], { encoding: 'utf8', cwd: root });
    assert.equal(result.status, 0, `${result.stderr || result.stdout}`);
  });

  const artifact = {
    suite: 'student-mobile-app-admin-accounts',
    generatedAt: new Date().toISOString(),
    checks: passed.length,
    checksPassed: passed,
    files: Object.fromEntries(Object.entries(files).map(([key, filename]) => [key, path.relative(root, filename)])),
  };
  await fs.mkdir(path.dirname(artifactPath), { recursive: true });
  await fs.writeFile(artifactPath, `${JSON.stringify(artifact, null, 2)}\n`, 'utf8');
  return artifact;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  runChecks().then(
    result => console.log(`student-mobile-app admin-accounts: ${result.checks} assertions passed`),
    error => { console.error(error); process.exitCode = 1; },
  );
}
