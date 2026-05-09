// 전역 상태 한 군데로 모으기 + 초기 로드
import { api } from './api.js';

export const state = {
  students: [], videos: [], materials: {}, updates: {}, assigns: {},
  extra: {}, logs: {}, absences: {}, absentByDate: {}, progress: {},
  schoolCal: {},
};

export async function bootstrap() {
  const [
    students, videos, materials, updates, assigns, extra, logs, abs, progress, schoolCal
  ] = await Promise.all([
    api.get('/api/students'),
    api.get('/api/videos'),
    api.get('/api/materials').catch(()=> ({})),
    api.get('/api/updates').catch(()=> ({})),
    api.get('/api/mat-assign').catch(()=> ({})),
    api.get('/api/extra-attend').catch(()=> ({})),
    api.get('/api/logs').catch(()=> ({})),
    api.get('/api/absent').catch(()=> ({})),
    api.get('/api/progress').catch(()=> ({})),
    api.get('/api/school-calendar').catch(()=> ({})),
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

  state.schoolCal = schoolCal || {};

  // 전역 노출(기존 코드 호환)
  window.students = state.students;
  window.extra = state.extra;
  window.absentByDate = state.absentByDate;
  window.schoolCal = state.schoolCal;
  window.logs = state.logs;
  window.progressData = state.progress;
  window.videos = state.videos;
}
