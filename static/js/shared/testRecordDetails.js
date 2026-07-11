import {
  escapeAttr,
  escapeHtml,
  isQaRecord,
  loadRecordDetail,
  loadStudentTestRecords,
  pctText,
  recordCreatedAt,
  recordSubtitle,
  recordTitle,
  recordsForSid,
  scoreText,
  wrongCount,
} from './testRecordData.js';

const STYLE_ID = 'student-test-record-details-style';
const DISABLED_STYLE_ID = 'student-test-record-details-disabled-style';
const MODAL_ID = 'studentTestRecordDetailsModal';
const TEST_RECORD_DETAILS_UI_ENABLED = false;

let activeRecords = [];

function ensureDisabledStyle() {
  if (document.getElementById(DISABLED_STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = DISABLED_STYLE_ID;
  style.textContent = `
.studentTestRecordBtn[data-test-result-sid]{display:none!important}
  `;
  document.head.appendChild(style);
}

function hideStudentTestRecordButtons(root = document) {
  ensureDisabledStyle();
  root?.querySelectorAll?.('.studentTestRecordBtn[data-test-result-sid]').forEach(button => {
    button.hidden = true;
    button.disabled = true;
    button.tabIndex = -1;
    button.setAttribute('aria-hidden', 'true');
  });
}

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
.studentTestRecordBtn{min-width:42px;min-height:32px;padding:0 8px;border:1px solid #cbd5e1;border-radius:9px;background:#fff;color:#0f172a;font-size:12px;font-weight:800;cursor:pointer;white-space:nowrap}
.studentTestRecordBtn[disabled]{opacity:.42;cursor:default}
body.dark .studentTestRecordBtn{border-color:#334155;background:#0b1220;color:#e5e7eb}
.student-test-record-modal[hidden]{display:none}
.student-test-record-modal{position:fixed;inset:0;z-index:10020;display:grid;place-items:center;padding:24px;background:rgba(15,23,42,.46)}
.student-test-record-dialog{width:min(760px,96vw);max-height:min(760px,90vh);overflow:auto;border-radius:16px;border:1px solid #e5e7eb;background:#fff;color:#0f172a;box-shadow:0 20px 48px rgba(15,23,42,.28)}
body.dark .student-test-record-dialog{border-color:#334155;background:#0f172a;color:#e5e7eb}
.student-test-record-head{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:18px 20px 12px;border-bottom:1px solid #e5e7eb}
body.dark .student-test-record-head{border-color:#334155}
.student-test-record-head h2{margin:0;font-size:20px;line-height:1.25}
.student-test-record-close{width:36px;height:36px;border:1px solid #cbd5e1;border-radius:10px;background:transparent;color:inherit;font-size:22px;cursor:pointer}
.student-test-record-body{display:grid;gap:12px;padding:16px 20px 20px}
.student-test-record-row{border:1px solid #e5e7eb;border-radius:12px;padding:12px;background:color-mix(in srgb,#f8fafc 78%,#fff)}
body.dark .student-test-record-row{border-color:#334155;background:#111827}
.student-test-record-top{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:start}
.student-test-record-title{font-weight:900;line-height:1.3;word-break:keep-all}
.student-test-record-meta{margin-top:4px;color:#64748b;font-size:12px;line-height:1.45}
body.dark .student-test-record-meta{color:#94a3b8}
.student-test-record-metrics{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.student-test-record-pill{border:1px solid #cbd5e1;border-radius:999px;padding:4px 8px;background:#fff;font-size:12px;font-weight:800}
body.dark .student-test-record-pill{border-color:#334155;background:#0b1220}
.student-test-record-pill.is-qa{border-color:#f59e0b;color:#92400e;background:#fff7ed}
.student-test-record-detail-btn,.student-test-record-answer-link{min-height:34px;border-radius:9px;border:1px solid #2563eb;background:#2563eb;color:#fff;padding:0 10px;font-size:12px;font-weight:900;text-decoration:none;cursor:pointer}
.student-test-record-detail{margin-top:12px;padding-top:12px;border-top:1px solid #e5e7eb}
body.dark .student-test-record-detail{border-color:#334155}
.student-test-record-wrong-list{display:grid;gap:8px;padding:0;margin:8px 0 0;list-style:none}
.student-test-record-wrong-list li{display:grid;grid-template-columns:56px minmax(0,1fr) minmax(0,1fr);gap:8px;align-items:center}
.student-test-record-answer{border:1px solid #e5e7eb;border-radius:10px;padding:8px;background:#fff;min-width:0}
body.dark .student-test-record-answer{border-color:#334155;background:#0b1220}
.student-test-record-answer span{display:block;color:#64748b;font-size:11px;font-weight:800}
.student-test-record-answer strong{display:block;margin-top:2px;font-size:16px;word-break:break-word}
@media (max-width:640px){.student-test-record-modal{padding:12px}.student-test-record-top{grid-template-columns:1fr}.student-test-record-wrong-list li{grid-template-columns:1fr}}
  `;
  document.head.appendChild(style);
}

function ensureModal() {
  let modal = document.getElementById(MODAL_ID);
  if (modal) return modal;
  modal = document.createElement('section');
  modal.id = MODAL_ID;
  modal.className = 'student-test-record-modal';
  modal.hidden = true;
  modal.innerHTML = `
    <div class="student-test-record-dialog" role="dialog" aria-modal="true" aria-labelledby="studentTestRecordTitle" tabindex="-1">
      <div class="student-test-record-head">
        <h2 id="studentTestRecordTitle">테스트 기록</h2>
        <button type="button" class="student-test-record-close" data-test-record-close aria-label="닫기">×</button>
      </div>
      <div class="student-test-record-body" id="studentTestRecordBody"></div>
    </div>
  `;
  document.body.appendChild(modal);
  return modal;
}

function renderDetailHtml(record, detailPayload, detailRecord) {
  const answerUrl = String(detailPayload?.answerUrl || '').trim();
  const wrong = Array.isArray(detailRecord?.wrong) ? detailRecord.wrong : record.wrong;
  const details = Array.isArray(detailRecord?.wrongDetails) ? detailRecord.wrongDetails : [];
  const detailRows = details.map(item => `
    <li>
      <strong>${escapeHtml(`${item.questionNo ?? item.question_no ?? '-'}번`)}</strong>
      <b class="student-test-record-answer"><span>내 답</span><strong>${escapeHtml(item.myAnswer ?? item.my_answer ?? '-')}</strong></b>
      <em class="student-test-record-answer"><span>정답</span><strong>${escapeHtml(item.correctAnswer ?? item.correct_answer ?? '-')}</strong></em>
    </li>
  `).join('');
  const wrongText = Array.isArray(wrong) && wrong.length
    ? `틀린 문항 ${wrong.map(value => String(value).trim()).filter(Boolean).join(', ')}`
    : '틀린 문항 없음';
  return `
    ${answerUrl ? `<p><a class="student-test-record-answer-link" href="${escapeAttr(answerUrl)}" target="_blank" rel="noopener noreferrer">전체 답지 보기</a></p>` : ''}
    <strong>${escapeHtml(wrongText)}</strong>
    ${detailRows ? `<ul class="student-test-record-wrong-list">${detailRows}</ul>` : (
      Array.isArray(wrong) && wrong.length
        ? '<p class="student-test-record-meta">이전 제출 기록이라 제출 답안 원본이 없어 내 답/정답 비교는 표시할 수 없습니다. 새 제출 기록부터 문항별 비교가 표시됩니다.</p>'
        : ''
    )}
  `;
}

async function showRecordDetail(index, host) {
  const record = activeRecords[index];
  if (!record || !host) return;
  host.innerHTML = '<p class="student-test-record-meta">정답 비교를 불러오는 중입니다.</p>';
  const loaded = await loadRecordDetail(record);
  host.innerHTML = loaded
    ? renderDetailHtml(record, loaded.payload, loaded.detailRecord)
    : '<p class="student-test-record-meta">이 기록은 상세 비교를 불러올 수 없습니다.</p>';
}

function recordRowHtml(record, index) {
  const wrong = wrongCount(record);
  const meta = [recordSubtitle(record), recordCreatedAt(record).slice(0, 10)].filter(Boolean).join(' · ');
  return `
    <article class="student-test-record-row">
      <div class="student-test-record-top">
        <div>
          <div class="student-test-record-title">${escapeHtml(recordTitle(record))}</div>
          <div class="student-test-record-meta">${escapeHtml(meta)}</div>
          <div class="student-test-record-metrics">
            <span class="student-test-record-pill">정답률 ${escapeHtml(pctText(record))}</span>
            <span class="student-test-record-pill">점수 ${escapeHtml(scoreText(record))}</span>
            <span class="student-test-record-pill">오답 ${wrong}개</span>
            ${isQaRecord(record) ? '<span class="student-test-record-pill is-qa">QA 기록</span>' : ''}
          </div>
        </div>
        <button type="button" class="student-test-record-detail-btn" data-test-record-detail="${index}">비교 보기</button>
      </div>
      <div class="student-test-record-detail" data-test-record-detail-host="${index}" hidden></div>
    </article>
  `;
}

async function openStudentRecords(sid, name = '') {
  ensureStyle();
  const modal = ensureModal();
  const title = modal.querySelector('#studentTestRecordTitle');
  const body = modal.querySelector('#studentTestRecordBody');
  if (title) title.textContent = `${name || sid} 테스트 기록`;
  modal.hidden = false;
  modal.setAttribute('aria-hidden', 'false');
  modal.querySelector('.student-test-record-dialog')?.focus();

  const allRecords = await loadStudentTestRecords();
  activeRecords = recordsForSid(allRecords, sid).slice(0, 12);
  if (body) {
    body.innerHTML = activeRecords.length
      ? activeRecords.map(recordRowHtml).join('')
      : '<p class="student-test-record-meta">아직 제출된 테스트 기록이 없습니다.</p>';
  }
}

export function initStudentTestRecordDetails(root = document) {
  if (!TEST_RECORD_DETAILS_UI_ENABLED) {
    hideStudentTestRecordButtons(root);
    return;
  }
  ensureStyle();
  ensureModal();
  if (document.body.dataset.testRecordDetailsBound === '1') return;
  document.body.dataset.testRecordDetailsBound = '1';
  document.addEventListener('click', async event => {
    const close = event.target?.closest?.('[data-test-record-close]');
    if (close) {
      const modal = document.getElementById(MODAL_ID);
      if (modal) modal.hidden = true;
      return;
    }
    const detailButton = event.target?.closest?.('[data-test-record-detail]');
    if (detailButton) {
      const index = Number(detailButton.dataset.testRecordDetail);
      const host = document.querySelector(`[data-test-record-detail-host="${index}"]`);
      if (host) {
        host.hidden = false;
        await showRecordDetail(index, host);
      }
      return;
    }
    const button = event.target?.closest?.('[data-test-result-sid]');
    if (!button || !root.contains(button)) return;
    await openStudentRecords(button.dataset.testResultSid || '', button.dataset.testResultName || '');
  });
}

export async function decorateStudentTestRecordButtons(root = document) {
  if (!TEST_RECORD_DETAILS_UI_ENABLED) {
    hideStudentTestRecordButtons(root);
    return;
  }
  ensureStyle();
  const buttons = Array.from(root.querySelectorAll('[data-test-result-sid]'));
  if (!buttons.length) return;
  const allRecords = await loadStudentTestRecords();
  buttons.forEach(button => {
    const records = recordsForSid(allRecords, button.dataset.testResultSid || '');
    const latest = records[0];
    if (button.dataset.testRecordClickBound !== '1') {
      button.dataset.testRecordClickBound = '1';
      button.addEventListener('click', async event => {
        event.preventDefault();
        event.stopPropagation();
        await openStudentRecords(button.dataset.testResultSid || '', button.dataset.testResultName || '');
      });
    }
    button.disabled = !latest;
    button.textContent = latest ? `기록 ${pctText(latest)}` : '기록';
    button.title = latest
      ? `테스트 기록 보기 · ${recordTitle(latest)} · ${pctText(latest)} · 오답 ${wrongCount(latest)}개`
      : '제출된 테스트 기록 없음';
  });
}
