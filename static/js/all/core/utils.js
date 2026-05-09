import { resolveSchoolCalendarEntry } from '../../shared/schoolCalendar.js';

export const $ = (id) => document.getElementById(id);

export const toast = (msg) => {
  const d = document.createElement('div');
  d.textContent = msg;
  d.style.cssText =
    'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);' +
    'background:#333;color:#fff;padding:6px 10px;border-radius:6px;' +
    'z-index:99999;font-size:13px';
  document.body.appendChild(d);
  setTimeout(() => d.remove(), 1400);
};

export const fmtDate = (v) => {
  if (!v) return '-';
  if (typeof v === 'string') return v.trim();
  if (Array.isArray(v)) return v.filter(Boolean).join('~') || '-';
  if (typeof v === 'object') {
    const s = v.start ?? v.s ?? v.from;
    const e = v.end ?? v.e ?? v.to;
    if (s && e) return `${s}~${e}`;
    return s || e || '-';
  }
  return '-';
};

export const getScheduleLine = (schoolCal, schoolName, grade = '') => {
  if (!schoolName) return '';
  const sc = resolveSchoolCalendarEntry(schoolCal, schoolName, grade);
  const open = sc.semesterStart ?? sc['개학식'] ?? sc['개학'];
  const mid = sc.midterm ?? sc['1차 지필평가'] ?? sc['중간'];
  const fin = sc.final ?? sc['2차 지필평가'] ?? sc['기말'];
  return `개학 ${fmtDate(open)} · 중간 ${fmtDate(mid)} · 기말 ${fmtDate(fin)}`;
};
