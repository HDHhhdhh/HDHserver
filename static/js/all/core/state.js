import { getJSON, getJSONOr } from './api.js';

export const state = {
  students: [],
  videos: [],
  progress: {},
  schoolCal: {},
  homeworkBooksBySid: {},
  homeworkBooksStatus: 'idle',
};

const progressLoadedSids = new Set();
let homeworkBooksRequest = null;

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

export function loadHomeworkBooks({ force = false } = {}) {
  if (!force && homeworkBooksRequest) return homeworkBooksRequest;

  state.homeworkBooksStatus = 'loading';
  const request = getJSON('/api/homework-books')
    .then((homeworkBooks) => {
      state.homeworkBooksBySid = homeworkBooks && typeof homeworkBooks === 'object'
        ? homeworkBooks
        : {};
      state.homeworkBooksStatus = 'ready';
      window.homeworkBooksBySid = state.homeworkBooksBySid;
      return state.homeworkBooksBySid;
    })
    .catch((error) => {
      console.warn('[students] homework books load failed', error);
      state.homeworkBooksBySid = {};
      state.homeworkBooksStatus = 'error';
      window.homeworkBooksBySid = state.homeworkBooksBySid;
      return state.homeworkBooksBySid;
    });

  homeworkBooksRequest = request;
  return request;
}

export async function loadAll({ waitForHomeworkBooks = true } = {}) {
  const homeworkBooksReady = loadHomeworkBooks();
  const [stu, vid, sch] = await Promise.all([
    getJSON('/api/students'),
    getJSON('/api/videos'),
    getJSONOr('/api/school-calendar', {}),
  ]);
  state.students  = Array.isArray(stu) ? stu : [];
  state.videos    = Array.isArray(vid) ? vid : [];
  state.progress  = state.progress || {};
  state.schoolCal = sch  || {};

  if (waitForHomeworkBooks) await homeworkBooksReady;

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
