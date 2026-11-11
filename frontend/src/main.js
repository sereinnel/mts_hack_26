import { api } from './api/client.js';
import {
  getActiveSessionId, setActiveSessionId, clearActiveSessionId,
  getRecentSessions, rememberSession, markSessionClosed,
  getSavedLeadId, rememberLeadId,
} from './lib/storage.js';

const root = document.getElementById('app');
const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);
const state = {
  sessionId: null,
  messages: [],
  loadingHistory: false,
  creating: false,
  sending: false,
  pendingMessage: null,
  error: '',
  draft: '',
  health: null,
  debug: false,
  sidebarOpen: false,
  leadOpen: false,
  leadSending: false,
  lead: { fullName: '', phone: '', company: '', consent: false },
  leadError: '',
  leadSuccessId: null,
  messageMeta: {},
};

const icons = {
  bolt: '<path d="m13 2-9 12h7l-1 8 10-12h-7l1-8Z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
  message: '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8A8.5 8.5 0 0 1 12.5 3a8.5 8.5 0 0 1 8.5 8.5 8.5 0 0 1 0 8.5Z"/>',
  user: '<path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="8" r="4"/>',
  bot: '<rect x="3" y="7" width="18" height="14" rx="4"/><path d="M12 3v4M9 3h6M8.5 13h.01M15.5 13h.01M9 17h6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h7"/>',
  bug: '<path d="m8 2 1.5 2M16 2l-1.5 2M8 8h8M5 12H2M5 17l-3 2M19 12h3M19 17l3 2"/><rect x="5" y="5" width="14" height="16" rx="7"/><path d="M12 8v13"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  arrow: '<path d="m5 12 14 0M13 6l6 6-6 6"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14-5L4 8M4 4v4h4M4 13a8 8 0 0 0 14 5l2-2M16 16h4v4"/>',
  alert: '<path d="m10.3 4.3-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-2.7l-8-14a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  external: '<path d="M14 3h7v7M10 14 21 3"/><path d="M21 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h6"/>',
};
function icon(name, size = 18) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.message}</svg>`;
}
function escapeHTML(value = '') {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[ch]);
}
function formatDate(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return 'Недавний диалог';
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(d);
}
function formatTime(value) {
  if (!value) return '';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '' : new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(d);
}
const busy = () => state.creating || state.sending || state.loadingHistory;
function diagnosticsFor(message) {
  const meta = state.messageMeta[String(message.id)] || {};
  return { ...meta, sources: Array.isArray(message.sources) ? message.sources : (meta.sources || []), intent: message.intent || meta.intent };
}
function sidebar() {
  const sessions = getRecentSessions();
  return `
    <aside class="sidebar ${state.sidebarOpen ? 'sidebar-open' : ''}" aria-label="История консультаций">
      <div class="sidebar-brand">
        <div class="brand-symbol" aria-hidden="true"><span class="brand-symbol-stroke"></span><span class="brand-symbol-stroke"></span><span class="brand-symbol-stroke"></span></div>
        <div class="brand-type"><strong>EnergyTool<span>.</span></strong><small>Консультант для бизнеса</small></div>
        <button class="icon-button mobile-close" data-action="sidebar-toggle" aria-label="Закрыть меню">${icon('x')}</button>
      </div>
      <div class="sidebar-content">
        <button class="new-chat-btn" data-action="new-session" ${busy() ? 'disabled' : ''}>${icon('plus', 18)}<span>${state.creating ? 'Создаём диалог…' : 'Новый диалог'}</span></button>
        <div class="sidebar-label"><span>ВАШИ ДИАЛОГИ</span><span class="session-count">${sessions.length}</span></div>
        <nav class="session-list" aria-label="Предыдущие диалоги">
          ${sessions.length ? sessions.map((item, index) => `
            <button class="session-item ${item.id === state.sessionId ? 'active' : ''}" data-action="open-session" data-id="${escapeHTML(item.id)}" ${busy() ? 'disabled' : ''} aria-current="${item.id === state.sessionId ? 'page' : 'false'}" title="${escapeHTML(item.id)}">
              <span class="session-icon">${icon('message', 16)}</span>
              <span class="session-details"><span class="session-title">Консультация ${String(sessions.length - index).padStart(2, '0')}</span><span class="session-subtitle">${item.closed_at ? 'Завершена' : escapeHTML(formatDate(item.created_at))}</span></span>
              ${item.id === state.sessionId ? '<span class="session-active-indicator" aria-hidden="true"></span>' : ''}
            </button>
          `).join('') : '<p class="empty-sessions">Здесь появится история ваших обращений.</p>'}
        </nav>
      </div>
      <div class="sidebar-bottom">
        <div class="sidebar-support-label">О ПРОЕКТЕ</div>
        <p>Демонстрация консультанта по решениям для управления электроэнергией.</p>
        <div class="sidebar-safe">${icon('shield', 15)} <span>Используйте тестовые данные</span></div>
      </div>
    </aside>`;
}
function statusText() {
  if (state.health === null) return { label: 'Подключаемся', css: 'neutral' };
  if (state.health.status !== 'ok') return { label: 'Backend недоступен', css: 'offline' };
  if (state.health.ai_mode === 'mock') return { label: 'Тестовый режим', css: 'mock' };
  return { label: 'AI настроен', css: 'online' };
}
function header() {
  const status = statusText();
  const isFresh = state.messages.length === 0 && !state.pendingMessage;
  return `<header class="topbar">
    <div class="topbar-left">
      <button class="icon-button menu-button" data-action="sidebar-toggle" aria-label="Открыть меню">${icon('menu', 21)}</button>
      <div class="topbar-location"><span class="topbar-section">ENERGYTOOL <span class="breadcrumb-sep">/</span> КОНСУЛЬТАЦИИ</span><strong>${isFresh ? 'Новая консультация' : 'Обсуждение задачи'}</strong></div>
    </div>
    <div class="topbar-actions">
      <span class="status status-${status.css}"><span class="status-dot"></span>${status.label}</span>
      ${isLocal ? `<button class="debug-toggle ${state.debug ? 'selected' : ''}" data-action="toggle-debug" aria-pressed="${state.debug}" title="Показать отладочные сведения">${icon('bug', 16)} <span>Отладка</span></button>` : ''}
      <span class="topbar-action-sep" aria-hidden="true"></span>
      <button class="topbar-lead" aria-label="Связаться со специалистом" data-action="open-lead" ${!state.sessionId || state.creating ? 'disabled' : ''}>Связаться со специалистом ${icon('arrow', 16)}</button>
    </div>
  </header>`;
}
const samples = [
  { number: '01', title: 'Снизить расходы', detail: 'Платежи, тарифы, оптимизация', prompt: 'Хочу снизить расходы компании на электроэнергию. Какие решения есть?' },
  { number: '02', title: 'Настроить учёт', detail: 'Счётчики, показания, объекты', prompt: 'У нас несколько объектов и много счётчиков. Как автоматизировать сбор показаний?' },
  { number: '03', title: 'Рассмотреть СЭС', detail: 'Солнечная генерация для бизнеса', prompt: 'Можно ли установить солнечную электростанцию для нашего бизнеса?' },
  { number: '04', title: 'Оценить оптовый рынок', detail: 'Условия перехода и ограничения', prompt: 'Хотим оценить возможность выхода на оптовый рынок электроэнергии. Что нужно знать?' },
];
function welcome() {
  return `<section class="welcome" aria-label="Начало консультации">
    <div class="welcome-primary">
      <div class="welcome-eyebrow"><span class="eyebrow-pulse"></span> ЭНЕРГЕТИКА БИЗНЕСА / ENERGYTOOL</div>
      <h1>Вопрос по энергетике?<br/><span>Давайте разберёмся.</span></h1>
      <p class="welcome-description">Опишите ситуацию: расходы на электроэнергию, учёт показаний или собственная генерация. Поможем разобраться в решениях EnergyTool и их ограничениях.</p>
      <div class="suggestions-heading"><span>С ЧЕГО МОЖНО НАЧАТЬ</span></div>
      <div class="suggestions">
        ${samples.map((sample, i) => `<button class="suggestion" data-action="suggestion" data-index="${i}" ${busy() || !state.sessionId ? 'disabled' : ''}><span class="suggestion-number">${sample.number}</span><span class="suggestion-text"><strong>${escapeHTML(sample.title)}</strong><small>${escapeHTML(sample.detail)}</small></span>${icon('arrow', 17)}</button>`).join('')}
      </div>
    </div>
    <aside class="welcome-aside" aria-label="Как проходит консультация">
      <div class="welcome-aside-graphic" aria-hidden="true">
        <svg viewBox="0 0 280 150" fill="none" role="presentation"><path d="M8 79H75V47H140V105H203V73H274" stroke="currentColor" stroke-width="2"/><path d="M8 119H274M8 30H274M43 22V126M108 22V126M172 22V126M237 22V126" stroke="currentColor" stroke-width=".6" opacity=".13"/><circle cx="75" cy="79" r="4" fill="currentColor"/><circle cx="140" cy="47" r="5" fill="var(--brand)"/><circle cx="203" cy="105" r="4" fill="currentColor"/><circle cx="274" cy="73" r="4" fill="currentColor"/></svg>
      </div>
      <div class="welcome-aside-inner">
        <div class="welcome-aside-head"><span>КАК МЫ РАБОТАЕМ</span><span>01 — 03</span></div>
        <div class="process-step"><span>01</span><div><strong>Вы описываете ситуацию</strong><p>Можно своими словами. Специальные термины необязательны.</p></div></div>
        <div class="process-step"><span>02</span><div><strong>Мы уточняем детали</strong><p>Ищем решения в материалах EnergyTool и объясняем ограничения.</p></div></div>
        <div class="process-step"><span>03</span><div><strong>Вы выбираете следующий шаг</strong><p>Продолжить разговор или оставить обращение специалисту.</p></div></div>
        <div class="welcome-aside-footer">${icon('shield', 16)} <span>Это демонстрационный сервис. Для заявки используйте вымышленные контакты.</span></div>
      </div>
    </aside>
  </section>`;
}
function sourceLabel(source) {
  if (typeof source === 'string') return source;
  if (source && typeof source === 'object') return source.title || source.document_id || source.chunk_id || 'Источник';
  return String(source);
}
function messageDebug(message) {
  const meta = diagnosticsFor(message);
  const sources = meta.sources || [];
  if (!state.debug || message.role !== 'assistant') return '';
  const attrs = [
    meta.intent ? `<span>${icon('chevron', 13)} Intent: ${escapeHTML(meta.intent)}</span>` : '',
    Number.isFinite(meta.latency_ms) ? `<span>${icon('clock', 13)} ${Number(meta.latency_ms)} мс</span>` : '',
    meta.stage ? `<span>Стадия: ${escapeHTML(meta.stage)}</span>` : '',
    meta.route ? `<span>Маршрут: ${escapeHTML(meta.route)}</span>` : '',
  ].filter(Boolean).join('');
  return `<div class="message-debug">
    <div class="debug-meta">${attrs || '<span>Дополнительных метрик пока нет</span>'}</div>
    <div class="debug-source-title">${icon('file', 14)} Источники (${sources.length})</div>
    ${sources.length ? `<ul class="debug-source-list">${sources.map((s) => `<li><strong>${escapeHTML(sourceLabel(s))}</strong>${typeof s === 'object' && s?.section ? `<small>${escapeHTML(s.section)}</small>` : ''}${typeof s === 'object' && s?.text ? `<p>${escapeHTML(s.text)}</p>` : ''}</li>`).join('')}</ul>` : '<div class="debug-no-sources">Backend не предоставил источников для этого ответа.</div>'}
  </div>`;
}
function messageHtml(item) {
  const isBot = item.role === 'assistant';
  const meta = diagnosticsFor(item);
  return `<article class="message-row ${isBot ? 'assistant-row' : 'user-row'}">
    ${isBot ? '<div class="avatar bot-avatar" aria-hidden="true">E</div>' : ''}
    <div class="message-main">
      <div class="message-heading"><span>${isBot ? 'EnergyTool' : 'Вы'}</span><time>${escapeHTML(formatTime(item.created_at))}</time></div>
      <div class="message-bubble ${isBot ? 'assistant-bubble' : 'user-bubble'}"><div class="message-content">${escapeHTML(item.content)}</div></div>
      ${messageDebug(item)}
      ${isBot && meta.suggested_action === 'offer_lead' ? `<button class="inline-lead-link" data-action="open-lead">Связаться со специалистом ${icon('arrow', 15)}</button>` : ''}
    </div>
  </article>`;
}
function chatContent() {
  if (state.loadingHistory) return `<div class="center-state"><span class="spinner"></span><p>Загружаем историю…</p></div>`;
  if (!state.messages.length && !state.pendingMessage) return welcome();
  return `<div class="messages" aria-live="polite" aria-relevant="additions text">
    <div class="messages-intro"><div><span class="messages-intro-kicker">ТЕКУЩАЯ КОНСУЛЬТАЦИЯ</span><h2>Обсуждение задачи</h2></div><span class="messages-intro-status"><span class="status-dot"></span> Диалог открыт</span></div>
    ${state.messages.map(messageHtml).join('')}
    ${state.pendingMessage ? messageHtml({role: 'user', content: state.pendingMessage, created_at: new Date().toISOString(), id: 'pending'}) : ''}
    ${state.sending ? `<div class="message-row assistant-row"><div class="avatar bot-avatar" aria-hidden="true">E</div><div class="message-main"><div class="message-heading"><span>EnergyTool</span></div><div class="message-bubble assistant-bubble typing-bubble"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-caption">Изучаем ваш вопрос…</span></div></div></div>` : ''}
  </div>`;
}
function composer() {
  const disabled = !state.sessionId || busy();
  return `<div class="composer-wrap composer-docked" aria-label="Поле ввода сообщения">
    ${state.error ? `<div class="error-notice" role="alert">${icon('alert', 19)}<div>${escapeHTML(state.error)}</div><button data-action="dismiss-error" aria-label="Закрыть ошибку">${icon('x', 16)}</button></div>` : ''}
    <form id="chat-form" class="composer-form" autocomplete="off">
      <textarea id="messageInput" name="message" rows="2" maxlength="4000" aria-label="Сообщение консультанту" placeholder="Например, у нас выросли счета за электричество…" ${disabled ? 'disabled' : ''}>${escapeHTML(state.draft)}</textarea>
      <button class="send-button" type="submit" title="Отправить сообщение" aria-label="Отправить сообщение" ${disabled || !state.draft.trim() ? 'disabled' : ''}>${state.sending ? '<span class="small-spinner"></span>' : icon('arrow', 20)}</button>
    </form>
    <div class="composer-bottom"><span>Enter — отправить · Shift+Enter — новая строка</span><span class="input-counter" id="inputCounter">${state.draft.length} / 4000</span></div>
  </div>`;
}
function leadModal() {
  if (!state.leadOpen) return '';
  const successId = state.leadSuccessId || (state.sessionId ? getSavedLeadId(state.sessionId) : null);
  return `<div class="modal-overlay" id="modalOverlay" role="presentation">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="leadTitle">
      <button class="modal-close" data-action="close-lead" aria-label="Закрыть форму" ${state.leadSending ? 'disabled' : ''}>${icon('x', 20)}</button>
      ${successId ? `
        <div class="lead-success-icon">${icon('check', 25)}</div>
        <div class="modal-badge">ЗАЯВКА СОЗДАНА</div>
        <h2 id="leadTitle">Обращение зарегистрировано</h2>
        <p class="modal-description">Заявка сохранена в демонстрационной системе. Передача менеджеру зависит от настройки backend.</p>
        <div class="lead-id-box"><span>Номер обращения</span><strong>${escapeHTML(successId)}</strong></div>
        <button class="primary-button modal-submit" data-action="close-lead">Вернуться к консультации ${icon('arrow', 17)}</button>
      ` : `
        <div class="modal-badge">СВЯЗЬ СО СПЕЦИАЛИСТОМ</div>
        <h2 id="leadTitle">Обсудим вашу задачу предметно</h2>
        <p class="modal-description">Укажите, как с вами связаться. Мы прикрепим обращение к текущему диалогу.</p>
        ${state.leadError ? `<div class="lead-error" role="alert">${icon('alert', 17)} ${escapeHTML(state.leadError)}</div>` : ''}
        <form id="lead-form" class="lead-form">
          <div class="lead-fields">
            <div class="lead-field"><label for="leadName">Как к вам обращаться <span>*</span></label>
              <input id="leadName" name="fullName" type="text" minlength="2" maxlength="200" autocomplete="name" placeholder="Иван Иванов" required value="${escapeHTML(state.lead.fullName)}" ${state.leadSending ? 'disabled' : ''} /></div>
            <div class="lead-field"><label for="leadCompany">Компания <span>*</span></label>
              <input id="leadCompany" name="company" type="text" minlength="2" maxlength="200" autocomplete="organization" placeholder="ООО «Компания»" required value="${escapeHTML(state.lead.company)}" ${state.leadSending ? 'disabled' : ''} /></div>
            <div class="lead-field lead-field-wide"><label for="leadPhone">Телефон для связи <span>*</span></label>
              <input id="leadPhone" name="phone" type="tel" minlength="5" maxlength="40" autocomplete="tel" placeholder="+7 999 000-00-00" required value="${escapeHTML(state.lead.phone)}" ${state.leadSending ? 'disabled' : ''} /></div>
          </div>
          <label class="consent-label"><input type="checkbox" id="leadConsent" name="consent" ${state.lead.consent ? 'checked' : ''} ${state.leadSending ? 'disabled' : ''} required /> <span>Согласен(на) передать указанные данные для связи по этому обращению.</span></label>
          <div class="lead-data-warning">${icon('shield', 16)} <span>Демонстрационный стенд. Не вводите реальные персональные данные.</span></div>
          <button type="submit" class="primary-button modal-submit" ${state.leadSending || !state.lead.consent ? 'disabled' : ''}>${state.leadSending ? '<span class="small-spinner"></span> Отправляем…' : `Отправить обращение ${icon('arrow', 17)}`}</button>
        </form>
      `}
    </div>
  </div>`;
}
function render() {
  // Rerenders must not lose the user's text cursor or jump a long conversation to the top.
  const previousScroll = document.getElementById('chatScroll');
  const scrollTop = previousScroll?.scrollTop ?? 0;
  const focused = root.contains(document.activeElement) ? document.activeElement : null;
  const focusedId = focused?.id;
  const selection = focusedId && typeof focused.selectionStart === 'number'
    ? [focused.selectionStart, focused.selectionEnd] : null;
  root.innerHTML = `
    <div class="app-shell">
      ${state.sidebarOpen ? '<div class="mobile-shade" data-action="sidebar-toggle"></div>' : ''}
      ${sidebar()}
      <div class="main-panel">${header()}<main id="chatScroll" class="chat-scroll" tabindex="-1">${chatContent()}</main>${composer()}</div>
      ${leadModal()}
    </div>`;
  const input = document.getElementById('messageInput');
  if (input) resizeTextarea(input);
  const newScroll = document.getElementById('chatScroll');
  if (newScroll) newScroll.scrollTop = scrollTop;
  if (focusedId) {
    const replacement = document.getElementById(focusedId);
    if (replacement && !replacement.disabled) {
      replacement.focus({ preventScroll: true });
      if (selection && typeof replacement.setSelectionRange === 'function') {
        replacement.setSelectionRange(...selection);
      }
    }
  }
}
function resizeTextarea(el) {
  el.style.height = 'auto';
  el.style.height = `${Math.min(el.scrollHeight, 150)}px`;
}
function scrollToBottom() {
  requestAnimationFrame(() => {
    const el = document.getElementById('chatScroll');
    if (el) el.scrollTop = el.scrollHeight;
  });
}
function focusComposer() {
  requestAnimationFrame(() => document.getElementById('messageInput')?.focus());
}
async function checkHealth() {
  try { state.health = await api.health(); } catch { state.health = { status: 'offline' }; }
  render();
}
async function createNewSession() {
  if (busy()) return;
  state.creating = true; state.error = ''; render();
  try {
    const item = await api.createSession();
    if (!item || typeof item.id !== 'string' || !item.id) throw new Error('Backend не вернул id новой сессии.');
    rememberSession(item);
    setActiveSessionId(item.id);
    state.sessionId = item.id;
    state.messages = [];
    state.pendingMessage = null;
    state.messageMeta = {};
    state.draft = '';
    state.sidebarOpen = false;
    state.leadSuccessId = null;
    state.lead = { fullName: '', phone: '', company: '', consent: false };
  } catch (err) {
    state.error = `Не удалось создать диалог. ${err.message}`;
  } finally {
    state.creating = false;
    render();
    document.getElementById('chatScroll').scrollTop = 0;
    if (state.sessionId) focusComposer();
  }
}
async function openSession(id) {
  if (busy() || !id) return;
  state.sessionId = id;
  setActiveSessionId(id);
  state.loadingHistory = true;
  state.error = '';
  state.draft = '';
  state.sidebarOpen = false;
  state.messageMeta = {};
  state.leadSuccessId = getSavedLeadId(id);
  state.leadOpen = false;
  state.leadError = '';
  // A draft from another customer's conversation must never appear in this session.
  state.lead = { fullName: '', phone: '', company: '', consent: false };
  render();
  try {
    const messages = await api.getMessages(id);
    if (!Array.isArray(messages)) throw new Error('История не является массивом сообщений.');
    state.messages = messages.filter((m) => m && ['user', 'assistant'].includes(m.role));
  } catch (err) {
    state.messages = [];
    if (err.status === 404) {
      state.error = 'Сессия не найдена на сервере. Создайте новый диалог.';
      clearActiveSessionId();
      state.sessionId = null;
    } else {
      state.error = `Не удалось загрузить историю: ${err.message}`;
    }
  } finally {
    state.loadingHistory = false;
    render();
    scrollToBottom();
  }
}
async function sendMessage(raw) {
  const message = String(raw || '').trim();
  if (!message || !state.sessionId || busy()) return;
  if (message.length > 4000) { state.error = 'Сообщение не должно превышать 4000 символов.'; render(); return; }
  const sessionId = state.sessionId;
  state.draft = '';
  state.error = '';
  state.sending = true;
  state.pendingMessage = message;
  render(); scrollToBottom();
  try {
    const answer = await api.chat(sessionId, message);
    if (typeof answer.answer !== 'string') throw new Error('Ответ backend не содержит поле answer.');
    try {
      const history = await api.getMessages(sessionId);
      if (!Array.isArray(history)) throw new Error('Некорректная история.');
      const previousIds = new Set(state.messages.map((m) => String(m.id)));
      state.messages = history;
      const bot = [...history].reverse().find((m) => m.role === 'assistant'
        && m.content === answer.answer && (!previousIds.has(String(m.id)) || String(m.id) === String(answer.message_id))); 
      if (bot) {
        state.messageMeta[String(bot.id)] = {
          latency_ms: answer.latency_ms,
          intent: answer.intent,
          sources: answer.sources,
          stage: answer.stage,
          route: answer.diagnostics?.route ?? answer.route,
          suggested_action: answer.suggested_action,
        };
      }
    } catch {
      state.messages = [...state.messages,
        { id: `temp-u-${Date.now()}`, role: 'user', content: message },
        { id: `temp-a-${Date.now()}`, role: 'assistant', content: answer.answer, sources: answer.sources, intent: answer.intent },
      ];
      state.error = 'Ответ получен, но не удалось обновить историю. При следующем открытии она будет загружена с сервера.';
    }
  } catch (err) {
    // Backend persists the user's message BEFORE the AI request. Never auto-retry POST /api/chat.
    try {
      const history = await api.getMessages(sessionId);
      if (Array.isArray(history)) {
        const oldCount = state.messages.length;
        state.messages = history;
        const wasSaved = history.slice(oldCount).some((m) => m.role === 'user' && m.content === message);
        if (!wasSaved) state.draft = message;
        state.error = `Ответ не получен: ${err.message} История обновлена. ${wasSaved ? 'Сообщение могло сохраниться — не отправляйте его повторно без проверки.' : 'Текст сохранён в поле ввода.'}`;
      } else throw new Error('Не удалось проверить историю.');
    } catch {
      state.error = `Ошибка отправки: ${err.message} Состояние неизвестно: проверьте историю перед повторной отправкой.`;
      state.draft = message;
    }
  } finally {
    state.sending = false;
    state.pendingMessage = null;
    render(); scrollToBottom();
    if (!state.error) focusComposer();
  }
}
function openLead() {
  if (!state.sessionId) return;
  state.leadError = '';
  state.leadSuccessId = getSavedLeadId(state.sessionId);
  state.leadOpen = true;
  render();
  requestAnimationFrame(() => document.getElementById('leadName')?.focus());
}
async function submitLead() {
  if (state.leadSending || !state.sessionId || state.leadSuccessId || getSavedLeadId(state.sessionId)) return;
  const { fullName, phone, company, consent } = state.lead;
  if (!consent) { state.leadError = 'Для отправки заявки нужно ваше согласие.'; render(); return; }
  if (fullName.trim().length < 2 || company.trim().length < 2 || phone.trim().length < 5 || phone.trim().length > 40) {
    state.leadError = 'Проверьте имя, компанию и номер телефона.'; render(); return;
  }
  if (!/^[+\d\s()\-]{5,40}$/.test(phone.trim()) || (phone.match(/\d/g) || []).length < 5) {
    state.leadError = 'Введите телефон в формате +7 999 000-00-00.'; render(); return;
  }
  state.leadSending = true; state.leadError = ''; render();
  try {
    const result = await api.createLead({ sessionId: state.sessionId, fullName, phone, company, consent });
    if (typeof result.id !== 'string' || !result.id) throw new Error('Backend не вернул ID заявки.');
    state.leadSuccessId = result.id;
    rememberLeadId(state.sessionId, result.id);
    state.lead = { fullName: '', phone: '', company: '', consent: false };
  } catch (err) {
    // Backend does not implement idempotency. Do not automatically retry uncertain submissions.
    state.leadError = `Не удалось подтвердить заявку: ${err.message} Если соединение прервалось, запись могла сохраниться. Не отправляйте повторно без проверки.`;
  } finally { state.leadSending = false; render(); }
}
root.addEventListener('click', (event) => {
  const el = event.target.closest('[data-action]');
  if (!el) return;
  const action = el.dataset.action;
  if (action === 'sidebar-toggle') { state.sidebarOpen = !state.sidebarOpen; render(); }
  if (action === 'new-session') createNewSession();
  if (action === 'open-session') openSession(el.dataset.id);
  if (action === 'toggle-debug' && isLocal) { state.debug = !state.debug; render(); }
  if (action === 'open-lead') openLead();
  if (action === 'close-lead' && !state.leadSending) { state.leadOpen = false; state.leadError = ''; render(); requestAnimationFrame(() => document.querySelector('.topbar-lead')?.focus()); }
  if (action === 'dismiss-error') { state.error = ''; render(); }
  if (action === 'suggestion') sendMessage(samples[Number(el.dataset.index)]?.prompt);
});
root.addEventListener('submit', (event) => {
  if (event.target.id === 'chat-form') {
    event.preventDefault();
    sendMessage(document.getElementById('messageInput')?.value);
  }
  if (event.target.id === 'lead-form') { event.preventDefault(); submitLead(); }
});
root.addEventListener('input', (event) => {
  if (event.target.id === 'messageInput') {
    state.draft = event.target.value;
    resizeTextarea(event.target);
    const counter = document.getElementById('inputCounter');
    if (counter) counter.textContent = `${state.draft.length} / 4000`;
    const send = document.querySelector('#chat-form .send-button');
    if (send) send.disabled = !state.draft.trim() || busy() || !state.sessionId;
  }
  const fields = { leadName: 'fullName', leadPhone: 'phone', leadCompany: 'company' };
  if (fields[event.target.id]) state.lead[fields[event.target.id]] = event.target.value;
});
root.addEventListener('change', (event) => {
  if (event.target.id === 'leadConsent') {
    state.lead.consent = event.target.checked;
    const submit = document.querySelector('#lead-form .modal-submit');
    if (submit) submit.disabled = !event.target.checked || state.leadSending;
  }
});
root.addEventListener('keydown', (event) => {
  if (state.leadOpen && event.key === 'Tab') {
    const modal = document.querySelector('.modal');
    const items = [...(modal?.querySelectorAll('button:not(:disabled), input:not(:disabled), [href], [tabindex]:not([tabindex="-1"])') || [])];
    if (items.length) {
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    }
  }
  if (event.target.id === 'messageInput' && event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault(); sendMessage(event.target.value);
  }
  if (event.key === 'Escape' && state.leadOpen && !state.leadSending) {
    state.leadOpen = false; render(); requestAnimationFrame(() => document.querySelector('.topbar-lead')?.focus());
  }
});

async function init() {
  render();
  checkHealth();
  const stored = getActiveSessionId();
  if (stored) {
    await openSession(stored);
  } else {
    await createNewSession();
  }
}
init();
