function requireMap(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} 초기 데이터 형식이 올바르지 않습니다.`);
  }
}

export async function loadAdminBootstrapTransport(api, today) {
  const ensured = await api.postStrict('/api/updates/ensure-today', {}, 'admin bootstrap assignments', { cache: 'no-store' });
  requireMap(ensured, 'updates');
  let payload;
  try {
    payload = await api.getStrict(`/api/admin/bootstrap?date=${encodeURIComponent(today)}`, 'admin bootstrap', { cache: 'no-store' });
  } catch (error) {
    if (error?.status !== 404) throw error;
    const [students, videos, logs, absent, progress, schoolCal] = await Promise.all([
      api.get('/api/students'),
      api.get('/api/videos'),
      api.getStrict(`/api/logs?date=${encodeURIComponent(today)}`, 'admin bootstrap /api/logs'),
      api.getOr('/api/absent', {}),
      api.getStrict(`/api/progress?date=${encodeURIComponent(today)}`, 'admin bootstrap /api/progress'),
      api.getOr('/api/school-calendar', {}),
    ]);
    return { students, videos, updates: ensured, logs, absent, progress, schoolCal, revisions: {} };
  }
  requireMap(payload, 'bootstrap');
  if (payload.date !== today) throw new Error('관리자 초기 데이터 날짜가 다릅니다.');
  for (const key of ['students', 'videos', 'updates', 'logs', 'absent', 'progress', 'schoolCal']) {
    if (!Object.prototype.hasOwnProperty.call(payload, key)) throw new Error(`bootstrap ${key} 응답이 없습니다.`);
  }
  requireMap(payload.updates, 'updates');
  requireMap(payload.revisions, 'revisions');
  return payload;
}
