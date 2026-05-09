import { $, toast } from '../core/utils.js';
import { state } from '../core/state.js';
import { getAdminDate } from '../core/adminDate.js';
import { patchLog, truthy } from './today.state.js';

export function initClearAll() {
  $('clearAllBtn')?.addEventListener('click', async () => {
    const targets = [];
    const logs = state.logs || {};
    const dateKey = String(getAdminDate() || '').trim();
    const dayMap = logs?.[dateKey] || {};

    for (const sid in dayMap) {
      const entry = dayMap[sid];
      if (truthy(entry?.done) && !truthy(entry?.archived)) targets.push([dateKey, sid]);
    }

    try {
      for (const [date, sid] of targets) {
        await patchLog(date, sid, { archived: true });
      }
      toast('선택 날짜의 완료 기록을 정리했습니다.');
      document.dispatchEvent(new CustomEvent('admin:refresh'));
    } catch (e) {
      console.warn('[clearAll] archive failed:', e);
      toast('선택 날짜 완료 기록 정리에 실패했습니다.');
    }
  });
}
