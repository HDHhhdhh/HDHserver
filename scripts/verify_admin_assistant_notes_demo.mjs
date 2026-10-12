// Run with: node scripts/verify_admin_assistant_notes_demo.mjs

class MemoryStorage {
  #values = new Map();

  get length() {
    return this.#values.size;
  }

  getItem(key) {
    return this.#values.has(key) ? this.#values.get(key) : null;
  }

  setItem(key, value) {
    this.#values.set(String(key), String(value));
  }

  removeItem(key) {
    this.#values.delete(String(key));
  }

  key(index) {
    return Array.from(this.#values.keys())[index] ?? null;
  }
}

function check(condition, message) {
  if (!condition) throw new Error(message);
}

globalThis.sessionStorage = new MemoryStorage();

const { applyAssistantStudentNotesRequest } = await import(
  '../static/js/admin/demo/assistantStudentNotesContract.js'
);
const { createDemoFetch } = await import('../static/js/admin/demo/fetch.js');

const fixedCreatedAt = () => '2026-08-20T12:34:56+09:00';
const contractStore = {
  students: [{ id: '007' }],
  assistantStudentNotes: [],
};
const created = applyAssistantStudentNotesRequest({
  method: 'POST',
  path: '/api/assistant-student-notes',
  body: {
    student_id: '007',
    content: '데모 학생 확인',
    author: '귤',
    remind_on: '2026-08-21',
  },
  store: contractStore,
  createdAt: fixedCreatedAt,
});
check(created.status === 201 && created.changed, 'shared contract create failed');
check(created.payload.note.remind_on === '2026-08-21', 'shared contract reminder was lost');

const listed = applyAssistantStudentNotesRequest({
  method: 'GET',
  path: '/api/assistant-student-notes',
  params: new URLSearchParams({ student_id: '007' }),
  store: contractStore,
  createdAt: fixedCreatedAt,
});
check(listed.status === 200 && listed.payload.notes.length === 1, 'shared contract list failed');

const pinned = applyAssistantStudentNotesRequest({
  method: 'PATCH',
  path: `/api/assistant-student-notes/${created.payload.note.id}/pin`,
  body: { student_id: '007', pinned: true },
  store: contractStore,
  createdAt: fixedCreatedAt,
});
check(pinned.status === 200 && pinned.payload.note.pinned === true, 'shared contract pin failed');

const wrongStudent = applyAssistantStudentNotesRequest({
  method: 'GET',
  path: '/api/assistant-student-notes',
  params: new URLSearchParams({ student_id: '999' }),
  store: contractStore,
  createdAt: fixedCreatedAt,
});
check(wrongStudent.status === 404, 'shared contract accepted an unknown student');

let forwardedApiCalls = 0;
const originalFetch = async () => {
  forwardedApiCalls += 1;
  return new Response('{}', { status: 500 });
};
const root = {
  fetch: originalFetch,
  location: {
    href: 'http://localhost/demo/rh3123',
    origin: 'http://localhost',
    pathname: '/demo/rh3123',
  },
};
const demoFetch = createDemoFetch({ window: root, originalFetch });
const studentsResponse = await demoFetch('/api/students');
const students = await studentsResponse.json();
const studentId = String(students[0]?.id || '');
check(studentsResponse.ok && studentId, 'demo student fixture is missing');

const initialResponse = await demoFetch(
  `/api/assistant-student-notes?student_id=${encodeURIComponent(studentId)}`,
);
const initial = await initialResponse.json();
check(initialResponse.ok && initial.ok && Array.isArray(initial.notes), 'demo assistant note list failed');

const createResponse = await demoFetch('/api/assistant-student-notes', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    student_id: studentId,
    content: '브라우저 데모 메모',
    author: '세빈',
    remind_on: '',
  }),
});
const createPayload = await createResponse.json();
check(createResponse.status === 201 && createPayload.note.content === '브라우저 데모 메모', 'demo note create failed');

const noteId = createPayload.note.id;
const editResponse = await demoFetch(`/api/assistant-student-notes/${noteId}`, {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ student_id: studentId, content: '수정된 데모 메모', author: '세빈' }),
});
const edited = await editResponse.json();
check(editResponse.ok && edited.note.content === '수정된 데모 메모', 'demo note edit failed');

const reloadedFetch = createDemoFetch({ window: root, originalFetch });
const persisted = await (
  await reloadedFetch(`/api/assistant-student-notes?student_id=${encodeURIComponent(studentId)}`)
).json();
check(persisted.notes.some(note => note.id === noteId && note.content === '수정된 데모 메모'), 'demo note did not persist');

const deleteResponse = await reloadedFetch(`/api/assistant-student-notes/${noteId}`, {
  method: 'DELETE',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ student_id: studentId }),
});
check(deleteResponse.ok, 'demo note delete failed');
const afterDelete = await (
  await reloadedFetch(`/api/assistant-student-notes?student_id=${encodeURIComponent(studentId)}`)
).json();
check(!afterDelete.notes.some(note => note.id === noteId), 'deleted demo note is still listed');
check(forwardedApiCalls === 0, 'demo assistant notes reached the live fetch implementation');

// Add before the final demo-verifier success message.
{
  const [{ default: fs }, { default: vm }, { default: assert }, { createHash }] = await Promise.all([
    import('node:fs'), import('node:vm'), import('node:assert/strict'), import('node:crypto'),
  ]);
  const source = fs.readFileSync(new URL('../static/js/admin/features/assistantStudentNotes.js', import.meta.url), 'utf8').replaceAll('\r\n', '\n');
  const hash = value => createHash('sha256').update(value).digest('hex');
  // This DOM fixture covers created elements/properties, node movement and
  // listeners. SVG innerHTML is opaque; no native parser/layout evidence is claimed.
  class NoteElement {
    constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.attrs = {}; this.listeners = {}; this.className = ''; this.disabled = false; this.scrollTop = 99; this.parentNode = null; this._text = ''; }
    get textContent() { return this._text + this.children.map(x => x.textContent).join(''); }
    set textContent(value) { this.replaceChildren(); this._text = String(value); }
    set innerHTML(_markup) { this.replaceChildren(); }
    get isConnected() { return this.parentNode ? this.parentNode.isConnected : this.connected === true; }
    get classList() {
      return { contains: name => this.className.split(/\s+/).includes(name), toggle: (name, on) => {
        const names = new Set(this.className.split(/\s+/).filter(Boolean));
        if (on) names.add(name); else names.delete(name); this.className = [...names].join(' ');
      } };
    }
    append(...nodes) { for (const node of nodes) {
      if (node.parentNode) node.parentNode.children.splice(node.parentNode.children.indexOf(node), 1);
      node.parentNode = this; this.children.push(node);
    } }
    appendChild(node) { this.append(node); return node; }
    replaceChildren(...nodes) { for (const node of this.children) node.parentNode = null; this.children = []; this._text = ''; this.append(...nodes); }
    setAttribute(name, value) { this.attrs[name] = String(value); }
    getAttribute(name) { return this.attrs[name] ?? null; }
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
    querySelectorAll(selector) {
      const matches = node => selector[0] === '.' ? node.classList.contains(selector.slice(1))
        : selector.startsWith('[data-') ? Object.hasOwn(node.dataset, selector.slice(6, -1).replace(/-([a-z])/g, (_, c) => c.toUpperCase()))
          : node.tagName === selector;
      const found = [], visit = node => { for (const child of node.children) { if (matches(child)) found.push(child); visit(child); } };
      visit(this); return found;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  }
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : ['2026-10-03T12:00:00'])); }
  }
  const n = (id, fields = {}) => ({ id, content: `메모 ${id}`, created_at: '2026-10-01T09:00:00+09:00', created_by: '귤', pinned: false, unknown: { keep: true }, ...fields });
  const fixtures = [
    { name: 'due outranks pin; pin then reminder rank', notes: [
      n(1, { pinned: true }), n(2, { remind_on: '2026-10-03', created_at: '2026-09-01T09:00:00+09:00' }),
      n(3, { pinned: true, remind_on: '2026-10-04' }), n(4, { pinned: true, remind_on: '2026-10-02' }),
      n(5, { pinned: 1, remind_on: '2026-10-03' }), n(6, { remind_on: '2026-10-03', created_at: '2026-10-02T09:00:00+09:00' }),
      n(7, { remind_on: '2026-10-04' }), n(8), n(9, { remind_on: '2026-10-02' }),
    ], order: ['5','6','2','3','1','4','7','8','9'], pins: ['1','3','4','5'] },
    { name: 'upcoming and past dates ascending before created time', notes: [
      n(11, { remind_on: '2026-10-06', created_at: '2026-10-02T09:00:00+09:00' }), n(12, { remind_on: '2026-10-04' }),
      n(14, { remind_on: '2026-10-02' }), n(13, { remind_on: '2026-09-01', created_at: '2026-10-02T09:00:00+09:00' }),
    ], order: ['12','11','13','14'], pins: [] },
    { name: 'newest then numeric ID; invalid creation dates; updated fallback', notes: [
      n(21), n(22), n(23, { created_at: '2026-10-02T09:00:00+09:00' }),
      n(24, { created_at: 'bad-date', updated_at: '2026-10-02T09:00:00+09:00' }),
      n(25, { created_at: '', updated_at: '2026-10-02T09:00:00+09:00' }), n(26, { created_at: 'bad-date' }),
    ], order: ['25','23','22','21','26','24'], pins: [] },
    { name: 'mixed pin values use exact existing pin vocabulary', notes: [
      n(31, { pinned: true }), n(32, { pinned: 1 }), n(33, { pinned: '1' }), n(34, { pinned: 'true' }),
      n(35, { pinned: false }), n(36, { pinned: 0 }), n(37, { pinned: '0' }), n(38, { pinned: null }), n(39, { pinned: undefined }),
    ], order: ['33','32','31','39','38','37','36','35','34'], pins: ['31','32','33'] },
    { name: 'reminder DOM and malformed/impossible legacy date behavior', notes: [
      n(41, { remind_on: '2026-10-03', content: '<b>문자 그대로</b>' }), n(42, { remind_on: '2026-10-04' }),
      n(43, { remind_on: '2026-09-30' }), n(44, { remind_on: '2026/10/03' }),
      n(45, { remind_on: '2026-02-30' }), n(46, { remind_on: 'bad-date', created_at: 'bad-date' }),
    ], order: ['41','42','44','46','45','43'], pins: [] },
    { name: 'exact comparator ties stay stable, including nonnumeric legacy IDs', notes: [
      n(77, { content: '동시 첫째' }), n('legacy-b', { created_at: 'bad-date' }),
      n(77, { content: '동시 둘째' }), n('legacy-a', { created_at: 'bad-date' }),
    ], order: ['77','77','legacy-b','legacy-a'], pins: [], contents: ['동시 첫째','동시 둘째','메모 legacy-b','메모 legacy-a'] },
  ];
  const deepFreeze = value => { if (value && typeof value === 'object') { Object.values(value).forEach(deepFreeze); Object.freeze(value); } return value; };
  fixtures.forEach(f => deepFreeze(f.notes));
  let apiCalls = 0;
  const forbiddenApi = () => { apiCalls++; throw new Error('render fixture must not use transport'); };
  const context = vm.createContext({ Date: FixedDate, Element: NoteElement,
    document: { createElement: tag => new NoteElement(tag) },
    requestAnimationFrame: callback => callback(), api: { getStrict: forbiddenApi, post: forbiddenApi },
  });
  const executable = source.replace(/^import[^\n]+;\s*$/gm, '').replace(/\bexport function /g, 'function ');
  assert.equal(/^import /m.test(executable), false, 'no actual module imports');
  vm.runInContext(executable + '\nglobalThis.renderFixture = renderNotes;', context, { filename: 'assistantStudentNotes.render.js' });
  for (const fixture of fixtures) for (const existingReadOnly of [false, true]) {
    const root = new NoteElement('section'), list = new NoteElement('div'); root.connected = true;
    root.dataset.existingReadOnly = String(existingReadOnly); list.dataset.noteList = ''; root.append(list);
    const before = hash(JSON.stringify(fixture.notes)), identities = fixture.notes.slice();
    const callbacks = [], renderOptions = { scrollTop: 42, pinFeedbackNoteId: fixture.order[0],
      onTogglePin: note => callbacks.push(['pin', note]), onEdit: note => callbacks.push(['edit', note]), onDelete: note => callbacks.push(['delete', note]),
    };
    context.renderFixture(root, fixture.notes, renderOptions);
    const articles = list.children;
    assert.deepEqual(articles.map(x => x.dataset.noteId), fixture.order, fixture.name);
    assert.equal(hash(JSON.stringify(fixture.notes)), before, 'note input bytes preserved');
    identities.forEach((note, i) => assert.equal(fixture.notes[i], note, 'input array order/identity preserved'));
    assert.equal(list.scrollTop, 42, 'explicit read-only render keeps requested scroll');
    assert.equal(articles[0].classList.contains('is-pin-feedback'), true);
    for (const article of articles) {
      const pinned = fixture.pins.includes(article.dataset.noteId);
      assert.equal(article.dataset.notePinned, String(pinned));
      assert.equal(article.classList.contains('is-pinned'), pinned);
      assert.equal(article.querySelector('.assistant-note-pin').getAttribute('aria-pressed'), String(pinned));
      for (const selector of ['.assistant-note-pin','.assistant-note-edit','.assistant-note-delete']) assert.equal(article.querySelector(selector).disabled, existingReadOnly, 'existingReadOnly applies to each existing-note action');
    }
    if (fixture.contents) assert.deepEqual(articles.map(x => x.querySelector('.assistant-note-item-content').textContent), fixture.contents);
    if (fixture.name.startsWith('reminder DOM')) {
      const expected = { 41: ['due','[확인 필요]','10/1(목)','→','10/3(토)'], 42: ['upcoming','[확인 예정]','10/1(목)','→','10/4(일)'],
        43: ['past','[지난 확인일]','10/1(목)','→','9/30(수)'], 45: ['past','[지난 확인일]','10/1(목)','→','2/30(월)'] };
      for (const article of articles) {
        const info = article.querySelector('.assistant-note-reminder-info'), literal = expected[article.dataset.noteId];
        assert.equal(Boolean(info), Boolean(literal)); assert.equal(article.classList.contains('has-reminder'), Boolean(literal));
        if (literal) {
          assert.deepEqual([info.dataset.reminderState, info.querySelector('.assistant-note-reminder-badge').textContent,
            ...info.querySelector('.assistant-note-reminder-dates').children.map(x => x.textContent)], literal);
          const body = article.querySelector('.assistant-note-reminder-body');
          assert.equal(body.classList.contains('is-stacked'), true);
          assert.deepEqual(body.children.map(x => x.className), ['assistant-note-item-author-group','assistant-note-item-content','assistant-note-action-group']);
          assert.equal(article.querySelector('time'), null, 'reminder uses compact dates instead of standalone time');
        }
      }
      assert.equal(articles[0].querySelector('.assistant-note-item-content').textContent, '<b>문자 그대로</b>');
      assert.equal(articles.find(x => x.dataset.noteId === '46').querySelector('time').textContent, 'bad-date');
    }
    if (!existingReadOnly) {
      for (const [selector, kind] of [['.assistant-note-pin','pin'],['.assistant-note-edit','edit'],['.assistant-note-delete','delete']]) {
        articles[0].querySelector(selector).listeners.click[0]({ preventDefault() {}, stopPropagation() {} });
        assert.equal(callbacks.at(-1)[0], kind); assert.ok(fixture.notes.includes(callbacks.at(-1)[1]), 'listener receives original note');
      }
    }
  }
  const emptyRoot = new NoteElement('section'), emptyList = new NoteElement('div'); emptyList.dataset.noteList = ''; emptyRoot.append(emptyList);
  context.renderFixture(emptyRoot, Object.freeze([]));
  assert.equal(emptyList.children[0].textContent, '아직 등록된 댓글이 없습니다.');
  assert.equal(apiCalls, 0, 'actual full-module rendering stays transport-free');
}

console.log('admin assistant student notes demo checks passed');
