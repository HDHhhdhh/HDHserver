import { getJSON } from './api.js';

export const state = {
  students: [],
  videos: [],
  progress: {},
  schoolCal: {},
};

export async function loadAll() {
  const [stu, vid, prog, sch] = await Promise.all([
    getJSON('/api/students'),
    getJSON('/api/videos'),
    getJSON('/api/progress').catch(() => ({})),
    getJSON('/api/school-calendar').catch(() => ({})),
  ]);
  state.students  = Array.isArray(stu) ? stu : [];
  state.videos    = Array.isArray(vid) ? vid : [];
  state.progress  = prog || {};
  state.schoolCal = sch  || {};

  // 전역 노출(다른 스크립트/콘솔 편의)
  window.students     = state.students;
  window.videos       = state.videos;
  window.progressData = state.progress;
  window.schoolCal    = state.schoolCal;

  return state;
}
