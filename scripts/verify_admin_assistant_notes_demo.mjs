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

console.log('admin assistant student notes demo checks passed');
