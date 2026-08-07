const assert = require('node:assert/strict');

function installBrowserStubs(fetchPayload) {
  globalThis.window = {
    addEventListener() {},
    extra: {},
    state: {},
  };
  globalThis.document = {
    addEventListener() {},
    dispatchEvent() {},
    createElement() {
      return {
        style: {},
        appendChild() {},
        remove() {},
      };
    },
    head: { appendChild() {} },
    body: { appendChild() {} },
    getElementById() { return null; },
    querySelector() { return null; },
  };
  globalThis.sessionStorage = {
    getItem() { return null; },
    setItem() {},
  };
  globalThis.CustomEvent = class CustomEvent {
    constructor(type, init = {}) {
      this.type = type;
      this.detail = init.detail;
    }
  };
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    async json() { return fetchPayload; },
    async text() { return JSON.stringify(fetchPayload); },
  });
}

async function main() {
  const dateKey = '2026-07-05';
  const sid = 'slot-override-sid';
  installBrowserStubs({ [dateKey]: { [sid]: [1] } });

  const stateModule = await import('../static/js/admin/core/state.js');
  const todayState = await import('../static/js/admin/features/today.state.js');

  stateModule.state.students = [{ id: sid, name: '구분테스트', day1: '일1', day2: '일2' }];
  stateModule.state.extra = { [dateKey]: [sid] };
  globalThis.window.extra = stateModule.state.extra;

  await todayState.loadWeekendSlots();

  assert.deepEqual(
    todayState.getSlots(dateKey, sid),
    [1],
    'explicit weekend slot override must narrow 일1일2 to 일1 even for extra-attend rows',
  );
  assert.equal(todayState.labelFor(dateKey, sid), '일1');

  console.log('admin weekend slot override PASS');
}

main().catch((err) => {
  console.error(err?.stack || err?.message || err);
  process.exit(1);
});
