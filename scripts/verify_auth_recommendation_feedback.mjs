import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'static/js/auth.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const response = data => ({ ok: true, status: 200, json: async () => data });
function storage() {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key) };
}
function element(id = '') {
  return { id, value: '', style: {}, textContent: '', innerHTML: '', dataset: {}, children: [], disabled: false,
    handlers: {}, addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); },
    appendChild(child) { this.children.push(child); }, focus() {}, setAttribute() {} };
}
function fixture() {
  const ids = new Map('sid pw spin msg loginBox loggedBox loggedWho modalBack curPw newId newPw modalMsg loginBtn goBtn logoutBtn changeBtn closeModalBtn saveChangeBtn curiWrap curiSelect curiHint curiReco curiRecoText curiRecoGoBtn curiRecoHideBtn'.split(' ').map(id => [id, element(id)]));
  ids.get('sid').value = 'synthetic-login'; ids.get('pw').value = 'synthetic-password';
  const document = { ...element(), getElementById: id => ids.get(id) || null, body: element(), createElement: () => element() };
  const requests = [], recommendations = [], timers = [];
  let account = 'one';
  const data = () => ({ ok: true, sid: account, aid: 'synthetic-account', token: 'synthetic-token-' + account,
    curris: [{ sid: account, cur: '기하' }, { sid: 'other', cur: '대수' }] });
  const ctx = vm.createContext({ document, window: element(), location: { href: '' }, localStorage: storage(), sessionStorage: storage(), console,
    Date: class extends Date { getDay() { return 5; } },
    setTimeout: (fn, delay) => { timers.push({ fn, delay }); return timers.length; },
    fetch: (url, options = {}) => {
      requests.push({ url, method: options.method || 'GET' });
      if (url === '/api/students') return new Promise((resolve, reject) => recommendations.push({ resolve, reject }));
      assert.ok(['/api/auth/login', '/api/auth/change', '/api/auth/me'].includes(url));
      return Promise.resolve(response(data()));
    } });
  vm.runInContext(source + '\nwindow.qa={login,logout,openModal,closeModal,saveChange};', ctx);
  const release = (index = 0, sid = 'one') => recommendations[index].resolve(response([{ id: sid, day: ['금1'] }]));
  const clickHide = () => document.handlers.click.forEach(fn => fn({ target: { id: 'curiRecoHideBtn' } }));
  return { ids, ctx, qa: ctx.window.qa, requests, recommendations, timers, release, clickHide, account: value => { account = value; } };
}
let cases = 0;
{
  const f = fixture(); const login = f.qa.login(); await flush();
  assert.match(f.ids.get('msg').textContent, /로그인됨/);
  assert.equal(f.ids.get('loggedBox').style.display, 'block');
  assert.equal(f.ids.get('spin').style.display, 'none');
  assert.equal(f.ids.get('curiRecoGoBtn').disabled, true);
  assert.equal(f.ids.get('curiReco').dataset.sid, '');
  assert.match(f.ids.get('curiRecoText').textContent, /확인하는 중/);
  assert.deepEqual(plain(f.ids.get('curiSelect').children.map(x => x.value)), ['one', 'other']);
  f.release(); await login;
  assert.equal(f.ids.get('curiReco').dataset.sid, 'one');
  assert.equal(f.ids.get('curiRecoGoBtn').disabled, false); cases++;
}
for (const action of ['logout', 'hide', 'sid-change', 'token-change']) {
  const f = fixture(); const login = f.qa.login(); await flush();
  if (action === 'logout') f.qa.logout();
  if (action === 'hide') f.clickHide();
  if (action === 'sid-change') f.ctx.localStorage.setItem('studentSid', 'new-session');
  if (action === 'token-change') f.ctx.localStorage.setItem('studentToken', 'new-session-token');
  f.release(); await login;
  assert.notEqual(f.ids.get('curiReco').dataset.sid, 'one', action + ' must reject late recommendation');
  assert.equal(f.ids.get('curiReco').style.display, 'none', action + ' must remove its stale loading UI');
  if (action === 'logout') assert.match(f.ids.get('msg').textContent, /로그아웃됨/); cases++;
}
{
  const f = fixture(); const older = f.qa.login(); await flush();
  f.account('two'); const newer = f.qa.login(); await flush();
  assert.equal(f.recommendations.length, 2);
  f.release(1, 'two'); await newer;
  f.release(0); await older;
  assert.equal(f.ids.get('curiReco').dataset.sid, 'two'); cases++;
}
{
  const f = fixture(); f.ctx.sessionStorage.setItem('hideCuriReco', '1'); await f.qa.login();
  assert.equal(f.recommendations.length, 0);
  assert.equal(f.ids.get('curiReco').style.display, 'none'); cases++;
}
{
  const f = fixture(); const login = f.qa.login(); await flush();
  f.recommendations[0].reject(new Error('synthetic recommendation failure')); await login;
  assert.match(f.ids.get('msg').textContent, /로그인됨/);
  assert.equal(f.ids.get('curiReco').style.display, 'none'); cases++;
}
for (const reopen of [false, true]) {
  const f = fixture(); f.ctx.localStorage.setItem('studentToken', 'existing-synthetic-token');
  f.qa.openModal(); f.ids.get('curPw').value = 'synthetic-password'; f.ids.get('newId').value = 'synthetic-new-id';
  const changing = f.qa.saveChange(); await flush();
  assert.equal(f.recommendations.length, 1);
  assert.equal(f.ids.get('modalMsg').textContent, '변경 완료.');
  assert.match(f.ids.get('msg').textContent, /변경됨/);
  assert.equal(f.timers.length, 1); assert.equal(f.timers[0].delay, 300);
  if (reopen) { f.qa.closeModal(); f.qa.openModal(); }
  f.timers[0].fn();
  assert.equal(f.ids.get('modalBack').style.display, reopen ? 'flex' : 'none');
  f.release(); await changing;
  assert.equal(f.ids.get('modalBack').style.display, reopen ? 'flex' : 'none');
  if (reopen) assert.equal(f.ids.get('modalMsg').textContent, ''); cases++;
}
console.log('PASS auth recommendation feedback: ' + cases + ' deferred transport/session/modal cases; synthetic I/O only');
