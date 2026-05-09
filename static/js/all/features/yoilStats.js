// /js/all/yoilStats.js
import { $ } from '../core/utils.js';
import { state } from '../core/state.js';

export function renderYoilStats() {
  // ── 요일/슬롯 집계 ─────────────────────────────────
  const counts = {
    '월': 0, '화': 0, '수': 0, '목': 0, '금': 0,
    '토1': 0, '토2': 0, '토3': 0,
    '일1': 0, '일2': 0, '일3': 0
  };
  const mapping = Object.fromEntries(Object.keys(counts).map(k => [k, []]));
  const dayKeys = ['day1', 'day2', 'day3', 'day4', 'day5'];

  for (const s of state.students) {
    dayKeys.forEach(k => {
      const d = s[k];
      if (d && counts[d] != null) {
        counts[d]++;
        mapping[d].push(s.name);
      }
    });
  }

  const host = $('yoilStats');
  if (!host) return;

  const yoilRow  = ['월', '화', '수', '목', '금', '토', '일'];
  const slotRow1 = ['', '', '', '', '', '토1', '일1'];
  const slotRow2 = ['', '', '', '', '', '토2', '일2'];
  const slotRow3 = ['월', '화', '수', '목', '금', '토3', '일3'];

  const sumRow = yoilRow.map(y => {
    if (y === '토') return counts['토1'] + counts['토2'] + counts['토3'];
    if (y === '일') return counts['일1'] + counts['일2'] + counts['일3'];
    return counts[y] || 0;
  });
  const totalYoil = Object.values(counts).reduce((a, b) => a + b, 0);
  sumRow.push(totalYoil);

  // 안전하게 data-names 넣기
  const cellYoil = (key) => {
    if (!key) {
      return '<td style="border:1px solid #e5e7eb;padding:4px"></td>';
    }
    const num = counts[key] || 0;
    const safe = encodeURIComponent(JSON.stringify(mapping[key] || []));
    return `
      <td class="yoil-cell"
          data-yoil="${key}"
          data-names="${safe}"
          style="border:1px solid #e5e7eb;padding:6px;cursor:pointer">
        ${num}
      </td>`;
  };

  const yoilTableHtml = `
    <table style="border-collapse:collapse;text-align:center;width:100%;max-width:520px;border:2px solid #e5e7eb;margin-bottom:1rem">
      <tr>
        ${yoilRow.map(y => `<th style="border:1px solid #e5e7eb;padding:6px">${y}</th>`).join('')}
        <th>합계</th>
      </tr>
      <tr>${slotRow1.map(cellYoil).join('')}<td></td></tr>
      <tr>${slotRow2.map(cellYoil).join('')}<td></td></tr>
      <tr>${slotRow3.map(cellYoil).join('')}<td></td></tr>
      <tr>
        ${sumRow.map(n => `
          <td style="border:1px solid #e5e7eb;padding:6px;font-weight:600">
            ${n}
          </td>`).join('')}
      </tr>
    </table>
  `;

  // ── 난이도 집계(상/중상/중/하) ──────────────────────
  const LEVELS = ['상', '중상', '중', '하'];
  const levelCounts = Object.fromEntries(LEVELS.map(l => [l, 0]));
  const levelMapping = Object.fromEntries(LEVELS.map(l => [l, []]));

  for (const s of state.students) {
    const lv = s.level;
    if (LEVELS.includes(lv)) {
      levelCounts[lv]++;
      levelMapping[lv].push(s.name);
    }
  }
  const totalLevel = LEVELS.reduce((acc, lv) => acc + levelCounts[lv], 0);

  const rowLevel = (lv) => {
    const num = levelCounts[lv] || 0;
    const safe = encodeURIComponent(JSON.stringify(levelMapping[lv] || []));
    return `
      <tr class="level-row"
          data-level="${lv}"
          data-names="${safe}"
          style="cursor:pointer">
        <th style="text-align:left;border:1px solid #e5e7eb;padding:6px">${lv}</th>
        <td style="text-align:right;border:1px solid #e5e7eb;padding:6px;font-weight:600">${num}</td>
      </tr>`;
  };

  const levelTableHtml = `
    <table style="border-collapse:collapse;width:100%;max-width:360px;border:2px solid #e5e7eb;margin-bottom:1rem">
      <tr>
        <th style="text-align:left;border:1px solid #e5e7eb;padding:6px">난이도</th>
        <th style="text-align:right;border:1px solid #e5e7eb;padding:6px">학생 수</th>
      </tr>
      ${LEVELS.map(rowLevel).join('')}
      <tr>
        <td style="text-align:left;border:1px solid #e5e7eb;padding:6px">합계</td>
        <td style="text-align:right;border:1px solid #e5e7eb;padding:6px;font-weight:700">${totalLevel}</td>
      </tr>
    </table>
  `;

  // ── 두 표를 가로 배치 ────────────────────────────────────
  host.innerHTML = `
    <div id="yoilStatsInner"
         style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap">
      <section style="flex:1 1 520px; min-width:300px">
        <h3 style="margin:.2rem 0 .4rem 0; font-size:14px; opacity:.75">요일별 학생 수</h3>
        ${yoilTableHtml}
      </section>
      <section style="flex:0 1 360px; min-width:260px">
        <h3 style="margin:.2rem 0 .4rem 0; font-size:14px; opacity:.75">난이도별 학생 수</h3>
        ${levelTableHtml}
      </section>
    </div>`;

  // 렌더마다 클릭 핸들러를 다시 붙이지 않도록 플래그 체크
  const inner = document.getElementById('yoilStatsInner');
  if (inner && !inner._yoilBound) {
    inner._yoilBound = true;
    bindYoilClick(inner);
  }

  // 모달도 이 시점에서 보장
  ensureYoilModal();
}

// ── 모달 DOM 만들기 ─────────────────────────────────
let _yoilModal = null;
let _yoilTitle = null;
let _yoilList  = null;

function ensureYoilModal() {
  if (_yoilModal) return;

  if (!document.body) return; // 아주 이른 시점 보호

  document.body.insertAdjacentHTML('beforeend', `
    <div id="yoilModal"
         style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);justify-content:center;align-items:center;z-index:99999">
      <div style="background:#fff;padding:1rem;border-radius:10px;width:280px;max-height:80%;overflow:auto;color:#111">
        <div id="yoilTitle" style="font-weight:700;margin-bottom:.5rem"></div>
        <div id="yoilList"
             style="white-space:pre-line;min-height:200px;border:1px solid #eee;border-radius:6px;padding:8px"></div>
        <div style="text-align:right;margin-top:.8rem">
          <button id="yoilClose"
                  style="background:#3b82f6;color:#fff;border:none;padding:6px 12px;border-radius:6px">
            닫기
          </button>
        </div>
      </div>
    </div>
  `);

  _yoilModal = document.getElementById('yoilModal');
  _yoilTitle = document.getElementById('yoilTitle');
  _yoilList  = document.getElementById('yoilList');

  if (!_yoilModal) return;

  _yoilModal.addEventListener('click', (e) => {
    if (e.target.id === 'yoilClose' || e.target === _yoilModal) {
      _yoilModal.style.display = 'none';
    }
  });
}

function openYoilModal(title, names) {
  ensureYoilModal();
  if (!_yoilModal || !_yoilTitle || !_yoilList) return;

  _yoilTitle.textContent = `${title} – ${names.length}명`;
  _yoilList.textContent  = names.join('\n');
  _yoilModal.style.display = 'flex';
}

// ── 클릭 위임 핸들러 ─────────────────────────────────
function bindYoilClick(container) {
  container.addEventListener('click', (e) => {
    // 요일 셀
    const yoilCell = e.target.closest('.yoil-cell');
    if (yoilCell) {
      let names = [];
      try {
        names = JSON.parse(decodeURIComponent(yoilCell.dataset.names || '[]'));
      } catch {
        names = [];
      }
      const t = yoilCell.dataset.yoil || '';
      openYoilModal(t, names);
      return;
    }

    // 난이도 행
    const levelRow = e.target.closest('.level-row');
    if (levelRow) {
      let names = [];
      try {
        names = JSON.parse(decodeURIComponent(levelRow.dataset.names || '[]'));
      } catch {
        names = [];
      }
      const lv = levelRow.dataset.level || '';
      openYoilModal(`난이도 ${lv}`, names);
    }
  });
}
