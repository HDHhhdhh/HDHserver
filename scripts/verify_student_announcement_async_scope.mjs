import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
const args = process.argv.slice(2), rootArg = args.indexOf('--source-root');
const root = path.resolve(rootArg < 0 ? path.join(path.dirname(fileURLToPath(import.meta.url)), '..') : args[rootArg + 1]);
const moduleSource = fs.readFileSync(path.join(root, 'static/js/student/announcementState.js'), 'utf8');
const studentSource = fs.readFileSync(path.join(root, 'static/js/student.js'), 'utf8');
const marker = studentSource.indexOf('STUDENT_APP_ANNOUNCEMENT_DEEP_LINK_START');
const helperStart = studentSource.lastIndexOf('/*', marker), endMarker = '/* STUDENT_APP_ANNOUNCEMENT_DEEP_LINK_END */';
const helperEnd = studentSource.indexOf(endMarker, marker) + endMarker.length;
const closureStart = studentSource.indexOf('(() => {', studentSource.indexOf('공지 팝업 / 공지함'));
assert.ok(marker >= 0 && helperStart >= 0 && closureStart > helperStart);
const copy = value => JSON.parse(JSON.stringify(value)), same = (a, b) => assert.deepEqual(copy(a), b);
const flush = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };
const defer = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const response = (body = {}, status = 200) => ({ ok: status === 200, status, json: async () => copy(body), text: async () => String(body) });
class Element {
  constructor(id = '') {
    Object.assign(this, { id, style: {}, attrs: {}, handlers: {}, dataset: {}, children: [], hidden: false, disabled: false, value: '', checked: false, textContent: '', innerHTML: '' });
    this.classList = { add() {}, remove() {}, toggle() {} };
  }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  fire(type, target = this) { return (this.handlers[type] || []).map(fn => fn({ target, currentTarget: this, preventDefault() {}, stopPropagation() {} })); }
  querySelector() { return null; } querySelectorAll() { return []; } closest() { return null; } getClientRects() { return []; }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  getAttribute(k) { return this.attrs[k] ?? null; } setAttribute(k, v) { this.attrs[k] = String(v); }
  toggleAttribute(k, on) { if (on) this.attrs[k] = ''; else delete this.attrs[k]; }
  focus() {} scrollIntoView() {} append(...xs) { this.children.push(...xs); } replaceChildren(...xs) { this.children = xs; }
}
const notice = id => ({ id, title: id + ' title', content: id + ' content', requireCompletion: false });
const survey = (multiple = false) => ({ ...notice('A'), kind: 'survey', requireCompletion: true,
  survey: { status: 'public', anonymous: true, allowMultiple: multiple, questions: [{ id: 'q1', type: 'short', text: '질문', required: true, options: [] }] } });
function fixture({ isSurvey = false, multiple = false, publicMode = false } = {}) {
  const records = [isSurvey ? survey(multiple) : notice('A'), notice('B')];
  const ids = new Map(('announceModal announceHistoryModal noticeBtn noticeBadge annTitle annContent annReply annAnonymous annSendReply annReplyStatus annRead annSurvey annSurveyQuestions annSurveyError annSurveySubmit annSurveyMeta annHistoryList annHistoryClose').split(' ').map(id => [id, new Element(id)]));
  const answer = new Element(), field = new Element(); field.querySelector = () => answer;
  ids.get('annSurveyQuestions').querySelector = q => q === '[data-survey-qid="q1"]' ? field : null;
  let html = '';
  Object.defineProperty(ids.get('annSurveyQuestions'), 'innerHTML', { get: () => html, set: value => {
    if (document.activeElement === answer) document.activeElement = document.body;
    html = String(value); answer.value = html.match(/<input type="text" value="([^"]*)"/)?.[1] || '';
    answer.disabled = /<input type="text"[^>]*\bdisabled\b/.test(html);
  } });
  const document = new Element(); document.body = new Element(); document.hidden = false;
  document.activeElement = document.body;
  for (const node of [...ids.values(), answer]) {
    let disabled = node.disabled;
    Object.defineProperty(node, 'disabled', {get:()=>disabled,set:value=>{
      disabled=Boolean(value);
      if(disabled && document.activeElement===node) document.activeElement=document.body;
    }});
    node.focus = () => { document.activeElement = node; };
    node.getClientRects = () => node.hidden || node.disabled ? [] : [{}];
  }
  const announcementDialog = ids.get('announceModal');
  announcementDialog.children = [...ids.values()].filter(node => node !== announcementDialog && !['noticeBtn','noticeBadge','announceHistoryModal','annHistoryList','annHistoryClose'].includes(node.id));
  ids.get('annSurveyQuestions').children = [answer];
  ids.get('annSurveyQuestions').querySelector = q => q === '[data-survey-qid="q1"]' ? field : q === 'input:not(:disabled), textarea:not(:disabled)' && !answer.disabled ? answer : null;
  announcementDialog.querySelectorAll = () => ['annSendReply','annRead','annSurveySubmit'].map(id => ids.get(id)).filter(node => !node.disabled);
  document.querySelector = q => q.startsWith('#') ? ids.get(q.slice(1)) || null : null;
  document.createElement = tag => new Element(tag); document.createDocumentFragment = () => new Element();
  document.dispatchEvent = () => true;
  const writes = [], reads = [], alerts = [], intervals = [], timers = [];
  let pausedSid = null, pauseRead = false, remoteStatuses = {};
  const ctx = { document, URLSearchParams, location: { pathname: '/student/sid-a', search: '' }, STUDENT_APP_PUBLIC_MODE: publicMode,
    STUDENT_APP_PUBLIC_SESSION: { activeSid: () => 'sid-a', refreshSession: () => {
      if (!pausedSid) return Promise.resolve({ activeSid: 'sid-a' }); const gate = pausedSid; pausedSid = null; return gate.promise;
    } }, CSS: { escape: String }, CustomEvent: class { constructor(type, options) { this.type = type; Object.assign(this, options); } },
    console: { warn() {} }, alert: m => alerts.push(String(m)), handleStudentAppSessionFailure() {},
    setTimeout: (fn, delay) => { timers.push({ fn, delay }); return timers.length; }, clearTimeout() {}, requestAnimationFrame: fn => fn(),
    setInterval: fn => { intervals.push(fn); return intervals.length; }, studentAppRequest: (url, opt = {}) => {
      const method = opt.method || 'GET';
      if (method === 'GET' && (url.startsWith('/api/announcements?') || url.startsWith('/api/announce-status?'))) {
        const body = url.startsWith('/api/announcements?') ? records : remoteStatuses;
        if (!pauseRead) return Promise.resolve(response(body)); const gate = defer(); reads.push({ body: copy(body), gate }); return gate.promise;
      }
      if (method === 'POST' && ['/api/announce-submit', '/api/announce-ack'].includes(url)) {
        const gate = defer(); writes.push({ url, payload: JSON.parse(opt.body), gate }); return gate.promise;
      }
      throw new Error('Unexpected request: ' + method + ' ' + url);
    } };
  ctx.window = ctx; vm.createContext(ctx); vm.runInContext(moduleSource, ctx);
  // The whole init closure, original controller, renders and listeners execute.
  vm.runInContext(studentSource.slice(helperStart, helperEnd) + '\n' + studentSource.slice(closureStart), ctx);
  return { ids, answer, writes, reads, alerts, intervals, timers,
    open: id => { const item = new Element(); item.dataset.annHistoryId = id; item.closest = q => q === '[data-ann-history-id]' ? item : null; return ids.get('annHistoryList').fire('click', item); },
    send: (type, value = 'sent', anonymous = false) => {
      if (type === 'reply') { ids.get('annReply').value = value; ids.get('annAnonymous').checked = anonymous; }
      if (type === 'survey') answer.value = value;
      return ids.get(type === 'reply' ? 'annSendReply' : type === 'survey' ? 'annSurveySubmit' : 'annRead').fire('click');
    },
    pauseSid: () => { pausedSid = defer(); return pausedSid; },
    pauseReads: () => { pauseRead = true; },
    failReads: status => { pauseRead = false; reads.forEach(r => r.gate.resolve(response('failed', status))); },
    resumeReads: statuses => { remoteStatuses = copy(statuses); pauseRead = false; reads.forEach(r => r.gate.resolve(response(r.body))); },
    finish: async (index, tasks, status = 200) => { writes[index].gate.resolve(response(status === 200 ? {} : 'failed', status)); await Promise.all(tasks); await flush(); },
    section: id => { const text = ids.get('annHistoryList').innerHTML, start = text.indexOf('data-ann-history-id="' + id + '"'); return start < 0 ? '' : text.slice(start, text.indexOf('</button>', start)); },
    ui: () => [ids.get('annTitle').textContent, ids.get('announceModal').style.display, ids.get('annReplyStatus').textContent],
    focused: () => document.activeElement,
    pending: type => ids.get(type === 'reply' ? 'annSendReply' : type === 'survey' ? 'annSurveySubmit' : 'annRead').disabled,
  };
}
let cases = 0;
for (const type of ['reply', 'survey', 'ack']) {
  const f = fixture({ isSurvey: type === 'survey', publicMode: true }); await flush(); f.open('A');
  const gate = f.pauseSid(), task = f.send(type, 'A sent', true), duplicate = f.send(type, 'A sent', true);
  f.open('B'); f.ids.get('annReply').value = 'B draft'; f.ids.get('annAnonymous').checked = false; f.answer.value = 'B answer'; same(f.writes.length, 0);
  gate.resolve({ activeSid: 'sid-a' }); await flush(); same(f.writes.length, 1);
  same(f.writes[0].payload, type === 'reply' ? { sid: 'sid-a', id: 'A', reply: 'A sent', anonymous: true } : type === 'survey' ? { sid: 'sid-a', id: 'A', surveyAnswers: { q1: 'A sent' } } : { sid: 'sid-a', id: 'A' });
  await f.finish(0, [...task, ...duplicate]); same(f.ui(), ['B title', 'flex', '']); same(f.ids.get('annReply').value, 'B draft'); same(f.pending(type), false);
  f.open('A'); if (type === 'reply') same(f.ids.get('annReply').value, 'A sent');
  if (type === 'survey') same([f.answer.value, f.answer.disabled, f.ids.get('annSurveySubmit').hidden], ['A sent', true, true]); cases++;
}
for (const type of ['reply', 'survey']) {
  const f = fixture({ isSurvey: type === 'survey' }); await flush(); f.open('A'); const task = f.send(type, 'first'); await flush();
  f.open('B'); f.open('A'); f.send(type, 'second draft'); await flush(); same(f.writes.length, 1); same(f.pending(type), true);
  await f.finish(0, task); same(f.ui(), ['A title', 'flex', '']); same(type === 'reply' ? f.ids.get('annReply').value : f.answer.value, 'second draft');
  assert.ok(f.section('A').includes(type === 'reply' ? '내 답장: first' : '질문: first')); assert.ok(!f.section('B').includes(type === 'reply' ? '내 답장:' : '내 설문:')); cases++;
}
for (const type of ['reply', 'survey', 'ack']) {
  const f = fixture({ isSurvey: type === 'survey' }); await flush(); f.open('A'); const first = f.send(type, 'retry'); await flush();
  const payload = copy(f.writes[0].payload); await f.finish(0, first, 503); same(f.pending(type), false);
  same(type === 'survey' ? f.ids.get('annSurveyError').textContent : f.ui()[2], type === 'survey' ? '설문 제출에 실패했습니다.' : type === 'reply' ? '전송에 실패했습니다.' : '읽음 처리에 실패했습니다. 다시 눌러 주세요.');
  const retry = f.send(type, 'retry'); await flush(); same(f.writes.length, 2); same(f.writes[1].payload, payload); await f.finish(1, retry); cases++;
}
for (const type of ['reply', 'survey', 'ack']) {
  const f = fixture({ isSurvey: type === 'survey' }); await flush(); f.open('A'); const task = f.send(type); await flush(); f.open('B');
  await f.finish(0, task, 503); same(f.ui(), ['B title', 'flex', '']); same(f.ids.get('annSurveyError').textContent, ''); same(f.pending(type), false); cases++;
}
{
  const f = fixture(); await flush(); f.open('A');
  for (let i = 0; i < 3; i++) { const task = f.send('reply', 'reply ' + i); await flush(); await f.finish(i, task); }
  f.send('reply', 'fourth'); await flush(); same([f.writes.length, f.pending('reply'), f.alerts], [3, true, ['2번 더 답장 가능!', '마지막 답장 남음!', '이제 쉿!', '이제 쉿!']]); cases++;
}
{
  const f = fixture({ isSurvey: true, multiple: true }); await flush(); f.open('A');
  for (let i = 0; i < 2; i++) { const task = f.send('survey', 'answer ' + i), duplicate = f.send('survey', 'answer ' + i); await flush(); same(f.writes.length, i + 1); await f.finish(i, [...task, ...duplicate]); }
  same([f.ids.get('annSurveySubmit').textContent, f.pending('survey')], ['추가 제출', false]); assert.ok(f.section('A').includes('질문: answer 1')); cases++;
}
{
  const f = fixture({ isSurvey: true }); await flush(); const task = f.send('survey'); await flush(); await f.finish(0, task);
  f.open('B'); f.timers.filter(t => t.delay === 650).forEach(t => t.fn()); same(f.ui().slice(0, 2), ['B title', 'flex']); cases++;
}
{
  const f = fixture(); await flush(); f.open('A'); const a = f.send('ack'); await flush(); f.open('B'); const b = f.send('ack'); await flush();
  await f.finish(0, a); same([f.ui()[0], f.pending('ack')], ['B title', true]); await f.finish(1, b); same([f.ids.get('noticeBadge').textContent, f.ui()[1]], ['0', 'none']); cases++;
}
{
  const f = fixture(); await flush(); f.open('A'); const task = f.send('reply', 'committed'); await flush(); f.pauseReads(); f.intervals[0](); await flush(); same(f.reads.length, 2);
  await f.finish(0, task); f.resumeReads({ A: { reply: 'committed', repliedAt: '2026-10-01T00:00:00Z' } }); await flush(); assert.ok(f.section('A').includes('내 답장: committed')); assert.ok(!f.section('B').includes('내 답장:')); cases++;
}
for (const beforeResponse of [true, false]) {
  const f = fixture({ isSurvey: true, multiple: true }); await flush(); const task = f.send('survey', 'first'); await flush();
  if (beforeResponse) f.answer.value = 'next draft'; await f.finish(0, task); if (!beforeResponse) f.answer.value = 'next draft';
  f.timers.filter(t => t.delay === 650).forEach(t => t.fn()); same([f.answer.value, f.answer.disabled, f.ui()[0], f.ui()[1]], ['next draft', false, 'A title', 'flex']); same(f.ids.get('annSurveySubmit').textContent, '추가 제출'); cases++;
}
{
  const f = fixture({ isSurvey: true, multiple: true }); await flush(); const first = f.send('survey'); await flush(); await f.finish(0, first);
  f.send('survey', ''); await flush(); same(f.ids.get('annSurveyError').textContent, '필수 질문에 모두 응답해 주세요.');
  f.timers.filter(t => t.delay === 650).forEach(t => t.fn()); same(f.ids.get('annSurveyError').textContent, '필수 질문에 모두 응답해 주세요.'); same(f.ui()[1], 'flex'); cases++;
}
for (const failed of [false, true]) {
  const f = fixture({ isSurvey: true, multiple: true }); await flush(); const first = f.send('survey', 'same'); await flush(); await f.finish(0, first);
  const oldTimers = f.timers.filter(t => t.delay === 650), second = f.send('survey', 'same'); await flush(); same(f.writes.length, 2);
  if (failed) await f.finish(1, second, 503); oldTimers.forEach(t => t.fn()); same(f.ui().slice(0, 2), ['A title', 'flex']);
  if (failed) same(f.ids.get('annSurveyError').textContent, '설문 제출에 실패했습니다.');
  else { same(f.pending('survey'), true); await f.finish(1, second); f.timers.filter(t => t.delay === 650 && !oldTimers.includes(t)).forEach(t => t.fn()); same(f.ui()[0], 'B title'); } cases++;
}
for (const closePending of [false,true]) {
  const f=fixture();await flush();f.pauseReads();
  const tasks=f.ids.get('noticeBtn').fire('click');await flush();
  same(f.reads.length,2);same(f.ids.get('announceHistoryModal').style.display,'flex');
  assert.match(f.ids.get('annHistoryList').innerHTML,/role="status">공지를 불러오는 중…/);
  if(closePending)f.ids.get('annHistoryClose').fire('click');
  f.resumeReads({});await Promise.all(tasks);await flush();
  same(f.ids.get('announceHistoryModal').style.display,closePending?'none':'flex');
  assert.ok(f.section('A'));same(f.writes.length,0);cases++;
}
{
  const f=fixture();await flush();f.pauseReads();
  const first=f.ids.get('noticeBtn').fire('click'),second=f.ids.get('noticeBtn').fire('click');await flush();
  same(f.reads.length,2);f.resumeReads({});await Promise.all([...first,...second]);await flush();
  assert.ok(f.section('B'));same(f.writes.length,0);cases++;
}
{
  const f=fixture();await flush();f.pauseReads();const tasks=f.ids.get('noticeBtn').fire('click');await flush();
  f.failReads(503);await Promise.all(tasks);await flush();
  same(f.ids.get('annHistoryList').innerHTML,'<div class="muted">공지를 불러오지 못했습니다.</div>');cases++;
}
{
  const f=fixture({publicMode:true});await flush();f.pauseReads();const tasks=f.ids.get('noticeBtn').fire('click');await flush();
  assert.notEqual(f.ids.get('announceHistoryModal').style.display,'flex');
  f.resumeReads({});await Promise.all(tasks);await flush();same(f.ids.get('announceHistoryModal').style.display,'flex');cases++;
}
{
  const f=fixture({isSurvey:true,multiple:false});await flush();f.open('A');
  f.answer.focus();const tasks=f.send('survey','focus regression');
  await flush();
  await f.finish(0,tasks);
  assert.ok(f.ids.get('announceModal').contains(f.focused()), 'survey rerender returns focus to an enabled control inside the dialog');
  same(f.ui()[1],'flex');
  for (const handler of f.ids.get('announceModal').handlers.keydown || []) handler({key:'Escape',preventDefault(){},stopPropagation(){}});
  same(f.ui()[1],'none', 'Escape closes the completed survey through its modal owner');
  cases++;
}
for(const status of [200,500]) {
  const f=fixture({isSurvey:true,multiple:true});await flush();f.open('A');
  f.ids.get('annSurveySubmit').focus();const tasks=f.send('survey','button-focused submission');await flush();
  assert.equal(f.ids.get('announceModal').contains(f.focused()),false,'disabling the focused submit button releases browser focus');
  await f.finish(0,tasks,status);
  assert.ok(f.ids.get('announceModal').contains(f.focused()),'after success or failure unlock, focus returns to the same open dialog');cases++;
}
console.log('PASS student announcement async safety: ' + cases + ' whole actual init/controller/listener and pending history cases');
