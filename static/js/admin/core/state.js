// 전역 상태 한 군데로 모으기 + 초기 로드
import { api } from './api.js';
import { todayLocalKey } from './utils.js';

export const state = {
  students: [], videos: [], materials: {}, updates: {}, assigns: {},
  extra: {}, logs: {}, absences: {}, absentByDate: {}, absentSlotsByDate: {}, progress: {},
  schoolCal: {}, testsConfig: { categories: {} },
};

async function getCriticalJson(url, label) {
  return await api.getStrict(url, label);
}

export async function bootstrap() {
  const today = todayLocalKey();
  const [
    students, videos, materials, updates, assigns, extra, logs, abs, progress, schoolCal, testsConfig
  ] = await Promise.all([
    api.get('/api/students'),
    api.get('/api/videos'),
    api.getOr('/api/materials', {}),
    getCriticalJson('/api/updates', 'admin bootstrap /api/updates'),
    api.getOr('/api/mat-assign', {}),
    api.getOr('/api/extra-attend', {}),
    getCriticalJson(`/api/logs?date=${encodeURIComponent(today)}`, 'admin bootstrap /api/logs'),
    api.getOr('/api/absent', {}),
    getCriticalJson(`/api/progress?date=${encodeURIComponent(today)}`, 'admin bootstrap /api/progress'),
    api.getOr('/api/school-calendar', {}),
    api.getOr('/api/tests-config', { categories: {} }),
  ]);

  state.students = students;
  state.videos = videos;
  state.materials = materials;
  state.updates = updates;
  state.assigns = assigns;
  state.extra = extra;
  state.logs = logs;
  state.progress = progress;

  const isUnified = abs && (abs.by_date || abs.by_student);
  state.absentByDate = isUnified ? (abs.by_date || {}) : {};
  state.absences    = isUnified ? (abs.by_student || {}) : (abs || {});
  state.absentSlotsByDate = isUnified ? (abs.by_slot || {}) : {};

  state.schoolCal = schoolCal || {};
  state.testsConfig = testsConfig || { categories: {} };

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
