// Сохраняем только UUID/времена сессий и ID заявок, НЕ текст беседы, телефоны и ключи.
const KEY = 'mts-energytool.demo.sessions.v1';
const ACTIVE = 'mts-energytool.demo.active.v1';
const LEADS = 'mts-energytool.demo.leads.v1';
const MAX = 25;

const read = (key, fallback) => {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch { return fallback; }
};
const write = (key, value) => {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ }
};
export const getRecentSessions = () => {
  const list = read(KEY, []);
  return Array.isArray(list) ? list.filter((s) => typeof s?.id === 'string').slice(0, MAX) : [];
};
export function rememberSession(session) {
  const list = getRecentSessions().filter((s) => s.id !== session.id);
  write(KEY, [{ id: session.id, created_at: session.created_at || new Date().toISOString(), closed_at: session.closed_at || null }, ...list].slice(0, MAX));
}
export function markSessionClosed(id) {
  write(KEY, getRecentSessions().map((s) => s.id === id ? { ...s, closed_at: new Date().toISOString() } : s));
}
export const getActiveSessionId = () => {
  const result = read(ACTIVE, null);
  return typeof result === 'string' ? result : null;
};
export const setActiveSessionId = (id) => write(ACTIVE, id);
export const clearActiveSessionId = () => {
  try { localStorage.removeItem(ACTIVE); } catch { /* private mode */ }
};
export const getSavedLeadId = (sessionId) => read(LEADS, {})[sessionId] || null;
export function rememberLeadId(sessionId, leadId) {
  const current = read(LEADS, {});
  const ids = getRecentSessions().map((s) => s.id);
  write(LEADS, Object.fromEntries([...Object.entries(current), [sessionId, leadId]].filter(([id]) => ids.includes(id))));
}
