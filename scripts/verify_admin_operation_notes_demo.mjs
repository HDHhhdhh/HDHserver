// Run with: node scripts/verify_admin_operation_notes_demo.mjs

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

const { applyOperationNotesRequest } = await import('../static/js/admin/demo/operationNotesContract.js');
const { createDemoFetch } = await import('../static/js/admin/demo/fetch.js');

const contractStore = { operationNotes: [{ id: 4, content: 'seed', created_at: '2026-08-03T00:00:00Z' }] };
const fixedCreatedAt = () => '2026-08-03T01:00:00Z';
const contractList = applyOperationNotesRequest({
  method: 'GET',
  path: '/api/admin-operation-notes',
  store: contractStore,
  createdAt: fixedCreatedAt,
});
check(contractList.status === 200 && contractList.payload.notes.length === 1, 'shared demo contract list failed');

const blankCreate = applyOperationNotesRequest({
  method: 'POST',
  path: '/api/admin-operation-notes',
  body: { content: '   ' },
  store: contractStore,
  createdAt: fixedCreatedAt,
});
check(blankCreate.status === 400 && !blankCreate.changed, 'shared demo contract accepted a blank note');

const contractCreate = applyOperationNotesRequest({
  method: 'POST',
  path: '/api/admin-operation-notes',
  body: { content: '  focused\n  goal  ' },
  store: contractStore,
  createdAt: fixedCreatedAt,
});
check(
  contractCreate.status === 201
    && contractCreate.changed
    && contractCreate.payload.note.content === 'focused goal',
  'shared demo contract create failed',
);

const missingDelete = applyOperationNotesRequest({
  method: 'DELETE',
  path: '/api/admin-operation-notes/999',
  store: contractStore,
  createdAt: fixedCreatedAt,
});
check(missingDelete.status === 404 && !missingDelete.changed, 'shared demo contract missing delete failed');

const contractDelete = applyOperationNotesRequest({
  method: 'DELETE',
  path: `/api/admin-operation-notes/${contractCreate.payload.note.id}`,
  store: contractStore,
  createdAt: fixedCreatedAt,
});
check(contractDelete.status === 200 && contractDelete.changed, 'shared demo contract delete failed');

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
const initialResponse = await demoFetch('/api/admin-operation-notes');
const initial = await initialResponse.json();
check(initialResponse.ok && initial.ok && Array.isArray(initial.notes), 'demo note list failed');

const createResponse = await demoFetch('/api/admin-operation-notes', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ content: '데모 운영 목표' }),
});
const created = await createResponse.json();
check(createResponse.status === 201 && created.note.content === '데모 운영 목표', 'demo note create failed');

const reloadedFetch = createDemoFetch({ window: root, originalFetch });
const persisted = await (await reloadedFetch('/api/admin-operation-notes')).json();
check(persisted.notes.some(note => note.id === created.note.id), 'demo note did not persist in the session store');

const deleteResponse = await reloadedFetch(`/api/admin-operation-notes/${created.note.id}`, { method: 'DELETE' });
check(deleteResponse.ok, 'demo note delete failed');
const afterDelete = await (await reloadedFetch('/api/admin-operation-notes')).json();
check(!afterDelete.notes.some(note => note.id === created.note.id), 'deleted demo note is still listed');
check(forwardedApiCalls === 0, 'demo operation notes reached the live fetch implementation');

console.log('admin operation notes demo checks passed');
