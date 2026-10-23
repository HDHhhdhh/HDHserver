import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { PaymentClient, paymentMessage } from '../static/js/admin/features/paymentClient.js';

// Source/HTML only: no app import, runtime files, real HTTP, or browser server.
const pagePath = new URL('../static/js/admin/features/paymentsPage.js', import.meta.url);
const source = fs.readFileSync(pagePath, 'utf8');
const html = fs.readFileSync(new URL('../static/payments.html', import.meta.url), 'utf8');
const clone = (value) => JSON.parse(JSON.stringify(value));
const decode = (value) => String(value).replace(/&(amp|lt|gt|quot|#39);/g,
  (_, key) => ({ amp:'&', lt:'<', gt:'>', quot:'"', '#39':"'" }[key]));
const attributes = (markup) => Object.fromEntries([...markup.matchAll(/([\w:-]+)(?:="([^"]*)")?/g)]
  .map(([, name, value]) => [name, decode(value ?? '')]));

class Element {
  constructor(tag, attrs = {}) {
    this.tagName = tag.toUpperCase();
    this.id = attrs.id || '';
    this.name = attrs.name || '';
    this.type = attrs.type || '';
    this._value = attrs.value || '';
    this._max = attrs.max || '';
    this.hidden = Object.hasOwn(attrs, 'hidden');
    this.disabled = Object.hasOwn(attrs, 'disabled');
    this.required = Object.hasOwn(attrs, 'required');
    this.options = [];
    this.listeners = new Map();
    this._html = '';
    this.textContent = '';
    this.open = false;
  }
  get value() { return this._value; }
  set value(value) {
    const text = String(value);
    this._value = this.tagName === 'SELECT' && !this.options.some((o) => o.value === text) ? '' : text;
  }
  get max() { return this._max; }
  set max(value) { this._max = String(value); }
  get innerHTML() { return this._html; }
  set innerHTML(value) {
    this._html = String(value);
    if (this.tagName === 'SELECT') {
      this.options = [...this._html.matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/g)]
        .map(([, attrs, text]) => ({ ...attributes(attrs), textContent:decode(text) }));
      this._value = (this.options.find((o) => Object.hasOwn(o, 'selected')) || this.options[0])?.value || '';
    }
    this.onHtml?.(this._html);
  }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
  async emit(type, properties = {}) {
    assert.ok(this.listeners.has(type), `${this.id} has a real ${type} listener`);
    const event = { target:this, preventDefault() {}, ...properties };
    await Promise.all(this.listeners.get(type).map((listener) => listener(event)));
  }
  showModal() { this.open = true; }
  close() { this.open = false; }
}

function createDocument() {
  const nodes = new Map();
  for (const [, tag, attrs] of html.matchAll(/<([a-z][\w-]*)\b([^>]*)>/gi)) {
    const parsed = attributes(attrs);
    if (parsed.id) nodes.set(parsed.id, new Element(tag, parsed));
  }
  for (const [, attrs, body] of html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)) {
    const id = attributes(attrs).id;
    if (id) nodes.get(id).innerHTML = body;
  }
  const get = (id) => {
    const node = nodes.get(id);
    assert.ok(node, `HTML node #${id} exists`);
    return node;
  };
  // Parse the actual generated form controls, including selected/default options.
  let controls = [], dynamicIds = [];
  get('dialogFields').onHtml = (markup) => {
    for (const id of dynamicIds) nodes.delete(id);
    controls = [];
    dynamicIds = [];
    for (const match of markup.matchAll(/<input\b([^>]*?)>|<(select|textarea)\b([^>]*)>([\s\S]*?)<\/\2>/g)) {
      const tag = match[2] || 'input', parsed = attributes(match[1] ?? match[3]);
      const element = new Element(tag, parsed);
      if (tag === 'select') element.innerHTML = match[4];
      else if (tag === 'textarea') element.value = decode(match[4]);
      controls.push(element);
    }
    for (const [, tag, attrs] of markup.matchAll(/<([a-z][\w-]*)\b([^>]*)>/gi)) {
      const parsed = attributes(attrs);
      if (parsed.id) { nodes.set(parsed.id, new Element(tag, parsed)); dynamicIds.push(parsed.id); }
    }
  };
  get('dialogFields').querySelectorAll = (selector) => {
    assert.equal(selector, 'input,select,textarea');
    return controls;
  };
  get('editForm').elements = { namedItem:(name) => controls.find((e) => e.name === name) || null };
  get('accountFilter').value = 'all';
  class FormData {
    constructor(form) { assert.equal(form, get('editForm')); }
    entries() { return controls.filter((e) => e.name && !e.disabled).map((e) => [e.name, e.value])[Symbol.iterator](); }
  }
  return { document:{ getElementById:(id) => nodes.get(id) || null }, get, FormData };
}

function fixtures() {
  const chosen = { id:'package-chosen', date:'2026-09-01', units:8, discount:1, memo:'반올림 검증용',
    lines:[{ label:'기본', units:8, unitPrice:56250 }] };
  const newer = { id:'package-newer', date:'2026-10-01', units:4, discount:0, memo:'',
    lines:[{ label:'특강', units:4, unitPrice:37500 }] };
  const balance = { netAmount:449999, usedUnits:0, cancelledUnits:0, remainingUnits:8,
    creditAmount:0, billed:449999, paid:449999, due:0, refundDue:0 };
  const otherBalance = { netAmount:150000, usedUnits:0, cancelledUnits:0, remainingUnits:4,
    creditAmount:0, billed:150000, paid:150000, due:0, refundDue:0 };
  const summary = { configured:true, remainingUnits:12, usedUnits:0, billed:599999,
    paid:599999, due:0, refundDue:0, lastPaymentDate:'2026-10-01' };
  const session = (id, date, memo) => ({ id, date, memo, slot:2, kind:'regular', status:'planned',
    packageId:chosen.id, lineIndex:0, chargedUnits:0 });
  const account = { config:{ startsOn:'2026-09-01', policy:'attended', lines:chosen.lines },
    packages:[chosen, newer], sessions:[session('prior-month', '2026-09-30', '9월 원장 수업'),
      session('next-month', '2026-11-01', '11월 원장 수업')],
    receipts:[{ id:'paid-chosen', packageId:chosen.id, lineIndex:0, date:'2026-09-01',
      kind:'payment', method:'card', amount:449999, memo:'' },
      { id:'paid-newer', packageId:newer.id, lineIndex:0, date:'2026-10-01',
        kind:'payment', method:'transfer', amount:150000, memo:'' }] };
  const old = { revision:10, account, summary, balances:{ [chosen.id]:balance, [newer.id]:otherBalance },
    lineBalances:{ [chosen.id]:[balance], [newer.id]:[otherBalance] }, audit:[] };
  const fresh = clone(old);
  fresh.revision = 11;
  // One attended lesson plus one earlier cancellation/refund, from another editor.
  const changed = { netAmount:449999, usedUnits:1, cancelledUnits:1, remainingUnits:6,
    creditAmount:56249, billed:393750, paid:430000, due:0, refundDue:36250 };
  fresh.balances[chosen.id] = changed;
  fresh.lineBalances[chosen.id] = [changed];
  fresh.summary = { ...summary, remainingUnits:10, usedUnits:1, billed:543750, paid:580000, refundDue:36250 };
  fresh.account.sessions.push({ ...session('other-editor', '2026-10-20', '다른 창 출석'), status:'attended', chargedUnits:1 });
  fresh.account.receipts.push({ id:'other-refund', packageId:chosen.id, lineIndex:0, date:'2026-10-20',
    kind:'refund', method:'refund', amount:-19999, cancelledUnits:1, creditAmount:56249, memo:'다른 창 취소' });
  return { old, fresh, overview:{ today:'2026-10-24', plans:[{ id:'standard', label:'기본', lines:chosen.lines }],
    students:[{ sid:'qa-payment-page', student:{ name:'합성 학생', school:'QA 학교', curriculum:'수학', grade:'고1' },
      archived:false, ...summary, revision:10 }] } };
}

async function createPage(pageSource = source) {
  const dom = createDocument(), data = fixtures(), requests = [], calendars = [];
  let current = data.old;
  const request = async (url, options = {}) => {
    const parsed = new URL(url, 'https://payment-page.test');
    requests.push({ path:parsed.pathname, params:Object.fromEntries(parsed.searchParams),
      method:options.method || 'GET', body:options.body ? JSON.parse(options.body) : null });
    if (parsed.pathname === '/api/payments/overview') return clone(data.overview);
    if (parsed.pathname === '/api/payments/account') return clone(current);
    if (parsed.pathname === '/api/payments/evidence') {
      const month = parsed.searchParams.get('month');
      return { events:month === '2026-09' ? [{ date:'2026-09-30', slot:2, kind:'attendance', label:'9월 운영판 출결' }]
        : month === '2026-11' ? [{ date:'2026-11-01', slot:2, kind:'attendance', label:'11월 운영판 출결' }] : [] };
    }
    if (parsed.pathname === '/api/payments/command') {
      current = data.fresh;
      throw Object.assign(new Error('다른 창에서 변경했습니다.'), { status:409 });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  class InjectedPaymentClient extends PaymentClient {
    constructor() { super({ request, uuid:() => '00000000-0000-4000-8000-000000000001' }); }
  }
  class Calendar {
    constructor(element, options) { this.element = element; this.options = options; this.events = []; calendars.push(this); }
    render() {}
    gotoDate(date) { this.date = date; }
    removeAllEvents() { this.events = []; }
    addEventSource(events) { this.events.push(...clone(events)); }
  }
  const executable = pageSource.replace(/^import\s+\{[^}]+\}\s+from\s+['"][^'"]+['"];?\s*$/gm, '');
  assert.doesNotMatch(executable, /^\s*import\b/m, 'all page dependencies must be explicitly injected');
  vm.runInNewContext(executable, { document:dom.document, FormData:dom.FormData,
    window:{ FullCalendar:{ Calendar }, addEventListener() {} }, fetchJson:request,
    PaymentClient:InjectedPaymentClient, paymentMessage, URLSearchParams, console },
  { filename:pagePath.pathname, timeout:1000 });
  const settle = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };
  await settle();
  const sid = dom.get('studentList').innerHTML.match(/data-sid="([^"]+)"/)?.[1];
  assert.equal(sid, 'qa-payment-page', 'actual overview rendering supplies the selection target');
  const target = { dataset:{ sid }, closest:(selector) => selector === '[data-sid]' ? target : null };
  await dom.get('studentList').emit('click', { target });
  await settle();
  assert.equal(dom.get('accountContent').hidden, false);
  assert.equal(calendars.length, 1);
  return { ...dom, requests, calendar:calendars[0], settle,
    field:(name) => { const field = dom.get('editForm').elements.namedItem(name); assert.ok(field, name); return field; } };
}

async function verifyCalendarSelection(callback) {
  const page = await createPage();
  assert.equal(page.get('historyMonth').value, '2026-10');
  const select = page.calendar.options[callback];
  assert.equal(typeof select, 'function', `actual FullCalendar ${callback} callback is registered`);
  select(callback === 'dateClick' ? { dateStr:'2026-09-30' } : { event:{ startStr:'2026-09-30T14:00:00' } });
  await page.settle();
  assert.equal(page.get('historyMonth').value, '2026-09', `${callback}: synchronize the adjacent month`);
  assert.equal(page.get('historyDate').value, '2026-09-30');
  assert.equal(page.get('dayTitle').textContent, '2026-09-30');
  assert.equal(page.calendar.date, '2026-09-01');
  const evidenceRequests = page.requests.filter((r) => r.path === '/api/payments/evidence');
  assert.deepEqual(evidenceRequests.map((r) => r.params.month), ['2026-10', '2026-09']);
  assert.equal(evidenceRequests[1].params.sid, 'qa-payment-page');
  assert.match(page.get('dayEvents').innerHTML, /9월 원장 수업/);
  assert.match(page.get('dayEvents').innerHTML, /9월 운영판 출결/);
  assert.doesNotMatch(page.get('dayEvents').innerHTML, /이 날짜의 기록이 없습니다|11월 원장 수업/);
  assert.ok(page.calendar.events.some((e) => e.id === 'prior-month'));
  assert.equal(page.requests.filter((r) => r.method !== 'GET').length, 0);
}

async function verifyConflictReload() {
  const page = await createPage();
  await page.get('refundOpen').emit('click');
  assert.equal(page.get('editDialog').open, true);
  page.field('packageId').value = 'package-chosen';
  await page.get('editForm').emit('change', { target:page.field('packageId') });
  page.field('lineIndex').value = '0';
  await page.get('editForm').emit('change', { target:page.field('lineIndex') });
  page.field('date').value = '2026-10-23';
  page.field('units').value = '1';
  page.field('amount').value = '50000';
  page.field('memo').value = '입력 중인 취소 사유';
  await page.get('editForm').emit('input', { target:page.field('units') });
  const draft = () => Object.fromEntries(['packageId','lineIndex','date','units','amount','memo']
    .map((name) => [name, page.field(name).value]));
  const before = draft();
  assert.equal(page.field('creditAmount').value, '56249');
  assert.equal(page.field('units').max, '8');
  assert.equal(page.field('amount').max, '56249');
  await page.get('editForm').emit('submit');
  assert.equal(page.get('dialogReload').hidden, false, '409 exposes the real recovery action');
  assert.equal(page.get('dialogSave').disabled, true);
  assert.deepEqual(draft(), before, '409 preserves the draft');
  const first = page.requests.find((r) => r.path === '/api/payments/command');
  assert.equal(first.body.baseRevision, 10);
  assert.equal(first.body.lineIndex, 0);
  await page.get('dialogReload').emit('click');
  await page.settle();
  assert.equal(page.get('editDialog').open, true);
  assert.equal(page.get('dialogReload').hidden, true);
  assert.equal(page.get('dialogSave').disabled, false);
  assert.deepEqual(draft(), before, 'reload preserves package, course, date, units, cash and reason');
  assert.match(page.get('studentList').innerHTML, /남은 10회/, 'student card follows the refreshed account');
  assert.match(page.get('accountStats').innerHTML, /<strong>10회<\/strong>/);
  assert.equal(page.field('creditAmount').value, '56250', 'recompute the next rounded 1/n credit');
  assert.equal(page.field('units').max, '6', 'use the latest remaining lessons');
  assert.equal(page.field('amount').max, '92500', 'use the latest net receipts and existing credit');
  assert.equal(page.get('paymentPreview').textContent, '취소 후 5회 남음 · 청구 감액 56,250원 · 환불 가능 92,500원');
  assert.match(page.field('packageId').options.find((o) => o.value === 'package-chosen').textContent, /남은 6회/);
  assert.match(page.field('lineIndex').options.find((o) => o.value === '0').textContent, /남은 6\/8회/);
  for (const name of Object.keys(before)) assert.equal(page.field(name).disabled, false);
  assert.equal(page.requests.filter((r) => r.path === '/api/payments/account').length, 2);
  assert.equal(page.requests.filter((r) => r.path === '/api/payments/command').length, 1,
    'reload must not automatically resubmit the financial operation');
  await page.get('editForm').emit('submit');
  const retry = page.requests.filter((r) => r.path === '/api/payments/command')[1];
  assert.equal(retry.body.baseRevision, 11, 'explicit retry uses the refreshed revision');
  assert.equal(retry.body.amount, 50000);
  assert.equal(retry.body.memo, before.memo);
}

const failures = [];
for (const [label, verify] of [
  ['calendar dateClick', () => verifyCalendarSelection('dateClick')],
  ['calendar eventClick', () => verifyCalendarSelection('eventClick')],
  ['409 draft/balance recovery', verifyConflictReload],
]) {
  try { await verify(); }
  catch (cause) { failures.push(new Error(label, { cause })); }
}
if (failures.length) throw new AggregateError(failures, `${failures.length} payment page checks failed`);
console.log('Payment page: calendar date/event selection and 409 draft/balance recovery passed (VM, synthetic data only).');
