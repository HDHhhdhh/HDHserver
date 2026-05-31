import { getJSON, getJSONOr } from './api.js';

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
    getJSONOr('/api/progress', {}),
    getJSONOr('/api/school-calendar', {}),
  ]);
  state.students  = Array.isArray(stu) ? stu : [];
  state.videos    = Array.isArray(vid) ? vid : [];
  state.progress  = prog || {};
  state.schoolCal = sch  || {};

  window.students     = state.students;
  window.videos       = state.videos;
  window.progressData = state.progress;
  window.schoolCal    = state.schoolCal;

  return state;
}
