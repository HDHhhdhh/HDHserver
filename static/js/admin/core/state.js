// 전역 상태 한 군데로 모으기 + 초기 로드
import { api } from './api.js';
import { todayLocalKey } from './utils.js';

export const state = {
  students: [], videos: [], materials: {}, updates: {}, assigns: {},
  extra: {}, logs: {}, absences: {}, absentByDate: {}, absentSlotsByDate: {}, progress: {},
  schoolCal: {}, testsConfig: { categories: {} },
};


export async function bootstrap() {
  const today = todayLocalKey();
  const [
    students, videos, updates, logs, abs, progress, schoolCal
  ] = await Promise.all([
    api.get('/api/students'),
    api.get('/api/videos'),
    api.postStrict('/api/updates/ensure-today', {}, 'admin bootstrap assignments', { cache: 'no-store' }),
    api.getStrict(`/api/logs?date=${encodeURIComponent(today)}`, 'admin bootstrap /api/logs'),
    api.getOr('/api/absent', {}),
    api.getStrict(`/api/progress?date=${encodeURIComponent(today)}`, 'admin bootstrap /api/progress'),
    api.getOr('/api/school-calendar', {}),
  ]);

  for (const [name, rows] of Object.entries({ students, videos })) {
    if (!Array.isArray(rows) || rows.some(row => !row || typeof row !== 'object' || Array.isArray(row))) {
      throw new Error(`${name} 초기 데이터 형식이 올바르지 않습니다.`);
    }
  }
  for (const [name, value] of Object.entries({ updates, logs, progress })) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      throw new Error(`${name} 초기 데이터 형식이 올바르지 않습니다.`);
    }
  }

  state.students = students;
  state.videos = videos;
  state.updates = updates;
  state.logs = logs;
  state.progress = progress;

  const isUnified = abs && (abs.by_date || abs.by_student);
  state.absentByDate = isUnified ? (abs.by_date || {}) : {};
  state.absences    = isUnified ? (abs.by_student || {}) : (abs || {});
  state.absentSlotsByDate = isUnified ? (abs.by_slot || {}) : {};

  state.schoolCal = schoolCal || {};
  // 전역 노출(기존 코드 호환)
  window.students = state.students;
  window.extra = state.extra;
  window.absentByDate = state.absentByDate;
  window.absentSlotsByDate = state.absentSlotsByDate;
  window.schoolCal = state.schoolCal;
  window.testsConfig = state.testsConfig;
  window.logs = state.logs;
  window.progressData = state.progress;
  window.videos = state.videos;
}
