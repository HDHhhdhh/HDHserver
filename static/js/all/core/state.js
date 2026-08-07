import { getJSON, getJSONOr } from './api.js';

export const state = {
  students: [],
  videos: [],
  progress: {},
  schoolCal: {},
  homeworkBooksBySid: {},
};

const progressLoadedSids = new Set();

function mergeDateSidMap(target, source) {
  const out = (target && typeof target === 'object') ? target : {};
  Object.entries(source || {}).forEach(([date, day]) => {
    if (!day || typeof day !== 'object') return;
    const nextDay = (out[date] && typeof out[date] === 'object') ? out[date] : {};
    Object.entries(day).forEach(([sid, entry]) => {
      if (sid && entry && typeof entry === 'object') {
        nextDay[String(sid)] = entry;
      }
    });
    out[date] = nextDay;
  });
  return out;
}

export async function loadAll() {
  const [stu, vid, sch, homeworkBooks] = await Promise.all([
    getJSON('/api/students'),
    getJSON('/api/videos'),
    getJSONOr('/api/school-calendar', {}),
    getJSONOr('/api/homework-books', {}),
  ]);
  state.students  = Array.isArray(stu) ? stu : [];
  state.videos    = Array.isArray(vid) ? vid : [];
  state.progress  = state.progress || {};
  state.schoolCal = sch  || {};
  state.homeworkBooksBySid = homeworkBooks || {};

  window.students     = state.students;
  window.videos       = state.videos;
  window.progressData = state.progress;
  window.schoolCal    = state.schoolCal;
  window.homeworkBooksBySid = state.homeworkBooksBySid;

  return state;
}

export async function ensureProgressForSid(sid) {
  const key = String(sid ?? '').trim();
  if (!key) return false;
  if (progressLoadedSids.has(key)) return true;

  const query = new URLSearchParams({ sid: key }).toString();
  const progress = await getJSONOr(`/api/progress?${query}`, null);
  if (!progress || typeof progress !== 'object') return false;

  state.progress = mergeDateSidMap(state.progress || {}, progress);
  progressLoadedSids.add(key);
  window.progressData = state.progress;
  return true;
}
