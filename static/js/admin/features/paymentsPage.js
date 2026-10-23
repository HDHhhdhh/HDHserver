import { fetchJson } from '../../shared/api.js';
import { PaymentClient, paymentMessage } from './paymentClient.js';

const $ = (id) => document.getElementById(id);
const client = new PaymentClient();
const money = (value) => `${Number(value || 0).toLocaleString('ko-KR')}원`;
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
const kindText = { regular:'정규수업', makeup:'보강', self_study:'자습' };
const statusText = { planned:'예정', attended:'출석', absent:'결석', cancelled:'취소' };
const actionText = { configure:'요금 설정', package:'수강권 등록', payment:'수납', refund:'취소·환불', session:'수업 기록', void:'기록 정정' };
const methodText = { card:'카드', transfer:'이체', cash:'현금', other:'기타', refund:'환불' };
let overview = { students:[], plans:[], today:'' };
let selectedSid = '', detail = null, evidence = [], evidenceSequence = 0, selectedDay = '', calendar = null;
let dialogAction = '', dialogSeed = {}, dialogRevision = 0, conflict = false;
let overviewSequence = 0;

function notice(id, message) { $(id).textContent = message; $(id).hidden = !message; }
function stat(label, value, hint = '') { return `<div class="stat"><span>${escape(label)}</span><strong>${escape(value)}</strong><small>${escape(hint)}</small></div>`; }
function studentRecord() { return overview.students.find((row) => row.sid === selectedSid); }
function lineSummary(lines) { return lines.map((row) => `${row.label} ${row.units}회 × ${money(row.unitPrice)}`).join(' + '); }
function componentName(row) { return detail.account.packages.find((p) => p.id === row.packageId)?.lines[row.lineIndex]?.label || ''; }
function auditDescription(record) {
  const d = record.details || {};
  return [d.date || d.startsOn, d.slot ? `${d.slot}타임` : '', kindText[d.kind], statusText[d.status],
    d.lines ? lineSummary(d.lines) : '', d.amount !== undefined ? `금액 ${money(d.amount)}` : '',
    d.creditAmount !== undefined ? `감액 ${money(d.creditAmount)}` : '', d.memo].filter(Boolean).join(' · ');
}

function renderOverview() {
  const configured = overview.students.filter((row) => row.configured);
  $('overviewStats').innerHTML = stat('전체 미수금', money(configured.reduce((sum, row) => sum + row.due, 0)), '등록된 수강권 기준')
    + stat('미수금 있는 계정', `${configured.filter((row) => row.due > 0).length}개`, '학생·과목별 집계')
    + stat('회차가 얼마 안 남았어요', `${configured.filter((row) => !row.archived && row.remainingUnits <= 2).length}개`, '남은 회차 2회 이하')
    + stat('요금 설정 완료', `${configured.length}개`, `전체 ${overview.students.length}개 계정`);
  renderStudents();
}
function renderStudents() {
  const query = $('studentSearch').value.trim().toLocaleLowerCase();
  const filter = $('accountFilter').value;
  const rows = overview.students.filter((row) => {
    const values = [row.student.name, row.student.school, row.student.curriculum, row.sid].join(' ').toLocaleLowerCase();
    return values.includes(query) && (filter === 'all' || filter === 'due' && row.due > 0
      || filter === 'low' && row.configured && row.remainingUnits <= 2 || filter === 'unset' && !row.configured);
  });
  $('studentCount').textContent = `${rows.length}개`;
  $('studentList').innerHTML = rows.length ? rows.map((row) => `<button type="button" class="student-card" data-sid="${escape(row.sid)}" aria-current="${row.sid === selectedSid}">
    <strong>${escape(row.student.name || row.sid)}${row.archived ? ' · 과거 계정' : ''}</strong>
    <small>${escape([row.student.school, row.student.curriculum].filter(Boolean).join(' · ') || '과목 미지정')}</small>
    <span class="card-foot"><span>${row.configured ? `남은 ${row.remainingUnits}회` : '요금 설정 필요'}</span><span class="${row.due ? 'amount-due' : ''}">${row.due ? `미수 ${money(row.due)}` : row.configured ? '미수 없음' : ''}</span></span></button>`).join('') : '<p class="muted">검색 결과가 없습니다.</p>';
}

async function loadOverview() {
  const sequence = ++overviewSequence;
  notice('pageMessage', '결제 현황을 불러오고 있습니다.');
  try {
    const loaded = await fetchJson('/api/payments/overview', { cache:'no-store' });
    if (sequence !== overviewSequence || client.saving || client.pending) return;
    overview = loaded;
    if (!$('historyMonth').value) $('historyMonth').value = overview.today.slice(0,7);
    renderOverview();
    notice('pageMessage', '');
    if (selectedSid) await selectStudent(selectedSid);
  } catch (error) { if (sequence === overviewSequence) notice('pageMessage', paymentMessage(error)); }
}
async function selectStudent(sid) {
  if (client.pending || client.saving) { notice('dialogError', '진행 중인 저장 결과를 먼저 확인해 주세요.'); return; }
  selectedSid = sid;
  detail = null;
  evidence = [];
  evidenceSequence += 1;
  $('accountContent').hidden = true;
  $('emptySelection').hidden = false;
  $('emptySelection').innerHTML = '<h2>결제 기록을 불러오고 있습니다.</h2>';
  renderStudents();
  try {
    const result = await client.readAccount(sid);
    if (!result || sid !== selectedSid) return;
    detail = result;
    Object.assign(studentRecord(), result.summary, { revision:result.revision });
    renderOverview();
    selectedDay = $('historyMonth').value === overview.today.slice(0,7) ? overview.today : `${$('historyMonth').value}-01`;
    $('emptySelection').hidden = true;
    $('accountContent').hidden = false;
    renderAccount();
    await loadEvidence();
  } catch (error) {
    if (sid !== selectedSid) return;
    $('emptySelection').innerHTML = `<h2>불러오지 못했습니다.</h2><p>${escape(paymentMessage(error))}</p><p>상단 새로고침으로 다시 확인해 주세요.</p>`;
  }
}
function renderAccount() {
  const row = studentRecord();
  const state = detail.account;
  $('studentName').textContent = row.student.name || selectedSid;
  $('studentCourse').textContent = row.student.curriculum || '과목 미지정';
  $('studentMeta').textContent = [row.student.school, row.student.grade, `계정 ${selectedSid}`, row.archived ? '과거 계정' : ''].filter(Boolean).join(' · ');
  const s = detail.summary;
  $('accountStats').innerHTML = stat('남은 수업', `${s.remainingUnits}회`, `실제 출석 ${s.usedUnits}회`)
    + stat('미수금', money(s.due), `청구 ${money(s.billed)}`)
    + stat('순수납', money(s.paid), s.lastPaymentDate ? `최근 수납 ${s.lastPaymentDate}` : '아직 수납 기록이 없습니다')
    + stat('환급 대기', money(s.refundDue), '청구 감액 후 지급할 금액');
  notice('accountMessage', !state.config ? '먼저 요금을 설정하세요. 기존 출결 기록은 아래에서 확인할 수 있습니다.' : `회차 관리 시작일 ${state.config.startsOn} · 결석과 자습은 차감하지 않습니다.`);
  $('configureOpen').disabled = row.archived;
  $('packageOpen').disabled = !state.config || row.archived;
  $('sessionOpen').disabled = !state.config || row.archived;
  $('paymentOpen').disabled = !state.packages.length;
  $('refundOpen').disabled = !state.packages.length;
  $('packageList').innerHTML = state.packages.length ? [...state.packages].reverse().map((p) => {
    const b = detail.balances[p.id];
    return `<article class="package-card"><p class="eyebrow">${escape(p.date)} 등록</p><strong>${b.remainingUnits}회 남음 <span class="muted">/ ${p.units}회</span></strong><progress value="${b.usedUnits + b.cancelledUnits}" max="${p.units}" aria-label="사용 또는 취소한 회차"></progress>${p.lines.map((line,i) => { const part=detail.lineBalances[p.id][i]; return `<p><strong>${escape(line.label)}</strong> · ${part.remainingUnits}/${line.units}회 남음</p><p class="muted">${money(part.netAmount)} · 출석 ${part.usedUnits}회 · 취소 ${part.cancelledUnits}회 · 미수 ${money(part.due)}</p>`; }).join('')}<p>청구 ${money(b.billed)} · 할인 ${money(p.discount)}</p><p class="${b.due ? 'amount-due' : 'muted'}">미수 ${money(b.due)}</p>${p.memo ? `<p class="muted">${escape(p.memo)}</p>` : ''}</article>`;
  }).join('') : '<p class="muted">등록된 수강권이 없습니다.</p>';
  $('receiptList').innerHTML = state.receipts.length ? [...state.receipts].reverse().map((r) => `<div class="record-row"><div><strong>${escape(r.date)} · ${escape(componentName(r))} · ${methodText[r.method] || '기타'} ${r.voided ? '· 정정 취소됨' : ''}</strong><p>${r.kind === 'refund' ? `회차 취소 ${r.cancelledUnits}회 · 청구 감액 ${money(r.creditAmount)}` : '수납 기록'}</p><p class="muted">${escape(r.voidReason || r.memo)}</p></div><div><strong>${money(r.amount)}</strong>${!r.voided ? `<button type="button" data-void="receipt" data-id="${escape(r.id)}">오입력 정정</button>` : ''}</div></div>`).join('') : '<p class="muted">수납·환불 내역이 없습니다.</p>';
  $('auditList').innerHTML = detail.audit.map((r) => `<div class="record-row"><div><strong>${actionText[r.action] || escape(r.action)}</strong><p>${escape(auditDescription(r))}</p><p class="muted">${escape(r.actor)} · ${escape(r.createdAt.replace('T',' ').slice(0,19))}</p></div></div>`).join('') || '<p class="muted">변경 이력이 없습니다.</p>';
  renderCalendar();
}
async function loadEvidence() {
  const sequence = ++evidenceSequence, sid = selectedSid, month = $('historyMonth').value;
  evidence = [];
  renderCalendar();
  notice('evidenceMessage', '운영판의 출결 기록을 확인하고 있습니다.');
  try {
    const result = await fetchJson(`/api/payments/evidence?${new URLSearchParams({ sid, month })}`, { cache:'no-store' });
    if (sequence !== evidenceSequence || sid !== selectedSid) return;
    evidence = result.events;
    notice('evidenceMessage', result.archived ? '과거 계정은 확정한 수업 기록만 표시합니다.' : '회색 기록은 운영판 자료입니다. 확인 전에는 결제 회차를 차감하지 않습니다.');
    renderCalendar();
  } catch (error) {
    if (sequence === evidenceSequence) notice('evidenceMessage', `운영판 기록을 가져오지 못했습니다. ${paymentMessage(error)}`);
  }
}
function visibleSessions() { return detail.account.sessions.filter((r) => !r.voided && r.date.startsWith($('historyMonth').value)); }
function renderCalendar() {
  if (!detail) return;
  const sessions = visibleSessions();
  const events = sessions.map((r) => ({ id:r.id, start:r.date, title:`${r.slot}타임 ${componentName(r)} ${r.kind === 'makeup' ? '보강 ' : ''}${statusText[r.status]}`, color:r.status === 'absent' ? '#b84d60' : r.kind === 'makeup' ? '#7060ad' : r.status === 'attended' ? '#257b56' : '#64758d' }));
  const sourceDates = [...new Set(evidence.map((r) => r.date))];
  events.push(...sourceDates.map((date) => ({ start:date, title:'운영판 기록 확인', color:'#697789' })));
  if (window.FullCalendar) {
    $('calendar').hidden = false;
    $('calendarFallback').hidden = true;
    if (!calendar) {
      calendar = new window.FullCalendar.Calendar($('calendar'), { initialView:'dayGridMonth', locale:'ko', headerToolbar:false,
        height:'auto', fixedWeekCount:false, dayMaxEvents:3,
        dateClick:({ dateStr }) => { selectedDay = dateStr; renderDay(); },
        eventClick:({ event }) => { selectedDay = event.startStr.slice(0,10); renderDay(); } });
      calendar.render();
    }
    calendar.gotoDate(`${$('historyMonth').value}-01`);
    calendar.removeAllEvents();
    calendar.addEventSource(events);
  } else {
    $('calendar').hidden = true;
    $('calendarFallback').hidden = false;
    const [year, month] = $('historyMonth').value.split('-').map(Number);
    const count = new Date(year, month, 0).getDate();
    const offset = new Date(year, month - 1, 1).getDay();
    $('calendarFallback').innerHTML = ['일','월','화','수','목','금','토'].map((s) => `<span>${s}</span>`).join('') + '<span></span>'.repeat(offset)
      + Array.from({ length:count }, (_, i) => { const date = `${$('historyMonth').value}-${String(i+1).padStart(2,'0')}`;
        return `<button type="button" data-day="${date}">${i+1}<small>${sessions.filter((r) => r.date === date).length}개 수업${sourceDates.includes(date) ? ' · 확인' : ''}</small></button>`;
      }).join('');
  }
  renderDay();
}
function renderDay() {
  $('historyDate').value = selectedDay;
  $('dayTitle').textContent = selectedDay;
  const sessions = visibleSessions().filter((r) => r.date === selectedDay);
  const sources = evidence.filter((r) => r.date === selectedDay);
  $('dayEvents').innerHTML = sessions.map((r) => `<article class="day-record"><div><span class="badge ${r.kind === 'makeup' ? 'makeup' : r.status}">${kindText[r.kind]} · ${statusText[r.status]}</span></div><p>${r.slot}타임 · ${r.chargedUnits}회 차감</p>${r.sourceSessionId ? `<p class="muted">원결석 ${escape(detail.account.sessions.find((s) => s.id === r.sourceSessionId)?.date || '')}</p>` : ''}<p class="muted">${escape(r.memo)}</p><div class="actions"><button type="button" data-edit-session="${escape(r.id)}">기록 수정</button><button type="button" data-void="session" data-id="${escape(r.id)}">오입력 정정</button></div></article>`).join('')
    + sources.map((r, i) => `<article class="day-record"><span class="badge evidence">운영판 기록</span><p>${escape(r.label)}${r.slot ? ` · ${r.slot}타임` : ''}</p><button type="button" data-confirm-evidence="${i}" ${!detail.account.config || studentRecord().archived ? 'disabled' : ''}>수업 확인·기록</button></article>`).join('')
    + (!sessions.length && !sources.length ? '<p class="muted">이 날짜의 기록이 없습니다.</p>' : '');
}

function input(label, name, type = 'text', value = '', attrs = '') { return `<label>${escape(label)}<input name="${name}" type="${type}" value="${escape(value)}" ${attrs}></label>`; }
function select(label, name, options, value = '') { return `<label>${escape(label)}<select name="${name}">${options.map(([id, text]) => `<option value="${escape(id)}" ${String(id) === String(value) ? 'selected' : ''}>${escape(text)}</option>`).join('')}</select></label>`; }
function packagesOptions() { return [...detail.account.packages].reverse().map((p) => [p.id, `${p.date} · ${p.units}회 · 남은 ${detail.balances[p.id].remainingUnits}회 · 미수 ${money(detail.balances[p.id].due)}`]); }
function componentOptions(packageId, action) {
  const p = detail.account.packages.find((row) => row.id === packageId);
  return [...(action === 'payment' ? [['all','전체 미수금 일괄 수납']] : [['','강좌를 선택하세요']]), ...(p?.lines || []).map((line,i) => [i, `${line.label} · 남은 ${detail.lineBalances[p.id][i].remainingUnits}/${line.units}회`])];
}
function linesFields(lines) {
  return `<div class="wide"><div class="line-fields"><span>구성</span><span>회차</span><span>회당 단가(원)</span></div>${[...lines, ...Array(Math.max(0,2-lines.length)).fill({ label:'추가', units:0, unitPrice:0 })].map((r, i) => `<div class="line-fields"><input aria-label="${i+1}번째 구성 이름" name="lineLabel${i}" value="${escape(r.label)}" maxlength="40"><input aria-label="${i+1}번째 회차" name="lineUnits${i}" type="number" min="0" max="200" step="1" value="${r.units}"><input aria-label="${i+1}번째 회당 단가" name="linePrice${i}" type="number" min="0" max="1000000000" step="1" value="${r.unitPrice}"></div>`).join('')}<p class="form-help">추가 회차가 없으면 0으로 두세요. 기존 수강권의 금액은 바뀌지 않습니다.</p></div>`;
}
function openDialog(action, seed = {}) {
  if (!detail || client.pending || client.saving) return;
  dialogAction = action; dialogSeed = seed; dialogRevision = detail.revision; conflict = false;
  $('dialogTitle').textContent = actionText[action];
  $('dialogStudent').textContent = `${studentRecord().student.name} · ${studentRecord().student.curriculum || selectedSid}`;
  $('dialogSave').textContent = '저장'; $('dialogSave').disabled = false; $('dialogReload').hidden = true;
  notice('dialogError', '');
  const memo = '<label class="wide">메모·사유<textarea name="memo" maxlength="1000" rows="2"></textarea></label>';
  const today = overview.today;
  let fields = '';
  if (action === 'configure' || action === 'package') {
    fields = select('요금 구성', 'plan', [...overview.plans.map((p) => [p.id, `${p.label} · ${money(p.lines.reduce((s,l) => s+l.units*l.unitPrice,0))}`]), ['custom','직접 설정']], 'custom')
      + input(action === 'configure' ? '회차 관리 시작일' : '수강권 등록일', 'date', 'date', action === 'configure' ? detail.account.config?.startsOn || today : today, 'required')
      + `<div id="priceLines" class="wide">${linesFields(detail.account.config?.lines || overview.plans[0].lines)}</div>`
      + (action === 'package' ? input('할인액(원) · 단일 강좌만', 'discount', 'number', 0, 'min="0" step="1" required') + '<p class="wide form-help">기본+특강의 할인은 각 강좌 단가를 조정하세요. 수납과 환불은 강좌별로 구분합니다.</p>' + memo : '<p class="wide form-help">별도의 (특) 학생·과목 행이면 추가 강좌만 선택하세요. 기본 행과 자동으로 합산하지 않습니다. 결석·취소·자습은 회차를 차감하지 않습니다.</p>')
      + '<p id="priceTotal" class="wide form-total"></p>';
  } else if (action === 'payment' || action === 'refund') {
    const packageId = seed.packageId || packagesOptions()[0]?.[0];
    fields = select('수강권', 'packageId', packagesOptions(), packageId)
      + select(action === 'payment' ? '수납 강좌' : '취소·환불 강좌', 'lineIndex', componentOptions(packageId,action), action === 'payment' ? 'all' : '')
      + input(action === 'payment' ? '수납일' : '환불일', 'date', 'date', today, `max="${today}" required`);
    if (action === 'payment') fields += input('수납액(원)', 'amount', 'number', '', 'min="1" step="1" required')
      + select('수납 수단', 'method', Object.entries(methodText).filter(([key]) => key !== 'refund'))
      + '<p class="wide form-help">이미 받은 금액을 기록합니다. 카드 승인이나 계좌이체를 실행하지 않습니다.</p>';
    else fields += input('취소할 남은 회차', 'units', 'number', 0, 'min="0" step="1" required')
      + input('자동 계산한 청구 감액(원)', 'creditAmount', 'number', 0, 'readonly')
      + input('실제로 돌려준 금액(원)', 'amount', 'number', 0, 'min="0" step="1" required')
      + '<p class="wide form-help">선택한 강좌 금액의 1/n로 미사용 회차를 취소합니다. 지급 전이면 실제 환불액은 0원으로 남기세요. 나중에 지급할 때는 취소 회차 0으로 기록합니다.</p>';
    fields += memo + '<p id="paymentPreview" class="wide form-total"></p>';
  } else if (action === 'session') {
    const absences = detail.account.sessions.filter((r) => !r.voided && r.kind === 'regular' && r.status === 'absent');
    fields = input('수업 날짜', 'date', 'date', seed.date || selectedDay || today, 'required')
      + select('수업 타임', 'slot', [['','선택하세요'], ...[1,2,3,4,5,6].map((i) => [i,`${i}타임`])], seed.slot || '')
      + select('수업 종류', 'kind', Object.entries(kindText), seed.kind || 'regular')
      + select('수업 상태', 'status', Object.entries(statusText), seed.status || 'planned')
      + select('차감할 수강권', 'packageId', [['','선택하세요'], ...packagesOptions()], seed.packageId || '')
      + select('수업 강좌', 'lineIndex', componentOptions(seed.packageId || '',action), seed.lineIndex ?? '')
      + select('보강의 원래 결석', 'sourceSessionId', [['','보강이면 원결석을 선택'], ...absences.map((r) => [r.id, `${r.date} · ${r.slot}타임 · ${componentName(r)}`])], seed.sourceSessionId || '')
      + '<p class="wide form-help">하루에 두 수업이면 타임별로 하나씩 기록합니다. 보강은 같은 수강권의 원결석과 연결하세요. 출석만 1회 차감됩니다.</p>' + memo;
  } else if (action === 'void') {
    fields = '<p class="wide form-help">잘못 입력한 기록의 효력을 취소합니다. 원본과 정정 사유는 변경 이력에 남습니다. 실제 환불은 취소·환불 기록에서 처리하세요.</p>' + memo;
  }
  $('dialogFields').innerHTML = fields;
  const memoField = $('editForm').elements.namedItem('memo');
  if (memoField) { memoField.value = seed.memo || ''; memoField.required = ['refund','void'].includes(action); }
  updateFormPreview();
  $('editDialog').showModal();
}
function readLines() {
  const f = $('editForm').elements, rows = [];
  for (let i=0; f.namedItem(`lineUnits${i}`); i++) {
    const units = Number(f.namedItem(`lineUnits${i}`).value);
    if (units) rows.push({ label:f.namedItem(`lineLabel${i}`).value, units, unitPrice:Number(f.namedItem(`linePrice${i}`).value) });
  }
  return rows;
}
function formPayload() {
  const data = Object.fromEntries(new FormData($('editForm')).entries());
  const action = dialogAction;
  if (action === 'configure') return { action, lines:readLines(), startsOn:data.date };
  if (action === 'package') return { action, date:data.date, lines:readLines(), discount:Number(data.discount), memo:data.memo };
  const lineIndex = data.lineIndex === 'all' ? 'all' : data.lineIndex === '' ? null : Number(data.lineIndex);
  if (action === 'payment') return { action, packageId:data.packageId, lineIndex, date:data.date, amount:Number(data.amount), method:data.method, memo:data.memo };
  if (action === 'refund') return { action, packageId:data.packageId, lineIndex, date:data.date, units:Number(data.units), amount:Number(data.amount), memo:data.memo };
  if (action === 'void') return { action, targetType:dialogSeed.targetType, targetId:dialogSeed.targetId, memo:data.memo };
  return { action, date:data.date, slot:Number(data.slot), kind:data.kind, status:data.status, packageId:data.packageId || null, lineIndex,
    sourceSessionId:data.sourceSessionId || null, memo:data.memo, ...(dialogSeed.id ? { sessionId:dialogSeed.id } : {}) };
}
function updateFormPreview() {
  const f = $('editForm').elements;
  if ($('priceTotal')) { const lines = readLines(); $('priceTotal').textContent = `${lines.reduce((s,l) => s+l.units,0)}회 · ${money(lines.reduce((s,l) => s+l.units*l.unitPrice,0) - Number(f.namedItem('discount')?.value || 0))}`; }
  if ($('paymentPreview')) {
    const packageId = f.namedItem('packageId').value, index = f.namedItem('lineIndex').value;
    const balance = index === 'all' ? detail.balances[packageId] : index === '' ? null : detail.lineBalances[packageId]?.[Number(index)];
    if (!balance) { $('paymentPreview').textContent = '강좌를 선택하세요.'; return; }
    if (dialogAction === 'payment') {
      if (f.namedItem('amount').value === '') f.namedItem('amount').value = balance.due;
      $('paymentPreview').textContent = `미수 ${money(balance.due)} · 분할 수납은 해당 강좌를 선택하세요.`;
    } else {
      const p = detail.account.packages.find((row) => row.id === packageId), units = Number(f.namedItem('units').value);
      const credit = Math.floor(balance.netAmount * (balance.cancelledUnits + units) / p.lines[Number(index)].units) - balance.creditAmount;
      f.namedItem('creditAmount').value = credit;
      f.namedItem('units').max = balance.remainingUnits;
      const payable = Math.max(balance.paid - balance.billed + credit,0);
      f.namedItem('amount').max = Math.min(payable,balance.paid);
      $('paymentPreview').textContent = `취소 후 ${balance.remainingUnits-units}회 남음 · 청구 감액 ${money(credit)} · 환불 가능 ${money(Math.min(payable,balance.paid))}`;
    }
  }
}
function lockForm(locked) {
  for (const element of $('dialogFields').querySelectorAll('input,select,textarea')) element.disabled = locked;
  $('dialogClose').disabled = locked; $('dialogCancel').disabled = locked;
  $('dialogSave').disabled = client.saving || conflict;
}
function closeDialog() { if (!client.pending && !client.saving) $('editDialog').close(); }
async function saveDialog(event) {
  event.preventDefault();
  if (client.saving || conflict) return;
  const sid = selectedSid, payload = client.pending || formPayload();
  overviewSequence += 1;
  notice('dialogError', '저장하고 있습니다.');
  const saving = client.save(sid, dialogRevision, payload);
  lockForm(true); $('dialogSave').textContent = '저장 중…';
  try {
    const result = await saving;
    $('editDialog').close();
    detail = null;
    notice('pageMessage', '저장했습니다. 최신 내역을 확인하고 있습니다.');
    const row = overview.students.find((r) => r.sid === sid);
    Object.assign(row, result.summary, { revision:result.revision });
    renderOverview();
    await selectStudent(sid);
    notice('pageMessage', detail ? '저장했습니다.' : '저장은 완료했습니다. 내역을 다시 불러오려면 새로고침하세요.');
  } catch (error) {
    conflict = error.status === 409;
    notice('dialogError', client.pending ? '저장 결과를 확인하지 못했습니다. 입력을 그대로 유지했습니다. 같은 작업으로 재시도해 주세요.' : paymentMessage(error));
    $('dialogReload').hidden = !conflict;
    $('dialogSave').textContent = client.pending ? '같은 작업 재시도' : '저장';
  } finally { lockForm(Boolean(client.pending)); }
}

$('studentSearch').addEventListener('input', renderStudents);
$('accountFilter').addEventListener('change', renderStudents);
$('studentList').addEventListener('click', (event) => { const row = event.target.closest('[data-sid]'); if (row) void selectStudent(row.dataset.sid); });
$('reloadPage').addEventListener('click', () => { if (!client.pending && !client.saving) void loadOverview(); });
$('historyMonth').addEventListener('change', () => { if ($('historyMonth').value && detail) { selectedDay = `${$('historyMonth').value}-01`; void loadEvidence(); } });
$('historyDate').addEventListener('change', () => { if (!$('historyDate').value || !detail) return; selectedDay = $('historyDate').value;
  if ($('historyMonth').value !== selectedDay.slice(0,7)) { $('historyMonth').value = selectedDay.slice(0,7); void loadEvidence(); } else renderDay(); });
for (const action of ['configure','package','payment','refund','session']) $(`${action}Open`).addEventListener('click', () => openDialog(action));
$('calendarFallback').addEventListener('click', (event) => { const day = event.target.closest('[data-day]'); if (day) { selectedDay = day.dataset.day; renderDay(); } });
$('accountContent').addEventListener('click', (event) => {
  const edit = event.target.closest('[data-edit-session]');
  if (edit) openDialog('session', detail.account.sessions.find((r) => r.id === edit.dataset.editSession));
  const correction = event.target.closest('[data-void]');
  if (correction) openDialog('void', { targetType:correction.dataset.void, targetId:correction.dataset.id });
  const source = event.target.closest('[data-confirm-evidence]');
  if (source) { const row = evidence.filter((r) => r.date === selectedDay)[Number(source.dataset.confirmEvidence)];
    openDialog('session', { date:row.date, slot:row.slot, kind:row.kind === 'makeup' ? 'makeup' : 'regular', status:row.kind === 'absence' ? 'absent' : 'planned', memo:row.label });
  }
});
$('editForm').addEventListener('submit', saveDialog);
$('editForm').addEventListener('input', updateFormPreview);
$('editForm').addEventListener('change', (event) => {
  if (event.target.name === 'plan') { const plan = overview.plans.find((p) => p.id === event.target.value); if (plan) $('priceLines').innerHTML = linesFields(plan.lines); }
  if (event.target.name === 'packageId') {
    const field = $('editForm').elements.namedItem('lineIndex');
    if (field) field.innerHTML = componentOptions(event.target.value,dialogAction).map(([id,label]) => `<option value="${escape(id)}">${escape(label)}</option>`).join('');
  }
  if (dialogAction === 'payment' && ['packageId','lineIndex'].includes(event.target.name)) $('editForm').elements.namedItem('amount').value = '';
  updateFormPreview();
});
$('dialogClose').addEventListener('click', closeDialog);
$('dialogCancel').addEventListener('click', closeDialog);
$('editDialog').addEventListener('cancel', (event) => { if (client.pending || client.saving) event.preventDefault(); });
$('dialogReload').addEventListener('click', async () => {
  try { const fresh = await client.readAccount(selectedSid); if (!fresh) return; detail = fresh; dialogRevision = fresh.revision; conflict = false; $('dialogReload').hidden = true;
    renderAccount(); notice('dialogError', '최신 내역을 불러왔습니다. 입력한 내용과 비교한 뒤 다시 저장하세요.'); lockForm(false);
  } catch (error) { notice('dialogError', paymentMessage(error)); }
});
window.addEventListener('beforeunload', (event) => { if (client.pending || client.saving) { event.preventDefault(); event.returnValue = ''; } });
window.addEventListener('load', () => { if (detail) renderCalendar(); });
void loadOverview();
