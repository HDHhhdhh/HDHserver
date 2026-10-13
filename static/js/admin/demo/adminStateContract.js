import { cloneDemoValue } from './store.js';

export function demoAdminState(store, date, revision) {
  const day = key => ({ [date]: store[key]?.[date] || {} });
  const payload = {
    date, students: store.students || [], videos: store.videos || [],
    updates: store.updates || {}, logs: day('logs'),
    absent: store.absent || { by_date: {}, by_student: {}, by_slot: {} },
    progress: day('progress'), schoolCal: store.schoolCalendar || {},
  };
  payload.revisions = Object.fromEntries(Object.entries(payload).filter(([key]) => key !== 'date').map(
    ([key, value]) => [key, revision(value)]));
  return cloneDemoValue(payload);
}

export function demoAdminRevisions(store, date, revision) {
  const payload = demoAdminState(store, date, revision);
  const result = { ...payload.revisions };
  for (const [key, field] of Object.entries({
    logHistory: 'logs', progressHistory: 'progress', arriveHistory: 'arriveTime',
    makeupCarryover: 'makeupCarryover', weekend: 'weekendSlots', extra: 'extraAttend', todayOrder: 'todayOrder',
  })) result[key] = revision(store[field] || {});
  for (const [key, field] of Object.entries({ attendance: 'attendance', contact: 'contact', arriveTime: 'arriveTime' })) {
    result[key] = revision({ [date]: store[field]?.[date] || {} });
  }
  return { date, revisions: result };
}
