export const TODAY_REVISION_KEYS = [
  'students', 'videos', 'updates', 'absent', 'schoolCal', 'weekend',
  'makeupCarryover', 'extra', 'todayOrder', 'logs', 'logHistory',
  'progress', 'progressHistory', 'attendance', 'contact', 'arriveTime', 'arriveHistory',
];

export class TodayRevisionPoller {
  constructor() {
    this.epoch = 0;
    this.date = '';
    this.acknowledged = {};
    this.lastFull = 0;
    this.flight = null;
  }

  invalidate() {
    this.epoch += 1;
  }

  async poll({ date, realDate, isCurrent, getRevisions, refresh, now = Date.now() }) {
    if (this.flight) return this.flight;
    if (this.date !== date) {
      this.invalidate();
      this.date = date;
      this.acknowledged = {};
      this.lastFull = 0;
    }
    const epoch = this.epoch;
    const current = () => epoch === this.epoch && this.date === date && isCurrent(date, realDate);
    const run = async () => {
      let revisions;
      try {
        const payload = await getRevisions(date);
        if (!payload || payload.date !== date || !payload.revisions || TODAY_REVISION_KEYS.some(
          key => typeof payload.revisions[key] !== 'string' || !payload.revisions[key])) {
          throw new Error('관리자 변경 정보 형식이 올바르지 않습니다.');
        }
        revisions = payload.revisions;
      } catch (error) {
        if (current() && ![401, 403].includes(error?.status)) await refresh(null);
        return;
      }
      if (!current()) return;
      const full = !this.lastFull || now - this.lastFull >= 10 * 60 * 1000;
      const changed = full ? TODAY_REVISION_KEYS : TODAY_REVISION_KEYS.filter(key => this.acknowledged[key] !== revisions[key]);
      if (!changed.length) return;
      const loaded = await refresh(changed);
      if (!current()) return;
      for (const key of loaded || []) {
        if (TODAY_REVISION_KEYS.includes(key)) this.acknowledged[key] = revisions[key];
      }
      if (full && TODAY_REVISION_KEYS.every(key => this.acknowledged[key] === revisions[key])) this.lastFull = now;
    };
    this.flight = run();
    try { return await this.flight; }
    finally { this.flight = null; }
  }
}
