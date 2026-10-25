import { cloneDemoValue as clone } from './store.js';

function revision(store) {
  let hash = 2166136261;
  for (const character of JSON.stringify([store.students, store.graveyard || []])) {
    hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  }
  return (hash >>> 0) + 1;
}

export function applyDemoGraveyardRequest({ method, path, body, store }) {
  const listPath = path === '/api/students/graveyard';
  const restoreMatch = path.match(/^\/api\/students\/([^/]+)\/restore$/);
  const deleteMatch = method === 'DELETE' && path.match(/^\/api\/students\/([^/]+)$/);
  if (!listPath && !restoreMatch && !deleteMatch) return null;
  const result = (payload, status = 200, changed = false) => ({ payload, status, changed });
  const rows = store.graveyard || [];
  if (listPath && method === 'GET') return result({ ok: true, configured: true, revision: revision(store), students: clone(rows) });
  if (listPath || restoreMatch && method !== 'POST') return result({ ok: false, error: 'method not allowed' }, 405);
  const sid = decodeURIComponent((restoreMatch || deleteMatch)[1]);
  if (!sid.startsWith('demo-')) return result({ ok: false, error: 'demo SID required' }, 400);
  if (restoreMatch) {
    if (!Number.isInteger(body?.revision)) return result({ ok: false, error: 'revision required' }, 400);
    if (body.revision !== revision(store)) return result({ ok: false, error: '명단이 변경되었습니다. 새로고침 후 다시 복원하세요.' }, 409);
    const archived = rows.find(row => row.student.id === sid);
    if (!archived) return result({ ok: false, error: '보관 기록을 찾을 수 없습니다.' }, 404);
    if (store.students.some(row => row.id === sid)) return result({ ok: false, error: '이미 복원된 학생입니다.' }, 409);
    store.students.push(clone(archived.student));
    store.graveyard = rows.filter(row => row.student.id !== sid);
    return result({ ok: true, student: clone(archived.student) }, 200, true);
  }
  const student = store.students.find(row => row.id === sid);
  if (!student) return result({ ok: false, error: '학생을 찾을 수 없습니다.' }, 404);
  store.graveyard = [{ student: clone(student), retiredAt: store.generatedAt || '2026-06-17T00:00:00+09:00',
    snapshotComplete: true, activeCourses: [], restorable: true }, ...rows.filter(row => row.student.id !== sid)];
  store.students = store.students.filter(row => row.id !== sid);
  return result({ ok: true, id: sid, deleted: true }, 200, true);
}
