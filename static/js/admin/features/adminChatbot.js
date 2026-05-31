import { api } from '../core/api.js';

const DEFAULT_SUGGESTIONS = [
  '보강 잡기 기능 설명',
  '학생 이름 정보',
  '학생 이름 오늘 숙제 진도',
  '학교명 기말 일정',
  '영상 배정 기능 설명',
  '테스트 관리 기능 설명',
];

function $(id) {
  return document.getElementById(id);
}

function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

function tokenHeaders() {
  const token = String(sessionStorage.getItem('adminChatToken') || '').trim();
  return token ? { 'X-Admin-Chat-Token': token } : {};
}

function scrollMessages(messages) {
  requestAnimationFrame(() => {
    messages.scrollTop = messages.scrollHeight;
  });
}

function appendMessage(messages, role, text) {
  const msg = makeEl('article', `admin-chat-msg ${role}`);
  msg.appendChild(makeEl('p', '', text));
  messages.appendChild(msg);
  scrollMessages(messages);
  return msg;
}

function renderCards(host, cards = []) {
  cards.forEach((card) => {
    const box = makeEl('section', 'admin-chat-result');
    box.appendChild(makeEl('h4', '', card.title || '결과'));
    const list = makeEl('ul', '');
    (card.lines || []).forEach((line) => {
      const item = makeEl('li', '', line);
      list.appendChild(item);
    });
    if (list.children.length) box.appendChild(list);
    host.appendChild(box);
  });
}

function renderSources(host, sources = []) {
  if (!sources.length) return;
  const wrap = makeEl('div', 'admin-chat-sources');
  sources.slice(0, 12).forEach((source) => {
    wrap.appendChild(makeEl('span', '', source));
  });
  host.appendChild(wrap);
}

function appendBotResponse(messages, data) {
  const msg = makeEl('article', 'admin-chat-msg bot');
  msg.appendChild(makeEl('p', '', data?.answer || '확인된 답변이 없습니다.'));
  renderCards(msg, Array.isArray(data?.cards) ? data.cards : []);
  renderSources(msg, Array.isArray(data?.sources) ? data.sources : []);
  messages.appendChild(msg);
  scrollMessages(messages);
}

function renderSuggestions(host, suggestions, onPick) {
  host.textContent = '';
  (suggestions && suggestions.length ? suggestions : DEFAULT_SUGGESTIONS).slice(0, 6).forEach((text) => {
    const btn = makeEl('button', 'admin-chat-chip', text);
    btn.type = 'button';
    btn.addEventListener('click', () => onPick(text));
    host.appendChild(btn);
  });
}

export function initAdminChatbot() {
  const openBtn = $('adminChatOpen');
  const panel = $('adminChatPanel');
  const closeBtn = $('adminChatClose');
  const messages = $('adminChatMessages');
  const suggestions = $('adminChatSuggestions');
  const form = $('adminChatForm');
  const input = $('adminChatInput');

  if (!openBtn || !panel || !closeBtn || !messages || !suggestions || !form || !input) return;

  let busy = false;
  let greeted = false;

  function openPanel() {
    panel.hidden = false;
    panel.style.display = '';
    panel.classList.add('is-open');
    openBtn.setAttribute('aria-expanded', 'true');
    if (!greeted) {
      appendMessage(messages, 'bot', '내부 자료에서 학생, 출결·보강, 학교 일정, 운영 기능을 찾아볼게요.');
      renderSuggestions(suggestions, DEFAULT_SUGGESTIONS, submitQuestion);
      greeted = true;
    }
    setTimeout(() => input.focus(), 30);
  }

  function closePanel() {
    panel.classList.remove('is-open');
    panel.hidden = true;
    panel.style.display = '';
    openBtn.setAttribute('aria-expanded', 'false');
    openBtn.focus();
  }

  async function submitQuestion(raw) {
    const message = String(raw || input.value || '').trim();
    if (!message || busy) return;

    busy = true;
    input.value = '';
    appendMessage(messages, 'user', message);
    const pending = appendMessage(messages, 'bot pending', '찾는 중...');

    try {
      const res = await api.post('/api/admin/chat', { message }, {
        cache: 'no-store',
        headers: tokenHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      pending.remove();
      if (!res.ok || data?.ok === false) {
        throw new Error(data?.error || `요청 실패 (${res.status})`);
      }
      appendBotResponse(messages, data);
      renderSuggestions(suggestions, data.suggestions, submitQuestion);
    } catch (err) {
      pending.remove();
      appendMessage(messages, 'bot error', err?.message || '챗봇 요청에 실패했습니다.');
    } finally {
      busy = false;
      input.focus();
    }
  }

  openBtn.addEventListener('click', openPanel);
  closeBtn.addEventListener('click', closePanel);
  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    submitQuestion();
  });
  input.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' || ev.shiftKey) return;
    ev.preventDefault();
    submitQuestion();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !panel.hidden) closePanel();
  });
}
