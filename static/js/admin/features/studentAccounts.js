import { ensureOk, fetchJsonChecked, sendJson } from '../../shared/api.js';

const LIST_URL = '/api/student-accounts';

function element(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function accountStatus(group) {
  if (!group?.account) return 'unavailable';
  return String(group.account.status || 'active');
}

function accountKey(group) {
  return String(group?.account?.aid || group?.identity?.aid || group?.identity?.name || '').trim();
}

function statusLabel(group) {
  const labels = { active: '사용 중', disabled: '비활성', unavailable: '계정 없음' };
  return labels[accountStatus(group)] || accountStatus(group);
}

function normalizedGroups(payload) {
  return Array.isArray(payload?.groups) ? payload.groups.filter(group => group?.identity) : [];
}

function expiryLabel(value) {
  const numeric = Number(value);
  const date = Number.isFinite(numeric)
    ? new Date(numeric < 1e12 ? numeric * 1000 : numeric)
    : new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString('ko-KR') : '24시간 후';
}

function matches(group, query, filter) {
  const account = group.account || {};
  if (filter === 'active' && accountStatus(group) !== 'active') return false;
  if (filter === 'disabled' && accountStatus(group) !== 'disabled') return false;
  if (filter === 'activation' && !group.activationCodeRequired) return false;
  if (filter === 'must-change' && !account.mustChangeCredentials) return false;
  const identity = group.identity || {};
  const haystack = [identity.name, identity.school, identity.grade, ...(identity.sids || []), account.aid]
    .join(' ')
    .toLocaleLowerCase('ko-KR');
  return !query || haystack.includes(query);
}

export function initStudentAccounts() {
  const openButton = document.getElementById('studentAccountsOpen');
  const modal = document.getElementById('studentAccountsModal');
  if (!openButton || !modal) return;

  const closeButton = document.getElementById('studentAccountsClose');
  const search = document.getElementById('studentAccountsSearch');
  const filter = document.getElementById('studentAccountsFilter');
  const refresh = document.getElementById('studentAccountsRefresh');
  const status = document.getElementById('studentAccountsStatus');
  const list = document.getElementById('studentAccountsList');
  const codePanel = document.getElementById('studentActivationCodePanel');
  const codeValue = document.getElementById('studentActivationCodeValue');
  const copyButton = document.getElementById('studentActivationCodeCopy');
  const codeDismiss = document.getElementById('studentActivationCodeDismiss');
  let groups = [];
  let pendingCode = '';
  let restoreFocus = null;

  const setStatus = (message, kind = '') => {
    status.textContent = message;
    status.className = `student-accounts-status${kind ? ` is-${kind}` : ''}`;
  };

  const clearActivationCode = () => {
    pendingCode = '';
    codeValue.textContent = '';
    codePanel.hidden = true;
    copyButton.disabled = false;
  };

  const actionButton = (label, action, group, tone = '') => {
    const button = element('button', `btn secondary student-accounts-action${tone ? ` is-${tone}` : ''}`, label);
    button.type = 'button';
    button.dataset.accountAction = action;
    button.dataset.aid = accountKey(group);
    button.addEventListener('click', () => runAction(action, group, button));
    return button;
  };

  const render = () => {
    const query = search.value.trim().toLocaleLowerCase('ko-KR');
    const visible = groups.filter(group => matches(group, query, filter.value));
    list.replaceChildren();
    if (!visible.length) {
      list.append(element('p', 'student-accounts-empty', '조건에 맞는 계정이 없습니다.'));
      return;
    }
    visible.forEach(group => {
      const identity = group.identity;
      const account = group.account;
      const card = element('article', 'student-accounts-card');
      const heading = element('div', 'student-accounts-card-head');
      const title = element('div');
      title.append(
        element('strong', '', identity.name || '이름 없음'),
        element('span', 'student-accounts-identity', `${identity.school || '-'} · ${identity.grade || '-'} · SID ${(identity.sids || []).join(', ')}`),
      );
      heading.append(title, element('span', `student-accounts-badge is-${accountStatus(group)}`, statusLabel(group)));
      const flags = element('div', 'student-accounts-flags');
      if (group.activationCodeRequired) flags.append(element('span', 'student-accounts-flag', '활성화 코드 필요'));
      if (group.duplicateName || (identity.sids || []).length > 1) flags.append(element('span', 'student-accounts-flag is-warning', '동명이인 확인'));
      if (account?.mustChangeCredentials) flags.append(element('span', 'student-accounts-flag is-warning', '자격 증명 변경 필요'));
      const metrics = element('p', 'student-accounts-metrics', account
        ? `계정 ${account.aid} · 세션 ${Number(account.activeSessionCount || 0)} · 푸시 ${Number(account.activePushSubscriptionCount || 0)}`
        : '연결된 학생 앱 계정이 없습니다.');
      card.append(heading, flags, metrics);
      if (!account && group.activationCodeRequired && accountKey(group)) {
        const activationActions = element('div', 'student-accounts-actions');
        activationActions.append(actionButton('활성화 코드', 'activation-code', group));
        card.append(activationActions);
      }
      if (account) {
        const actions = element('div', 'student-accounts-actions');
        if (accountStatus(group) === 'disabled') {
          actions.append(actionButton('계정 활성화', 'enable', group));
        } else {
          if (group.activationCodeRequired) actions.append(actionButton('활성화 코드', 'activation-code', group));
          actions.append(actionButton('비밀번호 초기화', 'reset', group));
          actions.append(actionButton('세션 해제', 'revoke-sessions', group));
          actions.append(actionButton('계정 비활성화', 'disable', group, 'danger'));
        }
        card.append(actions);
      }
      list.append(card);
    });
  };

  const load = async () => {
    refresh.disabled = true;
    setStatus('계정 목록을 불러오는 중입니다.');
    try {
      const payload = await fetchJsonChecked(LIST_URL, '학생 앱 계정 조회', { cache: 'no-store', credentials: 'same-origin' });
      groups = normalizedGroups(payload);
      render();
      setStatus(`${groups.length}개 학생 식별 그룹을 확인했습니다.`, 'success');
    } catch {
      groups = [];
      render();
      setStatus('계정 목록을 불러오지 못했습니다.', 'error');
    } finally {
      refresh.disabled = false;
    }
  };

  const runAction = async (action, group, button) => {
    const aid = accountKey(group);
    if (!aid) return;
    if (action === 'reset' && !globalThis.confirm(`${group.identity.name} 계정의 비밀번호를 1234로 초기화하고 모든 세션을 해제할까요?`)) return;
    if (action === 'disable' && !globalThis.confirm(`${group.identity.name} 계정을 비활성화하고 세션과 푸시를 모두 해제할까요?`)) return;
    button.disabled = true;
    clearActivationCode();
    setStatus('요청을 처리하는 중입니다.');
    try {
      const body = action === 'activation-code' ? { sids: [...(group.identity.sids || [])] } : {};
      const response = await sendJson(`${LIST_URL}/${encodeURIComponent(aid)}/${action}`, body, { credentials: 'same-origin' });
      await ensureOk(response, `학생 앱 계정 ${action}`);
      const payload = await response.json();
      if (action === 'activation-code') {
        pendingCode = String(payload.activationCode || '');
        if (!/^\d{6}$/.test(pendingCode)) throw new Error('invalid activation code response');
        codeValue.textContent = pendingCode;
        codePanel.hidden = false;
        copyButton.focus();
        setStatus(`활성화 코드는 ${expiryLabel(payload.expiresAt)} 만료됩니다. 이 화면에서 한 번만 복사하세요.`, 'success');
      } else {
        await load();
      }
    } catch {
      setStatus('요청을 처리하지 못했습니다. 목록을 새로고침한 뒤 다시 시도해 주세요.', 'error');
    } finally {
      button.disabled = false;
    }
  };

  const close = () => {
    clearActivationCode();
    document.body.classList.remove('student-accounts-open');
    modal.style.display = 'none';
    modal.hidden = true;
    restoreFocus?.focus();
  };

  openButton.addEventListener('click', () => {
    restoreFocus = document.activeElement;
    document.body.classList.add('student-accounts-open');
    modal.hidden = false;
    modal.style.display = 'flex';
    search.focus();
    load();
  });
  closeButton.addEventListener('click', close);
  codeDismiss.addEventListener('click', clearActivationCode);
  refresh.addEventListener('click', load);
  search.addEventListener('input', render);
  filter.addEventListener('change', render);
  modal.addEventListener('click', event => { if (event.target === modal) close(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !modal.hidden) close(); });
  copyButton.addEventListener('click', async () => {
    if (!pendingCode) return;
    try {
      await navigator.clipboard.writeText(pendingCode);
      clearActivationCode();
      setStatus('활성화 코드를 복사했습니다. 화면에서는 즉시 지웠습니다.', 'success');
    } catch {
      setStatus('자동 복사가 차단되었습니다. 표시된 코드를 직접 복사해 주세요.', 'error');
    }
  });
}
