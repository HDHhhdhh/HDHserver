import { $, toast } from '../core/utils.js';
import { patchLogsBatch } from './today.state.js';
import {
  completeAssignedTestsForRecordCleanup,
  preloadRecordCleanupEntries,
} from './today.render.js?v=20260821-log-batch1';

function collectRenderedCleanupTargets() {
  const rows = $('doneWrap')?.querySelectorAll('tr[data-sid][data-date]') || [];
  const seen = new Set();
  const targets = [];

  rows.forEach(row => {
    const date = String(row?.dataset?.date || '').trim();
    const sid = String(row?.dataset?.sid || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !sid) return;

    const key = `${date}\u0000${sid}`;
    if (seen.has(key)) return;
    seen.add(key);
    targets.push([date, sid]);
  });

  return targets;
}

async function prepareTargetsWithLimit(targets, latestByTarget, limit = 6) {
  const results = new Array(targets.length);
  let cursor = 0;
  const workers = Array.from({ length: Math.min(limit, targets.length) }, async () => {
    while (cursor < targets.length) {
      const index = cursor;
      cursor += 1;
      const [date, sid] = targets[index];
      try {
        const key = `${date}\u0000${sid}`;
        const testPatch = await completeAssignedTestsForRecordCleanup(date, sid, latestByTarget.get(key));
        results[index] = { ok: true, date, sid, testPatch };
      } catch (error) {
        console.warn('[clearAll] target preparation failed:', { date, sid, error });
        results[index] = { ok: false, date, sid, error };
      }
    }
  });
  await Promise.all(workers);
  return results;
}

export function initClearAll() {
  const button = $('clearAllBtn');
  button?.addEventListener('click', async () => {
    const targets = collectRenderedCleanupTargets();
    if (!targets.length) {
      toast('정리할 하원 기록이 없습니다.');
      return;
    }

    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = '정리 중';
    button.setAttribute('aria-busy', 'true');
    try {
      const latestByTarget = await preloadRecordCleanupEntries(targets);
      const prepared = await prepareTargetsWithLimit(targets, latestByTarget);
      const ready = prepared.filter(result => result?.ok);
      if (ready.length) {
        await patchLogsBatch(ready.map(({ date, sid, testPatch }) => ({
          date,
          sid,
          entry: { ...testPatch, archived: true },
        })));
      }

      if (ready.length === targets.length) toast(`하원 기록 ${ready.length}건을 정리했습니다.`);
      else if (ready.length > 0) toast(`하원 기록 ${ready.length}/${targets.length}건을 정리했습니다.`);
      else toast('하원 기록 정리에 실패했습니다.');
      document.dispatchEvent(new CustomEvent('admin:refresh'));
    } catch (error) {
      console.warn('[clearAll] batch archive failed:', error);
      toast('하원 기록 정리에 실패했습니다.');
      document.dispatchEvent(new CustomEvent('admin:refresh'));
    } finally {
      button.disabled = false;
      button.textContent = originalLabel;
      button.removeAttribute('aria-busy');
    }
  });
}
